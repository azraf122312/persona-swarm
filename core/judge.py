"""
core/judge.py - Independent verdict on a swarm run.

A persona agent reports its own outcome ("done" / "give_up") — but personas
over-claim and under-claim. The Judge looks at every run together and produces
an independent verdict per persona plus a cross-persona synthesis: which
problems multiple personas hit, what to fix first, and an overall health score
for the goal. Seeing all runs at once is what makes the shared-blocker
detection possible.

Falls back to a heuristic report when no LLM is configured.
"""

from dataclasses import dataclass, field

from core.llm import LLMError


@dataclass
class PersonaVerdict:
    persona_id: str
    verdict: str  # success | partial | failure
    summary: str = ""


@dataclass
class SwarmReport:
    health_score: int = 0  # 0-100
    headline: str = ""
    persona_verdicts: list = field(default_factory=list)
    shared_blockers: list = field(default_factory=list)
    prioritized_fixes: list = field(default_factory=list)  # {priority, issue, why}
    worst_persona_id: str = ""
    best_persona_id: str = ""

    def verdict_for(self, persona_id: str) -> PersonaVerdict:
        for v in self.persona_verdicts:
            if v.persona_id == persona_id:
                return v
        return PersonaVerdict(persona_id, "partial", "")


_JUDGE_SYSTEM = """You are a senior UX research lead reviewing an automated usability test.

A swarm of simulated user personas each tried to accomplish the same goal on a
website. You are given each persona's outcome, the steps they took, the
friction they logged, AND a static technical audit of the site (broken links,
SEO/meta gaps, accessibility, copy bugs, UI tap targets, mixed content, auth
softlock signals). Judge it independently — personas sometimes claim success
when they didn't really finish, or give up over something trivial.

When ranking "prioritized_fixes", combine BOTH sources:
  - persona friction (subjective UX)
  - audit findings (deterministic technical bugs)
A static-audit "blocker" (lorem ipsum live in prod, mixed content blocked,
broken link, login form with no error region) belongs at the top of the fix
list even if no persona explicitly hit it.

Produce:
1. A verdict for each persona: "success", "partial", or "failure".
2. A short, concrete summary of each persona's experience.
3. "shared_blockers": problems that affected MULTIPLE personas (the costliest).
4. "prioritized_fixes": what the team should fix, most important first.
5. A "health_score" 0-100 for how well this goal works across all personas.
6. The persona that had the worst experience and the one that had the best.

Respond with ONLY a JSON object:
{
  "health_score": <0-100>,
  "headline": "<one sentence overall verdict>",
  "persona_verdicts": [
    {"persona_id": "...", "verdict": "success|partial|failure", "summary": "..."}
  ],
  "shared_blockers": ["<issue hitting multiple personas>", ...],
  "prioritized_fixes": [
    {"priority": "high|medium|low", "issue": "...", "why": "..."}
  ],
  "worst_persona_id": "...",
  "best_persona_id": "..."
}"""


def _run_digest(run) -> str:
    lines = [
        f"### persona_id: {run.persona_id}  ({run.persona_name}, patience {_patience(run)})",
        f"Self-reported outcome: {run.status}"
        + (f' — "{run.outcome_note}"' if run.outcome_note else ""),
        f"Steps taken: {run.step_count}   Final URL: {run.final_url or run.start_url}",
    ]
    if run.error:
        lines.append(f"Error: {run.error}")
    if run.friction_points:
        lines.append("Friction logged:")
        for f in run.friction_points:
            lines.append(f"  - [{f.severity}] {f.note}")
    else:
        lines.append("Friction logged: none")
    if run.steps:
        lines.append("Step trail:")
        for s in run.steps[:12]:
            lines.append(f"  {s.index}. {s.action} {s.target} -> {s.observation}")
    return "\n".join(lines)


def _patience(run) -> str:
    return "?"  # patience isn't carried on the run; kept for prompt readability


def _audit_digest(audit) -> str:
    """Compact, prompt-friendly summary of static-audit findings."""
    if audit is None or not audit.findings:
        return ""
    lines = [
        f"Pages audited: {audit.pages_audited}, "
        f"links checked: {audit.links_checked}, "
        f"broken links: {audit.broken_links}",
        f"Severity counts: "
        f"{audit.by_severity('blocker')} blocker / "
        f"{audit.by_severity('major')} major / "
        f"{audit.by_severity('minor')} minor",
        "Findings (grouped by category):",
    ]
    by_cat = audit.by_category()
    cat_order = ["links", "auth", "mixed-content", "copy", "seo", "a11y", "ui"]
    for cat in cat_order:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"  [{cat}]")
        for f in items[:8]:
            detail = f" -> {f.detail}" if f.detail else ""
            lines.append(f"    - [{f.severity}] {f.note}{detail}  ({f.page_url})")
        if len(items) > 8:
            lines.append(f"    ... and {len(items) - 8} more in this category")
    return "\n".join(lines)


class Judge:
    def __init__(self, llm=None):
        self.llm = llm

    def synthesize(self, swarm_result) -> SwarmReport:
        if self.llm is None:
            return self._heuristic(swarm_result)
        digest = "\n\n".join(_run_digest(r) for r in swarm_result.runs)
        audit_section = _audit_digest(getattr(swarm_result, "audit", None))
        user = (
            f"GOAL UNDER TEST: {swarm_result.goal}\n"
            f"TARGET SITE: {swarm_result.target_url}\n"
            f"PERSONAS IN SWARM: {len(swarm_result.runs)}\n\n"
            f"PERSONA RUNS:\n\n{digest}"
            + (f"\n\nSTATIC SITE AUDIT (deterministic — no LLM produced this):\n{audit_section}"
               if audit_section else "")
        )
        try:
            data = self.llm.chat_json(_JUDGE_SYSTEM, user, max_tokens=1600, temperature=0.3)
        except LLMError:
            return self._heuristic(swarm_result)
        return self._from_json(data, swarm_result)

    def _from_json(self, data, swarm_result) -> SwarmReport:
        verdicts = []
        valid_ids = {r.persona_id for r in swarm_result.runs}
        for v in data.get("persona_verdicts", []):
            pid = str(v.get("persona_id", ""))
            if pid not in valid_ids:
                continue
            verdict = str(v.get("verdict", "partial")).lower()
            if verdict not in ("success", "partial", "failure"):
                verdict = "partial"
            verdicts.append(PersonaVerdict(pid, verdict, str(v.get("summary", "")).strip()))
        # ensure every persona has a verdict
        covered = {v.persona_id for v in verdicts}
        for r in swarm_result.runs:
            if r.persona_id not in covered:
                verdicts.append(PersonaVerdict(r.persona_id, _status_to_verdict(r.status), ""))

        fixes = []
        for f in data.get("prioritized_fixes", []):
            prio = str(f.get("priority", "medium")).lower()
            if prio not in ("high", "medium", "low"):
                prio = "medium"
            fixes.append({
                "priority": prio,
                "issue": str(f.get("issue", "")).strip(),
                "why": str(f.get("why", "")).strip(),
            })

        try:
            score = max(0, min(100, int(data.get("health_score", 0))))
        except (TypeError, ValueError):
            score = 0

        return SwarmReport(
            health_score=score,
            headline=str(data.get("headline", "")).strip(),
            persona_verdicts=verdicts,
            shared_blockers=[str(b).strip() for b in data.get("shared_blockers", []) if str(b).strip()],
            prioritized_fixes=fixes,
            worst_persona_id=str(data.get("worst_persona_id", "")),
            best_persona_id=str(data.get("best_persona_id", "")),
        )

    def _heuristic(self, swarm_result) -> SwarmReport:
        """No-LLM fallback: a verdict report built purely from run outcomes."""
        runs = swarm_result.runs
        verdicts = [
            PersonaVerdict(
                r.persona_id,
                _status_to_verdict(r.status),
                _heuristic_summary(r),
            )
            for r in runs
        ]
        n = len(runs) or 1
        succeeded = sum(1 for v in verdicts if v.verdict == "success")
        persona_blockers = swarm_result.blockers()
        audit = getattr(swarm_result, "audit", None)
        audit_blockers = audit.by_severity("blocker") if audit else 0

        # Audit blockers penalize the health score too — a lorem-ipsum page or
        # a broken-link page is a real "this isn't ready" signal.
        score = int(100 * succeeded / n) - min(40, persona_blockers * 8) - min(30, audit_blockers * 6)
        score = max(0, min(100, score))

        shared = [f.note for r in runs for f in r.friction_points if f.severity == "blocker"]
        fixes = []
        # Audit blockers go to the top of the fix list, before persona friction.
        if audit:
            cat_label = {
                "links": "broken link", "seo": "SEO/meta",
                "a11y": "accessibility", "copy": "copywriting",
                "ui": "UI", "auth": "auth flow", "mixed-content": "mixed content",
            }
            for f in audit.findings:
                if f.severity == "blocker":
                    fixes.append({
                        "priority": "high",
                        "issue": f.note,
                        "why": f"Static audit ({cat_label.get(f.category, f.category)}) on {f.page_url}.",
                    })
        for r in runs:
            for f in r.friction_points:
                if f.severity in ("blocker", "major"):
                    fixes.append({
                        "priority": "high" if f.severity == "blocker" else "medium",
                        "issue": f.note,
                        "why": f"Hit by {r.persona_name}.",
                    })
        if audit:
            for f in audit.findings:
                if f.severity == "major":
                    fixes.append({
                        "priority": "medium",
                        "issue": f.note,
                        "why": f"Static audit ({f.category}) on {f.page_url}.",
                    })

        worst = min(runs, key=lambda r: _outcome_rank(r.status), default=None)
        best = max(runs, key=lambda r: _outcome_rank(r.status), default=None)
        audit_tail = (
            f"  +  static audit: {audit_blockers} blocker(s), "
            f"{audit.by_severity('major') if audit else 0} major"
            if audit and audit.findings else ""
        )
        return SwarmReport(
            health_score=score,
            headline=f"{succeeded}/{n} personas completed the goal "
                     f"({persona_blockers} persona blocker(s){audit_tail}). "
                     f"Heuristic report — no AI judge.",
            persona_verdicts=verdicts,
            shared_blockers=shared[:8],
            prioritized_fixes=fixes[:12],
            worst_persona_id=worst.persona_id if worst else "",
            best_persona_id=best.persona_id if best else "",
        )


def _status_to_verdict(status: str) -> str:
    return {
        "completed": "success",
        "abandoned": "failure",
        "stuck": "partial",
        "error": "failure",
    }.get(status, "partial")


def _outcome_rank(status: str) -> int:
    return {"completed": 3, "stuck": 2, "abandoned": 1, "error": 0}.get(status, 0)


def _heuristic_summary(run) -> str:
    if run.status == "completed":
        base = f"Completed the goal in {run.step_count} steps."
    elif run.status == "abandoned":
        base = f"Gave up after {run.step_count} steps."
    elif run.status == "error":
        base = f"Run failed: {run.error}"
    else:
        base = f"Ran out of steps after {run.step_count} without finishing."
    b, m = run.friction_by_severity("blocker"), run.friction_by_severity("major")
    if b or m:
        base += f" {b} blocker(s), {m} major friction point(s)."
    return base
