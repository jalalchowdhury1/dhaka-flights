#!/usr/bin/env python3
"""
Daily runner: scrapes Google Flights for BOS→DAC and BOS→BKK,
writes results to Google Sheet, then sends cheapest prices to Telegram.
Run via cron at 3am EST.
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from scraper import scrape_all
from sheet_writer import write_to_sheet
from notify_telegram import notify_cheapest


def main():
    print("=== Daily flight search starting ===")

    flights = scrape_all()

    if not flights:
        from notify_telegram import send_message
        send_message("⚠️ Daily flight search ran but found no results. Google may have blocked the scraper.")
        return

    def sort_key(f):
        p = f.get("price_per_person", "N/A")
        return p if isinstance(p, (int, float)) else float("inf")

    flights.sort(key=sort_key)

    write_to_sheet(flights, tab_name="Google Flights")
    notify_cheapest(flights)
    print("=== Done ===")


if __name__ == "__main__":
    main()
