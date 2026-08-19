"""The hotel-rate refresh must be FAIL-CLOSED: a page that doesn't prove both
the property and the dates may never yield a number, because a plausible-but-
wrong nightly rate silently corrupts every offset band on the Stays screen.

The date proof reads Google's OWN check-in/check-out fields. Verified live
2026-08-03: with only &checkin=/&checkout= in the URL a clean browser session
silently prices TONIGHT while still rendering a believable number."""
import base64
import datetime
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hotel_rates as hr
import hotel_rates

JAN5 = datetime.date(2027, 1, 5)
JAN7 = datetime.date(2027, 1, 7)
ENTRY = {"key": "ritz_ist", "city": "IST", "name": "Ritz-Carlton Istanbul",
         "query": "Ritz Carlton Istanbul", "match": "Ritz-Carlton",
         "program": "FHR", "angle": "x"}

def page(**kw):
    base = {"title": "The Ritz-Carlton, Istanbul - Google hotels",
            "checkin": "Tue, Jan 5", "checkout": "Thu, Jan 7",
            "price": "425", "len": 11695}
    base.update(kw)
    return base


def test_good_page_yields_rate():
    assert hr.parse_rate(page(), ENTRY, JAN5, JAN7) == (425, "ok")


def test_silently_defaulted_dates_are_rejected():
    """The exact live failure: URL asked for Jan 2027, page priced tonight."""
    rate, note = hr.parse_rate(
        page(checkin="Sun, Aug 9", checkout="Mon, Aug 10", price="253"),
        ENTRY, JAN5, JAN7)
    assert rate is None and "did not bind" in note


def test_wrong_hotel_is_rejected():
    rate, note = hr.parse_rate(page(title="Hilton Istanbul"), ENTRY, JAN5, JAN7)
    assert rate is None and "expected Ritz-Carlton" in note


def test_empty_render_is_rejected():
    rate, note = hr.parse_rate(page(len=0), ENTRY, JAN5, JAN7)
    assert rate is None and "empty" in note


def test_missing_payload_is_rejected():
    rate, note = hr.parse_rate(None, ENTRY, JAN5, JAN7)
    assert rate is None and "no page payload" in note


def test_dates_bound_but_no_price_is_rejected():
    rate, note = hr.parse_rate(page(price=None), ENTRY, JAN5, JAN7)
    assert rate is None and "no price" in note


def test_implausible_rate_is_rejected():
    """A parse that grabs a review count or a phone fragment must not ship."""
    assert hr.parse_rate(page(price="4"), ENTRY, JAN5, JAN7)[0] is None
    assert hr.parse_rate(page(price="99999"), ENTRY, JAN5, JAN7)[0] is None


def test_ts_param_round_trips_to_a_known_good_google_url():
    """Byte-for-byte against a ts captured from a session where Jan 5-7 bound.
    If this breaks, dates stop binding and every rate silently becomes tonight."""
    assert hr.ts_param(JAN5, JAN7, guests=2) == \
        "CAAaGhIYEhIKBwjrDxABGAUSBwjrDxABGAcyAggCKgcKBToDVVNE"


def test_ts_param_encodes_the_dates_it_was_given():
    blob = base64.urlsafe_b64decode(
        hr.ts_param(datetime.date(2027, 2, 2), datetime.date(2027, 2, 6)) + "==")
    # 2027 = 0x7EB -> varint EB 0F; months/days follow as single bytes.
    assert bytes([0xEB, 0x0F, 0x10, 0x02, 0x18, 0x02]) in blob   # Feb 2
    assert bytes([0xEB, 0x0F, 0x10, 0x02, 0x18, 0x06]) in blob   # Feb 6


def test_google_url_carries_ts_and_not_raw_date_params():
    u = hr.google_url("Ritz Carlton Istanbul", JAN5, JAN7)
    assert "ts=" in u and "checkin=" not in u and "checkout=" not in u


def test_extract_js_survives_being_flattened_to_one_line():
    """The JS is newline-stripped and shell-quoted before it reaches `browse
    eval`. A // comment would then silently comment out the REST of the
    function (observed live: every property returned "no page payload"), and an
    apostrophe would fight the shell quoting."""
    assert "//" not in hr.EXTRACT_JS, "// comment would swallow the flattened JS"
    assert "'" not in hr.EXTRACT_JS, "apostrophe breaks shell quoting"
    flat = hr.EXTRACT_JS.replace("\n", " ")
    assert flat.rstrip().endswith("})()")
    assert flat.count("{") == flat.count("}")


def test_price_may_carry_a_badge_before_the_date_chip():
    """Cirağan renders '$475 / GREAT DEAL / Jan 5 - 7' — the badge sits
    between the price and the dates, which broke the first anchor."""
    import re as _re
    js_re = (hr.EXTRACT_JS % hr._range_pattern(JAN5, JAN7)).replace("\\\\", "\\")
    m = _re.search(r'RegExp\("(.+?)"\)', js_re)
    pattern = m.group(1).replace("\\\\", "\\")
    text = "Ciragan Palace Kempinski\n$475\nGREAT DEAL\n•\nJan 5 – 7, 2027"
    assert _re.search(pattern, text).group(1) == "475"


def test_price_anchor_will_not_jump_over_another_price():
    import re as _re
    js_re = (hr.EXTRACT_JS % hr._range_pattern(JAN5, JAN7)).replace("\\\\", "\\")
    pattern = _re.search(r'RegExp\("(.+?)"\)', js_re).group(1).replace("\\\\", "\\")
    text = "$141 InterContinental\n$425\nJan 5 – 7, 2027"
    assert _re.search(pattern, text).group(1) == "425"   # nearest, not the first


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


# ── Infrastructure failures must never be reported as Google failures ───────
# 2026-08-11 → 08-16: Browserbase's free tier ran out, every `browse` command
# returned "402 Free plan browser minutes limit reached", and all eight
# properties came back as "no page payload (throttled, blocked or still
# loading)". Five nights were spent believing Google had blocked us.

QUOTA_STDERR = ("Error: 402 Free plan browser minutes limit reached. "
                "Please upgrade your account at https://browserbase.com/plans")


def test_classify_stderr_names_the_quota():
    note = hr.classify_stderr(QUOTA_STDERR)
    assert note and "quota" in note.lower() and hr.is_infra_note(note)


def test_classify_stderr_ignores_ordinary_noise():
    """A page that merely disappointed us must keep its fail-closed note."""
    assert hr.classify_stderr("") is None
    assert hr.classify_stderr(None) is None
    assert hr.classify_stderr("DevTools listening on ws://127.0.0.1:9222") is None


def test_quota_failure_is_reported_as_itself_not_as_google(monkeypatch):
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)

    class Dead:
        DIAG = {"last_stderr": ""}
        @staticmethod
        def _run(cmd):
            Dead.DIAG["last_stderr"] = QUOTA_STDERR
            return ""

    rate, note = hr.scrape_rate(ENTRY, JAN5, JAN7, scraper=Dead)
    assert rate is None
    assert hr.is_infra_note(note), f"not flagged as infra: {note!r}"
    assert "quota" in note.lower()
    assert "throttl" not in note.lower(), "must not blame Google for our quota"


def test_quota_failure_does_not_burn_the_retry(monkeypatch):
    """Retrying a 402 cannot help and costs a second page load every time."""
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)
    opens = []

    class Dead:
        DIAG = {"last_stderr": ""}
        @staticmethod
        def _run(cmd):
            if cmd.startswith("browse open"):
                opens.append(cmd)
            Dead.DIAG["last_stderr"] = QUOTA_STDERR
            return ""

    hr.scrape_rate(ENTRY, JAN5, JAN7, scraper=Dead, attempts=2)
    assert len(opens) == 1, f"retried an unretryable failure: {len(opens)} opens"


def test_stale_stderr_from_a_previous_property_is_not_reused(monkeypatch):
    """DIAG holds the LAST stderr process-wide. Without clearing it per
    property, one 402 would mislabel every later property in the run."""
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)

    class Recovered:
        DIAG = {"last_stderr": QUOTA_STDERR}       # left over from earlier
        @staticmethod
        def _run(cmd):
            if "eval" in cmd:
                return json.dumps({"result": json.dumps(page())})
            return ""

    rate, note = hr.scrape_rate(ENTRY, JAN5, JAN7, scraper=Recovered)
    assert rate == 425 and note == "ok"


def test_wait_for_page_stops_as_soon_as_the_dates_bind(monkeypatch):
    """Every extra poll is a billed second on a remote session."""
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)
    calls = []

    class Fast:
        @staticmethod
        def _run(cmd):
            calls.append(cmd)
            return json.dumps({"result": json.dumps(page())})

    got = hr._wait_for_page(Fast, JAN5, JAN7)
    assert got["price"] == "425"
    assert len(calls) == 1, f"kept polling after the page bound: {len(calls)}"


def test_wait_for_page_gives_up_and_returns_the_last_bad_payload(monkeypatch):
    """A page that never binds still has to reach parse_rate, so the run can
    say WHICH way it failed instead of just 'no payload'."""
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)
    wrong = page(checkin="Sun, Aug 9", checkout="Mon, Aug 10")

    class Wrong:
        @staticmethod
        def _run(cmd):
            return json.dumps({"result": json.dumps(wrong)})

    got = hr._wait_for_page(Wrong, JAN5, JAN7)
    assert got["checkin"] == "Sun, Aug 9"
    rate, note = hr.parse_rate(got, ENTRY, JAN5, JAN7)
    assert rate is None and "did not bind" in note


# ── 🏨 rate-moves morning alert (2026-08-19) ────────────────────────────────
def _rates_file(rows):
    return {"updated": "2026-08-19", "rows": rows}


def test_rate_moves_fires_on_abs_and_pct_thresholds():
    prev = _rates_file([
        {"key": "stregis_sin", "name": "St. Regis Singapore", "rate": 248},
        {"key": "ritz_ist", "name": "Ritz-Carlton Istanbul", "rate": 439},
        {"key": "panpacific", "name": "Pan Pacific Orchard", "rate": 255},
    ])
    new = _rates_file([
        {"key": "stregis_sin", "name": "St. Regis Singapore", "rate": 218},  # −$30, −12.1% → pct fires
        {"key": "ritz_ist", "name": "Ritz-Carlton Istanbul", "rate": 484},   # +$45, +10.3% → both fire
        {"key": "panpacific", "name": "Pan Pacific Orchard", "rate": 262},   # +$7, +2.7% → quiet
    ])
    moves = hotel_rates.rate_moves(prev, new)
    assert [(m[0], m[1], m[2]) for m in moves] == [
        ("St. Regis Singapore", 248, 218),
        ("Ritz-Carlton Istanbul", 439, 484),
    ]


def test_rate_moves_ignores_stale_missing_and_new_rows():
    prev = _rates_file([
        {"key": "a", "name": "A", "rate": 300},
        {"key": "b", "name": "B", "rate": None},
    ])
    new = _rates_file([
        {"key": "a", "name": "A", "rate": 300},          # unchanged (kept-stale shape)
        {"key": "b", "name": "B", "rate": 200},          # no prior number → no move
        {"key": "c", "name": "C", "rate": 100},          # new row → no move
    ])
    assert hotel_rates.rate_moves(prev, new) == []
    assert hotel_rates.rate_moves(None, new) == []
    assert hotel_rates.rate_moves(prev, None) == []


def test_moves_message_format_and_silence():
    assert hotel_rates.moves_message([]) is None
    msg = hotel_rates.moves_message([("St. Regis Singapore", 248, 218),
                                     ("Ritz-Carlton Istanbul", 439, 484)])
    assert msg == ("🏨 Hotel rate moves: St. Regis Singapore $248→$218 (▼12%) · "
                   "Ritz-Carlton Istanbul $439→$484 (▲10%)")
