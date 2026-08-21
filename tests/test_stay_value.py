"""Tests for the hotel-aware SIN night-count layer (stay math, 2026-08-19).
Spec: docs/superpowers/specs/2026-08-19-hotel-aware-sin-nights-design.md"""
import sys, os, re, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stay_value
import publish
import notify_telegram
from tests.test_main_trip import FLIGHTS, TICKET1, SG_TICKETS, TICKET2

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


TOTALS = {2: 4614, 3: 4660, 4: 4660}    # tonight's real 2026-08-19 flight totals


def test_build_rows_and_pick():
    sv = stay_value.build(RATES, TOTALS, None, 4, today=TODAY)
    assert sv["mode"] == "steering"
    assert [r["n"] for r in sv["rows"]] == [2, 3, 4]
    assert [r["allin"] for r in sv["rows"]] == [4614, 4812, 4997]
    assert [r["score"] for r in sv["rows"]] == [4614, 4587, 4547]
    assert sv["picked_n"] == 4
    assert sv["trip_n"] == 4 and sv["warning"] is None
    assert sv["trip_allin"] == 4997
    assert sv["hotel"]["key"] == "stregis_sin" and sv["knob"] == 225
    assert "St. Regis" in sv["assumption"] and "218" in sv["assumption"]


def test_build_warns_when_trip_ignored_the_math():
    sv = stay_value.build(RATES, TOTALS, None, 2, today=TODAY)
    assert sv["picked_n"] == 4 and sv["trip_n"] == 2
    assert "hook was not applied" in sv["warning"]


def test_build_advisory_never_warns_and_says_why():
    stale = {"rows": [dict(RATES["rows"][1], checked="2026-08-14")]}
    sv = stay_value.build(stale, TOTALS, None, 2, today=TODAY)
    assert sv["mode"] == "advisory"
    assert sv["warning"] is None
    assert "days old" in sv["note"]


def test_build_off_mode_degrades_cleanly():
    sv = stay_value.build(None, TOTALS, None, 2, today=TODAY)
    assert sv["mode"] == "off" and sv["rows"] == [] and sv["picked_n"] is None
    assert sv["trip_allin"] is None


def test_watchdog_barks_when_a_rival_beats_the_bold_pick():
    rival = dict(RATES, rows=RATES["rows"] + [
        {"key": "cheap", "city": "SIN", "name": "Cheap Palace",
         "program": "FHR", "bold": False, "rate": 100, "checked": "2026-08-19"}])
    sv = stay_value.build(rival, TOTALS, None, 4, today=TODAY)
    # bold net at 4N = 337 → $84/n; Cheap Palace: 4×100×1.12−640 → 0 → $0/n
    assert sv["watchdog"] is not None and "Cheap Palace" in sv["watchdog"]
    # Pan Pacific at $255 does NOT trigger (it nets MORE than the bold pick)
    sv2 = stay_value.build(RATES, TOTALS, None, 4, today=TODAY)
    assert sv2["watchdog"] is None


def test_load_rates_degrades_to_none():
    assert stay_value.load_rates("/nonexistent/path.json") is None
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write("{not json")
        bad = f.name
    try:
        assert stay_value.load_rates(bad) is None
    finally:
        os.unlink(bad)


def test_load_rates_reads_real_json():
    import tempfile, json as _json
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        _json.dump(RATES, f)
        good = f.name
    try:
        assert stay_value.load_rates(good)["rows"][1]["key"] == "stregis_sin"
    finally:
        os.unlink(good)


def test_bold_row_city_filter_both_directions():
    assert stay_value.bold_row(RATES, "IST")["key"] == "ritz_ist"


def test_build_ignores_non_int_flight_total_keys():
    sv = stay_value.build(RATES, {2: 4614, "junk": 1}, None, 2, today=TODAY)
    assert [r["n"] for r in sv["rows"]] == [2]


def test_watchdog_zero_nights_guard():
    assert stay_value._watchdog(RATES, stay_value.bold_row(RATES), 0) is None


def test_build_payload_steers_and_records_stay_value():
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS + [four_night],
                              stay_rates=RATES)
    sv = p["stay_value"]
    assert sv["mode"] == "steering"
    assert p["main"]["sg_nights"] == 4            # the hook steered the pick
    assert sv["picked_n"] == 4 and sv["trip_n"] == 4 and sv["warning"] is None
    assert p["main"]["total"] == 4660             # flights-only, always
    assert p["history"][-1]["sg_allin"] == 4660 + 337
    assert p["history"][-1]["stay_mode"] == "steering"
    assert not any("🛏️" in w for w in p["warnings"])


def test_build_payload_without_rates_is_tonights_old_behavior():
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS)
    assert p["stay_value"] is None
    assert p["main"]["sg_nights"] == 2
    assert p["history"][-1]["sg_allin"] is None
    assert p["history"][-1]["stay_mode"] is None


def test_build_payload_advisory_shows_table_but_does_not_steer():
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    stale = {"rows": [dict(RATES["rows"][1], checked="2026-08-10")]}
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS + [four_night],
                              stay_rates=stale)
    assert p["main"]["sg_nights"] == 2            # pick stayed flight-only
    assert p["stay_value"]["mode"] == "advisory"
    assert p["stay_value"]["warning"] is None     # mismatch is EXPECTED here


def test_incumbent_comes_from_the_last_history_entry():
    # Yesterday picked 4N; today 2N is only $10 better adjusted → dead-band
    # keeps 4N. (4N incumbent bonus −25 makes its score win.)
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027",
                      price_total=1000 + 113 + 10,   # 2N would win by $10 raw
                      airline="Biman", link="http://t2flex")
    hist = [{"date": "2026-08-18", "sg_nights": 4, "main_total": 4700}]
    p = publish.build_payload(FLIGHTS, [TICKET1], hist, "2026-08-19",
                              sg_tickets=SG_TICKETS + [four_night],
                              stay_rates=RATES)
    assert p["main"]["sg_nights"] == 4


def test_malformed_rates_never_crash_publish():
    for bad in ({"rows": None}, {"rows": "x"}, {"rows": [1, 2]}, [], "junk", 123):
        p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                                  sg_tickets=SG_TICKETS, stay_rates=bad)
        assert p["main"]["sg_nights"] == 2          # degraded, not crashed
        assert (p["stay_value"] or {}).get("mode") in (None, "off")


def test_mismatch_warning_folds_into_payload(monkeypatch):
    import stay_value as sv_mod
    real_build = sv_mod.build
    def fake_build(*a, **k):
        return dict(real_build(*a, **k), warning="synthetic mismatch for test")
    monkeypatch.setattr(sv_mod, "build", fake_build)
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS, stay_rates=RATES)
    assert any(w == "🛏️ synthetic mismatch for test" for w in p["warnings"])


def _steering_payload():
    four_night = dict(TICKET2, out_date="January 28, 2027",
                      out_arrive="January 28, 2027", price_total=1060,
                      airline="Biman", link="http://t2flex")
    return publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                                 sg_tickets=SG_TICKETS + [four_night],
                                 stay_rates=RATES)


def test_brief_carries_the_stay_math_line():
    # v4 redesign (2026-08-20): the core shows the CONCLUSION only ("St.
    # Regis 4N ✓ · $4,997 all-in"); the per-night-count arithmetic moved
    # into the 🛏️ Stay math expandable, "←" replaced by "✓picked".
    msg = notify_telegram.build_message(_steering_payload())
    assert "🛏️" in msg
    assert "St. Regis <b>4N ✓</b>" in msg and "all-in" in msg
    assert "2N $4,600" in msg
    assert "4N $4,997 ✓picked" in msg      # 4660 flights + 337 net, picked


def test_brief_flags_advisory_mode():
    stale = {"rows": [dict(RATES["rows"][1], checked="2026-08-10")]}
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS, stay_rates=stale)
    msg = notify_telegram.build_message(p)
    assert "advisory only" in msg      # note text unchanged, now inside the quote


def test_brief_without_stay_value_is_unchanged():
    p = publish.build_payload(FLIGHTS, [TICKET1], [], "2026-08-19",
                              sg_tickets=SG_TICKETS)
    assert "🛏️" not in notify_telegram.build_message(p)


def test_brief_core_lines_fit_a_phone():
    # Design principle (2026-08-20 v4): every core line fits a phone width
    # (~44 chars incl. emoji) without wrapping.
    msg = notify_telegram.build_message(_steering_payload())
    core = msg.split("<blockquote", 1)[0]
    lines = [re.sub(r"<[^>]+>", "", ln) for ln in core.split("\n")]
    assert all(len(ln) <= 48 for ln in lines if ln)


def test_fire_alerts_fold_into_context_not_core():
    # 🔥 alerts (new lows) fold into a compact tag on the price-context
    # line instead of leading the whole message in bold; their full text
    # moves into the stays expandable so nothing is silently dropped.
    p = dict(_steering_payload(),
            alerts=["🔥 Ticket ① new low: $3,622 (prev $3,647)"])
    msg = notify_telegram.build_message(p)
    core, _, rest = msg.partition("<blockquote")
    assert "① new low 🔥" in core
    assert "🔥 Ticket ① new low: $3,622 (prev $3,647)" in rest
    assert "<b>🔥" not in msg
