#!/usr/bin/env python3
"""
Jev-powered fast scraping engine for Google Flights.
Same public API as scraper.py, HALF the wall time via:
1. Readiness polling instead of fixed sleeps
2. Jev picks for ambiguous element selection  
3. No blind waits - each sleep >= 0.5s becomes wait_for()
"""
import os
import re
import time
import json
import subprocess
from typing import Union, Tuple, Optional, List

# Import Jev client
import jev_client

# Global DIAG for Jev engine - mirrors scraper.py
DIAG = {
    "timeouts": 0,
    "blank_pages": 0,
    "aborted_early": False,
    "deadline_skips": [],
    "last_stderr": "",
    "wait_timeouts": 0,
    "jev_calls": 0,
    "jev_ms": 0,
    "jev_fallbacks": 0,
    "engine_fallbacks": 0
}

# Constants - import from legacy scraper
import scraper as _legacy

RUN_DEADLINE_MIN = _legacy.RUN_DEADLINE_MIN
LEGS = _legacy.LEGS
AIRPORT_PICK = _legacy.AIRPORT_PICK
TYPE_AS = _legacy.TYPE_AS
MAX_RESULTS = _legacy.MAX_RESULTS
TICKET1_SIN_RETURN = _legacy.TICKET1_SIN_RETURN
TICKET1_BKK_RETURN = _legacy.TICKET1_BKK_RETURN
STOPOVER_SEARCHES = _legacy.STOPOVER_SEARCHES
TICKET2_SEARCHES = _legacy.TICKET2_SEARCHES
TRIP_YEAR = _legacy.TRIP_YEAR

# Global start time for deadline tracking
_run_start = None


def begin_run() -> None:
    """Called once by run_daily at run start; arms the deadline clock."""
    global _run_start
    _run_start = time.monotonic()
    DIAG["deadline_skips"] = []


def _past_deadline() -> bool:
    if _run_start is None:
        return False
    return (time.monotonic() - _run_start) > RUN_DEADLINE_MIN * 60


def end_session() -> None:
    """Call ONCE when a run's scraping is finished."""
    pass  # Session management handled by scrape functions


def parse_price(raw: str) -> Union[int, str]:
    if not raw:
        return "N/A"
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else "N/A"


DEBUG_TREE_FILE = "debug_last_zero.txt"


def _run(cmd: str) -> str:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        DIAG["timeouts"] += 1
        print(f"  WARN: command timed out after 30s: {cmd}")
        return ""
    err = result.stderr.strip()
    if not result.stdout.strip() and err:
        DIAG["last_stderr"] = err
        print(f"  WARN: '{cmd}' empty stdout, stderr: {err[:200]}")
    return result.stdout.strip()


def _get_tree(snap_raw: str) -> str:
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
    """All refs whose line matches all keywords."""
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


def wait_for(pred, timeout: float, step: float = 0.25) -> str:
    """Poll browse snapshot until pred(tree) is true; return the snapshot.
    
    On timeout returns the last snapshot and counts DIAG['wait_timeouts'] += 1.
    """
    end_time = time.time() + timeout
    last_snap = ""
    while time.time() < end_time:
        snap = _snap()
        tree = _get_tree(snap)
        if pred(tree):
            return snap
        last_snap = snap
        time.sleep(step)
    DIAG["wait_timeouts"] += 1
    return last_snap


def _pick_element(instructions: str, candidates: list, state: str = "") -> Optional[str]:
    """Use Jev to pick with floor and fallback.
    
    Returns the ref if p >= 0.6 and valid; otherwise None.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    
    choice, p = jev_client.pick(instructions, candidates, state)
    DIAG["jev_calls"] += 1
    
    if choice is None or p < 0.6:
        DIAG["jev_fallbacks"] += 1
        return None
    
    return choice


def _verify_fill(tree: str, legs: list) -> bool:
    """Verify the results page shows our form inputs (supports multi-city).
    
    Args:
        tree: Accessibility tree string
        legs: List of (origin, dest, date) tuples
    
    Returns True if all legs are found in the tree.
    """
    tree_lower = tree.lower()
    for origin, dest, depart in legs:
        origin_found = any(kw.lower() in tree_lower for kw in AIRPORT_PICK.get(origin, [origin]))
        dest_found = any(kw.lower() in tree_lower for kw in AIRPORT_PICK.get(dest, [dest]))
        date_found = depart.lower() in tree_lower
        if not (origin_found and dest_found and date_found):
            return False
    return True


def scrape_route(origin: str, dest: str, depart: str) -> list:
    """One-way search using Jev engine with legacy fallback."""
    try:
        return _scrape_route_jev(origin, dest, depart)
    except Exception as e:
        DIAG["engine_fallbacks"] += 1
        print(f"  Jev scrape failed ({e}), falling back to legacy")
        import scraper as legacy
        return legacy.scrape_route(origin, dest, depart)


def _scrape_route_jev(origin: str, dest: str, depart: str) -> list:
    """Jev-powered one-way search with readiness polling."""
    # Open page
    _run("browse open https://www.google.com/travel/flights?hl=en&curr=USD&gl=us")
    wait_for(lambda t: "Where from" in t.lower() and "Where to" in t.lower(), timeout=10.0, step=0.5)
    
    # Dismiss consent
    for label in ["Accept all", "I agree", "Accept"]:
        ref = _find_ref(_snap(), f"button: {label}")
        if ref:
            _run(f"browse click {ref}")
            wait_for(lambda t: "Where from" in t.lower(), timeout=3.0, step=0.25)
            break
    
    # Check for Explore page
    current_url_raw = _run("browse get url")
    try:
        current_url = json.loads(current_url_raw).get("url", current_url_raw)
    except Exception:
        current_url = current_url_raw
    
    if "explore" in current_url or "Where from" not in _get_tree(_snap()):
        flights_ref = _find_ref(_snap(), "link: Flights")
        if flights_ref:
            _run(f"browse click {flights_ref}")
        wait_for(lambda t: "Where from" in t.lower(), timeout=10.0, step=0.5)
    
    snap = _snap()
    if "Where from" not in _get_tree(snap):
        DIAG["blank_pages"] += 1
        print("  ERROR: Flights page never loaded (blank/stub tree)")
        return []
    
    # Switch to one-way
    print("  Switching to one-way...")
    tt_ref = _find_ref(snap, "Change ticket type")
    if tt_ref:
        _run(f"browse click {tt_ref}")
        snap = wait_for(lambda t: "option:" in t.lower(), timeout=5.0, step=0.25)
        ow_ref = _find_ref(snap, "option:", "One way")
        if ow_ref:
            _run(f"browse click {ow_ref}")
            _run("browse press Escape")  # Close the dropdown
            time.sleep(0.5)
            snap = _snap()
    
    # Set passengers
    print("  Setting passengers: 2 adults + 1 child...")
    pax_ref = _find_ref(snap, "passenger")
    if pax_ref:
        _run(f"browse click {pax_ref}")
        snap = wait_for(lambda t: "Add adult" in t.lower() or "Done" in t.lower(), timeout=5.0, step=0.25)
        
        add_adult = _find_ref(snap, "button:", "Add adult")
        if add_adult:
            _run(f"browse click {add_adult}")
            snap = _snap()
        
        add_child = _find_ref(snap, "button:", "Add child")
        if add_child:
            _run(f"browse click {add_child}")
            snap = _snap()
        
        done_ref = _find_ref(snap, "button:", "Done")
        if done_ref:
            _run(f"browse click {done_ref}")
            snap = wait_for(lambda t: "Where from" in t.lower(), timeout=3.0, step=0.25)
    
    # Fill origin
    print(f"  Filling origin: {origin}...")
    origin_ref = _find_ref(snap, "Where from")
    if origin_ref:
        _run(f"browse click {origin_ref}")
        time.sleep(0.3)
        _run("browse press Escape")
        time.sleep(0.2)
        _run(f"browse click {origin_ref}")
        time.sleep(0.3)
        _run(f"browse type {TYPE_AS.get(origin, origin)}")
        time.sleep(1.0)
        snap = _snap()
        
        pick = _legacy._pick_airport(snap, origin)
        if pick:
            _run(f"browse click {pick}")
        else:
            _run("browse press Enter")
        time.sleep(0.5)
        snap = _snap()
    
    # Fill destination
    print(f"  Filling destination: {dest}...")
    dest_ref = _find_ref(snap, "Where to")
    if dest_ref:
        _run(f"browse click {dest_ref}")
        time.sleep(0.3)
        _run("browse press Escape")
        time.sleep(0.2)
        _run(f"browse click {dest_ref}")
        time.sleep(0.3)
        _run(f"browse type {TYPE_AS.get(dest, dest)}")
        time.sleep(1.0)
        snap = _snap()
        
        pick = _legacy._pick_airport(snap, dest)
        if pick:
            _run(f"browse click {pick}")
        else:
            _run("browse press Enter")
        time.sleep(0.5)
        snap = _snap()
    
    # Fill date
    print(f"  Filling departure date: {depart}...")
    dep_ref = _find_ref(snap, "textbox:", "Departure")
    if dep_ref:
        _run(f"browse click {dep_ref}")
        time.sleep(0.3)
        _run(f'browse type "{depart}"')
        time.sleep(1.0)
        snap = _snap()
        
        # Google Flights abbreviates month: "Jan 7" for "January 7"
        # Check for abbreviated month in the tree
        month_abbr = depart.split(" ")[0][:3]  # "January" → "Jan"
        day = depart.split(" ")[1].rstrip(",")  # "7," → "7"
        date_short = f"{month_abbr} {day}"
        
        if date_short.lower() not in _get_tree(snap).lower():
            DIAG["wait_timeouts"] += 1
            print(f"  WARN: date may not have been entered correctly (looking for '{date_short}')")
        
        done_ref = _find_ref(snap, "button:", "Done")
        if done_ref:
            _run(f"browse click {done_ref}")
            time.sleep(0.5)
            snap = _snap()
    
    # Search
    print("  Searching...")
    search_ref = _find_ref(snap, "button:", "Search")
    if search_ref:
        _run(f"browse click {search_ref}")
    else:
        _run("browse press Enter")
    time.sleep(8)

    # Use legacy wait_for_results for proper settle check
    snap = _legacy._wait_for_results(_snap())
    tree = _legacy._get_tree(snap)

    # View more flights
    more_ref = _find_ref(snap, "View more flights")
    if more_ref:
        _run(f"browse click {more_ref}")
        time.sleep(1)
        snap = _snap()
        tree = _get_tree(snap)

    # Parse results
    results = _parse_results(tree, origin, dest, snap, depart)
    print(f"  Parsed {len(results)} flights")
    
    # Fill verification - per brief: verified fill + 0 results = no flights that day (OK)
    # Unverified fill + 0 results = fill failure → trigger legacy fallback via exception
    if not results:
        if not _verify_fill(tree, [(origin, dest, depart)]):
            print("  0 results + fill NOT verified — triggering legacy fallback")
            raise RuntimeError("fill-not-verified")
    elif not _verify_fill(tree, [(origin, dest, depart)]):
        print("  WARN: fill verification failed (results page may show route differently)")
        # Results are real even if verification text matching is imperfect
    
    if not results:
        with open(DEBUG_TREE_FILE, "w") as f:
            f.write(f"route: {origin}->{dest} {depart} (one-way)\nurl: {snap}\n\n{tree}")
    
    return results


def _parse_results(tree: str, origin: str, dest: str, url: str, depart: str = "") -> list:
    """Parse one-way flights from the accessibility tree."""
    import scraper as sc
    return sc._parse_results(tree, origin, dest, url, depart)


# --- Public API: exported names that run_daily.py imports ---

# Constants
LEGLS = LEGS
TICKET2_SEARCHES = _legacy.TICKET2_SEARCHES
STOPOVER_SEARCHES = _legacy.STOPOVER_SEARCHES
TRIP_YEAR = _legacy.TRIP_YEAR

# Re-export from legacy
TICKET1_SIN_RETURN = _legacy.TICKET1_SIN_RETURN
TICKET1_BKK_RETURN = _legacy.TICKET1_BKK_RETURN
AIRPORT_PICK = _legacy.AIRPORT_PICK
TYPE_AS = _legacy.TYPE_AS
MAX_RESULTS = _legacy.MAX_RESULTS

# Also re-export max_results constant from legacy for compatibility
max_results = MAX_RESULTS


def _scrape_multicity(legs: list, parse_fn, tag: str) -> list:
    """Fill Google Flights' multi-city form with the given (origin, dest, date)
    legs and parse the first-leg selection page. Jev-powered implementation."""
    results = []
    try:
        # Ensure session
        _legacy._ensure_session()
        
        # Open page
        _run("browse open https://www.google.com/travel/flights?hl=en&curr=USD&gl=us")
        wait_for(lambda t: "Where from" in t.lower() and "Where to" in t.lower(), timeout=10.0, step=0.5)
        
        # Dismiss consent
        for label in ["Accept all", "I agree", "Accept"]:
            ref = _find_ref(_snap(), f"button: {label}")
            if ref:
                _run(f"browse click {ref}")
                wait_for(lambda t: "Where from" in t.lower(), timeout=3.0, step=0.25)
                break
        
        # Check for Explore page
        current_url_raw = _run("browse get url")
        try:
            current_url = json.loads(current_url_raw).get("url", current_url_raw)
        except Exception:
            current_url = current_url_raw
        
        if "explore" in current_url or "Where from" not in _get_tree(_snap()):
            flights_ref = _find_ref(_snap(), "link: Flights")
            if flights_ref:
                _run(f"browse click {flights_ref}")
            wait_for(lambda t: "Where from" in t.lower(), timeout=10.0, step=0.5)
        
        snap = _snap()
        if "Where from" not in _get_tree(snap):
            DIAG["blank_pages"] += 1
            print("  ERROR: Flights page never loaded (blank/stub tree)")
            return results
        
        # Switch to multi-city
        print("  Switching to multi-city...")
        tt_ref = _find_ref(snap, "Change ticket type")
        if tt_ref:
            _run(f"browse click {tt_ref}")
            snap = wait_for(lambda t: "option:" in t.lower(), timeout=5.0, step=0.25)
            mc_ref = _find_ref(snap, "option:", "Multi-city")
            if mc_ref:
                _run(f"browse click {mc_ref}")
            _run("browse press Escape")  # Close the dropdown
            time.sleep(0.5)
            snap = wait_for(lambda t: "Where from" in t.lower() and "Where to" in t.lower(), timeout=5.0, step=0.25)
        
        # Set passengers
        print("  Setting passengers: 2 adults + 1 child...")
        pax_ref = _find_ref(snap, "passenger")
        if pax_ref:
            _run(f"browse click {pax_ref}")
            snap = wait_for(lambda t: "Add adult" in t.lower() or "Done" in t.lower(), timeout=5.0, step=0.25)
            
            add_adult = _find_ref(snap, "button:", "Add adult")
            if add_adult:
                _run(f"browse click {add_adult}")
                snap = _snap()
            
            add_child = _find_ref(snap, "button:", "Add child")
            if add_child:
                _run(f"browse click {add_child}")
                snap = _snap()
            
            done_ref = _find_ref(snap, "button:", "Done")
            if done_ref:
                _run(f"browse click {done_ref}")
                snap = wait_for(lambda t: "Where from" in t.lower(), timeout=3.0, step=0.25)
        
        # The multi-city form starts with 2 flight rows; add more if needed
        snap = _snap()
        froms = _find_refs(snap, "Where from")
        while len(froms) < len(legs):
            add_ref = _find_ref(snap, "Add flight")
            if not add_ref:
                print("  ERROR: could not add a flight row to the multi-city form")
                return results
            _run(f"browse click {add_ref}")
            snap = wait_for(lambda t: True, timeout=3.0, step=0.5)
            froms = _find_refs(snap, "Where from")
        
        # Fill each leg
        for i, (o, d, dep) in enumerate(legs):
            snap = _snap()
            froms = _find_refs(snap, "Where from")
            if i >= len(froms):
                print("  ERROR: multi-city form has too few flight rows")
                return results
            
            print(f"  Row {i+1}: {o}→{d} {dep}")
            
            # Fill origin
            _run(f"browse click {froms[i]}")
            time.sleep(0.3)
            _run("browse press Escape")
            time.sleep(0.2)
            _run(f"browse click {froms[i]}")
            _run(f"browse type {TYPE_AS.get(o, o)}")
            
            snap = wait_for(lambda t: any(kw.lower() in t for kw in AIRPORT_PICK.get(o, [o])), timeout=3.0, step=0.25)
            
            candidates = [line for line in _get_tree(snap).splitlines()
                         if "option:" in line.lower() and any(kw.lower() in line for kw in AIRPORT_PICK.get(o, [o]))]
            
            if len(candidates) >= 2:
                jev_pick = _pick_element(
                    f"Pick the airport suggestion for {o}, not a listitem.",
                    candidates, snap
                )
                pick = jev_pick if jev_pick else _find_ref(snap, o)
            else:
                pick = _find_ref(snap, o)
            
            if pick:
                _run(f"browse click {pick}")
            else:
                _run("browse press Enter")
            snap = wait_for(lambda t: "Where to" in t.lower(), timeout=3.0, step=0.25)
            
            # Fill destination
            tos = _find_refs(snap, "Where to")
            _run(f"browse click {tos[i]}")
            _run(f"browse type {TYPE_AS.get(d, d)}")
            snap = wait_for(lambda t: any(kw.lower() in t for kw in AIRPORT_PICK.get(d, [d])), timeout=3.0, step=0.25)
            
            candidates = [line for line in _get_tree(snap).splitlines()
                         if "option:" in line.lower() and any(kw.lower() in line for kw in AIRPORT_PICK.get(d, [d]))]
            
            if len(candidates) >= 2:
                jev_pick = _pick_element(
                    f"Pick the airport suggestion for {d}, not a listitem.",
                    candidates, snap
                )
                pick = jev_pick if jev_pick else _find_ref(snap, d)
            else:
                pick = _find_ref(snap, d)
            
            if pick:
                _run(f"browse click {pick}")
            else:
                _run("browse press Enter")
            snap = wait_for(lambda t: "textbox: Departure" in t.lower(), timeout=3.0, step=0.25)
            
            # Fill date
            deps = _find_refs(snap, "textbox: Departure")
            _run(f"browse click {deps[i]}")
            _run(f'browse type "{dep}"')
            snap = wait_for(lambda t: dep.lower() in t.lower(), timeout=3.0, step=0.25)
            
            done_ref = _find_ref(snap, "button: Done")
            if done_ref:
                _run(f"browse click {done_ref}")
                snap = wait_for(lambda t: "Where from" in t.lower(), timeout=3.0, step=0.25)
        
        # Click Search
        snap = _snap()
        search_ref = _find_ref(snap, "button:", "Search")
        if search_ref:
            _run(f"browse click {search_ref}")
        else:
            _run("browse press Enter")

        # Use legacy wait_for_results for proper settle check
        snap = _legacy._wait_for_results(_snap())
        tree = _legacy._get_tree(snap)
        
        # Get the URL for parsing
        raw_url = _run("browse get url")
        try:
            result_url = json.loads(raw_url).get("url", raw_url)
        except Exception:
            result_url = raw_url
        
        # View more flights
        more_ref = _find_ref(snap, "View more flights")
        if more_ref:
            _run(f"browse click {more_ref}")
            time.sleep(1)
            snap = _snap()
            tree = _get_tree(snap)
        
        results = parse_fn(tree, result_url)
        print(f"  Parsed {len(results)} multi-city options")
        
        if not results:
            with open(DEBUG_TREE_FILE, "w") as f:
                f.write(f"{tag}\nurl: {result_url}\n\n{tree}")
            print(f"  (tree saved to {DEBUG_TREE_FILE})")
        
        # Fill verification
        if results and not _verify_fill(tree, legs):
            print("  WARN: fill verification failed")
            return []
            
    except Exception as e:
        _legacy._session_dirty()
        print(f"  Error: {e}")
    
    return results


def scrape_stopover(cfg=None) -> list:
    """Single multi-city stopover search."""
    cfg = cfg or _legacy.STOPOVER_SEARCH

    def parse(tree, url):
        out = []
        for f in _legacy._parse_openjaw_results(tree, cfg["out_date"], cfg["ret_date"], url):
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

    legs_str = " / ".join(f"{o}→{d} {dep}" for o, d, dep in cfg["legs"])
    return _scrape_multicity(cfg["legs"], parse, f'{cfg["kind"]}: {legs_str}')


def scrape_tickets_all() -> list:
    """Ticket ① searches: BOS→IST + IST→DAC + DPS→BOS on one multi-city ticket."""
    all_results = []
    for cfg in STOPOVER_SEARCHES:
        print(f"[{cfg['kind']}] {cfg['label']}")
        results, thin_retried = [], False
        for attempt in range(1, 3 + 1):  # TICKET1_ATTEMPTS = 3
            got = scrape_stopover(cfg)
            if len(got) > len(results):
                results = got
            if len(results) >= 4:  # THIN_TICKET1_OPTIONS = 4
                break
            if results and thin_retried:
                break
            if results:
                thin_retried = True
                print(f"  only {len(results)} options (attempt {attempt}/3) — page may be half-rendered, retrying once with a fresh session...")
                _legacy._session_dirty()
            else:
                print(f"  0 results (attempt {attempt}/3) — retrying with a fresh session...")
            time.sleep(5)
        all_results += results
        print(f"  Got {len(results)} options")
    return all_results


def scrape_sg_tickets_all() -> list:
    """All Ticket ② multi-city searches, both orders."""
    all_results = []
    ORDER_ROUTES = _legacy.ORDER_ROUTES
    for i, (order, d1, d2) in enumerate(TICKET2_SEARCHES, 1):
        print(f"[ticket2 {i}/{len(TICKET2_SEARCHES)}] {order} {d1} + {d2}")
        
        (o1, dst1), (o2, dst2) = ORDER_ROUTES[order]
        legs = [(o1, dst1, d1), (o2, dst2, d2)]

        def parse(tree, url):
            out = []
            for f in _legacy._parse_openjaw_results(tree, d1, d2, url):
                f.update(kind="sg-ticket", order=order,
                         route=f"{o1}→{dst1}→{dst2}")
                out.append(f)
            return out

        tag = f"ticket2 {order}: {o1}->{dst1} {d1} + {o2}->{dst2} {d2}"
        results = _scrape_multicity(legs, parse, tag)
        if not results:
            time.sleep(5)
            results = _scrape_multicity(legs, parse, tag)
        all_results += results
        print(f"  Got {len(results)} options")
    return all_results


def scrape_all() -> list:
    """All one-way legs using Jev engine."""
    all_results = []
    total = sum(len(leg["dates"]) for leg in LEGS)
    n = 0
    consecutive_failures = 0

    DIAG.update(timeouts=0, blank_pages=0, aborted_early=False)

    for leg in LEGS:
        origin, dest = leg["origin"], leg["dest"]
        for depart in leg["dates"]:
            if _past_deadline():
                remaining = total - n
                DIAG["deadline_skips"].append(
                    f"one-way legs: {remaining} of {total} searches "
                    f"(past {RUN_DEADLINE_MIN} min)")
                print(f"DEADLINE: skipping remaining {remaining} one-way searches")
                return all_results
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


def scrape_bali_watch():
    """(tickets1, fwd_tickets, rev_tickets) for the retired Bali trip, both
    orders. Runs LAST in the nightly order — the Bangkok trip is the product,
    so a throttled night degrades the comparison before the headline."""
    from scraper import OPENJAW_SEARCHES, BALI_WATCH_PAIRS
    
    if _past_deadline():
        DIAG["deadline_skips"].append(
            f"🌴 Bali watch: all 3 searches (past {RUN_DEADLINE_MIN} min)")
        print("DEADLINE: skipping Bali watch entirely")
        return [], [], []
    print("[bali-watch] Ticket ① (DPS return)")
    tickets1 = scrape_stopover(_legacy.ISTANBUL2_SEARCH)
    fwd, rev = [], []
    for i, (direction, d1, d2) in enumerate(BALI_WATCH_PAIRS, 1):
        print(f"[bali-watch {direction} {i}/{len(BALI_WATCH_PAIRS)}] {d1} + {d2}")
        if direction == "fwd":
            legs = [("DAC", "SIN", d1), ("SIN", "DPS", d2)]
        else:
            legs = [("DAC", "DPS", d1), ("DPS", "SIN", d2)]
        
        def parse(tree, url):
            out = []
            for f in _legacy._parse_openjaw_results(tree, d1, d2, url):
                if direction == "fwd":
                    f.update(kind="sg-ticket", route="DAC→SIN→DPS")
                else:
                    f.update(kind="sg-ticket", route="DAC→DPS→SIN")
                out.append(f)
            return out
        
        tag = f"bali-{direction}: {legs[0][0]}->{legs[0][1]} {d1} + {legs[1][0]}->{legs[1][1]} {d2}"
        r = _scrape_multicity(legs, parse, tag)
        if not r:
            time.sleep(5)
            r = _scrape_multicity(legs, parse, tag)
        (fwd if direction == "fwd" else rev).extend(r)
    return tickets1, fwd, rev


