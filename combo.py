"""Trip rules + cheapest-valid-combination pickers.

THE trip since 2026-08-01 (docs/superpowers/specs/2026-08-01-bangkok-singapore-
swap-design.md — Bali retired, "I don't like the tail risk of dengue"):
- BOS → Istanbul 2n → Dhaka → Bangkok 5n + Singapore 2n → BOS, home ≤ Feb 7
- Dhaka stay ≤ 29 days, counting BOTH the arrival and departure day (30-day visa)
- 5 nights in Bangkok (Marriott 5th-night-free); 4 or 6 allowed but ranked below 5
- BOTH city orders (DAC→BKK→SIN→BOS and DAC→SIN→BKK→BOS) are priced nightly and
  the cheaper complete trip wins — Jalal 2026-08-01: "whatever is cheaper"

Uses the arrival dates parsed from Google's result text; when a flight's
arrival didn't parse, falls back to depart+1 day (see _FALLBACK_ARRIVAL_LAG;
short intra-Asia hops usually parse their real arrival). The Bali-era
functions further down are RETIRED but kept working + tested.
"""
import re
from datetime import datetime, timedelta

MAX_DHAKA_DAYS = 29
IDEAL_BKK_NIGHTS = 5                # the Marriott 5th-night-free block
ALLOWED_BKK_NIGHTS = (4, 5, 6)
IDEAL_BALI_NIGHTS = 5               # retired Bali-era constants, used only by
ALLOWED_BALI_NIGHTS = (4, 5, 6)     # the kept-but-retired functions below
HOME_DEADLINE = datetime(2027, 2, 7)

# The two ways the same trip can run after Dhaka (2026-08-01). Ticket ① always
# includes the return from whichever city comes LAST, so each order has its own
# Ticket ① search (ret_city) and its own Ticket ② route pair.
ORDERS = {
    "BKK-first": {
        "label": "Bangkok first",
        "route": "DAC→BKK→SIN→BOS",
        "route1": "DAC→BKK", "route2": "BKK→SIN",
        "ret_city": "SIN",          # Ticket ① comes home from Singapore
        "bkk_position": "middle",   # the 5-night Bangkok block sits between ②'s legs
    },
    "SIN-first": {
        "label": "Singapore first",
        "route": "DAC→SIN→BKK→BOS",
        "route1": "DAC→SIN", "route2": "SIN→BKK",
        "ret_city": "BKK",
        "bkk_position": "final",    # Bangkok is pinned against the Feb 6 return
    },
}

# Airline rules (Jalal 2026-07-18, revised same day): NOTHING is excluded —
# "US-Bangla prices are unbeatable, keep that". CHEAPEST WINS. THAI/Singapore
# Airlines remain a soft preference: when the cheapest pick is a different
# airline, the THAI/SQ upgrade price is surfaced as a note (alt_note).
AIRLINE_EXCLUDE = ()


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
# Dhaka a few nights shorter, ≥2 nights in Singapore en route to Bali. Kept as
# an isolated parallel path so the direct-trip ranking is never destabilized.
# Singapore nights are a FLEX BAND, not a fixed number (Jalal 2026-07-27 +
# 2026-08-01: "minimum of 2 nights" … "isn't a hardline. you can take it up
# to 3 or even 4 if its cheaper in terms of the flight"). A 2-4-night middle
# always outranks one outside the band; price decides within it. An
# out-of-band day survives only flagged so the trip never silently disappears.
MIN_SG_NIGHTS = 2
MAX_SG_NIGHTS = 4


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
            if sg_nights < 1:       # impossible pairing (fly out before arriving)
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
        # STRICT nights from the actual arrival date — an overnight DAC→SIN
        # landing at 4 AM gives 1 real hotel night, not 2 (2026-07-18: the old
        # departure-date fallback overcounted and mislabeled the trip plan).
        sg_nights = (d2 - arr).days
        if sg_nights < 1:           # ret before arrival — a parse error, not a fare
            continue
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
    4/6-night Bali or <2-Singapore-night compromises get flagged instead."""
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
        # Minimum 2 Singapore nights (2026-07-27): ≥2-night middles always
        # outrank shorter ones — even a 5-night-Bali pairing loses to a
        # 4/6-night one if only the latter keeps 2 Singapore nights.
        def _sg_ok(pool):
            return [t for t in pool if t[0]["sg_nights"] >= MIN_SG_NIGHTS]
        pool = _sg_ok(exact) or _sg_ok(near) or exact or near
        if not pool:
            return
        # CHEAPEST WINS (US-Bangla and all). THAI/SQ is a soft preference: if
        # the winner isn't THAI/SQ but such an option exists, note the upsell.
        m, nights, dhaka_days = min(pool, key=lambda t: t[0]["cost"])
        alt_note = None
        pref = [t for t in pool if t[0]["preferred"]]
        if pref and not m["preferred"]:
            pm, _, _ = min(pref, key=lambda t: t[0]["cost"])
            alt_note = (f"THAI/Singapore Airlines option +${pm['cost'] - m['cost']:,.0f} "
                        f"({pm['airlines']})")
        flags = []
        if home > HOME_DEADLINE:
            flags.append(f"home {home.strftime('%b %-d')} — after Feb 7")
        if nights != IDEAL_BALI_NIGHTS:
            flags.append(f"only a {nights}-night Bali pairing today")
        if m["sg_nights"] < MIN_SG_NIGHTS:
            flags.append(f"only a {m['sg_nights']}-night Singapore pairing today")
        # ≥2 Singapore nights are never flagged — price decides between 2 and 3.
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


# ── The one tracked trip, in either order (2026-08-01) ─────────────────────
def _order_middles(flights, tickets2, order_key):
    """Every valid Dhaka→city1→city2 MIDDLE for one order, priced two ways:
      - two one-ways on the order's route pair
      - one multi-city ticket (rows tagged with this order by the scraper)
    Each: {cost, dhaka_out (DAC depart), city2_in (arrival at the second city),
    mid_nights (nights at the FIRST city), kind, legs, ticket}."""
    cfg = ORDERS[order_key]
    middles = []
    for a in _priced(flights, cfg["route1"]):
        a_dep, a_arr = _date(a.get("depart", "")), _arrival(a)
        if not (a_dep and a_arr):
            continue
        for b in _priced(flights, cfg["route2"]):
            b_dep, b_arr = _date(b.get("depart", "")), _arrival(b)
            if not (b_dep and b_arr):
                continue
            mid_nights = (b_dep - a_arr).days
            if mid_nights < 1:      # impossible pairing (fly out before arriving)
                continue
            middles.append({
                "cost": a["price_total"] + b["price_total"],
                "dhaka_out": a_dep, "city2_in": b_arr, "mid_nights": mid_nights,
                "kind": "2 one-ways", "legs": [a, b], "ticket": None,
                "preferred": _is_preferred(a.get("airline")) and _is_preferred(b.get("airline")),
                "airlines": f"{a.get('airline')} + {b.get('airline')}",
            })
    for t in (tickets2 or []):
        if t.get("order") != order_key:
            continue
        if not isinstance(t.get("price_total"), (int, float)) or not _airline_ok(t):
            continue
        d1, d2 = _date(t.get("out_date", "")), _date(t.get("ret_date", ""))
        if not (d1 and d2):
            continue
        arr = _date(t.get("out_arrive", "")) or d1   # leg-1 arrival (may be +1)
        # STRICT nights from the actual arrival date — an overnight first hop
        # landing at 4 AM gives 1 real hotel night, not 2 (2026-07-18 lesson).
        mid_nights = (d2 - arr).days
        if mid_nights < 1:          # ret before arrival — a parse error, not a fare
            continue
        middles.append({
            "cost": t["price_total"], "dhaka_out": d1, "city2_in": d2,
            "mid_nights": mid_nights, "kind": "1 ticket", "legs": [], "ticket": t,
            "preferred": _is_preferred(t.get("airline")),
            "airlines": t.get("airline", ""),
        })
    return middles


def _split_nights(cfg, mid_nights, final_nights):
    """(bkk_nights, sin_nights) — which city got the middle vs final stay
    depends on the order."""
    if cfg["bkk_position"] == "middle":
        return mid_nights, final_nights
    return final_nights, mid_nights


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
    cfg = ORDERS[order_key]
    ojs = [o for o in (openjaws or [])
           if o.get("kind") == "stopover2" and o.get("ret_city") == cfg["ret_city"]
           and isinstance(o.get("price_total"), (int, float)) and _airline_ok(o)]
    if not ojs:
        return None
    oj = min(ojs, key=lambda o: o["price_total"])
    ret = _date(oj["ret_date"])
    dac_in = _date(oj.get("out_arrive", "")) or (_date(oj["out_date"]) + timedelta(days=1))
    if not ret:
        return None

    exact, near = [], []
    for m in _order_middles(flights, tickets2, order_key):
        dhaka_days = (m["dhaka_out"] - dac_in).days + 1
        if not 1 <= dhaka_days <= MAX_DHAKA_DAYS:
            continue
        final_nights = (ret - m["city2_in"]).days
        if final_nights < 1:
            continue
        bkk_nights, sin_nights = _split_nights(cfg, m["mid_nights"], final_nights)
        if bkk_nights not in ALLOWED_BKK_NIGHTS:
            continue
        (exact if bkk_nights == IDEAL_BKK_NIGHTS else near).append(
            (m, bkk_nights, sin_nights, dhaka_days))

    def _sg_ok(pool):
        return [t for t in pool if MIN_SG_NIGHTS <= t[2] <= MAX_SG_NIGHTS]
    pool = _sg_ok(exact) or _sg_ok(near) or exact or near
    if not pool:
        return None
    cost_key = ((lambda t: t[0]["cost"] + hotel_cost(t[2])) if hotel_cost
                else (lambda t: t[0]["cost"]))
    m, bkk_nights, sin_nights, dhaka_days = min(pool, key=cost_key)

    alt_note = None
    pref = [t for t in pool if t[0]["preferred"]]
    if pref and not m["preferred"]:
        pm = min(pref, key=lambda t: t[0]["cost"])[0]
        alt_note = (f"THAI/Singapore Airlines option +${pm['cost'] - m['cost']:,.0f} "
                    f"({pm['airlines']})")

    home = ret + timedelta(days=1)   # return leg lands next day (heuristic)
    flags = []
    if home > HOME_DEADLINE:
        flags.append(f"home {home.strftime('%b %-d')} — after Feb 7")
    if bkk_nights != IDEAL_BKK_NIGHTS:
        flags.append(f"only a {bkk_nights}-night Bangkok pairing today")
    if sin_nights < MIN_SG_NIGHTS:
        flags.append(f"only a {sin_nights}-night Singapore pairing today")
    elif sin_nights > MAX_SG_NIGHTS:
        flags.append(f"a {sin_nights}-night Singapore stay — beyond the "
                     f"{MAX_SG_NIGHTS}-night comfort band")

    return {
        "name": f"{cfg['label']} · {m['kind']} middle",
        "kind": "sg-stopover2", "trip": cfg["route"],
        "order": order_key, "order_label": cfg["label"],
        "total": oj["price_total"] + m["cost"],
        "valid": not flags, "flag": " · ".join(flags) or None,
        "home": home.strftime("%b %-d"),
        "dhaka_days": dhaka_days, "bkk_nights": bkk_nights,
        "sg_nights": sin_nights, "ist_nights": oj.get("ist_nights"),
        "sg_preferred": m["preferred"], "sg_airlines": m["airlines"],
        "alt_note": alt_note,
        "legs": list(m["legs"]), "sg_ticket": m["ticket"],
        "openjaw": oj,
    }


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
    win = dict(trips[0])
    if len(trips) > 1:
        o = trips[1]
        t2_total = (o["sg_ticket"]["price_total"] if o.get("sg_ticket")
                    else sum(f.get("price_total", 0) for f in o.get("legs", [])))
        win["other_order"] = {
            "order": o["order"], "order_label": o["order_label"],
            "total": o["total"], "delta": o["total"] - win["total"],
            "valid": o["valid"], "flag": o["flag"],
            "sg_nights": o["sg_nights"], "bkk_nights": o["bkk_nights"],
            "dhaka_days": o["dhaka_days"],
            "ticket1_total": o["openjaw"]["price_total"],
            "ticket1_airline": o["openjaw"].get("airline"),
            "ticket2_total": t2_total,
            "ticket2_airlines": o.get("sg_airlines"),
            "ticket2_kind": "1 ticket" if o.get("sg_ticket") else "2 one-ways",
        }
    return win


def budget_trip(flights, sg_tickets, main):
    """The 💸 companion (Jalal 2026-07-27: "also present one which is cheaper
    … feel free to squeeze dates in Bangladesh"). Same Ticket ① — and
    therefore the SAME ORDER — as the main trip, same Bangkok block; the
    minimum-2-Singapore-nights rule is WAIVED (≥1 night allowed) and the Dhaka
    departure may shift to whatever scraped date prices best. Returned ONLY
    when strictly cheaper than the main trip — None means today's cheapest
    honest trip IS the main one, and nothing is shown."""
    if not main or not main.get("openjaw") or main.get("order") not in ORDERS:
        return None
    cfg = ORDERS[main["order"]]
    oj = main["openjaw"]
    ret = _date(oj["ret_date"])
    dac_in = _date(oj.get("out_arrive", "")) or (_date(oj["out_date"]) + timedelta(days=1))
    if not ret:
        return None
    exact, near = [], []
    for m in _order_middles(flights, sg_tickets, main["order"]):
        dhaka_days = (m["dhaka_out"] - dac_in).days + 1
        if not 1 <= dhaka_days <= MAX_DHAKA_DAYS:
            continue
        final_nights = (ret - m["city2_in"]).days
        if final_nights < 1:
            continue
        bkk_nights, sin_nights = _split_nights(cfg, m["mid_nights"], final_nights)
        if bkk_nights not in ALLOWED_BKK_NIGHTS:
            continue
        (exact if bkk_nights == IDEAL_BKK_NIGHTS else near).append(
            (m, bkk_nights, sin_nights, dhaka_days))
    pool = exact or near
    if not pool:
        return None
    m, bkk_nights, sin_nights, dhaka_days = min(pool, key=lambda t: t[0]["cost"])
    total = oj["price_total"] + m["cost"]
    if total >= main["total"]:
        return None
    diffs = []
    if sin_nights != main.get("sg_nights"):
        diffs.append(f"{sin_nights} Singapore night"
                     f"{'s' if sin_nights != 1 else ''} instead of "
                     f"{main.get('sg_nights')}")
    dd = dhaka_days - main["dhaka_days"]
    if dd:
        diffs.append(f"{abs(dd)} Dhaka day{'s' if abs(dd) != 1 else ''} "
                     f"{'more' if dd > 0 else 'fewer'} than the main trip")
    if bkk_nights != IDEAL_BKK_NIGHTS:
        diffs.append(f"{bkk_nights}-night Bangkok pairing")
    return {
        "name": f"Budget · same trip, flexible dates · {m['kind']} middle",
        "kind": "sg-budget", "trip": cfg["route"],
        "order": main["order"], "order_label": main.get("order_label"),
        "total": total, "savings": main["total"] - total,
        "valid": True, "flag": None,
        "home": main["home"], "dhaka_days": dhaka_days,
        "bkk_nights": bkk_nights, "sg_nights": sin_nights,
        "ist_nights": main.get("ist_nights"),
        "sg_preferred": m["preferred"], "sg_airlines": m["airlines"],
        "alt_note": None, "diffs": diffs,
        "legs": list(m["legs"]), "sg_ticket": m["ticket"],
        "openjaw": oj,
    }


# ── 🌴 The Bali benchmark, in either order (2026-08-01 late) ────────────────
def bali_watch_trip(flights, bali_t1, fwd_tickets, rev_tickets, main_t1s):
    """The benchmark, mirroring the Bangkok logic: BOTH Bali orders priced,
    the cheaper valid one wins, the loser rides along as `other_bali`.
    Forward = SIN 2n then Bali 5n (its own DPS-return Ticket ①); reversed =
    Bali 5n then SIN 2n, reusing the Bangkok-first SIN→BOS Ticket ① that the
    main scrape already collected."""
    fwd = main_trip_bali(flights, bali_t1, fwd_tickets)
    if fwd:
        fwd = dict(fwd, bali_order="fwd", order_label="Singapore → Bali")
    rev = _bali_rev_trip(rev_tickets, main_t1s)
    trips = [t for t in (fwd, rev) if t]
    if not trips:
        return None
    trips.sort(key=lambda s: (not s["valid"], s["total"]))
    win = dict(trips[0])
    if len(trips) > 1:
        lose = trips[1]
        win["other_bali"] = {"order_label": lose["order_label"],
                             "total": lose["total"],
                             "delta": lose["total"] - win["total"],
                             "valid": lose["valid"], "flag": lose["flag"]}
    return win


def _bali_rev_trip(rev_tickets, main_t1s):
    """Reversed Bali order from a DAC→DPS→SIN one-ticket middle + the
    already-scraped SIN→BOS Ticket ①."""
    ojs = [o for o in main_t1s or []
           if o.get("kind") == "stopover2" and o.get("ret_city") == "SIN"
           and isinstance(o.get("price_total"), (int, float))]
    cands = [t for t in rev_tickets or []
             if isinstance(t.get("price_total"), (int, float))]
    if not (ojs and cands):
        return None
    oj = min(ojs, key=lambda o: o["price_total"])
    ret = _date(oj["ret_date"])
    dac_in = _date(oj.get("out_arrive", "")) or (_date(oj["out_date"]) + timedelta(days=1))
    if not ret:
        return None
    best = None
    for t in cands:
        d1, d2 = _date(t.get("out_date", "")), _date(t.get("ret_date", ""))
        if not (d1 and d2):
            continue
        arr = _date(t.get("out_arrive", "")) or d1
        bali_n = (d2 - arr).days
        sin_n = (ret - d2).days
        dhaka = (d1 - dac_in).days + 1
        if bali_n < 1 or sin_n < 1 or not 1 <= dhaka <= MAX_DHAKA_DAYS:
            continue
        total = oj["price_total"] + t["price_total"]
        if best is not None and total >= best["total"]:
            continue
        flags = []
        if bali_n != IDEAL_BALI_NIGHTS:
            flags.append(f"only a {bali_n}-night Bali pairing today")
        if sin_n < MIN_SG_NIGHTS:
            flags.append(f"only a {sin_n}-night Singapore pairing today")
        best = {
            "name": "Bali first · 1 ticket middle",
            "kind": "sg-stopover2", "trip": "DAC→DPS→SIN→BOS",
            "order": "bali-rev", "order_label": "Bali → Singapore",
            "bali_order": "rev",
            "total": total, "valid": not flags,
            "flag": " · ".join(flags) or None,
            "home": (ret + timedelta(days=1)).strftime("%b %-d"),
            "dhaka_days": dhaka, "bali_nights": bali_n, "sg_nights": sin_n,
            "ist_nights": oj.get("ist_nights"),
            "sg_airlines": t.get("airline", ""), "sg_preferred": False,
            "alt_note": None, "legs": [], "sg_ticket": t, "openjaw": oj,
        }
    return best


# Bali-era versions, RETIRED 2026-08-01 — kept working + tested like the other
# retired paths (re-adding is a call-site swap, and the old history's
# best_detail entries still make sense to code that reads them).
def main_trip_bali(flights, openjaws, sg_tickets):
    """THE trip of the Bali era: BOS → Istanbul 2n → Dhaka → Singapore →
    Bali 5n → BOS (kind 'sg-stopover2' out of best_singapore)."""
    for s in best_singapore(flights, openjaws, sg_tickets or [], top_n=5):
        if s.get("kind") == "sg-stopover2":
            return s
    return None


def budget_trip_bali(flights, sg_tickets, main):
    """Bali-era 💸 companion: same Ticket ①, same Bali block, min-2-SG waived."""
    if not main or not main.get("openjaw"):
        return None
    oj = main["openjaw"]
    ret = _date(oj["ret_date"])
    dac_in = _date(oj.get("out_arrive", "")) or (_date(oj["out_date"]) + timedelta(days=1))
    if not ret:
        return None
    exact, near = [], []
    for m in _sg_middles(flights, sg_tickets):
        dhaka_days = (m["dhaka_out"] - dac_in).days + 1
        if not 1 <= dhaka_days <= MAX_DHAKA_DAYS:
            continue
        nights = (ret - m["bali_in"]).days
        if nights not in ALLOWED_BALI_NIGHTS:
            continue
        (exact if nights == IDEAL_BALI_NIGHTS else near).append((m, nights, dhaka_days))
    pool = exact or near
    if not pool:
        return None
    m, nights, dhaka_days = min(pool, key=lambda t: t[0]["cost"])
    total = oj["price_total"] + m["cost"]
    if total >= main["total"]:
        return None
    diffs = []
    if m["sg_nights"] != main.get("sg_nights"):
        diffs.append(f"{m['sg_nights']} Singapore night"
                     f"{'s' if m['sg_nights'] != 1 else ''} instead of "
                     f"{main.get('sg_nights')}")
    dd = dhaka_days - main["dhaka_days"]
    if dd:
        diffs.append(f"{abs(dd)} Dhaka day{'s' if abs(dd) != 1 else ''} "
                     f"{'more' if dd > 0 else 'fewer'} than the main trip")
    if nights != IDEAL_BALI_NIGHTS:
        diffs.append(f"{nights}-night Bali pairing")
    return {
        "name": f"Budget · same trip, flexible dates · {m['kind']} middle",
        "kind": "sg-budget", "trip": "via-SIN",
        "total": total, "savings": main["total"] - total,
        "valid": True, "flag": None,
        "home": main["home"], "dhaka_days": dhaka_days,
        "bali_nights": nights, "sg_nights": m["sg_nights"],
        "ist_nights": main.get("ist_nights"),
        "sg_preferred": m["preferred"], "sg_airlines": m["airlines"],
        "alt_note": None, "diffs": diffs,
        "legs": list(m["legs"]), "sg_ticket": m["ticket"],
        "openjaw": oj,
    }


def ticket1_options(openjaws, chosen=None, top_n=8) -> list:
    """Every airline that sells Ticket ① on the tracked dates, cheapest first,
    with the price gap against the one the trip is priced on."""
    base = (chosen or {}).get("price_total")
    out_d = (chosen or {}).get("out_date")
    ret_d = (chosen or {}).get("ret_date")
    ret_city = (chosen or {}).get("ret_city")
    opts = []
    for oj in openjaws or []:
        if oj.get("kind") != "stopover2":
            continue
        if not isinstance(oj.get("price_total"), (int, float)):
            continue
        if out_d and (oj.get("out_date") != out_d or oj.get("ret_date") != ret_d):
            continue
        # Same ticket = same return city too — the other order's Ticket ① is a
        # different purchase, surfaced via other_order, not as an "alternative".
        if ret_city and oj.get("ret_city") and oj["ret_city"] != ret_city:
            continue
        opts.append({
            "kind": "1 ticket",
            "airline": oj.get("airline", "?"),
            "price": oj["price_total"],
            "stops": oj.get("stops"), "duration": oj.get("duration"),
            "layovers": oj.get("layovers"), "link": oj.get("link"),
            "delta": (oj["price_total"] - base) if isinstance(base, (int, float)) else None,
            "chosen": isinstance(base, (int, float)) and oj["price_total"] == base,
        })
    opts.sort(key=lambda o: o["price"])
    return _dedupe_options(opts)[:top_n]


def ticket2_options(flights, sg_tickets, main, top_n=10) -> list:
    """Alternatives to whatever airline won the Ticket ② middle, ON THE SAME
    DATES (Jalal 2026-07-25: "how much more is it").

    Two shapes are comparable and both are listed:
      · '1 ticket'  — a multi-city fare on the trip's order
      · '2 tickets' — the two one-way legs bought separately, same two dates
    Same dates ⇒ the Singapore and Bangkok nights are identical, so the price
    gap is the whole story. Routes come from the trip's ORDER; Bali-era mains
    (no order key) keep the old DAC→SIN→DPS routes so history still renders."""
    if not main:
        return []
    cfg = ORDERS.get(main.get("order"))
    r1, r2 = (cfg["route1"], cfg["route2"]) if cfg else ("DAC→SIN", "SIN→DPS")
    t = main.get("sg_ticket")
    legs = {f.get("route"): f for f in (main.get("legs") or [])}
    if t:
        out_d, ret_d, base = t.get("out_date"), t.get("ret_date"), t.get("price_total")
    else:
        a, b = legs.get(r1), legs.get(r2)
        if not (a and b):
            return []
        out_d, ret_d = a.get("depart"), b.get("depart")
        base = (a.get("price_total") or 0) + (b.get("price_total") or 0)

    opts = []
    for x in sg_tickets or []:
        if not isinstance(x.get("price_total"), (int, float)):
            continue
        if cfg and x.get("order") and x["order"] != main["order"]:
            continue
        if x.get("out_date") != out_d or x.get("ret_date") != ret_d:
            continue
        opts.append({
            "kind": "1 ticket", "airline": x.get("airline", "?"),
            "price": x["price_total"], "stops": x.get("stops"),
            "duration": x.get("duration"), "layovers": x.get("layovers"),
            "link": x.get("link"),
            "depart_time": x.get("out_depart_time"), "arrive_time": x.get("out_arrive_time"),
            "chosen": bool(t) and x["price_total"] == base and x.get("airline") == t.get("airline"),
        })

    for a in _priced(flights, r1):
        if a.get("depart") != out_d:
            continue
        for b in _priced(flights, r2):
            if b.get("depart") != ret_d:
                continue
            opts.append({
                "kind": "2 tickets",
                "airline": f"{a.get('airline')} + {b.get('airline')}",
                "price": a["price_total"] + b["price_total"],
                "stops": f"{a.get('stops')} / {b.get('stops')}",
                "duration": f"{a.get('duration')} / {b.get('duration')}",
                # Two separate purchases ⇒ two booking links (one Book button
                # per ticket in the UI; a single button would only buy leg 1).
                "layovers": None, "link": a.get("link"), "link2": b.get("link"),
                "depart_time": a.get("depart_time"), "arrive_time": a.get("arrive_time"),
                "chosen": not t and (a["price_total"] + b["price_total"]) == base,
            })

    opts.sort(key=lambda o: o["price"])
    opts = _dedupe_options(opts)[:top_n]
    for o in opts:
        o["delta"] = (o["price"] - base) if isinstance(base, (int, float)) else None
    return opts


def _dedupe_options(opts) -> list:
    """One row per (airline, price) — Google lists the same fare on several
    departure times and the table shouldn't repeat it."""
    seen, out = set(), []
    for o in opts:
        key = (o["kind"], o["airline"], o["price"])
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out
