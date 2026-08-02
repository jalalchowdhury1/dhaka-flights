"""⏱ Wall-clock guard: a slow-walked night skips the skippable (Bali watch,
remaining one-way legs) instead of grinding for hours. Ticket ①/② never skip."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scraper


def _expire(monkeypatch):
    scraper.begin_run()
    monkeypatch.setattr(scraper, "_run_start",
                        time.monotonic() - (scraper.RUN_DEADLINE_MIN * 60 + 1))


def test_fresh_run_is_not_past_deadline():
    scraper.begin_run()
    assert not scraper._past_deadline()
    assert scraper.DIAG["deadline_skips"] == []


def test_expired_run_is_past_deadline(monkeypatch):
    _expire(monkeypatch)
    assert scraper._past_deadline()


def test_scrape_all_skips_remaining_legs_past_deadline(monkeypatch):
    _expire(monkeypatch)
    called = []
    monkeypatch.setattr(scraper, "scrape_route",
                        lambda o, d, dep: called.append((o, d, dep)) or [])
    out = scraper.scrape_all()
    assert out == []
    assert called == []                       # nothing scraped at all
    assert any("one-way" in s for s in scraper.DIAG["deadline_skips"])


def test_scrape_bali_watch_skips_past_deadline(monkeypatch):
    _expire(monkeypatch)
    monkeypatch.setattr(scraper, "_scrape_multicity",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not scrape past deadline")))
    t1, fwd, rev = scraper.scrape_bali_watch()
    assert (t1, fwd, rev) == ([], [], [])
    assert any("Bali" in s for s in scraper.DIAG["deadline_skips"])


def test_begin_run_resets_state(monkeypatch):
    _expire(monkeypatch)
    scraper.DIAG["deadline_skips"].append("stale")
    scraper.begin_run()
    assert not scraper._past_deadline()
    assert scraper.DIAG["deadline_skips"] == []
