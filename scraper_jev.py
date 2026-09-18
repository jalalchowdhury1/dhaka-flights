#!/usr/bin/env python3
"""
Jev-powered fast engine for Google Flights. Same public API as scraper.py.

Where the speed comes from:
1. Readiness polling (`wait_for`) instead of fixed sleeps — each step waits
   only until the page shows what the next step needs.
2. Results polling at a 1 s step (legacy: 8 s blind sleep + 5 s steps), with
   the "$18,913" settle check kept (priced-row count equal on two
   consecutive snapshots 2 s apart).
3. Jev picks the airport suggestion when the dropdown offers several; the
   legacy keyword match is the guardrail and the fallback.

Parsers, constants and session management are imported from scraper.py —
only the driving code is re-implemented.
"""
import re
import json
import time
import subprocess
from typing import Optional

import jev_client
import scraper as _legacy

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
    "engine_fallbacks": 0,
}

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
parse_price = _legacy.parse_price
DEBUG_TREE_FILE = _legacy.DEBUG_TREE_FILE

FLIGHTS_URL = "https://www.google.com/travel/flights?hl=en&curr=USD&gl=us"
JEV_P_FLOOR = 0.6
SETTLE_S = _legacy.SETTLE_POLL_SECONDS          # 2 s, the $18,913 lesson
RESULT_BUDGET_S = _legacy.RESULT_WAIT_SECONDS + 8   # legacy: 8 s sleep + 40 s poll

_run_start = None


def begin_run() -> None:
    global _run_start
    _run_start = time.monotonic()
    DIAG["deadline_skips"] = []


def _past_deadline() -> bool:
    if _run_start is None:
        return False
    return (time.monotonic() - _run_start) > RUN_DEADLINE_MIN * 60


def end_session() -> None:
    _legacy.end_session()


# ── browse plumbing ─────────────────────────────────────────────────────────

def _run(cmd: str) -> str:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        DIAG["timeouts"] += 1
        _legacy.DIAG["timeouts"] += 1        # _ensure_session's wedge detector reads this
        print(f"  WARN: command timed out after 30s: {cmd}")
        return ""
    err = result.stderr.strip()
    if not result.stdout.strip() and err:
        DIAG["last_stderr"] = err
        print(f"  WARN: '{cmd}' empty stdout, stderr: {err[:200]}")
    return result.stdout.strip()


def _snap() -> str:
    return _run("browse snapshot")


_get_tree = _legacy._get_tree
_find_ref = _legacy._find_ref
_find_refs = _legacy._find_refs


def _url() -> str:
    raw = _run("browse get url")
    try:
        return json.loads(raw).get("url", raw)
    except Exception:
        return raw


def _has(tree: str, *needles: str) -> bool:
    tl = tree.lower()
    return all(n.lower() in tl for n in needles)


def _lines_with(tree: str, needle: str) -> list:
    return [l for l in tree.splitlines() if needle.lower() in l.lower()]


def wait_for(pred, timeout: float, step: float = 0.25, count_timeout: bool = True) -> str:
    """Poll `browse snapshot` until pred(tree) is true; return the snapshot.
    On timeout return the last snapshot and count DIAG['wait_timeouts'] += 1."""
    end_time = time.time() + timeout
    snap = ""
    while True:
        snap = _snap()
        if pred(_get_tree(snap)):
            return snap
        if time.time() >= end_time:
            break
        time.sleep(step)
    if count_timeout:
        DIAG["wait_timeouts"] += 1
    return snap


# ── Jev ─────────────────────────────────────────────────────────────────────

def _pick_element(instructions: str, candidates: list, state: str = "") -> Optional[str]:
    """One Jev decision with the p >= 0.6 floor. None means: use the fallback."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    client = jev_client.get_client()
    if not client.started:
        DIAG["jev_fallbacks"] += 1
        return None
    t0 = time.time()
    choice, p = client.pick(instructions, candidates, state)
    DIAG["jev_calls"] += 1
    DIAG["jev_ms"] += int((time.time() - t0) * 1000)
    if choice is None or p < JEV_P_FLOOR or choice not in candidates:
        DIAG["jev_fallbacks"] += 1
        return None
    return choice


def _airport_keywords(code: str) -> list:
    kws = [k.replace("option: ", "").split(",")[0] for k in AIRPORT_PICK.get(code, [])]
    return kws + [code]


def _pick_airport(snap: str, code: str) -> str:
    """Ref of the dropdown suggestion for `code`. Jev decides when the
    dropdown offers several options; the legacy keyword match must agree
    with the choice (guardrail) and is the fallback."""
    tree = _get_tree(snap)
    legacy_ref = _legacy._pick_airport(snap, code)
    candidates = [l.strip() for l in tree.splitlines()
                  if "option:" in l.lower() and re.search(r"\[\d+-\d+\]", l)][:40]
    if len(candidates) >= 2:
        want = (AIRPORT_PICK.get(code) or [code])[0].replace("option: ", "")
        instr = (f"Pick the dropdown entry for '{want}' (airport code {code}). "
                 f"If no entry is named exactly that, pick the one that best matches it; "
                 f"never a different city, region or nearby airport.")
        choice = _pick_element(instr, candidates)
        if choice:
            if any(kw.lower() in choice.lower() for kw in _airport_keywords(code)):
                return "@" + re.findall(r"\[(\d+-\d+)\]", choice)[-1]
            DIAG["jev_fallbacks"] += 1      # Jev disagreed with the keyword guardrail
    return legacy_ref


# ── form steps ──────────────────────────────────────────────────────────────

def _open_form() -> str:
    """Open Google Flights and return a snapshot showing the search form ("" = blank page)."""
    _legacy._ensure_session()
    _run(f"browse open {FLIGHTS_URL}")
    form = lambda t: _has(t, "where from?")
    snap = wait_for(form, timeout=12.0, step=0.5)

    for label in ("Accept all", "I agree", "Accept"):
        ref = _find_ref(snap, f"button: {label}")
        if ref:
            _run(f"browse click {ref}")
            snap = wait_for(form, timeout=5.0)
            break

    if "explore" in _url() or not form(_get_tree(snap)):
        flights_ref = _find_ref(snap, "link: Flights")
        if flights_ref:
            _run(f"browse click {flights_ref}")
        else:
            _run(f"browse open {FLIGHTS_URL}")
        snap = wait_for(form, timeout=10.0, step=0.5)

    if not form(_get_tree(snap)):
        DIAG["blank_pages"] += 1
        _legacy._session_dirty()
        print("  ERROR: Flights page never loaded (blank/stub tree) — local browser problem, NOT a Google block")
        return ""
    return snap


def _set_ticket_type(snap: str, label: str) -> str:
    """label = 'One way' or 'Multi-city'."""
    tt_ref = _find_ref(snap, "Change ticket type")
    if not tt_ref:
        return snap
    _run(f"browse click {tt_ref}")
    snap = wait_for(lambda t: _has(t, f"option: {label}"), timeout=4.0)
    opt_ref = _find_ref(snap, f"option: {label}")
    if opt_ref:
        _run(f"browse click {opt_ref}")
    chosen = lambda t: _has(t, f"change ticket type. {label}") and not _has(t, "option: round trip")
    snap = wait_for(chosen, timeout=4.0)
    if _has(_get_tree(snap), "option: round trip"):        # listbox still open
        _run("browse press Escape")
        snap = wait_for(lambda t: not _has(t, "option: round trip"), timeout=2.0)
    if not _has(_get_tree(snap), f"change ticket type. {label}"):
        print(f"  WARN: trip type may not be {label}")
    return snap


def _set_passengers(snap: str) -> str:
    """2 adults + 1 child."""
    pax_ref = _find_ref(snap, "passenger")
    if not pax_ref:
        return snap
    _run(f"browse click {pax_ref}")
    snap = wait_for(lambda t: _has(t, "button: add adult"), timeout=4.0)
    add_adult = _find_ref(snap, "button: Add adult")
    if add_adult:
        _run(f"browse click {add_adult}")
        time.sleep(0.3)
    snap = _snap()
    add_child = _find_ref(snap, "button: Add child")
    if add_child:
        _run(f"browse click {add_child}")
        time.sleep(0.3)
    snap = _snap()
    done_ref = _find_ref(snap, "button: Done")
    if done_ref:
        _run(f"browse click {done_ref}")
    snap = wait_for(lambda t: _has(t, "3 passengers") and not _has(t, "button: add adult"), timeout=4.0)
    if not _has(_get_tree(snap), "3 passengers"):
        print("  WARN: passenger count may not be 3")
    return snap


def _fill_airport(snap: str, box_ref: str, label: str, code: str, row: int = 0) -> str:
    """Type into a 'Where from?'/'Where to?' box and pick the suggestion."""
    if not box_ref:
        raise RuntimeError(f"no '{label}' box on the form")
    # click → Escape → click: the first click sometimes only focuses the row
    _run(f"browse click {box_ref}"); time.sleep(0.3)
    _run("browse press Escape"); time.sleep(0.2)
    _run(f"browse click {box_ref}"); time.sleep(0.3)
    _run(f"browse type {TYPE_AS.get(code, code)}")
    snap = wait_for(lambda t: bool(_legacy._pick_airport(t, code)), timeout=5.0)
    pick = _pick_airport(snap, code)
    if pick:
        _run(f"browse click {pick}")
    else:
        _run("browse press Enter")
    kws = [k.lower() for k in _airport_keywords(code)]

    def filled(t: str) -> bool:
        boxes = _lines_with(t, label)
        return row < len(boxes) and any(k in boxes[row].lower() for k in kws)

    snap = wait_for(filled, timeout=4.0)
    if not filled(_get_tree(snap)):
        print(f"  WARN: '{label}' may not show {code} after the pick")
    return snap


def _fill_date(snap: str, box_ref: str, depart: str) -> str:
    if not box_ref:
        raise RuntimeError("no 'Departure' box on the form")
    _run(f"browse click {box_ref}"); time.sleep(0.3)
    _run(f'browse type "{depart}"')
    snap = wait_for(lambda t: _has(t, "button: done"), timeout=3.0, count_timeout=False)
    done_ref = _find_ref(snap, "button: Done")
    if done_ref:
        _run(f"browse click {done_ref}")
        snap = wait_for(lambda t: not _has(t, "button: done"), timeout=3.0)
    return snap


def _search(snap: str) -> None:
    search_ref = _find_ref(snap, "button: Search")
    if search_ref:
        _run(f"browse click {search_ref}")
    else:
        _run("browse press Enter")


def _wait_for_results() -> str:
    """Poll at 1 s until prices show, then keep the legacy settle rule: the
    priced-row count must be the same on two snapshots 2 s apart."""
    deadline = time.time() + RESULT_BUDGET_S
    last_n, snap = -1, ""
    while time.time() < deadline:
        snap = _snap()
        n = _get_tree(snap).lower().count("us dollars")
        if n and n == last_n:
            return snap
        last_n = n
        time.sleep(SETTLE_S if n else 1.0)
    DIAG["wait_timeouts"] += 1
    return snap


def _expand_more(snap: str) -> str:
    more_ref = _find_ref(snap, "View more flights")
    if not more_ref:
        return snap
    before = _get_tree(snap).lower().count("us dollars")
    _run(f"browse click {more_ref}")
    snap = wait_for(lambda t: t.lower().count("us dollars") > before, timeout=4.0, step=0.5,
                    count_timeout=False)
    time.sleep(0.5)                       # let the last expanded rows land
    return _snap()


def _verify_fill(tree: str, legs: list) -> bool:
    """The results page must still show every leg's origin, destination and date."""
    tl = tree.lower()
    for origin, dest, depart in legs:
        parts = depart.replace(",", "").split()
        month, day = parts[0], parts[1] if len(parts) > 1 else ""
        date_ok = f"{month} {day}".lower() in tl or f"{month[:3]} {day}".lower() in tl
        origin_ok = any(k.lower() in tl for k in _airport_keywords(origin))
        dest_ok = any(k.lower() in tl for k in _airport_keywords(dest))
        if not (origin_ok and dest_ok and date_ok):
            return False
    return True


def _save_debug(tag: str, url: str, tree: str) -> None:
    with open(DEBUG_TREE_FILE, "w") as f:
        f.write(f"{tag}\nurl: {url}\n\n{tree}")
    print(f"  (tree saved to {DEBUG_TREE_FILE})")


# ── one-way ─────────────────────────────────────────────────────────────────

def scrape_route(origin: str, dest: str, depart: str) -> list:
    """One-way search; any failure re-runs the search through the legacy engine."""
    try:
        return _scrape_route_jev(origin, dest, depart)
    except Exception as e:
        DIAG["engine_fallbacks"] += 1
        print(f"  Jev engine failed ({e}) — falling back to legacy for this search")
        return _legacy.scrape_route(origin, dest, depart)


def _scrape_route_jev(origin: str, dest: str, depart: str) -> list:
    snap = _open_form()
    if not snap:
        raise RuntimeError("blank-page")

    print("  Switching to one-way...")
    snap = _set_ticket_type(snap, "One way")
    print("  Setting passengers: 2 adults + 1 child...")
    snap = _set_passengers(snap)
    print(f"  Filling origin: {origin}...")
    snap = _fill_airport(snap, _find_ref(snap, "Where from"), "Where from?", origin)
    print(f"  Filling destination: {dest}...")
    snap = _fill_airport(snap, _find_ref(snap, "Where to"), "Where to?", dest)
    print(f"  Filling departure date: {depart}...")
    snap = _fill_date(snap, _find_ref(snap, "textbox: Departure"), depart)
    print("  Searching...")
    _search(snap)
    snap = _wait_for_results()
    result_url = _url()
    snap = _expand_more(snap)
    tree = _get_tree(snap)

    results = _legacy._parse_results(tree, origin, dest, result_url, depart)
    print(f"  Parsed {len(results)} flights")
    verified = _verify_fill(tree, [(origin, dest, depart)])
    if not results:
        _save_debug(f"route: {origin}->{dest} {depart} (one-way)", result_url, tree)
        if not verified:
            raise RuntimeError("fill-not-verified")
    elif not verified:
        print("  WARN: fill verification text not found on results page")
    return results


# ── multi-city ──────────────────────────────────────────────────────────────

def _scrape_multicity(legs: list, parse_fn, tag: str) -> list:
    """Fill the multi-city form with (origin, dest, date) legs and parse the
    first-leg selection page. Falls back to the legacy engine on failure."""
    try:
        return _scrape_multicity_jev(legs, parse_fn, tag)
    except Exception as e:
        DIAG["engine_fallbacks"] += 1
        if str(e) not in ("fill-not-verified",):
            _legacy._session_dirty()
        print(f"  Jev engine failed ({e}) — falling back to legacy for this search")
        return _legacy._scrape_multicity(legs, parse_fn, tag)


def _scrape_multicity_jev(legs: list, parse_fn, tag: str) -> list:
    snap = _open_form()
    if not snap:
        raise RuntimeError("blank-page")

    print("  Switching to multi-city...")
    snap = _set_ticket_type(snap, "Multi-city")
    print("  Setting passengers: 2 adults + 1 child...")
    snap = _set_passengers(snap)

    froms = _find_refs(snap, "Where from")
    while len(froms) < len(legs):
        add_ref = _find_ref(snap, "Add flight")
        if not add_ref:
            raise RuntimeError("could not add a flight row to the multi-city form")
        have = len(froms)
        _run(f"browse click {add_ref}")
        snap = wait_for(lambda t: len(_find_refs(t, "Where from")) > have, timeout=3.0)
        froms = _find_refs(snap, "Where from")

    for i, (o, d, dep) in enumerate(legs):
        print(f"  Row {i + 1}: {o}→{d} {dep}")
        froms = _find_refs(snap, "Where from")
        if i >= len(froms):
            raise RuntimeError("multi-city form has too few flight rows")
        snap = _fill_airport(snap, froms[i], "Where from?", o, row=i)
        tos = _find_refs(snap, "Where to")
        snap = _fill_airport(snap, tos[i] if i < len(tos) else "", "Where to?", d, row=i)
        deps = _find_refs(snap, "textbox: Departure")
        snap = _fill_date(snap, deps[i] if i < len(deps) else "", dep)

    print("  Searching...")
    _search(snap)
    snap = _wait_for_results()
    result_url = _url()
    snap = _expand_more(snap)
    tree = _get_tree(snap)

    results = parse_fn(tree, result_url)
    print(f"  Parsed {len(results)} multi-city options")
    verified = _verify_fill(tree, legs)
    if not results:
        _save_debug(tag, result_url, tree)
        if not verified:
            raise RuntimeError("fill-not-verified")
    elif not verified:
        print("  WARN: fill verification text not found on results page")
    return results


# ── wrappers (mirror scraper.py, routed to the engine above) ────────────────

def scrape_stopover(cfg=None) -> list:
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
    all_results = []
    for cfg in STOPOVER_SEARCHES:
        print(f"[{cfg['kind']}] {cfg['label']}")
        results, thin_retried = [], False
        for attempt in range(1, _legacy.TICKET1_ATTEMPTS + 1):
            got = scrape_stopover(cfg)
            if len(got) > len(results):
                results = got
            if len(results) >= _legacy.THIN_TICKET1_OPTIONS:
                break
            if results and thin_retried:
                break
            if results:
                thin_retried = True
                print(f"  only {len(results)} options (attempt {attempt}/{_legacy.TICKET1_ATTEMPTS}) "
                      f"— page may be half-rendered, retrying once with a fresh session...")
                _legacy._session_dirty()
            else:
                print(f"  0 results (attempt {attempt}/{_legacy.TICKET1_ATTEMPTS}) — retrying with a fresh session...")
            time.sleep(5)
        all_results += results
        print(f"  Got {len(results)} options")
    return all_results


def scrape_sg_tickets_all() -> list:
    all_results = []
    for i, (order, d1, d2) in enumerate(TICKET2_SEARCHES, 1):
        print(f"[ticket2 {i}/{len(TICKET2_SEARCHES)}] {order} {d1} + {d2}")
        (o1, dst1), (o2, dst2) = _legacy.ORDER_ROUTES[order]
        legs = [(o1, dst1, d1), (o2, dst2, d2)]

        def parse(tree, url, d1=d1, d2=d2, order=order, o1=o1, dst1=dst1, dst2=dst2):
            out = []
            for f in _legacy._parse_openjaw_results(tree, d1, d2, url):
                f.update(kind="sg-ticket", order=order, route=f"{o1}→{dst1}→{dst2}")
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
                    f"one-way legs: {remaining} of {total} searches (past {RUN_DEADLINE_MIN} min)")
                print(f"DEADLINE: skipping remaining {remaining} one-way searches")
                return all_results
            n += 1
            print(f"[{n}/{total}] {origin}→{dest}  {depart} (one-way)")
            results = scrape_route(origin, dest, depart)
            if not results:
                print("  0 results — retrying route once with a fresh session...")
                time.sleep(5)
                results = scrape_route(origin, dest, depart)
            all_results += results
            print(f"  Got {len(results)} results")

            consecutive_failures = 0 if results else consecutive_failures + 1
            if consecutive_failures >= 4:
                DIAG["aborted_early"] = True
                print(f"ABORTING: {consecutive_failures} consecutive routes returned 0 results "
                      f"(timeouts={DIAG['timeouts']}, blank_pages={DIAG['blank_pages']})")
                return all_results
    return all_results


def scrape_bali_watch():
    if _past_deadline():
        DIAG["deadline_skips"].append(
            f"🌴 Bali watch: all 3 searches (past {RUN_DEADLINE_MIN} min)")
        print("DEADLINE: skipping Bali watch entirely")
        return [], [], []
    print("[bali-watch] Ticket ① (DPS return)")
    tickets1 = scrape_stopover(_legacy.ISTANBUL2_SEARCH)
    fwd, rev = [], []
    for i, (direction, d1, d2) in enumerate(_legacy.BALI_WATCH_PAIRS, 1):
        print(f"[bali-watch {direction} {i}/{len(_legacy.BALI_WATCH_PAIRS)}] {d1} + {d2}")
        if direction == "fwd":
            legs = [("DAC", "SIN", d1), ("SIN", "DPS", d2)]
        else:
            legs = [("DAC", "DPS", d1), ("DPS", "SIN", d2)]

        def parse(tree, url, d1=d1, d2=d2, direction=direction):
            out = []
            for f in _legacy._parse_openjaw_results(tree, d1, d2, url):
                f.update(kind="sg-ticket",
                         route="DAC→SIN→DPS" if direction == "fwd" else "DAC→DPS→SIN")
                out.append(f)
            return out

        tag = f"bali-{direction}: {legs[0][0]}->{legs[0][1]} {d1} + {legs[1][0]}->{legs[1][1]} {d2}"
        r = _scrape_multicity(legs, parse, tag)
        if not r:
            time.sleep(5)
            r = _scrape_multicity(legs, parse, tag)
        (fwd if direction == "fwd" else rev).extend(r)
    return tickets1, fwd, rev
