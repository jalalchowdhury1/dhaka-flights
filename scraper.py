import os
import re
import subprocess
import time
import json
from typing import Union

# ONE TRIP ONLY (Jalal, 2026-07-25: "i only need the main trip … you just need
# to track this one and not the others"), reshaped 2026-08-01 (Bali retired —
# dengue tail risk): BOS → Istanbul 2n → Dhaka → Bangkok 5n + Singapore 2n →
# BOS, BOTH city orders priced nightly, the cheaper complete trip wins.
# Ticket ① (the two long legs + Istanbul) is one multi-city search PER ORDER
# (the return city differs); Ticket ② is the Dhaka→city1→city2 middle.
#
# RETIRED 2026-07-25 — the direct BOS→DAC / DAC→DPS / DPS→BOS one-ways and the
# plain open-jaw watch. RETIRED 2026-08-01 — every DPS/Bali search (the old
# LEGS pair lives on in BALI_LEGS below for the kept-but-retired combo paths).
# Restoring anything = put the legs back in LEGS and the configs back in
# scrape_tickets_all(); the retired combo functions still work.
LEGS = [
    # Ticket ② legs for BOTH orders, priced as one-ways — the cheaper of
    # {2 one-ways, 1 multi-city ticket} wins inside combo.order_trip.
    # Jan 27–28 starts serve the 2-4-night Singapore FLEX BAND (2026-08-01:
    # "you can take it up to 3 or even 4 if its cheaper") and the 💸 budget
    # companion's early-Dhaka-exit deals — restored under the 30-search
    # allowance ("you can get it up to 30 searches if it helps you").
    # SIN-first order: DAC→SIN (2-4 SIN nights) then SIN→BKK (5 BKK nights to Feb 6)
    {"origin": "DAC", "dest": "SIN",
     "dates": ["January 27, 2027", "January 28, 2027", "January 29, 2027",
               "January 30, 2027", "January 31, 2027", "February 1, 2027"]},
    {"origin": "SIN", "dest": "BKK",
     "dates": ["January 31, 2027", "February 1, 2027", "February 2, 2027"]},
    # BKK-first order: DAC→BKK (5 BKK nights) then BKK→SIN (2-4 SIN nights to Feb 6)
    {"origin": "DAC", "dest": "BKK",
     "dates": ["January 27, 2027", "January 28, 2027", "January 29, 2027",
               "January 30, 2027", "January 31, 2027", "February 1, 2027"]},
    {"origin": "BKK", "dest": "SIN",
     "dates": ["February 2, 2027", "February 3, 2027", "February 4, 2027"]},
]

# Bali-era LEGS, retired 2026-08-01 — kept for the retired combo paths' tests.
BALI_LEGS = [
    {"origin": "DAC", "dest": "SIN",
     "dates": ["January 27, 2027", "January 28, 2027", "January 29, 2027",
               "January 30, 2027", "January 31, 2027", "February 1, 2027"]},
    {"origin": "SIN", "dest": "DPS",
     "dates": ["January 31, 2027", "February 1, 2027", "February 2, 2027", "February 3, 2027"]},
]

TRIP_YEAR = 2027

# Keywords that identify the right suggestion in the airport dropdown, tried in order.
AIRPORT_PICK = {
    "BOS": ["Boston Logan", "Boston"],
    "DAC": ["Hazrat Shahjalal", "Dhaka"],
    "DPS": ["Ngurah Rai", "Denpasar", "Bali"],
    # Never fall back to the bare code here: "IST" substring-matches random
    # tree lines ("listitem", ...) and clicks derail the whole form. "SIN"
    # would do the same ("listitem", "single"), so give it explicit picks.
    "IST": ["Istanbul Airport", "Istanbul"],
    "SIN": ["Singapore Changi", "Changi", "Singapore"],
    # BKK types "Bangkok" (TYPE_AS) and picks the CITY option, which covers
    # BOTH airports — Thai AirAsia/Thai Lion fly the cheap DAC routes out of
    # Don Mueang (DMK), and typing the bare code offers ONLY Suvarnabhumi
    # (live-checked 2026-08-01). The "option:" prefix stops the keyword from
    # matching the input box's own value line (which now reads "Bangkok"),
    # and a plain "Bangkok" keyword would also hit "Bangkok Yai, Thailand".
    "BKK": ["option: Bangkok, Thailand", "Suvarnabhumi"],
}

# What to TYPE into the airport box, when it isn't the airport code itself.
TYPE_AS = {"BKK": "Bangkok"}

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


def _find_refs(snap_raw: str, *keywords) -> list:
    """All refs whose line matches all keywords, in tree order (multi-city
    forms repeat 'Where from'/'Where to'/'Departure' once per flight row)."""
    tree = _get_tree(snap_raw)
    out = []
    for line in tree.splitlines():
        if all(kw.lower() in line.lower() for kw in keywords):
            refs = re.findall(r'\[(\d+-\d+)\]', line)
            if refs:
                out.append("@" + refs[-1])
    return out


def _snap() -> str:
    return _run("browse snapshot")


# ── One browser session per RUN (2026-08-01 evening) ────────────────────────
# The per-search stop→env→open cycle cost ~35-40s of pure overhead per search
# — the single biggest chunk of the nightly runtime (Jalal: "no more than 25
# minutes"). The session now starts once and is REUSED; any blank page or
# exception marks it dirty so the NEXT search (or the existing retry paths)
# restarts it. That keeps the 2026-07-15 wedge hardening: a broken browser
# still gets a fresh session before another attempt.
_SESSION_STARTED = False


def _ensure_session(fresh: bool = False) -> None:
    global _SESSION_STARTED
    if fresh or not _SESSION_STARTED:
        _run("browse stop")
        time.sleep(1)
        _run("browse env local")
        _SESSION_STARTED = True


def _session_dirty() -> None:
    global _SESSION_STARTED
    _SESSION_STARTED = False


def end_session() -> None:
    """Call ONCE when a run's scraping is finished — never between searches."""
    _session_dirty()
    try:
        _run("browse stop")
    except Exception as e:
        print(f"  WARN: browse stop failed during cleanup: {e}")


# Google streams its results in after the page URL changes. A FIXED sleep
# snapshots an empty list whenever the Mac is busy — seen live 2026-07-25: the
# search URL was right, the tree had 153 lines and zero fares, and the run
# reported "0 results" as if Google had nothing. Poll instead: cheap on a fast
# night, and the difference between a real empty day and a slow one.
RESULT_WAIT_SECONDS = 40
RESULT_POLL_SECONDS = 5


def _wait_for_results(snap: str) -> str:
    waited = 0
    while ("us dollars" not in _get_tree(snap).lower()
           and waited < RESULT_WAIT_SECONDS):
        time.sleep(RESULT_POLL_SECONDS)
        waited += RESULT_POLL_SECONDS
        snap = _snap()
    return snap


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
        _ensure_session()
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
            _session_dirty()          # retry paths get a fresh browser
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
        _run(f"browse type {TYPE_AS.get(origin, origin)}"); time.sleep(2)
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
        _run(f"browse type {TYPE_AS.get(dest, dest)}"); time.sleep(2)
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
        time.sleep(8)

        raw_url = _run("browse get url")
        try:
            result_url = json.loads(raw_url).get("url", raw_url)
        except Exception:
            result_url = raw_url
        snap = _wait_for_results(_snap())

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
        _session_dirty()
        print(f"  Error: {e}")
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

        # Times of day (2026-07-18, for the site's Trip-plan itinerary):
        # "Leaves <airport> at 10:40 PM on ..." / "arrives at <airport> at 12:15 PM on ..."
        depart_time = arrive_time = ""
        m = re.search(r'Leaves .+? at (\d{1,2}:\d{2}\s*[AP]M) on', text, re.IGNORECASE)
        if m:
            depart_time = m.group(1).upper().replace(" ", " ")
        m = re.search(r'arrives at .+? at (\d{1,2}:\d{2}\s*[AP]M) on', text, re.IGNORECASE)
        if m:
            arrive_time = m.group(1).upper()

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
            "depart_time": depart_time,
            "arrive_time": arrive_time,
            "airline": airline,
            "stops": stops,
            "duration": duration,
            "layovers": layovers,
            "price_total": price,   # USD, all 3 travelers
            "link": url,
        })

    # Keep the CHEAPEST options, not the first in page order — Google's "top
    # flights" ranking buried a $1,340 THAI fare below the cap on 2026-07-16.
    results.sort(key=lambda f: f["price_total"]
                 if isinstance(f["price_total"], (int, float)) else float("inf"))
    return results[:MAX_RESULTS]


# Open-jaw watch: BOS→DAC + DPS→BOS on ONE multi-city ticket (the middle
# DAC→DPS hop is bought separately). Found 2026-07-15 to be ~$1.7k cheaper
# than three one-ways ($3.4k vs $5.1k for the two long legs, all 3 pax).
# RETIRED from the nightly rotation 2026-07-25 (main trip only) — config kept
# so a comparison run is one line away.
OPENJAW_SEARCHES = [
    ("January 4, 2027", "February 6, 2027"),   # home Feb 7 (deadline-safe)
    ("January 4, 2027", "February 7, 2027"),   # home Feb 8 (flagged)
]


def scrape_openjaw(out_date: str, ret_date: str) -> list:
    """Multi-city search: BOS→DAC on out_date + DPS→BOS on ret_date, one ticket."""
    legs = [("BOS", "DAC", out_date), ("DPS", "BOS", ret_date)]
    return _scrape_multicity(
        legs,
        lambda tree, url: _parse_openjaw_results(tree, out_date, ret_date, url),
        f"openjaw: BOS->DAC {out_date} + DPS->BOS {ret_date}")


def _scrape_multicity(legs: list, parse_fn, tag: str) -> list:
    """Fill Google Flights' multi-city form with the given (origin, dest, date)
    legs and parse the first-leg selection page. Prices there are the TOTAL for
    the whole itinerary, all passengers; flight details (airline/times/layovers)
    describe the FIRST leg — each choice is priced with its cheapest completion."""
    results = []
    try:
        _ensure_session()
        _run("browse open https://www.google.com/travel/flights?hl=en&curr=USD&gl=us")
        time.sleep(4)
        snap = _snap()

        if "Where from" not in _get_tree(snap):
            DIAG["blank_pages"] += 1
            _session_dirty()          # retry paths get a fresh browser
            print("  ERROR: Flights page never loaded (blank/stub tree)")
            return results

        # Ticket type → Multi-city
        tt_ref = _find_ref(snap, "Change ticket type")
        if tt_ref:
            _run(f"browse click {tt_ref}"); time.sleep(1)
            snap = _snap()
            mc_ref = _find_ref(snap, "option: Multi-city")
            if mc_ref:
                _run(f"browse click {mc_ref}"); time.sleep(1.5)
            snap = _snap()

        # Passengers: 2 adults + 1 child
        pax_ref = _find_ref(snap, "passenger")
        if pax_ref:
            _run(f"browse click {pax_ref}"); time.sleep(0.8)
            snap = _snap()
            add_adult = _find_ref(snap, "button: Add adult")
            if add_adult:
                _run(f"browse click {add_adult}"); time.sleep(0.4)
            snap = _snap()
            add_child = _find_ref(snap, "button: Add child")
            if add_child:
                _run(f"browse click {add_child}"); time.sleep(0.4)
            snap = _snap()
            done_ref = _find_ref(snap, "button: Done")
            if done_ref:
                _run(f"browse click {done_ref}"); time.sleep(0.8)
            snap = _snap()

        # The multi-city form starts with 2 flight rows; add more if needed
        snap = _snap()
        froms = _find_refs(snap, "Where from")
        while len(froms) < len(legs):
            add_ref = _find_ref(snap, "Add flight")
            if not add_ref:
                print("  ERROR: could not add a flight row to the multi-city form")
                return results
            _run(f"browse click {add_ref}"); time.sleep(1)
            snap = _snap()
            froms = _find_refs(snap, "Where from")

        for i, (o, d, dep) in enumerate(legs):
            snap = _snap()
            froms = _find_refs(snap, "Where from")
            if i >= len(froms):
                print("  ERROR: multi-city form has too few flight rows")
                return results
            print(f"  Row {i+1}: {o}→{d} {dep}")
            _run(f"browse click {froms[i]}"); time.sleep(0.6)
            _run("browse press Escape"); time.sleep(0.3)
            _run(f"browse click {froms[i]}"); time.sleep(0.5)
            _run(f"browse type {TYPE_AS.get(o, o)}"); time.sleep(2)
            snap = _snap()
            pick = _pick_airport(snap, o)
            if pick:
                _run(f"browse click {pick}")
            else:
                _run("browse press Enter")
            time.sleep(1)
            snap = _snap()

            tos = _find_refs(snap, "Where to")
            _run(f"browse click {tos[i]}"); time.sleep(0.5)
            _run(f"browse type {TYPE_AS.get(d, d)}"); time.sleep(2)
            snap = _snap()
            pick = _pick_airport(snap, d)
            if pick:
                _run(f"browse click {pick}")
            else:
                _run("browse press Enter")
            time.sleep(1)
            snap = _snap()

            deps = _find_refs(snap, "textbox: Departure")
            _run(f"browse click {deps[i]}"); time.sleep(0.5)
            _run(f'browse type "{dep}"'); time.sleep(0.8)
            snap = _snap()
            done_ref = _find_ref(snap, "button: Done")
            if done_ref:
                _run(f"browse click {done_ref}"); time.sleep(0.8)

        snap = _snap()
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
        snap = _wait_for_results(_snap())
        more_ref = _find_ref(snap, "View more flights")
        if more_ref:
            _run(f"browse click {more_ref}")
            time.sleep(3)
            snap = _snap()
        tree = _get_tree(snap)

        results = parse_fn(tree, result_url)
        print(f"  Parsed {len(results)} multi-city options")

        if not results:
            with open(DEBUG_TREE_FILE, "w") as f:
                f.write(f"{tag}\nurl: {result_url}\n\n{tree}")
            print(f"  (tree saved to {DEBUG_TREE_FILE})")
    except Exception as e:
        _session_dirty()
        print(f"  Error: {e}")
    return results


def _parse_openjaw_results(tree: str, out_date: str, ret_date: str, url: str) -> list:
    """Multi-city first-leg selection lines read 'From 3423 US dollars total.'
    — reuse the one-way parser and re-shape the fields."""
    parsed = _parse_results(tree, "BOS", "DAC", url, out_date)
    results = []
    for f in parsed:
        results.append({
            "out_date": out_date,
            "ret_date": ret_date,
            "price_total": f["price_total"],   # BOTH legs, all 3 travelers
            "airline": f["airline"],
            "out_arrive": f["arrive"],
            # first-leg times (multi-city selection page describes leg 1 only)
            "out_depart_time": f.get("depart_time", ""),
            "out_arrive_time": f.get("arrive_time", ""),
            "stops": f["stops"],
            "duration": f["duration"],
            "layovers": f["layovers"],
            "link": f["link"],
        })
    return results


# Turkish 30h-Istanbul-stopover itinerary, verified bookable 2026-07-15 at
# $3,688 promo (vs $3,423 plain open-jaw): the outbound is split into two
# flights on one reservation, which qualifies for TK's free 4-star hotel
# night (connection 20h–7d; apply via their Stopover "Booker" ≥72h before;
# N and R fare classes are excluded from the hotel benefit).
STOPOVER_SEARCH = {
    "kind": "stopover",
    "ist_nights": 1,
    "label": "Turkish + 30h Istanbul stopover (free hotel)",
    "legs": [("BOS", "IST", "January 4, 2027"),
             ("IST", "DAC", "January 6, 2027"),
             ("DPS", "BOS", "February 6, 2027")],
    "airline_filter": "Turkish",
    "out_date": "January 4, 2027",
    "out_arrive": "January 7, 2027",   # IST→DAC 7:30pm Jan 6 lands next morning
    "ret_date": "February 6, 2027",
    "desc": ("BOS→IST Jan 4 · 30h Istanbul (free TK hotel) · IST→DAC Jan 6 "
             "+ DPS→BOS Feb 6 — one Turkish ticket"),
    "note": ("Free 4-star hotel night: apply at Turkish's Stopover Booker ≥72h "
             "before flying; excluded on N/R fare classes — check the booking "
             "class letter before paying."),
}

# Istanbul 2-NIGHT variant (2026-07-18): same 3-leg one-ticket shape, IST→DAC
# pushed to Jan 7 → land IST Jan 5 morning, 2 full nights in Istanbul, arrive
# Dhaka Jan 8 (overnight flight). Any airline (in practice Turkish — IST→DAC is
# TK-only — but unfiltered so codeshares/partners aren't dropped). US passports
# are visa-free in Türkiye; TK's free-hotel benefit needs 20h+ connection ✓.
ISTANBUL2_SEARCH = {
    "kind": "stopover2",
    "ist_nights": 2,
    "label": "Istanbul 2-night stopover",
    "legs": [("BOS", "IST", "January 4, 2027"),
             ("IST", "DAC", "January 7, 2027"),
             ("DPS", "BOS", "February 6, 2027")],
    "airline_filter": None,
    "out_date": "January 4, 2027",
    "out_arrive": "January 8, 2027",   # IST→DAC evening Jan 7 lands next morning
    "ret_date": "February 6, 2027",
    "desc": ("BOS→IST Jan 4 · 2 nights Istanbul · IST→DAC Jan 7 "
             "+ DPS→BOS Feb 6 — one ticket"),
    "note": ("2 full Istanbul nights (US passports visa-free). On Turkish, the "
             "20h–7d connection still qualifies for ONE free 4-star hotel night "
             "via their Stopover Booker (≥72h before; not on N/R fares) — "
             "night 2 is on you."),
}

# 3-night Istanbul sibling (2026-07-18: nights in IST/SIN are flexible — price
# decides; the ONLY hard constant is 5 Bali nights). Same kind "stopover2" so
# history's istanbul2_total automatically tracks the cheaper of 2 vs 3 nights.
ISTANBUL3_SEARCH = dict(
    ISTANBUL2_SEARCH,
    ist_nights=3,
    label="Istanbul 3-night stopover",
    legs=[("BOS", "IST", "January 4, 2027"),
          ("IST", "DAC", "January 8, 2027"),
          ("DPS", "BOS", "February 6, 2027")],
    out_arrive="January 9, 2027",      # IST→DAC evening Jan 8 lands next morning
    desc=("BOS→IST Jan 4 · 3 nights Istanbul · IST→DAC Jan 8 "
          "+ DPS→BOS Feb 6 — one ticket"),
)

# ISTANBUL3_SEARCH retired from the nightly rotation (2026-07-18 final: exactly
# 2 nights in Istanbul). STOPOVER_SEARCH (the Turkish 30h/1-night version)
# retired 2026-07-25. ISTANBUL2_SEARCH (the DPS/Bali return) retired
# 2026-08-01 with Bali itself. All configs kept above for easy re-adding.

# Ticket ① since 2026-08-01: one search per ORDER — same Boston→Istanbul→Dhaka
# front, the return leg comes from whichever city the order visits LAST.
# ret_city is what pairs each fare with its order in combo.ORDERS.
TICKET1_SIN_RETURN = dict(
    ISTANBUL2_SEARCH,
    ret_city="SIN",
    label="Istanbul 2n + return from Singapore (Bangkok-first order)",
    legs=[("BOS", "IST", "January 4, 2027"),
          ("IST", "DAC", "January 7, 2027"),
          ("SIN", "BOS", "February 6, 2027")],
    desc=("BOS→IST Jan 4 · 2 nights Istanbul · IST→DAC Jan 7 "
          "+ SIN→BOS Feb 6 — one ticket"),
)
TICKET1_BKK_RETURN = dict(
    ISTANBUL2_SEARCH,
    ret_city="BKK",
    label="Istanbul 2n + return from Bangkok (Singapore-first order)",
    legs=[("BOS", "IST", "January 4, 2027"),
          ("IST", "DAC", "January 7, 2027"),
          ("BKK", "BOS", "February 6, 2027")],
    desc=("BOS→IST Jan 4 · 2 nights Istanbul · IST→DAC Jan 7 "
          "+ BKK→BOS Feb 6 — one ticket"),
)
STOPOVER_SEARCHES = [TICKET1_SIN_RETURN, TICKET1_BKK_RETURN]

# Ticket ① is the ONLY search that can kill the whole trip if it comes back
# empty — nothing else can stand in for it now that the alternatives are gone —
# so it gets more attempts than everything else.
TICKET1_ATTEMPTS = 3


def scrape_stopover(cfg=None) -> list:
    cfg = cfg or STOPOVER_SEARCH
    legs_str = " / ".join(f"{o}→{d} {dep}" for o, d, dep in cfg["legs"])

    def parse(tree, url):
        out = []
        for f in _parse_openjaw_results(tree, cfg["out_date"], cfg["ret_date"], url):
            filt = cfg.get("airline_filter")
            if filt and filt.lower() not in f["airline"].lower():
                continue
            f.update(kind=cfg["kind"], label=cfg["label"], desc=cfg["desc"],
                     note=cfg["note"], out_arrive=cfg["out_arrive"],
                     ist_nights=cfg.get("ist_nights"))
            if cfg.get("ret_city"):
                f.update(ret_city=cfg["ret_city"],
                         route=f"BOS→IST→DAC + {cfg['ret_city']}→BOS")
            out.append(f)
        return out

    return _scrape_multicity(cfg["legs"], parse, f"{cfg['kind']}: {legs_str}")


# Ticket ② as a single multi-city ticket, one route pair PER ORDER
# (2026-08-01). The two-one-way version of the same middles comes from LEGS.
ORDER_ROUTES = {"SIN-first": (("DAC", "SIN"), ("SIN", "BKK")),
                "BKK-first": (("DAC", "BKK"), ("BKK", "SIN"))}

TICKET2_SEARCHES = [
    # 7 pairs (2026-08-01 evening, 30-search allowance): the diagonal around
    # each order's ideal shape + the Jan 28 4-SIN-night flex pair.
    # SIN-first: DAC→SIN + SIN→BKK; second leg arriving Feb 1 = the 5-night
    # Bangkok block against the Feb 6 return.
    ("SIN-first", "January 28, 2027", "February 1, 2027"),   # 4 SIN nights
    ("SIN-first", "January 29, 2027", "January 31, 2027"),
    ("SIN-first", "January 30, 2027", "February 1, 2027"),
    ("SIN-first", "January 31, 2027", "February 2, 2027"),
    # BKK-first: DAC→BKK + BKK→SIN, 5 nights apart (Bangkok block first),
    # landing SIN with 2-4 nights before the Feb 6 SIN→BOS return.
    ("BKK-first", "January 28, 2027", "February 2, 2027"),   # 4 SIN nights
    ("BKK-first", "January 29, 2027", "February 3, 2027"),
    ("BKK-first", "January 30, 2027", "February 4, 2027"),
]

# Bali-era pairs (DAC→SIN + SIN→DPS), retired 2026-08-01 — kept for the
# retired combo paths' tests and easy re-adding.
SG_TICKET_SEARCHES = [
    ("January 27, 2027", "February 1, 2027"),
    ("January 28, 2027", "February 1, 2027"),
    ("January 29, 2027", "January 31, 2027"),
    ("January 30, 2027", "February 1, 2027"),
    ("January 31, 2027", "February 2, 2027"),
    ("February 1, 2027", "February 3, 2027"),
]


def scrape_ticket2(order: str, d1: str, d2: str) -> list:
    """Multi-city Ticket ② on one ticket, routes per ORDER_ROUTES. Returns
    dicts tagged kind='sg-ticket' + order, out_date=leg-1, ret_date=leg-2
    (the leg-2 date doubles as the second city's arrival date — these are
    short, usually same-day hops)."""
    (o1, dst1), (o2, dst2) = ORDER_ROUTES[order]
    legs = [(o1, dst1, d1), (o2, dst2, d2)]

    def parse(tree, url):
        out = []
        for f in _parse_openjaw_results(tree, d1, d2, url):
            f.update(kind="sg-ticket", order=order,
                     route=f"{o1}→{dst1}→{dst2}")
            out.append(f)
        return out

    return _scrape_multicity(legs, parse,
                             f"ticket2 {order}: {o1}->{dst1} {d1} + {o2}->{dst2} {d2}")


def scrape_sg_ticket(dac_sin_date: str, sin_dps_date: str) -> list:
    """RETIRED Bali-era version (DAC→SIN→DPS), kept for tests/re-adding."""
    legs = [("DAC", "SIN", dac_sin_date), ("SIN", "DPS", sin_dps_date)]

    def parse(tree, url):
        out = []
        for f in _parse_openjaw_results(tree, dac_sin_date, sin_dps_date, url):
            f.update(kind="sg-ticket", route="DAC→SIN→DPS")
            out.append(f)
        return out

    return _scrape_multicity(legs, parse,
                             f"sg-ticket: DAC->SIN {dac_sin_date} + SIN->DPS {sin_dps_date}")


def scrape_sg_tickets_all() -> list:
    """All Ticket ② multi-city searches, both orders. (Name kept from the
    Singapore-detour era — run_daily imports it.) Kept SEPARATE from the
    open-jaw list — the open-jaw pairing loop would mis-handle these."""
    all_results = []
    for i, (order, d1, d2) in enumerate(TICKET2_SEARCHES, 1):
        print(f"[ticket2 {i}/{len(TICKET2_SEARCHES)}] {order} {d1} + {d2}")
        results = scrape_ticket2(order, d1, d2)
        if not results:
            print("  0 results — retrying once with a fresh session...")
            time.sleep(5)
            results = scrape_ticket2(order, d1, d2)
        all_results += results
        print(f"  Got {len(results)} options")
    return all_results


# 🌴 Bali comparison watch (2026-08-01 evening): the ORIGINAL trip stays
# scraped nightly so the price gap vs the Bangkok rework stays visible
# (Jalal: "keep another tab open for the original bali trip. i want to be
# able to compare"). SLIMMED same day for the 25-minute cap: Ticket ① (DPS
# return) + the two one-ticket middle pairs around the ideal shape — 3
# searches, no one-way middles. It's a BENCHMARK, not a bookable product;
# a consistent yardstick beats exhaustive coverage here.
BALI_WATCH_PAIRS = [
    ("January 29, 2027", "January 31, 2027"),
    ("January 30, 2027", "February 1, 2027"),   # the ideal 2-SIN/5-Bali pair
]


def scrape_bali_watch():
    """(tickets1, sg_tickets, legs) for the retired Bali trip: Ticket ① with
    the DPS→BOS return + the BALI_WATCH_PAIRS one-ticket middles. Runs LAST
    in the nightly order — the Bangkok trip is the product, so a throttled
    night degrades the comparison before the headline. legs is always [] —
    the one-way SIN→DPS middles were dropped for speed."""
    print("[bali-watch] Ticket ① (DPS return)")
    tickets1 = []
    for attempt in range(1, TICKET1_ATTEMPTS + 1):
        tickets1 = scrape_stopover(ISTANBUL2_SEARCH)
        if tickets1:
            break
        print(f"  0 results (attempt {attempt}/{TICKET1_ATTEMPTS}) — retrying...")
        time.sleep(5)
    sg = []
    for i, (d1, d2) in enumerate(BALI_WATCH_PAIRS, 1):
        print(f"[bali-watch sg-ticket {i}/{len(BALI_WATCH_PAIRS)}] {d1} + {d2}")
        r = scrape_sg_ticket(d1, d2)
        if not r:
            time.sleep(5)
            r = scrape_sg_ticket(d1, d2)
        sg += r
    return tickets1, sg, []


def scrape_tickets_all() -> list:
    """Ticket ① searches: BOS→IST + IST→DAC + DPS→BOS on one multi-city ticket.
    (Was scrape_openjaw_all; the plain open-jaw searches retired 2026-07-25.)"""
    all_results = []
    for cfg in STOPOVER_SEARCHES:
        print(f"[{cfg['kind']}] {cfg['label']}")
        results = []
        for attempt in range(1, TICKET1_ATTEMPTS + 1):
            results = scrape_stopover(cfg)
            if results:
                break
            print(f"  0 results (attempt {attempt}/{TICKET1_ATTEMPTS}) — "
                  f"retrying with a fresh session...")
            time.sleep(5)
        all_results += results
        print(f"  Got {len(results)} options")
    return all_results


# Back-compat alias: run_daily used to call this name.
scrape_openjaw_all = scrape_tickets_all


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
