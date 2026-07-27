import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from combo import main_trip, budget_trip
from tests.test_combo import _f
from tests.test_singapore import IST2_OJ, ONE_NIGHT_TICKET

# The 💸 budget companion (Jalal 2026-07-27): "also present one which is
# cheaper, like the 1-night option — feel free to squeeze dates in Bangladesh".
# Same Ticket ①, same Bali block; the minimum-2-Singapore-nights rule is
# waived (≥1) and the Dhaka dates may shift. Shown ONLY when strictly cheaper
# than the main trip.

DAC_SIN_2N = _f("DAC→SIN", "January 30, 2027", "January 30, 2027", 600)
SIN_DPS_F1 = _f("SIN→DPS", "February 1, 2027", "February 1, 2027", 200)


def _main(flights, sg_tickets):
    return main_trip(flights, [IST2_OJ], sg_tickets)


def test_budget_offers_the_cheaper_one_night_ticket():
    flights = [DAC_SIN_2N, SIN_DPS_F1]
    main = _main(flights, [ONE_NIGHT_TICKET])
    assert main["total"] == 3600 + 800          # min-2 rule keeps the 2-night middle
    b = budget_trip(flights, [ONE_NIGHT_TICKET], main)
    assert b is not None
    assert b["kind"] == "sg-budget"
    assert b["total"] == 3600 + 700
    assert b["savings"] == 100
    assert b["sg_nights"] == 1
    assert b["valid"] is True and b["flag"] is None
    assert any("1 Singapore night" in d for d in b["diffs"])


def test_budget_none_when_nothing_cheaper():
    flights = [DAC_SIN_2N, SIN_DPS_F1]
    main = _main(flights, [])
    assert budget_trip(flights, [], main) is None


def test_budget_none_without_a_main_trip():
    assert budget_trip([DAC_SIN_2N, SIN_DPS_F1], [], None) is None


def test_budget_diffs_name_the_dhaka_shift():
    # A 1-night day-flight ticket leaving Dhaka Jan 31 — one Dhaka day MORE
    # than the main trip's Jan 30 departure. Both diffs must be spelled out.
    late = dict(ONE_NIGHT_TICKET, out_date="January 31, 2027",
                out_arrive="January 31, 2027", price_total=650)
    flights = [DAC_SIN_2N, SIN_DPS_F1]
    main = _main(flights, [late])
    b = budget_trip(flights, [late], main)
    assert b["total"] == 3600 + 650
    assert b["dhaka_days"] == main["dhaka_days"] + 1
    assert any("1 Singapore night" in d for d in b["diffs"])
    assert any("Dhaka day" in d for d in b["diffs"])


def test_publish_payload_carries_budget_and_history_total():
    import publish
    flights = [DAC_SIN_2N, SIN_DPS_F1]
    p = publish.build_payload(flights, [IST2_OJ], [], "2026-07-27",
                              warnings=[], sg_tickets=[ONE_NIGHT_TICKET])
    assert p["budget"]["total"] == 4300
    assert p["history"][-1]["budget_total"] == 4300
    p2 = publish.build_payload(flights, [IST2_OJ], [], "2026-07-27",
                               warnings=[], sg_tickets=[])
    assert p2["budget"] is None
    assert p2["history"][-1]["budget_total"] is None


def test_telegram_shows_budget_block_only_when_present():
    import publish
    from notify_telegram import build_message
    flights = [DAC_SIN_2N, SIN_DPS_F1]
    p = publish.build_payload(flights, [IST2_OJ], [], "2026-07-27",
                              warnings=[], sg_tickets=[ONE_NIGHT_TICKET])
    msg = build_message(p)
    assert "Cheaper if flexible" in msg and "$4,300" in msg and "save $100" in msg
    p2 = publish.build_payload(flights, [IST2_OJ], [], "2026-07-27",
                               warnings=[], sg_tickets=[])
    assert "Cheaper if flexible" not in build_message(p2)


def test_history_row_appends_budget_column():
    from sheet_writer import history_row, HISTORY_HEADERS
    assert HISTORY_HEADERS[-1] == "💸 Budget $"
    row = history_row({"date": "2026-07-27", "main_total": 5048, "budget_total": 4669})
    assert len(row) == len(HISTORY_HEADERS)
    assert row[-1] == 4669
    assert history_row({"date": "x"})[-1] == ""     # no budget day → blank cell
