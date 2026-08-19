"""Tests for the hotel-aware SIN night-count layer (stay math, 2026-08-19).
Spec: docs/superpowers/specs/2026-08-19-hotel-aware-sin-nights-design.md"""
import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stay_value

TODAY = datetime.date(2026, 8, 19)

RATES = {
    "updated": "2026-08-19",
    "rows": [
        {"key": "ritz_ist", "city": "IST", "name": "Ritz-Carlton Istanbul",
         "program": "FHR", "bold": True, "rate": 439, "checked": "2026-08-19"},
        {"key": "stregis_sin", "city": "SIN", "name": "St. Regis Singapore",
         "program": "FHR", "bold": True, "rate": 218, "checked": "2026-08-19"},
        {"key": "panpacific", "city": "SIN", "name": "Pan Pacific Orchard",
         "program": "THC + Edit", "bold": False, "rate": 255,
         "checked": "2026-08-19"},
    ],
}


def test_credits_scale_with_nights():
    assert stay_value.credits(2) == 520          # $400/stay + $60×2
    assert stay_value.credits(3) == 580
    assert stay_value.credits(4) == 640


def test_edit_only_programs_get_the_smaller_fixed_credit():
    assert stay_value.credits(2, "The Edit only") == 470   # $350 + $120
    assert stay_value.credits(2, "THC + Edit") == 470
    assert stay_value.credits(2, "FHR") == 520


def test_hotel_net_floors_at_zero():
    # 2×218×1.12 = 488.32 < $520 credits — credits beyond the bill are NOT cash back
    assert stay_value.hotel_net(218, 2) == 0


def test_hotel_net_at_three_and_four():
    assert stay_value.hotel_net(218, 3) == 152
    assert stay_value.hotel_net(218, 4) == 337


def test_bold_row_finds_the_sin_play_not_the_ist_one():
    row = stay_value.bold_row(RATES)
    assert row["key"] == "stregis_sin"


def test_bold_row_none_when_rate_missing():
    r = {"rows": [{"key": "x", "city": "SIN", "bold": True, "rate": None}]}
    assert stay_value.bold_row(r) is None
    assert stay_value.bold_row(None) is None
    assert stay_value.bold_row({}) is None


def test_mode_ladder():
    assert stay_value.mode(RATES, TODAY) == "steering"          # checked today
    assert stay_value.mode(RATES, datetime.date(2026, 8, 22)) == "steering"  # 3d = limit
    assert stay_value.mode(RATES, datetime.date(2026, 8, 23)) == "advisory"  # 4d = stale
    assert stay_value.mode(None, TODAY) == "off"
    assert stay_value.mode({"rows": []}, TODAY) == "off"


def test_score_adjust_values_extra_nights_at_the_knob():
    # f(n) = net − 225×(n−2) − dead-band bonus
    assert stay_value.score_adjust(218, 2, None) == 0
    assert stay_value.score_adjust(218, 3, None) == 152 - 225      # −73
    assert stay_value.score_adjust(218, 4, None) == 337 - 450      # −113


def test_score_adjust_gives_the_incumbent_the_dead_band():
    assert stay_value.score_adjust(218, 2, 2) == -25
    assert stay_value.score_adjust(218, 4, 2) == -113              # not incumbent


def test_hook_none_unless_steering():
    assert stay_value.hotel_hook(None, None, today=TODAY) is None
    stale = {"rows": [dict(RATES["rows"][1], checked="2026-08-10")]}
    assert stay_value.hotel_hook(stale, None, today=TODAY) is None


def test_hook_returns_the_adjuster_when_fresh():
    h = stay_value.hotel_hook(RATES, None, today=TODAY)
    assert h(2) == 0 and h(3) == -73 and h(4) == -113
    h2 = stay_value.hotel_hook(RATES, 2, today=TODAY)
    assert h2(2) == -25
