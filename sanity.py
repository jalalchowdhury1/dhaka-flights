"""Self-check watchdog: invariants that turn silent data losses into loud,
user-visible warnings (Telegram + dashboard banner).

Born 2026-07-16, after the exact-5-night pairing rule silently hid a valid
$3,423 open-jaw from the daily message. The scraper had the data; the output
lost it; nothing complained. Every invariant here exists to make that class
of failure impossible to miss:
  1. every scraped multi-city variant must appear as a structure
  2. every leg×date search should have produced at least one fare
  3. a metric that had a value yesterday must not silently become None
  4. big day-over-day swings get called out for a human sanity look
  5. the arrival-date parser must still be parsing (Google phrasing drift)
"""
from scraper import LEGS


def _variant_key(oj):
    return (oj.get("label", ""), oj["out_date"], oj["ret_date"])


def _short(d):
    parts = str(d).replace(",", "").split(" ")
    return f"{parts[0][:3]} {parts[1]}" if len(parts) >= 2 else d


def self_check(flights, openjaws, structures, prev_entry=None,
               sg=None, sg_tickets=None) -> list:
    """Return a list of human-readable warning strings (empty = all good)."""
    warnings = []

    # 0. Singapore-detour variant: if we scraped Singapore data (one-way legs
    # priced, or a multi-city ticket priced) but built NO via-SIN structure,
    # the whole variant vanished silently — surface it (same principle as #1).
    sg_leg_prices = any(
        isinstance(f.get("price_total"), (int, float))
        for f in flights if f.get("route") in ("DAC→SIN", "SIN→DPS"))
    sg_ticket_prices = any(
        isinstance(t.get("price_total"), (int, float)) for t in (sg_tickets or []))
    if (sg_leg_prices or sg_ticket_prices) and not sg:
        warnings.append("Singapore-detour data was scraped but NO via-SIN trip "
                        "was built — check pairing rules in combo.best_singapore")

    # 1. Every priced multi-city variant is represented in structures
    scraped = {}
    for oj in openjaws:
        if isinstance(oj.get("price_total"), (int, float)):
            k = _variant_key(oj)
            if k not in scraped or oj["price_total"] < scraped[k]["price_total"]:
                scraped[k] = oj
    present = {_variant_key(s["openjaw"]) for s in structures if s.get("openjaw")}
    for k, oj in scraped.items():
        if k not in present:
            name = oj.get("label") or (f"open-jaw {_short(oj['out_date'])} + "
                                       f"{_short(oj['ret_date'])}")
            warnings.append(
                f"{name} was scraped at ${oj['price_total']:,} but shows in NO "
                f"structure — pairing rules dropped it, investigate combo.py")

    routes_with_fares = {f["route"] for f in flights
                         if isinstance(f.get("price_total"), (int, float))}
    if len(routes_with_fares) == 3 and not any(
            s.get("kind") == "oneways" for s in structures):
        warnings.append("all 3 legs have fares but no one-way combo was built "
                        "— check date/visa pairing in combo.py")

    # 2. Every leg×date search produced at least one fare
    seen = {(f["route"], f["depart"]) for f in flights}
    for leg in LEGS:
        route = f"{leg['origin']}→{leg['dest']}"
        for date in leg["dates"]:
            if (route, date) not in seen:
                warnings.append(f"no fares captured for {route} {_short(date)} "
                                f"— search failed or parsed 0")

    # 3 + 4. Compare tracked totals against yesterday's history entry
    if prev_entry:
        today = {}
        for s in structures:
            if s["valid"]:
                key = {"openjaw": "openjaw_total", "stopover": "stopover_total",
                       "stopover2": "istanbul2_total",
                       "oneways": "oneway_combo_total"}.get(s.get("kind"))
                if key and key not in today:
                    today[key] = s["total"]
        for s in (sg or []):
            if s["valid"]:
                today.setdefault("singapore_total", s["total"])
        labels = {"openjaw_total": "open-jaw structure",
                  "stopover_total": "Turkish stopover structure",
                  "istanbul2_total": "Istanbul 2-night structure",
                  "singapore_total": "via-Singapore trip",
                  "oneway_combo_total": "one-way combo"}
        for key, label in labels.items():
            prev = prev_entry.get(key)
            cur = today.get(key)
            if isinstance(prev, (int, float)) and cur is None:
                warnings.append(f"{label} was ${prev:,} yesterday but is "
                                f"MISSING today — check the flagged structures "
                                f"and cron.log")
            elif isinstance(prev, (int, float)) and isinstance(cur, (int, float)):
                if prev and abs(cur - prev) / prev > 0.25:
                    warnings.append(f"{label} moved {(cur - prev) / prev:+.0%} "
                                    f"(${prev:,} → ${cur:,}) — big swing, "
                                    f"double-check before acting")

    # 5. Parser drift: arrival dates should parse for most fares
    priced = [f for f in flights if isinstance(f.get("price_total"), (int, float))]
    if priced:
        missing = sum(1 for f in priced if f.get("arrive") in (None, "", "N/A"))
        if missing / len(priced) > 0.3:
            warnings.append(f"arrival date failed to parse on {missing}/"
                            f"{len(priced)} fares — Google may have changed "
                            f"its wording; combo math is falling back to "
                            f"estimates")

    return warnings
