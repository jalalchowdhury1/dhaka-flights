"""🌴 Bali comparison watch (2026-08-01 evening): the retired trip stays
scraped nightly so the Bangkok-vs-Bali price gap stays visible."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import publish
from combo import main_trip_bali
from notify_telegram import build_message
from sanity import self_check
from tests.test_main_trip import TICKET1, FLIGHTS, SG_TICKETS

BALI_T1 = {"kind": "stopover2", "label": "Istanbul 2-night stopover",
           "out_date": "January 4, 2027", "ret_date": "February 6, 2027",
           "out_arrive": "January 8, 2027", "price_total": 3500,
           "airline": "Turkish Airlines", "stops": "1 stop", "duration": "x",
           "layovers": "N/A", "link": "http://bt1", "ist_nights": 2,
           "desc": "BOS→IST Jan 4 · 2n Istanbul · IST→DAC Jan 7 + DPS→BOS Feb 6",
           "note": "n"}
BALI_SG = {"kind": "sg-ticket", "route": "DAC→SIN→DPS",
           "out_date": "January 30, 2027", "ret_date": "February 1, 2027",
           "out_arrive": "January 30, 2027", "price_total": 950,
           "airline": "US-Bangla Airlines", "stops": "Nonstop",
           "duration": "4 hr", "layovers": "none", "link": "http://bt2"}


def _bali():
    return main_trip_bali(FLIGHTS, [BALI_T1], [BALI_SG])


def test_bali_trip_still_builds_from_the_retired_paths():
    b = _bali()
    assert b is not None
    assert b["total"] == 3500 + 950
    assert b["sg_nights"] == 2 and b["bali_nights"] == 5


def test_payload_carries_bali_with_its_delta():
    p = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                              warnings=[], sg_tickets=list(SG_TICKETS),
                              bali=_bali())
    assert p["bali"]["total"] == 4450
    assert p["bali"]["delta_vs_main"] == 4450 - 4600
    assert p["history"][-1]["bali_total"] == 4450
    assert p["bali"]["baggage"], "the benchmark keeps its baggage rows too"


def test_payload_without_bali_stays_none():
    p = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                              warnings=[], sg_tickets=list(SG_TICKETS))
    assert p["bali"] is None
    assert p["history"][-1]["bali_total"] is None


def test_telegram_shows_the_benchmark_line():
    # v4 redesign (2026-08-20): the 🌴 Bali line moved out of the core into
    # the 🛏️ Stay math expandable — the core only ever shows conclusions.
    p = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                              warnings=[], sg_tickets=list(SG_TICKETS),
                              bali=_bali())
    msg = build_message(p)
    assert "🌴 Bali: $4,450 (−$150 vs Bangkok)" in msg      # 4450 vs 4600
    p2 = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                               warnings=[], sg_tickets=list(SG_TICKETS))
    assert "🌴 Bali" not in build_message(p2)


def test_missing_bali_watch_warns_once():
    w = self_check([], [], None, sg_tickets=[], bali=None, bali_t1=[])
    assert sum("Bali watch" in x for x in w) == 1


def test_history_row_appends_bali_column():
    from sheet_writer import history_row, HISTORY_HEADERS
    assert HISTORY_HEADERS[-2] == "🌴 Bali $"
    row = history_row({"date": "2026-08-01", "main_total": 4600,
                       "bali_total": 4450})
    assert row[-2] == 4450
    assert row[-1] == ""


# ── Both Bali orders (2026-08-01 late: "probe both Bali orders nightly") ─────
from combo import bali_watch_trip
from tests.test_main_trip import TICKET1_SIN

BALI_REV = {"kind": "sg-ticket", "route": "DAC→DPS→SIN",
            "out_date": "January 29, 2027", "ret_date": "February 4, 2027",
            "out_arrive": "January 30, 2027", "price_total": 1200,
            "airline": "Batik Air", "stops": "1 stop", "duration": "9 hr",
            "layovers": "KUL", "link": "http://brev"}


def test_reversed_bali_shares_the_bangkok_first_ticket1():
    b = bali_watch_trip([], [], [], [BALI_REV], [TICKET1_SIN])
    assert b is not None
    assert b["order"] == "bali-rev" and b["order_label"] == "Bali → Singapore"
    assert b["total"] == 3800 + 1200          # TICKET1_SIN + rev middle
    assert b["bali_nights"] == 5              # Jan 30 arrival → Feb 4 hop
    assert b["sg_nights"] == 2                # Feb 4 → Feb 6 return
    assert b["valid"] is True
    assert b["openjaw"]["ret_city"] == "SIN"


def test_cheaper_bali_order_wins_and_other_rides_along():
    b = bali_watch_trip(FLIGHTS, [BALI_T1], [BALI_SG], [BALI_REV], [TICKET1_SIN])
    # fwd = 3500+950 = 4450 · rev = 3800+1200 = 5000 → forward wins
    assert b["bali_order"] == "fwd" and b["total"] == 4450
    assert b["other_bali"]["order_label"] == "Bali → Singapore"
    assert b["other_bali"]["total"] == 5000 and b["other_bali"]["delta"] == 550
    # make the reversed order cheaper → it must win
    cheap_rev = dict(BALI_REV, price_total=500)
    b2 = bali_watch_trip(FLIGHTS, [BALI_T1], [BALI_SG], [cheap_rev], [TICKET1_SIN])
    assert b2["bali_order"] == "rev" and b2["total"] == 4300
    assert b2["other_bali"]["total"] == 4450


def test_benchmark_survives_a_missing_forward_ticket1():
    b = bali_watch_trip(FLIGHTS, [], [BALI_SG], [BALI_REV], [TICKET1_SIN])
    assert b is not None and b["bali_order"] == "rev"


def test_reversed_bali_baggage_and_hotel_follow_the_reversed_shape():
    import baggage, hotels
    b = bali_watch_trip([], [], [], [BALI_REV], [TICKET1_SIN])
    rows = baggage.annotate(b)
    assert [r["route"] for r in rows] == ["BOS→IST", "IST→DAC", "DAC→DPS",
                                          "DPS→SIN", "SIN→BOS"]
    h = hotels.hotel_plan(b)
    assert "Laguna" in h["property"]
    assert (h["checkin"], h["checkout"]) == ("Jan 30", "Feb 4")
    assert h["nights"] == 5


def test_core_only_fallback_keeps_the_answer_and_drops_the_reference():
    # A busy night must degrade to the one-screen core, never to silence.
    # v4 redesign (2026-08-20): the Bali comparison is arithmetic reference
    # material now — it lives only in the 🛏️ Stay math expandable, so a
    # core_only fallback (which drops ALL expandables) legitimately drops it
    # too. The answer that must survive is the trip's own total.
    p = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                              warnings=["x"], sg_tickets=list(SG_TICKETS),
                              bali=_bali())
    full = build_message(p)
    core = build_message(p, core_only=True)
    assert len(core) < len(full)
    assert "$4,600" in core
    assert "🌴 Bali" not in core and "🌴 Bali" in full
    assert "blockquote" not in core and "blockquote" in full
