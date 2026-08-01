import os
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE"
SERVICE_ACCOUNT_PATH = os.path.expanduser("~/.config/mcp-google-sheets/service-account.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADERS = ["Leg", "Depart", "Arrive", "Airline", "Stops", "Duration",
           "Layovers", "Price 3-pax TOTAL (USD)", "Link"]


def build_rows(flights: list) -> list:
    rows = [HEADERS]
    for f in flights:
        rows.append([
            f.get("route", "N/A"),
            f.get("depart", "N/A"),
            f.get("arrive", "N/A"),
            f.get("airline", "N/A"),
            f.get("stops", "N/A"),
            f.get("duration", "N/A"),
            f.get("layovers", "N/A"),
            f.get("price_total", "N/A"),
            f'=HYPERLINK("{f.get("link","").replace(chr(34), "")}", "View flights")' if f.get("link") else "N/A",
        ])
    return rows


def _get_or_create_tab(spreadsheet, tab_name: str):
    """Return the worksheet with tab_name, creating it if it doesn't exist."""
    try:
        return spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=tab_name, rows=200, cols=10)


def multicity_as_rows(tickets: list, route_label: str) -> list:
    """Multi-city fares (Ticket ① / Ticket ②) reshaped like one-way flights so
    the daily Sheet tab shows the whole trip, not just its one-way legs.
    Rows that carry their own route (order-aware since 2026-08-01) keep it;
    route_label is the fallback."""
    out = []
    for t in tickets or []:
        out.append({
            "route": t.get("route") or route_label,
            "depart": t.get("out_date", "N/A"),
            "arrive": t.get("out_arrive", "N/A"),
            "airline": t.get("airline", "N/A"),
            "stops": t.get("stops", "N/A"),
            "duration": t.get("duration", "N/A"),
            "layovers": t.get("layovers", "N/A"),
            "price_total": t.get("price_total", "N/A"),
            "link": t.get("link", ""),
        })
    return out


# ── daily History tab (append-only, cloud-redundant copy of data.json history) ─
# APPEND-ONLY: never reorder or delete a column — the sheet is the third copy of
# the price history. Columns 3–7 belong to trips retired on 2026-07-25 (direct
# open-jaw, Singapore-only, Istanbul-only, TK 30h, three one-ways); they stay in
# place, holding their old values, and are written blank from now on. The nights
# column's last figure is Bali before 2026-08-01 and Bangkok after (same slot —
# both are the trip's 5-night Marriott block); "Order" appended 2026-08-01.
HISTORY_HEADERS = ["Date", "⭐ IST+SIN main", "Direct OJ + hop", "SIN only",
                   "IST only", "TK 30h stopover", "3 one-ways", "Best $",
                   "Best structure",
                   "Ticket ① $", "Ticket ② $", "① airline", "② airline",
                   "IST/DAC/SIN/5n-city", "💸 Budget $", "Order"]


def history_row(entry: dict) -> list:
    """Pure: one history entry → one sheet row (testable without gspread)."""
    e = entry or {}
    main = e.get("main_total", e.get("combined_total", ""))
    five_city = e.get("bkk_nights", e.get("bali_nights"))
    nights = "/".join(str(v if v is not None else "–")
                      for v in (e.get("ist_nights"), e.get("dhaka_days"),
                                e.get("sg_nights"), five_city))
    return [
        e.get("date", ""),
        main,
        e.get("openjaw_total", ""), e.get("singapore_total", ""),
        e.get("istanbul2_total", ""), e.get("stopover_total", ""),
        e.get("oneway_combo_total", ""),
        e.get("best_total", ""), e.get("best_structure", ""),
        e.get("ticket1_total", ""), e.get("ticket2_total", ""),
        e.get("ticket1_airline", ""), e.get("ticket2_airline", ""),
        nights if e.get("date") else "",
        e.get("budget_total") if e.get("budget_total") is not None else "",
        e.get("order", ""),
    ]


def append_history_row(entry: dict, tab_name: str = "History") -> None:
    """Append (or same-day update) one row per day. Never reorders columns —
    append-only, so the history is safe even if this code changes later."""
    if not entry or not entry.get("date"):
        print("WARN: no history entry to append")
        return
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    client = gspread.Client(auth=creds)
    sheet = _get_or_create_tab(client.open_by_key(SPREADSHEET_ID), tab_name)
    values = sheet.get_all_values()
    row = history_row(entry)
    # New columns were appended (2026-07-25) — widen the header in place. Only
    # ever extends to the right; existing columns keep their meaning and data.
    if values and len(values[0]) < len(HISTORY_HEADERS):
        sheet.update("A1", [HISTORY_HEADERS], value_input_option="USER_ENTERED")
    if not values:
        sheet.update("A1", [HISTORY_HEADERS, row], value_input_option="USER_ENTERED")
    elif values[-1] and values[-1][0] == entry["date"]:
        sheet.update(f"A{len(values)}", [row], value_input_option="USER_ENTERED")
    else:
        sheet.append_row(row, value_input_option="USER_ENTERED")
    print(f"History tab: recorded {entry['date']}.")


def write_to_sheet(flights: list, tab_name: str = "Google Flights") -> None:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    try:
        client = gspread.Client(auth=creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = _get_or_create_tab(spreadsheet, tab_name)
        sheet.clear()
        rows = build_rows(flights)
        sheet.update("A1", rows, value_input_option="USER_ENTERED")
        print(f"Wrote {len(flights)} flights to tab '{tab_name}'.")
    except FileNotFoundError:
        print(f"ERROR: Service account file not found at {SERVICE_ACCOUNT_PATH}")
        raise
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Spreadsheet not found. Check that the sheet is shared with the service account.")
        raise
    except Exception as e:
        print(f"ERROR writing to Google Sheet: {e}")
        raise
