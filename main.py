from scraper import scrape_all
from sheet_writer import write_to_sheet

def main():
    print("Starting flight search: BOS → DAC and BOS → BKK")
    print("Dates: Jan 3, 2027 → Jan 28, 2027 | 3 adults\n")

    flights = scrape_all()

    if not flights:
        print("No flights found. Google may have blocked the scraper.")
        print("Try running again — the browser will be visible so you can solve any CAPTCHA.")
        return

    # Sort by price per person (cheapest first), put N/A at end
    def sort_key(f):
        p = f.get("price_per_person", "N/A")
        return p if isinstance(p, (int, float)) else float("inf")

    flights.sort(key=sort_key)

    print(f"\nFound {len(flights)} total flights. Writing to Google Sheet...")
    write_to_sheet(flights)

    # Print terminal summary
    print("\n--- Top 5 Cheapest ---")
    for f in flights[:5]:
        p = f["price_per_person"]
        total = p * 3 if isinstance(p, (int, float)) else "N/A"
        print(f"  {f['route']} | {f['airline']} | {f['stops']} | "
              f"${p}/person | ${total} total | Baggage: {f['baggage']}")

    print("\nDone! Open your Google Sheet to see all results.")

if __name__ == "__main__":
    main()
