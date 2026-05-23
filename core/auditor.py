"""
core/auditor.py - Static technical audit of the mapped site.

Runs after the crawler, before the personas synthesize judgement. No LLM.
Catches the deterministic class of problems personas can't see (meta tags) or
won't focus on (broken links, lorem ipsum, mixed content). Findings merge into
the swarm report so the team gets a single prioritized list of fixes.

Categories produced:
    links            broken / 4xx / 5xx targets, network failures
    seo              missing title / meta description / h1 / canonical / og:*
    a11y             images without alt, inputs without label
    copy             lorem ipsum, placeholder strings, vague link text
    ui               tap targets <32px, page load failures
    mixed-content    http:// resources on an https:// page
    auth             login form with no visible error region

Severity: blocker | major | minor.
"""

import re
import time
import socket
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)


@dataclass
class AuditFinding:
    category: str    # links | seo | a11y | copy | ui | auth | mixed-content
    severity: str    # blocker | major | minor
    page_url: str
    note: str
    detail: str = ""   # e.g. the broken-link URL


@dataclass
class AuditResult:
    findings: list = field(default_factory=list)
    pages_audited: int = 0
    links_checked: int = 0
    broken_links: int = 0
    total_time_ms: float = 0.0

    def by_severity(self, sev: str) -> int:
        return sum(1 for f in self.findings if f.severity == sev)

    def by_category(self) -> dict:
        out: dict = {}
        for f in self.findings:
            out.setdefault(f.category, []).append(f)
        return out


_LOREM_RE = re.compile(r"\blorem ipsum\b", re.I)
_PLACEHOLDER_RE = re.compile(r"\b(TODO|FIXME|TBD|PLACEHOLDER|XXX)\b")
_VAGUE_LINK_TEXTS = {
    "click here", "read more", "here", "more", "link", "this", "this link", "learn more"
}


class SiteAuditor:
    """Static checks against a crawled SiteMap. Network-light, deterministic."""

    def __init__(self, check_links: bool = True, link_timeout: float = 6.0,
                 max_links: int = 80, max_workers: int = 8):
        self.check_links = check_links
        self.link_timeout = link_timeout
        self.max_links = max_links
        self.max_workers = max_workers

    def audit(self, site_map) -> AuditResult:
        result = AuditResult()
        started = time.time()
        if not site_map or not site_map.pages:
            result.total_time_ms = (time.time() - started) * 1000
            return result

        for page in site_map.pages:
            self._audit_page(page, result)

        if self.check_links:
            try:
                self._check_broken_links(site_map, result)
            except Exception as e:
                logger.warning("Broken-link pass failed: %s", e)

        result.pages_audited = len(site_map.pages)
        result.total_time_ms = (time.time() - started) * 1000
        return result

    # ------------------------------------------------------------------
    # per-page checks
    # ------------------------------------------------------------------
    def _audit_page(self, page, result):
        url = page.url
        is_https = url.startswith("https://")

        # Page-level HTTP status
        if page.status and 500 <= page.status:
            result.findings.append(AuditFinding(
                "links", "blocker", url,
                f"Page returned HTTP {page.status} (server error)."))
        elif page.status and 400 <= page.status:
            result.findings.append(AuditFinding(
                "links", "blocker", url,
                f"Page returned HTTP {page.status} (client error)."))

        if page.error:
            result.findings.append(AuditFinding(
                "ui", "major", url, f"Page failed to load cleanly: {page.error}"))

        # SEO / meta
        title = (page.title or "").strip()
        if not title:
            result.findings.append(AuditFinding(
                "seo", "major", url, "Missing <title> tag — bad for search and tabs."))
        elif len(title) > 70:
            result.findings.append(AuditFinding(
                "seo", "minor", url,
                f"Title is {len(title)} chars (>70) — will be truncated in search results."))

        desc = (page.meta_description or "").strip()
        if not desc:
            result.findings.append(AuditFinding(
                "seo", "major", url,
                "Missing meta description — Google will scrape body text instead."))
        elif len(desc) > 160:
            result.findings.append(AuditFinding(
                "seo", "minor", url,
                f"Meta description is {len(desc)} chars (>160) — likely truncated."))

        if page.h1_count == 0:
            result.findings.append(AuditFinding(
                "seo", "major", url, "No <h1> on the page — bad for SEO and document outline."))
        elif page.h1_count > 1:
            result.findings.append(AuditFinding(
                "seo", "minor", url,
                f"{page.h1_count} <h1> tags — best practice is exactly one per page."))

        if is_https and not page.canonical:
            result.findings.append(AuditFinding(
                "seo", "minor", url,
                "Missing canonical URL — duplicate-content risk if the page is reachable by multiple paths."))

        og = page.og_tags or {}
        missing_og = [k for k in ("title", "description", "image") if not og.get(k)]
        if missing_og:
            result.findings.append(AuditFinding(
                "seo", "minor", url,
                "Missing Open Graph tag(s): " +
                ", ".join("og:" + k for k in missing_og) +
                " — link previews on Slack / Twitter / iMessage will look bad."))

        # Accessibility
        if page.images_no_alt:
            sev = "major" if page.images_no_alt > 3 else "minor"
            result.findings.append(AuditFinding(
                "a11y", sev, url,
                f"{page.images_no_alt} image(s) without alt text — screen readers skip them."))
        if page.inputs_no_label:
            result.findings.append(AuditFinding(
                "a11y", "major", url,
                f"{page.inputs_no_label} form input(s) without an accessible label — "
                "unusable for screen readers and voice control."))

        # UI edges — tap targets
        if page.small_tap_targets >= 1:
            sev = "major" if page.small_tap_targets >= 3 else "minor"
            result.findings.append(AuditFinding(
                "ui", sev, url,
                f"{page.small_tap_targets} interactive element(s) smaller than 32×32px — "
                "hard to tap on mobile."))

        # Mixed content
        if is_https and page.insecure_resources:
            n = len(page.insecure_resources)
            sample = page.insecure_resources[0]
            result.findings.append(AuditFinding(
                "mixed-content", "blocker", url,
                f"{n} insecure (http://) resource(s) loaded on an https page — "
                f"browser will block them. Sample: {sample}"))

        # Copywriting
        text = (page.visible_text or "").strip()
        if text:
            if _LOREM_RE.search(text):
                result.findings.append(AuditFinding(
                    "copy", "blocker", url,
                    "Lorem ipsum placeholder text is live on the page."))
            placeholders = _PLACEHOLDER_RE.findall(text)
            if placeholders:
                unique = sorted(set(placeholders))[:4]
                result.findings.append(AuditFinding(
                    "copy", "major", url,
                    f"Placeholder strings visible to users: {', '.join(unique)}."))

        # Vague / SEO-unfriendly link text
        if page.links:
            vague = 0
            for l in page.links:
                t = (l.get("text") or "").strip().lower()
                if t and t in _VAGUE_LINK_TEXTS:
                    vague += 1
            if vague >= 3:
                result.findings.append(AuditFinding(
                    "copy", "minor", url,
                    f"{vague} link(s) with vague text ('click here', 'read more'). "
                    "Bad for accessibility, screen readers, and SEO."))

        # Auth softlock signal — login form but no visible error feedback region
        if page.has_login_form and not page.has_error_region:
            result.findings.append(AuditFinding(
                "auth", "major", url,
                "Login / signup form has no obvious error or feedback region — "
                "users who submit invalid credentials may not see why it failed (auth softlock risk)."))

    # ------------------------------------------------------------------
    # broken-link pass (concurrent HEAD requests, internal links only)
    # ------------------------------------------------------------------
    def _check_broken_links(self, site_map, result):
        base_domain = urlparse(site_map.start_url).netloc.lower()
        seen: set = set()
        # source_url -> set of (href, anchor_text)
        targets: list = []
        for pg in site_map.pages:
            for link in (pg.links or []):
                href = (link.get("href") or "").strip()
                if not href or href in seen:
                    continue
                seen.add(href)
                try:
                    parsed = urlparse(href)
                except Exception:
                    continue
                if parsed.scheme not in ("http", "https"):
                    continue
                if parsed.netloc.lower() != base_domain:
                    continue
                # strip fragment
                clean = href.split("#", 1)[0]
                if not clean:
                    continue
                targets.append((clean, pg.url, link.get("text", "")))
                if len(targets) >= self.max_links:
                    break
            if len(targets) >= self.max_links:
                break

        if not targets:
            return

        def check(args):
            href, source, anchor = args
            try:
                req = Request(href, method="HEAD", headers={
                    "User-Agent": "PersonaSwarm-Auditor/1.0",
                    "Accept": "*/*",
                })
                with urlopen(req, timeout=self.link_timeout) as resp:
                    return (href, source, anchor, getattr(resp, "status", 200), None)
            except HTTPError as e:
                # 405 = HEAD not allowed; retry as GET so we don't false-positive.
                if e.code in (405, 501):
                    try:
                        req = Request(href, method="GET", headers={
                            "User-Agent": "PersonaSwarm-Auditor/1.0",
                            "Accept": "*/*",
                        })
                        with urlopen(req, timeout=self.link_timeout) as resp:
                            return (href, source, anchor, getattr(resp, "status", 200), None)
                    except HTTPError as e2:
                        return (href, source, anchor, e2.code, None)
                    except Exception as e2:
                        return (href, source, anchor, 0, str(e2)[:120])
                return (href, source, anchor, e.code, None)
            except (URLError, socket.timeout, ConnectionError, ValueError) as e:
                return (href, source, anchor, 0, str(e)[:120])
            except Exception as e:
                return (href, source, anchor, 0, str(e)[:120])

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for href, source, anchor, status, err in pool.map(check, targets):
                result.links_checked += 1
                anchor_hint = f' (link "{anchor[:40]}")' if anchor else ""
                if status and status >= 400:
                    result.broken_links += 1
                    sev = "blocker" if status >= 500 else "major"
                    result.findings.append(AuditFinding(
                        "links", sev, source,
                        f"Broken link → HTTP {status}{anchor_hint}",
                        detail=href,
                    ))
                elif status == 0 and err:
                    # Real network failure — only flag the obvious ones
                    low = err.lower()
                    if any(t in low for t in (
                            "name or service not known", "no host", "name resolution",
                            "getaddrinfo failed", "nodename nor servname",
                            "no address associated", "connection refused")):
                        result.broken_links += 1
                        result.findings.append(AuditFinding(
                            "links", "major", source,
                            f"Broken link → {err}{anchor_hint}",
                            detail=href,
                        ))
