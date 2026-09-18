# ROLLBACK — three ways to revert the jev-fast changes

## 1. Env var (fastest, preferred)

Unset `SCRAPER_ENGINE` on the nightly machine:

```bash
unset SCRAPER_ENGINE
```

Or edit the launchd plist to remove any environment setting:

```bash
# Nightly runs SCRAPER_ENGINE=unset = legacy engine
# Nothing Jev-related executes
```

Nothing to do — the default is legacy engine. This is the normal nightly behavior.

## 2. Per search (graceful degradation)

Delete `AI_GATEWAY_API_KEY` from `.env` for one run.

When `jev_client.pick()` cannot call Jev (key missing, API down, timeout), it returns `(None, 0)` and increments `DIAG["jev_fallbacks"]`. The scraper_jev engine falls back to legacy `_find_ref` substring matching and keeps working — just without the speed benefit and potential Jev picks.

## 3. Git

`main` never moved; the whole feature is branch `jev-fast` in a separate worktree. Discard everything with:

```bash
# From any terminal:
git worktree remove --force /Users/jalalchowdhury/PycharmProjects/dhaka-flights-jev
git branch -D jev-fast
```

(Jalal or Claude runs this, not you.)