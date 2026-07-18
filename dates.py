"""Generates candidate (depart, return) date pairs for trip patterns.

Sampled weekly (one departure per week per pattern), not every calendar day,
to keep query volume sane. Only `fri_mon` is implemented for now; the rest
(thu_mon, thu_sun, week) are added in a later build step.
"""

from datetime import date, timedelta

WINDOW_DAYS = 330


def fri_mon_pairs(today: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """One Friday-depart / Monday-return pair per week over the window."""
    days_until_friday = (4 - today.weekday()) % 7  # Monday=0 ... Friday=4
    first_friday = today + timedelta(days=days_until_friday)
    end = today + timedelta(days=window_days)

    pairs = []
    depart = first_friday
    while depart <= end:
        pairs.append((depart, depart + timedelta(days=3)))
        depart += timedelta(days=7)
    return pairs
