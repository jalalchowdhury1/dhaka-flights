"""site/cash_plan.json — the hand-kept 'cash to keep ready' ledger (2026-09-25).
The repo is PUBLIC: no confirmation numbers, card digits or account ids."""
import json
import os
import re

P = os.path.join(os.path.dirname(__file__), "..", "site", "cash_plan.json")
STATUSES = {"not_booked", "reserved", "optional", "paid"}


def load():
    with open(P) as f:
        return json.load(f)


def test_items_follow_the_contract():
    c = load()
    for it in c["items"]:
        assert it["status"] in STATUSES, it["id"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", it["due"]), it["id"]
        assert it["usd"] is None or isinstance(it["usd"], (int, float)), it["id"]
        assert it["what"] and it["due_label"], it["id"]
    assert len({it["id"] for it in c["items"]}) == len(c["items"])


def test_unpriced_items_are_never_summed_as_zero():
    for it in load()["items"]:
        if it["usd"] is None:
            assert it.get("range") or it["status"] == "optional", it["id"]


def test_no_private_reference_numbers_in_the_public_file():
    raw = open(P).read()
    # 6+ digit runs = confirmation / PNR / account / card-ish numbers
    assert not re.search(r"\d{6,}", raw.replace("2026-", "").replace("2027-", ""))
    assert not re.search(r"\b(?:ending|…|x{2,})\s?\d{4}\b", raw, re.I)
    assert not re.search(r"\b[A-Z]{2}-[A-Z]{2}\d{4}", raw)          # Amex trip refs
