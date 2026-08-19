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


# ── 🛏️ Stay-math recompute (2026-08-19) ────────────────────────────────────
import datetime as _dt
import stay_value as _sv
import verify as _verify
from tests.test_main_trip import (FLIGHTS as _MT_FLIGHTS, TICKET1 as _MT_T1,
                                  SG_TICKETS as _MT_SG, TICKET2 as _MT_T2)
from tests.test_stay_value import RATES as _RATES

_FOUR = dict(_MT_T2, out_date="January 28, 2027",
             out_arrive="January 28, 2027", price_total=1060,
             airline="Biman", link="http://t2flex")


def _stay_payload(hook):
    from combo import main_trip
    t2 = _MT_SG + [_FOUR]
    main = main_trip(_MT_FLIGHTS, [_MT_T1], t2, hotel_cost=hook)
    return {
        "main": main,
        "history": [{"date": "2026-08-19", "main_total": main["total"]}],
        "stay_value": {"mode": "steering"},
    }, t2


def test_strict_by_sg_totals():
    by = _verify.strict_by_sg(_MT_FLIGHTS, [_MT_T1], _MT_SG + [_FOUR],
                              "SIN-first")
    assert by == {2: 4600, 4: 4660}


def test_recompute_agrees_with_a_hotel_aware_pick():
    hook = _sv.hotel_hook(_RATES, None, today=_dt.date(2026, 8, 19))
    payload, t2 = _stay_payload(hook)
    assert payload["main"]["sg_nights"] == 4
    probs = _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2,
                                   rates=_RATES)
    assert probs == []


def test_recompute_flags_a_flight_only_pick_when_steering():
    payload, t2 = _stay_payload(None)          # hook not applied → 2N
    assert payload["main"]["sg_nights"] == 2
    probs = _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2,
                                   rates=_RATES)
    assert any("hotel-aware recompute picks 4" in p for p in probs)


def test_stay_rows_arithmetic_is_rechecked():
    payload, t2 = _stay_payload(
        _sv.hotel_hook(_RATES, None, today=_dt.date(2026, 8, 19)))
    payload["stay_value"] = {
        "mode": "steering",
        "rows": [{"n": 4, "flights": 4660, "hotel_net": 337, "allin": 9999}],
    }
    probs = _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2,
                                   rates=_RATES)
    assert any("stay-math row" in p for p in probs)


def test_no_rates_no_steering_checks():
    payload, t2 = _stay_payload(None)
    payload["stay_value"] = None
    assert _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2) == []


def test_malformed_rates_degrade_verify_not_crash():
    payload, t2 = _stay_payload(None)
    # claims steering but the rates are garbage → adjuster must be None,
    # old flight-only checks run, nothing raises
    probs = _verify.verify_payload(payload, _MT_FLIGHTS, [_MT_T1], t2,
                                   rates={"rows": None})
    assert probs == []
