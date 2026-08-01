"""🔎 The independent nightly re-check (2026-08-01: "once done verify.
Multiple times. take different perspectives.")."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import publish
import verify
from tests.test_main_trip import (TICKET1, TICKET1_SIN, FLIGHTS, SG_TICKETS,
                                  DAC_BKK, BKK_SIN, TICKET2_BKK_FIRST)


def _payload(flights=None, t1=None, sg=None):
    flights = FLIGHTS + [DAC_BKK, BKK_SIN] if flights is None else flights
    t1 = [TICKET1, TICKET1_SIN] if t1 is None else t1
    sg = SG_TICKETS + [TICKET2_BKK_FIRST] if sg is None else sg
    return publish.build_payload(list(flights), list(t1), [], "2026-08-01",
                                 warnings=[], sg_tickets=list(sg)), flights, t1, sg


def test_clean_payload_verifies():
    p, flights, t1, sg = _payload()
    assert verify.verify_payload(p, flights, t1, sg) == []


def test_recompute_catches_a_wrong_total():
    p, flights, t1, sg = _payload()
    p["main"]["total"] += 100                     # corrupt the headline
    out = " ".join(verify.verify_payload(p, flights, t1, sg))
    assert "recompute" in out or "don't sum" in out


def test_recompute_catches_a_dropped_cheaper_option():
    # A strict-shape ticket the pipeline "missed" (simulated by adding it to
    # the raw data only) must trip the recompute perspective.
    p, flights, t1, sg = _payload()
    cheap = dict(SG_TICKETS[0], price_total=100, airline="Ghost Air",
                 link="http://ghost")
    out = " ".join(verify.verify_payload(p, flights, t1, sg + [cheap]))
    assert "recompute" in out


def test_arithmetic_catches_a_bad_delta():
    p, flights, t1, sg = _payload()
    p["main"]["other_order"]["delta"] = 999999
    out = " ".join(verify.verify_payload(p, flights, t1, sg))
    assert "Δ is wrong" in out


def test_contract_catches_hotel_mismatch():
    p, flights, t1, sg = _payload()
    p["hotel"]["nights"] = 3
    out = " ".join(verify.verify_payload(p, flights, t1, sg))
    assert "hotel" in out


def test_no_trip_day_is_not_a_false_alarm():
    p = publish.build_payload([], [], [], "2026-08-01")
    assert verify.verify_payload(p, [], [], []) == []
