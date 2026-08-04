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

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

# Own browser identity, never shared with the flight run (carmax-scraper does
# the same with BROWSE_SESSION=carmax). Must be set BEFORE scraper is imported.
os.environ.setdefault("BROWSE_SESSION", "hotels")
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
except Exception:                                # noqa: BLE001
    pass

import hotel_rates

PAYLOAD = os.path.join(REPO, "site", "data.json")


def start_session(scraper):
    """Prefer Browserbase. Its residential IPs mean the HOME ip is never spent
    on hotel scraping — which is what got Google to slow-walk us on 2026-08-03
    and is the one thing that can also degrade the midnight flight run. Local
    Chrome stays as the fallback so a missing key never means no rates."""
    scraper._run("browse stop")
    time.sleep(1)
    if os.environ.get("BROWSERBASE_API_KEY"):
        out = scraper._run("browse env remote")
        if '"mode":"remote"' in (out or ""):
            print("  browser: Browserbase remote (home IP not used)")
            return "remote"
        print(f"  WARN: Browserbase unavailable ({(out or '')[:120]}) — using local Chrome")
    else:
        print("  WARN: no BROWSERBASE_API_KEY — using local Chrome (home IP)")
    scraper._run("browse env local")
    return "local"


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

    import random
    import scraper
    scraped = {}
    try:
        mode = start_session(scraper)
        for i, e in enumerate(hotel_rates.SHORTLIST):
            win = windows.get(e["city"])
            if not win:
                scraped[e["key"]] = (None, f"no {e['city']} stay dates tonight")
                continue
            rate, note = hotel_rates.scrape_rate(e, win[0], win[1], scraper=scraper)
            print(f"  [{e['key']}] {'$' + str(rate) if rate else 'MISS'} — {note}")
            scraped[e["key"]] = (rate, note)
            if i < len(hotel_rates.SHORTLIST) - 1:
                # Jittered, not a metronome — a fixed cadence is itself a
                # bot signature, and 8 requests/night is already tiny.
                time.sleep(random.uniform(4, 11))
    finally:
        try:
            scraper.end_session()
        except Exception as e:                   # noqa: BLE001
            print(f"WARN: session cleanup failed: {e}")

    data = hotel_rates.build(payload, scraped=scraped)
    # Count what THIS run actually fetched. Counting rows whose checked-date is
    # today would also count a successful earlier run and hide a total failure.
    hit = sum(1 for v in scraped.values() if v and v[0])
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
