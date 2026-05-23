# Persona Swarm — Strategy & Business Notes

A living reference for how Persona Swarm works, what it catches, and how to
turn it into a real business. Keep this open when planning the next move.

---

## 1. What the service actually is

A local Python service. User points it at a URL with a goal in plain English.
The service:

1. **Crawls** the site once (Playwright + BFS) to build a page graph.
2. **Spawns persona agents in parallel** — each is an LLM (Claude or GPT)
   driving its own headless Chromium. Each persona has a distinct system
   prompt: patience, viewport, mindset (impatient power user, screen-reader
   user, skeptical shopper, etc.).
3. **Each persona acts in character** — perceives the rendered DOM, decides
   the next action, logs friction in its own voice.
4. **Static auditor pass** — deterministic, no LLM — checks every mapped page
   for broken links, SEO/meta gaps, accessibility, copywriting bugs, UI
   edges, mixed content, and auth softlock signals.
5. **A judge LLM** scores the runs, finds shared blockers (issues that
   tripped multiple personas = high priority), and merges persona findings
   with audit findings into a single ranked fix list.
6. **History store** keeps prior runs keyed by URL+goal — next run diffs
   against the last to flag regressions.

Output: a JSON + Markdown report with a 0–100 health score, shared blockers,
per-persona verdicts, audit findings grouped by category, and prioritized
fixes.

### Tech stack
Python 3.13 · Flask backend · Playwright (Chromium) · Anthropic + OpenAI
SDKs · vanilla JS frontend · file-based history (`reports/history/`).

### What the customer needs
- An Anthropic or OpenAI API key (they pay tokens; you never touch their key
  in BYOK mode).
- A URL reachable from wherever the service runs (their machine, or your
  hosted box).
- A one-sentence goal.

---

## 2. What the swarm catches

### Persona findings (subjective UX)
The personas surface things real users feel:
- Confusing labels, jargon, idioms
- Dead-end clicks, infinite spinners, silent failures
- Missing trust signals, hidden fees, forced signups
- Tap targets too small to hit
- Auth flows that loop back to themselves
- Pages that feel scammy, broken, or untrustworthy

### Static-audit findings (deterministic, no LLM)
The auditor catches the technical bugs personas can't see:

| Category | What it catches |
|---|---|
| **links** | Broken links (HEAD-tested), pages returning 4xx/5xx, DNS failures |
| **seo** | Missing `<title>`, meta description, `<h1>`, canonical, `og:title/description/image`; titles >70ch, descriptions >160ch |
| **a11y** | Images without alt, form inputs without an accessible label |
| **copy** | Live lorem ipsum, `TODO/TBD/FIXME/PLACEHOLDER` strings, vague link text (`click here`, `read more`) |
| **ui** | Interactive elements <32×32px (mobile-hostile tap targets), page load failures |
| **mixed-content** | http:// resources on https:// pages (browser will block them) |
| **auth** | Login/signup form with no visible error or feedback region — auth softlock signal |

Audit findings are merged into the judge's prioritized fix list — audit
blockers sort to the top alongside persona blockers.

---

## 3. Persona roster (18 total)

### Core 8 — default on, runs by every swarm
1. ⚡ Impatient Power User
2. 🐣 Cautious First-Timer
3. 🦮 Screen-Reader User
4. 📱 Mobile Thumb User
5. 🕵️ Skeptical Shopper
6. 🤹 Distracted Multitasker
7. 🌍 Non-Native Speaker
8. 😤 Rage Clicker

### Extra 6 — opt-in, universal value
9. 🔁 Returning Power User — catches redesign regressions, broken bookmarks
10. 👓 Older / Low-Vision User — catches low contrast, thin fonts, color-only meaning
11. 🛡️ Privacy-Strict User — catches features that silently break without trackers/cookies
12. 🚪 Cancellation Hunter — tests the exit flow (where dark patterns hide)
13. ✍️ Awkward-Data Filler — catches validation that breaks on apostrophes, accents, real emails
14. ⌨️ Keyboard-Only Power User — catches missing focus rings, broken tab order, focus traps

### Niche 4 — opt-in, context-specific
15. ⚖️ Comparison Shopper — for marketing/sales pages: is the value prop clear vs. competitors?
16. 📋 Compliance Buyer — for B2B SaaS: missing security/privacy/legal info before purchase
17. 🔍 First-Touch Prospect — for ad-targeted landing pages: 10-second comprehension test
18. 🐢 Slow-Connection User — for media-heavy / SPA-heavy sites: skeleton screens, layout shifts

### Cost per run (very rough)
- 1 persona ≈ 15 steps ≈ ~30K tokens ≈ $0.15 (Sonnet) / $0.04 (Haiku)
- 8 personas (core only): ~$1.20 (Sonnet), ~$0.30 (Haiku), ~5 min wall time
- 18 personas (full): ~$2.70 (Sonnet), ~$0.70 (Haiku), ~6 min wall time
- Each persona adds ~30s of runtime since they run in parallel

---

## 4. The "early access vs paid" answer

**Early access is a tool, not a revenue model.** It collects signal so you
know who to charge, what they'll pay, and what feature unlocks willingness
to pay. The money comes from a pricing structure that lives on top of it.

### What early access actually does
- A waitlist → 200+ emails of qualified prospects when you flip the paywall on
- A reason to talk → DM the first 20 signups, ask what they'd pay; that
  conversation is worth more than the email
- Social proof → "X founders on the waitlist" boosts the next signup
- Free QA → beta users find the bugs before paying customers do

It doesn't make money. It earns the right to charge later.

---

## 5. Recommended pricing model

Hybrid: **free tier (lead gen) + paid subscription (revenue) + BYOK option
(removes the token-cost objection) + per-audit option (high-margin
consulting)**.

| Tier | $/mo | Runs/mo | Personas | Who it's for |
|---|---|---|---|---|
| **Free / BYOK** | $0 | 3 / mo | Core 8 only, bring your own API key | Solo devs, evaluators — their LLM bill, your platform free |
| **Solo** | $29 | 20 / mo | All 18 personas, BYOK or pay tokens to you | Indie hackers, freelancers, vibe coders |
| **Team** | $99 | 100 / mo | All 18 + scheduled runs, regression alerts, shareable report links, included tokens (Sonnet) | Startups, small SaaS, agencies |
| **Agency** | $299 | Unlimited | Team plan + multiple workspaces, white-label reports, CI integration, priority support | Agencies, larger teams |

Plus a **one-off audit at $499** — they paste a URL, you (or the system)
run a thorough swarm and ship them a written PDF + actionable Slack
message. Highest margin per hour. Sell this on Twitter/X *before* you
build the subscription product to learn what report shape customers
actually pay for.

### Why these numbers work

- 8 personas × 15 steps × Sonnet ≈ $0.80/run in token cost; Haiku ≈ $0.20
- Full 18-persona run ≈ $2 in tokens
- **Solo $29 BYOK**: pure platform margin, ~$28/mo profit per customer
- **Team $99 with included tokens**: 100 runs × $1 avg = breakeven on
  tokens; margin is the platform fee + customers who run far less than 100
  (most do)
- **One-off audit $499**: ~5 min compute, ~$5 in tokens, ~15 min to write
  up = ~$490 margin

### BYOK is the unlock

"Bring Your Own Key" converts skeptics. Their objection is *"AI tools
will burn through tokens — what's my actual bill going to be?"* BYOK
answers it: **the platform is $29/mo flat, your Anthropic bill is yours,
here's our estimator that says expect ~$X/mo at your usage**. They feel
in control. You get pure platform revenue.

---

## 6. Go-to-market sequence

You don't have to build all of this now. Sequence:

1. **This week** — Change the landing CTA from "Get early access" to
   *"Lock in 50% off — paid plans launching [DATE]. Free during beta."*
   That single change converts vague signups into "I'm reserving a
   discount", which is dramatically more motivating.

2. **Next 2 weeks** — Sell **10 one-off audits at $250** (introductory
   price) on Twitter/X / IndieHackers / Reddit. You're not selling
   software, you're selling a report. This teaches you what customers
   actually value. **Cheapest, fastest validation of willingness to
   pay.** If 10 people pay $250, that's $2500 — and far more importantly,
   ten conversations about what would convince them to subscribe.

3. **Month 1** — Hosted version with Stripe → Solo $29 + Team $99 tiers.
   Free tier with BYOK and 3 runs/mo. Email the early-access list with a
   "lock in 50% off for life" offer. Expect 10–20% conversion.

4. **Month 2–3** — Ship scheduled runs, regression alerts, shareable
   links. These unlock the Team $99 tier (companies will pay for
   automated regression detection on every release).

5. **Month 3+** — CI integration (GitHub Action that posts a comment on
   every PR). Unlocks Agency tier and enterprise conversations.

---

## 7. Other revenue paths to consider

- **GitHub Action / CI plugin** — "Run a persona swarm on every PR."
  Per-seat to engineering teams. Big-ticket, slow sales cycle.
- **Slack bot** — paste a URL in `#design`, get a report back.
  Per-workspace pricing.
- **API access** — developer tier with API keys, charge per programmatic
  run. Lets people build it into their own workflows.
- **White-label for agencies** — agencies pay $299/mo to run audits in
  their branding for their clients. They mark up to clients. Force-
  multiplier on your revenue per customer.
- **Persona pack marketplace** — "E-commerce pack", "B2B SaaS pack",
  "Healthcare HIPAA-aware pack" sold as one-time $19 add-ons. Tiny
  revenue, big positioning ("there's a specialized pack for my industry").
- **Credits model alternative** — instead of monthly subscription, user
  buys 50 credits for $49. Each run consumes credits based on persona
  count. Better psychology for occasional users; many AI tools use this.

---

## 8. Delivery models — three to pick from

### A. Self-hosted (today)
Customer clones the repo, runs `python server.py`, opens localhost. Zero
cost to you. Sell as "DevDependency" — one-time license fee or a paid
Pro tier with more personas, scheduled runs, CI integration. Lowest
revenue per customer, lowest support burden.

### B. Hosted SaaS (the real business)
You run the service. Customer pastes URL + goal in your dashboard. Two
cost layers to manage:
- LLM tokens — pass through (BYOK) or mark up your own key
- Browser compute — each persona = one headless Chromium. 8 personas ×
  5 min = real CPU/RAM. Use Browserbase, Steel.dev, or roll your own on
  Fly.io / Hetzner with isolated workers per run

This is where the recurring revenue lives.

### C. White-glove / agency
Sell *runs* as a consulting deliverable. You run the swarm on the
customer's app, write up findings, charge $500–$2000 per audit. Highest
margin, doesn't scale — but it's how you find what customers actually
pay for before building the SaaS.

**Recommendation: start with C → migrate to A→B**. Audits this month,
hosted SaaS in 8–12 weeks.

---

## 9. The unfair angle for marketing

*"Your Playwright tests confirm the path you wrote works. Persona Swarm
finds the paths you never wrote."*

The pitch lands hardest with:
- Solo founders shipping vibe-coded apps (their primary fear is silent UX failure)
- Small startups with no QA team
- Agencies who need to show clients "the bot found this"
- Indie hackers iterating fast and wanting a sanity check before each release

---

## 10. Honest risks & gaps

- **Token cost per run** — price plans accordingly. Default to Haiku, let
  paid users opt up to Sonnet/Opus.
- **Site-blocked** — some sites detect headless Chromium. Needs
  stealth/anti-bot mode for v2.
- **Auth flows** — personas can't get past login walls without
  credentials. Needs a "session injection" feature for v2 (encrypted
  cookie / token paste).
- **LLM nondeterminism** — same run produces slightly different reports.
  Mitigated by seed control + the regression diff doing the heavy lifting.
- **Concurrency limits at scale** — 8 parallel Chromium browsers per
  customer × N customers means real infrastructure. Browserbase /
  Steel.dev solve this if you don't want to operate browser farms.

---

## 11. One tactical thing to do today

Change the landing CTA from `Get early access` to
**`Lock in 50% off — paid plans coming [DATE]`**. Free during beta, but
the signup now reserves a discount.

That single change converts "vague signup" into "I'm holding my spot",
which is dramatically more motivating.

---

_Last updated: 2026-05-23. This file is git-tracked — edit it as your
plan changes._
