"""The hotel-rate refresh must be FAIL-CLOSED: a page that doesn't prove both
the property and the dates may never yield a number, because a plausible-but-
wrong nightly rate silently corrupts every offset band on the Stays screen."""
import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hotel_rates as hr

JAN5 = datetime.date(2027, 1, 5)
JAN7 = datetime.date(2027, 1, 7)
ENTRY = {"key": "ritz_ist", "city": "IST", "name": "Ritz-Carlton Istanbul",
         "query": "Ritz Carlton Istanbul", "match": "Ritz-Carlton",
         "program": "FHR", "angle": "x"}

GOOD_TREE = "\n".join([
    "[0-1] RootWebArea: The Ritz-Carlton, Istanbul - Google hotels",
] + [f"[0-{i}] div" for i in range(60)] + [
    "[0-900] StaticText: $425",
    "Jan 5 – 7, 2027",
])


def test_good_page_yields_rate():
    rate, note = hr.parse_rate(GOOD_TREE, "The Ritz-Carlton, Istanbul - Google hotels",
                               ENTRY, JAN5, JAN7)
    assert rate == 425 and note == "ok"


def test_wrong_dates_are_rejected():
    tree = GOOD_TREE.replace("Jan 5 – 7, 2027", "Aug 9 – 10, 2026")
    rate, note = hr.parse_rate(tree, "The Ritz-Carlton, Istanbul", ENTRY, JAN5, JAN7)
    assert rate is None and "did not bind" in note


def test_wrong_hotel_is_rejected():
    rate, note = hr.parse_rate(GOOD_TREE, "Hilton Istanbul - Google hotels",
                               ENTRY, JAN5, JAN7)
    assert rate is None and "expected Ritz-Carlton" in note


def test_no_results_page_is_rejected():
    tree = GOOD_TREE + "\nNo results"
    rate, note = hr.parse_rate(tree, "The Ritz-Carlton, Istanbul", ENTRY, JAN5, JAN7)
    assert rate is None


def test_empty_page_is_rejected():
    rate, note = hr.parse_rate("", "", ENTRY, JAN5, JAN7)
    assert rate is None and "empty" in note


def test_sidebar_price_alone_is_not_accepted():
    """Other hotels' prices litter the sidebar; without the date anchor next to
    a price we must return nothing rather than grab the first dollar figure."""
    tree = "\n".join([
        "[0-1] RootWebArea: The Ritz-Carlton, Istanbul - Google hotels",
    ] + [f"[0-{i}] div" for i in range(60)] + [
        "[0-500] link: $141 InterContinental Istanbul",
        "Jan 5 – 7, 2027 is your stay",   # dates present, but no price beside them
    ])
    rate, _ = hr.parse_rate(tree, "The Ritz-Carlton, Istanbul", ENTRY, JAN5, JAN7)
    assert rate != 141


def test_cross_month_stay_matches_googles_long_form():
    """A Jan 31 -> Feb 2 stay renders as 'Jan 31 – Feb 2'; the same-month
    shorthand would never match and every night would look like a mismatch."""
    e = dict(ENTRY, match="St. Regis")
    tree = "\n".join([
        "[0-1] RootWebArea: The St. Regis Singapore - Google hotels",
    ] + [f"[0-{i}] div" for i in range(60)] + [
        "[0-900] StaticText: $329", "Jan 31 – Feb 2, 2027",
    ])
    rate, note = hr.parse_rate(tree, "The St. Regis Singapore", e,
                               datetime.date(2027, 1, 31), datetime.date(2027, 2, 2))
    assert rate == 329, note


def test_same_month_shorthand_does_not_match_a_different_day():
    """'Feb 2 – 6' must not satisfy a request for Feb 2 – 16."""
    e = dict(ENTRY, match="Pan Pacific")
    tree = "\n".join([
        "[0-1] RootWebArea: Pan Pacific Orchard - Google hotels",
    ] + [f"[0-{i}] div" for i in range(60)] + [
        "[0-900] StaticText: $252", "Feb 2 – 6, 2027",
    ])
    rate, _ = hr.parse_rate(tree, "Pan Pacific Orchard", e,
                            datetime.date(2027, 2, 2), datetime.date(2027, 2, 16))
    assert rate is None


def test_offset_math_matches_the_published_bands():
    # IST 2 nights, $520 credits: the site's long-standing ~74% for a $314 room.
    assert hr.offset_pct(314, 2, 520) == 74
    # and the corrected $425 room drops it out of the "book now" band.
    assert hr.offset_pct(425, 2, 520) == 55


def test_bands():
    assert hr.band(86) == "good" and hr.band(55) == "warn" and hr.band(32) == "dim"
    assert hr.band(None) == "dim"


def test_offset_is_none_safe():
    assert hr.offset_pct(None, 2, 520) is None
    assert hr.offset_pct(0, 2, 520) is None
    assert hr.offset_pct(300, None, 520) is None


def test_build_keeps_previous_rate_when_scrape_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    out = hr.build({"main": None}, scraped={"ritz_ist": (None, "throttled")},
                   today="2026-08-09")
    ritz = [r for r in out["rows"] if r["key"] == "ritz_ist"][0]
    assert ritz["rate"] == hr.SEED["ritz_ist"]["rate"]      # last good kept
    assert ritz["checked"] == hr.SEED["ritz_ist"]["checked"]  # NOT stamped today
    assert any("throttled" in n for n in out["notes"])


def test_build_stamps_today_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    out = hr.build({"main": None}, scraped={"ritz_ist": (512, "ok")},
                   today="2026-08-09")
    ritz = [r for r in out["rows"] if r["key"] == "ritz_ist"][0]
    assert ritz["rate"] == 512 and ritz["checked"] == "2026-08-09"


def test_build_covers_every_shortlist_row(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    out = hr.build({"main": None}, today="2026-08-09")
    assert len(out["rows"]) == len(hr.SHORTLIST)
    assert all(r["offsets"] for r in out["rows"])
    assert [r["key"] for r in out["rows"] if r["city"] == "SIN"] and \
           all(len(r["offsets"]) == 2 for r in out["rows"] if r["city"] == "SIN")


def test_stay_windows_follow_the_winning_order():
    bkk_first = {"main": {"order": "BKK-first", "sg_nights": 4,
                          "openjaw": {"out_date": "January 4, 2027",
                                      "out_arrive": "January 7, 2027",
                                      "ret_date": "February 6, 2027"},
                          "legs": [{"route": "BKK→SIN", "depart": "February 2, 2027"}]}}
    w = hr.stay_windows(bkk_first)
    assert w["IST"][0] == datetime.date(2027, 1, 5)
    assert w["SIN"][0] == datetime.date(2027, 2, 2)
    assert w["SIN"][1] == datetime.date(2027, 2, 6)


def test_stay_windows_never_raise_on_garbage():
    for bad in ({}, {"main": {}}, {"main": None}, None, {"main": {"legs": "x"}}):
        assert isinstance(hr.stay_windows(bad), dict)


def test_scrape_rate_never_raises(monkeypatch):
    class Boom:
        @staticmethod
        def _run(c): raise OSError("browse died")
        _snap = _get_tree = staticmethod(lambda *a: "")
    rate, note = hr.scrape_rate(ENTRY, JAN5, JAN7, scraper=Boom)
    assert rate is None and "crashed" in note
