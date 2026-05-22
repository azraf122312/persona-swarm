"""
server.py - HTTP backend for the Persona Swarm web app.

Serves the static site in web/ and exposes a small JSON API so a swarm run can
be launched and watched from a browser instead of the Streamlit dashboard.

Each run executes in its own background thread. The swarm's progress callbacks
are buffered on the job; the browser polls GET /api/runs/<id> for live status
and, when finished, the full report.

    pip install -r requirements.txt
    playwright install chromium
    python server.py            # -> http://localhost:8000
"""

import os
import time
import uuid
import logging
import threading

from flask import Flask, request, jsonify, send_from_directory

from core.config import settings
from core.llm import LLMClient, LLMError
from core.swarm import PersonaSwarm
from core.judge import Judge
from core import reporter
from personas.profiles import PERSONAS

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
JOB_TTL_S = 3600  # finished jobs are forgotten after an hour

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger("persona-swarm")

app = Flask(__name__, static_folder=None)

_JOBS = {}
_JOBS_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Job model — one swarm run, owned by a background thread, polled by the browser
# --------------------------------------------------------------------------
class Job:
    def __init__(self, job_id, params):
        self.id = job_id
        self.params = params
        self._lock = threading.Lock()
        self.created_at = time.time()
        self.status = "queued"     # queued|mapping|running|judging|done|error
        self.phase = "Queued."
        self.events = []
        self.report = None
        self.regression = None
        self.error = None

    def emit(self, event):
        with self._lock:
            self.events.append(event)

    def update(self, **fields):
        with self._lock:
            for key, value in fields.items():
                setattr(self, key, value)

    def snapshot(self):
        """A browser-safe view of the job — never includes the API key."""
        with self._lock:
            return {
                "job_id": self.id,
                "status": self.status,
                "phase": self.phase,
                "events": list(self.events),
                "report": self.report,
                "regression": self.regression,
                "error": self.error,
            }

    def finished(self):
        return self.status in ("done", "error")


def _run_job(job):
    """Execute a swarm run end to end. Runs on a daemon thread."""
    p = job.params
    try:
        llm = LLMClient(provider=p["provider"], api_key=p["api_key"], model=p["model"])
    except LLMError as e:
        job.update(status="error", error=f"LLM setup failed: {e}")
        return

    try:
        history = reporter.RunHistory()
        previous = history.previous(p["url"], p["goal"])

        swarm = PersonaSwarm(
            llm=llm,
            max_steps=p["max_steps"],
            headless=True,
            timeout_ms=settings.crawl_timeout_ms,
            max_concurrency=p["concurrency"],
        )
        judge = Judge(llm=llm)

        job.update(status="mapping", phase="Mapping the target site...")

        def on_progress(event):
            # Fires from worker threads — Job.emit/update are lock-guarded.
            job.emit(event)
            if event.get("event") == "site_mapped":
                job.update(
                    status="running",
                    phase=f"Site mapped ({event.get('pages', 0)} pages). "
                          f"Personas exploring...",
                )

        result = swarm.run(
            p["url"], p["goal"],
            persona_ids=p["persona_ids"],
            max_pages=p["max_pages"],
            progress_cb=on_progress,
        )

        job.update(status="judging", phase="Judging the runs...")
        report = judge.synthesize(result)
        report_dict = reporter.to_dict(result, report)
        regression = history.regression_diff(report_dict, previous)
        history.save(report_dict)
        try:
            reporter.save_json(report_dict, reporter.timestamped_path())
        except Exception as e:
            log.warning("Could not save report JSON: %s", e)

        job.update(status="done", phase="Swarm complete.",
                   report=report_dict, regression=regression)
        log.info("Job %s done — health %s/100",
                 job.id, report_dict["swarm_report"]["health_score"])
    except Exception as e:
        log.exception("Job %s crashed", job.id)
        job.update(status="error", error=f"Swarm run failed: {e}")


def _prune_jobs():
    """Drop finished jobs older than the TTL so the registry stays small."""
    now = time.time()
    with _JOBS_LOCK:
        stale = [jid for jid, j in _JOBS.items()
                 if j.finished() and now - j.created_at > JOB_TTL_S]
        for jid in stale:
            del _JOBS[jid]


def _clamp_int(data, key, default, lo, hi):
    try:
        return max(lo, min(hi, int(data.get(key, default))))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.get("/api/personas")
def api_personas():
    return jsonify([
        {
            "id": p.id,
            "name": p.name,
            "emoji": p.emoji,
            "summary": p.summary,
            "patience": p.patience,
            "mobile": bool(p.viewport.get("is_mobile")),
        }
        for p in PERSONAS
    ])


@app.post("/api/runs")
def api_create_run():
    _prune_jobs()
    data = request.get_json(silent=True) or {}

    url = str(data.get("url", "")).strip()
    goal = str(data.get("goal", "")).strip()
    provider = str(data.get("provider", "anthropic")).strip().lower()
    api_key = str(data.get("api_key", "")).strip()
    model = str(data.get("model", "")).strip()

    valid_ids = {p.id for p in PERSONAS}
    persona_ids = [pid for pid in (data.get("persona_ids") or []) if pid in valid_ids]

    errors = []
    if not (url.startswith("http://") or url.startswith("https://")):
        errors.append("Target URL must start with http:// or https://.")
    if not goal:
        errors.append("A goal is required.")
    if provider not in ("anthropic", "openai"):
        errors.append("Provider must be 'anthropic' or 'openai'.")
    if not api_key:
        errors.append("An API key is required — persona agents need an LLM to act.")
    if not persona_ids:
        errors.append("Select at least one persona.")
    if errors:
        return jsonify({"errors": errors}), 400

    if not model:
        model = settings.model_for(provider)

    params = {
        "url": url, "goal": goal, "provider": provider,
        "api_key": api_key, "model": model, "persona_ids": persona_ids,
        "max_steps": _clamp_int(data, "max_steps", 15, 5, 30),
        "max_pages": _clamp_int(data, "max_pages", 20, 3, 40),
        "concurrency": _clamp_int(data, "concurrency", 4, 1, 8),
    }

    job_id = uuid.uuid4().hex[:12]
    job = Job(job_id, params)
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    threading.Thread(target=_run_job, args=(job,), daemon=True,
                     name=f"swarm-{job_id}").start()
    log.info("Job %s queued — %d persona(s) on %s", job_id, len(persona_ids), url)
    return jsonify({"job_id": job_id}), 202


@app.get("/api/runs/<job_id>")
def api_get_run(job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "Unknown or expired job id."}), 404
    return jsonify(job.snapshot())


# --------------------------------------------------------------------------
# Static site
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:filename>")
def static_file(filename):
    if filename.startswith("api/"):
        return jsonify({"error": "Not found."}), 404
    target = os.path.normpath(os.path.join(WEB_DIR, filename))
    if not target.startswith(WEB_DIR) or not os.path.isfile(target):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory(WEB_DIR, filename)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"\n  Persona Swarm  ->  http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, threaded=True)
