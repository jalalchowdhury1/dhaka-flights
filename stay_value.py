"""Hotel-aware Singapore night-count layer ("stay math", 2026-08-19).

The SIN stay is a 2-4 night flex band; combo.py historically picked within it
by flight price alone. This module prices the whole choice — flights + what
the curated hotel play actually costs out of pocket (the portal-anchored
all-in per paid night, since 2026-08-22 — see hotel_rates.PORTAL — minus
card credits) — and values each extra Singapore night at EXTRA_NIGHT_WORTH
(derived 2026-08-19 from Jalal's own ≥70% book-now band, the Athenee
points-value, and replacement cost; he chose $225).

    score(n) = allin(n) − EXTRA_NIGHT_WORTH × (n − MIN_N)     lowest wins
    allin(n) = flights(n) + hotel_net(n)
    hotel_net(n) = max(0, paid_nights(n)·allin_night − credits(n))   never cash back
    allin_night  = est_allin_night from hotel_rates.json (portal-anchored),
                   else rate·(1+TAX) for a row with no anchor

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
TAX_RATE = 0.19           # FALLBACK for a row with no portal anchor (observed
                          # 1.19–1.20× on the Amex portal 2026-08-22)
AMEX_FIXED = 300          # $300 Amex FHR/THC per stay
EDIT_FIXED = 250          # $250 Edit — non-FHR programs
PROPERTY_CREDIT = 100     # default; an anchored row carries its own ($100/$125)
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
    a row switches the decision hotel with no logic change here.

    "Rate present" is deliberate even now that an anchored row could price
    from est_allin_night alone: the stay math may only STEER the trip on a
    number corroborated by a live public read, and the mode ladder's
    freshness test needs that read's `checked` date. A brand-new bold hotel
    is therefore "off" until its first successful scrape (the rollout runs
    the hotel job once by hand for exactly this reason)."""
    for r in _rows(rates):
        if (r.get("city") == city and r.get("bold")
                and isinstance(r.get("rate"), (int, float))):
            return r
    return None


def fixed_credits(program):
    """FHR-bookable stays get the $300 Amex; Edit/THC-only get $250 Edit."""
    return AMEX_FIXED if "FHR" in (program or "") else EDIT_FIXED


def _anchor(row):
    a = row.get("anchor") if isinstance(row, dict) else None
    return a if isinstance(a, dict) else {}


def property_credit(row):
    c = _anchor(row).get("credit")
    return c if isinstance(c, (int, float)) else PROPERTY_CREDIT


def credits(n, program="FHR", prop=PROPERTY_CREDIT):
    return fixed_credits(program) + prop + DAILY_CREDIT * n


def paid_nights(n, free_night_min=None):
    """A 'free 4th night' promo bills 3 nights for a 4-night stay.
    Same rule as hotel_rates.paid_nights, copied on purpose: this module
    never imports hotel_rates (it reads the JSON it writes), and verify.py
    carries a third copy as its independent check — keep all three in sync."""
    return n - 1 if free_night_min and n >= free_night_min else n


def allin_night(row):
    """Estimated all-in per paid night: the portal-anchored estimate the
    hotel job writes (est_allin_night), else public rate × (1 + TAX_RATE)."""
    est = row.get("est_allin_night")
    if isinstance(est, (int, float)) and est > 0:
        return est
    return row["rate"] * (1 + TAX_RATE)


def hotel_net(row, n):
    """Out-of-pocket for n nights after credits, floored at 0 — credits
    beyond the bill are not cash back. `row` is a hotel_rates.json row."""
    program = row.get("program", "FHR")
    nights = paid_nights(n, _anchor(row).get("free_night_min"))
    return max(0, round(nights * allin_night(row)
                        - credits(n, program, property_credit(row))))


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


def score_adjust(row, n, incumbent_n):
    """What the combo hook adds to a candidate's flight cost: its net hotel
    bill, minus the value of its extra nights, minus the incumbent shape's
    dead-band bonus (so the pick only flips when the challenger clearly
    wins — no 4N-Monday/2N-Tuesday whiplash from volatile flex fares)."""
    return (hotel_net(row, n)
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
    return lambda n: score_adjust(row, n, incumbent_n)


def _watchdog(rates, row, n):
    """A non-bold SIN hotel netting >WATCHDOG_GAP/night less than the play
    can't stay silent — the bold flag is frozen human curation (2026-08-01)
    and the rates under it move nightly."""
    if not n:
        return None
    bold_pn = hotel_net(row, n) / n
    best = None
    for r in _rows(rates):
        if (r.get("city") != "SIN" or r.get("bold")
                or not isinstance(r.get("rate"), (int, float))):
            continue
        pn = hotel_net(r, n) / n
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
        net = hotel_net(row, n)
        rows.append({"n": n, "flights": fl, "hotel_net": net, "allin": fl + net,
                     "score": fl + score_adjust(row, n, incumbent_n)})
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
               "program": program,
               "allin_night": round(allin_night(row), 2),
               "anchor_date": _anchor(row).get("date")},
        rows=rows, picked_n=picked,
        trip_allin=trip_row["allin"] if trip_row else None,
        watchdog=_watchdog(rates, row, trip_n if trip_row else MIN_N),
        warning=warning, note=note,
        assumption=(f"{row['name']} est. ${allin_night(row):,.0f}/paid night "
                    f"all-in ("
                    + (f"FHR portal {_anchor(row).get('date')}, drifted by the "
                       f"public rate ${row['rate']:,} checked {row.get('checked')}"
                       if _anchor(row).get("date") else
                       f"public ${row['rate']:,} checked {row.get('checked')} "
                       f"× ~{round(TAX_RATE * 100)}% tax, no portal anchor")
                    + f") · credits ${fixed_credits(program)}+"
                    f"${property_credit(row)}/stay + ${DAILY_CREDIT}/day"
                    + (f" · free night from {_anchor(row).get('free_night_min')}n"
                       if _anchor(row).get("free_night_min") else "")),
    )
