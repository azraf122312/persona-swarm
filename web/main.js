/* ============================================================
   Persona Swarm — landing page interactions & motion
   ============================================================ */
(function () {
  "use strict";

  // mark JS as available — CSS only hides .reveal elements once this is set,
  // so a JS failure leaves the page fully visible instead of blank.
  document.documentElement.classList.add("js");

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function $(id) { return document.getElementById(id); }

  // -- persona roster (mirrors personas/profiles.py) -----------------------
  var PERSONAS = [
    { emoji: "⚡", name: "Impatient Power User",
      summary: "Rushes through everything and abandons anything slow.", patience: 3 },
    { emoji: "🐣", name: "Cautious First-Timer",
      summary: "Has never used the site; reads everything and fears mistakes.", patience: 7 },
    { emoji: "🦮", name: "Screen-Reader User",
      summary: "Navigates by keyboard and accessible labels — cannot see layout.", patience: 8 },
    { emoji: "📱", name: "Mobile Thumb User",
      summary: "On a phone, one-handed, with imprecise fat-finger taps.", patience: 4 },
    { emoji: "🕵️", name: "Skeptical Shopper",
      summary: "Won't commit without clear pricing and visible trust signals.", patience: 5 },
    { emoji: "🤹", name: "Distracted Multitasker",
      summary: "Switches tabs constantly and returns later having lost context.", patience: 4 },
    { emoji: "🌍", name: "Non-Native Speaker",
      summary: "Translates the UI mentally; idioms and slang confuse them.", patience: 6 },
    { emoji: "😤", name: "Rage Clicker",
      summary: "Expects instant feedback; clicks repeatedly when nothing happens.", patience: 2 }
  ];

  var VERDICTS = [
    { name: "Impatient Power User", verdict: "success" },
    { name: "Cautious First-Timer", verdict: "success" },
    { name: "Screen-Reader User",  verdict: "failure" },
    { name: "Mobile Thumb User",   verdict: "failure" },
    { name: "Skeptical Shopper",   verdict: "failure" },
    { name: "Distracted Multitasker", verdict: "success" },
    { name: "Non-Native Speaker",  verdict: "success" },
    { name: "Rage Clicker",        verdict: "success" }
  ];
  var HEALTH_SCORE = 62;

  // ========================================================================
  // Scroll reveal + stagger
  // ========================================================================
  var io = null;
  if (!reduceMotion && "IntersectionObserver" in window) {
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12 });
  }
  function reveal(el) {
    if (io) io.observe(el);
    else el.classList.add("in");
  }
  function applyStagger(container) {
    container.querySelectorAll(".reveal").forEach(function (el, i) {
      el.style.setProperty("--reveal-delay", (i * 70) + "ms");
    });
  }

  // ========================================================================
  // Nav — solidify on scroll
  // ========================================================================
  var nav = $("nav");
  function onScroll() {
    if (nav) nav.classList.toggle("scrolled", window.scrollY > 12);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ========================================================================
  // Persona grid
  // ========================================================================
  var grid = $("persona-grid");
  if (grid) {
    PERSONAS.forEach(function (p) {
      var card = document.createElement("article");
      card.className = "persona reveal";
      card.style.setProperty("--pat", Math.round(p.patience / 10 * 100) + "%");
      card.innerHTML =
        '<div class="persona-top">' +
          '<div class="persona-emoji">' + p.emoji + '</div>' +
          '<div class="persona-name">' + p.name + '</div>' +
        '</div>' +
        '<p class="persona-summary">' + p.summary + '</p>' +
        '<div class="persona-meta">' +
          '<span class="patience-label">Patience ' + p.patience + '/10</span>' +
          '<span class="patience-bar"><span class="patience-fill"></span></span>' +
        '</div>';
      grid.appendChild(card);
    });
  }

  // ========================================================================
  // Report — verdict list + score ring
  // ========================================================================
  var vlist = $("verdict-list");
  if (vlist) {
    VERDICTS.forEach(function (v) {
      var li = document.createElement("li");
      li.innerHTML =
        '<span class="v-name">' + v.name + '</span>' +
        '<span class="vchip ' + v.verdict + '">' + v.verdict + '</span>';
      vlist.appendChild(li);
    });
  }

  var ring = $("score-ring");
  var scoreVal = $("score-val");
  function fillRing() {
    var targetDeg = (HEALTH_SCORE / 100) * 360;
    if (reduceMotion) {
      ring.style.setProperty("--ring-deg", targetDeg + "deg");
      if (scoreVal) scoreVal.textContent = HEALTH_SCORE;
      return;
    }
    var start = null;
    function step(ts) {
      if (start === null) start = ts;
      var t = Math.min((ts - start) / 1100, 1);
      var eased = 1 - Math.pow(1 - t, 3);
      ring.style.setProperty("--ring-deg", (targetDeg * eased) + "deg");
      if (scoreVal) scoreVal.textContent = Math.round(HEALTH_SCORE * eased);
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  if (ring) {
    if (reduceMotion || !io) {
      fillRing();
    } else {
      var ringIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { fillRing(); ringIO.disconnect(); }
        });
      }, { threshold: 0.5 });
      ringIO.observe(ring);
    }
  }

  // ========================================================================
  // Stat band — count up
  // ========================================================================
  function countUp(el) {
    var target = parseInt(el.dataset.count, 10) || 0;
    var prefix = el.dataset.prefix || "";
    var suffix = el.dataset.suffix || "";
    if (reduceMotion || target === 0) {
      el.textContent = prefix + target + suffix;
      return;
    }
    var start = null, dur = 1150;
    function step(ts) {
      if (start === null) start = ts;
      var t = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = prefix + Math.round(target * eased) + suffix;
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  var statband = $("statband");
  if (statband) {
    var nums = statband.querySelectorAll(".stat-num");
    if (reduceMotion || !io) {
      nums.forEach(countUp);
    } else {
      var sIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { nums.forEach(countUp); sIO.disconnect(); }
        });
      }, { threshold: 0.4 });
      sIO.observe(statband);
    }
  }

  // ========================================================================
  // Hero — live swarm console
  // ========================================================================
  var rowsEl = $("console-rows");
  var footEl = $("console-foot");
  if (rowsEl && footEl) {
    var SHOW = [
      { i: 0, outcome: "completed" },
      { i: 1, outcome: "completed" },
      { i: 2, outcome: "abandoned" },
      { i: 3, outcome: "abandoned" },
      { i: 4, outcome: "abandoned" },
      { i: 7, outcome: "completed" }
    ];
    var STEP_VERBS = ["mapping site", "reading page", "clicking",
                      "filling form", "scrolling", "checking price"];

    SHOW.forEach(function (s) {
      var p = PERSONAS[s.i];
      var row = document.createElement("div");
      row.className = "crow dim";
      row.innerHTML =
        '<span class="crow-emoji">' + p.emoji + '</span>' +
        '<span class="crow-name">' + p.name + '</span>' +
        '<span class="crow-status">queued</span>';
      rowsEl.appendChild(row);
    });
    var rowEls = rowsEl.querySelectorAll(".crow");

    function setStatus(row, text, cls) {
      var st = row.querySelector(".crow-status");
      st.textContent = text;
      st.className = "crow-status" + (cls ? " " + cls : "");
    }

    function runCycle() {
      footEl.textContent = "";
      rowEls.forEach(function (row) {
        row.classList.add("dim");
        setStatus(row, "queued", "");
      });
      SHOW.forEach(function (s, idx) {
        setTimeout(function () {
          rowEls[idx].classList.remove("dim");
          setStatus(rowEls[idx], STEP_VERBS[idx % STEP_VERBS.length] + "…", "running");
        }, 500 + idx * 520);
        setTimeout(function () {
          var label = s.outcome === "completed" ? "✓ completed" : "✕ abandoned";
          setStatus(rowEls[idx], label, s.outcome);
        }, 500 + idx * 520 + 1700);
      });
      var done = 500 + SHOW.length * 520 + 1900;
      setTimeout(function () {
        var ok = SHOW.filter(function (s) { return s.outcome === "completed"; }).length;
        footEl.innerHTML = "swarm complete — <b>" + ok + "/" + SHOW.length +
          "</b> reached the goal · 3 blockers found";
      }, done);
      if (!reduceMotion) setTimeout(runCycle, done + 3600);
    }

    if (reduceMotion) {
      SHOW.forEach(function (s, idx) {
        rowEls[idx].classList.remove("dim");
        var label = s.outcome === "completed" ? "✓ completed" : "✕ abandoned";
        setStatus(rowEls[idx], label, s.outcome);
      });
      footEl.innerHTML = "swarm complete — <b>3/6</b> reached the goal · 3 blockers found";
    } else {
      var consoleEl = $("console");
      if ("IntersectionObserver" in window && consoleEl) {
        var cIO = new IntersectionObserver(function (entries) {
          entries.forEach(function (e) {
            if (e.isIntersecting) { runCycle(); cIO.disconnect(); }
          });
        }, { threshold: 0.4 });
        cIO.observe(consoleEl);
      } else {
        runCycle();
      }
    }
  }

  // ========================================================================
  // Setup section — self-playing demo + presets
  // ========================================================================
  var DEMO = [
    { url: "shop.example.com",     goal: "Add a product to the cart and complete checkout." },
    { url: "app.example.io",       goal: "Sign up for an account and reach the dashboard." },
    { url: "example.com/pricing",  goal: "Compare the plans and start a free trial." }
  ];

  var demoPersonasEl = $("demo-personas");
  var spills = [];
  if (demoPersonasEl) {
    PERSONAS.forEach(function (p) {
      var s = document.createElement("span");
      s.className = "spill";
      s.innerHTML = '<span>' + p.emoji + '</span>' + p.name;
      demoPersonasEl.appendChild(s);
      spills.push(s);
    });
  }

  var demoTimers = [];
  function later(fn, ms) { var id = setTimeout(fn, ms); demoTimers.push(id); return id; }
  function clearDemo() { demoTimers.forEach(clearTimeout); demoTimers = []; }

  function runSetupDemo() {
    var idx = 0;
    function typeInto(el, text, speed, cb) {
      var i = 0;
      (function tick() {
        el.textContent = text.slice(0, i);
        if (i < text.length) { i++; later(tick, speed); }
        else if (cb) later(cb, 0);
      })();
    }
    function cycle() {
      var ex = DEMO[idx];
      $("demo-url").textContent = "";
      $("demo-goal").textContent = "";
      $("demo-tag").classList.remove("on");
      spills.forEach(function (s) { s.classList.remove("on", "pop"); });
      $("caret-url").classList.add("on");
      $("caret-goal").classList.remove("on");

      typeInto($("demo-url"), ex.url, 55, function () {
        $("caret-url").classList.remove("on");
        later(function () { $("demo-tag").classList.add("on"); }, 240);
        spills.forEach(function (s, i) {
          later(function () {
            s.classList.add("on", "pop");
            later(function () { s.classList.remove("pop"); }, 420);
          }, 320 + i * 95);
        });
        later(function () {
          $("caret-goal").classList.add("on");
          typeInto($("demo-goal"), ex.goal, 32, function () {
            $("caret-goal").classList.remove("on");
            later(function () {
              $("setup-btn").classList.add("pulse");
              later(function () { $("setup-btn").classList.remove("pulse"); }, 1000);
            }, 280);
            idx = (idx + 1) % DEMO.length;
            later(cycle, 3400);
          });
        }, 320 + spills.length * 95 + 260);
      });
    }
    cycle();
  }

  function setupStatic(ex) {
    clearDemo();
    $("demo-url").textContent = ex.url;
    $("demo-goal").textContent = ex.goal;
    $("demo-tag").classList.add("on");
    $("caret-url").classList.remove("on");
    $("caret-goal").classList.remove("on");
    spills.forEach(function (s) { s.classList.add("on"); });
  }

  var presets = Array.prototype.slice.call(document.querySelectorAll(".preset"));
  presets.forEach(function (btn) {
    btn.addEventListener("click", function () {
      presets.forEach(function (b) { b.classList.toggle("active", b === btn); });
      setupStatic({ url: btn.dataset.url, goal: btn.dataset.goal });
      var b = $("setup-btn");
      b.classList.add("pulse");
      setTimeout(function () { b.classList.remove("pulse"); }, 1000);
    });
  });

  var setupPanel = $("setup-panel");
  if (setupPanel && spills.length) {
    if (reduceMotion || !io) {
      setupStatic(DEMO[0]);
    } else {
      var dIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { runSetupDemo(); dIO.disconnect(); }
        });
      }, { threshold: 0.35 });
      dIO.observe(setupPanel);
    }
  }

  // ========================================================================
  // Honest questions — accordion
  // ========================================================================
  var faqItems = Array.prototype.slice.call(document.querySelectorAll(".faq-item"));
  function closeItem(item) {
    item.classList.remove("open");
    item.querySelector(".faq-q").setAttribute("aria-expanded", "false");
    item.querySelector(".faq-a").style.maxHeight = "0px";
  }
  function openItem(item) {
    item.classList.add("open");
    item.querySelector(".faq-q").setAttribute("aria-expanded", "true");
    var a = item.querySelector(".faq-a");
    a.style.maxHeight = a.scrollHeight + "px";
  }
  faqItems.forEach(function (item) {
    item.querySelector(".faq-q").addEventListener("click", function () {
      var isOpen = item.classList.contains("open");
      faqItems.forEach(function (other) {
        if (other.classList.contains("open")) closeItem(other);
      });
      if (!isOpen) openItem(item);
    });
  });
  if (faqItems.length) {
    var firstFaq = faqItems[0];
    requestAnimationFrame(function () { openItem(firstFaq); });
    // keep the open panel sized correctly after fonts load / on resize
    function resizeOpenFaq() {
      var open = document.querySelector(".faq-item.open");
      if (open) {
        var a = open.querySelector(".faq-a");
        a.style.maxHeight = a.scrollHeight + "px";
      }
    }
    window.addEventListener("load", resizeOpenFaq);
    var rt;
    window.addEventListener("resize", function () {
      clearTimeout(rt);
      rt = setTimeout(resizeOpenFaq, 150);
    });
  }

  // ========================================================================
  // Early access — form submit
  // ========================================================================
  var eaForm = $("ea-form");
  if (eaForm) {
    eaForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var emailEl = $("ea-email");
      var email = emailEl.value.trim();
      var note = $("ea-note");
      emailEl.classList.remove("bad");
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        emailEl.classList.add("bad");
        note.textContent = "Please enter a valid email address.";
        emailEl.focus();
        return;
      }
      var btn = $("ea-submit");
      btn.disabled = true;
      btn.textContent = "Sending…";
      fetch("/api/early-access", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email, role: $("ea-role").value })
      })
        .then(function (r) {
          return r.json().then(function (b) { return { ok: r.ok, b: b }; });
        })
        .then(function (res) {
          if (!res.ok) throw new Error((res.b && res.b.error) || "failed");
          eaForm.hidden = true;
          $("ea-success").hidden = false;
        })
        .catch(function () {
          btn.disabled = false;
          btn.textContent = "Get early access";
          note.textContent = "Couldn't reach the server — run it with: python server.py";
        });
    });
  }

  // ========================================================================
  // Kick off reveal — stagger every group, then observe everything
  // ========================================================================
  document.querySelectorAll("[data-stagger]").forEach(applyStagger);
  document.querySelectorAll(".reveal").forEach(reveal);

})();
