import os
import urllib.request
import urllib.parse
import json

import baggage

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

LEG_EMOJI = {"BOS→DAC": "🇧🇩", "DAC→DPS": "🌴", "DPS→BOS": "🏠",
             "DAC→SIN": "🇸🇬", "SIN→DPS": "🌴", "DAC→SIN→DPS": "🇸🇬"}


def send_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def _short_date(s: str) -> str:
    """'January 4, 2027' → 'Jan 4'"""
    parts = str(s).replace(",", "").split()
    return f"{parts[0][:3]} {parts[1]}" if len(parts) >= 2 else s


def _leg_line(f: dict) -> str:
    return (f"{LEG_EMOJI.get(f['route'], '✈️')} {f['route']} · {_short_date(f['depart'])} · "
            f"{f['airline']} · {f['stops']}"
            f"{' (' + f['layovers'] + ')' if f.get('layovers') not in ('N/A', 'none', None) else ''}"
            f" · ${f['price_total']:,} · [book]({f['link']})")


def _ticket1_line(oj: dict) -> str:
    route = oj.get("desc") or (f"BOS→DAC {_short_date(oj['out_date'])} + "
                               f"DPS→BOS {_short_date(oj['ret_date'])} (one ticket)")
    return f"🎫 *Ticket ①* {route} · {oj.get('airline','?')} · ${oj['price_total']:,} · [book]({oj['link']})"


def _ticket2_line(t: dict) -> str:
    return (f"🇸🇬 *Ticket ②* DAC→SIN→DPS · {_short_date(t['out_date'])} + "
            f"{_short_date(t['ret_date'])} (one ticket) · {t.get('airline','?')} · "
            f"${t['price_total']:,} · [book]({t['link']})")


def _baggage_block(main: dict) -> list:
    """Per-leg allowance — the thing that's "all over the place" (2026-07-25).
    Reference figures only; the fare page is the authority."""
    rows = baggage.annotate(main)
    if not rows:
        return []
    lines = ["🧳 *Baggage per leg* (reference — confirm at booking):"]
    seen = set()
    for r in rows:
        # Ticket ① legs share one allowance; print it once.
        key = (r["ticket"], r["carrier"], r["checked"])
        if key in seen:
            continue
        seen.add(key)
        tick = "①" if r["ticket"] == 1 else "②"
        legs = "/".join(x["route"] for x in rows
                        if (x["ticket"], x["carrier"], x["checked"]) == key)
        lines.append(f"  {tick} {legs} · {r['carrier']}: {r['checked']}")
    for w in baggage.warnings(main)[:2]:
        lines.append(f"  ⚠️ {w}")
    return lines


def _alternatives_block(options: list, title: str, limit: int = 4) -> list:
    """What else could buy this ticket, and how much more (Jalal 2026-07-25)."""
    others = [o for o in options if not o.get("chosen")][:limit]
    if not others:
        return []
    lines = [f"🔀 *{title}* (same dates):"]
    for o in others:
        d = o.get("delta")
        gap = ("same price" if not d else
               (f"+${d:,}" if d > 0 else f"−${-d:,} CHEAPER"))
        b = o.get("baggage") or {}
        bag = b.get("summary") or b.get("checked", "")
        lines.append(f"  {gap} · {o['airline']} · {o['kind']}"
                     f"{' · ' + bag if bag else ''}")
    return lines


def build_message(main: dict, warnings: list = None,
                  ticket2_options: list = None, ticket1_options: list = None) -> str:
    lines = ["✈️ *BOS → Istanbul → Dhaka → Singapore → Bali → BOS* (2 adults + 1 child)\n"]

    if warnings:
        lines.append("🧪 *Self-check found issues:*")
        for w in warnings:
            lines.append(f"  ⚠️ {w}")
        lines.append("")

    if not main:
        lines.append("⚠️ *No trip could be priced today* — the Istanbul ticket or the "
                     "Singapore middle came back empty. Check cron.log; the retry "
                     "slots will try again.")
        return "\n".join(lines)

    flag = "" if main.get("valid") else f" ⚠️ {main.get('flag') or 'check dates'}"
    lines.append(f"🌟 *${main['total']:,} total*{flag}")
    lines.append(f"_Istanbul {main.get('ist_nights') or 2}n · Dhaka {main['dhaka_days']}d · "
                 f"Singapore {main.get('sg_nights')}n · Bali {main['bali_nights']}n · "
                 f"home {main['home']}_")
    if main.get("openjaw"):
        lines.append(_ticket1_line(main["openjaw"]))
    if main.get("sg_ticket"):
        lines.append(_ticket2_line(main["sg_ticket"]))
    for f in main.get("legs", []):
        lines.append(_leg_line(f))
    if main.get("alt_note"):
        lines.append(f"💸 {main['alt_note']}")

    lines.append("")
    lines += _baggage_block(main)

    alts = _alternatives_block(ticket2_options or [], "Ticket ② alternatives")
    if alts:
        lines.append("")
        lines += alts
    alts1 = _alternatives_block(ticket1_options or [], "Ticket ① alternatives", limit=3)
    if alts1:
        lines.append("")
        lines += alts1

    lines.append("\n_Google Flights · prices are totals for all 3 travelers_")
    lines.append("dhaka-flights.vercel.app")
    return "\n".join(lines)


def notify_cheapest(main: dict, warnings: list = None,
                    ticket2_options: list = None, ticket1_options: list = None) -> None:
    ok = send_message(build_message(main, warnings, ticket2_options, ticket1_options))
    if ok:
        print("Telegram notification sent.")
    else:
        print("Telegram notification failed.")
