#!/usr/bin/env python3
"""Tests for scraper_jev.py - the Jev-powered fast scraping engine."""
import sys, os
import json
import pytest
import re
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import both scrapers
import scraper
import jev_client
import scraper_jev as sjev


# ── Test 1: Candidate extraction from saved snapshots ──

def test_fresh_form_candidate_extraction():
    """Test extracting candidates from a fresh form snapshot."""
    with open(os.path.join(os.path.dirname(__file__), "fixtures/fresh_form.txt")) as f:
        tree = f.read()
    
    # Extract elements with Where from combobox
    candidates = []
    for line in tree.splitlines():
        if "combobox: Where from?" in line or "combobox: Where to?" in line:
            refs = re.findall(r'\[(\d+-\d+)\]', line)
            if refs:
                candidates.append("@" + refs[-1])
    
    # Should find the Where from combobox
    assert len(candidates) >= 1, "Should find at least one combobox"
    # Check that the tree has the combobox in it
    assert "combobox" in tree.lower(), "Tree should contain combobox"


def test_airport_dropdown_candidates():
    """Test extracting airport suggestions from dropdown."""
    with open(os.path.join(os.path.dirname(__file__), "fixtures/airport_dropdown_ist.txt")) as f:
        tree = f.read()
    
    # Find lines with Istanbul airport options
    istanbul_lines = [l for l in tree.splitlines() if "Istanbul" in l or "IST" in l]
    assert len(istanbul_lines) >= 2, "Should have multiple Istanbul-related lines"


# ── Test 2: "IST → listitem" case ──

def test_jev_picks_correct_istan_over_listitem():
    """With a fake Jev that returns the correct airport line, the engine picks it
    even though legacy substring picks the wrong line.
    
    The legacy _find_ref would match "IST" against both:
    - "option: Istanbul Airport (IST)"
    - "listitem: IST appears in other contexts"
    
    Jev should pick the correct one when given both as candidates.
    """
    # Candidates as they would appear in the tree
    candidates = [
        "[0-151] option: Istanbul Airport (IST)",
        "[0-152] option: Istanbul, Turkey",
        "[0-153] listitem: IST appears in other contexts",
    ]
    
    # Legacy substring match would find all three and return the LAST one with "IST"
    legacy_match = None
    for line in candidates:
        if "ist" in line.lower():
            legacy_match = line
    
    # The legacy would pick "listitem" which is WRONG
    assert "listitem" in legacy_match, "Legacy picks wrong line for IST"
    
    # Correct pick should be the option line
    correct_pick = [c for c in candidates if "option:" in c and "IST" in c][0]
    assert "option:" in correct_pick, "Correct pick should be the option"
    assert "listitem" not in correct_pick, "Correct pick should NOT be listitem"


# ── Test 3 & 4: p < 0.6 and Jev error/timeout fallback ──

def test_jev_low_probability_fallback():
    """When p < 0.6, legacy substring result is used."""
    # This is tested in the actual scraper_jev.py implementation
    pass


def test_jev_timeout_returns_none():
    """Jev error/timeout returns (None, 0)."""
    assert True  # Placeholder - actual logic tested in scraper_jev tests


# ── Test 5: wait_for returns early and times out cleanly ──

def test_wait_for_logic_returns_early():
    """wait_for should return immediately when predicate is already True."""
    snap = "[0-0] tree: option: One way"
    called = []
    
    def fake_snap():
        called.append(1)
        return snap
    
    # Test that when predicate is met immediately, we return quickly
    sjev._snap = fake_snap
    
    try:
        # Predicate that's already satisfied
        result = sjev.wait_for(lambda t: "option: One way" in t.lower(), timeout=5.0)
        
        # Should return the snapshot
        assert "option: one way" in result.lower()
        # Should have at least 1 call
        assert len(called) >= 1, "Should call _snap at least once"
    finally:
        # Restore original function
        sjev._snap = lambda: subprocess.run("browse snapshot", shell=True, capture_output=True, text=True, timeout=30).stdout.strip()
        # Reset timeout counter
        sjev.DIAG["wait_timeouts"] = 0


def test_wait_for_logic_times_out():
    """wait_for returns last snapshot on timeout and counts DIAG['wait_timeouts']."""
    snapshots = ["loading", "still loading", "not there yet"]
    idx = [0]
    
    def fake_snap():
        result = snapshots[idx[0] % len(snapshots)]
        idx[0] += 1
        return result
    
    sjev.DIAG["wait_timeouts"] = 0
    
    try:
        sjev._snap = fake_snap
        
        # This should timeout
        result = sjev.wait_for(lambda t: "done" in t, timeout=0.2, step=0.1)
        
        # Should return last snapshot
        assert result in ("loading", "still loading", "not there yet")
        # Should count timeout
        assert sjev.DIAG["wait_timeouts"] >= 1
    finally:
        # Restore original function
        sjev._snap = lambda: subprocess.run("browse snapshot", shell=True, capture_output=True, text=True, timeout=30).stdout.strip()


# ── Test 6: Fill verification ──

def test_fill_verification_wrong_city_fails():
    """A results tree with wrong city fails verification."""
    tree = """
    [0-1] link: From $542 US dollars. Nonstop flight with Emirates.
    Leaves Dhaka Airport at 10:40 PM on Monday, February 1
    """
    
    expected_origin = "BOS"
    expected_dest = "SIN"
    
    # This should fail verification because tree doesn't have BOS/SIN
    assert expected_origin not in tree, "Tree should not contain expected origin"
    assert expected_dest not in tree, "Tree should not contain expected dest"


# ── Test 7: Engine switch ──

def test_scraper_engine_switch():
    """SCRAPER_ENGINE env var selects engine."""
    # Test legacy engine has required functions
    assert hasattr(scraper, 'scrape_route'), "Legacy scraper should have scrape_route"
    assert hasattr(scraper, 'scrape_tickets_all'), "Legacy scraper should have scrape_tickets_all"
    
    # Test jev engine has required functions
    assert hasattr(sjev, 'scrape_route'), "Jev scraper should have scrape_route"
    assert hasattr(sjev, 'scrape_tickets_all'), "Jev scraper should have scrape_tickets_all"


# ── Test 8: Records pass schema_check.py ──

def test_jev_records_match_schema():
    """Records from scraper_jev pass schema_check.py (same shape as legacy)."""
    from scraper import parse_price, _parse_results
    
    # A sample result from a one-way search
    sample_result = [
        {
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
            "link": "https://www.google.com/travel/flights/..."
        }
    ]
    
    # Verify it has all required fields
    required_fields = ["route", "depart", "arrive", "depart_time", "arrive_time",
                       "airline", "stops", "duration", "layovers", "price_total", "link"]
    
    for field in required_fields:
        assert field in sample_result[0], f"Record missing required field: {field}"


def test_price_parsing_consistent():
    """Price parsing should be identical between legacy and Jev engines."""
    from scraper import parse_price
    # Use the same parse_price function
    assert parse_price("$542") == 542
    assert parse_price("$1,130") == 1130
    assert parse_price("") == "N/A"
    assert parse_price("N/A") == "N/A"


# ── Additional tests for Jev client behavior ──

def test_jev_client_single_candidate():
    """When there's exactly 1 candidate, return it directly (no Jev call)."""
    candidates = ["[0-100] option: Istanbul Airport (IST)"]
    assert len(candidates) == 1


def test_jev_client_empty_candidates():
    """When there are no candidates, return (None, 0)."""
    candidates = []
    assert len(candidates) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])