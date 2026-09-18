# BRIEF — make the nightly Dhaka-flights scrape FAST with a Jev-driven engine

Written 2026-09-18 by Claude (Fable) for DeepSeek Harness. You (DeepSeek) build
it. Claude reviews it afterwards. Nothing you build touches the nightly run
until Claude signs off and Jalal merges. **Speed is the only goal. The old
scraper stays as the fallback.**

Read `AGENTS.md` in this repo first (sections 1, 3, 5, 5b). Then this file,
all of it. Then `scraper.py` lines 80–415 and 537–670, all of it.

---

## 0. The problem in one paragraph

Every night at 00:00 `run_daily.py` scrapes 30 Google Flights searches through
the `browse` CLI (local Chrome, accessibility tree, one browser session per
run). A search takes ~45–60 s. The run has a 35-minute deadline
(`scraper.RUN_DEADLINE_MIN`), and it is HITTING it — `cron.log` on the nights
of 15 and 16 Sep 2026 shows `DEADLINE: skipping remaining 18 one-way searches`
and `DEADLINE: skipping Bali watch entirely`. Skipped searches = missing prices
= a worse trip decision. Jalal's words: "I want to cut that time out, I want to
do it as fast as possible."

Where the time goes (read the code, then MEASURE it yourself in Phase 1):
- ~30 s per search of fixed `time.sleep(...)` calls that guess how long Google
  takes, instead of watching the page.
- 8–12 `browse snapshot` calls per search, each a subprocess spawn.
- `_find_ref`/`_find_refs` pick DOM elements by substring matching. The code's
  own comment documents "IST" matching random `listitem` lines, and a wrong
  click derails the whole form → retries → more time.
- A fixed 8 s sleep after clicking Search, then a 5 s-step poll for results.

## 1. What you are building

A second scraping engine, `scraper_jev.py`, with the SAME public API as
`scraper.py`, that produces the SAME records, in roughly HALF the wall time,
selected by an environment variable with the old engine as the default and as
the per-search fallback.

The two ingredients, taken from `browser-use/jev-ultrafast` (the idea) and
`~/.claude/skills/webai/jev-pick.mjs` (the working code, reproduced in §6):

1. **Readiness polling instead of sleeping.** `jev-ultrafast` never sleeps a
   fixed amount: snapshot → decide → act → snapshot. You do the same: every
   `time.sleep(x)` with x ≥ 0.5 in the driving code becomes
   `wait_for(predicate, timeout)` that polls `browse snapshot` at a short step
   and returns the moment the page shows what the next step needs. Most
   predicates are deterministic string checks on the tree (e.g. after clicking
   "Change ticket type", wait until the tree contains `option: One way`).
2. **Jev picks the element when substring matching is ambiguous.** Jev
   (`typesafe-ai/jev` via the Vercel AI Gateway) is a decision-only model: give
   it page state + a bounded list of candidate tree lines + an instruction, it
   returns one choice with a probability, in ~70–500 ms, ~$0.0002 per call.
   Use it wherever `_find_ref` today either finds several matching lines or
   finds none: airport-dropdown suggestions, `Done`/`Search`/`Add adult`
   buttons when duplicated, the multi-city `Where from`/`Where to`/`Departure`
   rows. Never for parsing prices — the parsers stay exactly as they are.

Jev alone is not what makes it fast. Fewer wrong clicks + no blind sleeps is
what makes it fast. Jev is what lets you drop the sleeps without becoming
fragile.

## 2. Hard rules (any violation = Claude rejects the whole branch)

1. **Work ONLY in this worktree**: `/Users/jalalchowdhury/PycharmProjects/dhaka-flights-jev`,
   branch `jev-fast`. Never `cd` into `/Users/jalalchowdhury/PycharmProjects/Dhaka flights`
   (that is `main`, the live nightly checkout). Never `git checkout main`,
   never `git merge`, never `git push`. Commit on `jev-fast` after every phase.
2. **`scraper.py` stays byte-identical to `main`.** It is the backup engine.
   `git diff main -- scraper.py` must be empty at the end. Import from it;
   never edit it.
3. **These files stay byte-identical too:** `run_daily.sh`, `notify_telegram.py`,
   `publish.py`, `sheet_writer.py`, `combo.py`, `verify.py`, `sanity.py`,
   `alerts.py`, everything under `site/`, and the launchd plist
   (`~/Library/LaunchAgents/com.jalal.dhaka-flights.plist`, don't even read
   it with intent to change it). `run_daily.py` may change by ≤ 25 lines, only
   for the engine switch in §3.
4. **Never run `run_daily.py` or `run_daily.sh`.** They send Telegram, write
   the Google Sheet, publish `site/data.json`, and stamp `.last_run_date`. Use
   `bench.py` (§4) for every live test.
5. **Browser time window: run live tests only between 07:30 and 23:30 local
   time.** `browse stop` kills the shared daemon; running a bench at 00:00–05:30
   would kill the real nightly run and the 05:00 hotel job. `bench.py` must
   enforce this itself and refuse to start outside the window.
6. **One browser session per run** (AGENTS.md speed rule 1). Reuse
   `scraper._ensure_session`, `scraper._session_dirty`, `scraper.end_session`.
   Never a per-search `browse stop`. Never a second parallel browser session
   or parallel searches — Google throttles, and the benchmark must be honest.
7. **Keep the "$18,913 lesson"** (AGENTS.md §5b, `scraper._wait_for_results`):
   results are done only when the number of priced rows is the SAME on two
   consecutive snapshots. You may shorten the poll step; you may not remove
   the settle check.
8. **Jev sees ONLY Google Flights accessibility-tree lines.** Nothing from
   `.env`, nothing from other files, no file paths, no names. The candidate
   strings you send are tree lines and nothing else.
9. **Every Jev pick has a floor and a fallback.** Accept a pick only if
   `p ≥ 0.6` AND the choice is one of the candidates you sent; otherwise fall
   back to the legacy substring result. If the Jev process is down, the key is
   missing, or a call exceeds 3 s, the engine keeps working via the fallback
   and counts it in `DIAG["jev_fallbacks"]`. A missing key must never crash a
   run.
10. **Per-search fallback to the legacy engine.** If a search in the Jev
    engine raises, hits a blank page, fails to fill the form (see §3
    "fill verified"), or finishes with 0 results while the fill was NOT
    verified, re-run THAT search once through the corresponding
    `scraper.scrape_*` function in the same browser session, and count it in
    `DIAG["engine_fallbacks"]`.
11. **No new Python dependencies** beyond `requirements.txt`. Node deps only
    inside `jev/` (`ai`, `@ai-sdk/gateway`, pinned). Add `jev/node_modules/`
    and `bench/` to `.gitignore`.
12. **Do not build URL-direct searches** (encoding the search into the
    Google Flights `tfs` URL parameter). Out of scope for this brief; noted
    for a later one.
13. **Don't ask Jalal questions mid-task and don't send Telegram.** If you
    are blocked, write the blocker under "BLOCKERS" in `RESULTS.md` (§5),
    commit, and stop.

## 3. Design contract

### Files you create (all new)

| file | what |
|---|---|
| `jev/package.json`, `jev/jev-server.mjs` | ONE long-lived Node process per run. Line-delimited JSON over stdin/stdout. Request: `{"id":n,"instructions":"...","state":"...","candidates":["..."]}`. Response: `{"id":n,"choice":"...","index":i,"p":0.93,"ms":142}` or `{"id":n,"error":"..."}`. Uses the code in §6. Reads `AI_GATEWAY_API_KEY` from its environment. Starting Node once matters: spawning `node` per pick costs ~1 s each. |
| `jev_client.py` | Python side. `JevClient.start()` (spawns the server with the repo `.env` loaded via `python-dotenv`, like `run_daily.py` does), `pick(instructions, candidates, state) -> (choice or None, p)`, 3 s timeout per call, `stop()`. Counts calls, ms, fallbacks into `scraper.DIAG` (add keys `jev_calls`, `jev_ms`, `jev_fallbacks`, `engine_fallbacks`; `DIAG` is a plain dict — adding keys is fine). |
| `scraper_jev.py` | The engine. Exports every public name `run_daily.py`, `main.py` and `sanity.py` import from `scraper` (`scrape_all`, `scrape_tickets_all`, `scrape_sg_tickets_all`, `scrape_bali_watch`, `begin_run`, `end_session`, `DIAG`, `LEGS`, `TICKET2_SEARCHES`, …). Constants, parsers (`_parse_results`, `_parse_openjaw_results`, `parse_price`) and session helpers are imported from `scraper`, not copied. Only the DRIVING functions are re-implemented: `scrape_route` and `_scrape_multicity` (and the thin wrappers that call them). Each must honour `scraper._past_deadline()` exactly as the legacy code does. |
| `run_daily.py` (edit, ≤ 25 lines) | `SCRAPER_ENGINE=jev` selects `scraper_jev`; anything else (including unset) selects `scraper`. Print one line at run start: `engine: legacy` or `engine: jev`. Nothing else changes. |
| `bench.py` | See §4. |
| `tests/test_scraper_jev.py` + `tests/fixtures/*.txt` | See §4. |
| `ROLLBACK.md` | Exactly the three ways back (§7), nothing else. |
| `docs/superpowers/plans/2026-09-18-jev-fast-RESULTS.md` | Your evidence file (§5). |

### "Fill verified"

Before you trust a results page, prove the form took your inputs: the tree on
the results page still shows the `Where from` / `Where to` values and the date.
Assert the expected city/airport names (`AIRPORT_PICK` / `TYPE_AS` in
`scraper.py`) and the date text appear in it. If they don't, the search is a
fill failure → legacy fallback for that search (rule 10). A verified fill with 0
results is a legitimate "no flights that day" and is NOT a fallback trigger.

### `wait_for`

```python
def wait_for(pred, timeout: float, step: float = 0.25) -> str:
    """Poll `browse snapshot` until pred(tree) is true; return the snapshot.
    On timeout return the last snapshot and count DIAG['wait_timeouts'] += 1."""
```

Every place the legacy code sleeps ≥ 0.5 s must become a `wait_for` with a
concrete predicate (write the predicate next to the step it unblocks). Small
sleeps (< 0.5 s) inside a click sequence may stay if you measured that removing
them breaks the click.

### Candidate extraction for Jev

A candidate is one tree line that contains a `[n-m]` ref. Build the list from
a cheap pre-filter (role, or a loose keyword set), cap it at 40 lines, and pass
the ref back exactly as `scraper._find_ref` does (`"@" + last ref on the
line`). Instructions are one plain sentence, e.g. `Pick the dropdown suggestion
for Istanbul airport (IST), not a list item that merely contains the letters
"ist".` Use Jev when the pre-filter yields ≥ 2 candidates, or when the legacy
substring match yields none. When it yields exactly 1, use it directly (no
call, same as `jev-pick.mjs`).

## 4. Tests and benchmarks — the deterministic finish line

### Offline (no browser, no network) — `python3 -m pytest tests/ -q`

Runner: `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3`
(the one `run_daily.sh` uses; pytest 8.4.1 is installed for it). Existing
tests keep passing, count unchanged. New `tests/test_scraper_jev.py` covers at
least:

1. Candidate extraction from a saved real snapshot (save 3–4 real trees into
   `tests/fixtures/` during Phase 1: fresh form, airport dropdown open,
   multi-city form, settled results page).
2. The "IST → listitem" case: with a fake Jev that returns the correct airport
   line, the engine picks it even though legacy substring picks the wrong line.
3. `p < 0.6` → legacy substring result is used; Jev error/timeout → same.
4. `wait_for` returns early when the predicate turns true, and times out
   cleanly.
5. Fill-verification: a results tree with the wrong city fails verification.
6. Engine switch: `SCRAPER_ENGINE` unset → `scraper`; `=jev` → `scraper_jev`.
7. Records from `scraper_jev` pass `schema_check.py` (same shape as legacy).
8. With `AI_GATEWAY_API_KEY` removed from the environment, `JevClient.pick`
   returns `(None, 0)` and increments `jev_fallbacks` — it does not raise.

### Live — `bench.py`

```
bench.py --engine legacy|jev --set smoke|full [--repeat N]
```

- Runs ONLY scraping (the same call sequence as `run_daily.main`:
  `begin_run` → `scrape_tickets_all` → `scrape_sg_tickets_all` → `scrape_all`
  → `scrape_bali_watch` → `end_session`, or the smoke subset). No Telegram,
  no Sheet, no publish, no stamp.
- `smoke` = 3 searches: one-way `DAC→SIN January 30, 2027`;
  `TICKET1_SIN_RETURN` (Ticket ①); `TICKET2_SEARCHES` entry 5 (BKK-first,
  Jan 28 + Feb 2). `full` = all 30.
- Refuses to start between 23:30 and 07:30 (rule 5).
- Writes `bench/<UTC-timestamp>-<engine>-<set>.json`: per search → wall
  seconds, flight count, cheapest price, fill verified?, Jev calls, Jev ms,
  Jev fallbacks, engine fallbacks, wait timeouts; plus run total and
  `DEADLINE` skips. Prints a one-table summary and the median per-search
  seconds.
- `--engine legacy` runs `scraper` untouched, so it doubles as the rollback
  drill.

### Gates — ALL must be green before you write "DONE"

| gate | requirement | evidence |
|---|---|---|
| G1 offline | `pytest tests/ -q` green; old test count unchanged; new tests ≥ 8 | pasted pytest tail |
| G2 untouched | `git diff main --stat` shows changes ONLY in: `run_daily.py` (≤ 25 lines), new files, `.gitignore` | pasted `git diff main --stat` |
| G3 correct | `--engine jev --set smoke --repeat 3`: every search ≥ 1 flight; fill verified on every search; engine fallbacks = 0 in at least 2 of 3 repeats; cheapest price per search within 15% of a `--engine legacy --set smoke` run in the same hour | both bench JSON paths + summary tables |
| G4 fast | median per-search seconds, jev ≤ 50% of legacy, same smoke set, same hour | the two summary tables |
| G5 full | `--engine jev --set full` twice, in different hours: total ≤ 12 min each; 0 `DEADLINE` skips; ≥ 27 of 30 searches with ≥ 1 flight; engine fallbacks ≤ 3 per run; wait timeouts ≤ 5 per run | both bench JSON paths + summaries |
| G6 cheap | Jev cost per full run ≤ $0.10 (calls × ~$0.0002 — report the call count; the AI Gateway dashboard is the source of truth, Claude will check it) | call count from bench JSON |
| G7 degrades | `AI_GATEWAY_API_KEY` removed from the environment for one `--engine jev --set smoke` run: completes, every search ≥ 1 flight, `jev_fallbacks` > 0, no crash | bench JSON path + summary |
| G8 rollback | `ROLLBACK.md` exists with the three ways in §7 and you have executed way 1 (env var) and way 2 (legacy bench) yourself | pasted output |

If a gate cannot be met, do NOT lower the bar in this file. Report the number
you reached and why under BLOCKERS.

## 5. Phases (commit after each one, message `jev-fast: phase N — ...`)

1. **Profile before you touch anything.** Run `bench.py --engine legacy --set smoke`
   with per-STEP timing (each sleep, each snapshot, each click, the results
   wait) and write `bench/profile-legacy.md`: a table of where the seconds go.
   Save the 3–4 fixture trees. This is the map; don't optimize blind.
2. **`jev/` server + `jev_client.py` + offline tests 3 and 8.** Prove one
   live pick works with a tiny script (`node jev/jev-server.mjs` with a
   hand-written request) and paste the JSON in RESULTS.md.
3. **`scraper_jev.scrape_route`** (one-way) with `wait_for`, Jev picks,
   fill verification, legacy fallback. Smoke bench on the one-way search only.
4. **`scraper_jev._scrape_multicity`** and the wrappers. Full smoke bench.
   Gates G3, G4.
5. **`run_daily.py` switch, `bench.py --set full`, gates G5–G8, `ROLLBACK.md`,
   `RESULTS.md`.** Then stop and write DONE at the top of RESULTS.md.

`RESULTS.md` layout: `STATUS: DONE | BLOCKED`, then one section per gate G1–G8
with the pasted evidence (real output, trimmed, never edited or estimated),
then BLOCKERS, then a short "what I changed and why" (≤ 20 lines). Claude
reads only this file first, then the diff.

## 6. Jev reference — working code from the webai skill (proven 17 Sep 2026)

Package versions that work: `"ai": "^7.0.105"`, `"@ai-sdk/gateway": "^4.0.85"`,
Node 24 at `/Users/jalalchowdhury/.nvm/versions/node/v24.15.0/bin` (already on
the run PATH). `"type": "module"` in `package.json`.

```js
// jev-pick.mjs — one-shot version. Your jev-server.mjs is this, wrapped in a
// readline loop over stdin with an `id` echoed back per line.
import { experimental_evaluate as evaluate } from 'ai';
import { gateway } from '@ai-sdk/gateway';

const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));

const results = await Promise.all(
  input.sites.map(async (site) => {
    if (!site.candidates || site.candidates.length === 0) {
      return { site: site.name, ms: 0, choice: null, index: -1, p: 0, error: 'no-candidates' };
    }
    if (site.candidates.length === 1) {
      return { site: site.name, ms: 0, choice: site.candidates[0], index: 0, p: 1 };
    }
    const t0 = performance.now();
    try {
      const result = await evaluate({
        model: gateway.evaluationModel('typesafe-ai/jev'),
        state: site.state || `Real accessibility-tree elements read from the live ${site.name} page right now.`,
        questions: {
          pick: {
            type: 'choice',
            instructions: site.instructions || 'Pick the element ...',
            criteria: Object.fromEntries(site.candidates.map((c) => [c, c])),
          },
        },
      });
      const ms = performance.now() - t0;
      const choice = result.answers.pick.choice;
      const index = site.candidates.indexOf(choice);
      const p = result.answers.pick.probabilities[choice];
      return { site: site.name, ms, choice, index, p };
    } catch (err) {
      const ms = performance.now() - t0;
      return { site: site.name, ms, choice: null, index: -1, p: 0, error: String(err.message || err) };
    }
  })
);
for (const r of results) console.log(JSON.stringify(r));
```

`gateway` reads `AI_GATEWAY_API_KEY` from the environment. The key is in this
worktree's `.env` (gitignored). Load `.env` in Python with `python-dotenv`
before spawning the server, and pass `env=os.environ` to the subprocess.

## 7. The three ways back (this is `ROLLBACK.md`)

1. **Env var** — nightly runs `SCRAPER_ENGINE` unset = legacy engine. Nothing
   Jev-related executes. This is the default even after merge.
2. **Per search** — inside the Jev engine every failed search re-runs through
   `scraper.scrape_*` (rule 10). A bad night degrades to the old speed, not to
   missing data.
3. **Git** — `main` never moved; the whole feature is branch `jev-fast` in a
   separate worktree. Discard everything with
   `git worktree remove --force /Users/jalalchowdhury/PycharmProjects/dhaka-flights-jev && git branch -D jev-fast`
   (Jalal or Claude runs this, not you).

## 8. Ask yourself before writing DONE

- Would the nightly run behave EXACTLY as before if nobody set `SCRAPER_ENGINE`?
- Did the speed come from removing blind sleeps and wrong clicks, or from
  weakening a check that exists because of a past incident? (AGENTS.md §5b.)
- Is every number in RESULTS.md pasted from a real run?
