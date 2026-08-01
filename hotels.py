"""Marriott award-stay plan riding along with the trip (2026-08-01 evening,
Jalal: "integrate the hotels / resorts part in here as well. the one where we
use the marriot points and get that 5th night free").

WHY THIS IS A CURATED TABLE AND NOT SCRAPED: Marriott award pricing is
dynamic and marriott.com is aggressively bot-guarded — scraping it nightly
would be fragile and would blow the 25-minute run cap. Like baggage.py, this
file holds LIVE-CHECKED reference numbers with their CHECKED date; refresh
them by re-running the sweep (see the Bangkok-hotel memory / Notion page),
not by trusting them blindly at booking time.

Quality bar (Jalal 2026-08-01): "hotel quality has to be top notch. we did
the kempinsky last time and it was awesome" — hence the Luxury Collection
pick over the cheaper Marquis.

What IS dynamic here: the stay DATES. They come from each night's winning
trip (which order won, which dates its middle priced), so the hotel card
always matches the flights above it. 5th-night-free applies to award stays
of 5+ nights — a 4/6-night flight pairing gets a loud note.
"""
from datetime import datetime, timedelta

CHECKED = "2026-08-01"

BKK_HOTEL = {
    "city": "Bangkok",
    "property": "The Athenee Hotel, a Luxury Collection Hotel",
    "points": {"Feb 1–6": 177_000, "Jan 30–Feb 4": 173_000},
    "cash_ref": "~$927 + tax for the same 5 nights",
    "note": ("Top-notch tier (the Kempinski bar): quiet Wireless Rd embassy "
             "district — same Langsuan neighborhood as Sindhorn Kempinski — "
             "rooftop lagoon pool, kids' club, 5 min to BTS Ploenchit; award "
             "room sleeps 2 adults + 1 child (live-verified)."),
    "runner_up": ("Sheraton Grande Sukhumvit (Luxury Collection) — 179K/170K "
                  "pts, connected to BTS Asok · value alt: Marriott Marquis "
                  "Queen's Park 133K/126K"),
}

BALI_HOTEL = {
    "city": "Bali",
    "property": "The Laguna, a Luxury Collection Resort & Spa, Nusa Dua",
    "points": {"Feb 1–6": 167_000},
    "points_note": ("167K is the base-room list rate; the real 3-guest play "
                    "was the 1BR-suite hybrid: 167K + ~$1,310 cash (pure-"
                    "points 3-guest Studio was 223K). Checked 2026-07-27."),
    "cash_ref": "~$2,692 cash-alone for the suite",
    "note": "Benchmark only — the Bali leg was dropped 2026-08-01.",
    "runner_up": None,
}


def _d(s):
    try:
        return datetime.strptime(s, "%B %d, %Y")
    except (ValueError, TypeError):
        return None


def _fmt(d):
    return d.strftime("%b %-d") if d else "?"


def _stay_dates(trip, city_position):
    """(checkin, checkout) datetimes for the 5-night city's stay, derived from
    the trip's actual middle. city_position: 'middle' = the stay sits between
    Ticket ②'s two legs; 'final' = it runs to Ticket ①'s return date."""
    t = trip.get("sg_ticket")
    legs = trip.get("legs") or []
    oj = trip.get("openjaw") or {}
    if t:
        leg1_arr = _d(t.get("out_arrive", "")) or _d(t.get("out_date", ""))
        leg2_dep = _d(t.get("ret_date", ""))
    else:
        if len(legs) < 2:
            return None, None
        l1, l2 = legs[0], legs[1]
        leg1_arr = (_d(l1.get("arrive", "")) if l1.get("arrive") not in (None, "N/A")
                    else _d(l1.get("depart", "")))
        leg2_dep = _d(l2.get("depart", ""))
    ret = _d(oj.get("ret_date", ""))
    if city_position == "middle":
        return leg1_arr, leg2_dep
    return leg2_dep, ret


def hotel_plan(trip, hotel=None):
    """The award-stay card for a built trip (main → Bangkok, bali → Bali).
    Returns None when there's no trip. Dates follow the trip's winning shape;
    points figures are the CHECKED reference values, not a live quote."""
    if not trip:
        return None
    is_bali = trip.get("bkk_nights") is None
    hotel = hotel or (BALI_HOTEL if is_bali else BKK_HOTEL)
    nights = trip.get("bali_nights") if is_bali else trip.get("bkk_nights")
    if is_bali:
        position = "final"                    # Bali always ran to the return
    else:
        position = ("middle" if trip.get("order") == "BKK-first" else "final")
    checkin, checkout = _stay_dates(trip, position)
    warn = None
    if isinstance(nights, int) and nights != 5:
        warn = (f"tonight's cheapest pairing gives {nights} hotel nights — "
                f"the 5th-night-free credit needs a 5-night award stay")
    return {
        "city": hotel["city"],
        "property": hotel["property"],
        "points": hotel["points"],
        "points_note": hotel.get("points_note"),
        "cash_ref": hotel.get("cash_ref"),
        "note": hotel.get("note"),
        "runner_up": hotel.get("runner_up"),
        "nights": nights,
        "checkin": _fmt(checkin), "checkout": _fmt(checkout),
        "fifth_night_free": nights == 5,
        "warn": warn,
        "checked": CHECKED if not is_bali else "2026-07-27",
    }
