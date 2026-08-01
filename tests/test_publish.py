import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from publish import build_payload
from tests.test_main_trip import TICKET1, FLIGHTS, SG_TICKETS


def _payload(day="2026-07-25", history=None, flights=FLIGHTS,
             tickets1=(TICKET1,), sg=SG_TICKETS):
    return build_payload(list(flights), list(tickets1), list(history or []), day,
                         sg_tickets=list(sg))


def test_payload_has_all_sections():
    p = _payload()
    for key in ("updated", "trip", "main", "ticket1_options", "ticket2_options",
                "sg_tickets", "flights", "history"):
        assert key in p


def test_payload_carries_one_trip_not_a_menu():
    p = _payload()
    assert p["main"]["kind"] == "sg-stopover2"
    assert "structures" not in p and "singapore" not in p


def test_history_entry_splits_the_two_tickets():
    h = _payload()["history"][-1]
    assert h["date"] == "2026-07-25"
    assert h["main_total"] == 4600
    assert h["ticket1_total"] == 3600
    assert h["ticket2_total"] == 1000
    assert h["ticket1_airline"] == "Turkish Airlines"
    assert h["ist_nights"] == 2 and h["sg_nights"] == 2 and h["bkk_nights"] == 5
    assert h["order"] == "Singapore first"
    assert h["dhaka_days"] == 23 and h["home"] == "Feb 7"


def test_combined_total_still_written_so_the_chart_stays_continuous():
    # 8 days of pre-2026-07-25 history use the old key; both must agree.
    h = _payload()["history"][-1]
    assert h["combined_total"] == h["main_total"] == h["best_total"]


def test_history_keeps_the_full_trip_snapshot():
    h = _payload()["history"][-1]
    assert h["best_detail"]["openjaw"]["airline"] == "Turkish Airlines"
    assert h["best_detail"]["baggage"], "baggage rules of the day belong in history"


def test_baggage_is_attached_to_the_trip():
    m = _payload()["main"]
    assert [b["route"] for b in m["baggage"]][0] == "BOS→IST"
    assert m["baggage_warnings"] and m["baggage_checked"]


def test_alternatives_are_annotated_with_bag_rules():
    p = _payload()
    sq = next(o for o in p["ticket2_options"] if o["airline"] == "Singapore Airlines")
    assert sq["delta"] == 200
    assert "kg" in sq["baggage"]["checked"]
    assert p["ticket1_options"][0]["baggage"]["checked"].startswith("2 × 23")


def test_same_day_rerun_overwrites_not_duplicates():
    p1 = _payload()
    p2 = build_payload(FLIGHTS, [TICKET1], p1["history"], "2026-07-25",
                       sg_tickets=SG_TICKETS)
    assert len(p2["history"]) == 1


def test_new_day_appends():
    p1 = _payload("2026-07-25")
    p2 = build_payload(FLIGHTS, [TICKET1], p1["history"], "2026-07-26",
                       sg_tickets=SG_TICKETS)
    assert [h["date"] for h in p2["history"]] == ["2026-07-25", "2026-07-26"]


def test_empty_scrape_day_records_nulls_but_keeps_history():
    p1 = _payload("2026-07-25")
    p2 = build_payload([], [], p1["history"], "2026-07-26", sg_tickets=[])
    assert len(p2["history"]) == 2
    assert p2["history"][-1]["main_total"] is None
    assert p2["history"][-1]["best_detail"] is None
    assert p2["main"] is None


def test_old_history_entries_are_left_untouched():
    old = [{"date": "2026-07-24", "combined_total": 4665, "openjaw_total": 4465}]
    p = _payload("2026-07-25", history=old)
    assert p["history"][0] == old[0], "yesterday's record must never be rewritten"
