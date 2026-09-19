"""No test may reach the real Silent digest or Telegram.

2026-09-19: a pytest run in a shell that had sourced ~/.config/secrets.env
(DIGEST_URL/DIGEST_KEY) posted test_notify_fallback's fake payload
($4,626 · SIN-first · ① ? $0) to the live digest under id "flights",
overwriting the real nightly brief; the 06:50 card replayed the fixture.
Tests stubbed send_message but never digest_post.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import notify_telegram  # noqa: E402

_LIVE_VARS = ("DIGEST_URL", "DIGEST_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID")
REAL_DIGEST_POST = notify_telegram.digest_post   # for test_no_live_sends only


@pytest.fixture(autouse=True)
def _no_live_sends(monkeypatch):
    for v in _LIVE_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(notify_telegram, "digest_post",
                        lambda *a, **k: False)
    monkeypatch.setattr(notify_telegram, "TELEGRAM_TOKEN", "")
    monkeypatch.setattr(notify_telegram, "TELEGRAM_CHAT_ID", "")
