# FHR Portal Anchors + Luxury Shortlist Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track every luxury FHR candidate in Istanbul and Singapore nightly (8 → 20 properties) and make every offset / stay-math number derive from the REAL Amex FHR booking rate read from the portal on 2026-08-22, drifted nightly by the public Google rate — instead of a Google 2-adult rate × a guessed 12% tax.

**Architecture:** `hotel_rates.py` gains a `PORTAL` anchor table (per-hotel all-in total, nights, property credit, free-night promo) and writes three new fields per row into `site/hotel_rates.json` — `anchor`, `est_allin_night`, `drift_pct`. `est_allin_night` = portal all-in per PAID night × (Google rate now ÷ Google rate on the anchor date); the Google anchor is seeded for the 8 existing rows (same-day read) and bootstrapped from the first live scrape for new rows. `stay_value.py` and `verify.py` (independently, as AGENTS.md demands) switch `hotel_net` to `paid_nights(n) × est_allin_night − credits(n)`, falling back to `rate × 1.19` only for rows with no anchor. `run_hotel_rates.py` derives its quota estimate from the shortlist length and widens the local-Chrome spacing. The site renders the new columns. SIN bold moves to **The Capitol Kempinski** (FHR, free 4th night, $166/night net — Jalal's "Kempinski standard" bar, half the St. Regis).

**Tech Stack:** Python 3 stdlib, pytest, vanilla JS in `site/index.html`, `browse` CLI + Browserbase (existing).

**Source data:** `docs/research/2026-08-22-fhr-portal-snapshot.md` (the portal read, 2 adults + 1 child). Read it before Task 1.

**Repo rules that bind this plan** (AGENTS.md §1 "Nightly hotel rates"): no hotel number lives in HTML; `ts=` never `checkin=`; keep Google queries SHORT; read with `browse eval`; scrape from Browserbase; never run concurrently with the flight run; verify.py stays an independent re-implementation. Commit straight to `main` (solo repo), one commit per task.

**Quota reality (tell Jalal at handoff, it's in Task 9 too):** measured 0.29 min/property on Browserbase → 20 properties ≈ 6 min/night ≈ 180 min/month vs the FREE 60-min cap. `should_conserve` will put ~2 of 3 nights on local Chrome (home IP, 20 searches each, spaced 8–20 s + page time ≈ 10 min). Browserbase **Developer plan is $20/mo for 100 h** (browserbase.com/pricing, read 2026-08-22) — our demand is ~3 h. That is the clean fix; the code below works either way.

---

## File map

| File | Change |
|---|---|
| `hotel_rates.py` | `PORTAL` anchors, 12 new `SHORTLIST` entries, SIN bold → `kempinski_sin`, `SEED` refreshed to 2026-08-22 + `anchor_google`, credit helpers, `paid_nights`, `anchor_for`, `est_allin_night`, `drift_pct`, `offset_from_allin`, `build()` writes `anchor`/`est_allin_night`/`drift_pct`, `TAX_RATE` 0.12 → 0.19 (fallback only) |
| `tests/test_hotel_rates.py` | new anchor tests; offset test numbers updated for 0.19 |
| `stay_value.py` | row-based `hotel_net(row, n)` using `est_allin_night` + anchor credit + free-night rule; constants split (300 + property credit); `assumption` wording |
| `tests/test_stay_value.py` | fixture row gains anchor fields; signatures updated |
| `verify.py` | `_stay_adj` mirrors the new rule with its OWN constants |
| `run_hotel_rates.py` | `PER_PROPERTY_MINUTES`, derived `EST_RUN_MINUTES`, local `JITTER` (8, 20), demand line at startup |
| `tests/test_hotel_pacing.py` | two tests rewritten to be cost-derived |
| `notify_telegram.py` | 🛏️ line shows est all-in/night |
| `site/index.html` | Stays tables: new columns (FHR all-in est · public + drift · offsets), text fixes (12% → portal-anchored; CNY note) |
| `AGENTS.md` | new subsection "Portal anchors (2026-08-22)" |
| `~/PycharmProjects/github-notion-sync/schedule_snapshot.py` | catalog text "8 properties" → 20 |

---

### Task 1: Anchors, helpers and the expanded shortlist in `hotel_rates.py`

**Files:**
- Modify: `hotel_rates.py` (constants lines 38–47, `SHORTLIST` 84–114, `SEED` 116–128, `offset_pct` 139–143, `build` 460–507)
- Test: `tests/test_hotel_rates.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_hotel_rates.py`:

```python
# ── Portal anchors (2026-08-22) ─────────────────────────────────────────────
def test_paid_nights_free_night_rule():
    assert hr.paid_nights(4, 4) == 3 and hr.paid_nights(3, 4) == 3
    assert hr.paid_nights(2, 4) == 2
    assert hr.paid_nights(4, None) == 4 and hr.paid_nights(4, 3) == 3


def test_credits_for_splits_fixed_property_and_daily():
    assert hr.credits_for(2) == 520 and hr.credits_for(4) == 640     # unchanged totals
    assert hr.credits_for(2, "THC + Edit") == 470                     # $250 Edit
    assert hr.credits_for(4, "FHR", 125) == 665                       # $125 property credit


def test_anchor_allin_night_is_per_paid_night():
    k = hr.anchor_for("kempinski_sin")
    assert k["nights"] == 4 and k["free_night_min"] == 4 and k["credit"] == 125
    assert k["allin_night"] == round(1327.08 / 3, 2)                  # 442.36, 4th night free
    assert hr.anchor_for("ritz_ist")["allin_night"] == round(1250.42 / 2, 2)   # 625.21
    assert hr.anchor_for("jw_sin") is None                            # Edit-only: no portal row
    assert k["date"] == hr.PORTAL_DATE == "2026-08-22"


def test_est_allin_drifts_with_the_public_rate():
    a = dict(hr.anchor_for("ritz_ist"), google=447)
    assert hr.est_allin_night(a, 447) == 625.21
    assert hr.est_allin_night(a, 492) == round(625.21 * 492 / 447, 2)
    assert hr.est_allin_night(dict(a, google=None), 600) == 625.21    # no Google anchor yet: no drift
    assert hr.est_allin_night(a, None) == 625.21                       # no public rate yet
    assert hr.est_allin_night(None, 447) is None
    assert hr.drift_pct(492, 447) == 10 and hr.drift_pct(447, None) is None


def test_offsets_from_the_portal_total():
    # Capitol Kempinski 4n: $1,327.08 incl. tax with the free 4th night; credits 300+125+240
    assert hr.offset_from_allin(442.36, 4, 665, free_night_min=4) == 50
    assert hr.offset_from_allin(442.36, 2, 545, free_night_min=4) == 62
    assert hr.offset_from_allin(None, 2, 545) is None
    assert hr.offset_from_allin(442.36, 0, 545) is None


def test_build_rows_carry_anchor_est_and_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    out = hr.build({"main": None}, scraped={"kempinski_sin": (300, "ok")},
                   today="2026-08-23")
    k = next(r for r in out["rows"] if r["key"] == "kempinski_sin")
    assert k["bold"] is True                                           # the new SIN play
    assert k["anchor"]["google"] == 300 and k["anchor"]["google_date"] == "2026-08-23"
    assert k["est_allin_night"] == 442.36 and k["drift_pct"] == 0
    assert [o["pct"] for o in k["offsets"]] == [62, 50]
    ritz = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    assert ritz["anchor"]["google"] == hr.SEED["ritz_ist"]["anchor_google"]
    assert ritz["anchor"]["google_date"] == "2026-08-22"
    jw = next(r for r in out["rows"] if r["key"] == "jw_sin")
    assert jw["anchor"] is None and jw["drift_pct"] is None
    assert jw["est_allin_night"] == round(jw["rate"] * 1.19, 2)        # fallback path
    new = next(r for r in out["rows"] if r["key"] == "shangrila_sin")
    assert new["rate"] is None and new["est_allin_night"] == round(1734.16 / 4, 2)
    assert new["offsets"][1]["pct"] == 37                              # offsets exist before the first scrape


def test_build_keeps_a_bootstrapped_google_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "RATES_FILE", str(tmp_path / "hotel_rates.json"))
    first = hr.build({"main": None}, scraped={"kempinski_sin": (300, "ok")},
                     today="2026-08-23")
    hr.write(first)
    second = hr.build({"main": None}, scraped={"kempinski_sin": (330, "ok")},
                      today="2026-08-24")
    k = next(r for r in second["rows"] if r["key"] == "kempinski_sin")
    assert k["anchor"]["google"] == 300 and k["anchor"]["google_date"] == "2026-08-23"
    assert k["drift_pct"] == 10 and k["est_allin_night"] == round(442.36 * 330 / 300, 2)


def test_only_one_bold_per_city():
    for city in ("IST", "SIN"):
        assert sum(1 for e in hr.SHORTLIST if e["city"] == city and e.get("bold")) == 1


def test_shortlist_keys_unique_and_anchored_rows_have_portal_rows():
    keys = [e["key"] for e in hr.SHORTLIST]
    assert len(keys) == len(set(keys)) == 20
    assert set(hr.PORTAL) <= set(keys)
```

And change the two numbers in the existing `test_offset_math_matches_the_published_bands` (the fallback tax is now 19%):

```python
def test_offset_math_matches_the_published_bands():
    # Fallback path (no portal anchor) now assumes the observed ~19% tax/fees:
    # a $314 IST room with $520 credits sits exactly on the 70% line,
    assert hr.offset_pct(314, 2, 520) == 70
    # and the corrected $425 room drops it out of the "book now" band.
    assert hr.offset_pct(425, 2, 520) == 51
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights" && python3 -m pytest tests/test_hotel_rates.py -q 2>&1 | tail -5`
Expected: FAIL — `AttributeError: module 'hotel_rates' has no attribute 'paid_nights'` (and the offset test: 74 != 70).

- [ ] **Step 3: Replace the constants block** (lines 38–47) with:

```python
CREDITS_NOTE = ("$300 Amex (or $250 Edit) + $100–125 property credit "
                "+ $60/day breakfast")
# FALLBACK ONLY — used for a row that has no portal anchor (today: JW South
# Beach, Edit-only). Every anchored row prices from the portal's all-in total,
# which already contains the real taxes/fees: 1.19–1.20× the ex-tax rate in
# BOTH cities on 2026-08-22. The old 0.12 was a guess and understated every
# offset by ~6 points.
TAX_RATE = 0.19

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
```

- [ ] **Step 4: Replace `SHORTLIST` and `SEED`** (lines 84–128) with:

```python
# The shortlist. `query` is the Google Hotels search string — keep it SHORT;
# long official names fall through to a no-results search page (proven
# 2026-08-03). `match` is the substring the resolved page title must contain,
# so a query that drifts to a different hotel is rejected rather than trusted.
# 2026-08-22: 8 → 20 properties = every luxury FHR candidate that fit 2 adults
# + 1 child on the portal (Jalal: "track everything luxury nightly"). The
# Browserbase quota math that this changes is in run_hotel_rates.py.
SHORTLIST = [
    # ── Istanbul · Jan 5–7 ──────────────────────────────────────────────────
    {"key": "sanasaryan", "city": "IST", "program": "FHR",
     "name": "Sanasaryan Han (Lux. Coll.)", "query": "Sanasaryan Han Istanbul",
     "match": "Sanasaryan", "angle": "Old-city boutique · Bonvoy stacks · cheapest FHR in IST"},
    {"key": "ritz_ist", "city": "IST", "program": "FHR", "bold": True,
     "name": "Ritz-Carlton Istanbul", "query": "Ritz Carlton Istanbul",
     "match": "Ritz-Carlton", "angle": "Value pick · Bonvoy Platinum stacks (points + elite nights)"},
    {"key": "parkhyatt_ist", "city": "IST", "program": "FHR",
     "name": "Park Hyatt Maçka Palas", "query": "Park Hyatt Istanbul",
     "match": "Park Hyatt", "angle": "Nişantaşı boutique · second-cheapest FHR"},
    {"key": "shangrila_ist", "city": "IST", "program": "FHR",
     "name": "Shangri-La Bosphorus", "query": "Shangri-La Bosphorus Istanbul",
     "match": "Shangri-La", "angle": "Bosphorus-front · TA 4.8 · Ritz money"},
    {"key": "stregis_ist", "city": "IST", "program": "FHR",
     "name": "St. Regis Istanbul", "query": "St Regis Istanbul Nisantasi",
     "match": "St. Regis", "angle": "Butler with every room · Bonvoy stacks"},
    {"key": "ciragan", "city": "IST", "program": "FHR",
     "name": "Çırağan Palace Kempinski", "query": "Ciragan Palace Kempinski",
     "match": "Kempinski", "angle": "The sentimental splurge · Bosphorus palace, the favorite brand"},
    {"key": "fs_bosphorus", "city": "IST", "program": "FHR",
     "name": "Four Seasons Bosphorus", "query": "Four Seasons Bosphorus Istanbul",
     "match": "Bosphorus", "angle": "Palace on the water · fits 3 (portal-proven)"},
    {"key": "raffles_ist", "city": "IST", "program": "FHR",
     "name": "Raffles Istanbul", "query": "Raffles Istanbul",
     "match": "Raffles", "angle": "TA 4.9, the best-reviewed in town · Zorlu mall"},
    # ── Singapore · Feb 2–6 ─────────────────────────────────────────────────
    {"key": "kempinski_sin", "city": "SIN", "program": "FHR", "bold": True,
     "name": "The Capitol Kempinski", "query": "Capitol Kempinski Singapore",
     "match": "Kempinski",
     "angle": "THE find · free 4th night · $125 F&B credit · Kempinski standard at half the St. Regis"},
    {"key": "shangrila_sin", "city": "SIN", "program": "FHR",
     "name": "Shangri-La Singapore", "query": "Shangri-La Singapore Orange Grove",
     "match": "Shangri-La", "angle": "Garden resort in town · Valley Wing is the play"},
    {"key": "fs_sin", "city": "SIN", "program": "FHR",
     "name": "Four Seasons Singapore", "query": "Four Seasons Hotel Singapore",
     "match": "Four Seasons", "angle": "Orchard · kids' program · cheaper than St. Regis"},
    {"key": "artyzen", "city": "SIN", "program": "FHR",
     "name": "Artyzen Singapore", "query": "Artyzen Singapore",
     "match": "Artyzen", "angle": "New 2023 · $125 property credit · rooftop pool"},
    {"key": "laurus", "city": "SIN", "program": "FHR",
     "name": "The Laurus (Lux. Coll.)", "query": "The Laurus Singapore",
     "match": "Laurus", "angle": "New Luxury Collection · TA 5.0 · Bonvoy stacks"},
    {"key": "ritz_sin", "city": "SIN", "program": "FHR",
     "name": "Ritz-Carlton Millenia", "query": "Ritz Carlton Millenia Singapore",
     "match": "Ritz-Carlton", "angle": "Marina views · Bonvoy stacks"},
    {"key": "stregis_sin", "city": "SIN", "program": "FHR",
     "name": "St. Regis Singapore", "query": "St Regis Singapore",
     "match": "St. Regis", "angle": "Butler standard · Bonvoy stacks · the old play"},
    {"key": "fullerton_bay", "city": "SIN", "program": "FHR",
     "name": "Fullerton Bay Hotel", "query": "Fullerton Bay Hotel Singapore",
     "match": "Fullerton Bay", "angle": "Free 3rd night · $125 F&B · TA 4.8 · on the water"},
    {"key": "mo_sin", "city": "SIN", "program": "FHR",
     "name": "Mandarin Oriental", "query": "Mandarin Oriental Singapore",
     "match": "Mandarin Oriental", "angle": "Free 4th night · TA 4.8 · Marina Bay"},
    {"key": "edition_sin", "city": "SIN", "program": "FHR",
     "name": "Singapore EDITION", "query": "The Singapore EDITION",
     "match": "EDITION", "angle": "TA 4.8 · Bonvoy stacks · Orchard-adjacent"},
    {"key": "panpacific", "city": "SIN", "program": "THC + Edit",
     "name": "Pan Pacific Orchard", "query": "Pan Pacific Orchard Singapore",
     "match": "Pan Pacific Orchard",
     "angle": "Wildcard · CSR select-hotels credit may stack (see note)"},
    {"key": "jw_sin", "city": "SIN", "program": "The Edit only",
     "name": "JW Marriott South Beach", "query": "JW Marriott South Beach Singapore",
     "match": "JW Marriott", "angle": "Best Edit-exclusive if the fallback strategy is needed"},
]

# ── Portal anchors — READ FROM THE AMEX FHR PORTAL, 2026-08-22 ───────────────
# These are the rates the card play actually books, for a 2-adult + 1-child
# search on the real dates, so every row here fits the three of us. `total`
# is the WHOLE stay incl. taxes and fees; `avg` is the portal's ex-tax
# average per night (kept for the record, not used in the math). A
# `free_night_min` means the portal's price already includes a free night
# for stays of at least that length. Source doc + read method:
# docs/research/2026-08-22-fhr-portal-snapshot.md. Re-anchor by re-reading
# the portal WITH JALAL PRESENT (it is Nabila's Amex login) — never automate.
PORTAL_DATE = "2026-08-22"
PORTAL = {
    # Istanbul, 2 nights
    "sanasaryan":    {"avg": 426.84, "total": 956.12,  "nights": 2, "credit": 100, "promo": "was $502"},
    "ritz_ist":      {"avg": 525.52, "total": 1250.42, "nights": 2, "credit": 100},
    "parkhyatt_ist": {"avg": 506.25, "total": 1133.98, "nights": 2, "credit": 100},
    "shangrila_ist": {"avg": 531.36, "total": 1190.26, "nights": 2, "credit": 100},
    "stregis_ist":   {"avg": 642.30, "total": 1438.76, "nights": 2, "credit": 100},
    "ciragan":       {"avg": 656.90, "total": 1471.46, "nights": 2, "credit": 100},
    "fs_bosphorus":  {"avg": 700.69, "total": 1569.54, "nights": 2, "credit": 100},
    "raffles_ist":   {"avg": 729.88, "total": 1634.94, "nights": 2, "credit": 100},
    # Singapore, 4 nights
    "kempinski_sin": {"avg": 276.70, "total": 1327.08, "nights": 4, "credit": 125,
                      "free_night_min": 4, "promo": "free 4th night (in the rate) · was $378"},
    "shangrila_sin": {"avg": 361.59, "total": 1734.16, "nights": 4, "credit": 100},
    "fs_sin":        {"avg": 386.48, "total": 1853.56, "nights": 4, "credit": 100},
    "artyzen":       {"avg": 403.74, "total": 1936.31, "nights": 4, "credit": 125},
    "laurus":        {"avg": 454.94, "total": 2181.86, "nights": 4, "credit": 100},
    "ritz_sin":      {"avg": 490.38, "total": 2351.92, "nights": 4, "credit": 100},
    "stregis_sin":   {"avg": 504.17, "total": 2418.00, "nights": 4, "credit": 100},
    "fullerton_bay": {"avg": 547.50, "total": 2625.82, "nights": 4, "credit": 125,
                      "free_night_min": 3, "promo": "free 3rd night (in the rate) · was $741"},
    "mo_sin":        {"avg": 551.24, "total": 2643.77, "nights": 4, "credit": 100,
                      "free_night_min": 4, "promo": "free 4th night (in the rate) · was $719"},
    "edition_sin":   {"avg": 567.20, "total": 2720.28, "nights": 4, "credit": 100},
    "panpacific":    {"avg": 364.34, "total": 1747.39, "nights": 4, "credit": 100},   # THC rate
    # jw_sin: Edit-only, not on the Amex portal — no anchor, fallback math.
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
```

- [ ] **Step 5: Add the anchor helpers** directly after `offset_pct` (after line 143 in the old numbering; keep `offset_pct` and `band` as they are):

```python
def anchor_for(key):
    """The portal anchor for a shortlist key as the JSON row carries it, or
    None. `allin_night` is per PAID night so the free-night promos price
    2n/3n honestly (a free-4th-night hotel costs the same for 3n and 4n)."""
    p = PORTAL.get(key)
    if not p:
        return None
    fnm = p.get("free_night_min")
    return {"date": PORTAL_DATE, "total": p["total"], "nights": p["nights"],
            "allin_night": round(p["total"] / paid_nights(p["nights"], fnm), 2),
            "credit": p.get("credit", DEFAULT_PROPERTY_CREDIT),
            "free_night_min": fnm, "promo": p.get("promo"),
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
```

- [ ] **Step 6: Rewrite `build()`** (old lines 460–507) as:

```python
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
    first live rate. None until one of those exists."""
    pa = prev.get("anchor") if isinstance(prev.get("anchor"), dict) else {}
    if _num(pa.get("google")):
        return pa["google"], pa.get("google_date")
    seeded = prev.get("anchor_google") or (SEED.get(key) or {}).get("anchor_google")
    if _num(seeded):
        return seeded, (SEED.get(key) or {}).get("checked") or prev.get("checked")
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
        if est is None and _num(rate):
            est = round(rate * (1 + TAX_RATE), 2)          # fallback path
        win = windows.get(e["city"])
        nights = win[2] if win else (2 if e["city"] == "IST" else None)
        row = {"key": e["key"], "city": e["city"], "name": e["name"],
               "program": e["program"], "angle": e["angle"],
               "bold": bool(e.get("bold")), "rate": rate, "checked": checked,
               "anchor": anchor, "est_allin_night": est,
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
        "source": ("est_allin_night = Amex FHR portal all-in per paid night "
                   f"(read {PORTAL_DATE}, 2 adults + 1 child) × tonight's public "
                   "Google rate ÷ the public rate on the anchor date; `rate` is "
                   "that public rate (2 adults, incl. fees) and is the drift alarm"),
        "rows": rows,
        "notes": notes,
    }
```

Delete the old `CREDIT_POOL` / `CREDIT_POOL_EDIT` dicts (nothing else uses them — confirm with `grep -rn CREDIT_POOL *.py tests/`; expected: no hits after this task).

- [ ] **Step 7: Run the tests**

Run: `python3 -m pytest tests/test_hotel_rates.py -q 2>&1 | tail -5`
Expected: all PASS (the pre-existing `test_build_covers_every_shortlist_row` still passes: 20 rows, every row has offsets, SIN rows have 2).

- [ ] **Step 8: Regenerate the JSON locally without scraping and eyeball it**

Run:
```bash
python3 -c "
import hotel_rates as hr, json
d = hr.build(json.load(open('site/data.json')))
for r in d['rows']:
    a = r['anchor'] or {}
    print(f\"{r['city']} {r['name']:28s} pub={r['rate']}  est/n={r['est_allin_night']}  g_anchor={a.get('google')}  off={[o['pct'] for o in r['offsets']]}\")
"
```
Expected: 20 lines; Kempinski `est/n=442.36 off=[62, 50]`; Ritz IST `pub=447 est/n=625.21 g_anchor=447 off=[42]`; new rows `pub=None` with offsets present. Do NOT write the file here — the nightly job (Task 8) does that with real scrapes.

- [ ] **Step 9: Commit**

```bash
git add hotel_rates.py tests/test_hotel_rates.py docs/research/2026-08-22-fhr-portal-snapshot.md docs/superpowers/plans/2026-08-22-fhr-portal-anchors-luxury-shortlist.md
git commit -m "feat(hotels): portal anchors + 20-property luxury shortlist, Kempinski bold in SIN"
```

---

### Task 2: `stay_value.py` prices from the anchored all-in

**Files:**
- Modify: `stay_value.py` (constants lines 28–36, `fixed_credits`/`credits`/`hotel_net` 68–82, `score_adjust` 101–109, `hotel_hook` 112–121, `_watchdog` 124–143, `build` 146–195)
- Test: `tests/test_stay_value.py`

- [ ] **Step 1: Update the fixture and the tests** in `tests/test_stay_value.py`.

Replace the `stregis_sin` row in `RATES` (lines 16–17) with an anchored row. `244.15` is chosen so every previously pinned number (net 0/152/337, all-in $4,997) still holds — the fixture moves to the real path without moving the expectations:

```python
        {"key": "stregis_sin", "city": "SIN", "name": "St. Regis Singapore",
         "program": "FHR", "bold": True, "rate": 218, "checked": "2026-08-19",
         "est_allin_night": 244.15,
         "anchor": {"date": "2026-08-19", "total": 976.6, "nights": 4,
                    "allin_night": 244.15, "credit": 100,
                    "free_night_min": None, "promo": None,
                    "google": 218, "google_date": "2026-08-19"}},
```

Replace the three `hotel_net` tests (lines 38–46) with:

```python
ROW = RATES["rows"][1]                                  # the anchored St. Regis


def test_hotel_net_floors_at_zero():
    # 2×244.15 = 488.30 < $520 credits — credits beyond the bill are NOT cash back
    assert stay_value.hotel_net(ROW, 2) == 0


def test_hotel_net_at_three_and_four():
    assert stay_value.hotel_net(ROW, 3) == 152          # 732.45 − 580
    assert stay_value.hotel_net(ROW, 4) == 337          # 976.60 − 640


def test_hotel_net_fallback_without_an_anchor_assumes_19pct():
    bare = {"rate": 218, "program": "FHR"}
    assert stay_value.hotel_net(bare, 4) == 398         # 4×218×1.19 − 640 = 397.68


def test_hotel_net_honours_free_night_and_property_credit():
    kemp = {"rate": 300, "program": "FHR", "est_allin_night": 442.36,
            "anchor": {"credit": 125, "free_night_min": 4}}
    assert stay_value.hotel_net(kemp, 4) == 662         # 3 paid × 442.36 − 665
    assert stay_value.hotel_net(kemp, 3) == 747         # 3 paid × 442.36 − 580
    assert stay_value.hotel_net(kemp, 2) == 340         # 2 paid × 442.36 − 545
```

In `test_build_rows_and_pick` change the last assertion to:

```python
    assert "St. Regis" in sv["assumption"] and "244" in sv["assumption"] \
        and "218" in sv["assumption"]
    assert sv["hotel"]["allin_night"] == 244.15
```

Everything else in the file stays: the watchdog test's `Cheap Palace` (no anchor → 4×100×1.19 − 640 → 0) still barks, Pan Pacific (no anchor → 4×255×1.19 − 590 = $624 → $156/n) still doesn't.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_stay_value.py -q 2>&1 | tail -5`
Expected: FAIL — `TypeError` in `hotel_net` (number passed where a row is expected) / `AttributeError` on `.get`.

- [ ] **Step 3: Rewrite the constants and money functions** in `stay_value.py`. Replace lines 28–36 with:

```python
EXTRA_NIGHT_WORTH = 225   # $ one extra SIN night is worth (Jalal, 2026-08-19)
DEAD_BAND = 25            # challenger must beat the incumbent shape by this
STALE_DAYS = 3            # bold rate older than this → advisory, not steering
WATCHDOG_GAP = 50         # $/night a rival must beat the bold pick by to bark
TAX_RATE = 0.19           # FALLBACK for a row with no portal anchor (observed
                          # 1.19–1.20× on the Amex portal 2026-08-22)
AMEX_FIXED = 300          # $300 Amex FHR/THC per stay
EDIT_FIXED = 250          # $250 Edit — non-FHR programs
PROPERTY_CREDIT = 100     # default; an anchored row carries its own ($100/$125)
DAILY_CREDIT = 60         # breakfast credit per day
MIN_N = 2                 # mirrors combo.MIN_SG_NIGHTS — the score baseline
```

Replace `fixed_credits`, `credits`, `hotel_net` (lines 68–82) with:

```python
def fixed_credits(program):
    """FHR-bookable stays get the $300 Amex; Edit/THC-only get $250 Edit."""
    return AMEX_FIXED if "FHR" in (program or "") else EDIT_FIXED


def _anchor(row):
    a = row.get("anchor") if isinstance(row, dict) else None
    return a if isinstance(a, dict) else {}


def property_credit(row):
    c = _anchor(row).get("credit")
    return c if isinstance(c, (int, float)) else PROPERTY_CREDIT


def credits(n, program="FHR", prop=PROPERTY_CREDIT):
    return fixed_credits(program) + prop + DAILY_CREDIT * n


def paid_nights(n, free_night_min=None):
    """A 'free 4th night' promo bills 3 nights for a 4-night stay."""
    return n - 1 if free_night_min and n >= free_night_min else n


def allin_night(row):
    """Estimated all-in per paid night: the portal-anchored estimate the
    hotel job writes (est_allin_night), else public rate × (1 + TAX_RATE)."""
    est = row.get("est_allin_night")
    if isinstance(est, (int, float)) and est > 0:
        return est
    return row["rate"] * (1 + TAX_RATE)


def hotel_net(row, n):
    """Out-of-pocket for n nights after credits, floored at 0 — credits
    beyond the bill are not cash back. `row` is a hotel_rates.json row."""
    program = row.get("program", "FHR")
    nights = paid_nights(n, _anchor(row).get("free_night_min"))
    return max(0, round(nights * allin_night(row)
                        - credits(n, program, property_credit(row))))
```

Replace `score_adjust` and `hotel_hook` (lines 101–121) with:

```python
def score_adjust(row, n, incumbent_n):
    """What the combo hook adds to a candidate's flight cost: its net hotel
    bill, minus the value of its extra nights, minus the incumbent shape's
    dead-band bonus (so the pick only flips when the challenger clearly
    wins — no 4N-Monday/2N-Tuesday whiplash from volatile flex fares)."""
    return (hotel_net(row, n)
            - EXTRA_NIGHT_WORTH * (n - MIN_N)
            - (DEAD_BAND if n == incumbent_n else 0))


def hotel_hook(rates, incumbent_n, today=None):
    """combo.py's optional hotel_cost hook: f(sin_nights) → $ adjustment,
    or None unless mode is steering. combo adds f(n) to each candidate's
    flight cost, so the in-band winner minimizes
    flights + net_hotel − WORTH×extra_nights (− dead-band on the incumbent)."""
    today = today or datetime.date.today()
    if mode(rates, today) != "steering":
        return None
    row = bold_row(rates)
    return lambda n: score_adjust(row, n, incumbent_n)
```

In `_watchdog` replace the two `hotel_net(...)` calls:

```python
    bold_pn = hotel_net(row, n) / n
    ...
        pn = hotel_net(r, n) / n
```

In `build`, replace the `rows` loop body, the `hotel=` dict and the `assumption=` string:

```python
    for n in sorted(k for k in (flight_totals or {}) if isinstance(k, int)):
        fl = flight_totals[n]
        net = hotel_net(row, n)
        rows.append({"n": n, "flights": fl, "hotel_net": net, "allin": fl + net,
                     "score": fl + score_adjust(row, n, incumbent_n)})
```

```python
        hotel={"key": row.get("key"), "name": row.get("name"),
               "rate": row["rate"], "checked": row.get("checked"),
               "program": program,
               "allin_night": round(allin_night(row), 2),
               "anchor_date": _anchor(row).get("date")},
```

```python
        assumption=(f"{row['name']} est. ${allin_night(row):,.0f}/paid night "
                    f"all-in ("
                    + (f"FHR portal {_anchor(row).get('date')}, drifted by the "
                       f"public rate ${row['rate']:,} checked {row.get('checked')}"
                       if _anchor(row).get("date") else
                       f"public ${row['rate']:,} checked {row.get('checked')} "
                       f"× ~{round(TAX_RATE * 100)}% tax, no portal anchor")
                    + f") · credits ${fixed_credits(program)}+"
                    f"${property_credit(row)}/stay + ${DAILY_CREDIT}/day"
                    + (f" · free night from {_anchor(row).get('free_night_min')}n"
                       if _anchor(row).get("free_night_min") else "")),
```

Also update the module docstring's formula lines to:

```
    hotel_net(n) = max(0, paid_nights(n)·allin_night − credits(n))   never cash back
    allin_night  = est_allin_night from hotel_rates.json (portal-anchored),
                   else rate·(1+TAX) for a row with no anchor
```

- [ ] **Step 4: Run the stay-value and publish tests**

Run: `python3 -m pytest tests/test_stay_value.py tests/test_publish.py tests/test_notify_fallback.py -q 2>&1 | tail -5`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add stay_value.py tests/test_stay_value.py
git commit -m "feat(stay-math): price SIN nights from the portal-anchored all-in, free-night aware"
```

---

### Task 3: `verify.py` mirrors the rule independently

**Files:**
- Modify: `verify.py` (constants lines 25–30, `_stay_adj` 120–146)
- Test: `tests/test_verify.py`

- [ ] **Step 1: Add a test** to `tests/test_verify.py` (after `test_stay_rows_arithmetic_is_rechecked`):

```python
def test_stay_adj_uses_the_anchor_not_the_public_rate():
    """verify must re-derive from est_allin_night + anchor (free night,
    property credit) with its OWN constants — a drift in stay_value's rule
    must show up here as a disagreement, not be copied."""
    kemp = {"rows": [{"key": "k", "city": "SIN", "bold": True, "program": "FHR",
                      "rate": 300, "est_allin_night": 442.36,
                      "anchor": {"credit": 125, "free_night_min": 4}}]}
    adj = _verify._stay_adj({"stay_value": {"mode": "steering"}}, kemp, None)
    # net(4) = 3 paid × 442.36 − (300+125+240) = 662; minus 225×2 extra nights
    assert adj(4) == 662 - 450
    # net(2) = 2 × 442.36 − 545 = 340 (rounded); no extra-night value
    assert adj(2) == 340
    bare = {"rows": [{"key": "b", "city": "SIN", "bold": True, "program": "FHR",
                      "rate": 218}]}
    adj2 = _verify._stay_adj({"stay_value": {"mode": "steering"}}, bare, None)
    assert adj2(4) == 398 - 450                     # fallback 4×218×1.19 − 640
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_verify.py -q 2>&1 | tail -5`
Expected: FAIL — `adj(4)` computes with the public rate × 1.12 (old rule).

- [ ] **Step 3: Update verify.py.** Replace the constants (lines 25–30) with:

```python
# 🛏️ Stay-math constants — deliberately DUPLICATED from stay_value.py (this
# file's value is being a second implementation; keep the numbers in sync).
STAY_WORTH = 225
STAY_DEAD_BAND = 25
STAY_TAX = 0.19                      # fallback only — anchored rows carry est_allin_night
STAY_AMEX_FIXED, STAY_EDIT_FIXED = 300, 250
STAY_PROPERTY_DEFAULT, STAY_DAILY = 100, 60
```

Replace the body of `_stay_adj` from `fixed = ...` to the end of `adj` with:

```python
    fixed = (STAY_AMEX_FIXED if "FHR" in (row.get("program") or "")
             else STAY_EDIT_FIXED)
    anchor = row.get("anchor") if isinstance(row.get("anchor"), dict) else {}
    prop = anchor.get("credit")
    prop = prop if isinstance(prop, (int, float)) else STAY_PROPERTY_DEFAULT
    free_min = anchor.get("free_night_min")
    est = row.get("est_allin_night")
    per_night = (est if isinstance(est, (int, float)) and est > 0
                 else row["rate"] * (1 + STAY_TAX))

    def adj(n):
        paid = n - 1 if free_min and n >= free_min else n
        net = max(0, round(paid * per_night - (fixed + prop + STAY_DAILY * n)))
        return (net - STAY_WORTH * (n - SG_BAND[0])
                - (STAY_DEAD_BAND if n == incumbent_n else 0))
    return adj
```

- [ ] **Step 4: Run the verify tests**

Run: `python3 -m pytest tests/test_verify.py -q 2>&1 | tail -5`
Expected: all PASS (the fixture's St. Regis row is anchored at 244.15, so the 4N pick and the 337 net are unchanged).

- [ ] **Step 5: Commit**

```bash
git add verify.py tests/test_verify.py
git commit -m "feat(verify): re-derive stay math from the portal anchor with independent constants"
```

---

### Task 4: Quota pacing for a 20-property run

**Files:**
- Modify: `run_hotel_rates.py` (lines 41–66 constants, `start_session` print, `main` startup print)
- Test: `tests/test_hotel_pacing.py`

- [ ] **Step 1: Rewrite the two tests that assumed "a few local nights"** in `tests/test_hotel_pacing.py`:

```python
def _expected_local(year, month, cost=None):
    """Nights that CANNOT be remote at this run cost: demand − cap, in runs."""
    cost = cost if cost is not None else rh.EST_RUN_MINUTES
    days = calendar.monthrange(year, month)[1]
    return max(0, days - int(CAP // cost))


def test_day_one_conserve_rate_tracks_the_shortfall():
    """Day 1 with a full tank conserves with probability shortfall/nights —
    ~13% when 8 properties fit the cap, ~68% at 20 properties. Pin the
    FORMULA, not a seed: asserting 'mostly remote' was true only while
    demand barely exceeded the cap."""
    d = datetime.date(2026, 9, 1)
    nights = 30
    need = nights * rh.EST_RUN_MINUTES
    p = max(0.0, (need - CAP) / rh.EST_RUN_MINUTES) / nights
    trials = 200
    local = sum(rh.should_conserve(0, CAP, today=d, rng=Seeded(s))
                for s in range(trials))
    sd = (trials * p * (1 - p)) ** 0.5
    assert abs(local - trials * p) <= 4 * sd + 1, \
        f"day-1 conserve rate {local}/{trials} vs expected p={p:.2f}"


def test_local_nights_match_demand_and_are_not_all_at_month_end():
    """Whatever the shortlist length, the month must (a) spend the quota
    rather than hoard it, (b) go local only about as often as demand
    forces, and (c) scatter those nights instead of clumping at the end —
    a multi-night burst from the home IP is the shape Google slow-walked."""
    local, used = simulate(2026, 10)          # 31 days
    want = _expected_local(2026, 10)
    assert want - 3 <= len(local) <= want + 4, \
        f"local nights {len(local)} vs demand-forced {want}: {local}"
    assert used > CAP * 0.75, f"hoarded quota instead of spending it: {used:.1f}"
    tail = set(range(31 - len(local) + 1, 32))
    assert set(local) != tail, f"local nights clumped at month-end: {local}"
```

(Delete `test_early_month_with_full_quota_is_usually_remote` and `test_local_nights_are_few_and_are_not_all_at_month_end`.) Add:

```python
def test_run_estimate_scales_with_the_shortlist():
    import hotel_rates
    assert rh.EST_RUN_MINUTES == round(
        rh.PER_PROPERTY_MINUTES * len(hotel_rates.SHORTLIST), 1)
    assert rh.PER_PROPERTY_MINUTES >= 0.29          # the 2026-08-16 measurement


def test_local_spacing_is_wide_enough_for_twenty_searches():
    """20 searches from the home IP must not look like the 2026-08-03 burst
    (~10 rapid searches). ≥8 s floor, on top of the page polling."""
    assert rh.JITTER["local"][0] >= 8
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_hotel_pacing.py -q 2>&1 | tail -5`
Expected: FAIL — `AttributeError: PER_PROPERTY_MINUTES`; local floor 4 < 8.

- [ ] **Step 3: Update `run_hotel_rates.py` constants** (replace lines 41–66):

```python
# MEASURED 2026-08-16: two full 8-property remote runs billed 2.25 and 2.32 min
# → ~0.29 min per property. Set a hair ABOVE that on purpose: overestimating
# costs a few needless local nights, underestimating dries the quota out
# mid-month — the exact failure this pacing exists to prevent. Re-derive from
# `GET /v1/projects/{id}/usage` after a month of 20-property runs.
PER_PROPERTY_MINUTES = 0.30
EST_RUN_MINUTES = round(PER_PROPERTY_MINUTES * len(hotel_rates.SHORTLIST), 1)

# 2026-08-22: the shortlist went 8 → 20 ("track everything luxury nightly"),
# so demand is ~180 min/month against the 60-min free tier and ~2 nights in 3
# fall back to local Chrome. That is Jalal's explicit choice; the clean fix is
# Browserbase's Developer plan ($20/mo, 100 h — read 2026-08-22), which makes
# every night remote. Nothing here needs to change when that happens: usage
# comes back under cap and should_conserve stops firing.


def monthly_demand_minutes(today=None):
    today = today or datetime.date.today()
    return calendar.monthrange(today.year, today.month)[1] * EST_RUN_MINUTES


# Delay between properties, per mode. The SAME pause is expensive-and-pointless
# on one and free-and-valuable on the other, so it must not be one number:
#   remote — every second is BILLED, and 20 requests from a rotating
#            residential IP is not a shape Google throttles. Keep it tight.
#   local  — seconds are free, and this is the home IP the midnight flight run
#            depends on. 20 searches at 4–11 s would resemble the 2026-08-03
#            burst (~10 rapid searches got slow-walked); 8–20 s on top of the
#            page polling puts them ~30 s apart, ~10 min a night.
JITTER = {"remote": (1, 3), "local": (8, 20)}
```

In `start_session`, after the `print(f"  Browserbase: {used}/{cap} min used this month")` line add:

```python
            demand = monthly_demand_minutes()
            if demand > cap:
                print(f"  demand ≈ {demand:.0f} min/month for "
                      f"{len(hotel_rates.SHORTLIST)} properties vs a {cap}-min "
                      f"cap — expect ~{max(0, round((demand - cap) / EST_RUN_MINUTES))} "
                      f"local-Chrome nights; the $20 Developer plan removes them")
```

- [ ] **Step 4: Run the pacing tests**

Run: `python3 -m pytest tests/test_hotel_pacing.py -q 2>&1 | tail -5`
Expected: all PASS. (`test_pacing_survives_a_run_costing_more_than_estimated` and `test_a_month_never_runs_dry` still hold — the simulate() guard `used >= cap` is what they test.)

- [ ] **Step 5: Commit**

```bash
git add run_hotel_rates.py tests/test_hotel_pacing.py
git commit -m "feat(hotels): quota estimate derives from shortlist length; wider local spacing for 20 searches"
```

---

### Task 5: Telegram 🛏️ line shows the all-in estimate

**Files:**
- Modify: `notify_telegram.py:226-227`
- Test: `tests/test_stay_value.py` (the Telegram assertions near line 264)

- [ ] **Step 1: Extend the existing Telegram test** — find the test around line 255–266 that asserts `"St. Regis <b>4N ✓</b>" in msg`; add one assertion:

```python
    assert "~$244/n all-in" in msg          # est per paid night, not the public $218
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_stay_value.py -q -k "telegram or brief or msg" 2>&1 | tail -5`
Expected: FAIL — message still says `$218/n`.

- [ ] **Step 3: Change the line** in `notify_telegram.py`:

```python
        per_night = hotel.get("allin_night") or hotel.get("rate", 0)
        body.append(f"{esc_html(_short_prop(hotel.get('name')))} "
                    f"~${per_night:,.0f}/n all-in{stamp}{credit_note}")
```

- [ ] **Step 4: Run**

Run: `python3 -m pytest tests/test_stay_value.py tests/test_notify_fallback.py tests/test_alerts.py -q 2>&1 | tail -5`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add notify_telegram.py tests/test_stay_value.py
git commit -m "feat(telegram): stay line quotes the all-in estimate per night"
```

---

### Task 6: Site — Stays tables show the anchored FHR estimate

**Files:**
- Modify: `site/index.html` (`rateCell`/`offCell`/`cardPlayTables` lines ~1055–1100; explanatory text at ~1160 and ~1215; the "Good to know" CNY sentence ~1166)

- [ ] **Step 1: Replace `rateCell` and add `allinCell`** (the existing `offCell` stays):

```js
/* Public Google rate (2 adults, incl. fees) — the DRIFT ALARM, with how far
   it has moved since the portal anchor date. */
function rateCell(row) {
  if (row.rate == null) return `<td class="num muted">— <span class="small">1st read tonight</span></td>`;
  const age = daysSince(row.checked);
  const stale = age != null && age > 3
    ? ` <span class="badge warn" title="last confirmed ${esc(row.checked)}">${age}d</span>` : "";
  const d = row.drift_pct;
  const drift = typeof d === "number" && d !== 0
    ? ` <span class="badge ${d > 0 ? "warn" : "good"}" title="vs the public rate on ${esc((row.anchor || {}).google_date || "anchor day")}">${d > 0 ? "▲" : "▼"}${Math.abs(d)}%</span>` : "";
  return `<td class="num">$${row.rate.toLocaleString()}${stale}${drift}</td>`;
}
/* Estimated FHR all-in per paid night: the portal figure drifted by the public
   rate. This is the number the offsets and the stay math use. */
function allinCell(row) {
  if (row.est_allin_night == null) return `<td class="num">—</td>`;
  const a = row.anchor;
  const tip = a
    ? `Amex FHR portal ${a.date}: $${a.total.toLocaleString()} for ${a.nights}n incl. taxes` +
      (a.free_night_min ? ` · free night from ${a.free_night_min}n` : "") +
      (a.promo ? ` · ${a.promo}` : "") + ` · $${a.credit} property credit`
    : "no portal anchor — public rate × ~19% tax";
  const promo = a && a.free_night_min ? ` <span class="badge good" title="${esc(tip)}">free nt</span>` : "";
  return `<td class="num" title="${esc(tip)}"><b>$${Math.round(row.est_allin_night).toLocaleString()}</b>${a ? "" : '<span class="small">*</span>'}${promo}</td>`;
}
```

- [ ] **Step 2: Replace `cardPlayTables`** with:

```js
function cardPlayTables() {
  if (!RATES || !Array.isArray(RATES.rows) || !RATES.rows.length)
    return `<div class="small" style="margin-top:10px">Nightly rates are refreshed
      by their own job and weren't reachable just now — reload, or see the
      shortlist notes below.</div>`;
  const byNet = (a, b) => (a.est_allin_night ?? 1e9) - (b.est_allin_night ?? 1e9);
  const ist = RATES.rows.filter(r => r.city === "IST").sort(byNet);
  const sin = RATES.rows.filter(r => r.city === "SIN").sort(byNet);
  const nameCell = r => `<td>${r.bold ? `<b>${esc(r.name)}</b>` : esc(r.name)}</td>`;
  const istRows = ist.map(r => `<tr>${nameCell(r)}<td>${esc(r.program)}</td>
      ${allinCell(r)}${rateCell(r)}${offCell(r.offsets && r.offsets[0])}
      <td class="wrap">${esc(r.angle)}</td></tr>`).join("");
  const sinRows = sin.map(r => `<tr>${nameCell(r)}<td>${esc(r.program)}</td>
      ${allinCell(r)}${rateCell(r)}${offCell(r.offsets && r.offsets[0])}${offCell(r.offsets && r.offsets[1])}
      <td class="wrap">${esc(r.angle)}</td></tr>`).join("");
  const aged = RATES.rows.filter(r => r.rate != null).map(r => daysSince(r.checked) ?? 0);
  const oldest = aged.length ? Math.max(...aged) : 0;
  const freshness = oldest > 3
    ? `<div class="small" style="margin-top:6px">⚠️ Oldest public rate here was last
       confirmed ${oldest} days ago — the nightly refresh has not reached every
       property since.</div>` : "";
  const anchorDate = esc(RATES.portal_date || "2026-08-22");
  return `<div class="scroll-x" style="margin-top:10px"><table>
      <tr><th>🕌 Istanbul · ${stayHeading("IST", "Jan 5–7 (2n)")}</th><th>Program</th>
          <th class="num">FHR all-in/nt</th><th class="num">Public</th><th class="num">Offset</th><th>Angle</th></tr>
      ${istRows}</table></div>
    <div class="scroll-x" style="margin-top:10px"><table>
      <tr><th>🇸🇬 Singapore · ${stayHeading("SIN", "2–4n")}</th><th>Program</th>
          <th class="num">FHR all-in/nt</th><th class="num">Public</th><th class="num">2n</th><th class="num">4n</th><th>Angle</th></tr>
      ${sinRows}</table></div>${freshness}
    <div class="small" style="margin-top:6px"><b>FHR all-in/nt</b> is the rate the card
      play actually books: read once from the Amex FHR portal on ${anchorDate}
      (2 adults + 1 child, taxes and fees in, per <i>paid</i> night — a free-night
      promo shows as "free nt"), then moved each night by however far the
      <b>public</b> Google rate (2 adults, incl. fees, re-checked nightly — last run
      ${esc(RATES.updated || "—")}) has drifted since that day. Sorted cheapest
      first. * = no portal row (Edit-only), public × ~19% tax. Re-confirm in the
      portal before booking.</div>`;
}
```

- [ ] **Step 3: Fix the explanatory text.** At ~line 1160 replace `<b>Offset</b> = credits used ÷ (room + ~12% tax). Credits assumed: $300 Amex (or $250 Edit) + $100 property + $60/day breakfast — so IST 2n = $520 · SIN 2n = $520 FHR / $470 Edit · SIN 4n = $640 / $590.` with:

```html
<b>Offset</b> = credits used ÷ the FHR all-in above. Credits: $300 Amex (or $250 Edit)
        + the property's own credit ($100, or $125 at Capitol Kempinski / Fullerton Bay /
        Artyzen) + $60/day breakfast — so IST 2n = $520 · SIN 4n = $640 ($665 with a $125 credit).
```

At ~line 1166 replace `Good to know: CNY is Feb 6, 2027 — Singapore hasn't loaded holiday premiums yet, so book early once dates firm.` with:

```html
Good to know: CNY is Feb 6, 2027 — Singapore HAS now loaded it (St. Regis public rate
        $329 on Aug 1 → $472 on Aug 22), which is why the Capitol Kempinski's free-4th-night
        rate matters so much; book early once dates firm.
```

At ~line 1215 replace `Offset = credits you'll actually use ÷ (room + ~12% tax).` with `Offset = credits you'll actually use ÷ the real all-in (portal-anchored; ~19% tax/fees in both cities, not the 12% first assumed).`

- [ ] **Step 4: Smoke-test the page locally against the regenerated JSON**

Run:
```bash
python3 -c "import hotel_rates as hr, json; hr.write(hr.build(json.load(open('site/data.json'))))"
python3 -m http.server 8765 --directory site >/dev/null 2>&1 & sleep 1
```
Open `http://localhost:8765/#/stays` in Chrome (via the `browse` CLI or the Chrome extension) and confirm: two tables, 8 + 12 rows, Kempinski bold and first in SIN, "1st read tonight" on the new rows' Public column, offsets populated, no `undefined` anywhere. Then `kill %1` and `git checkout site/hotel_rates.json` (the nightly job is the only thing that should commit that file).

Note: the page fetches `RATES_RAW` from GitHub first and only falls back to `./hotel_rates.json` — to see the local file, temporarily block the raw URL in DevTools or test after Task 8's push instead.

- [ ] **Step 5: Commit**

```bash
git add site/index.html
git commit -m "feat(site): Stays tables show portal-anchored FHR all-in, public drift, free-night promos"
```

---

### Task 7: Full test run

- [ ] **Step 1:** `python3 -m pytest -q 2>&1 | tail -8`
Expected: every test passes. If `tests/test_schema_check.py` or `tests/test_sanity.py` complain about new `hotel_rates.json` keys, they are wrong to — those files validate `data.json`, not `hotel_rates.json`; report rather than loosen.

---

### Task 8: Live verification — do the 12 new Google queries resolve?

A `match` string that never matches publishes nothing for that row forever (fail-closed), so this must be observed live before the first nightly run. Costs ≈ 3.6 Browserbase minutes (August has ~43 left as of 08-22 per cron.log).

- [ ] **Step 1: Dry-run ONLY the new entries, from Browserbase, printing the resolved titles**

Run (from the repo, `.env` present):
```bash
BROWSE_SESSION=hotels python3 - <<'EOF'
import os, json, time, random
from dotenv import load_dotenv; load_dotenv(".env")
import hotel_rates as hr, run_hotel_rates as rh, scraper
NEW = {"parkhyatt_ist","shangrila_ist","fs_bosphorus","raffles_ist","kempinski_sin",
       "shangrila_sin","fs_sin","artyzen","laurus","fullerton_bay","mo_sin","edition_sin"}
windows = hr.stay_windows(json.load(open("site/data.json")))
mode = rh.start_session(scraper)
try:
    for e in [x for x in hr.SHORTLIST if x["key"] in NEW]:
        w = windows[e["city"]]
        rate, note = hr.scrape_rate(e, w[0], w[1], scraper=scraper)
        print(f"{e['key']:15s} {'$'+str(rate) if rate else 'MISS':8s} {note}")
        time.sleep(random.uniform(*rh.JITTER[mode]))
finally:
    scraper.end_session()
EOF
```
Expected: 12 lines, each `$NNN ok`. For any `resolved to '<title>', expected <match>` line: if the title IS the right hotel, loosen that entry's `match` to a substring of the printed title (e.g. Google titles Four Seasons Bosphorus as "Four Seasons Hotel Istanbul at the Bosphorus" — `match: "Bosphorus"` is set for that). If the title is the WRONG hotel (e.g. Shangri-La Rasa Sentosa), shorten/adjust the `query` and re-run just that key. For `no results`, the query is too long — shorten it. Commit any query/match fixes:

```bash
git add hotel_rates.py && git commit -m "fix(hotels): Google query/match strings verified live for the 12 new properties"
```

- [ ] **Step 2: Run the real nightly job once, now, so tonight's midnight flight run sees a Kempinski rate**

Without this, `stay_value.bold_row` finds Kempinski with `rate: null`, mode goes `off` for one night and the Telegram brief says so. Check no flight run is active (`pgrep -f run_daily.py` → nothing), then:

```bash
/bin/bash run_hotel_rates.sh 2>&1 | grep -v "jittering" | tail -30
```
(The wrapper sleeps 0–35 min for jitter; to skip that, run `python3 run_hotel_rates.py` directly instead — the stand-down guard is what matters and it is only about the flight run.)
Expected: `Refreshed N/20 rates` with N ≥ 18, `Pushed hotel_rates.json`, and a 🏨 Telegram movers line is plausible (the St. Regis seed is unchanged, so probably silent).

- [ ] **Step 3: Confirm the live site**

Open https://dhaka-flights.vercel.app/#/stays (or the GitHub-pages URL in AGENTS.md) and check the tables render as in Task 6 Step 4 with real public rates on all 20 rows. Check `site/hotel_rates.json` on GitHub shows `"anchor"` blocks with `"google"` filled for every anchored row.

---

### Task 9: Documentation — AGENTS.md, the fleet catalog, memory

**Files:**
- Modify: `AGENTS.md` (§1 "Nightly hotel rates", after rule 9 and before the postmortem)
- Modify: `~/PycharmProjects/github-notion-sync/schedule_snapshot.py:44,46`

- [ ] **Step 1: Add to AGENTS.md** after rule 9:

```markdown
10. **Portal anchors (2026-08-22) — the number that matters is `est_allin_night`,
    not `rate`.** Jalal opened the Amex FHR portal (Nabila's Platinum) and the
    full IST/SIN rosters were read once for the real dates as 2 adults + 1
    child (`docs/research/2026-08-22-fhr-portal-snapshot.md`). Two things fell
    out: the Google public rate understates the FHR booking rate by 23–55 %
    (3rd guest + flexible rate), and taxes/fees are ~19–20 % in BOTH cities, not
    the 12 % every offset had assumed. So `hotel_rates.PORTAL` holds each
    hotel's all-in stay total, nights, property credit and free-night promo;
    `build()` writes `anchor` (with the Google rate on the anchor day —
    seeded for the original 8, bootstrapped from the first live scrape for
    the rest), `est_allin_night` (portal all-in per PAID night × Google now ÷
    Google on anchor day) and `drift_pct`. Offsets, `stay_value`, `verify`
    and the Telegram 🛏️ line all price from `est_allin_night`; `rate` is the
    drift alarm. `TAX_RATE = 0.19` is a FALLBACK for un-anchored rows only
    (JW South Beach, Edit-only). **Re-anchor by re-reading the portal with
    Jalal present — it is a cardholder login and must never be automated;
    the read method (URL shape, lazy-render scroll, `main.innerText` split on
    "Available Rooms") is in the snapshot doc.** Anchors are a point-in-time
    read: when the Google drift on a bold row exceeds ~25 % or the stay dates
    move, re-read.
11. **20 properties, not 8, since 2026-08-22** ("track everything luxury
    nightly" — every 5★ FHR candidate that fit 3 on the portal, plus the
    Edit/THC wildcards). SIN bold moved to **The Capitol Kempinski** (FHR,
    $125 F&B credit, free 4th night → ~$166/night net vs St. Regis ~$444);
    that bold drives the 🛏️ stay math, and a free-4th-night hotel prices 3n
    and 4n identically, so expect the math to favour 4N. Quota: ~0.30
    min/property → ~6 min/night ≈ 180 min/month vs the 60-min free tier;
    `should_conserve` scatters ~2 nights in 3 onto local Chrome (local
    spacing widened to 8–20 s so 20 searches do not resemble the 2026-08-03
    burst). Browserbase Developer ($20/mo, 100 h) makes every night remote
    with no code change — Jalal's call.
```

Also bump the file's "eight hotel searches" / "8-property" mentions in rules 6b and 8 to "20" where they describe the current run, leaving historical measurements ("two 8-property runs billed 2.25 min") as they are.

- [ ] **Step 2: Update the fleet catalog** in `~/PycharmProjects/github-notion-sync/schedule_snapshot.py`: line 44 `(8 properties)` → `(20 properties since 2026-08-22)`; line 46 `Uses Browserbase (60 free min/month) for ~26 nights and local Chrome for ~4 paced, scattered nights` → `Uses Browserbase (60 free min/month) for ~10 nights and local Chrome for ~20 paced, scattered nights at 20 properties — the $20 Developer plan would make it all-remote`. Commit there:

```bash
cd ~/PycharmProjects/github-notion-sync && git add schedule_snapshot.py && git commit -m "catalog: dhaka-hotels now 20 properties" && git push
```

- [ ] **Step 3: Commit AGENTS.md and push the trip repo**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
git add AGENTS.md && git commit -m "docs: portal anchors + 20-property shortlist rules" && git push
```

- [ ] **Step 4: Memory.** Update `~/.claude/projects/-Users-jalalchowdhury/memory/project_ist_sin_card_hotels.md`: shortlists → the 20-row anchored table lives in the repo; Capitol Kempinski is the SIN recommendation ($166/n net, free 4th night, Kempinski brand); IST unchanged (Ritz value / Shangri-La Bosphorus TA 4.8 at the same money / Sanasaryan cheapest); FHR ≈ Google × 1.23–1.55; tax 19–20 %; portal read method + "never automate the login". Update the MEMORY.md hook line accordingly.

---

## Self-review

- **Spec coverage:** expand to everything luxury (T1 shortlist, T8 live check) ✓ · calibration: per-hotel FHR anchor + real tax (T1 anchors/est/drift, T2 stay math, T3 verify, T5 Telegram, T6 site) ✓ · quota handling for 20 (T4) ✓ · docs/catalog/memory (T9) ✓ · first-night `bold_row` gap handled (T8 step 2) ✓.
- **Placeholders:** none — every step has code or an exact command.
- **Type consistency:** `hotel_net(row, n)` / `score_adjust(row, n, incumbent_n)` used identically in T2 and tests; `anchor` keys (`date,total,nights,allin_night,credit,free_night_min,promo,google,google_date`) identical in T1 `anchor_for`, T2 fixture, T3 verify, T6 JS; `est_allin_night`/`drift_pct` names identical across T1/T2/T3/T5/T6; `PER_PROPERTY_MINUTES`/`EST_RUN_MINUTES`/`monthly_demand_minutes` consistent in T4 code and tests.
- **Known judgment calls to surface at handoff:** SIN bold → Kempinski (flip `bold` in `SHORTLIST` to revert); `fs_bosphorus` uses `match: "Bosphorus"` (also true of Shangri-La/Swissôtel/Hilton Bosphorus titles — the query pins it to Four Seasons, and T8 proves it live); sorting the tables cheapest-first replaces the hand order.
