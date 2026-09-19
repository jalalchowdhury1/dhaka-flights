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
FULL_LIST_ROWS = 10        # priced rows at which a one-way list counts as already expanded
ONEWAY_READY_CAP_S = 14.0  # wait this long for the expander before taking the page as is
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
    print("jev diag: " + " ".join(
        f"{k}={DIAG.get(k, 0)}" for k in (
            "jev_calls", "jev_ms", "jev_fallbacks", "pick_retries",
            "judge_disagreements", "engine_fallbacks", "wait_timeouts")))


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


def _pick_keywords(code: str) -> list:
    """The legacy pick keywords, exact ('Bangkok, Thailand', not 'Bangkok')."""
    return [k.replace("option: ", "") for k in AIRPORT_PICK.get(code, [])] + [code]


def _airport_keywords(code: str) -> list:
    """Loose names for checking a filled box / results page ('Bangkok')."""
    return [k.split(",")[0] for k in _pick_keywords(code)]


def _ref_of(line: str) -> str:
    refs = re.findall(r"\[(\d+-\d+)\]", line)
    return "@" + refs[-1] if refs else ""


def _pick_airport(snap: str, code: str) -> str:
    """Ref of the dropdown suggestion for `code`.

    The legacy rule (first option line matching the first keyword) has run
    nightly for months, so when it is unambiguous it is used as-is. Jev
    decides only when the keyword filter leaves several options or none,
    and its choice must still contain one of the keywords (guardrail)."""
    tree = _get_tree(snap)
    options = [l.strip() for l in tree.splitlines()
               if "option:" in l.lower() and re.search(r"\[\d+-\d+\]", l)][:40]
    kws = [k.lower() for k in _pick_keywords(code)]
    first_kw = [l for l in options if kws[0] in l.lower()]
    if len(first_kw) == 1:
        return _ref_of(first_kw[0])
    keyword_hits = [l for l in options if any(k in l.lower() for k in kws)]
    if len(keyword_hits) == 1:
        return _ref_of(keyword_hits[0])
    legacy_ref = _legacy._pick_airport(snap, code)
    if len(options) >= 2:
        want = _pick_keywords(code)[0]
        instr = (f"Pick the dropdown entry for '{want}' (airport code {code}). "
                 f"If no entry is named exactly that, pick the one that best matches it; "
                 f"never a different city, region or nearby airport.")
        choice = _pick_element(instr, options)
        if choice:
            if any(k in choice.lower() for k in kws):
                return _ref_of(choice)
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


def _box_ref(label: str, row: int) -> str:
    """Fresh ref for the row-th box labelled `label` (refs go stale whenever
    the form re-renders, so resolve right before clicking)."""
    refs = _find_refs(_snap(), label)
    return refs[row] if row < len(refs) else ""


def _box_shows(tree: str, label: str, row: int, names: list) -> bool:
    """Google puts the chosen value either on the combobox line itself
    ('combobox: Where to? Dhaka DAC') or on the child line below it
    ('combobox: Where to?' / 'StaticText: Bangkok')."""
    lines = tree.splitlines()
    idx = [i for i, l in enumerate(lines) if label.lower() in l.lower()]
    if row >= len(idx):
        return False
    text = " ".join(lines[idx[row]:idx[row] + 3]).lower()
    return any(n.lower() in text for n in names)


def _pick_settled(tree: str, label: str, row: int, names: list) -> bool:
    """The box shows the airport AND the suggestion list has closed. While the
    dropdown is still open the typed text alone already satisfies _box_shows,
    and the open list hides the Departure box (19 Sep 2026 nightly)."""
    return _box_shows(tree, label, row, names) and "option:" not in tree.lower()


def _form_region(tree: str, label: str, row: int, before: int = 6, after: int = 40) -> str:
    """The lines around the row-th `label` box: the box, its value and any open
    suggestion list beneath it — the state Jev judges a pick from."""
    lines = tree.splitlines()
    idx = [i for i, l in enumerate(lines) if label.lower() in l.lower()]
    if row >= len(idx):
        return tree[:4000]
    i = idx[row]
    return "\n".join(l.strip() for l in lines[max(0, i - before):i + after])


PICK_VERDICTS = {
    "settled": "The box shows the wanted airport/city and NO suggestion list "
               "(no 'option:' lines) is open beneath it — the pick has landed",
    "dropdown-open": "A suggestion list with 'option:' lines is still open under "
                     "the box — the pick did not land yet",
    "wrong-or-empty": "The box is empty or shows a different city/airport",
}


def _judge_pick(tree: str, label: str, row: int, code: str, names: list) -> bool:
    """Jev decides whether the airport pick landed, from the live form region.
    The deterministic rule answers only when Jev is unavailable or unsure, and
    every disagreement between the two is counted in DIAG."""
    rule = _pick_settled(tree, label, row, names)
    instr = (f"Google Flights search form. We typed into the '{label}' box (row {row + 1}) "
             f"to select {names[0]} ({code}) and clicked a suggestion. "
             f"Which statement describes the current state of that box?")
    choice = _pick_element(instr, list(PICK_VERDICTS.values()), state=_form_region(tree, label, row))
    if choice is None:
        return rule
    verdict = next(k for k, v in PICK_VERDICTS.items() if v == choice)
    settled = verdict == "settled"
    if settled != rule:
        DIAG["judge_disagreements"] = DIAG.get("judge_disagreements", 0) + 1
        print(f"  jev judged '{label}' {code} as {verdict} (rule said {'settled' if rule else 'not settled'})")
    return settled


def _fill_airport(label: str, code: str, row: int = 0) -> str:
    """Type into the row-th 'Where from?'/'Where to?' box and pick the suggestion.

    The suggestion list re-renders while Google's autocomplete answers, so a
    pick ref taken a moment ago can be stale ("Unknown ref") and leave the
    dropdown open over the form. If the box does not show the airport after
    the pick, Escape and redo the whole fill once before giving up (18 Sep
    full run: two Ticket 1 searches fell back to legacy on exactly this)."""
    names = _airport_keywords(code)
    snap = ""
    for attempt in (1, 2):
        box_ref = ""
        for _ in range(3):                    # an open dropdown can hide the boxes briefly
            box_ref = _box_ref(label, row)
            if box_ref:
                break
            _run("browse press Escape"); time.sleep(0.5)
        if not box_ref:
            raise RuntimeError(f"no '{label}' box on the form")
        # click → Escape → click: the first click sometimes only focuses the row
        _run(f"browse click {box_ref}"); time.sleep(0.3)
        _run("browse press Escape"); time.sleep(0.2)
        box_ref = _box_ref(label, row) or box_ref
        _run(f"browse click {box_ref}"); time.sleep(0.3)
        _run(f"browse type {TYPE_AS.get(code, code)}")
        snap = wait_for(lambda t: bool(_legacy._pick_airport(t, code)), timeout=5.0)
        pick = _pick_airport(snap, code)
        if pick:
            _run(f"browse click {pick}")
        else:
            _run("browse press Enter")
        snap = wait_for(lambda t: _pick_settled(t, label, row, names), timeout=4.0)
        if _judge_pick(_get_tree(snap), label, row, code, names):
            return snap
        if attempt == 1:
            print(f"  retrying '{label}' {code} once (the pick did not stick)")
            DIAG["pick_retries"] = DIAG.get("pick_retries", 0) + 1
            _run("browse press Escape"); time.sleep(0.5)
    print(f"  WARN: '{label}' may not show {code} after the pick")
    return snap


def _fill_date(depart: str, row: int = 0) -> str:
    box_ref = _box_ref("textbox: Departure", row)
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


def _count_prices(snap: str) -> int:
    return _get_tree(snap).lower().count("us dollars")


def _has_more_button_or_full(snap: str) -> bool:
    """One-way page is 'whole' once the expander is showing, or the list is
    already long. Top flights alone (5-7 rows) look settled but hide the cheap
    ones behind 'View more flights' (A/B 18 Sep: a 7-flight read missed $746)."""
    return bool(_find_ref(snap, "View more flights")) or _count_prices(snap) >= FULL_LIST_ROWS


def _wait_for_results(stable_polls: int = 1, min_wait: float = 0.0,
                      ready=None, ready_cap_s: float = 0.0) -> str:
    """Poll at 1 s until prices show, then keep the legacy settle rule: the
    priced-row count must be unchanged across `stable_polls` consecutive
    checks 2 s apart. Multi-city pages render their itineraries in slow
    bursts, so they use 2 stable polls and a minimum wait (legacy slept a
    blind 10 s there and still saw half-rendered pages).

    `ready(snap)` is an extra condition that must also hold before we settle,
    but only until `ready_cap_s` seconds have passed (then the page is taken
    as it is - some result lists genuinely have no expander)."""
    t0 = time.time()
    deadline = t0 + RESULT_BUDGET_S
    last_n, stable, snap = -1, 0, ""
    while time.time() < deadline:
        snap = _snap()
        n = _count_prices(snap)
        stable = stable + 1 if (n and n == last_n) else 0
        if stable >= stable_polls and time.time() - t0 >= min_wait:
            if ready is None or ready(snap) or time.time() - t0 >= ready_cap_s:
                return snap
        last_n = n
        time.sleep(SETTLE_S if n else 1.0)
    DIAG["wait_timeouts"] += 1
    return snap


def _expand_more(snap: str, stable_polls: int = 1) -> str:
    more_ref = _find_ref(snap, "View more flights")
    if not more_ref:
        return snap
    before = _count_prices(snap)
    _run(f"browse click {more_ref}")
    snap = wait_for(lambda t: t.lower().count("us dollars") > before, timeout=4.0, step=0.5,
                    count_timeout=False)
    last_n, stable = _count_prices(snap), 0
    for _ in range(4):                    # expanded rows land in bursts too
        time.sleep(1.0)
        snap = _snap()
        n = _count_prices(snap)
        stable = stable + 1 if n == last_n else 0
        last_n = n
        if stable >= stable_polls:
            break
    return snap


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
    _fill_airport("Where from?", origin)
    print(f"  Filling destination: {dest}...")
    _fill_airport("Where to?", dest)
    print(f"  Filling departure date: {depart}...")
    snap = _fill_date(depart)
    print("  Searching...")
    _search(snap)
    snap = _wait_for_results(stable_polls=2, ready=_has_more_button_or_full,
                             ready_cap_s=ONEWAY_READY_CAP_S)
    result_url = _url()
    snap = _expand_more(snap, stable_polls=2)
    tree = _get_tree(snap)

    results = _legacy._parse_results(tree, origin, dest, result_url, depart)
    print(f"  Parsed {len(results)} flights")
    if 0 < len(results) < 8:
        _save_debug(f"THIN one-way {origin}->{dest} {depart}: {len(results)} flights", result_url, tree)
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

    if len(_find_refs(snap, "Where from")) < len(legs):
        raise RuntimeError("multi-city form has too few flight rows")
    for i, (o, d, dep) in enumerate(legs):
        print(f"  Row {i + 1}: {o}→{d} {dep}")
        _fill_airport("Where from?", o, row=i)
        _fill_airport("Where to?", d, row=i)
        snap = _fill_date(dep, row=i)

    print("  Searching...")
    _search(snap)
    snap = _wait_for_results(stable_polls=2, min_wait=8.0)
    result_url = _url()
    snap = _expand_more(snap, stable_polls=2)
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
