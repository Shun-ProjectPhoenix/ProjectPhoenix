from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "tripflow.db"

# Web v0.2以前（ユーザー概念が無かった時代）のデータを引き継ぐための
# プレースホルダーユーザー。実際のGoogleアカウントでログインした後、
# 手動でこのユーザーのtripsを本物のuser_idへ付け替える想定。
LEGACY_USER_GOOGLE_SUB = "legacy-local-data"


class OwnershipError(Exception):
    """指定されたリソースが、指定されたユーザーの所有物ではない場合に送出する。"""


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
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                google_sub TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                display_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
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
                gmail_message_id TEXT,
                gmail_thread_id TEXT,
                source_type TEXT NOT NULL DEFAULT 'manual',
                reservation_key TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips (id) ON DELETE CASCADE
            )
            """
        )

        reservations_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(reservations)")
        }

        if "reservation_service" not in reservations_columns:
            conn.execute(
                "ALTER TABLE reservations "
                "ADD COLUMN reservation_service TEXT NOT NULL DEFAULT 'その他'"
            )

        if "check_in_date" not in reservations_columns:
            conn.execute("ALTER TABLE reservations ADD COLUMN check_in_date TEXT")

        if "check_out_date" not in reservations_columns:
            conn.execute("ALTER TABLE reservations ADD COLUMN check_out_date TEXT")

        # Web v0.4 Phase E-1：将来のGmail解析結果登録・重複防止設計
        # （claude_report.md参照）に向けた土台となる列を追加する。
        # この段階ではINSERT/UPDATE処理・重複チェック・キー生成ロジックは
        # 一切実装せず、列を安全に追加するだけにとどめる。
        # gmail_message_id・reservation_keyにはUNIQUE制約を付けない
        # （同一予約が複数区間・複数泊・複数搭乗者にまたがる可能性があり、
        # DB層で一意性を強制すると正当なケースでINSERTが失敗しうるため）。
        if "gmail_message_id" not in reservations_columns:
            conn.execute("ALTER TABLE reservations ADD COLUMN gmail_message_id TEXT")

        if "gmail_thread_id" not in reservations_columns:
            conn.execute("ALTER TABLE reservations ADD COLUMN gmail_thread_id TEXT")

        if "source_type" not in reservations_columns:
            conn.execute(
                "ALTER TABLE reservations "
                "ADD COLUMN source_type TEXT NOT NULL DEFAULT 'manual'"
            )

        if "reservation_key" not in reservations_columns:
            conn.execute("ALTER TABLE reservations ADD COLUMN reservation_key TEXT")

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

        trips_columns = {row["name"] for row in conn.execute("PRAGMA table_info(trips)")}

        if "user_id" not in trips_columns:
            conn.execute("ALTER TABLE trips ADD COLUMN user_id INTEGER REFERENCES users(id)")

        # Web v0.2以前のデータ（user_idが無い）を、legacy userへ安全に割り当てる。
        # user_idがまだ無い行が無ければ何もしない（何度実行しても安全＝冪等）。
        # 特定のGoogleアカウントへ自動で割り当てることはしない。
        null_user_trip_count = conn.execute(
            "SELECT COUNT(*) FROM trips WHERE user_id IS NULL"
        ).fetchone()[0]

        if null_user_trip_count > 0:
            legacy_user = conn.execute(
                "SELECT id FROM users WHERE google_sub = ?",
                (LEGACY_USER_GOOGLE_SUB,),
            ).fetchone()

            if legacy_user is None:
                now = datetime.now().isoformat(timespec="seconds")
                cursor = conn.execute(
                    """
                    INSERT INTO users (google_sub, email, display_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (LEGACY_USER_GOOGLE_SUB, "", "（v0.2以前の既存データ）", now, now),
                )
                legacy_user_id = cursor.lastrowid
            else:
                legacy_user_id = legacy_user["id"]

            conn.execute(
                "UPDATE trips SET user_id = ? WHERE user_id IS NULL",
                (legacy_user_id,),
            )

        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------
# ユーザー
# --------------------------------------------------
def get_or_create_user(
    google_sub: str, email: str, display_name: str | None
) -> sqlite3.Row:
    """Googleログイン成功時に呼び出す。

    google_subに一致するユーザーが無ければ新規作成し、あれば
    email／display_nameを最新の値に更新して返す。
    """
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()

    try:
        existing = conn.execute(
            "SELECT * FROM users WHERE google_sub = ?", (google_sub,)
        ).fetchone()

        if existing is None:
            cursor = conn.execute(
                """
                INSERT INTO users (google_sub, email, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (google_sub, email, display_name, now, now),
            )
            conn.commit()
            user_id = cursor.lastrowid
        else:
            conn.execute(
                """
                UPDATE users
                SET email = ?, display_name = ?, updated_at = ?
                WHERE id = ?
                """,
                (email, display_name, now, existing["id"]),
            )
            conn.commit()
            user_id = existing["id"]

        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()


def fetch_user_by_google_sub(google_sub: str) -> sqlite3.Row | None:
    conn = get_connection()

    try:
        return conn.execute(
            "SELECT * FROM users WHERE google_sub = ?", (google_sub,)
        ).fetchone()
    finally:
        conn.close()


# --------------------------------------------------
# 出張
# 読み取り・更新・削除は、必ずuser_idによる所有者条件をWHERE句に含める。
# --------------------------------------------------
def fetch_trips_in_range(
    user_id: int, range_start: date, range_end: date
) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT * FROM trips
            WHERE user_id = ? AND start_date <= ? AND end_date >= ?
            ORDER BY start_date ASC
            """,
            (user_id, range_end.isoformat(), range_start.isoformat()),
        ).fetchall()
    finally:
        conn.close()


def fetch_trips(user_id: int) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            "SELECT * FROM trips WHERE user_id = ? ORDER BY start_date ASC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def fetch_upcoming_trips(user_id: int, today: date, limit: int = 3) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT * FROM trips
            WHERE user_id = ? AND end_date >= ?
            ORDER BY start_date ASC
            LIMIT ?
            """,
            (user_id, today.isoformat(), limit),
        ).fetchall()
    finally:
        conn.close()


def fetch_trip(user_id: int, trip_id: int) -> sqlite3.Row | None:
    conn = get_connection()

    try:
        return conn.execute(
            "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
        ).fetchone()
    finally:
        conn.close()


def update_trip(
    user_id: int,
    trip_id: int,
    name: str,
    start_date: date,
    end_date: date,
    destination: str,
    category: str,
    memo: str,
) -> int:
    """更新した行数を返す。0ならtrip_idが存在しないか、他ユーザーの所有物。"""
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            UPDATE trips
            SET name = ?, start_date = ?, end_date = ?, destination = ?,
                category = ?, memo = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
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
                user_id,
            ),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def delete_trip(user_id: int, trip_id: int) -> int:
    """削除した行数を返す。0ならtrip_idが存在しないか、他ユーザーの所有物。"""
    conn = get_connection()

    try:
        cursor = conn.execute(
            "DELETE FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def insert_trip(
    user_id: int,
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
                user_id, name, start_date, end_date, destination,
                category, memo, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
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


# --------------------------------------------------
# 予約
# reservationsテーブル自体にはuser_idを持たせない（設計方針A）。
# 所有者判定は必ず reservations.trip_id -> trips.user_id の経路で行う。
# --------------------------------------------------
def fetch_reservations_by_trip(user_id: int, trip_id: int) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT reservations.* FROM reservations
            JOIN trips ON reservations.trip_id = trips.id
            WHERE reservations.trip_id = ? AND trips.user_id = ?
            ORDER BY reservations.reservation_date ASC, reservations.id ASC
            """,
            (trip_id, user_id),
        ).fetchall()
    finally:
        conn.close()


def fetch_reservation(user_id: int, reservation_id: int) -> sqlite3.Row | None:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT reservations.* FROM reservations
            JOIN trips ON reservations.trip_id = trips.id
            WHERE reservations.id = ? AND trips.user_id = ?
            """,
            (reservation_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def update_reservation(
    user_id: int,
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
) -> int:
    """更新した行数を返す。0ならreservation_idが存在しないか、他ユーザーの所有物。"""
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            UPDATE reservations
            SET reservation_type = ?, reservation_service = ?, title = ?,
                reservation_date = ?, amount = ?, reservation_number = ?,
                reservation_url = ?, status = ?, memo = ?,
                check_in_date = ?, check_out_date = ?, updated_at = ?
            WHERE id = ?
              AND trip_id IN (SELECT id FROM trips WHERE user_id = ?)
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
                user_id,
            ),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def delete_reservation(user_id: int, reservation_id: int) -> int:
    """削除した行数を返す。0ならreservation_idが存在しないか、他ユーザーの所有物。"""
    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            DELETE FROM reservations
            WHERE id = ?
              AND trip_id IN (SELECT id FROM trips WHERE user_id = ?)
            """,
            (reservation_id, user_id),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def fetch_reservations_in_range(
    user_id: int, range_start: date, range_end: date
) -> list[sqlite3.Row]:
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT reservations.* FROM reservations
            JOIN trips ON reservations.trip_id = trips.id
            WHERE trips.user_id = ?
              AND (
                  (
                      reservations.reservation_type != 'ホテル'
                      AND reservations.reservation_date BETWEEN ? AND ?
                  )
                  OR
                  (
                      reservations.reservation_type = 'ホテル'
                      AND reservations.check_in_date IS NOT NULL
                      AND reservations.check_in_date <= ?
                      AND (
                          reservations.check_out_date IS NULL
                          OR reservations.check_out_date >= ?
                      )
                  )
              )
            ORDER BY reservations.reservation_date ASC, reservations.id ASC
            """,
            (
                user_id,
                range_start.isoformat(),
                range_end.isoformat(),
                range_end.isoformat(),
                range_start.isoformat(),
            ),
        ).fetchall()
    finally:
        conn.close()


def get_reservation_status(user_id: int, trip_id: int) -> dict:
    reservations = fetch_reservations_by_trip(user_id, trip_id)

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
    user_id: int,
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
    """予約を登録する。trip_idがuser_idの所有物でない場合はOwnershipErrorを送出する。"""
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()

    try:
        owned_trip = conn.execute(
            "SELECT id FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
        ).fetchone()

        if owned_trip is None:
            raise OwnershipError(
                f"trip_id={trip_id} is not owned by user_id={user_id}"
            )

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
