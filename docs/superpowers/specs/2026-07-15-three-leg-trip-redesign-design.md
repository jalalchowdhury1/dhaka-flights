# Three-Leg Trip Redesign — BOS → DAC → DPS → BOS

**Date:** 2026-07-15 · **Status:** Approved by Jalal (chat, mobile)

## Trip (hard requirements)

- Travelers: **2 adults + 1 child (own seat)**
- Leave Boston **Jan 4, 2027 or after**; back in Boston **by Feb 7, 2027**
- **≤ 29 days in Bangladesh** (30-day visa, 1-day safety margin), counted arrival day → departure day
- **5 nights in Bali** (Marriott 5th-night-free redemption)
- Cheapest total wins; long layovers (IST/HKG style) are fine — traveling with a small child, breaking up the journey is a plus

## What changes

The tracker stops searching round trips (BOS⇄DAC, BOS⇄BKK) and instead searches
**three one-way legs**, each over a small date window:

| Leg | Route | Depart dates tracked |
|-----|-------|----------------------|
| 1 | BOS → DAC | Jan 4, 5, 6 |
| 2 | DAC → DPS | Feb 1, 2, 3 |
| 3 | DPS → BOS | Feb 5, 6, 7 |

9 searches/day (was 32).

## Components

- **`scraper.py`** — `LEGS` config replaces `DEPART_DATES`/`RETURN_DATES`/route pairs.
  Form flow gains: switch trip type to *One way*; passengers = 2 adults + 1 child
  (Add adult ×1, Add child ×1); no Return-date fill. Origin/destination pickers are
  generalized (keyword list per airport: Boston Logan / Hazrat Shahjalal / Ngurah Rai–Denpasar).
  Parser accepts "one way total" result lines. All 2026-07-15 hardening (DIAG, blank-page
  bail, retry, early abort, zero-tree dump) is preserved.
- **`main.py` / `run_daily.py`** — after scraping, a **combo optimizer** picks the cheapest
  valid (leg1, leg2, leg3) triple subject to: Dhaka stay ≤ 29 days (leg-1 arrival assumed
  depart+1 day), leg3 = leg2 arrival + 5 nights (leg-2 arrival assumed same day), leg-3
  arrival ≤ Feb 7 (flagged, not enforced — user checks arrival time when booking).
- **`notify_telegram.py`** — message becomes: cheapest valid full combo (per person and
  ×3 total) + cheapest option per leg with airline/stops/date + booking links.
- **`sheet_writer.py`** — unchanged schema; "Return" column left blank for one-way rows
  (route column already identifies the leg).
- **Tests** — update URL/parser tests for one-way phrasing; add combo-optimizer tests
  (visa cap, 5-night rule, missing-leg handling).

## Error handling

Unchanged from the hardened design: per-route retry, DIAG counters, early abort after 4
dead routes, Telegram distinguishes local-browser failure from genuine 0 results. New:
if any leg has zero valid prices, the combo section says which leg is missing instead of
silently showing nothing.

## Out of scope (manual, one-off today)

Single-airline multi-city fares (e.g., Qatar BOS→DAC + DPS→BOS on one ticket) and
budget-carrier DAC→DPS options — researched by hand today, not tracked daily.

## Addendum (same day, approved in chat): open-jaw watch + Vercel dashboard

- `scrape_openjaw_all()` adds 2 daily multi-city searches (BOS→DAC Jan 4 + DPS→BOS
  Feb 6 / Feb 7, one ticket) — found ~$1.7k cheaper than separate one-ways.
- `combo.best_structures()` ranks ticketing structures (one-ways vs open-jaw +
  compatible DAC→DPS middle leg) under the same trip rules; Telegram leads with it.
- `publish.py` writes `site/data.json` (results + per-day history) and pushes; the
  static dashboard at dhaka-flights.vercel.app fetches it raw from GitHub per load,
  so data updates need no redeploy.
