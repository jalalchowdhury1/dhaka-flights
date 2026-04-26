import os
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE"
SERVICE_ACCOUNT_PATH = os.path.expanduser("~/.config/mcp-google-sheets/service-account.json")
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

HEADERS = ["Route", "Depart", "Return", "Airline", "Stops", "Duration",
           "Price/Person (USD)", "Total x3 (USD)", "Baggage", "Link"]


def build_rows(flights: list) -> list:
    rows = [HEADERS]
    for f in flights:
        price = f.get("price_per_person", 0)
        total = price * 3 if isinstance(price, (int, float)) else "N/A"
        rows.append([
            f.get("route", "N/A"),
            f.get("depart", "N/A"),
            f.get("return_date", "N/A"),
            f.get("airline", "N/A"),
            f.get("stops", "N/A"),
            f.get("duration", "N/A"),
            price,
            total,
            f.get("baggage", "N/A"),
            f.get("link", "N/A"),
        ])
    return rows


def write_to_sheet(flights: list) -> None:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    sheet.clear()
    rows = build_rows(flights)
    sheet.update("A1", rows)
    print(f"Wrote {len(flights)} flights to Google Sheet.")
