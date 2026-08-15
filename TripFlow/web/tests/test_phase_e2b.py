"""reservation_parser.py（Web v0.4 Phase E-2B）のテスト。

「Gmail解析結果をユーザー確認後にTripFlowへ登録する最小機能」のうち、
reservation_parser.py側の追加分（can_register()・thread_id伝播・
title/memo組み立て）を検証する。ここで使う件名・本文・予約情報は
すべて人工的なサンプルであり、実際のメール・個人情報とは無関係。
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reservation_parser as rp


def _make_candidate(**overrides) -> rp.ReservationCandidate:
    """テスト用のReservationCandidateを、必要な項目だけ上書きして作る。"""
    base = dict(
        service="えきねっと",
        message_id="MSG-BASE",
        relevance=rp.RELEVANCE_TARGET,
        reservation_type="電車",
        confidence="高",
        title="件名フォールバック用タイトル",
        date=date(2026, 9, 1),
        start_time="08:00",
        end_time="10:33",
        origin="東京",
        destination="新大阪",
        train_name="のぞみ1号",
        car_number="8号車",
        seat_number="19A",
        hotel_name=None,
        checkin_date=None,
        checkout_date=None,
        amount=13000,
        reservation_reference="REF-0001",
        flight_number=None,
        fare_type=None,
        missing_fields=(),
    )
    base.update(overrides)
    return rp.ReservationCandidate(**base)


class CanRegisterTests(unittest.TestCase):
    def test_target_can_register(self) -> None:
        self.assertTrue(rp.can_register(rp.RELEVANCE_TARGET))

    def test_supplementary_cannot_register(self) -> None:
        self.assertFalse(rp.can_register(rp.RELEVANCE_SUPPLEMENTARY))

    def test_unknown_cannot_register(self) -> None:
        self.assertFalse(rp.can_register(rp.RELEVANCE_UNKNOWN))

    def test_excluded_cannot_register(self) -> None:
        self.assertFalse(rp.can_register(rp.RELEVANCE_EXCLUDED))

    def test_can_analyze_is_unchanged_and_broader_than_can_register(self) -> None:
        # can_analyze()自体は今回変更していないため、SUPPLEMENTARY・UNKNOWNは
        # 引き続き解析可能（can_register()より緩い判定）であることを確認する。
        self.assertTrue(rp.can_analyze(rp.RELEVANCE_SUPPLEMENTARY))
        self.assertTrue(rp.can_analyze(rp.RELEVANCE_UNKNOWN))
        self.assertFalse(rp.can_analyze(rp.RELEVANCE_EXCLUDED))


class ThreadIdPropagationTests(unittest.TestCase):
    SAMPLE_BODY = (
        "ご乗車日：2026年9月1日\n"
        "出発駅：東京\n"
        "到着駅：新大阪\n"
        "出発時刻：08:00\n"
        "到着時刻：10:33\n"
        "列車名：のぞみ1号\n"
        "予約番号：REF-0001\n"
    )

    def test_thread_id_propagates_from_analyze_email(self) -> None:
        result = rp.analyze_email(
            service="えきねっと",
            message_id="MSG-001",
            relevance=rp.RELEVANCE_TARGET,
            subject="【えきねっと】ご予約内容の確認",
            text_plain=self.SAMPLE_BODY,
            text_html="",
            thread_id="THREAD-001",
        )

        self.assertEqual(result.thread_id, "THREAD-001")
        # thread_id以外の既存フィールドは、抽出結果として変わらないことを確認する。
        self.assertEqual(result.message_id, "MSG-001")
        self.assertEqual(result.train_name, "のぞみ1号")

    def test_existing_call_without_thread_id_still_works(self) -> None:
        # Phase C/D時点の既存呼び出し（thread_idを渡さない）が壊れないことを
        # 確認する回帰テスト。
        result = rp.analyze_email(
            service="えきねっと",
            message_id="MSG-002",
            relevance=rp.RELEVANCE_TARGET,
            subject="【えきねっと】ご予約内容の確認",
            text_plain=self.SAMPLE_BODY,
            text_html="",
        )

        self.assertIsNone(result.thread_id)
        self.assertEqual(result.train_name, "のぞみ1号")

    def test_falsy_thread_id_does_not_override_default(self) -> None:
        result = rp.analyze_email(
            service="えきねっと",
            message_id="MSG-003",
            relevance=rp.RELEVANCE_TARGET,
            subject="【えきねっと】ご予約内容の確認",
            text_plain=self.SAMPLE_BODY,
            text_html="",
            thread_id="",
        )

        self.assertIsNone(result.thread_id)


class BuildReservationTitleTests(unittest.TestCase):
    def test_ekinet_train_name_and_route(self) -> None:
        candidate = _make_candidate(
            service="えきねっと", train_name="のぞみ1号", origin="東京", destination="新大阪"
        )
        self.assertEqual(rp.build_reservation_title(candidate), "のぞみ1号 東京→新大阪")

    def test_smart_ex_train_name_and_route(self) -> None:
        candidate = _make_candidate(
            service="スマートEX", train_name="ひかり5号", origin="新大阪", destination="博多"
        )
        self.assertEqual(rp.build_reservation_title(candidate), "ひかり5号 新大阪→博多")

    def test_train_name_only_when_route_missing(self) -> None:
        candidate = _make_candidate(
            service="えきねっと", train_name="のぞみ1号", origin=None, destination=None
        )
        self.assertEqual(rp.build_reservation_title(candidate), "のぞみ1号")

    def test_falls_back_to_candidate_title_when_train_name_missing(self) -> None:
        candidate = _make_candidate(
            service="えきねっと",
            train_name=None,
            origin="東京",
            destination="新大阪",
            title="件名フォールバック用タイトル",
        )
        self.assertEqual(
            rp.build_reservation_title(candidate), "件名フォールバック用タイトル"
        )

    def test_skymark_flight_number_and_route(self) -> None:
        candidate = _make_candidate(
            service="スカイマーク",
            reservation_type="飛行機",
            train_name=None,
            flight_number="SKY123便",
            origin="羽田",
            destination="福岡",
        )
        self.assertEqual(rp.build_reservation_title(candidate), "SKY123便 羽田→福岡")

    def test_skymark_flight_number_only_when_route_missing(self) -> None:
        candidate = _make_candidate(
            service="スカイマーク",
            reservation_type="飛行機",
            train_name=None,
            flight_number="SKY123便",
            origin=None,
            destination=None,
        )
        self.assertEqual(rp.build_reservation_title(candidate), "SKY123便")

    def test_agoda_hotel_name(self) -> None:
        candidate = _make_candidate(
            service="Agoda",
            reservation_type="ホテル",
            train_name=None,
            hotel_name="サンプルホテル東京",
            origin=None,
            destination=None,
        )
        self.assertEqual(rp.build_reservation_title(candidate), "サンプルホテル東京")

    def test_agoda_falls_back_to_candidate_title_when_hotel_name_missing(self) -> None:
        candidate = _make_candidate(
            service="Agoda",
            reservation_type="ホテル",
            train_name=None,
            hotel_name=None,
            title="件名フォールバック用タイトル",
        )
        self.assertEqual(
            rp.build_reservation_title(candidate), "件名フォールバック用タイトル"
        )


class BuildReservationMemoTests(unittest.TestCase):
    def test_train_memo_includes_all_present_fields_in_fixed_order(self) -> None:
        candidate = _make_candidate(
            origin="東京",
            destination="新大阪",
            start_time="08:00",
            end_time="10:33",
            train_name="のぞみ1号",
            flight_number=None,
            car_number="8号車",
            seat_number="19A",
            fare_type=None,
        )
        memo = rp.build_reservation_memo(candidate)
        self.assertEqual(
            memo,
            "出発：東京\n到着：新大阪\n時刻：08:00 → 10:33\n列車：のぞみ1号\n"
            "号車：8号車\n座席：19A",
        )

    def test_flight_memo_omits_car_number(self) -> None:
        candidate = _make_candidate(
            service="スカイマーク",
            reservation_type="飛行機",
            origin="羽田",
            destination="福岡",
            start_time="13:45",
            end_time="15:40",
            train_name=None,
            flight_number="SKY015便",
            car_number=None,
            seat_number="18H",
            fare_type=None,
        )
        memo = rp.build_reservation_memo(candidate)
        self.assertEqual(
            memo,
            "出発：羽田\n到着：福岡\n時刻：13:45 → 15:40\n便名：SKY015便\n座席：18H",
        )
        self.assertNotIn("号車", memo)

    def test_missing_fields_are_omitted_not_guessed(self) -> None:
        candidate = _make_candidate(
            origin=None,
            destination=None,
            start_time=None,
            end_time=None,
            train_name="のぞみ1号",
            car_number=None,
            seat_number=None,
            fare_type=None,
        )
        memo = rp.build_reservation_memo(candidate)
        self.assertEqual(memo, "列車：のぞみ1号")

    def test_time_line_omitted_when_only_one_side_present(self) -> None:
        # 時刻は「開始 → 終了」の対で1行にまとめるため、片方しか無い場合は
        # 「？」等の推測表現を入れず、行ごと省略する。
        candidate = _make_candidate(start_time="08:00", end_time=None)
        memo = rp.build_reservation_memo(candidate)
        self.assertNotIn("時刻", memo)

    def test_fare_type_included_only_when_present(self) -> None:
        candidate = _make_candidate(fare_type="いま得")
        memo = rp.build_reservation_memo(candidate)
        self.assertIn("運賃種別：いま得", memo)
        self.assertTrue(memo.endswith("運賃種別：いま得"))

    def test_empty_memo_when_nothing_available(self) -> None:
        candidate = _make_candidate(
            origin=None,
            destination=None,
            start_time=None,
            end_time=None,
            train_name=None,
            car_number=None,
            seat_number=None,
            fare_type=None,
        )
        self.assertEqual(rp.build_reservation_memo(candidate), "")


if __name__ == "__main__":
    unittest.main()
