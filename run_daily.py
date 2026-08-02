#!/usr/bin/env python3
"""
Daily runner for ONE trip (2026-07-25; Bangkok+Singapore since 2026-08-01):
BOS → Istanbul 2n → Dhaka → Bangkok 5n + Singapore 2n → BOS, 2 adults +
1 child — BOTH city orders priced nightly, the cheaper complete trip wins.

  Ticket ①  BOS→IST + IST→DAC + {SIN or BKK}→BOS, one multi-city ticket per order
  Ticket ②  DAC→{BKK→SIN or SIN→BKK}, one ticket or two one-ways (cheaper wins)

Scrapes both, prices the trip, self-checks, writes the Sheet, Telegrams the
result with per-leg baggage + same-date alternatives, and publishes data.json.
Runs from launchd at 12:00am with 2:00/4:00 retry slots.
"""
import os
import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from scraper import (scrape_all, scrape_tickets_all, scrape_sg_tickets_all,
                     scrape_bali_watch)
from sheet_writer import write_to_sheet, multicity_as_rows
from notify_telegram import notify_cheapest
import publish

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

    # Ticket ① goes FIRST: it's the one search nothing else can substitute for,
    # so it should run while the browser session is freshest.
    tickets1 = scrape_tickets_all()
    sg_tickets = scrape_sg_tickets_all()      # Ticket ② as one multi-city ticket
    flights = scrape_all()                    # Ticket ② as two one-ways
    # 🌴 comparison watch: the retired Bali trip, scraped LAST so a throttled
    # night hurts the benchmark before it hurts the product.
    bali_t1, bali_fwd, bali_rev = scrape_bali_watch()
    from scraper import end_session
    end_session()                             # one browser session per run

    if not (tickets1 or sg_tickets or flights):
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

    # Self-check: any invariant violation rides along to Telegram + the site,
    # so data losses are loud instead of silent (see sanity.py).
    from combo import main_trip, bali_watch_trip
    from sanity import self_check
    trip = main_trip(flights, tickets1, sg_tickets)
    bali = bali_watch_trip(flights, bali_t1, bali_fwd, bali_rev, tickets1)
    warnings = self_check(flights, tickets1, trip, publish.last_history_entry(),
                          sg_tickets=sg_tickets, bali=bali, bali_t1=bali_t1)
    for w in warnings:
        print(f"SELF-CHECK WARNING: {w}")

    # Build the payload BEFORE notifying, so Telegram and the dashboard quote
    # the same numbers, alternatives and baggage rules.
    payload = publish.build_today(flights, tickets1, warnings, sg_tickets,
                                  bali=bali)

    # 🔎 Independent re-check (2026-08-01: "once done verify. Multiple times.
    # take different perspectives.") — recompute / arithmetic / contract.
    # Findings join the self-check block; a clean pass adds a footer line.
    try:
        import verify
        issues = verify.verify_payload(payload, flights, tickets1, sg_tickets)
    except Exception as e:                     # noqa: BLE001 — never kill the run
        issues = [f"re-check crashed: {e}"]
    if issues:
        for p in issues:
            print(f"VERIFY: {p}")
        payload["warnings"] = list(payload.get("warnings") or []) +             [f"🔎 {p}" for p in issues]
    else:
        payload["verified"] = ("independent re-check ✓ (recompute · "
                               "arithmetic · trip contract)")

    write_to_sheet(
        multicity_as_rows(tickets1, "① BOS→IST→DAC + return")
        + multicity_as_rows(sg_tickets, "② Dhaka→BKK/SIN middle")
        + multicity_as_rows(bali_t1, "🌴① BOS→IST→DAC + DPS→BOS")
        + multicity_as_rows(bali_fwd + bali_rev, "🌴② Bali middle")
        + flights,
        tab_name="Google Flights")
    notify_cheapest(payload)
    publish.write_payload(payload)

    # Cloud-redundant history: one appended row per day in the Google Sheet,
    # so the price history survives even if data.json/git is ever lost.
    try:
        from sheet_writer import append_history_row
        append_history_row(payload["history"][-1])
    except Exception as e:                     # noqa: BLE001 — never kill the run
        print(f"WARN: history-sheet append failed (run continues): {e}")

    if payload["main"]:
        mark_ran_today()
    else:
        # Catastrophic day (fares but no priceable trip): DON'T stamp, so the
        # 2:00 / 4:00 retry slots automatically try again.
        print("NOT marking success — no trip was built; retry slots will re-run")
    print("=== Done ===")


if __name__ == "__main__":
    main()
