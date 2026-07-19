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


def test_exactly_two_sg_nights_required():
    # 2026-07-18 final rule: EXACTLY 2 Singapore nights. A cheaper 1-night
    # pairing must be ignored in favor of the 2-night one.
    dac_sin_late = _f("DAC→SIN", "February 1, 2027", "February 1, 2027", 300)  # 1 SG night
    sg = best_singapore([LEG1, LEG3, DAC_SIN, SIN_DPS, dac_sin_late], [], [])
    s = sg[0]
    assert s["sg_nights"] == 2
    assert s["total"] == 2400 + 600 + 200 + 2700   # the 2-night middle, not the $300 1-night
    assert s["valid"] is True


def test_offnight_bali_pairing_kept_but_flagged():
    # 2-night SG pairing whose Bali arrival (Feb 3) leaves only 4 Bali nights
    # before the Feb 7 return — kept but flagged.
    dac_sin_f1 = _f("DAC→SIN", "February 1, 2027", "February 1, 2027", 600)
    sin_dps_late = _f("SIN→DPS", "February 3, 2027", "February 3, 2027", 200)
    sg = best_singapore([LEG1, LEG3, dac_sin_f1, sin_dps_late], [], [])
    assert sg
    s = sg[0]
    assert s["bali_nights"] == 4
    assert s["valid"] is False
    assert "4-night" in (s["flag"] or "")


# ── combined trip + airline rules (2026-07-18) ──────────────────────────────
IST2_OJ = {"kind": "stopover2", "label": "Istanbul 2-night stopover", "ist_nights": 2,
           "out_date": "January 4, 2027", "ret_date": "February 6, 2027",
           "out_arrive": "January 8, 2027", "price_total": 3600,
           "airline": "Turkish Airlines", "stops": "1 stop", "duration": "x",
           "layovers": "N/A", "link": "http://ist2", "desc": "d", "note": "n"}


def test_combined_istanbul_plus_singapore_is_built():
    # IST2 ticket long legs (arrive DAC Jan 8) + SG middle arriving Bali Feb 1
    # (5 nights before the Feb 6 return) = the MAIN trip.
    dac_sin = _f("DAC→SIN", "January 30, 2027", "January 30, 2027", 600)
    sin_dps = _f("SIN→DPS", "February 1, 2027", "February 1, 2027", 200)
    sg = best_singapore([dac_sin, sin_dps], [IST2_OJ], [])
    main = next(s for s in sg if s["kind"] == "sg-stopover2")
    assert main["total"] == 3600 + 800
    assert main["ist_nights"] == 2
    assert main["dhaka_days"] == 23        # Jan 8 → Jan 30 incl. both ends
    assert main["bali_nights"] == 5
    assert main["valid"] is True


def test_us_bangla_is_allowed_and_wins_when_cheapest():
    # Revised same day: US-Bangla prices are unbeatable — cheapest wins.
    usb = dict(_f("DAC→SIN", "January 31, 2027", "January 31, 2027", 100),
               airline="US-Bangla Airlines")
    sg = best_singapore([LEG1, LEG3, usb, DAC_SIN, SIN_DPS], [], [])
    s = sg[0]
    assert "US-Bangla" in s["sg_airlines"]
    assert s["total"] == 2400 + 100 + 200 + 2700


def test_cheapest_wins_with_thai_sq_upsell_note():
    cheap_other = dict(_f("DAC→SIN", "January 31, 2027", "January 31, 2027", 400),
                       airline="Biman")
    sq = dict(_f("DAC→SIN", "January 31, 2027", "January 31, 2027", 600),
              airline="Singapore Airlines")
    sq2 = dict(_f("SIN→DPS", "February 2, 2027", "February 2, 2027", 200),
               airline="THAI")
    sg = best_singapore([LEG1, LEG3, cheap_other, sq, sq2], [], [])
    s = sg[0]
    assert s["total"] == 2400 + 400 + 200 + 2700   # cheapest (Biman) wins
    assert s["sg_preferred"] is False
    assert "THAI/Singapore Airlines option +$200" in (s["alt_note"] or "")


def test_mixed_airline_ticket_is_not_preferred():
    from combo import _is_preferred
    assert _is_preferred("Singapore Airlines") is True
    assert _is_preferred("THAI") is True
    assert _is_preferred("Malaysia Airlines and Singapore Airlines") is False
    assert _is_preferred("Thai Lion Air") is False
    assert _is_preferred("THAI and Singapore Airlines") is True
