import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sheet_writer import build_rows, HEADERS

# Column indices: Leg=0, Depart=1, Arrive=2, Airline=3, Stops=4, Duration=5,
#                 Layovers=6, Price=7, Link=8

FLIGHT = {
    "route": "DAC→DPS",
    "depart": "February 1, 2027",
    "arrive": "February 2, 2027",
    "airline": "AirAsia",
    "stops": "1 stop",
    "duration": "11 hr 35 min",
    "layovers": "4 hr 25 min at Kuala Lumpur International Airport",
    "price_total": 1130,
    "link": "https://flights.google.com/example",
}


def test_build_rows_returns_header_and_data():
    rows = build_rows([FLIGHT])
    assert rows[0] == HEADERS
    assert rows[1][0] == "DAC→DPS"
    assert rows[1][2] == "February 2, 2027"
    assert rows[1][6].startswith("4 hr 25 min")
    assert rows[1][7] == 1130


def test_build_rows_missing_price_falls_back_to_na():
    f = {k: v for k, v in FLIGHT.items() if k != "price_total"}
    rows = build_rows([f])
    assert rows[1][7] == "N/A"


def test_build_rows_empty_flights_returns_only_headers():
    rows = build_rows([])
    assert len(rows) == 1
    assert rows[0] == HEADERS


def test_build_rows_link_is_hyperlink_formula():
    rows = build_rows([FLIGHT])
    assert rows[1][8].startswith("=HYPERLINK(")
    assert "View flights" in rows[1][8]


def test_build_rows_no_link_falls_back_to_na():
    f = {k: v for k, v in FLIGHT.items() if k != "link"}
    rows = build_rows([f])
    assert rows[1][8] == "N/A"
