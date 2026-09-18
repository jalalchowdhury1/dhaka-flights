#!/usr/bin/env python3
"""
Benchmark runner for comparing legacy vs Jev scraping engines.
Usage: bench.py --engine legacy|jev --set smoke|full [--repeat N]

- smoke = 3 searches: one-way DAC→SIN January 30, 2027; TICKET1_SIN_RETURN; TICKET2_SEARCHES entry 5
- full = all 30 searches
- Refuses to start between 23:30 and 07:30 local time
- Writes bench/<UTC-timestamp>-<engine>-<set>.json
- Prints summary table and median per-search seconds
"""
import os
import sys
import time
import json
import argparse
import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def _check_time_window():
    """Refuse to start outside 07:30-23:30 local time."""
    now = datetime.datetime.now().strftime("%H:%M")
    start = "07:30"
    end = "23:30"
    if now < start or now >= end:
        print(f"ERROR: Bench refused to start at {now} (window is {start}-{end})")
        print("Wait until business hours (07:30-23:30 local time)")
        sys.exit(1)


def run_bench(engine: str, search_set: str, repeat: int = 1, no_key: bool = False):
    """Run benchmark for the given engine and search set."""
    # Import the appropriate scraper module
    if engine == "jev":
        if no_key:
            os.environ.pop("AI_GATEWAY_API_KEY", None)
        import jev_client
        import scraper_jev as scraper
        started = jev_client.start().started       # same wiring as run_daily.py
        print(f"jev server: {'running' if started else 'NOT running (fallback picks only)'}")
    else:
        import scraper

    # Smoke search set - 3 key searches
    smoke_searches = [
        # One-way DAC→SIN January 30, 2027
        ("route", "DAC", "SIN", "January 30, 2027"),
        # TICKET1_SIN_RETURN one-way portion
        ("route", "BOS", "IST", "January 4, 2027"),
        ("route", "IST", "DAC", "January 7, 2027"),
        # TICKET2_SEARCHES entry 5 (BKK-first, 4 SIN nights)
        ("route", "DAC", "BKK", "January 28, 2027"),
        ("route", "BKK", "SIN", "February 2, 2027"),
    ]

    results = []
    all_search_results = []

    for rep in range(1, repeat + 1):
        print(f"\n=== Run {rep}/{repeat} (engine={engine}) ===")

        # Initialize DIAG
        scraper.DIAG = {"timeouts": 0, "blank_pages": 0, "aborted_early": False,
                       "deadline_skips": [], "last_stderr": "",
                       "jev_calls": 0, "jev_ms": 0, "jev_fallbacks": 0, "engine_fallbacks": 0,
                       "wait_timeouts": 0}

        run_start = time.monotonic()
        scraper.begin_run()

        run_data = {
            "run_number": rep,
            "searches": [],
            "total_seconds": 0,
            "deadline_skips": [],
            "jev_calls": 0,
            "jev_ms": 0,
            "jev_fallbacks": 0,
            "engine_fallbacks": 0,
            "wait_timeouts": 0,
        }

        if search_set == "full":
            # Full run: all 30 searches
            print("[tickets-1] BOS→IST + IST→DAC + SIN→BOS (Bangkok-first order)")
            tickets1 = scraper.scrape_tickets_all()
            for t in tickets1:
                if isinstance(t, dict) and t.get("route"):
                    run_data["searches"].append({
                        "type": "ticket1",
                        "route": t.get("route", ""),
                        "price": t.get("price_total", "N/A"),
                    })

            print("[tickets-2] Ticket ② multi-city (both orders)")
            sg_tickets = scraper.scrape_sg_tickets_all()
            for t in sg_tickets:
                if isinstance(t, dict) and t.get("route"):
                    run_data["searches"].append({
                        "type": "ticket2",
                        "route": t.get("route", ""),
                        "price": t.get("price_total", "N/A"),
                    })

            print("[one-ways] All one-way legs")
            flights = scraper.scrape_all()
            for f in flights:
                if isinstance(f, dict) and f.get("route"):
                    run_data["searches"].append({
                        "type": "oneway",
                        "route": f.get("route", ""),
                        "price": f.get("price_total", "N/A"),
                    })

            print("[bali-watch] Bali comparison")
            bali_t1, bali_fwd, bali_rev = scraper.scrape_bali_watch()
            for t in bali_t1:
                if isinstance(t, dict) and t.get("route"):
                    run_data["searches"].append({
                        "type": "bali",
                        "route": t.get("route", ""),
                        "price": t.get("price_total", "N/A"),
                    })

            scraper.end_session()
        elif search_set == "multi":
            # One real multi-city search (Ticket ① config 0), the nightly's main shape
            cfg = scraper.STOPOVER_SEARCHES[0]
            print(f"[{cfg['kind']}] {cfg['label']}")
            calls_before = scraper.DIAG.get("jev_calls", 0)
            t0 = time.time()
            options = scraper.scrape_stopover(cfg)
            elapsed = time.time() - t0
            prices = [o.get("price_total") for o in options if isinstance(o.get("price_total"), (int, float))]
            run_data["searches"].append({
                "type": "multicity",
                "legs": cfg["legs"],
                "seconds": round(elapsed, 2),
                "flights": len(options),
                "cheapest_price": min(prices, default="N/A"),
                "jev_calls": scraper.DIAG.get("jev_calls", 0) - calls_before,
            })
            print(f"  -> {len(options)} options, cheapest {min(prices, default='N/A')}, "
                  f"{elapsed:.1f}s, jev calls {scraper.DIAG.get('jev_calls', 0) - calls_before}")
        else:
            # Smoke run: just a few key searches
            import time as time_module

            for search_type, origin, dest, depart in smoke_searches[:3]:
                calls_before = scraper.DIAG.get("jev_calls", 0)
                t0 = time_module.time()
                results_here = scraper.scrape_route(origin, dest, depart)
                elapsed = time_module.time() - t0
                print(f"  -> {len(results_here)} flights, {elapsed:.1f}s, "
                      f"jev calls {scraper.DIAG.get('jev_calls', 0) - calls_before}, "
                      f"wait timeouts so far {scraper.DIAG.get('wait_timeouts', 0)}")

                fill_verified = False
                if results_here:
                    # Check fill verification: the tree should show the route
                    fill_verified = (origin in [r.get("route", "").split("→")[0] for r in results_here]
                                    or any(origin in str(r) for r in results_here))

                run_data["searches"].append({
                    "type": search_type,
                    "origin": origin,
                    "dest": dest,
                    "depart": depart,
                    "seconds": round(elapsed, 2),
                    "flights": len(results_here),
                    "cheapest_price": min((r.get("price_total") for r in results_here if isinstance(r.get("price_total"), (int, float))), default="N/A"),
                    "fill_verified": fill_verified,
                    "jev_calls": scraper.DIAG.get("jev_calls", 0) - calls_before,
                })

        run_data["total_seconds"] = round(time.monotonic() - run_start, 2)
        run_data["deadline_skips"] = scraper.DIAG.get("deadline_skips", [])
        run_data["jev_calls"] = scraper.DIAG.get("jev_calls", 0)
        run_data["jev_ms"] = scraper.DIAG.get("jev_ms", 0)
        run_data["jev_fallbacks"] = scraper.DIAG.get("jev_fallbacks", 0)
        run_data["engine_fallbacks"] = scraper.DIAG.get("engine_fallbacks", 0)
        run_data["wait_timeouts"] = scraper.DIAG.get("wait_timeouts", 0)
        run_data["timeouts"] = scraper.DIAG.get("timeouts", 0)
        run_data["blank_pages"] = scraper.DIAG.get("blank_pages", 0)

        all_search_results.append(run_data)

    if engine == "jev":
        jev_client.stop()
    return all_search_results


def main():
    parser = argparse.ArgumentParser(description="Benchmark scraping engines")
    parser.add_argument("--engine", required=True, choices=["legacy", "jev"],
                       help="Scraping engine to benchmark")
    parser.add_argument("--set", required=True, choices=["smoke", "multi", "full"],
                       help="Search set: 'smoke' (3 one-ways), 'multi' (1 multi-city), 'full' (30 searches)")
    parser.add_argument("--repeat", type=int, default=1,
                       help="Number of times to repeat the benchmark")
    parser.add_argument("--no-key", action="store_true",
                       help="Run the jev engine with AI_GATEWAY_API_KEY removed (gate G7)")
    args = parser.parse_args()

    _check_time_window()

    # Create bench directory if needed
    bench_dir = os.path.join(os.path.dirname(__file__), "bench")
    os.makedirs(bench_dir, exist_ok=True)

    # Run benchmark
    results = run_bench(args.engine, args.set, args.repeat, args.no_key)

    # Calculate median per-search time
    if args.set in ("smoke", "multi"):
        all_times = []
        for r in results:
            for s in r["searches"]:
                if "seconds" in s:
                    all_times.append(s["seconds"])
        median_time = sorted(all_times)[len(all_times)//2] if all_times else 0
    else:
        median_time = sum(r["total_seconds"] for r in results) / len(results) if results else 0

    # Save results
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H%M%SZ")
    filename = f"{timestamp}-{args.engine}-{args.set}.json"
    filepath = os.path.join(bench_dir, filename)
    with open(filepath, "w") as f:
        json.dump(results, f, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print(f"BENCHMARK RESULTS: {args.engine.upper()} engine, {args.set} set")
    print(f"{'='*60}")

    total_time = sum(r["total_seconds"] for r in results)
    total_jev_calls = sum(r.get("jev_calls", 0) for r in results)
    total_jev_ms = sum(r.get("jev_ms", 0) for r in results)
    total_jev_fallbacks = sum(r.get("jev_fallbacks", 0) for r in results)
    total_engine_fallbacks = sum(r.get("engine_fallbacks", 0) for r in results)
    total_timeouts = sum(r.get("wait_timeouts", 0) for r in results)

    print(f"\n{'Metric':<30} {'Value':>20}")
    print("-" * 50)
    print(f"{'Total time (seconds)':<30} {total_time:>20.2f}")
    print(f"{'Median per-search (seconds)':<30} {median_time:>20.2f}")
    print(f"{'Jev calls':<30} {total_jev_calls:>20}")
    print(f"{'Jev ms total':<30} {total_jev_ms:>20}")
    print(f"{'Jev fallbacks':<30} {total_jev_fallbacks:>20}")
    print(f"{'Engine fallbacks':<30} {total_engine_fallbacks:>20}")
    print(f"{'Wait timeouts':<30} {total_timeouts:>20}")

    if total_deadline_skips := sum(len(r.get("deadline_skips", [])) for r in results):
        print(f"{'Deadline skips':<30} {total_deadline_skips:>20}")

    print(f"\nResults saved to: {filepath}")

    return results


if __name__ == "__main__":
    main()