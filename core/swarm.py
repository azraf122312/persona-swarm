"""
core/swarm.py - The swarm orchestrator.

Maps the target site once, then spawns one PersonaAgent per persona and runs
them in parallel — each in its own browser. Because every persona reasons and
behaves differently, the same goal produces genuinely different coverage; that
divergence is the whole point of the swarm.

Parallelism here is a local thread pool (each persona agent owns an isolated
Playwright browser). The structure intentionally mirrors a ruflo swarm — a
coordinator dispatching independent workers — so the orchestration can later be
delegated to ruflo's swarm tools without reshaping the result model.
"""

import time
from datetime import datetime
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.crawler import SiteCrawler, SiteMap
from agents.persona_agent import PersonaAgent, PersonaRun
from personas.profiles import get_personas


@dataclass
class SwarmResult:
    target_url: str
    goal: str
    started_at: str = ""
    total_time_ms: float = 0.0
    site_map: SiteMap = None
    runs: list = field(default_factory=list)  # list[PersonaRun]

    def completed(self):
        return [r for r in self.runs if r.status == "completed"]

    def abandoned(self):
        return [r for r in self.runs if r.status == "abandoned"]

    def stuck(self):
        return [r for r in self.runs if r.status == "stuck"]

    def errored(self):
        return [r for r in self.runs if r.status == "error"]

    def total_friction(self) -> int:
        return sum(len(r.friction_points) for r in self.runs)

    def blockers(self) -> int:
        return sum(r.friction_by_severity("blocker") for r in self.runs)


class PersonaSwarm:
    def __init__(self, llm, max_steps: int = 15, headless: bool = True,
                 timeout_ms: int = 30000, max_concurrency: int = 4):
        self.llm = llm
        self.max_steps = max_steps
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.max_concurrency = max_concurrency

    def run(self, target_url: str, goal: str, persona_ids=None, max_pages: int = 20,
            progress_cb=None) -> SwarmResult:
        """
        progress_cb, if given, is called from worker threads with dict events:
          {"event": "site_mapped", "pages": int}
          {"event": "persona_started", "persona_id": str, "persona_name": str}
          {"event": "persona_done", "persona_id": str, "status": str}
        Callbacks fire on worker threads — keep them thread-safe (e.g. a queue).
        """
        started = time.time()
        result = SwarmResult(
            target_url=target_url,
            goal=goal,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

        def emit(event):
            if progress_cb:
                try:
                    progress_cb(event)
                except Exception:
                    pass

        # Phase 1 — map the site (coordinator pass).
        crawler = SiteCrawler(headless=self.headless, timeout_ms=self.timeout_ms)
        result.site_map = crawler.crawl(target_url, max_pages=max_pages)
        emit({"event": "site_mapped", "pages": result.site_map.pages_crawled})
        site_overview = result.site_map.overview()

        # Phase 2 — dispatch one persona agent per persona, in parallel.
        personas = get_personas(persona_ids)

        def run_one(persona) -> PersonaRun:
            emit({"event": "persona_started", "persona_id": persona.id,
                  "persona_name": persona.name})
            agent = PersonaAgent(
                persona=persona,
                llm=self.llm,
                max_steps=self.max_steps,
                headless=self.headless,
                timeout_ms=self.timeout_ms,
            )
            run = agent.run(target_url, goal, site_overview)
            emit({"event": "persona_done", "persona_id": persona.id, "status": run.status})
            return run

        workers = max(1, min(self.max_concurrency, len(personas)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, p): p for p in personas}
            for future in as_completed(futures):
                persona = futures[future]
                try:
                    result.runs.append(future.result())
                except Exception as e:
                    result.runs.append(PersonaRun(
                        persona_id=persona.id,
                        persona_name=persona.name,
                        persona_emoji=persona.emoji,
                        goal=goal,
                        start_url=target_url,
                        status="error",
                        error=f"Swarm worker failed: {e}",
                    ))

        # Keep results in roster order for stable display.
        order = {p.id: i for i, p in enumerate(personas)}
        result.runs.sort(key=lambda r: order.get(r.persona_id, 999))
        result.total_time_ms = (time.time() - started) * 1000
        return result
