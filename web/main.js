/* ============================================================
   Persona Swarm — showcase site interactions
   ============================================================ */
(function () {
  "use strict";

  // mark JS as available — CSS only hides .reveal elements once this is set
  document.documentElement.classList.add("js");

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

  // sample verdicts for the report card — 5 of 8 succeed
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

  // -- nav: solidify on scroll --------------------------------------------
  var nav = document.getElementById("nav");
  function onScroll() {
    if (nav) nav.classList.toggle("scrolled", window.scrollY > 12);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // -- reveal on scroll ----------------------------------------------------
  var reveals = document.querySelectorAll(".reveal");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    reveals.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.12 });
    reveals.forEach(function (el) { io.observe(el); });
  }

  // -- render persona grid -------------------------------------------------
  var grid = document.getElementById("persona-grid");
  if (grid) {
    PERSONAS.forEach(function (p) {
      var pct = Math.round((p.patience / 10) * 100);
      var card = document.createElement("article");
      card.className = "persona reveal";
      card.innerHTML =
        '<div class="persona-top">' +
          '<div class="persona-emoji">' + p.emoji + '</div>' +
          '<div class="persona-name">' + p.name + '</div>' +
        '</div>' +
        '<p class="persona-summary">' + p.summary + '</p>' +
        '<div class="persona-meta">' +
          '<span class="patience-label">Patience ' + p.patience + '/10</span>' +
          '<span class="patience-bar"><span class="patience-fill" ' +
            'style="width:' + pct + '%"></span></span>' +
        '</div>';
      grid.appendChild(card);
      if (reduceMotion || typeof io === "undefined") card.classList.add("in");
      else io.observe(card);
    });
  }

  // -- render verdict list -------------------------------------------------
  var vlist = document.getElementById("verdict-list");
  if (vlist) {
    VERDICTS.forEach(function (v) {
      var li = document.createElement("li");
      li.innerHTML =
        '<span class="v-name">' + v.name + '</span>' +
        '<span class="vchip ' + v.verdict + '">' + v.verdict + '</span>';
      vlist.appendChild(li);
    });
  }

  // -- score ring fill -----------------------------------------------------
  var ring = document.getElementById("score-ring");
  var scoreVal = document.getElementById("score-val");
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
    if (reduceMotion || !("IntersectionObserver" in window)) {
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

  // -- live swarm console --------------------------------------------------
  var rowsEl = document.getElementById("console-rows");
  var footEl = document.getElementById("console-foot");
  if (rowsEl && footEl) {
    // 6 personas with a scripted outcome each
    var SHOW = [
      { i: 0, outcome: "completed" },
      { i: 1, outcome: "completed" },
      { i: 2, outcome: "abandoned" },
      { i: 3, outcome: "abandoned" },
      { i: 4, outcome: "abandoned" },
      { i: 7, outcome: "completed" }
    ];
    var STEP_VERBS = ["mapping site", "reading page", "clicking", "filling form",
                      "scrolling", "checking price"];

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
        setTimeout(function () {  // start running
          rowEls[idx].classList.remove("dim");
          setStatus(rowEls[idx], STEP_VERBS[idx % STEP_VERBS.length] + "…", "running");
        }, 500 + idx * 520);
        setTimeout(function () {  // resolve
          var label = s.outcome === "completed" ? "✓ completed" : "✕ abandoned";
          setStatus(rowEls[idx], label, s.outcome);
        }, 500 + idx * 520 + 1700);
      });

      var done = 500 + SHOW.length * 520 + 1900;
      setTimeout(function () {  // footer summary
        var ok = SHOW.filter(function (s) { return s.outcome === "completed"; }).length;
        footEl.innerHTML = "swarm complete — <b>" + ok + "/" + SHOW.length +
          "</b> reached the goal · 3 blockers found";
      }, done);

      if (!reduceMotion) setTimeout(runCycle, done + 3600);
    }

    if (reduceMotion) {
      // static end-state
      SHOW.forEach(function (s, idx) {
        rowEls[idx].classList.remove("dim");
        var label = s.outcome === "completed" ? "✓ completed" : "✕ abandoned";
        setStatus(rowEls[idx], label, s.outcome);
      });
      footEl.innerHTML = "swarm complete — <b>3/6</b> reached the goal · 3 blockers found";
    } else {
      // kick off when the console scrolls into view
      var consoleEl = document.getElementById("console");
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

})();
