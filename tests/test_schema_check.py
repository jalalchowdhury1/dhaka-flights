"""Payload contract: the exact shape site/index.html renders from.
A violation must come back as a human-readable warning, never an exception."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import json
import pytest
import publish
import schema_check
from tests.test_main_trip import (TICKET1, TICKET1_SIN, FLIGHTS, SG_TICKETS,
                                  DAC_BKK, BKK_SIN, TICKET2_BKK_FIRST)


def _payload():
    return publish.build_payload(
        list(FLIGHTS + [DAC_BKK, BKK_SIN]), [TICKET1, TICKET1_SIN], [],
        "2026-08-01", warnings=[], sg_tickets=list(SG_TICKETS + [TICKET2_BKK_FIRST]))


def test_real_payload_passes():
    assert schema_check.validate(_payload()) == []


def test_no_trip_day_still_passes():
    # A catastrophic day publishes main=None — that is contract-legal.
    assert schema_check.validate(publish.build_payload([], [], [], "2026-08-01")) == []


def test_missing_top_level_key_is_reported():
    p = _payload()
    del p["history"]
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "history" in out[0]


def test_wrong_type_is_reported():
    p = _payload()
    p["warnings"] = "oops a string"
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "warnings" in out[0]


def test_history_entry_shape_is_checked():
    p = _payload()
    p["history"][-1].pop("date")
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "date" in out[0]


def test_main_total_must_be_number_when_trip_exists():
    p = _payload()
    p["main"]["total"] = "4626"
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "total" in out[0]


def test_non_dict_history_entry_is_reported():
    p = _payload()
    p["history"][-1] = "not-a-dict"
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "history" in out[0]


def test_history_numeric_violation_is_reported():
    p = _payload()
    p["history"][-1]["ticket1_total"] = "1200"
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "ticket1_total" in out[0]


def test_main_missing_required_key_is_reported():
    p = _payload()
    del p["main"]["order_label"]
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "order_label" in out[0]


def test_main_total_bool_is_not_a_number():
    # bool is a subclass of int in Python — True/False must not sneak past
    # the numeric check as a valid "total".
    p = _payload()
    p["main"]["total"] = True
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "total" in out[0]


def test_non_serializable_value_is_reported():
    p = _payload()
    p["main"]["weird"] = object()          # nothing knows how to serialize this
    out = schema_check.validate(p)
    assert len(out) == 1
    assert "serialize" in out[0]


def test_history_violations_are_capped():
    # A systemic drift (every history row's numerics turn into strings) must
    # fold into one summary line, not one violation per row — that's the
    # difference between a Telegram message that arrives and one that
    # silently overflows into a warnings-free core message.
    p = _payload()
    p["history"] = [{"date": f"2026-08-{i:02d}", "main_total": "bad"}
                    for i in range(1, 11)]
    out = schema_check.validate(p)
    assert len(out) == schema_check.HISTORY_VIOLATION_CAP + 1
    assert "7 more history-row violations" in out[-1]


def test_validate_never_raises_on_garbage():
    out1 = schema_check.validate({"nonsense": True})
    assert isinstance(out1, list) and len(out1) == 16
    out2 = schema_check.validate(None)
    assert isinstance(out2, list) and len(out2) == 1


def test_real_data_json_passes():
    data_path = os.path.join(os.path.dirname(__file__), "..", "site", "data.json")
    try:
        with open(data_path) as f:
            real = json.load(f)
    except FileNotFoundError:
        pytest.skip("site/data.json not present in this environment")
    assert schema_check.validate(real) == []
