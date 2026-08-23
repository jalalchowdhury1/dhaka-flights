"""Telegram brief. REDESIGNED 2026-08-20 v4 (Jalal iterated 4 phone previews
and approved this shape) — conclusions-first core, arithmetic collapsed.

Format rules:
- The core is two blank-line-separated stanzas, each line ≤ ~44 visible
  chars so nothing wraps on a phone: (1) PRICE — total + order + a compact
  price-context/fire-alert line + the trip shape (IST/DAC/stay nights/home)
  + the two ticket totals; (2) STAYS — the hotel line and a one-line stay-
  math CONCLUSION ("St. Regis 4N ✓ · $4,954 all-in"), never the arithmetic
  behind it.
- The core answers "should I book, and did anything move?" in CONCLUSIONS
  only. Every number's arithmetic — the per-night-count table, the flexible-
  dates breakdown, the Bali comparison, folded 🔥 alert text — lives in the
  🛏️ Stay math <blockquote expandable>, which rides FIRST among the
  expandables because it's decision-adjacent. Nothing is silently dropped:
  every fact that leaves the core has a home in that quote.
- 🚨 alerts (and anything with neither 🚨 nor 🔥) still LEAD the message in
  bold. 🔥 alerts (new lows) FOLD into a compact tag on the price-context
  line ("① new low 🔥") — their full text moves into the stays quote instead
  of leading, so a routine low doesn't cost a whole bold line.
- Everything else that repeats nightly (booking links, baggage rules,
  alternatives, self-check detail) lives in its own <blockquote expandable>
  row, unchanged — Telegram renders them collapsed with the first line as
  the row label.
- parse_mode is HTML (expandable quotes don't exist in Markdown mode).
  EVERY dynamic string goes through esc_html; link hrefs too.
"""
import os
import re
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


REMINDER_STAMP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              ".reminders_sent")


def reminder_message(today=None) -> Optional[str]:
    """⏰ day-of push (2026-08-23, Jalal: "remind me when it's time on
    Telegram what to do"): every reminder due TODAY with its numbered steps.
    None when nothing is due. Stands alone — NOT part of the brief — so it
    survives a night when the scrape fails."""
    import datetime
    import alerts
    due = alerts.due_reminders(today or datetime.date.today())
    if not due:
        return None
    parts = []
    for _i, text, steps in due:
        parts.append(f"⏰ <b>TODAY — {esc_html(text)}</b>")
        parts.extend(f"{n}. {esc_html(step)}" for n, step in enumerate(steps, 1))
        parts.append("")
    return "\n".join(parts).rstrip()


def _stamped(path) -> set:
    try:
        with open(path) as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return set()


def send_due_reminders(today=None, stamp_path=REMINDER_STAMP, send=None) -> bool:
    """Push today's reminders ONCE. Both nightly jobs call this (midnight
    flights run, 5 am hotel run) so a failed scrape can't swallow a deadline;
    the stamp file makes the second caller a no-op. True when a message went
    out (or nothing was due)."""
    import datetime
    import alerts
    today = today or datetime.date.today()
    send = send or send_message
    keys = [f"{today.isoformat()}:{i}" for i, _t, _s in alerts.due_reminders(today)]
    done = _stamped(stamp_path)
    if not keys or all(k in done for k in keys):
        return True
    msg = reminder_message(today)
    if not msg or not send(msg):
        return False
    with open(stamp_path, "a") as f:
        f.write("".join(k + "\n" for k in keys if k not in done))
    return True


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


def _short_air(s):
    """Display-only: 'US-Bangla Airlines + Scoot' → 'US-Bangla+Scoot'."""
    return (str(s or "?").replace(" Airlines", "").replace(" Airways", "")
            .replace(" + ", "+"))


def _short_prop(s):
    """Display-only hotel name: 'The Athenee Hotel, a Luxury Collection
    Hotel' → 'Athenee'; 'St. Regis Singapore' → 'St. Regis'."""
    s = str(s or "?").split(",")[0].strip()
    for pre in ("The ",):
        if s.startswith(pre):
            s = s[len(pre):]
    for suf in (" Hotel", " Singapore", " Istanbul"):
        if s.endswith(suf):
            s = s[:-len(suf)]
    return s


def _compact_countdown(s):
    """'12 days to your usual booking window (booked …)' → '12 days'."""
    m = re.search(r"(\d+) days?", str(s or ""))
    return f"{m.group(1)} days" if m else None


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
    line = (f"🎫 ① {esc_html(route)} · {esc_html(oj.get('airline', '?'))} · "
            f"${oj['price_total']:,} · {_link(oj['link'])}")
    pick = oj.get("pick") or {}
    if pick.get("note"):
        # 2026-08-23 convenience rule: say WHY the pick is not the cheapest.
        line += f"\n   ✈️ {esc_html(pick['note'])}"
    return line


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


def _stays_quote(payload: dict, main: dict, sv: Optional[dict],
                 fire_full: list) -> str:
    """The FIRST expandable (2026-08-20 v4): the arithmetic behind the core's
    stay-math CONCLUSION line — the per-night-count table, the rate, folded
    🔥 alert text, the flexible-dates breakdown, and the Bali comparison.
    Built from whatever exists; skipped entirely if it would only be its own
    header (nothing to show)."""
    header_bits = ["🛏️ Stay math"]
    body = []

    if sv and sv.get("rows"):
        hotel = sv.get("hotel") or {}
        picked_n = sv.get("picked_n")
        body.append(" · ".join(
            f"{r['n']}N ${r['allin']:,}" + (" ✓picked" if r["n"] == picked_n else "")
            for r in sv["rows"]))
        checked = str(hotel.get("checked") or "")
        stamp = (f" ✓{int(checked[5:7])}/{int(checked[8:10])}"
                if len(checked) == 10 and checked[4] == "-" else "")
        two_free = any(r["n"] == 2 and r.get("hotel_net") == 0 for r in sv["rows"])
        credit_note = " — credits cover the first 2N" if two_free else ""
        # Est. all-in per paid night (portal-anchored, 2026-08-22); the
        # public rate is only the fallback for a row with no anchor.
        per_night = hotel.get("allin_night") or hotel.get("rate", 0)
        body.append(f"{esc_html(_short_prop(hotel.get('name')))} "
                    f"~${per_night:,.0f}/n all-in{stamp}{credit_note}")
        if sv.get("mode") == "advisory" and sv.get("note"):
            body.append(f"⚠️ {esc_html(sv['note'])}")
        if sv.get("watchdog"):
            body.append(f"👀 {esc_html(sv['watchdog'])}")

    for a in fire_full:
        body.append(esc_html(a))

    budget = payload.get("budget")
    if budget:
        header_bits.append("💸 flexible")
        dd = (budget.get("dhaka_days") or 0) - (main.get("dhaka_days") or 0)
        dac_note = (f" · {'+' if dd > 0 else '−'}{abs(dd)} DAC days" if dd else "")
        savings = budget.get("savings")
        save_note = (f" — save ${savings:,}"
                    if isinstance(savings, (int, float)) else "")
        body.append(f"💸 Flights-only ${budget['total']:,} "
                    f"({budget.get('sg_nights')}N{dac_note}){save_note}")

    bali = payload.get("bali")
    if bali:
        header_bits.append("🌴 Bali")
        d = bali.get("delta_vs_main")
        if isinstance(d, (int, float)):
            gap = (f"+${d:,}" if d > 0 else f"−${-d:,}" if d < 0 else "same price")
        else:
            gap = "n/a"
        ob = bali.get("other_bali")
        rev = f" · rev ${ob['total']:,}" if ob else ""
        body.append(f"🌴 Bali: ${bali['total']:,} ({gap} vs Bangkok{rev})")

    if not body:
        return ""
    return _quote([" · ".join(header_bits)] + body)


def build_message(payload: dict, core_only: bool = False) -> str:
    """The nightly brief (2026-08-20 v4): a one-screen core of two blank-
    line-separated stanzas (price · stays) + expandable reference rows, all
    built from the published payload so Telegram and the dashboard can never
    disagree. core_only=True drops the expandable rows — the fallback when a
    very busy night overflows Telegram's message limit."""
    main = payload.get("main")
    warnings = payload.get("warnings") or []
    parts = []

    if not main:
        # ── Alerts lead, always visible (unchanged — no stays quote exists
        # on a no-trip night, so there's nowhere for a folded 🔥 to go) ──
        for a in payload.get("alerts") or []:
            parts.append(f"<b>{esc_html(str(a).replace('*', ''))}</b>")
        parts.append("⚠️ <b>No trip could be priced today</b> — Ticket ① or the "
                     "Bangkok/Singapore middle came back empty in both orders. "
                     "Check cron.log; the retry slots will try again.")
        if warnings:
            parts.append(_quote([f"🧪 Self-check · {len(warnings)} note"
                                 f"{'s' if len(warnings) != 1 else ''}"] +
                                [f"⚠️ {esc_html(w)}" for w in warnings]))
        parts.append(f'<a href="{SITE_URL}">dashboard</a>')
        return "\n".join(parts)

    # ── Alert partition: 🚨 (and anything with neither marker) LEADS in
    # bold, exactly as today. 🔥 (a new low) FOLDS into a compact tag on the
    # price-context line instead — its full text moves into the stays quote
    # below, never silently dropped. ──
    lead_alerts, fire_tags, fire_full = [], [], []
    for a in payload.get("alerts") or []:
        s = str(a)
        if "🚨" in s:
            lead_alerts.append(s)
        elif "🔥" in s:
            fire_tags.append("① new low 🔥" if "Ticket ①" in s else "trip low 🔥")
            fire_full.append(s)
        else:
            lead_alerts.append(s)
    for a in lead_alerts:
        parts.append(f"<b>{esc_html(a.replace('*', ''))}</b>")

    # ── Price stanza ──
    flag = "" if main.get("valid") else f" ⚠️ {esc_html(main.get('flag') or 'check dates')}"
    parts.append(f"🌟 <b>${main['total']:,}</b> · {esc_html(main.get('order_label', '?'))}{flag}")

    ctx_bits = []
    if payload.get("price_context"):
        ctx_bits.append(esc_html(payload["price_context"]))
    if fire_tags:
        ctx_bits.append(" · ".join(fire_tags))
    if ctx_bits:
        parts.append(f"<i>{' · '.join(ctx_bits)}</i>")

    stays = (f"🇹🇭 {main.get('bkk_nights')}n · 🇸🇬 {main.get('sg_nights')}n"
             if main.get("order") == "BKK-first" else
             f"🇸🇬 {main.get('sg_nights')}n · 🇹🇭 {main.get('bkk_nights')}n")
    parts.append(f"🕌 {main.get('ist_nights') or 2}n · 🇧🇩 {main['dhaka_days']}d · "
                 f"{stays} · 🏠 {esc_html(main['home'])}")

    oj, t2 = main.get("openjaw") or {}, main.get("sg_ticket")
    t2_cost = (t2["price_total"] if t2 else
               sum(f.get("price_total", 0) for f in main.get("legs") or []))
    parts.append(f"① {esc_html(_short_air(oj.get('airline', '?')))} "
                 f"${oj.get('price_total', 0):,} · "
                 f"② {esc_html(_short_air(main.get('sg_airlines', '?')))} ${t2_cost:,}")

    # ── Stays stanza ──
    parts.append("")
    hotel = payload.get("hotel")
    sv = payload.get("stay_value")
    if hotel:
        pts = hotel.get("points") or {}
        pts_str = f"{min(pts.values()) // 1000}K pts" if pts else "? pts"
        free = " · 5th night FREE" if hotel.get("fifth_night_free") else ""
        parts.append(f"🏨 {esc_html(_short_prop(hotel.get('property')))} "
                     f"{hotel.get('nights')}n · {pts_str}{free}")
        if hotel.get("warn"):
            parts.append(f"⚠️ {esc_html(hotel['warn'])}")
    if sv and sv.get("mode") == "steering" and sv.get("rows"):
        h = sv.get("hotel") or {}
        parts.append(f"🛏️ {esc_html(_short_prop(h.get('name')))} "
                     f"<b>{sv.get('picked_n')}N ✓</b> · "
                     f"${sv.get('trip_allin') or 0:,} all-in")
    elif sv and sv.get("mode") == "advisory":
        parts.append(f"🛏️ SIN {main.get('sg_nights')}N · ⚠️ stay math advisory")

    if core_only:
        parts.append(f'<i>full detail on the</i> <a href="{SITE_URL}">dashboard</a>')
        return "\n".join(parts)

    # ── Expandable reference rows: stays FIRST (decision-adjacent — it
    # holds the arithmetic behind the stays stanza's conclusion, the folded
    # 🔥 text, the budget breakdown, and the Bali comparison), then the
    # self-check/changes/flights/baggage/alternatives/budget-detail rows in
    # their existing order. ──
    parts.append("")
    stq = _stays_quote(payload, main, sv, fire_full)
    if stq:
        parts.append(stq)
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
    budget = payload.get("budget")
    if budget and (budget.get("sg_ticket") or budget.get("legs")):
        blines = ["💸 The flexible-dates option, in full"]
        if budget.get("sg_ticket"):
            blines.append(_ticket2_line(budget["sg_ticket"]))
        for f in budget.get("legs", []):
            blines.append(_leg_line(f))
        parts.append(_quote(blines))

    # ── Footer ──
    foot = []
    cc = _compact_countdown(payload.get("countdown"))
    if cc:
        foot.append(esc_html(cc))
    if payload.get("verified"):
        foot.append("🔎 ✓")
    link = f'<a href="{SITE_URL}">dashboard</a>'
    parts.append(f"<i>📅 {' · '.join(foot)}</i> · {link}" if foot else link)
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
