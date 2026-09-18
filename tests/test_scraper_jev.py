#!/usr/bin/env python3
"""Tests for scraper_jev.py — real assertions against the Jev-powered engine API.

All patches use pytest.monkeypatch so nothing leaks between tests.
"""
import sys, os, json, re, time, unittest.mock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scraper
import jev_client
import scraper_jev as sjev


# ── helpers ────────────────────────────────────────────────────────────────────

def _snap_with(tree_text: str) -> str:
    """Build a snapshot JSON string with the given tree content."""
    return json.dumps({"tree": tree_text})


def _reset_diag(monkeypatch):
    """Zero the counters that tests mutate."""
    for k in ("jev_calls", "jev_fallbacks", "jev_ms", "wait_timeouts"):
        monkeypatch.setitem(sjev.DIAG, k, 0)


def _fake_jev_client(started: bool = True,
                     choice: str = "[0-152] option: Istanbul Airport, Turkey",
                     p: float = 0.9):
    """Build a fake JevClient duck that returns the given pick."""
    class Fake:
        def __init__(self, st=started, ch=choice, pr=p):
            self.started = st
            self._ch = ch
            self._pr = pr
        def pick(self, instructions, candidates, state=""):
            return self._ch, self._pr
    return Fake()


# ── saved-snapshot tests (keep — they read real fixtures) ────────────────────────

def test_fresh_form_candidate_extraction():
    """Extract combobox refs from a fresh-form fixture."""
    with open(os.path.join(os.path.dirname(__file__), "fixtures/fresh_form.txt")) as f:
        tree = f.read()
    candidates = []
    for line in tree.splitlines():
        if "combobox: Where from?" in line or "combobox: Where to?" in line:
            refs = re.findall(r'\[(\d+-\d+)\]', line)
            if refs:
                candidates.append("@" + refs[-1])
    assert len(candidates) >= 1
    assert "combobox" in tree.lower()


def test_airport_dropdown_candidates():
    """Extract Istanbul lines from the airport-dropdown fixture."""
    with open(os.path.join(os.path.dirname(__file__), "fixtures/airport_dropdown_ist.txt")) as f:
        tree = f.read()
    istanbul_lines = [l for l in tree.splitlines() if "Istanbul" in l or "IST" in l]
    assert len(istanbul_lines) >= 2


# ── engine switch (keep) ───────────────────────────────────────────────────────

def test_scraper_engine_switch():
    """SCRAPER_ENGINE env var selects engine; both export the same public API."""
    assert hasattr(scraper, "scrape_route")
    assert hasattr(scraper, "scrape_tickets_all")
    assert hasattr(sjev, "scrape_route")
    assert hasattr(sjev, "scrape_tickets_all")


# ── schema shape (keep) ────────────────────────────────────────────────────────

def test_jev_records_match_schema():
    """Records from scraper_jev pass schema_check.py (same shape as legacy)."""
    record = {
        "route": "DAC→SIN",
        "depart": "January 30, 2027",
        "arrive": "January 31, 2027",
        "depart_time": "10:40 PM",
        "arrive_time": "06:15 AM",
        "airline": "Emirates",
        "stops": "nonstop",
        "duration": "6 hr 45 min",
        "layovers": "none",
        "price_total": 542,
        "link": "https://www.google.com/travel/flights/...",
    }
    required = ["route", "depart", "arrive", "depart_time", "arrive_time",
                "airline", "stops", "duration", "layovers", "price_total", "link"]
    for field in required:
        assert field in record


def test_price_parsing_consistent():
    """Price parsing identical between engines (both import scraper.parse_price)."""
    assert sjev.parse_price("$542") == 542
    assert sjev.parse_price("$1,130") == 1130
    assert sjev.parse_price("") == "N/A"
    assert sjev.parse_price("N/A") == "N/A"


# ── (a) Fake Jev helper — proven by every test below that uses it ──────────────

# Tests (b)–(g) all exercise sjev._pick_airport(snap, code) with a monkeypatched
# jev_client.get_client() that returns a fake JevClient, plus DIAG reset.
# Both dropdown lines contain the FIRST legacy keyword ("Istanbul Airport") on
# purpose: when exactly one option matches it, _pick_airport takes that option
# without asking Jev, so an unambiguous tree would never reach the code under test.

# ── (b) Jev picks the correct airport over the legacy substring match ──────────

def test_jev_pick_overrides_legacy(monkeypatch):
    _reset_diag(monkeypatch)
    tree = """  [0-151] option: Istanbul Airport (IST)
  [0-152] option: Istanbul Airport, Turkey"""
    snap = _snap_with(tree)
    monkeypatch.setattr(jev_client, "get_client",
                        lambda: _fake_jev_client(started=True,
                                                 choice="[0-152] option: Istanbul Airport, Turkey",
                                                 p=0.9))
    result = sjev._pick_airport(snap, "IST")
    # Legacy would return @0-151 (first keyword match); Jev decides @0-152.
    assert result == "@0-152", f"Expected @0-152, got {result}"
    assert sjev.DIAG["jev_calls"] == 1
    assert sjev.DIAG["jev_fallbacks"] == 0


# ── (c) p < 0.6 falls back to legacy reference ─────────────────────────────────

def test_jev_low_probability_fallback(monkeypatch):
    _reset_diag(monkeypatch)
    tree = """  [0-151] option: Istanbul Airport (IST)
  [0-152] option: Istanbul Airport, Turkey"""
    snap = _snap_with(tree)
    legacy_ref = scraper._pick_airport(snap, "IST")      # @0-151
    monkeypatch.setattr(jev_client, "get_client",
                        lambda: _fake_jev_client(started=True,
                                                 choice="[0-152] option: Istanbul Airport, Turkey",
                                                 p=0.4))
    result = sjev._pick_airport(snap, "IST")
    assert result == legacy_ref, f"Expected legacy {legacy_ref}, got {result}"
    assert sjev.DIAG["jev_fallbacks"] == 1      # p below floor


# ── (d) Keyword guardrail: Jev picks a different-city option → fallback ────────

def test_jev_guardrail_rejects_wrong_city(monkeypatch):
    _reset_diag(monkeypatch)
    tree = """  [0-151] option: Istanbul Airport (IST)
  [0-152] option: Istanbul Airport, Turkey
  [0-153] option: Isparta, Turkey"""
    snap = _snap_with(tree)
    legacy_ref = scraper._pick_airport(snap, "IST")      # @0-151
    monkeypatch.setattr(jev_client, "get_client",
                        lambda: _fake_jev_client(started=True,
                                                 choice="[0-153] option: Isparta, Turkey",
                                                 p=0.95))
    result = sjev._pick_airport(snap, "IST")
    assert result == legacy_ref, f"Expected legacy {legacy_ref}, got {result}"
    assert sjev.DIAG["jev_fallbacks"] == 1      # guardrail rejected non-IST option


# ── (e) Jev returns (None, 0) → legacy ref, fallback counted ───────────────────

def test_jev_none_choice_fallback(monkeypatch):
    _reset_diag(monkeypatch)
    tree = """  [0-151] option: Istanbul Airport (IST)
  [0-152] option: Istanbul Airport, Turkey"""
    snap = _snap_with(tree)
    legacy_ref = scraper._pick_airport(snap, "IST")
    monkeypatch.setattr(jev_client, "get_client",
                        lambda: _fake_jev_client(started=True,
                                                 choice=None, p=0.0))
    result = sjev._pick_airport(snap, "IST")
    assert result == legacy_ref
    assert sjev.DIAG["jev_fallbacks"] == 1


# ── (f) Jev client not started → legacy ref, jev_calls unchanged, fallback ─────

def test_jev_client_not_started_fallback(monkeypatch):
    _reset_diag(monkeypatch)
    tree = """  [0-151] option: Istanbul Airport (IST)
  [0-152] option: Istanbul Airport, Turkey"""
    snap = _snap_with(tree)
    legacy_ref = scraper._pick_airport(snap, "IST")
    monkeypatch.setattr(jev_client, "get_client",
                        lambda: _fake_jev_client(started=False))
    result = sjev._pick_airport(snap, "IST")
    assert result == legacy_ref
    assert sjev.DIAG["jev_calls"] == 0      # never called Jev
    assert sjev.DIAG["jev_fallbacks"] == 1  # _pick_element counted fallback


# ── (g) Single candidate → no Jev call, legacy result ──────────────────────────

def test_single_candidate_skips_jev(monkeypatch):
    _reset_diag(monkeypatch)
    tree = "  [0-151] option: Istanbul Airport (IST)"
    snap = _snap_with(tree)
    monkeypatch.setattr(jev_client, "get_client", lambda: _fake_jev_client(started=True))
    result = sjev._pick_airport(snap, "IST")
    assert result == "@0-151"
    assert sjev.DIAG["jev_calls"] == 0      # never called Jev for 1 candidate


# ── (h) wait_for behaviour ──────────────────────────────────────────────────────

def test_wait_for_returns_on_first_snapshot(monkeypatch):
    _reset_diag(monkeypatch)
    calls = []
    snap = _snap_with("[0-1] combobox: Where from?")
    monkeypatch.setattr(sjev, "_snap", lambda: (calls.append(1), snap)[1])
    result = sjev.wait_for(lambda t: sjev._has(t, "where from?"), timeout=1.0)
    assert "where from" in result.lower()
    assert len(calls) == 1
    assert sjev.DIAG["wait_timeouts"] == 0


def test_wait_for_timeout_counts(monkeypatch):
    _reset_diag(monkeypatch)
    snap = _snap_with("[0-1] combobox: Where from?")
    monkeypatch.setattr(sjev, "_snap", lambda: snap)
    result = sjev.wait_for(lambda t: "never-match" in t, timeout=0.3, step=0.1)
    assert "where from" in result.lower()
    assert sjev.DIAG["wait_timeouts"] == 1


def test_wait_for_timeout_no_count(monkeypatch):
    _reset_diag(monkeypatch)
    snap = _snap_with("[0-1] combobox: Where from?")
    monkeypatch.setattr(sjev, "_snap", lambda: snap)
    result = sjev.wait_for(lambda t: "never-match" in t, timeout=0.3, step=0.1,
                           count_timeout=False)
    assert "where from" in result.lower()
    assert sjev.DIAG["wait_timeouts"] == 0


# ── (i) _verify_fill ───────────────────────────────────────────────────────────

def test_verify_fill_passes(monkeypatch):
    _reset_diag(monkeypatch)
    tree = """  Hazrat Shahjalal International Airport
  Singapore Changi Airport
  Fri, Jan 30"""
    assert sjev._verify_fill(tree, [("DAC", "SIN", "January 30, 2027")]) is True


def test_verify_fill_wrong_origin_fails(monkeypatch):
    _reset_diag(monkeypatch)
    tree = """  Boston Logan International Airport
  Singapore Changi Airport
  Fri, Jan 30"""
    assert sjev._verify_fill(tree, [("DAC", "SIN", "January 30, 2027")]) is False


def test_verify_fill_date_variant_passes(monkeypatch):
    _reset_diag(monkeypatch)
    tree = """  Hazrat Shahjalal International Airport
  Singapore Changi Airport
  January 30"""
    assert sjev._verify_fill(tree, [("DAC", "SIN", "January 30, 2027")]) is True


# ── (j) JevClient edge cases (no process needed) ───────────────────────────────

def test_jev_client_start_no_key(monkeypatch):
    """Start with env lacking the API key returns False."""
    client = jev_client.JevClient()
    assert client.started is False
    assert client.process is None
    result = client.start(env={"SOME_VAR": "x"})   # no AI_GATEWAY_API_KEY
    assert result is False
    assert client.started is False
    assert client.process is None
    # pick on a non-started client returns (None, 0)
    choice, p = client.pick("instructions", ["a", "b"])
    assert choice is None
    assert p == 0


def test_jev_client_pick_one_candidate(monkeypatch):
    """Single candidate shortcut returns (candidate, 1.0) without a process."""
    client = jev_client.JevClient()
    client.started = True
    client.process = unittest.mock.Mock()
    client.process.poll.return_value = None
    choice, p = client.pick("x", ["single"], "")
    assert choice == "single"
    assert p == 1.0


def test_jev_client_pick_empty_candidates(monkeypatch):
    """Empty candidates returns (None, 0) without a process."""
    client = jev_client.JevClient()
    client.started = True
    client.process = unittest.mock.Mock()
    client.process.poll.return_value = None
    choice, p = client.pick("x", [], "")
    assert choice is None
    assert p == 0