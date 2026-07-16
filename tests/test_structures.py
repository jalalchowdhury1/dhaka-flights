import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import best_structures
from tests.test_combo import LEG1, LEG2, LEG3, _f

# Open-jaw fixture: BOS→DAC Jan 4 (arrive Jan 6) + DPS→BOS Feb 6 = one ticket
OJ_FEB6 = {"out_date": "January 4, 2027", "ret_date": "February 6, 2027",
           "price_total": 3423, "airline": "Turkish Airlines",
           "out_arrive": "January 6, 2027", "stops": "1 stop",
           "duration": "22 hr 50 min", "layovers": "N/A", "link": "http://oj"}
OJ_FEB7 = dict(OJ_FEB6, ret_date="February 7, 2027", price_total=3382)

# Middle leg arriving Feb 1 → 5 nights before a Feb 6 return
MID_FEB1 = _f("DAC→DPS", "February 1, 2027", "February 1, 2027", 1340)


def test_openjaw_structure_beats_oneways_and_sorts_first():
    s = best_structures([LEG1, LEG2, LEG3, MID_FEB1], [OJ_FEB6])
    assert s[0]["name"].startswith("open-jaw")
    assert s[0]["total"] == 3423 + 1340
    assert s[0]["valid"] is True          # home Feb 7 heuristic (ret+1)
    assert s[0]["dhaka_days"] == 27       # Jan 6 → Feb 1 incl. both ends
    assert s[1]["name"] == "3 one-way tickets"
    assert s[1]["total"] == 6200


def test_feb7_return_flagged_invalid_but_reported():
    # Middle leg arriving Feb 2 gives 5 nights before a Feb 7 return
    mid_feb2 = _f("DAC→DPS", "February 1, 2027", "February 2, 2027", 1099)
    s = best_structures([mid_feb2], [OJ_FEB7])
    assert len(s) == 1
    assert s[0]["valid"] is False         # home Feb 8 > deadline
    assert s[0]["total"] == 3382 + 1099


def test_openjaw_without_compatible_middle_leg_is_dropped():
    # Only middle option arrives Feb 2 → 4 nights before Feb 6 return: no pair
    mid_feb2 = _f("DAC→DPS", "February 2, 2027", "February 2, 2027", 1100)
    s = best_structures([LEG1, mid_feb2, LEG3], [OJ_FEB6])
    assert all("openjaw" not in x for x in s)


def test_visa_cap_applies_to_openjaw_middle_leg():
    # Arrive DAC Jan 1 → leaving Feb 1 is 32 days: illegal pairing
    oj_early = dict(OJ_FEB6, out_date="December 31, 2026", out_arrive="January 1, 2027")
    s = best_structures([MID_FEB1], [oj_early])
    assert s == []


def test_no_openjaws_returns_oneway_structure_only():
    s = best_structures([LEG1, LEG2, LEG3], [])
    assert len(s) == 1
    assert s[0]["name"] == "3 one-way tickets"


# Turkish stopover fixture: 3 legs on one ticket, DAC arrival Jan 7
STOPOVER = {"kind": "stopover", "label": "Turkish + 30h Istanbul stopover (free hotel)",
            "desc": "BOS→IST Jan 4 · 30h Istanbul · IST→DAC Jan 6 + DPS→BOS Feb 6",
            "note": "Apply at Booker ≥72h before; N/R classes excluded.",
            "out_date": "January 4, 2027", "ret_date": "February 6, 2027",
            "price_total": 3688, "airline": "Turkish Airlines",
            "out_arrive": "January 7, 2027", "stops": "nonstop",
            "duration": "10 hr 20 min", "layovers": "none", "link": "http://tk"}


def test_stopover_structure_named_and_priced_separately():
    s = best_structures([MID_FEB1], [OJ_FEB6, STOPOVER])
    names = [x["name"] for x in s]
    assert "Turkish + 30h Istanbul stopover (free hotel)" in names
    stop = next(x for x in s if x["kind"] == "stopover")
    assert stop["total"] == 3688 + 1340
    assert stop["dhaka_days"] == 26          # Jan 7 → Feb 1 incl. both ends
    assert stop["note"].startswith("Apply")
    oj = next(x for x in s if x["kind"] == "openjaw")
    assert oj["total"] == 3423 + 1340


def test_stopover_uses_configured_dac_arrival_for_visa_math():
    # If arrival were Jan 5 (parsed IST arrival), Feb 1 departure = 28 days;
    # with the configured Jan 7 it must be 26.
    s = best_structures([MID_FEB1], [STOPOVER])
    assert s[0]["dhaka_days"] == 26
