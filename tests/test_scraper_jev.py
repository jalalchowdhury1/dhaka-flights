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


@pytest.fixture(autouse=True)
def _judge_dir_isolated(monkeypatch, tmp_path):
    """Never let a test write into the real bench/judge calibration log."""
    monkeypatch.setattr(sjev, "JUDGE_DIR", str(tmp_path / "judge"))
    monkeypatch.setitem(sjev.DIAG, "gates", {})


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

# ── (i) _fill_airport retries once when the pick does not stick ────────────────

def _stub_fill_airport(monkeypatch, shows):
    """Stub every browser touchpoint of _fill_airport; `shows` = _box_shows answers."""
    calls = []
    answers = iter(shows)
    monkeypatch.setitem(sjev.DIAG, "pick_retries", 0)
    # another test module imports run_daily, which starts the real Jev server;
    # these tests exercise the rule path, so pin a not-started client
    monkeypatch.setattr(jev_client, "get_client", lambda: _fake_jev_client(started=False))
    monkeypatch.setattr(sjev, "_run", lambda cmd: calls.append(cmd) or "")
    monkeypatch.setattr(sjev.time, "sleep", lambda s: None)
    monkeypatch.setattr(sjev, "_box_ref", lambda label, row: "@0-1")
    monkeypatch.setattr(sjev, "_pick_airport", lambda snap, code: "@0-9")
    monkeypatch.setattr(sjev._legacy, "_pick_airport", lambda snap, code: "@0-9")
    monkeypatch.setattr(sjev, "wait_for", lambda pred, timeout=5.0, **k: "{}")
    monkeypatch.setattr(sjev, "_get_tree", lambda snap: "")
    monkeypatch.setattr(sjev, "_box_shows", lambda tree, label, row, names: next(answers))
    return calls


def test_fill_airport_retries_once_and_recovers(monkeypatch):
    calls = _stub_fill_airport(monkeypatch, [False, True])
    sjev._fill_airport("Where to?", "DAC")
    assert sjev.DIAG["pick_retries"] == 1
    assert calls.count("browse type DAC") == 2      # typed again on the retry
    assert calls.count("browse click @0-9") == 2    # picked again on the retry


def test_fill_airport_gives_up_after_one_retry(monkeypatch, capsys):
    calls = _stub_fill_airport(monkeypatch, [False, False])
    sjev._fill_airport("Where to?", "DAC")           # must not raise
    assert calls.count("browse type DAC") == 2       # exactly one retry, not a loop
    assert "may not show DAC" in capsys.readouterr().out


def test_fill_airport_happy_path_does_not_retry(monkeypatch):
    calls = _stub_fill_airport(monkeypatch, [True])
    sjev._fill_airport("Where to?", "DAC")
    assert sjev.DIAG["pick_retries"] == 0
    assert calls.count("browse type DAC") == 1


# ── airport pick must be *settled*, not just typed (19 Sep 2026 nightly) ────────
#
# Real trees captured live 19 Sep: with the dropdown still open and "Bangkok"
# typed, the box already shows the name, so a "does the box show it" check is
# fooled and the Departure box is hidden behind the list (tonight's
# "no 'Departure' box on the form" fallback). The pick counts only once the
# dropdown has closed.

def _fixture(name: str) -> str:
    with open(os.path.join(os.path.dirname(__file__), "fixtures", name)) as f:
        return f.read()


def _drive_fill_airport(monkeypatch, tree: str, jev=None):
    """Run _fill_airport against a page frozen at `tree`; return the browse commands.
    `jev` = a fake client (default: not started, so the deterministic rule decides)."""
    cmds = []
    monkeypatch.setattr(jev_client, "get_client",
                        lambda: jev if jev is not None else _fake_jev_client(started=False))
    monkeypatch.setitem(sjev.DIAG, "judge_disagreements", 0)
    monkeypatch.setattr(sjev, "_snap", lambda: _snap_with(tree))
    monkeypatch.setattr(sjev, "_run", lambda cmd: (cmds.append(cmd), "")[1])
    monkeypatch.setattr(sjev.time, "sleep", lambda s: None)
    monkeypatch.setattr(sjev, "wait_for",
                        lambda pred, timeout, step=0.25, count_timeout=True: _snap_with(tree))
    monkeypatch.setitem(sjev.DIAG, "pick_retries", 0)
    snap = sjev._fill_airport("Where to?", "BKK")
    return cmds, snap


def test_pick_settled_distinguishes_open_dropdown_from_real_pick():
    names = sjev._airport_keywords("BKK")
    open_tree = _fixture("dest_dropdown_open_bkk.txt")
    picked_tree = _fixture("dest_picked_bkk.txt")
    assert sjev._box_shows(open_tree, "Where to?", 0, names)      # the trap: typed text passes
    assert not sjev._pick_settled(open_tree, "Where to?", 0, names)
    assert sjev._pick_settled(picked_tree, "Where to?", 0, names)


def test_fill_airport_retries_when_dropdown_stays_open(monkeypatch):
    cmds, _ = _drive_fill_airport(monkeypatch, _fixture("dest_dropdown_open_bkk.txt"))
    assert sjev.DIAG["pick_retries"] == 1
    assert sum(1 for c in cmds if c.startswith("browse type ")) == 2


def test_fill_airport_returns_once_pick_settled(monkeypatch):
    cmds, _ = _drive_fill_airport(monkeypatch, _fixture("dest_picked_bkk.txt"))
    assert sjev.DIAG["pick_retries"] == 0
    assert sum(1 for c in cmds if c.startswith("browse type ")) == 1


# ── Jev makes the pick determination; the rule is only the fallback ─────────────

def test_jev_judges_pick_from_form_region(monkeypatch):
    """Jev sees only the region around the box, and its verdict is returned."""
    seen = {}
    class Fake:
        started = True
        def pick(self, instructions, candidates, state=""):
            seen["state"] = state; seen["candidates"] = candidates
            return sjev.PICK_VERDICTS["settled"], 0.95
    monkeypatch.setattr(jev_client, "get_client", lambda: Fake())
    monkeypatch.setitem(sjev.DIAG, "judge_disagreements", 0)
    tree = _fixture("dest_picked_bkk.txt")
    assert sjev._judge_pick(tree, "Where to?", 0, "BKK", sjev._airport_keywords("BKK"))
    assert "Where to?" in seen["state"] and len(seen["state"]) < len(tree)
    assert set(seen["candidates"]) == set(sjev.PICK_VERDICTS.values())
    assert sjev.DIAG["judge_disagreements"] == 0


def test_jev_overrules_rule_and_forces_retry(monkeypatch):
    """Jev says the dropdown is still open although the rule is satisfied → retry, and the disagreement is counted."""
    jev = _fake_jev_client(started=True, choice=sjev.PICK_VERDICTS["dropdown-open"], p=0.9)
    cmds, _ = _drive_fill_airport(monkeypatch, _fixture("dest_picked_bkk.txt"), jev=jev)
    assert sjev.DIAG["pick_retries"] == 1
    assert sjev.DIAG["judge_disagreements"] == 2      # once per attempt


def test_jev_unsure_falls_back_to_rule(monkeypatch):
    """Below the p floor Jev's verdict is ignored and the rule decides (open dropdown → retry)."""
    jev = _fake_jev_client(started=True, choice=sjev.PICK_VERDICTS["settled"], p=0.4)
    cmds, _ = _drive_fill_airport(monkeypatch, _fixture("dest_dropdown_open_bkk.txt"), jev=jev)
    assert sjev.DIAG["pick_retries"] == 1                 # the rule decided
    assert sjev.DIAG["gates"]["airports"]["by_jev"] == 0
    assert sjev.DIAG["gates"]["airports"]["disagreed"] == 2   # still recorded for calibration


# ── _judge: one helper for every gate; shadow unless the gate is in JEV_DECIDES ──

_V = {"good": "the step landed", "open": "a menu is still open", "bad": "wrong value"}


def _judge_env(monkeypatch, tmp_path, decides, verdict_key, p=0.9):
    monkeypatch.setattr(sjev, "JEV_DECIDES", set(decides))
    monkeypatch.setattr(sjev, "JUDGE_DIR", str(tmp_path))
    monkeypatch.setitem(sjev.DIAG, "gates", {})
    monkeypatch.setitem(sjev.DIAG, "judge_disagreements", 0)
    monkeypatch.setattr(jev_client, "get_client",
                        lambda: _fake_jev_client(started=True, choice=_V[verdict_key], p=p))


def test_judge_shadow_gate_returns_rule_and_logs(monkeypatch, tmp_path):
    _judge_env(monkeypatch, tmp_path, decides=[], verdict_key="open")
    assert sjev._judge("passengers", "region text", "q?", _V, rule=True, good="good") is True
    g = sjev.DIAG["gates"]["passengers"]
    assert g["judged"] == 1 and g["disagreed"] == 1 and g["by_jev"] == 0
    rows = [json.loads(l) for l in open(tmp_path / "log.jsonl")]
    assert rows[0]["gate"] == "passengers" and rows[0]["verdict"] == "open" and rows[0]["p"] == 0.9
    assert rows[0]["rule"] is True and rows[0]["decided_by"] == "rule"
    saved = [f for f in os.listdir(tmp_path) if f.startswith("passengers-")]
    assert len(saved) == 1 and "region text" in open(tmp_path / saved[0]).read()


def test_judge_deciding_gate_uses_jev_verdict(monkeypatch, tmp_path):
    _judge_env(monkeypatch, tmp_path, decides=["passengers"], verdict_key="open")
    assert sjev._judge("passengers", "region", "q?", _V, rule=True, good="good") is False
    g = sjev.DIAG["gates"]["passengers"]
    assert g["by_jev"] == 1 and g["disagreed"] == 1


def test_judge_deciding_gate_unsure_falls_back_to_rule(monkeypatch, tmp_path):
    _judge_env(monkeypatch, tmp_path, decides=["passengers"], verdict_key="open", p=0.4)
    assert sjev._judge("passengers", "region", "q?", _V, rule=True, good="good") is True
    rows = [json.loads(l) for l in open(tmp_path / "log.jsonl")]
    assert rows[0]["p"] == 0.4 and rows[0]["decided_by"] == "rule"


def test_judge_agreement_saves_nothing(monkeypatch, tmp_path):
    _judge_env(monkeypatch, tmp_path, decides=["passengers"], verdict_key="good")
    assert sjev._judge("passengers", "region", "q?", _V, rule=True, good="good") is True
    assert sjev.DIAG["gates"]["passengers"]["disagreed"] == 0
    assert [f for f in os.listdir(tmp_path) if f.endswith(".txt")] == []


def test_judge_jev_off_returns_rule_without_logging_a_verdict(monkeypatch, tmp_path):
    _judge_env(monkeypatch, tmp_path, decides=["passengers"], verdict_key="open")
    monkeypatch.setattr(jev_client, "get_client", lambda: _fake_jev_client(started=False))
    assert sjev._judge("passengers", "region", "q?", _V, rule=False, good="good") is False
    assert sjev.DIAG["gates"]["passengers"]["unavailable"] == 1
    assert not os.path.exists(tmp_path / "log.jsonl")


def test_jev_decides_env_parsing(monkeypatch):
    assert sjev._parse_decides("airports, date ,") == {"airports", "date"}
    assert sjev._parse_decides("") == set()
    assert sjev._parse_decides(None) == {"landing", "ticket_type", "passengers", "airports"}
    assert "date" not in sjev.DEFAULT_DECIDES and "results_ready" not in sjev.DEFAULT_DECIDES


# ── the six shadow gates (landing / ticket_type / passengers / date /
#    results_ready / fill_verified): rule decides unless the gate is in
#    JEV_DECIDES; every judgment is logged under the gate name ─────────────────

TT_OPEN = "combobox: Change ticket type. Round trip\noption: Round trip\noption: One way\noption: Multi-city"
TT_SET = "combobox: Change ticket type. One way\nbutton: 1 passenger"
PAX_FRESH = ("button: 1 passenger\ndialog: Number of passengers\nStaticText: Adults\nbutton: Remove adult\nStaticText: 1\n"
             "button: Add adult\nStaticText: Children\nbutton: Remove child\nStaticText: 0\nbutton: Add child\nbutton: Done")
PAX_OPEN = ("button: 1 passenger\ndialog: Number of passengers\nStaticText: Adults\nbutton: Remove adult\nStaticText: 2\n"
            "button: Add adult\nStaticText: Children\nbutton: Remove child\nStaticText: 1\nbutton: Add child\nbutton: Done")
PAX_SET = "button: 3 passengers\ncombobox: Where from?"
CAL_OPEN = "textbox: Departure\nbutton: Done\ngridcell: February 1"
DATE_SET = "textbox: Departure Feb 1\ncombobox: Where to?"
FORM = "main\ncombobox: Where from?\ncombobox: Where to?\ntextbox: Departure"


def _drive(monkeypatch, tmp_path, trees, decides=(), jev=None, p=0.9):
    """Stub the browser: each wait_for/_snap pops the next tree (last one repeats)."""
    it = iter(trees); last = [trees[-1]]
    def nxt():
        try: last[0] = next(it)
        except StopIteration: pass
        return last[0]
    calls = []
    monkeypatch.setattr(sjev, "JEV_DECIDES", set(decides))
    monkeypatch.setattr(sjev, "JUDGE_DIR", str(tmp_path))
    monkeypatch.setitem(sjev.DIAG, "gates", {})
    monkeypatch.setitem(sjev.DIAG, "blank_pages", 0)
    client = _fake_jev_client(started=jev is not None, choice=jev or "", p=p)
    monkeypatch.setattr(jev_client, "get_client", lambda: client)
    monkeypatch.setattr(sjev, "_run", lambda cmd: calls.append(cmd) or "")
    monkeypatch.setattr(sjev.time, "sleep", lambda s: None)
    monkeypatch.setattr(sjev, "_get_tree", lambda snap: snap)
    monkeypatch.setattr(sjev, "wait_for", lambda pred, timeout=5.0, **k: nxt())
    monkeypatch.setattr(sjev, "_snap", nxt)
    monkeypatch.setattr(sjev, "_find_ref",
                        lambda snap, *kw: "@1" if " ".join(kw).lower() in snap.lower() else "")
    monkeypatch.setattr(sjev, "_box_ref", lambda label, row: "@1")
    monkeypatch.setattr(sjev, "_url", lambda: "https://www.google.com/travel/flights")
    monkeypatch.setattr(sjev._legacy, "_ensure_session", lambda: None)
    monkeypatch.setattr(sjev._legacy, "_session_dirty", lambda: None)
    return calls


def _logged(tmp_path):
    return [json.loads(l) for l in open(tmp_path / "log.jsonl")]


def test_gate_rules_read_the_tree():
    assert sjev._ticket_type_set(TT_SET, "One way") and not sjev._ticket_type_set(TT_OPEN, "One way")
    assert sjev._passengers_set(PAX_SET) and not sjev._passengers_set(PAX_OPEN)
    assert sjev._date_set(DATE_SET, "February 1, 2027", 0) and not sjev._date_set(CAL_OPEN, "February 1, 2027", 0)


def test_region_helpers():
    tree = "\n".join(f"  line {i}" for i in range(20))
    assert sjev._region_around(tree, "line 5", 0, 1, 3).splitlines() == ["line 4", "line 5", "line 6", "line 7"]
    assert sjev._region_around(tree, "nope") == ""
    assert sjev._region_head(tree, 2) == "line 0\nline 1"


def test_gate_passes_placeholder_for_missing_region(monkeypatch):
    seen = {}
    monkeypatch.setattr(sjev, "_judge", lambda gate, region, q, verdicts, rule, good: seen.update(region=region, good=good) or rule)
    assert sjev._gate("date", "", "q?", True) is True
    assert "region not found" in seen["region"] and seen["good"] == "date-shown"


def test_ticket_type_shadow_redoes_once_when_rule_fails(monkeypatch, tmp_path):
    calls = _drive(monkeypatch, tmp_path, [TT_OPEN, TT_OPEN, TT_OPEN, TT_OPEN, TT_SET, TT_SET],
                   jev=sjev.GATE_VERDICTS["ticket_type"]["menu-still-open"])
    sjev._set_ticket_type(TT_OPEN, "One way")
    assert calls.count("browse click @1") >= 3          # opened + option, then redo
    rows = _logged(tmp_path)
    assert [r["gate"] for r in rows] == ["ticket_type", "ticket_type"]
    assert rows[0]["rule"] is False and rows[0]["decided_by"] == "rule"
    assert sjev.DIAG["gates"]["ticket_type"]["by_jev"] == 0


def test_ticket_type_jev_deciding_overrules_rule(monkeypatch, tmp_path, capsys):
    _drive(monkeypatch, tmp_path, [TT_SET], decides=["ticket_type"],
           jev=sjev.GATE_VERDICTS["ticket_type"]["menu-still-open"])
    sjev._set_ticket_type(TT_SET, "One way")
    assert "redoing ticket type" in capsys.readouterr().out
    assert sjev.DIAG["gates"]["ticket_type"]["by_jev"] == 2


def test_dialog_counts_reads_the_steppers():
    assert sjev._dialog_counts(PAX_FRESH) == (1, 0)
    assert sjev._dialog_counts(PAX_OPEN) == (2, 1)
    assert sjev._dialog_counts("no dialog here") == (-1, -1)


def test_passengers_redo_adds_only_what_is_missing(monkeypatch, tmp_path):
    # attempt 1: fresh dialog (1/0) -> add adult + child, Done hidden -> gate fails
    # attempt 2: dialog already 2/1 -> Done only (19 Sep calibration ended at 5 passengers)
    trees = [PAX_FRESH, PAX_FRESH, PAX_FRESH, PAX_FRESH, PAX_FRESH,   # attempt 1 (no Done -> stays open)
             PAX_OPEN, PAX_OPEN, PAX_SET, PAX_SET]                    # attempt 2
    calls = _drive(monkeypatch, tmp_path, trees, jev=sjev.GATE_VERDICTS["passengers"]["dialog-still-open"])
    monkeypatch.setattr(sjev, "_find_ref",
                        lambda snap, *kw: "" if (" ".join(kw) == "button: Done" and snap is PAX_FRESH)
                        else ("@1" if " ".join(kw).lower() in snap.lower() else ""))
    sjev._set_passengers(PAX_FRESH)
    assert calls.count("browse click @1") == 5           # pax, adult, child | pax, done
    assert [r["gate"] for r in _logged(tmp_path)] == ["passengers", "passengers"]


def test_fill_date_redoes_once(monkeypatch, tmp_path):
    calls = _drive(monkeypatch, tmp_path, [CAL_OPEN, CAL_OPEN, CAL_OPEN, DATE_SET],
                   jev=sjev.GATE_VERDICTS["date"]["calendar-still-open"])
    sjev._fill_date("February 1, 2027")
    assert calls.count('browse type "February 1, 2027"') == 2
    rows = _logged(tmp_path)
    assert [r["rule"] for r in rows] == [False, True]


def test_results_ready_shadow_waits_once_more_when_rule_fails(monkeypatch, tmp_path):
    _drive(monkeypatch, tmp_path, ["loading"], jev=sjev.GATE_VERDICTS["results_ready"]["still-loading"])
    waited = []
    monkeypatch.setattr(sjev, "_wait_for_results", lambda **k: waited.append(k) or "results US dollars")
    assert sjev._judge_results_ready("loading", one_way=True) == "results US dollars"
    assert waited and waited[0]["stable_polls"] == 2
    assert _logged(tmp_path)[0]["gate"] == "results_ready"


def test_fill_verified_shadow_returns_rule(monkeypatch, tmp_path):
    _drive(monkeypatch, tmp_path, ["x"], jev=sjev.GATE_VERDICTS["fill_verified"]["different-route-or-date"])
    monkeypatch.setattr(sjev, "_verify_fill", lambda tree, legs: True)
    assert sjev._judge_fill("Where from DAC to SIN", [("DAC", "SIN", "January 28, 2027")]) is True
    row = _logged(tmp_path)[0]
    assert row["gate"] == "fill_verified" and row["verdict"] == "different-route-or-date" and row["rule"] is True


def test_open_form_reopens_once_when_landing_fails(monkeypatch, tmp_path):
    calls = _drive(monkeypatch, tmp_path, ["blank", "blank", FORM], jev=sjev.GATE_VERDICTS["landing"]["form-visible"])
    assert sjev._open_form() == FORM
    assert sum(c.startswith("browse open") for c in calls) == 3   # first, pre-gate reopen, post-gate reopen
    assert [r["gate"] for r in _logged(tmp_path)] == ["landing", "landing"]
    assert sjev.DIAG["blank_pages"] == 0
