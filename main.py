from scraper import scrape_all
from sheet_writer import write_to_sheet
from combo import best_combos


def main():
    print("Starting flight search: BOS → DAC → DPS → BOS (three one-way legs)")
    print("BOS→DAC Jan 4–6 · DAC→DPS Feb 1–3 · DPS→BOS Feb 5–7 · 2 adults + 1 child\n")

    flights = scrape_all()

    if not flights:
        print("No flights found. Google may have blocked the scraper.")
        print("Try running again — the browser will be visible so you can solve any CAPTCHA.")
        return

    # Sort by total price (cheapest first), put N/A at end
    def sort_key(f):
        p = f.get("price_total", "N/A")
        return p if isinstance(p, (int, float)) else float("inf")

    flights.sort(key=sort_key)

    print(f"\nFound {len(flights)} total flights. Writing to Google Sheet...")
    write_to_sheet(flights, tab_name="Google Flights")

    combos = best_combos(flights, top_n=3)
    if combos:
        print("\n--- Best valid trip combos (visa ≤29d, Bali ~5 nights, home ≤Feb 7) ---")
        for i, c in enumerate(combos, 1):
            print(f"{i}. ${c['total']:,} total · Dhaka {c['dhaka_days']}d · Bali {c['bali_nights']}n")
            for f in c["legs"]:
                print(f"     {f['route']} {f['depart']} · {f['airline']} · {f['stops']} · ${f['price_total']:,}")
    else:
        print("\nNo valid 3-leg combo found — check per-leg results in the sheet.")

    print("\n--- Top 5 Cheapest individual legs ---")
    for f in flights[:5]:
        print(f"  {f['route']} | {f['depart']} | {f['airline']} | {f['stops']} | ${f['price_total']}")

    print("\nDone! Open your Google Sheet to see all results.")


if __name__ == "__main__":
    main()
