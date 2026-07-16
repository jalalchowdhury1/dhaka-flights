import os
import urllib.request
import urllib.parse
import json

from combo import best_combos, cheapest_by_leg, best_structures

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

LEG_EMOJI = {"BOS→DAC": "🇧🇩", "DAC→DPS": "🌴", "DPS→BOS": "🏠"}


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
    parts = s.replace(",", "").split()
    return f"{parts[0][:3]} {parts[1]}" if len(parts) >= 2 else s


def _leg_line(f: dict) -> str:
    return (f"{LEG_EMOJI.get(f['route'], '✈️')} {f['route']} · {_short_date(f['depart'])} · "
            f"{f['airline']} · {f['stops']}"
            f"{' (' + f['layovers'] + ')' if f.get('layovers') not in ('N/A', 'none', None) else ''}"
            f" · ${f['price_total']:,} · [book]({f['link']})")


def _openjaw_line(oj: dict) -> str:
    route = oj.get("desc") or (f"BOS→DAC {_short_date(oj['out_date'])} + "
                               f"DPS→BOS {_short_date(oj['ret_date'])} (one ticket) · {oj['airline']} out")
    return f"🎫 {route} · ${oj['price_total']:,} · [book]({oj['link']})"


def build_message(all_flights: list, openjaws: list = None) -> str:
    openjaws = openjaws or []
    lines = ["✈️ *BOS → Dhaka → Bali → BOS* (2 adults + 1 child)\n"]

    structures = best_structures(all_flights, openjaws)
    if structures:
        s = structures[0]
        flag = "" if s["valid"] else f" ⚠️ {s.get('flag') or 'check dates'}"
        lines.append(f"💰 *Best today: ${s['total']:,} total — {s['name']}*{flag}")
        lines.append(f"_Dhaka {s['dhaka_days']} days · Bali {s['bali_nights']} nights · home {s['home']}_")
        if "openjaw" in s:
            lines.append(_openjaw_line(s["openjaw"]))
        for f in s["legs"]:
            lines.append(_leg_line(f))
        if len(structures) > 1:
            lines.append("")
            lines.append("*Other structures:*")
            for s2 in structures[1:]:
                flag = "" if s2["valid"] else f" ⚠️ {s2.get('flag') or 'check dates'}"
                lines.append(f"  ${s2['total']:,} — {s2['name']} · home {s2['home']}{flag}")
    elif best_combos(all_flights, top_n=1):
        c = best_combos(all_flights, top_n=1)[0]
        home = c["home"].strftime("%b %-d") if c["home"] else "?"
        lines.append(f"💰 *Best full trip: ${c['total']:,} total*")
        lines.append(f"_Dhaka {c['dhaka_days']} days · Bali {c['bali_nights']} nights · home {home}_")
        for f in c["legs"]:
            lines.append(_leg_line(f))
    else:
        missing = [r for r in ("BOS→DAC", "DAC→DPS", "DPS→BOS")
                   if r not in cheapest_by_leg(all_flights)]
        if missing:
            lines.append(f"⚠️ No valid combo — no prices for: {', '.join(missing)}")
        else:
            lines.append("⚠️ No combo satisfied the visa/5-night/Feb-7 rules today")

    best = cheapest_by_leg(all_flights)
    if best:
        lines.append("\n*Cheapest per leg* (dates may not combine):")
        for route in ("BOS→DAC", "DAC→DPS", "DPS→BOS"):
            f = best.get(route)
            lines.append(_leg_line(f) if f else f"{route}: no results")

    lines.append("\n_Google Flights · prices are totals for all 3 travelers_")
    return "\n".join(lines)


def notify_cheapest(all_flights: list, openjaws: list = None) -> None:
    ok = send_message(build_message(all_flights, openjaws))
    if ok:
        print("Telegram notification sent.")
    else:
        print("Telegram notification failed.")
