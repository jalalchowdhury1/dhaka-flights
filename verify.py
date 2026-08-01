"""Independent post-build verification (2026-08-01 evening, Jalal: "once done
verify. Multiple times. take different perspectives.").

Three perspectives, run against EVERY night's payload before it is sent:

  1. RECOMPUTE — a brute-force cheapest-strict-shape trip search written
     independently of combo.py (same spec, different code). The totals must
     agree, per order; a flagged day must really have no strict-shape option.
  2. ARITHMETIC — every displayed number must be self-consistent: ① + ② sum
     to the total, the other-order and Bali deltas are right, the history
     entry mirrors the trip, the budget companion really is cheaper.
  3. CONTRACT — an unflagged trip must be the trip Jalal asked for:
     2 Istanbul / 5 Bangkok / 2-4 Singapore (flex band) nights, and the
     hotel card's nights must match the flights above it.

Findings ride into the Telegram/self-check block; a clean pass adds a quiet
footer line. This module must NEVER raise into the run (run_daily wraps it).
"""
from datetime import datetime, timedelta

SG_BAND = (2, 4)
BKK_IDEAL = 5
MAX_DHAKA = 29

_ORDER_SPEC = {
    "BKK-first": ("DAC→BKK", "BKK→SIN", "SIN", True),
    "SIN-first": ("DAC→SIN", "SIN→BKK", "BKK", False),
}


def _d(s):
    try:
        return datetime.strptime(s, "%B %d, %Y")
    except (ValueError, TypeError):
        return None


def _arr(f):
    a = _d(f.get("arrive", ""))
    if a:
        return a
    dep = _d(f.get("depart", ""))
    return dep + timedelta(days=1) if dep else None


def _priced(x):
    return isinstance(x.get("price_total"), (int, float))


def _middles(flights, tickets2, r1, r2, order_key):
    out = []
    legs1 = [f for f in flights if f.get("route") == r1 and _priced(f)]
    legs2 = [f for f in flights if f.get("route") == r2 and _priced(f)]
    for a in legs1:
        a_arr = _arr(a)
        a_dep = _d(a.get("depart", ""))
        if not (a_arr and a_dep):
            continue
        for b in legs2:
            b_dep = _d(b.get("depart", ""))
            if not b_dep:
                continue
            mid = (b_dep - a_arr).days
            if mid < 1:
                continue
            out.append({"cost": a["price_total"] + b["price_total"],
                        "dhaka_out": a_dep, "mid": mid,
                        "c2_in": _arr(b) or b_dep})
    for t in tickets2 or []:
        if t.get("order") != order_key or not _priced(t):
            continue
        d1, d2 = _d(t.get("out_date", "")), _d(t.get("ret_date", ""))
        if not (d1 and d2):
            continue
        arr = _d(t.get("out_arrive", "")) or d1
        mid = (d2 - arr).days
        if mid < 1:
            continue
        out.append({"cost": t["price_total"], "dhaka_out": d1,
                    "mid": mid, "c2_in": d2})
    return out


def strict_best(flights, tickets1, tickets2, order_key):
    """Cheapest trip total in the EXACT asked-for shape for one order
    (5 BKK nights, 2-4 SIN nights, visa + deadline), or None."""
    r1, r2, ret_city, bkk_is_mid = _ORDER_SPEC[order_key]
    ojs = [o for o in tickets1 or []
           if o.get("ret_city") == ret_city and _priced(o)]
    if not ojs:
        return None
    oj = min(ojs, key=lambda o: o["price_total"])
    ret, dac_in = _d(oj.get("ret_date", "")), _d(oj.get("out_arrive", ""))
    if not (ret and dac_in):
        return None
    best = None
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
        if best is None or total < best:
            best = total
    return best


def verify_payload(payload, flights, tickets1, sg_tickets):
    """Return a list of human-readable discrepancy strings (empty = verified)."""
    problems = []
    main = payload.get("main")
    if not main:
        return []                     # nothing priced; sanity already screams

    # ── 1. RECOMPUTE ────────────────────────────────────────────────────────
    claimed = {main.get("order"): (main.get("total"), main.get("valid"))}
    other = main.get("other_order") or {}
    if other:
        claimed[other.get("order")] = (other.get("total"), other.get("valid"))
    for order in _ORDER_SPEC:
        strict = strict_best(flights, tickets1, sg_tickets, order)
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
            elif total != strict:
                problems.append(f"re-check: {order} total ${total:,} ≠ "
                                f"independent recompute ${strict:,}")
        elif strict is not None and strict <= total:
            problems.append(f"re-check: {order} is flagged, but a strict-shape "
                            f"trip exists at ${strict:,}")
    if (other and other.get("valid") and main.get("valid")
            and other["total"] < main["total"]):
        problems.append("re-check: the losing order is cheaper than the winner")

    # ── 2. ARITHMETIC ───────────────────────────────────────────────────────
    oj = main.get("openjaw") or {}
    t2 = main.get("sg_ticket")
    t2_cost = (t2["price_total"] if t2 else
               sum(f.get("price_total", 0) for f in main.get("legs") or []))
    if oj and main.get("total") != (oj.get("price_total") or 0) + t2_cost:
        problems.append("re-check: Ticket ① + Ticket ② don't sum to the trip total")
    if other and other.get("delta") != other.get("total") - main.get("total"):
        problems.append("re-check: the other-order Δ is wrong")
    bali = payload.get("bali")
    if (bali and isinstance(bali.get("delta_vs_main"), (int, float))
            and bali["delta_vs_main"] != bali["total"] - main["total"]):
        problems.append("re-check: the Bali benchmark Δ is wrong")
    budget = payload.get("budget")
    if budget and budget.get("total", 0) >= main.get("total", 0):
        problems.append("re-check: the budget trip isn't cheaper than the main trip")
    hist = payload.get("history") or []
    if hist and hist[-1].get("main_total") != main.get("total"):
        problems.append("re-check: the history entry doesn't mirror the trip total")

    # ── 3. CONTRACT ─────────────────────────────────────────────────────────
    if main.get("valid"):
        if main.get("ist_nights") not in (None, 2):
            problems.append("re-check: Istanbul nights ≠ 2 on an unflagged day")
        if main.get("bkk_nights") != BKK_IDEAL:
            problems.append("re-check: Bangkok nights ≠ 5 on an unflagged day")
        sg = main.get("sg_nights")
        if isinstance(sg, int) and not SG_BAND[0] <= sg <= SG_BAND[1]:
            problems.append("re-check: Singapore nights outside the 2-4 band "
                            "on an unflagged day")
    hotel = payload.get("hotel")
    if (hotel and isinstance(hotel.get("nights"), int)
            and hotel["nights"] != main.get("bkk_nights")):
        problems.append("re-check: the hotel card's nights don't match the "
                        "trip's Bangkok nights")
    return problems
