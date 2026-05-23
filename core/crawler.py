"""
core/crawler.py - Lightweight site mapper.

Runs once before the swarm. Produces a SiteMap (which pages exist, how they
link together) so the dashboard can show coverage and personas get a hint of
the site's shape. Persona agents do their own live perception while navigating;
this is just the overview pass — but it also harvests every signal the static
auditor needs (meta tags, broken-link candidates, alt-text gaps, tap targets,
mixed-content, lorem-ipsum) so a single visit produces everything downstream.
"""

import time
import logging
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

SKIP_EXTS = {
    ".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".mp4", ".mp3",
    ".doc", ".docx", ".xls", ".xlsx", ".css", ".js", ".json", ".xml", ".csv",
    ".woff", ".woff2", ".ico", ".webp",
}

# Injected per page — single round-trip to collect everything the auditor needs.
_AUDIT_JS = r"""
() => {
  const head = document.head || document;
  const meta = (sel) => {
    const el = head.querySelector(sel);
    return el ? (el.getAttribute('content') || '').trim() : '';
  };
  const og = {};
  ['title','description','image','url','type','site_name'].forEach(k => {
    const v = meta("meta[property='og:" + k + "']");
    if (v) og[k] = v;
  });
  const canonicalEl = head.querySelector("link[rel='canonical']");
  const canonical = canonicalEl ? (canonicalEl.getAttribute('href') || '') : '';

  // links — href + visible text
  const links = Array.from(document.querySelectorAll('a[href]')).slice(0, 200).map(a => ({
    href: a.href,
    text: (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120),
  }));

  // images without alt (skip purely decorative if explicitly aria-hidden)
  let imgsNoAlt = 0;
  Array.from(document.querySelectorAll('img')).forEach(img => {
    if (img.getAttribute('aria-hidden') === 'true') return;
    const alt = img.getAttribute('alt');
    if (alt === null || (typeof alt === 'string' && alt.trim() === '' &&
        !(img.getAttribute('role') === 'presentation'))) {
      imgsNoAlt++;
    }
  });

  // inputs without an accessible label
  let inputsNoLabel = 0;
  Array.from(document.querySelectorAll('input, select, textarea')).forEach(el => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (type === 'hidden' || type === 'submit' || type === 'button' || type === 'reset')
      return;
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return;
    if (el.id) {
      try {
        if (document.querySelector("label[for='" + CSS.escape(el.id) + "']")) return;
      } catch (e) {}
    }
    if (el.closest('label')) return;
    inputsNoLabel++;
  });

  // small interactive tap targets (mobile-hostile UI)
  let smallTaps = 0;
  Array.from(document.querySelectorAll(
    "a[href], button, input[type='submit'], input[type='button'], [role='button']"
  )).forEach(el => {
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;            // invisible
    const min = Math.min(rect.width, rect.height);
    if (min > 0 && min < 32) smallTaps++;
  });

  // mixed content — http resources on an https page
  const isHttps = location.protocol === 'https:';
  const insecure = [];
  if (isHttps) {
    Array.from(document.querySelectorAll('img[src], script[src], link[href], iframe[src], source[src]'))
      .forEach(el => {
        const src = el.getAttribute('src') || el.getAttribute('href') || '';
        if (src.startsWith('http://') && insecure.length < 10) insecure.push(src);
      });
  }

  // headings
  const h1Count = document.querySelectorAll('h1').length;
  const hasH1 = h1Count > 0;

  // login-form heuristic: a form with a password field
  const hasLoginForm = !!document.querySelector("input[type='password']");
  // any obvious error / feedback region — exists if any element has aria-live,
  // role=alert, or a class/id containing 'error' / 'feedback' / 'invalid'
  const hasErrorRegion = !!document.querySelector(
    "[aria-live], [role='alert'], [role='status'], " +
    "[class*='error'], [id*='error'], [class*='feedback'], [class*='invalid']"
  );

  // visible body text (truncated) — used for lorem/placeholder detection
  const bodyText = (document.body ? document.body.innerText : '')
    .replace(/\s+/g, ' ').trim().slice(0, 4000);

  return {
    title: document.title || '',
    meta_description: meta("meta[name='description']") || meta("meta[property='og:description']"),
    canonical: canonical,
    og: og,
    links: links,
    h1_count: h1Count,
    has_h1: hasH1,
    images_no_alt: imgsNoAlt,
    inputs_no_label: inputsNoLabel,
    small_tap_targets: smallTaps,
    insecure_resources: insecure,
    has_login_form: hasLoginForm,
    has_error_region: hasErrorRegion,
    visible_text: bodyText,
    n_forms: document.querySelectorAll('form').length,
    n_buttons: document.querySelectorAll(
      "button, input[type='submit'], input[type='button'], [role='button']"
    ).length,
  };
}
"""


@dataclass
class PageNode:
    url: str
    title: str = ""
    status: Optional[int] = None
    load_time_ms: float = 0.0
    n_links: int = 0
    n_forms: int = 0
    n_buttons: int = 0
    error: Optional[str] = None

    # ---- audit-source fields ---------------------------------------------
    meta_description: str = ""
    canonical: str = ""
    og_tags: dict = field(default_factory=dict)
    links: list = field(default_factory=list)   # [{"href": "...", "text": "..."}]
    h1_count: int = 0
    images_no_alt: int = 0
    inputs_no_label: int = 0
    small_tap_targets: int = 0
    insecure_resources: list = field(default_factory=list)
    has_login_form: bool = False
    has_error_region: bool = False
    visible_text: str = ""


@dataclass
class SiteMap:
    start_url: str = ""
    pages: list = field(default_factory=list)
    total_time_ms: float = 0.0
    error: Optional[str] = None

    @property
    def pages_crawled(self) -> int:
        return len(self.pages)

    def overview(self, limit: int = 25) -> str:
        """Compact text summary handed to persona agents as site context."""
        lines = []
        for p in self.pages[:limit]:
            tag = p.title or p.url
            extra = []
            if p.n_forms:
                extra.append(f"{p.n_forms} form(s)")
            if p.status and p.status >= 400:
                extra.append(f"HTTP {p.status}")
            suffix = f" [{', '.join(extra)}]" if extra else ""
            lines.append(f"- {tag} ({p.url}){suffix}")
        if len(self.pages) > limit:
            lines.append(f"- ...and {len(self.pages) - limit} more pages")
        return "\n".join(lines)


def _normalize(base: str, href: str) -> str:
    if not href or not href.strip():
        return ""
    href = href.strip()
    if href.startswith(("javascript:", "mailto:", "tel:", "data:", "blob:")):
        return ""
    joined = urljoin(base, href)
    if "#" in joined:
        joined = joined[: joined.index("#")]
    if joined.startswith("//"):
        joined = f"{urlparse(base).scheme}:{joined}"
    return joined


def _should_visit(url: str, base_domain: str, seen: set) -> bool:
    if not url or url in seen:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc.lower() != base_domain:
        return False
    path = parsed.path.lower()
    return not any(path.endswith(ext) for ext in SKIP_EXTS)


class SiteCrawler:
    def __init__(self, headless: bool = True, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms

    def crawl(self, start_url: str, max_pages: int = 20) -> SiteMap:
        site = SiteMap(start_url=start_url)
        started = time.time()
        base_domain = urlparse(start_url).netloc.lower()
        if not base_domain:
            site.error = f"Invalid URL: {start_url}"
            return site

        to_visit = [start_url]
        visited: set = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = context.new_page()
            page.on("dialog", lambda d: d.dismiss())

            while to_visit and len(visited) < max_pages:
                url = to_visit.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                node, raw_links = self._visit(page, url)
                site.pages.append(node)
                for href in raw_links:
                    norm = _normalize(url, href)
                    if _should_visit(norm, base_domain, visited | set(to_visit)):
                        to_visit.append(norm)

            browser.close()

        site.total_time_ms = (time.time() - started) * 1000
        return site

    def _visit(self, page, url: str):
        node = PageNode(url=url)
        started = time.time()
        raw_link_hrefs: list = []
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            if response:
                node.status = response.status
            page.wait_for_timeout(800)
            try:
                node.title = page.title()
            except Exception:
                pass
            data = page.evaluate(_AUDIT_JS) or {}

            node.title = data.get("title") or node.title
            node.meta_description = data.get("meta_description", "")
            node.canonical = data.get("canonical", "")
            node.og_tags = data.get("og", {}) or {}
            node.links = data.get("links", []) or []
            node.h1_count = data.get("h1_count", 0)
            node.images_no_alt = data.get("images_no_alt", 0)
            node.inputs_no_label = data.get("inputs_no_label", 0)
            node.small_tap_targets = data.get("small_tap_targets", 0)
            node.insecure_resources = data.get("insecure_resources", []) or []
            node.has_login_form = bool(data.get("has_login_form"))
            node.has_error_region = bool(data.get("has_error_region"))
            node.visible_text = data.get("visible_text", "")
            node.n_forms = data.get("n_forms", 0)
            node.n_buttons = data.get("n_buttons", 0)
            node.n_links = len(node.links)

            raw_link_hrefs = [l.get("href", "") for l in node.links if l.get("href")]
        except PlaywrightTimeout:
            node.error = f"Timed out after {self.timeout_ms}ms"
            node.status = 0
        except Exception as e:
            node.error = str(e)[:300]
        node.load_time_ms = (time.time() - started) * 1000
        return node, raw_link_hrefs
