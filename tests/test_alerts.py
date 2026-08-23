"""The buy-signal rule: BEFORE the book-by date price decides, AFTER it the
date decides. These tests pin that behavior + the change-diff."""
import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import alerts
from alerts import (headlines, price_context, countdown, changes_since, stage,
                    BUY_BELOW, WINDOW_OPENS, BOOK_BY)

WATCH_DAY = datetime.date(2026, 8, 5)      # inside the new 2026-08-01 epoch
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
    {"date": "2026-07-15", "best_total": 4763},                 # open-jaw era
    {"date": "2026-07-24", "combined_total": 4300},             # Bali era — retired 2026-08-01
    {"date": "2026-08-02", "main_total": 4709},
    {"date": "2026-08-04", "main_total": 4665},
]


def test_stages():
    assert stage(WATCH_DAY) == "watch"
    assert stage(WINDOW_OPENS) == "window"
    assert stage(BOOK_BY) == "past"


def test_quiet_ordinary_day():
    # above the buy line, not a new low → nothing to say (relative to the
    # knob so a BUY_BELOW change does not silently turn this into a buy day)
    e = _entry("2026-08-05", BUY_BELOW + 166, t1=3647)
    assert headlines(e, HIST + [e], WATCH_DAY) == []


def test_new_all_time_low_fires():
    e = _entry("2026-08-05", 4600, t1=3647)
    lines = headlines(e, HIST + [e], WATCH_DAY)
    assert any("🔥 New all-time low: $4,600" in l and "$4,665" in l for l in lines)


def test_retired_trip_prices_do_not_pollute_the_low():
    # The Bali era's $4,300 (and the open-jaw era's $4,763) were DIFFERENT
    # trips; the low must come from the 2026-08-01+ era only. $4,400 beats
    # $4,665 → the alert fires; if the Bali $4,300 leaked in, it wouldn't.
    e = _entry("2026-08-05", 4400, t1=3647)
    lines = headlines(e, HIST + [e], WATCH_DAY)
    assert any("New all-time low: $4,400" in l and "$4,665" in l for l in lines)


def test_buy_zone_fires_in_watch_stage_too():
    e = _entry("2026-08-05", BUY_BELOW - 1, t1=3647)
    lines = headlines(e, HIST + [e], WATCH_DAY)
    assert any("BUY ZONE" in l for l in lines)


def test_ticket1_low_fires_even_when_trip_total_does_not():
    prev = _entry("2026-08-05", 4666, t1=3647)
    cur = _entry("2026-08-06", 4666, t1=3500)           # trip flat, ① dropped
    lines = headlines(cur, HIST + [prev, cur], WATCH_DAY)
    assert any("Ticket ① new low: $3,500" in l for l in lines)


def test_past_book_by_leads_and_retires_the_price_threshold():
    e = _entry("2026-09-21", 4700, t1=3647)
    lines = headlines(e, HIST + [e], SEP_21)
    assert len(lines) == 1 and "PAST YOUR USUAL BOOKING WINDOW" in lines[0]
    assert "cheapest of" in lines[0]


def test_price_context_ranks_within_tracked_era():
    # Only the two Aug entries + today count → 3 tracked days, not 5.
    # Compact form (2026-08-20 v4 brief redesign): single source for the
    # Telegram core AND the site's Tonight chip.
    e = _entry("2026-08-05", 4666)
    ctx = price_context(e, HIST + [e])
    assert ctx == "#2/3 · $1 over low"


def test_price_context_at_the_low():
    e = _entry("2026-08-05", 4665)
    assert price_context(e, HIST + [e]) == "#1/3 · at the low"


def test_countdown_by_stage():
    assert "days to your usual booking window" in countdown(WATCH_DAY)
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


def test_order_flip_leads_the_changes_and_flags_baggage():
    a = _entry("2026-08-05", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET,
               order="Singapore first")
    b = _entry("2026-08-06", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET,
               order="Bangkok first")
    out = changes_since(a, b)
    assert any("Cheaper order flipped: Singapore first → Bangkok first" in l
               for l in out)
    assert any("🧳⚠️" in l for l in out)


def test_old_format_yesterday_is_skipped_gracefully():
    old = {"date": "2026-07-24", "combined_total": 4665}     # pre-rewrite entry
    cur = _entry("2026-07-25", 4666, t1=3647, t2=1019, detail=T2_ONE_TICKET)
    assert changes_since(old, cur) == []
    assert changes_since(None, cur) == []


def test_sg_nights_change_is_tagged_when_hotel_aware():
    import alerts
    prev = {"ticket1_total": 3600, "sg_nights": 2}
    cur = {"ticket1_total": 3600, "sg_nights": 4, "sg_allin": 4997,
           "stay_mode": "steering"}
    out = alerts.changes_since(prev, cur)
    assert any("Singapore nights: 2 → 4 (hotel-aware pick)" in c for c in out)
    # advisory mode: sg_allin present but the pick was flight-only — NO tag
    cur_adv = {"ticket1_total": 3600, "sg_nights": 4, "sg_allin": 4997,
               "stay_mode": "advisory"}
    out2 = alerts.changes_since(prev, cur_adv)
    assert any(c == "Singapore nights: 2 → 4" for c in out2)
    assert not any("hotel-aware" in c for c in out2)
    cur_plain = {"ticket1_total": 3600, "sg_nights": 4}
    out3 = alerts.changes_since(prev, cur_plain)
    assert any(c == "Singapore nights: 2 → 4" for c in out3)
