# Bangkok + Singapore swap (Bali retired) — design

**Date:** 2026-08-01 · **Approved by:** Jalal (in session, 2026-08-01)

## Why

Jalal is dropping Bali from the Jan/Feb 2027 trip — "I don't like the tail risk of
dengue." The 5 Marriott award nights (5th-night-free) move to **Bangkok**; Singapore
stays. Order of BKK vs SIN is explicitly "whatever is cheaper."

## New trip definition

> **BOS → Istanbul (2 nights) → Dhaka (≤29 days; 30-day visa) → Bangkok (5 nights;
> Marriott) + Singapore (2 nights), order decided by price → BOS, home by Feb 7, 2027.**
> 2 adults + 1 child with seat.

Total nights after Dhaka remain 7 (was SIN 2 + Bali 5), so the existing date grid and
Ticket-① anchor dates (BOS→IST Jan 4, IST→DAC Jan 7, last-city→BOS Feb 6) carry over.

Still **two purchases**:

| | Order A (BKK first) | Order B (SIN first) |
|---|---|---|
| **Ticket ①** | BOS→IST Jan 4 + IST→DAC Jan 7 + **SIN→BOS Feb 6** | BOS→IST Jan 4 + IST→DAC Jan 7 + **BKK→BOS Feb 6** |
| **Ticket ②** | DAC→BKK→SIN (1 ticket or 2 one-ways) | DAC→SIN→BKK (1 ticket or 2 one-ways) |

**Both orders are scraped every night; the cheaper complete trip (①+②) headlines,
the other order surfaces as an alternative with its Δ.** This was the approved choice
over scout-once-and-fix — prices flip week to week and the user booked "whatever is
cheaper."

## Rules carried over unchanged

- 2 Istanbul nights, Dhaka ≤29 days counting both end days, home ≤ Feb 7.
- **5 Bangkok nights ideal** (replaces 5 Bali nights — Marriott 5th-night-free);
  4/6-night pairings survive as flagged fallback, never dropped silently.
- **MINIMUM 2 Singapore nights** (`MIN_SG_NIGHTS = 2`): a ≥2-night SIN stay always
  outranks a shorter one; price decides only within a tier; a <2-night day survives
  only flagged.
- Airline rules: NOTHING excluded, cheapest wins; THAI/SQ soft preference via
  `alt_note` (every carrier in a multi-airline string must match).
- 💸 Budget companion: cheapest same trip with min-2-SIN waived (≥1 night) and Dhaka
  departure free to shift; shown only when strictly cheaper than main. Now searches
  across both orders.
- The trip must NEVER be dropped silently; publish must never crash the run;
  history is append-only everywhere.

## Code changes

- **scraper.py** — config swap: LEGS becomes {DAC→BKK, DAC→SIN (kept), BKK→SIN,
  SIN→BKK} over the Jan 27–Feb 1 departure grid + connecting dates; two Ticket-①
  multi-city searches (kind `stopover2`, per-order return city, both retry-hard);
  Ticket-② multi-city searches for both orders (separate lists, as today).
  DPS legs/searches RETIRE (configs + combo fns kept and tested, per §1 house rule).
  BKK airport-picker entry added to AIRPORT_PICK.
- **combo.py** — `IDEAL_BALI_NIGHTS` → `IDEAL_BKK_NIGHTS = 5` (retired name kept as
  alias for old tests); `main_trip()` builds both orders and picks the cheaper;
  per-order alternatives in `ticket1_options()` / `ticket2_options()`; the losing
  order is emitted as a first-class alternative with Δ; `budget_trip()` spans both
  orders.
- **baggage.py** — add/verify BKK-route carriers: THAI (weight, DAC→BKK), US-Bangla
  DAC→BKK allowance, AirAsia/Thai AirAsia (paid bags), Thai Vietjet, plus BKK⇄SIN
  carriers (Scoot, Jetstar, SQ, THAI). Same honesty rules (sourced URL + confidence,
  checkout page is the authority).
- **alerts.py** — `TRIP_TRACKED_SINCE = 2026-08-01` (Bali-era totals are a different
  trip; they must not pollute rank/new-low context). `BUY_BELOW` stays $4,500 until
  the first real run, then recalibrate deliberately. Sep 1 / Sep 20 window unchanged.
- **sanity.py** — invariants extended: BOTH Ticket-① variants must price (warn if one
  is empty), every new leg×date and both orders' ②-pairs must have fares, trip-shape
  drift check becomes 2 IST / 5 BKK + 2 SIN (any order), plus the existing
  vanish/swing/parser-drift checks.
- **sheet_writer.py / publish.py** — history keys unchanged (`main_total`,
  `ticket1_total`, `ticket2_total`, `budget_total`, `combined_total` duplicate);
  a new appended Sheet column for the winning order (e.g. "Order"); retired columns
  stay in place, written blank. data.json history remains append-only by date.
- **notify_telegram.py** — trip line shows the winning order (DAC→BKK→SIN→BOS or
  DAC→SIN→BKK→BOS); alternatives include the losing order with Δ; baggage per leg
  as today.
- **site/index.html** — timeline chips (🕌 IST → 🇧🇩 DAC → 🛕 BKK / 🇸🇬 SIN in winning
  order), alternatives tables get the losing-order row, booking playbook: Indonesia
  e-VOA onward-proof note OUT, Thailand visa-exempt (US passports) + Singapore
  visa-free notes IN. Requires one `cd site && vercel --prod --yes` redeploy.
- **tests/** — fixtures move to BKK/SIN both-order shapes; pinned search counts in
  test_scraper updated; retired DPS paths still covered via kept configs.

## Search budget

~24 searches/night (was 17): 2× Ticket ① (up to 3 attempts each, run first),
~6 Ticket-② multi-city pairs across both orders, ~16 one-way leg×dates.
Run ≈ 20 min — fine for launchd (no timeout); still never run inside a ≤10-min
tool harness (killed-run gotcha, AGENTS §6).

## Validation plan

1. Full pytest suite green.
2. Interactive one-off `scrape_route`/multi-city calls for the NEW searches
   (DAC→BKK, BKK→SIN, SIN→BKK, both Ticket-① variants) — proves parsing live and
   gives Jalal a same-day first read on which order is cheaper.
3. First full nightly run tonight (launchd 12:00/2:00/4:00 slots unchanged);
   check Telegram + dashboard in the morning.

## Out of scope here

- Bangkok Marriott property choice (separate research task, running in parallel).
- Booking anything. The Bali Notion decision table is marked superseded; The Laguna
  was never booked, so there is nothing to cancel.

## Rollback

Bali-era configs and combo functions stay in the tree (retired, tested) — reverting
is a config swap, and all Bali-era history stays in data.json / the Sheet untouched.
