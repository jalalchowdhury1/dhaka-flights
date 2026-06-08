# AGENTS.md — Dhaka Flights

> **This is the single source of truth for anyone (human or AI) touching this repo.**
> Read it fully before changing code or running anything. It replaces the old
> `docs/superpowers/plans/2026-04-26-flight-search.md` and
> `docs/superpowers/specs/2026-04-26-flight-search-design.md`, which were point-in-time
> design docs that have since drifted from the code and **have been deleted**. Where the
> old docs disagreed with the code, the code won and the corrections are recorded below in
> §Gotchas. If something here is wrong, fix *this* file.

---

## 1. What this is

A **one-shot, run-by-hand Python script** that scrapes Google Flights for round-trip
fares from **Boston (BOS)** to **Dhaka (DAC)** and **Bangkok (BKK)**, then writes the
results into a shared Google Sheet for easy comparison. It is the owner's annual family
trip planner (3 adults, heavy luggage — so baggage info matters).

- **Trigger:** the owner runs `python3 main.py` on their Mac and walks away. There is **no
  server, no scheduler, no cron, no CI, no `.github/`, no deploy target.** It runs once
  and exits.
- **Search matrix (current code):** 2 routes × 4 depart dates × 4 return dates = **32
  searches**.
  - Routes: `BOS→DAC`, `BOS→BKK`.
  - Depart: **January 3, 4, 5, 6, 2027** (`DEPART_DATES` in `scraper.py`).
  - Return: **January 25, 26, 27, 28, 2027** (`RETURN_DATES` in `scraper.py`).
  - Passengers: **3 adults** (`ADULTS = 3`).
  - Up to **10 flights** kept per search (`MAX_RESULTS = 10`).
- **Stack:** Python 3 (tested on 3.9). The scrape is driven through the **`browse` CLI**
  (the Browser skill's command-line tool), **not** Playwright directly — see the big
  gotcha in §4. Sheet writes go through **gspread** + a Google **service account**.
- **Output sheet:** Google Sheet ID
  `1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE`, worksheet **`Sheet1`**. The sheet is
  **cleared and fully rewritten** every run (idempotent).
- **GitHub:** `https://github.com/jalalchowdhury1/dhaka-flights` (note: the remote owner
  is `jalalchowdhury1`). There is also a `flyai` branch on origin; `main` is primary.

---

## 2. Architecture / data flow

```
python3 main.py
   │
   ├─▶ scraper.scrape_all()                      # loops the 32-search matrix
   │      └─ for each (route, depart, return):
   │           scraper.scrape_route(...)
   │              └─ shells out to the `browse` CLI via subprocess:
   │                   browse stop → env local → open Google Flights
   │                   → dismiss cookie consent → (if on Explore map, click "Flights")
   │                   → set 3 adults → type origin/destination → pick airport
   │                   → type depart + return dates → click Search → wait 10s
   │                   → browse snapshot (accessibility tree, JSON)
   │              └─ _parse_results(tree)         # regex-parse flight rows from the a11y tree
   │      └─ returns list[ flight dict ]
   │
   ├─▶ main(): sort flights by price_per_person (N/A sinks to the bottom), print top 5
   │
   └─▶ sheet_writer.write_to_sheet(flights)
          └─ Credentials.from_service_account_file(...)  # ~/.config/mcp-google-sheets/service-account.json
          └─ gspread.Client → open_by_key(SPREADSHEET_ID).worksheet("Sheet1")
          └─ sheet.clear(); sheet.update("A1", rows, value_input_option="USER_ENTERED")
```

Each flight is a dict with keys: `route`, `depart`, `return_date`, `airline`, `stops`,
`duration`, `price_per_person` (int USD or `"N/A"`), `baggage` (always `"N/A"` — see §5),
`link` (the Google Flights results URL for that search).

---

## 3. How to run

```bash
# from the repo root
pip3 install -r requirements.txt        # gspread (+ a stale playwright pin, see §4)
python3 main.py
```

Prerequisites the script assumes already exist on the machine:
- The **`browse` CLI** is on `PATH` and works in `env local` mode (a local Chromium-based
  browser). This is provided by the Browser skill / Browserbase tooling, **not** by
  `requirements.txt`. If `browse` is missing, every search returns 0 results and `main.py`
  prints "No flights found. Google may have blocked the scraper."
- A Google **service account JSON** at `~/.config/mcp-google-sheets/service-account.json`
  (path is `os.path.expanduser`-ed in `sheet_writer.py`). The account is
  `claude-sheets@hoa-tracker-494016.iam.gserviceaccount.com` (per the old design doc) and
  the target sheet must be **shared with that service account as Editor**. If the file is
  missing you get a `FileNotFoundError`; if the sheet isn't shared you get
  `SpreadsheetNotFound`.

### Tests
```bash
python3 -m pytest tests/ -v        # 11 tests, all passing as of this writing
```
Tests cover only the **pure helpers** — `build_google_flights_url`, `parse_price`
(in `tests/test_scraper.py`) and `build_rows` / `HEADERS` (in `tests/test_sheet_writer.py`).
The browser-driving and Google-Sheets-writing paths are **not** unit-tested (they need a
live browser and live Google auth). There is no mocking of `browse` or `gspread`.

### Secrets / config — where they live (never hardcode, never commit)
- **Service account key:** `~/.config/mcp-google-sheets/service-account.json` (outside the
  repo). Do not copy its contents into the repo — this is a public GitHub repo.
- **`SPREADSHEET_ID`** and **`SCOPES`** are constants at the top of `sheet_writer.py`.
  `SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]` (spreadsheets-only; see §4
  for the drift from the old doc).
- The search matrix, routes, `ADULTS`, and `MAX_RESULTS` are constants at the top of
  `scraper.py` — change those to retarget dates/routes/passengers.

---

## 4. Gotchas / hard rules (highest-value section — read before editing)

These are the non-obvious traps, including every correction made when reconciling the old
design/plan docs against the actual code. **The code is the source of truth.**

1. **The scraper uses the `browse` CLI, NOT Playwright — despite what the old docs and
   `requirements.txt` say.** `scraper.py` never imports `playwright`; it shells out to
   `browse open/click/type/press/snapshot/get url/stop` via `subprocess.run(..., shell=True)`
   and parses the resulting **accessibility-tree snapshot** (JSON with a `"tree"` field).
   - `requirements.txt` still pins `playwright==1.44.0` (and `gspread==5.6.0`). The
     `playwright` pin is **vestigial/unused** — kept from the original Playwright design.
     `gspread` IS used. Don't trust `requirements.txt` as the real runtime dependency list:
     the live runtime dependency is the external `browse` CLI, which pip can't install.
   - The old spec/plan describe `sync_playwright()`, `chromium.launch(headless=False)`,
     CSS/`jsname` selectors (`[jsname="IWWDBc"]`, `.gvkrdb`, etc.). **None of that exists
     in the code anymore.** Ignore those selectors.

2. **`build_google_flights_url()` is essentially dead code.** It builds a `#flt=...` hash
   URL but the live scrape flow (`scrape_route`) does **not** navigate to it — it opens the
   bare `https://www.google.com/travel/flights?hl=en&curr=USD&gl=us` page and drives the UI
   (typing origin/dest/dates, clicking Search). `build_google_flights_url` exists only to
   satisfy the unit tests in `tests/test_scraper.py`. (The old plan's `tfs=`/base64 URL form
   is also stale — the function actually uses the `#flt=` form. Either way it's unused at
   runtime.) Don't waste time "fixing" the URL builder to make scraping work.

3. **The "Total x3" column was REMOVED.** The old docs/plan describe a 10-column sheet with
   a calculated `Total x3 (USD)` column (and tests asserting `rows[1][7] == 2550`). The
   current `HEADERS` has **9 columns and no Total x3** (commit `77c365a`):
   `Route | Depart | Return | Airline | Stops | Duration | Price/Person (USD) | Baggage | Link`.
   `build_rows` does **no price×3 math**. The current tests reflect this (`rows[1][7]` is
   Baggage, `rows[1][8]` is Link). If you re-add a total column, update both `HEADERS` and
   all column-index assertions in `tests/test_sheet_writer.py`.

4. **The `Link` cell is a `=HYPERLINK()` formula, not a raw URL.** `build_rows` emits
   `=HYPERLINK("<url>", "View flights")` (with `"` stripped from the URL). That is why the
   write uses **`value_input_option="USER_ENTERED"`** — so Sheets evaluates the formula.
   If you switch to `RAW`, the cell shows the literal formula text instead of a link. A
   missing `link` falls back to `"N/A"`.

5. **`baggage` is always `"N/A"`.** The design called for scraping per-flight baggage
   allowance (the original motivation — heavy luggage). The current `browse`-CLI scraper
   does **not** extract baggage; `_parse_results` hardcodes `"baggage": "N/A"`. The column
   exists but is always empty. This is a known unfinished item, not a bug to "restore" from
   the Playwright code (that path no longer exists).

6. **Google Flights "Explore map" redirect.** Opening the flights URL sometimes lands on
   the Explore map instead of the search form. `scrape_route` detects this (URL contains
   `explore`, or the snapshot lacks "Where from") and clicks the **"Flights"** nav link (or
   re-opens the URL) before filling the form (commit `e583d02`). Keep this — without it the
   form fields aren't found and the search yields 0 results.

7. **Cookie-consent dialog must be dismissed first.** The scraper looks for an
   "Accept all" / "I agree" / "Accept" button and clicks it before doing anything else. EU/
   first-visit consent walls otherwise block the form.

8. **Origin selection does a click → Escape → click → type dance.** The "Where from"
   field is finicky; the code clicks it, presses Escape, clicks again, then types and picks
   **"Boston Logan"** specifically (falls back to Enter). Don't simplify this to a single
   click+type — it was made deliberately awkward to make the autocomplete behave.

9. **Destination airport picking is keyword-cascaded.** After typing the dest code,
   `scrape_route` tries refs matching `Hazrat Shahjalal` (DAC) → `Suvarnabhumi` (BKK) →
   `Dhaka` → `Bangkok` → the raw dest code, in that order, before falling back to Enter.

10. **All timing is `time.sleep()`-based, and the post-Search wait is 10s.** There are no
    real wait-for-selector conditions (the `browse` CLI snapshot is point-in-time). Google
    can be slow; if results come back empty intermittently, the sleeps (especially the 10s
    after Search and the `time.sleep(2)` after typing) are the first thing to lengthen. Each
    `browse` subprocess call has a **30s `timeout`** (`_run`).

11. **CAPTCHA / bot-block handling is manual.** Runs in a **visible** local browser
    (`browse env local`) on purpose, so the owner can solve any CAPTCHA by hand in the
    window; the script keeps going. If a route returns 0 results across the board, Google
    likely blocked it — re-run.

12. **gspread auth specifics (drifted from the old doc).** Actual code uses
    `gspread.Client(auth=Credentials.from_service_account_file(...))` and
    `.worksheet("Sheet1")` — **not** the old plan's `gspread.authorize(creds)` + `.sheet1`.
    `SCOPES` is **just** `["https://www.googleapis.com/auth/spreadsheets"]`; the old design
    doc's `spreadsheets.google.com/feeds` + `/auth/drive` scopes are stale. Don't widen the
    scopes back.

13. **`parse_price` returns an `int` or the string `"N/A"`** (never a float, never 0).
    Sorting in `main.py` treats non-numeric prices as `float("inf")` so N/A rows sink to the
    bottom. Price parsing strips everything non-digit, so `"$1,234"` → `1234`, `"817 US
    dollars"` → `817`.

14. **`_parse_results` keys off accessibility-tree text patterns.** A flight line must
    contain `"round trip total"` AND (`"flight with"` OR `"nonstop flight"`). Price is read
    from `"From N US dollars"` or `"From $N"`; airline from `"...flight with X."`; duration
    from `"Total duration X."`; stops from `"(nonstop|N stops?) flight"`. If Google changes
    this aria-label phrasing, parsing silently returns 0 results — that's the most likely
    future breakage point.

15. **No `.gitignore`.** If you ever build artifacts or dump a snapshot to disk, don't let
    them get committed. (There is currently nothing to ignore — pure source.)

---

## 5. Known issues / open items

- **Baggage is never scraped** (always `"N/A"`) — the original heavy-luggage requirement is
  unfulfilled in the `browse`-CLI rewrite (§4.5).
- **`requirements.txt` lists `playwright`, which is unused** (§4.1). Harmless but
  misleading; could be removed, but leaving it is fine.
- **`build_google_flights_url` is dead at runtime** (§4.2) — kept only for tests.
- **Hardcoded dates/routes.** Retargeting the next year's trip means editing the
  `DEPART_DATES` / `RETURN_DATES` / `routes` constants by hand. Years are 2027 in the
  current code.
- **Fragile selectors/timing** (§4.10, §4.14): this is a hand-driven UI scraper of a
  third-party site with no stable contract; expect it to need touch-ups when Google's
  Flights UI or aria labels change.

---

## 6. File / module map

| File | What it does |
|---|---|
| `main.py` | Entry point. `scrape_all()` → sort by `price_per_person` (N/A last) → `write_to_sheet()` → print top-5 summary. Bails with a "Google may have blocked" message if no flights. |
| `scraper.py` | The scraper. Constants (`DEPART_DATES`, `RETURN_DATES`, `ADULTS=3`, `MAX_RESULTS=10`). `build_google_flights_url` (unused at runtime), `parse_price`, `_run`/`_get_tree`/`_find_ref`/`_snap` (`browse` CLI helpers + a11y-tree parsing), `scrape_route` (drives one search), `_parse_results` (regex-extracts flights from the tree), `scrape_all` (the 32-search loop). |
| `sheet_writer.py` | `SPREADSHEET_ID`, `SERVICE_ACCOUNT_PATH`, `SCOPES`, `HEADERS` (9 cols, no Total x3). `build_rows` (dicts → 2D rows, Link as `=HYPERLINK`). `write_to_sheet` (service-account auth, clear, `update` with `USER_ENTERED`). |
| `tests/test_scraper.py` | Unit tests for `build_google_flights_url` + `parse_price`. |
| `tests/test_sheet_writer.py` | Unit tests for `build_rows` / `HEADERS` (current 9-column layout + HYPERLINK behavior). |
| `tests/__init__.py` | Empty package marker. |
| `requirements.txt` | `playwright==1.44.0` (unused), `gspread==5.6.0` (used). |
