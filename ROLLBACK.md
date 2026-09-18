# ROLLBACK — going back to the legacy engine

Since 18 Sep 2026 the nightly runs the **jev engine** (`scraper_jev.py`) by default.
The legacy engine (`scraper.py`, unchanged) is the backup — and the jev engine already
falls back to it per search when anything goes wrong.

## 1. Force the legacy engine (fastest, preferred)

In `run_daily.sh`, uncomment the one line:

```bash
export SCRAPER_ENGINE=legacy
```

Manual / catch-up runs: `SCRAPER_ENGINE=legacy python3 run_daily.py`.
`run_daily.py` prints `engine: legacy` (or `engine: jev`) at the top of every run.

## 2. Jev without the AI (keep the new engine, drop the model)

Delete `AI_GATEWAY_API_KEY` from `.env`. `jev_client` returns `(None, 0)`, the engine counts a
`jev_fallback` and uses the deterministic/legacy airport picks. This is what happens on Jalal's
airports anyway — Jev is called 0-1 times per run.

## 3. Automatic fallbacks already in place

- `run_daily.py`: if `scraper_jev` cannot be imported, it warns and uses the legacy engine.
- Per search: any jev-engine failure re-runs that one search through the legacy engine
  (`DIAG["engine_fallbacks"]`).

## 4. Git

The whole change is the commit range `81754a4..b5c1e83` plus the default-engine commit on top.
`git revert` that range, or `git checkout 81754a4 -- run_daily.py` (the last pre-jev version).
Jalal or Claude runs this, not a nightly job.
