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
