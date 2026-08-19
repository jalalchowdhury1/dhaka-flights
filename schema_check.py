"""The data.json contract, as code. site/index.html renders exactly these
keys; publish-time validation makes drift loud instead of silent. Violations
are returned as human strings (they ride to Telegram + the site's 🧪 line) —
validation must NEVER raise and NEVER block publishing."""
import datetime
import json

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
    "stay_value": (dict, type(None)),
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
                   "bali_total", "budget_total", "other_order_total",
                   "sg_allin"]

# When main exists these must be present (str/dict); "total" must also be
# numeric. legs_text is NOT part of the real shape (main carries "legs", a
# list of leg dicts) — dropped after checking both the real data.json and
# the fixture-built payload.
MAIN_NUMERIC = ["total"]
MAIN_REQUIRED = ["total", "order_label"]

# Cap on per-history-row findings that ride to Telegram. A systemic drift
# (e.g. every numeric silently turns into a string) can otherwise emit one
# violation per history row — up to 114 strings today — blowing past
# Telegram's 4096-char message limit and silently degrading the nightly
# brief to a warnings-free core message: the check would go quiet exactly
# when it matters most. One summary line beats per-row noise.
HISTORY_VIOLATION_CAP = 3


def _type_name(t):
    return "null" if t is type(None) else t.__name__


def _is_number(v):
    # bool is a subclass of int in Python — True/False must not sneak past
    # this check as a valid number.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _default(o):
    """Mirrors publish._jsonable's datetime rule without importing publish —
    this checker must stay independent of the module it's checking, so a bug
    in publish can never blind the checker to it."""
    if isinstance(o, datetime.datetime):
        return o.strftime("%B %d, %Y")
    raise TypeError(f"not JSON-serializable: {type(o)}")


def validate(payload) -> list:
    """Return a list of human-readable contract violations (empty = clean)."""
    probs = []
    try:
        if not isinstance(payload, dict):
            return [f"payload shape: payload is {type(payload).__name__}, "
                    f"not an object"]
        for key, types in TOP.items():
            if key not in payload:
                probs.append(f"payload shape: top-level key '{key}' is missing")
            elif not isinstance(payload[key], types):
                want = "/".join(_type_name(t) for t in types)
                probs.append(f"payload shape: '{key}' is "
                             f"{type(payload[key]).__name__}, expected {want}")

        # History rows are gathered separately and capped (HISTORY_VIOLATION_CAP)
        # before joining the main list — see the constant's comment above.
        hist_probs = []
        for i, h in enumerate(payload.get("history") or []):
            if not isinstance(h, dict):
                hist_probs.append(f"payload shape: history[{i}] is not an object")
                continue
            for k in HISTORY_REQUIRED:
                if k not in h:
                    hist_probs.append(f"payload shape: history[{i}] "
                                      f"({h.get('date', '?')}) is missing '{k}'")
            for k in HISTORY_NUMERIC:
                v = h.get(k)
                if v is not None and not _is_number(v):
                    hist_probs.append(f"payload shape: history[{i}].{k} is "
                                      f"{type(v).__name__}, expected number/null")
        if len(hist_probs) > HISTORY_VIOLATION_CAP:
            probs.extend(hist_probs[:HISTORY_VIOLATION_CAP])
            probs.append(f"payload shape: …and "
                         f"{len(hist_probs) - HISTORY_VIOLATION_CAP} more "
                         f"history-row violations")
        else:
            probs.extend(hist_probs)

        main = payload.get("main")
        if isinstance(main, dict):
            for k in MAIN_REQUIRED:
                if k not in main:
                    probs.append(f"payload shape: main is missing '{k}'")
            for k in MAIN_NUMERIC:
                if k in main and not _is_number(main.get(k)):
                    probs.append(f"payload shape: main.{k} is "
                                 f"{type(main.get(k)).__name__}, expected number")

        # 🧬 Serializability probe: json.dump writes data.json incrementally,
        # so one non-serializable value nested anywhere in the payload
        # truncates the file mid-write — the exact corruption this layer
        # exists to prevent, and the type table above can't see it (it
        # checks shape, not every nested leaf). Independent of publish.py on
        # purpose: this checker must not trust the thing it's checking.
        # allow_nan=False: a NaN/Infinity leaf serializes "successfully" into
        # JSON that no standard parser can read back — same blank-site
        # outcome as truncation, just without the TypeError this probe would
        # otherwise rely on to catch it.
        try:
            json.dumps(payload, default=_default, allow_nan=False)
        except (TypeError, ValueError) as e:
            probs.append(f"payload shape: payload will not serialize to JSON "
                         f"({e}) — data.json would be written truncated")
    except Exception as e:  # noqa: BLE001 — the checker must never take down a run
        probs.append(f"payload shape: checker crashed: {e}")
    return probs
