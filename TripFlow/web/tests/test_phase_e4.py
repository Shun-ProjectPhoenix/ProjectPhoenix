"""Phase E-4「予約日と出張期間の自動マッチング」のテスト。

reservation_parser.resolve_registration_date()（登録候補から基準日を選ぶ）と
components.filter_matching_trips_for_candidate()（基準日が出張期間に
含まれる出張だけへ絞り込む）を検証する。ここで使う出張名・予約情報は
すべて人工的なサンプルであり、実際のメール・個人情報とは無関係。
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reservation_parser as rp
from components import filter_matching_trips_for_candidate


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


def _make_trip(trip_id: int, start: str, end: str) -> dict:
    """filter_matching_trips_for_candidate()向けのTrip代替オブジェクト。

    実装はsqlite3.Row同様trip["start_date"]の形でしかアクセスしないため、
    テストでは実DBを使わずdictで代用する。
    """
    return {"id": trip_id, "name": f"テスト出張{trip_id}", "start_date": start, "end_date": end}


class ResolveRegistrationDateTests(unittest.TestCase):
    def test_transit_uses_date(self) -> None:
        candidate = _make_candidate(
            reservation_type="電車", date=date(2026, 9, 1), checkin_date=None
        )
        self.assertEqual(rp.resolve_registration_date(candidate), date(2026, 9, 1))

    def test_flight_uses_date(self) -> None:
        candidate = _make_candidate(
            service="スカイマーク",
            reservation_type="飛行機",
            date=date(2026, 9, 2),
            checkin_date=None,
        )
        self.assertEqual(rp.resolve_registration_date(candidate), date(2026, 9, 2))

    def test_hotel_uses_checkin_date_not_date(self) -> None:
        candidate = _make_candidate(
            service="Agoda",
            reservation_type="ホテル",
            date=date(2026, 9, 9),
            checkin_date=date(2026, 9, 3),
            checkout_date=date(2026, 9, 5),
        )
        # ホテルはcheckin_dateを基準日とし、（仮にdateが別値でも）優先しない。
        self.assertEqual(rp.resolve_registration_date(candidate), date(2026, 9, 3))

    def test_transit_date_none_returns_none(self) -> None:
        candidate = _make_candidate(reservation_type="電車", date=None)
        self.assertIsNone(rp.resolve_registration_date(candidate))

    def test_hotel_checkin_date_none_returns_none(self) -> None:
        candidate = _make_candidate(
            service="Agoda", reservation_type="ホテル", date=None, checkin_date=None
        )
        self.assertIsNone(rp.resolve_registration_date(candidate))


class FilterMatchingTripsForCandidateTests(unittest.TestCase):
    def test_date_within_trip_range_is_included(self) -> None:
        trip = _make_trip(1, "2026-08-20", "2026-08-25")
        result = filter_matching_trips_for_candidate([trip], date(2026, 8, 22))
        self.assertEqual(result, [trip])

    def test_date_equal_to_start_date_is_included(self) -> None:
        trip = _make_trip(1, "2026-08-20", "2026-08-25")
        result = filter_matching_trips_for_candidate([trip], date(2026, 8, 20))
        self.assertEqual(result, [trip])

    def test_date_equal_to_end_date_is_included(self) -> None:
        trip = _make_trip(1, "2026-08-20", "2026-08-25")
        result = filter_matching_trips_for_candidate([trip], date(2026, 8, 25))
        self.assertEqual(result, [trip])

    def test_date_outside_trip_range_is_excluded(self) -> None:
        trip = _make_trip(1, "2026-08-20", "2026-08-25")
        result = filter_matching_trips_for_candidate([trip], date(2026, 8, 26))
        self.assertEqual(result, [])

    def test_no_matching_trip_returns_empty_list(self) -> None:
        trips = [
            _make_trip(1, "2026-08-12", "2026-08-14"),
            _make_trip(2, "2026-09-01", "2026-09-03"),
        ]
        result = filter_matching_trips_for_candidate(trips, date(2026, 8, 24))
        self.assertEqual(result, [])

    def test_single_matching_trip_among_others_is_selected(self) -> None:
        trip_a = _make_trip(1, "2026-08-12", "2026-08-14")
        trip_b = _make_trip(2, "2026-08-24", "2026-08-28")
        result = filter_matching_trips_for_candidate(
            [trip_a, trip_b], date(2026, 8, 24)
        )
        self.assertEqual(result, [trip_b])

    def test_multiple_matching_trips_are_all_returned_and_non_matching_excluded(
        self,
    ) -> None:
        trip_a = _make_trip(1, "2026-08-20", "2026-08-30")
        trip_b = _make_trip(2, "2026-08-22", "2026-08-24")
        trip_c = _make_trip(3, "2026-09-10", "2026-09-12")
        result = filter_matching_trips_for_candidate(
            [trip_a, trip_b, trip_c], date(2026, 8, 23)
        )
        self.assertEqual(result, [trip_a, trip_b])

    def test_empty_trip_list_returns_empty_list(self) -> None:
        self.assertEqual(
            filter_matching_trips_for_candidate([], date(2026, 8, 22)), []
        )


if __name__ == "__main__":
    unittest.main()
