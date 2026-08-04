"""Nightly public nightly-rate refresh for the IST/SIN card-play shortlist.

WHY THIS EXISTS (2026-08-03): the shortlist's nightly rates were hand-researched
on 2026-08-01 and then sat frozen in the site's HTML with no provenance. By
2026-08-03 two of them were ~30% low against live Google Hotels for the real
stay dates (Ritz-Carlton Istanbul $314 → $425; Sanasaryan Han $270 → $348), so
the offset bands they drive were wrong too.

WHAT THIS CAN AND CANNOT SEE — read before trusting a number:
  * The rates the card play actually books (Amex FHR, Chase "The Edit") sit
    behind CARDHOLDER LOGINS. They are not scrapable and never will be from
    here. What this module tracks is the PUBLIC nightly rate incl. fees from
    Google Hotels for the same property and the same dates. FHR/Edit rates
    normally sit near the flexible/BAR rate, so the public rate is a good
    drift alarm and a good offset denominator — but the booking rate must be
    confirmed in the portal.
  * Google Hotels throttles. A blocked or slow night must NEVER publish a
    guess: every rate carries its own `checked` date, a failed refresh keeps
    the last good value, and the site shows how old each figure is.

FAIL-CLOSED DATE GUARD (the whole point): a Google Hotels query can silently
land on a search page with NO dates bound, or on a different property, and it
still renders plausible prices. Verified live 2026-08-03: "Sanasaryan Han
Luxury Collection Istanbul" → "No results" with empty date fields, while
"Sanasaryan Han Istanbul" → correct entity with Jan 5–7 bound. So a scraped
price is accepted ONLY when the page proves BOTH the property and the dates.
Anything else returns None and the previous value is kept.
"""
import datetime
import json
import os
import re

CREDITS_NOTE = ("$300 Amex (or $250 Edit) + $100 property + $60/day breakfast")
TAX_RATE = 0.12          # the ~12% the offset math has always assumed

# Per-stay credit pools, matching the site's long-standing assumption line.
CREDIT_POOL = {
    ("IST", 2): 520,
    ("SIN", 2): 520,     # FHR; Edit variant is 470
    ("SIN", 4): 640,     # FHR; Edit variant is 590
}
CREDIT_POOL_EDIT = {("SIN", 2): 470, ("SIN", 4): 590}

# The shortlist. `query` is the Google Hotels search string — keep it SHORT;
# long official names fall through to a no-results search page (proven
# 2026-08-03). `match` is the substring the resolved page title must contain,
# so a query that drifts to a different hotel is rejected rather than trusted.
SHORTLIST = [
    {"key": "sanasaryan", "city": "IST", "program": "FHR",
     "name": "Sanasaryan Han (Lux. Coll.)", "query": "Sanasaryan Han Istanbul",
     "match": "Sanasaryan", "angle": "Old-city boutique · Bonvoy stacks"},
    {"key": "ritz_ist", "city": "IST", "program": "FHR", "bold": True,
     "name": "Ritz-Carlton Istanbul", "query": "Ritz Carlton Istanbul",
     "match": "Ritz-Carlton", "angle": "Value pick · Bonvoy Platinum stacks (points + elite nights)"},
    {"key": "stregis_ist", "city": "IST", "program": "FHR",
     "name": "St. Regis Istanbul", "query": "St Regis Istanbul Nisantasi",
     "match": "St. Regis", "angle": "Butler with every room · Bonvoy stacks"},
    {"key": "ciragan", "city": "IST", "program": "FHR",
     "name": "Çırağan Palace Kempinski", "query": "Ciragan Palace Kempinski",
     "match": "Kempinski", "angle": "The sentimental splurge · Bosphorus palace, the favorite brand"},
    {"key": "panpacific", "city": "SIN", "program": "THC + Edit",
     "name": "Pan Pacific Orchard", "query": "Pan Pacific Orchard Singapore",
     "match": "Pan Pacific Orchard",
     "angle": "Wildcard · CSR select-hotels credit may stack (see note)"},
    {"key": "stregis_sin", "city": "SIN", "program": "FHR", "bold": True,
     "name": "St. Regis Singapore", "query": "St Regis Singapore",
     "match": "St. Regis", "angle": "Butler standard · Bonvoy stacks · cheap for SIN luxury"},
    {"key": "ritz_sin", "city": "SIN", "program": "FHR",
     "name": "Ritz-Carlton Millenia", "query": "Ritz Carlton Millenia Singapore",
     "match": "Ritz-Carlton", "angle": "Marina views · Bonvoy stacks"},
    {"key": "jw_sin", "city": "SIN", "program": "The Edit only",
     "name": "JW Marriott South Beach", "query": "JW Marriott South Beach Singapore",
     "match": "JW Marriott", "angle": "Best Edit-exclusive if the fallback strategy is needed"},
]

# Seed values. Rates carrying `checked` 2026-08-01 are the ORIGINAL hand
# research; 2026-08-03 entries were re-verified live that evening against
# Google Hotels for the real stay dates. The nightly job overwrites these.
SEED = {
    "sanasaryan":  {"rate": 348, "checked": "2026-08-03"},
    "ritz_ist":    {"rate": 425, "checked": "2026-08-03"},
    "stregis_ist": {"rate": 525, "checked": "2026-08-01"},
    "ciragan":     {"rate": 726, "checked": "2026-08-01"},
    "panpacific":  {"rate": 252, "checked": "2026-08-01"},
    "stregis_sin": {"rate": 329, "checked": "2026-08-01"},
    "ritz_sin":    {"rate": 420, "checked": "2026-08-01"},
    "jw_sin":      {"rate": 497, "checked": "2026-08-01"},
}

RATES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "site", "hotel_rates.json")
DEBUG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "debug_last_hotel.txt")

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def offset_pct(rate, nights, credits):
    """Credits ÷ (room + tax) as a whole-number percent. None-safe."""
    if not isinstance(rate, (int, float)) or rate <= 0 or not nights:
        return None
    return round(100 * credits / (rate * nights * (1 + TAX_RATE)))


def band(pct):
    """The July deal-calculator bands: >=70 book now, 50-70 solid, <50 wait."""
    if pct is None:
        return "dim"
    return "good" if pct >= 70 else ("dim" if pct < 50 else "warn")


def _label(d):
    """'2027-01-05' -> 'Jan 5' — the form Google renders in its date chips."""
    return f"{_MONTHS[d.month - 1]} {d.day}"


def _range_pattern(checkin, checkout):
    """Google collapses a same-month stay to 'Jan 5 – 7' and only spells the
    second month when the stay crosses one ('Jan 31 – Feb 2'). Matching the
    wrong shape would make every page look like a date mismatch."""
    m1, d1 = _MONTHS[checkin.month - 1], checkin.day
    m2, d2 = _MONTHS[checkout.month - 1], checkout.day
    if (checkin.month, checkin.year) == (checkout.month, checkout.year):
        return rf"{m1}\s+{d1}\s*[–—-]\s*{d2}\b"
    return rf"{m1}\s+{d1}\s*[–—-]\s*{m2}\s+{d2}\b"


def google_url(query, checkin, checkout):
    q = query.replace(" ", "+")
    return (f"https://www.google.com/travel/search?q={q}"
            f"&checkin={checkin.isoformat()}&checkout={checkout.isoformat()}"
            f"&hl=en&curr=USD&gl=us")


def parse_rate(tree, title, entry, checkin, checkout):
    """Return (rate, note). rate is None unless the page proves BOTH the
    property and the requested dates — a page that merely *looks* like a hotel
    result is exactly how a wrong number gets published."""
    if not tree or len(tree.splitlines()) < 40:
        return None, "empty page (throttled or still loading)"
    if entry["match"].lower() not in (title or "").lower():
        return None, f"resolved to '{(title or '?')[:40]}', expected {entry['match']}"
    if re.search(r"\bNo results\b", tree):
        return None, "search returned no results"

    want = _range_pattern(checkin, checkout)
    if not re.search(want, tree):
        return None, (f"page never showed {_label(checkin)}–{_label(checkout)}; "
                      "dates did not bind")
    # Price must sit next to the confirmed date range, never picked up loose
    # from the sidebar (which lists OTHER hotels' prices).
    m = re.search(r"\$([\d,]+)\s*\n?\s*" + want, tree)
    if not m:
        m = re.search(want + r"[^$\n]{0,40}\$([\d,]+)", tree)
    if not m:
        return None, "dates confirmed but no price anchored to them"
    try:
        return int(m.group(1).replace(",", "")), "ok"
    except ValueError:
        return None, f"unparseable price {m.group(1)!r}"


def scrape_rate(entry, checkin, checkout, scraper=None):
    """One property. Never raises — a failure is a (None, reason) pair."""
    if scraper is None:
        import scraper as scraper_mod
        scraper = scraper_mod
    url = google_url(entry["query"], checkin, checkout)
    try:
        scraper._run(f'browse open "{url}"')
        import time
        time.sleep(8)
        raw = scraper._snap()
        tree = scraper._get_tree(raw)
        title = ""
        for line in tree.splitlines():
            if "RootWebArea" in line:
                title = line.split("RootWebArea:", 1)[-1].strip()
                break
        rate, note = parse_rate(tree, title, entry, checkin, checkout)
        if rate is None:
            try:
                with open(DEBUG_FILE, "w") as f:
                    f.write(f"{entry['key']} :: {note}\n{url}\n\n{tree[:20000]}")
            except Exception:
                pass
        return rate, note
    except Exception as e:                       # noqa: BLE001 — never kill a run
        return None, f"crashed: {e}"


def stay_windows(payload):
    """The real stay dates, derived from tonight's winning trip.
    Istanbul is fixed by Ticket ①; Singapore follows whichever order won."""
    out = {"IST": None, "SIN": None}
    try:
        main = (payload or {}).get("main") or {}
        oj = main.get("openjaw") or {}
        # Istanbul: land the day after the BOS departure, leave the day before
        # the Dhaka arrival — the same arithmetic the trip plan renders.
        dep = _parse(oj.get("out_date"))
        dac_in = _parse(oj.get("out_arrive"))
        if dep and dac_in:
            ist_in = dep + datetime.timedelta(days=1)
            ist_out = dac_in - datetime.timedelta(days=1)
            if ist_out > ist_in:
                out["IST"] = (ist_in, ist_out,
                              main.get("ist_nights") or (ist_out - ist_in).days)
        order = main.get("order")
        sg_nights = main.get("sg_nights")
        legs = {l.get("route"): l for l in (main.get("legs") or [])}
        tkt = main.get("sg_ticket") or {}
        if order == "BKK-first":
            sin_in = _parse(tkt.get("ret_date")) or _parse(
                (legs.get("BKK→SIN") or {}).get("depart"))
            sin_out = _parse(oj.get("ret_date"))
        else:
            sin_in = _parse(tkt.get("out_date")) or _parse(
                (legs.get("DAC→SIN") or {}).get("depart"))
            sin_out = _parse((legs.get("SIN→BKK") or {}).get("depart")) or (
                _parse(tkt.get("ret_date")))
        if sin_in and sin_out and sin_out > sin_in:
            out["SIN"] = (sin_in, sin_out, sg_nights or (sin_out - sin_in).days)
    except Exception:                            # noqa: BLE001
        pass
    return out


def _parse(s):
    if not s:
        return None
    for fmt in ("%B %d, %Y", "%Y-%m-%d", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def load_previous():
    try:
        with open(RATES_FILE) as f:
            data = json.load(f)
        return {r["key"]: r for r in data.get("rows", []) if r.get("key")}
    except Exception:                            # noqa: BLE001
        return {}


def build(payload, scraped=None, today=None):
    """Merge freshly scraped rates over the last-known ones and compute the
    offsets. A property with no fresh rate keeps its previous value AND its
    previous `checked` date, so staleness is always visible."""
    today = today or datetime.date.today().isoformat()
    previous = load_previous()
    scraped = scraped or {}
    windows = stay_windows(payload)
    rows, notes = [], []
    for e in SHORTLIST:
        prev = previous.get(e["key"]) or SEED.get(e["key"]) or {}
        fresh = scraped.get(e["key"])
        if fresh and fresh[0]:
            rate, checked = fresh[0], today
        else:
            rate, checked = prev.get("rate"), prev.get("checked")
            if fresh and fresh[1] and fresh[1] != "ok":
                notes.append(f"{e['name']}: {fresh[1]}")
        win = windows.get(e["city"])
        nights = win[2] if win else (2 if e["city"] == "IST" else None)
        row = {"key": e["key"], "city": e["city"], "name": e["name"],
               "program": e["program"], "angle": e["angle"],
               "bold": bool(e.get("bold")), "rate": rate, "checked": checked}
        if e["city"] == "IST":
            pct = offset_pct(rate, nights or 2, CREDIT_POOL[("IST", 2)])
            row["offsets"] = [{"label": f"{nights or 2}n", "pct": pct, "band": band(pct)}]
        else:
            row["offsets"] = []
            for n in (2, 4):
                # Anything booked through Chase's Edit draws the $250 Edit
                # credit, not the $300 Amex one — that is what makes Pan
                # Pacific 2n read 83% and not 92%.
                pool = (CREDIT_POOL_EDIT if "Edit" in e["program"]
                        else CREDIT_POOL)[("SIN", n)]
                pct = offset_pct(rate, n, pool)
                row["offsets"].append({"label": f"{n}n", "pct": pct, "band": band(pct)})
        rows.append(row)
    return {
        "updated": today,
        "stays": {c: ({"checkin": w[0].isoformat(), "checkout": w[1].isoformat(),
                       "nights": w[2]} if w else None)
                  for c, w in windows.items()},
        "credits_note": CREDITS_NOTE,
        "source": ("public nightly rate incl. fees, Google Hotels, same dates — "
                   "FHR/Edit rates are login-gated and must be confirmed in the portal"),
        "rows": rows,
        "notes": notes,
    }


def write(data):
    """Atomic write — a half-written file would blank the site's table."""
    os.makedirs(os.path.dirname(RATES_FILE), exist_ok=True)
    tmp = RATES_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, RATES_FILE)
