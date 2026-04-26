# Flight Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrape Google Flights for BOS→DAC and BOS→BKK round trips (Jan 3–28, 3 adults) and write the cheapest results into a Google Sheet, including baggage info for a traveler with heavy luggage.

**Architecture:** A single-run Python script (`main.py`) orchestrates two modules: `scraper.py` drives a Playwright Chromium browser to Google Flights and extracts flight data, and `sheet_writer.py` authenticates via a service account and writes results to the user's Google Sheet. No server or scheduler — user runs it once and walks away.

**Tech Stack:** Python 3, Playwright (Python), gspread 5.x, Google Sheets API v4, service account auth

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scraper.py` | Create | Playwright browser automation, Google Flights scraping |
| `sheet_writer.py` | Create | gspread auth + write results to Google Sheet |
| `main.py` | Create | Orchestrator: calls scraper then sheet_writer |
| `tests/test_sheet_writer.py` | Create | Unit tests for sheet_writer data formatting |
| `tests/test_scraper.py` | Create | Unit tests for scraper result parsing helpers |
| `requirements.txt` | Create | Pin dependencies |

---

## Task 1: Install Dependencies

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1: Create requirements.txt**

```
playwright==1.44.0
gspread==5.6.0
```

- [ ] **Step 2: Install dependencies**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
pip3 install playwright==1.44.0 gspread==5.6.0
playwright install chromium
```

Expected output: `Downloading Chromium...` followed by `chromium` install success. No errors.

- [ ] **Step 3: Verify installs**

```bash
python3 -c "import playwright; import gspread; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git init
git add requirements.txt
git commit -m "chore: add requirements"
```

---

## Task 2: sheet_writer.py — Core Write Function

**Files:**
- Create: `sheet_writer.py`
- Create: `tests/test_sheet_writer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sheet_writer.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
python3 -m pytest tests/test_sheet_writer.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'sheet_writer'`

- [ ] **Step 3: Create sheet_writer.py**

```python
import os
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE"
SERVICE_ACCOUNT_PATH = os.path.expanduser("~/.config/mcp-google-sheets/service-account.json")
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

HEADERS = ["Route", "Depart", "Return", "Airline", "Stops", "Duration",
           "Price/Person (USD)", "Total x3 (USD)", "Baggage", "Link"]


def build_rows(flights: list[dict]) -> list[list]:
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


def write_to_sheet(flights: list[dict]) -> None:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    sheet.clear()
    rows = build_rows(flights)
    sheet.update("A1", rows)
    print(f"Wrote {len(flights)} flights to Google Sheet.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_sheet_writer.py -v
```

Expected: 3 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add sheet_writer.py tests/test_sheet_writer.py
git commit -m "feat: add sheet_writer with build_rows and write_to_sheet"
```

---

## Task 3: scraper.py — URL Builder and Result Parser

**Files:**
- Create: `scraper.py`
- Create: `tests/test_scraper.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scraper.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scraper import build_google_flights_url, parse_price

def test_build_url_bos_dac():
    url = build_google_flights_url("BOS", "DAC", "2027-01-03", "2027-01-28", adults=3)
    assert "BOS" in url
    assert "DAC" in url
    assert "2027-01-03" in url
    assert "2027-01-28" in url

def test_build_url_bos_bkk():
    url = build_google_flights_url("BOS", "BKK", "2027-01-03", "2027-01-28", adults=3)
    assert "BKK" in url

def test_parse_price_strips_dollar_sign():
    assert parse_price("$1,234") == 1234

def test_parse_price_handles_missing():
    assert parse_price("") == "N/A"

def test_parse_price_handles_already_int():
    assert parse_price("850") == 850
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_scraper.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'scraper'`

- [ ] **Step 3: Create scraper.py with URL builder and price parser**

```python
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

DEPART_DATE = "2027-01-03"
RETURN_DATE = "2027-01-28"
ADULTS = 3
MAX_RESULTS = 10


def build_google_flights_url(origin: str, dest: str, depart: str, return_date: str, adults: int) -> str:
    return (
        f"https://www.google.com/travel/flights/search?"
        f"tfs=CBwQAhoeEgoyMDI3LTAxLTAzagcIARIDQk9TcgcIARID{dest}GgcIARID{dest}agcIARIDeol7MHKMQH"
        f"&hl=en&curr=USD&adults={adults}"
        f"&q=Flights+from+{origin}+to+{dest}+on+{depart}+returning+{return_date}"
    )


def parse_price(raw: str) -> int | str:
    if not raw:
        return "N/A"
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else "N/A"


def _safe_text(el, selector: str, default: str = "N/A") -> str:
    try:
        node = el.query_selector(selector)
        return node.inner_text().strip() if node else default
    except Exception:
        return default


def scrape_route(origin: str, dest: str, page) -> list[dict]:
    url = (
        f"https://www.google.com/travel/flights?"
        f"hl=en&curr=USD"
        f"#flt={origin}.{dest}.{DEPART_DATE}*{dest}.{origin}.{RETURN_DATE}"
        f";c:USD;e:1;sd:1;t:f;tt:o;pax:{ADULTS}"
    )
    results = []
    try:
        page.goto(url, timeout=30000)
        # Wait for flight list items to appear
        page.wait_for_selector('[jsname="IWWDBc"]', timeout=20000)
        time.sleep(3)  # allow dynamic content to fully render
        cards = page.query_selector_all('[jsname="IWWDBc"]')[:MAX_RESULTS]
        for card in cards:
            airline = _safe_text(card, '[data-gs]') or _safe_text(card, '.sSHqwe')
            price_raw = _safe_text(card, '[data-gs] span[aria-label*="$"]') or _safe_text(card, 'span[aria-label*="USD"]')
            stops = _safe_text(card, '.VG3hNb') or _safe_text(card, '[jsname="Xn9bfb"]')
            duration = _safe_text(card, '.gvkrdb') or _safe_text(card, '[jsname="pIJ4ob"]')
            # Try to get baggage info by expanding the card
            baggage = "N/A"
            try:
                card.click()
                page.wait_for_selector('[jsname="TszEd"]', timeout=5000)
                bag_el = page.query_selector('[data-ved] [jsname="TszEd"]') or page.query_selector('[jsname="TszEd"]')
                if bag_el:
                    baggage = bag_el.inner_text().strip()
                # close the expanded card
                card.click()
                time.sleep(0.5)
            except Exception:
                pass

            price = parse_price(price_raw)
            results.append({
                "route": f"{origin}→{dest}",
                "depart": "Jan 3, 2027",
                "return_date": "Jan 28, 2027",
                "airline": airline,
                "stops": stops,
                "duration": duration,
                "price_per_person": price,
                "baggage": baggage,
                "link": url,
            })
    except PlaywrightTimeout:
        print(f"Timeout scraping {origin}→{dest}. Partial results: {len(results)}")
    except Exception as e:
        print(f"Error scraping {origin}→{dest}: {e}")
    return results


def scrape_all() -> list[dict]:
    all_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()
        print("Scraping BOS → DAC...")
        all_results += scrape_route("BOS", "DAC", page)
        print(f"  Found {len([r for r in all_results if 'DAC' in r['route']])} results")
        print("Scraping BOS → BKK...")
        all_results += scrape_route("BOS", "BKK", page)
        print(f"  Found {len([r for r in all_results if 'BKK' in r['route']])} results")
        browser.close()
    return all_results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_scraper.py -v
```

Expected: 5 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add scraper.py tests/test_scraper.py
git commit -m "feat: add scraper with URL builder, price parser, and Playwright scrape logic"
```

---

## Task 4: main.py — Orchestrator

**Files:**
- Create: `main.py`

- [ ] **Step 1: Create main.py**

```python
from scraper import scrape_all
from sheet_writer import write_to_sheet

def main():
    print("Starting flight search: BOS → DAC and BOS → BKK")
    print("Dates: Jan 3, 2027 → Jan 28, 2027 | 3 adults\n")
    
    flights = scrape_all()
    
    if not flights:
        print("No flights found. Google may have blocked the scraper.")
        print("Try running again — the browser will be visible so you can solve any CAPTCHA.")
        return

    # Sort by price per person (cheapest first), put N/A at end
    def sort_key(f):
        p = f.get("price_per_person", "N/A")
        return p if isinstance(p, (int, float)) else float("inf")

    flights.sort(key=sort_key)

    print(f"\nFound {len(flights)} total flights. Writing to Google Sheet...")
    write_to_sheet(flights)

    # Print terminal summary
    print("\n--- Top 5 Cheapest ---")
    for f in flights[:5]:
        p = f["price_per_person"]
        total = p * 3 if isinstance(p, (int, float)) else "N/A"
        print(f"  {f['route']} | {f['airline']} | {f['stops']} | "
              f"${p}/person | ${total} total | Baggage: {f['baggage']}")

    print("\nDone! Open your Google Sheet to see all results.")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run a smoke test**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
python3 -c "from main import main; print('main.py imports OK')"
```

Expected: `main.py imports OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add main orchestrator"
```

---

## Task 5: End-to-End Run and Sheet Verification

**Files:** None new — this is verification only.

- [ ] **Step 1: Run the full script**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
python3 main.py
```

Expected:
- Chromium browser opens visibly
- Navigates to Google Flights twice (BOS→DAC, BOS→BKK)
- Terminal prints found flight counts
- Terminal prints "Done! Open your Google Sheet..."

- [ ] **Step 2: Verify Google Sheet**

Open: `https://docs.google.com/spreadsheets/d/1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE`

Check:
- Row 1 = headers: `Route | Depart | Return | Airline | Stops | Duration | Price/Person (USD) | Total x3 (USD) | Baggage | Link`
- Rows 2+ have BOS→DAC and BOS→BKK flight data
- "Total x3 (USD)" = "Price/Person (USD)" × 3 for at least 2 rows
- "Baggage" column has values (even if some are "N/A")
- Sorted cheapest first

- [ ] **Step 3: If Google blocks the scraper (shows CAPTCHA)**

The browser is visible — manually solve the CAPTCHA in the open window. The script will continue automatically once the page loads.

If results are still empty after solving CAPTCHA, run:

```bash
python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    pg = b.new_page()
    pg.goto('https://www.google.com/travel/flights')
    input('Solve CAPTCHA if shown, then press Enter...')
    b.close()
"
```

Then re-run `python3 main.py`.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: flight search complete - BOS to DAC and BKK via Google Flights"
```

---

## Self-Review

**Spec coverage check:**
- [x] BOS→DAC search — `scrape_route("BOS", "DAC", page)` in Task 3
- [x] BOS→BKK search — `scrape_route("BOS", "BKK", page)` in Task 3
- [x] 3 adults — `ADULTS = 3` constant, used in URL
- [x] Jan 3–28 dates — `DEPART_DATE` / `RETURN_DATE` constants
- [x] Price per person — scraped, `price_per_person` field
- [x] Total ×3 — calculated in `build_rows`, tested in Task 2
- [x] Airline, stops, duration — scraped in `scrape_route`
- [x] Baggage info — card expansion attempt in `scrape_route`, falls back to "N/A"
- [x] Google Sheet write — `write_to_sheet` in Task 2
- [x] Sort cheapest first — `main.py` sorts by `price_per_person`
- [x] CAPTCHA handling — documented in Task 5, browser is headful
- [x] N/A fallback on missing data — `_safe_text` default + `parse_price` fallback

**Placeholder scan:** None found.

**Type consistency:** `scrape_all()` returns `list[dict]`, `write_to_sheet(flights: list[dict])` accepts same — consistent across Tasks 3, 4, 2.
