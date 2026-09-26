"""Ticket ① price guard (2026-09-25): a degraded premium-only Google list
(BA $18,914 against a real $3,884) must never be published as the price."""
import datetime

import scraper
import combo


REAL_TFS = ("CBwQAhoeEgoyMDI3LTAxLTA0agcIARIDQk9TcgcIARIDSVNUGh4SCjIwMjctMDEtMDdqBwgBEgNJU1Ry"
            "BwgBEgNEQUMaHhIKMjAyNy0wMi0wNmoHCAESA1NJTnIHCAESA0JPU0ABQAFAAkgBcAGCAQsI____________"
            "AZgBAw")


def row(price, airline="Turkish Airlines", ret="SIN", t="8:00 PM"):
    return {"price_total": price, "airline": airline, "ret_city": ret, "out_depart_time": t,
            "stops": "Nonstop", "kind": "stopover2", "label": f"ret {ret}",
            "out_date": "January 4, 2027", "ret_date": "February 6, 2027"}


def test_search_url_matches_googles_own_url_byte_for_byte():
    url = scraper.ticket1_search_url(scraper.TICKET1_SIN_RETURN)
    assert f"tfs={REAL_TFS}&" in url
    assert "curr=USD" in url


def test_search_url_differs_per_return_city():
    assert (scraper.ticket1_search_url(scraper.TICKET1_SIN_RETURN)
            != scraper.ticket1_search_url(scraper.TICKET1_BKK_RETURN))


def test_baseline_is_median_and_skips_suspect_nights():
    h = [{"ticket1_total": 3885}] * 5 + [{"ticket1_total": 18914, "ticket1_suspect": "x"}]
    base = scraper._real_ticket1_baseline
    assert base(h) == 3885
    assert base([{"ticket1_total": 3885}]) is None      # too few nights
    assert base([{"ticket1_total": 100}] * 5) is None   # nonsense floor


def test_suspect_reason_cases():
    good = [row(3884), row(3681, "British Airways"), row(4100), row(4200)]
    assert scraper.ticket1_suspect_reason(good, 3885) == ""
    assert "degraded" in scraper.ticket1_suspect_reason([row(18914)] * 5, 3885)
    assert "only 2 fares" in scraper.ticket1_suspect_reason([row(3884), row(3900)], 3885)
    assert scraper.ticket1_suspect_reason([], 3885) == "no fares came back"
    # no baseline (fresh history): thinness still counts, price alone can't
    assert scraper.ticket1_suspect_reason([row(18914)] * 5, None) == ""


def test_merge_dedupes_and_sorts_cheapest_first():
    a = [row(18914, "British Airways"), row(21284, "Lufthansa")]
    b = [row(3884), row(18914, "British Airways")]
    m = scraper.merge_ticket1(a, b)
    assert [r["price_total"] for r in m] == [3884, 18914, 21284]


def test_guard_direct_read_fixes_a_degraded_list(monkeypatch):
    scraper.T1_PENDING.clear()
    monkeypatch.setattr(scraper, "_scrape_ticket1_direct",
                        lambda cfg: [row(3884), row(3681, "British Airways"), row(4000), row(4100)])
    out = scraper.guard_ticket1(scraper.TICKET1_SIN_RETURN,
                                [row(18914, "British Airways"), row(21284, "Lufthansa")], 3885)
    assert out[0]["price_total"] == 3681
    assert not scraper.T1_PENDING


def test_guard_queues_then_rescue_marks_suspect(monkeypatch):
    scraper.T1_PENDING.clear()
    monkeypatch.setattr(scraper, "_scrape_ticket1_direct", lambda cfg: [])
    bad = [row(18914, "British Airways"), row(21284, "Lufthansa")]
    out = scraper.guard_ticket1(scraper.TICKET1_SIN_RETURN, bad, 3885)
    assert "SIN" in scraper.T1_PENDING
    other = [row(3900, ret="BKK")] * 5
    final = scraper.rescue_tickets1(out + other, baseline=3885)
    sin = [r for r in final if r["ret_city"] == "SIN"]
    bkk = [r for r in final if r["ret_city"] == "BKK"]
    assert all(r.get("suspect") for r in sin)
    assert not any(r.get("suspect") for r in bkk)          # the healthy order is untouched
    assert not scraper.T1_PENDING


def test_rescue_late_read_clears_suspicion(monkeypatch):
    scraper.T1_PENDING.clear()
    scraper.T1_PENDING["SIN"] = (scraper.TICKET1_SIN_RETURN, "degraded")
    monkeypatch.setattr(scraper, "_scrape_ticket1_direct",
                        lambda cfg: [row(3884), row(3681), row(4000), row(4100)])
    final = scraper.rescue_tickets1([row(18914)], baseline=3885)
    assert min(r["price_total"] for r in final) == 3681
    assert not any(r.get("suspect") for r in final)


def test_healthy_night_never_touches_the_browser(monkeypatch):
    scraper.T1_PENDING.clear()
    def boom(cfg):
        raise AssertionError("direct read must not run on a healthy night")
    monkeypatch.setattr(scraper, "_scrape_ticket1_direct", boom)
    good = [row(3884), row(3681), row(4000), row(4100), row(4300)]
    assert scraper.guard_ticket1(scraper.TICKET1_SIN_RETURN, good, 3885) == good
    assert scraper.rescue_tickets1(good, baseline=3885) == good


def test_jev_engine_uses_the_same_guard():
    import scraper_jev
    assert scraper_jev.rescue_tickets1 is scraper.rescue_tickets1


def test_suspect_flag_reaches_the_options_table():
    r = row(18914, "British Airways")
    r["suspect"] = "degraded"
    opts = combo.ticket1_options([r, row(19000, "Lufthansa")], chosen=r)
    assert opts[0]["suspect"] == "degraded"
    assert "suspect" not in opts[1]


def test_run_daily_warns_and_reruns_once(monkeypatch, tmp_path):
    import run_daily
    monkeypatch.setattr(run_daily, "T1_RERUN_FILE", str(tmp_path / ".t1"))
    bad = row(18914)
    bad["suspect"] = "degraded list"
    w = run_daily.ticket1_suspect_warnings([bad, dict(bad), row(3900, ret="BKK")])
    assert len(w) == 1 and "SIN" in w[0]
    payload = {"main": {"openjaw": bad}}
    assert run_daily.ticket1_rerun_wanted(payload) is True       # midnight: skip the stamp
    assert run_daily.ticket1_rerun_wanted(payload) is False      # 2:00 re-run: stamp
    assert run_daily.ticket1_rerun_wanted({"main": {"openjaw": row(3884)}}) is False
