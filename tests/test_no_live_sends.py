"""The suite can never post to the live Silent digest or Telegram.

2026-09-19: a pytest run in a shell carrying DIGEST_KEY posted the
test_notify_fallback fixture ($4,626 · SIN-first · ① ? $0) to the real digest
under id "flights"; the 06:50 card replayed it in place of the nightly brief.
Two layers now hold: tests/conftest.py (env stripped, digest_post stubbed) and
digest_post's own PYTEST_CURRENT_TEST refusal. Both are asserted here, with
urlopen booby-trapped so any leak fails loudly instead of silently posting.
"""
import os
import sys
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import notify_telegram  # noqa: E402
from conftest import REAL_DIGEST_POST  # noqa: E402


def _trap(monkeypatch):
    hits = []

    def boom(*a, **k):
        hits.append(a)
        raise AssertionError("a test reached the network")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    return hits


def test_conftest_strips_live_env_and_stubs_digest_post(monkeypatch):
    for v in ("DIGEST_URL", "DIGEST_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
        assert os.environ.get(v) is None
    hits = _trap(monkeypatch)
    assert notify_telegram.digest_post("flights", "<b>x</b>") is False
    assert hits == []


def test_real_digest_post_refuses_under_pytest_even_with_keys(monkeypatch):
    monkeypatch.setenv("DIGEST_URL", "https://example.invalid/api/digest")
    monkeypatch.setenv("DIGEST_KEY", "k")
    hits = _trap(monkeypatch)
    assert os.environ.get("PYTEST_CURRENT_TEST")
    assert REAL_DIGEST_POST("flights", "<b>x</b>") is False
    assert hits == []


def test_notify_cheapest_never_touches_the_network(monkeypatch):
    monkeypatch.setenv("DIGEST_URL", "https://example.invalid/api/digest")
    monkeypatch.setenv("DIGEST_KEY", "k")
    hits = _trap(monkeypatch)
    sent = []
    monkeypatch.setattr(notify_telegram, "send_message",
                        lambda text, parse_mode="HTML", silent=False: sent.append(text) or True)
    payload = {"warnings": [], "history": [],
               "main": {"total": 1, "order_label": "x", "valid": True,
                        "dhaka_days": 1, "home": "Feb 7", "ist_nights": 2,
                        "order": "BKK-first", "sg_nights": 2, "bkk_nights": 5}}
    assert notify_telegram.notify_cheapest(payload) == "full"
    assert len(sent) == 1
    assert hits == []
