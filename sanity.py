"""Self-check watchdog: invariants that turn silent data losses into loud,
user-visible warnings (Telegram + dashboard banner).

Born 2026-07-16, after the exact-5-night pairing rule silently hid a valid
$3,423 open-jaw from the daily message. The scraper had the data; the output
lost it; nothing complained.

Rewritten 2026-07-25 when the tracker narrowed to ONE trip. That narrowing
removed the safety net of "some other structure will still be there", so these
invariants matter more than before:
  1. Ticket ① priced but no trip built  → pairing rules ate the trip
  2. Ticket ① not priced at all         → the run has nothing to say
  3. every leg×date and every Ticket ② date pair produced a fare
  4. a metric that had a value yesterday must not silently become None
  5. big day-over-day swings get called out for a human sanity look
  6. the arrival-date parser must still be parsing (Google phrasing drift)
  7. the trip's shape (2 IST / 2 SG / 5 Bali nights) is what was asked for
"""
from scraper import LEGS, SG_TICKET_SEARCHES

TRACKED = {
    "main_total": "MAIN trip total",
    "ticket1_total": "Ticket ① (Boston–Istanbul–Dhaka + Bali–Boston)",
    "ticket2_total": "Ticket ② (Dhaka–Singapore–Bali)",
}


def _short(d):
    parts = str(d).replace(",", "").split(" ")
    return f"{parts[0][:3]} {parts[1]}" if len(parts) >= 2 else d


def _priced(items):
    return [x for x in items if isinstance(x.get("price_total"), (int, float))]


def self_check(flights, openjaws, main, prev_entry=None, sg_tickets=None) -> list:
    """Return a list of human-readable warning strings (empty = all good)."""
    warnings = []
    tickets1 = _priced([o for o in (openjaws or []) if o.get("kind") == "stopover2"])
    tickets2 = _priced(sg_tickets or [])
    sg_legs = _priced([f for f in flights
                       if f.get("route") in ("DAC→SIN", "SIN→DPS")])

    # 1 + 2. The trip itself
    if not tickets1:
        warnings.append("Ticket ① (BOS→IST→DAC + DPS→BOS) returned NO fares — "
                        "the trip can't be priced today; check cron.log and "
                        "debug_last_zero.txt")
    elif not main:
        cheapest = min(t["price_total"] for t in tickets1)
        warnings.append(f"Ticket ① was scraped from ${cheapest:,} but NO trip was "
                        f"built — a pairing rule dropped it, investigate "
                        f"combo.best_singapore")
    if (tickets2 or sg_legs) and not main:
        warnings.append("Dhaka→Singapore→Bali fares exist but no trip used them "
                        "— check the Bali-night / visa-window pairing rules")

    # 3. Coverage: every one-way leg×date and every Ticket ② date pair
    seen = {(f["route"], f["depart"]) for f in flights}
    for leg in LEGS:
        route = f"{leg['origin']}→{leg['dest']}"
        for date in leg["dates"]:
            if (route, date) not in seen:
                warnings.append(f"no fares captured for {route} {_short(date)} "
                                f"— search failed or parsed 0")
    seen_pairs = {(t.get("out_date"), t.get("ret_date")) for t in (sg_tickets or [])}
    for d1, d2 in SG_TICKET_SEARCHES:
        if (d1, d2) not in seen_pairs:
            warnings.append(f"no Ticket ② fares for {_short(d1)} + {_short(d2)} "
                            f"— search failed or parsed 0")

    # 4 + 5. Compare today's tracked totals against yesterday's history entry
    if prev_entry:
        today = {
            "main_total": main.get("total") if main else None,
            "ticket1_total": ((main or {}).get("openjaw") or {}).get("price_total"),
            "ticket2_total": ((main or {}).get("sg_ticket") or {}).get("price_total"),
        }
        if main and today["ticket2_total"] is None:
            today["ticket2_total"] = sum(
                f.get("price_total", 0) for f in main.get("legs", [])) or None
        for key, label in TRACKED.items():
            prev = prev_entry.get(key)
            if prev is None and key == "main_total":
                prev = prev_entry.get("combined_total")   # pre-2026-07-25 name
            cur = today.get(key)
            if isinstance(prev, (int, float)) and cur is None:
                warnings.append(f"{label} was ${prev:,} yesterday but is MISSING "
                                f"today — check cron.log")
            elif isinstance(prev, (int, float)) and isinstance(cur, (int, float)):
                if prev and abs(cur - prev) / prev > 0.25:
                    warnings.append(f"{label} moved {(cur - prev) / prev:+.0%} "
                                    f"(${prev:,} → ${cur:,}) — big swing, "
                                    f"double-check before acting")

    # 6. Parser drift: arrival dates should parse for most fares
    priced = _priced(flights)
    if priced:
        missing = sum(1 for f in priced if f.get("arrive") in (None, "", "N/A"))
        if missing / len(priced) > 0.3:
            warnings.append(f"arrival date failed to parse on {missing}/"
                            f"{len(priced)} fares — Google may have changed its "
                            f"wording; combo math is falling back to estimates")

    # 7. Shape drift — the trip Jalal asked for is 2 / 2 / 5 nights. Cheapest
    # still wins (a 1-night Singapore ticket is allowed to be the answer), but
    # he should never discover it at the airport.
    if main:
        for got, want, what in ((main.get("ist_nights"), 2, "Istanbul"),
                                (main.get("sg_nights"), 2, "Singapore"),
                                (main.get("bali_nights"), 5, "Bali")):
            if isinstance(got, int) and got != want:
                warnings.append(f"today's cheapest trip gives {got} {what} "
                                f"night{'s' if got != 1 else ''}, not {want}")

    return warnings
