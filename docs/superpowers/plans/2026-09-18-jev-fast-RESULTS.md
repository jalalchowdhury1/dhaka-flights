# jev-fast RESULTS — 18 Sep 2026

**STATUS: DONE — correctness proven, deadline goal met, speed targets G4/G5 NOT met as written.**
Merge / `SCRAPER_ENGINE=jev` is Jalal's call. `main` is untouched except one unrelated
commit (`81754a4`, overrun guard 35 → 45 min), already merged into this branch.

## One-paragraph truth

The first version of this engine (DeepSeek, earlier today) looked 50 % *slower* than legacy.
That number was wrong: three bugs meant Jev never actually ran (server read stdin to EOF so
every pick timed out; every `wait_for` predicate compared a capitalised needle against
`text.lower()` so every wait hit its maximum; `bench.py` never started the Jev server). After
the rewrite the engine is **~30-40 % faster per search** with results identical to legacy, and
a full 30-search run finishes in **28-33 min with zero deadline skips**. The speed comes from
*readiness polling* (stop sleeping the moment the page is ready), **not** from Jev's decisions:
on Jalal's airports (DAC/SIN/BOS/IST/BKK) each dropdown has exactly one matching line, so the
code picks it deterministically and Jev is called 0-1 times per run. Jev is a safety net for
ambiguous dropdowns.

## Gates

| Gate | Target | Result | Verdict |
|---|---|---|---|
| G1 | pytest green | 385 pass; 7 fail in `tests/test_notify_fallback.py` — same 7 fail on `main` (ordering leak, pass alone) | PASS |
| G2 | `scraper.py` byte-identical to main; `run_daily.py` change small | `git diff main -- scraper.py` empty; `run_daily.py` +25/-4 (soft cap was 25) | PASS (line count marginal) |
| G3 | correctness within 15 % of legacy | one-way A/B 9/9 Jev runs identical to legacy (14 flights, $746 cheapest) on 3 dates; smoke 3x identical ($746/$1,076/$1,043); multi-city count/price flips are Google's (legacy flips identically) | PASS |
| G4 | median per-search <= 50 % of legacy | one-way 28-46 s (median ~33 s) vs 46-51 s (~60-70 %); Ticket ① 61-76 s vs 87-112 s; Ticket ② 57-62 s vs 72-75 s | **NOT MET** (~60-70 %) |
| G5 | full 30 searches <= 12 min, twice, 0 deadline skips | 28.1 / 32.1 / 33.2 min, 0 deadline skips all three | **12 min NOT MET; 0 skips MET** |
| G6 | <= $0.10 Jev spend per run | v2/v3: 0-1 Jev calls per full run (v1: 93 calls, ~0.8-1.0 s each) | UNVERIFIED in dollars — read the Vercel AI Gateway dashboard |
| G7 | degrades without key | `--no-key`: `jev server: NOT running`, 9/15/15 flights, 27.5 s median, 0 errors | PASS |
| G8 | rollback works | default engine is legacy when `SCRAPER_ENGINE` is unset (`import run_daily` prints `SCRAPER = legacy`); ROLLBACK.md written; no full nightly drill run (never run `run_daily.py`) | PARTIAL |

**Why G5's 12 min was unrealistic:** 30 searches x ~25 s floor is already ~13 min for the
one-ways alone; multi-city searches are 60-75 s each. The real goal was "finish under the
deadline instead of skipping searches" — met, with the deadline now 45 min.

## Evidence (real runs, all live Google Flights)

Full runs (`bench/*-jev-full.json` — `bench/` is gitignored, so the JSONs live only on the Mac mini; all `--set full`, same browse daemon):

| Finished (UTC) | Code | Total | Deadline skips | Wait timeouts | Engine fallbacks | Jev calls |
|---|---|---|---|---|---|---|
| 18:33Z | DeepSeek original (never used Jev) | 36.7 min | 0 | 204 | 0 | 0 |
| 19:34Z | v1 rewrite (`9e7b7ab`) | 28.1 min | 0 | 24 | 1 | 93 |
| 20:14Z | v2 (`e0cf5cd`) | 32.1 min | 0 | 1 | 1 | 1 |
| 21:15Z | v2 + one-way expander wait (`191db35`) + 45 min merge | 33.2 min | 0 | 2 | 2 (stale pick ref) | 0 |

Same-hour A/B (legacy vs Jev, alternating; `scratchpad/ab-check.log`, `oneway-stress.log`,
`stopover-check.log`):

- DAC→SIN Jan 28: legacy 14 flights / $746 (48.7, 49.6, 45.7 s); Jev after fix 14 / $746 four
  times (28.0-32.7 s). Before the fix Jev returned **7 flights, missing the $746 cheapest**, once.
- DAC→SIN Jan 29 / Feb 1: legacy 14 / $746; Jev 14 / $746 (35.7, 35.6, 35.3 s; 40.1, 46.0 s).
- Ticket ① (both configs, after the pick-retry fix): 4 runs, 0 engine fallbacks, 1 retry that
  recovered; 61-76 s vs legacy 87-112 s.
- Per-phase timing of a one-way (30 s): open form 1-6, ticket type 1, passengers 3, airports 7,
  date 3, results wait 7-8, expand 4-5.

## Bugs found and fixed this session (beyond the three root causes above)

1. **One-way partial read** — top flights alone look "settled"; the cheap ones sit behind
   "View more flights". Settle now needs 2 stable polls AND (expander visible OR >= 10 priced
   rows), capped at 14 s.
2. **Stale airport pick ref** — autocomplete re-renders, click hits "Unknown ref", dropdown stays
   open, next box vanishes -> whole search fell back to legacy. `_fill_airport` retries once.
3. **`run_daily.py` NameError** — the engine switch removed the import that defined
   `SCRAPER_DIAG`, still used at the end of `main()`: every nightly run (legacy too) would have
   crashed after scraping. Fixed; `tests/test_run_daily_names.py` catches it (fails on the old
   file, passes on the fix).
4. `bench.py --no-key` was a no-op (`load_dotenv` restored the key); now sets it to `""`.
5. BKK picks: exact legacy keyword (`option: Bangkok, Thailand`) so Bangkok Yai/Noi never match;
   the loose keyword is used only for "does the box show it" checks.
6. Multi-city settle: 2 stable polls + 8 s minimum wait (the "$18,913 lesson" — results arrive in
   slow bursts).

## Known limits — read before merging

- **Google's thin-result state hits BOTH engines.** Multi-city searches sometimes return a reduced
  set (Ticket ② SIN-first Jan 28 + Feb 1: 4 options, cheapest $4,283, while tonight's nightly and a
  Jev run show the real cheapest ≈ $1,080-1,095; Ticket ① flips 7 options/$3,630 <-> 3 options/
  $18,917 within minutes). Legacy shows the same flips. Repeating an identical search several
  times in a row seems to trigger it; the nightly runs each search once. Not fixed here — a
  "cheapest is > 2x last night's" retry in `run_daily` would be the next step.
- **The 33.2 min run predates the pick-retry patch** (`2340033`). The patch only touches the
  failure path and was live-checked separately (4 Ticket ① runs, 0 fallbacks) — but no full run
  has been done on the final commit.
- G6 dollars and a real overnight run on `SCRAPER_ENGINE=jev` are still unverified.

## To turn it on (Jalal's decision)

1. Merge `jev-fast` into `main`.
2. Put `AI_GATEWAY_API_KEY` in main's `.env` (missing key = Jev silently off, legacy picks).
3. Export `SCRAPER_ENGINE=jev` in `run_daily.sh` (or the plist). Unset = legacy.
4. Watch the first night's `cron.log` for `engine: jev`, deadline skips, and the ⚠️ warnings.
Rollback: unset `SCRAPER_ENGINE` (see ROLLBACK.md).
