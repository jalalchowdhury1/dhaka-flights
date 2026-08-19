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
