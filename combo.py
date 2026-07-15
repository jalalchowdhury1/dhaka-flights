"""Pick the cheapest valid 3-leg combination (BOS→DAC, DAC→DPS, DPS→BOS).

Trip rules (docs/superpowers/specs/2026-07-15-three-leg-trip-redesign-design.md):
- Dhaka stay ≤ 29 days, counting BOTH the arrival and departure day (30-day visa)
- 5 nights in Bali (Marriott 5th-night-free); 4 or 6 allowed but ranked below 5
- Back in Boston on/before Feb 7, 2027

Uses the arrival dates parsed from Google's result text; when a flight's
arrival didn't parse, falls back to depart+1 day for long-haul legs
(BOS→DAC, DPS→BOS) and same-day for DAC→DPS.
"""
from datetime import datetime, timedelta

MAX_DHAKA_DAYS = 29
IDEAL_BALI_NIGHTS = 5
ALLOWED_BALI_NIGHTS = (4, 5, 6)
HOME_DEADLINE = datetime(2027, 2, 7)

_FALLBACK_ARRIVAL_LAG = {"BOS→DAC": 1, "DAC→DPS": 0, "DPS→BOS": 1}


def _date(s):
    try:
        return datetime.strptime(s, "%B %d, %Y")
    except (ValueError, TypeError):
        return None


def _arrival(flight):
    a = _date(flight.get("arrive", ""))
    if a:
        return a
    dep = _date(flight.get("depart", ""))
    if not dep:
        return None
    return dep + timedelta(days=_FALLBACK_ARRIVAL_LAG.get(flight.get("route", ""), 1))


def _priced(flights, route):
    return [f for f in flights
            if f.get("route") == route
            and isinstance(f.get("price_total"), (int, float))]


def cheapest_by_leg(flights) -> dict:
    """Cheapest single option per route, ignoring combo constraints."""
    best = {}
    for route in ("BOS→DAC", "DAC→DPS", "DPS→BOS"):
        options = _priced(flights, route)
        if options:
            best[route] = min(options, key=lambda f: f["price_total"])
    return best


def best_combos(flights, top_n=3) -> list:
    """Valid (leg1, leg2, leg3) triples, 5-night-Bali ones first, then by price."""
    combos = []
    for a in _priced(flights, "BOS→DAC"):
        dac_in = _arrival(a)
        if not dac_in:
            continue
        for b in _priced(flights, "DAC→DPS"):
            b_dep = _date(b.get("depart", ""))
            if not b_dep:
                continue
            dhaka_days = (b_dep - dac_in).days + 1  # both ends count toward the visa
            if not 1 <= dhaka_days <= MAX_DHAKA_DAYS:
                continue
            bali_in = _arrival(b)
            if not bali_in:
                continue
            for c in _priced(flights, "DPS→BOS"):
                c_dep = _date(c.get("depart", ""))
                if not c_dep:
                    continue
                nights = (c_dep - bali_in).days
                if nights not in ALLOWED_BALI_NIGHTS:
                    continue
                home = _arrival(c)
                if home and home > HOME_DEADLINE:
                    continue
                combos.append({
                    "legs": (a, b, c),
                    "total": a["price_total"] + b["price_total"] + c["price_total"],
                    "dhaka_days": dhaka_days,
                    "bali_nights": nights,
                    "home": home,
                })
    combos.sort(key=lambda x: (x["bali_nights"] != IDEAL_BALI_NIGHTS, x["total"]))
    return combos[:top_n]
