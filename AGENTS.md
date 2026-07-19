# AGENTS.md — dhaka-flights trip tracker

> Read this first. `README.md` / `JALAL_READ.md` are Jalal's plain-English docs — leave
> them alone unless asked. This file is the single LLM source of truth for this repo.

## 1. What this is

Daily price tracker for one fixed family trip (2 adults + 1 child with seat):
**BOS → Dhaka (≤29 days; 30-day visa) → Bali (5 nights; Marriott 5th-night-free)
→ BOS, home by Feb 7, 2027.** Every night at midnight it scrapes Google Flights, ranks
*ticketing structures* (three one-ways vs an open-jaw multi-city ticket + separate
Dhaka→Bali hop), writes a Google Sheet, Telegrams the best price, and publishes
`site/data.json` for the public dashboard at **dhaka-flights.vercel.app**.

**THE MAIN TRIP (final, 2026-07-18):** BOS → **Istanbul (EXACTLY 2 nights)** →
Dhaka → **Singapore (EXACTLY 2 nights)** → **Bali (5 nights, FIXED)** → BOS.
Hard rules: 5 Bali nights, 2 Istanbul nights, 2 Singapore nights, home ≤ Feb 7,
Dhaka ≤ 29 days. **Airline rules (revised same day):** NOTHING excluded —
"US-Bangla prices are unbeatable" — the CHEAPEST airline wins. THAI / Singapore
Airlines are a soft preference only: when the winner isn't THAI/SQ but such an
option exists, its upgrade price surfaces as `alt_note`
("THAI/Singapore Airlines option +$X"). `_is_preferred` requires EVERY carrier
in a multi-airline string to be THAI/SQ (substring matching once paid +$1,328
for a half-Malaysia-Airlines ticket). ISTANBUL3_SEARCH is retired from the
nightly rotation (config kept in scraper.py for easy re-adding).
The combined trip needs NO extra searches: it pairs the Istanbul-stopover tickets
(long legs) with the Singapore middles inside `combo.best_singapore` — kinds
`sg-stopover2` (= the main trip, history metric `combined_total`) and `sg-stopover`
(TK-30h + SIN). Singapore-only variants (kinds `sg-openjaw`/`sg-oneways`,
metric `singapore_total`) and all direct/Istanbul-only structures are still tracked
for comparison. Spec: `docs/superpowers/specs/2026-07-18-singapore-detour-variant-design.md`
(the combined-trip + airline-rules evolution is documented here and in git history).

Redesigned 2026-07-15 from the original round-trip BOS⇄DAC/BKK watcher; design spec:
`docs/superpowers/specs/2026-07-15-three-leg-trip-redesign-design.md`.

## 2. Architecture / data flow

```
launchd 12:00am + 2:00am retry slot (com.jalal.dhaka-flights.plist, parallel with com.jalal.carmax — isolated browse sessions; retry no-ops after success via .last_run_date; run_daily.sh Telegrams on a crash exit AND refuses to START after 5:30 AM — user awake/working — so wake-replays of missed slots skip for the day) → run_daily.sh → run_daily.py
  scraper.py   scrape_all()          18 one-way searches (LEGS: BOS→DAC Jan 4–6,
                                     DAC→DPS Jan 31–Feb 3, DPS→BOS Feb 5–7, plus
                                     DAC→SIN Jan 29–Feb 1, SIN→DPS Jan 31–Feb 3)
               scrape_openjaw_all()  4 multi-city searches: OPENJAW_SEARCHES
                                     (BOS→DAC Jan 4 + DPS→BOS Feb 6 / Feb 7) +
                                     STOPOVER_SEARCHES: the Turkish 30h-Istanbul
                                     free-hotel itinerary (kind "stopover") AND the
                                     Istanbul 2- AND 3-NIGHT variants (both kind "stopover2" —
                                     istanbul2_total = cheaper of the two; IST→DAC Jan 7 or 8, no airline
                                     filter). IST/SIN nights flex 1–3, price decides — ONLY 5 Bali nights is a hard constant
               scrape_sg_tickets_all() 4 multi-city DAC→SIN→DPS tickets (SEPARATE
                                     list, NOT mixed into openjaws — the direct
                                     open-jaw loop would mis-pair them)
        │  drives real Chrome via the `browse` CLI (a11y-tree snapshots)
        ▼
  combo.py     best_combos()       cheapest valid one-way triple
               best_structures()   one-ways vs open-jaw+middle, cheapest first
               best_singapore()    via-SIN trips (isolated); long legs = one-ways
                                   or open-jaw, SG middle = cheaper of 2-one-ways
                                   / 1-ticket; flags off-ideal Bali/Singapore nights
        ▼
  sheet_writer.py → Google Sheet tab "Google Flights" (one-ways only, replaced daily)
  notify_telegram.py → Telegram: best structure + cheapest per leg
  publish.py  → site/data.json (results + appended history) → git commit+push
        ▼
  site/index.html (static, deployed once on Vercel) fetches data.json raw from
  GitHub on every page load — no redeploy needed for data updates. Three tabs:
  ⭐ The Trip (the MAIN combined itinerary: visual timeline chips, hero card,
  ⚖️ option matrix comparing every variant's total/Δ-vs-main/nights) ·
  🔀 All options (every structure card grouped: IST+SIN, SIN-only, IST-only,
  direct) · History (columns incl. ⭐ IST+SIN). Strip tiles + chart lead with
  combined_total. All views degrade gracefully when a section is missing.
```

## 3. How to run / test / deploy

- Tests: `python3 -m pytest tests/ -q` (pure logic only — parsers, combos, sheets rows).
- Manual full run: `./run_daily.sh` (delete `.last_run_date` first or it skips).
- One search interactively: `python3 -c "from scraper import scrape_route; print(scrape_route('BOS','DAC','January 4, 2027'))"`.
- Dashboard deploy (only when site/index.html changes): `cd site && vercel --prod --yes`
  (project `dhaka-flights`, account `jalalchowdhury-8053`). Data updates need NO deploy.

## 4. Secrets & env

- `.env` in repo root (gitignored): `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`.
- Google service account JSON: `~/.config/mcp-google-sheets/service-account.json`.
- git push uses the Mac's stored GitHub credentials; Vercel CLI is logged in locally.

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
4. **Structures must NEVER be dropped silently** (2026-07-16: the exact-5-night
   pairing rule hid a valid $3.4k open-jaw from the daily message). When no
   5-night DAC→DPS pairing exists, `best_structures` falls back to 4/6 nights
   and sets `flag` (shown verbatim in Telegram + site badges). The parser keeps
   the CHEAPEST `MAX_RESULTS` fares, not the first in page order.
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
- Open-jaw watch is fixed to Jan 4 out; if Jan 5/6 open-jaws get interesting, add
  pairs to `OPENJAW_SEARCHES` (each adds ~2 min to the run).
- **Killed-run gotcha (2026-07-18):** a full run is now ~20–25 min (30 searches).
  Never run it inside a harness/tool with a ≤10-min timeout — it gets SIGKILLed
  mid-scrape (no stamp written, no output flushed with buffered stdout). Manual
  runs: `nohup … python3 -u run_daily.py > log 2>&1 &` and watch the log. The
  launchd job has no timeout and is unaffected.

## 7. File map

- `run_daily.sh` / `run_daily.py` — launchd entrypoint; stamp + DIAG alerting
- `sanity.py` — self-check watchdog run before every send: every scraped variant
  must appear in structures, every leg×date must have fares, yesterday's metrics
  must not silently vanish, >25% swings and parser drift get flagged. Violations
  ride along to Telegram ("🧪 Self-check") and the site's amber banner. When
  adding a new tracked structure/search, add its invariant here too.
- `scraper.py` — browse-CLI form driving + parsing (one-way & multi-city), LEGS config
- `combo.py` — trip rules, `best_combos`, `best_structures`, `cheapest_by_leg`
- `publish.py` — data.json build + git push
- `sheet_writer.py`, `notify_telegram.py` — outputs
- `site/` — static dashboard (index.html) + data.json (machine-written)
- `main.py` — manual run: scrape + sheet + terminal summary (no Telegram/publish)
- `tests/` — pytest suite (29 tests)
