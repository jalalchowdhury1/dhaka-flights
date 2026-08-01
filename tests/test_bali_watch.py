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
    p = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                              warnings=[], sg_tickets=list(SG_TICKETS),
                              bali=_bali())
    msg = build_message(p)
    assert "Original Bali trip" in msg
    assert "CHEAPER than Bangkok" in msg          # 4450 vs 4600
    p2 = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                               warnings=[], sg_tickets=list(SG_TICKETS))
    assert "Original Bali trip" not in build_message(p2)


def test_missing_bali_watch_warns_once():
    w = self_check([], [], None, sg_tickets=[], bali=None, bali_t1=[])
    assert sum("Bali watch" in x for x in w) == 1


def test_history_row_appends_bali_column():
    from sheet_writer import history_row, HISTORY_HEADERS
    assert HISTORY_HEADERS[-1] == "🌴 Bali $"
    row = history_row({"date": "2026-08-01", "main_total": 4600,
                       "bali_total": 4450})
    assert row[-1] == 4450
    assert history_row({"date": "x"})[-1] == ""
