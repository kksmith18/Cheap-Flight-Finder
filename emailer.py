"""Sends all outbound email via Gmail SMTP.

Credentials come from GMAIL_ADDRESS / GMAIL_APP_PASSWORD environment
variables only — never hardcoded. All mail is self-addressed (sent to the
same Gmail account that sends it).
"""

import os
import smtplib
from datetime import date
from email.message import EmailMessage

from flights import FareResult

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def _send(subject: str, body: str) -> None:
    address = os.environ["GMAIL_ADDRESS"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = address
    msg.set_content(body)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(address, app_password)
        server.send_message(msg)


def _format_date_range(depart: date, return_: date) -> str:
    depart_str = f"{depart.strftime('%b')} {depart.day}"
    if depart.month == return_.month and depart.year == return_.year:
        return f"{depart_str}–{return_.day}"
    return f"{depart_str}–{return_.strftime('%b')} {return_.day}"


def _deal_subject(deals: list[FareResult]) -> str:
    if len(deals) == 1:
        d = deals[0]
        date_range = _format_date_range(date.fromisoformat(d.depart_date), date.fromisoformat(d.return_date))
        return f"✈️ DEAL: {d.origin}→{d.destination} ${d.price} roundtrip {date_range}"

    cheapest = min(deals, key=lambda d: d.price)
    return f"✈️ DEAL: {len(deals)} deals found (cheapest ${cheapest.price})"


def _deal_body(deals: list[FareResult]) -> str:
    lines = ["Confirm now on Google Flights before booking — fares change by the minute. This is not a locked price.\n"]
    for d in deals:
        date_range = _format_date_range(date.fromisoformat(d.depart_date), date.fromisoformat(d.return_date))
        lines.append(
            f"{d.origin} -> {d.destination}: ${d.price} on {d.airline}\n"
            f"  Dates: {date_range}  ({d.depart_date} to {d.return_date})\n"
            f"  Book: {d.google_flights_url}\n"
        )
    return "\n".join(lines)


def send_deal_email(deals: list[FareResult]) -> None:
    """Send one summary email covering all deals found this run. No-op if empty."""
    if not deals:
        return
    _send(_deal_subject(deals), _deal_body(deals))


def send_tracker_down_email(reasons: list[str]) -> None:
    """Alert that the scraper is presumed broken. reasons: canary/error-rate detail strings."""
    subject = "⚠️ TRACKER DOWN: " + "; ".join(reasons)
    body = (
        "The flight tracker detected a probable scraper breakage on this run:\n\n"
        + "\n".join(f"- {r}" for r in reasons)
        + "\n\nThis usually means Google changed their markup or is blocking requests. "
        "Check the run logs for details. You'll get one ✅ TRACKER RECOVERED email "
        "once the canary check passes again. No more than one of this email per day."
    )
    _send(subject, body)


def send_tracker_recovered_email() -> None:
    _send(
        "✅ TRACKER RECOVERED",
        "The canary check passed again — the scraper appears healthy.",
    )
