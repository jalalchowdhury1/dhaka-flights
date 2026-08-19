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
import base64
import datetime
import json
import os
import random
import re
import time
import urllib.parse

CREDITS_NOTE = ("$300 Amex (or $250 Edit) + $100 property + $60/day breakfast")
TAX_RATE = 0.12          # the ~12% the offset math has always assumed

# Per-stay credit pools, matching the site's long-standing assumption line.
CREDIT_POOL = {
    ("IST", 2): 520,
    ("SIN", 2): 520,     # FHR; Edit variant is 470
    ("SIN", 4): 640,     # FHR; Edit variant is 590
}
CREDIT_POOL_EDIT = {("SIN", 2): 470, ("SIN", 4): 590}

# 🏨 Morning movers alert (Jalal 2026-08-19: "give me any major changes in
# hotel prices"). A mover = the rate changed ≥ MOVE_ALERT_PCT% of its old
# value OR ≥ $MOVE_ALERT_ABS/night — either fires. Lives in this job (not the
# midnight brief) because rates refresh at 5am, hours after the brief is
# built; here old and new are both in hand and the alert lands pre-wake-up.
MOVE_ALERT_PCT = 10
MOVE_ALERT_ABS = 40


def rate_moves(prev, new):
    """Major nightly movers: [(name, old_rate, new_rate)]. A kept-stale row
    never registers (fail-closed keeps the old number verbatim), so this only
    ever reports genuinely re-checked rates. None-safe on both sides."""
    old = {r.get("key"): r.get("rate") for r in (prev or {}).get("rows", [])}
    out = []
    for r in (new or {}).get("rows", []):
        o, n = old.get(r.get("key")), r.get("rate")
        if not (isinstance(o, (int, float)) and isinstance(n, (int, float))):
            continue
        if abs(n - o) >= MOVE_ALERT_ABS or abs(n - o) / o * 100 >= MOVE_ALERT_PCT:
            out.append((r.get("name") or r.get("key"), o, n))
    return out


def moves_message(moves):
    """One compact Telegram line for the movers, or None when quiet."""
    if not moves:
        return None
    parts = []
    for name, o, n in moves:
        pct = round(abs(n - o) / o * 100)
        arrow = "▼" if n < o else "▲"
        parts.append(f"{name} ${o:,.0f}→${n:,.0f} ({arrow}{pct}%)")
    return "🏨 Hotel rate moves: " + " · ".join(parts)

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


GUESTS = 2          # the shortlist has always been quoted at 2-guest rates;
                    # keep it fixed so night-over-night drift is comparable.


def _varint(n):
    out = b""
    while True:
        b_ = n & 0x7F
        n >>= 7
        out += bytes([b_ | (0x80 if n else 0)])
        if not n:
            return out


def _field(num, payload, wire=2):
    head = bytes([num << 3 | wire])
    return head + (_varint(len(payload)) + payload if wire == 2 else payload)


def _date_msg(d):
    return (_field(1, _varint(d.year), 0) + _field(2, _varint(d.month), 0)
            + _field(3, _varint(d.day), 0))


def ts_param(checkin, checkout, guests=GUESTS):
    """Google Hotels' `ts` parameter, built from scratch.

    THIS IS THE FIX for the silent-wrong-dates bug. `&checkin=/&checkout=` are
    honoured only in a browser that already carries Google session state; in a
    clean automated session they are DROPPED and the page quietly prices
    TONIGHT instead (verified 2026-08-03: a Jan-2027 request rendered
    "Sun, Aug 9 / Mon, Aug 10"). `ts` is a protobuf that carries the dates
    inside the URL, so it binds with no cookies at all — decoded from a working
    URL and re-encoded byte-identically before being trusted."""
    dates = _field(1, _date_msg(checkin)) + _field(2, _date_msg(checkout))
    inner = _field(2, dates) + _field(6, _field(1, _varint(guests), 0))
    body = _field(3, _field(2, inner))
    currency = _field(5, _field(1, _field(7, b"USD")))
    blob = _field(1, _varint(0), 0) + body + currency
    return base64.urlsafe_b64encode(blob).decode().rstrip("=")


def google_url(query, checkin, checkout, guests=GUESTS):
    q = urllib.parse.quote_plus(query)
    return (f"https://www.google.com/travel/search?q={q}"
            f"&ts={ts_param(checkin, checkout, guests)}"
            f"&hl=en&curr=USD&gl=us")


# Read the page through ONE tiny eval rather than a full accessibility
# snapshot. The snapshot of a Google Hotels page is ~5 MB and repeatedly blew
# the 30 s CLI timeout; this returns ~150 bytes. (carmax-scraper learned the
# same lesson on kbb.com: read via `browse eval` + innerText, never a dump.)
EXTRACT_JS = """(function(){
  var t = document.body.innerText || "";
  var inp = [].slice.call(document.querySelectorAll("input"))
              .map(function(i){return i.value}).filter(Boolean);
  /* Allow a short badge between the price and the date chip ("GREAT DEAL"),
     but never skip over another "$" — that would let a sidebar hotel price
     attach itself to our date range. Use ONLY block comments here and no
     apostrophes: this source is flattened to a single line and shell-quoted,
     so a line comment would swallow the rest of the function. */
  var m = t.match(new RegExp("\\\\$([\\\\d,]+)[^$]{0,40}?%s"));
  return JSON.stringify({title: document.title,
                         checkin: inp[0] || "", checkout: inp[1] || "",
                         price: m ? m[1] : null, len: t.length});
})()"""


def parse_rate(payload, entry, checkin, checkout):
    """Return (rate, note) from the EXTRACT_JS payload.

    rate is None unless the page proves BOTH the property and the requested
    dates. The date proof reads Google's own check-in/check-out fields, which
    is the only signal that survives a silently-defaulted URL: the page still
    renders a perfectly plausible price for tonight, so trusting the price
    alone is how a wrong number gets published."""
    if not isinstance(payload, dict):
        return None, "no page payload (throttled, blocked or still loading)"
    if not payload.get("len"):
        return None, "page rendered empty (throttled or blocked)"
    title = payload.get("title") or ""
    if entry["match"].lower() not in title.lower():
        return None, f"resolved to '{title[:40]}', expected {entry['match']}"

    want_in, want_out = _label(checkin), _label(checkout)
    got_in = payload.get("checkin") or ""
    got_out = payload.get("checkout") or ""
    if want_in not in got_in or want_out not in got_out:
        return None, (f"dates did not bind — page shows "
                      f"'{got_in or '?'}'→'{got_out or '?'}', wanted "
                      f"{want_in}→{want_out}")
    price = payload.get("price")
    if not price:
        return None, "dates bound but no price anchored to them"
    try:
        rate = int(str(price).replace(",", ""))
    except ValueError:
        return None, f"unparseable price {price!r}"
    if not 20 <= rate <= 20000:
        return None, f"implausible nightly rate ${rate}"
    return rate, "ok"


def _eval_payload(scraper, checkin, checkout):
    """Run EXTRACT_JS and decode it. browse wraps the result as {"result": str}."""
    js = EXTRACT_JS % _range_pattern(checkin, checkout).replace("\\", "\\\\")
    raw = scraper._run("browse eval " + _shquote(js.replace("\n", " ")))
    if not raw:
        return None
    try:
        outer = json.loads(raw)
        inner = outer.get("result") if isinstance(outer, dict) else outer
        return json.loads(inner) if isinstance(inner, str) else inner
    except Exception:                            # noqa: BLE001
        return None


def _shquote(s):
    return "'" + s.replace("'", "'\\''") + "'"


# Substrings that mean "no browser ever ran", not "the page misbehaved".
# Browserbase answers an out-of-quota account with HTTP 402 on EVERY command,
# so all eight properties fail identically and the night looks exactly like a
# Google block. It is not one. Telling the two apart is the difference between
# "wait for the quota to reset" and "go fight Google" — 2026-08-11 → 08-16 was
# spent believing the second one, because the CLI said "402 Free plan browser
# minutes limit reached" in plain words and nothing kept the sentence.
QUOTA_MARKERS = ("browser minutes limit", "402", "upgrade your account")
AUTH_MARKERS = ("api key", "unauthorized", "401", "forbidden")


# Every infra note starts with this, so a caller can recognise one without
# re-parsing prose. (Matching on "402" inside the rendered note happened to
# work and would have broken the first time the wording changed.)
INFRA_PREFIX = "browser backend: "


def classify_stderr(err):
    """A human reason when stderr proves the failure was on OUR side.

    None means nothing in stderr explains it — the page really did load and
    disappoint us, so the normal fail-closed notes stand."""
    low = (err or "").lower()
    if any(m in low for m in QUOTA_MARKERS):
        return INFRA_PREFIX + "Browserbase quota exhausted (402), no browser ran"
    if any(m in low for m in AUTH_MARKERS):
        return INFRA_PREFIX + f"key rejected ({(err or '').strip()[:60]})"
    return None


def is_infra_note(note):
    """True when a (None, note) failure was the browser backend, not Google."""
    return str(note or "").startswith(INFRA_PREFIX)


# Poll for the page instead of sleeping a flat 7-10 s. scraper.py already
# learned this on the flight side ("A FIXED sleep snapshots an empty list
# whenever the Mac is busy"). Here it is also money: a remote session bills by
# wall-clock, so a fixed sleep bills the idle seconds too. A warm Google Hotels
# page settles in ~2 s, so the old sleep spent ~5 s per property doing nothing
# — ~40 s a night, ~20 min a month against a 60-min free cap.
PAGE_WAIT_SECONDS = 12
PAGE_POLL_SECONDS = 2


def _wait_for_page(scraper, checkin, checkout, deadline=PAGE_WAIT_SECONDS):
    """Eval until the page proves its dates, or the budget runs out.

    Returns the first payload carrying BOTH dates; otherwise the last payload
    seen, so parse_rate still gets to render its specific complaint."""
    waited, last = 0.0, None
    want_in, want_out = _label(checkin), _label(checkout)
    while waited < deadline:
        payload = _eval_payload(scraper, checkin, checkout)
        if isinstance(payload, dict):
            last = payload
            if (want_in in (payload.get("checkin") or "")
                    and want_out in (payload.get("checkout") or "")):
                return payload                     # bound: stop paying to wait
        time.sleep(PAGE_POLL_SECONDS)
        waited += PAGE_POLL_SECONDS
    return last


def scrape_rate(entry, checkin, checkout, scraper=None, attempts=2):
    """One property. Never raises — a failure is a (None, reason) pair.

    Retries once on an empty render: a first-hit cold page is common and is
    NOT the same thing as being blocked. An infrastructure failure (no quota,
    bad key) is neither, and is reported as itself instead of as a guess."""
    if scraper is None:
        import scraper as scraper_mod
        scraper = scraper_mod
    diag = getattr(scraper, "DIAG", None)
    url = google_url(entry["query"], checkin, checkout)
    note = "never ran"
    for attempt in range(1, attempts + 1):
        try:
            if isinstance(diag, dict):
                diag["last_stderr"] = ""           # only THIS property's error
            scraper._run(f'browse open "{url}"')
            # Check the OPEN before polling. When the backend refuses (402),
            # the follow-up eval has nothing to talk to and burns the CLI's
            # full 30 s timeout before returning empty — observed live
            # 2026-08-16. Bailing here turns a 30 s hang into an instant note.
            infra = classify_stderr(
                diag.get("last_stderr") if isinstance(diag, dict) else "")
            if infra:
                return None, infra
            time.sleep(1)                          # let the navigation commit
            payload = _wait_for_page(scraper, checkin, checkout)
            rate, note = parse_rate(payload, entry, checkin, checkout)
            if rate is not None:
                return rate, note
            infra = classify_stderr(
                diag.get("last_stderr") if isinstance(diag, dict) else "")
            if infra:
                return None, infra                 # retrying cannot fix this
            if "empty" not in note and "no page payload" not in note:
                break                              # a real mismatch: don't retry
        except Exception as e:                     # noqa: BLE001 — never kill a run
            note = f"crashed: {e}"
        if attempt < attempts:
            time.sleep(2 + random.uniform(0, 2))
    try:
        with open(DEBUG_FILE, "w") as f:
            f.write(f"{entry['key']} :: {note}\n{url}\n")
    except Exception:                              # noqa: BLE001
        pass
    return None, note


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
