"""The data.json contract, as code. site/index.html renders exactly these
keys; publish-time validation makes drift loud instead of silent. Violations
are returned as human strings (they ride to Telegram + the site's 🧪 line) —
validation must NEVER raise and NEVER block publishing."""

# Top-level keys → allowed types (tuple). None is allowed everywhere a day
# can legitimately lack the thing (no trip, no budget, no bali...).
# "verified" is written only on a clean re-check night — deliberately left
# out, since its absence is legal, not a violation.
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

# Every history entry must carry a date — that's the one field every era of
# this tracker has written. main_total/ticket1_total/ticket2_total are NOT
# required: 10 of the 19 rows currently in site/data.json predate the
# 2026-07-25 single-trip narrowing and only carry the old best_total/
# best_structure/best_detail shape. site/index.html's own mainTotal() helper
# (`h.main_total ?? h.combined_total ?? null`) and its `??` fallbacks
# throughout treat that as normal, so the contract does too.
HISTORY_REQUIRED = ["date"]
HISTORY_NUMERIC = ["main_total", "ticket1_total", "ticket2_total",
                   "bali_total", "budget_total", "other_order_total"]

# When main exists these must be present (str/dict); "total" must also be
# numeric. legs_text is NOT part of the real shape (main carries "legs", a
# list of leg dicts) — dropped after checking both the real data.json and
# the fixture-built payload.
MAIN_NUMERIC = ["total"]
MAIN_REQUIRED = ["total", "order_label"]


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
