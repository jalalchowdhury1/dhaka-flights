# Hotel-aware Singapore night count ("stay math") — design

**Date:** 2026-08-19 · **Status:** approved by Jalal (knob set at $225)

## Why

The SIN stay is a 2–4 night flex band, but `combo.py` picks within it by flight
price alone. Meanwhile the nightly hotel-rate job now tracks the St. Regis
Singapore at $218/night (2026-08-19) — cheap enough that Jalal asked for the
tracker to "automatically make it a 4N stay… given that the savings from the
hotel aren't offset by the flight cost completely."

Pure all-in cost minimization would almost never extend (extra nights always
add cost unless the 4N flight shape is outright cheaper), so the decision rule
carries an explicit **worth-it knob**: what one extra SIN night is worth to the
family. Derived 2026-08-19 by triangulating (a) Jalal's own ≥70% book-now
offset band → ~$170, (b) the Athenee centerpiece at ~$300/night points-value
with add-on nights priced below centerpiece → ~$200–225, (c) replacement value
$450–500 at his habitual 40–50¢-on-the-dollar → $180–250, (d) ~$120–180/day of
off-tracker incidentals capping the tracker-visible part → ~$225.
**Jalal chose $225.**

## The decision rule

For each SIN night count `n` in the band with a candidate trip tonight:

```
allin(n) = flight_total(n) + hotel_net(n)
score(n) = allin(n) − EXTRA_NIGHT_WORTH × (n − MIN_SG_NIGHTS)
```

- `hotel_net(n) = max(0, n × rate × 1.12 − credits(n))` — floored at 0
  because credits beyond the bill are not cash back.
- `credits(n)` = the FHR pool: $400/stay fixed ($300 Amex + $100 property)
  + $60/day breakfast → 2n $520, 3n $580, 4n $640 (matches
  `hotel_rates.CREDIT_POOL` where entries exist; the formula covers 3n).
- Lowest score wins. Equivalent to "keep extending while each extra night
  costs ≤ $225" when marginals are monotone; handles a missing 3N pairing
  naturally.
- **Dead-band $25:** yesterday's picked count gets a −$25 score bonus, so the
  shape only flips when the challenger clearly wins — no 4N-Monday/2N-Tuesday
  whiplash from volatile Jan-28 flex fares.

Worked example (2026-08-19 fares, St. Regis $218): flights 2N $4,614 /
3N $4,660 / 4N $4,660 → hotel net $0/$152/$337 → allin $4,614/$4,812/$4,997 →
scores $4,614/$4,587/$4,547 → **4N picked** ($67 clear of 2N).

Knobs `EXTRA_NIGHT_WORTH = 225` and `DEAD_BAND = 25` live at the top of the
new module, like `alerts.BUY_BELOW`.

## Hotel input

- The **bold SIN row** of `hotel_rates.json` drives the math (St. Regis today;
  `bold` is the curated play in `hotel_rates.SHORTLIST` — re-bolding a row
  switches the decision hotel with no logic change).
- Every surface carries the assumption line: hotel, rate, checked date, FHR
  credit set, and the approximation that a longer stay reuses the tracked
  2N-window nightly rate (the 4N window starts 2 days earlier; scraping it
  separately would cost Browserbase minutes the quota doesn't have).
- **Watchdog:** if another SIN shortlist row beats the bold pick by
  >$50/night net at the picked count, a note says so — the frozen curation
  can never go stale silently.

## Safety rails (mode ladder)

`stay_value` runs in one of three modes, surfaced in the payload:

1. **steering** — bold rate `checked` ≤ 3 days old: the hook changes the pick.
2. **advisory** — rate older than 3 days (the hotel job fail-closes: quota
   exhaustion, throttling, stand-downs — a 5-night outage happened 08-11):
   the table still renders with a ⚠️, but the pick stays flight-only. A stale
   rate must not steer the trip.
3. **off** — `hotel_rates.json` missing/unreadable or no bold SIN row:
   behavior identical to today, one warning line.

## Where it lives

- **`stay_value.py` (new)** — pure logic, no scraping, no new searches. Reads
  `site/hotel_rates.json`, exposes:
  - `hotel_hook(yesterday_n)` → `f(n) = hotel_net(n) − 225×(n−2) − (25 if
    n == yesterday_n else 0)`, or `None` when not steering;
  - `build(payload-ish inputs)` → the `stay_value` payload dict (mode, knob,
    dead-band, hotel {key,name,rate,checked}, per-n rows {n, flights,
    hotel_net, allin, score}, picked_n, incumbent_n, watchdog, assumption).
- **`combo.py`** — `order_trip()` and `main_trip()` accept an optional
  `hotel_cost` hook. When present, in-band candidates rank by
  `flight_cost + hotel_cost(sg_nights)`; cross-order winner sort becomes
  `(not valid, flight_total + hotel_cost(n))` so both orders are judged on the
  same all-in basis. Everything else — band rules, flags, valid-beats-flagged,
  `total` = flights-only — unchanged. No hook (tests, interactive, budget
  companion, Bali benchmark) = exactly today's behavior.
- **`run_daily.py`** — wires the hook in: reads yesterday's `main.sg_nights`
  from `site/data.json` before the overwrite (the dead-band incumbent), calls
  `stay_value.build`, folds its warnings into the night's warnings.
- **`verify.py`** — RECOMPUTE independently re-derives the all-in winner from
  the raw fares + its own reading of `hotel_rates.json` + its own credit
  arithmetic (stays independent of combo.py AND stay_value.py) and must agree
  with the picked night count; ARITHMETIC re-checks allin = flights +
  hotel_net per row; CONTRACT is unchanged (2–4 SIN already in-band).
- **`sanity.py`** — new invariant: when mode is steering, the trip's
  `sg_nights` must equal `stay_value.picked_n`.
- **`schema_check.py` + site `validatePayload()`** — both learn the optional
  `stay_value` key (the mirror rule).

## Surfaces

- **Telegram** — one 🛏️ block after the hotel plan:
  `🛏️ Stay math: 2N $4,614 · 3N $4,812 · 4N $4,997 → 4N picked
  (worth-it $225/n · St. Regis $218/n ✓8/19)` — plus the watchdog line and a
  ⚠️ advisory/off note when degraded.
- **Site** — #/stays gets the table as a card (offset-% convention +
  assumption line, per the 2026-08-02 standard); Tonight shows a chip when
  picked_n > 2 ("4N SIN · hotel math"); #/history table rows already carry
  sg_nights.
- **History / Sheet** — history `total` stays flights-only (chart and
  buy-signal thresholds unpolluted). The day's history entry gains
  `sg_allin` (picked n + allin total); the Sheet History tab gains one
  APPENDED column "🛏️ SIN all-in" (append-only rule). `alerts.changes_since`
  already reports night-count drift; it learns to tag a flip "(hotel math)".

## Testing (pure pytest, no browser)

- credit math per n incl. the $0 floor and missing-(SIN,3) formula case;
- score/dead-band: flips only past $25, sticks otherwise; missing-3N jump;
- mode ladder: fresh→steering, stale→advisory (pick unchanged), missing→off;
- combo hook: changes the in-band pick only when it should; cross-order
  all-in sort; hookless behavior byte-identical to today (existing fixtures);
- verify agreement + a deliberate-mismatch case that must flag;
- watchdog trigger at >$50/night;
- schema: payload with and without `stay_value` validates.

## Out of scope (deliberate)

- No new scraping (25-min cap, Browserbase quota untouched).
- IST nights (fixed 2) and BKK (5N award, 5th-night-free) — no decision there.
- Buy-signal thresholds, Bali benchmark, budget companion — untouched.
