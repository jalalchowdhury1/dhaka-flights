import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scraper import build_google_flights_url, parse_price

def test_build_url_bos_dac():
    url = build_google_flights_url("BOS", "DAC", "2027-01-03", "2027-01-28", adults=3)
    assert "BOS" in url
    assert "DAC" in url
    assert "2027-01-03" in url
    assert "2027-01-28" in url

def test_build_url_bos_bkk():
    url = build_google_flights_url("BOS", "BKK", "2027-01-03", "2027-01-28", adults=3)
    assert "BKK" in url

def test_parse_price_strips_dollar_sign():
    assert parse_price("$1,234") == 1234

def test_parse_price_handles_missing():
    assert parse_price("") == "N/A"

def test_parse_price_handles_already_int():
    assert parse_price("850") == 850

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
    # 4 routes tried, each retried once = 8 scrape_route calls, not 64
    assert len(calls) == 8

def test_scrape_all_retries_route_once_then_moves_on(monkeypatch):
    import scraper
    calls = {"n": 0}
    def flaky(*a):
        calls["n"] += 1
        return [] if calls["n"] == 1 else [{"price_per_person": 100}]
    monkeypatch.setattr(scraper, "scrape_route", flaky)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    result = scraper.scrape_all()
    assert scraper.DIAG["aborted_early"] is False
    # 32 routes: first call empty + retry, rest succeed first try = 33 calls
    assert calls["n"] == 33
    assert len(result) == 32
