"""Telegram brief. REDESIGNED 2026-08-02 (Jalal: "looks too info dense") —
one-phone-screen core + tap-to-expand blockquotes for reference material.

Format rules:
- The VISIBLE core answers "should I book, and did anything move?": alerts,
  total + order + trend, the trip shape, the two tickets, the Bali gap, the
  hotel, countdown. One line each.
- Everything that repeats nightly (booking links, baggage rules,
  alternatives, self-check detail) lives in <blockquote expandable> rows —
  Telegram renders them collapsed with the first line as the row label.
- parse_mode is HTML (expandable quotes don't exist in Markdown mode).
  EVERY dynamic string goes through esc_html; link hrefs too.
"""
import os
import urllib.request
import json
from typing import Optional

import baggage

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

LEG_EMOJI = {"BOS→DAC": "🇧🇩", "DAC→DPS": "🌴", "DPS→BOS": "🏠",
             "DAC→SIN": "🇸🇬", "SIN→DPS": "🌴", "DAC→SIN→DPS": "🇸🇬",
             "DAC→BKK": "🇹🇭", "BKK→SIN": "🇸🇬", "SIN→BKK": "🇹🇭",
             "DAC→BKK→SIN": "🇹🇭", "DAC→SIN→BKK": "🇸🇬",
             "DPS→SIN": "🇸🇬", "DAC→DPS→SIN": "🌴"}

SITE_URL = "https://dhaka-flights.vercel.app"


def esc_html(s) -> str:
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def _short_date(s: str) -> str:
    """'January 4, 2027' → 'Jan 4'"""
    parts = str(s).replace(",", "").split()
    return f"{parts[0][:3]} {parts[1]}" if len(parts) >= 2 else str(s)


def _link(url, label="book") -> str:
    return f'<a href="{esc_html(url)}">{esc_html(label)}</a>' if url else ""


def _quote(lines: list) -> str:
    """An expandable blockquote — collapsed, the first line is the row label."""
    return "<blockquote expandable>" + "\n".join(lines) + "</blockquote>"


def _leg_line(f: dict) -> str:
    lay = (" (" + esc_html(f["layovers"]) + ")"
           if f.get("layovers") not in ("N/A", "none", None) else "")
    return (f"{LEG_EMOJI.get(f['route'], '✈️')} {esc_html(f['route'])} "
            f"{_short_date(f['depart'])} · {esc_html(f['airline'])} · "
            f"{esc_html(f['stops'])}{lay} · ${f['price_total']:,} · {_link(f['link'])}")


def _ticket1_line(oj: dict) -> str:
    route = oj.get("desc") or (f"BOS→DAC {_short_date(oj['out_date'])} + "
                               f"DPS→BOS {_short_date(oj['ret_date'])} (one ticket)")
    return (f"🎫 ① {esc_html(route)} · {esc_html(oj.get('airline', '?'))} · "
            f"${oj['price_total']:,} · {_link(oj['link'])}")


def _ticket2_line(t: dict) -> str:
    route = t.get("route", "DAC→SIN→DPS")
    return (f"{LEG_EMOJI.get(route, '✈️')} ② {esc_html(route)} "
            f"{_short_date(t['out_date'])} + {_short_date(t['ret_date'])} "
            f"(one ticket) · {esc_html(t.get('airline', '?'))} · "
            f"${t['price_total']:,} · {_link(t['link'])}")


def _flights_quote(main: dict) -> str:
    lines = ["✈️ Flights &amp; booking links"]
    if main.get("openjaw"):
        lines.append(_ticket1_line(main["openjaw"]))
    if main.get("sg_ticket"):
        lines.append(_ticket2_line(main["sg_ticket"]))
    for f in main.get("legs", []):
        lines.append(_leg_line(f))
    if main.get("alt_note"):
        lines.append(f"💸 {esc_html(main['alt_note'])}")
    other = main.get("other_order")
    if other:
        gap = (f"+${other['delta']:,}" if other["delta"] > 0 else
               "same price" if other["delta"] == 0 else f"−${-other['delta']:,}")
        oflag = "" if other.get("valid") else f" ⚠️ {esc_html(other.get('flag') or '')}"
        lines.append(f"🔁 {esc_html(other.get('order_label', 'other order'))}: "
                     f"${other['total']:,} ({gap}){oflag} — "
                     f"① {esc_html(other.get('ticket1_airline', '?'))} "
                     f"${other.get('ticket1_total', 0):,} + "
                     f"② {esc_html(other.get('ticket2_airlines', '?'))} "
                     f"${other.get('ticket2_total', 0):,}")
    lines.append("Prices are Google Flights totals for all 3 travelers.")
    return _quote(lines)


def _baggage_quote(main: dict) -> str:
    rows = baggage.annotate(main)
    if not rows:
        return ""
    lines = ["🧳 Baggage per leg (confirm at booking)"]
    seen = set()
    for r in rows:
        key = (r["ticket"], r["carrier"], r["checked"])
        if key in seen:
            continue
        seen.add(key)
        tick = "①" if r["ticket"] == 1 else "②"
        legs = "/".join(x["route"] for x in rows
                        if (x["ticket"], x["carrier"], x["checked"]) == key)
        lines.append(f"{tick} {esc_html(legs)} · {esc_html(r['carrier'])}: "
                     f"{esc_html(r['checked'])}")
    for w in baggage.warnings(main)[:2]:
        lines.append(f"⚠️ {esc_html(w)}")
    return _quote(lines)


def _alts_quote(payload: dict) -> str:
    lines = ["🔀 Same-date alternatives"]

    def rows(options, tag, limit):
        out = []
        for o in [x for x in options if not x.get("chosen")][:limit]:
            d = o.get("delta")
            gap = ("same price" if not d else
                   (f"+${d:,}" if d > 0 else f"−${-d:,} CHEAPER"))
            b = o.get("baggage") or {}
            bag = b.get("summary") or b.get("checked", "")
            books = _link(o.get("link"))
            if o.get("link2"):
                books = _link(o.get("link"), "book 1st") + " " + _link(o["link2"], "2nd")
            out.append(f"{tag} {gap} · {esc_html(o['airline'])} · {esc_html(o['kind'])}"
                       f"{' · ' + esc_html(bag) if bag else ''}"
                       f"{' · ' + books if books else ''}")
        return out

    t2 = rows(payload.get("ticket2_options") or [], "②", 4)
    t1 = rows(payload.get("ticket1_options") or [], "①", 3)
    if not (t1 or t2):
        return ""
    return _quote(lines + t2 + t1)


def build_message(payload: dict, core_only: bool = False) -> str:
    """The nightly brief: a one-screen core + expandable reference rows,
    all built from the published payload so Telegram and the dashboard can
    never disagree. core_only=True drops the expandable rows — the fallback
    when a very busy night overflows Telegram's message limit."""
    main = payload.get("main")
    warnings = payload.get("warnings") or []
    parts = []

    # ── Alerts lead, always visible ──
    for a in payload.get("alerts") or []:
        parts.append(f"<b>{esc_html(str(a).replace('*', ''))}</b>")

    if not main:
        parts.append("⚠️ <b>No trip could be priced today</b> — Ticket ① or the "
                     "Bangkok/Singapore middle came back empty in both orders. "
                     "Check cron.log; the retry slots will try again.")
        if warnings:
            parts.append(_quote([f"🧪 Self-check · {len(warnings)} note"
                                 f"{'s' if len(warnings) != 1 else ''}"] +
                                [f"⚠️ {esc_html(w)}" for w in warnings]))
        parts.append(f'<a href="{SITE_URL}">dashboard</a>')
        return "\n".join(parts)

    # ── The one-screen core ──
    flag = "" if main.get("valid") else f" ⚠️ {esc_html(main.get('flag') or 'check dates')}"
    parts.append(f"🌟 <b>${main['total']:,}</b> · {esc_html(main.get('order_label', '?'))}{flag}")
    if payload.get("price_context"):
        parts.append(f"<i>{esc_html(payload['price_context'])}</i>")
    stays = (f"BKK {main.get('bkk_nights')}n · SIN {main.get('sg_nights')}n"
             if main.get("order") == "BKK-first" else
             f"SIN {main.get('sg_nights')}n · BKK {main.get('bkk_nights')}n")
    parts.append(f"🕌 IST {main.get('ist_nights') or 2}n · 🇧🇩 DAC {main['dhaka_days']}d · "
                 f"{stays} · 🏠 home {esc_html(main['home'])}")

    oj, t2 = main.get("openjaw") or {}, main.get("sg_ticket")
    t2_cost = (t2["price_total"] if t2 else
               sum(f.get("price_total", 0) for f in main.get("legs") or []))
    t2_air = esc_html(main.get("sg_airlines", "?"))
    parts.append(f"① {esc_html(oj.get('airline', '?'))} ${oj.get('price_total', 0):,} · "
                 f"② {t2_air} ${t2_cost:,}")

    bali = payload.get("bali")
    if bali:
        d = bali.get("delta_vs_main")
        gap = ("no Bangkok trip to compare" if not isinstance(d, (int, float))
               else "same price as Bangkok" if d == 0
               else f"+${d:,} more than Bangkok" if d > 0
               else f"−${-d:,} CHEAPER than Bangkok")
        ob = bali.get("other_bali")
        ob_note = (f" (other order ${ob['total']:,})" if ob else "")
        parts.append(f"🌴 Original Bali trip: ${bali['total']:,} · "
                     f"{esc_html(bali.get('order_label', ''))} — {gap}{ob_note}")

    hotel = payload.get("hotel")
    if hotel:
        pts = "–".join(f"{p // 1000}K" for p in sorted((hotel.get("points") or {}).values()))
        parts.append(f"🏨 {esc_html(hotel['property'])} · {esc_html(hotel['checkin'])}–"
                     f"{esc_html(hotel['checkout'])} ({hotel['nights']}n) · ~{pts} pts"
                     f"{' · 5th night FREE ✓' if hotel.get('fifth_night_free') else ''}")
        if hotel.get("warn"):
            parts.append(f"⚠️ {esc_html(hotel['warn'])}")

    # 🛏️ Stay math (2026-08-19): the all-in night-count table, one line.
    sv = payload.get("stay_value")
    if sv and sv.get("rows"):
        seg = " · ".join(
            f"{r['n']}N ${r['allin']:,}"
            + (" ←" if r["n"] == sv.get("picked_n") else "")
            for r in sv["rows"])
        sh = sv.get("hotel") or {}
        parts.append(f"🛏️ Stay math: {seg} · {esc_html(sh.get('name', '?'))} "
                     f"${sh.get('rate', 0):,}/n")
        if sv.get("mode") == "advisory" and sv.get("note"):
            parts.append(f"⚠️ {esc_html(sv['note'])}")
        if sv.get("watchdog"):
            parts.append(f"👀 {esc_html(sv['watchdog'])}")

    budget = payload.get("budget")
    if budget:
        diffs = f" — <i>{esc_html(' · '.join(budget.get('diffs') or []))}</i>" \
            if budget.get("diffs") else ""
        parts.append(f"💸 Cheaper if flexible: <b>${budget['total']:,}</b> · "
                     f"save ${budget['savings']:,}{diffs}")

    # ── Expandable reference rows ──
    if core_only:
        parts.append(f'<i>full detail on the</i> <a href="{SITE_URL}">dashboard</a>')
        return "\n".join(parts)
    if warnings:
        parts.append(_quote([f"🧪 Self-check · {len(warnings)} note"
                             f"{'s' if len(warnings) != 1 else ''}"] +
                            [f"⚠️ {esc_html(w)}" for w in warnings]))
    changes = payload.get("changes") or []
    if changes:
        parts.append(_quote(["ℹ️ Changed since yesterday"] +
                            [esc_html(c) for c in changes]))
    parts.append(_flights_quote(main))
    bag_q = _baggage_quote(main)
    if bag_q:
        parts.append(bag_q)
    alts_q = _alts_quote(payload)
    if alts_q:
        parts.append(alts_q)
    if budget and (budget.get("sg_ticket") or budget.get("legs")):
        blines = ["💸 The flexible-dates option, in full"]
        if budget.get("sg_ticket"):
            blines.append(_ticket2_line(budget["sg_ticket"]))
        for f in budget.get("legs", []):
            blines.append(_leg_line(f))
        parts.append(_quote(blines))

    # ── Footer ──
    foot = []
    if payload.get("countdown"):
        foot.append(esc_html(str(payload["countdown"]).replace("📅 ", "")))
    if payload.get("verified"):
        foot.append("🔎 re-check ✓")
    if foot:
        parts.append(f"<i>📅 {' · '.join(foot)}</i>")
    parts.append(f'<a href="{SITE_URL}">dashboard</a>')
    return "\n".join(parts)


# The last-resort rung: fixed text (can't fail to render — no dict lookups,
# no formatting that depends on the payload), warnings (if any) in the
# middle, and the dashboard link LAST — same shape as every other rung,
# which always ends on the link.
MINIMAL_FALLBACK_TEXT = (
    "⚠️ tonight's brief could not be built — see cron.log; data may still "
    "have published."
)
MINIMAL_FALLBACK_LINK = f'<a href="{SITE_URL}">dashboard</a>'
MINIMAL_FALLBACK_PLAIN = MINIMAL_FALLBACK_TEXT + "\n" + MINIMAL_FALLBACK_LINK


def _safe_build(*args, **kwargs) -> Optional[str]:
    """build_message assumes a well-formed payload (main['total'] etc.) — a
    structurally broken one must degrade like a send failure, not raise and
    take write_payload's turn to run with it."""
    try:
        return build_message(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        print(f"build_message failed: {e}")
        return None


def _safe_send(text: str) -> bool:
    """send_message already swallows its own network errors, but callers
    (tests, or a future patch) can replace it with something that doesn't —
    this is the last line of defense before notify_cheapest itself."""
    try:
        return send_message(text)
    except Exception as e:  # noqa: BLE001
        print(f"send_message raised: {e}")
        return False


def _minimal_fallback_message(payload: dict) -> str:
    """The last rung: MINIMAL_FALLBACK_TEXT, then (if any) the first few
    self-check warnings — escaped like every other dynamic string in this
    module — then the dashboard link LAST, so a broken-brief night still
    says WHY it broke and still ends on the same link every other rung
    ends on."""
    lines = [MINIMAL_FALLBACK_TEXT]
    for w in (payload.get("warnings") or [])[:3]:
        lines.append(f"⚠️ {esc_html(w)}")
    lines.append(MINIMAL_FALLBACK_LINK)
    return "\n".join(lines)


def notify_cheapest(payload: dict) -> str:
    """Send the brief; on failure (length overflow, parse hiccup, or a
    broken payload build_message can't render) degrade step by step — full,
    core-only, then a minimal static line naming why — rather than losing
    the night's message or raising and costing the run its publish step.

    Returns the rung that actually sent: "full" | "core" | "minimal". If
    even the minimal send failed, the split that matters is WHY nothing
    reached anyone: "none" means at least one real build (full or core)
    succeeded — Telegram itself was unreachable, a delivery problem the
    published data doesn't share in. "broken" means BOTH real builds
    failed — a genuine payload/shape problem, the same class of trouble a
    no-trip night is. run_daily.py stamps on "full"/"core"/"none" but not
    on "minimal"/"broken" — the former three mean tonight's data is fine
    even if Telegram never heard about it; the latter two mean tonight's
    run needs another shot."""
    full = _safe_build(payload)
    if full is not None and _safe_send(full):
        print("Telegram notification sent.")
        return "full"
    print("Full brief failed — sending core-only fallback...")
    core = _safe_build(payload, core_only=True)
    if core is not None and _safe_send(core):
        print("Telegram notification sent (core-only fallback).")
        return "core"
    built_ok = full is not None or core is not None
    print("Core-only fallback failed too — sending minimal static message...")
    try:
        minimal = _minimal_fallback_message(payload)
    except Exception as e:  # noqa: BLE001 — the last rung must not raise either
        print(f"minimal fallback message build failed too: {e}")
        minimal = MINIMAL_FALLBACK_PLAIN
    if _safe_send(minimal):
        print("Telegram notification sent (minimal fallback).")
        return "minimal"
    print("Telegram notification failed.")
    return "none" if built_ok else "broken"
