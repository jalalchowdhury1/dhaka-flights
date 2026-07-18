import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import best_structures, best_singapore
from sanity import self_check
from tests.test_combo import LEG1, LEG2, LEG3, _f
from tests.test_structures import OJ_FEB6, STOPOVER, MID_FEB1

ALL_FLIGHTS = [LEG1, LEG2, LEG3, MID_FEB1]


def _full_coverage(flights):
    """Pad fares so invariant 2 (every leg×date has a fare) stays quiet."""
    from scraper import LEGS
    fares = list(flights)
    seen = {(f["route"], f["depart"]) for f in fares}
    for leg in LEGS:
        route = f"{leg['origin']}→{leg['dest']}"
        for date in leg["dates"]:
            if (route, date) not in seen:
                fares.append(_f(route, date, date, 9999))
    return fares


def test_clean_day_produces_no_warnings():
    flights = _full_coverage(ALL_FLIGHTS)
    ojs = [OJ_FEB6, STOPOVER]
    sg = best_singapore(flights, ojs, [])   # padded SIN legs → a via-SIN trip exists
    w = self_check(flights, ojs, best_structures(flights, ojs), sg=sg)
    assert w == []


def test_scraped_variant_with_no_structure_warns():
    # Open-jaw scraped, but zero DAC→DPS fares in any legal window → invariant 1
    flights = _full_coverage([LEG1, LEG3])
    flights = [f for f in flights if f["route"] != "DAC→DPS"]
    structures = best_structures(flights, [OJ_FEB6])
    w = self_check(flights, [OJ_FEB6], structures)
    assert any("NO structure" in x for x in w)


def test_missing_search_date_warns():
    flights = _full_coverage(ALL_FLIGHTS)
    flights = [f for f in flights if not (f["route"] == "DAC→DPS" and
                                          f["depart"] == "January 31, 2027")]
    w = self_check(flights, [OJ_FEB6], best_structures(flights, [OJ_FEB6]))
    assert any("Jan 31" in x and "no fares" in x for x in w)


def test_metric_that_vanished_since_yesterday_warns():
    flights = _full_coverage(ALL_FLIGHTS)
    structures = best_structures(flights, [OJ_FEB6])  # no stopover today
    prev = {"stopover_total": 5028, "openjaw_total": 4763, "oneway_combo_total": 6229}
    w = self_check(flights, [OJ_FEB6], structures, prev)
    assert any("Turkish stopover structure" in x and "MISSING" in x for x in w)


def test_big_swing_warns():
    flights = _full_coverage(ALL_FLIGHTS)
    structures = best_structures(flights, [OJ_FEB6])
    prev = {"openjaw_total": 3000}  # today's is 4763 → +59%
    w = self_check(flights, [OJ_FEB6], structures, prev)
    assert any("big swing" in x for x in w)


def test_parser_drift_warns():
    flights = [dict(f, arrive="N/A") for f in _full_coverage(ALL_FLIGHTS)]
    w = self_check(flights, [], [], None)
    assert any("arrival date failed to parse" in x for x in w)
