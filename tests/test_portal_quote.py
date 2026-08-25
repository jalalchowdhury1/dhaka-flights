"""The Edit-vs-public gap check.

Rule 2 in AGENTS.md: card-portal rates (Amex FHR, Chase Edit) live behind
logins and are never scraped. So the play's Edit quote is a HAND-ENTERED
number from a cart read, and every nightly run compares it against the public
rate that IS scraped. The bell rings once, on the crossing, when the quote
stops beating booking direct — the exact inversion that sat unnoticed from
2026-08-22 until a Reddit thread prompted a manual look on 08-25.
"""
import hotel_rates


def _quote(total=1285.0, credit=250.0):
    return {"via": "Chase The Edit", "total": total, "credit": credit,
            "date": "2026-08-23"}


def _row(key="ritz_ist", public_allin=486.08, nights=2, quote=None, name="Ritz-Carlton Istanbul"):
    row = {"key": key, "city": "IST", "name": name,
           "public_allin_night": public_allin,
           "stay": {"nights": nights, "total": 1214.06, "credits": 470, "net": 744}}
    if quote is not None:
        row["portal_quote"] = hotel_rates.portal_quote_fields(quote, public_allin, nights)
    return row


# ── the arithmetic ──────────────────────────────────────────────────────────

def test_fields_compute_public_stay_premium_and_edge():
    q = hotel_rates.portal_quote_fields(_quote(), 486.08, 2)
    assert q["public_stay"] == 972.16
    assert q["premium"] == 312.84            # quote is $313 over public
    assert q["net_after_credit"] == 1035.0
    assert q["edge"] == -62.84               # direct beats the Edit today


def test_edge_positive_when_the_quote_still_wins():
    q = hotel_rates.portal_quote_fields(_quote(), 700.0, 2)   # public $1,400
    assert q["edge"] == 365.0


def test_no_public_rate_means_no_fields():
    assert hotel_rates.portal_quote_fields(_quote(), None, 2) is None


def test_build_attaches_the_quote_to_the_configured_play():
    """PORTAL_QUOTES is keyed like SHORTLIST; build() must surface it on the
    row so the site JSON and the bells both see the same numbers."""
    assert "ritz_ist" in hotel_rates.PORTAL_QUOTES
    payload = {"rows": [{"key": "ritz_ist", "rate": 434, "checked": "2026-08-24"}]}
    out = hotel_rates.build(payload)
    row = next(r for r in out["rows"] if r["key"] == "ritz_ist")
    pq = row.get("portal_quote")
    assert pq is not None
    assert pq["via"] == "Chase The Edit"
    assert pq["total"] == 1285.0
    assert pq["edge"] is not None


def test_rows_without_a_quote_are_untouched():
    payload = {"rows": [{"key": "stregis_ist", "rate": 545, "checked": "2026-08-24"}]}
    out = hotel_rates.build(payload)
    row = next(r for r in out["rows"] if r["key"] == "stregis_ist")
    assert "portal_quote" not in row


# ── the bell: crossing-based, never a nightly nag ───────────────────────────

def _snap(edge_now, edge_was):
    new = {"rows": [_row(quote=_quote())]}
    new["rows"][0]["portal_quote"]["edge"] = edge_now
    prev = {"rows": [_row(quote=_quote())]}
    if edge_was is None:
        del prev["rows"][0]["portal_quote"]
    else:
        prev["rows"][0]["portal_quote"]["edge"] = edge_was
    return prev, new


def test_bell_rings_when_the_edge_goes_negative():
    prev, new = _snap(edge_now=-62.84, edge_was=40.0)
    bells = hotel_rates.portal_quote_bells(prev, new)
    assert len(bells) == 1
    assert "Ritz-Carlton" in bells[0]
    assert "direct" in bells[0].lower()
    assert "$63" in bells[0]                 # the gap, rounded, visible


def test_bell_rings_on_first_run_if_already_negative():
    """prev has no portal_quote (feature just shipped) — a live inversion must
    not wait a night to be reported."""
    prev, new = _snap(edge_now=-62.84, edge_was=None)
    assert len(hotel_rates.portal_quote_bells(prev, new)) == 1


def test_no_bell_while_the_quote_still_wins():
    prev, new = _snap(edge_now=120.0, edge_was=150.0)
    assert hotel_rates.portal_quote_bells(prev, new) == []


def test_no_repeat_bell_while_it_stays_negative():
    """Rings on the crossing, then goes quiet — the moves message still shows
    the number nightly, but the 🔔 must not nag."""
    prev, new = _snap(edge_now=-70.0, edge_was=-62.84)
    assert hotel_rates.portal_quote_bells(prev, new) == []


def test_bell_rings_again_on_recovery():
    """The other direction matters too: the Edit becoming the better deal
    again is the moment to prepay."""
    prev, new = _snap(edge_now=35.0, edge_was=-62.84)
    bells = hotel_rates.portal_quote_bells(prev, new)
    assert len(bells) == 1
    assert "again" in bells[0].lower() or "back" in bells[0].lower()


def test_deal_alerts_includes_portal_quote_bells():
    prev, new = _snap(edge_now=-62.84, edge_was=40.0)
    assert any("Ritz-Carlton" in b for b in hotel_rates.deal_alerts(prev, new))


def test_bell_mentions_the_benefits_caveat():
    """Direct-vs-Edit is not apples to apples — the Edit carries breakfast and
    a property credit. The bell must say the gap is BEFORE those extras, or a
    $10 inversion would read as 'cancel the plan'."""
    prev, new = _snap(edge_now=-62.84, edge_was=40.0)
    assert "before" in hotel_rates.portal_quote_bells(prev, new)[0].lower()
