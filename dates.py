"""Generates candidate (depart, return) date pairs for trip patterns.

Sampled weekly (one departure per week per pattern), not every calendar day,
to keep query volume sane. Each pattern is a depart weekday + nights-away
pair, except `week` which is a fixed 7-night stay (the specific anchor
weekday doesn't matter for a full week, so it just uses Saturday).
"""

from datetime import date, timedelta

WINDOW_DAYS = 330


def _weekday_pairs(today: date, depart_weekday: int, nights: int, window_days: int) -> list[tuple[date, date]]:
    """One (depart, return) pair per week: next occurrence of depart_weekday, `nights` days later."""
    days_until = (depart_weekday - today.weekday()) % 7
    first_depart = today + timedelta(days=days_until)
    end = today + timedelta(days=window_days)

    pairs = []
    depart = first_depart
    while depart <= end:
        pairs.append((depart, depart + timedelta(days=nights)))
        depart += timedelta(days=7)
    return pairs


def fri_mon_pairs(today: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Friday depart, Monday return (3 nights)."""
    return _weekday_pairs(today, 4, 3, window_days)


def thu_mon_pairs(today: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Thursday depart, Monday return (4 nights)."""
    return _weekday_pairs(today, 3, 4, window_days)


def thu_sun_pairs(today: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Thursday depart, Sunday return (3 nights)."""
    return _weekday_pairs(today, 3, 3, window_days)


def fri_sun_pairs(today: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Friday depart, Sunday return (2 nights)."""
    return _weekday_pairs(today, 4, 2, window_days)


def sat_sun_pairs(today: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Saturday depart, Sunday return (1 night)."""
    return _weekday_pairs(today, 5, 1, window_days)


def week_pairs(today: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Any sampled day (Saturday anchor), 7 nights away."""
    return _weekday_pairs(today, 5, 7, window_days)
