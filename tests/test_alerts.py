"""The buy-signal rule: BEFORE the book-by date price decides, AFTER it the
date decides. These tests pin that behavior + the change-diff."""
import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import alerts
from alerts import (headlines, price_context, countdown, changes_since, stage,
                    BUY_BELOW, WINDOW_OPENS, BOOK_BY)

JUL = datetime.date(2026, 7, 25)
SEP_5 = datetime.date(2026, 9, 5)
SEP_21 = datetime.date(2026, 9, 21)


def _entry(date, main, t1=None, t2=None, **kw):
    e = {"date": date, "main_total": main, "ticket1_total": t1,
         "ticket2_total": t2, "ticket1_airline": kw.get("t1_air", "Turkish Airlines"),
         "ist_nights": 2, "sg_nights": 2, "bali_nights": 5, "dhaka_days": 22,
         "home": "Feb 7", "best_detail": kw.get("detail", {})}
    e.update({k: v for k, v in kw.items() if k not in ("t1_air", "detail")})
    return e


HIST = [
    {"date": "2026-07-15", "best_total": 4763},                 # retired-trip era
    {"date": "2026-07-18", "combined_total": 4709},             # old key
    {"date": "2026-07-24", "combined_total": 4665},
]


def test_stages():
    assert stage(JUL) == "watch"
    assert stage(WINDOW_OPENS) == "window"
    assert stage(BOOK_BY) == "past"


def test_quiet_ordinary_day():
    e = _entry("2026-07-25", 4666, t1=3647)
    assert headlines(e, HIST + [e], JUL) == []


def test_new_all_time_low_fires():
    e = _entry("2026-07-25", 4600, t1=3647)
    lines = headlines(e, HIST + [e], JUL)
    assert any("🔥 New all-time low: $4,600" in l and "$4,665" in l for l in lines)


def test_retired_trip_prices_do_not_pollute_the_low():
    # 2026-07-15's $4,763 open-jaw was a DIFFERENT trip; the low must come
    # from the tracked-trip era only (min $4,665, not $4,763).
    e = _entry("2026-07-25", 4700, t1=3647)
    assert headlines(e, HIST + [e], JUL) == []          # 4700 > 4665: no alert


def test_buy_zone_fires_in_watch_stage_too():
    e = _entry("2026-07-25", BUY_BELOW - 1, t1=3647)
    lines = headlines(e, HIST + [e], JUL)
    assert any("BUY ZONE" in l for l in lines)


def test_ticket1_low_fires_even_when_trip_total_does_not():
    prev = _entry("2026-07-25", 4666, t1=3647)
    cur = _entry("2026-07-26", 4666, t1=3500)           # trip flat, ① dropped
    lines = headlines(cur, HIST + [prev, cur], JUL)
    assert any("Ticket ① new low: $3,500" in l for l in lines)


def test_past_book_by_leads_and_retires_the_price_threshold():
    e = _entry("2026-09-21", 4700, t1=3647)
    lines = headlines(e, HIST + [e], SEP_21)
    assert len(lines) == 1 and "PAST YOUR USUAL BOOKING WINDOW" in lines[0]
    assert "cheapest of" in lines[0]


def test_price_context_ranks_within_tracked_era():
    # 2026-07-15 has no main-trip value → 3 tracked days, not 4.
    e = _entry("2026-07-25", 4666)
    ctx = price_context(e, HIST + [e])
    assert "2nd-cheapest of 3 days" in ctx and "$1 above the low" in ctx


def test_price_context_at_the_low():
    e = _entry("2026-07-25", 4665)
    assert "matches the all-time low" in price_context(e, HIST + [e])


def test_countdown_by_stage():
    assert "days to your usual booking window" in countdown(JUL)
    assert "days left" in countdown(SEP_5)
    assert countdown(SEP_21) is None                    # 'past' leads instead


# ── changes_since ───────────────────────────────────────────────────────────
T2_ONE_TICKET = {"sg_ticket": {"airline": "US-Bangla Airlines",
                               "out_date": "January 30, 2027",
                               "ret_date": "February 1, 2027"}}
T2_TWO_TICKETS = {"legs": [
    {"airline": "US-Bangla Airlines", "depart": "January 29, 2027"},
    {"airline": "Jetstar", "depart": "February 1, 2027"}]}


def test_no_changes_on_identical_days():
    a = _entry("2026-07-25", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET)
    b = _entry("2026-07-26", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET)
    assert changes_since(a, b) == []


def test_composition_flip_flags_baggage():
    a = _entry("2026-07-25", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET)
    b = _entry("2026-07-26", 4666, t1=3647, t2=1019, detail=T2_TWO_TICKETS)
    out = changes_since(a, b)
    assert any("Ticket ② composition" in l and "1-ticket" in l and "2 one-ways" in l
               for l in out)
    assert any("🧳⚠️" in l for l in out)


def test_ticket1_airline_change_flags_baggage():
    a = _entry("2026-07-25", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET)
    b = _entry("2026-07-26", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET,
               t1_air="Air France")
    out = changes_since(a, b)
    assert any("Turkish Airlines → Air France" in l for l in out)
    assert any("🧳⚠️" in l for l in out)


def test_small_price_moves_stay_quiet_big_ones_do_not():
    a = _entry("2026-07-25", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET)
    small = _entry("2026-07-26", 4666, t1=3690, t2=1019, detail=T2_ONE_TICKET)
    big = _entry("2026-07-26", 4666, t1=3757, t2=1019, detail=T2_ONE_TICKET)
    assert changes_since(a, small) == []                # $43 < $50 threshold
    assert any("$3,647 → $3,757" in l for l in changes_since(a, big))


def test_nights_change_is_reported():
    a = _entry("2026-07-25", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET)
    b = dict(_entry("2026-07-26", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET),
             sg_nights=1)
    assert any("Singapore nights: 2 → 1" in l for l in changes_since(a, b))


def test_old_format_yesterday_is_skipped_gracefully():
    old = {"date": "2026-07-24", "combined_total": 4665}     # pre-rewrite entry
    cur = _entry("2026-07-25", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET)
    assert changes_since(old, cur) == []
    assert changes_since(None, cur) == []
