"""Ticket ① convenience preference (2026-08-23): a nonstop BOS→IST is worth
NONSTOP_WORTH to the family over a 1-stop — Jalal: "for $300-something we
should definitely take the direct flight". The pick minimises
price − (NONSTOP_WORTH if nonstop); the trip TOTAL stays the real price."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import preference
import verify
from combo import main_trip, _resolve_ticket1
from tests.test_main_trip import TICKET1, TICKET1_SIN, FLIGHTS, SG_TICKETS

ONE_STOP = dict(TICKET1, price_total=3625, airline="Air France", stops="1 stop",
                duration="15 hr 30 min", link="http://af")
NONSTOP = dict(TICKET1, price_total=4003, airline="Turkish Airlines", stops="Nonstop",
               link="http://tk")


def test_score_discounts_a_nonstop_by_the_knob():
    assert preference.ticket1_score(NONSTOP) == 4003 - preference.NONSTOP_WORTH
    assert preference.ticket1_score(ONE_STOP) == 3625
    assert preference.is_nonstop({"stops": "nonstop"}) and not preference.is_nonstop({"stops": "1 stop"})
    assert not preference.is_nonstop({})


def test_nonstop_wins_inside_the_knob_and_keeps_its_real_price():
    oj, _, _ = _resolve_ticket1([ONE_STOP, NONSTOP], {"ret_city": "BKK"})
    assert oj["airline"] == "Turkish Airlines" and oj["price_total"] == 4003
    assert oj["pick"]["premium"] == 378 and oj["pick"]["over"]["airline"] == "Air France"
    assert "nonstop" in oj["pick"]["note"].lower() and "$378" in oj["pick"]["note"]


def test_nonstop_loses_beyond_the_knob():
    dear = dict(NONSTOP, price_total=3625 + preference.NONSTOP_WORTH + 1)
    oj, _, _ = _resolve_ticket1([ONE_STOP, dear], {"ret_city": "BKK"})
    assert oj["airline"] == "Air France" and "pick" not in oj


def test_cheapest_is_nonstop_means_no_note():
    oj, _, _ = _resolve_ticket1([dict(ONE_STOP, price_total=4500), NONSTOP], {"ret_city": "BKK"})
    assert oj["airline"] == "Turkish Airlines" and "pick" not in oj


def test_trip_total_is_the_real_fare_and_verify_agrees():
    trip = main_trip(FLIGHTS, [ONE_STOP, NONSTOP, TICKET1_SIN], SG_TICKETS)
    assert trip["openjaw"]["airline"] == "Turkish Airlines"
    assert trip["total"] == 4003 + (trip["total"] - trip["openjaw"]["price_total"])
    probs = verify.verify_payload({"main": trip, "history": [], "stay_value": None},
                                  FLIGHTS, [ONE_STOP, NONSTOP, TICKET1_SIN], SG_TICKETS)
    assert probs == []
    assert trip.get("cheapest_total") == trip["total"] - 378
