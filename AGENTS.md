# AGENTS.md — dhaka-flights trip tracker

> Read this first. `README.md` / `JALAL_READ.md` are Jalal's plain-English docs — leave
> them alone unless asked. This file is the single LLM source of truth for this repo.

## 1. What this is

Nightly price tracker for **ONE** trip (2 adults + 1 child with seat) —
narrowed 2026-07-25 from "price every variant" to "price the trip he's buying",
reshaped 2026-08-01 (**Bali OUT** — "I don't like the tail risk of dengue" —
Bangkok in, the 5 Marriott nights move there):

> **BOS → Istanbul (2 nights) → Dhaka (≤29 days; 30-day visa) → Bangkok
> (5 nights; Marriott 5th-night-free) + Singapore (2 nights), IN WHICHEVER
> ORDER IS CHEAPER → BOS, home by Feb 7, 2027.**

Both city orders are priced every night; the cheaper complete trip headlines
and the loser is surfaced as `other_order` with its Δ (never hidden). It buys
as **two purchases**, and everything in the code is named for them:

| | what | how it's scraped |
|---|---|---|
| **Ticket ①** | BOS→IST + IST→DAC + **{SIN or BKK}→BOS**, one multi-city ticket per order | `STOPOVER_SEARCHES` = `TICKET1_SIN_RETURN` + `TICKET1_BKK_RETURN` (kind `stopover2`, `ret_city` keys the order) |
| **Ticket ②** | DAC→BKK→SIN (BKK-first) or DAC→SIN→BKK (SIN-first) — one multi-city ticket **or** two one-ways, whichever is cheaper | `TICKET2_SEARCHES` (order-tagged) + the four `LEGS` |

Every night at midnight it scrapes those 30 searches (2 Ticket ① + 10 Ticket ②
pairs + 18 one-way leg×dates), prices both orders, self-checks, writes a
Google Sheet, Telegrams the result (with per-leg baggage + same-date
alternatives), and publishes `site/data.json` for **dhaka-flights.vercel.app**.
Spec: `docs/superpowers/specs/2026-08-01-bangkok-singapore-swap-design.md`.

**💸 Budget companion (`combo.budget_trip`, 2026-07-27):** alongside the main
trip, the cheapest version of the SAME trip — same Ticket ① (and therefore the
same ORDER), same 5-night Bangkok block — with the minimum-2-Singapore-nights
rule waived (≥1 night) and the Dhaka departure free to shift (both DAC exits
scraped from Jan 27). Only shown when STRICTLY cheaper than the main trip
(else `budget` is None and nothing renders); carries `savings` + human `diffs`
vs main. Surfaces as a 💸 block in Telegram, a collapsible card on the site,
`budget_total` in history/data.json, and the Sheet History column "💸 Budget $"
(appended, per the append-only rule).

**Hard rules:** 5 Bangkok nights, 2 Istanbul nights, **MINIMUM 2 Singapore
nights** (`MIN_SG_NIGHTS`, Jalal 2026-07-27 — an overnight first hop had priced
a 1-night ticket below every 2-night option and headlined the trip; a ≥2-night
Singapore stay now always outranks a shorter one, price decides only within a
tier, and a <2-night day survives only as a flagged fallback), home ≤ Feb 7,
Dhaka ≤ 29 days. **Across orders, a valid trip always outranks a flagged one**
(sort key `(not valid, total)`), so a cheap-but-off-shape order never silently
displaces the on-shape one. Other nights that come out different still win on
price — they're surfaced as a self-check note, never silently. **Airline
rules:** NOTHING excluded — "US-Bangla prices are unbeatable" — the CHEAPEST
wins. THAI / Singapore Airlines are a soft preference: when the winner isn't
THAI/SQ but such an option exists, its upgrade price surfaces as `alt_note`.
`_is_preferred` requires EVERY carrier in a multi-airline string to be THAI/SQ
(substring matching once paid +$1,328 for a half-Malaysia-Airlines ticket;
"Thai Lion Air"/"Thai AirAsia"/"Thai Vietjet" are NOT THAI).

**RETIRED 2026-07-25 — do not resurrect without asking.** The direct open-jaw, the
three-one-ways combo, the Istanbul-only and Singapore-only variants, and the TK
30h-stopover trip are no longer scraped, tracked, charted or Telegrammed
("i only need the main trip … not the others"). **RETIRED 2026-08-01:** every
DPS/Bali search and path — `ISTANBUL2_SEARCH` (the DPS-return Ticket ①),
`BALI_LEGS`, `SG_TICKET_SEARCHES`, `scrape_sg_ticket`, and the Bali-era combo
pair `main_trip_bali`/`budget_trip_bali`. All retired configs
(`OPENJAW_SEARCHES`, `STOPOVER_SEARCH`, `ISTANBUL3_SEARCH`, the Bali set) and
their combo functions (`best_structures`, `best_combos`, `best_singapore`,
`cheapest_by_leg`) still work and are still tested — re-adding one is a
two-line change in `scrape_tickets_all()` / `LEGS`. Their historical numbers
stay in `site/data.json` and in the Sheet's columns; nothing is rewritten
backwards. Specs: `docs/superpowers/specs/2026-07-18-singapore-detour-variant-design.md`
(the trip's evolution), `2026-08-01-bangkok-singapore-swap-design.md` (the swap).

Redesigned 2026-07-15 from the original round-trip BOS⇄DAC/BKK watcher; design spec:
`docs/superpowers/specs/2026-07-15-three-leg-trip-redesign-design.md`.

## 2. Architecture / data flow

```
launchd 12:00am + 2:00am retry slot (com.jalal.dhaka-flights.plist, parallel with com.jalal.carmax — isolated browse sessions; retry no-ops after success via .last_run_date; run_daily.sh Telegrams on a crash exit AND refuses to START after 5:30 AM — user awake/working — so wake-replays of missed slots skip for the day) → run_daily.sh → run_daily.py
  scraper.py   scrape_tickets_all()    Ticket ① — 2 multi-city searches (one per
                                       order: …+ SIN→BOS and …+ BKK→BOS Feb 6),
                                       up to TICKET1_ATTEMPTS=3 tries each
                                       (nothing else can substitute, so they run
                                       FIRST and retry hardest), no airline filter
               scrape_sg_tickets_all() Ticket ② as one ticket — 10 multi-city
                                       searches (TICKET2_SEARCHES, order-tagged:
                                       6 DAC→SIN→BKK + 4 DAC→BKK→SIN; SEPARATE
                                       list; the open-jaw pairing loop would
                                       mis-handle them)
               scrape_all()            Ticket ② as two one-ways — 18 searches
                                       (LEGS: DAC→SIN + DAC→BKK Jan 27–Feb 1,
                                       SIN→BKK Jan 31–Feb 2, BKK→SIN Feb 2–4)
        │  drives real Chrome via the `browse` CLI (a11y-tree snapshots)
        ▼
  combo.py     ORDERS             the two city orders: route pair + Ticket ①
                                   ret_city + which city holds the 5-night block
               order_trip()        best complete trip for ONE order
               main_trip()         cheaper valid order wins; loser rides along as
                                   `other_order` (slim dict + Δ) — never hidden
               ticket1_options()   same-dates-AND-same-return alternatives to ①
               ticket2_options()   same-dates alternatives to ②, within the
                                   winning order ('1 ticket'/'2 tickets', deduped)
               best_structures/best_combos/best_singapore/cheapest_by_leg/
               main_trip_bali/budget_trip_bali — retired from the nightly path,
                                   kept working + tested
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
  which vary by carrier *and* route (US-Bangla: 40 kg DAC→SIN but 30 kg
  DAC→BKK, 20 kg to Doha).
- **CARRIERS key order matters**: `_carrier_key` is first-substring-match in
  insertion order, so "thai lion"/"thai vietjet"/"thai airasia" MUST stay
  ABOVE "thai" — otherwise the Thai LCCs inherit THAI Airways' full-service
  allowance (caught 2026-08-01 while adding the BKK routes).
- A multi-city ticket's **second leg carrier is unknown to us** — Google names
  only the first leg. `annotate()` says "not shown on this ticket" rather than
  guessing; don't "fix" that by assuming the first carrier flies both legs.
- Multi-airline strings ("US-Bangla + Jetstar") get a `summary` naming BOTH
  allowances — the cheap half often includes no free bag at all.
- When a carrier's policy changes, edit `CARRIERS` and bump `CHECKED`.

## 4d. Buy-signal layer (`alerts.py`, added 2026-07-25)

The rule, agreed with Jalal explicitly: **before the book-by date price
decides; after it, the date decides.** Three stages keyed off two knobs at the
top of `alerts.py` (`BUY_BELOW = 4500`, `BOOK_BY = Sep 20 2026`,
`WINDOW_OPENS = Sep 1`). `TRIP_TRACKED_SINCE = 2026-08-01` — the Bangkok-era
epoch; Bali-era totals are a different trip and never pollute rank/low context
(`BUY_BELOW` kept at $4,500 through the swap until real BKK numbers arrive):

- **watch** (→ Sep 1): message stays quiet; a context line always shows rank +
  distance-to-low. Alerts only on 🔥 new all-time low (trip or Ticket ① alone)
  or 🚨 buy zone (≤ $4,500).
- **window** (Sep 1–20): + countdown line; buy-zone hit leads 🚨 BOOK NOW.
- **past** (after Sep 20): every message leads 🚨 book-this-week and the price
  threshold RETIRES — don't re-add it, that's the point.

Also here: `changes_since()` — the diff vs yesterday's entry (ticket airlines,
Ticket ② composition 1-ticket ⇄ 2-one-ways + dates, ≥$50 per-ticket moves,
nights drift) with a 🧳⚠️ suffix when the change alters baggage rules. Rank /
low comparisons only use entries from `TRIP_TRACKED_SINCE` (2026-07-18) — the
earlier open-jaw-era totals are a different trip and must not pollute the low.
Everything lands in the payload (`alerts`, `price_context`, `countdown`,
`changes`) so Telegram and the site render the same facts;
`notify_telegram.build_message(payload)` takes the whole payload for that
reason.

## 5. Gotchas / hard rules

1. **Google shows the TOTAL price for all selected passengers** (verified 2026-07-15:
   1-pax $367 vs 3-pax $1,099). `price_total` = whole family. Never label it per person.
2. **Wedged browse daemon** ⇒ every command times out, then silent `about:blank`
   trees with exit 0 ⇒ fake 0-result runs. Hardening lives in `_run()` (timeout →
   `DIAG`), blank-page bail, per-route retry, 4-dead-routes abort, and the Telegram
   alert distinguishes LOCAL browser failure from a real 0-result day.
   Debug a 0-day via `cron.log` + `debug_last_zero.txt`.
3. Airport pickers must have an AIRPORT_PICK entry — the bare-code fallback substring-matches random tree lines ("IST" hit "listitem") and derails the form. BKK TYPES "Bangkok" (`TYPE_AS`) and picks the `option: Bangkok, Thailand` CITY line — typing the code offers ONLY Suvarnabhumi (live-checked 2026-08-01), which would hide Don-Mueang LCC fares (Thai AirAsia/Lion); the `option:` prefix keeps the keyword off the input box's own value line and off "Bangkok Yai, Thailand". **Multi-city result lines say "From X US dollars total."**; one-way lines say just
   "From X US dollars." — `_parse_results` accepts both. Flight details on the
   multi-city selection page describe the FIRST leg; the price includes its cheapest
   completion. Only ~top-10 fares show inline — the scraper clicks "View more flights".
4. **The trip must NEVER be dropped silently** (2026-07-16: the exact-5-night
   pairing rule hid a valid $3.4k open-jaw from the daily message). When no
   5-night Bangkok pairing exists, 4/6 nights are used and `flag` is set (shown
   verbatim in Telegram + site badges); a day with only <2 Singapore nights is
   likewise kept but flagged; off-target Istanbul nights become a
   self-check note. The parser keeps the CHEAPEST `MAX_RESULTS` fares, not the
   first in page order. `sanity.py` warns loudly when Ticket ① prices but no
   trip builds, and when one ORDER's Ticket ① variant comes back empty (the
   "cheaper order" claim is hollow when only one order priced).
5. **Trip rules live in combo.py** (`MAX_DHAKA_DAYS=29` counting both end days,
   `IDEAL_BKK_NIGHTS=5`, `HOME_DEADLINE=Feb 7`, `ORDERS` for the two city
   orders). Open-jaw "home" date is a +1-day heuristic (return-leg arrival
   isn't parsed on the selection page).
6. **publish.py must never crash the run** — it swallows all exceptions. History is
   append-only inside `site/data.json`, keyed by ISO date (same-day reruns overwrite
   that day's entry).
7. The launchd job often fires twice; `.last_run_date` (written only on success)
   makes the duplicate skip. Machine stays awake via a long-running `caffeinate`.
8. Booking insight (2026-07-15): the open-jaw ticket was ~$1.7k cheaper than
   separate one-ways ($3.4k vs $5.1k for the two long legs). Thailand + Singapore
   are visa-free for US passports; both want an online arrival card ≤3 days out
   (TDAC / SG Arrival Card). The old Indonesia e-VOA onward-proof constraint died
   with Bali.

## 6. Known issues / TODO

- `main_flyai.py` / `scraper_flyai.py` are dead legacy (flyai experiment) — ignore.
- `cron.log`, `debug_last_zero.txt`, `.DS_Store` are untracked local artifacts.
- Ticket ① is fixed to BOS→IST Jan 4 / IST→DAC Jan 7 / {SIN|BKK}→BOS Feb 6.
  Other outbound or return dates would change the trip's shape, so they're a
  product decision, not a config tweak — ask before adding.
- **Killed-run gotcha (2026-07-18):** a full run is ~25 min again (back to 30
  searches with the 2026-08-01 both-orders rework; it was ~14 min at 17). Never
  run it inside a harness/tool with a ≤10-min timeout — it gets SIGKILLed
  mid-scrape (no stamp written, no output flushed with buffered stdout). Manual
  runs: `nohup … python3 -u run_daily.py > log 2>&1 &` and watch the log. The
  launchd job has no timeout and is unaffected.

## 7. File map

- `run_daily.sh` / `run_daily.py` — launchd entrypoint; stamp + DIAG alerting
- `sanity.py` — self-check watchdog run before every send: Ticket ① must price
  (per order variant too), a priced Ticket ① must produce a trip, every
  leg×date and Ticket ② order+date pair must have fares, yesterday's totals
  must not silently vanish, >25% swings, parser drift, and trip-shape drift
  (2 IST / 2 SIN / 5 BKK nights) all get flagged. Violations ride along to
  Telegram ("🧪 Self-check") and the site's amber banner. When adding a tracked
  search, add its invariant here too.
- `scraper.py` — browse-CLI form driving + parsing (one-way & multi-city); LEGS,
  STOPOVER_SEARCHES (2 Ticket ① variants), TICKET2_SEARCHES + ORDER_ROUTES
  (+ retired configs, kept)
- `combo.py` — trip rules, `ORDERS`, `order_trip`, `main_trip`, `budget_trip`,
  `ticket1_options`, `ticket2_options` (+ retired `best_structures` /
  `best_combos` / `best_singapore` / `cheapest_by_leg` / `*_bali`)
- `baggage.py` — sourced per-carrier allowance table; `annotate`, `warnings` (§4c)
- `alerts.py` — buy-signal stages, price context, countdown, change diff (§4d)
- `publish.py` — `build_today` → payload → `write_payload` (backup, write, push)
- `sheet_writer.py`, `notify_telegram.py` — outputs
- `site/` — static dashboard (index.html) + data.json (machine-written)
- `main.py` — manual run: scrape + sheet + terminal summary (no Telegram/publish)
- `tests/` — pytest suite (129 tests; `test_main_trip.py` holds the shared trip
  fixtures, `test_baggage.py` guards the allowance table's honesty)
