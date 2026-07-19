"""Write site/data.json (today's results + running price history) and push it,
so the Vercel dashboard — which fetches the file raw from GitHub — updates
without a redeploy. A publish failure must never kill the daily run."""
import datetime
import json
import os
import shutil
import subprocess

from combo import best_combos, cheapest_by_leg, best_structures, best_singapore

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


def build_payload(flights: list, openjaws: list, history: list, today: str,
                  warnings: list = None, sg_tickets: list = None) -> dict:
    structures = best_structures(flights, openjaws)
    singapore = best_singapore(flights, openjaws, sg_tickets or [])
    legs_min = {r: f["price_total"] for r, f in cheapest_by_leg(flights).items()}
    oj_min = {}
    for oj in openjaws:
        if isinstance(oj.get("price_total"), (int, float)):
            key = oj["ret_date"]
            if key not in oj_min or oj["price_total"] < oj_min[key]:
                oj_min[key] = oj["price_total"]

    entry = {
        "date": today,
        "best_total": structures[0]["total"] if structures else None,
        "best_structure": structures[0]["name"] if structures else None,
        # Full winning-structure snapshot so the dashboard's History tab can
        # show airlines/legs/links for past days, not just totals.
        "best_detail": structures[0] if structures else None,
        "oneway_combo_total": next(
            (s["total"] for s in structures if s["name"] == "3 one-way tickets"), None),
        "openjaw_total": next(
            (s["total"] for s in structures
             if s.get("kind") == "openjaw" and s["valid"]), None),
        "stopover_total": next(
            (s["total"] for s in structures
             if s.get("kind") == "stopover" and s["valid"]), None),
        "istanbul2_total": next(
            (s["total"] for s in structures
             if s.get("kind") == "stopover2" and s["valid"]), None),
        "openjaw_min": oj_min,
        "legs_min": legs_min,
        # combined = the MAIN trip (Istanbul 2-3 nights + Singapore + Bali 5)
        "combined_total": next((s["total"] for s in singapore
                                if s.get("kind") == "sg-stopover2" and s["valid"]), None),
        "singapore_total": next((s["total"] for s in singapore
                                 if s.get("kind") in ("sg-openjaw", "sg-oneways")
                                 and s["valid"]), None),
    }
    history = [h for h in history if h.get("date") != today] + [entry]

    return {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip(),
        "warnings": warnings or [],
        "trip": {
            "route": "BOS → Istanbul → Dhaka → Singapore → Bali → BOS",
            "travelers": "2 adults + 1 child",
            "rules": ("5 nights Bali · 2 nights Istanbul · 2 nights Singapore · "
                      "Dhaka ≤29 days · home by Feb 7, 2027 · cheapest airline wins "
                      "(THAI/SQ upgrade noted when available)"),
        },
        "structures": structures,
        "singapore": singapore,
        "combos": best_combos(flights, top_n=3),
        "cheapest_by_leg": cheapest_by_leg(flights),
        "openjaws": openjaws,
        "flights": flights,
        "history": history,
    }


def publish(flights: list, openjaws: list, warnings: list = None,
            sg_tickets: list = None) -> None:
    try:
        today = datetime.date.today().isoformat()
        payload = build_payload(flights, openjaws, _load_history(), today, warnings,
                                sg_tickets)
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
