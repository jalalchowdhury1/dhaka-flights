#!/usr/bin/env python3
"""Calibrate the Jev gate judgments against ground truth — live, on purpose.

Runs one-way searches (plus one multi-city) through scraper_jev with a known
failure injected at ONE gate per search (the click or lookup that lands the
step is dropped, exactly like the 19 Sep stale-ref night), then scores every
judgment: for the injected gate the first judgment's truth is "not landed"; a
judgment after the redo, and every judgment at a non-injected gate, is scored
"landed" when the search produced results (any real failure there shows up as
a disagreement whose region is saved by _judge for review).

Writes bench/judge/calib.jsonl (one row per judgment, with the region) and
prints a per-gate table: how often Jev was right, how often the rule was right,
and Jev's confidence. Promotion into JEV_DECIDES happens by hand from that table.

Usage: python3 judge_calibrate.py [--rounds N] [--plan]
Never run while the nightly is running (00:00-00:45).
"""
import argparse, datetime, json, os, sys, time
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE); sys.path.insert(0, HERE)
load_dotenv(os.path.join(HERE, ".env"))
import scraper_jev as S
import jev_client

GATES = ["landing", "ticket_type", "passengers", "airports", "date", "results_ready", "fill_verified"]
ONEWAYS = [("DAC", "BKK", "February 1, 2027"), ("DAC", "SIN", "January 28, 2027"),
           ("SIN", "BKK", "February 2, 2027"), ("BKK", "SIN", "February 3, 2027")]
OUT = os.path.join(S.JUDGE_DIR, "calib.jsonl")

ctx = {"inject": None, "phase": None, "done": False, "n": 0, "typed": False, "search": "", "rows": [], "seen": {}}

# ── injection plumbing ────────────────────────────────────────────────────────
real = {n: getattr(S, n) for n in ("_run", "_find_ref", "_set_passengers", "_fill_date",
                                   "_fill_airport", "_wait_for_results", "_judge_fill", "_save_judgment")}

def run(cmd):
    g = ctx["inject"]
    if g == "landing" and ctx["n"] < 2 and cmd.startswith("browse open https://www.google.com/travel/flights"):
        ctx["n"] += 1; ctx["done"] = ctx["n"] >= 2
        print(f"  >>> inject landing: opening about:blank instead (open #{ctx['n']})"); return real["_run"]("browse open about:blank")
    if g == "airports" and ctx["phase"] == "airports" and not ctx["done"]:
        if cmd.startswith("browse type "): ctx["typed"] = True
        elif ctx["typed"] and cmd.startswith("browse click"):
            ctx["done"] = True; print("  >>> inject airports: dropped the suggestion click"); return ""
    return real["_run"](cmd)

def find_ref(snap, *kw):
    g = ctx["inject"]; needle = " ".join(kw).lower()
    if not ctx["done"]:
        if g == "ticket_type" and needle == "option: one way":
            ctx["done"] = True; print("  >>> inject ticket_type: hid the 'One way' option"); return ""
        if g == "passengers" and ctx["phase"] == "passengers" and needle == "button: done":
            ctx["done"] = True; print("  >>> inject passengers: hid the Done button"); return ""
        if g == "date" and ctx["phase"] == "date" and needle == "button: done":
            ctx["done"] = True; print("  >>> inject date: hid the Done button"); return ""
    return real["_find_ref"](snap, *kw)

def phased(name, phase):
    def f(*a, **k):
        ctx["phase"] = phase
        try: return real[name](*a, **k)
        finally: ctx["phase"] = None
    return f

def wait_for_results(*a, **k):
    if ctx["inject"] == "results_ready" and not ctx["done"]:
        ctx["done"] = True; time.sleep(1.0); print("  >>> inject results_ready: judging 1 s after Search")
        return S._snap()
    return real["_wait_for_results"](*a, **k)

def judge_fill(tree, legs):
    if ctx["inject"] == "fill_verified" and not ctx["done"]:
        ctx["done"] = True
        legs = [(o, "SIN" if d != "SIN" else "BKK", dep) for o, d, dep in legs]
        print(f"  >>> inject fill_verified: asking about the wrong route {legs[0][0]}→{legs[0][1]}")
    return real["_judge_fill"](tree, legs)

def save_judgment(gate, verdict, p, rule, decided_by, region):
    """Record truth next to what the engine logged (called by the real _judge)."""
    n = ctx["seen"].get(gate, 0); ctx["seen"][gate] = n + 1
    injected = (gate == ctx["inject"] and n == 0)
    ctx["rows"].append({"ts": time.strftime("%Y%m%dT%H%M%S"), "search": ctx["search"], "gate": gate,
                        "injected": injected, "jev": verdict, "p": p, "rule": rule,
                        "decided_by": decided_by, "region": region})
    return real["_save_judgment"](gate, verdict, p, rule, decided_by, region)

def install():
    S._run = run; S._find_ref = find_ref
    S._set_passengers = phased("_set_passengers", "passengers")
    S._fill_date = phased("_fill_date", "date")
    S._fill_airport = phased("_fill_airport", "airports")
    S._wait_for_results = wait_for_results; S._judge_fill = judge_fill; S._save_judgment = save_judgment

# ── scoring ──────────────────────────────────────────────────────────────────
def score(rows):
    print("\ngate           n  inj  jev_ok  rule_ok  jev_ok(p>=.6)  unsure  mean_p   jev_wrong_on")
    for g in GATES:
        rs = [r for r in rows if r["gate"] == g and r["jev"] is not None and r["truth"] is not None]
        if not rs: print(f"{g:14s} 0"); continue
        good = "good"
        jev_ok = [(r["jev"] == good) == r["truth"] for r in rs]
        rule_ok = [r["rule"] == r["truth"] for r in rs]
        conf = [r for r in rs if r["p"] >= S.JEV_P_FLOOR]
        conf_ok = [(r["jev"] == good) == r["truth"] for r in conf]
        wrong = sorted({("INJ" if r["injected"] else "normal") + ":" + r["jev"] for r, ok in zip(rs, jev_ok) if not ok})
        print(f"{g:14s} {len(rs):2d}  {sum(r['injected'] for r in rs):3d}  {sum(jev_ok):3d}/{len(rs):<3d} {sum(rule_ok):3d}/{len(rs):<3d}"
              f"   {sum(conf_ok):3d}/{len(conf):<3d}        {len(rs)-len(conf):3d}   {sum(r['p'] for r in rs)/len(rs):.2f}   {', '.join(wrong) or '-'}")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--rounds", type=int, default=1); ap.add_argument("--plan", action="store_true"); ap.add_argument("--shift", type=int, default=0, help="days to add to every one-way date")
    a = ap.parse_args()
    def shift(d):
        dt = datetime.datetime.strptime(d, "%B %d, %Y") + datetime.timedelta(days=a.shift)
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    oneways = [(o, d, shift(dep)) for o, d, dep in ONEWAYS]
    plan = []
    for r in range(a.rounds):
        for i, g in enumerate(GATES):
            plan.append((g, oneways[i % len(oneways)]))
        plan.append((None, oneways[(r + 2) % len(oneways)]))
        plan.append(("multicity", None))
    for g, s in plan: print(f"  {g or 'normal':14s} {s or 'STOPOVER_SEARCHES[0] multi-city'}")
    if a.plan: return
    os.makedirs(S.JUDGE_DIR, exist_ok=True)
    print("jev server started:", jev_client.start().started)
    install(); S.begin_run(); all_rows = []
    try:
        for g, s in plan:
            ctx.update(inject=None if g == "multicity" else g, done=False, n=0, typed=False, seen={}, rows=[],
                       search=f"{g or 'normal'}:{s[0]+'-'+s[1]+' '+s[2] if s else 'multicity'}")
            print(f"\n=== search {ctx['search']}"); t0 = time.time()
            try:
                res = S.scrape_stopover(S.STOPOVER_SEARCHES[0]) if g == "multicity" else S.scrape_route(*s)
            except Exception as e:
                res = []; print("  search raised:", e)
            ok = bool(res)
            try:
                final = S._get_tree(S._snap()).lower()
            except Exception:
                final = ""
            pax_ok = "for 3 passengers" in final
            if ok and not pax_ok: print("  !! results page does not say 'for 3 passengers'")
            for r in ctx["rows"]:
                r["truth"] = False if r["injected"] else (True if ok else None)
                if r["gate"] == "passengers" and not r["injected"] and ok:
                    r["truth"] = pax_ok
                r["search_ok"] = ok; r["search_s"] = round(time.time() - t0, 1)
            print(f"  -> {len(res)} results in {time.time()-t0:.0f}s; judgments={len(ctx['rows'])} engine_fallbacks={S.DIAG['engine_fallbacks']}")
            all_rows += ctx["rows"]
            with open(OUT, "a") as f:
                for r in ctx["rows"]: f.write(json.dumps(r) + "\n")
    finally:
        S.end_session()
        try: jev_client.get_client().stop()
        except Exception: pass
    score(all_rows); print(f"\nrows appended to {OUT}")

if __name__ == "__main__":
    main()
