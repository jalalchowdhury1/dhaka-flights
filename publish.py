"""Write site/data.json (today's results + running price history) and push it,
so the Vercel dashboard — which fetches the file raw from GitHub — updates
without a redeploy. A publish failure must never kill the daily run."""
import datetime
import json
import os
import shutil
import subprocess

import alerts
import baggage
from combo import budget_trip, main_trip, ticket1_options, ticket2_options

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(REPO_DIR, "site", "data.json")


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
                  warnings: list = None, sg_tickets: list = None) -> dict:
    """One trip, one payload (2026-07-25). The alternative trips — direct
    open-jaw, three one-ways, Istanbul-only, Singapore-only — are no longer
    scraped, tracked, or charted; `main` IS the product now."""
    main = main_trip(flights, openjaws, sg_tickets or [])
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
        "bkk_nights": (main or {}).get("bkk_nights"),
        "other_order_total": ((main or {}).get("other_order") or {}).get("total"),
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
    try:
        as_of = datetime.date.fromisoformat(today)
    except ValueError:
        as_of = datetime.date.today()
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
            "rules": ("2 nights Istanbul · Dhaka ≤29 days · min 2 nights Singapore · "
                      "5 nights Bangkok · either order, cheaper wins · "
                      "home by Feb 7, 2027 · cheapest airline wins"),
        },
        "main": main,
        "budget": budget,
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
                sg_tickets: list = None) -> dict:
    """Today's payload, history included — built BEFORE Telegram goes out so the
    message and the dashboard can't disagree about what the trip costs."""
    return build_payload(flights, openjaws, _load_history(),
                         datetime.date.today().isoformat(), warnings, sg_tickets)


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
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(payload, f, indent=1, default=_jsonable)
        print(f"Wrote {DATA_FILE}")

        def git(*args):
            return subprocess.run(["git", "-C", REPO_DIR] + list(args),
                                  capture_output=True, text=True, timeout=60)

        git("add", "site/data.json")
        commit = git("commit", "-m", f"Daily data: {today}")
        if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
            print(f"WARN: git commit failed: {commit.stderr.strip()[:200]}")
            return
        push = git("push")
        if push.returncode != 0:
            print(f"WARN: git push failed: {push.stderr.strip()[:200]}")
        else:
            print("Pushed data.json — dashboard will show it on next load.")
    except Exception as e:
        print(f"WARN: publish failed (daily run continues): {e}")


def publish(flights: list, openjaws: list, warnings: list = None,
            sg_tickets: list = None) -> None:
    """Build + write in one call (kept for manual runs and older callers)."""
    write_payload(build_today(flights, openjaws, warnings, sg_tickets))
