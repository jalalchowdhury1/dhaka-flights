import os
import urllib.request
import urllib.parse
import json

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


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


def notify_cheapest(all_flights: list) -> None:
    dac = [f for f in all_flights if "DAC" in f.get("route", "")]
    bkk = [f for f in all_flights if "BKK" in f.get("route", "")]

    def cheapest(flights):
        valid = [f for f in flights if isinstance(f.get("price_per_person"), (int, float))]
        return min(valid, key=lambda f: f["price_per_person"]) if valid else None

    best_dac = cheapest(dac)
    best_bkk = cheapest(bkk)

    lines = ["✈️ *Daily Flight Prices — BOS Departures*\n"]

    if best_dac:
        lines.append(
            f"🇧🇩 *Dhaka (DAC)*\n"
            f"  ${best_dac['price_per_person']}/person · {best_dac['airline']}\n"
            f"  {best_dac['depart']} → {best_dac['return_date']} · {best_dac['stops']}\n"
            f"  [Book]({best_dac['link']})"
        )
    else:
        lines.append("🇧🇩 *Dhaka (DAC)*\n  No results found")

    lines.append("")

    if best_bkk:
        lines.append(
            f"🇹🇭 *Bangkok (BKK)*\n"
            f"  ${best_bkk['price_per_person']}/person · {best_bkk['airline']}\n"
            f"  {best_bkk['depart']} → {best_bkk['return_date']} · {best_bkk['stops']}\n"
            f"  [Book]({best_bkk['link']})"
        )
    else:
        lines.append("🇹🇭 *Bangkok (BKK)*\n  No results found")

    lines.append("\n_Prices from Google Flights · Jan 3–6 depart, Jan 25–28 return_")

    message = "\n".join(lines)
    ok = send_message(message)
    if ok:
        print("Telegram notification sent.")
    else:
        print("Telegram notification failed.")
