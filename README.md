# Flight Price Tracker

Personal, self-hosted flight price tracker. Scans saved routes daily across a
rolling ~330-day window using [fast-flights](https://github.com/AWeirdDev/fast-flights)
(a live Google Flights scraper — no API key, widest airline coverage) and
emails a deal alert when a fare drops to or below your target price.

## How it works

- **Watches** (route + target price + trip patterns) are stored in `tracker.db` (SQLite).
- Once a day, GitHub Actions runs `tracker.py`, which scans every active watch,
  emails a `✈️ DEAL:` summary for any new price low at/under target, and pings
  [Healthchecks.io](https://healthchecks.io) on success.
- A canary check (JFK→SFO) runs before the main scan. If it fails, or the
  main scan's success rate collapses, the run is flagged unhealthy: you get
  one `⚠️ TRACKER DOWN:` email per day, a `✅ TRACKER RECOVERED` email once
  it's fixed, and the Healthchecks ping is withheld so the external monitor
  also notices.

Two independent safety nets, because "scraper broken" and "no cheap flights"
both look like silence otherwise:
1. **Scraper breakage** (Google changed markup / blocked us) → canary +
   error-rate check → email alert.
2. **Job never runs at all** (Actions disabled, crash before it starts) →
   Healthchecks.io pings you back when the expected ping doesn't arrive.

## Setup

### 1. Gmail App Password

Deal/health emails send via Gmail SMTP using an **App Password**, not your
real password (App Passwords require 2-Step Verification to be enabled):

1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password (name it anything, e.g. "flight-tracker") and copy
   the 16-character code.

### 2. Healthchecks.io

1. Sign up free at https://healthchecks.io
2. Create a new check with a schedule matching the cron below (daily,
   ~10:00 UTC), with a reasonable grace period (e.g. a few hours).
3. Copy its ping URL (`https://hc-ping.com/<uuid>`).

### 3. Local `.env`

Copy `.env.example` to `.env` and fill in:

```
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=your16charapppassword
HEALTHCHECK_URL=https://hc-ping.com/your-uuid-here
```

`.env` is gitignored and only used for local runs — GitHub Actions uses repo
secrets instead (below).

### 4. GitHub Actions secrets

In the repo: **Settings → Secrets and variables → Actions → New repository
secret**, add:

- `GMAIL_ADDRESS`
- `GMAIL_APP_PASSWORD`
- `HEALTHCHECK_URL`

### 5. Enable Actions write permission

The workflow commits `tracker.db` back to the repo after each run so alert
history/dedup state persists between runs (simplest option — no external
cache needed). Under **Settings → Actions → General → Workflow permissions**,
select **Read and write permissions**, or the commit/push step will fail
with a permissions error.

## Managing routes

```
python tracker.py add JFK ROC 100                        # add a watch, defaults to fri_mon pattern
python tracker.py add JFK SFO 230 thu_sun,fri_mon,fri_sun # or specify explicitly (comma-separated for multiple)
python tracker.py list                                   # show all watches, active and inactive
python tracker.py deactivate 2                            # stop scanning a watch by its id
```

`add` runs one validation search on a near-term date before saving — if the
IATA codes don't resolve or return no flights, it's rejected instead of
silently storing a dead route.

Available trip patterns (comma-separated, any combination per watch):

| Pattern | Shape | Nights |
|---|---|---|
| `fri_mon` | Friday depart, Monday return | 3 |
| `thu_mon` | Thursday depart, Monday return | 4 |
| `thu_sun` | Thursday depart, Sunday return | 3 |
| `fri_sun` | Friday depart, Sunday return | 2 |
| `sat_sun` | Saturday depart, Sunday return | 1 |
| `week` | Any day depart, 7 nights away | 7 |

Each pattern samples one departure per week over the ~330-day window, so
adding patterns multiplies query volume per watch (~47 queries/pattern/year).
The scan logs a warning if a run's planned total creeps past ~500 queries.

Since watches aren't unique per route, you can track the same city pair
multiple times with different patterns and target prices — e.g. a lower bar
for a long weekend and a separate, pricier bar for a full week trip.

## Running locally

```
pip install -r requirements.txt
python tracker.py
```

## Known caveats

- **Southwest never appears.** Google Flights doesn't index Southwest fares,
  so Southwest-only deals will never be caught by this tool.
- **GitHub auto-disables scheduled workflows after ~60 days of repo
  inactivity.** Push any commit (or manually re-enable the workflow under the
  Actions tab) to reset the clock. This is exactly the kind of silent failure
  the Healthchecks.io ping is meant to catch.
- **Prices are a snapshot, not a lock.** Fares change by the minute — always
  confirm on Google Flights before booking.
- **"Separate tickets booked together" fares aren't captured.** Google
  Flights sometimes shows a cheaper price by stitching two independent
  one-way tickets into a round trip. Those aren't real round-trip fares —
  the two legs are unrelated reservations, so a delay on one leg gives you
  no rebooking protection on the other. This tracker only reports genuine
  single round-trip fares, so it may look slightly higher than the very
  cheapest number shown on Google Flights.
- **Cron is fixed to UTC**, so the "6:00 AM Eastern" schedule drifts by an
  hour across DST transitions (5:00 AM Eastern during EST/winter).
