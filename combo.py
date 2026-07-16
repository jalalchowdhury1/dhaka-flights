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


def best_structures(flights, openjaws, top_n=4) -> list:
    """Compare ticketing structures and return them cheapest-first:
      - 'three one-ways': the classic best_combos winner
      - 'open-jaw + separate DAC→DPS': one multi-city ticket for the two long
        legs plus the cheapest COMPATIBLE middle leg (5 Bali nights, visa cap)
    Each entry: name, total, valid (home ≤ Feb 7 and 5 nights), notes, legs."""
    structures = []

    combos = best_combos(flights, top_n=1)
    if combos:
        c = combos[0]
        structures.append({
            "name": "3 one-way tickets",
            "total": c["total"],
            "valid": c["bali_nights"] == IDEAL_BALI_NIGHTS,
            "home": c["home"].strftime("%b %-d") if c["home"] else "?",
            "dhaka_days": c["dhaka_days"],
            "bali_nights": c["bali_nights"],
            "legs": list(c["legs"]),
        })

    # Cheapest option per multi-city variant (plain open-jaws keyed by dates;
    # labeled variants like the Turkish stopover keyed separately)
    best_oj = {}
    for oj in openjaws:
        if not isinstance(oj.get("price_total"), (int, float)):
            continue
        key = (oj.get("label", ""), oj["out_date"], oj["ret_date"])
        if key not in best_oj or oj["price_total"] < best_oj[key]["price_total"]:
            best_oj[key] = oj

    for oj in best_oj.values():
        ret = _date(oj["ret_date"])
        dac_in = _date(oj.get("out_arrive", "")) or (
            _date(oj["out_date"]) + timedelta(days=1))
        # Cheapest middle leg giving exactly 5 Bali nights and a legal Dhaka stay
        candidates = []
        for m in _priced(flights, "DAC→DPS"):
            m_dep, m_arr = _date(m.get("depart", "")), _arrival(m)
            if not (m_dep and m_arr):
                continue
            if (ret - m_arr).days != IDEAL_BALI_NIGHTS:
                continue
            if not 1 <= (m_dep - dac_in).days + 1 <= MAX_DHAKA_DAYS:
                continue
            candidates.append(m)
        if not candidates:
            continue
        mid = min(candidates, key=lambda f: f["price_total"])
        home = ret + timedelta(days=1)  # DPS→BOS lands next day (heuristic)
        structures.append({
            "name": oj.get("label") or "open-jaw ticket + separate DAC→DPS",
            "kind": oj.get("kind", "openjaw"),
            "note": oj.get("note"),
            "total": oj["price_total"] + mid["price_total"],
            "valid": home <= HOME_DEADLINE,
            "home": home.strftime("%b %-d"),
            "dhaka_days": (_date(mid["depart"]) - dac_in).days + 1,
            "bali_nights": IDEAL_BALI_NIGHTS,
            "openjaw": oj,
            "legs": [mid],
        })

    structures.sort(key=lambda s: (not s["valid"], s["total"]))
    return structures[:top_n]


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
