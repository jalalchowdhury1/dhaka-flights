import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sheet_writer import build_rows, HEADERS

# Column indices: Route=0, Depart=1, Return=2, Airline=3, Stops=4, Duration=5,
#                 Price/Person=6, Baggage=7, Link=8

def test_build_rows_returns_header_and_data():
    flights = [
        {
            "route": "BOS→DAC",
            "depart": "Jan 3, 2027",
            "return_date": "Jan 28, 2027",
            "airline": "Qatar Airways",
            "stops": "1 stop",
            "duration": "22h 15m",
            "price_per_person": 850,
            "baggage": "1 checked bag",
            "link": "https://flights.google.com/example",
        }
    ]
    rows = build_rows(flights)
    assert rows[0] == HEADERS
    assert rows[1][0] == "BOS→DAC"
    assert rows[1][6] == 850
    assert rows[1][7] == "1 checked bag"

def test_build_rows_missing_baggage_key_falls_back_to_na():
    flights = [
        {
            "route": "BOS→BKK",
            "depart": "Jan 3, 2027",
            "return_date": "Jan 28, 2027",
            "airline": "Thai Airways",
            "stops": "1 stop",
            "duration": "20h 00m",
            "price_per_person": 700,
            "link": "https://flights.google.com/example2",
        }
    ]
    rows = build_rows(flights)
    assert rows[1][7] == "N/A"

def test_build_rows_missing_price_falls_back_to_na():
    flights = [
        {
            "route": "BOS→DAC",
            "depart": "Jan 3, 2027",
            "return_date": "Jan 28, 2027",
            "airline": "Emirates",
            "stops": "1 stop",
            "duration": "19h 30m",
            "baggage": "1 bag",
            "link": "https://flights.google.com/example3",
        }
    ]
    rows = build_rows(flights)
    assert rows[1][6] == "N/A"

def test_build_rows_empty_flights_returns_only_headers():
    rows = build_rows([])
    assert len(rows) == 1
    assert rows[0] == HEADERS

def test_build_rows_link_is_hyperlink_formula():
    flights = [
        {
            "route": "BOS→DAC",
            "depart": "Jan 3, 2027",
            "return_date": "Jan 28, 2027",
            "airline": "Emirates",
            "stops": "1 stop",
            "duration": "19h 30m",
            "price_per_person": 900,
            "baggage": "N/A",
            "link": "https://flights.google.com/example4",
        }
    ]
    rows = build_rows(flights)
    assert rows[1][8].startswith("=HYPERLINK(")
    assert "View flights" in rows[1][8]

def test_build_rows_no_link_falls_back_to_na():
    flights = [
        {
            "route": "BOS→DAC",
            "depart": "Jan 3, 2027",
            "return_date": "Jan 28, 2027",
            "airline": "Emirates",
            "stops": "1 stop",
            "duration": "19h 30m",
            "price_per_person": 900,
            "baggage": "N/A",
        }
    ]
    rows = build_rows(flights)
    assert rows[1][8] == "N/A"
