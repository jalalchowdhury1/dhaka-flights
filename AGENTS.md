# AGENTS.md — dhaka-flights trip tracker

> Read this first. `README.md` / `JALAL_READ.md` are Jalal's plain-English docs — leave
> them alone unless asked. This file is the single LLM source of truth for this repo.

## 1. What this is

Daily price tracker for one fixed family trip (2 adults + 1 child with seat):
**BOS → Dhaka (≤29 days; 30-day visa) → Bali (5 nights; Marriott 5th-night-free)
→ BOS, home by Feb 7, 2027.** Every day at 3am it scrapes Google Flights, ranks
*ticketing structures* (three one-ways vs an open-jaw multi-city ticket + separate
Dhaka→Bali hop), writes a Google Sheet, Telegrams the best price, and publishes
`site/data.json` for the public dashboard at **dhaka-flights.vercel.app**.

Redesigned 2026-07-15 from the original round-trip BOS⇄DAC/BKK watcher; design spec:
`docs/superpowers/specs/2026-07-15-three-leg-trip-redesign-design.md`.

## 2. Architecture / data flow

```
launchd 3:00am (com.jalal.dhaka-flights.plist) → run_daily.sh → run_daily.py
  scraper.py   scrape_all()          9 one-way searches (LEGS: BOS→DAC Jan 4–6,
                                     DAC→DPS Feb 1–3, DPS→BOS Feb 5–7)
               scrape_openjaw_all()  3 multi-city searches: OPENJAW_SEARCHES
                                     (BOS→DAC Jan 4 + DPS→BOS Feb 6 / Feb 7) +
                                     STOPOVER_SEARCH (BOS→IST / IST→DAC / DPS→BOS,
                                     the Turkish 30h-Istanbul free-hotel itinerary)
        │  drives real Chrome via the `browse` CLI (a11y-tree snapshots)
        ▼
  combo.py     best_combos()       cheapest valid one-way triple
               best_structures()   one-ways vs open-jaw+middle, cheapest first
        ▼
  sheet_writer.py → Google Sheet tab "Google Flights" (one-ways only, replaced daily)
  notify_telegram.py → Telegram: best structure + cheapest per leg
  publish.py  → site/data.json (results + appended history) → git commit+push
        ▼
  site/index.html (static, deployed once on Vercel) fetches data.json raw from
  GitHub on every page load — no redeploy needed for data updates.
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
4. **Trip rules live in combo.py** (`MAX_DHAKA_DAYS=29` counting both end days,
   `IDEAL_BALI_NIGHTS=5`, `HOME_DEADLINE=Feb 7`). Open-jaw "home" date is a
   +1-day heuristic (return-leg arrival isn't parsed on the selection page).
5. **publish.py must never crash the run** — it swallows all exceptions. History is
   append-only inside `site/data.json`, keyed by ISO date (same-day reruns overwrite
   that day's entry).
6. The launchd job often fires twice; `.last_run_date` (written only on success)
   makes the duplicate skip. Machine stays awake via a long-running `caffeinate`.
7. Booking insight (2026-07-15): the open-jaw ticket was ~$1.7k cheaper than
   separate one-ways ($3.4k vs $5.1k for the two long legs). Indonesia e-VOA needs
   proof of onward travel ⇒ the DPS→BOS ticket must be booked before landing in Bali.

## 6. Known issues / TODO

- `main_flyai.py` / `scraper_flyai.py` are dead legacy (flyai experiment) — ignore.
- `cron.log`, `debug_last_zero.txt`, `.DS_Store` are untracked local artifacts.
- Open-jaw watch is fixed to Jan 4 out; if Jan 5/6 open-jaws get interesting, add
  pairs to `OPENJAW_SEARCHES` (each adds ~2 min to the run).

## 7. File map

- `run_daily.sh` / `run_daily.py` — launchd entrypoint; stamp + DIAG alerting
- `scraper.py` — browse-CLI form driving + parsing (one-way & multi-city), LEGS config
- `combo.py` — trip rules, `best_combos`, `best_structures`, `cheapest_by_leg`
- `publish.py` — data.json build + git push
- `sheet_writer.py`, `notify_telegram.py` — outputs
- `site/` — static dashboard (index.html) + data.json (machine-written)
- `main.py` — manual run: scrape + sheet + terminal summary (no Telegram/publish)
- `tests/` — pytest suite (29 tests)
