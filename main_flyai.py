from scraper_flyai import scrape_all
from sheet_writer import write_to_sheet

def main():
    print("Starting flight search via FlyAI (Fliggy): BOS → DAC and BOS → BKK")
    print(f"Depart: Jan 3–6, 2027  |  Return: Jan 25–28, 2027\n")

    flights = scrape_all()

    if not flights:
        print("No flights found.")
        return

    def sort_key(f):
        p = f.get("price_per_person", "N/A")
        return p if isinstance(p, (int, float)) else float("inf")

    flights.sort(key=sort_key)

    print(f"\nFound {len(flights)} total flights. Writing to Google Sheet...")
    write_to_sheet(flights)

    print("\n--- Top 5 Cheapest (USD) ---")
    for f in flights[:5]:
        print(f"  {f['route']} | {f['depart']} → {f['return_date']} | "
              f"{f['airline']} | {f['stops']} | ${f['price_per_person']} "
              f"(¥{f['price_cny']})")

    print("\nDone! Open your Google Sheet to see all results.")

if __name__ == "__main__":
    main()
