"""Daily scan loop. Loads watches from SQLite, alerts only on new lows."""

import random
import time
from datetime import date

from dotenv import load_dotenv

load_dotenv()

import db
import health
from dates import fri_mon_pairs
from emailer import send_deal_email
from flights import get_cheapest_fare

# Only fri_mon is implemented so far; thu_mon/thu_sun/week land in a later step.
PATTERN_GENERATORS = {"fri_mon": fri_mon_pairs}

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


def main() -> None:
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


if __name__ == "__main__":
    main()
