"""database.py（Web v0.4 Phase E-1）のテスト。

Gmail由来情報を保存するための土台となる4列（gmail_message_id・
gmail_thread_id・source_type・reservation_key）を安全に追加できることと、
既存の予約CRUDが引き続き正しく動作することを確認する。

実データベースファイル（web/data/tripflow.db）は一切使わず、テストごとに
一時ディレクトリ内のDBファイルへdatabase.DB_PATHを差し替えて検証する。
ここで使うユーザー名・メールアドレス・予約情報はすべて人工的なテスト用の
値であり、実際の個人情報とは無関係。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import database as db


class _TempDatabaseTestCase(unittest.TestCase):
    """テストごとに一時DBファイルへdatabase.DB_PATHを差し替える基底クラス。"""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = db.DB_PATH
        db.DB_PATH = Path(self._tmp_dir.name) / "test_tripflow.db"

    def tearDown(self) -> None:
        db.DB_PATH = self._original_db_path
        self._tmp_dir.cleanup()


def _reservations_columns(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(reservations)")}


class NewDatabaseSchemaTests(_TempDatabaseTestCase):
    """新規DB（初回のinit_db()呼び出し）で4列が存在することを確認する。"""

    def test_new_db_has_gmail_and_dedup_columns(self) -> None:
        db.init_db()

        conn = db.get_connection()
        try:
            columns = _reservations_columns(conn)
        finally:
            conn.close()

        self.assertIn("gmail_message_id", columns)
        self.assertIn("gmail_thread_id", columns)
        self.assertIn("source_type", columns)
        self.assertIn("reservation_key", columns)

    def test_no_unique_constraint_on_gmail_message_id_or_reservation_key(self) -> None:
        # UNIQUE制約を付けない、という今回の要求を検証する。同じ
        # gmail_message_id・reservation_keyを持つ2行のINSERTが両方
        # 成功することで、意図せずUNIQUE制約が付いていないことを確認する。
        db.init_db()

        conn = db.get_connection()
        try:
            now = "2026-08-15T00:00:00"
            user_cursor = conn.execute(
                """
                INSERT INTO users (google_sub, email, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("unique-check-sub", "unique-check@example.invalid", "テストユーザー", now, now),
            )
            user_id = user_cursor.lastrowid

            trip_cursor = conn.execute(
                """
                INSERT INTO trips (
                    user_id, name, start_date, end_date, destination,
                    category, memo, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, "テスト出張", "2026-09-01", "2026-09-03", "テスト行き先",
                 "業務", "", now, now),
            )
            trip_id = trip_cursor.lastrowid

            for _ in range(2):
                conn.execute(
                    """
                    INSERT INTO reservations (
                        trip_id, reservation_type, reservation_service, title,
                        reservation_date, amount, reservation_number, reservation_url,
                        status, memo, gmail_message_id, reservation_key,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trip_id, "その他", "えきねっと", "サンプル予約",
                        "2026-09-01", 0, "", "", "予約済み", "",
                        "SAME-MESSAGE-ID", "SAME-RESERVATION-KEY",
                        now, now,
                    ),
                )
            conn.commit()

            count = conn.execute(
                "SELECT COUNT(*) FROM reservations WHERE gmail_message_id = ?",
                ("SAME-MESSAGE-ID",),
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(count, 2)


class SourceTypeDefaultTests(_TempDatabaseTestCase):
    """既存のinsert_reservation()経由（手動登録相当）でsource_typeがmanualになることを確認する。"""

    def test_source_type_defaults_to_manual_via_insert_reservation(self) -> None:
        db.init_db()

        user = db.get_or_create_user(
            google_sub="phase-e1-test-sub",
            email="phase-e1@example.invalid",
            display_name="テストユーザー",
        )
        trip_id = db.insert_trip(
            user_id=user["id"],
            name="Phase E-1テスト出張",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            destination="テスト行き先",
            category="業務",
            memo="",
        )
        reservation_id = db.insert_reservation(
            user_id=user["id"],
            trip_id=trip_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="サンプル予約",
            reservation_date=date(2026, 9, 1),
            amount=0,
            reservation_number="",
            reservation_url="",
            status="予約済み",
            memo="",
        )

        reservation = db.fetch_reservation(user["id"], reservation_id)

        self.assertEqual(reservation["source_type"], "manual")
        self.assertIsNone(reservation["gmail_message_id"])
        self.assertIsNone(reservation["gmail_thread_id"])
        self.assertIsNone(reservation["reservation_key"])


class LegacySchemaMigrationTests(_TempDatabaseTestCase):
    """Phase E-1より前のスキーマ（4列が無い状態）からのアップグレードを検証する。"""

    def _create_legacy_schema(self) -> tuple[int, int]:
        """4列を持たない旧スキーマのDBを直接作成し、既存ユーザー・出張・予約を1件ずつ入れる。"""
        conn = db.get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE users (
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
                CREATE TABLE trips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
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
            # Phase E-1で追加する4列を持たない、それ以前のreservationsスキーマ。
            conn.execute(
                """
                CREATE TABLE reservations (
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

            now = "2026-08-01T00:00:00"
            user_cursor = conn.execute(
                """
                INSERT INTO users (google_sub, email, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("legacy-sub", "legacy@example.invalid", "既存ユーザー", now, now),
            )
            user_id = user_cursor.lastrowid

            trip_cursor = conn.execute(
                """
                INSERT INTO trips (
                    user_id, name, start_date, end_date, destination,
                    category, memo, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, "既存出張", "2026-08-10", "2026-08-12", "既存行き先",
                 "業務", "", now, now),
            )
            trip_id = trip_cursor.lastrowid

            conn.execute(
                """
                INSERT INTO reservations (
                    trip_id, reservation_type, reservation_service, title,
                    reservation_date, amount, reservation_number, reservation_url,
                    status, memo, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (trip_id, "往路", "えきねっと", "既存予約",
                 "2026-08-10", 5000, "EXIST-001", "", "予約済み", "",
                 now, now),
            )
            conn.commit()

            return user_id, trip_id
        finally:
            conn.close()

    def test_legacy_reservations_table_gains_four_columns_after_init_db(self) -> None:
        user_id, trip_id = self._create_legacy_schema()

        db.init_db()

        conn = db.get_connection()
        try:
            columns = _reservations_columns(conn)
        finally:
            conn.close()

        self.assertIn("gmail_message_id", columns)
        self.assertIn("gmail_thread_id", columns)
        self.assertIn("source_type", columns)
        self.assertIn("reservation_key", columns)

        existing_reservations = db.fetch_reservations_by_trip(user_id, trip_id)
        self.assertEqual(len(existing_reservations), 1)

        reservation = existing_reservations[0]
        self.assertEqual(reservation["title"], "既存予約")
        self.assertEqual(reservation["source_type"], "manual")
        self.assertIsNone(reservation["gmail_message_id"])
        self.assertIsNone(reservation["gmail_thread_id"])
        self.assertIsNone(reservation["reservation_key"])

    def test_init_db_is_idempotent_after_legacy_migration(self) -> None:
        self._create_legacy_schema()

        # init_db()を複数回実行してもエラーにならず、既存データも増減しない
        # （冪等である）ことを確認する。
        db.init_db()
        db.init_db()
        db.init_db()

        conn = db.get_connection()
        try:
            columns = _reservations_columns(conn)
            count = conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        finally:
            conn.close()

        self.assertIn("gmail_message_id", columns)
        self.assertIn("gmail_thread_id", columns)
        self.assertIn("source_type", columns)
        self.assertIn("reservation_key", columns)
        self.assertEqual(count, 1)


class ExistingReservationCrudUnaffectedTests(_TempDatabaseTestCase):
    """Phase E-1の列追加後も、既存の予約CRUDが壊れていないことを確認する。"""

    def setUp(self) -> None:
        super().setUp()
        db.init_db()
        self.user = db.get_or_create_user(
            google_sub="crud-test-sub",
            email="crud-test@example.invalid",
            display_name="CRUDテストユーザー",
        )
        self.trip_id = db.insert_trip(
            user_id=self.user["id"],
            name="CRUDテスト出張",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            destination="テスト行き先",
            category="業務",
            memo="",
        )

    def test_insert_fetch_update_delete_reservation(self) -> None:
        reservation_id = db.insert_reservation(
            user_id=self.user["id"],
            trip_id=self.trip_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="CRUDテスト予約",
            reservation_date=date(2026, 9, 1),
            amount=1000,
            reservation_number="R-001",
            reservation_url="",
            status="予約済み",
            memo="",
        )

        fetched = db.fetch_reservation(self.user["id"], reservation_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "CRUDテスト予約")
        self.assertEqual(fetched["source_type"], "manual")

        affected = db.update_reservation(
            user_id=self.user["id"],
            reservation_id=reservation_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="CRUDテスト予約（更新）",
            reservation_date=date(2026, 9, 2),
            amount=1200,
            reservation_number="R-001",
            reservation_url="",
            status="予約済み",
            memo="",
        )
        self.assertEqual(affected, 1)

        updated = db.fetch_reservation(self.user["id"], reservation_id)
        self.assertEqual(updated["title"], "CRUDテスト予約（更新）")
        self.assertEqual(updated["amount"], 1200)
        # update_reservation()は今回対象外のため、source_typeは
        # 既存の値（manual）のまま変化しないことを確認する。
        self.assertEqual(updated["source_type"], "manual")

        deleted = db.delete_reservation(self.user["id"], reservation_id)
        self.assertEqual(deleted, 1)
        self.assertIsNone(db.fetch_reservation(self.user["id"], reservation_id))

    def test_fetch_reservations_by_trip_and_in_range_still_work(self) -> None:
        db.insert_reservation(
            user_id=self.user["id"],
            trip_id=self.trip_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="範囲確認テスト予約",
            reservation_date=date(2026, 9, 1),
            amount=0,
            reservation_number="",
            reservation_url="",
            status="予約済み",
            memo="",
        )

        by_trip = db.fetch_reservations_by_trip(self.user["id"], self.trip_id)
        self.assertEqual(len(by_trip), 1)

        in_range = db.fetch_reservations_in_range(
            self.user["id"], date(2026, 9, 1), date(2026, 9, 1)
        )
        self.assertEqual(len(in_range), 1)

    def test_ownership_error_still_raised_for_other_users_trip(self) -> None:
        other_user = db.get_or_create_user(
            google_sub="crud-test-other-sub",
            email="crud-test-other@example.invalid",
            display_name="別のテストユーザー",
        )

        with self.assertRaises(db.OwnershipError):
            db.insert_reservation(
                user_id=other_user["id"],
                trip_id=self.trip_id,
                reservation_type="往路",
                reservation_service="えきねっと",
                title="所有者チェックテスト予約",
                reservation_date=date(2026, 9, 1),
                amount=0,
                reservation_number="",
                reservation_url="",
                status="予約済み",
                memo="",
            )


class GmailInsertReservationTests(_TempDatabaseTestCase):
    """Phase E-2Bで追加したinsert_reservation()のGmail由来引数を検証する。"""

    def setUp(self) -> None:
        super().setUp()
        db.init_db()
        self.user = db.get_or_create_user(
            google_sub="gmail-insert-test-sub",
            email="gmail-insert-test@example.invalid",
            display_name="Gmail登録テストユーザー",
        )
        self.trip_id = db.insert_trip(
            user_id=self.user["id"],
            name="Gmail登録テスト出張",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            destination="テスト行き先",
            category="業務",
            memo="",
        )

    def test_gmail_origin_reservation_saves_gmail_metadata(self) -> None:
        reservation_id = db.insert_reservation(
            user_id=self.user["id"],
            trip_id=self.trip_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="のぞみ1号 東京→新大阪",
            reservation_date=date(2026, 9, 1),
            amount=13000,
            reservation_number="REF-0001",
            reservation_url="",
            status="予約済み",
            memo="出発：東京\n到着：新大阪",
            gmail_message_id="MSG-GMAIL-001",
            gmail_thread_id="THREAD-GMAIL-001",
            source_type="gmail",
        )

        reservation = db.fetch_reservation(self.user["id"], reservation_id)

        self.assertEqual(reservation["source_type"], "gmail")
        self.assertEqual(reservation["gmail_message_id"], "MSG-GMAIL-001")
        self.assertEqual(reservation["gmail_thread_id"], "THREAD-GMAIL-001")
        # reservation_keyはPhase E-2Bでは生成しないため、常にNULLのまま。
        self.assertIsNone(reservation["reservation_key"])

    def test_manual_reservation_without_new_kwargs_is_unaffected(self) -> None:
        # 新しいキーワード引数を一切渡さない、既存の手動登録と同じ呼び出し方。
        # Phase E-1と同じ結果（source_type='manual'・Gmail関連列NULL）に
        # なることを、insert_reservation()のシグネチャ変更後にも確認する。
        reservation_id = db.insert_reservation(
            user_id=self.user["id"],
            trip_id=self.trip_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="手動登録テスト予約",
            reservation_date=date(2026, 9, 2),
            amount=5000,
            reservation_number="MANUAL-001",
            reservation_url="",
            status="予約済み",
            memo="",
        )

        reservation = db.fetch_reservation(self.user["id"], reservation_id)

        self.assertEqual(reservation["source_type"], "manual")
        self.assertIsNone(reservation["gmail_message_id"])
        self.assertIsNone(reservation["gmail_thread_id"])
        self.assertIsNone(reservation["reservation_key"])

    def test_hotel_manual_registration_with_check_in_out_still_works(self) -> None:
        # ホテル予約（check_in_date/check_out_dateを使う既存の呼び出し方）が、
        # シグネチャ変更後も位置引数の並びを変えずに動作することを確認する。
        reservation_id = db.insert_reservation(
            user_id=self.user["id"],
            trip_id=self.trip_id,
            reservation_type="ホテル",
            reservation_service="Agoda",
            title="手動登録テストホテル",
            reservation_date=date(2026, 9, 3),
            amount=8000,
            reservation_number="",
            reservation_url="",
            status="予約済み",
            memo="",
            check_in_date=date(2026, 9, 3),
            check_out_date=date(2026, 9, 4),
        )

        reservation = db.fetch_reservation(self.user["id"], reservation_id)

        self.assertEqual(reservation["check_in_date"], "2026-09-03")
        self.assertEqual(reservation["check_out_date"], "2026-09-04")
        self.assertEqual(reservation["source_type"], "manual")


class IsGmailMessageRegisteredTests(_TempDatabaseTestCase):
    """Phase E-3で追加したis_gmail_message_registered()を検証する。

    ここで確認するのは「同じGmail message_idからの二重登録」防止のみ。
    予約番号・日付・区間等による類似判定や、別メール間の同一予約判定は
    対象外（今後のフェーズ）。
    """

    def setUp(self) -> None:
        super().setUp()
        db.init_db()
        self.user = db.get_or_create_user(
            google_sub="dedup-test-sub",
            email="dedup-test@example.invalid",
            display_name="重複防止テストユーザー",
        )
        self.trip_id = db.insert_trip(
            user_id=self.user["id"],
            name="重複防止テスト出張",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            destination="テスト行き先",
            category="業務",
            memo="",
        )

    def _insert_gmail_reservation(self, gmail_message_id: str) -> int:
        return db.insert_reservation(
            user_id=self.user["id"],
            trip_id=self.trip_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="重複防止テスト予約",
            reservation_date=date(2026, 9, 1),
            amount=1000,
            reservation_number="R-DEDUP-001",
            reservation_url="",
            status="予約済み",
            memo="",
            gmail_message_id=gmail_message_id,
            gmail_thread_id="THREAD-DEDUP-001",
            source_type="gmail",
        )

    def test_same_user_same_message_id_is_registered(self) -> None:
        self._insert_gmail_reservation("MSG-DEDUP-001")

        self.assertTrue(
            db.is_gmail_message_registered(self.user["id"], "MSG-DEDUP-001")
        )

    def test_same_user_different_message_id_is_not_registered(self) -> None:
        self._insert_gmail_reservation("MSG-DEDUP-001")

        self.assertFalse(
            db.is_gmail_message_registered(self.user["id"], "MSG-DEDUP-999")
        )

    def test_other_users_same_message_id_does_not_block_current_user(self) -> None:
        other_user = db.get_or_create_user(
            google_sub="dedup-test-other-sub",
            email="dedup-test-other@example.invalid",
            display_name="別の重複防止テストユーザー",
        )
        other_trip_id = db.insert_trip(
            user_id=other_user["id"],
            name="別ユーザーの出張",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            destination="テスト行き先",
            category="業務",
            memo="",
        )
        db.insert_reservation(
            user_id=other_user["id"],
            trip_id=other_trip_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="別ユーザーの予約",
            reservation_date=date(2026, 9, 1),
            amount=1000,
            reservation_number="",
            reservation_url="",
            status="予約済み",
            memo="",
            gmail_message_id="MSG-DEDUP-SHARED",
            gmail_thread_id="THREAD-DEDUP-SHARED",
            source_type="gmail",
        )

        self.assertFalse(
            db.is_gmail_message_registered(self.user["id"], "MSG-DEDUP-SHARED")
        )

    def test_none_message_id_is_not_registered(self) -> None:
        self.assertFalse(db.is_gmail_message_registered(self.user["id"], None))

    def test_empty_string_message_id_is_not_registered(self) -> None:
        self.assertFalse(db.is_gmail_message_registered(self.user["id"], ""))

    def test_whitespace_only_message_id_is_not_registered(self) -> None:
        self.assertFalse(db.is_gmail_message_registered(self.user["id"], "   "))

    def test_manual_reservation_with_null_message_id_is_not_matched(self) -> None:
        # 手動登録（gmail_message_id=NULL）は重複判定の対象にならないことを
        # 確認する。空白のみのmessage_idを渡した場合にNULL行と誤って
        # 一致しないことも合わせて確認する。
        db.insert_reservation(
            user_id=self.user["id"],
            trip_id=self.trip_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="手動登録予約",
            reservation_date=date(2026, 9, 1),
            amount=0,
            reservation_number="",
            reservation_url="",
            status="予約済み",
            memo="",
        )

        self.assertFalse(db.is_gmail_message_registered(self.user["id"], "   "))
        self.assertFalse(
            db.is_gmail_message_registered(self.user["id"], "MSG-NOT-PRESENT")
        )

    def test_becomes_registered_immediately_after_gmail_insert(self) -> None:
        self.assertFalse(
            db.is_gmail_message_registered(self.user["id"], "MSG-DEDUP-LATER")
        )

        self._insert_gmail_reservation("MSG-DEDUP-LATER")

        self.assertTrue(
            db.is_gmail_message_registered(self.user["id"], "MSG-DEDUP-LATER")
        )


class UserIsolationRegressionTests(_TempDatabaseTestCase):
    """Phase F-1：ユーザー分離（他ユーザーのTrip/Reservationへアクセスできない
    こと）の回帰テスト。

    これまでinsert_reservation()のOwnershipErrorだけがテストされており、
    fetch/update/deleteの所有者チェックは自動テストで担保されていなかった。
    ここではユーザーA所有のTrip・Reservation（手動登録・Gmail由来の両方）に
    対して、ユーザーBがfetch/update/deleteを試みても、ユーザーAのデータを
    閲覧・変更・削除できないことを確認する。
    """

    def setUp(self) -> None:
        super().setUp()
        db.init_db()

        self.user_a = db.get_or_create_user(
            google_sub="isolation-test-user-a",
            email="isolation-test-a@example.invalid",
            display_name="ユーザーA",
        )
        self.user_b = db.get_or_create_user(
            google_sub="isolation-test-user-b",
            email="isolation-test-b@example.invalid",
            display_name="ユーザーB",
        )

        self.trip_a_id = db.insert_trip(
            user_id=self.user_a["id"],
            name="ユーザーAの出張",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            destination="ユーザーAの行き先",
            category="業務",
            memo="ユーザーAのメモ",
        )

        self.reservation_a_id = db.insert_reservation(
            user_id=self.user_a["id"],
            trip_id=self.trip_a_id,
            reservation_type="往路",
            reservation_service="えきねっと",
            title="ユーザーAの予約（手動）",
            reservation_date=date(2026, 9, 1),
            amount=1000,
            reservation_number="A-MANUAL-001",
            reservation_url="",
            status="予約済み",
            memo="",
        )

        self.gmail_reservation_a_id = db.insert_reservation(
            user_id=self.user_a["id"],
            trip_id=self.trip_a_id,
            reservation_type="復路",
            reservation_service="えきねっと",
            title="ユーザーAの予約（Gmail由来）",
            reservation_date=date(2026, 9, 5),
            amount=1000,
            reservation_number="A-GMAIL-001",
            reservation_url="",
            status="予約済み",
            memo="",
            gmail_message_id="MSG-ISOLATION-A-001",
            gmail_thread_id="THREAD-ISOLATION-A-001",
            source_type="gmail",
        )

    # ---- Trip ----

    def test_fetch_trip_by_other_user_returns_none(self) -> None:
        self.assertIsNone(db.fetch_trip(self.user_b["id"], self.trip_a_id))
        # ユーザーA自身からは引き続き取得できることも確認する。
        self.assertIsNotNone(db.fetch_trip(self.user_a["id"], self.trip_a_id))

    def test_fetch_trips_by_other_user_excludes_it(self) -> None:
        trip_ids_for_b = [trip["id"] for trip in db.fetch_trips(self.user_b["id"])]
        self.assertNotIn(self.trip_a_id, trip_ids_for_b)

    def test_update_trip_by_other_user_does_not_change_it(self) -> None:
        affected = db.update_trip(
            user_id=self.user_b["id"],
            trip_id=self.trip_a_id,
            name="改ざんされた出張名",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),
            destination="改ざんされた行き先",
            category="プライベート",
            memo="改ざんされたメモ",
        )

        # 既存仕様（update_trip()のdocstring）通り、影響行数0で失敗を表す。
        self.assertEqual(affected, 0)

        unchanged = db.fetch_trip(self.user_a["id"], self.trip_a_id)
        self.assertEqual(unchanged["name"], "ユーザーAの出張")
        self.assertEqual(unchanged["destination"], "ユーザーAの行き先")
        self.assertEqual(unchanged["category"], "業務")

    def test_delete_trip_by_other_user_does_not_delete_it(self) -> None:
        affected = db.delete_trip(user_id=self.user_b["id"], trip_id=self.trip_a_id)

        # 既存仕様（delete_trip()のdocstring）通り、影響行数0で失敗を表す。
        self.assertEqual(affected, 0)
        self.assertIsNotNone(db.fetch_trip(self.user_a["id"], self.trip_a_id))

    # ---- Reservation（手動登録） ----

    def test_fetch_reservation_by_other_user_returns_none(self) -> None:
        self.assertIsNone(
            db.fetch_reservation(self.user_b["id"], self.reservation_a_id)
        )
        self.assertIsNotNone(
            db.fetch_reservation(self.user_a["id"], self.reservation_a_id)
        )

    def test_update_reservation_by_other_user_does_not_change_it(self) -> None:
        affected = db.update_reservation(
            user_id=self.user_b["id"],
            reservation_id=self.reservation_a_id,
            reservation_type="復路",
            reservation_service="Agoda",
            title="改ざんされた予約名",
            reservation_date=date(2026, 12, 1),
            amount=999999,
            reservation_number="HACKED",
            reservation_url="",
            status="キャンセル",
            memo="改ざんされたメモ",
        )

        self.assertEqual(affected, 0)

        unchanged = db.fetch_reservation(self.user_a["id"], self.reservation_a_id)
        self.assertEqual(unchanged["title"], "ユーザーAの予約（手動）")
        self.assertEqual(unchanged["amount"], 1000)
        self.assertEqual(unchanged["status"], "予約済み")

    def test_delete_reservation_by_other_user_does_not_delete_it(self) -> None:
        affected = db.delete_reservation(
            user_id=self.user_b["id"], reservation_id=self.reservation_a_id
        )

        self.assertEqual(affected, 0)
        self.assertIsNotNone(
            db.fetch_reservation(self.user_a["id"], self.reservation_a_id)
        )

    def test_fetch_reservations_by_trip_with_other_users_trip_id_returns_empty(
        self,
    ) -> None:
        # ユーザーBが、ユーザーAのtrip_idを直接指定しても、
        # ユーザーAの予約一覧は一切返らない。
        result = db.fetch_reservations_by_trip(self.user_b["id"], self.trip_a_id)
        self.assertEqual(result, [])

    def test_fetch_reservations_in_range_does_not_mix_other_users_reservations(
        self,
    ) -> None:
        # ユーザーBにも同じ期間内に自分の出張・予約を作り、
        # 「たまたま0件だから混ざっていないだけ」ではないことを確認する。
        trip_b_id = db.insert_trip(
            user_id=self.user_b["id"],
            name="ユーザーBの出張",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            destination="ユーザーBの行き先",
            category="業務",
            memo="",
        )
        reservation_b_id = db.insert_reservation(
            user_id=self.user_b["id"],
            trip_id=trip_b_id,
            reservation_type="往路",
            reservation_service="スマートEX",
            title="ユーザーBの予約",
            reservation_date=date(2026, 9, 2),
            amount=2000,
            reservation_number="B-001",
            reservation_url="",
            status="予約済み",
            memo="",
        )

        result = db.fetch_reservations_in_range(
            self.user_b["id"], date(2026, 9, 1), date(2026, 9, 5)
        )
        result_ids = [reservation["id"] for reservation in result]

        self.assertIn(reservation_b_id, result_ids)
        self.assertNotIn(self.reservation_a_id, result_ids)
        self.assertNotIn(self.gmail_reservation_a_id, result_ids)

    # ---- Reservation（Gmail由来） ----

    def test_gmail_origin_reservation_is_also_isolated_by_user(self) -> None:
        # Gmail由来（source_type='gmail'）だからといって、所有者チェックを
        # 迂回する特別な経路は無いことを確認する。
        self.assertIsNone(
            db.fetch_reservation(self.user_b["id"], self.gmail_reservation_a_id)
        )
        self.assertIsNotNone(
            db.fetch_reservation(self.user_a["id"], self.gmail_reservation_a_id)
        )

        by_trip_for_b = db.fetch_reservations_by_trip(
            self.user_b["id"], self.trip_a_id
        )
        self.assertEqual(by_trip_for_b, [])

        affected = db.delete_reservation(
            user_id=self.user_b["id"], reservation_id=self.gmail_reservation_a_id
        )
        self.assertEqual(affected, 0)
        self.assertIsNotNone(
            db.fetch_reservation(self.user_a["id"], self.gmail_reservation_a_id)
        )

    def test_existing_crud_for_owner_still_works(self) -> None:
        # 今回の追加テストが既存の正常系（自分自身のTrip/Reservationの
        # CRUD）を壊していないことも合わせて確認する。
        affected = db.update_trip(
            user_id=self.user_a["id"],
            trip_id=self.trip_a_id,
            name="ユーザーAの出張（更新後）",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 6),
            destination="ユーザーAの行き先",
            category="業務",
            memo="",
        )
        self.assertEqual(affected, 1)

        updated = db.fetch_trip(self.user_a["id"], self.trip_a_id)
        self.assertEqual(updated["name"], "ユーザーAの出張（更新後）")


if __name__ == "__main__":
    unittest.main()
