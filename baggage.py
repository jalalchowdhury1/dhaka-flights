"""Baggage allowance per leg (2026-07-25, Jalal: "it seems all over the place").

WHY THIS IS A LOOKUP TABLE AND NOT SCRAPED: Google Flights' accessibility tree
carries price/airline/times/layovers only — no bag information. Bag rules also
depend on the FARE BRAND (EcoFly vs Flex, Economy Lite vs Standard), which isn't
visible until the airline's own checkout. So this file holds carrier policy as
published, every entry with its source URL, and the site labels it "reference —
confirm on the fare page". Never present these numbers as the booked allowance.

Two rules drive the whole table:
  * PIECE CONCEPT — any itinerary touching the Americas is counted in bags, not
    kilos, in BOTH directions, and it applies to the whole through-ticket
    (so Ticket ① keeps its US allowance on IST→DAC too).
  * WEIGHT CONCEPT — intra-Asia tickets are counted in kilos and vary wildly
    by carrier AND route (US-Bangla gives 40 kg to Singapore but 20 kg to Doha).

Verified against the carriers' own pages on the CHECKED date below.
"""

CHECKED = "2026-07-25"

UNKNOWN = {
    "checked": "not published for this carrier here",
    "cabin": "—",
    "confidence": "unknown",
    "note": "Carrier isn't in the reference table — open its baggage page before paying.",
    "url": "https://www.google.com/search?q=checked+baggage+allowance+economy",
}

# checked_us   → allowance when the TICKET touches the USA (piece concept)
# checked_asia → allowance on an intra-Asia ticket (weight concept); a dict keys
#                on route for carriers that publish route-by-route numbers.
CARRIERS = {
    "turkish": {
        "name": "Turkish Airlines",
        "checked_us": "2 × 23 kg per person",
        "checked_asia": "1 × 23 kg (30 kg on some fares)",
        "cabin": "1 × 8 kg (55×40×23 cm)",
        "confidence": "verified",
        "note": ("US piece rule applies in both directions and to the onward "
                 "IST→DAC leg of the same ticket. Deep-promo/EcoFly fares can "
                 "differ — the fare page shows the real number."),
        "url": "https://www.turkishairlines.com/en-us/any-questions/baggage-information/usa-free-baggage-rules/",
    },
    "us-bangla": {
        "name": "US-Bangla Airlines",
        "checked_us": None,
        "checked_asia": {
            "DAC→SIN": "40 kg (max 2 pieces) per person",
            "SIN→DAC": "40 kg (max 2 pieces) per person",
            "DAC→BKK": "30 kg (max 2 pieces) per person",
            "DAC→KUL": "30 kg (max 2 pieces) per person",
            "_default": "20–30 kg depending on route — check the ticket",
        },
        "cabin": "7 kg (published per ticket)",
        "confidence": "verified",
        "note": "Dhaka→Singapore is one of their most generous routes: 40 kg in two bags.",
        "url": "https://usbair.com/free-baggage-allowence",
    },
    "singapore airlines": {
        "name": "Singapore Airlines",
        "checked_us": "2 × 23 kg per person",
        "checked_asia": "Economy Lite 25 kg · Standard 30 kg · Flexi 35 kg",
        "cabin": "1 × 7 kg (115 cm total)",
        "confidence": "verified",
        "note": "Allowance follows the fare brand — Lite is the cheap one you'll be quoted.",
        "url": "https://www.singaporeair.com/en_UK/us/travel-info/baggage/free-baggage-allowance/",
    },
    # The three "Thai <LCC>" carriers MUST sit before "thai" — _carrier_key is
    # a first-substring-match in insertion order, and "thai" would otherwise
    # credit Thai Lion / Thai Vietjet / Thai AirAsia with THAI Airways' full-
    # service allowance (they're big on the DAC/SIN⇄BKK routes).
    "thai lion": {
        "name": "Thai Lion Air", "checked_us": None,
        "checked_asia": "20 kg on most international routes (0 on some promos)",
        "cabin": "7 kg", "confidence": "varies",
        "note": "Low-cost carrier — confirm the fare actually includes the bag.",
        "url": "https://www.lionairthai.com/en/ThaiLionAir-Baggage-Allowance"},
    "thai vietjet": {
        "name": "Thai Vietjet", "checked_us": None,
        "checked_asia": "NONE on Eco fares — prepay 20 kg+ (Deluxe includes 20 kg)",
        "cabin": "7 kg", "confidence": "varies",
        "note": "Low-cost carrier: bags are an add-on on the cheap fares.",
        "url": "https://www.vietjetair.com/en/pages/checked-baggage-1638496498500"},
    "thai airasia": {
        "name": "Thai AirAsia", "checked_us": None,
        "checked_asia": "NONE included — prepay 20 kg+ online",
        "cabin": "7 kg total (2 items)", "confidence": "verified",
        "note": "AirAsia group: bags are an add-on and cost ~2× more at the airport.",
        "url": "https://support.airasia.com/s/article/baggage-allowance"},
    "thai": {
        "name": "THAI Airways",
        "checked_us": "2 × 23 kg per person",
        "checked_asia": "Economy Saver 23 kg · Flexi/Full 30 kg",
        "cabin": "1 × 7 kg",
        "confidence": "verified",
        "note": "Saver dropped from 25→23 kg in Apr 2025; excess is charged per piece since Mar 2026.",
        "url": "https://www.thaiairways.com/en-th/content/baggage/checked-baggage/",
    },
    "qatar": {
        "name": "Qatar Airways", "checked_us": "2 × 23 kg per person",
        "checked_asia": "25–35 kg depending on fare", "cabin": "1 × 7 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.qatarairways.com/en/baggage/allowance.html"},
    "emirates": {
        "name": "Emirates", "checked_us": "2 × 23 kg per person",
        "checked_asia": "25–35 kg depending on fare", "cabin": "1 × 7 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.emirates.com/us/english/before-you-fly/baggage/"},
    "etihad": {
        "name": "Etihad", "checked_us": "2 × 23 kg per person",
        "checked_asia": "25–35 kg depending on fare", "cabin": "1 × 7 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.etihad.com/en-us/fly-etihad/baggage"},
    "saudia": {
        "name": "Saudia", "checked_us": "2 × 23 kg per person",
        "checked_asia": "2 × 23 kg", "cabin": "1 × 7 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.saudia.com/before-flying/baggage/baggage-allowance"},
    "delta": {
        "name": "Delta", "checked_us": "1 × 23 kg (Main; 2nd bag charged on most Europe/Asia itineraries)",
        "checked_asia": None, "cabin": "1 bag + personal item",
        "confidence": "typical",
        "note": "Showed up as the Ticket ① winner 2026-08-01 (Delta + Air France codeshare) — the operating carrier's rule applies per leg; confirm at checkout.",
        "url": "https://www.delta.com/us/en/baggage/checked-baggage"},
    "united": {
        "name": "United", "checked_us": "1 × 23 kg (Economy; Basic has no free bag on some routes)",
        "checked_asia": None, "cabin": "1 bag + personal item", "confidence": "typical",
        "note": "", "url": "https://www.united.com/en/us/fly/baggage.html"},
    "american": {
        "name": "American Airlines", "checked_us": "1 × 23 kg (Main Cabin international)",
        "checked_asia": None, "cabin": "1 bag + personal item", "confidence": "typical",
        "note": "", "url": "https://www.aa.com/i18n/travel-info/baggage/checked-baggage-policy.jsp"},
    "air india": {
        "name": "Air India", "checked_us": "2 × 23 kg per person",
        "checked_asia": "25–30 kg", "cabin": "1 × 8 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.airindia.com/en-us/baggage-information/"},
    "lufthansa": {
        "name": "Lufthansa", "checked_us": "1 × 23 kg (Economy Classic)",
        "checked_asia": "1 × 23 kg", "cabin": "1 × 8 kg",
        "confidence": "typical",
        "note": "European carriers give ONE bag where Turkish/Gulf give two — the gap that makes a cheap fare expensive.",
        "url": "https://www.lufthansa.com/us/en/free-baggage-allowance"},
    "air france": {
        "name": "Air France", "checked_us": "1 × 23 kg (Economy Standard)",
        "checked_asia": "1 × 23 kg", "cabin": "1 × 12 kg total",
        "confidence": "typical",
        "note": "Light fares include NO checked bag — check the brand name at checkout.",
        "url": "https://wwws.airfrance.us/information/bagages/bagage-soute-taille-poids"},
    "klm": {
        "name": "KLM", "checked_us": "1 × 23 kg (Economy Standard)",
        "checked_asia": "1 × 23 kg", "cabin": "1 × 12 kg total",
        "confidence": "typical", "note": "Light fares include no checked bag.",
        "url": "https://www.klm.com/information/baggage/checked-baggage-allowance"},
    "british airways": {
        "name": "British Airways", "checked_us": "1 × 23 kg (Economy)",
        "checked_asia": "1 × 23 kg", "cabin": "1 × 23 kg cabin bag + personal",
        "confidence": "typical", "note": "Basic fares are hand-baggage only.",
        "url": "https://www.britishairways.com/en-us/information/baggage-essentials"},
    "malaysia": {
        "name": "Malaysia Airlines", "checked_us": "2 × 23 kg per person",
        "checked_asia": "30 kg (Basic fares less)", "cabin": "1 × 7 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.malaysiaairlines.com/us/en/plan/baggage-information.html"},
    "airasia": {
        "name": "AirAsia", "checked_us": None,
        "checked_asia": "NONE included — prepay 20 kg+ online",
        "cabin": "7 kg total (2 items)", "confidence": "verified",
        "note": "Low-cost carrier: bags are an add-on and cost ~2× more at the airport.",
        "url": "https://support.airasia.com/s/article/baggage-allowance"},
    "scoot": {
        "name": "Scoot", "checked_us": None,
        "checked_asia": "NONE on Fly fares — prepay 20 kg+",
        "cabin": "10 kg total (2 items)", "confidence": "verified",
        "note": "Low-cost carrier: bags are an add-on.",
        "url": "https://www.flyscoot.com/en/plan/booking-your-flight/baggage"},
    "jetstar": {
        "name": "Jetstar", "checked_us": None,
        "checked_asia": "NONE on Starter fares — prepay 20 kg+",
        "cabin": "7 kg total", "confidence": "verified",
        "note": "Low-cost carrier: bags are an add-on.",
        "url": "https://www.jetstar.com/au/en/help/articles/carry-on-baggage-restrictions"},
    "batik": {
        "name": "Batik Air", "checked_us": None,
        "checked_asia": "20 kg (varies by market/fare)", "cabin": "7 kg",
        "confidence": "varies", "note": "Allowance differs between Batik Air Malaysia and Indonesia — verify.",
        "url": "https://www.batikair.com/en-ID/Baggage"},
    "indigo": {
        "name": "IndiGo", "checked_us": None,
        "checked_asia": "20–30 kg international (varies)", "cabin": "1 × 7 kg",
        "confidence": "varies", "note": "",
        "url": "https://www.goindigo.in/information/baggage-allowance.html"},
    "garuda": {
        "name": "Garuda Indonesia", "checked_us": None,
        "checked_asia": "30 kg economy", "cabin": "1 × 7 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.garuda-indonesia.com/id/en/garuda-indonesia-experience/on-ground/baggage"},
    "biman": {
        "name": "Biman Bangladesh", "checked_us": None,
        "checked_asia": "30 kg (route-dependent)", "cabin": "1 × 7 kg",
        "confidence": "varies", "note": "",
        "url": "https://www.biman-airlines.com/baggage-information"},
    "srilankan": {
        "name": "SriLankan Airlines", "checked_us": None,
        "checked_asia": "30 kg economy", "cabin": "1 × 7 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.srilankan.com/en_uk/plan-and-book/baggage-information"},
    "cathay": {
        "name": "Cathay Pacific", "checked_us": "2 × 23 kg per person",
        "checked_asia": "20–30 kg by fare", "cabin": "1 × 7 kg",
        "confidence": "typical", "note": "",
        "url": "https://www.cathaypacific.com/cx/en_US/baggage/checked-baggage.html"},
}

# Ticket ① always starts in Boston, so every one of its legs is priced under the
# US piece rule; Ticket ② never touches the US and follows Asian weight rules.
US_TICKET, ASIA_TICKET = "us", "asia"


def _carrier_key(airline: str) -> str:
    a = (airline or "").lower()
    for key in CARRIERS:
        if key in a:
            return key
    return ""


def split_carriers(airline: str) -> list:
    """'Lufthansa and Turkish Airlines' → ['Lufthansa', 'Turkish Airlines'].
    Google returns multi-carrier itineraries as one string and the legs can
    carry DIFFERENT allowances — the single most common baggage surprise."""
    if not airline:
        return []
    parts, buf = [], (airline.replace(" and ", ",").replace("+", ",")
                      .replace("/", ","))
    for p in buf.split(","):
        p = p.strip()
        if p and p.lower() not in ("n/a",):
            parts.append(p)
    return parts


def for_carrier(airline: str, ticket_type: str, route: str = "") -> dict:
    """Allowance for ONE named carrier on one ticket type."""
    key = _carrier_key(airline)
    if not key:
        return dict(UNKNOWN, carrier=(airline or "unknown airline"),
                    url=("https://www.google.com/search?q=" +
                         (airline or "").replace(" ", "+") + "+checked+baggage+allowance+economy"))
    c = CARRIERS[key]
    allowance = c["checked_us"] if ticket_type == US_TICKET else c["checked_asia"]
    if isinstance(allowance, dict):                    # route-by-route carrier
        allowance = allowance.get(route) or allowance["_default"]
    if not allowance:                                  # e.g. an LCC on a US ticket
        allowance = c["checked_asia"] if ticket_type == US_TICKET else c["checked_us"]
        if isinstance(allowance, dict):
            allowance = allowance.get(route) or allowance["_default"]
    return {
        "carrier": c["name"],
        "checked": allowance or UNKNOWN["checked"],
        "cabin": c["cabin"],
        "note": c["note"],
        "url": c["url"],
        "confidence": c["confidence"],
    }


def for_leg(airline: str, ticket_type: str, route: str = "") -> dict:
    """Allowance for a leg, handling multi-carrier strings. Returns the first
    carrier's entry plus `others` for the rest, so the UI can show every rule
    that applies instead of averaging them into a comfortable lie."""
    carriers = split_carriers(airline)
    if not carriers:
        return dict(UNKNOWN, carrier="airline not shown", others=[], summary=UNKNOWN["checked"])
    first = for_carrier(carriers[0], ticket_type, route)
    first["others"] = [for_carrier(c, ticket_type, route) for c in carriers[1:]]
    # A two-airline option is only as good as its WORST leg — "US-Bangla 40 kg"
    # hides that the Singapore→Bali half on Jetstar carries no free bag at all.
    first["summary"] = " · ".join(
        f"{b['carrier']}: {b['checked']}" for b in [first] + first["others"]) \
        if first["others"] else first["checked"]
    return first


# Per-order Ticket ② routes + display names; the Bali-era entry keeps old
# history's best_detail rendering correctly.
CITY_NAMES = {"DAC": "Dhaka", "SIN": "Singapore", "BKK": "Bangkok",
              "DPS": "Bali", "BOS": "Boston", "IST": "Istanbul"}
_ORDER_T2 = {
    "BKK-first": (("DAC→BKK", "BKK→SIN"), "SIN→BOS"),
    "SIN-first": (("DAC→SIN", "SIN→BKK"), "BKK→BOS"),
    "bali-rev":  (("DAC→DPS", "DPS→SIN"), "SIN→BOS"),   # reversed benchmark
    None:        (("DAC→SIN", "SIN→DPS"), "DPS→BOS"),   # forward Bali
}


def _label(route: str) -> str:
    a, b = route.split("→")
    return f"{CITY_NAMES.get(a, a)} → {CITY_NAMES.get(b, b)}"


def annotate(main: dict) -> list:
    """Per-leg baggage rows for the main trip, in travel order.

    Ticket ① (BOS→IST→DAC + the return from the order's LAST city) is one
    purchase: one allowance across all three of its flights. Ticket ② is a
    separate purchase, and when it's sold as ONE multi-city ticket Google only
    names the FIRST leg's carrier — the second hop is then genuinely unknown
    to us and says so.
    """
    if not main:
        return []
    oj = main.get("openjaw") or {}
    t2 = main.get("sg_ticket")
    legs = {f.get("route"): f for f in (main.get("legs") or [])}
    t1_air = oj.get("airline", "")
    (r1, r2), ret_route = _ORDER_T2.get(main.get("order"), _ORDER_T2[None])

    rows = [
        {"route": "BOS→IST", "label": "Boston → Istanbul", "ticket": 1,
         **for_leg(t1_air, US_TICKET, "BOS→IST")},
        {"route": "IST→DAC", "label": "Istanbul → Dhaka", "ticket": 1,
         **for_leg(t1_air, US_TICKET, "IST→DAC")},
    ]

    if t2:
        rows.append({"route": r1, "label": _label(r1), "ticket": 2,
                     **for_leg(t2.get("airline", ""), ASIA_TICKET, r1)})
        dest = _label(r2).split(" → ")[1]
        rows.append({"route": r2, "label": _label(r2), "ticket": 2,
                     "carrier": "not shown on this ticket",
                     "checked": "unknown until booking",
                     "cabin": "—", "confidence": "unknown", "others": [],
                     "note": ("Google names only the first leg of a multi-city "
                              "ticket. If this hop is Scoot/Jetstar/AirAsia it "
                              f"may include NO free bag even though {_label(r1)} did."),
                     "url": ("https://www.google.com/search?q=" +
                             _label(r2).replace(" → ", "+to+").replace(" ", "+") +
                             "+baggage+allowance")})
    else:
        for route in (r1, r2):
            f = legs.get(route)
            rows.append({"route": route, "label": _label(route), "ticket": 2,
                         **for_leg((f or {}).get("airline", ""), ASIA_TICKET, route)})

    rows.append({"route": ret_route, "label": _label(ret_route), "ticket": 1,
                 **for_leg(t1_air, US_TICKET, ret_route)})
    return rows


def warnings(main: dict) -> list:
    """The structural traps that hold no matter which airline wins tonight."""
    if not main:
        return []
    (r1, r2), _ = _ORDER_T2.get(main.get("order"), _ORDER_T2[None])
    stop_city = _label(r1).split(" → ")[1]
    out = [
        "Two separate purchases → bags are NOT checked through. Collect them in "
        "Dhaka and re-check for Ticket ②; same again in "
        f"{stop_city} if the middle is two one-way tickets.",
        "Allowance is per person and the child with a seat normally gets the "
        "adult allowance — infants on a lap do not.",
    ]
    if main.get("sg_ticket"):
        out.append(f"Ticket ②'s {_label(r2).replace(' → ', '→')} carrier isn't "
                   "visible on Google's multi-city page — confirm that leg's "
                   "allowance before paying.")
    mixed = [r for r in annotate(main) if r.get("others")]
    if mixed:
        out.append("This itinerary mixes airlines on one ticket (" +
                   ", ".join(sorted({r["carrier"] for r in mixed})) +
                   " + partners) — the operating carrier's rule applies per leg.")
    return out
