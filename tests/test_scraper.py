import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scraper import parse_price, _parse_results, LEGS

# Real accessibility-tree line captured from a one-way DAC→DPS search (2026-07-15)
SAMPLE_LINE = (
    "  [0-13835] link: From 1130 US dollars. 1 stop flight with AirAsia. "
    "Leaves Hazrat Shahjalal International Airport at 10:40 PM on Monday, February 1 "
    "and arrives at I Gusti Ngurah Rai International Airport at 12:15 PM on Tuesday, February 2. "
    "Total duration 11 hr 35 min. "
    "Layover (1 of 1) is a 4 hr 25 min layover at Kuala Lumpur International Airport. Select flight"
)


def test_parse_price_strips_dollar_sign():
    assert parse_price("$1,234") == 1234

def test_parse_price_handles_missing():
    assert parse_price("") == "N/A"

def test_parse_price_handles_already_int():
    assert parse_price("850") == 850


def test_parse_results_one_way_line():
    results = _parse_results(SAMPLE_LINE, "DAC", "DPS", "http://x", "February 1, 2027")
    assert len(results) == 1
    f = results[0]
    assert f["route"] == "DAC→DPS"
    assert f["price_total"] == 1130
    assert f["airline"] == "AirAsia"
    assert f["stops"] == "1 stop"
    assert f["duration"] == "11 hr 35 min"
    assert f["arrive"] == "February 2, 2027"
    assert "4 hr 25 min" in f["layovers"]
    assert "Kuala Lumpur" in f["layovers"]

def test_parse_results_ignores_non_flight_lines():
    tree = "[0-1] StaticText: Prices in US dollars\n[0-2] button: Search"
    assert _parse_results(tree, "BOS", "DAC", "http://x", "January 4, 2027") == []

def test_parse_results_nonstop_without_layover():
    line = ("[0-9] link: From 250 US dollars. Nonstop flight with Biman. "
            "Leaves A at 1:00 PM on Monday, February 1 and arrives at B at "
            "5:00 PM on Monday, February 1. Total duration 4 hr 0 min.")
    results = _parse_results(line, "DAC", "DPS", "http://x", "February 1, 2027")
    assert len(results) == 1
    assert results[0]["stops"].lower() == "nonstop"
    assert results[0]["layovers"] == "none"


def test_legs_config_is_the_ticket2_middles_both_orders():
    # 2026-08-01 evening, 30-search allowance: Jan 27–28 restored — they feed
    # the 2-4-night Singapore flex band and the 💸 early-Dhaka-exit deals.
    assert [(l["origin"], l["dest"]) for l in LEGS] == [
        ("DAC", "SIN"), ("SIN", "BKK"), ("DAC", "BKK"), ("BKK", "SIN")]
    assert sum(len(l["dates"]) for l in LEGS) == 18
    for leg in (LEGS[0], LEGS[2]):
        assert "January 27, 2027" in leg["dates"]
        assert "January 29, 2027" in leg["dates"]
    # SIN-first: SIN→BKK arriving Feb 1 gives the 5-night Bangkok block.
    assert "February 1, 2027" in LEGS[1]["dates"]
    # BKK-first: BKK→SIN Feb 4 keeps 2 Singapore nights before the Feb 6 return.
    assert "February 4, 2027" in LEGS[3]["dates"]


def test_run_timeout_returns_empty_and_counts(monkeypatch):
    import subprocess
    import scraper
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="browse snapshot", timeout=30)
    monkeypatch.setattr(scraper.subprocess, "run", boom)
    scraper.DIAG["timeouts"] = 0
    assert scraper._run("browse snapshot") == ""
    assert scraper.DIAG["timeouts"] == 1


def test_scrape_all_aborts_after_4_consecutive_empty_routes(monkeypatch):
    import scraper
    calls = []
    monkeypatch.setattr(scraper, "scrape_route", lambda *a: calls.append(a) or [])
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    result = scraper.scrape_all()
    assert result == []
    assert scraper.DIAG["aborted_early"] is True
    # 4 routes tried, each retried once = 8 scrape_route calls, not 18
    assert len(calls) == 8


def test_scrape_all_retries_route_once_then_moves_on(monkeypatch):
    import scraper
    calls = {"n": 0}
    def flaky(*a):
        calls["n"] += 1
        return [] if calls["n"] == 1 else [{"price_total": 100}]
    monkeypatch.setattr(scraper, "scrape_route", flaky)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    result = scraper.scrape_all()
    assert scraper.DIAG["aborted_early"] is False
    # 18 searches: first call empty + retry, rest succeed first try = 19 calls
    assert calls["n"] == 19
    assert len(result) == 18


def test_bkk_picker_survives_the_input_echo_and_bangkok_yai():
    # Typing "Bangkok" (TYPE_AS) puts that word in the input box's own tree
    # line, and Google also offers a "Bangkok Yai, Thailand" district — both
    # must lose to the real city option, which covers BKK *and* DMK.
    import json
    from scraper import _pick_airport, TYPE_AS
    assert TYPE_AS["BKK"] == "Bangkok"
    tree = "\n".join([
        "[0-1] combobox: Where to? Bangkok",
        "[0-2] option: Bangkok Yai, Thailand",
        "[0-3] option: Bangkok, Thailand Capital of Thailand",
        "[0-4] option: Suvarnabhumi Airport BKK 17 mi to destination",
    ])
    assert _pick_airport(json.dumps({"tree": tree}), "BKK") == "@0-3"


def test_browser_session_is_reused_until_marked_dirty(monkeypatch):
    # 2026-08-01 evening: one session per RUN (the per-search restart cost
    # ~35-40s each). A dirty mark — blank page, exception — must force a
    # fresh stop/env cycle on the next search.
    import scraper
    cmds = []
    monkeypatch.setattr(scraper, "_run", lambda c: cmds.append(c) or "")
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    scraper._session_dirty()
    scraper._ensure_session()
    scraper._ensure_session()
    scraper._ensure_session()
    assert cmds.count("browse env local") == 1, "session must be reused"
    scraper._session_dirty()
    scraper._ensure_session()
    assert cmds.count("browse env local") == 2, "dirty mark must force restart"
    scraper._session_dirty()
