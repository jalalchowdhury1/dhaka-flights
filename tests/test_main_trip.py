"""Fixtures + tests for THE tracked trip (2026-07-25 narrowing; Bangkok +
Singapore both-orders rework 2026-08-01).

SIN-first shape mirrors production expectations: Ticket ① lands Dhaka Jan 8,
Ticket ② leaves Dhaka Jan 30, reaches Bangkok Feb 1, return BKK→BOS Feb 6 →
Istanbul 2 nights, Dhaka 23 days, Singapore 2 nights, Bangkok 5 nights, home
Feb 7. The BKK-first mirror: DAC→BKK Jan 30, BKK→SIN Feb 4, SIN→BOS Feb 6.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import main_trip, order_trip, ticket1_options, ticket2_options
from tests.test_combo import _f

# ── Ticket ①: BOS→IST + IST→DAC + {BKK|SIN}→BOS on one multi-city ticket ────
TICKET1 = {
    "kind": "stopover2", "label": "Istanbul 2n + return from Bangkok",
    "ret_city": "BKK",
    "out_date": "January 4, 2027", "ret_date": "February 6, 2027",
    "out_arrive": "January 8, 2027", "price_total": 3600,
    "airline": "Turkish Airlines", "stops": "Nonstop", "duration": "9 hr 20 min",
    "layovers": "none", "link": "http://t1", "ist_nights": 2,
    "desc": "BOS→IST Jan 4 · 2 nights Istanbul · IST→DAC Jan 7 + BKK→BOS Feb 6",
    "note": "n",
}
TICKET1_PRICIER = dict(TICKET1, price_total=4200, airline="Air France", link="http://t1b")
# The other order's Ticket ① (return from Singapore) — pricier by default so
# SIN-first wins in the shared fixtures.
TICKET1_SIN = dict(TICKET1, ret_city="SIN", price_total=3800,
                   label="Istanbul 2n + return from Singapore", link="http://t1sin",
                   desc="BOS→IST Jan 4 · 2 nights Istanbul · IST→DAC Jan 7 + SIN→BOS Feb 6")

# ── Ticket ② (SIN-first): DAC→SIN→BKK, as one ticket or as two one-ways ─────
DAC_SIN = dict(_f("DAC→SIN", "January 30, 2027", "January 30, 2027", 700),
               airline="US-Bangla Airlines", link="http://dacsin")
SIN_BKK = dict(_f("SIN→BKK", "February 1, 2027", "February 1, 2027", 400),
               airline="Scoot", link="http://sinbkk")
TICKET2 = {"kind": "sg-ticket", "order": "SIN-first", "route": "DAC→SIN→BKK",
           "out_date": "January 30, 2027", "ret_date": "February 1, 2027",
           "out_arrive": "January 30, 2027", "price_total": 1000,
           "airline": "US-Bangla Airlines", "stops": "Nonstop", "duration": "4 hr 15 min",
           "layovers": "none", "link": "http://t2"}
TICKET2_SQ = dict(TICKET2, price_total=1200, airline="Singapore Airlines",
                  link="http://t2sq")
TICKET2_OTHER_DATES = dict(TICKET2, out_date="January 31, 2027",
                           ret_date="February 2, 2027", price_total=800,
                           airline="Cheap But Wrong Dates Air")

# ── Ticket ② (BKK-first): DAC→BKK→SIN ──────────────────────────────────────
DAC_BKK = dict(_f("DAC→BKK", "January 30, 2027", "January 30, 2027", 500),
               airline="US-Bangla Airlines", link="http://dacbkk")
BKK_SIN = dict(_f("BKK→SIN", "February 4, 2027", "February 4, 2027", 300),
               airline="Scoot", link="http://bkksin")
TICKET2_BKK_FIRST = {"kind": "sg-ticket", "order": "BKK-first",
                     "route": "DAC→BKK→SIN",
                     "out_date": "January 30, 2027", "ret_date": "February 4, 2027",
                     "out_arrive": "January 30, 2027", "price_total": 900,
                     "airline": "THAI", "stops": "Nonstop",
                     "duration": "2 hr 40 min", "layovers": "none",
                     "link": "http://t2bkk"}

FLIGHTS = [DAC_SIN, SIN_BKK]
SG_TICKETS = [TICKET2, TICKET2_SQ, TICKET2_OTHER_DATES]


def test_main_trip_has_the_asked_for_shape():
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    assert t is not None
    assert t["kind"] == "sg-stopover2"
    assert t["order"] == "SIN-first"
    assert t["ist_nights"] == 2
    assert t["sg_nights"] == 2
    assert t["bkk_nights"] == 5
    assert t["dhaka_days"] == 23
    assert t["home"] == "Feb 7"
    assert t["valid"] is True


def test_main_trip_takes_the_cheaper_middle():
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    assert t["total"] == 3600 + 1000          # one ticket (1000) beats 700+400
    assert t["sg_ticket"]["airline"] == "US-Bangla Airlines"


def test_main_trip_is_none_without_ticket1():
    assert main_trip(FLIGHTS, [], SG_TICKETS) is None


def test_bkk_first_order_builds_its_own_shape():
    t = order_trip([DAC_BKK, BKK_SIN], [TICKET1_SIN], [TICKET2_BKK_FIRST],
                   "BKK-first")
    assert t is not None
    assert t["order"] == "BKK-first"
    assert t["bkk_nights"] == 5               # Jan 30 → Feb 4, the middle stay
    assert t["sg_nights"] == 2                # Feb 4 → Feb 6 return
    assert t["valid"] is True
    assert t["total"] == 3800 + 800           # one-ways 500+300 beat the 900 ticket


def test_cheaper_order_wins_and_the_other_rides_along():
    both_t1 = [TICKET1, TICKET1_SIN]
    both_flights = FLIGHTS + [DAC_BKK, BKK_SIN]
    both_tickets = SG_TICKETS + [TICKET2_BKK_FIRST]
    t = main_trip(both_flights, both_t1, both_tickets)
    # SIN-first: 3600 + 1000 = 4600 · BKK-first: 3800 + 800 = 4600 → tie goes
    # to sort order, but make it strict: cheapen the BKK-first middle.
    cheaper_bkk = [dict(DAC_BKK, price_total=400), BKK_SIN]
    t = main_trip(FLIGHTS + cheaper_bkk, both_t1, both_tickets)
    assert t["order"] == "BKK-first"
    assert t["total"] == 3800 + 700
    other = t["other_order"]
    assert other["order"] == "SIN-first"
    assert other["total"] == 4600
    assert other["delta"] == 100
    assert other["ticket1_total"] == 3600


def test_a_flagged_order_never_beats_a_valid_one():
    # BKK-first is cheaper but only has a 4-night Bangkok pairing (flagged);
    # the on-shape SIN-first trip must still headline.
    short_bkk = [dict(DAC_BKK, depart="January 31, 2027",
                      arrive="January 31, 2027", price_total=100), BKK_SIN]
    t = main_trip(FLIGHTS + short_bkk, [TICKET1, TICKET1_SIN], SG_TICKETS)
    assert t["order"] == "SIN-first"
    assert t["valid"] is True
    assert t["other_order"]["valid"] is False
    assert "4-night Bangkok" in t["other_order"]["flag"]


def test_ticket2_alternatives_are_same_dates_only():
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    opts = ticket2_options(FLIGHTS, SG_TICKETS, t)
    airlines = [o["airline"] for o in opts]
    assert "Cheap But Wrong Dates Air" not in airlines, "different dates ≠ same trip"
    assert "US-Bangla Airlines" in airlines and "Singapore Airlines" in airlines


def test_ticket2_alternatives_stay_within_the_winning_order():
    both = SG_TICKETS + [dict(TICKET2_BKK_FIRST, out_date="January 30, 2027",
                              ret_date="February 1, 2027", price_total=950)]
    t = main_trip(FLIGHTS, [TICKET1], both)
    assert t["order"] == "SIN-first"
    opts = ticket2_options(FLIGHTS, both, t)
    assert "THAI" not in [o["airline"] for o in opts], \
        "the other order's ticket is not a same-trip alternative"


def test_ticket2_alternatives_carry_the_price_gap():
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    opts = {o["airline"]: o for o in ticket2_options(FLIGHTS, SG_TICKETS, t)}
    assert opts["US-Bangla Airlines"]["delta"] == 0
    assert opts["US-Bangla Airlines"]["chosen"] is True
    assert opts["Singapore Airlines"]["delta"] == 200
    two = opts["US-Bangla Airlines + Scoot"]
    assert two["kind"] == "2 tickets" and two["price"] == 1100 and two["delta"] == 100


def test_two_ticket_rows_carry_both_booking_links():
    # Two separate purchases need two Book buttons — one link only buys leg 1.
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    opts = {o["airline"]: o for o in ticket2_options(FLIGHTS, SG_TICKETS, t)}
    two = opts["US-Bangla Airlines + Scoot"]
    assert two["link"] == DAC_SIN["link"] and two["link2"] == SIN_BKK["link"]
    one = opts["US-Bangla Airlines"]
    assert one["kind"] == "1 ticket" and "link2" not in one


def test_ticket1_alternatives_ranked_with_gap():
    opts = ticket1_options([TICKET1, TICKET1_PRICIER], TICKET1)
    assert [o["airline"] for o in opts] == ["Turkish Airlines", "Air France"]
    assert opts[0]["chosen"] is True and opts[0]["delta"] == 0
    assert opts[1]["delta"] == 600


def test_ticket1_alternatives_exclude_the_other_orders_return():
    opts = ticket1_options([TICKET1, TICKET1_PRICIER, TICKET1_SIN], TICKET1)
    assert [o["airline"] for o in opts] == ["Turkish Airlines", "Air France"], \
        "the SIN→BOS return is a different purchase, not an alternative"


def test_two_oneway_middle_wins_when_cheaper():
    cheap_pair = [dict(DAC_SIN, price_total=400), dict(SIN_BKK, price_total=300)]
    t = main_trip(cheap_pair, [TICKET1], [TICKET2])
    assert t["total"] == 3600 + 700
    assert t["sg_ticket"] is None
    assert len(t["legs"]) == 2


def test_three_or_four_singapore_nights_win_unflagged_when_cheaper():
    # 2026-08-01: "The singapore one isn't a hardline. you can take it up to
    # 3 or even 4 if its cheaper in terms of the flight."
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=800,
                      airline="Biman", link="http://t2flex")
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS + [four_night])
    assert t["sg_nights"] == 4
    assert t["total"] == 3600 + 800
    assert t["valid"] is True and t["flag"] is None


def test_five_singapore_nights_survive_only_flagged():
    five_night = dict(TICKET2, out_date="January 27, 2027",
                      out_arrive="January 27, 2027", price_total=500,
                      airline="Biman", link="http://t2long")
    t = main_trip([], [TICKET1], [five_night])   # only option → kept, flagged
    assert t["sg_nights"] == 5
    assert t["valid"] is False
    assert "comfort band" in t["flag"]
    # …but never beats an in-band option, even a pricier one:
    t2 = main_trip(FLIGHTS, [TICKET1], SG_TICKETS + [five_night])
    assert t2["sg_nights"] == 2 and t2["total"] == 4600


def test_hotel_hook_flips_the_pick_within_the_band():
    # 4N shape is $60 pricier on flights; the hook (worth-it knob) flips it.
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    tickets2 = SG_TICKETS + [four_night]
    flat = main_trip(FLIGHTS, [TICKET1], tickets2)
    assert flat["sg_nights"] == 2 and flat["total"] == 4600   # flight-only pick
    hook = lambda n: {2: 0, 3: -73, 4: -113}.get(n, 0)        # St.Regis@218 math
    t = main_trip(FLIGHTS, [TICKET1], tickets2, hotel_cost=hook)
    assert t["sg_nights"] == 4
    assert t["total"] == 3600 + 1060      # total stays FLIGHTS-ONLY — history rule


def test_hotel_hook_cannot_pull_an_out_of_band_shape_in():
    # Validity tiers run BEFORE the hook: a 5-night SIN shape stays a flagged
    # fallback even if a (buggy) hook rewards it hugely.
    five_night = dict(TICKET2, out_date="January 27, 2027",
                      out_arrive="January 27, 2027", price_total=500,
                      airline="Biman", link="http://t2long")
    hook = lambda n: -10_000 if n == 5 else 0
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS + [five_night], hotel_cost=hook)
    assert t["sg_nights"] == 2 and t["valid"] is True


def test_cross_order_winner_is_judged_all_in_too():
    # Flights-only: SIN-first 2N wins ($4,600 < $4,700). All-in with the hook:
    # BKK-first's 4N SIN shape wins (4700−113=4587 < 4600).
    dac_bkk28 = dict(_f("DAC→BKK", "January 28, 2027", "January 28, 2027", 600),
                     airline="US-Bangla Airlines", link="http://db28")
    bkk_sin2 = dict(_f("BKK→SIN", "February 2, 2027", "February 2, 2027", 300),
                    airline="Scoot", link="http://bs2")
    flights = FLIGHTS + [dac_bkk28, bkk_sin2]
    t1s = [TICKET1, TICKET1_SIN]
    flat = main_trip(flights, t1s, SG_TICKETS)
    assert flat["order"] == "SIN-first" and flat["total"] == 4600
    hook = lambda n: {2: 0, 3: -73, 4: -113}.get(n, 0)
    t = main_trip(flights, t1s, SG_TICKETS, hotel_cost=hook)
    assert t["order"] == "BKK-first"
    assert t["sg_nights"] == 4 and t["bkk_nights"] == 5
    assert t["total"] == 3800 + 900       # flights-only total of the 4N shape


def test_sin_night_flight_totals_by_band():
    from combo import sin_night_flight_totals
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    totals = sin_night_flight_totals(FLIGHTS, [TICKET1],
                                     SG_TICKETS + [four_night], "SIN-first")
    # 2N: min(1000 one-ticket, 700+400 one-ways) + 3600 · 4N: 1060 + 3600.
    # TICKET2_OTHER_DATES pairs to a 4-night Bangkok block → excluded (strict 5).
    assert totals == {2: 4600, 4: 4660}
    assert sin_night_flight_totals(FLIGHTS, [], SG_TICKETS, "SIN-first") == {}


def test_sin_night_flight_totals_excludes_out_of_band():
    from combo import sin_night_flight_totals
    five_night = dict(TICKET2, out_date="January 27, 2027",
                      out_arrive="January 27, 2027", price_total=500,
                      airline="Biman", link="http://t2long")
    totals = sin_night_flight_totals(FLIGHTS, [TICKET1],
                                     SG_TICKETS + [five_night], "SIN-first")
    assert 5 not in totals and totals[2] == 4600
