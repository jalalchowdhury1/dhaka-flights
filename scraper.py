import re
import time
from typing import Union
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

DEPART_DATE = "2027-01-03"
RETURN_DATE = "2027-01-28"
ADULTS = 3
MAX_RESULTS = 10


def build_google_flights_url(origin: str, dest: str, depart: str, return_date: str, adults: int) -> str:
    return (
        f"https://www.google.com/travel/flights?"
        f"hl=en&curr=USD"
        f"#flt={origin}.{dest}.{depart}*{dest}.{origin}.{return_date}"
        f";c:USD;e:1;sd:1;t:f;tt:o;pax:{adults}"
    )


def parse_price(raw: str) -> Union[int, str]:
    if not raw:
        return "N/A"
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else "N/A"


def _safe_text(el, selector: str, default: str = "N/A") -> str:
    try:
        node = el.query_selector(selector)
        return node.inner_text().strip() if node else default
    except Exception:
        return default


def scrape_route(origin: str, dest: str, page) -> list:
    url = build_google_flights_url(origin, dest, DEPART_DATE, RETURN_DATE, ADULTS)
    results = []
    try:
        page.goto(url, timeout=30000)
        # Wait for flight list items to appear
        page.wait_for_selector('[jsname="IWWDBc"]', timeout=20000)
        time.sleep(3)  # allow dynamic content to fully render
        cards = page.query_selector_all('[jsname="IWWDBc"]')[:MAX_RESULTS]
        for card in cards:
            airline = _safe_text(card, '.sSHqwe')
            price_raw = _safe_text(card, 'span[aria-label*="$"]', "")
            stops = _safe_text(card, '.VG3hNb')
            duration = _safe_text(card, '.gvkrdb')
            # Try to get baggage info by expanding the card
            baggage = "N/A"
            try:
                card.click()
                page.wait_for_selector('[jsname="TszEd"]', timeout=5000)
                bag_el = page.query_selector('[jsname="TszEd"]')
                if bag_el:
                    baggage = bag_el.inner_text().strip()
                card.click()
                time.sleep(0.5)
            except Exception:
                pass

            price = parse_price(price_raw)
            results.append({
                "route": f"{origin}→{dest}",
                "depart": "Jan 3, 2027",
                "return_date": "Jan 28, 2027",
                "airline": airline,
                "stops": stops,
                "duration": duration,
                "price_per_person": price,
                "baggage": baggage,
                "link": url,
            })
    except PlaywrightTimeout:
        print(f"Timeout scraping {origin}→{dest}. Partial results: {len(results)}")
    except Exception as e:
        print(f"Error scraping {origin}→{dest}: {e}")
    return results


def scrape_all() -> list:
    all_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()
        print("Scraping BOS → DAC...")
        all_results += scrape_route("BOS", "DAC", page)
        print(f"  Found {len([r for r in all_results if 'DAC' in r['route']])} results")
        print("Scraping BOS → BKK...")
        all_results += scrape_route("BOS", "BKK", page)
        print(f"  Found {len([r for r in all_results if 'BKK' in r['route']])} results")
        browser.close()
    return all_results
