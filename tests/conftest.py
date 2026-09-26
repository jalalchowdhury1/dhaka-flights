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
notify_telegram._real_digest_post = notify_telegram.digest_post   # for test_no_live_sends only


@pytest.fixture(autouse=True)
def _no_live_sends(monkeypatch):
    for v in _LIVE_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(notify_telegram, "digest_post",
                        lambda *a, **k: False)
    monkeypatch.setattr(notify_telegram, "TELEGRAM_TOKEN", "")
    monkeypatch.setattr(notify_telegram, "TELEGRAM_CHAT_ID", "")


@pytest.fixture(autouse=True)
def _no_live_browser(monkeypatch):
    """2026-09-25: the Ticket ① guard's direct-URL read drove the real browser
    from test_scraper's thin-list test. No test may open Google; tests that
    exercise the guard stub _scrape_ticket1_direct themselves. History reads
    are pinned too so a bad night in site/data.json can't flip a test."""
    import scraper
    if not hasattr(scraper, "_real_ticket1_baseline"):
        scraper._real_ticket1_baseline = scraper.ticket1_baseline   # for test_ticket1_guard
    monkeypatch.setattr(scraper, "_scrape_ticket1_direct", lambda cfg: [])
    monkeypatch.setattr(scraper, "ticket1_baseline", lambda history=None: 3885)
    scraper.T1_PENDING.clear()
