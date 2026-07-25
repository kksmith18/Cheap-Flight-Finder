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

## Adding routes

_(CLI for add/list/deactivate lands in a later build step — for now, watches
are edited directly or via the seed row in `db.py`.)_

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
- **Cron is fixed to UTC**, so the "6:00 AM Eastern" schedule drifts by an
  hour across DST transitions (5:00 AM Eastern during EST/winter).
