"""Health monitoring: canary check, error-rate check, TRACKER DOWN/RECOVERED
alerts, and the Healthchecks.io dead-man's-switch ping.

Two independent failure modes this guards against:
  1. The job runs but the scraper is broken (Google changed markup / blocked
     us) -> canary + error-rate checks below, alerting via email.
  2. The job never runs at all (Actions disabled, crash on startup) -> the
     Healthchecks.io ping at the end of a healthy run; a missed ping means
     Healthchecks alerts independently of this script.
"""

import os
import urllib.request
from datetime import date, datetime, timedelta, timezone

import db
from emailer import send_tracker_down_email, send_tracker_recovered_email
from flights import get_cheapest_fare

CANARY_ORIGIN = "JFK"
CANARY_DESTINATION = "SFO"
CANARY_DEPART_OFFSET_DAYS = 21
CANARY_RETURN_OFFSET_DAYS = 24

# Below this success rate across the main scan, treat the run as broken
# rather than "this route just has no cheap flights right now". Only applied
# once enough queries ran to be a meaningful sample.
ERROR_RATE_THRESHOLD = 0.10
MIN_QUERIES_FOR_ERROR_RATE_CHECK = 5


def run_canary_check(today: date) -> tuple[bool, str]:
    depart = today + timedelta(days=CANARY_DEPART_OFFSET_DAYS)
    ret = today + timedelta(days=CANARY_RETURN_OFFSET_DAYS)
    try:
        fare = get_cheapest_fare(CANARY_ORIGIN, CANARY_DESTINATION, depart.isoformat(), ret.isoformat())
    except Exception as exc:
        return False, f"canary query raised: {exc}"
    if fare is None:
        return False, "canary returned 0 flights"
    return True, f"canary ok (${fare.price} on {fare.airline})"


def is_unhealthy(canary_ok: bool, attempted: int, successes: int) -> tuple[bool, list[str]]:
    """Decide breakage from the two independent signals; either alone is enough."""
    reasons = []
    if not canary_ok:
        reasons.append("canary check failed")
    if attempted >= MIN_QUERIES_FOR_ERROR_RATE_CHECK:
        success_rate = successes / attempted
        if success_rate < ERROR_RATE_THRESHOLD:
            reasons.append(f"main scan success rate collapsed ({success_rate:.0%}, {successes}/{attempted})")
    return bool(reasons), reasons


def handle_health_result(unhealthy: bool, reasons: list[str], canary_detail: str) -> None:
    """Update health_state and send TRACKER DOWN / RECOVERED emails per dedup rules."""
    state = db.get_health_state()
    now = datetime.now(timezone.utc)

    if unhealthy:
        already_alerted_today = (
            state.last_health_alert_at is not None
            and datetime.fromisoformat(state.last_health_alert_at).date() == now.date()
        )
        db.set_scraper_healthy(False)
        if not already_alerted_today:
            send_tracker_down_email([*reasons, canary_detail])
            db.set_last_health_alert_at(now.isoformat())
    else:
        if not state.scraper_healthy:
            send_tracker_recovered_email()
        db.set_scraper_healthy(True)
        db.set_last_ok_run_at(now.isoformat())


def ping_healthcheck() -> None:
    """Ping the Healthchecks.io dead-man's switch. Only call after a healthy run."""
    url = os.environ.get("HEALTHCHECK_URL")
    if not url:
        print("HEALTHCHECK_URL not set, skipping ping")
        return
    try:
        urllib.request.urlopen(url, timeout=10)
    except Exception as exc:
        print(f"Healthchecks ping failed: {exc}")
