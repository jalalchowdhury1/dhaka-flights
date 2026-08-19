"""Write site/data.json (today's results + running price history) and push it,
so the Vercel dashboard — which fetches the file raw from GitHub — updates
without a redeploy. A publish failure must never kill the daily run."""
import datetime
import json
import os
import shutil
import subprocess
import time

import alerts
import baggage
import hotels
import stay_value
from combo import (budget_trip, main_trip, sin_night_flight_totals,
                   ticket1_options, ticket2_options)

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(REPO_DIR, "site", "data.json")

PUSH_BACKOFF_S = [10, 30]          # sleeps between attempts 1→2 and 2→3
# Derived, not duplicated: a future bump of attempts without extending the
# backoff list would IndexError inside write_payload's own outer except —
# silently swallowing the warning it was trying to send.
PUSH_ATTEMPTS = len(PUSH_BACKOFF_S) + 1


def _telegram_warn(msg: str) -> None:
    """Best-effort Telegram warning — publish must survive notify failures.
    send_message signals failure by returning False (not raising), so that
    has to be checked too — the network-down case is exactly the trigger
    that would otherwise make the warning vanish without a trace."""
    try:
        from notify_telegram import send_message
        if not send_message(msg):
            print("WARN: stale-dashboard warning did not reach Telegram")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: telegram warn failed too: {e}")


def _load_history() -> list:
    try:
        with open(DATA_FILE) as f:
            return json.load(f).get("history", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def last_history_entry() -> dict:
    """Most recent history entry (yesterday's, or today's on a same-day rerun)."""
    h = _load_history()
    return h[-1] if h else None


def _jsonable(obj):
    if isinstance(obj, datetime.datetime):
        return obj.strftime("%B %d, %Y")
    raise TypeError(f"not JSON-serializable: {type(obj)}")


def _with_baggage(options: list, ticket_type: str, route: str) -> list:
    for o in options:
        o["baggage"] = baggage.for_leg(o.get("airline", ""), ticket_type, route)
    return options


def build_payload(flights: list, openjaws: list, history: list, today: str,
                  warnings: list = None, sg_tickets: list = None,
                  bali: dict = None, stay_rates: dict = None) -> dict:
    """One trip, one payload (2026-07-25). The alternative trips — direct
    open-jaw, three one-ways, Istanbul-only, Singapore-only — are no longer
    scraped, tracked, or charted; `main` IS the product now.
    stay_rates (2026-08-19): parsed hotel_rates.json. When present and fresh,
    the 🛏️ stay-math hook steers the SIN night count all-in (flights + net
    hotel after credits, $225/extra-night knob); the block always rides as
    payload["stay_value"] and history gains sg_allin. None → exact pre-stay
    behavior (manual runs, tests)."""
    try:
        as_of = datetime.date.fromisoformat(today)
    except ValueError:
        as_of = datetime.date.today()
    incumbent_n = (history[-1] or {}).get("sg_nights") if history else None
    hook = (stay_value.hotel_hook(stay_rates, incumbent_n, today=as_of)
            if stay_rates is not None else None)
    main = main_trip(flights, openjaws, sg_tickets or [], hotel_cost=hook)
    if main:
        # Baggage rides inside the trip so history keeps the rules that applied
        # on the day, not just the price.
        main = dict(main,
                    baggage=baggage.annotate(main),
                    baggage_warnings=baggage.warnings(main),
                    baggage_checked=baggage.CHECKED)

    # 💸 companion: same trip with the min-2-SG-nights rule waived and Dhaka
    # dates free to shift — present only when strictly cheaper than main.
    budget = budget_trip(flights, sg_tickets or [], main)
    if budget:
        budget = dict(budget,
                      baggage=baggage.annotate(budget),
                      baggage_warnings=baggage.warnings(budget),
                      baggage_checked=baggage.CHECKED)

    # 🌴 comparison watch: the retired Bali trip rides along with its Δ so
    # "was dropping Bali worth it" stays answerable at a glance.
    if bali:
        bali = dict(bali,
                    baggage=baggage.annotate(bali),
                    baggage_warnings=baggage.warnings(bali),
                    baggage_checked=baggage.CHECKED,
                    hotel=hotels.hotel_plan(bali))
        if main:
            bali["delta_vs_main"] = bali["total"] - main["total"]

    # 🛏️ Stay math (2026-08-19): the per-night-count all-in table + what it
    # picked. A steering-mode mismatch with the trip is a wiring bug — it
    # rides to Telegram as a warning.
    stay = None
    if stay_rates is not None and main:
        totals = sin_night_flight_totals(flights, openjaws, sg_tickets or [],
                                         main["order"])
        stay = stay_value.build(stay_rates, totals, incumbent_n,
                                main.get("sg_nights"), today=as_of)
        if stay.get("warning"):
            warnings = list(warnings or []) + [f"🛏️ {stay['warning']}"]

    t1 = (main or {}).get("openjaw") or None
    t2 = (main or {}).get("sg_ticket") or None
    t1_total = t1.get("price_total") if t1 else None
    t2_total = (t2.get("price_total") if t2 else
                sum(f.get("price_total", 0) for f in (main or {}).get("legs", []))
                if main else None)

    entry = {
        "date": today,
        # main_total is the number that matters; combined_total is written too
        # so the 8 days of pre-2026-07-25 history and the Sheet's ⭐ column stay
        # one continuous series.
        "main_total": main["total"] if main else None,
        "combined_total": main["total"] if main else None,
        "ticket1_total": t1_total,
        "ticket2_total": t2_total if main else None,
        "ticket1_airline": t1.get("airline") if t1 else None,
        "ticket2_airline": (main or {}).get("sg_airlines"),
        "order": (main or {}).get("order_label"),
        "ist_nights": (main or {}).get("ist_nights"),
        "sg_nights": (main or {}).get("sg_nights"),
        "sg_allin": (stay or {}).get("trip_allin"),
        "bkk_nights": (main or {}).get("bkk_nights"),
        "other_order_total": ((main or {}).get("other_order") or {}).get("total"),
        "bali_total": bali["total"] if bali else None,
        "dhaka_days": (main or {}).get("dhaka_days"),
        "home": (main or {}).get("home"),
        "valid": main.get("valid") if main else None,
        "flag": (main or {}).get("flag"),
        "budget_total": budget["total"] if budget else None,
        # Kept for the Sheet's existing columns + the History tab's detail row.
        "best_total": main["total"] if main else None,
        "best_structure": main["name"] if main else None,
        "best_detail": main,
    }
    prior = [h for h in history if h.get("date") != today]
    history = prior + [entry]

    # Buy-signal + diff layer: what leads the message, the perspective line,
    # the booking-window countdown, and what changed vs yesterday.
    alert_lines = alerts.headlines(entry, history, as_of)
    context = alerts.price_context(entry, history)
    count = alerts.countdown(as_of)
    changes = alerts.changes_since(prior[-1] if prior else None, entry)

    return {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip(),
        "alerts": alert_lines,
        "price_context": context,
        "countdown": count,
        "changes": changes,
        "warnings": warnings or [],
        "trip": {
            "route": ("BOS → Istanbul → Dhaka → " +
                      ("Bangkok → Singapore" if (main or {}).get("order") == "BKK-first"
                       else "Singapore → Bangkok") + " → BOS"),
            "travelers": "2 adults + 1 child",
            "rules": ("2 nights Istanbul · Dhaka ≤29 days · Singapore 2-4 nights "
                      "(price decides) · 5 nights Bangkok · either order, cheaper "
                      "wins · home by Feb 7, 2027 · cheapest airline wins"),
        },
        "main": main,
        "budget": budget,
        "bali": bali,
        # 🏨 the Marriott award stay rides with the trip: reference points
        # figures (hotels.CHECKED), stay dates derived from tonight's winner.
        "hotel": hotels.hotel_plan(main),
        "stay_value": stay,
        # "how much more is the non-US-Bangla option?" — with each airline's bag
        # rule alongside, because a $60 saving that drops 40 kg isn't a saving.
        "ticket1_options": _with_baggage(ticket1_options(openjaws, t1),
                                         baggage.US_TICKET, "BOS→IST"),
        "ticket2_options": _with_baggage(
            ticket2_options(flights, sg_tickets or [], main),
            baggage.ASIA_TICKET,
            "DAC→BKK" if (main or {}).get("order") == "BKK-first" else "DAC→SIN"),
        "sg_tickets": sg_tickets or [],
        "flights": flights,
        "history": history,
    }


def build_today(flights: list, openjaws: list, warnings: list = None,
                sg_tickets: list = None, bali: dict = None,
                stay_rates: dict = None) -> dict:
    """Today's payload, history included — built BEFORE Telegram goes out so the
    message and the dashboard can't disagree about what the trip costs."""
    return build_payload(flights, openjaws, _load_history(),
                         datetime.date.today().isoformat(), warnings, sg_tickets,
                         bali=bali, stay_rates=stay_rates)


def write_payload(payload: dict) -> None:
    """Backup → write → commit → push. Never raises: a publish failure must not
    cost the run its Telegram message or its Sheet row."""
    try:
        today = datetime.date.today().isoformat()
        # Backup yesterday's file before overwriting — 60 daily snapshots kept
        # locally (backups/ is gitignored; git history is the second copy, the
        # Google Sheet History tab the third).
        try:
            if os.path.exists(DATA_FILE):
                bdir = os.path.join(REPO_DIR, "backups")
                os.makedirs(bdir, exist_ok=True)
                shutil.copy2(DATA_FILE, os.path.join(bdir, f"data-{today}.json"))
                for old in sorted(os.listdir(bdir))[:-60]:
                    os.remove(os.path.join(bdir, old))
        except OSError as e:
            print(f"WARN: data.json backup failed: {e}")
        # Serialize BEFORE opening the file: json.dumps must run to
        # completion (or raise) before the live file is truncated, so an
        # unserializable payload leaves yesterday's good file on disk
        # instead of half- (or fully-) overwritten with garbage. allow_nan
        # =False agrees with schema_check's own probe — NaN/Infinity would
        # otherwise write "successfully" into JSON no parser can read back.
        text = json.dumps(payload, indent=1, default=_jsonable, allow_nan=False)
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            f.write(text)
        print(f"Wrote {DATA_FILE}")

        def git(*args):
            return subprocess.run(["git", "-C", REPO_DIR] + list(args),
                                  capture_output=True, text=True, timeout=60)

        git("add", "site/data.json")
        commit = git("commit", "-m", f"Daily data: {today}")
        if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
            print(f"WARN: git commit failed: {commit.stderr.strip()[:200]}")
            _telegram_warn(
                "⚠️ dhaka-flights: git commit failed — tonight's data was "
                "written locally but not committed; the dashboard will be "
                "stale. Check for a stray index.lock in the repo.")
            return
        for attempt in range(1, PUSH_ATTEMPTS + 1):
            push = git("push")
            if push.returncode == 0:
                print("Pushed data.json — dashboard will show it on next load.")
                break
            stderr = push.stderr or ""
            print(f"WARN: git push failed (attempt {attempt}/{PUSH_ATTEMPTS}): "
                  f"{stderr.strip()[:200]}")
            # A GitHub-side rejection (a repo rule / push-protection hook,
            # "[remote rejected] ... push declined due to a detected
            # secret") is a different animal from a plain non-fast-forward:
            # no amount of pulling fixes a blocked secret — this repo has
            # hit push-protection before — so it gets its own fail-fast
            # branch and its own advice instead of the wrong "pull" hint.
            if "remote rejected" in stderr:
                _telegram_warn(
                    "⚠️ dhaka-flights: origin rejected the push (hook/"
                    "push-protection) — see cron.log for git's message; "
                    "this needs a human.")
                break
            # A non-fast-forward rejection can't be fixed by waiting and
            # retrying — only a pull fixes it — so burning the remaining
            # backoff on more of the same rejection just delays the warning
            # that actually tells the user what to do.
            if "non-fast-forward" in stderr or "fetch first" in stderr:
                _telegram_warn(
                    "⚠️ dhaka-flights: origin/main has commits this Mac "
                    "doesn't have — run `git pull --rebase` in the repo, "
                    "then the next nightly push will succeed.")
                break
            if attempt < PUSH_ATTEMPTS:
                time.sleep(PUSH_BACKOFF_S[attempt - 1])
        else:
            _telegram_warn(
                f"⚠️ dhaka-flights: git push failed {PUSH_ATTEMPTS}× — "
                "tonight's data is committed locally but the dashboard will "
                "be stale until the next successful push. Check network/"
                "GitHub creds on the Mac mini.")
    except Exception as e:
        print(f"WARN: publish failed (daily run continues): {e}")
        # The only failure path with no Telegram warning of its own — a
        # serialization failure lands here BEFORE data.json is touched, so
        # yesterday's file is safe, but the user still needs to know
        # tonight's run never got that far.
        _telegram_warn(
            "⚠️ dhaka-flights: publish crashed before writing data.json — "
            "dashboard keeps yesterday's data. See cron.log.")


def publish(flights: list, openjaws: list, warnings: list = None,
            sg_tickets: list = None) -> None:
    """Build + write in one call (kept for manual runs and older callers)."""
    write_payload(build_today(flights, openjaws, warnings, sg_tickets))
