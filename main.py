"""Manual run: scrape the tracked trip, write the Sheet, print a summary.
No Telegram, no publish, no git push — safe to run any time.
The full nightly pipeline is run_daily.py.
"""
from scraper import scrape_all, scrape_tickets_all, scrape_sg_tickets_all
from sheet_writer import write_to_sheet, multicity_as_rows
from combo import main_trip, ticket2_options


def main():
    print("Trip: BOS → Istanbul 2n → Dhaka → Bangkok 5n + Singapore 2n → BOS "
          "(2 adults + 1 child, either order — cheaper wins)")
    print("Ticket ① BOS→IST + IST→DAC + {SIN|BKK}→BOS · "
          "Ticket ② DAC→{BKK→SIN | SIN→BKK}\n")

    tickets1 = scrape_tickets_all()
    sg_tickets = scrape_sg_tickets_all()
    flights = scrape_all()
    from scraper import end_session
    end_session()                             # one browser session per run

    if not (tickets1 or sg_tickets or flights):
        print("Nothing scraped. Check the browse daemon (see AGENTS.md §5.2).")
        return

    def sort_key(f):
        p = f.get("price_total", "N/A")
        return p if isinstance(p, (int, float)) else float("inf")

    flights.sort(key=sort_key)
    write_to_sheet(
        multicity_as_rows(tickets1, "① BOS→IST→DAC + return")
        + multicity_as_rows(sg_tickets, "② Dhaka→BKK/SIN middle")
        + flights,
        tab_name="Google Flights")

    trip = main_trip(flights, tickets1, sg_tickets)
    if not trip:
        print("\nNo valid trip built — check the pairing rules in combo.py.")
        return

    print(f"\n--- THE TRIP: ${trip['total']:,} total · {trip.get('order_label')} ---")
    print(f"Istanbul {trip.get('ist_nights')}n · Dhaka {trip['dhaka_days']}d · "
          f"Singapore {trip.get('sg_nights')}n · Bangkok {trip['bkk_nights']}n · "
          f"home {trip['home']}")
    if trip.get("openjaw"):
        oj = trip["openjaw"]
        print(f"  ① {oj['airline']} · ${oj['price_total']:,}")
    if trip.get("sg_ticket"):
        t = trip["sg_ticket"]
        print(f"  ② {t['airline']} · ${t['price_total']:,}")
    for f in trip.get("legs", []):
        print(f"  ② {f['route']} {f['depart']} · {f['airline']} · ${f['price_total']:,}")

    alts = [o for o in ticket2_options(flights, sg_tickets, trip) if not o.get("chosen")]
    if alts:
        print("\n--- Ticket ② alternatives (same dates) ---")
        for o in alts[:6]:
            d = o.get("delta")
            gap = "same" if not d else (f"+${d:,}" if d > 0 else f"-${-d:,}")
            print(f"  {gap:>8}  {o['airline']} ({o['kind']}) ${o['price']:,}")


if __name__ == "__main__":
    main()
