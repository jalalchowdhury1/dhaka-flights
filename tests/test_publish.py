import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from publish import build_payload
from tests.test_combo import LEG1, LEG2, LEG3
from tests.test_structures import OJ_FEB6, MID_FEB1

FLIGHTS = [LEG1, LEG2, LEG3, MID_FEB1]
OPENJAWS = [OJ_FEB6]


def test_payload_has_all_sections():
    p = build_payload(FLIGHTS, OPENJAWS, [], "2026-07-15")
    for key in ("updated", "trip", "structures", "combos", "cheapest_by_leg",
                "openjaws", "flights", "history"):
        assert key in p


def test_history_entry_fields_complete():
    p = build_payload(FLIGHTS, OPENJAWS, [], "2026-07-15")
    h = p["history"][-1]
    assert h["date"] == "2026-07-15"
    assert h["best_total"] == 3423 + 1340
    assert h["best_structure"].startswith("open-jaw")
    assert h["best_detail"]["total"] == h["best_total"]
    assert h["best_detail"]["openjaw"]["airline"] == "Turkish Airlines"
    assert h["oneway_combo_total"] == 6200
    assert h["openjaw_total"] == 3423 + 1340
    assert h["openjaw_min"] == {"February 6, 2027": 3423}
    assert h["legs_min"]["DAC→DPS"] == 1100


def test_same_day_rerun_overwrites_not_duplicates():
    p1 = build_payload(FLIGHTS, OPENJAWS, [], "2026-07-15")
    p2 = build_payload(FLIGHTS, OPENJAWS, p1["history"], "2026-07-15")
    assert len(p2["history"]) == 1


def test_new_day_appends():
    p1 = build_payload(FLIGHTS, OPENJAWS, [], "2026-07-15")
    p2 = build_payload(FLIGHTS, OPENJAWS, p1["history"], "2026-07-16")
    assert [h["date"] for h in p2["history"]] == ["2026-07-15", "2026-07-16"]


def test_empty_scrape_day_records_nulls_but_keeps_history():
    p1 = build_payload(FLIGHTS, OPENJAWS, [], "2026-07-15")
    p2 = build_payload([], [], p1["history"], "2026-07-16")
    assert len(p2["history"]) == 2
    assert p2["history"][-1]["best_total"] is None
    assert p2["history"][-1]["best_detail"] is None


def test_stopover_total_tracked_separately_from_openjaw():
    from tests.test_structures import STOPOVER
    p = build_payload(FLIGHTS, OPENJAWS + [STOPOVER], [], "2026-07-15")
    h = p["history"][-1]
    assert h["openjaw_total"] == 3423 + 1340
    assert h["stopover_total"] == 3688 + 1340
