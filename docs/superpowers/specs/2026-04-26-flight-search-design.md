# Flight Search Design: BOS → DAC / BKK

**Date:** 2026-04-26

## Context

Jalal and 2 others (3 adults total) travel from Boston (BOS) to Dhaka, Bangladesh (DAC) and/or Bangkok, Thailand (BKK) every year around the same window. This tool automates the search for cheapest round-trip flights departing Jan 3 and returning Jan 28, scraping Google Flights via Playwright and writing results to a shared Google Sheet for easy comparison.

Heavy luggage is a factor — baggage allowance info must be captured per result.

## Goals

- Search Google Flights for BOS→DAC and BOS→BKK (round trip, Jan 3–28, 3 adults)
- Capture: price per person, total price (×3), airline(s), number of stops, total duration, baggage info
- Write all results into Google Sheet ID `1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE`
- Run fully unattended once triggered

## Architecture

```
main.py
  └── scraper.py          # Playwright browser automation → Google Flights
  └── sheet_writer.py     # gspread → writes to Google Sheet
```

Single-run script. No server, no scheduler. User runs `python main.py` and walks away.

## Components

### scraper.py
- Uses Playwright (Python) in non-headless mode (visible browser, less bot detection)
- Navigates to Google Flights with pre-built URL for each route:
  - BOS → DAC, depart Jan 3, return Jan 28, 3 adults, round trip
  - BOS → BKK, same params
- Waits for flight results to render
- Scrapes top results (up to 10 per route): price, airline, stops, duration
- Expands each result to read baggage allowance where available
- Returns structured list of result dicts

### sheet_writer.py
- Authenticates via service account at `~/.config/mcp-google-sheets/service-account.json`
- Opens sheet `1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE`
- Writes header row + one row per flight result
- Columns: Route | Depart | Return | Airline | Stops | Duration | Price/Person | Total (×3) | Baggage | Link
- Clears existing data before writing (idempotent reruns)

### main.py
- Calls scraper for BOS→DAC, then BOS→BKK
- Passes combined results to sheet_writer
- Prints summary to terminal when done

## Data Model

| Field | Source |
|---|---|
| Route | BOS→DAC or BOS→BKK |
| Depart Date | Jan 3 2027 |
| Return Date | Jan 28 2027 |
| Airline | Scraped (may be "Multiple airlines") |
| Stops | Scraped (0, 1, 2+) |
| Duration | Scraped (e.g. "22h 15m") |
| Price/Person | Scraped USD |
| Total (×3) | Calculated |
| Baggage | Scraped (e.g. "1 carry-on, 1 checked bag") |
| Link | Google Flights URL for that result |

## Dependencies

- `playwright` (Python) — browser automation
- `gspread` — Google Sheets API (already installed)
- Service account: `claude-sheets@hoa-tracker-494016.iam.gserviceaccount.com`
- Sheet shared with service account (Editor access — confirmed done)

## Error Handling

- If Google Flights shows CAPTCHA or bot block: script prints warning, saves partial results
- If a field can't be scraped: writes "N/A" rather than crashing
- Retry up to 3× on element-not-found before skipping a result

## Verification

1. Run `pip install playwright && playwright install chromium`
2. Run `python main.py`
3. Chrome opens, navigates to Google Flights, scrapes results
4. Open Google Sheet — rows should be populated with flight data for both routes
5. Confirm Total (×3) = Price/Person × 3 for a few rows
