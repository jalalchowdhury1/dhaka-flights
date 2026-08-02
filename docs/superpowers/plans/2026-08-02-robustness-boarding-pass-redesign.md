# Robustness + Boarding-Pass Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the dhaka-flights pipeline (push-retry, payload contract check, run-overrun guard) and rebuild the site as a hash-routed boarding-pass-styled dashboard with drill-in screens that can never render blank.

**Architecture:** Approach 1 from the spec (`docs/superpowers/specs/2026-08-02-robustness-boarding-pass-redesign-design.md`): the `data.json` contract is FROZEN; pipeline changes are three surgical, test-driven commits; the site is rebuilt fresh as `site/index_v2.html` (old site keeps running), QA'd against real + mutated payloads, then swapped in one commit + one Vercel deploy. Rollback = git tag `v1-pre-overhaul`.

**Tech Stack:** Python 3 + pytest (pipeline), single-file vanilla HTML/CSS/JS site (no framework, no build step), Vercel static hosting, data fetched raw from GitHub.

**Execution notes:**
- Work directly on `main` (Jalal's standing solo-repo preference) — every commit must leave the repo green because launchd runs the pipeline from this working copy at midnight. Never leave `run_daily.py`/`scraper.py`/`publish.py` broken between commits.
- Site visual work (Tasks 5–9): load the **design-taste-frontend** skill before writing CSS/markup, and the **dataviz** skill before touching the chart. The spec §3.3 defines the boarding-pass token values.
- Run tests with: `cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights" && python3 -m pytest tests/ -q` (152 tests green today).
- NEVER run `./run_daily.sh` or any live scrape during this work (same-day rescrape degrades the scraper — AGENTS.md §4b.3b).

---

### Task 1: Rollback tag + documented restore recipe

**Files:**
- Modify: `AGENTS.md` (§3 "How to run / test / deploy")

- [ ] **Step 1: Tag the current working version and push the tag**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
git tag v1-pre-overhaul
git push origin v1-pre-overhaul
```

- [ ] **Step 2: Verify the tag exists locally and on GitHub**

Run: `git tag -l v1-pre-overhaul && git ls-remote --tags origin | grep v1-pre-overhaul`
Expected: both print the tag (remote line shows a commit hash + `refs/tags/v1-pre-overhaul`).

- [ ] **Step 3: Document the restore recipe in AGENTS.md §3**

Append to the §3 bullet list:

```markdown
- **Rollback the site to the pre-overhaul version** (tagged `v1-pre-overhaul`,
  2026-08-02): `git checkout v1-pre-overhaul -- site/index.html && git commit
  -m "Rollback site to v1" && git push && cd site && vercel --prod --yes`.
  Plan B: Vercel dashboard → Deployments → pick an older one → Promote to
  Production.
```

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md
git commit -m "Rollback tag v1-pre-overhaul + restore recipe (overhaul spec 2026-08-02)"
git push
```

---

### Task 2: Payload contract check (`schema_check.py`)

The contract the site depends on, as executable Python. Violations become
warnings that ride to Telegram + the site's 🧪 line — publishing is never
blocked.

**Files:**
- Create: `schema_check.py`
- Create: `tests/test_schema_check.py`
- Modify: `run_daily.py` (after the verify block, ~line 116)

- [ ] **Step 1: Write the failing tests**

`tests/test_schema_check.py`:

```python
"""Payload contract: the exact shape site/index.html renders from.
A violation must come back as a human-readable warning, never an exception."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import publish
import schema_check
from tests.test_main_trip import (TICKET1, TICKET1_SIN, FLIGHTS, SG_TICKETS,
                                  DAC_BKK, BKK_SIN, TICKET2_BKK_FIRST)


def _payload():
    return publish.build_payload(
        list(FLIGHTS + [DAC_BKK, BKK_SIN]), [TICKET1, TICKET1_SIN], [],
        "2026-08-01", warnings=[], sg_tickets=list(SG_TICKETS + [TICKET2_BKK_FIRST]))


def test_real_payload_passes():
    assert schema_check.validate(_payload()) == []


def test_no_trip_day_still_passes():
    # A catastrophic day publishes main=None — that is contract-legal.
    assert schema_check.validate(publish.build_payload([], [], [], "2026-08-01")) == []


def test_missing_top_level_key_is_reported():
    p = _payload()
    del p["history"]
    out = " ".join(schema_check.validate(p))
    assert "history" in out


def test_wrong_type_is_reported():
    p = _payload()
    p["warnings"] = "oops a string"
    out = " ".join(schema_check.validate(p))
    assert "warnings" in out


def test_history_entry_shape_is_checked():
    p = _payload()
    p["history"][-1].pop("date")
    out = " ".join(schema_check.validate(p))
    assert "date" in out


def test_main_total_must_be_number_when_trip_exists():
    p = _payload()
    p["main"]["total"] = "4626"
    out = " ".join(schema_check.validate(p))
    assert "total" in out


def test_validate_never_raises_on_garbage():
    assert isinstance(schema_check.validate({"nonsense": True}), list)
    assert isinstance(schema_check.validate(None), list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_schema_check.py -q`
Expected: FAIL / errors with `ModuleNotFoundError: No module named 'schema_check'`

- [ ] **Step 3: Implement `schema_check.py`**

```python
"""The data.json contract, as code. site/index.html renders exactly these
keys; publish-time validation makes drift loud instead of silent. Violations
are returned as human strings (they ride to Telegram + the site's 🧪 line) —
validation must NEVER raise and NEVER block publishing."""

# Top-level keys → allowed types (tuple). None is allowed everywhere a day
# can legitimately lack the thing (no trip, no budget, no bali...).
TOP = {
    "updated": (str,),
    "alerts": (list,),
    "price_context": (str, type(None)),
    "countdown": (str, type(None)),
    "changes": (list, type(None)),
    "warnings": (list,),
    "trip": (dict,),
    "main": (dict, type(None)),
    "budget": (dict, type(None)),
    "bali": (dict, type(None)),
    "hotel": (dict, type(None)),
    "ticket1_options": (list,),
    "ticket2_options": (list,),
    "sg_tickets": (list,),
    "flights": (list,),
    "history": (list,),
}

# Keys every history entry must carry (values may be None on a bad day,
# but numbers must be numbers when present).
HISTORY_REQUIRED = ["date", "main_total", "ticket1_total", "ticket2_total"]
HISTORY_NUMERIC = ["main_total", "ticket1_total", "ticket2_total",
                   "bali_total", "budget_total", "other_order_total"]

# When main exists these must be present and numeric/str as noted.
MAIN_NUMERIC = ["total"]
MAIN_REQUIRED = ["total", "order_label", "legs_text"]


def _type_name(t):
    return "null" if t is type(None) else t.__name__


def validate(payload) -> list:
    """Return a list of human-readable contract violations (empty = clean)."""
    probs = []
    try:
        if not isinstance(payload, dict):
            return [f"contract: payload is {type(payload).__name__}, not an object"]
        for key, types in TOP.items():
            if key not in payload:
                probs.append(f"contract: top-level key '{key}' is missing")
            elif not isinstance(payload[key], types):
                want = "/".join(_type_name(t) for t in types)
                probs.append(f"contract: '{key}' is "
                             f"{type(payload[key]).__name__}, expected {want}")

        for i, h in enumerate(payload.get("history") or []):
            if not isinstance(h, dict):
                probs.append(f"contract: history[{i}] is not an object")
                continue
            for k in HISTORY_REQUIRED:
                if k not in h:
                    probs.append(f"contract: history[{i}] ({h.get('date', '?')}) "
                                 f"is missing '{k}'")
            for k in HISTORY_NUMERIC:
                v = h.get(k)
                if v is not None and not isinstance(v, (int, float)):
                    probs.append(f"contract: history[{i}].{k} is "
                                 f"{type(v).__name__}, expected number/null")

        main = payload.get("main")
        if isinstance(main, dict):
            for k in MAIN_REQUIRED:
                if k not in main:
                    probs.append(f"contract: main is missing '{k}'")
            for k in MAIN_NUMERIC:
                if k in main and not isinstance(main.get(k), (int, float)):
                    probs.append(f"contract: main.{k} is "
                                 f"{type(main.get(k)).__name__}, expected number")
    except Exception as e:  # noqa: BLE001 — the checker must never take down a run
        probs.append(f"contract: checker crashed: {e}")
    return probs
```

NOTE: before finalizing, confirm `main` really carries `order_label` and
`legs_text` on a good day — check with
`python3 -c "import json; m=json.load(open('site/data.json'))['main']; print(sorted(m.keys()))"`
and adjust `MAIN_REQUIRED` to keys that are genuinely always present
(the site renders `order_label`; drop `legs_text` from the list if absent).

- [ ] **Step 4: Run the tests, iterate until green**

Run: `python3 -m pytest tests/test_schema_check.py -q`
Expected: all pass.

- [ ] **Step 5: Wire into `run_daily.py` after the verify block**

In `run_daily.py`, directly after the `payload["verified"] = ...` else-branch
(i.e., after line ~115, before `write_to_sheet`), insert:

```python
    # 📐 Contract check: the payload must match the shape the site renders.
    # Violations are warnings (they must reach Telegram + the 🧪 line) —
    # publishing is never blocked.
    try:
        import schema_check
        contract = schema_check.validate(payload)
    except Exception as e:                     # noqa: BLE001 — never kill the run
        contract = [f"contract check crashed: {e}"]
    if contract:
        for p in contract:
            print(f"CONTRACT: {p}")
        payload["warnings"] = list(payload.get("warnings") or []) + \
            [f"📐 {p}" for p in contract]
```

- [ ] **Step 6: Full suite green**

Run: `python3 -m pytest tests/ -q`
Expected: 152 + 7 new tests pass, 0 failures.

- [ ] **Step 7: Commit**

```bash
git add schema_check.py tests/test_schema_check.py run_daily.py
git commit -m "Contract check: payload validated against the site's expected shape nightly"
git push
```

---

### Task 3: `publish.py` push-retry + Telegram warning

Today a failed `git push` prints one WARN line into cron.log and the site
goes silently stale. New behavior: 3 attempts (backoff 10 s / 30 s), then a
Telegram warning. Still never raises.

**Files:**
- Modify: `publish.py:195-210` (the git section of `write_payload`)
- Create: `tests/test_publish_push.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_publish_push.py`:

```python
"""git push must retry, and a final failure must warn Telegram — a silently
stale dashboard was the failure mode this guards against."""
import sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import publish


class FakeProc:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _run_factory(push_results, calls):
    """subprocess.run stand-in: add/commit succeed, push pops push_results."""
    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "push" in cmd:
            return push_results.pop(0)
        if "commit" in cmd:
            return FakeProc(0, out="committed")
        return FakeProc(0)
    return fake_run


def _write(monkeypatch, push_results):
    calls, warnings = [], []
    monkeypatch.setattr(publish.subprocess, "run",
                        _run_factory(push_results, calls))
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    monkeypatch.setattr(publish, "_telegram_warn", lambda msg: warnings.append(msg))
    publish.write_payload({"history": [], "updated": "t"})
    return calls, warnings


def test_push_succeeds_first_try_no_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    calls, warnings = _write(monkeypatch, [FakeProc(0)])
    assert len([c for c in calls if "push" in c]) == 1
    assert warnings == []


def test_push_retries_then_recovers(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    calls, warnings = _write(monkeypatch,
                             [FakeProc(1, err="network"), FakeProc(0)])
    assert len([c for c in calls if "push" in c]) == 2
    assert warnings == []


def test_push_final_failure_warns_telegram(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    calls, warnings = _write(monkeypatch,
                             [FakeProc(1, err="x"), FakeProc(1, err="x"),
                              FakeProc(1, err="x")])
    assert len([c for c in calls if "push" in c]) == 3
    assert len(warnings) == 1
    assert "stale" in warnings[0]


def test_write_payload_still_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    monkeypatch.setattr(publish.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    publish.write_payload({"history": []})   # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publish_push.py -q`
Expected: FAIL — `publish` has no `time` import and no `_telegram_warn`.

- [ ] **Step 3: Implement in `publish.py`**

Add `import time` to the imports. Add module-level helper above `write_payload`:

```python
PUSH_ATTEMPTS = 3
PUSH_BACKOFF_S = [10, 30]          # sleeps between attempts 1→2 and 2→3


def _telegram_warn(msg: str) -> None:
    """Best-effort Telegram warning — publish must survive notify failures."""
    try:
        from notify_telegram import send_message
        send_message(msg)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: telegram warn failed too: {e}")
```

Replace the push block inside `write_payload` (currently
`push = git("push")` … `else: print("Pushed…")`) with:

```python
        for attempt in range(1, PUSH_ATTEMPTS + 1):
            push = git("push")
            if push.returncode == 0:
                print("Pushed data.json — dashboard will show it on next load.")
                break
            print(f"WARN: git push failed (attempt {attempt}/{PUSH_ATTEMPTS}): "
                  f"{push.stderr.strip()[:200]}")
            if attempt < PUSH_ATTEMPTS:
                time.sleep(PUSH_BACKOFF_S[attempt - 1])
        else:
            _telegram_warn(
                "⚠️ dhaka-flights: git push failed 3× — tonight's data is "
                "committed locally but the dashboard will be stale until the "
                "next successful push. Check network/GitHub creds on the Mac mini.")
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `python3 -m pytest tests/test_publish_push.py tests/ -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add publish.py tests/test_publish_push.py
git commit -m "publish: git push retries 3x then warns Telegram (no more silently stale site)"
git push
```

---

### Task 4: Run-overrun guard (wall-clock soft deadline)

On a Google-slow-walk night (Aug 1: 64 timeouts, hours of grinding) the run
must degrade instead of grind: past `RUN_DEADLINE_MIN`, skip what's skippable
in reverse priority — Bali watch entirely, then remaining one-way legs.
Ticket ① and Ticket ② multi-city searches are never skipped.

**Files:**
- Modify: `scraper.py` (near `DIAG`, ~line 91; `scrape_all` loop ~line 938; `scrape_bali_watch` entry ~line 883)
- Modify: `run_daily.py` (call `begin_run()`; fold skips into warnings)
- Create: `tests/test_overrun_guard.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_overrun_guard.py`:

```python
"""⏱ Wall-clock guard: a slow-walked night skips the skippable (Bali watch,
remaining one-way legs) instead of grinding for hours. Ticket ①/② never skip."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scraper


def _expire(monkeypatch):
    scraper.begin_run()
    monkeypatch.setattr(scraper, "_run_start",
                        time.monotonic() - (scraper.RUN_DEADLINE_MIN * 60 + 1))


def test_fresh_run_is_not_past_deadline():
    scraper.begin_run()
    assert not scraper._past_deadline()
    assert scraper.DIAG["deadline_skips"] == []


def test_expired_run_is_past_deadline(monkeypatch):
    _expire(monkeypatch)
    assert scraper._past_deadline()


def test_scrape_all_skips_remaining_legs_past_deadline(monkeypatch):
    _expire(monkeypatch)
    called = []
    monkeypatch.setattr(scraper, "scrape_route",
                        lambda o, d, dep: called.append((o, d, dep)) or [])
    out = scraper.scrape_all()
    assert out == []
    assert called == []                       # nothing scraped at all
    assert any("one-way" in s for s in scraper.DIAG["deadline_skips"])


def test_scrape_bali_watch_skips_past_deadline(monkeypatch):
    _expire(monkeypatch)
    monkeypatch.setattr(scraper, "_scrape_multicity",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not scrape past deadline")))
    t1, fwd, rev = scraper.scrape_bali_watch()
    assert (t1, fwd, rev) == ([], [], [])
    assert any("Bali" in s for s in scraper.DIAG["deadline_skips"])


def test_begin_run_resets_state(monkeypatch):
    _expire(monkeypatch)
    scraper.DIAG["deadline_skips"].append("stale")
    scraper.begin_run()
    assert not scraper._past_deadline()
    assert scraper.DIAG["deadline_skips"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_overrun_guard.py -q`
Expected: FAIL — `scraper` has no `begin_run`.

- [ ] **Step 3: Implement in `scraper.py`**

Next to `DIAG` (line ~91), change DIAG's initializer to include the new key
and add the guard:

```python
DIAG = {"timeouts": 0, "blank_pages": 0, "aborted_early": False,
        "deadline_skips": []}

# ⏱ Soft wall-clock deadline (2026-08-02): past this, skippable searches are
# dropped in reverse priority (Bali watch, then remaining one-way legs) so a
# Google slow-walk night degrades instead of grinding for hours. Ticket ① /
# Ticket ② multi-city searches are never skipped — they're the product.
RUN_DEADLINE_MIN = 35
_run_start = None


def begin_run() -> None:
    """Called once by run_daily at run start; arms the deadline clock."""
    global _run_start
    _run_start = time.monotonic()
    DIAG["deadline_skips"] = []


def _past_deadline() -> bool:
    if _run_start is None:        # manual/interactive use: no deadline
        return False
    return (time.monotonic() - _run_start) > RUN_DEADLINE_MIN * 60
```

In `scrape_all()` (line ~938), at the TOP of the inner date loop (before
`n += 1`), add:

```python
            if _past_deadline():
                remaining = total - n
                DIAG["deadline_skips"].append(
                    f"one-way legs: {remaining} of {total} searches "
                    f"(past {RUN_DEADLINE_MIN} min)")
                print(f"DEADLINE: skipping remaining {remaining} one-way searches")
                return all_results
```

Also fix the existing `DIAG.update(...)` inside `scrape_all` so it does NOT
clobber `deadline_skips` (it currently resets only the three original keys —
keep it that way, just verify).

In `scrape_bali_watch()` (line ~883), add at the very top:

```python
    if _past_deadline():
        DIAG["deadline_skips"].append(
            f"🌴 Bali watch: all 3 searches (past {RUN_DEADLINE_MIN} min)")
        print("DEADLINE: skipping Bali watch entirely")
        return [], [], []
```

- [ ] **Step 4: Wire into `run_daily.py`**

In `main()`, right after `print("=== Daily flight search starting ===")`:

```python
    from scraper import begin_run, DIAG as SCRAPER_DIAG
    begin_run()
```

And right after the `self_check(...)` call that produces `warnings`
(~line 92), add:

```python
    # ⏱ Deadline skips ride along as warnings — they also explain any
    # "no fares for leg×date" sanity warnings from the same night.
    warnings += [f"⏱ {s}" for s in SCRAPER_DIAG.get("deadline_skips", [])]
```

- [ ] **Step 5: Run the new tests, then the full suite**

Run: `python3 -m pytest tests/test_overrun_guard.py tests/ -q`
Expected: all green (existing `test_scraper.py` must still pass — `begin_run`
is opt-in, so interactive `scrape_route` use has no deadline).

- [ ] **Step 6: Commit**

```bash
git add scraper.py run_daily.py tests/test_overrun_guard.py
git commit -m "Overrun guard: past 35 min, skip Bali watch + remaining one-ways, flagged in warnings"
git push
```

---

### Task 5: Site v2 scaffold — tokens, shell, router, bulletproof data layer

Everything robustness-critical in the new site lives in this task; screens
(Tasks 6–9) only add render functions. Build `site/index_v2.html` from
scratch; the live `site/index.html` keeps serving until Task 11.

**Files:**
- Create: `site/index_v2.html`
- Reference (read, don't modify): `site/index.html` — port `esc`, `usd`,
  `plain`, `orderInfo` helpers verbatim (lines near the top of its script).

**Load the design-taste-frontend skill before writing any CSS in this task.**

- [ ] **Step 1: Head + boarding-pass design tokens**

Structure: proper `<!doctype html>`, `<meta name="viewport" content="width=device-width, initial-scale=1">`, `<title>Istanbul · Dhaka · Bangkok · Singapore — Trip Tracker</title>`. Token block (spec §3.3 — light "paper" is home; dark is a navy night variant, not grey inversion):

```css
:root {
  --paper-bg: #e8e4dc;      /* page background — warm boarding-hall paper */
  --card: #fffdf8;          /* the pass/card stock */
  --ink: #1a2b49;           /* deep navy — headings, prices, pass headers */
  --ink-2: #5a5648;         /* body text on paper */
  --ink-3: #8a8371;         /* micro-labels, muted */
  --rule: #d8d2c4;          /* hairlines + perforation dashes */
  --chip-bg: #f0ebdf;
  --good: #0f7b3f; --good-bg: #e7f2e9;
  --warn: #7a5200; --warn-bg: #fbf0d2;
  --bad:  #a4262c; --bad-bg:  #fbe4e4;
  --accent: var(--ink);
  --shadow: 0 2px 10px rgb(26 43 73 / .14);
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root {
  --paper-bg: #10182a; --card: #1a2338; --ink: #e9ecf4; --ink-2: #b8bfce;
  --ink-3: #8590a6; --rule: #2e3a55; --chip-bg: #232f4a;
  --good: #7fd49a; --good-bg: #14311f; --warn: #f0c86a; --warn-bg: #3a2c07;
  --bad: #f2a0a4; --bad-bg: #43181a; --shadow: none;
} }
:root[data-theme="dark"]  { /* repeat the dark block */ }
:root[data-theme="light"] { /* repeat the light block */ }
```

(Write the two explicit `data-theme` overrides in full — the toggle must beat
the media query in both directions. Port the theme-toggle JS from the current
site.) All prices get `font-variant-numeric: tabular-nums`. Keep
`:focus-visible` rings and a `prefers-reduced-motion` guard. Verify AA
contrast for `--ink-2`/`--ink-3` on `--card` in both modes before moving on.

- [ ] **Step 2: Boarding-pass CSS primitives**

Reusable classes, used by every screen: `.pass` (card with rounded corners +
shadow), `.pass-head` (navy header band: white uppercase letter-spaced
micro-type, flex space-between), `.perf` (perforation: 2px dashed `--rule`
rule with two punched `--paper-bg` circles absolutely positioned at the
ends), `.chip` (pill; variants `.chip-good/.chip-warn/.chip-bad`),
`.mono-route` (mono, bold, letter-spaced — `BOS ✈ IST ✈ DAC…`), `.tile`
(tappable drill-in card: emoji, bold label + →, one-line muted description),
`.micro` (9–10px uppercase letter-spaced `--ink-3` label). Desktop
(`min-width: 720px`): content column max-width ~640px for drill-ins, Tonight
tiles go 4-across, chart full width.

- [ ] **Step 3: App shell + hash router**

Body skeleton + router:

```html
<header id="topbar"></header>
<main id="screen" aria-live="polite"></main>
<footer id="selfcheck"></footer>
<script>
const ROUTES = {
  "":         () => renderTonight(DATA),
  "flights":  () => renderFlights(DATA),
  "stays":    () => renderStays(DATA),
  "history":  () => renderHistory(DATA),
};
function route() {
  const name = location.hash.replace(/^#\/?/, "");
  const fn = ROUTES[name] || ROUTES[""];
  const el = document.getElementById("screen");
  el.innerHTML = "";
  el.appendChild(renderSafe(fn));
  window.scrollTo(0, 0);
  document.querySelectorAll("#topbar .back").forEach(b =>
    b.hidden = !name);          // drill-ins get a ← Tonight link
}
window.addEventListener("hashchange", route);
</script>
```

Screens are functions returning a DOM node (build with a `h()` helper or
`innerHTML` on a container — match the current site's `innerHTML` style).
Top bar: wordmark (links to `#/`), `← back` link (hidden on Tonight),
"updated HH:MM" chip, 🔎 verified chip (from `payload.verified`), theme
toggle. Staleness banner: port the >36 h red banner logic from the current
site into the shell (renders above `<main>` on every screen).

- [ ] **Step 4: Bulletproof data layer — the core robustness code**

```js
const RAW = "https://raw.githubusercontent.com/jalalchowdhury1/dhaka-flights/main/site/data.json";
const LS_KEY = "dhaka-flights:last-good";
let DATA = null, DATA_SOURCE = "live";   // live | local | cache

async function loadData() {
  // 1. GitHub raw (fresh)  2. same-origin copy  3. last-good localStorage
  try {
    DATA = await (await fetch(RAW, {cache: "no-store"})).json();
    saveLastGood(DATA);
    return;
  } catch (e) { console.warn("raw fetch failed", e); }
  try {
    DATA = await (await fetch("./data.json", {cache: "no-store"})).json();
    DATA_SOURCE = "local";
    saveLastGood(DATA);
    return;
  } catch (e) { console.warn("local fetch failed", e); }
  const cached = loadLastGood();
  if (cached) { DATA = cached.payload; DATA_SOURCE = "cache"; return; }
  DATA = null;
}
function saveLastGood(payload) {
  try { localStorage.setItem(LS_KEY,
        JSON.stringify({savedAt: new Date().toISOString(), payload})); }
  catch (e) {}                                  // quota/private mode: fine
}
function loadLastGood() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)); }
  catch (e) { return null; }
}

function renderSafe(fn) {
  // Per-section error boundary: one broken section must never blank the page.
  try { return fn(); }
  catch (e) {
    console.error(e);
    const d = document.createElement("div");
    d.className = "pass error-card";
    d.innerHTML = `<b>⚠ This section couldn't render.</b>
      <span class="micro">The data may have an unexpected shape — the rest
      of the page is unaffected.</span>`;
    return d;
  }
}

function validatePayload(d) {
  // Mirrors schema_check.py TOP — keep the two lists in sync.
  const probs = [];
  if (!d || typeof d !== "object") return ["payload missing entirely"];
  const want = {updated: "string", warnings: "array", trip: "object",
                ticket1_options: "array", ticket2_options: "array",
                flights: "array", history: "array"};
  for (const [k, t] of Object.entries(want)) {
    const v = d[k];
    const ok = t === "array" ? Array.isArray(v)
             : typeof v === t && v !== null;
    if (!ok) probs.push(`'${k}' missing or not ${t}`);
  }
  for (const k of ["main", "budget", "bali", "hotel"])
    if (d[k] !== null && d[k] !== undefined && typeof d[k] !== "object")
      probs.push(`'${k}' should be object or null`);
  return probs;
}

function arithmeticFindings(d) {
  // The page re-checks the headline math it displays.
  const out = [], m = d && d.main, h = d && d.history && d.history.at(-1);
  if (m && typeof m.total === "number" && h &&
      typeof h.ticket1_total === "number" && typeof h.ticket2_total === "number" &&
      Math.abs(h.ticket1_total + h.ticket2_total - m.total) > 1)
    out.push(`①(${h.ticket1_total}) + ②(${h.ticket2_total}) ≠ total (${m.total})`);
  if (m && h && typeof m.total === "number" &&
      typeof h.main_total === "number" && h.main_total !== m.total)
    out.push(`history mirror (${h.main_total}) ≠ tonight's total (${m.total})`);
  return out;
}
```

Boot sequence: `await loadData()` → if `DATA === null` render the designed
"can't reach data" screen (pass-styled card: what failed, "try again" button
that calls `location.reload()`) → else render shell; if
`DATA_SOURCE === "cache"` show a prominent banner "Showing saved data from
<cached savedAt date> — live fetch failed"; merge `validatePayload(DATA)` +
`arithmeticFindings(DATA)` into the 🧪 self-check footer (collapsed
`<details>`; findings prefixed 📐 and ⚠ alongside the payload's own
`warnings`); then `route()`.

- [ ] **Step 5: Port shared helpers**

Copy `esc`, `usd`, `plain`, `orderInfo` from `site/index.html` verbatim into
the new script (keep the `orderInfo` ↔ `combo.ORDERS` sync comment).

- [ ] **Step 6: Verify the scaffold in a browser**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights/site" && python3 -m http.server 8901
```

Open `http://localhost:8901/index_v2.html` (claude-in-chrome). Expected:
paper background, top bar with updated/verified chips, empty screen bodies
(stub text per route is fine at this point), working hash nav
`#/flights` ⇄ `#/`, 🧪 footer showing 0 findings, no console errors. Check
dark mode + 390 px width.

- [ ] **Step 7: Commit**

```bash
git add site/index_v2.html
git commit -m "Site v2 scaffold: boarding-pass tokens, hash router, bulletproof data layer"
git push
```

---

### Task 6: Tonight screen (`#/`)

**Files:**
- Modify: `site/index_v2.html`
- Reference: `site/index.html` — `renderDecision` (~line 396), `renderStrip`/`tileDelta` (~427), `chart` (~580) for the sparkline data plumbing; approved mock: `.superpowers/brainstorm/56189-1785690997/content/front-page-mock.html`

- [ ] **Step 1: Implement `renderTonight(d)`** — sections in order, each individually wrapped in `renderSafe`:

1. **Verdict pass** (the mock, made real): `.pass` with `.pass-head`
   ("Tonight's cheapest" · `esc(m.order_label)`), `.mono-route` built from
   `orderInfo(m)` (order-aware city sequence), price row `usd(m.total)` +
   Δ vs previous history entry (green ▼ / red ▲), chip row: buy-signal chip
   from `d.alerts` (🚨 lines get `.chip-bad`, otherwise `.chip-warn` watch
   chip with `d.countdown`), price-context chip (`d.price_context`), flag
   badge when `m.flag`. Then `.perf`, then stub row:
   `① {esc(h.ticket1_airline)} {usd(h.ticket1_total)}` ·
   `② {esc(h.ticket2_airline)} {usd(h.ticket2_total)}`.
   No-trip night (`m == null`): the pass renders "No trip could be priced in
   the latest run" + the reason from warnings — port the existing
   `renderDecision` fallback branch.
2. **💸 budget teaser** (only when `d.budget`): one-line card —
   "Same trip {usd(budget.total)} with looser dates · save {usd(savings)} →"
   linking `#/flights`.
3. **Since yesterday** card: `d.changes` lines (port from current site);
   hide the card entirely when empty.
4. **Sparkline**: inline SVG, `main_total` series only, last ~30 entries,
   ring endpoint, no axes (it's a teaser, not the chart) — whole card links
   to `#/history` with "history →" micro-label.
5. **Tiles** (2×2 phone / 4-across desktop): ✈️ Flights, 🏨 Stays,
   📈 History, 🌴 Bali watch. Bali tile shows `usd(bali.total)` +
   `delta_vs_main` (sign-aware: "+$232 vs yours" in good-green when
   positive — Bali costing MORE is good news for the swap). Tiles are `<a>`
   elements with hash hrefs.

- [ ] **Step 2: Verify against tonight's real data**

Reload `http://localhost:8901/index_v2.html`. Expected: every number matches
what `site/index.html` (old site, same server) shows for the same payload —
cross-check total, Δ, ①/②, Bali Δ, countdown text. Light + dark + 390 px.

- [ ] **Step 3: Commit**

```bash
git add site/index_v2.html
git commit -m "Site v2: Tonight screen — verdict pass, changes, sparkline, drill-in tiles"
git push
```

---

### Task 7: Flights screen (`#/flights`)

**Files:**
- Modify: `site/index_v2.html`
- Reference: `site/index.html` — `legLine`/`ojLine`/`sgTicketLine` (~456-478), `structureCard` (~538), `otherOrderCard` (~498), the baggage-table renderer, alternatives renderers, booking-playbook markup, budget card.

- [ ] **Step 1: Implement `renderFlights(d)`** — order per spec §3.2, each section `renderSafe`-wrapped, each with a `.micro` plain-English label:

1. **Trip plan**: the winning trip's legs with dates + 🧳 line per flight
   (port `legLine`/`ojLine`/`sgTicketLine` data logic; restyle as rows inside
   one `.pass` per ticket — Ticket ① pass and Ticket ② pass, each with
   `.pass-head` naming airline + price, booking-link button).
2. **💸 Budget companion** (when present): collapsible pass with `diffs`
   list + savings; port current budget card content.
3. **🔁 Other order** card: port `otherOrderCard` content incl. its
   "both orders scraped nightly" footnote.
4. **Alternatives**: Ticket ② options then Ticket ① options
   (`d.ticket2_options`, `d.ticket1_options`) — table/rows with Δ-vs-chosen
   and per-option `baggage.summary`; keep the "same dates only" caption.
5. **Baggage reference table**: port from current site, including the
   verbatim line "reference — the checkout page is the authority" and the
   `baggage_checked` date.
6. **Booking playbook**: port the current playbook list (incl. the
   direction-arbitrage entry) as-is.

- [ ] **Step 2: Verify against real data** — same cross-check routine against the old site's rendering of the same sections; confirm every option row, bag rule, and playbook entry survived the port. Light/dark/390 px.

- [ ] **Step 3: Commit**

```bash
git add site/index_v2.html
git commit -m "Site v2: Flights screen — tickets as passes, alternatives, baggage, playbook"
git push
```

---

### Task 8: Stays screen (`#/stays`)

**Files:**
- Modify: `site/index_v2.html`
- Reference: `site/index.html` — `hotelCard` (~480), the "Hotel — Marriott points" section, and the entire IST/SIN card-play section (static HTML with the offset-% tables).

- [ ] **Step 1: Implement `renderStays(d)`**:

1. **The Athenee pass** (`d.hotel`): `.pass-head` = hotel name + "5 nights ·
   Marriott points"; body: order-aware stay dates, points math, 5th-night-free
   note; the ≠5-night warning renders as `.chip-bad` when present; runner-up +
   cash-reference lines; `CHECKED` date shown.
2. **Bali hotel footnote** (`d.bali.hotel`, when present): one muted line —
   it's a benchmark, keep it small.
3. **IST/SIN card-play section**: port the ENTIRE current static section
   (shortlists, both offset-% tables incl. the SIN 2-night column, band
   colors ≥70/50–70/<50, assumption lines, strategy notes, "deciding state"
   framing) restyled onto the new tokens. Content is hand-curated — port
   text verbatim, do not paraphrase.

- [ ] **Step 2: Verify** — every hotel number, offset %, band color, and assumption line matches the old site. Light/dark/390 px.

- [ ] **Step 3: Commit**

```bash
git add site/index_v2.html
git commit -m "Site v2: Stays screen — Athenee pass + IST/SIN card-play port"
git push
```

---

### Task 9: History screen (`#/history`) + chart re-skin

**Load the dataviz skill before this task.**

**Files:**
- Modify: `site/index_v2.html`
- Reference: `site/index.html` — `chart` (~580), `niceTicks` (~571), `bindChartHover`, the History-tab table with per-day detail, `renderBali` (~512).

- [ ] **Step 1: Implement `renderHistory(d)`**:

1. **Full chart**: port `chart()`/`niceTicks`/`bindChartHover` logic intact —
   same 4 series (⭐ trip / ① / ② / 🌴 Bali with the pre-swap stitch),
   same dataviz spec (2 px lines, ring endpoints, hairline grid, $ ticks,
   legend, selective end labels, crosshair tooltip). Re-map the 4 series
   colors onto the new palette WITHOUT reshuffling assignment order (order
   is the CVD-safety mechanism); validate the new 4 colors with the dataviz
   skill's checker before committing. Keep the "before 1 Aug 2026 the trip
   visited Bali" caption.
2. **Price context** block: `d.price_context` + `d.countdown` + alert lines.
3. **Per-night table**: port the History-tab table (date / ⭐ / ① / ② /
   airlines / nights / home) with tap-a-row expanding that day's full detail
   from `best_detail`. Restyle: mono numerals, hairline rules.
4. **🌴 Bali watch card**: port `renderBali` content (benchmark framing,
   other-Bali-order line, delta).

- [ ] **Step 2: Verify** — chart pixel-sanity vs old site (same shapes, same stitch point), tooltip works on touch + mouse, table rows expand, all in light/dark/390 px.

- [ ] **Step 3: Commit**

```bash
git add site/index_v2.html
git commit -m "Site v2: History screen — spec-compliant chart on new palette, night table, Bali watch"
git push
```

---

### Task 10: Degraded-data QA matrix

The robustness claims get proven here, before anything ships.

**Files:**
- Create: `site/qa/` mutated payloads (gitignored via `backups/`-style local use — do NOT commit; delete the folder after QA)

- [ ] **Step 1: Build the mutated payloads**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights/site" && mkdir -p qa
jq '.hotel = null | .bali = null | .budget = null' data.json > qa/no-extras.json
jq '.main = null' data.json > qa/no-trip.json
jq '.history = []' data.json > qa/no-history.json
jq '.main.total = "oops" | .history[-1].ticket1_total = "bad"' data.json > qa/bad-types.json
jq 'del(.ticket1_options) | del(.warnings)' data.json > qa/missing-keys.json
head -c 400 data.json > qa/truncated.json
jq '.updated = "2026-07-25 00:31"' data.json > qa/stale.json
```

- [ ] **Step 2: Run the matrix**

For each QA file: temporarily point the fetch at it (in the browser console:
`localStorage.clear()`, then load
`http://localhost:8901/index_v2.html?qa=no-trip` — add a tiny dev hook in
`loadData()`: `const qa = new URLSearchParams(location.search).get("qa");
if (qa) { DATA = await (await fetch("./qa/" + qa + ".json")).json(); return; }`
— the hook ships; it only activates with an explicit query param). Expected
per file:

| file | expectation |
|---|---|
| no-extras | Tonight renders; hotel/Bali/budget sections absent, no error cards |
| no-trip | verdict pass shows the no-trip fallback; rest of page alive |
| no-history | sparkline + chart show "history appears after a couple of days"; no crash |
| bad-types | 📐/⚠ findings in 🧪 footer; affected section degrades alone |
| missing-keys | 📐 findings listed; other sections render |
| truncated | fetch parse fails → localStorage last-good renders with the labeled banner (seed it by loading real data first); with storage cleared → designed error screen |
| stale | red staleness banner on every screen |

Also confirm: all 4 routes × light/dark × 390 px/desktop for the REAL
payload one final time, zero console errors anywhere.

- [ ] **Step 3: Clean up and commit the dev hook**

```bash
rm -rf "/Users/jalalchowdhury/PycharmProjects/Dhaka flights/site/qa"
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
git add site/index_v2.html
git commit -m "Site v2: qa query-param hook + fixes found in degraded-data matrix"
git push
```

(Fold any bugs the matrix caught into this commit; list them in the commit body.)

---

### Task 11: Swap, deploy, document

**Files:**
- Modify: `site/index.html` (replaced by v2), `AGENTS.md` (§2 site description, §7 file map), memory file `~/.claude/projects/-Users-jalalchowdhury/memory/project_dhaka_flights.md`

- [ ] **Step 1: Swap v2 into place**

```bash
cd "/Users/jalalchowdhury/PycharmProjects/Dhaka flights"
git mv -f site/index_v2.html site/index.html
git commit -m "Site: boarding-pass redesign goes live (rollback: v1-pre-overhaul)"
git push
```

- [ ] **Step 2: Deploy**

Run: `cd site && vercel --prod --yes`
Expected: production URL printed; then open https://dhaka-flights.vercel.app
(hard-refresh) and click through all 4 routes on the LIVE site.

- [ ] **Step 3: Update AGENTS.md**

- §2 data-flow block: replace the two-tab site description with the four
  hash routes and what lives on each.
- §7 `site/` entry: rewrite to describe the boarding-pass token system, the
  fetch fallback chain (raw → local → localStorage), `renderSafe` boundaries,
  `validatePayload` (mirror of `schema_check.py` — note the two must stay in
  sync), the `?qa=` dev hook, and keep the `orderInfo()`/`combo.ORDERS` sync
  rule + chart CVD-order rule.
- §7: add `schema_check.py` entry; note the overrun guard under
  `scraper.py`'s entry and push-retry under `publish.py`'s.

```bash
git add AGENTS.md && git commit -m "AGENTS: v2 site conventions, contract check, overrun guard" && git push
```

- [ ] **Step 4: Update the project memory file**

Edit `~/.claude/projects/-Users-jalalchowdhury/memory/project_dhaka_flights.md`:
add the 2026-08-02 overhaul (boarding-pass 4-route site, robustness layer,
`v1-pre-overhaul` rollback tag, schema/push-retry/deadline pipeline guards).
Keep the existing gotchas.

- [ ] **Step 5: Watch the next nightly run**

Next morning (or via the fleet-health 7 am brief): confirm the overnight run
published, the live site renders the new night's data on all 4 routes, and no
📐/⏱ warnings fired spuriously. Only then is this plan done.

---

## Self-review notes (run after drafting — resolved)

- **Spec coverage**: §4.2.1 push-retry → Task 3; §4.2.2 contract → Task 2;
  §4.2.3 overrun → Task 4; §4.1.1–5 site robustness → Task 5 (+ proven in
  Task 10); §3 screens → Tasks 6–9; §4.3 rollback → Task 1; §6 testing →
  Tasks 2–4 (pytest) + 10 (browser); §7 rollout → Tasks 1, 11. No gaps.
- **Spec deviation (deliberate)**: contract validation is wired in
  `run_daily.py` (not inside `publish.py`) so findings reach Telegram AND the
  site — the spec's intent ("violations ride along as warnings") requires it
  to run before `notify_cheapest`. Documented in Task 2 Step 5.
- **Type consistency**: `begin_run`/`_past_deadline`/`deadline_skips` names
  match across Task 4's scraper/run_daily/test code; `_telegram_warn` matches
  between Task 3's impl and tests; `validatePayload`/`renderSafe`/`loadData`
  match between Tasks 5 and 10.
- **Verify-before-done**: Task 2 Step 3 includes a live check of `main`'s
  real keys before locking `MAIN_REQUIRED` — do not skip it.
