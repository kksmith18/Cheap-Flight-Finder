"""SQLite persistence: watches, alert_state (dedup), health_state.

Single-file DB at tracker.db, plain sqlite3 - no ORM. All DB access is
isolated to this module's functions, so swapping the backend later (e.g. to
hosted Postgres if this ever needs multi-device/multi-user access) means
touching only this file.
"""

import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

DB_PATH = "tracker.db"


@dataclass
class Watch:
    id: int
    origin: str
    destination: str
    target_price: int
    trip_patterns: list[str]
    active: bool
    created_at: str


@dataclass
class HealthState:
    last_ok_run_at: str | None
    scraper_healthy: bool
    last_health_alert_at: str | None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with contextlib.closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                target_price INTEGER NOT NULL,
                trip_patterns TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_state (
                watch_id INTEGER NOT NULL,
                depart_date TEXT NOT NULL,
                return_date TEXT NOT NULL,
                last_alerted_price INTEGER NOT NULL,
                PRIMARY KEY (watch_id, depart_date, return_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS health_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_ok_run_at TEXT,
                scraper_healthy INTEGER NOT NULL DEFAULT 1,
                last_health_alert_at TEXT
            )
            """
        )
        conn.execute("INSERT OR IGNORE INTO health_state (id, scraper_healthy) VALUES (1, 1)")


def _row_to_watch(row: sqlite3.Row) -> Watch:
    return Watch(
        id=row["id"],
        origin=row["origin"],
        destination=row["destination"],
        target_price=row["target_price"],
        trip_patterns=row["trip_patterns"].split(","),
        active=bool(row["active"]),
        created_at=row["created_at"],
    )


def get_active_watches() -> list[Watch]:
    with contextlib.closing(_connect()) as conn, conn:
        rows = conn.execute("SELECT * FROM watches WHERE active = 1").fetchall()
    return [_row_to_watch(row) for row in rows]


def list_watches() -> list[Watch]:
    with contextlib.closing(_connect()) as conn, conn:
        rows = conn.execute("SELECT * FROM watches ORDER BY id").fetchall()
    return [_row_to_watch(row) for row in rows]


def add_watch(origin: str, destination: str, target_price: int, trip_patterns: list[str]) -> int:
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO watches (origin, destination, target_price, trip_patterns, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (origin, destination, target_price, ",".join(trip_patterns), datetime.now(timezone.utc).isoformat()),
        )
    return cursor.lastrowid


def deactivate_watch(watch_id: int) -> bool:
    """Returns True if a watch with that id existed and was deactivated."""
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.execute("UPDATE watches SET active = 0 WHERE id = ?", (watch_id,))
    return cursor.rowcount > 0


def get_last_alerted_price(watch_id: int, depart_date: str, return_date: str) -> int | None:
    with contextlib.closing(_connect()) as conn, conn:
        row = conn.execute(
            "SELECT last_alerted_price FROM alert_state "
            "WHERE watch_id = ? AND depart_date = ? AND return_date = ?",
            (watch_id, depart_date, return_date),
        ).fetchone()
    return row["last_alerted_price"] if row else None


def record_alert(watch_id: int, depart_date: str, return_date: str, price: int) -> None:
    with contextlib.closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO alert_state (watch_id, depart_date, return_date, last_alerted_price)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (watch_id, depart_date, return_date)
            DO UPDATE SET last_alerted_price = excluded.last_alerted_price
            """,
            (watch_id, depart_date, return_date, price),
        )


def get_health_state() -> HealthState:
    with contextlib.closing(_connect()) as conn, conn:
        row = conn.execute("SELECT * FROM health_state WHERE id = 1").fetchone()
    return HealthState(
        last_ok_run_at=row["last_ok_run_at"],
        scraper_healthy=bool(row["scraper_healthy"]),
        last_health_alert_at=row["last_health_alert_at"],
    )


def set_scraper_healthy(healthy: bool) -> None:
    with contextlib.closing(_connect()) as conn, conn:
        conn.execute("UPDATE health_state SET scraper_healthy = ? WHERE id = 1", (int(healthy),))


def set_last_ok_run_at(timestamp: str) -> None:
    with contextlib.closing(_connect()) as conn, conn:
        conn.execute("UPDATE health_state SET last_ok_run_at = ? WHERE id = 1", (timestamp,))


def set_last_health_alert_at(timestamp: str) -> None:
    with contextlib.closing(_connect()) as conn, conn:
        conn.execute("UPDATE health_state SET last_health_alert_at = ? WHERE id = 1", (timestamp,))
