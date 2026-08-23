"""Nightly public nightly-rate refresh for the IST/SIN card-play shortlist.

WHY THIS EXISTS (2026-08-03): the shortlist's nightly rates were hand-researched
on 2026-08-01 and then sat frozen in the site's HTML with no provenance. By
2026-08-03 two of them were ~30% low against live Google Hotels for the real
stay dates (Ritz-Carlton Istanbul $314 → $425; Sanasaryan Han $270 → $348), so
the offset bands they drive were wrong too.

WHAT THIS CAN AND CANNOT SEE — read before trusting a number:
  * The rates the card play actually books (Amex FHR, Chase "The Edit") sit
    behind CARDHOLDER LOGINS and are never scraped from here. Since
    2026-08-22, `PORTAL` holds a one-time HUMAN read of the real FHR all-in
    totals for the shortlist (see
    docs/research/2026-08-22-fhr-portal-snapshot.md). `est_allin_night` is
    that portal figure drifted by tonight's PUBLIC nightly rate from Google
    Hotels for the same property and dates — the public rate is now the
    DRIFT ALARM, not the price. Re-anchor ONLY by re-reading the portal WITH
    JALAL PRESENT (it is Nabila's Amex login) — never automate that read.
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

CREDITS_NOTE = ("$300 Amex (or $250 Edit) + $100–125 property credit "
                "+ $60/day breakfast")
# FALLBACK ONLY — used for a row that has no portal anchor (today: JW South
# Beach, Edit-only). Every anchored row prices from the portal's all-in total,
# which already contains the real taxes/fees: 1.19–1.20× the ex-tax rate in
# BOTH cities on 2026-08-22. The old 0.12 was a guess and understated every
# offset by ~6 points.
TAX_RATE = 0.19

# Per-city all-in multipliers, READ OFF THE PORTAL TOTALS (total ÷ avg × nights,
# 2026-08-22): Istanbul 1.12 (10 % VAT + 2 % accommodation tax — the Ritz's
# 1.19 is the lone outlier), Singapore 1.20 (9 % GST + 10 % service charge).
# Used for the "public all-in" column (Google's headline rate is PRE-tax for a
# US viewer) and for the no-anchor fallback.
TAX_MULT = {"IST": 1.12, "SIN": 1.20}

# Credits, split the way the programs actually pay them out.
AMEX_FIXED = 300            # Amex Platinum $300 per half-year on prepaid FHR/THC
EDIT_FIXED = 250            # CSR "The Edit" — non-FHR programs
DAILY_CREDIT = 60           # breakfast for two, per night
DEFAULT_PROPERTY_CREDIT = 100


def fixed_credit(program):
    """Anything booked through Chase's Edit draws the $250 Edit credit, not
    the $300 Amex one — that is what makes Pan Pacific 2n read lower."""
    return EDIT_FIXED if "Edit" in (program or "") else AMEX_FIXED


def credits_for(n, program="FHR", property_credit=DEFAULT_PROPERTY_CREDIT):
    """Per-stay credit pool for n nights: fixed + property + daily."""
    return fixed_credit(program) + property_credit + DAILY_CREDIT * n


def paid_nights(n, free_night_min=None):
    """Nights actually billed. A 'free 4th night' promo means 3n and 4n cost
    the same — the portal's avg/night already bakes the free night in."""
    return n - 1 if free_night_min and n >= free_night_min else n

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
        if abs(n - o) >= MOVE_ALERT_ABS or (o and abs(n - o) / o * 100 >= MOVE_ALERT_PCT):
            out.append((r.get("name") or r.get("key"), o, n))
    return out


SWAP_BAR = 150    # $ a rival must net under the play for the alert to ring a bell
REBOOK_BAR = 100  # $ the play's own stay must fall under what you hold (or its
                  # anchor) before the "rebook it cheaper" bell rings

_CITY_LABEL = {"IST": "🕌 Istanbul", "SIN": "🇸🇬 Singapore"}

# How to lock a NOT-yet-booked play when it gets cheaper (per city).
LOCK_HINT = {
    "IST": ("lock it on chase.com/travel (The Edit, refundable, card not "
            "points) — it must be prepaid by Dec 31 anyway"),
}


def _net(row):
    v = ((row or {}).get("stay") or {}).get("net")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _city_rows(data, city):
    rows = [r for r in (data or {}).get("rows", []) if r.get("city") == city and r.get("stay")]
    play = next((r for r in rows if r.get("bold")), None)
    return rows, play


def _drift_factor(row):
    d = (row or {}).get("drift_pct")
    if isinstance(d, (int, float)) and not isinstance(d, bool) and d > -100:
        return 1 + d / 100
    return None


def rival_bells(prev, new):
    """{city: 🔔 line} for a rival that CROSSED the swap bar tonight — nets
    ≥ SWAP_BAR under the play now, and did not last night. Sanasaryan Han
    sits ~$230 under the Istanbul play every night by design (cheaper,
    lesser) — a bell that rings nightly is no bell."""
    by_key_prev = {r.get("key"): r for r in (prev or {}).get("rows", [])}
    out = {}
    for city in _CITY_LABEL:
        rows, play = _city_rows(new, city)
        if not play or _net(play) is None:
            continue
        prev_play_net = _net(by_key_prev.get(play.get("key")))
        rivals = []
        for r in rows:
            if r is play or _net(r) is None:
                continue
            d = _net(play) - _net(r)
            was_net = _net(by_key_prev.get(r.get("key")))
            d_was = (prev_play_net - was_net
                     if prev_play_net is not None and was_net is not None else None)
            if d >= SWAP_BAR and (d_was is None or d_was < SWAP_BAR):
                rivals.append((d, r))
        if rivals:
            d, r = max(rivals, key=lambda t: t[0])
            bk = BOOKED.get(city) or {}
            line = (f"🔔 {r['name']} nets ${d:,.0f} less than the play "
                    f"({play['name']}) — worth a look")
            line += (f"\n   → check it on the Stays tab; if it holds up, book it "
                     f"refundable FIRST, then cancel {bk.get('confirmation')}"
                     if bk.get("confirmation") else
                     "\n   → check it on the Stays tab before anything is booked")
            out[city] = line
    return out


def play_drop_bells(prev, new):
    """🔔 lines for the play itself getting cheaper — crossing REBOOK_BAR
    tonight. Booked (BOOKED[city] on the play's key): the booked total
    drifted by tonight's public move vs what you hold → rebook, then cancel.
    Not booked: tonight's stay total vs its portal-anchor total → lock it."""
    by_key_prev = {r.get("key"): r for r in (prev or {}).get("rows", [])}
    out = []
    for city in _CITY_LABEL:
        _rows, play = _city_rows(new, city)
        if not play:
            continue
        was = by_key_prev.get(play.get("key")) or {}
        bk = BOOKED.get(city) or {}
        booked = bk if bk.get("key") == play.get("key") and _num(bk.get("total")) else None
        f_now, f_was = _drift_factor(play), _drift_factor(was)
        if booked:
            if f_now is None:
                continue
            est = booked["total"] * f_now
            saving = booked["total"] - est
            saving_was = booked["total"] * (1 - f_was) if f_was is not None else None
            if saving >= REBOOK_BAR and (saving_was is None or saving_was < REBOOK_BAR):
                out.append(
                    f"🔔 {play['name']} got cheaper: your booked ${booked['total']:,.0f} "
                    f"now prices ≈ ${est:,.0f} (−${saving:,.0f})"
                    f"\n   → rebook the same room/dates the same way ({bk.get('via', 'same program')}), "
                    f"THEN cancel {bk.get('confirmation') or 'the old booking'}")
            continue
        total = (play.get("stay") or {}).get("total")
        if f_now is None or not _num(total):
            continue
        anchor_total = total / f_now
        saving = anchor_total - total
        was_total = (was.get("stay") or {}).get("total")
        saving_was = (was_total / f_was - was_total
                      if f_was is not None and _num(was_total) else None)
        if saving >= REBOOK_BAR and (saving_was is None or saving_was < REBOOK_BAR):
            hint = LOCK_HINT.get(city, "see the Stays tab")
            out.append(
                f"🔔 {play['name']} is ${saving:,.0f} under its portal anchor "
                f"(${anchor_total:,.0f} → ≈ ${total:,.0f} for the stay)\n   → {hint}")
    return out


def deal_alerts(prev, new):
    """Every 🔔 line that should ring tonight (rivals + play drops)."""
    return list(rival_bells(prev, new).values()) + play_drop_bells(prev, new)


def deal_message(prev, new):
    """The quiet-night bell: None unless something crossed a bar tonight."""
    bells = deal_alerts(prev, new)
    if not bells:
        return None
    return "🏨 <b>Hotel deal</b> — something crossed a bar overnight\n" + "\n".join(bells)


def moves_message(moves, prev=None, new=None):
    """The 🏨 movers alert. With the before/after JSON (v2, 2026-08-23) it
    speaks in what you would PAY — net for the tracked stay — grouped by
    city, and ends with a verdict per city: play unchanged, or a rival now
    nets ≥ SWAP_BAR under it (rival_bells), plus any play-drop bell. The
    public Google rate that actually moved is kept as the trailing detail.
    Without rows it is the original flat line. HTML parse mode (bold only);
    None when quiet."""
    if not moves:
        return None
    if not (new and new.get("rows")):
        parts = []
        for name, o, n in moves:
            pct = round(abs(n - o) / o * 100)
            arrow = "▼" if n < o else "▲"
            parts.append(f"{name} ${o:,.0f}→${n:,.0f} ({arrow}{pct}%)")
        return "🏨 Hotel rate moves: " + " · ".join(parts)

    by_name_new = {r.get("name"): r for r in new["rows"]}
    by_key_prev = {r.get("key"): r for r in (prev or {}).get("rows", [])}
    lines = ["🏨 <b>Hotel moves overnight</b> — what you'd pay for the stay"]
    for city, label in _CITY_LABEL.items():
        city_moves = [(n, o, r) for n, o, r in moves
                      if (by_name_new.get(n) or {}).get("city") == city]
        if not city_moves:
            continue
        lines.append(label)
        for name, o, n in city_moves:
            row = by_name_new[name]
            was = by_key_prev.get(row.get("key")) or {}
            st, wst = row.get("stay") or {}, was.get("stay") or {}
            pct = round(abs(n - o) / o * 100)
            arrow = "▼" if n < o else "▲"
            net = (f"net {st['nights']}n ${wst['net']:,.0f} → ${st['net']:,.0f}"
                   if _num(st.get("net")) or st.get("net") == 0 else "net —") \
                if st and wst else "net —"
            lines.append(f"  {arrow}{pct}% {name} · {net} · public ${o:,.0f}→${n:,.0f}")
    rivals = rival_bells(prev, new)
    for city, label in _CITY_LABEL.items():
        _rows, play = _city_rows(new, city)
        if not play:
            continue
        lines.append(rivals.get(city) or
                     f"{label.split(' ', 1)[1]}: play unchanged ({play['name']})")
    lines.extend(play_drop_bells(prev, new))
    return "\n".join(lines)

# The shortlist. `query` is the Google Hotels search string — keep it SHORT;
# long official names fall through to a no-results search page (proven
# 2026-08-03). `match` is the substring the resolved page title must contain,
# so a query that drifts to a different hotel is rejected rather than trusted.
# 2026-08-22: 8 → 20 properties = every luxury FHR candidate that fit 2 adults
# + 1 child on the portal (Jalal: "track everything luxury nightly"). The
# Browserbase quota math that this changes is in run_hotel_rates.py.
# `rank` is Jalal-facing VALUE ORDER per city (1 = the play, also the bold row):
# net cost for the tracked stay after credits, then quality (TA score, brand
# tier, location). Hand-curated 2026-08-22 from the portal read — the site
# sorts by it, so it is a recommendation, not a price sort. Re-rank when the
# anchors are re-read.
SHORTLIST = [
    # ── Istanbul · Jan 5–7 ──────────────────────────────────────────────────
    {"key": "sanasaryan", "city": "IST", "program": "FHR", "rank": 3,
     "name": "Sanasaryan Han (Lux. Coll.)", "query": "Sanasaryan Han Istanbul",
     "match": "Sanasaryan", "angle": "Old-city boutique · Bonvoy stacks · cheapest FHR in IST"},
    {"key": "ritz_ist", "city": "IST", "program": "FHR + Edit", "bold": True, "rank": 1,
     "name": "Ritz-Carlton Istanbul", "query": "Ritz Carlton Istanbul",
     "match": "Ritz-Carlton", "angle": "THE PLAY (2026-08-23): on The Edit at $1,285 — $250 credit + breakfast + $100 + Bonvoy stacks; prepay via Chase by Dec 31"},
    {"key": "parkhyatt_ist", "city": "IST", "program": "FHR", "rank": 4,
     "name": "Park Hyatt Maçka Palas", "query": "Park Hyatt Istanbul",
     "match": "Park Hyatt", "angle": "Nişantaşı boutique · second-cheapest FHR"},
    {"key": "shangrila_ist", "city": "IST", "program": "FHR", "rank": 2,
     "name": "Shangri-La Bosphorus", "query": "Shangri-La Bosphorus Istanbul",
     "match": "Shangri-La", "angle": "Bosphorus-front · TA 4.8 · not on The Edit (Amex FHR only, no $300 left in 2026)"},
    {"key": "stregis_ist", "city": "IST", "program": "FHR", "rank": 5,
     "name": "St. Regis Istanbul", "query": "St Regis Istanbul Nisantasi",
     "match": "St. Regis", "angle": "Butler with every room · Bonvoy stacks"},
    {"key": "ciragan", "city": "IST", "program": "FHR", "rank": 6,
     "name": "Çırağan Palace Kempinski", "query": "Ciragan Palace Kempinski",
     "match": "Kempinski", "angle": "The sentimental splurge · Bosphorus palace, the favorite brand"},
    {"key": "fs_bosphorus", "city": "IST", "program": "FHR", "rank": 7,
     "name": "Four Seasons Bosphorus", "query": "Four Seasons Bosphorus Istanbul",
     "match": "Bosphorus", "angle": "Palace on the water · fits 3 (portal-proven)"},
    {"key": "raffles_ist", "city": "IST", "program": "FHR", "rank": 8,
     "name": "Raffles Istanbul", "query": "Raffles Istanbul",
     "match": "Raffles", "angle": "TA 4.9, the best-reviewed in town · Zorlu mall"},
    # ── Singapore · Feb 2–6 ─────────────────────────────────────────────────
    {"key": "kempinski_sin", "city": "SIN", "program": "FHR", "bold": True, "rank": 1,
     "name": "The Capitol Kempinski", "query": "Capitol Kempinski Singapore",
     "match": "Kempinski",
     "angle": "THE find · free 4th night · $125 F&B credit · Kempinski standard at half the St. Regis"},
    {"key": "shangrila_sin", "city": "SIN", "program": "FHR", "rank": 2,
     "name": "Shangri-La Singapore", "query": "Shangri-La Singapore Orange Grove",
     "match": "Shangri-La", "angle": "Garden resort in town · Valley Wing is the play"},
    {"key": "fs_sin", "city": "SIN", "program": "FHR", "rank": 3,
     "name": "Four Seasons Singapore", "query": "Four Seasons Hotel Singapore",
     "match": "Four Seasons", "angle": "Orchard · kids' program · cheaper than St. Regis"},
    {"key": "artyzen", "city": "SIN", "program": "FHR", "rank": 4,
     "name": "Artyzen Singapore", "query": "Artyzen Singapore",
     "match": "Artyzen", "angle": "New 2023 · $125 property credit · rooftop pool"},
    {"key": "ritz_sin", "city": "SIN", "program": "FHR", "rank": 6,
     "name": "Ritz-Carlton Millenia", "query": "Ritz Carlton Millenia Singapore",
     "match": "Ritz-Carlton", "angle": "Marina views · Bonvoy stacks"},
    {"key": "stregis_sin", "city": "SIN", "program": "FHR", "rank": 7,
     "name": "St. Regis Singapore", "query": "St Regis Singapore",
     "match": "St. Regis", "angle": "Butler standard · Bonvoy stacks · the old play"},
    {"key": "fullerton_bay", "city": "SIN", "program": "FHR", "rank": 8,
     "name": "Fullerton Bay Hotel", "query": "Fullerton Bay Hotel Singapore",
     "match": "Fullerton Bay", "angle": "Free 3rd night · $125 F&B · TA 4.8 · on the water"},
    {"key": "mo_sin", "city": "SIN", "program": "FHR", "rank": 9,
     "name": "Mandarin Oriental", "query": "Mandarin Oriental Singapore",
     "match": "Mandarin Oriental", "angle": "Free 4th night · TA 4.8 · Marina Bay"},
    {"key": "edition_sin", "city": "SIN", "program": "FHR", "rank": 10,
     "name": "Singapore EDITION", "query": "The Singapore EDITION",
     "match": "EDITION", "angle": "TA 4.8 · Bonvoy stacks · Orchard-adjacent"},
    {"key": "panpacific", "city": "SIN", "program": "THC + Edit", "rank": 5,
     "name": "Pan Pacific Orchard", "query": "Pan Pacific Orchard Singapore",
     "match": "Pan Pacific Orchard",
     "angle": "Wildcard · CSR select-hotels credit may stack (see note)"},
    {"key": "jw_sin", "city": "SIN", "program": "The Edit only", "rank": 11,
     "name": "JW Marriott South Beach", "query": "JW Marriott South Beach Singapore",
     "match": "JW Marriott", "angle": "Best Edit-exclusive if the fallback strategy is needed"},
]

# ── Portal anchors — READ FROM THE AMEX FHR PORTAL, 2026-08-22 ───────────────
# These are the rates the card play actually books, for a 2-adult + 1-child
# search on the real dates, so every row here fits the three of us. `total`
# is the WHOLE stay incl. taxes and fees; `avg` is the portal's ex-tax
# average per night (kept for the record, not used in the math). A
# `free_night_min` means the portal's price already includes a free night
# for stays of at least that length; `ta` is the TripAdvisor score the portal
# showed that day (the quality half of the value rank). Source doc + read method:
# docs/research/2026-08-22-fhr-portal-snapshot.md. Re-anchor by re-reading
# the portal WITH JALAL PRESENT (it is Nabila's Amex login) — never automate.
PORTAL_DATE = "2026-08-22"
PORTAL = {
    # Istanbul, 2 nights
    "sanasaryan":    {"avg": 426.84, "total": 956.12,  "nights": 2, "credit": 100, "ta": 4.8, "promo": "was $502"},
    "ritz_ist":      {"avg": 525.52, "total": 1250.42, "nights": 2, "credit": 100, "ta": 4.7},
    "parkhyatt_ist": {"avg": 506.25, "total": 1133.98, "nights": 2, "credit": 100, "ta": 4.7},
    "shangrila_ist": {"avg": 531.36, "total": 1190.26, "nights": 2, "credit": 100, "ta": 4.8},
    "stregis_ist":   {"avg": 642.30, "total": 1438.76, "nights": 2, "credit": 100, "ta": 4.6},
    "ciragan":       {"avg": 656.90, "total": 1471.46, "nights": 2, "credit": 100, "ta": 4.6},
    "fs_bosphorus":  {"avg": 700.69, "total": 1569.54, "nights": 2, "credit": 100, "ta": 4.7},
    "raffles_ist":   {"avg": 729.88, "total": 1634.94, "nights": 2, "credit": 100, "ta": 4.9},
    # Singapore, 4 nights
    "kempinski_sin": {"avg": 276.70, "total": 1327.08, "nights": 4, "credit": 125, "ta": 4.7,
                      "free_night_min": 4, "promo": "free 4th night (in the rate) · was $378"},
    "shangrila_sin": {"avg": 361.59, "total": 1734.16, "nights": 4, "credit": 100, "ta": 4.6},
    "fs_sin":        {"avg": 386.48, "total": 1853.56, "nights": 4, "credit": 100, "ta": 4.7},
    "artyzen":       {"avg": 403.74, "total": 1936.31, "nights": 4, "credit": 125, "ta": 4.6},
    # "laurus" (The Laurus, Luxury Collection, $454.94 avg / $2,181.86 4n) is
    # NOT tracked: Google Hotels has no entity for it yet (three query shapes
    # tried live 2026-08-22, all landed on an unresolved search page), so the
    # date guard can never bind. Re-try a month or two after it opens.
    "ritz_sin":      {"avg": 490.38, "total": 2351.92, "nights": 4, "credit": 100, "ta": 4.6},
    "stregis_sin":   {"avg": 504.17, "total": 2418.00, "nights": 4, "credit": 100, "ta": 4.5},
    "fullerton_bay": {"avg": 547.50, "total": 2625.82, "nights": 4, "credit": 125, "ta": 4.8,
                      "free_night_min": 3, "promo": "free 3rd night (in the rate) · was $741"},
    "mo_sin":        {"avg": 551.24, "total": 2643.77, "nights": 4, "credit": 100, "ta": 4.8,
                      "free_night_min": 4, "promo": "free 4th night (in the rate) · was $719"},
    "edition_sin":   {"avg": 567.20, "total": 2720.28, "nights": 4, "credit": 100, "ta": 4.8},
    "panpacific":    {"avg": 364.34, "total": 1747.39, "nights": 4, "credit": 100, "ta": 4.7},   # THC rate
    # jw_sin: Edit-only, not on the Amex portal — no anchor, fallback math.
}

# Confirmed / in-progress bookings, hand-maintained (the site's Total tab
# prefers a booking over the play's cheapest-room estimate). `total` is the
# all-in USD figure on the Amex review page; credits are NOT subtracted here.
BOOKED = {
    "BKK": {"key": "athenee", "hotel": "The Athenee Hotel, a Luxury Collection Hotel, Bangkok",
            "room": "Athenee, Guest room, 1 King (2 adults + 1 child)",
            "checkin": "2027-01-28", "checkout": "2027-02-02", "nights": 5,
            "total": 0, "points": 177000, "via": "Marriott Bonvoy award · 5th night free",
            "status": "BOOKED 2026-08-23 · free cancel to Jan 26 2027 11:59pm hotel time",
            "next": "Sept: email the hotel for suite + Club-lounge supplement quotes on conf #88518376",
            "confirmation": "88518376"},
    "SIN": {"key": "kempinski_sin", "hotel": "The Capitol Kempinski",
            "room": "Heritage Room, 1 King (484 sq ft, sleeps 3)",
            "checkin": "2027-02-02", "checkout": "2027-02-06", "nights": 4,
            "total": 1497.11, "via": "Amex FHR · Pay at Check-in",
            "status": "BOOKED 2026-08-23 · hold, $0 down · free cancel to Jan 31 2027 11:59pm hotel time",
            "next": "Jan 2 2027: rebook as Pay Today on the Platinum for the Jan–Jun $300, then cancel ref ZO-AX1078-06155",
            "confirmation": "ZO-AX1078-06155",
            "confirmation_note": "Amex Travel trip reference (guest Nabila); hotel's own number follows by email"},
}

# Which stay takes the ONE Amex $300 available before the trip (Jan–Jun 2027;
# the Jul–Dec 2026 one was spent on the July Marriott stay — tracker read
# 2026-08-22). The other card stay is assumed on Chase's The Edit ($250).
# The Total tab reads this; the Stays table keeps showing each program's own
# best case.
CREDIT_PLAN = {"amex_300_to": "SIN",
               "note": ("Amex $300 → Singapore via the January rebook; "
                        "Istanbul = Ritz-Carlton on CSR The Edit ($250, "
                        "confirmed on the roster 2026-08-23), prepaid before Dec 31")}

# Points routes for the Istanbul stay (Chase read 2026-08-23) — the Total tab
# prices the play off `edit_total` (drifted by the Ritz's public rate, since
# the play is bought on The Edit, not FHR) and renders "why not points?" from
# the rest. Snapshots: Boost points scale with the drifted total at
# `boost_cents`; the Hyatt figures are the live award read that day.
POINTS_ROUTES = {"IST": {
    "read": "2026-08-23",
    "edit_total": 1285.0,          # Ritz-Carlton, Jan 5–7, 3 guests, all-in on Chase Travel
    "edit_credit": 250,            # the statement credit a points booking forfeits
    "boost_cents": 1.65,           # Points Boost on Edit hotels ($1,285 ↔ 77,873 pts)
    "hyatt": {"hotel": "Park Hyatt Maçka Palas", "key": "parkhyatt_ist",
              "pts": 50000, "per_night": 25000, "breakfast_cash": 150},
    "bar_cents": 1.5,              # what the legacy bucket is guaranteed on Ticket ①
    "future_cents": 2.0,           # what ordinary UR points fetch via Hyatt later
    # Cart test 2026-08-23: split-pay works and Boost applies to partial
    # redemptions. AFTER Ticket ① drains the 1.5× bucket, ~$260 card + ~62K
    # ordinary pts at 1.65¢ keeps the $250 (pending Chase confirming the
    # credit posts on the card portion) — the one route that clears the bar.
    "split": {"card": 260, "cents": 1.65,
              "note": ("split-pay AFTER Ticket ①: ~$260 card + ordinary points "
                       "at 1.65¢ Boost — the checkout credits modal (8/23) "
                       "confirmed the $250 applies to the card portion")},
}}

# Flights plan (Chase Travel read 2026-08-23, docs/research/2026-08-23-chase-marriott-amex-read.md):
# Ticket ① is sold on Chase as the exact Turkish multi-city ($4,147 vs $4,003
# on Google) and the cart honours the 1.5× bucket — 127,825 eligible points
# cover $1,917. Ticket ②'s carriers (US-Bangla, Scoot) are not sold on Chase.
FLIGHT_PLAN = {
    "ticket1": ("Chase Travel: Turkish TK 82/712/23+81 Ecofly, pay with ONLY the "
                "127,825 points eligible for 1.5× (= $1,917) + ~$2,230 cash; "
                "never the 1× points. Or turkish.com for ~$4,003 cash."),
    "ticket2": ("Cash, booked direct: US-Bangla DAC→BKK + Scoot BKK→SIN (~$992); "
                "neither carrier is on Chase Travel. Add Scoot bags on scoot.com."),
    "points_1_5x": 127825,
    "cents_1_5x": 1.5,
    # Chase Travel sells Ticket ① above the airline price; the Total tab adds
    # this fixed premium (snapshot) on top of tonight's live Google fare,
    # then takes the points off. Re-read the cart before buying.
    "chase_read": "2026-08-23",
    "chase_ticket1": 4147.29,
    "google_ticket1": 4003,
    "chase_premium": 144,
    "marriott_points": 177000,
}

# Seed values: the Google public rates read 2026-08-22, the SAME DAY as the
# portal anchors, which is what makes `anchor_google` an honest drift baseline
# for the original eight. New rows have no seed; their Google anchor is
# bootstrapped from their first live scrape (see build()).
SEED = {
    "sanasaryan":  {"rate": 353, "checked": "2026-08-22", "anchor_google": 353},
    "ritz_ist":    {"rate": 447, "checked": "2026-08-22", "anchor_google": 447},
    "stregis_ist": {"rate": 546, "checked": "2026-08-22", "anchor_google": 546},
    "ciragan":     {"rate": 472, "checked": "2026-08-22", "anchor_google": 472},
    "panpacific":  {"rate": 250, "checked": "2026-08-22", "anchor_google": 250},
    "stregis_sin": {"rate": 472, "checked": "2026-08-22", "anchor_google": 472},
    "ritz_sin":    {"rate": 477, "checked": "2026-08-22", "anchor_google": 477},
    "jw_sin":      {"rate": 444, "checked": "2026-08-22"},
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


def anchor_for(key):
    """The portal anchor for a shortlist key as the JSON row carries it, or
    None. `allin_night` is per PAID night so the free-night promos price
    2n/3n honestly (a free-4th-night hotel costs the same for 3n and 4n).

    A malformed PORTAL entry (missing/non-numeric total or nights) degrades
    to None for that ONE row instead of raising and killing the whole build
    — the row then falls back to rate × (1 + TAX_RATE)."""
    p = PORTAL.get(key)
    if not p or not _num(p.get("total")) or not _num(p.get("nights")):
        return None
    fnm = p.get("free_night_min")
    return {"date": PORTAL_DATE, "total": p["total"], "nights": p["nights"],
            "allin_night": round(p["total"] / paid_nights(p["nights"], fnm), 2),
            "credit": p.get("credit", DEFAULT_PROPERTY_CREDIT),
            "free_night_min": fnm, "promo": p.get("promo"), "ta": p.get("ta"),
            "google": None, "google_date": None}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0


def est_allin_night(anchor, rate):
    """Tonight's estimated FHR all-in per paid night: the portal figure,
    scaled by how far the public Google rate has moved since the anchor.
    No Google anchor or no rate tonight → the portal figure unscaled."""
    if not anchor:
        return None
    base = anchor["allin_night"]
    g = anchor.get("google")
    if _num(rate) and _num(g):
        return round(base * rate / g, 2)
    return base


def drift_pct(rate, google_anchor):
    """Public-rate movement since the anchor date, whole percent, or None."""
    if not (_num(rate) and _num(google_anchor)):
        return None
    return round(100 * (rate / google_anchor - 1))


def offset_from_allin(allin_night, n, credits, free_night_min=None):
    """Credits ÷ estimated all-in for n nights, whole percent. None-safe."""
    if not _num(allin_night) or not n:
        return None
    return round(100 * credits / (allin_night * paid_nights(n, free_night_min)))


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


def _offset(entry, anchor, est, rate, n):
    """One offset cell. Anchored rows price from the portal estimate; the
    rest fall back to Google rate × (1 + TAX_RATE)."""
    prop = anchor["credit"] if anchor else DEFAULT_PROPERTY_CREDIT
    c = credits_for(n, entry["program"], prop)
    if est is not None and anchor:
        pct = offset_from_allin(est, n, c, anchor.get("free_night_min"))
    else:
        pct = offset_pct(rate, n, c)
    return {"label": f"{n}n", "pct": pct, "band": band(pct)}


def _google_anchor(prev, key, fresh, today):
    """(google, google_date) for the anchor: what the previous row already
    carried, else the seeded same-day read, else bootstrap from tonight's
    first live rate. None until one of those exists.

    A persisted baseline is trusted ONLY when it was recorded against the
    CURRENT PORTAL_DATE. Bumping PORTAL_DATE (a future portal re-read)
    self-invalidates every already-run row's old Google baseline — without
    this check, a new portal total would be silently scaled against a
    baseline it was never measured against, and est_allin_night would drift
    on a comparison that no longer means anything."""
    pa = prev.get("anchor") if isinstance(prev.get("anchor"), dict) else {}
    if pa.get("date") == PORTAL_DATE and _num(pa.get("google")):
        return pa["google"], pa.get("google_date")
    # The seed is a same-day Google read and is only a valid baseline while
    # SEED's `checked` date IS the portal date; a PORTAL_DATE bump without a
    # SEED refresh must bootstrap from a live scrape instead.
    seed = SEED.get(key) or {}
    seeded = prev.get("anchor_google") or seed.get("anchor_google")
    if _num(seeded) and seed.get("checked") == PORTAL_DATE:
        return seeded, seed.get("checked")
    if fresh and _num(fresh[0]):
        return fresh[0], today
    return None, None


def build(payload, scraped=None, today=None):
    """Merge freshly scraped rates over the last-known ones and compute the
    offsets. A property with no fresh rate keeps its previous value AND its
    previous `checked` date, so staleness is always visible.

    2026-08-22: every row also carries its portal `anchor` (the real FHR
    all-in, read once), `est_allin_night` (that figure drifted by tonight's
    public rate) and `drift_pct`. Offsets and the stay math price from
    est_allin_night; the Google rate is the drift alarm, not the price."""
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
        anchor = anchor_for(e["key"])
        if anchor:
            anchor["google"], anchor["google_date"] = _google_anchor(
                prev, e["key"], fresh, today)
        est = est_allin_night(anchor, rate)
        mult = TAX_MULT[e["city"]]
        if est is None and _num(rate):
            est = round(rate * mult, 2)                     # fallback path
        win = windows.get(e["city"])
        nights = win[2] if win else (2 if e["city"] == "IST" else None)
        stay_n = nights or (2 if e["city"] == "IST" else 4)
        # Two apples-to-apples per-night figures for the table: the public
        # Google rate with the city's taxes/fees added, and the FHR estimate
        # AVERAGED over the tracked stay (a free-night hotel's per-paid-night
        # figure looks 33 % dearer than what the stay actually averages).
        public_allin = round(rate * mult, 2) if _num(rate) else None
        avg_allin = (round(est * paid_nights(stay_n, (anchor or {}).get("free_night_min")) / stay_n, 2)
                     if est is not None else None)
        # The Stay column: total − credits = net for the tracked window, from
        # the same per-paid-night estimate the offsets use.
        stay = None
        if est is not None:
            fnm = (anchor or {}).get("free_night_min")
            prop = anchor["credit"] if anchor else DEFAULT_PROPERTY_CREDIT
            total = round(est * paid_nights(stay_n, fnm), 2)
            cred = credits_for(stay_n, e["program"], prop)
            stay = {"nights": stay_n, "total": total, "credits": cred,
                    "net": max(0, round(total - cred))}
        row = {"key": e["key"], "city": e["city"], "name": e["name"],
               "program": e["program"], "angle": e["angle"], "rank": e["rank"],
               "stay": stay,
               "bold": bool(e.get("bold")), "rate": rate, "checked": checked,
               "anchor": anchor, "est_allin_night": est,
               "avg_allin_night": avg_allin, "public_allin_night": public_allin,
               "drift_pct": drift_pct(rate, anchor.get("google")) if anchor else None}
        if e["city"] == "IST":
            row["offsets"] = [_offset(e, anchor, est, rate, nights or 2)]
        else:
            row["offsets"] = [_offset(e, anchor, est, rate, n) for n in (2, 4)]
        rows.append(row)
    return {
        "updated": today,
        "stays": {c: ({"checkin": w[0].isoformat(), "checkout": w[1].isoformat(),
                       "nights": w[2]} if w else None)
                  for c, w in windows.items()},
        "credits_note": CREDITS_NOTE,
        "portal_date": PORTAL_DATE,
        "bookings": BOOKED,
        "credit_plan": CREDIT_PLAN,
        "flight_plan": FLIGHT_PLAN,
        "points_routes": POINTS_ROUTES,
        "source": ("est_allin_night = Amex FHR portal all-in per paid night "
                   f"(read {PORTAL_DATE}, 2 adults + 1 child) × tonight's public "
                   "Google rate ÷ the public rate on the anchor date; `rate` is "
                   "that public rate (2 adults, incl. fees) and is the drift alarm"),
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
