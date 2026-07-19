import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import best_structures, best_singapore
from publish import build_payload
from scraper import STOPOVER_SEARCHES, ISTANBUL2_SEARCH
from tests.test_combo import LEG1, LEG2, LEG3, _f
from tests.test_structures import OJ_FEB6, MID_FEB1

# Istanbul 2-night one-ticket fixture: arrive DAC Jan 8, return Feb 6.
IST2 = {"kind": "stopover2", "label": "Istanbul 2-night stopover",
        "out_date": "January 4, 2027", "ret_date": "February 6, 2027",
        "out_arrive": "January 8, 2027", "price_total": 3600,
        "airline": "Turkish Airlines", "stops": "1 stop", "duration": "x",
        "layovers": "N/A", "link": "http://ist2",
        "desc": "BOS→IST Jan 4 · 2 nights Istanbul · IST→DAC Jan 7 + DPS→BOS Feb 6 — one ticket",
        "note": "n"}


def test_search_config_has_all_stopover_variants():
    kinds = [c["kind"] for c in STOPOVER_SEARCHES]
    # 2- and 3-night Istanbul share kind stopover2 so history's istanbul2_total
    # tracks the cheaper of the two automatically.
    assert kinds == ["stopover", "stopover2", "stopover2"]
    assert ISTANBUL2_SEARCH["airline_filter"] is None
    # 2-night version: IST→DAC on Jan 7 (vs Jan 6 for the 30h stopover)
    assert ISTANBUL2_SEARCH["legs"][1] == ("IST", "DAC", "January 7, 2027")
    from scraper import ISTANBUL3_SEARCH
    assert ISTANBUL3_SEARCH["legs"][1] == ("IST", "DAC", "January 8, 2027")
    assert ISTANBUL3_SEARCH["kind"] == "stopover2"


def test_istanbul2_builds_structure_with_shorter_dhaka():
    s = best_structures([LEG1, LEG2, LEG3, MID_FEB1], [OJ_FEB6, IST2])
    ist = next(x for x in s if x.get("kind") == "stopover2")
    assert ist["total"] == 3600 + 1340         # ticket + DAC→DPS Feb 1 middle
    # arrive Dhaka Jan 8, leave Feb 1 → 25 days (both ends), vs 27 for the OJ
    assert ist["dhaka_days"] == 25
    assert ist["bali_nights"] == 5
    assert ist["valid"] is True


def test_payload_tracks_istanbul2_and_singapore_totals():
    p = build_payload([LEG1, LEG2, LEG3, MID_FEB1], [OJ_FEB6, IST2], [], "2026-07-18")
    h = p["history"][-1]
    assert h["istanbul2_total"] == 3600 + 1340
    assert "singapore_total" in h
    assert "singapore" in p
