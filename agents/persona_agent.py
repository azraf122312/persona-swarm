"""
agents/persona_agent.py - One persona, one browser, one goal.

A PersonaAgent drives its own Playwright browser toward a goal while staying in
character. At each step it perceives the live page, asks the LLM (acting as the
persona) for the next action, executes it, and logs friction the way THIS
persona would feel it. The run ends when the persona declares success, gives
up, or runs out of steps.
"""

import time
from dataclasses import dataclass, field

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from core.perception import perceive
from core.llm import LLMError

VALID_ACTIONS = {"click", "type", "scroll", "navigate", "done", "give_up"}


@dataclass
class FrictionPoint:
    step: int
    severity: str  # blocker | major | minor
    note: str


@dataclass
class StepRecord:
    index: int
    action: str
    target: str = ""
    thought: str = ""
    observation: str = ""
    url: str = ""


@dataclass
class PersonaRun:
    persona_id: str
    persona_name: str
    persona_emoji: str
    goal: str
    start_url: str
    final_url: str = ""
    status: str = "stuck"  # completed | abandoned | stuck | error
    steps: list = field(default_factory=list)
    friction_points: list = field(default_factory=list)
    outcome_note: str = ""
    duration_ms: float = 0.0
    error: str = ""

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def friction_by_severity(self, severity: str) -> int:
        return sum(1 for f in self.friction_points if f.severity == severity)


def _patience_hint(patience: int) -> str:
    if patience <= 3:
        return "You give up fast — minor frustration is enough to make you quit."
    if patience <= 6:
        return "You will push through some friction, but repeated problems wear you down."
    return "You are persistent and will keep trying even when frustrated."


def _build_system_prompt(persona) -> str:
    traits = "\n".join(f"- {t}" for t in persona.traits)
    sensitivities = "\n".join(f"- {s}" for s in persona.sensitivities)
    return f"""You are role-playing a specific kind of website user. Stay fully in character at all times.

PERSONA: {persona.name}
{persona.summary}

HOW YOU BEHAVE:
{persona.behavior}

YOUR TRAITS:
{traits}

WHAT FRUSTRATES YOU (watch for these specifically):
{sensitivities}

Your patience is {persona.patience}/10. {_patience_hint(persona.patience)}

You are testing whether THIS persona can accomplish a goal on a website. Each
turn you see the current page and a numbered list of interactive elements.
Choose exactly ONE action.

Report "friction" only for things that would genuinely confuse, frustrate, or
block THIS persona. Do not report issues this persona would not notice or care
about. Severity: "blocker" = cannot continue, "major" = serious frustration,
"minor" = mild annoyance.

Be alert to these failure modes in particular — they are common and easy to miss:
  - Confusing or broken COPY: lorem ipsum, "TODO" / "TBD" / placeholder text,
    typos, idioms an outsider wouldn't get, vague link text ("click here").
  - AUTH SOFTLOCKS: submitting a login / signup form and getting no feedback
    (no error, no redirect), reaching a "forgot password" link that goes
    nowhere, being looped back to the same auth page after a click. Flag as
    blocker if it stops you from continuing.
  - DEAD ENDS: clicks that visibly do nothing, links that 404, infinite
    spinners, forms that submit but appear to vanish without confirmation.
  - TRUST RED FLAGS for personas who care: missing pricing, missing privacy
    or returns info before payment, hidden fees revealed only at the last step.
  - UI EDGE CASES the persona can feel: tiny tap targets on mobile, content
    overlapping or cut off, controls hidden behind a banner.

Call action "done" only when the goal is truly accomplished. Call "give_up"
when this persona would realistically quit. Use the element numbers exactly as
shown.

Respond with ONLY a JSON object, no other text:
{{
  "thought": "first-person reasoning, in this persona's voice",
  "friction": [{{"severity": "blocker|major|minor", "note": "..."}}],
  "action": "click|type|scroll|navigate|done|give_up",
  "target_id": <element number, or null>,
  "text": "<text to type, or null>",
  "url": "<absolute url for navigate, or null>",
  "reason": "<why you are done or giving up, or null>"
}}"""


def _build_step_prompt(persona, goal, site_overview, snapshot, history, step_no, max_steps, console_errors):
    parts = [
        f"GOAL: {goal}",
        "",
        "SITE MAP (overview only — you navigate the live page below):",
        site_overview or "(not available)",
        "",
        f"STEP {step_no} of {max_steps}",
        "",
        f"CURRENT PAGE: {snapshot.title or '(untitled)'}",
        f"URL: {snapshot.url}",
        "",
        "PAGE TEXT (excerpt):",
        snapshot.text or "(no visible text)",
        "",
        "INTERACTIVE ELEMENTS:",
        snapshot.render_elements(),
    ]
    if snapshot.can_scroll_down():
        parts += ["", "(There is more content below — you can 'scroll' to see it.)"]
    if console_errors:
        recent = console_errors[-3:]
        parts += ["", "BROWSER CONSOLE ERRORS on this page:"] + [f"- {e}" for e in recent]
    if history:
        parts += ["", "WHAT YOU'VE DONE SO FAR:"] + history
    else:
        parts += ["", "(This is your first step.)"]
    parts += ["", f"Decide your next action as {persona.name}."]
    return "\n".join(parts)


class PersonaAgent:
    def __init__(self, persona, llm, max_steps: int = 15, headless: bool = True,
                 timeout_ms: int = 30000):
        self.persona = persona
        self.llm = llm
        self.max_steps = max_steps
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._console_errors: list = []

    def run(self, start_url: str, goal: str, site_overview: str = "") -> PersonaRun:
        run = PersonaRun(
            persona_id=self.persona.id,
            persona_name=self.persona.name,
            persona_emoji=self.persona.emoji,
            goal=goal,
            start_url=start_url,
        )
        started = time.time()
        system_prompt = _build_system_prompt(self.persona)
        history: list = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(
                    viewport={
                        "width": self.persona.viewport["width"],
                        "height": self.persona.viewport["height"],
                    },
                    is_mobile=self.persona.viewport.get("is_mobile", False),
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                )
                page = context.new_page()
                page.on("dialog", lambda d: d.dismiss())
                page.on("console", lambda m: self._console_errors.append(m.text[:200])
                        if m.type == "error" else None)
                page.on("pageerror", lambda e: self._console_errors.append(str(e)[:200]))

                try:
                    page.goto(start_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                except PlaywrightTimeout:
                    run.error = "Start page timed out."
                    run.status = "error"
                    browser.close()
                    run.duration_ms = (time.time() - started) * 1000
                    return run

                for step_no in range(1, self.max_steps + 1):
                    page.wait_for_timeout(600)
                    snapshot = perceive(page)
                    decision = self._decide(system_prompt, goal, site_overview, snapshot,
                                            history, step_no)
                    if decision is None:
                        run.error = "LLM decision failed."
                        run.status = "error"
                        break

                    for f in decision.get("friction", []):
                        sev = str(f.get("severity", "minor")).lower()
                        if sev not in ("blocker", "major", "minor"):
                            sev = "minor"
                        note = str(f.get("note", "")).strip()
                        if note:
                            run.friction_points.append(FrictionPoint(step_no, sev, note))

                    action = str(decision.get("action", "")).lower()
                    thought = str(decision.get("thought", "")).strip()
                    record = StepRecord(index=step_no, action=action, thought=thought,
                                        url=snapshot.url)

                    if action == "done":
                        run.status = "completed"
                        run.outcome_note = str(decision.get("reason", "")).strip()
                        record.observation = "Persona declared the goal accomplished."
                        run.steps.append(record)
                        break
                    if action == "give_up":
                        run.status = "abandoned"
                        run.outcome_note = str(decision.get("reason", "")).strip()
                        record.observation = "Persona gave up."
                        run.steps.append(record)
                        break

                    target, observation = self._execute(page, action, decision, snapshot)
                    record.target = target
                    record.observation = observation
                    run.steps.append(record)
                    history.append(f"Step {step_no}: {action} {target} -> {observation}")

                run.final_url = page.url
                browser.close()
        except LLMError as e:
            run.error = f"LLM error: {e}"
            run.status = "error"
        except Exception as e:
            run.error = f"Agent crashed: {e}"
            run.status = "error"

        run.duration_ms = (time.time() - started) * 1000
        return run

    def _decide(self, system_prompt, goal, site_overview, snapshot, history, step_no):
        user_prompt = _build_step_prompt(
            self.persona, goal, site_overview, snapshot, history[-8:], step_no,
            self.max_steps, self._console_errors,
        )
        try:
            return self.llm.chat_json(system_prompt, user_prompt, max_tokens=900, temperature=0.5)
        except LLMError:
            return None

    def _execute(self, page, action, decision, snapshot):
        """Run one action against the live page. Returns (target_desc, observation)."""
        if action not in VALID_ACTIONS:
            return "", f"Unknown action '{action}' — skipped."

        if action == "scroll":
            page.evaluate("() => window.scrollBy(0, Math.round(window.innerHeight * 0.85))")
            page.wait_for_timeout(400)
            return "page", "Scrolled down."

        if action == "navigate":
            url = str(decision.get("url", "")).strip()
            if not url:
                return "", "Navigate requested with no URL."
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                return url, f"Navigated to {url}."
            except PlaywrightTimeout:
                return url, f"Navigation to {url} timed out."
            except Exception as e:
                return url, f"Navigation failed: {e}"

        # click / type both need a target element
        target_id = decision.get("target_id")
        if target_id is None:
            return "", f"Action '{action}' needs a target element, but none was given."
        try:
            target_id = int(target_id)
        except (TypeError, ValueError):
            return "", f"Invalid target id: {target_id!r}"

        element = snapshot.get(target_id)
        if element is None:
            return f"#{target_id}", f"Element [{target_id}] no longer exists on the page."

        label = element.name or element.placeholder or f"element {target_id}"
        selector = element.selector()

        if action == "type":
            text = str(decision.get("text", "") or "")
            if not element.is_typable():
                return f'"{label}"', f'Cannot type into "{label}" — it is not a text field.'
            try:
                page.fill(selector, text, timeout=8000)
                return f'"{label}"', f'Typed "{text[:60]}" into "{label}".'
            except Exception as e:
                return f'"{label}"', f'Could not type into "{label}": {e}'

        # click
        if element.disabled:
            return f'"{label}"', f'Clicked "{label}" but it is disabled — nothing happened.'
        try:
            page.click(selector, timeout=8000)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=6000)
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(400)
            return f'"{label}"', f'Clicked "{label}". Now on {page.url}'
        except PlaywrightTimeout:
            return f'"{label}"', f'Clicked "{label}" but the page did not respond in time.'
        except Exception as e:
            return f'"{label}"', f'Could not click "{label}": {e}'
