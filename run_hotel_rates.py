#!/usr/bin/env python3
"""Nightly refresh of the IST/SIN card-play nightly rates.

Runs as its OWN launchd job, deliberately NOT inside run_daily.py: the flight
run is budgeted at 25 minutes (AGENTS.md §1 speed rules) and eight hotel
searches would push it past that and into the 35-minute overrun guard. This
job runs after every flight slot has finished.

It writes site/hotel_rates.json only — never data.json — so it can never race
publish.py for the same file. It pulls --rebase before pushing because the
flight run pushes to the same repo.

Failure policy, matching the rest of this project: a throttled or blocked night
keeps the previous rates with their ORIGINAL checked dates and records why, so
the site shows honestly stale numbers instead of confident wrong ones.
"""
import datetime
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hotel_rates

REPO = os.path.dirname(os.path.abspath(__file__))
PAYLOAD = os.path.join(REPO, "site", "data.json")


def _git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args),
                          capture_output=True, text=True)


def _load_payload():
    try:
        with open(PAYLOAD) as f:
            return json.load(f)
    except Exception as e:                       # noqa: BLE001
        print(f"WARN: could not read data.json ({e}); using fixed stay dates")
        return {}


def main():
    print("=== Hotel rate refresh starting ===")
    payload = _load_payload()
    windows = hotel_rates.stay_windows(payload)
    for city, w in windows.items():
        print(f"  {city} stay: {w[0]} -> {w[1]} ({w[2]}n)" if w else
              f"  {city} stay: UNKNOWN (falling back to previous rates)")

    import scraper
    scraped = {}
    try:
        scraper._ensure_session(fresh=True)
        for e in hotel_rates.SHORTLIST:
            win = windows.get(e["city"])
            if not win:
                scraped[e["key"]] = (None, f"no {e['city']} stay dates tonight")
                continue
            rate, note = hotel_rates.scrape_rate(e, win[0], win[1], scraper=scraper)
            print(f"  [{e['key']}] {'$' + str(rate) if rate else 'MISS'} — {note}")
            scraped[e["key"]] = (rate, note)
            time.sleep(3)          # be a polite guest; Google throttles hotels
    finally:
        try:
            scraper.end_session()
        except Exception as e:                   # noqa: BLE001
            print(f"WARN: session cleanup failed: {e}")

    data = hotel_rates.build(payload, scraped=scraped)
    hit = sum(1 for r in data["rows"] if r.get("checked") == data["updated"])
    print(f"Refreshed {hit}/{len(data['rows'])} rates")
    for n in data["notes"]:
        print(f"  NOTE: {n}")

    hotel_rates.write(data)

    _git("add", "site/hotel_rates.json")
    if not _git("diff", "--cached", "--quiet").returncode:
        print("No rate changes to commit.")
        return
    _git("commit", "-m", f"Hotel rates refreshed ({hit}/{len(data['rows'])} live)")
    _git("pull", "--rebase")                     # publish.py pushes here too
    for attempt in range(1, 4):
        if _git("push").returncode == 0:
            print("Pushed hotel_rates.json")
            break
        print(f"WARN: push failed (attempt {attempt}/3)")
        time.sleep(10)
    else:
        try:
            from notify_telegram import send_message
            send_message("⚠️ dhaka-flights: hotel-rate push failed 3× — the "
                         "Stays table will show older rates until it recovers.")
        except Exception as e:                   # noqa: BLE001
            print(f"WARN: telegram warn failed: {e}")

    # A whole night with zero live rates means the scrape path is broken, not
    # just noisy — say so once, rather than letting the table quietly age.
    if hit == 0:
        try:
            from notify_telegram import send_message
            send_message("⚠️ dhaka-flights: hotel-rate refresh got 0 live rates "
                         "tonight (Google likely throttling). The Stays table is "
                         "showing its last known figures with their check dates.")
        except Exception as e:                   # noqa: BLE001
            print(f"WARN: telegram warn failed: {e}")
    print("=== Done ===")


if __name__ == "__main__":
    main()
