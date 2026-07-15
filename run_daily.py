#!/usr/bin/env python3
"""
Daily runner: scrapes Google Flights for BOS→DAC and BOS→BKK,
writes results to Google Sheet, then sends cheapest prices to Telegram.
Run via cron at 3am EST.
"""
import os
import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from scraper import scrape_all
from sheet_writer import write_to_sheet
from notify_telegram import notify_cheapest

STAMP_FILE = os.path.join(os.path.dirname(__file__), ".last_run_date")


def already_ran_today():
    today = datetime.date.today().isoformat()
    try:
        with open(STAMP_FILE) as f:
            return f.read().strip() == today
    except FileNotFoundError:
        return False


def mark_ran_today():
    with open(STAMP_FILE, "w") as f:
        f.write(datetime.date.today().isoformat())


def main():
    if already_ran_today():
        print("=== Already ran today, skipping ===")
        return

    print("=== Daily flight search starting ===")

    flights = scrape_all()

    if not flights:
        from notify_telegram import send_message
        from scraper import DIAG
        if DIAG["timeouts"] or DIAG["blank_pages"] or DIAG["aborted_early"]:
            send_message(
                "⚠️ Daily flight search failed: the LOCAL browser automation broke "
                f"(browse timeouts: {DIAG['timeouts']}, blank pages: {DIAG['blank_pages']}"
                f"{', aborted early' if DIAG['aborted_early'] else ''}) — not a Google block. "
                "Check cron.log and debug_last_zero.txt."
            )
        else:
            send_message(
                "⚠️ Daily flight search ran but parsed 0 flights on every search. "
                "Pages loaded normally, so Google may have changed its results page "
                "or blocked the scraper. Check debug_last_zero.txt for the last page tree."
            )
        return

    def sort_key(f):
        p = f.get("price_per_person", "N/A")
        return p if isinstance(p, (int, float)) else float("inf")

    flights.sort(key=sort_key)

    write_to_sheet(flights, tab_name="Google Flights")
    notify_cheapest(flights)
    mark_ran_today()
    print("=== Done ===")


if __name__ == "__main__":
    main()
