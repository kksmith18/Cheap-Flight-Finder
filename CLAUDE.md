Flight Price Tracker — Full Build Brief for Claude Code

What we're building and why

I want a personal, self-hosted flight price tracker. I save routes (any origin → destination)
each with a target price. Once a day, an automated job scans each route's roundtrip fares across
a rolling ~11-month window and emails me when a fare drops to or below my target — with the dates,
price, airline, and a Google Flights link so I can confirm and book. It must ALSO alert me if the
scraper itself breaks, so silent failures never look like "no deals this week."

Context on decisions already made (do not relitigate these):


There is no official Google Flights API (QPX Express shut down in 2018), and the Amadeus
Self-Service API was decommissioned in July 2026 — so the classic free-API path is dead.
We chose the fast-flights Python library (free, no API key) because it reads live Google
Flights results, which has the widest airline coverage — important because cheap fares on thin
routes often come from smaller carriers. It's a scraper, so its failure mode is breakage/downtime
(errors, empty results), never fabricated prices. That's why health monitoring is a first-class
requirement, not an afterthought.
Skipped by design: average-price display (I set a flat target number myself), and booking
integration (the email just points me to Google Flights).
Known coverage gap: Southwest never appears on Google Flights and won't be tracked.
The data source must be swappable (Duffel or SerpApi later) if coverage or reliability
disappoints — so isolate it behind one function.


This is a personal tool. Favor simple, boring, reliable choices. Do NOT over-build.

Tech stack (don't substitute without asking)


Language: Python 3 (single small project; standard library + minimal deps).
Flight data: fast-flights library. Wrap ALL usage behind one function:
get_cheapest_fare(origin, dest, depart_date, return_date) -> FareResult | None
where FareResult has: price (int, USD total roundtrip), airline (str), and enough info to build
a Google Flights link for that exact search. A future provider swap must touch only this module.
Database: SQLite, single file (tracker.db). No external DB, no ORM required (plain sqlite3 is fine).
Email: smtplib with a Gmail App Password. Credentials from environment variables only.
Scheduling: GitHub Actions scheduled workflow (daily cron). Secrets via Actions Secrets.
External uptime net: Healthchecks.io (free) — script pings a URL at the end of a fully
successful run; Healthchecks emails me if the ping doesn't arrive on schedule.


Data model (SQLite)


watches: id, origin (IATA, e.g. "JFK"), destination (IATA), target_price (int USD),
trip_patterns (which patterns apply — store as JSON list or comma string), active (bool), created_at.
alert_state: watch_id, depart_date, return_date, last_alerted_price.
Purpose: dedup deal emails — only alert on NEW LOWS.
health_state: single row — last_ok_run_at, scraper_healthy (bool), last_health_alert_at.
Purpose: dedup health alerts and enable recovery emails.


Trip patterns

Each pattern = a (departure weekday → return weekday) pair or fixed nights:


fri_mon  (Friday depart, Monday return)
thu_mon
thu_sun
week     (depart any sampled day, return +7 nights)


All four must be implemented and toggleable per watch, but only fri_mon is enabled during
initial build (see build order). Others turn on at step 7.

Daily scan logic


Load all active watches.
For each watch, generate candidate (depart, return) date pairs from its enabled trip patterns
across today → today + 330 days. Sample weekly — one departure per week per pattern —
NOT every calendar day. (Goal: catch big price dips, not exhaustively enumerate; keeps volume sane.)
Query each pair via get_cheapest_fare(...). Insert a randomized 1–3 second delay between
requests to stay polite and avoid rate-limiting. Wrap each call in try/except; one failed pair
must never kill the run — log it and continue, but COUNT failures (used by health check below).
A fare ≤ the watch's target is a candidate deal → apply dedup rules below.


Rough volume sanity check: 1 route × 1 pattern × ~47 weeks ≈ 47 queries/run. Even several routes
with all patterns stays in the low hundreds/day. If a config change would push a run past ~500
queries, warn in the logs.

Deal alert rules (anti-spam)


Email ONLY when fare ≤ target AND it's a new low for that (watch, depart, return) — i.e. strictly
lower than last_alerted_price, or that date pair has never been alerted.
Update alert_state immediately after a successful send.
One email per deal is fine; if multiple deals fire in one run, batching them into one summary
email is acceptable and preferred.
Deal email must include: route, depart + return dates, total price, airline, and a Google Flights
URL prefilled for that exact origin/destination/dates.
Wording must convey "confirm now — fares change by the minute," never imply the price is locked.
Subject prefix for deal emails: ✈️ DEAL: (e.g. ✈️ DEAL: JFK→ROC $87 roundtrip Oct 9–12).


Health monitoring (CRITICAL FEATURE — two separate failure modes)

The trap this solves: "scraper broken" and "no cheap flights" both produce zero deal emails.
Without explicit health checks, a breakage is invisible for weeks.

Failure mode 1 — job runs, but the scraper is broken (Google changed markup / blocked us):


Canary check: every run, before the main scan, query the canary route — JFK → SFO,
roundtrip, departing ~21 days from today, returning ~24 days from today. This route always has
many flights. If the canary returns 0 flights or raises, the scraper is presumed broken.
Error-rate check: across the main scan, track what fraction of queries returned ≥1 flight.
If nearly all queries come back empty/erroring on a run (say, <10% success when the canary also
looks shaky), treat as breakage.
On breakage: send a health alert email with subject prefix ⚠️ TRACKER DOWN: describing what
failed (canary empty vs. error rate collapse) and the exception text if any.
Dedup: at most ONE health alert per day (health_state.last_health_alert_at). When the canary
passes again after a failure, send ONE recovery email (✅ TRACKER RECOVERED).
If the canary fails, still ATTEMPT the main scan (partial data beats none) but flag the run
as unhealthy and do NOT ping Healthchecks (see below), so the external net also notices.


Failure mode 2 — job never runs at all (Actions disabled, crash on startup):


The script pings the Healthchecks.io URL (from env var HEALTHCHECK_URL) ONLY at the end of a
fully successful, healthy run. Missed/withheld ping → Healthchecks emails me independently.
This also catches GitHub's auto-disabling of scheduled workflows after ~60 days of repo
inactivity. Note this caveat in the README.


Route input validation

When a watch is added (CLI command for now — e.g. python tracker.py add JFK ROC 100), run one
validation search on a near-term date. If the IATA codes don't resolve or return nothing, reject
with a clear error instead of silently storing a dead route.

Build order — do these IN SEQUENCE, each working before the next


Core loop, no DB, no email. Hardcode one route (JFK→ROC, target $100) + fri_mon.
Generate weekly-sampled date pairs over 330 days, query fast-flights, print cheapest per pair.
STOP HERE and show me sample output so I can sanity-check the numbers before continuing.
Deal email. Send via Gmail SMTP when fare ≤ target. Dates, price, airline, GF link, ✈️ DEAL: subject.
SQLite + dedup. Create the three tables. Move route config into watches. Enforce new-low-only alerts.
Health monitoring. JFK→SFO canary + error-rate check → ⚠️ TRACKER DOWN: email (deduped daily)

recovery email + Healthchecks ping on success only.



GitHub Actions cron. Daily run (~6:00 AM Eastern). Workflow YAML + secrets:
GMAIL_ADDRESS, GMAIL_APP_PASSWORD, HEALTHCHECK_URL. The SQLite file must persist between
runs — commit tracker.db back to the repo from the workflow (simplest) or use an Actions cache;
pick one, implement it, and document the choice.
Multi-route. CLI to add/list/deactivate watches, with validation. Confirm scan loops over all watches.
Remaining trip patterns. Enable thu_mon, thu_sun, week as per-watch options. Re-check volume.
(Later — do NOT build yet) Web UI. Thin form over watches. Only after 1–7 are solid.


Guardrails


NO web UI, NO average-price feature, NO booking integration in this phase.
All fast-flights usage stays behind the single get_cheapest_fare module boundary.
Never hardcode credentials; env vars / Actions Secrets only. Include a .env.example.
Keep per-request delays; never parallelize scraper calls.
Log every run to stdout (visible in Actions logs): counts of queries, successes, deals, failures.
Write a short README covering: setup, adding a Gmail App Password, Healthchecks setup,
adding routes, and the known caveats (Southwest gap, Actions 60-day auto-disable, prices-go-stale).


Config to fill in (I'll provide at setup)


GMAIL_ADDRESS, GMAIL_APP_PASSWORD (env)
HEALTHCHECK_URL (env)
Canary: JFK→SFO (hardcoded constant is fine)
First watch: JFK→ROC, target $100, fri_mon