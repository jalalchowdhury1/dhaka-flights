import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import best_structures
from scraper import (STOPOVER_SEARCHES, ISTANBUL2_SEARCH, LEGS,
                     OPENJAW_SEARCHES, TICKET1_ATTEMPTS)
from tests.test_combo import LEG1, LEG2, LEG3
from tests.test_structures import OJ_FEB6, MID_FEB1

# Istanbul 2-night one-ticket fixture: arrive DAC Jan 8, return Feb 6.
IST2 = {"kind": "stopover2", "label": "Istanbul 2-night stopover",
        "out_date": "January 4, 2027", "ret_date": "February 6, 2027",
        "out_arrive": "January 8, 2027", "price_total": 3600,
        "airline": "Turkish Airlines", "stops": "1 stop", "duration": "x",
        "layovers": "N/A", "link": "http://ist2",
        "desc": "BOS→IST Jan 4 · 2 nights Istanbul · IST→DAC Jan 7 + DPS→BOS Feb 6 — one ticket",
        "note": "n"}


def test_ticket1_is_one_two_night_istanbul_search_per_order():
    # 2026-08-01: two Ticket ① searches, one per city order — same Istanbul
    # front, the return leg from whichever city the order visits last. The TK
    # 30h variant, the plain open-jaw and the Bali (DPS) return stay retired.
    assert [c["kind"] for c in STOPOVER_SEARCHES] == ["stopover2", "stopover2"]
    assert sorted(c["ret_city"] for c in STOPOVER_SEARCHES) == ["BKK", "SIN"]
    for c in STOPOVER_SEARCHES:
        assert c["airline_filter"] is None
        assert c["legs"][1] == ("IST", "DAC", "January 7, 2027")
        assert c["legs"][2] == (c["ret_city"], "BOS", "February 6, 2027")
    assert ISTANBUL2_SEARCH["legs"][2][0] == "DPS", "Bali config kept, just not scraped"
    assert OPENJAW_SEARCHES, "config kept, just not scraped"


def test_only_the_ticket2_middle_legs_are_scraped_as_one_ways():
    assert [(l["origin"], l["dest"]) for l in LEGS] == [
        ("DAC", "SIN"), ("SIN", "BKK"), ("DAC", "BKK"), ("BKK", "SIN")]


def test_ticket1_gets_extra_attempts_since_nothing_can_replace_it():
    assert TICKET1_ATTEMPTS >= 2


def test_istanbul2_builds_structure_with_shorter_dhaka():
    s = best_structures([LEG1, LEG2, LEG3, MID_FEB1], [OJ_FEB6, IST2])
    ist = next(x for x in s if x.get("kind") == "stopover2")
    assert ist["total"] == 3600 + 1340         # ticket + DAC→DPS Feb 1 middle
    # arrive Dhaka Jan 8, leave Feb 1 → 25 days (both ends), vs 27 for the OJ
    assert ist["dhaka_days"] == 25
    assert ist["bali_nights"] == 5
    assert ist["valid"] is True
