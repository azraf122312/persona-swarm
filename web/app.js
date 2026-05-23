/* ============================================================
   Persona Swarm — run.html app logic
   Talks to the Flask backend in server.py: launches a swarm,
   polls for live progress, and renders the full report.
   ============================================================ */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  /* build a DOM node; `text` is set via textContent — never innerHTML —
     so site text and LLM output can never inject markup. */
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  var MODEL_DEFAULTS = {
    anthropic: "claude-haiku-4-5-20251001",
    openai: "gpt-4o-mini"
  };
  var KEY_PLACEHOLDER = { anthropic: "sk-ant-...", openai: "sk-..." };
  var STORE_KEY = "persona-swarm-form";
  var POLL_MS = 1500;

  var form = $("run-form");
  var providerSel = $("f-provider");
  var modelInput = $("f-model");
  var keyInput = $("f-key");
  var pickGrid = $("persona-pick");
  var errorsBox = $("form-errors");
  var launchBtn = $("launch-btn");
  var progressPanel = $("progress-panel");
  var progressPhase = $("progress-phase");
  var progressMeta = $("progress-meta");
  var progressRows = $("progress-rows");
  var progressSpin = $("progress-spin");
  var resultsPanel = $("results-panel");

  var personas = [];
  var selected = {};        // persona id -> bool
  var pollTimer = null;
  var startedAt = 0;

  /* ---- sliders: live value labels ----------------------------------- */
  [["f-steps", "v-steps"], ["f-pages", "v-pages"], ["f-conc", "v-conc"]]
    .forEach(function (pair) {
      var input = $(pair[0]), label = $(pair[1]);
      input.addEventListener("input", function () {
        label.textContent = input.value;
      });
    });

  /* ---- provider -> model + key placeholder -------------------------- */
  function syncProvider(keepModel) {
    var prov = providerSel.value;
    keyInput.placeholder = KEY_PLACEHOLDER[prov] || "";
    if (!keepModel || !modelInput.value.trim()) {
      modelInput.value = MODEL_DEFAULTS[prov] || "";
    }
  }
  providerSel.addEventListener("change", function () { syncProvider(false); });

  /* ---- persona picker ----------------------------------------------- */
  var TIER_LABELS = {
    core:  "Core swarm — runs by default",
    extra: "Extra personas — opt-in, universal value",
    niche: "Niche personas — context-specific (B2B, commerce, marketing)"
  };
  var TIER_HINTS = {
    core:  "These eight cover the orthogonal failure modes — patience, device, accessibility, language, trust.",
    extra: "Tick these for a thorough run. Each adds ~30s of runtime and ~$0.10 in tokens.",
    niche: "Enable the ones that fit your product. Cancel hunter for subscriptions; compliance buyer for B2B; first-touch prospect for marketing pages."
  };

  function renderPersonas() {
    pickGrid.innerHTML = "";
    if (!personas.length) {
      pickGrid.appendChild(el("p", "hint",
        "Could not load personas — is the server running? (python server.py)"));
      return;
    }

    // group by tier, preserving roster order within each
    var groups = { core: [], extra: [], niche: [] };
    personas.forEach(function (p) {
      var t = p.tier || "core";
      (groups[t] || groups.core).push(p);
    });

    ["core", "extra", "niche"].forEach(function (tier) {
      var group = groups[tier];
      if (!group.length) return;

      var head = el("div", "pick-tier-head");
      head.appendChild(el("div", "pick-tier-name", TIER_LABELS[tier]));
      head.appendChild(el("div", "pick-tier-hint", TIER_HINTS[tier]));
      pickGrid.appendChild(head);

      group.forEach(function (p) {
        if (selected[p.id] === undefined) {
          // honor server default_on (core defaults true, extra/niche false)
          selected[p.id] = p.default_on !== false;
        }
        var chip = el("button", "pick" + (selected[p.id] ? " on" : ""));
        chip.type = "button";
        chip.setAttribute("aria-pressed", String(!!selected[p.id]));

        var top = el("div", "pick-top");
        top.appendChild(el("span", "pick-emoji", p.emoji));
        top.appendChild(el("span", "pick-name", p.name));
        top.appendChild(el("span", "pick-check", "✓"));
        chip.appendChild(top);
        chip.appendChild(el("p", "pick-summary", p.summary));

        chip.addEventListener("click", function () {
          selected[p.id] = !selected[p.id];
          chip.classList.toggle("on", selected[p.id]);
          chip.setAttribute("aria-pressed", String(!!selected[p.id]));
        });
        pickGrid.appendChild(chip);
      });
    });
  }
  function setAll(value) {
    personas.forEach(function (p) { selected[p.id] = value; });
    renderPersonas();
  }
  function setCoreOnly() {
    personas.forEach(function (p) {
      selected[p.id] = (p.tier || "core") === "core";
    });
    renderPersonas();
  }
  $("pick-all").addEventListener("click", function () { setAll(true); });
  $("pick-none").addEventListener("click", function () { setAll(false); });
  var coreBtn = $("pick-core");
  if (coreBtn) coreBtn.addEventListener("click", setCoreOnly);

  /* ---- persisted form values (never the API key) -------------------- */
  function restore() {
    try {
      var s = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
      if (s.url) $("f-url").value = s.url;
      if (s.goal) $("f-goal").value = s.goal;
      if (s.provider) providerSel.value = s.provider;
      if (s.model) modelInput.value = s.model;
      ["steps", "pages", "conc"].forEach(function (k) {
        var v = s["max_" + (k === "conc" ? "concurrency" : k)];
        if (v != null) { $("f-" + k).value = v; $("v-" + k).textContent = v; }
      });
      if (s.selected && typeof s.selected === "object") selected = s.selected;
    } catch (e) { /* ignore corrupt storage */ }
    syncProvider(true);
  }
  function save(params) {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        url: params.url, goal: params.goal, provider: params.provider,
        model: params.model, max_steps: params.max_steps,
        max_pages: params.max_pages, concurrency: params.concurrency,
        selected: selected
      }));
    } catch (e) { /* storage full / disabled — non-fatal */ }
  }

  /* ---- load personas ------------------------------------------------ */
  fetch("/api/personas")
    .then(function (r) { return r.json(); })
    .then(function (data) { personas = data || []; restore(); renderPersonas(); })
    .catch(function () { restore(); renderPersonas(); });

  /* ---- errors / launch state ---------------------------------------- */
  function showErrors(list) {
    errorsBox.innerHTML = "";
    list.forEach(function (m) { errorsBox.appendChild(el("div", "form-error", m)); });
    errorsBox.hidden = false;
    errorsBox.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function hideErrors() { errorsBox.hidden = true; errorsBox.innerHTML = ""; }
  function setLaunching(on) {
    launchBtn.disabled = on;
    launchBtn.textContent = on ? "Running the swarm…" : "Launch the swarm";
  }

  /* ---- submit ------------------------------------------------------- */
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    hideErrors();

    var ids = personas.filter(function (p) { return selected[p.id]; })
                       .map(function (p) { return p.id; });
    var params = {
      url: $("f-url").value.trim(),
      goal: $("f-goal").value.trim(),
      provider: providerSel.value,
      model: modelInput.value.trim(),
      api_key: keyInput.value.trim(),
      persona_ids: ids,
      max_steps: parseInt($("f-steps").value, 10),
      max_pages: parseInt($("f-pages").value, 10),
      concurrency: parseInt($("f-conc").value, 10)
    };

    var clientErr = [];
    if (!/^https?:\/\//.test(params.url))
      clientErr.push("Target URL must start with http:// or https://.");
    if (!params.goal) clientErr.push("A goal is required.");
    if (!params.api_key) clientErr.push("An API key is required.");
    if (!ids.length) clientErr.push("Select at least one persona.");
    if (clientErr.length) { showErrors(clientErr); return; }

    save(params);
    setLaunching(true);

    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params)
    })
      .then(function (r) {
        return r.json().then(function (body) { return { ok: r.ok, body: body }; });
      })
      .then(function (res) {
        if (!res.ok) {
          showErrors(res.body.errors || [res.body.error || "Could not start the run."]);
          setLaunching(false);
          return;
        }
        beginRun(res.body.job_id, ids);
      })
      .catch(function () {
        showErrors(["Could not reach the server. Is it still running?"]);
        setLaunching(false);
      });
  });

  /* ---- run lifecycle ------------------------------------------------ */
  function beginRun(jobId, ids) {
    startedAt = Date.now();
    resultsPanel.hidden = true;
    resultsPanel.innerHTML = "";
    progressPanel.hidden = false;
    progressSpin.style.display = "";
    progressPhase.textContent = "Queued…";
    progressMeta.textContent = "";
    progressRows.innerHTML = "";

    var rowById = {};
    personas.filter(function (p) { return ids.indexOf(p.id) >= 0; })
      .forEach(function (p) {
        var row = el("div", "crow dim");
        row.appendChild(el("span", "crow-emoji", p.emoji));
        row.appendChild(el("span", "crow-name", p.name));
        var status = el("span", "crow-status", "queued");
        row.appendChild(status);
        progressRows.appendChild(row);
        rowById[p.id] = { row: row, status: status };
      });

    progressPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    poll(jobId, rowById);
  }

  function stopPoll() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  function poll(jobId, rowById) {
    fetch("/api/runs/" + jobId)
      .then(function (r) { return r.json(); })
      .then(function (snap) {
        applySnapshot(snap, rowById);
        if (snap.status === "done" || snap.status === "error") {
          stopPoll();
          finishRun(snap);
        } else {
          pollTimer = setTimeout(function () { poll(jobId, rowById); }, POLL_MS);
        }
      })
      .catch(function () {
        // transient network hiccup — back off slightly and retry
        pollTimer = setTimeout(function () { poll(jobId, rowById); }, 2500);
      });
  }

  function setStatus(node, text, cls) {
    node.textContent = text;
    node.className = "crow-status " + cls;
  }

  function applySnapshot(snap, rowById) {
    progressPhase.textContent = snap.phase || snap.status;
    progressMeta.textContent = "elapsed " + fmtDuration(Date.now() - startedAt);

    var state = {};
    (snap.events || []).forEach(function (ev) {
      if (ev.event === "persona_started") state[ev.persona_id] = "running";
      else if (ev.event === "persona_done") state[ev.persona_id] = ev.status;
    });

    Object.keys(rowById).forEach(function (pid) {
      var r = rowById[pid], s = state[pid];
      if (!s) return;                       // still queued
      r.row.classList.remove("dim");
      if (s === "running")        setStatus(r.status, "exploring…", "running");
      else if (s === "completed") setStatus(r.status, "✓ completed", "completed");
      else if (s === "abandoned") setStatus(r.status, "✕ abandoned", "abandoned");
      else if (s === "stuck")     setStatus(r.status, "ran out of steps", "stuck");
      else                        setStatus(r.status, "⚠ error", "error");
    });
  }

  function finishRun(snap) {
    progressSpin.style.display = "none";
    setLaunching(false);
    if (snap.status === "error") {
      progressPhase.textContent = "Run failed.";
      renderError(snap.error || "The swarm run failed.");
      return;
    }
    progressPhase.textContent = "Swarm complete.";
    renderResults(snap.report, snap.regression);
    resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderError(msg) {
    resultsPanel.hidden = false;
    resultsPanel.innerHTML = "";
    var box = el("div", "panel run-error");
    box.appendChild(el("h3", "results-h", "The run failed"));
    box.appendChild(el("p", null, msg));
    resultsPanel.appendChild(box);
  }

  /* ---- results rendering -------------------------------------------- */
  function renderResults(rd, reg) {
    resultsPanel.hidden = false;
    resultsPanel.innerHTML = "";
    var meta = rd.meta, sr = rd.swarm_report, oc = rd.outcomes;

    var panel = el("div", "panel results");

    // header — goal, url, ring
    var head = el("div", "results-head");
    var left = el("div");
    left.appendChild(el("div", "results-goal", meta.goal));
    left.appendChild(el("div", "results-url", meta.target_url));
    left.appendChild(el("div", "results-sub",
      meta.persona_count + " personas · " + fmtDuration(meta.total_time_ms) +
      " · " + meta.started_at));
    head.appendChild(left);
    head.appendChild(buildRing(sr.health_score));
    panel.appendChild(head);

    if (sr.headline) panel.appendChild(el("div", "results-headline", sr.headline));

    // outcome metrics
    var metrics = el("div", "metrics");
    [["Completed", oc.completed], ["Abandoned", oc.abandoned],
     ["Stuck", oc.stuck], ["Blockers", oc.blockers],
     ["Friction", oc.total_friction]].forEach(function (m) {
      var box = el("div", "metric");
      box.appendChild(el("div", "metric-num", String(m[1])));
      box.appendChild(el("div", "metric-label", m[0]));
      metrics.appendChild(box);
    });
    panel.appendChild(metrics);

    if (reg && reg.has_baseline) panel.appendChild(buildRegression(reg));

    // static audit
    var audit = rd.audit;
    if (audit && audit.enabled && audit.findings && audit.findings.length) {
      panel.appendChild(buildAudit(audit));
    }

    // shared blockers
    if (sr.shared_blockers && sr.shared_blockers.length) {
      var sb = el("div", "results-block");
      sb.appendChild(el("h3", "results-h", "Shared blockers"));
      var ul = el("ul", "blocker-list");
      sr.shared_blockers.forEach(function (b) {
        var li = el("li");
        li.appendChild(el("span", "sev sev-blocker"));
        li.appendChild(el("span", null, b));
        ul.appendChild(li);
      });
      sb.appendChild(ul);
      panel.appendChild(sb);
    }

    // prioritized fixes
    if (sr.prioritized_fixes && sr.prioritized_fixes.length) {
      var fx = el("div", "results-block");
      fx.appendChild(el("h3", "results-h", "Prioritized fixes"));
      sr.prioritized_fixes.forEach(function (f) {
        var prio = f.priority || "medium";
        var d = el("details", "fix fix-" + prio);
        var sum = el("summary");
        sum.appendChild(el("span", "fix-prio", prio.toUpperCase()));
        sum.appendChild(el("span", "fix-issue", f.issue));
        d.appendChild(sum);
        if (f.why) d.appendChild(el("p", "fix-why", f.why));
        fx.appendChild(d);
      });
      panel.appendChild(fx);
    }

    // per-persona breakdown
    var pp = el("div", "results-block");
    pp.appendChild(el("h3", "results-h", "Per-persona results"));
    (rd.personas || []).forEach(function (p) { pp.appendChild(buildPersonaCard(p)); });
    panel.appendChild(pp);

    // actions
    var actions = el("div", "results-actions");
    var dl = el("button", "btn btn-ghost btn-sm", "Download JSON");
    dl.type = "button";
    dl.addEventListener("click", function () { downloadJSON(rd); });
    var again = el("button", "btn btn-primary btn-sm", "Run another swarm");
    again.type = "button";
    again.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    actions.appendChild(dl);
    actions.appendChild(again);
    panel.appendChild(actions);

    resultsPanel.appendChild(panel);
  }

  function buildRing(score) {
    var safe = Math.max(0, Math.min(100, score || 0));
    var ring = el("div", "score-ring");
    ring.style.setProperty("--ring-deg", (safe / 100 * 360) + "deg");
    var num = el("div", "score-num");
    num.appendChild(el("span", null, String(score)));
    num.appendChild(el("small", null, "/100"));
    ring.appendChild(num);
    ring.appendChild(el("div", "score-label", "health"));
    return ring;
  }

  function buildRegression(reg) {
    var box = el("div", "results-block regression");
    box.appendChild(el("h3", "results-h", "Change since last run"));
    if (reg.baseline_date)
      box.appendChild(el("p", "hint", "Baseline: " + reg.baseline_date));

    var d = reg.deltas || {};
    var row = el("div", "delta-row");
    // [label, value, lowerIsBetter]
    [["Health score", d.health_score, false],
     ["Blockers", d.blockers, true],
     ["Friction", d.total_friction, true]].forEach(function (x) {
      var v = x[1] || 0;
      var cls = v === 0 ? "flat" : ((x[2] ? v < 0 : v > 0) ? "good" : "bad");
      var box2 = el("div", "delta " + cls);
      box2.appendChild(el("div", "delta-num", (v > 0 ? "+" : "") + v));
      box2.appendChild(el("div", "delta-label", x[0]));
      row.appendChild(box2);
    });
    box.appendChild(row);

    (reg.regressions || []).forEach(function (r) {
      box.appendChild(el("p", "reg-line bad", "▼ " + r));
    });
    (reg.improvements || []).forEach(function (i) {
      box.appendChild(el("p", "reg-line good", "▲ " + i));
    });
    if (!(reg.regressions || []).length && !(reg.improvements || []).length)
      box.appendChild(el("p", "hint", "No verdict changes since the last run."));
    return box;
  }

  function buildAudit(audit) {
    var box = el("div", "results-block audit-block");
    box.appendChild(el("h3", "results-h", "Site audit — broken links, SEO, a11y, copy"));

    var c = audit.counts || {};
    var summary = el("p", "audit-summary");
    summary.appendChild(el("span", "audit-stat", String(audit.pages_audited || 0) + " pages"));
    summary.appendChild(el("span", "audit-stat", String(audit.links_checked || 0) + " links checked"));
    summary.appendChild(el("span", "audit-stat", String(audit.broken_links || 0) + " broken"));
    summary.appendChild(el("span", "audit-stat sev-blocker-stat", (c.blocker || 0) + " blocker"));
    summary.appendChild(el("span", "audit-stat sev-major-stat",   (c.major || 0) + " major"));
    summary.appendChild(el("span", "audit-stat sev-minor-stat",   (c.minor || 0) + " minor"));
    box.appendChild(summary);

    var CAT_LABELS = {
      "links": "Broken / problem links",
      "auth": "Auth softlock signals",
      "mixed-content": "Mixed content",
      "copy": "Copywriting",
      "seo": "SEO & meta",
      "a11y": "Accessibility",
      "ui": "UI edges"
    };
    var ORDER = ["links", "auth", "mixed-content", "copy", "seo", "a11y", "ui"];
    var byCat = audit.by_category || {};

    ORDER.forEach(function (cat) {
      var items = byCat[cat] || [];
      if (!items.length) return;
      var det = el("details", "audit-cat");
      var blockers = items.filter(function (f) { return f.severity === "blocker"; }).length;
      det.open = blockers > 0;  // open by default if there's a blocker in the category
      var sum = el("summary");
      sum.appendChild(el("span", "audit-cat-name", CAT_LABELS[cat] || cat));
      sum.appendChild(el("span", "audit-cat-count", "(" + items.length + ")"));
      det.appendChild(sum);

      var ul = el("ul", "audit-list");
      items.slice(0, 30).forEach(function (f) {
        var li = el("li", "audit-item audit-" + f.severity);
        li.appendChild(el("span", "audit-sev sev-" + f.severity, f.severity));
        var body = el("div", "audit-body");
        body.appendChild(el("div", "audit-note", f.note));
        var meta = el("div", "audit-meta");
        meta.appendChild(el("span", "audit-url", f.page_url));
        if (f.detail) {
          meta.appendChild(el("span", "audit-detail", "→ " + f.detail));
        }
        body.appendChild(meta);
        li.appendChild(body);
        ul.appendChild(li);
      });
      if (items.length > 30) {
        ul.appendChild(el("li", "audit-item audit-more",
          "... and " + (items.length - 30) + " more in this category."));
      }
      det.appendChild(ul);
      box.appendChild(det);
    });

    return box;
  }

  function buildPersonaCard(p) {
    var card = el("div", "persona-result " + p.verdict);

    var top = el("div", "pr-top");
    top.appendChild(el("span", "pr-emoji", p.emoji));
    top.appendChild(el("span", "pr-name", p.persona_name));
    top.appendChild(el("span", "vchip " + p.verdict, p.verdict));
    card.appendChild(top);

    card.appendChild(el("p", "pr-summary",
      p.summary || p.outcome_note || "(no summary)"));

    var friction = p.friction || [], steps = p.steps || [];
    var det = el("details", "pr-details");
    det.appendChild(el("summary", null,
      p.status + " · " + p.step_count + " steps · " +
      friction.length + " friction point(s)"));

    if (p.error) det.appendChild(el("p", "pr-error", p.error));

    if (friction.length) {
      det.appendChild(el("div", "pr-sub", "Friction logged"));
      var fl = el("ul", "friction-list");
      friction.forEach(function (f) {
        var li = el("li", "friction-" + f.severity);
        li.appendChild(el("span", "sev sev-" + f.severity));
        var body = el("span");
        body.appendChild(el("b", null, "[" + f.severity + "] "));
        body.appendChild(document.createTextNode(f.note + " "));
        body.appendChild(el("span", "step-tag", "(step " + f.step + ")"));
        li.appendChild(body);
        fl.appendChild(li);
      });
      det.appendChild(fl);
    }

    if (steps.length) {
      det.appendChild(el("div", "pr-sub", "Step trail"));
      var trail = el("ol", "step-trail");
      steps.forEach(function (s) {
        var li = el("li", "step-item");
        var sh = el("div", "step-head");
        sh.appendChild(el("span", "step-idx", String(s.index)));
        sh.appendChild(el("span", "step-action", s.action));
        if (s.target) sh.appendChild(el("span", "step-target", s.target));
        li.appendChild(sh);
        if (s.thought) li.appendChild(el("p", "step-thought", s.thought));
        if (s.observation) li.appendChild(el("p", "step-obs", "→ " + s.observation));
        trail.appendChild(li);
      });
      det.appendChild(trail);
    }

    card.appendChild(det);
    return card;
  }

  function downloadJSON(rd) {
    var blob = new Blob([JSON.stringify(rd, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "persona-swarm-" + Date.now() + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function fmtDuration(ms) {
    var s = Math.round((ms || 0) / 1000);
    if (s < 60) return s + "s";
    return Math.floor(s / 60) + "m " + (s % 60) + "s";
  }

})();
