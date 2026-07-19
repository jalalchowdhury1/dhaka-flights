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


# ── daily History tab (append-only, cloud-redundant copy of data.json history) ─
HISTORY_HEADERS = ["Date", "⭐ IST+SIN main", "Direct OJ + hop", "SIN only",
                   "IST only", "TK 30h stopover", "3 one-ways", "Best $", "Best structure"]


def history_row(entry: dict) -> list:
    """Pure: one history entry → one sheet row (testable without gspread)."""
    e = entry or {}
    return [
        e.get("date", ""),
        e.get("combined_total", ""), e.get("openjaw_total", ""),
        e.get("singapore_total", ""), e.get("istanbul2_total", ""),
        e.get("stopover_total", ""), e.get("oneway_combo_total", ""),
        e.get("best_total", ""), e.get("best_structure", ""),
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
