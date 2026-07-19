"""Pick the cheapest valid 3-leg combination (BOS→DAC, DAC→DPS, DPS→BOS).

Trip rules (docs/superpowers/specs/2026-07-15-three-leg-trip-redesign-design.md):
- Dhaka stay ≤ 29 days, counting BOTH the arrival and departure day (30-day visa)
- 5 nights in Bali (Marriott 5th-night-free); 4 or 6 allowed but ranked below 5
- Back in Boston on/before Feb 7, 2027

Uses the arrival dates parsed from Google's result text; when a flight's
arrival didn't parse, falls back to depart+1 day for long-haul legs
(BOS→DAC, DPS→BOS) and same-day for DAC→DPS.
"""
import re
from datetime import datetime, timedelta

MAX_DHAKA_DAYS = 29
IDEAL_BALI_NIGHTS = 5
ALLOWED_BALI_NIGHTS = (4, 5, 6)
HOME_DEADLINE = datetime(2027, 2, 7)

# Airline rules (Jalal 2026-07-18): US-Bangla is EXCLUDED everywhere; THAI and
# Singapore Airlines are PREFERRED on the Singapore legs — a preferred-airline
# middle wins even over a cheaper non-preferred one (the cheaper option is
# surfaced as a note, never silently dropped).
AIRLINE_EXCLUDE = ("us-bangla",)


def _airline_ok(f) -> bool:
    a = (f.get("airline") or "").lower()
    return not any(x in a for x in AIRLINE_EXCLUDE)


def _is_preferred(airline: str) -> bool:
    """True only if EVERY carrier named in the string is THAI or Singapore
    Airlines — "Malaysia Airlines and Singapore Airlines" is NOT preferred
    (caught live 2026-07-18: substring matching paid +$1,328 for a half-MH
    ticket). Exact-ish tokens avoid "Thai Lion Air"/"Thai AirAsia" false hits."""
    a = (airline or "").strip().lower()
    if not a:
        return False
    parts = [p.strip() for p in re.split(r",|\band\b|\+", a) if p.strip()]
    return all(p == "thai" or "thai airways" in p or "singapore airlines" in p
               for p in parts)

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
            and isinstance(f.get("price_total"), (int, float))
            and _airline_ok(f)]


def cheapest_by_leg(flights) -> dict:
    """Cheapest single option per route, ignoring combo constraints."""
    best = {}
    for route in ("BOS→DAC", "DAC→DPS", "DPS→BOS"):
        options = _priced(flights, route)
        if options:
            best[route] = min(options, key=lambda f: f["price_total"])
    return best


def best_structures(flights, openjaws, top_n=8) -> list:
    # top_n must exceed the number of scraped variants (oneways + 2 open-jaws +
    # 3 stopover variants = 6 today) or a flagged variant silently truncates off
    # the end and sanity invariant #1 fires (seen live 2026-07-18 at top_n=4).
    """Compare ticketing structures and return them cheapest-first:
      - 'three one-ways': the classic best_combos winner
      - 'open-jaw + separate DAC→DPS': one multi-city ticket for the two long
        legs plus the cheapest COMPATIBLE middle leg (5 Bali nights, visa cap)
    Each entry: name, total, valid (home ≤ Feb 7 and 5 nights), notes, legs."""
    structures = []

    combos = best_combos(flights, top_n=1)
    if combos:
        c = combos[0]
        ok = c["bali_nights"] == IDEAL_BALI_NIGHTS
        structures.append({
            "name": "3 one-way tickets",
            "kind": "oneways",
            "total": c["total"],
            "valid": ok,
            "flag": None if ok else f"only a {c['bali_nights']}-night Bali pairing today",
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
        # Cheapest middle leg with a legal Dhaka stay; prefer exactly 5 Bali
        # nights but NEVER drop the structure when only 4/6-night pairings
        # exist — flag the compromise instead (2026-07-16: the exact-5 rule
        # silently hid a valid $3,423 open-jaw from the daily message).
        exact, near = [], []
        for m in _priced(flights, "DAC→DPS"):
            m_dep, m_arr = _date(m.get("depart", "")), _arrival(m)
            if not (m_dep and m_arr):
                continue
            nights = (ret - m_arr).days
            if nights not in ALLOWED_BALI_NIGHTS:
                continue
            if not 1 <= (m_dep - dac_in).days + 1 <= MAX_DHAKA_DAYS:
                continue
            (exact if nights == IDEAL_BALI_NIGHTS else near).append((m, nights))
        pool = exact or near
        if not pool:
            continue
        mid, nights = min(pool, key=lambda t: t[0]["price_total"])
        home = ret + timedelta(days=1)  # DPS→BOS lands next day (heuristic)
        flags = []
        if home > HOME_DEADLINE:
            flags.append(f"home {home.strftime('%b %-d')} — after Feb 7")
        if nights != IDEAL_BALI_NIGHTS:
            flags.append(f"only a {nights}-night Bali pairing today")
        structures.append({
            "name": oj.get("label") or "open-jaw ticket + separate DAC→DPS",
            "kind": oj.get("kind", "openjaw"),
            "note": oj.get("note"),
            "total": oj["price_total"] + mid["price_total"],
            "valid": not flags,
            "flag": " · ".join(flags) or None,
            "home": home.strftime("%b %-d"),
            "dhaka_days": (_date(mid["depart"]) - dac_in).days + 1,
            "bali_nights": nights,
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


# ── Singapore-detour variant (2026-07-18) ──────────────────────────────────
# Dhaka a few nights shorter, 1–3 nights in Singapore en route to Bali. Kept as
# an isolated parallel path so the direct-trip ranking is never destabilized.
# Singapore nights are FLEXIBLE — price decides, no flag (per Jalal 2026-07-18:
# "the only constant needs to be 5 nights in Bali").
ALLOWED_SG_NIGHTS = (1, 2, 3)


def _sg_middles(flights, sg_tickets):
    """Every valid Dhaka→Singapore→Bali MIDDLE, priced two ways:
      - two one-ways: DAC→SIN + SIN→DPS
      - one multi-city ticket: DAC→SIN→DPS (from sg_tickets)
    Each: {cost, dhaka_out (DAC depart), bali_in (Bali arrival), sg_nights,
    kind, legs (for display), ticket}."""
    middles = []
    for a in _priced(flights, "DAC→SIN"):
        a_dep, a_arr = _date(a.get("depart", "")), _arrival(a)
        if not (a_dep and a_arr):
            continue
        for b in _priced(flights, "SIN→DPS"):
            b_dep, b_arr = _date(b.get("depart", "")), _arrival(b)
            if not (b_dep and b_arr):
                continue
            sg_nights = (b_dep - a_arr).days
            if sg_nights not in ALLOWED_SG_NIGHTS:
                continue
            middles.append({
                "cost": a["price_total"] + b["price_total"],
                "dhaka_out": a_dep, "bali_in": b_arr, "sg_nights": sg_nights,
                "kind": "2 one-ways", "legs": [a, b], "ticket": None,
                "preferred": _is_preferred(a.get("airline")) and _is_preferred(b.get("airline")),
                "airlines": f"{a.get('airline')} + {b.get('airline')}",
            })
    for t in (sg_tickets or []):
        if not isinstance(t.get("price_total"), (int, float)) or not _airline_ok(t):
            continue
        d1, d2 = _date(t.get("out_date", "")), _date(t.get("ret_date", ""))
        if not (d1 and d2):
            continue
        arr = _date(t.get("out_arrive", "")) or d1  # DAC→SIN arrival (may be +1)
        sg_nights = (d2 - arr).days
        if sg_nights not in ALLOWED_SG_NIGHTS:
            sg_nights = (d2 - d1).days
        middles.append({
            "cost": t["price_total"], "dhaka_out": d1, "bali_in": d2,
            "sg_nights": sg_nights, "kind": "1 ticket", "legs": [], "ticket": t,
            "preferred": _is_preferred(t.get("airline")),
            "airlines": t.get("airline", ""),
        })
    return middles


def best_singapore(flights, openjaws, sg_tickets, top_n=3) -> list:
    """Via-Singapore trip structures, cheapest-first. Long legs = two one-ways
    (BOS→DAC + DPS→BOS) OR a direct open-jaw ticket; the Singapore middle is
    whichever of {two one-ways, one ticket} is cheaper & valid. Entries mirror
    best_structures shape, tagged trip='via-SIN'. Never drops a valid trip:
    only 4/6-night Bali or 1/3 Singapore-night compromises get flagged."""
    middles = _sg_middles(flights, sg_tickets)
    if not middles:
        return []
    structures = []

    def _consider(name, kind, long_cost, dac_in, ret, home, extra_legs,
                  openjaw=None, ist_nights=None):
        exact, near = [], []
        for m in middles:
            dhaka_days = (m["dhaka_out"] - dac_in).days + 1
            if not 1 <= dhaka_days <= MAX_DHAKA_DAYS:
                continue
            nights = (ret - m["bali_in"]).days
            if nights not in ALLOWED_BALI_NIGHTS:
                continue
            (exact if nights == IDEAL_BALI_NIGHTS else near).append((m, nights, dhaka_days))
        pool = exact or near
        if not pool:
            return
        # THAI / Singapore Airlines preferred on the SG legs: a preferred-airline
        # middle wins; a cheaper non-preferred one becomes a note, never a switch.
        pref = [t for t in pool if t[0]["preferred"]]
        m, nights, dhaka_days = min(pref or pool, key=lambda t: t[0]["cost"])
        alt_note = None
        if pref:
            cheapest_any, _, _ = min(pool, key=lambda t: t[0]["cost"])
            if cheapest_any["cost"] < m["cost"]:
                alt_note = (f"${m['cost'] - cheapest_any['cost']:,.0f} cheaper on "
                            f"{cheapest_any['airlines']} if airline-flexible")
        flags = []
        if home > HOME_DEADLINE:
            flags.append(f"home {home.strftime('%b %-d')} — after Feb 7")
        if nights != IDEAL_BALI_NIGHTS:
            flags.append(f"only a {nights}-night Bali pairing today")
        # Singapore nights (1–3) are deliberately NOT flagged — price decides.
        structures.append({
            "name": f"{name} · {m['kind']} middle",
            "kind": kind, "trip": "via-SIN",
            "total": long_cost + m["cost"],
            "valid": not flags, "flag": " · ".join(flags) or None,
            "home": home.strftime("%b %-d"),
            "dhaka_days": dhaka_days, "bali_nights": nights,
            "sg_nights": m["sg_nights"], "ist_nights": ist_nights,
            "sg_preferred": m["preferred"], "sg_airlines": m["airlines"],
            "alt_note": alt_note,
            "legs": list(extra_legs) + list(m["legs"]),
            "sg_ticket": m["ticket"],
            **({"openjaw": openjaw} if openjaw else {}),
        })

    # Long legs as two one-ways
    for a in _priced(flights, "BOS→DAC"):
        dac_in = _arrival(a)
        if not dac_in:
            continue
        for c in _priced(flights, "DPS→BOS"):
            c_dep = _date(c.get("depart", ""))
            if not c_dep:
                continue
            home = _arrival(c) or (c_dep + timedelta(days=1))
            _consider("via Singapore · one-ways", "sg-oneways",
                      a["price_total"] + c["price_total"], dac_in, c_dep, home, [a, c])

    # Long legs as ONE ticket: the plain open-jaw, OR an Istanbul-stopover
    # ticket — the latter builds the COMBINED trip (Istanbul + Singapore),
    # which is the trip Jalal mainly tracks (2026-07-18).
    best_oj = {}
    for oj in openjaws:
        if not isinstance(oj.get("price_total"), (int, float)) or not _airline_ok(oj):
            continue
        okind = oj.get("kind") or "openjaw"
        key = (okind, oj.get("label", ""), oj["out_date"], oj["ret_date"])
        if key not in best_oj or oj["price_total"] < best_oj[key]["price_total"]:
            best_oj[key] = oj
    for oj in best_oj.values():
        ret = _date(oj["ret_date"])
        dac_in = _date(oj.get("out_arrive", "")) or (_date(oj["out_date"]) + timedelta(days=1))
        if not ret:
            continue
        okind = oj.get("kind") or "openjaw"
        if okind == "openjaw":
            name, kind, ist_n = "via Singapore · open-jaw", "sg-openjaw", None
        else:
            name = f"{oj.get('label', 'stopover')} + Singapore"
            kind = f"sg-{okind}"                       # sg-stopover / sg-stopover2
            ist_n = oj.get("ist_nights")
        _consider(name, kind, oj["price_total"], dac_in, ret,
                  ret + timedelta(days=1), [], openjaw=oj, ist_nights=ist_n)

    structures.sort(key=lambda s: (not s["valid"], s["total"]))
    seen, deduped = set(), []
    for s in structures:            # cheapest per kind → at most one per kind
        if s["kind"] in seen:
            continue
        seen.add(s["kind"])
        deduped.append(s)
    return deduped[:top_n]
