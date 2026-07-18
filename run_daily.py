#!/usr/bin/env python3
"""
Daily runner: scrapes Google Flights for the three one-way legs
BOS→DAC, DAC→DPS, DPS→BOS (2 adults + 1 child), writes results to
Google Sheet, then sends the cheapest valid trip combo to Telegram.
Run via cron at 3am EST.
"""
import os
import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from scraper import scrape_all, scrape_openjaw_all, scrape_sg_tickets_all
from sheet_writer import write_to_sheet
from notify_telegram import notify_cheapest
from publish import publish

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
        p = f.get("price_total", "N/A")
        return p if isinstance(p, (int, float)) else float("inf")

    flights.sort(key=sort_key)

    openjaws = scrape_openjaw_all()
    sg_tickets = scrape_sg_tickets_all()   # Singapore-detour multi-city tickets

    # Self-check: any invariant violation rides along to Telegram + the site,
    # so data losses are loud instead of silent (see sanity.py).
    from combo import best_structures, best_singapore
    from sanity import self_check
    from publish import last_history_entry
    sg = best_singapore(flights, openjaws, sg_tickets)
    warnings = self_check(flights, openjaws, best_structures(flights, openjaws),
                          last_history_entry(), sg=sg, sg_tickets=sg_tickets)
    for w in warnings:
        print(f"SELF-CHECK WARNING: {w}")

    write_to_sheet(flights, tab_name="Google Flights")
    notify_cheapest(flights, openjaws, warnings, sg=sg)
    publish(flights, openjaws, warnings, sg_tickets=sg_tickets)
    mark_ran_today()
    print("=== Done ===")


if __name__ == "__main__":
    main()
