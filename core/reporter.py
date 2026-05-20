"""
core/reporter.py - Turns a swarm run into a report, and remembers past runs.

to_dict / save_json / generate_markdown produce the shareable report. RunHistory
persists each run keyed by (target, goal) and diffs the current run against the
previous one — that cross-run diff is the regression detector: a persona that
went success -> failure, a new blocker, a dropped health score.
"""

import json
import os
import hashlib
from datetime import datetime


def to_dict(swarm_result, swarm_report) -> dict:
    sm = swarm_result.site_map
    personas = []
    for r in swarm_result.runs:
        verdict = swarm_report.verdict_for(r.persona_id)
        personas.append({
            "persona_id": r.persona_id,
            "persona_name": r.persona_name,
            "emoji": r.persona_emoji,
            "status": r.status,
            "verdict": verdict.verdict,
            "summary": verdict.summary,
            "outcome_note": r.outcome_note,
            "step_count": r.step_count,
            "final_url": r.final_url,
            "duration_ms": round(r.duration_ms, 1),
            "error": r.error,
            "friction": [
                {"step": f.step, "severity": f.severity, "note": f.note}
                for f in r.friction_points
            ],
            "steps": [
                {"index": s.index, "action": s.action, "target": s.target,
                 "thought": s.thought, "observation": s.observation, "url": s.url}
                for s in r.steps
            ],
        })

    return {
        "meta": {
            "target_url": swarm_result.target_url,
            "goal": swarm_result.goal,
            "started_at": swarm_result.started_at,
            "total_time_ms": round(swarm_result.total_time_ms, 1),
            "persona_count": len(swarm_result.runs),
        },
        "site_map": {
            "pages_crawled": sm.pages_crawled if sm else 0,
            "pages": [
                {"url": p.url, "title": p.title, "status": p.status,
                 "n_forms": p.n_forms, "error": p.error}
                for p in (sm.pages if sm else [])
            ],
        },
        "swarm_report": {
            "health_score": swarm_report.health_score,
            "headline": swarm_report.headline,
            "shared_blockers": swarm_report.shared_blockers,
            "prioritized_fixes": swarm_report.prioritized_fixes,
            "worst_persona_id": swarm_report.worst_persona_id,
            "best_persona_id": swarm_report.best_persona_id,
        },
        "outcomes": {
            "completed": len(swarm_result.completed()),
            "abandoned": len(swarm_result.abandoned()),
            "stuck": len(swarm_result.stuck()),
            "errored": len(swarm_result.errored()),
            "total_friction": swarm_result.total_friction(),
            "blockers": swarm_result.blockers(),
        },
        "personas": personas,
    }


def save_json(report_dict: dict, filepath: str) -> str:
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)
    return filepath


def generate_markdown(report_dict: dict) -> str:
    m = report_dict["meta"]
    sr = report_dict["swarm_report"]
    oc = report_dict["outcomes"]
    md = [
        "# Persona Swarm — Usability Report",
        "",
        f"**Goal:** {m['goal']}  ",
        f"**Target:** {m['target_url']}  ",
        f"**Run:** {m['started_at']}  ",
        f"**Personas:** {m['persona_count']}",
        "",
        f"## Health Score: {sr['health_score']}/100",
        "",
        f"{sr['headline']}",
        "",
        f"- Completed: {oc['completed']}  |  Abandoned: {oc['abandoned']}  "
        f"|  Stuck: {oc['stuck']}  |  Errored: {oc['errored']}",
        f"- Friction points: {oc['total_friction']}  |  Blockers: {oc['blockers']}",
        "",
    ]
    if sr["shared_blockers"]:
        md += ["## Shared Blockers (hit multiple personas)", ""]
        md += [f"- {b}" for b in sr["shared_blockers"]] + [""]
    if sr["prioritized_fixes"]:
        md += ["## Prioritized Fixes", ""]
        for fix in sr["prioritized_fixes"]:
            md.append(f"- **[{fix['priority'].upper()}]** {fix['issue']}")
            if fix.get("why"):
                md.append(f"  - _{fix['why']}_")
        md.append("")
    md += ["## Per-Persona Results", ""]
    for p in report_dict["personas"]:
        md.append(f"### {p['emoji']} {p['persona_name']} — {p['verdict'].upper()}")
        md.append("")
        if p["summary"]:
            md.append(p["summary"])
            md.append("")
        md.append(f"- Self-reported: {p['status']} in {p['step_count']} steps")
        if p["friction"]:
            md.append("- Friction:")
            for f in p["friction"]:
                md.append(f"  - [{f['severity']}] {f['note']}")
        md.append("")
    return "\n".join(md)


# --------------------------------------------------------------------------
# Run history & regression detection
# --------------------------------------------------------------------------

def _run_key(target_url: str, goal: str) -> str:
    raw = f"{target_url.strip().lower()}||{goal.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class RunHistory:
    """Persists swarm runs and diffs the latest against the previous one."""

    def __init__(self, history_dir: str = "reports/history"):
        self.history_dir = history_dir

    def _file(self, target_url: str, goal: str) -> str:
        return os.path.join(self.history_dir, f"{_run_key(target_url, goal)}.jsonl")

    def previous(self, target_url: str, goal: str):
        """Most recent stored run for this (target, goal), or None."""
        path = self._file(target_url, goal)
        if not os.path.exists(path):
            return None
        last = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = line
        if not last:
            return None
        try:
            return json.loads(last)
        except json.JSONDecodeError:
            return None

    def save(self, report_dict: dict) -> str:
        m = report_dict["meta"]
        path = self._file(m["target_url"], m["goal"])
        os.makedirs(self.history_dir, exist_ok=True)
        snapshot = {
            "started_at": m["started_at"],
            "health_score": report_dict["swarm_report"]["health_score"],
            "verdicts": {p["persona_id"]: p["verdict"] for p in report_dict["personas"]},
            "blockers": report_dict["outcomes"]["blockers"],
            "total_friction": report_dict["outcomes"]["total_friction"],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        return path

    def regression_diff(self, report_dict: dict, previous: dict) -> dict:
        """Compare the current report against a previous snapshot."""
        if not previous:
            return {"has_baseline": False, "regressions": [], "improvements": [], "deltas": {}}

        cur_score = report_dict["swarm_report"]["health_score"]
        prev_score = previous.get("health_score", 0)
        cur_verdicts = {p["persona_id"]: p["verdict"] for p in report_dict["personas"]}
        prev_verdicts = previous.get("verdicts", {})

        rank = {"failure": 0, "partial": 1, "success": 2}
        regressions, improvements = [], []
        for pid, cur in cur_verdicts.items():
            prev = prev_verdicts.get(pid)
            if prev is None:
                continue
            if rank.get(cur, 1) < rank.get(prev, 1):
                regressions.append(f"{pid}: {prev} -> {cur}")
            elif rank.get(cur, 1) > rank.get(prev, 1):
                improvements.append(f"{pid}: {prev} -> {cur}")

        deltas = {
            "health_score": cur_score - prev_score,
            "blockers": report_dict["outcomes"]["blockers"] - previous.get("blockers", 0),
            "total_friction": report_dict["outcomes"]["total_friction"]
            - previous.get("total_friction", 0),
        }
        if deltas["health_score"] < 0:
            regressions.append(f"Health score dropped {prev_score} -> {cur_score}")
        elif deltas["health_score"] > 0:
            improvements.append(f"Health score rose {prev_score} -> {cur_score}")

        return {
            "has_baseline": True,
            "baseline_date": previous.get("started_at", ""),
            "regressions": regressions,
            "improvements": improvements,
            "deltas": deltas,
        }


def timestamped_path(prefix: str = "reports/swarm", ext: str = "json") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}.{ext}"
