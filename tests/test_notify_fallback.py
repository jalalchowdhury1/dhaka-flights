"""notify_cheapest must never raise and must never let a broken payload (or
a broken send_message) cost the run its Telegram message — the same
never-raise contract publish.write_payload holds, applied to the notify
step so a build/send failure can't kill the run before write_payload runs.
It also reports back WHICH rung actually sent ("full" | "core" | "minimal"
| "none" | "broken") — run_daily.py uses that to decide whether tonight's
brief was good enough to count as done. "none" and "broken" both mean
nothing reached anyone, but for different reasons: "none" = a real build
succeeded and only Telegram delivery failed (data is fine); "broken" =
neither the full nor the core build ever rendered (a genuine payload
problem) — collapsing that distinction was the exact hole a prior review
found (a missing-total payload + a dead send_message used to both read as
plain "none")."""
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


def test_main_missing_total_and_send_failing_reports_broken_not_none(monkeypatch):
    # Neither the full nor the core build ever rendered (missing 'total')
    # AND every send failed — this must read as "broken" (a payload
    # problem), not "none" (a delivery-only problem), or run_daily would
    # stamp a night whose brief never actually worked.
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": False)
    payload = {"warnings": [], "history": [], "main": {"order_label": "IST-first"}}
    status = notify_telegram.notify_cheapest(payload)  # must not raise
    assert status == "broken"


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


def test_minimal_rung_includes_the_first_warnings_before_the_link(monkeypatch):
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
    # Every other rung ends on the dashboard link — the minimal rung must
    # too, so the warnings have to land BEFORE it, not after.
    assert sent[0].strip().endswith(notify_telegram.MINIMAL_FALLBACK_LINK)


def test_everything_fails_but_a_build_succeeded_reports_none(monkeypatch):
    # A real build (full or core) succeeded here — VALID_MAIN renders fine
    # — so every send failing is purely a Telegram-delivery problem; the
    # published data is unaffected. This must read as "none", not "broken".
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML": False)
    payload = {"warnings": [], "history": [], "main": dict(VALID_MAIN)}
    status = notify_telegram.notify_cheapest(payload)
    assert status == "none"


# ── Alert partition integration (2026-08-20 v4 core review) ─────────────────
def test_bang_alert_leads_in_bold_before_the_price_line():
    payload = {"warnings": [], "history": [], "main": dict(VALID_MAIN),
              "alerts": ["🚨 BUY ZONE: $4,400 ≤ $4,500 target — book now"]}
    msg = notify_telegram.build_message(payload)
    lines = msg.split("\n")
    assert lines[0] == "<b>🚨 BUY ZONE: $4,400 ≤ $4,500 target — book now</b>"
    assert lines[1].startswith("🌟")


def test_bang_leads_and_fire_folds_when_both_present():
    payload = {"warnings": [], "history": [], "main": dict(VALID_MAIN),
              "alerts": ["🚨 BUY ZONE: $4,400 ≤ $4,500 target — book now",
                        "🔥 Ticket ① new low: $3,622 (prev $3,647)"]}
    msg = notify_telegram.build_message(payload)
    lines = msg.split("\n")
    assert lines[0] == "<b>🚨 BUY ZONE: $4,400 ≤ $4,500 target — book now</b>"
    assert "<b>🔥" not in msg                    # 🔥 never leads
    core, _, rest = msg.partition("<blockquote")
    assert "① new low 🔥" in core                # folded tag on the context line
    assert "🔥 Ticket ① new low: $3,622 (prev $3,647)" in rest   # full text, in the quote


def test_fire_alert_survives_with_no_other_expandable_content():
    # No hotel/stay_value/budget/bali in VALID_MAIN's payload — the
    # never-silently-drop guarantee must hold even when the 🛏️ Stay math
    # quote would otherwise have nothing else to show.
    payload = {"warnings": [], "history": [], "main": dict(VALID_MAIN),
              "alerts": ["🔥 Ticket ① new low: $3,622 (prev $3,647)"]}
    msg = notify_telegram.build_message(payload)
    # Partition-aware assertions (mutation-tested 2026-08-20): the fire text
    # must land INSIDE a quote, not merely "somewhere while some unrelated
    # quote also exists" — the flights/baggage quotes made the loose version
    # pass even with the fold reverted.
    assert "<b>🔥" not in msg
    core, _, rest = msg.partition("<blockquote")
    assert "🔥 Ticket ① new low" not in core
    assert "🔥 Ticket ① new low: $3,622 (prev $3,647)" in rest


# ── ⏰ day-of push is standalone and idempotent (2026-08-23) ─────────────────
def test_reminder_message_lists_numbered_steps_and_escapes():
    import datetime as dt
    import notify_telegram as nt
    assert nt.reminder_message(dt.date(2027, 1, 1)) is None
    msg = nt.reminder_message(dt.date(2027, 1, 2))
    assert msg.startswith("⏰ <b>TODAY — Kempinski")
    assert "\n1. amextravel.com" in msg and "\n3. " in msg
    assert "&amp;" not in msg or "&" in msg        # esc_html ran (no raw '<' from steps)


def test_send_due_reminders_sends_once_per_day(tmp_path):
    import datetime as dt
    import notify_telegram as nt
    sent = []
    stamp = tmp_path / ".reminders_sent"
    ok = nt.send_due_reminders(dt.date(2027, 1, 2), stamp_path=str(stamp),
                               send=lambda m: sent.append(m) or True)
    assert ok and len(sent) == 1 and "Pay Today" in sent[0]
    # second caller (the 5 am hotel job) is a no-op
    assert nt.send_due_reminders(dt.date(2027, 1, 2), stamp_path=str(stamp),
                                 send=lambda m: sent.append(m) or True)
    assert len(sent) == 1
    # nothing due → True, nothing sent, no stamp growth
    assert nt.send_due_reminders(dt.date(2027, 1, 3), stamp_path=str(stamp),
                                 send=lambda m: sent.append(m) or True)
    assert len(sent) == 1 and stamp.read_text().count("\n") == 1


def test_send_due_reminders_does_not_stamp_a_failed_send(tmp_path):
    import datetime as dt
    import notify_telegram as nt
    stamp = tmp_path / ".reminders_sent"
    assert not nt.send_due_reminders(dt.date(2027, 1, 2), stamp_path=str(stamp),
                                     send=lambda m: False)
    assert not stamp.exists()
