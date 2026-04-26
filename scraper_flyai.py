import subprocess
import json
from typing import Union

# CNY to USD approximate rate — update if needed
CNY_TO_USD = 0.138

# Common Chinese airline names → English
AIRLINE_NAMES = {
    "土耳其航空": "Turkish Airlines",
    "国泰航空": "Cathay Pacific",
    "阿联酋航空": "Emirates",
    "卡塔尔航空": "Qatar Airways",
    "新加坡航空": "Singapore Airlines",
    "中国国际航空": "Air China",
    "国航": "Air China",
    "中国东方航空": "China Eastern",
    "东航": "China Eastern",
    "中国南方航空": "China Southern",
    "南航": "China Southern",
    "海南航空": "Hainan Airlines",
    "新海航": "Hainan Airlines",
    "泰国国际航空": "Thai Airways",
    "泰航": "Thai Airways",
    "印度航空": "Air India",
    "孟加拉国航空": "Biman Bangladesh",
    "马来西亚航空": "Malaysia Airlines",
    "斯里兰卡航空": "SriLankan Airlines",
    "香港航空": "Hong Kong Airlines",
    "美国航空": "American Airlines",
    "联合航空": "United Airlines",
    "达美航空": "Delta Air Lines",
    "英国航空": "British Airways",
    "法国航空": "Air France",
    "汉莎航空": "Lufthansa",
    "荷兰皇家航空": "KLM",
    "沙特阿拉伯航空": "Saudia",
    "科威特航空": "Kuwait Airways",
    "阿提哈德航空": "Etihad Airways",
}

DEPART_DATE_START = "2027-01-03"
DEPART_DATE_END = "2027-01-06"
RETURN_DATE_START = "2027-01-25"
RETURN_DATE_END = "2027-01-28"
MAX_RESULTS = 20


def _run_flyai(args: list) -> dict:
    cmd = ["flyai"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return json.loads(result.stdout)
    except Exception:
        return {}


def _cny_to_usd(cny_str: str) -> Union[int, str]:
    try:
        cny = float(cny_str)
        return round(cny * CNY_TO_USD)
    except Exception:
        return "N/A"


def _format_duration(minutes: Union[int, str]) -> str:
    try:
        m = int(minutes)
        return f"{m // 60}h {m % 60}m"
    except Exception:
        return "N/A"


def _parse_item(item: dict, origin: str, dest: str) -> dict:
    journeys = item.get("journeys", [])
    outbound = journeys[0] if journeys else {}

    # Airline: collect unique marketing names across all segments
    airlines = []
    for seg in outbound.get("segments", []):
        name = seg.get("marketingTransportName", "")
        # name is "AliasName|AirlineName" — take the part after "|" if present
        if "|" in name:
            name = name.split("|")[-1]
        # Translate Chinese name to English if known
        name = AIRLINE_NAMES.get(name, name)
        if name and name not in airlines:
            airlines.append(name)
    airline = " + ".join(airlines) if airlines else "N/A"

    # Stops
    segs = outbound.get("segments", [])
    stops = f"{len(segs) - 1} stop" if len(segs) > 1 else "Nonstop"
    if len(segs) - 1 > 1:
        stops = f"{len(segs) - 1} stops"

    # Depart / arrival dates
    dep_dt = segs[0].get("depDateTime", "") if segs else ""
    depart_date = dep_dt[:10] if dep_dt else "N/A"

    ret_journey = journeys[1] if len(journeys) > 1 else {}
    ret_segs = ret_journey.get("segments", [])
    ret_dep_dt = ret_segs[0].get("depDateTime", "") if ret_segs else ""
    return_date = ret_dep_dt[:10] if ret_dep_dt else "N/A"

    # Duration (outbound only)
    duration = _format_duration(outbound.get("totalDuration", "N/A"))

    price_cny = item.get("ticketPrice", "N/A")
    price_usd = _cny_to_usd(price_cny)

    booking_url = item.get("jumpUrl", "N/A")

    return {
        "route": f"{origin}→{dest}",
        "depart": depart_date,
        "return_date": return_date,
        "airline": airline,
        "stops": stops,
        "duration": duration,
        "price_per_person": price_usd,
        "price_cny": price_cny,
        "baggage": "N/A",
        "link": booking_url,
    }


def search_route(origin: str, dest_name: str, dest_code: str) -> list:
    print(f"  Querying FlyAI: {origin} → {dest_name}...")
    data = _run_flyai([
        "search-flight",
        "--origin", origin,
        "--destination", dest_name,
        "--dep-date-start", DEPART_DATE_START,
        "--dep-date-end", DEPART_DATE_END,
        "--back-date-start", RETURN_DATE_START,
        "--back-date-end", RETURN_DATE_END,
        "--sort-type", "3",  # price ascending
    ])

    items = data.get("data", {}).get("itemList", [])
    results = []
    for item in items[:MAX_RESULTS]:
        try:
            results.append(_parse_item(item, origin, dest_code))
        except Exception as e:
            print(f"    Skipping item: {e}")

    return results


def scrape_all() -> list:
    all_results = []

    print("Querying BOS → DAC (Dhaka)...")
    dac = search_route("Boston", "Dhaka", "DAC")
    all_results += dac
    print(f"  Got {len(dac)} results")

    print("Querying BOS → BKK (Bangkok)...")
    bkk = search_route("Boston", "Bangkok", "BKK")
    all_results += bkk
    print(f"  Got {len(bkk)} results")

    return all_results
