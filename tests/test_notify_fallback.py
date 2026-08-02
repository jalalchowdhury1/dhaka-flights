"""notify_cheapest must never raise and must never let a broken payload (or
a broken send_message) cost the run its Telegram message — the same
never-raise contract publish.write_payload holds, applied to the notify
step so a build/send failure can't kill the run before write_payload runs.
It also reports back WHICH rung actually sent ("full" | "core" | "minimal"
| "none") — run_daily.py uses that to decide whether tonight's brief was
good enough to count as done."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import notify_telegram

# A minimal well-formed `main` — enough for build_message to render both the
# full and core_only cores without raising (it indexes total/dhaka_days/home
# directly, unguarded, so those three are non-negotiable).
VALID_MAIN = {
    "total": 4626,
    "order_label": "SIN-first",
    "valid": True,
    "dhaka_days": 20,
    "home": "Feb 7, 2027",
    "ist_nights": 2,
    "order": "SIN-first",
    "sg_nights": 3,
    "bkk_nights": 5,
}


def test_no_trip_day_still_sends(monkeypatch):
    sent = []
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": sent.append(text) or True)
    # No "main" key — a catastrophic-but-contract-legal day (main=None is
    # explicitly allowed), which build_message's own "no trip" branch
    # already handles without raising.
    status = notify_telegram.notify_cheapest({"warnings": [], "history": []})
    assert len(sent) == 1
    assert status == "full"


def test_send_message_raising_does_not_propagate(monkeypatch):
    def boom(text, parse_mode="HTML"):
        raise RuntimeError("network is on fire")
    monkeypatch.setattr(notify_telegram, "send_message", boom)
    status = notify_telegram.notify_cheapest({"warnings": [], "history": []})
    assert status == "none"  # must not raise, and must honestly report nothing sent


def test_main_missing_total_falls_through_to_a_fallback_send(monkeypatch):
    # This is the concrete case build_message can't survive on its own:
    # main is a non-empty dict (so the "no trip" branch is skipped) but
    # lacks 'total', which the core message indexes unconditionally — for
    # both the full and core_only builds, so both rungs fail identically
    # and only the minimal static rung is left.
    sent = []
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": sent.append(text) or True)
    payload = {"warnings": [], "history": [], "main": {"order_label": "IST-first"}}
    status = notify_telegram.notify_cheapest(payload)
    assert len(sent) == 1
    assert status == "minimal"
    assert "could not be built" in sent[0]


def test_main_missing_total_and_send_failing_still_does_not_raise(monkeypatch):
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": False)
    payload = {"warnings": [], "history": [], "main": {"order_label": "IST-first"}}
    status = notify_telegram.notify_cheapest(payload)  # must not raise
    assert status == "none"


def test_full_send_fails_core_only_succeeds(monkeypatch):
    calls = []

    def fake_send(text, parse_mode="HTML"):
        calls.append(text)
        return len(calls) != 1  # first attempt (full) fails, second succeeds
    monkeypatch.setattr(notify_telegram, "send_message", fake_send)
    payload = {"warnings": [], "history": [], "main": dict(VALID_MAIN)}
    status = notify_telegram.notify_cheapest(payload)
    assert status == "core"
    assert len(calls) == 2


def test_minimal_rung_includes_the_first_warnings(monkeypatch):
    sent = []
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": sent.append(text) or True)
    payload = {
        "warnings": ["scraper timed out", "sanity check failed", "extra note",
                     "should be dropped"],
        "history": [],
        "main": {"order_label": "IST-first"},   # missing 'total' -> forces minimal
    }
    notify_telegram.notify_cheapest(payload)
    assert len(sent) == 1
    assert "scraper timed out" in sent[0]
    assert "sanity check failed" in sent[0]
    assert "extra note" in sent[0]
    assert "should be dropped" not in sent[0]


def test_everything_fails_reports_none_and_still_does_not_raise(monkeypatch):
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": False)
    payload = {"warnings": [], "history": [], "main": dict(VALID_MAIN)}
    status = notify_telegram.notify_cheapest(payload)
    assert status == "none"
