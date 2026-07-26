"""Daily scan loop and watch-management CLI.

Run with no arguments to perform the daily scan (what GitHub Actions calls).
Run with a subcommand (add/list/deactivate) to manage watches instead.
"""

import argparse
import random
import sys
import time
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

import db
import health
from dates import fri_mon_pairs
from emailer import send_deal_email
from flights import get_cheapest_fare

# Only fri_mon is implemented so far; thu_mon/thu_sun/week land in a later step.
PATTERN_GENERATORS = {"fri_mon": fri_mon_pairs}

# All four pattern names are valid to store on a watch even before they're
# implemented (see PATTERN_GENERATORS) — scan_watch skips unimplemented ones.
VALID_PATTERN_NAMES = {"fri_mon", "thu_mon", "thu_sun", "week"}

# Airlines don't publish schedules for the whole date window; once results go
# empty/failed this many weeks in a row for a pattern, assume we've walked
# past the booking horizon for that route and stop querying further-out dates.
BOOKING_HORIZON_STREAK = 2


def scan_watch(watch: db.Watch, today: date) -> tuple[list[tuple[db.Watch, object]], int, int, int]:
    """Scan one watch across its patterns.

    Returns (deals, attempted, failures, successes). deals is a list of
    (watch, FareResult) pairs that are at/under target AND a new low vs.
    alert_state. successes counts queries that returned >=1 flight, used by
    the health error-rate check.
    """
    deals = []
    attempted = 0
    failures = 0
    successes = 0

    for pattern in watch.trip_patterns:
        generator = PATTERN_GENERATORS.get(pattern)
        if generator is None:
            print(f"  pattern '{pattern}' not implemented yet, skipping")
            continue

        pairs = generator(today)
        consecutive_empty = 0
        for i, (depart, ret) in enumerate(pairs):
            attempted += 1
            depart_s, ret_s = depart.isoformat(), ret.isoformat()
            try:
                fare = get_cheapest_fare(watch.origin, watch.destination, depart_s, ret_s)
            except Exception as exc:
                failures += 1
                consecutive_empty += 1
                print(f"  {depart} -> {ret}: QUERY FAILED ({exc})")
            else:
                if fare is None:
                    consecutive_empty += 1
                    print(f"  {depart} -> {ret}: no flights found")
                else:
                    successes += 1
                    consecutive_empty = 0
                    note = ""
                    if fare.price <= watch.target_price:
                        last_price = db.get_last_alerted_price(watch.id, depart_s, ret_s)
                        if last_price is None or fare.price < last_price:
                            deals.append((watch, fare))
                            note = " <-- NEW LOW, alerting"
                        else:
                            note = f" <-- under target but already alerted at ${last_price}"
                    print(f"  {depart} -> {ret}: ${fare.price} on {fare.airline}{note}")

            if consecutive_empty >= BOOKING_HORIZON_STREAK:
                print(f"  Stopping '{pattern}' early: {consecutive_empty} consecutive empty/failed results.")
                break

            if i < len(pairs) - 1:
                time.sleep(random.uniform(1, 3))

    return deals, attempted, failures, successes


def run_scan() -> None:
    db.init_db()
    today = date.today()

    canary_ok, canary_detail = health.run_canary_check(today)
    print(f"Canary check ({health.CANARY_ORIGIN}->{health.CANARY_DESTINATION}): {canary_detail}\n")

    watches = db.get_active_watches()
    print(f"Scanning {len(watches)} active watch(es)\n")

    all_deals = []
    total_attempted = 0
    total_failures = 0
    total_successes = 0

    for watch in watches:
        print(f"{watch.origin} -> {watch.destination}, target ${watch.target_price}, patterns={watch.trip_patterns}")
        deals, attempted, failures, successes = scan_watch(watch, today)
        all_deals.extend(deals)
        total_attempted += attempted
        total_failures += failures
        total_successes += successes
        print()

    print(f"{total_attempted} queries attempted, {total_failures} failed, {len(all_deals)} new-low deal(s)")

    if all_deals:
        send_deal_email([fare for _, fare in all_deals])
        for watch, fare in all_deals:
            db.record_alert(watch.id, fare.depart_date, fare.return_date, fare.price)
        print(f"Sent deal email for {len(all_deals)} deal(s); alert_state updated.")

    unhealthy, reasons = health.is_unhealthy(canary_ok, total_attempted, total_successes)
    health.handle_health_result(unhealthy, reasons, canary_detail)

    if unhealthy:
        print(f"Run flagged UNHEALTHY: {reasons}. Skipping Healthchecks ping.")
    else:
        print("Run healthy.")
        health.ping_healthcheck()


def _is_iata_code(code: str) -> bool:
    return len(code) == 3 and code.isalpha()


def cmd_add(args: argparse.Namespace) -> None:
    origin = args.origin.upper()
    destination = args.destination.upper()

    if not _is_iata_code(origin) or not _is_iata_code(destination):
        print(f"Error: origin/destination must be 3-letter IATA codes, got '{args.origin}' / '{args.destination}'")
        sys.exit(1)

    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]
    unknown = [p for p in patterns if p not in VALID_PATTERN_NAMES]
    if unknown:
        print(f"Error: unknown trip pattern(s) {unknown}. Valid patterns: {sorted(VALID_PATTERN_NAMES)}")
        sys.exit(1)

    not_yet_implemented = [p for p in patterns if p not in PATTERN_GENERATORS]
    if not_yet_implemented:
        print(f"Note: pattern(s) {not_yet_implemented} aren't implemented yet and will be skipped until they land.")

    # Validate the route resolves to real flights before storing it, on a
    # near-term date pair so we don't wait weeks out for the check.
    depart = date.today() + timedelta(days=14)
    ret = depart + timedelta(days=3)
    print(f"Validating {origin} -> {destination} ({depart} to {ret})...")
    try:
        fare = get_cheapest_fare(origin, destination, depart.isoformat(), ret.isoformat())
    except Exception as exc:
        print(f"Error: validation search failed ({exc}). Not adding this route.")
        sys.exit(1)
    if fare is None:
        print(f"Error: no flights found for {origin} -> {destination}. Check the IATA codes. Not adding this route.")
        sys.exit(1)

    db.init_db()
    watch_id = db.add_watch(origin, destination, args.target_price, patterns)
    print(
        f"Added watch #{watch_id}: {origin} -> {destination}, target ${args.target_price}, "
        f"patterns={patterns} (validated ${fare.price} on {fare.airline})"
    )


def cmd_list(args: argparse.Namespace) -> None:
    db.init_db()
    watches = db.list_watches()
    if not watches:
        print("No watches yet. Add one with: python tracker.py add ORIGIN DEST TARGET_PRICE [patterns]")
        return
    for w in watches:
        status = "active" if w.active else "inactive"
        print(f"#{w.id}  {w.origin} -> {w.destination}  target ${w.target_price}  patterns={','.join(w.trip_patterns)}  [{status}]")


def cmd_deactivate(args: argparse.Namespace) -> None:
    db.init_db()
    if db.deactivate_watch(args.id):
        print(f"Deactivated watch #{args.id}.")
    else:
        print(f"Error: no watch with id {args.id}.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="tracker.py", description="Flight price tracker")
    subparsers = parser.add_subparsers(dest="command")

    p_add = subparsers.add_parser("add", help="Add a new watch (validates the route before saving)")
    p_add.add_argument("origin", help="Origin IATA code, e.g. JFK")
    p_add.add_argument("destination", help="Destination IATA code, e.g. ROC")
    p_add.add_argument("target_price", type=int, help="Alert when roundtrip price is at or below this (USD)")
    p_add.add_argument(
        "patterns", nargs="?", default="fri_mon", help="Comma-separated trip patterns (default: fri_mon)"
    )
    p_add.set_defaults(func=cmd_add)

    p_list = subparsers.add_parser("list", help="List all watches")
    p_list.set_defaults(func=cmd_list)

    p_deactivate = subparsers.add_parser("deactivate", help="Deactivate a watch by id")
    p_deactivate.add_argument("id", type=int)
    p_deactivate.set_defaults(func=cmd_deactivate)

    args = parser.parse_args()
    if args.command is None:
        run_scan()
    else:
        args.func(args)


if __name__ == "__main__":
    main()
