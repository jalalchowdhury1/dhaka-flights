"""Ticket ① convenience preference (2026-08-23).

Until tonight the engine chose Ticket ① purely by price. Jalal, looking at
Air France $3,625 (1 stop, 15 h 30, Google-stitched "separate tickets") next
to Turkish $4,003 (nonstop, 9 h 20): "for $300-something we should definitely
take the direct flight to Istanbul." So a nonstop BOS→IST is worth
NONSTOP_WORTH to the family, and the pick minimises

    score(o) = price_total − (NONSTOP_WORTH if o is nonstop else 0)

while the trip TOTAL, the history and the buy signal stay on the REAL fare.
The multi-city selection page describes leg 1 only, so `stops` IS the
BOS→IST leg — exactly the one that matters. The knob lives here the way
stay_value.EXTRA_NIGHT_WORTH and alerts.BUY_BELOW live in theirs;
verify.py re-implements the rule with its own constant — keep them in sync.
"""

NONSTOP_WORTH = 500     # $ (whole family) a nonstop BOS→IST is worth over a 1-stop


def is_nonstop(o):
    return str((o or {}).get("stops") or "").strip().lower() == "nonstop"


def ticket1_score(o):
    """Lower is better. Never changes the price the trip is priced at."""
    return o["price_total"] - (NONSTOP_WORTH if is_nonstop(o) else 0)


def pick_note(chosen, cheapest):
    """One human line for the site/brief when the pick is NOT the cheapest."""
    premium = chosen["price_total"] - cheapest["price_total"]
    return (f"nonstop {chosen.get('airline')} preferred over "
            f"{cheapest.get('airline')} ${cheapest['price_total']:,} "
            f"({cheapest.get('stops')}, {cheapest.get('duration')}): +${premium:,}, "
            f"under the ${NONSTOP_WORTH:,} nonstop-worth knob")
