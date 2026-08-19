# Hotel-Aware SIN Night Count ("Stay Math") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The nightly tracker picks the Singapore night count (2–4 band) by all-in cost — flights + net St. Regis out-of-pocket after card credits — with a $225/extra-night worth-it knob, instead of flight price alone.

**Architecture:** A new pure-logic module `stay_value.py` reads `site/hotel_rates.json` (already refreshed nightly by its own 5am job) and produces (a) a `hotel_cost` hook that `combo.order_trip`/`main_trip` optionally accept to re-rank in-band candidates, and (b) a `stay_value` payload block for Telegram/site/history. `verify.py` re-derives the pick independently. History `total` stays flights-only. Mode ladder: steering (fresh rate) → advisory (stale >3d) → off (no data).

**Tech Stack:** Python 3 (no new deps), pytest, vanilla-JS single-file dashboard (`site/index.html`).

**Spec:** `docs/superpowers/specs/2026-08-19-hotel-aware-sin-nights-design.md`

**Repo cautions (read before starting):**
- Work directly on `main` (Jalal's convention), but **every commit must leave `python3 -m pytest tests/ -q` green** — the midnight flight run and 5am hotel run execute from this working tree. Finish (or leave green) well before midnight.
- Do NOT run `./run_daily.sh` or any scraper during implementation (same-day rescrape caution, AGENTS §4b.3b). Tests are pure logic.
- One deviation from the spec, decided at planning: the "picked matches stay_value winner" invariant lives in `stay_value.build` (which emits a `warning` that publish folds into payload warnings) rather than `sanity.py` — the two values only coexist inside publish. verify.py still checks it independently (Task 8), so the invariant is enforced twice as the spec intended.

**Worked numbers used throughout tests** (St. Regis $218/n, FHR credits $400/stay + $60/day, 12% tax):
- `hotel_net(218, 2)` = max(0, 488.32 − 520) = **0**
- `hotel_net(218, 3)` = round(732.48 − 580) = **152**
- `hotel_net(218, 4)` = round(976.64 − 640) = **337**
- score adjustments (no incumbent): f(2)=0, f(3)=152−225=**−73**, f(4)=337−450=**−113**

(Note: f(3) = 152 − 225 = −73, not −72 — compute, don't copy.)

---

### Task 1: `stay_value.py` — core math (credits, net, bold row, mode)

**Files:**
- Create: `stay_value.py`
- Create: `tests/test_stay_value.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stay_value.py`:

```python
"""Tests for the hotel-aware SIN night-count layer (stay math, 2026-08-19).
Spec: docs/superpowers/specs/2026-08-19-hotel-aware-sin-nights-design.md"""
import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stay_value

TODAY = datetime.date(2026, 8, 19)

RATES = {
    "updated": "2026-08-19",
    "rows": [
        {"key": "ritz_ist", "city": "IST", "name": "Ritz-Carlton Istanbul",
         "program": "FHR", "bold": True, "rate": 439, "checked": "2026-08-19"},
        {"key": "stregis_sin", "city": "SIN", "name": "St. Regis Singapore",
         "program": "FHR", "bold": True, "rate": 218, "checked": "2026-08-19"},
        {"key": "panpacific", "city": "SIN", "name": "Pan Pacific Orchard",
         "program": "THC + Edit", "bold": False, "rate": 255,
         "checked": "2026-08-19"},
    ],
}


def test_credits_scale_with_nights():
    assert stay_value.credits(2) == 520          # $400/stay + $60×2
    assert stay_value.credits(3) == 580
    assert stay_value.credits(4) == 640


def test_edit_only_programs_get_the_smaller_fixed_credit():
    assert stay_value.credits(2, "The Edit only") == 470   # $350 + $120
    assert stay_value.credits(2, "THC + Edit") == 470
    assert stay_value.credits(2, "FHR") == 520


def test_hotel_net_floors_at_zero():
    # 2×218×1.12 = 488.32 < $520 credits — credits beyond the bill are NOT cash back
    assert stay_value.hotel_net(218, 2) == 0


def test_hotel_net_at_three_and_four():
    assert stay_value.hotel_net(218, 3) == 152
    assert stay_value.hotel_net(218, 4) == 337


def test_bold_row_finds_the_sin_play_not_the_ist_one():
    row = stay_value.bold_row(RATES)
    assert row["key"] == "stregis_sin"


def test_bold_row_none_when_rate_missing():
    r = {"rows": [{"key": "x", "city": "SIN", "bold": True, "rate": None}]}
    assert stay_value.bold_row(r) is None
    assert stay_value.bold_row(None) is None
    assert stay_value.bold_row({}) is None


def test_mode_ladder():
    assert stay_value.mode(RATES, TODAY) == "steering"          # checked today
    assert stay_value.mode(RATES, datetime.date(2026, 8, 22)) == "steering"  # 3d = limit
    assert stay_value.mode(RATES, datetime.date(2026, 8, 23)) == "advisory"  # 4d = stale
    assert stay_value.mode(None, TODAY) == "off"
    assert stay_value.mode({"rows": []}, TODAY) == "off"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights" && python3 -m pytest tests/test_stay_value.py -q`
Expected: FAIL / error — `ModuleNotFoundError: No module named 'stay_value'`

- [ ] **Step 3: Write the implementation**

Create `stay_value.py`:

```python
"""Hotel-aware Singapore night-count layer ("stay math", 2026-08-19).

The SIN stay is a 2-4 night flex band; combo.py historically picked within it
by flight price alone. This module prices the whole choice — flights + what
the curated hotel play actually costs out of pocket (rate + ~12% tax − card
credits) — and values each extra Singapore night at EXTRA_NIGHT_WORTH
(derived 2026-08-19 from Jalal's own ≥70% book-now band, the Athenee
points-value, and replacement cost; he chose $225).

    score(n) = allin(n) − EXTRA_NIGHT_WORTH × (n − MIN_N)     lowest wins
    allin(n) = flights(n) + hotel_net(n)
    hotel_net(n) = max(0, n·rate·(1+TAX) − credits(n))        never cash back

Mode ladder — a stale rate must never steer the trip (the hotel job
fail-closes and has gone 5 nights dark before, 2026-08-11):
    steering   bold-SIN rate checked ≤ STALE_DAYS ago → hook reshapes the pick
    advisory   rate older → the table renders, the pick stays flight-only
    off        hotel_rates.json missing / no usable bold SIN row

The knobs live here like alerts.BUY_BELOW lives in alerts.py. verify.py
re-implements this math independently (own constants, own argmin) — keep it
that way; that's the point of verify.
"""
import datetime
import json
import os

EXTRA_NIGHT_WORTH = 225   # $ one extra SIN night is worth (Jalal, 2026-08-19)
DEAD_BAND = 25            # challenger must beat the incumbent shape by this
STALE_DAYS = 3            # bold rate older than this → advisory, not steering
WATCHDOG_GAP = 50         # $/night a rival must beat the bold pick by to bark
TAX_RATE = 0.12           # hotel_rates.py's long-standing offset assumption
FHR_FIXED = 400           # $300 Amex FHR + $100 property, per stay
EDIT_FIXED = 350          # $250 Edit + $100 property — non-FHR programs
DAILY_CREDIT = 60         # breakfast credit per day
MIN_N = 2                 # mirrors combo.MIN_SG_NIGHTS — the score baseline

RATES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "site", "hotel_rates.json")


def load_rates(path=RATES_FILE):
    """Parsed hotel_rates.json, or None (missing/corrupt = mode 'off')."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def bold_row(rates, city="SIN"):
    """The curated play — the bold row for the city, rate present. The bold
    flag is hand-set in hotel_rates.SHORTLIST (2026-08-01 research); re-bolding
    a row switches the decision hotel with no logic change here."""
    for r in (rates or {}).get("rows", []):
        if (r.get("city") == city and r.get("bold")
                and isinstance(r.get("rate"), (int, float))):
            return r
    return None


def fixed_credits(program):
    """FHR-bookable stays get the $300 Amex; Edit/THC-only get $250 Edit."""
    return FHR_FIXED if "FHR" in (program or "") else EDIT_FIXED


def credits(n, program="FHR"):
    return fixed_credits(program) + DAILY_CREDIT * n


def hotel_net(rate, n, program="FHR"):
    """Out-of-pocket for n nights after credits, floored at 0 — credits
    beyond the bill are not cash back."""
    return max(0, round(n * rate * (1 + TAX_RATE) - credits(n, program)))


def _age_days(row, today):
    try:
        return (today - datetime.date.fromisoformat(row.get("checked", ""))).days
    except (ValueError, TypeError):
        return None


def mode(rates, today):
    row = bold_row(rates)
    if row is None:
        return "off"
    age = _age_days(row, today)
    if age is None or age > STALE_DAYS:
        return "advisory"
    return "steering"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_stay_value.py -q`
Expected: all PASS

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q     # must stay green (242 + new)
git add stay_value.py tests/test_stay_value.py
git commit -m "feat: stay_value core — credits/net/bold-row/mode ladder"
```

---

### Task 2: `stay_value.hotel_hook` — the score adjuster with dead-band

**Files:**
- Modify: `stay_value.py` (append after `mode`)
- Modify: `tests/test_stay_value.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_stay_value.py`)

```python
def test_score_adjust_values_extra_nights_at_the_knob():
    # f(n) = net − 225×(n−2) − dead-band bonus
    assert stay_value.score_adjust(218, 2, None) == 0
    assert stay_value.score_adjust(218, 3, None) == 152 - 225      # −73
    assert stay_value.score_adjust(218, 4, None) == 337 - 450      # −113


def test_score_adjust_gives_the_incumbent_the_dead_band():
    assert stay_value.score_adjust(218, 2, 2) == -25
    assert stay_value.score_adjust(218, 4, 2) == -113              # not incumbent


def test_hook_none_unless_steering():
    assert stay_value.hotel_hook(None, None, today=TODAY) is None
    stale = {"rows": [dict(RATES["rows"][1], checked="2026-08-10")]}
    assert stay_value.hotel_hook(stale, None, today=TODAY) is None


def test_hook_returns_the_adjuster_when_fresh():
    h = stay_value.hotel_hook(RATES, None, today=TODAY)
    assert h(2) == 0 and h(3) == -73 and h(4) == -113
    h2 = stay_value.hotel_hook(RATES, 2, today=TODAY)
    assert h2(2) == -25
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_stay_value.py -q`
Expected: FAIL — `AttributeError: ... no attribute 'score_adjust'`

- [ ] **Step 3: Implement** (append to `stay_value.py`)

```python
def score_adjust(rate, n, incumbent_n, program="FHR"):
    """What the combo hook adds to a candidate's flight cost: its net hotel
    bill, minus the value of its extra nights, minus the incumbent shape's
    dead-band bonus (so the pick only flips when the challenger clearly
    wins — no 4N-Monday/2N-Tuesday whiplash from volatile flex fares)."""
    return (hotel_net(rate, n, program)
            - EXTRA_NIGHT_WORTH * (n - MIN_N)
            - (DEAD_BAND if n == incumbent_n else 0))


def hotel_hook(rates, incumbent_n, today=None):
    """combo.py's optional hotel_cost hook: f(sin_nights) → $ adjustment,
    or None unless mode is steering. combo adds f(n) to each candidate's
    flight cost, so the in-band winner minimizes
    flights + net_hotel − WORTH×extra_nights (− dead-band on the incumbent)."""
    today = today or datetime.date.today()
    if mode(rates, today) != "steering":
        return None
    row = bold_row(rates)
    rate, program = row["rate"], row.get("program", "FHR")
    return lambda n: score_adjust(rate, n, incumbent_n, program)
```

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_stay_value.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add stay_value.py tests/test_stay_value.py
git commit -m "feat: stay_value hotel_hook — knob + dead-band score adjuster"
```

---

### Task 3: `stay_value.build` — the payload block (rows, watchdog, warning)

**Files:**
- Modify: `stay_value.py` (append)
- Modify: `tests/test_stay_value.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
TOTALS = {2: 4614, 3: 4660, 4: 4660}    # tonight's real 2026-08-19 flight totals


def test_build_rows_and_pick():
    sv = stay_value.build(RATES, TOTALS, None, 4, today=TODAY)
    assert sv["mode"] == "steering"
    assert [r["n"] for r in sv["rows"]] == [2, 3, 4]
    assert [r["allin"] for r in sv["rows"]] == [4614, 4812, 4997]
    assert [r["score"] for r in sv["rows"]] == [4614, 4587, 4547]
    assert sv["picked_n"] == 4
    assert sv["trip_n"] == 4 and sv["warning"] is None
    assert sv["trip_allin"] == 4997
    assert sv["hotel"]["key"] == "stregis_sin" and sv["knob"] == 225
    assert "St. Regis" in sv["assumption"] and "218" in sv["assumption"]


def test_build_warns_when_trip_ignored_the_math():
    sv = stay_value.build(RATES, TOTALS, None, 2, today=TODAY)
    assert sv["picked_n"] == 4 and sv["trip_n"] == 2
    assert "hook was not applied" in sv["warning"]


def test_build_advisory_never_warns_and_says_why():
    stale = {"rows": [dict(RATES["rows"][1], checked="2026-08-14")]}
    sv = stay_value.build(stale, TOTALS, None, 2, today=TODAY)
    assert sv["mode"] == "advisory"
    assert sv["warning"] is None
    assert "days old" in sv["note"]


def test_build_off_mode_degrades_cleanly():
    sv = stay_value.build(None, TOTALS, None, 2, today=TODAY)
    assert sv["mode"] == "off" and sv["rows"] == [] and sv["picked_n"] is None
    assert sv["trip_allin"] is None


def test_watchdog_barks_when_a_rival_beats_the_bold_pick():
    rival = dict(RATES, rows=RATES["rows"] + [
        {"key": "cheap", "city": "SIN", "name": "Cheap Palace",
         "program": "FHR", "bold": False, "rate": 100, "checked": "2026-08-19"}])
    sv = stay_value.build(rival, TOTALS, None, 4, today=TODAY)
    # bold net at 4N = 337 → $84/n; Cheap Palace: 4×100×1.12−640 → 0 → $0/n
    assert sv["watchdog"] is not None and "Cheap Palace" in sv["watchdog"]
    # Pan Pacific at $255 does NOT trigger (it nets MORE than the bold pick)
    sv2 = stay_value.build(RATES, TOTALS, None, 4, today=TODAY)
    assert sv2["watchdog"] is None
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_stay_value.py -q` → FAIL (`no attribute 'build'`)

- [ ] **Step 3: Implement** (append to `stay_value.py`)

```python
def _watchdog(rates, row, n):
    """A non-bold SIN hotel netting >WATCHDOG_GAP/night less than the play
    can't stay silent — the bold flag is frozen human curation (2026-08-01)
    and the rates under it move nightly."""
    bold_pn = hotel_net(row["rate"], n, row.get("program", "FHR")) / n
    best = None
    for r in (rates or {}).get("rows", []):
        if (r.get("city") != "SIN" or r.get("bold")
                or not isinstance(r.get("rate"), (int, float))):
            continue
        pn = hotel_net(r["rate"], n, r.get("program", "")) / n
        if bold_pn - pn > WATCHDOG_GAP and (best is None or pn < best[1]):
            best = (r, pn)
    if not best:
        return None
    r, pn = best
    return (f"{r['name']} nets ~${bold_pn - pn:,.0f}/night less than "
            f"{row['name']} at {n}N — consider re-bolding the play")


def build(rates, flight_totals, incumbent_n, trip_n, today=None):
    """The `stay_value` payload block. Pure logic; must never raise into the
    run. flight_totals = {sin_nights: flight total} for the winning order
    (combo.sin_night_flight_totals); trip_n = the sg_nights the trip chose."""
    today = today or datetime.date.today()
    m = mode(rates, today)
    base = {"mode": m, "knob": EXTRA_NIGHT_WORTH, "dead_band": DEAD_BAND,
            "incumbent_n": incumbent_n, "trip_n": trip_n}
    if m == "off":
        return dict(base, hotel=None, rows=[], picked_n=None, trip_allin=None,
                    watchdog=None, warning=None, assumption=None,
                    note=("no usable bold SIN rate in hotel_rates.json — "
                          "the night-count pick stayed flight-only"))
    row = bold_row(rates)
    program = row.get("program", "FHR")
    rows = []
    for n in sorted(k for k in (flight_totals or {}) if isinstance(k, int)):
        fl = flight_totals[n]
        net = hotel_net(row["rate"], n, program)
        rows.append({"n": n, "flights": fl, "hotel_net": net, "allin": fl + net,
                     "score": fl + score_adjust(row["rate"], n, incumbent_n,
                                                program)})
    picked = min(rows, key=lambda r: r["score"])["n"] if rows else None
    trip_row = next((r for r in rows if r["n"] == trip_n), None)
    warning = None
    if (m == "steering" and picked is not None and trip_n is not None
            and picked != trip_n):
        warning = (f"stay math picked {picked}N SIN but the trip built with "
                   f"{trip_n}N — the hotel hook was not applied; check "
                   f"run_daily wiring")
    note = None
    if m == "advisory":
        note = (f"{row['name']} rate is {_age_days(row, today)} days old — "
                f"advisory only, the pick stayed flight-only tonight")
    return dict(
        base,
        hotel={"key": row.get("key"), "name": row.get("name"),
               "rate": row["rate"], "checked": row.get("checked"),
               "program": program},
        rows=rows, picked_n=picked,
        trip_allin=trip_row["allin"] if trip_row else None,
        watchdog=_watchdog(rates, row, trip_n if trip_row else MIN_N),
        warning=warning, note=note,
        assumption=(f"{row['name']} ${row['rate']:,}/n (checked "
                    f"{row.get('checked')}) · credits "
                    f"${fixed_credits(program)}/stay + ${DAILY_CREDIT}/day · "
                    f"~12% tax · longer stays assume the tracked window's "
                    f"nightly rate"),
    )
```

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_stay_value.py -q` → PASS

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q
git add stay_value.py tests/test_stay_value.py
git commit -m "feat: stay_value.build — payload block with watchdog + mismatch warning"
```

---

### Task 4: `combo.py` — optional `hotel_cost` hook in `order_trip` / `main_trip`

**Files:**
- Modify: `combo.py` (`order_trip` ~line 457, `main_trip` ~line 531)
- Modify: `tests/test_main_trip.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_main_trip.py`)

```python
def test_hotel_hook_flips_the_pick_within_the_band():
    # 4N shape is $60 pricier on flights; the hook (worth-it knob) flips it.
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    tickets2 = SG_TICKETS + [four_night]
    flat = main_trip(FLIGHTS, [TICKET1], tickets2)
    assert flat["sg_nights"] == 2 and flat["total"] == 4600   # flight-only pick
    hook = lambda n: {2: 0, 3: -73, 4: -113}.get(n, 0)        # St.Regis@218 math
    t = main_trip(FLIGHTS, [TICKET1], tickets2, hotel_cost=hook)
    assert t["sg_nights"] == 4
    assert t["total"] == 3600 + 1060      # total stays FLIGHTS-ONLY — history rule


def test_hotel_hook_cannot_pull_an_out_of_band_shape_in():
    # Validity tiers run BEFORE the hook: a 5-night SIN shape stays a flagged
    # fallback even if a (buggy) hook rewards it hugely.
    five_night = dict(TICKET2, out_date="January 27, 2027",
                      out_arrive="January 27, 2027", price_total=500,
                      airline="Biman", link="http://t2long")
    hook = lambda n: -10_000 if n == 5 else 0
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS + [five_night], hotel_cost=hook)
    assert t["sg_nights"] == 2 and t["valid"] is True


def test_cross_order_winner_is_judged_all_in_too():
    # Flights-only: SIN-first 2N wins ($4,600 < $4,700). All-in with the hook:
    # BKK-first's 4N SIN shape wins (4700−113=4587 < 4600).
    dac_bkk28 = dict(_f("DAC→BKK", "January 28, 2027", "January 28, 2027", 600),
                     airline="US-Bangla Airlines", link="http://db28")
    bkk_sin2 = dict(_f("BKK→SIN", "February 2, 2027", "February 2, 2027", 300),
                    airline="Scoot", link="http://bs2")
    flights = FLIGHTS + [dac_bkk28, bkk_sin2]
    t1s = [TICKET1, TICKET1_SIN]
    flat = main_trip(flights, t1s, SG_TICKETS)
    assert flat["order"] == "SIN-first" and flat["total"] == 4600
    hook = lambda n: {2: 0, 3: -73, 4: -113}.get(n, 0)
    t = main_trip(flights, t1s, SG_TICKETS, hotel_cost=hook)
    assert t["order"] == "BKK-first"
    assert t["sg_nights"] == 4 and t["bkk_nights"] == 5
    assert t["total"] == 3800 + 900       # flights-only total of the 4N shape
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_main_trip.py -q`
Expected: FAIL — `TypeError: main_trip() got an unexpected keyword argument 'hotel_cost'`

- [ ] **Step 3: Implement**

In `combo.py`, change `order_trip`'s signature and its `min(...)` (currently `def order_trip(flights, openjaws, tickets2, order_key):` and `m, bkk_nights, sin_nights, dhaka_days = min(pool, key=lambda t: t[0]["cost"])`):

```python
def order_trip(flights, openjaws, tickets2, order_key, hotel_cost=None):
    """Best complete trip for ONE order (Ticket ① with the right return city +
    the cheapest valid middle), or None. Tier rules as agreed:
      - 5 Bangkok nights ideal; 4/6 rank below and get flagged
      - ≥2 Singapore nights always outrank fewer; <2 survives only flagged
      - nothing is dropped silently.
    hotel_cost (2026-08-19 stay math): optional f(sin_nights) → $ adjustment
    added to a candidate's flight cost when ranking WITHIN the selected pool —
    the validity tiers above still run first, and the returned `total` stays
    flights-only (history/chart rule)."""
```

and replace the selection line:

```python
    cost_key = ((lambda t: t[0]["cost"] + hotel_cost(t[2])) if hotel_cost
                else (lambda t: t[0]["cost"]))
    m, bkk_nights, sin_nights, dhaka_days = min(pool, key=cost_key)
```

(`t[2]` is `sin_nights` in the pool tuples. Leave the `alt_note` preferred-airline
comparison on raw `t[0]["cost"]` — it's a flight-price upsell note.)

In `main_trip`, change the signature and sort:

```python
def main_trip(flights, openjaws, sg_tickets, hotel_cost=None):
    """THE trip: both orders priced, the cheaper VALID one wins (a flagged day
    never outranks a clean one). The losing order rides along as
    `other_order` (slim dict with its Δ) so it's surfaced, never hidden.
    With hotel_cost, both the within-band pick and the cross-order comparison
    are judged all-in (flights + hook), so a 4N-SIN order isn't unfairly
    penalized for its hotel-justified shape; totals stay flights-only."""
    trips = [t for t in (order_trip(flights, openjaws, sg_tickets or [], k,
                                    hotel_cost=hotel_cost) for k in ORDERS) if t]
    if not trips:
        return None
    adj = ((lambda s: s["total"] + hotel_cost(s["sg_nights"])) if hotel_cost
           else (lambda s: s["total"]))
    trips.sort(key=lambda s: (not s["valid"], adj(s)))
```

(The rest of `main_trip` — `win`, `other_order` with its flights-only `delta` — is unchanged.)

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_main_trip.py tests/test_combo.py tests/test_budget.py -q` → PASS (hookless callers unchanged)

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q
git add combo.py tests/test_main_trip.py
git commit -m "feat: combo accepts optional hotel_cost hook for in-band + cross-order ranking"
```

---

### Task 5: `combo.sin_night_flight_totals` — the per-night-count table source

**Files:**
- Modify: `combo.py` (add after `order_trip`)
- Modify: `tests/test_main_trip.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/test_main_trip.py`; extend the import line at the top of the file to include `sin_night_flight_totals`)

```python
def test_sin_night_flight_totals_by_band():
    from combo import sin_night_flight_totals
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    totals = sin_night_flight_totals(FLIGHTS, [TICKET1],
                                     SG_TICKETS + [four_night], "SIN-first")
    # 2N: min(1000 one-ticket, 700+400 one-ways) + 3600 · 4N: 1060 + 3600.
    # TICKET2_OTHER_DATES pairs to a 4-night Bangkok block → excluded (strict 5).
    assert totals == {2: 4600, 4: 4660}
    assert sin_night_flight_totals(FLIGHTS, [], SG_TICKETS, "SIN-first") == {}
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_main_trip.py -q` → FAIL (`ImportError`)

- [ ] **Step 3: Implement** (add to `combo.py` after `order_trip`)

```python
def sin_night_flight_totals(flights, openjaws, tickets2, order_key):
    """{sin_nights: cheapest flight total} across tonight's strict-shape
    candidates (5 BKK nights, in-band SIN) for one order — the per-night-count
    table the stay-math layer renders. Mirrors order_trip's `exact` pool."""
    cfg = ORDERS[order_key]
    ojs = [o for o in (openjaws or [])
           if o.get("kind") == "stopover2" and o.get("ret_city") == cfg["ret_city"]
           and isinstance(o.get("price_total"), (int, float)) and _airline_ok(o)]
    if not ojs:
        return {}
    oj = min(ojs, key=lambda o: o["price_total"])
    ret = _date(oj["ret_date"])
    dac_in = _date(oj.get("out_arrive", "")) or (_date(oj["out_date"]) + timedelta(days=1))
    if not ret:
        return {}
    best = {}
    for m in _order_middles(flights, tickets2, order_key):
        dhaka_days = (m["dhaka_out"] - dac_in).days + 1
        if not 1 <= dhaka_days <= MAX_DHAKA_DAYS:
            continue
        final_nights = (ret - m["city2_in"]).days
        if final_nights < 1:
            continue
        bkk_nights, sin_nights = _split_nights(cfg, m["mid_nights"], final_nights)
        if bkk_nights != IDEAL_BKK_NIGHTS:
            continue
        if not MIN_SG_NIGHTS <= sin_nights <= MAX_SG_NIGHTS:
            continue
        total = oj["price_total"] + m["cost"]
        if sin_nights not in best or total < best[sin_nights]:
            best[sin_nights] = total
    return best
```

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_main_trip.py -q` → PASS

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q
git add combo.py tests/test_main_trip.py
git commit -m "feat: combo.sin_night_flight_totals — per-SIN-night cheapest flight totals"
```

---

### Task 6: `publish.py` — wire the hook + `stay_value` block + `sg_allin` history key

**Files:**
- Modify: `publish.py`
- Modify: `tests/test_stay_value.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_stay_value.py`)

```python
from tests.test_main_trip import FLIGHTS, TICKET1, SG_TICKETS, TICKET2
import publish


def test_build_payload_steers_and_records_stay_value():
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS + [four_night],
                              stay_rates=RATES)
    sv = p["stay_value"]
    assert sv["mode"] == "steering"
    assert p["main"]["sg_nights"] == 4            # the hook steered the pick
    assert sv["picked_n"] == 4 and sv["trip_n"] == 4 and sv["warning"] is None
    assert p["main"]["total"] == 4660             # flights-only, always
    assert p["history"][-1]["sg_allin"] == 4660 + 337
    assert not any("🛏️" in w for w in p["warnings"])


def test_build_payload_without_rates_is_tonights_old_behavior():
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS)
    assert p["stay_value"] is None
    assert p["main"]["sg_nights"] == 2
    assert p["history"][-1]["sg_allin"] is None


def test_build_payload_advisory_shows_table_but_does_not_steer():
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    stale = {"rows": [dict(RATES["rows"][1], checked="2026-08-10")]}
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS + [four_night],
                              stay_rates=stale)
    assert p["main"]["sg_nights"] == 2            # pick stayed flight-only
    assert p["stay_value"]["mode"] == "advisory"
    assert p["stay_value"]["warning"] is None     # mismatch is EXPECTED here


def test_incumbent_comes_from_the_last_history_entry():
    # Yesterday picked 4N; today 2N is only $10 better adjusted → dead-band
    # keeps 4N. (4N incumbent bonus −25 makes its score win.)
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027",
                      price_total=1000 + 113 + 10,   # 2N would win by $10 raw
                      airline="Biman", link="http://t2flex")
    hist = [{"date": "2026-08-18", "sg_nights": 4, "main_total": 4700}]
    p = publish.build_payload(FLIGHTS, [TICKET1], hist, "2026-08-19",
                              sg_tickets=SG_TICKETS + [four_night],
                              stay_rates=RATES)
    assert p["main"]["sg_nights"] == 4
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_stay_value.py -q` → FAIL (`unexpected keyword argument 'stay_rates'`)

- [ ] **Step 3: Implement**

In `publish.py`:

1. Add to the imports (top of file): `import stay_value` and extend the combo import to `from combo import budget_trip, main_trip, sin_night_flight_totals, ticket1_options, ticket2_options`.

2. Change `build_payload`'s signature and its opening (the current first line is `main = main_trip(flights, openjaws, sg_tickets or [])`; the current `as_of` parse sits further down before the alerts block — MOVE it up and reuse it, don't parse twice):

```python
def build_payload(flights: list, openjaws: list, history: list, today: str,
                  warnings: list = None, sg_tickets: list = None,
                  bali: dict = None, stay_rates: dict = None) -> dict:
    """One trip, one payload (2026-07-25). The alternative trips — direct
    open-jaw, three one-ways, Istanbul-only, Singapore-only — are no longer
    scraped, tracked, or charted; `main` IS the product now.
    stay_rates (2026-08-19): parsed hotel_rates.json. When present and fresh,
    the 🛏️ stay-math hook steers the SIN night count all-in (flights + net
    hotel after credits, $225/extra-night knob); the block always rides as
    payload["stay_value"] and history gains sg_allin. None → exact pre-stay
    behavior (manual runs, tests)."""
    try:
        as_of = datetime.date.fromisoformat(today)
    except ValueError:
        as_of = datetime.date.today()
    incumbent_n = (history[-1] or {}).get("sg_nights") if history else None
    hook = (stay_value.hotel_hook(stay_rates, incumbent_n, today=as_of)
            if stay_rates else None)
    main = main_trip(flights, openjaws, sg_tickets or [], hotel_cost=hook)
```

3. After the `bali` block (ends `bali["delta_vs_main"] = ...`) and before the `t1 = ...` line, add:

```python
    # 🛏️ Stay math (2026-08-19): the per-night-count all-in table + what it
    # picked. A steering-mode mismatch with the trip is a wiring bug — it
    # rides to Telegram as a warning.
    stay = None
    if stay_rates is not None and main:
        totals = sin_night_flight_totals(flights, openjaws, sg_tickets or [],
                                         main["order"])
        stay = stay_value.build(stay_rates, totals, incumbent_n,
                                main.get("sg_nights"), today=as_of)
        if stay.get("warning"):
            warnings = list(warnings or []) + [f"🛏️ {stay['warning']}"]
```

4. In the `entry = {...}` dict, after the `"sg_nights"` line, add:

```python
        "sg_allin": (stay or {}).get("trip_allin"),
```

5. Remove the now-duplicate `as_of` parse above the alerts block (keep using the one from step 2).

6. In the returned payload dict, after `"hotel": hotels.hotel_plan(main),` add:

```python
        "stay_value": stay,
```

7. `build_today` passes it through:

```python
def build_today(flights: list, openjaws: list, warnings: list = None,
                sg_tickets: list = None, bali: dict = None,
                stay_rates: dict = None) -> dict:
    """Today's payload, history included — built BEFORE Telegram goes out so the
    message and the dashboard can't disagree about what the trip costs."""
    return build_payload(flights, openjaws, _load_history(),
                         datetime.date.today().isoformat(), warnings, sg_tickets,
                         bali=bali, stay_rates=stay_rates)
```

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_stay_value.py tests/test_publish.py tests/test_publish_push.py -q` → PASS

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q
git add publish.py tests/test_stay_value.py
git commit -m "feat: publish wires stay-math hook + stay_value block + sg_allin history key"
```

---### Task 7: `run_daily.py` — load rates once, steer the sanity-path trip too

**Files:**
- Modify: `run_daily.py:118-123` (trip build) and `:151-153` (verify call)

No new test (pure wiring; every piece is unit-tested; `tests/test_run_daily_stamp.py` covers this file's other logic).

- [ ] **Step 1: Edit the trip build**

Replace (currently lines 118-123):

```python
    from combo import main_trip, bali_watch_trip
    from sanity import self_check
    trip = main_trip(flights, tickets1, sg_tickets)
```

with:

```python
    from combo import main_trip, bali_watch_trip
    from sanity import self_check
    import stay_value
    # 🛏️ Stay math: one rates load for the whole run — the same dict feeds
    # the pick (via publish), this sanity-path trip, and verify's independent
    # re-derivation. hotel_hook is None unless the bold SIN rate is fresh.
    stay_rates = stay_value.load_rates()
    stay_hook = stay_value.hotel_hook(
        stay_rates, (publish.last_history_entry() or {}).get("sg_nights"))
    trip = main_trip(flights, tickets1, sg_tickets, hotel_cost=stay_hook)
```

- [ ] **Step 2: Pass rates into the payload build**

Replace:

```python
    payload = publish.build_today(flights, tickets1, warnings, sg_tickets,
                                  bali=bali)
```

with:

```python
    payload = publish.build_today(flights, tickets1, warnings, sg_tickets,
                                  bali=bali, stay_rates=stay_rates)
```

- [ ] **Step 3: Pass rates into verify** (Task 8 adds the parameter — do this edit now; the default keeps it green meanwhile)

Replace:

```python
        return verify.verify_payload(payload, flights, tickets1, sg_tickets)
```

with:

```python
        return verify.verify_payload(payload, flights, tickets1, sg_tickets,
                                     rates=stay_rates)
```

Note: this call errors until Task 8 lands — so do Steps 1–2, run the suite, commit them, and fold Step 3's edit into Task 8's commit instead if executing tasks strictly separately. If executing Tasks 7+8 in one session, one commit at the end of Task 8 covering both files is fine.

- [ ] **Step 4: Full suite**

```bash
python3 -m pytest tests/ -q
```

- [ ] **Step 5: Commit** (Steps 1–2 only, if Task 8 is a separate session)

```bash
git add run_daily.py
git commit -m "feat: run_daily loads stay rates once and steers the sanity-path trip"
```

---

### Task 8: `verify.py` — independent hotel-aware recompute

**Files:**
- Modify: `verify.py`
- Modify: `tests/test_verify.py` (append)
- Modify (if deferred from Task 7): `run_daily.py` verify call

- [ ] **Step 1: Write the failing tests** (append to `tests/test_verify.py`; add the imports it needs at the top of the new block)

```python
# ── 🛏️ Stay-math recompute (2026-08-19) ────────────────────────────────────
import datetime as _dt
import stay_value as _sv
import verify as _verify
from tests.test_main_trip import (FLIGHTS as _MT_FLIGHTS, TICKET1 as _MT_T1,
                                  SG_TICKETS as _MT_SG, TICKET2 as _MT_T2)
from tests.test_stay_value import RATES as _RATES

_FOUR = dict(_MT_T2, out_date="January 28, 2027",
             out_arrive="January 28, 2027", price_total=1060,
             airline="Biman", link="http://t2flex")


def _stay_payload(hook):
    from combo import main_trip
    t2 = _MT_SG + [_FOUR]
    main = main_trip(_MT_FLIGHTS, [_MT_T1], t2, hotel_cost=hook)
    return {
        "main": main,
        "history": [{"date": "2026-08-19", "main_total": main["total"]}],
        "stay_value": {"mode": "steering"},
    }, t2


def test_strict_by_sg_totals():
    by = _verify.strict_by_sg(_MT_FLIGHTS, [_MT_T1], _MT_SG + [_FOUR],
                              "SIN-first")
    assert by == {2: 4600, 4: 4660}


def test_recompute_agrees_with_a_hotel_aware_pick():
    hook = _sv.hotel_hook(_RATES, None, today=_dt.date(2026, 8, 19))
    payload, t2 = _stay_payload(hook)
    assert payload["main"]["sg_nights"] == 4
    probs = _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2,
                                   rates=_RATES)
    assert probs == []


def test_recompute_flags_a_flight_only_pick_when_steering():
    payload, t2 = _stay_payload(None)          # hook not applied → 2N
    assert payload["main"]["sg_nights"] == 2
    probs = _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2,
                                   rates=_RATES)
    assert any("hotel-aware recompute picks 4" in p for p in probs)


def test_stay_rows_arithmetic_is_rechecked():
    payload, t2 = _stay_payload(
        _sv.hotel_hook(_RATES, None, today=_dt.date(2026, 8, 19)))
    payload["stay_value"] = {
        "mode": "steering",
        "rows": [{"n": 4, "flights": 4660, "hotel_net": 337, "allin": 9999}],
    }
    probs = _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2,
                                   rates=_RATES)
    assert any("stay-math row" in p for p in probs)


def test_no_rates_no_steering_checks():
    payload, t2 = _stay_payload(None)
    payload["stay_value"] = None
    assert _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2) == []
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_verify.py -q` → FAIL (`no attribute 'strict_by_sg'`)

- [ ] **Step 3: Implement**

In `verify.py`:

1. Add constants after `MAX_DHAKA = 29` — duplicated from stay_value ON PURPOSE (this module's value is being a second implementation; same pattern as SG_BAND/BKK_IDEAL vs combo):

```python
# 🛏️ Stay-math constants — deliberately DUPLICATED from stay_value.py (this
# file's value is being a second implementation; keep the numbers in sync).
STAY_WORTH = 225
STAY_DEAD_BAND = 25
STAY_TAX = 0.12
STAY_FHR_FIXED, STAY_EDIT_FIXED, STAY_DAILY = 400, 350, 60
```

2. Refactor `strict_best` into a per-night-count version (replace the whole function):

```python
def strict_by_sg(flights, tickets1, tickets2, order_key):
    """{sin_nights: cheapest strict-shape total} for one order (5 BKK nights,
    in-band SIN, visa + deadline) — independent re-derivation of combo's
    candidate table."""
    r1, r2, ret_city, bkk_is_mid = _ORDER_SPEC[order_key]
    ojs = [o for o in tickets1 or []
           if o.get("ret_city") == ret_city and _priced(o)]
    if not ojs:
        return {}
    oj = min(ojs, key=lambda o: o["price_total"])
    ret, dac_in = _d(oj.get("ret_date", "")), _d(oj.get("out_arrive", ""))
    if not (ret and dac_in):
        return {}
    best = {}
    for m in _middles(flights, tickets2, r1, r2, order_key):
        dhaka = (m["dhaka_out"] - dac_in).days + 1
        if not 1 <= dhaka <= MAX_DHAKA:
            continue
        fin = (ret - m["c2_in"]).days
        if fin < 1:
            continue
        bkk, sg = (m["mid"], fin) if bkk_is_mid else (fin, m["mid"])
        if bkk != BKK_IDEAL or not SG_BAND[0] <= sg <= SG_BAND[1]:
            continue
        total = oj["price_total"] + m["cost"]
        if sg not in best or total < best[sg]:
            best[sg] = total
    return best


def strict_best(flights, tickets1, tickets2, order_key):
    """Cheapest trip total in the EXACT asked-for shape for one order, or None."""
    by = strict_by_sg(flights, tickets1, tickets2, order_key)
    return min(by.values()) if by else None
```

3. Add the independent stay adjuster (after `strict_best`):

```python
def _stay_adj(payload, rates):
    """The stay-math score adjuster, re-derived from the raw rates dict with
    this module's own constants — None unless the payload claims steering AND
    the rates carry a usable bold SIN row. Incumbent = the sg_nights of the
    PREVIOUS history entry (today's entry is last)."""
    if ((payload.get("stay_value") or {}).get("mode") != "steering"
            or not rates):
        return None
    row = next((r for r in rates.get("rows", [])
                if r.get("city") == "SIN" and r.get("bold")
                and isinstance(r.get("rate"), (int, float))), None)
    if not row:
        return None
    hist = payload.get("history") or []
    incumbent = hist[-2].get("sg_nights") if len(hist) >= 2 else None
    fixed = (STAY_FHR_FIXED if "FHR" in (row.get("program") or "")
             else STAY_EDIT_FIXED)

    def adj(n):
        net = max(0, round(n * row["rate"] * (1 + STAY_TAX)
                           - (fixed + STAY_DAILY * n)))
        return (net - STAY_WORTH * (n - SG_BAND[0])
                - (STAY_DEAD_BAND if n == incumbent else 0))
    return adj
```

4. Update `verify_payload` — signature becomes:

```python
def verify_payload(payload, flights, tickets1, sg_tickets, rates=None):
```

Replace the RECOMPUTE loop body (the `for order in _ORDER_SPEC:` block) with:

```python
    adj = _stay_adj(payload, rates)
    claimed_n = {main.get("order"): main.get("sg_nights")}
    if other:
        claimed_n[other.get("order")] = other.get("sg_nights")
    for order in _ORDER_SPEC:
        by_n = strict_by_sg(flights, tickets1, sg_tickets, order)
        strict = min(by_n.values()) if by_n else None
        if order not in claimed:
            if strict is not None:
                problems.append(f"re-check: a strict-shape {order} trip exists "
                                f"(${strict:,}) but the payload has no entry "
                                f"for that order")
            continue
        total, valid = claimed[order]
        if valid:
            if strict is None:
                problems.append(f"re-check: {order} claims a clean shape but "
                                f"the independent recompute finds none")
            elif adj:
                exp_n = min(by_n, key=lambda n: by_n[n] + adj(n))
                got_n = claimed_n.get(order)
                if got_n != exp_n:
                    problems.append(f"re-check: {order} picked {got_n} SIN "
                                    f"nights but the hotel-aware recompute "
                                    f"picks {exp_n}")
                elif total != by_n.get(got_n):
                    problems.append(f"re-check: {order} total ${total:,} ≠ "
                                    f"independent recompute "
                                    f"${by_n[got_n]:,} at {got_n} SIN nights")
            elif total != strict:
                problems.append(f"re-check: {order} total ${total:,} ≠ "
                                f"independent recompute ${strict:,}")
        elif strict is not None and strict <= total:
            problems.append(f"re-check: {order} is flagged, but a strict-shape "
                            f"trip exists at ${strict:,}")
```

and replace the losing-order check just after it with the adjusted comparison:

```python
    if other and other.get("valid") and main.get("valid"):
        a = adj or (lambda n: 0)
        if (other["total"] + a(other.get("sg_nights"))
                < main["total"] + a(main.get("sg_nights"))):
            problems.append("re-check: the losing order is cheaper than the winner")
```

5. In the ARITHMETIC section, after the budget check, add:

```python
    sv = payload.get("stay_value") or {}
    for r in sv.get("rows") or []:
        if (isinstance(r.get("flights"), (int, float))
                and isinstance(r.get("hotel_net"), (int, float))
                and r.get("allin") != r["flights"] + r["hotel_net"]):
            problems.append(f"re-check: stay-math row {r.get('n')}N all-in "
                            f"≠ flights + hotel net")
```

6. If Task 7 Step 3 was deferred, apply the `run_daily.py` verify-call edit now.

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_verify.py -q` → PASS

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q
git add verify.py tests/test_verify.py run_daily.py
git commit -m "feat: verify re-derives the hotel-aware SIN pick independently"
```

---

### Task 9: `schema_check.py` + site `validatePayload()` — the mirror rule

**Files:**
- Modify: `schema_check.py:12-29` (TOP) and `:39-40` (HISTORY_NUMERIC)
- Modify: `site/index.html:445-472` (validatePayload)
- Modify: `tests/test_schema_check.py` (fixture + new test)

- [ ] **Step 1: Write the failing test** (append to `tests/test_schema_check.py`)

```python
def test_stay_value_key_is_part_of_the_contract():
    import schema_check
    assert "stay_value" in schema_check.TOP
    assert "sg_allin" in schema_check.HISTORY_NUMERIC
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_schema_check.py -q` → the new test FAILS

- [ ] **Step 3: Implement**

In `schema_check.py` add to `TOP` (after the `"hotel"` line):

```python
    "stay_value": (dict, type(None)),
```

and extend `HISTORY_NUMERIC`:

```python
HISTORY_NUMERIC = ["main_total", "ticket1_total", "ticket2_total",
                   "bali_total", "budget_total", "other_order_total",
                   "sg_allin"]
```

In `site/index.html` `validatePayload` (line ~458), change:

```js
  for (const k of ["main", "budget", "bali", "hotel"])
```

to:

```js
  for (const k of ["main", "budget", "bali", "hotel", "stay_value"])
```

and the history numeric loop (line ~468) to include the new key:

```js
    for (const k of ["main_total", "ticket1_total", "ticket2_total", "bali_total", "budget_total", "sg_allin"])
```

- [ ] **Step 4: Run the suite; fix hand-built payload fixtures**

Run: `python3 -m pytest tests/ -q`
Any test that hand-builds a full payload dict (rather than calling `publish.build_payload`) now fails with `top-level key 'stay_value' is missing` — expected for `tests/test_schema_check.py`'s valid-payload fixture. Add `"stay_value": None,` to each such fixture dict until the suite is green again. (Payloads from `build_payload` carry the key automatically.)

- [ ] **Step 5: Commit**

```bash
git add schema_check.py site/index.html tests/test_schema_check.py
git commit -m "feat: stay_value + sg_allin join the payload contract (both mirrors)"
```

---

### Task 10: Telegram — the 🛏️ line in the nightly brief

**Files:**
- Modify: `notify_telegram.py` (in `build_message`, after the `hotel` block ~line 227, before the `budget` block)
- Modify: `tests/test_stay_value.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_stay_value.py`)

```python
import notify_telegram


def _steering_payload():
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    return publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                                 sg_tickets=SG_TICKETS + [four_night],
                                 stay_rates=RATES)


def test_brief_carries_the_stay_math_line():
    msg = notify_telegram.build_message(_steering_payload())
    assert "🛏️" in msg
    assert "2N $4,600" in msg
    assert "4N $4,997 ←" in msg            # 4660 flights + 337 net, picked
    assert "St. Regis Singapore" in msg


def test_brief_flags_advisory_mode():
    stale = {"rows": [dict(RATES["rows"][1], checked="2026-08-10")]}
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS, stay_rates=stale)
    msg = notify_telegram.build_message(p)
    assert "advisory only" in msg


def test_brief_without_stay_value_is_unchanged():
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS)
    assert "🛏️" not in notify_telegram.build_message(p)
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_stay_value.py -q` → the three new tests FAIL

- [ ] **Step 3: Implement**

In `notify_telegram.py` `build_message`, insert AFTER the hotel block (i.e., after the `if hotel.get("warn"): ...` line) and BEFORE `budget = payload.get("budget")`:

```python
    # 🛏️ Stay math (2026-08-19): the all-in night-count table, one line.
    sv = payload.get("stay_value")
    if sv and sv.get("rows"):
        seg = " · ".join(
            f"{r['n']}N ${r['allin']:,}"
            + (" ←" if r["n"] == sv.get("picked_n") else "")
            for r in sv["rows"])
        sh = sv.get("hotel") or {}
        parts.append(f"🛏️ Stay math: {seg} · {esc_html(sh.get('name', '?'))} "
                     f"${sh.get('rate', 0):,}/n")
        if sv.get("mode") == "advisory" and sv.get("note"):
            parts.append(f"⚠️ {esc_html(sv['note'])}")
        if sv.get("watchdog"):
            parts.append(f"👀 {esc_html(sv['watchdog'])}")
```

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_stay_value.py tests/test_notify_fallback.py -q` → PASS

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q
git add notify_telegram.py tests/test_stay_value.py
git commit -m "feat: nightly brief carries the 🛏️ stay-math line"
```

---

### Task 11: `alerts.changes_since` — tag hotel-driven night flips

**Files:**
- Modify: `alerts.py:184-192` (the nights/days diff loop)
- Modify: `tests/test_alerts.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/test_alerts.py`)

```python
def test_sg_nights_change_is_tagged_when_hotel_aware():
    import alerts
    prev = {"ticket1_total": 3600, "sg_nights": 2}
    cur = {"ticket1_total": 3600, "sg_nights": 4, "sg_allin": 4997}
    out = alerts.changes_since(prev, cur)
    assert any("Singapore nights: 2 → 4 (hotel-aware pick)" in c for c in out)
    cur_plain = {"ticket1_total": 3600, "sg_nights": 4}
    out2 = alerts.changes_since(prev, cur_plain)
    assert any(c == "Singapore nights: 2 → 4" for c in out2)
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_alerts.py -q` → FAIL

- [ ] **Step 3: Implement**

In `alerts.py`, replace the body of the nights/days loop:

```python
    for key, label in (("ist_nights", "Istanbul nights"),
                       ("sg_nights", "Singapore nights"),
                       ("bkk_nights", "Bangkok nights"),
                       ("bali_nights", "Bali nights"),   # pre-2026-08-01 entries
                       ("dhaka_days", "Dhaka days"),
                       ("home", "home date")):
        if (prev.get(key) is not None and cur.get(key) is not None
                and prev[key] != cur[key]):
            suffix = (" (hotel-aware pick)"
                      if key == "sg_nights" and cur.get("sg_allin") is not None
                      else "")
            out.append(f"{label}: {prev[key]} → {cur[key]}{suffix}")
```

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_alerts.py -q` → PASS

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q
git add alerts.py tests/test_alerts.py
git commit -m "feat: changes_since tags hotel-driven SIN-night flips"
```

---

### Task 12: Sheet — appended "🛏️ SIN all-in" History column

**Files:**
- Modify: `sheet_writer.py:66-70` (HISTORY_HEADERS) and `:73-94` (history_row)
- Modify: `tests/test_sheet_writer.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/test_sheet_writer.py`)

```python
def test_history_row_carries_the_stay_allin_column():
    from sheet_writer import HISTORY_HEADERS, history_row
    assert HISTORY_HEADERS[-1] == "🛏️ SIN all-in"
    row = history_row({"date": "2026-08-19", "sg_nights": 4, "sg_allin": 4997})
    assert len(row) == len(HISTORY_HEADERS)
    assert row[-1] == "4N $4,997"
    assert history_row({"date": "2026-08-19"})[-1] == ""
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_sheet_writer.py -q` → FAIL

- [ ] **Step 3: Implement**

In `sheet_writer.py`, append to `HISTORY_HEADERS` (APPEND-ONLY — never reorder; the widen-in-place logic in `append_history_row` extends the sheet header automatically):

```python
HISTORY_HEADERS = ["Date", "⭐ IST+SIN main", "Direct OJ + hop", "SIN only",
                   "IST only", "TK 30h stopover", "3 one-ways", "Best $",
                   "Best structure",
                   "Ticket ① $", "Ticket ② $", "① airline", "② airline",
                   "IST/DAC/SIN/5n-city", "💸 Budget $", "Order", "🌴 Bali $",
                   "🛏️ SIN all-in"]
```

In `history_row`, before the `return`, add:

```python
    allin = e.get("sg_allin")
    stay_cell = (f"{e.get('sg_nights', '?')}N ${allin:,}"
                 if isinstance(allin, (int, float)) else "")
```

and append `stay_cell,` as the last element of the returned list (after the `bali_total` line).

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_sheet_writer.py -q` → PASS. If an existing test asserts the old row length, update its expectation — the column is appended, nothing moved.

- [ ] **Step 5: Full suite + commit**

```bash
python3 -m pytest tests/ -q
git add sheet_writer.py tests/test_sheet_writer.py
git commit -m "feat: History sheet gains appended 🛏️ SIN all-in column"
```

---

### Task 13: Site — Tonight chip + #/stays stay-math card

**Files:**
- Modify: `site/index.html` (verdictPass chips ~line 623; new `stayValueCard` before `renderStays` ~line 1097; one insert inside `renderStays`)

No JS test harness exists; correctness is guarded by the payload contract (Task 9) and a `?qa=` visual check below. Keep every access null-safe — the page must render with `stay_value` absent, null, or off-mode.

- [ ] **Step 1: Tonight chip**

In `verdictPass`, directly after `if (!m.valid) chips.push(...)` (~line 623), add:

```js
  const svc = d.stay_value;
  if (svc && svc.mode === "steering" && typeof m.sg_nights === "number" && m.sg_nights > 2)
    chips.push(`<span class="chip chip-good">🛏️ ${m.sg_nights}N SIN · hotel math</span>`);
```

- [ ] **Step 2: The stays card**

Add above `function renderStays(d) {` (~line 1097):

```js
/* 🛏️ Stay math (2026-08-19): the all-in SIN night-count table — flights +
   net hotel after credits, $knob/extra-night. Steers the pick only on fresh
   rates; advisory/off modes say so instead of pretending. */
function stayValueCard(d) {
  const sv = d && d.stay_value;
  if (!sv || !Array.isArray(sv.rows) || !sv.rows.length) return "";
  const rows = sv.rows.map(r => `<tr${r.n === sv.picked_n ? ' style="font-weight:700"' : ""}>
      <td>${r.n}N</td><td class="num">${usd(r.flights)}</td>
      <td class="num">${usd(r.hotel_net)}</td><td class="num">${usd(r.allin)}</td>
      <td>${r.n === sv.picked_n ? '<span class="badge good">picked by the math</span>' : ""}</td></tr>`).join("");
  const modeNote = sv.mode === "steering"
    ? `Steering tonight's pick — worth-it knob $${sv.knob}/extra night, ±$${sv.dead_band} dead-band.`
    : sv.mode === "advisory"
      ? `⚠️ Advisory only — ${esc(sv.note || "the hotel rate is stale; the pick stayed flight-only.")}`
      : `Off — ${esc(sv.note || "no usable hotel rate.")}`;
  return `<span class="micro" style="display:block;margin-top:18px">Singapore nights — the all-in math</span>
    <div class="pass">
      <div class="scroll-x"><table>
        <tr><th>SIN</th><th class="num">Flights</th><th class="num">Hotel net</th><th class="num">All-in</th><th></th></tr>
        ${rows}</table></div>
      ${sv.watchdog ? `<div style="margin-top:8px"><span class="chip chip-warn">👀 ${esc(sv.watchdog)}</span></div>` : ""}
      <div class="small" style="margin-top:8px">${modeNote}</div>
      ${sv.assumption ? `<div class="small" style="margin-top:4px">${esc(sv.assumption)}</div>` : ""}
    </div>`;
}
```

Inside `renderStays`, after the first `add(root, () => {...})` block (the Athenee pass) and before the `if (d.bali && d.bali.hotel)` line, add:

```js
  if (d.stay_value && Array.isArray(d.stay_value.rows) && d.stay_value.rows.length)
    add(root, () => el(stayValueCard(d)));
```

- [ ] **Step 3: QA check with a mutant payload**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights/site"
mkdir -p qa
python3 - <<'EOF'
import json
d = json.load(open("data.json"))
d["stay_value"] = {
    "mode": "steering", "knob": 225, "dead_band": 25,
    "hotel": {"key": "stregis_sin", "name": "St. Regis Singapore",
              "rate": 218, "checked": "2026-08-19", "program": "FHR"},
    "rows": [{"n": 2, "flights": 4614, "hotel_net": 0, "allin": 4614, "score": 4614},
             {"n": 3, "flights": 4660, "hotel_net": 152, "allin": 4812, "score": 4587},
             {"n": 4, "flights": 4660, "hotel_net": 337, "allin": 4997, "score": 4547}],
    "picked_n": 4, "trip_n": 4, "incumbent_n": 2, "trip_allin": 4997,
    "watchdog": None, "warning": None, "note": None,
    "assumption": "St. Regis Singapore $218/n (checked 2026-08-19) · credits $400/stay + $60/day · ~12% tax · longer stays assume the tracked window's nightly rate",
}
d["main"]["sg_nights"] = 4
json.dump(d, open("qa/stay.json", "w"), indent=1)
EOF
python3 -m http.server 8901 &
```

Open `http://localhost:8901/?qa=stay#/stays` and `#/` — confirm the card renders (4N row bold + badge), the Tonight chip shows "🛏️ 4N SIN · hotel math", and both light/dark themes look right. Then:

```bash
kill %1; rm -rf qa      # NEVER commit qa/
```

- [ ] **Step 4: Commit + deploy the site**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
python3 -m pytest tests/ -q
git add site/index.html
git commit -m "feat: dashboard renders the 🛏️ stay-math card + Tonight chip"
cd site && vercel --prod --yes && cd ..
```

(Dashboard deploys are only needed when index.html changes — AGENTS §3.)

---

### Task 14: AGENTS.md + push

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Document the layer**

In `AGENTS.md` §1, add a block after the **💸 Budget companion** paragraph:

```markdown
**🛏️ Stay math (`stay_value.py`, 2026-08-19):** the SIN night count (2-4
band) is picked ALL-IN — flights + the bold SIN hotel's net out-of-pocket
(rate ×1.12 tax − credits: $400/stay FHR or $350 Edit + $60/day, floored at
0) — with each extra night valued at `EXTRA_NIGHT_WORTH = 225` (Jalal
2026-08-19, derived from his own ≥70% book-now band / Athenee points-value /
replacement cost) and a `DEAD_BAND = 25` incumbent bonus against nightly
flapping. Implemented as an optional `hotel_cost` hook on
`combo.order_trip`/`main_trip` (hookless callers behave exactly as before;
`total` stays FLIGHTS-ONLY everywhere — history, chart, buy-signal). Mode
ladder: **steering** (bold rate ≤3 days old) / **advisory** (stale — table
renders, pick stays flight-only; the hotel job has gone 5 nights dark
before) / **off** (no data). The block rides as `payload["stay_value"]`,
history gains `sg_allin`, Telegram a 🛏️ line, the site a #/stays card + a
Tonight chip, the Sheet an appended "🛏️ SIN all-in" column. A >$50/night
cheaper non-bold SIN hotel triggers a re-bold watchdog note. verify.py
re-derives the pick with its OWN duplicated constants (keep them in sync
deliberately — second implementation is the point). Knobs live at the top of
stay_value.py like alerts.BUY_BELOW.
Spec: `docs/superpowers/specs/2026-08-19-hotel-aware-sin-nights-design.md`.
```

- [ ] **Step 2: Update the file map (§7)**

Add after the `hotels.py` entry:

```markdown
- `stay_value.py` — 🛏️ hotel-aware SIN night-count layer (§1 Stay math):
  knobs, mode ladder, the combo hook, the payload block, the re-bold watchdog
```

Update the `combo.py` line to mention `sin_night_flight_totals`, the `verify.py` line to mention the duplicated stay constants, and the `tests/` line's test count to the new total (run `python3 -m pytest tests/ -q` for the number).

- [ ] **Step 3: Final full suite + push**

```bash
python3 -m pytest tests/ -q
git add AGENTS.md
git commit -m "docs: AGENTS.md documents the 🛏️ stay-math layer"
git push
```

- [ ] **Step 4: Confirm the tree is safe for tonight's jobs**

`git status` must be clean; suite green. The midnight flight run + 5am hotel run will exercise the layer live — tomorrow's Telegram brief should carry the 🛏️ line (steering, since rates were fresh today).
