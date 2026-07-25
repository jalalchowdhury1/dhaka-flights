# AGENTS.md — dhaka-flights trip tracker

> Read this first. `README.md` / `JALAL_READ.md` are Jalal's plain-English docs — leave
> them alone unless asked. This file is the single LLM source of truth for this repo.

## 1. What this is

Nightly price tracker for **ONE** trip (2 adults + 1 child with seat) —
narrowed 2026-07-25 from "price every variant" to "price the trip he's buying":

> **BOS → Istanbul (2 nights) → Dhaka (≤29 days; 30-day visa) → Singapore
> (2 nights) → Bali (5 nights; Marriott 5th-night-free) → BOS, home by Feb 7, 2027.**

It buys as **two purchases**, and everything in the code is named for them:

| | what | how it's scraped |
|---|---|---|
| **Ticket ①** | BOS→IST + IST→DAC + DPS→BOS, one multi-city ticket | `ISTANBUL2_SEARCH` (kind `stopover2`) |
| **Ticket ②** | DAC→SIN→DPS — one multi-city ticket **or** two one-ways, whichever is cheaper | `SG_TICKET_SEARCHES` + the two `LEGS` |

Every night at midnight it scrapes those 13 searches, prices the trip, self-checks,
writes a Google Sheet, Telegrams the result (with per-leg baggage + same-date
alternatives), and publishes `site/data.json` for **dhaka-flights.vercel.app**.

**Hard rules:** 5 Bali nights, 2 Istanbul nights, 2 Singapore nights, home ≤ Feb 7,
Dhaka ≤ 29 days. Nights that come out different still win on price — they're
surfaced as a self-check note, never silently. **Airline rules:** NOTHING excluded
— "US-Bangla prices are unbeatable" — the CHEAPEST wins. THAI / Singapore Airlines
are a soft preference: when the winner isn't THAI/SQ but such an option exists, its
upgrade price surfaces as `alt_note`. `_is_preferred` requires EVERY carrier in a
multi-airline string to be THAI/SQ (substring matching once paid +$1,328 for a
half-Malaysia-Airlines ticket).

**RETIRED 2026-07-25 — do not resurrect without asking.** The direct open-jaw, the
three-one-ways combo, the Istanbul-only and Singapore-only variants, and the TK
30h-stopover trip are no longer scraped, tracked, charted or Telegrammed
("i only need the main trip … not the others"). Their configs
(`OPENJAW_SEARCHES`, `STOPOVER_SEARCH`, `ISTANBUL3_SEARCH`) and their combo
functions (`best_structures`, `best_combos`, `cheapest_by_leg`) still work and are
still tested — re-adding one is a two-line change in `scrape_tickets_all()` / `LEGS`.
Their historical numbers stay in `site/data.json` and in the Sheet's columns 3–7;
nothing is rewritten backwards.
Specs: `docs/superpowers/specs/2026-07-18-singapore-detour-variant-design.md`
(the trip's evolution) — the 2026-07-25 narrowing is documented here and in git history.

Redesigned 2026-07-15 from the original round-trip BOS⇄DAC/BKK watcher; design spec:
`docs/superpowers/specs/2026-07-15-three-leg-trip-redesign-design.md`.

## 2. Architecture / data flow

```
launchd 12:00am + 2:00am retry slot (com.jalal.dhaka-flights.plist, parallel with com.jalal.carmax — isolated browse sessions; retry no-ops after success via .last_run_date; run_daily.sh Telegrams on a crash exit AND refuses to START after 5:30 AM — user awake/working — so wake-replays of missed slots skip for the day) → run_daily.sh → run_daily.py
  scraper.py   scrape_tickets_all()    Ticket ① — 1 multi-city search, up to
                                       TICKET1_ATTEMPTS=3 tries (nothing else can
                                       substitute for it, so it runs FIRST and
                                       retries hardest): BOS→IST Jan 4 + IST→DAC
                                       Jan 7 + DPS→BOS Feb 6, no airline filter
               scrape_sg_tickets_all() Ticket ② as one ticket — 4 multi-city
                                       DAC→SIN→DPS searches (SEPARATE list; the
                                       open-jaw pairing loop would mis-handle them)
               scrape_all()            Ticket ② as two one-ways — 8 searches
                                       (LEGS: DAC→SIN Jan 29–Feb 1, SIN→DPS Jan 31–Feb 3)
        │  drives real Chrome via the `browse` CLI (a11y-tree snapshots)
        ▼
  combo.py     main_trip()         THE trip (kind 'sg-stopover2') — Ticket ① paired
                                   with the cheaper of {1-ticket, 2-one-way} middle
               ticket1_options()   same-dates alternatives to Ticket ①, w/ price gap
               ticket2_options()   same-dates alternatives to Ticket ②, w/ price gap
                                   ('1 ticket' and '2 tickets' rows, deduped)
               best_structures/best_combos/cheapest_by_leg — retired from the
                                   nightly path, kept working + tested
  baggage.py   annotate()/warnings()  per-leg allowance from a sourced carrier
                                   table (Google's tree has NO bag data); US piece
                                   rule for Ticket ①, Asian weight rules for ②
        ▼
  sheet_writer.py → Google Sheet tab "Google Flights" (Ticket ① + ② fares then the
                    one-way legs, replaced daily) + "History" tab (append-only)
  notify_telegram.py → Telegram: the trip, per-leg baggage, same-date alternatives
  publish.py  → site/data.json (main + options + appended history) → git commit+push
        ▼
  site/index.html (static, deployed once on Vercel) fetches data.json raw from
  GitHub on every page load — no redeploy needed for data updates. Two tabs:
  ⭐ The Trip (timeline chips · hero card · trip plan with a 🧳 line per flight ·
  baggage table · Ticket ② then Ticket ① alternatives with Δ-vs-chosen and bag
  rules · booking playbook · price history) · 📈 History (⭐ trip / Ticket ① /
  Ticket ② / airlines / nights / home, tap a row for that day's full detail).
  Strip tiles and chart show trip total + the two ticket prices. All views
  degrade gracefully when a section is missing.
```

## 3. How to run / test / deploy

- Tests: `python3 -m pytest tests/ -q` (pure logic only — parsers, combos,
  baggage table, sheets rows; no browser).
- Manual full run: `./run_daily.sh` (delete `.last_run_date` first or it skips).
- One search interactively: `python3 -c "from scraper import scrape_route; print(scrape_route('DAC','SIN','January 30, 2027'))"`.
- Dashboard deploy (only when site/index.html changes): `cd site && vercel --prod --yes`
  (project `dhaka-flights`, account `jalalchowdhury-8053`). Data updates need NO deploy.

## 4. Secrets & env

- `.env` in repo root (gitignored): `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`.
- Google service account JSON: `~/.config/mcp-google-sheets/service-account.json`.
- git push uses the Mac's stored GitHub credentials; Vercel CLI is logged in locally.

## 4b. Redundancy layers (hardened 2026-07-18 for the 6-week decision window)

Jalal relies on this nightly until an early-September 2026 booking decision
(calendar reminder set for Sep 1). Defense in depth:
1. **Wake**: `com.jalal.keepawake` LaunchAgent runs `caffeinate -s` with
   KeepAlive+RunAtLoad — survives reboots/terminal closes (the old ad-hoc
   terminal caffeinate died with its window). pmset would otherwise sleep.
2. **Slots**: launchd fires 12:00 + 2:00 + 4:00; `.last_run_date` stamp makes
   later slots no-ops after success. Stamp is written ONLY if ≥1 trip structure
   was built — a catastrophic zero-structure day auto-retries.
3. **No-start-after-5:30** window guard (wake-replays skip, user is working).
4. **Alerts**: wrapper Telegrams on crash exit; in-run Telegram warns on
   0-flight days (browser-broken vs Google-empty distinguished via DIAG).
5. **History in triplicate**: site/data.json (append-only, keyed by date) +
   its full git history on GitHub (pushed nightly) + the Google Sheet
   "History" tab (one appended row/day, `sheet_writer.append_history_row`).
   Plus `backups/` keeps the last 60 daily local snapshots (gitignored;
   Time Machine → T7 covers the disk).
6. **Staleness tripwire**: the dashboard shows a red banner when data.json is
   >36 h old — a silently dead tracker is visible on first glance.
7. Self-check warnings on the site are COLLAPSED by default (tap to expand).

## 4c. Baggage (added 2026-07-25)

Google Flights' a11y tree carries **no** bag information, and the real allowance
depends on the fare brand (EcoFly / Economy Lite / Basic) which only appears at
the airline's checkout. So `baggage.py` is a **sourced lookup table**, not a
scrape: every carrier entry has an official `url` and a `confidence`
(`verified` = read off the airline's own page on `CHECKED`, `typical`, `varies`,
`unknown`). Rules:

- **Never** present these numbers as the booked allowance — the UI says
  "reference — the checkout page is the authority", keep it that way.
- Ticket ① is priced under the **US piece concept** (any itinerary touching the
  Americas, both directions, whole through-ticket): Turkish/Gulf 2 × 23 kg,
  European carriers usually 1 × 23 kg. Ticket ② uses **Asian weight rules**,
  which vary by carrier *and* route (US-Bangla: 40 kg DAC→SIN, 20 kg to Doha).
- A multi-city ticket's **second leg carrier is unknown to us** — Google names
  only the first leg. `annotate()` says "not shown on this ticket" rather than
  guessing; don't "fix" that by assuming the first carrier flies both legs.
- Multi-airline strings ("US-Bangla + Jetstar") get a `summary` naming BOTH
  allowances — the cheap half often includes no free bag at all.
- When a carrier's policy changes, edit `CARRIERS` and bump `CHECKED`.

## 5. Gotchas / hard rules

1. **Google shows the TOTAL price for all selected passengers** (verified 2026-07-15:
   1-pax $367 vs 3-pax $1,099). `price_total` = whole family. Never label it per person.
2. **Wedged browse daemon** ⇒ every command times out, then silent `about:blank`
   trees with exit 0 ⇒ fake 0-result runs. Hardening lives in `_run()` (timeout →
   `DIAG`), blank-page bail, per-route retry, 4-dead-routes abort, and the Telegram
   alert distinguishes LOCAL browser failure from a real 0-result day.
   Debug a 0-day via `cron.log` + `debug_last_zero.txt`.
3. Airport pickers must have an AIRPORT_PICK entry — the bare-code fallback substring-matches random tree lines ("IST" hit "listitem") and derails the form. **Multi-city result lines say "From X US dollars total."**; one-way lines say just
   "From X US dollars." — `_parse_results` accepts both. Flight details on the
   multi-city selection page describe the FIRST leg; the price includes its cheapest
   completion. Only ~top-10 fares show inline — the scraper clicks "View more flights".
4. **The trip must NEVER be dropped silently** (2026-07-16: the exact-5-night
   pairing rule hid a valid $3.4k open-jaw from the daily message). When no
   5-night pairing exists, 4/6 nights are used and `flag` is set (shown verbatim
   in Telegram + site badges); off-target Istanbul/Singapore nights become a
   self-check note. The parser keeps the CHEAPEST `MAX_RESULTS` fares, not the
   first in page order. Since 2026-07-25 there is no second structure to fall
   back on, so `sanity.py` warns loudly when Ticket ① prices but no trip builds.
5. **Trip rules live in combo.py** (`MAX_DHAKA_DAYS=29` counting both end days,
   `IDEAL_BALI_NIGHTS=5`, `HOME_DEADLINE=Feb 7`). Open-jaw "home" date is a
   +1-day heuristic (return-leg arrival isn't parsed on the selection page).
6. **publish.py must never crash the run** — it swallows all exceptions. History is
   append-only inside `site/data.json`, keyed by ISO date (same-day reruns overwrite
   that day's entry).
7. The launchd job often fires twice; `.last_run_date` (written only on success)
   makes the duplicate skip. Machine stays awake via a long-running `caffeinate`.
8. Booking insight (2026-07-15): the open-jaw ticket was ~$1.7k cheaper than
   separate one-ways ($3.4k vs $5.1k for the two long legs). Indonesia e-VOA needs
   proof of onward travel ⇒ the DPS→BOS ticket must be booked before landing in Bali.

## 6. Known issues / TODO

- `main_flyai.py` / `scraper_flyai.py` are dead legacy (flyai experiment) — ignore.
- `cron.log`, `debug_last_zero.txt`, `.DS_Store` are untracked local artifacts.
- Ticket ① is fixed to BOS→IST Jan 4 / IST→DAC Jan 7 / DPS→BOS Feb 6. Other
  outbound or return dates would change the trip's shape, so they're a product
  decision, not a config tweak — ask before adding.
- **Killed-run gotcha (2026-07-18):** a full run is ~11 min (13 searches; it was
  ~25 min at 30 searches before the 2026-07-25 narrowing). Never run it inside a
  harness/tool with a ≤10-min timeout — it gets SIGKILLed mid-scrape (no stamp
  written, no output flushed with buffered stdout). Manual runs:
  `nohup … python3 -u run_daily.py > log 2>&1 &` and watch the log. The launchd
  job has no timeout and is unaffected.

## 7. File map

- `run_daily.sh` / `run_daily.py` — launchd entrypoint; stamp + DIAG alerting
- `sanity.py` — self-check watchdog run before every send: Ticket ① must price,
  a priced Ticket ① must produce a trip, every leg×date and Ticket ② date pair
  must have fares, yesterday's totals must not silently vanish, >25% swings,
  parser drift, and trip-shape drift (2/2/5 nights) all get flagged. Violations
  ride along to Telegram ("🧪 Self-check") and the site's amber banner. When
  adding a tracked search, add its invariant here too.
- `scraper.py` — browse-CLI form driving + parsing (one-way & multi-city); LEGS,
  STOPOVER_SEARCHES, SG_TICKET_SEARCHES config (+ retired configs, kept)
- `combo.py` — trip rules, `main_trip`, `ticket1_options`, `ticket2_options`
  (+ retired `best_structures` / `best_combos` / `cheapest_by_leg`)
- `baggage.py` — sourced per-carrier allowance table; `annotate`, `warnings` (§4c)
- `publish.py` — `build_today` → payload → `write_payload` (backup, write, push)
- `sheet_writer.py`, `notify_telegram.py` — outputs
- `site/` — static dashboard (index.html) + data.json (machine-written)
- `main.py` — manual run: scrape + sheet + terminal summary (no Telegram/publish)
- `tests/` — pytest suite (92 tests; `test_main_trip.py` holds the shared trip
  fixtures, `test_baggage.py` guards the allowance table's honesty)
