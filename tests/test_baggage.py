"""Baggage lookup — the numbers Jalal will act on, so the failure modes that
matter are 'silently wrong' and 'silently confident'."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import baggage
from combo import main_trip
from tests.test_main_trip import (TICKET1, TICKET2, DAC_SIN, SIN_DPS,
                                  FLIGHTS, SG_TICKETS)

TRIP = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)


def test_us_ticket_uses_the_piece_rule():
    b = baggage.for_leg("Turkish Airlines", baggage.US_TICKET, "BOS→IST")
    assert "2 × 23 kg" in b["checked"]
    assert b["confidence"] == "verified"
    assert b["url"].startswith("https://www.turkishairlines.com")


def test_asia_ticket_is_route_specific_where_the_airline_publishes_it():
    dac_sin = baggage.for_leg("US-Bangla Airlines", baggage.ASIA_TICKET, "DAC→SIN")
    other = baggage.for_leg("US-Bangla Airlines", baggage.ASIA_TICKET, "DAC→DXB")
    assert "40 kg" in dac_sin["checked"]
    assert dac_sin["checked"] != other["checked"], "route must change the answer"


def test_european_carriers_give_one_bag_not_two():
    assert "1 × 23 kg" in baggage.for_leg("Air France", baggage.US_TICKET, "BOS→IST")["checked"]
    assert "2 × 23 kg" in baggage.for_leg("Qatar Airways", baggage.US_TICKET, "BOS→IST")["checked"]


def test_low_cost_carrier_says_none_included():
    assert "NONE" in baggage.for_leg("Scoot", baggage.ASIA_TICKET, "SIN→DPS")["checked"]


def test_unknown_carrier_admits_it_instead_of_guessing():
    b = baggage.for_leg("Aeroflot", baggage.US_TICKET, "BOS→IST")
    assert b["confidence"] == "unknown"
    assert "check" in b["note"].lower() or "open" in b["note"].lower()


def test_multi_carrier_string_reports_every_carrier():
    b = baggage.for_leg("Lufthansa and Turkish Airlines", baggage.US_TICKET, "BOS→IST")
    assert b["carrier"] == "Lufthansa"
    assert [o["carrier"] for o in b["others"]] == ["Turkish Airlines"]


def test_two_airline_summary_names_both_allowances():
    # "US-Bangla: 40 kg" alone would hide that the Bali half includes no bag.
    b = baggage.for_leg("US-Bangla Airlines + Jetstar", baggage.ASIA_TICKET, "DAC→SIN")
    assert "40 kg" in b["summary"] and "Jetstar" in b["summary"]
    assert "NONE" in b["summary"]


def test_single_carrier_summary_is_just_the_allowance():
    b = baggage.for_leg("Turkish Airlines", baggage.US_TICKET, "BOS→IST")
    assert b["summary"] == b["checked"]


def test_annotate_covers_all_five_flights_in_order():
    rows = baggage.annotate(TRIP)
    assert [r["route"] for r in rows] == ["BOS→IST", "IST→DAC", "DAC→SIN",
                                          "SIN→DPS", "DPS→BOS"]
    assert [r["ticket"] for r in rows] == [1, 1, 2, 2, 1]


def test_ticket1_allowance_is_shared_across_its_three_flights():
    rows = {r["route"]: r for r in baggage.annotate(TRIP)}
    assert rows["BOS→IST"]["checked"] == rows["IST→DAC"]["checked"] == rows["DPS→BOS"]["checked"]


def test_second_leg_of_a_multicity_ticket_is_admitted_unknown():
    # Google names only the first leg of a multi-city ticket — pretending we
    # know the SIN→DPS allowance would be the exact trap Jalal asked about.
    rows = {r["route"]: r for r in baggage.annotate(TRIP)}
    assert rows["SIN→DPS"]["confidence"] == "unknown"
    assert "not shown" in rows["SIN→DPS"]["carrier"]


def test_two_oneway_middle_knows_both_carriers():
    trip = main_trip([dict(DAC_SIN, price_total=400), dict(SIN_DPS, price_total=300)],
                     [TICKET1], [TICKET2])
    rows = {r["route"]: r for r in baggage.annotate(trip)}
    assert rows["DAC→SIN"]["carrier"] == "US-Bangla Airlines"
    assert rows["SIN→DPS"]["carrier"] == "Scoot"


def test_warnings_flag_the_separate_ticket_trap():
    w = " ".join(baggage.warnings(TRIP)).lower()
    assert "not checked through" in w or "re-check" in w
    assert "child" in w


def test_no_trip_no_crash():
    assert baggage.annotate(None) == []
    assert baggage.warnings(None) == []
