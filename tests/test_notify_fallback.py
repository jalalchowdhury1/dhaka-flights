"""notify_cheapest must never raise and must never let a broken payload (or
a broken send_message) cost the run its Telegram message — the same
never-raise contract publish.write_payload holds, applied to the notify
step so a build/send failure can't kill the run before write_payload runs."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import notify_telegram


def test_broken_payload_still_sends_something(monkeypatch):
    sent = []
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": sent.append(text) or True)
    # No "main"/"trip" keys — structurally broken relative to what
    # build_message assumes a well-formed payload carries.
    notify_telegram.notify_cheapest({"warnings": [], "history": []})
    assert len(sent) == 1


def test_send_message_raising_does_not_propagate(monkeypatch):
    def boom(text, parse_mode="HTML"):
        raise RuntimeError("network is on fire")
    monkeypatch.setattr(notify_telegram, "send_message", boom)
    notify_telegram.notify_cheapest({"warnings": [], "history": []})  # must not raise


def test_main_missing_total_falls_through_to_a_fallback_send(monkeypatch):
    # This is the concrete case build_message can't survive on its own:
    # main is a non-empty dict (so the "no trip" branch is skipped) but
    # lacks 'total', which the core message indexes unconditionally.
    sent = []
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": sent.append(text) or True)
    payload = {"warnings": [], "history": [], "main": {"order_label": "IST-first"}}
    notify_telegram.notify_cheapest(payload)
    assert len(sent) == 1


def test_main_missing_total_and_send_failing_still_does_not_raise(monkeypatch):
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": False)
    payload = {"warnings": [], "history": [], "main": {"order_label": "IST-first"}}
    notify_telegram.notify_cheapest(payload)  # must not raise
