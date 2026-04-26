import os
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE"
SERVICE_ACCOUNT_PATH = os.path.expanduser("~/.config/mcp-google-sheets/service-account.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADERS = ["Route", "Depart", "Return", "Airline", "Stops", "Duration",
           "Price/Person (USD)", "Baggage", "Link"]


def build_rows(flights: list) -> list:
    rows = [HEADERS]
    for f in flights:
        price = f.get("price_per_person", "N/A")
        rows.append([
            f.get("route", "N/A"),
            f.get("depart", "N/A"),
            f.get("return_date", "N/A"),
            f.get("airline", "N/A"),
            f.get("stops", "N/A"),
            f.get("duration", "N/A"),
            price,
            f.get("baggage", "N/A"),
            f'=HYPERLINK("{f.get("link","").replace(chr(34), "")}", "View flights")' if f.get("link") else "N/A",
        ])
    return rows


def write_to_sheet(flights: list) -> None:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    try:
        client = gspread.Client(auth=creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Sheet1")
        sheet.clear()
        rows = build_rows(flights)
        # Write everything as USER_ENTERED so =HYPERLINK() formulas are evaluated
        sheet.update("A1", rows, value_input_option="USER_ENTERED")
        print(f"Wrote {len(flights)} flights to Google Sheet.")
    except FileNotFoundError:
        print(f"ERROR: Service account file not found at {SERVICE_ACCOUNT_PATH}")
        raise
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Spreadsheet not found. Check that the sheet is shared with the service account.")
        raise
    except Exception as e:
        print(f"ERROR writing to Google Sheet: {e}")
        raise
