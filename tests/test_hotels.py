"""🏨 The Marriott award stay riding with the trip (2026-08-01 evening)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hotels
import publish
from combo import main_trip, order_trip, main_trip_bali
from tests.test_main_trip import (TICKET1, TICKET1_SIN, FLIGHTS, SG_TICKETS,
                                  DAC_BKK, BKK_SIN, TICKET2_BKK_FIRST)
from tests.test_bali_watch import BALI_T1, BALI_SG


def test_sin_first_stay_runs_to_the_return():
    trip = main_trip(FLIGHTS, [TICKET1], SG_TICKETS)      # SIN-first, 1 ticket
    h = hotels.hotel_plan(trip)
    assert h["city"] == "Bangkok"
    assert "Athenee" in h["property"]
    assert (h["checkin"], h["checkout"]) == ("Feb 1", "Feb 6")
    assert h["nights"] == 5 and h["fifth_night_free"] and h["warn"] is None


def test_bkk_first_stay_sits_between_the_middle_legs():
    trip = order_trip([DAC_BKK, BKK_SIN], [TICKET1_SIN], [TICKET2_BKK_FIRST],
                      "BKK-first")                        # 2 one-ways middle
    h = hotels.hotel_plan(trip)
    assert (h["checkin"], h["checkout"]) == ("Jan 30", "Feb 4")
    assert h["nights"] == 5


def test_bali_benchmark_gets_the_laguna():
    b = main_trip_bali(FLIGHTS, [BALI_T1], [BALI_SG])
    h = hotels.hotel_plan(b)
    assert "Laguna" in h["property"]
    assert (h["checkin"], h["checkout"]) == ("Feb 1", "Feb 6")
    assert h["checked"] == "2026-07-27"


def test_off_shape_night_count_warns_about_the_free_night():
    trip = dict(main_trip(FLIGHTS, [TICKET1], SG_TICKETS), bkk_nights=4)
    h = hotels.hotel_plan(trip)
    assert h["fifth_night_free"] is False
    assert "5th-night-free" in h["warn"]


def test_payload_carries_hotel_for_main_and_bali():
    p = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                              warnings=[], sg_tickets=list(SG_TICKETS),
                              bali=main_trip_bali(FLIGHTS, [BALI_T1], [BALI_SG]))
    assert "Athenee" in p["hotel"]["property"]
    assert "Laguna" in p["bali"]["hotel"]["property"]
    assert publish.build_payload([], [], [], "2026-08-01")["hotel"] is None


def test_telegram_shows_the_hotel_line():
    from notify_telegram import build_message
    p = publish.build_payload(list(FLIGHTS), [TICKET1], [], "2026-08-01",
                              warnings=[], sg_tickets=list(SG_TICKETS))
    msg = build_message(p)
    assert "🏨" in msg and "Athenee" in msg and "5th night FREE" in msg
