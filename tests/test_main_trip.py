"""Fixtures + tests for THE tracked trip (2026-07-25 narrowing).

Shape mirrors production on 2026-07-25: Ticket ① lands Dhaka Jan 8, Ticket ②
leaves Dhaka Jan 30 and reaches Bali Feb 1, return Feb 6 → Istanbul 2 nights,
Dhaka 23 days, Singapore 2 nights, Bali 5 nights, home Feb 7.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import main_trip, ticket1_options, ticket2_options
from tests.test_combo import _f

# ── Ticket ①: BOS→IST + IST→DAC + DPS→BOS on one multi-city ticket ──────────
TICKET1 = {
    "kind": "stopover2", "label": "Istanbul 2-night stopover",
    "out_date": "January 4, 2027", "ret_date": "February 6, 2027",
    "out_arrive": "January 8, 2027", "price_total": 3600,
    "airline": "Turkish Airlines", "stops": "Nonstop", "duration": "9 hr 20 min",
    "layovers": "none", "link": "http://t1", "ist_nights": 2,
    "desc": "BOS→IST Jan 4 · 2 nights Istanbul · IST→DAC Jan 7 + DPS→BOS Feb 6",
    "note": "n",
}
TICKET1_PRICIER = dict(TICKET1, price_total=4200, airline="Air France", link="http://t1b")

# ── Ticket ②: DAC→SIN→DPS, as one ticket or as two one-ways ────────────────
DAC_SIN = dict(_f("DAC→SIN", "January 30, 2027", "January 30, 2027", 700),
               airline="US-Bangla Airlines")
SIN_DPS = dict(_f("SIN→DPS", "February 1, 2027", "February 1, 2027", 400),
               airline="Scoot")
TICKET2 = {"kind": "sg-ticket", "route": "DAC→SIN→DPS",
           "out_date": "January 30, 2027", "ret_date": "February 1, 2027",
           "out_arrive": "January 30, 2027", "price_total": 1000,
           "airline": "US-Bangla Airlines", "stops": "Nonstop", "duration": "4 hr 15 min",
           "layovers": "none", "link": "http://t2"}
TICKET2_SQ = dict(TICKET2, price_total=1200, airline="Singapore Airlines",
                  link="http://t2sq")
TICKET2_OTHER_DATES = dict(TICKET2, out_date="January 31, 2027",
                           ret_date="February 2, 2027", price_total=800,
                           airline="Cheap But Wrong Dates Air")

FLIGHTS = [DAC_SIN, SIN_DPS]
SG_TICKETS = [TICKET2, TICKET2_SQ, TICKET2_OTHER_DATES]


def test_main_trip_has_the_asked_for_shape():
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    assert t is not None
    assert t["kind"] == "sg-stopover2"
    assert t["ist_nights"] == 2
    assert t["sg_nights"] == 2
    assert t["bali_nights"] == 5
    assert t["dhaka_days"] == 23
    assert t["home"] == "Feb 7"
    assert t["valid"] is True


def test_main_trip_takes_the_cheaper_middle():
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    assert t["total"] == 3600 + 1000          # one ticket (1000) beats 700+400
    assert t["sg_ticket"]["airline"] == "US-Bangla Airlines"


def test_main_trip_is_none_without_ticket1():
    assert main_trip(FLIGHTS, [], SG_TICKETS) is None


def test_ticket2_alternatives_are_same_dates_only():
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    opts = ticket2_options(FLIGHTS, SG_TICKETS, t)
    airlines = [o["airline"] for o in opts]
    assert "Cheap But Wrong Dates Air" not in airlines, "different dates ≠ same trip"
    assert "US-Bangla Airlines" in airlines and "Singapore Airlines" in airlines


def test_ticket2_alternatives_carry_the_price_gap():
    t = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)
    opts = {o["airline"]: o for o in ticket2_options(FLIGHTS, SG_TICKETS, t)}
    assert opts["US-Bangla Airlines"]["delta"] == 0
    assert opts["US-Bangla Airlines"]["chosen"] is True
    assert opts["Singapore Airlines"]["delta"] == 200
    two = opts["US-Bangla Airlines + Scoot"]
    assert two["kind"] == "2 tickets" and two["price"] == 1100 and two["delta"] == 100


def test_ticket1_alternatives_ranked_with_gap():
    opts = ticket1_options([TICKET1, TICKET1_PRICIER], TICKET1)
    assert [o["airline"] for o in opts] == ["Turkish Airlines", "Air France"]
    assert opts[0]["chosen"] is True and opts[0]["delta"] == 0
    assert opts[1]["delta"] == 600


def test_two_oneway_middle_wins_when_cheaper():
    cheap_pair = [dict(DAC_SIN, price_total=400), dict(SIN_DPS, price_total=300)]
    t = main_trip(cheap_pair, [TICKET1], [TICKET2])
    assert t["total"] == 3600 + 700
    assert t["sg_ticket"] is None
    assert len(t["legs"]) == 2
