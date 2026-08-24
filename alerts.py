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

# 2026-08-23: the engine now pays up to preference.NONSTOP_WORTH ($500) for a
# nonstop BOS→IST, so the target for the trip as actually picked moved up by
# the premium observed that night (+$378, Turkish over Air France). The old
# $4,500 was the pure-price build; main["cheapest_total"] still records it.
BUY_BELOW = 4900                       # whole trip, all 3 travelers
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


# ── Dated reminders (2026-08-23) ────────────────────────────────────────────
# Booking deadlines and to-dos that must reach Telegram on the day, whatever
# the prices are doing. (date, lead days, text). Mirrors the Google Calendar
# events created the same day; this is the channel Jalal actually reads.
REMINDERS = [
    # (date, lead days, one-line text for the brief, step-by-step for the day-of push)
    (datetime.date(2026, 9, 14), 2,
     "buy the flights this week — Ticket ① Turkish on Chase Travel with ONLY "
     "the 127,825 points eligible for 1.5× (cart must show ~$1,917 covered) + "
     "cash, or turkish.com cash; Ticket ② cash direct (US-Bangla + Scoot)",
     ["Ticket ①: chase.com/travel → Flights → Multi-city: BOS→IST Mon Jan 4 · "
      "IST→DAC Thu Jan 7 · SIN→BOS Sat Feb 6, 2 adults + 1 child. Pick the "
      "Turkish nonstop itinerary the tracker shows (TK 82 / 712 / 23+81).",
      "In the cart choose pay-with-points: it MUST show ~127,825 pts covering "
      "~$1,917 (the 1.5× bucket), cash for the rest. If it only offers 1¢, "
      "stop — buy the same itinerary on turkish.com with the Sapphire Reserve.",
      "Same day, Ticket ② cash direct: usbangla-airlines.com DAC→BKK Jan 28 "
      "morning; flyscoot.com BKK→SIN Feb 2 morning — add a checked bag on Scoot.",
      "Send me the ticket numbers and I stamp them on the site, Notion and the "
      "calendar."]),
    (datetime.date(2026, 9, 15), 0,
     "email the Athenee for suite + Club-lounge supplement quotes "
     "(conf #88518376)",
     ["Email The Athenee Bangkok reservations quoting conf #88518376 "
      "(Jan 28–Feb 2, 2 adults + 1 child, Platinum Elite): ask the per-night "
      "supplement for (a) a suite and (b) a Club-floor room with Club lounge "
      "access, in THB. Say 'draft it' and I write the email.",
      "Fair (~$80–150/night) → accept in writing. Greedy → decline and keep the "
      "Platinum upgrade lottery at check-in. Never split the 5-night award.",
      "Tell me the quote — I update the money table."]),
    (datetime.date(2026, 12, 28), 3,
     "book the Ritz-Carlton Istanbul prepaid via Chase Travel / The Edit by "
     "Dec 31 (Jan 5–7, 3 guests, ~$1,285) to use the 2026 $250 credit",
     ["chase.com/travel → Hotels → Istanbul, Jan 5–7, 2 adults + 1 child (5) "
      "→ The Ritz-Carlton, Istanbul (The Edit badge).",
      "Pick the cheapest REFUNDABLE Guest Room that sleeps 3 (~$1,285 at the "
      "Aug read) — NOT the non-refundable Bosphorus-view rate the cart "
      "defaults to (cart test 2026-08-23: $1,387.70 non-ref).",
      "Payment (Ticket ① must already be bought, so the 1.5× bucket is gone): "
      "split-pay ~$300 on the card + the rest in ORDINARY points at Points "
      "Boost 1.65¢ (~60K pts). Verified two ways 8/23: Chase's checkout "
      "credits modal showed the Edit $500 applying to the card charge on a "
      "split payment, and Upgraded Points documented ~$300 card + points "
      "triggering the $250 twice. Credit can take up to 8 weeks to post; the "
      "charge must land by Dec 31.",
      "The $250 Edit credit posts by itself; the charge must land by Dec 31. "
      "Add your Bonvoy number at booking (points + Platinum perks stack).",
      "Within 24h of booking: check Booking/Expedia for the SAME Ritz room, "
      "dates and cancellation policy — if publicly cheaper, file Chase "
      "Travel's Price Match Guarantee (855-234-2542) for the difference. "
      "Mainstream sites only; opaque/member rates don't qualify.",
      "Send me the confirmation number."]),
    (datetime.date(2027, 1, 2), 0,
     "Kempinski: rebook as Pay Today on the Platinum (Jan–Jun $300), then "
     "cancel the Pay-at-Check-in hold (Amex ref ZO-AX1078-06155)",
     ["amextravel.com (Nabila's login) → Hotels → Singapore Feb 2–6, 2 adults "
      "+ 1 child (5) → The Capitol Kempinski → Room, 1 King Bed (Heritage).",
      "Choose 'Book and Pay Today' on the Platinum (…1004), guest Nabila. "
      "Expect ~$1,497 with the free 4th night; if it is over ~$1,650 or the "
      "promo is gone, keep the hold and skip the $300.",
      "Once the new confirmation arrives: Manage My Trips → cancel ref "
      "ZO-AX1078-06155 (free until Jan 31).",
      "Send me the new ref. The Jan–Jun $300 credit posts within ~2 "
      "statements."]),
    (datetime.date(2027, 1, 26), 3,
     "Athenee free-cancel deadline (conf #88518376) — 11:59pm Bangkok time",
     ["Keeping the Athenee? Check the Stays tab and any 🔔 alerts first.",
      "Keeping → nothing to do, the award stands. Switching → book the "
      "replacement FIRST, then cancel at marriott.com → Trips → #88518376 "
      "before 11:59 pm Bangkok time (= 11:59 am Eastern, Jan 26)."]),
    (datetime.date(2027, 1, 31), 3,
     "Kempinski free-cancel deadline (Amex ref ZO-AX1078-06155) — 11:59pm "
     "Singapore time",
     ["Make sure exactly ONE Kempinski booking remains: the Jan 2 prepaid one "
      "(hold ZO-AX1078-06155 cancelled) — or the hold itself if you skipped "
      "the rebook.",
      "Deadline 11:59 pm Singapore = 10:59 am Eastern on Jan 31. Cancel "
      "anything unwanted at amextravel.com → Manage My Trips."]),
]


def due_reminders(today: datetime.date) -> list:
    """[(index, text, steps)] for reminders whose day is TODAY — the day-of
    push with the what-to-do steps (notify_telegram.send_due_reminders)."""
    return [(i, text, list(steps)) for i, (when, _lead, text, steps)
            in enumerate(REMINDERS) if when == today]


def reminders(today: datetime.date) -> list:
    """⏰ lines due today or within their lead window, nearest first."""
    out = []
    for when, lead, text, _steps in REMINDERS:
        left = (when - today).days
        if 0 <= left <= lead:
            tag = "TODAY" if left == 0 else ("tomorrow" if left == 1 else f"in {left} days")
            out.append(f"⏰ {tag}: {text}")
    return out


def headlines(entry, history, today: datetime.date) -> list:
    """Lines that LEAD the Telegram message (empty = nothing alert-worthy)."""
    lines = reminders(today)
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
    """One always-on line of perspective: rank, distance to the low. Compact
    form (2026-08-20 v4 brief redesign) — single source for the Telegram
    core AND the site's Tonight chip, so they can never disagree."""
    cur = _main(entry)
    pts = _mains(history)
    if not isinstance(cur, (int, float)) or len(pts) < 2:
        return None
    lo = min(v for _, v in pts)
    rank = 1 + sum(1 for _, v in pts if v < cur)
    if cur == lo:
        return f"#{rank}/{len(pts)} · at the low"
    return f"#{rank}/{len(pts)} · ${cur - lo:,} over low"


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
            suffix = (" (hotel-aware pick)"
                      if key == "sg_nights" and cur.get("stay_mode") == "steering"
                      else "")
            out.append(f"{label}: {prev[key]} → {cur[key]}{suffix}")

    if bag_impact:
        out.append("🧳⚠️ Airline/composition changed — baggage rules changed "
                   "with it, check the baggage table before assuming yesterday's "
                   "allowances")
    return out
