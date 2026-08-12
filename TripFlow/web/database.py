from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "tripflow.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                destination TEXT,
                category TEXT,
                memo TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL,
                reservation_type TEXT NOT NULL,
                reservation_service TEXT NOT NULL DEFAULT 'その他',
                title TEXT NOT NULL,
                reservation_date TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                reservation_number TEXT,
                reservation_url TEXT,
                status TEXT NOT NULL,
                memo TEXT,
                check_in_date TEXT,
                check_out_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips (id) ON DELETE CASCADE
            )
            """
        )

        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(reservations)")
        }

        if "reservation_service" not in existing_columns:
            conn.execute(
                "ALTER TABLE reservations "
                "ADD COLUMN reservation_service TEXT NOT NULL DEFAULT 'その他'"
            )

        if "check_in_date" not in existing_columns:
            conn.execute("ALTER TABLE reservations ADD COLUMN check_in_date TEXT")

        if "check_out_date" not in existing_columns:
            conn.execute("ALTER TABLE reservations ADD COLUMN check_out_date TEXT")

        # 既存のホテル予約を安全に移行する。check_in_dateが未設定の行だけを
        # 対象にしているため、何度実行しても既存の値を上書きしない。
        # check_out_dateは推測できないため一切設定しない（NULLのまま）。
        conn.execute(
            """
            UPDATE reservations
            SET check_in_date = reservation_date
            WHERE reservation_type = 'ホテル' AND check_in_date IS NULL
            """
        )

        conn.commit()
    finally:
        conn.close()


def fetch_trips_in_range(range_start: date, range_end: date) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT * FROM trips
            WHERE start_date <= ? AND end_date >= ?
            ORDER BY start_date ASC
            """,
            (range_end.isoformat(), range_start.isoformat()),
        ).fetchall()
    finally:
        conn.close()


def fetch_trips() -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            "SELECT * FROM trips ORDER BY start_date ASC"
        ).fetchall()
    finally:
        conn.close()


def fetch_upcoming_trips(today: date, limit: int = 3) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT * FROM trips
            WHERE end_date >= ?
            ORDER BY start_date ASC
            LIMIT ?
            """,
            (today.isoformat(), limit),
        ).fetchall()
    finally:
        conn.close()


def fetch_trip(trip_id: int) -> sqlite3.Row | None:
    conn = get_connection()

    try:
        return conn.execute(
            "SELECT * FROM trips WHERE id = ?", (trip_id,)
        ).fetchone()
    finally:
        conn.close()


def update_trip(
    trip_id: int,
    name: str,
    start_date: date,
    end_date: date,
    destination: str,
    category: str,
    memo: str,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()

    try:
        conn.execute(
            """
            UPDATE trips
            SET name = ?, start_date = ?, end_date = ?, destination = ?,
                category = ?, memo = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                start_date.isoformat(),
                end_date.isoformat(),
                destination,
                category,
                memo,
                now,
                trip_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_trip(trip_id: int) -> None:
    conn = get_connection()

    try:
        conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        conn.commit()
    finally:
        conn.close()


def fetch_reservations_by_trip(trip_id: int) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT * FROM reservations
            WHERE trip_id = ?
            ORDER BY reservation_date ASC, id ASC
            """,
            (trip_id,),
        ).fetchall()
    finally:
        conn.close()


def fetch_reservation(reservation_id: int) -> sqlite3.Row | None:
    conn = get_connection()

    try:
        return conn.execute(
            "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        ).fetchone()
    finally:
        conn.close()


def update_reservation(
    reservation_id: int,
    reservation_type: str,
    reservation_service: str,
    title: str,
    reservation_date: date,
    amount: int,
    reservation_number: str,
    reservation_url: str,
    status: str,
    memo: str,
    check_in_date: date | None = None,
    check_out_date: date | None = None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()

    try:
        conn.execute(
            """
            UPDATE reservations
            SET reservation_type = ?, reservation_service = ?, title = ?,
                reservation_date = ?, amount = ?, reservation_number = ?,
                reservation_url = ?, status = ?, memo = ?,
                check_in_date = ?, check_out_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                reservation_type,
                reservation_service,
                title,
                reservation_date.isoformat(),
                amount,
                reservation_number,
                reservation_url,
                status,
                memo,
                check_in_date.isoformat() if check_in_date else None,
                check_out_date.isoformat() if check_out_date else None,
                now,
                reservation_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_reservation(reservation_id: int) -> None:
    conn = get_connection()

    try:
        conn.execute("DELETE FROM reservations WHERE id = ?", (reservation_id,))
        conn.commit()
    finally:
        conn.close()


def fetch_reservations_in_range(range_start: date, range_end: date) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT * FROM reservations
            WHERE
                (
                    reservation_type != 'ホテル'
                    AND reservation_date BETWEEN ? AND ?
                )
                OR
                (
                    reservation_type = 'ホテル'
                    AND check_in_date IS NOT NULL
                    AND check_in_date <= ?
                    AND (check_out_date IS NULL OR check_out_date >= ?)
                )
            ORDER BY reservation_date ASC, id ASC
            """,
            (
                range_start.isoformat(),
                range_end.isoformat(),
                range_end.isoformat(),
                range_start.isoformat(),
            ),
        ).fetchall()
    finally:
        conn.close()


def get_reservation_status(trip_id: int) -> dict:
    reservations = fetch_reservations_by_trip(trip_id)

    def _is_confirmed(reservation_type: str) -> bool:
        return any(
            reservation["reservation_type"] == reservation_type
            and reservation["status"] == "予約済み"
            for reservation in reservations
        )

    outbound = _is_confirmed("往路")
    hotel = _is_confirmed("ホテル")
    return_trip = _is_confirmed("復路")

    return {
        "outbound": outbound,
        "hotel": hotel,
        "return": return_trip,
        "complete": outbound and hotel and return_trip,
    }


def insert_reservation(
    trip_id: int,
    reservation_type: str,
    reservation_service: str,
    title: str,
    reservation_date: date,
    amount: int,
    reservation_number: str,
    reservation_url: str,
    status: str,
    memo: str,
    check_in_date: date | None = None,
    check_out_date: date | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            INSERT INTO reservations (
                trip_id, reservation_type, reservation_service, title,
                reservation_date, amount, reservation_number, reservation_url,
                status, memo, check_in_date, check_out_date,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trip_id,
                reservation_type,
                reservation_service,
                title,
                reservation_date.isoformat(),
                amount,
                reservation_number,
                reservation_url,
                status,
                memo,
                check_in_date.isoformat() if check_in_date else None,
                check_out_date.isoformat() if check_out_date else None,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def insert_trip(
    name: str,
    start_date: date,
    end_date: date,
    destination: str,
    category: str,
    memo: str,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            INSERT INTO trips (
                name, start_date, end_date, destination,
                category, memo, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                start_date.isoformat(),
                end_date.isoformat(),
                destination,
                category,
                memo,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()
