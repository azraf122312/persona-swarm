"""
core/crawler.py - Lightweight site mapper.

Runs once before the swarm. Produces a SiteMap (which pages exist, how they
link together) so the dashboard can show coverage and personas get a hint of
the site's shape. Persona agents do their own live perception while navigating;
this is just the overview pass.
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
                node, links = self._visit(page, url)
                site.pages.append(node)
                for href in links:
                    norm = _normalize(url, href)
                    if _should_visit(norm, base_domain, visited | set(to_visit)):
                        to_visit.append(norm)

            browser.close()

        site.total_time_ms = (time.time() - started) * 1000
        return site

    def _visit(self, page, url: str):
        node = PageNode(url=url)
        started = time.time()
        links: list = []
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            if response:
                node.status = response.status
            page.wait_for_timeout(800)
            try:
                node.title = page.title()
            except Exception:
                pass
            counts = page.evaluate(
                """() => ({
                    links: Array.from(document.querySelectorAll('a[href]')).map(a => a.href),
                    forms: document.querySelectorAll('form').length,
                    buttons: document.querySelectorAll(
                        "button, input[type='submit'], input[type='button'], [role='button']"
                    ).length,
                })"""
            )
            links = counts.get("links", []) or []
            node.n_links = len(links)
            node.n_forms = counts.get("forms", 0)
            node.n_buttons = counts.get("buttons", 0)
        except PlaywrightTimeout:
            node.error = f"Timed out after {self.timeout_ms}ms"
            node.status = 0
        except Exception as e:
            node.error = str(e)[:300]
        node.load_time_ms = (time.time() - started) * 1000
        return node, links
