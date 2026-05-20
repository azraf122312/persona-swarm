"""
core/perception.py - Turns a live page into something an LLM can reason about.

Each interactive element gets a stable `data-ps-id` attribute so the agent can
act on it precisely later (page.click('[data-ps-id="5"]')). We also compute an
accessible name for every element — that's what the screen-reader persona keys
on, and missing names are themselves a finding.
"""

from dataclasses import dataclass, field

# Injected into the page. Tags interactive elements and returns a snapshot.
_PERCEIVE_JS = r"""
() => {
  const SEL = "a[href], button, input, select, textarea, " +
              "[role='button'], [role='link'], [role='tab'], [role='menuitem'], [role='checkbox']";
  const els = Array.from(document.querySelectorAll(SEL));
  const out = [];
  let id = 0;
  for (const el of els) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const visible = rect.width > 1 && rect.height > 1 &&
                    style.visibility !== 'hidden' && style.display !== 'none' &&
                    parseFloat(style.opacity || '1') > 0.05;
    if (!visible) continue;

    el.setAttribute('data-ps-id', String(id));

    let name = (el.getAttribute('aria-label') || '').trim();
    if (!name && el.getAttribute('aria-labelledby')) {
      const ref = document.getElementById(el.getAttribute('aria-labelledby'));
      if (ref) name = ref.textContent.trim();
    }
    if (!name && el.id) {
      try {
        const lab = document.querySelector("label[for='" + CSS.escape(el.id) + "']");
        if (lab) name = lab.textContent.trim();
      } catch (e) {}
    }
    if (!name) {
      const wrap = el.closest('label');
      if (wrap) name = wrap.textContent.trim();
    }
    if (!name) name = (el.getAttribute('alt') || el.getAttribute('title') || '').trim();
    if (!name && (el.tagName === 'INPUT' || el.tagName === 'BUTTON')) name = (el.value || '').trim();
    if (!name) name = (el.textContent || '').replace(/\s+/g, ' ').trim();

    const inViewport = rect.bottom > 0 && rect.top < window.innerHeight;

    out.push({
      ps_id: id,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      role: (el.getAttribute('role') || '').toLowerCase(),
      name: name.slice(0, 140),
      has_name: name.length > 0,
      placeholder: (el.getAttribute('placeholder') || '').slice(0, 100),
      disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
      tap_size: Math.round(Math.min(rect.width, rect.height)),
      in_viewport: inViewport,
      href: el.tagName === 'A' ? (el.getAttribute('href') || '') : '',
    });
    id++;
  }

  const bodyText = (document.body ? document.body.innerText : '')
    .replace(/\s+/g, ' ').trim();

  return {
    url: location.href,
    title: document.title,
    text: bodyText.slice(0, 1600),
    elements: out,
    scroll_y: Math.round(window.scrollY),
    scroll_height: document.body ? document.body.scrollHeight : 0,
    viewport_height: window.innerHeight,
  };
}
"""


@dataclass
class Element:
    ps_id: int
    tag: str
    type: str = ""
    role: str = ""
    name: str = ""
    has_name: bool = True
    placeholder: str = ""
    disabled: bool = False
    tap_size: int = 0
    in_viewport: bool = True
    href: str = ""

    def kind(self) -> str:
        if self.tag == "a" or self.role == "link":
            return "link"
        if self.tag == "select":
            return "dropdown"
        if self.tag == "textarea":
            return "textbox"
        if self.tag == "input":
            if self.type in ("text", "email", "password", "search", "tel", "url", "number", ""):
                return "textbox"
            if self.type == "checkbox":
                return "checkbox"
            if self.type == "radio":
                return "radio"
            return "button"
        return "button"

    def is_typable(self) -> bool:
        return self.kind() == "textbox"

    def selector(self) -> str:
        return f'[data-ps-id="{self.ps_id}"]'


@dataclass
class PageSnapshot:
    url: str = ""
    title: str = ""
    text: str = ""
    elements: list = field(default_factory=list)
    scroll_y: int = 0
    scroll_height: int = 0
    viewport_height: int = 0

    def get(self, ps_id: int):
        for e in self.elements:
            if e.ps_id == ps_id:
                return e
        return None

    def can_scroll_down(self) -> bool:
        return self.scroll_y + self.viewport_height < self.scroll_height - 10

    def render_elements(self, max_elements: int = 60) -> str:
        """Compact, numbered list of interactive elements for the LLM prompt."""
        if not self.elements:
            return "(no interactive elements detected)"
        lines = []
        for e in self.elements[:max_elements]:
            label = e.name or e.placeholder or "(no visible label)"
            flags = []
            if not e.has_name:
                flags.append("NO ACCESSIBLE NAME")
            if e.disabled:
                flags.append("disabled")
            if e.tap_size and e.tap_size < 24:
                flags.append(f"tiny target {e.tap_size}px")
            if not e.in_viewport:
                flags.append("off-screen")
            flag_str = f"  <{', '.join(flags)}>" if flags else ""
            lines.append(f'[{e.ps_id}] {e.kind()}: "{label}"{flag_str}')
        if len(self.elements) > max_elements:
            lines.append(f"... and {len(self.elements) - max_elements} more elements")
        return "\n".join(lines)


def perceive(page) -> PageSnapshot:
    """Tag interactive elements on the live page and return a structured snapshot."""
    try:
        raw = page.evaluate(_PERCEIVE_JS)
    except Exception as e:
        return PageSnapshot(url=getattr(page, "url", ""), title="", text=f"(perception failed: {e})")

    elements = [
        Element(
            ps_id=d["ps_id"],
            tag=d.get("tag", ""),
            type=d.get("type", ""),
            role=d.get("role", ""),
            name=d.get("name", ""),
            has_name=d.get("has_name", True),
            placeholder=d.get("placeholder", ""),
            disabled=d.get("disabled", False),
            tap_size=d.get("tap_size", 0),
            in_viewport=d.get("in_viewport", True),
            href=d.get("href", ""),
        )
        for d in raw.get("elements", [])
    ]
    return PageSnapshot(
        url=raw.get("url", ""),
        title=raw.get("title", ""),
        text=raw.get("text", ""),
        elements=elements,
        scroll_y=raw.get("scroll_y", 0),
        scroll_height=raw.get("scroll_height", 0),
        viewport_height=raw.get("viewport_height", 0),
    )
