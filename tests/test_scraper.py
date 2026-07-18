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


def test_legs_config_has_direct_and_singapore_legs():
    # Core direct trip (first 3) + Singapore-detour legs (DAC→SIN, SIN→DPS).
    assert [(l["origin"], l["dest"]) for l in LEGS] == [
        ("BOS", "DAC"), ("DAC", "DPS"), ("DPS", "BOS"),
        ("DAC", "SIN"), ("SIN", "DPS")]
    # 3 + 4 + 3 core, + 4 + 4 Singapore = 18. DAC→DPS keeps Jan 31 (overnights
    # arrive Feb 1, the only cheap 5-night pairing for a Feb 6 return).
    assert sum(len(l["dates"]) for l in LEGS) == 18
    assert "January 31, 2027" in LEGS[1]["dates"]
    # DAC→SIN is the DAC→DPS window shifted 2 days earlier (2 fewer Dhaka nights)
    assert "January 29, 2027" in LEGS[3]["dates"]


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
