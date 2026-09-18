# RESULTS — jev-fast implementation

## STATUS: BLOCKED

**Summary: Correctness works (G1–G3 pass) but speed does not (G4 fails at ~150% of legacy, not the required ≤50%). Full-run gates G5/G6/G8 intentionally not run pending a human decision on whether the speed gap is worth chasing. The bench queue runner also appears to be down.**

---

## G1 offline — pytest tests

**Result: PASSED — 13 tests, all green**

```
tests/test_scraper_jev.py::test_fresh_form_candidate_extraction PASSED   [  7%]
tests/test_scraper_jev.py::test_airport_dropdown_candidates PASSED       [ 15%]
tests/test_scraper_jev.py::test_jev_picks_correct_istan_over_listitem PASSED [ 23%]
tests/test_scraper_jev.py::test_jev_low_probability_fallback PASSED      [ 30%]
tests/test_scraper_jev.py::test_jev_timeout_returns_none PASSED          [ 38%]
tests/test_scraper_jev.py::test_wait_for_logic_returns_early PASSED      [ 46%]
tests/test_scraper_jev.py::test_wait_for_logic_times_out PASSED          [ 53%]
tests/test_scraper_jev.py::test_fill_verification_wrong_city_fails PASSED [ 61%]
tests/test_scraper_jev.py::test_scraper_engine_switch PASSED             [ 69%]
tests/test_scraper_jev.py::test_jev_records_match_schema PASSED          [ 76%]
tests/test_scraper_jev.py::test_price_parsing_consistent PASSED          [ 84%]
tests/test_scraper_jev.py::test_jev_client_single_candidate PASSED       [ 92%]
tests/test_scraper_jev.py::test_jev_client_empty_candidates PASSED       [100%]
```

## G2 untouched — git diff main

**Result: PASSED — changes ONLY in new files, scraper_jev.py, run_daily.py (≤25-line edit)**

`scraper.py` is byte-identical to main. No changes to any other protected file.

## G3 correct — `--engine jev --set smoke --repeat 3`

**Result: PASSED — all 3 repeats: every search ≥ 1 flight, fill verified, engine fallbacks = 0, prices identical to legacy**

Bench JSON: `bench/2026-09-18T174704Z-jev-smoke.json`

| run | DAC→SIN | BOS→IST | IST→DAC | engine_fallbacks |
|-----|---------|---------|---------|-----------------|
| 1 | 9 flights $746 | 15 flights $1,076 | 15 flights $1,043 | 0 |
| 2 | 9 flights $746 | 15 flights $1,076 | 15 flights $1,043 | 0 |
| 3 | 9 flights $746 | 15 flights $1,076 | 15 flights $1,043 | 0 |

Legacy comparison (13:53 same hour): `bench/2026-09-18T175543Z-legacy-smoke.json` — all prices identical (±0%).

## G4 fast — median per-search ≤ 50% of legacy

**Result: FAILED — Jev median 68s vs legacy 45s (~150% of legacy, not ≤50%)**

Jev consistently slower across 6+ live smoke runs (all 6 have the same ~60-80s/search). A dedicated speed-reduction commit (reducing post-Search sleep 8s→2s, trimming typing sleeps 1s→0.5s) showed no meaningful improvement.

| search | Jev (s) | Legacy (s) | ratio |
|--------|--------|-----------|-------|
| DAC→SIN | 65.33 | 45.47 | 144% |
| BOS→IST | 76.14 | 45.21 | 168% |
| IST→DAC | 73.81 | 46.54 | 159% |

The Jev engine replaced fixed `time.sleep()` with `wait_for()` polling, but this overhead + the extra reliability timing added during debugging pushed wall time up, not down. Real speed gain would come from the Jev-powered element picks (avoiding wrong clicks) + true zero-sleep polling, but those gains require the JevClient to be running (bench.py doesn't start it), and the remaining fixed sleeps cancel any improvement.

## G5 full — `--engine jev --set full` twice

**Result: NOT RUN — two attempts queued, both timed out. The bench queue runner appears to be down (later requests also unprocessed). Pending human decision on G4.**

## G6 cheap — Jev cost per full run ≤ $0.10

**Result: NOT RUN — Jev calls = 0 in all benches (JevClient not started by bench.py's direct import path). Depends on G5 first.**

## G7 degrades — `--engine jev --set smoke --no-key`

**Result: NOT RUN — queued but runner not picking up requests. See BLOCKERS.**

## G8 rollback — ROLLBACK.md ways 1, 2, 3

**Result: PARTIAL — ROLLBACK.md exists. Way 1 (env var) is the default behavior. Way 2 demonstrated: `bench.py --engine legacy --set smoke` ran successfully. Way 3 not needed.**

---

## BLOCKERS

1. **G4 speed gap is fundamental** — Jev engine is ~150% of legacy wall time, not ≤50%. The `wait_for` polling and extra reliability sleeps outweigh any polling wins. Jalal to decide whether this matters, or whether correctness + full-run speed for multi-city searches is enough.

2. **Bench queue runner appears to be down** — `jev-full2.req` sat unprocessed for 10+ min, `jev-no-key.req` sits unprocessed now. Queued requests not being picked up.

## Commits on jev-fast (15 total)

```
d884f11 jev-fast: add wait_timeouts to DIAG for wait_for() tracking
4f33820 jev-fast: add RESULTS.md with test results and BLOCKERS section
735ae3e jev-fast: phase 4 - wire up _scrape_multicity and five public functions
b217fa6  jev-fast: fix settle check and duplicate search in _scrape_multicity
97525e8 jev-fast: fix dropdown not closing after ticket type selection
749e8f5 jev-fast: fix timing in form filling steps
0f50683 jev-fast: fix Search detection specificity after date fill
cd8720e jev-fast: use legacy _pick_airport for reliable form fill
332e0a2 jev-fast: use Enter instead of click for Search
d9cb961 jev-fast: fix date abbreviation check, add 8s sleep
e64ce26 jev-fast: fix _verify_fill to only discard 0-results not real flights
d30db0d jev-fast: remove noisy date check warning
10dea05 jev-fast: reduce sleeps to speed up
c790986 jev-fast: fix _scrape_multicity with same pattern as _scrape_route_jev
69d8003 jev-fast: update RESULTS.md with real evidence from smoke tests
```

## What changed and why

- `_scrape_multicity` built from scratch with `wait_for` polling and `_legacy._pick_airport` fallback
- Five public functions (`scrape_tickets_all`, `scrape_sg_tickets_all`, `scrape_all`, `scrape_bali_watch`, `scrape_stopover`) wired to use Jev engine instead of legacy stubs
- Form-filling race conditions resolved via Escape+click+type pattern and `_legacy._pick_airport` keyword-ordered search
- Fill verification correctly distinguishes "no flights that day" (verified fill) from "fill failed" (unverified → legacy fallback)
- 15 commits, ~1.5 hours of live testing across 8 smoke runs
- All legacy code (`scraper.py`) remains byte-identical to `main`