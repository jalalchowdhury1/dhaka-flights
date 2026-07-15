import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import best_combos, cheapest_by_leg


def _f(route, depart, arrive, price):
    return {"route": route, "depart": depart, "arrive": arrive,
            "airline": "X", "stops": "1 stop", "duration": "10 hr",
            "layovers": "N/A", "price_total": price, "link": "http://x"}


# Baseline valid trip: arrive DAC Jan 5, leave Feb 2 (29 days incl. both ends),
# arrive Bali Feb 2, leave Feb 7 (5 nights), home Feb 7.
LEG1 = _f("BOS→DAC", "January 4, 2027", "January 5, 2027", 2400)
LEG2 = _f("DAC→DPS", "February 2, 2027", "February 2, 2027", 1100)
LEG3 = _f("DPS→BOS", "February 7, 2027", "February 7, 2027", 2700)


def test_valid_combo_found_with_correct_math():
    combos = best_combos([LEG1, LEG2, LEG3])
    assert len(combos) == 1
    c = combos[0]
    assert c["total"] == 6200
    assert c["dhaka_days"] == 29
    assert c["bali_nights"] == 5


def test_visa_cap_excludes_30_day_dhaka_stay():
    # Leaving Dhaka Feb 3 after arriving Jan 5 = 30 days incl. both ends
    leg2_late = _f("DAC→DPS", "February 3, 2027", "February 3, 2027", 900)
    leg3 = _f("DPS→BOS", "February 8, 2027", "February 8, 2027", 2700)  # 5 nights later
    assert best_combos([LEG1, leg2_late, leg3]) == []


def test_home_deadline_excludes_arrival_after_feb_7():
    leg3_late = _f("DPS→BOS", "February 7, 2027", "February 8, 2027", 2000)
    assert best_combos([LEG1, LEG2, leg3_late]) == []


def test_five_nights_preferred_over_cheaper_four_nights():
    leg3_4n = _f("DPS→BOS", "February 6, 2027", "February 6, 2027", 1000)  # 4 nights, cheaper
    combos = best_combos([LEG1, LEG2, LEG3, leg3_4n])
    assert combos[0]["bali_nights"] == 5
    assert combos[0]["total"] == 6200


def test_wrong_night_counts_excluded():
    leg3_2n = _f("DPS→BOS", "February 4, 2027", "February 4, 2027", 500)
    assert best_combos([LEG1, LEG2, leg3_2n]) == []


def test_missing_leg_yields_no_combo():
    assert best_combos([LEG1, LEG3]) == []


def test_unparsed_arrival_falls_back_to_route_lag():
    # BOS→DAC with arrive N/A → assume depart+1 = Jan 5, still valid
    leg1_na = _f("BOS→DAC", "January 4, 2027", "N/A", 2400)
    combos = best_combos([leg1_na, LEG2, LEG3])
    assert len(combos) == 1
    assert combos[0]["dhaka_days"] == 29


def test_na_prices_skipped():
    leg1_na = _f("BOS→DAC", "January 4, 2027", "January 5, 2027", "N/A")
    assert best_combos([leg1_na, LEG2, LEG3]) == []
    assert "BOS→DAC" not in cheapest_by_leg([leg1_na])


def test_cheapest_by_leg_picks_minimum():
    dear = _f("DAC→DPS", "February 1, 2027", "February 1, 2027", 1500)
    best = cheapest_by_leg([LEG1, LEG2, dear])
    assert best["DAC→DPS"]["price_total"] == 1100
