import os
import re
import subprocess
import time
import json
from typing import Union

# Trip: BOS → Dhaka (≤29 days, 30-day visa) → Bali (5 nights, Marriott cert) → BOS.
# Three ONE-WAY searches; combo.py picks the cheapest valid combination.
LEGS = [
    {"origin": "BOS", "dest": "DAC",
     "dates": ["January 4, 2027", "January 5, 2027", "January 6, 2027"]},
    {"origin": "DAC", "dest": "DPS",
     "dates": ["February 1, 2027", "February 2, 2027", "February 3, 2027"]},
    {"origin": "DPS", "dest": "BOS",
     "dates": ["February 5, 2027", "February 6, 2027", "February 7, 2027"]},
]

TRIP_YEAR = 2027

# Keywords that identify the right suggestion in the airport dropdown, tried in order.
AIRPORT_PICK = {
    "BOS": ["Boston Logan", "Boston"],
    "DAC": ["Hazrat Shahjalal", "Dhaka"],
    "DPS": ["Ngurah Rai", "Denpasar", "Bali"],
}

# 2 adults + 1 child (aged 2-11, own seat). Google Flights shows the TOTAL
# price for all selected passengers (verified 2026-07-15: 1-pax search showed
# $367 where the 3-pax search showed $1,099).
MAX_RESULTS = 15


def parse_price(raw: str) -> Union[int, str]:
    if not raw:
        return "N/A"
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else "N/A"


# Diagnostics for the current scrape run, so run_daily can tell a local
# browser-automation failure apart from a genuine "Google returned nothing".
# (2026-07-15: the browse daemon wedged mid-run; every page after that was a
# silent about:blank stub and the Telegram alert wrongly blamed Google.)
DIAG = {"timeouts": 0, "blank_pages": 0, "aborted_early": False}

DEBUG_TREE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_last_zero.txt")


def _run(cmd: str) -> str:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        # A wedged browse daemon times out on every command; never let that
        # exception escape (it previously crashed the run from a finally block).
        DIAG["timeouts"] += 1
        print(f"  WARN: command timed out after 30s: {cmd}")
        return ""
    if not result.stdout.strip() and result.stderr.strip():
        print(f"  WARN: '{cmd}' empty stdout, stderr: {result.stderr.strip()[:200]}")
    return result.stdout.strip()


def _get_tree(snap_raw: str) -> str:
    """Parse browse snapshot JSON and return the tree string with real newlines."""
    try:
        return json.loads(snap_raw).get("tree", snap_raw)
    except Exception:
        return snap_raw


def _find_ref(snap_raw: str, *keywords) -> str:
    """Find the first accessibility ref matching all keywords."""
    tree = _get_tree(snap_raw)
    for line in tree.splitlines():
        if all(kw.lower() in line.lower() for kw in keywords):
            refs = re.findall(r'\[(\d+-\d+)\]', line)
            if refs:
                return "@" + refs[-1]
    return ""


def _snap() -> str:
    return _run("browse snapshot")


def _pick_airport(snap: str, code: str) -> str:
    """Ref for the dropdown suggestion matching an airport code's keywords."""
    for kw in AIRPORT_PICK.get(code, []) + [code]:
        ref = _find_ref(snap, kw)
        if ref:
            return ref
    return ""


def scrape_route(origin: str, dest: str, depart: str) -> list:
    """One-way search. depart is human-readable e.g. 'January 4, 2027'."""
    results = []
    try:
        _run("browse stop")
        time.sleep(1)
        _run("browse env local")
        _run("browse open https://www.google.com/travel/flights?hl=en&curr=USD&gl=us")
        time.sleep(4)
        snap = _snap()

        # Dismiss consent dialog if present
        for label in ["Accept all", "I agree", "Accept"]:
            ref = _find_ref(snap, f"button: {label}")
            if ref:
                _run(f"browse click {ref}")
                time.sleep(1)
                snap = _snap()
                break

        # If we ended up on the Explore map, click the Flights nav link
        current_url_raw = _run("browse get url")
        try:
            current_url = json.loads(current_url_raw).get("url", current_url_raw)
        except Exception:
            current_url = current_url_raw
        if "explore" in current_url or "Where from" not in _get_tree(snap):
            flights_ref = _find_ref(snap, "link: Flights")
            if flights_ref:
                _run(f"browse click {flights_ref}")
            else:
                _run("browse open https://www.google.com/travel/flights?hl=en&curr=USD&gl=us")
            time.sleep(4)
            snap = _snap()

        # If the search form STILL isn't there, the page never loaded (wedged
        # daemon → about:blank stub with exit 0). Bail now instead of "filling"
        # a form that doesn't exist and reporting a bogus 0-flights result.
        if "Where from" not in _get_tree(snap):
            DIAG["blank_pages"] += 1
            print("  ERROR: Flights page never loaded (blank/stub tree) — "
                  "local browser problem, NOT a Google block")
            return results

        # --- Trip type: switch Round trip → One way ---
        print("  Switching to one-way...")
        tt_ref = _find_ref(snap, "Change ticket type")
        if tt_ref:
            _run(f"browse click {tt_ref}"); time.sleep(0.8)
            snap = _snap()
            ow_ref = _find_ref(snap, "option: One way")
            if ow_ref:
                _run(f"browse click {ow_ref}"); time.sleep(0.8)
            snap = _snap()
        if "Change ticket type. One way" not in _get_tree(snap):
            print("  WARN: trip type may still be Round trip")

        # --- Passengers: 2 adults + 1 child (2-11) ---
        print("  Setting passengers: 2 adults + 1 child...")
        pax_ref = _find_ref(snap, "passenger")
        if pax_ref:
            _run(f"browse click {pax_ref}")
            time.sleep(0.8)
            snap = _snap()
            add_adult = _find_ref(snap, "button: Add adult")
            if add_adult:
                _run(f"browse click {add_adult}"); time.sleep(0.4)
            add_child = _find_ref(snap, "button: Add child")
            if add_child:
                _run(f"browse click {add_child}"); time.sleep(0.4)
            snap = _snap()
            done_ref = _find_ref(snap, "button: Done")
            if done_ref:
                _run(f"browse click {done_ref}"); time.sleep(0.8)
            snap = _snap()

        # --- Origin: click → Escape → click → type → pick from dropdown ---
        print(f"  Filling origin: {origin}...")
        origin_ref = _find_ref(snap, "Where from")
        _run(f"browse click {origin_ref}"); time.sleep(0.6)
        _run("browse press Escape"); time.sleep(0.3)
        _run(f"browse click {origin_ref}"); time.sleep(0.5)
        _run(f"browse type {origin}"); time.sleep(2)
        snap = _snap()
        pick = _pick_airport(snap, origin)
        if pick:
            _run(f"browse click {pick}")
        else:
            _run("browse press Enter")
        time.sleep(1)
        snap = _snap()

        # --- Destination ---
        print(f"  Filling destination: {dest}...")
        dest_ref = _find_ref(snap, "Where to")
        _run(f"browse click {dest_ref}"); time.sleep(0.5)
        _run(f"browse type {dest}"); time.sleep(2)
        snap = _snap()
        pick = _pick_airport(snap, dest)
        if pick:
            _run(f"browse click {pick}")
        else:
            _run("browse press Enter")
        time.sleep(1)
        snap = _snap()

        # --- Departure date (one-way: no return box exists) ---
        print(f"  Filling departure date: {depart}...")
        dep_ref = _find_ref(snap, "textbox: Departure")
        _run(f"browse click {dep_ref}"); time.sleep(0.5)
        _run(f'browse type "{depart}"'); time.sleep(0.8)
        snap = _snap()
        done_ref = _find_ref(snap, "button: Done")
        if done_ref:
            _run(f"browse click {done_ref}"); time.sleep(0.8)
        snap = _snap()

        # --- Search ---
        print("  Searching...")
        search_ref = _find_ref(snap, "button: Search")
        if search_ref:
            _run(f"browse click {search_ref}")
        else:
            _run("browse press Enter")
        time.sleep(10)

        raw_url = _run("browse get url")
        try:
            result_url = json.loads(raw_url).get("url", raw_url)
        except Exception:
            result_url = raw_url
        snap = _snap()

        # Google only shows a handful of "top" flights inline; the cheap ones
        # are often behind the expander.
        more_ref = _find_ref(snap, "View more flights")
        if more_ref:
            _run(f"browse click {more_ref}")
            time.sleep(3)
            snap = _snap()
        tree = _get_tree(snap)

        # --- Parse results from accessibility tree ---
        results = _parse_results(tree, origin, dest, result_url, depart)
        print(f"  Parsed {len(results)} flights")

        if not results:
            # Keep the evidence: without this, a 0-flight run is undiagnosable
            # (the 2026-07-15 failure left nothing to inspect).
            with open(DEBUG_TREE_FILE, "w") as f:
                f.write(f"route: {origin}->{dest} {depart} (one-way)\nurl: {result_url}\n\n{tree}")
            print(f"  (tree saved to {DEBUG_TREE_FILE})")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        try:
            _run("browse stop")
        except Exception as e:
            # Never let cleanup kill the whole daily run (it did on 2026-07-15).
            print(f"  WARN: browse stop failed during cleanup: {e}")

    return results


def _parse_results(tree: str, origin: str, dest: str, url: str, depart: str = "") -> list:
    """
    Parse one-way flights from the accessibility tree. Each flight is a link:
    'From 1130 US dollars. 1 stop flight with AirAsia. Leaves Hazrat Shahjalal
     International Airport at 10:40 PM on Monday, February 1 and arrives at
     I Gusti Ngurah Rai International Airport at 12:15 PM on Tuesday, February 2.
     Total duration 11 hr 35 min. Layover (1 of 1) is a 4 hr 25 min layover at ...'
    The dollar figure is the TOTAL for all selected passengers.
    """
    results = []
    lines = tree.splitlines()

    for line in lines:
        if len(results) >= MAX_RESULTS:
            break
        low = line.lower()
        if "us dollars" not in low and "from $" not in low:
            continue
        if "flight with" not in low and "nonstop flight" not in low:
            continue

        # Strip the accessibility tree prefix [X-Y] link: ...
        text = re.sub(r'^\s*\[\d+-\d+\]\s*link:\s*', '', line).strip()

        # Price: "From 1130 US dollars" or "From $1,130"
        price_raw = "N/A"
        m = re.search(r'From\s+([\d,]+)\s+US dollars', text, re.IGNORECASE)
        if m:
            price_raw = m.group(1)
        else:
            m = re.search(r'From\s+\$([\d,]+)', text, re.IGNORECASE)
            if m:
                price_raw = m.group(1)

        # Airline: "flight with AirAsia" or "nonstop flight with Emirates"
        airline = "N/A"
        m = re.search(r'(?:stops?|nonstop) flight with (.+?)\.', text, re.IGNORECASE)
        if m:
            airline = m.group(1).strip()

        # Duration: "Total duration 11 hr 35 min"
        duration = "N/A"
        m = re.search(r'Total duration (.+?)\.', text, re.IGNORECASE)
        if m:
            duration = m.group(1).strip()

        # Stops: "1 stop flight" or "2 stops flight" or "nonstop flight"
        stops = "N/A"
        m = re.search(r'(nonstop|\d+ stops?) flight', text, re.IGNORECASE)
        if m:
            stops = m.group(1).strip()

        # Arrival date: "arrives at ... at 12:15 PM on Tuesday, February 2"
        # (combo.py uses this for the visa / 5-night / home-deadline math)
        arrive = "N/A"
        m = re.search(r'arrives at .+? at \d{1,2}:\d{2}\s*[AP]M on \w+, (\w+ \d+)',
                      text, re.IGNORECASE)
        if m:
            arrive = f"{m.group(1)}, {TRIP_YEAR}"

        # Layovers: "Layover (1 of 1) is a 4 hr 25 min layover at <airport>".
        # Airport names can contain periods ("John F. Kennedy"), so prefer
        # matching through the word Airport before falling back to sentence end.
        lays = re.findall(
            r'Layover \(\d+ of \d+\) is a (.+?) (?:overnight )?layover (?:at|in) '
            r'(.+?(?:International )?Airport(?: in [A-Za-z \-]+)?|[^.]+)',
            text, re.IGNORECASE)
        layovers = "; ".join(f"{dur.strip()} at {place.strip()}" for dur, place in lays)
        if not layovers:
            layovers = "none" if stops.lower() == "nonstop" else "N/A"

        price = parse_price(price_raw)
        results.append({
            "route": f"{origin}→{dest}",
            "depart": depart,
            "arrive": arrive,
            "airline": airline,
            "stops": stops,
            "duration": duration,
            "layovers": layovers,
            "price_total": price,   # USD, all 3 travelers
            "link": url,
        })

    return results


def scrape_all() -> list:
    all_results = []
    total = sum(len(leg["dates"]) for leg in LEGS)
    n = 0
    consecutive_failures = 0

    DIAG.update(timeouts=0, blank_pages=0, aborted_early=False)

    for leg in LEGS:
        origin, dest = leg["origin"], leg["dest"]
        for depart in leg["dates"]:
            n += 1
            print(f"[{n}/{total}] {origin}→{dest}  {depart} (one-way)")
            results = scrape_route(origin, dest, depart)
            if not results:
                # One retry after a full stop: a fresh session recovers
                # transient hiccups (each route already restarts the env).
                print("  0 results — retrying route once with a fresh session...")
                time.sleep(5)
                results = scrape_route(origin, dest, depart)
            all_results += results
            print(f"  Got {len(results)} results")

            consecutive_failures = 0 if results else consecutive_failures + 1
            if consecutive_failures >= 4:
                # 4 routes (8 attempts) in a row with nothing = the browser
                # side is dead; grinding through the rest just burns time
                # and produces the same nothing.
                DIAG["aborted_early"] = True
                print(f"ABORTING: {consecutive_failures} consecutive routes returned "
                      f"0 results (timeouts={DIAG['timeouts']}, blank_pages={DIAG['blank_pages']})")
                return all_results

    return all_results
