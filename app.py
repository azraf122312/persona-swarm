"""
app.py - Streamlit dashboard for Persona Swarm.
Run with: streamlit run app.py
"""

import json
import time

import streamlit as st

st.set_page_config(page_title="Persona Swarm", page_icon="🐝", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""<style>
    .hero {
        background: linear-gradient(135deg, #f5576c 0%, #f093fb 100%);
        padding: 1.4rem 2rem; border-radius: 14px; margin-bottom: 1.2rem; color: white;
    }
    .hero h1 { margin: 0; font-size: 2rem; font-weight: 800; }
    .hero p { margin: 0.3rem 0 0 0; opacity: 0.92; }
    .pcard {
        background: #1e1e2e; padding: 1rem 1.2rem; border-radius: 10px;
        border-left: 4px solid #585b70; margin-bottom: 0.7rem;
    }
    .pcard.success { border-left-color: #a6e3a1; }
    .pcard.partial { border-left-color: #f9e2af; }
    .pcard.failure { border-left-color: #f38ba8; }
    .vbadge {
        display:inline-block; padding:0.15rem 0.6rem; border-radius:5px;
        font-size:0.72rem; font-weight:700; text-transform:uppercase;
    }
    .v-success { background:#a6e3a122; color:#a6e3a1; border:1px solid #a6e3a144; }
    .v-partial { background:#f9e2af22; color:#f9e2af; border:1px solid #f9e2af44; }
    .v-failure { background:#f38ba822; color:#f38ba8; border:1px solid #f38ba844; }
    .fr-blocker { color:#f38ba8; }
    .fr-major { color:#fab387; }
    .fr-minor { color:#89b4fa; }
    div[data-testid="stMetric"] {
        background:#1e1e2e; padding:0.8rem; border-radius:10px; border:1px solid #313244;
    }
</style>""", unsafe_allow_html=True)

from core.config import settings
from core.llm import LLMClient, LLMError
from core.swarm import PersonaSwarm
from core.judge import Judge
from core import reporter
from personas.profiles import PERSONAS, get_persona

_DEFAULTS = {"report_dict": None, "regression": None, "running": False}
for k, v in _DEFAULTS.items():
    st.session_state.setdefault(k, v)


# --------------------------------------------------------------------------
# Sidebar — configuration
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    provider = st.selectbox(
        "AI Provider", ["anthropic", "openai"],
        index=0 if settings.ai_provider != "openai" else 1,
        help="Persona agents need an LLM to reason. Required.",
    )
    default_key = settings.api_key_for(provider) or ""
    if "your-key" in default_key:
        default_key = ""
    api_key = st.text_input(
        f"{provider.title()} API Key", type="password", value=default_key,
        placeholder="sk-ant-..." if provider == "anthropic" else "sk-...",
    )
    model = st.text_input("Model", value=settings.model_for(provider))

    st.markdown("---")
    st.markdown("### 🐝 Swarm Settings")
    max_steps = st.slider("Max steps per persona", 5, 30, settings.max_steps_per_persona)
    max_pages = st.slider("Site map: max pages", 3, 40, settings.max_pages)
    concurrency = st.slider("Parallel personas", 1, 8, 4,
                            help="How many persona browsers run at once.")
    headless = st.checkbox("Headless browsers", value=settings.headless)

    has_key = bool(api_key)
    if not has_key:
        st.warning("An API key is required — persona agents need an LLM to act.")


# --------------------------------------------------------------------------
# Run logic
# --------------------------------------------------------------------------
def execute_swarm(url, goal, persona_ids):
    try:
        llm = LLMClient(provider=provider, api_key=api_key, model=model)
    except LLMError as e:
        st.error(f"LLM setup failed: {e}")
        return

    history = reporter.RunHistory()
    previous = history.previous(url, goal)

    swarm = PersonaSwarm(
        llm=llm, max_steps=max_steps, headless=headless,
        timeout_ms=settings.crawl_timeout_ms, max_concurrency=concurrency,
    )
    judge = Judge(llm=llm)

    with st.status("Running the swarm...", expanded=True) as status:
        status.write("Mapping the site...")
        events = []
        result = swarm.run(url, goal, persona_ids=persona_ids, max_pages=max_pages,
                           progress_cb=events.append)
        status.write(f"Site mapped: {result.site_map.pages_crawled} pages. "
                     f"{len(result.runs)} personas finished.")
        status.write("Judging results...")
        report = judge.synthesize(result)
        report_dict = reporter.to_dict(result, report)
        regression = history.regression_diff(report_dict, previous)
        history.save(report_dict)
        reporter.save_json(report_dict, reporter.timestamped_path())
        status.update(label="Swarm complete.", state="complete")

    st.session_state.report_dict = report_dict
    st.session_state.regression = regression


tab_run, tab_results, tab_about = st.tabs(["🐝  Run Swarm", "📊  Results", "ℹ️  About"])

# --------------------------------------------------------------------------
# TAB 1 — Run
# --------------------------------------------------------------------------
with tab_run:
    st.markdown(
        '<div class="hero"><h1>🐝 Persona Swarm</h1>'
        '<p>A swarm of user personas tests whether real people can use your app.</p></div>',
        unsafe_allow_html=True,
    )

    col_main, col_side = st.columns([2, 1])
    with col_main:
        url = st.text_input("Target URL", placeholder="https://example.com")
        goal = st.text_input(
            "Goal — what should a user be able to do?",
            placeholder="Sign up for an account",
            help="Describe the intent in plain language. Every persona tries this.",
        )

        st.markdown("**Personas in the swarm**")
        chosen = []
        pcols = st.columns(2)
        for i, p in enumerate(PERSONAS):
            with pcols[i % 2]:
                if st.checkbox(p.label(), value=True, key=f"persona_{p.id}",
                               help=p.summary):
                    chosen.append(p.id)

        valid = bool(url and url.startswith("http")) and bool(goal) and has_key and chosen
        if st.button("🚀  Launch Swarm", type="primary", use_container_width=True,
                     disabled=not valid):
            execute_swarm(url.strip(), goal.strip(), chosen)
        if url and not url.startswith("http"):
            st.caption("URL must start with http:// or https://")
        if not chosen:
            st.caption("Select at least one persona.")

    with col_side:
        st.markdown("### How it works")
        st.markdown(
            "1. The site is **mapped** once.\n"
            "2. Each **persona** gets its own browser and tries your goal.\n"
            "3. They log **friction** the way that persona would feel it.\n"
            "4. A **judge** scores the goal and flags shared blockers.\n"
            "5. Re-run later to catch **regressions**."
        )


# --------------------------------------------------------------------------
# TAB 2 — Results
# --------------------------------------------------------------------------
with tab_results:
    rd = st.session_state.report_dict
    if not rd:
        st.info("No results yet. Launch a swarm from the **Run Swarm** tab.")
    else:
        meta = rd["meta"]
        sr = rd["swarm_report"]
        oc = rd["outcomes"]

        st.markdown(f"### 🎯 {meta['goal']}")
        st.caption(f"{meta['target_url']}  •  {meta['started_at']}  "
                   f"•  {meta['total_time_ms']/1000:.0f}s  •  {meta['persona_count']} personas")

        score = sr["health_score"]
        score_color = "#a6e3a1" if score >= 70 else "#f9e2af" if score >= 40 else "#f38ba8"
        st.markdown(
            f'<div style="font-size:2.6rem;font-weight:800;color:{score_color};">'
            f'{score}<span style="font-size:1rem;color:#a6adc8;">/100 health</span></div>',
            unsafe_allow_html=True,
        )
        if sr["headline"]:
            st.markdown(f"**{sr['headline']}**")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("✅ Completed", oc["completed"])
        c2.metric("🚪 Abandoned", oc["abandoned"])
        c3.metric("🔁 Stuck", oc["stuck"])
        c4.metric("🔴 Blockers", oc["blockers"])
        c5.metric("⚠️ Friction", oc["total_friction"])

        # Regression panel
        reg = st.session_state.regression
        if reg and reg.get("has_baseline"):
            st.markdown("---")
            st.markdown("### 📈 Change Since Last Run")
            st.caption(f"Baseline: {reg.get('baseline_date', 'unknown')}")
            d = reg["deltas"]
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Health score", f"{d['health_score']:+d}", delta=d["health_score"])
            rc2.metric("Blockers", f"{d['blockers']:+d}", delta=-d["blockers"],
                       delta_color="inverse")
            rc3.metric("Friction", f"{d['total_friction']:+d}", delta=-d["total_friction"],
                       delta_color="inverse")
            if reg["regressions"]:
                st.error("**Regressions:**\n" + "\n".join(f"- {r}" for r in reg["regressions"]))
            if reg["improvements"]:
                st.success("**Improvements:**\n" + "\n".join(f"- {i}" for i in reg["improvements"]))
            if not reg["regressions"] and not reg["improvements"]:
                st.info("No verdict changes since the last run.")

        # Shared blockers
        if sr["shared_blockers"]:
            st.markdown("---")
            st.markdown("### 🔴 Shared Blockers")
            st.caption("Problems that tripped up multiple personas — fix these first.")
            for b in sr["shared_blockers"]:
                st.markdown(f"- {b}")

        # Prioritized fixes
        if sr["prioritized_fixes"]:
            st.markdown("---")
            st.markdown("### 🔧 Prioritized Fixes")
            for fix in sr["prioritized_fixes"]:
                icon = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(fix["priority"], "⚪")
                with st.expander(f"{icon} [{fix['priority'].upper()}] {fix['issue']}"):
                    st.write(fix.get("why", ""))

        # Per-persona breakdown
        st.markdown("---")
        st.markdown("### 👥 Per-Persona Results")
        for p in rd["personas"]:
            verdict = p["verdict"]
            with st.container():
                st.markdown(
                    f'<div class="pcard {verdict}">'
                    f'<span style="font-size:1.05rem;font-weight:700;">{p["emoji"]} {p["persona_name"]}</span> '
                    f'<span class="vbadge v-{verdict}">{verdict}</span>'
                    f'<div style="font-size:0.85rem;color:#cdd6f4;margin-top:0.3rem;">'
                    f'{p["summary"] or p["outcome_note"] or "(no summary)"}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                with st.expander(
                    f"Details — {p['status']}, {p['step_count']} steps, "
                    f"{len(p['friction'])} friction point(s)"
                ):
                    if p["error"]:
                        st.error(p["error"])
                    if p["friction"]:
                        st.markdown("**Friction logged:**")
                        for f in p["friction"]:
                            st.markdown(
                                f'<span class="fr-{f["severity"]}">●</span> '
                                f'**[{f["severity"]}]** {f["note"]} '
                                f'<span style="color:#6c7086;">(step {f["step"]})</span>',
                                unsafe_allow_html=True,
                            )
                    if p["steps"]:
                        st.markdown("**Step trail:**")
                        for s in p["steps"]:
                            st.markdown(
                                f"`{s['index']}` **{s['action']}** {s['target']}  \n"
                                f"<span style='color:#a6adc8;font-size:0.85rem;'>"
                                f"{s['thought']}</span>  \n"
                                f"<span style='color:#6c7086;font-size:0.82rem;'>"
                                f"→ {s['observation']}</span>",
                                unsafe_allow_html=True,
                            )

        # Export
        st.markdown("---")
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            st.download_button(
                "📋 Download JSON", data=json.dumps(rd, indent=2, ensure_ascii=False),
                file_name=f"persona_swarm_{int(time.time())}.json",
                mime="application/json", use_container_width=True,
            )
        with ec2:
            st.download_button(
                "📄 Download Markdown", data=reporter.generate_markdown(rd),
                file_name=f"persona_swarm_{int(time.time())}.md",
                mime="text/markdown", use_container_width=True,
            )
        with ec3:
            if st.button("🗑️ Clear Results", use_container_width=True):
                st.session_state.report_dict = None
                st.session_state.regression = None
                st.rerun()


# --------------------------------------------------------------------------
# TAB 3 — About
# --------------------------------------------------------------------------
with tab_about:
    st.markdown('<div class="hero"><h1>About Persona Swarm</h1></div>', unsafe_allow_html=True)
    st.markdown(
        "**Persona Swarm** sends a swarm of distinct user personas through your app — "
        "each in its own browser, each reasoning and behaving differently — to find "
        "where *real people* get stuck.\n\n"
        "Unlike a single test bot, the swarm's value is **divergence**: an impatient "
        "power user, a screen-reader user, and a skeptical shopper fail in completely "
        "different ways. One bot would never surface all three.\n\n"
        "### The personas\n"
    )
    for p in PERSONAS:
        st.markdown(f"- **{p.label()}** — {p.summary}")
    st.markdown(
        "\n### Pipeline\n"
        "`map site → spawn persona agents (parallel) → log friction → judge → "
        "report → diff vs last run`\n"
    )
