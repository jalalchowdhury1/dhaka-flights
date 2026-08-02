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


def should_stamp(payload: dict, notify_status: str) -> bool:
    """Only mark tonight as done when there's a trip AND the brief reached a
    rung that means the DATA was fine. "minimal" (build_message itself
    never rendered) and "broken" (same, plus even Telegram delivery failed)
    both mean a genuine payload/shape problem, the same "come back later"
    situation as a catastrophic no-trip night — neither may stamp. "none"
    is different: it means a real build succeeded but Telegram couldn't be
    reached, a delivery problem the published data doesn't share, so it
    still counts as done."""
    return bool(payload.get("main")) and notify_status not in ("minimal", "broken")


def _check(label, fn):
    """A check layer must never kill the run — a crash becomes a finding."""
    try:
        return fn()
    except Exception as e:                     # noqa: BLE001
        return [f"{label} crashed: {e}"]


def _fold_warnings(payload, findings, mark, log_prefix):
    for f in findings:
        print(f"{log_prefix}: {f}")
    if findings:
        payload["warnings"] = list(payload.get("warnings") or []) + \
            [f"{mark} {f}" for f in findings]


def main():
    if already_ran_today():
        print("=== Already ran today, skipping ===")
        return

    print("=== Daily flight search starting ===")

    from scraper import begin_run, DIAG as SCRAPER_DIAG
    begin_run()

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

    # ⏱ Deadline skips ride along as warnings — they also explain any
    # "no fares for leg×date" sanity warnings from the same night.
    warnings += [f"⏱ {s}" for s in SCRAPER_DIAG.get("deadline_skips", [])]

    # Build the payload BEFORE notifying, so Telegram and the dashboard quote
    # the same numbers, alternatives and baggage rules.
    payload = publish.build_today(flights, tickets1, warnings, sg_tickets,
                                  bali=bali)

    # 📐 Payload-shape check: the payload must match the shape the site
    # renders. Runs BEFORE the independent re-check below — when the payload
    # is structurally broken, verify.py crashes with a useless "unsupported
    # format string" message, so the shape diagnosis should lead and the
    # crash note should follow. Violations are warnings (they must reach
    # Telegram + the 🧪 line) — publishing is never blocked.
    def _run_shape_check():
        import schema_check
        return schema_check.validate(payload)
    shape_issues = _check("payload-shape check", _run_shape_check)
    _fold_warnings(payload, shape_issues, "📐", "PAYLOAD-SHAPE")

    # 🔎 Independent re-check (2026-08-01: "once done verify. Multiple times.
    # take different perspectives.") — recompute / arithmetic / contract.
    # Findings join the self-check block; a clean pass adds a footer line.
    def _run_verify():
        import verify
        return verify.verify_payload(payload, flights, tickets1, sg_tickets)
    issues = _check("re-check", _run_verify)
    _fold_warnings(payload, issues, "🔎", "VERIFY")
    if not issues:
        payload["verified"] = ("independent re-check ✓ (recompute · "
                               "arithmetic · trip contract)")

    write_to_sheet(
        multicity_as_rows(tickets1, "① BOS→IST→DAC + return")
        + multicity_as_rows(sg_tickets, "② Dhaka→BKK/SIN middle")
        + multicity_as_rows(bali_t1, "🌴① BOS→IST→DAC + DPS→BOS")
        + multicity_as_rows(bali_fwd + bali_rev, "🌴② Bali middle")
        + flights,
        tab_name="Google Flights")
    notify_status = notify_cheapest(payload)
    publish.write_payload(payload)

    # Cloud-redundant history: one appended row per day in the Google Sheet,
    # so the price history survives even if data.json/git is ever lost.
    try:
        from sheet_writer import append_history_row
        append_history_row(payload["history"][-1])
    except Exception as e:                     # noqa: BLE001 — never kill the run
        print(f"WARN: history-sheet append failed (run continues): {e}")

    if should_stamp(payload, notify_status):
        mark_ran_today()
    elif not payload["main"]:
        # Catastrophic day (fares but no priceable trip): DON'T stamp, so the
        # 2:00 / 4:00 retry slots automatically try again.
        print("NOT marking success — no trip was built; retry slots will re-run")
    else:
        # A trip was built, but the brief never got past the minimal static
        # fallback (build_message and send_message both failed) — same
        # "come back later" situation, so the retry slots get another shot.
        print("NOT marking success — tonight's brief never got past the "
              "minimal fallback; retry slots will re-run")
    print("=== Done ===")


if __name__ == "__main__":
    main()
