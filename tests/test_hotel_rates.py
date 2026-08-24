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
    rate, note = hr.parse_rate(page(), ENTRY, JAN5, JAN7)
    assert rate == 425 and note.startswith("ok")


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
    # Fallback path (no portal anchor) now assumes the observed ~19% tax/fees:
    # a $314 IST room with $520 credits sits exactly on the 70% line,
    assert hr.offset_pct(314, 2, 520) == 70
    # and the corrected $425 room drops it out of the "book now" band.
    assert hr.offset_pct(425, 2, 520) == 51


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
    assert rate == 425 and note.startswith("ok")


def test_wait_for_page_stops_as_soon_as_the_dates_bind(monkeypatch):
    """Every extra poll is a billed second on a remote session."""
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)
    calls = []

    class Fast:
        @staticmethod
        def _run(cmd):
            calls.append(cmd)
            p = page()
            p["offers"] = ["Expedia.com|425"]
            return json.dumps({"result": json.dumps(p)})

    got = hr._wait_for_page(Fast, JAN5, JAN7)
    assert got["price"] == "425"
    assert len(calls) == 1, f"kept polling after the page bound: {len(calls)}"


def test_wait_for_page_holds_briefly_for_the_seller_list(monkeypatch):
    """Dates bind before the provider list renders (proven live 2026-08-24);
    without the hold the catchit filter has nothing to read."""
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)
    calls = []

    class Lagging:
        @staticmethod
        def _run(cmd):
            calls.append(cmd)
            p = page()
            if len(calls) >= 3:
                p["offers"] = ["Hotels.com|520", "Catchit.com|196"]
            return json.dumps({"result": json.dumps(p)})

    got = hr._wait_for_page(Lagging, JAN5, JAN7)
    assert got["offers"] and len(calls) == 3
    rate, note = hr.parse_rate(got, ENTRY, JAN5, JAN7)
    assert rate == 520 and "ignored Catchit.com" in note


def test_wait_for_page_returns_bound_page_when_sellers_never_render(monkeypatch):
    monkeypatch.setattr(hr.time, "sleep", lambda *_: None)

    class NoSellers:
        @staticmethod
        def _run(cmd):
            return json.dumps({"result": json.dumps(page())})

    got = hr._wait_for_page(NoSellers, JAN5, JAN7)
    assert got["price"] == "425" and not got.get("offers")


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


def test_rate_moves_zero_old_rate_never_divides():
    prev = _rates_file([{"key": "x", "name": "X", "rate": 0}])
    new = _rates_file([{"key": "x", "name": "X", "rate": 5}])
    assert hotel_rates.rate_moves(prev, new) == []   # $5 < $40, pct guard skipped


# ── Portal anchors (2026-08-22) ─────────────────────────────────────────────
def test_paid_nights_free_night_rule():
    assert hr.paid_nights(4, 4) == 3 and hr.paid_nights(3, 4) == 3
    assert hr.paid_nights(2, 4) == 2
    assert hr.paid_nights(4, None) == 4 and hr.paid_nights(4, 3) == 3


def test_credits_for_splits_fixed_property_and_daily():
    assert hr.credits_for(2) == 520 and hr.credits_for(4) == 640     # unchanged totals
    assert hr.credits_for(2, "THC + Edit") == 470                     # $250 Edit
    assert hr.credits_for(4, "FHR", 125) == 665                       # $125 property credit


def test_anchor_allin_night_is_per_paid_night():
    k = hr.anchor_for("kempinski_sin")
    assert k["nights"] == 4 and k["free_night_min"] == 4 and k["credit"] == 125
    assert k["allin_night"] == round(1327.08 / 3, 2)                  # 442.36, 4th night free
    assert hr.anchor_for("ritz_ist")["allin_night"] == round(1250.42 / 2, 2)   # 625.21
    assert hr.anchor_for("jw_sin") is None                            # Edit-only: no portal row
    assert k["date"] == hr.PORTAL_DATE == "2026-08-22"


def test_est_allin_drifts_with_the_public_rate():
    a = dict(hr.anchor_for("ritz_ist"), google=447)
    assert hr.est_allin_night(a, 447) == 625.21
    assert hr.est_allin_night(a, 492) == round(625.21 * 492 / 447, 2)
    assert hr.est_allin_night(dict(a, google=None), 600) == 625.21    # no Google anchor yet: no drift
    assert hr.est_allin_night(a, None) == 625.21                       # no public rate yet
    assert hr.est_allin_night(None, 447) is None
    assert hr.drift_pct(492, 447) == 10 and hr.drift_pct(447, None) is None


def test_offsets_from_the_portal_total():
    # Capitol Kempinski 4n: $1,327.08 incl. tax with the free 4th night; credits 300+125+240
    assert hr.offset_from_allin(442.36, 4, 665, free_night_min=4) == 50
    assert hr.offset_from_allin(442.36, 2, 545, free_night_min=4) == 62
    assert hr.offset_from_allin(None, 2, 545) is None
    assert hr.offset_from_allin(442.36, 0, 545) is None


def test_build_rows_carry_anchor_est_and_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    out = hr.build({"main": None}, scraped={"kempinski_sin": (300, "ok")},
                   today="2026-08-23")
    k = next(r for r in out["rows"] if r["key"] == "kempinski_sin")
    assert k["bold"] is True                                           # the new SIN play
    assert k["anchor"]["google"] == 300 and k["anchor"]["google_date"] == "2026-08-23"
    assert k["est_allin_night"] == 442.36 and k["drift_pct"] == 0
    assert [o["pct"] for o in k["offsets"]] == [62, 50]
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    # 2026-08-24 basis change: the SEED reads were headline-basis, so under
    # the trusted-min basis they are NOT a valid baseline — no google anchor
    # until a live trusted scrape bootstraps one.
    assert ritz["anchor"]["google"] is None
    assert ritz["anchor"]["google_basis"] == hr.RATE_BASIS
    jw = next(r for r in out["rows"] if r["key"] == "jw_sin")
    assert jw["anchor"] is None and jw["drift_pct"] is None
    assert jw["est_allin_night"] == round(jw["rate"] * 1.20, 2)        # fallback path (SIN multiplier)
    new = next(r for r in out["rows"] if r["key"] == "shangrila_sin")
    assert new["rate"] is None and new["est_allin_night"] == round(1734.16 / 4, 2)
    assert new["offsets"][1]["pct"] == 37                              # offsets exist before the first scrape


def test_build_keeps_a_bootstrapped_google_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    first = hr.build({"main": None}, scraped={"kempinski_sin": (300, "ok")},
                     today="2026-08-23")
    hr.write(first)
    second = hr.build({"main": None}, scraped={"kempinski_sin": (330, "ok")},
                      today="2026-08-24")
    k = next(r for r in second["rows"] if r["key"] == "kempinski_sin")
    assert k["anchor"]["google"] == 300 and k["anchor"]["google_date"] == "2026-08-23"
    assert k["drift_pct"] == 10 and k["est_allin_night"] == round(442.36 * 330 / 300, 2)


# ── Code-review follow-ups (2026-08-22, post-Task-1) ────────────────────────
def test_stale_google_anchor_is_invalidated_when_portal_date_moves(tmp_path, monkeypatch):
    """A persisted google baseline from a DIFFERENT PORTAL_DATE (a future
    re-anchor) must never be reused — otherwise a new portal total would get
    silently scaled by an old baseline it was never measured against."""
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    stale = {"rows": [{"key": "kempinski_sin", "rate": 310, "checked": "2026-07-01",
                       "anchor": {"date": "2026-07-01", "google": 999,
                                  "google_date": "2026-07-01", "total": 1327.08,
                                  "nights": 4, "allin_night": 442.36, "credit": 125,
                                  "free_night_min": 4, "promo": None}}]}
    with open(tmp_path / "hotel_rates.json", "w") as f:
        json.dump(stale, f)
    out = hr.build({"main": None}, scraped={"kempinski_sin": (300, "ok")},
                   today="2026-08-23")
    k = next(r for r in out["rows"] if r["key"] == "kempinski_sin")
    assert k["anchor"]["google"] == 300 and k["anchor"]["google_date"] == "2026-08-23"


def test_non_dict_previous_anchor_is_ignored(tmp_path, monkeypatch):
    """A malformed previous row (`anchor` not a dict) must not raise, and
    must fall through to the seed/bootstrap baseline like a missing anchor."""
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    junk = {"rows": [{"key": "ritz_ist", "anchor": "junk", "rate": 447,
                      "checked": "2026-08-22"}]}
    with open(tmp_path / "hotel_rates.json", "w") as f:
        json.dump(junk, f)
    out = hr.build({"main": None}, today="2026-08-23")
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    assert ritz["anchor"]["google"] is None      # seed refused: wrong basis, no crash


def test_seed_baseline_valid_only_on_its_own_basis(tmp_path, monkeypatch):
    """The legacy (headline) basis still honours the same-day seed; the
    current basis refuses it and bootstraps from tonight's live scrape."""
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    monkeypatch.setattr(hr, "RATE_BASIS", hr.SEED_RATE_BASIS)
    out = hr.build({"main": None}, today="2026-08-23")
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    assert ritz["anchor"]["google"] == hr.SEED["ritz_ist"]["anchor_google"]
    assert ritz["anchor"]["google_date"] == "2026-08-22"


def test_persisted_baseline_refused_across_a_basis_change(tmp_path, monkeypatch):
    """A stored headline-basis google anchor must re-bootstrap from tonight's
    trusted rate, not silently scale the portal total against the old basis."""
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    prev = {"rows": [{"key": "ritz_ist", "rate": 447, "checked": "2026-08-23",
                      "rate_basis": "headline",
                      "anchor": {"date": hr.PORTAL_DATE, "google": 447,
                                 "google_date": "2026-08-22"}}]}
    with open(tmp_path / "hotel_rates.json", "w") as f:
        json.dump(prev, f)
    out = hr.build({"main": None}, scraped={"ritz_ist": (500, "ok · $500 Booking.com")},
                   today="2026-08-24")
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    assert ritz["anchor"]["google"] == 500 and ritz["anchor"]["google_date"] == "2026-08-24"
    assert ritz["drift_pct"] == 0                # night one on the new basis
    # and the migration night is silent: no mover, no bell for that row
    assert hr.rate_moves(prev, out) == []


def test_anchor_for_degrades_on_a_broken_portal_entry(monkeypatch):
    """One malformed PORTAL row (missing total/nights) must degrade to None
    for that key, not raise — the row then takes the fallback tax-rate path."""
    monkeypatch.setitem(hr.PORTAL, "ritz_ist", {"nights": 2, "credit": 100})
    assert hr.anchor_for("ritz_ist") is None
    monkeypatch.setitem(hr.PORTAL, "ritz_ist", {"total": 1250.42, "credit": 100})
    assert hr.anchor_for("ritz_ist") is None


def test_build_survives_a_broken_portal_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    monkeypatch.setitem(hr.PORTAL, "ritz_ist", {"nights": 2, "credit": 100})
    out = hr.build({"main": None}, today="2026-08-23")
    assert len(out["rows"]) == len(hr.SHORTLIST)
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    assert ritz["anchor"] is None


def test_only_one_bold_per_city():
    for city in ("IST", "SIN"):
        assert sum(1 for e in hr.SHORTLIST if e["city"] == city and e.get("bold")) == 1


def test_shortlist_keys_unique_and_anchored_rows_have_portal_rows():
    keys = [e["key"] for e in hr.SHORTLIST]
    assert len(keys) == len(set(keys)) == 19
    assert set(hr.PORTAL) <= set(keys)


def test_seeded_google_anchor_dies_with_a_portal_date_bump(tmp_path, monkeypatch):
    """SEED's anchor_google is a same-day read for PORTAL_DATE only. Bump the
    portal date without refreshing SEED and the original rows must bootstrap
    from a live scrape rather than reuse the old baseline."""
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    monkeypatch.setattr(hr, "PORTAL_DATE", "2026-10-01")
    out = hr.build({"main": None}, scraped={"ritz_ist": (500, "ok")}, today="2026-10-02")
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    assert ritz["anchor"]["google"] == 500 and ritz["anchor"]["google_date"] == "2026-10-02"
    untouched = next(r for r in out["rows"] if r["key"] == "stregis_ist")
    assert untouched["anchor"]["google"] is None        # no live read yet: no baseline


# ── Value rank + apples-to-apples columns (2026-08-22, evening) ──────────────
def test_city_tax_multipliers_come_from_the_portal_totals():
    """total ÷ (avg × nights) on the portal: IST 1.12 (VAT + accommodation
    tax), SIN 1.20 (GST + service). The Ritz IST is the lone 1.19 outlier."""
    assert hr.TAX_MULT == {"IST": 1.12, "SIN": 1.20}


def test_every_row_has_a_unique_value_rank_per_city():
    for city in ("IST", "SIN"):
        ranks = [e["rank"] for e in hr.SHORTLIST if e["city"] == city]
        assert sorted(ranks) == list(range(1, len(ranks) + 1)), (city, ranks)
        top = next(e for e in hr.SHORTLIST if e["city"] == city and e["rank"] == 1)
        assert top.get("bold"), f"{city}: rank 1 must be the bold play"


def test_build_writes_public_allin_and_stay_average(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    out = hr.build({"main": None}, scraped={"kempinski_sin": (287, "ok")},
                   today="2026-08-23")
    k = next(r for r in out["rows"] if r["key"] == "kempinski_sin")
    assert k["public_allin_night"] == round(287 * 1.20, 2)          # 344.4
    # per-night AVERAGE over the tracked 4n stay: 3 paid × 442.36 ÷ 4
    assert k["avg_allin_night"] == round(442.36 * 3 / 4, 2)          # 331.77
    assert k["rank"] == 1
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    assert ritz["public_allin_night"] == round(447 * 1.12, 2)
    assert ritz["avg_allin_night"] == ritz["est_allin_night"]        # no free night
    new = next(r for r in out["rows"] if r["key"] == "fs_sin")
    assert new["public_allin_night"] is None                          # no public rate yet
    jw = next(r for r in out["rows"] if r["key"] == "jw_sin")
    assert jw["est_allin_night"] == round(jw["rate"] * 1.20, 2)      # fallback uses the CITY multiplier


def test_build_writes_stay_total_credits_and_net(tmp_path, monkeypatch):
    """The Stay column: what the tracked stay costs all-in, what the card play
    hands back (Amex/Edit fixed + property credit + breakfast/day), and the
    net — all from the same per-paid-night estimate the offsets use."""
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    out = hr.build({"main": None}, today="2026-08-23")
    k = next(r for r in out["rows"] if r["key"] == "kempinski_sin")
    assert k["stay"] == {"nights": 4, "total": 1327.08, "credits": 665, "net": 662}
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    assert ritz["stay"] == {"nights": 2, "total": 1250.42, "credits": 470, "net": 780}   # Edit program: $250
    pp = next(r for r in out["rows"] if r["key"] == "panpacific")
    assert pp["stay"]["credits"] == 250 + 100 + 240                 # Edit-program credits
    new = next(r for r in out["rows"] if r["key"] == "fs_sin")
    assert new["stay"]["total"] == 1853.56                           # anchor alone, no public rate yet


def test_rows_carry_the_portal_tripadvisor_score():
    """Quality half of the value rank — the TA score read off the portal."""
    assert hr.anchor_for("raffles_ist")["ta"] == 4.9
    assert hr.anchor_for("kempinski_sin")["ta"] == 4.7
    for key, p in hr.PORTAL.items():
        assert isinstance(p.get("ta"), float) and 3.0 <= p["ta"] <= 5.0, key


def test_bookings_ride_in_the_json_and_point_at_shortlist_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    out = hr.build({"main": None}, today="2026-08-23")
    assert out["bookings"] is hr.BOOKED or out["bookings"] == hr.BOOKED
    keys = {e["key"] for e in hr.SHORTLIST}
    for city, b in hr.BOOKED.items():
        assert b["nights"] > 0 and (b["total"] > 0 or b.get("points", 0) > 0), city
        if city in ("IST", "SIN"):                 # card-play cities point at a tracked row
            assert b["key"] in keys, city
        else:                                      # Bangkok rides on the award block in data.json
            assert b.get("confirmation") and b.get("points"), city


# ── Movers alert v2 (2026-08-23, Jalal: "clean this up") ────────────────────
def _row(key, city, name, rate, est, net, nights, rank, bold=False):
    return {"key": key, "city": city, "name": name, "rate": rate, "rank": rank,
            "bold": bold, "est_allin_night": est,
            "stay": {"nights": nights, "total": est * nights, "credits": 0, "net": net}}

PREV = {"rows": [
    _row("shangrila_ist", "IST", "Shangri-La Bosphorus", 398, 595.13, 670, 2, 1, bold=True),
    _row("parkhyatt_ist", "IST", "Park Hyatt Maçka Palas", 403, 566.99, 614, 2, 4),
    _row("kempinski_sin", "SIN", "The Capitol Kempinski", 287, 442.36, 662, 4, 1, bold=True),
    _row("fs_sin", "SIN", "Four Seasons Singapore", 309, 463.39, 1214, 4, 3),
]}
NEW = {"rows": [
    _row("shangrila_ist", "IST", "Shangri-La Bosphorus", 398, 595.13, 670, 2, 1, bold=True),
    _row("parkhyatt_ist", "IST", "Park Hyatt Maçka Palas", 346, 486.79, 454, 2, 4),
    _row("kempinski_sin", "SIN", "The Capitol Kempinski", 287, 442.36, 662, 4, 1, bold=True),
    _row("fs_sin", "SIN", "Four Seasons Singapore", 355, 532.38, 1490, 4, 3),
]}


def test_moves_message_v2_groups_by_city_and_talks_in_net():
    moves = hr.rate_moves(PREV, NEW)
    msg = hr.moves_message(moves, PREV, NEW)
    assert msg.startswith("🏨 <b>Hotel moves overnight</b>")
    assert "🕌 Istanbul" in msg and "🇸🇬 Singapore" in msg
    assert msg.index("🕌 Istanbul") < msg.index("🇸🇬 Singapore")
    # one line per hotel: arrow, name, what you'd PAY (net for the stay), then the public move
    assert "▼14% Park Hyatt Maçka Palas · net 2n $614 → $454" in msg
    assert "▲15% Four Seasons Singapore · net 4n $1,214 → $1,490" in msg
    assert "public $403→$346" in msg and "public $309→$355" in msg
    # the verdict: Park Hyatt now nets $216 under the Istanbul play → a swap candidate
    assert "🔔 Park Hyatt Maçka Palas nets $216 less than the play (Shangri-La Bosphorus)" in msg
    assert "Singapore: play unchanged (The Capitol Kempinski)" in msg


def test_moves_message_v2_falls_back_to_the_flat_line_without_rows():
    msg = hr.moves_message([("St. Regis Singapore", 248, 218)])
    assert msg == "🏨 Hotel rate moves: St. Regis Singapore $248→$218 (▼12%)"


def test_moves_bell_only_rings_when_a_rival_crosses_the_bar():
    """Sanasaryan sits under the Istanbul play every night by design."""
    prev = {"rows": PREV["rows"] + [_row("sanasaryan", "IST", "Sanasaryan Han", 353, 478, 436, 2, 3)]}
    new = {"rows": NEW["rows"] + [_row("sanasaryan", "IST", "Sanasaryan Han", 340, 460, 400, 2, 3)]}
    moves = hr.rate_moves(prev, new)
    msg = hr.moves_message(moves, prev, new)
    assert "🔔 Park Hyatt" in msg and "🔔 Sanasaryan" not in msg


# ── 🔔 Deal bells (2026-08-23, "notify me when and if there's a better hotel deal") ──
def _drow(key, city, name, rate, net, nights, total, drift, bold=False):
    return {"key": key, "city": city, "name": name, "rate": rate, "rank": 1 if bold else 2,
            "bold": bold, "est_allin_night": total / nights, "drift_pct": drift,
            "stay": {"nights": nights, "total": total, "credits": 0, "net": net}}


def test_booked_play_getting_cheaper_rings_once(monkeypatch):
    """SIN is booked at $1,497.11 (BOOKED). A −8% public drift = −$120 on the
    booked total → crosses REBOOK_BAR; the next night at −9% it stays quiet."""
    monkeypatch.setattr(hr, "BOOKED", {"SIN": {"key": "kempinski_sin", "total": 1497.11,
                                               "via": "Amex FHR · Pay at Check-in",
                                               "confirmation": "ZO-AX1078-06155"}})
    prev = {"rows": [_drow("kempinski_sin", "SIN", "The Capitol Kempinski", 287, 662, 4, 1327, 0.0, bold=True)]}
    new = {"rows": [_drow("kempinski_sin", "SIN", "The Capitol Kempinski", 264, 600, 4, 1221, -8.0, bold=True)]}
    bells = hr.deal_alerts(prev, new)
    assert len(bells) == 1
    assert "The Capitol Kempinski got cheaper: your booked $1,497 now prices ≈ $1,377 (−$120)" in bells[0]
    assert "THEN cancel ZO-AX1078-06155" in bells[0]
    assert hr.deal_message(prev, new).startswith("🏨 <b>Hotel deal</b>")
    # already under the bar last night → no repeat bell
    later = {"rows": [_drow("kempinski_sin", "SIN", "The Capitol Kempinski", 261, 590, 4, 1207, -9.0, bold=True)]}
    assert hr.deal_alerts(new, later) == []
    assert hr.deal_message(new, later) is None
    # a −5% night (−$75) never crosses
    small = {"rows": [_drow("kempinski_sin", "SIN", "The Capitol Kempinski", 273, 630, 4, 1261, -5.0, bold=True)]}
    assert hr.deal_alerts(prev, small) == []


def test_unbooked_play_under_its_anchor_rings_with_the_lock_hint(monkeypatch):
    monkeypatch.setattr(hr, "BOOKED", {})
    prev = {"rows": [_drow("ritz_ist", "IST", "The Ritz-Carlton Istanbul", 500, 815, 2, 1285, 0.0, bold=True)]}
    new = {"rows": [_drow("ritz_ist", "IST", "The Ritz-Carlton Istanbul", 450, 700, 2, 1156.5, -10.0, bold=True)]}
    bells = hr.deal_alerts(prev, new)
    assert len(bells) == 1 and "$128 under its portal anchor" in bells[0]
    assert "chase.com/travel" in bells[0]
    assert hr.deal_alerts(new, new) == []          # no crossing when nothing changed


def test_rival_bell_rings_on_a_quiet_night_without_a_mover(monkeypatch):
    """A rival can creep under the bar through moves too small to be a
    'mover' (< 10% / $40) — deal_message still rings."""
    monkeypatch.setattr(hr, "BOOKED", {"SIN": {"key": "kempinski_sin", "total": 1497.11,
                                               "via": "Amex FHR", "confirmation": "ZO-AX1078-06155"}})
    play = _drow("kempinski_sin", "SIN", "The Capitol Kempinski", 287, 662, 4, 1327, 0.0, bold=True)
    prev = {"rows": [play, _drow("shangrila_sin", "SIN", "Shangri-La Singapore", 300, 520, 4, 1300, 0.0)]}
    new = {"rows": [play, _drow("shangrila_sin", "SIN", "Shangri-La Singapore", 290, 505, 4, 1260, -3.0)]}
    assert hr.rate_moves(prev, new) == []           # $10 / 3% — not a mover
    msg = hr.deal_message(prev, new)
    assert "🔔 Shangri-La Singapore nets $157 less than the play (The Capitol Kempinski)" in msg
    assert "book it refundable FIRST, then cancel ZO-AX1078-06155" in msg


def test_deal_bells_are_none_safe_on_rows_without_drift():
    assert hr.deal_alerts(PREV, NEW) == [ln for ln in hr.rival_bells(PREV, NEW).values()]
    assert hr.play_drop_bells(None, NEW) == []
    assert hr.deal_message(None, {"rows": []}) is None


def test_payload_carries_points_routes_for_the_edit_city():
    pr = hr.POINTS_ROUTES["IST"]
    assert pr["edit_total"] > 0 and pr["boost_cents"] > 1 and pr["hyatt"]["pts"] == 50000
    # the Hyatt comparison row must be a tracked property
    assert pr["hyatt"]["key"] in {e["key"] for e in hr.SHORTLIST}
    # The Edit city is the one NOT taking the Amex $300
    assert hr.CREDIT_PLAN["amex_300_to"] != "IST" and "IST" in hr.POINTS_ROUTES


# ── ⚠️ Suspect rates (2026-08-24: catchit.com bait poisoned the St. Regis) ──
def test_suspect_collapse_never_rings_but_warns(monkeypatch):
    monkeypatch.setattr(hr, "BOOKED", {"SIN": {"key": "kempinski_sin", "total": 1497.11,
                                               "via": "Amex FHR", "confirmation": "ZO-AX1078-06155"}})
    play = _drow("kempinski_sin", "SIN", "The Capitol Kempinski", 287, 662, 4, 1327, 0.0, bold=True)
    prev = {"rows": [play, _drow("stregis_sin", "SIN", "St. Regis Singapore", 520, 2024, 4, 2664, 0.0)]}
    new = {"rows": [play, _drow("stregis_sin", "SIN", "St. Regis Singapore", 196, 364, 4, 1004, -62.0)]}
    bells = hr.rival_bells(prev, new)
    assert "🔔" not in (bells.get("SIN") or "")
    assert "⚠️" in bells["SIN"] and "junk OTA" in bells["SIN"] and "$520" in bells["SIN"]
    # the movers line carries the same flag
    msg = hr.moves_message(hr.rate_moves(prev, new), prev, new)
    assert "⚠️ suspect (junk OTA rate?)" in msg
    # a genuine −30% drop still rings normally
    real = {"rows": [play, _drow("stregis_sin", "SIN", "St. Regis Singapore", 364, 500, 4, 1400, -30.0)]}
    assert "🔔" in hr.rival_bells(prev, real)["SIN"]


def test_suspect_play_never_triggers_the_rebook_bell(monkeypatch):
    monkeypatch.setattr(hr, "BOOKED", {"SIN": {"key": "kempinski_sin", "total": 1497.11,
                                               "via": "Amex FHR", "confirmation": "ZO-AX1078-06155"}})
    prev = {"rows": [_drow("kempinski_sin", "SIN", "The Capitol Kempinski", 287, 662, 4, 1327, 0.0, bold=True)]}
    new = {"rows": [_drow("kempinski_sin", "SIN", "The Capitol Kempinski", 120, 200, 4, 550, -58.0, bold=True)]}
    assert hr.play_drop_bells(prev, new) == []


def test_build_rows_carry_the_suspect_flag(monkeypatch):
    prev_rows = {e["key"]: {"rate": 520, "checked": "2026-08-23"} for e in hr.SHORTLIST}
    monkeypatch.setattr(hr, "load_previous", lambda: prev_rows)
    scraped = {e["key"]: (196 if e["key"] == "stregis_sin" else 500, "ok") for e in hr.SHORTLIST}
    data = hr.build({"stays": {}}, scraped=scraped, today="2026-08-24")
    flags = {r["key"]: r.get("suspect") for r in data["rows"]}
    assert flags["stregis_sin"] is True
    assert not flags["kempinski_sin"]


# ── Trusted-seller pricing (2026-08-24: filter catchit-class OTAs out) ──────
def test_offer_rate_prices_from_trusted_sellers_only():
    payload = {"offers": ["Hotels.com|520", "Official Site|520", "Expedia.com|520",
                          "Travelocity.com|520", "Catchit.com|196"]}
    rate, src, ignored = hr.offer_rate(payload)
    assert rate == 520 and src in ("Expedia.com", "Hotels.com", "Official Site", "Travelocity.com")
    assert ignored == [(196, "Catchit.com")]
    # parse_rate uses it and names the junk seller in the note
    p = page(price="196"); p["offers"] = payload["offers"]
    rate, note = hr.parse_rate(p, ENTRY, JAN5, JAN7)
    assert rate == 520 and "ignored Catchit.com $196" in note


def test_offer_rate_untrusted_only_falls_back_to_headline():
    p = page(price="425"); p["offers"] = ["Catchit.com|196", "ZenHotels.com|210"]
    rate, note = hr.parse_rate(p, ENTRY, JAN5, JAN7)
    assert rate == 425 and "no trusted seller" in note
    assert hr.offer_rate({"offers": []}) == (None, None, [])
    assert hr.offer_rate({"offers": ["garbage", "X|notanumber", "Y|999999"]}) == (None, None, [])


def test_build_records_the_rate_source(monkeypatch):
    prev_rows = {e["key"]: {"rate": 500, "checked": "2026-08-23", "rate_src": "$500 Expedia.com"}
                 for e in hr.SHORTLIST}
    monkeypatch.setattr(hr, "load_previous", lambda: prev_rows)
    scraped = {e["key"]: ((520, "ok · $520 Hotels.com (ignored Catchit.com $196)")
                          if e["key"] == "stregis_sin" else (None, "throttled"))
               for e in hr.SHORTLIST}
    data = hr.build({"stays": {}}, scraped=scraped, today="2026-08-24")
    by = {r["key"]: r for r in data["rows"]}
    assert by["stregis_sin"]["rate_src"] == "$520 Hotels.com (ignored Catchit.com $196)"
    assert by["kempinski_sin"]["rate_src"] == "$500 Expedia.com"   # stale keeps prev
    assert any("throttled" in n for n in data["notes"])
