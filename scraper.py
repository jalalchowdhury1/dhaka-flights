import os
import re
import subprocess
import time
import json
from typing import Union

DEPART_DATES = ["January 3, 2027", "January 4, 2027", "January 5, 2027", "January 6, 2027"]
RETURN_DATES = ["January 25, 2027", "January 26, 2027", "January 27, 2027", "January 28, 2027"]
ADULTS = 3
MAX_RESULTS = 10


def build_google_flights_url(origin: str, dest: str, depart: str, return_date: str, adults: int) -> str:
    return (
        f"https://www.google.com/travel/flights?"
        f"hl=en&curr=USD"
        f"#flt={origin}.{dest}.{depart}*{dest}.{origin}.{return_date}"
        f";c:USD;e:1;sd:1;t:f;tt:o;pax:{adults}"
    )


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


def scrape_route(origin: str, dest: str, depart: str, ret: str) -> list:
    """depart and ret are human-readable e.g. 'January 3, 2027'"""
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

        # --- Passengers: set to 3 adults ---
        print("  Setting 3 passengers...")
        pax_ref = _find_ref(snap, "passenger, change")
        if pax_ref:
            _run(f"browse click {pax_ref}")
            time.sleep(0.8)
            snap = _snap()
            add_ref = _find_ref(snap, "button: Add adult")
            if add_ref:
                _run(f"browse click {add_ref}"); time.sleep(0.4)
                _run(f"browse click {add_ref}"); time.sleep(0.4)
            snap = _snap()
            done_ref = _find_ref(snap, "button: Done")
            if done_ref:
                _run(f"browse click {done_ref}"); time.sleep(0.8)
            snap = _snap()

        # --- Origin: click → Escape → click → type → pick Boston Logan ---
        print(f"  Filling origin: {origin}...")
        origin_ref = _find_ref(snap, "Where from")
        _run(f"browse click {origin_ref}"); time.sleep(0.6)
        _run("browse press Escape"); time.sleep(0.3)
        _run(f"browse click {origin_ref}"); time.sleep(0.5)
        _run(f"browse type {origin}"); time.sleep(2)
        snap = _snap()
        bos_ref = _find_ref(snap, "Boston Logan")
        if bos_ref:
            _run(f"browse click {bos_ref}")
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
        # For DAC: Hazrat Shahjalal / Dhaka; for BKK: Suvarnabhumi / Bangkok
        airport_ref = (
            _find_ref(snap, "Hazrat Shahjalal") or
            _find_ref(snap, "Suvarnabhumi") or
            _find_ref(snap, "Dhaka") or
            _find_ref(snap, "Bangkok") or
            _find_ref(snap, dest)
        )
        if airport_ref:
            _run(f"browse click {airport_ref}")
        else:
            _run("browse press Enter")
        time.sleep(1)
        snap = _snap()

        # --- Departure date ---
        print(f"  Filling departure date: {depart}...")
        dep_ref = _find_ref(snap, "textbox: Departure")
        _run(f"browse click {dep_ref}"); time.sleep(0.5)
        _run(f'browse type "{depart}"'); time.sleep(0.8)
        snap = _snap()
        done_ref = _find_ref(snap, "button: Done")
        if done_ref:
            _run(f"browse click {done_ref}"); time.sleep(0.8)
        snap = _snap()

        # --- Return date ---
        print(f"  Filling return date: {ret}...")
        ret_ref = _find_ref(snap, "textbox: Return")
        _run(f"browse click {ret_ref}"); time.sleep(0.5)
        _run(f'browse type "{ret}"'); time.sleep(0.8)
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
        tree = _get_tree(snap)

        # --- Parse results from accessibility tree ---
        results = _parse_results(tree, origin, dest, result_url, depart, ret)
        print(f"  Parsed {len(results)} flights")

        if not results:
            # Keep the evidence: without this, a 0-flight run is undiagnosable
            # (the 2026-07-15 failure left nothing to inspect).
            with open(DEBUG_TREE_FILE, "w") as f:
                f.write(f"route: {origin}->{dest} {depart} -> {ret}\nurl: {result_url}\n\n{tree}")
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


def _parse_results(tree: str, origin: str, dest: str, url: str, depart: str = "", ret: str = "") -> list:
    """
    Parse flights from the accessibility tree.
    Each flight is a listitem containing a link whose text has all the info:
    'From 817 US dollars round trip total. 2 stops flight with Delta and Saudia.
     Leaves Boston Logan... Total duration 31 hr 10 min. ...'
    """
    results = []
    lines = tree.splitlines()

    for line in lines:
        if len(results) >= MAX_RESULTS:
            break
        # Flight links always say "round trip total" and "flight with"
        if "round trip total" not in line.lower():
            continue
        if "flight with" not in line.lower() and "nonstop flight" not in line.lower():
            continue

        # Strip the accessibility tree prefix [X-Y] link: ...
        text = re.sub(r'^\s*\[\d+-\d+\]\s*link:\s*', '', line).strip()

        # Price: "From 817 US dollars" or "From $817"
        price_raw = "N/A"
        m = re.search(r'From\s+([\d,]+)\s+US dollars', text, re.IGNORECASE)
        if m:
            price_raw = m.group(1)
        else:
            m = re.search(r'From\s+\$([\d,]+)', text, re.IGNORECASE)
            if m:
                price_raw = m.group(1)

        # Airline: "flight with Delta and Saudia" or "nonstop flight with Emirates"
        airline = "N/A"
        m = re.search(r'(?:stops?|nonstop) flight with (.+?)\.', text, re.IGNORECASE)
        if m:
            airline = m.group(1).strip()

        # Duration: "Total duration 31 hr 10 min"
        duration = "N/A"
        m = re.search(r'Total duration (.+?)\.', text, re.IGNORECASE)
        if m:
            duration = m.group(1).strip()

        # Stops: "2 stops flight" or "1 stop flight" or "nonstop flight"
        stops = "N/A"
        m = re.search(r'(nonstop|\d+ stops?) flight', text, re.IGNORECASE)
        if m:
            stops = m.group(1).strip()

        price = parse_price(price_raw)
        results.append({
            "route": f"{origin}→{dest}",
            "depart": depart,
            "return_date": ret,
            "airline": airline,
            "stops": stops,
            "duration": duration,
            "price_per_person": price,
            "baggage": "N/A",
            "link": url,
        })

    return results


def scrape_all() -> list:
    all_results = []
    routes = [("BOS", "DAC"), ("BOS", "BKK")]
    total = len(routes) * len(DEPART_DATES) * len(RETURN_DATES)
    n = 0
    consecutive_failures = 0

    DIAG.update(timeouts=0, blank_pages=0, aborted_early=False)

    for origin, dest in routes:
        for depart in DEPART_DATES:
            for ret in RETURN_DATES:
                n += 1
                print(f"[{n}/{total}] {origin}→{dest}  {depart} → {ret}")
                results = scrape_route(origin, dest, depart, ret)
                if not results:
                    # One retry after a full stop: a fresh session recovers
                    # transient hiccups (each route already restarts the env).
                    print("  0 results — retrying route once with a fresh session...")
                    time.sleep(5)
                    results = scrape_route(origin, dest, depart, ret)
                all_results += results
                print(f"  Got {len(results)} results")

                consecutive_failures = 0 if results else consecutive_failures + 1
                if consecutive_failures >= 4:
                    # 4 routes (8 attempts) in a row with nothing = the browser
                    # side is dead; grinding through the rest just burns an hour
                    # and produces the same nothing.
                    DIAG["aborted_early"] = True
                    print(f"ABORTING: {consecutive_failures} consecutive routes returned "
                          f"0 results (timeouts={DIAG['timeouts']}, blank_pages={DIAG['blank_pages']})")
                    return all_results

    return all_results
