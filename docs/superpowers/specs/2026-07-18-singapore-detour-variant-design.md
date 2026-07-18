# Design: Singapore-detour trip variant, tracked nightly alongside the direct trip

**Date:** 2026-07-18
**Status:** Approved (user answered all design questions)
**Repo:** dhaka-flights

## Problem / goal

The tracker prices one itinerary: BOS → Dhaka → Bali → BOS. Jalal wants to also
track a variant where the Dhaka stay is **2 nights shorter** and those nights are
spent in **Singapore** on the way to Bali: BOS → Dhaka → **Singapore (2 nights)** →
Bali → BOS. Both the direct and via-Singapore trips are tracked **every night**, and
the daily brief shows both so the cost of adding Singapore is visible.

The two hard anchors stay fixed: **5 Bali nights** (Marriott 5th-free) and **home by
Feb 7, 2027**. So the Dhaka departure just moves ~2 days earlier; Bali and the return
are unchanged.

## Decisions (from user)

1. **Alongside**, not replace — show direct and via-Singapore side by side.
2. **Price the Singapore middle both ways, show the cheaper**: as two one-way tickets
   (DAC→SIN + SIN→DPS) AND as one multi-city ticket (DAC→SIN→DPS); the cheaper valid
   one wins.
3. **Dates:** DAC→SIN Jan 29–Feb 1; SIN→DPS Jan 31–Feb 3; BOS→DAC (Jan 4–6) and
   DPS→BOS (Feb 5–7) unchanged.

## Approach

Add the Singapore variant as **new, isolated logic** that runs parallel to the working
direct-trip path — the direct `best_structures`/`best_combos` code is NOT modified in
its ranking, to avoid destabilizing it (it already caused one silent-dropped-fare bug).

### scraper.py
- `AIRPORT_PICK["SIN"] = ["Singapore Changi", "Singapore"]`.
- Add two one-way legs to `LEGS`: `DAC→SIN` (Jan 29–Feb 1) and `SIN→DPS` (Jan 31–Feb 3).
  These get scraped, written to the sheet, and feed the combo logic; sanity check #2
  auto-covers them (warns if a Singapore search returns nothing).
- New `SG_TICKET_SEARCHES` (DAC→SIN + SIN→DPS multi-city pairs, 2-night-Singapore
  aligned) + `scrape_sg_tickets()`, reusing `_scrape_multicity` / `_parse_openjaw_results`.
  Returned in a **separate list** (`sg_tickets`), NOT mixed into `openjaws` — the direct
  open-jaw loop would mis-pair them.

### combo.py — new `best_singapore(flights, openjaws, sg_tickets, top_n=3)`
- Constants: `SG_ROUTES=("DAC→SIN","SIN→DPS")`, `ALLOWED_SG_NIGHTS=(1,2,3)`,
  `IDEAL_SG_NIGHTS=2`.
- Build the **Singapore middle** candidates two ways and keep all:
  - two one-ways: DAC→SIN `a` + SIN→DPS `b`, valid if Singapore nights =
    (b.depart − a.arrive) ∈ ALLOWED_SG_NIGHTS. cost = a+b.
  - multi-city ticket: each `sg_ticket`, cost = its total; Singapore nights from its
    two leg dates.
- Build the **full via-SIN trip** = long legs + middle, long legs either:
  - two one-ways BOS→DAC + DPS→BOS, or
  - a direct open-jaw ticket (BOS→DAC+DPS→BOS) from `openjaws`.
- Validity = Dhaka stay ≤29 days (both ends), Bali nights ∈ ALLOWED (prefer 5),
  home ≤ Feb 7. Same flag-don't-drop rule as the direct path.
- Return cheapest-first list, entries shaped like `best_structures` entries plus
  `trip:"via-SIN"`, `sg_nights`, and which middle kind won.

### notify_telegram.py
- After the direct block, a `🇸🇬 *Via Singapore (2 nights)*` section: best via-SIN
  total, Δ vs the best direct total, and the Singapore leg lines. `SIN` emoji added.

### publish.py
- Add `singapore` (best via-SIN structure) to the payload and `singapore_total` to the
  history entry, so the dashboard/History can chart it.

### sanity.py
- Extend so a scraped-but-unrepresented Singapore option warns (same "never drop
  silently" principle), and the new SG legs are covered by the existing per-leg check.

## Testing
- `pytest tests/ -q` must stay green; add `test_singapore.py` (middle pairing, night
  math, cheaper-of selection, validity flags) with synthetic fixtures.
- One real `./run_daily.sh` (stamp deleted) to confirm the Singapore searches scrape,
  the brief shows both trips, and the sheet has the new legs.

## Runtime / risk
- ~2 new one-way searches + ~2 multi-city searches ≈ +4 min on the ~12-min run —
  still finishes well before the 5:30 AM cutoff.
- Isolated code path → the direct trip's tracking is unaffected if the Singapore
  logic has a bug (it just won't show a via-SIN line).
