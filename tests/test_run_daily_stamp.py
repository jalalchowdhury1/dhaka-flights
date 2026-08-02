"""should_stamp decides whether tonight's run counts as done. A trip with no
usable Telegram brief (the "minimal" rung — build_message and send_message
both failed all the way down) is the same "come back at 2:00/4:00" situation
as a catastrophic no-trip night, so neither may stamp .last_run_date."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_daily


def test_trip_and_full_brief_stamps():
    assert run_daily.should_stamp({"main": {"total": 1}}, "full") is True


def test_trip_and_core_brief_stamps():
    assert run_daily.should_stamp({"main": {"total": 1}}, "core") is True


def test_trip_but_minimal_brief_does_not_stamp():
    assert run_daily.should_stamp({"main": {"total": 1}}, "minimal") is False


def test_trip_but_delivery_totally_failed_still_stamps():
    # "none" means build_message succeeded (the trip data is good and will
    # still publish) but every send attempt failed — a Telegram-delivery
    # problem, not a data problem. A re-scrape at 2:00/4:00 can't fix
    # "Telegram is unreachable," so this is unlike "minimal" (a broken
    # build) and should still count tonight as done.
    assert run_daily.should_stamp({"main": {"total": 1}}, "none") is True


def test_no_trip_never_stamps_regardless_of_notify_status():
    assert run_daily.should_stamp({"main": None}, "full") is False
    assert run_daily.should_stamp({"main": {}}, "full") is False
