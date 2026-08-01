import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import main_trip
from sanity import self_check
from scraper import LEGS, TICKET2_SEARCHES
from tests.test_combo import _f
from tests.test_main_trip import (TICKET1, TICKET1_SIN, TICKET2, DAC_SIN,
                                  SIN_BKK, TICKET2_BKK_FIRST, FLIGHTS, SG_TICKETS)


def _full_coverage(flights=FLIGHTS):
    """Pad fares so the coverage invariant stays quiet in unrelated tests."""
    fares = list(flights)
    seen = {(f["route"], f["depart"]) for f in fares}
    for leg in LEGS:
        route = f"{leg['origin']}→{leg['dest']}"
        for date in leg["dates"]:
            if (route, date) not in seen:
                fares.append(_f(route, date, date, 9999))
    return fares


def _all_ticket2_pairs():
    """One Ticket ② fare per scraped order+date pair, so invariant 3 stays quiet."""
    out = list(SG_TICKETS)
    have = {(t.get("order"), t["out_date"], t["ret_date"]) for t in out}
    for order, d1, d2 in TICKET2_SEARCHES:
        if (order, d1, d2) not in have:
            base = TICKET2 if order == "SIN-first" else TICKET2_BKK_FIRST
            out.append(dict(base, order=order, out_date=d1, ret_date=d2,
                            out_arrive=d1, price_total=9999))
    return out


def _check(flights=None, tickets1=(TICKET1, TICKET1_SIN), sg=None, prev=None):
    flights = _full_coverage() if flights is None else flights
    sg = _all_ticket2_pairs() if sg is None else sg
    trip = main_trip(flights, list(tickets1), sg)
    return self_check(flights, list(tickets1), trip, prev, sg_tickets=sg)


def test_clean_day_produces_no_warnings():
    assert _check() == []


def test_missing_ticket1_is_the_loudest_warning():
    w = _check(tickets1=())
    assert any("Ticket ①" in x and "NO fares" in x for x in w)


def test_ticket1_priced_but_no_trip_built_warns():
    # Ticket ① exists, but no middle can pair with it in either order.
    w = _check(flights=[], sg=[])
    assert any("NO trip was built" in x or "no trip used them" in x for x in w)


def test_one_orders_ticket1_variant_empty_warns():
    # Only the BKK→BOS return priced → the Bangkok-first order never competed;
    # tonight's "cheaper order" claim would be hollow without a warning.
    w = _check(tickets1=(TICKET1,))
    assert any("SIN→BOS return" in x and "Bangkok-first" in x for x in w)


def test_missing_leg_date_warns():
    flights = [f for f in _full_coverage()
               if not (f["route"] == "DAC→SIN" and f["depart"] == "January 29, 2027")]
    w = _check(flights=flights)
    assert any("DAC→SIN" in x and "Jan 29" in x for x in w)


def test_missing_ticket2_date_pair_warns():
    w = _check(sg=SG_TICKETS)          # only the Jan 30 + Feb 1 pair is present
    assert any("Ticket ②" in x and "no" in x.lower() for x in w)


def test_metric_that_vanished_since_yesterday_warns():
    prev = {"main_total": 4600, "ticket1_total": 3600, "ticket2_total": 1000}
    w = _check(tickets1=(), prev=prev)
    assert any("MAIN trip total" in x and "MISSING" in x for x in w)


def test_pre_rewrite_history_key_still_compares():
    # Yesterday's file used combined_total; a swing must still be detected.
    w = _check(prev={"combined_total": 3000})
    assert any("big swing" in x for x in w)


def test_big_swing_warns():
    w = _check(prev={"main_total": 3000, "ticket1_total": 3600, "ticket2_total": 1000})
    assert any("big swing" in x for x in w)


def test_shape_drift_is_reported():
    # An overnight arrival that leaves only 1 Singapore night is allowed to win
    # on price — but it must never be a silent surprise.
    one_night = dict(TICKET2, out_arrive="January 31, 2027")
    w = _check(flights=[], sg=[one_night])
    assert any("Singapore night" in x for x in w)


def test_parser_drift_warns():
    flights = [dict(f, arrive="N/A") for f in _full_coverage()]
    w = _check(flights=flights)
    assert any("arrival date failed to parse" in x for x in w)


def test_three_singapore_nights_are_not_shape_drift():
    # 2-4 SIN nights are the flex band (2026-08-01) — no warning noise.
    three = dict(TICKET2, out_date="January 29, 2027",
                 out_arrive="January 29, 2027", ret_date="February 1, 2027")
    w = _check(flights=[], sg=[three])
    assert not any("Singapore night" in x for x in w)
