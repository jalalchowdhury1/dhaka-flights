"""Guard against a name run_daily.py uses but never defines.

18 Sep 2026: the SCRAPER_ENGINE switch removed `from scraper import begin_run,
DIAG as SCRAPER_DIAG` while line ~169 still read SCRAPER_DIAG — a NameError at the
END of every nightly run (legacy included), after all the scraping. pyflakes is
not installed here, so check with the stdlib: every name loaded anywhere in the
file must be bound somewhere in it (or be a builtin).
"""
import ast
import builtins
import os

RUN_DAILY = os.path.join(os.path.dirname(__file__), "..", "run_daily.py")


def _bound_names(tree):
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            names.update(n.names)
    return names


def test_run_daily_has_no_undefined_names():
    with open(RUN_DAILY) as f:
        tree = ast.parse(f.read())
    bound = _bound_names(tree) | set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
    loaded = {n.id for n in ast.walk(tree)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert not (loaded - bound), f"run_daily.py uses undefined names: {sorted(loaded - bound)}"


def test_run_daily_defines_scraper_diag_for_both_engines():
    with open(RUN_DAILY) as f:
        src = f.read()
    # module-level binding, outside the `if SCRAPER_ENGINE == "jev"` branches
    assert "\nSCRAPER_DIAG = scraper.DIAG" in src
