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


def _rows(rates):
    """The shortlist rows, defensively: anything but a list of dicts is [] —
    garbage input must degrade to mode 'off', never raise (publish calls this
    inside the nightly run; AGENTS.md: publish must never crash the run)."""
    rows = rates.get("rows") if isinstance(rates, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def bold_row(rates, city="SIN"):
    """The curated play — the bold row for the city, rate present. The bold
    flag is hand-set in hotel_rates.SHORTLIST (2026-08-01 research); re-bolding
    a row switches the decision hotel with no logic change here."""
    for r in _rows(rates):
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


def _watchdog(rates, row, n):
    """A non-bold SIN hotel netting >WATCHDOG_GAP/night less than the play
    can't stay silent — the bold flag is frozen human curation (2026-08-01)
    and the rates under it move nightly."""
    if not n:
        return None
    bold_pn = hotel_net(row["rate"], n, row.get("program", "FHR")) / n
    best = None
    for r in _rows(rates):
        if (r.get("city") != "SIN" or r.get("bold")
                or not isinstance(r.get("rate"), (int, float))):
            continue
        pn = hotel_net(r["rate"], n, r.get("program", "FHR")) / n
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
