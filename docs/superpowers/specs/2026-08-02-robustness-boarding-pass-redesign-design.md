# Robustness + Boarding-Pass Redesign — Design Spec

**Date:** 2026-08-02
**Status:** approved in brainstorming (visual companion session `.superpowers/brainstorm/56189-1785690997`)
**Prior specs:** `2026-08-01-bangkok-singapore-swap-design.md` (current trip), `2026-07-15-three-leg-trip-redesign-design.md` (pipeline shape)

## 1. Goal

Jalal asked for two things about dhaka-flights.vercel.app: make it **more robust**
(page, logic, and pipeline — "all of the above") and **overhaul the aesthetics**
("too long / cluttered" + "looks dated/plain"), with **rollback safety** — the
current working version must stay one command away.

Decisions made interactively:

| Question | Decision |
|---|---|
| Robustness scope | Full audit: page + logic + pipeline |
| "Come back to this" | Rollback safety (tag before touching anything) |
| Usage | Phone quick-glance **and** desktop deep-dive |
| Pain points | Too long/cluttered; looks plain |
| Information architecture | **C — dashboard front + drill-in detail screens** |
| Visual language | **Boarding Pass** (ticket-stub cards, perforations, deep navy `#1a2b49` + warm paper `#fffdf8`/`#e8e4dc`, mono flight codes) |
| Execution | **Approach 1 — freeze the data contract, rebuild the site fresh, harden the pipeline surgically** |

## 2. Non-negotiable constraints (carried from AGENTS.md)

- `data.json` contract is **frozen** — the redesign consumes exactly what
  `publish.py` writes today. No pipeline output changes.
- No new searches; the 25–30-min nightly budget is untouched.
- Site stays ONE static `site/index.html` on Vercel, fetching `data.json` raw
  from GitHub — data updates never need a deploy.
- Retired trips stay retired. 🌴 Bali watch stays visible (benchmark).
- Hotel/resort tables keep the **offset-%** standard with bands and the
  assumption line.
- Self-check warnings collapsed by default.
- Chart keeps the dataviz-spec conventions (4 validated categorical series
  slots, order = CVD-safety mechanism; 2px lines, ring endpoints, hairline
  grid, crosshair tooltip). Re-skin, don't respec.
- `orderInfo()` must keep mapping every trip shape incl. `bali-rev`; stays in
  sync with `combo.ORDERS`.
- Light AND dark shipped and verified; keep `prefers-color-scheme` auto with
  `data-theme` toggle override. Boarding-pass "home" mode is warm-paper light;
  dark mode is the night variant (navy surfaces, paper-toned text) — not a
  grey inversion.

## 3. Site design (rebuild of `site/index.html`)

### 3.1 Architecture

Hash-routed mini-app in one file, no framework, no build step. Routes:

- `#/` **Tonight** — the 5-second phone glance.
- `#/flights` — deep dive on the flights.
- `#/stays` — hotels + card-play.
- `#/history` — chart, per-night detail, Bali benchmark.

Browser back/forward and bookmarks work via `hashchange`. Unknown hash →
`#/`. Each screen is a render function over the same in-memory payload;
navigation never refetches.

### 3.2 Screen contents (every current section keeps a home)

**`#/` Tonight** (mock approved 2026-08-02):
1. Top bar: wordmark, "updated HH:MM" chip, 🔎 verified ✓ chip.
2. Staleness banner (>36 h) above everything when triggered.
3. **Verdict boarding pass**: navy header (Tonight's cheapest · order label),
   mono route strip (BOS ✈ IST ✈ DAC ✈ …, order-aware), total + Δ vs
   yesterday, buy-signal chip (watch/window/past stages + countdown), price
   context chip (rank · distance to low), perforated divider, stub row with
   ① and ② airline + price. Flag badge when the day is off-shape.
4. **Since yesterday** card (`changes` incl. 🧳⚠️).
5. Mini sparkline (trip total only) → taps to `#/history`.
6. Four drill-in tiles: ✈️ Flights, 🏨 Stays, 📈 History, 🌴 Bali watch
   (tile itself shows tonight's Bali total + Δ vs main).
7. 🧪 self-check footer line — collapsed; expands to sanity warnings +
   verify.py findings + client-side schema/arithmetic findings.
8. 💸 budget-companion teaser line under the verdict when `budget` exists
   ("same trip $X cheaper with looser dates → Flights").

**`#/flights`**: trip plan with per-leg 🧳 lines → Ticket ① and Ticket ② as
boarding-pass stubs → 💸 budget card → 🔁 other-order card → alternatives
(Ticket ② then Ticket ①, Δ-vs-chosen, bag rules) → baggage reference table
("reference — the checkout page is the authority" kept verbatim) → booking
playbook.

**`#/stays`**: The Athenee card (order-aware stay dates, points math,
5th-night-free warning when ≠5 nights) → IST/SIN card-play section
(shortlists, offset-% tables with bands + assumption lines, strategy notes).

**`#/history`**: full chart (trip / ① / ② / Bali series, pre-swap stitch
note) → price-context block → per-night table (tap a row for that day's full
detail: airlines, nights, home date, totals) → Bali watch card.

### 3.3 Visual system

Design tokens (CSS custom properties) for the boarding-pass language:
navy ink `#1a2b49`, paper card `#fffdf8`, paper background `#e8e4dc`,
mono (`ui-monospace`) for route codes and small labels, uppercase letter-
spaced micro-labels, perforation as a reusable CSS element (dashed rule +
two punched circles), pill chips for statuses, existing good/warn semantic
colors re-derived on the new palette with AA contrast in both modes.
`font-variant-numeric: tabular-nums` on all prices. Focus-visible rings,
`prefers-reduced-motion` guard, aria roles on nav/tabs preserved from the
current build. Implementation will load the **design-taste-frontend** and
**dataviz** skills before writing code.

## 4. Robustness design

### 4.1 Site side

1. **Fetch fallback chain**: GitHub raw → localStorage last-good payload
   (saved on every successful load; rendered with a prominent "showing data
   from <date> — live fetch failed" banner) → a designed "can't reach data"
   screen. The page can never be blank.
2. **Schema guard**: `validatePayload(d)` checks required keys/types
   (mirrors `schema.json`, §4.2). Findings feed the 🧪 line; only the
   affected section degrades.
3. **Per-section error boundaries**: every render function runs through
   `renderSafe(fn)`; a throw renders a compact "section couldn't render"
   card, everything else lives.
4. **Client-side arithmetic check**: ①+② = total; history mirror matches
   tonight's totals; mismatch → visible ⚠ in the 🧪 line.
5. Staleness banner unchanged (>36 h, red).

### 4.2 Pipeline side (surgical)

1. **`publish.py` push-retry**: `git push` retried 3× with backoff
   (10s/30s/60s). Final failure → Telegram warning via the existing bot
   creds ("site will be stale — data is committed locally"). Publish still
   never crashes the run.
2. **Pre-publish contract check**: `schema.json` in repo root describes the
   payload the site expects (required keys, types, history-entry shape).
   `publish.py` validates before writing; violations are appended to
   `warnings` (ride to Telegram + 🧪) — publishing is NEVER blocked.
   A pytest asserts the real `build_today` output validates, keeping the
   two sides in sync.
3. **Run-overrun guard**: `run_daily.py` wall-clock soft deadline
   (`RUN_DEADLINE_MIN = 35`, checked between searches in the runners).
   Past it, remaining searches are skipped in reverse priority (Bali watch
   first, then remaining one-way legs; Ticket ① and Ticket ② pairs are
   never skipped once started), each skip flagged into sanity warnings.
   Prevents the Aug-1-style multi-hour grind on a slow-walked night.

### 4.3 Rollback

- Before ANY change: `git tag v1-pre-overhaul && git push origin v1-pre-overhaul`.
- Restore recipe documented in AGENTS.md §3:
  `git checkout v1-pre-overhaul -- site/index.html && cd site && vercel --prod --yes`.
- Plan B: Vercel dashboard → previous deployment → "Promote to production".
- The old index.html additionally survives in git history by the tag, so no
  `site/legacy/` copy is needed.

## 5. Error handling summary

| Failure | Behavior |
|---|---|
| data.json fetch fails | localStorage last-good + labeled banner |
| Payload malformed | schema findings in 🧪; bad section degrades alone |
| One render throws | that section's error card only |
| ①+② ≠ total | visible ⚠ (client) + verify.py already flags (pipeline) |
| git push fails | 3 retries → Telegram warning |
| Run overruns | low-priority searches skipped + flagged, run completes |
| Scraper dead >36 h | red staleness banner (existing) |

## 6. Testing

- **Pytest** (new): schema validation of real `build_today` output; push-retry
  logic (mocked git failures); overrun-guard skip ordering. Existing 152
  tests must stay green — pipeline behavior otherwise unchanged.
- **Browser QA** before the swap commit: light + dark × phone (390px) +
  desktop × all four routes, with (a) tonight's real data.json,
  (b) mutated payloads — missing `hotel`, null totals, empty `history`,
  truncated file — served locally. ui-test/claude-in-chrome for the pass.
- **Content audit** during rebuild: every section gets a plain-English
  micro-label so it's self-explanatory (addresses "make sure all things are
  logical and make sense").

## 7. Rollout

1. Tag `v1-pre-overhaul` (rollback point).
2. Pipeline hardening first (publish retry, schema.json, overrun guard) —
   small, tested, independent commits; nightly runs keep working throughout.
3. New site built as `site/index_v2.html` locally; QA per §6 against real +
   mutated data.
4. Swap: single commit renames v2 → `site/index.html`, one
   `vercel --prod --yes` deploy.
5. AGENTS.md updated: new site conventions, rollback recipe, schema.json
   contract, overrun guard.
6. Watch the next nightly run end-to-end (or trigger the manual path per
   AGENTS.md §3 rules) before calling it done.

## 8. Out of scope

- No data-contract changes, no new/changed searches, no Telegram message
  changes, no Sheet changes.
- No multi-file site, no framework, no build step.
- Resurrecting retired trips.
