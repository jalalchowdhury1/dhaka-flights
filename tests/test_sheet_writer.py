import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sheet_writer import build_rows, HEADERS

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
    assert rows[1][7] == 2550  # 850 * 3
    assert rows[1][8] == "1 checked bag"

def test_build_rows_handles_missing_baggage():
    flights = [
        {
            "route": "BOS→BKK",
            "depart": "Jan 3, 2027",
            "return_date": "Jan 28, 2027",
            "airline": "Thai Airways",
            "stops": "1 stop",
            "duration": "20h 00m",
            "price_per_person": 700,
            "baggage": "N/A",
            "link": "https://flights.google.com/example2",
        }
    ]
    rows = build_rows(flights)
    assert rows[1][8] == "N/A"

def test_build_rows_total_is_price_times_three():
    flights = [
        {
            "route": "BOS→DAC",
            "depart": "Jan 3, 2027",
            "return_date": "Jan 28, 2027",
            "airline": "Emirates",
            "stops": "1 stop",
            "duration": "19h 30m",
            "price_per_person": 1200,
            "baggage": "2 checked bags",
            "link": "https://flights.google.com/example3",
        }
    ]
    rows = build_rows(flights)
    assert rows[1][7] == 3600
