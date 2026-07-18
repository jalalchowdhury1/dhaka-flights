import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import best_singapore
from tests.test_combo import LEG1, LEG3, _f   # BOS→DAC (arr Jan 5), DPS→BOS Feb 7
from tests.test_structures import OJ_FEB6

# Singapore-detour middle: DAC→SIN Jan 31 (2 nights) → SIN→DPS Feb 2 (arr Bali
# Feb 2). With LEG1 (arrive DAC Jan 5) and LEG3 (leave Bali Feb 7): Dhaka 27
# days, Bali 5 nights, home Feb 7 → a clean valid via-Singapore trip.
DAC_SIN = _f("DAC→SIN", "January 31, 2027", "January 31, 2027", 600)
SIN_DPS = _f("SIN→DPS", "February 2, 2027", "February 2, 2027", 200)
SG_TICKET = {"kind": "sg-ticket", "route": "DAC→SIN→DPS",
             "out_date": "January 31, 2027", "ret_date": "February 2, 2027",
             "out_arrive": "January 31, 2027", "price_total": 750,
             "airline": "Singapore Airlines", "stops": "nonstop",
             "duration": "x", "layovers": "N/A", "link": "http://sg"}


def test_builds_via_two_oneways():
    sg = best_singapore([LEG1, LEG3, DAC_SIN, SIN_DPS], [], [])
    assert sg, "expected a via-Singapore structure"
    s = sg[0]
    assert s["trip"] == "via-SIN"
    assert s["total"] == 2400 + 600 + 200 + 2700   # 5900
    assert s["sg_nights"] == 2
    assert s["bali_nights"] == 5
    assert s["dhaka_days"] == 27
    assert s["valid"] is True
    assert "2 one-ways" in s["name"]


def test_ticket_middle_wins_when_cheaper():
    # One-way middle = 800; the multi-city ticket = 750 → ticket should win.
    sg = best_singapore([LEG1, LEG3, DAC_SIN, SIN_DPS], [], [SG_TICKET])
    s = sg[0]
    assert s["total"] == 2400 + 750 + 2700          # 5850
    assert "1 ticket" in s["name"]
    assert s["sg_ticket"] is not None


def test_openjaw_long_legs_branch():
    # Long legs as the Feb-6 open-jaw ticket (arrive DAC Jan 6, ret Feb 6);
    # need Bali arrival Feb 1 for 5 nights → SIN→DPS arrives Feb 1.
    dac_sin = _f("DAC→SIN", "January 30, 2027", "January 30, 2027", 600)
    sin_dps = _f("SIN→DPS", "February 1, 2027", "February 1, 2027", 200)
    sg = best_singapore([dac_sin, sin_dps], [OJ_FEB6], [])
    kinds = {s["kind"] for s in sg}
    assert "sg-openjaw" in kinds
    oj = next(s for s in sg if s["kind"] == "sg-openjaw")
    assert oj["total"] == 3423 + 800
    assert oj["bali_nights"] == 5
    assert oj["valid"] is True


def test_no_singapore_data_returns_empty():
    assert best_singapore([LEG1, LEG3], [], []) == []


def test_offnight_bali_pairing_kept_but_flagged():
    # SIN→DPS arrives Feb 3 → only 4 Bali nights before a Feb 7 return.
    sin_dps_late = _f("SIN→DPS", "February 3, 2027", "February 3, 2027", 200)
    sg = best_singapore([LEG1, LEG3, DAC_SIN, sin_dps_late], [], [])
    assert sg
    s = sg[0]
    assert s["bali_nights"] == 4
    assert s["valid"] is False
    assert "4-night" in (s["flag"] or "")
