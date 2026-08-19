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
import calendar
import datetime
import json
import os
import random
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


# Browserbase's free plan allows 60 browser-minutes a CALENDAR month; the
# counter resets on the 1st. Verified 2026-08-16 by summing August's sessions
# (35.30 min completed + 25.61 min timed-out = 60.91) against the usage
# endpoint's reported 61 — it is a monthly figure, not a lifetime one.
FREE_TIER_MINUTES = 60

# MEASURED, not estimated: two full 8-property remote runs on 2026-08-16 billed
# 2.25 and 2.32 min. Tightening the inter-property jitter below was predicted to
# bring this to ~2.0; it did not — the ~10 s saved is inside the run-to-run
# variance of Google's page loads. Do not re-assert that without new numbers.
#
# Set ABOVE the observed max on purpose. The two errors are not symmetric:
# overestimating costs a few needless local nights, while underestimating dries
# the quota out mid-month — the exact failure this pacing exists to prevent.
# Re-derive from `GET /v1/projects/{id}/usage` after a full month of real runs
# (n=2 is thin), or whenever the shortlist changes length.
EST_RUN_MINUTES = 2.35

# Delay between properties, per mode. The SAME pause is expensive-and-pointless
# on one and free-and-valuable on the other, so it must not be one number:
#   remote — every second is BILLED, and 8 requests from a rotating residential
#            IP is not a shape Google throttles. Keep it tight.
#   local  — seconds are free, and this is the home IP the midnight flight run
#            depends on. Keep the original generous spacing (2026-08-03: Google
#            slow-walked this IP after ~10 rapid hotel searches).
JITTER = {"remote": (1, 3), "local": (4, 11)}


def should_conserve(used, cap, today=None, rng=random):
    """True when tonight should run on local Chrome to make the quota last.

    Demand (~30 nights x EST_RUN_MINUTES) slightly exceeds the 60-min free
    tier, so a handful of nights each month cannot be remote. WHICH nights
    matters more than how many: letting the quota simply run dry puts every
    local night in one consecutive block at month-end, and a multi-night burst
    of hotel searches from one IP is exactly the shape that got slow-walked on
    2026-08-03. A single isolated night is not.

    So the choice is RANDOM, weighted by how far behind pace we are. It also
    self-corrects: a local night spends no quota, which puts the next night
    back ahead of pace and returns it to Browserbase. No cliff, and there is
    always reserve left for a retry."""
    if used is None or cap is None:
        return False                     # unknown quota: try remote, the
                                         # 402 fallback is the real backstop
    today = today or datetime.date.today()
    nights_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    minutes_left = max(0.0, cap - used)
    if minutes_left < EST_RUN_MINUTES:
        return True                      # cannot afford even tonight
    need = nights_left * EST_RUN_MINUTES
    if minutes_left >= need:
        return False                     # comfortably ahead of pace
    shortfall_nights = (need - minutes_left) / EST_RUN_MINUTES
    return rng.random() < shortfall_nights / nights_left


def browserbase_usage(timeout=10):
    """(minutes_used_this_month, cap) for the key in the environment.

    Costs ZERO browser minutes — it is a plain REST call. Reading this BEFORE
    opening a session is what turns "eight identical mystery failures" into
    one honest line, and it is cheap enough to do every night."""
    key = os.environ.get("BROWSERBASE_API_KEY")
    if not key:
        return None, None
    import urllib.request

    def _get(path):
        req = urllib.request.Request(f"https://api.browserbase.com/v1{path}",
                                     headers={"X-BB-API-Key": key})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    try:
        pid = _get("/projects")[0]["id"]
        used = _get(f"/projects/{pid}/usage").get("browserMinutes")
        return (int(used) if used is not None else None), FREE_TIER_MINUTES
    except Exception as e:                           # noqa: BLE001
        print(f"  WARN: could not read Browserbase usage ({e})")
        return None, None


def start_session(scraper):
    """Prefer Browserbase. Its residential IPs mean the HOME ip is never spent
    on hotel scraping — which is what got Google to slow-walk us on 2026-08-03
    and is the one thing that can also degrade the midnight flight run.

    Local Chrome is the fallback, and it must cover BOTH ways the key can fail:
    missing, and out of quota. Only the first was handled until 2026-08-16, so
    when the free tier ran dry on 08-11 the fallback never fired and five
    nights published nothing while reporting a Google block."""
    # `browse stop --force`, NOT `browse stop`. The daemon caches
    # BROWSERBASE_API_KEY from the environment it was STARTED with and never
    # re-reads it; plain `browse stop` leaves that daemon alive, and the
    # following `browse env remote` cheerfully answers {"restarted":true}
    # while still holding the old key. Proved 2026-08-16: a daemon started
    # with a bogus key returned 401 for every later command even with a valid
    # key exported. This is why swapping the key in .env appeared to do
    # nothing — the 5 AM run's daemon was still up with the exhausted one.
    scraper._run("browse stop --force")
    time.sleep(2)
    if os.environ.get("BROWSERBASE_API_KEY"):
        used, cap = browserbase_usage()
        if used is not None:
            print(f"  Browserbase: {used}/{cap} min used this month")
        if used is not None and used >= cap:
            print("  Browserbase quota exhausted — falling back to local Chrome")
        elif should_conserve(used, cap):
            # Deliberate, not a failure: see should_conserve.
            print("  pacing: tonight runs on local Chrome so the month's "
                  "quota lasts (spreads local nights instead of clumping "
                  "them at month-end)")
        else:
            out = scraper._run("browse env remote")
            if '"mode":"remote"' in (out or ""):
                print("  browser: Browserbase remote (home IP not used)")
                return "remote"
            print(f"  WARN: Browserbase unavailable ({(out or '')[:120]}) — using local Chrome")
    else:
        print("  WARN: no BROWSERBASE_API_KEY — using local Chrome (home IP)")
    scraper._run("browse env local")
    return "local"


def to_local(scraper, why):
    """Mid-run demotion to local Chrome. The quota can die BETWEEN properties
    (it did on 2026-08-11, at property 7 of 8); finishing the night on the home
    IP beats publishing nothing."""
    print(f"  {why} — switching to local Chrome for the rest of the run")
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
            # An infra failure is not a Google failure: demote to local Chrome
            # and give this property a second, real chance on the way past.
            if rate is None and mode == "remote" and hotel_rates.is_infra_note(note):
                mode = to_local(scraper, note)
                rate, note = hotel_rates.scrape_rate(e, win[0], win[1], scraper=scraper)
            print(f"  [{e['key']}] {'$' + str(rate) if rate else 'MISS'} — {note}")
            scraped[e["key"]] = (rate, note)
            if i < len(hotel_rates.SHORTLIST) - 1:
                # Jittered, not a metronome — a fixed cadence is itself a bot
                # signature. Read `mode` EVERY iteration: to_local() can demote
                # mid-run, and the moment it does the spacing must widen again.
                time.sleep(random.uniform(*JITTER[mode]))
    finally:
        try:
            scraper.end_session()
        except Exception as e:                   # noqa: BLE001
            print(f"WARN: session cleanup failed: {e}")

    # 🏨 Morning movers alert (2026-08-19): captured BEFORE build() overwrites
    # the in-memory picture, so old and new can be diffed after write().
    # load_previous() returns {key: row}, not the file's {"rows": [...]}
    # shape that rate_moves()/build() use — reshape it here to match.
    prev = {"rows": list(hotel_rates.load_previous().values())}
    data = hotel_rates.build(payload, scraped=scraped)
    # Count what THIS run actually fetched. Counting rows whose checked-date is
    # today would also count a successful earlier run and hide a total failure.
    hit = sum(1 for v in scraped.values() if v and v[0])
    print(f"Refreshed {hit}/{len(data['rows'])} rates")
    for n in data["notes"]:
        print(f"  NOTE: {n}")

    hotel_rates.write(data)

    # 🏨 Morning movers alert (2026-08-19): major overnight changes land in
    # Telegram at ~5am, before wake-up — silent when nothing moved. The whole
    # path (including rate_moves itself) is shielded, so a bad/garbage rate
    # can never abort main() before the push.
    try:
        moves = hotel_rates.rate_moves(prev, data)
        if moves:
            from notify_telegram import send_message
            send_message(hotel_rates.moves_message(moves))
    except Exception as e:                       # noqa: BLE001
        print(f"WARN: telegram moves alert failed: {e}")

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
        # Say WHY, from what actually happened, never from a guess. The old
        # message hardcoded "Google likely throttling" and sent it whatever the
        # cause was; on 2026-08-11 the cause was an exhausted Browserbase quota
        # and that sentence sent five days of debugging at the wrong target.
        infra = [n for _, n in scraped.values()
                 if hotel_rates.is_infra_note(n)]
        if infra:
            why = infra[0].split(hotel_rates.INFRA_PREFIX, 1)[-1]
        else:
            notes = " ".join(str(n) for _, n in scraped.values()).lower()
            why = ("dates would not bind" if "did not bind" in notes else
                   "Google returned empty pages (throttling or a block)"
                   if "empty" in notes or "no page payload" in notes else
                   "see cron.log for the per-property notes")
        try:
            from notify_telegram import send_message
            send_message(f"⚠️ dhaka-flights: hotel-rate refresh got 0 live rates "
                         f"tonight — {why}. The Stays table is showing its last "
                         f"known figures with their check dates.")
        except Exception as e:                   # noqa: BLE001
            print(f"WARN: telegram warn failed: {e}")
    print("=== Done ===")


if __name__ == "__main__":
    main()
