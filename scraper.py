import re
import subprocess
import time
import json
from typing import Union

DEPART_DATE = "2027-01-03"
RETURN_DATE = "2027-01-28"
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


def _run(cmd: str) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
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


def scrape_route(origin: str, dest: str) -> list:
    results = []
    try:
        _run("browse stop")
        time.sleep(0.5)
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
        print("  Filling departure date...")
        dep_ref = _find_ref(snap, "textbox: Departure")
        _run(f"browse click {dep_ref}"); time.sleep(0.5)
        _run('browse type "January 3, 2027"'); time.sleep(0.8)
        snap = _snap()
        # Click the calendar Done button to confirm
        done_ref = _find_ref(snap, "button: Done")
        if done_ref:
            _run(f"browse click {done_ref}"); time.sleep(0.8)
        snap = _snap()

        # --- Return date ---
        print("  Filling return date...")
        ret_ref = _find_ref(snap, "textbox: Return")
        _run(f"browse click {ret_ref}"); time.sleep(0.5)
        _run('browse type "January 28, 2027"'); time.sleep(0.8)
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
        results = _parse_results(tree, origin, dest, result_url)
        print(f"  Parsed {len(results)} flights")

    except Exception as e:
        print(f"  Error: {e}")
    finally:
        _run("browse stop")

    return results


def _parse_results(tree: str, origin: str, dest: str, url: str) -> list:
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
            "depart": "Jan 3, 2027",
            "return_date": "Jan 28, 2027",
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

    print("Scraping BOS → DAC...")
    dac = scrape_route("BOS", "DAC")
    all_results += dac
    print(f"  Got {len(dac)} results")

    print("Scraping BOS → BKK...")
    bkk = scrape_route("BOS", "BKK")
    all_results += bkk
    print(f"  Got {len(bkk)} results")

    return all_results
