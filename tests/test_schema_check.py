"""Payload contract: the exact shape site/index.html renders from.
A violation must come back as a human-readable warning, never an exception."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
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
    out = " ".join(schema_check.validate(p))
    assert "history" in out


def test_wrong_type_is_reported():
    p = _payload()
    p["warnings"] = "oops a string"
    out = " ".join(schema_check.validate(p))
    assert "warnings" in out


def test_history_entry_shape_is_checked():
    p = _payload()
    p["history"][-1].pop("date")
    out = " ".join(schema_check.validate(p))
    assert "date" in out


def test_main_total_must_be_number_when_trip_exists():
    p = _payload()
    p["main"]["total"] = "4626"
    out = " ".join(schema_check.validate(p))
    assert "total" in out


def test_validate_never_raises_on_garbage():
    assert isinstance(schema_check.validate({"nonsense": True}), list)
    assert isinstance(schema_check.validate(None), list)


def test_real_data_json_passes():
    import json
    data_path = os.path.join(os.path.dirname(__file__), "..", "site", "data.json")
    with open(data_path) as f:
        real = json.load(f)
    assert schema_check.validate(real) == []
