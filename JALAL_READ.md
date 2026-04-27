# Dhaka Flights — How To Guide

## Run a search right now

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
python3 run_daily.py
```

Chrome will open, search all date combos, update the Google Sheet, and send you a Telegram with the cheapest prices. Takes ~15-20 minutes.

---

## Stop the daily 3am job

```bash
launchctl unload ~/Library/LaunchAgents/com.jalal.dhaka-flights.plist
```

To turn it back on:

```bash
launchctl load ~/Library/LaunchAgents/com.jalal.dhaka-flights.plist
```

To check if it's currently active:

```bash
launchctl list | grep dhaka
```

---

## Change the travel dates

Open `scraper.py` and edit these 4 lines near the top:

```python
DEPART_DATES = ["January 3, 2027", "January 4, 2027", "January 5, 2027", "January 6, 2027"]
RETURN_DATES = ["January 25, 2027", "January 26, 2027", "January 27, 2027", "January 28, 2027"]
```

Just replace the dates with whatever you need. Add or remove dates from the lists freely — each combination will be searched automatically.

---

## Files at a glance

| File | What it does |
|---|---|
| `run_daily.py` | The main script — runs scraper, updates sheet, sends Telegram |
| `scraper.py` | Google Flights browser scraper (edit dates here) |
| `sheet_writer.py` | Writes results to Google Sheet |
| `notify_telegram.py` | Sends Telegram message |
| `main_flyai.py` | Backup: Fliggy/Alibaba scraper (no browser, instant) |
| `.env` | Your Telegram token and chat ID (never committed to GitHub) |

---

## Google Sheet

[Open Sheet](https://docs.google.com/spreadsheets/d/1d5UTYY0LcQO3xCWuNdAo70r-Z-HIyOdzR5tFgKOrvRE)

- **Google Flights tab** — results from the browser scraper
- **Fliggy (FlyAI) tab** — backup results from Alibaba's API (run manually with `python3 main_flyai.py`)
