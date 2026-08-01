"""Buy-signal + change-detection layer (Jalal, 2026-07-25).

The rule this file encodes, agreed explicitly: BEFORE the book-by date, price
decides; AFTER it, the date decides. Three stages:

  watch   (now → Sep 1)   quiet nightly context line; alert only on a new
                          all-time low or the buy zone
  window  (Sep 1 → 20)    + countdown line; buy-zone hit leads 🚨 BOOK NOW
  past    (after Sep 20)  every message leads 🚨 book-this-week — the price
                          threshold retires; waiting past his historical
                          window (booked Sep 18 '24 · Sep 23 '25) is the
                          known losing move

All knobs live here; changing the target is a one-line edit.
"""
import datetime

BUY_BELOW = 4500                       # whole trip, all 3 travelers
WINDOW_OPENS = datetime.date(2026, 9, 1)
BOOK_BY = datetime.date(2026, 9, 20)
BOOKED_HISTORY = "booked Sep 18 '24 · Sep 23 '25"

# History entries before this date describe RETIRED trips — their totals
# aren't comparable to the tracked trip. Moved 2026-07-18 → 2026-08-01 when
# Bali was swapped for Bangkok: the Bali-era totals are a different trip and
# must not pollute the new trip's rank / all-time-low context.
TRIP_TRACKED_SINCE = "2026-08-01"


def _main(entry) -> float:
    """The trip total under either its current or pre-2026-07-25 key."""
    v = (entry or {}).get("main_total")
    return v if v is not None else (entry or {}).get("combined_total")


def _mains(history) -> list:
    return [(h["date"], _main(h)) for h in history or []
            if _main(h) is not None and h.get("date", "") >= TRIP_TRACKED_SINCE]


def _short(iso: str) -> str:
    try:
        return datetime.date.fromisoformat(iso).strftime("%b %-d")
    except (ValueError, TypeError):
        return str(iso)


def stage(today: datetime.date) -> str:
    if today >= BOOK_BY:
        return "past"
    if today >= WINDOW_OPENS:
        return "window"
    return "watch"


def headlines(entry, history, today: datetime.date) -> list:
    """Lines that LEAD the Telegram message (empty = nothing alert-worthy)."""
    lines = []
    cur = _main(entry)
    pts = _mains(history)
    prior = [(d, v) for d, v in pts if d != entry.get("date")]

    st = stage(today)
    if st == "past" and isinstance(cur, (int, float)) and pts:
        rank = 1 + sum(1 for _, v in pts if v < cur)
        lines.append(f"🚨 *PAST YOUR USUAL BOOKING WINDOW* ({BOOK_BY:%b %-d}) — "
                     f"today is the {_ordinal(rank)}-cheapest of {len(pts)} days "
                     f"tracked. Book this week.")
        return lines          # the price threshold has retired; date decides

    if isinstance(cur, (int, float)) and cur <= BUY_BELOW:
        lines.append(f"🚨 *BUY ZONE: ${cur:,} ≤ ${BUY_BELOW:,} target* — book now"
                     f"{' (your window is open)' if st == 'window' else ''}")
    if isinstance(cur, (int, float)) and prior:
        lo_date, lo = min(prior, key=lambda p: p[1])
        if cur < lo:
            lines.append(f"🔥 New all-time low: ${cur:,} "
                         f"(prev ${lo:,} on {_short(lo_date)})")

    # Ticket ① moves independently and is ~78% of the cost — its own low
    # matters even when a pricier middle hides it from the trip total.
    t1 = entry.get("ticket1_total")
    t1_prior = [h["ticket1_total"] for h in history or []
                if h.get("ticket1_total") is not None
                and h.get("date") != entry.get("date")]
    if isinstance(t1, (int, float)) and t1_prior and t1 < min(t1_prior):
        lines.append(f"🔥 Ticket ① new low: ${t1:,} (prev ${min(t1_prior):,})")
    return lines


def price_context(entry, history) -> str:
    """One always-on line of perspective: rank, distance to the low."""
    cur = _main(entry)
    pts = _mains(history)
    if not isinstance(cur, (int, float)) or len(pts) < 2:
        return None
    lo = min(v for _, v in pts)
    rank = 1 + sum(1 for _, v in pts if v < cur)
    gap = ("matches the all-time low" if cur == lo
           else f"${cur - lo:,} above the low")
    return f"{_ordinal(rank)}-cheapest of {len(pts)} days tracked · {gap}"


def countdown(today: datetime.date) -> str:
    st = stage(today)
    if st == "watch":
        return (f"📅 {(WINDOW_OPENS - today).days} days to your usual booking "
                f"window ({BOOKED_HISTORY})")
    if st == "window":
        return (f"📅 {(BOOK_BY - today).days} days left in your usual booking "
                f"window ({BOOKED_HISTORY})")
    return None    # stage 'past' leads the whole message instead


def _ordinal(n: int) -> str:
    if n == 1:
        return "1st"
    if n == 2:
        return "2nd"
    if n == 3:
        return "3rd"
    return f"{n}th"


# ── What changed since yesterday ────────────────────────────────────────────
def _t2_desc(entry) -> str:
    """Comparable description of Ticket ②'s composition: how it's bought,
    which airline(s), which dates. Changes here silently change the baggage
    rules — the exact trap the diff exists to catch."""
    d = (entry or {}).get("best_detail") or {}
    t = d.get("sg_ticket")
    if t:
        return (f"{t.get('airline', '?')} 1-ticket "
                f"({_short_h(t.get('out_date'))} + {_short_h(t.get('ret_date'))})")
    legs = d.get("legs") or []
    if legs:
        names = " + ".join(f.get("airline", "?") for f in legs)
        dates = " + ".join(_short_h(f.get("depart")) for f in legs)
        return f"{names} · 2 one-ways ({dates})"
    return None


def _short_h(s) -> str:
    parts = str(s or "").replace(",", "").split()
    return f"{parts[0][:3]} {parts[1]}" if len(parts) >= 2 else str(s)


def changes_since(prev, cur) -> list:
    """Human-readable diff vs yesterday's entry. Empty list = same trip.
    Only compares entries from the single-trip era (both need ticket1_total)."""
    if not prev or not cur:
        return []
    if prev.get("ticket1_total") is None or cur.get("ticket1_total") is None:
        return []
    out = []
    bag_impact = False

    # The single biggest thing that can change overnight now (2026-08-01):
    # which city order is cheaper. It flips the whole shape of both tickets.
    if (prev.get("order") and cur.get("order")
            and prev["order"] != cur["order"]):
        out.append(f"🔁 Cheaper order flipped: {prev['order']} → {cur['order']}")
        bag_impact = True

    if prev.get("ticket1_airline") != cur.get("ticket1_airline"):
        out.append(f"🎫 Ticket ① airline: {prev.get('ticket1_airline')} → "
                   f"{cur.get('ticket1_airline')}")
        bag_impact = True
    d1 = (cur.get("ticket1_total") or 0) - (prev.get("ticket1_total") or 0)
    if abs(d1) >= 50:
        out.append(f"🎫 Ticket ① ${prev['ticket1_total']:,} → "
                   f"${cur['ticket1_total']:,} ({'+' if d1 > 0 else '−'}${abs(d1):,})")

    p2, c2 = _t2_desc(prev), _t2_desc(cur)
    if p2 and c2 and p2 != c2:
        out.append(f"🇸🇬 Ticket ② composition: {p2} → {c2}")
        bag_impact = True
    if prev.get("ticket2_total") is not None and cur.get("ticket2_total") is not None:
        d2 = cur["ticket2_total"] - prev["ticket2_total"]
        if abs(d2) >= 50:
            out.append(f"🇸🇬 Ticket ② ${prev['ticket2_total']:,} → "
                       f"${cur['ticket2_total']:,} ({'+' if d2 > 0 else '−'}${abs(d2):,})")

    for key, label in (("ist_nights", "Istanbul nights"),
                       ("sg_nights", "Singapore nights"),
                       ("bkk_nights", "Bangkok nights"),
                       ("bali_nights", "Bali nights"),   # pre-2026-08-01 entries
                       ("dhaka_days", "Dhaka days"),
                       ("home", "home date")):
        if (prev.get(key) is not None and cur.get(key) is not None
                and prev[key] != cur[key]):
            out.append(f"{label}: {prev[key]} → {cur[key]}")

    if bag_impact:
        out.append("🧳⚠️ Airline/composition changed — baggage rules changed "
                   "with it, check the baggage table before assuming yesterday's "
                   "allowances")
    return out
