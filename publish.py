"""Write site/data.json (today's results + running price history) and push it,
so the Vercel dashboard — which fetches the file raw from GitHub — updates
without a redeploy. A publish failure must never kill the daily run."""
import datetime
import json
import os
import subprocess

from combo import best_combos, cheapest_by_leg, best_structures

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(REPO_DIR, "site", "data.json")


def _load_history() -> list:
    try:
        with open(DATA_FILE) as f:
            return json.load(f).get("history", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _jsonable(obj):
    if isinstance(obj, datetime.datetime):
        return obj.strftime("%B %d, %Y")
    raise TypeError(f"not JSON-serializable: {type(obj)}")


def build_payload(flights: list, openjaws: list, history: list, today: str) -> dict:
    structures = best_structures(flights, openjaws)
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
        "openjaw_min": oj_min,
        "legs_min": legs_min,
    }
    history = [h for h in history if h.get("date") != today] + [entry]

    return {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip(),
        "trip": {
            "route": "BOS → Dhaka → Bali → BOS",
            "travelers": "2 adults + 1 child",
            "rules": "Dhaka ≤29 days · 5 nights in Bali · home by Feb 7, 2027",
        },
        "structures": structures,
        "combos": best_combos(flights, top_n=3),
        "cheapest_by_leg": cheapest_by_leg(flights),
        "openjaws": openjaws,
        "flights": flights,
        "history": history,
    }


def publish(flights: list, openjaws: list) -> None:
    try:
        today = datetime.date.today().isoformat()
        payload = build_payload(flights, openjaws, _load_history(), today)
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
