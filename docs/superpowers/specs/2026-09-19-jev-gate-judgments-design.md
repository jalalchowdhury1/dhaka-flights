# Jev gate judgments — shadow first, power on evidence (19 Sep 2026)

**Ask (Jalal):** give Jev decision power across the nightly workflow, but only in the
areas where it is measurably good; test first, then decide, then write the limits down.

## Gates
One shared helper `_judge(gate, region, question, verdicts, rule, good)` runs at seven
points of every search. Jev sees only the form/results region around the step; the
deterministic rule is computed alongside.

| gate | region | verdicts (good first) | rule | redo when not landed |
|---|---|---|---|---|
| landing | top of page | form-visible / popup-or-consent / blank-or-error | "where from?" present | reopen once, then existing blank-page path |
| ticket_type | around "Change ticket type" | selected / other-type / menu-still-open | "change ticket type. <label>" and no "option: round trip" | redo the menu once |
| passengers | around "passenger" | three-passengers / other-count / dialog-still-open | "3 passengers" and no "button: add adult" | redo the dialog once |
| airports | around the box | settled / dropdown-open / wrong-or-empty | name shown and no "option:" lines | Escape + refill once (shipped 19 Sep) |
| date | around "textbox: Departure" | date-shown / calendar-still-open / empty-or-other-date | date text by the box and no "button: done" | Escape + refill once |
| results_ready | results list | list-complete / still-loading / no-results-or-error | expander or >= 10 priced rows (one-way); stable priced rows (multi-city) | one extra settle wait |
| fill_verified | results header | matches-search / different-route-or-date / cannot-tell | `_verify_fill` | existing fill-not-verified path |

## Who decides
`JEV_DECIDES` (env, comma list; default `airports`) names the gates where Jev's verdict is
the decision when its confidence is >= `JEV_P_FLOOR`. Every other gate is **shadow**: the
rule decides, Jev's verdict + p are recorded. `JEV_DECIDES=` (empty) = rules everywhere.

## Evidence trail
Every judgment appends one JSON line to `bench/judge/log.jsonl` (gate, verdict, p, rule,
decided_by, ts). Every disagreement also saves the region to `bench/judge/<gate>-<ts>.txt`.
`end_session` prints per-gate counts (judged / disagreed / by-jev) in the `jev diag:` line.

## Calibration (done before any promotion)
`judge_calibrate.py` runs live searches with a known failure injected at each gate (the
click that lands the step is dropped, as in the 19 Sep repro) plus normal searches, and
scores Jev per gate against ground truth (injected = not landed; normal + next step
succeeded = landed). A gate is promoted into `JEV_DECIDES` only when Jev is right on every
injected failure and every normal case with p >= floor; a gate where Jev errs is written
into AGENTS.md as a limit and stays on the rule.

## Cost / rollback
<= 7 Jev calls per search (~0.4 s each), ~+1.5 min per night. Rollback: `JEV_DECIDES=`.

## Out of scope
Jev choosing which element to click (beyond ambiguous airport dropdowns); Jev judging
whether prices/result sets are complete or plausible (rules vs last night stay).
