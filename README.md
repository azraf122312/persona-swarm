# 🐝 Persona Swarm

**A swarm of distinct user personas tests your app — each in its own browser, each reasoning differently — and tells you where real people get stuck.**

Drop a URL and a goal in plain English. Eighteen distinct personas (eight on by default) each try to accomplish it. Five minutes later you have every dead end, blocker, and confusing flow real people hit — ranked by what to fix first. Plus a static technical audit that catches broken links, SEO gaps, accessibility issues, lorem ipsum, mixed content, and auth softlocks.

Built for vibe-coded apps, indie products, and small teams who ship faster than they QA.

---

## Why this exists

A scripted happy-path test only ever fails the way it was written to. Your users aren't one person — they're impatient, cautious, on a phone, using a screen reader, distrustful, distracted. Each gets stuck somewhere different, and a single test bot never sees it.

> Your Playwright tests confirm the path you wrote works.
> Persona Swarm finds the paths you never wrote.

---

## What it catches

### Persona findings (subjective UX)
Each persona reports friction in its own voice — the impatient user notices slow loads, the screen-reader user notices missing labels, the skeptical shopper notices hidden fees. Severity is `blocker` / `major` / `minor`.

### Static audit findings (deterministic, no LLM)
On top of the persona runs, every swarm runs a technical audit:

| Category | What it catches |
|---|---|
| **links** | Broken links (HEAD-tested), 4xx / 5xx pages, DNS failures |
| **seo** | Missing `<title>`, meta description, `<h1>`, canonical, Open Graph tags; oversized titles/descriptions |
| **a11y** | Images without alt text, form inputs without labels |
| **copy** | Live lorem ipsum, `TODO/TBD/FIXME` placeholders, vague link text (`click here`, `read more`) |
| **ui** | Tap targets smaller than 32×32 px, page load failures |
| **mixed-content** | `http://` resources on `https://` pages |
| **auth** | Login / signup forms with no visible error or feedback region (softlock risk) |

Audit findings are merged into the same prioritized fix list — audit blockers sort to the top alongside persona blockers.

### Regression detection
Every run is saved, keyed to its `(URL, goal)`. Re-run later and the swarm diffs against the previous run — a persona that slipped from success to failure, a new blocker, a dropped health score — and flags it at the top of the report.

---

## Quick start

### Requirements
- Python 3.13 (the launcher must resolve `py -3.13` — bare `py` may pick a free-threaded build that breaks Playwright)
- An Anthropic or OpenAI API key (the personas need an LLM to reason and act)
- A browser (the in-browser dashboard runs at `http://localhost:8000`)

### Install

```bash
git clone https://github.com/azraf122312/persona-swarm.git
cd persona-swarm

py -3.13 -m pip install -r requirements.txt
py -3.13 -m playwright install chromium
```

### Run

```bash
py -3.13 server.py
```

Then open **http://localhost:8000** in a browser. Click *Launch a swarm*, paste a URL and a goal, paste your API key, pick personas, and hit launch.

> Your API key is held in memory for the duration of the run and never written to disk. Reports save to `reports/` on your machine. There is no Persona Swarm cloud.

### Streamlit dashboard (alternative UI)

If you prefer Streamlit:

```bash
py -3.13 -m streamlit run app.py
```

---

## Configuration

Copy `.env.example` to `.env` and edit:

```
AI_PROVIDER=anthropic                                   # anthropic | openai
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001               # default — fast, cheap
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

MAX_PAGES=20                                            # crawler limit
CRAWL_TIMEOUT_MS=30000
MAX_STEPS_PER_PERSONA=15
HEADLESS=true                                           # set false to watch the swarm live
```

You can also enter the API key directly in the web UI — it's never sent anywhere except your local server.

---

## The personas

Eighteen total, grouped in three tiers. The core 8 are checked by default; the rest are opt-in per run so cost stays predictable.

### Core 8 — orthogonal failure modes (default on)
| Persona | Catches |
|---|---|
| ⚡ Impatient Power User | Slow loads, redundant steps, friction in fast flows |
| 🐣 Cautious First-Timer | Jargon, unclear labels, scary irreversible-looking actions |
| 🦮 Screen-Reader User | Missing accessible names, alt text, keyboard traps |
| 📱 Mobile Thumb User | Tiny tap targets, horizontal scroll, fixed banners covering content |
| 🕵️ Skeptical Shopper | Hidden fees, missing trust signals, forced signups |
| 🤹 Distracted Multitasker | Lost form state, silent timeouts, no save-progress |
| 🌍 Non-Native Speaker | Idioms, slang, clever copy that doesn't survive literal reading |
| 😤 Rage Clicker | Buttons with no loading state, silent failures |

### Extra 6 — universal value, opt-in
| Persona | Catches |
|---|---|
| 🔁 Returning Power User | Redesign regressions, broken bookmarks, removed shortcuts |
| 👓 Older / Low-Vision User | Low contrast, thin fonts, color-only meaning |
| 🛡️ Privacy-Strict User | Sites that break without trackers / cookies, dark-pattern banners |
| 🚪 Cancellation Hunter | Buried cancel flows, dark patterns in the exit path |
| ✍️ Awkward-Data Filler | Validation that breaks on `O'Brien`, `José`, `user+test@brand.dev` |
| ⌨️ Keyboard-Only Power User | Missing focus rings, broken tab order, focus traps |

### Niche 4 — context-specific, opt-in
| Persona | Best for |
|---|---|
| ⚖️ Comparison Shopper | Marketing / pricing pages — is the value prop clear vs. competitors? |
| 📋 Compliance Buyer | B2B SaaS — missing security / privacy / legal pages |
| 🔍 First-Touch Prospect | Ad-targeted landing pages — 10-second comprehension test |
| 🐢 Slow-Connection User | Media-heavy / SPA-heavy sites — skeleton screens, layout shift |

Add your own in `personas/profiles.py` — the UI picks them up automatically through `/api/personas`.

---

## How it works (pipeline)

```
  ┌─────────────────────────────────────────────────────────────┐
  │  1. CRAWL         site mapper builds a page graph           │
  │  2. AUDIT         static checks — links, seo, a11y, copy    │
  │  3. SWARM         N persona agents, one browser each        │
  │  4. JUDGE         independent LLM scores + ranks fixes      │
  │  5. DIFF          regression vs. the previous run           │
  │  6. REPORT        JSON + Markdown + live web view           │
  └─────────────────────────────────────────────────────────────┘
```

- **Crawler** (`core/crawler.py`) — Playwright BFS that walks the site and harvests every audit signal (meta tags, links, alt-text gaps, tap targets, mixed content) in one round-trip per page.
- **Auditor** (`core/auditor.py`) — deterministic, no LLM. Runs HEAD-tests on internal links concurrently.
- **Persona agents** (`agents/persona_agent.py`) — each persona spawns its own Chromium with its own viewport. Reads the page, picks an action, logs friction in character.
- **Judge** (`core/judge.py`) — independent LLM verdict per persona, plus the synthesis: shared blockers, prioritized fixes, headline, health score 0–100.
- **Reporter** (`core/reporter.py`) — turns the result into JSON / Markdown. Run history is one JSONL per `(URL, goal)` keyed by hash.

Each persona is independent and runs in its own thread, so they're naturally parallel. Default concurrency is 4.

---

## Repository layout

```
.
├── server.py                  Flask backend — API + static file serving
├── app.py                     Streamlit dashboard (alternative UI)
├── core/
│   ├── config.py              env loading + defaults
│   ├── crawler.py             site mapper + audit data collection
│   ├── auditor.py             static audit (no LLM)
│   ├── perception.py          live-page DOM perception for personas
│   ├── llm.py                 Anthropic / OpenAI wrapper
│   ├── swarm.py               orchestrator
│   ├── judge.py               independent verdict + synthesis
│   └── reporter.py            JSON / Markdown / run history / regression diff
├── agents/
│   └── persona_agent.py       one persona, one browser, one goal
├── personas/
│   └── profiles.py            the 18-persona roster
├── web/                       in-browser dashboard
│   ├── index.html             landing
│   ├── run.html               run dashboard
│   ├── main.js                landing interactions
│   ├── app.js                 run-dashboard logic
│   └── styles.css             brutalist bento design system
├── reports/                   saved reports + history JSONL (gitignored)
└── STRATEGY.md                product / pricing / go-to-market notes
```

---

## Privacy & safety

- **No cloud.** Persona Swarm runs locally. The target URL, goal, and API key go only to the server you run yourself.
- **No persistence of secrets.** Your API key lives in memory for the run.
- **Exploratory, not destructive.** Personas read, scroll, type, and click — they're looking for friction, not trying to fire destructive actions. If your goal touches anything irreversible, point the swarm at a staging URL.
- **HEAD-only link checks.** The audit's broken-link pass uses HEAD requests with a polite user-agent (`PersonaSwarm-Auditor/1.0`). It does not crawl externally.

---

## FAQ

**Is the swarm real, or is the dashboard just a mockup?**
Real. Each persona is an LLM driving its own headless Chromium browser through Playwright. The console on the landing page is a scripted demo; a real run drives real browsers.

**Does anything I type leave my browser?**
Persona Swarm runs locally — there is no Persona Swarm cloud. Your URL, goal, and API key go only to the server you run yourself.

**How is this different from Playwright tests I already write?**
A Playwright test confirms the path you scripted still works. Persona Swarm finds the paths you never scripted. The personas wander off the happy path on purpose.

**Will it work on a vibe-coded app — something I built with Claude Code or Cursor?**
Yes — that's a primary use case. The report names each friction point, the persona who hit it, and ranks the fixes, so you can hand a prioritized list straight to the LLM writing your code.

**How long does a run take?**
A few minutes. Core 8 personas at default settings finishes in ~5 min. Full 18-persona run is ~6 min. More steps and more pages cost more time and tokens.

**Can it catch regressions?**
Yes. Every run is saved, keyed to its URL and goal. Re-run later and the swarm diffs against the previous run — a persona that slipped from success to failure, a new blocker, a dropped health score — and flags it at the top of the report.

---

## Roadmap

- **Shipped** — eight personas, parallel isolated browsers, AI judge, regression diffs, static auditor, in-browser dashboard, 18-persona roster
- **Now** — pricing page + paid tiers
- **Next** — scheduled runs, shareable report links, CI check (GitHub Action), session injection for auth-walled apps, stealth mode for anti-bot sites

See [STRATEGY.md](./STRATEGY.md) for the business plan, pricing model, and go-to-market sequence.

---

## License

TBD — currently personal / source-available. Reach out before reusing in commercial contexts.

---

*Built with Playwright + Flask. Made for shipping faster than you can QA.*
