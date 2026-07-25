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


def test_history_row_maps_entry_fields_in_order():
    from sheet_writer import history_row, HISTORY_HEADERS
    e = {"date": "2026-07-25", "main_total": 4666, "combined_total": 4666,
         "ticket1_total": 3647, "ticket2_total": 1019,
         "ticket1_airline": "Turkish Airlines", "ticket2_airline": "US-Bangla Airlines",
         "ist_nights": 2, "dhaka_days": 23, "sg_nights": 2, "bali_nights": 5,
         "best_total": 4666, "best_structure": "Istanbul 2-night stopover + Singapore"}
    row = history_row(e)
    assert len(row) == len(HISTORY_HEADERS)
    assert row[0] == "2026-07-25"
    assert row[1] == 4666 and row[7] == 4666           # ⭐ column and Best $
    assert row[9] == 3647 and row[10] == 1019          # appended Ticket ① / ②
    assert row[11] == "Turkish Airlines"
    assert row[13] == "2/23/2/5"
    # missing keys degrade to "" not crash
    assert history_row({"date": "x"})[1] == ""


def test_history_row_reads_pre_rewrite_entries():
    from sheet_writer import history_row
    assert history_row({"date": "2026-07-24", "combined_total": 4665})[1] == 4665


def test_retired_columns_keep_their_positions():
    from sheet_writer import history_row, HISTORY_HEADERS
    # Columns 2-6 belonged to the trips retired 2026-07-25; they must stay in
    # place (blank) so the sheet's older rows keep their meaning.
    assert HISTORY_HEADERS[2:7] == ["Direct OJ + hop", "SIN only", "IST only",
                                    "TK 30h stopover", "3 one-ways"]
    assert history_row({"date": "d", "main_total": 1})[2:7] == ["", "", "", "", ""]


def test_multicity_rows_are_sheet_shaped():
    from sheet_writer import multicity_as_rows, build_rows
    t = {"out_date": "January 4, 2027", "out_arrive": "January 8, 2027",
         "airline": "Turkish Airlines", "stops": "Nonstop", "duration": "9 hr",
         "layovers": "none", "price_total": 3647, "link": "http://t"}
    rows = build_rows(multicity_as_rows([t], "① BOS→IST→DAC + DPS→BOS"))
    assert rows[1][0] == "① BOS→IST→DAC + DPS→BOS"
    assert rows[1][1] == "January 4, 2027" and rows[1][7] == 3647
    assert multicity_as_rows([], "x") == [] and multicity_as_rows(None, "x") == []
