"""Web v0.4 Phase D（スマートEX・スカイマーク対応）のテスト。

スマートEX・スカイマークの実際のメール件名・本文はまだ一度も確認して
いないため、ここで使う本文・件名はすべて実際のメールとは無関係な
人工的なサンプルである。実在の予約番号・便名・氏名等は使用しない。
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gmail_service as gs
import reservation_parser as rp


class SupportedServicesTests(unittest.TestCase):
    def test_four_services_supported(self) -> None:
        self.assertEqual(
            set(gs.SUPPORTED_SERVICES),
            {"えきねっと", "Agoda", "スマートEX", "スカイマーク"},
        )


class BuildSearchQueryTests(unittest.TestCase):
    def test_smart_ex_query_includes_domain_and_keyword(self) -> None:
        # Phase D実機確認により、実際の送信元ドメインがexpy.jpであることを
        # 確認した。初期案だったsmart-ex.jpも、実送信元として未確認ながら
        # 引き続き候補に残しているため、両方がクエリに含まれることを確認する。
        query = gs.build_search_query("スマートEX", months=3)
        self.assertIn("from:expy.jp", query)
        self.assertIn("from:smart-ex.jp", query)
        self.assertIn("subject:スマートEX", query)
        self.assertIn("after:", query)

    def test_skymark_query_includes_domain_and_keyword(self) -> None:
        query = gs.build_search_query("スカイマーク", months=3)
        self.assertIn("from:skymark.co.jp", query)
        self.assertIn("subject:スカイマーク", query)
        self.assertIn("after:", query)

    def test_search_period_option_unaffected(self) -> None:
        # 検索期間の指定方法（months引数）自体はPhase Dで変更していない。
        query_short = gs.build_search_query("スマートEX", months=1)
        query_long = gs.build_search_query("スマートEX", months=12)
        self.assertNotEqual(query_short, query_long)


class ServiceDedupTests(unittest.TestCase):
    """4サービスを指定した検索で、サービスごとに正しく候補が識別されることを確認する。"""

    def test_search_reservation_candidates_tags_each_service(self) -> None:
        from unittest.mock import patch

        list_payloads = {
            "えきねっと": {"messages": [{"id": "ekinet-1"}]},
            "Agoda": {"messages": [{"id": "agoda-1"}]},
            "スマートEX": {"messages": [{"id": "smartex-1"}]},
            "スカイマーク": {"messages": [{"id": "skymark-1"}]},
        }
        summary_payloads = {
            "ekinet-1": {"id": "ekinet-1", "internalDate": "1", "snippet": "", "payload": {"headers": []}},
            "agoda-1": {"id": "agoda-1", "internalDate": "2", "snippet": "", "payload": {"headers": []}},
            "smartex-1": {"id": "smartex-1", "internalDate": "3", "snippet": "", "payload": {"headers": []}},
            "skymark-1": {"id": "skymark-1", "internalDate": "4", "snippet": "", "payload": {"headers": []}},
        }

        class FakeResponse:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        def fake_get(url, *, headers, params, timeout):
            if url.endswith("/messages"):
                query = params["q"]
                for service, payload in list_payloads.items():
                    if service in query or gs.SERVICE_SEARCH_RULES[service]["from_domains"][0] in query:
                        return FakeResponse(payload)
                return FakeResponse({"messages": []})
            message_id = url.rsplit("/", 1)[-1]
            return FakeResponse(summary_payloads[message_id])

        with patch("gmail_service.httpx.get", side_effect=fake_get):
            candidates = gs.search_reservation_candidates(
                "FAKE-TOKEN",
                ["えきねっと", "Agoda", "スマートEX", "スカイマーク"],
                months=3,
            )

        services_by_id = {c.message_id: c.service for c in candidates}
        self.assertEqual(services_by_id.get("ekinet-1"), "えきねっと")
        self.assertEqual(services_by_id.get("agoda-1"), "Agoda")
        self.assertEqual(services_by_id.get("smartex-1"), "スマートEX")
        self.assertEqual(services_by_id.get("skymark-1"), "スカイマーク")


class ClassifySmartExTests(unittest.TestCase):
    def test_campaign_email_is_excluded(self) -> None:
        relevance = rp.classify_candidate("スマートEX", "【スマートEX】お得なキャンペーンのご案内")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_review_request_is_excluded(self) -> None:
        relevance = rp.classify_candidate("スマートEX", "ご利用のレビューをお願いします")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_advertisement_is_excluded(self) -> None:
        relevance = rp.classify_candidate("スマートEX", "新機能の広告のお知らせ")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_reservation_confirmation_style_subject_is_target(self) -> None:
        # Phase D実機確認（スマートEX1回目）で、実際の予約メール本文構造
        # （乗車日・区間・列車名・号車・座席・お預かり番号）を確認できた。
        # 件名文言自体はまだ確認できていないが、えきねっと・Agodaの両方で
        # 有効だった汎用的な予約確認語彙を流用してTARGETに分類する。
        relevance = rp.classify_candidate("スマートEX", "【スマートEX】ご予約内容")
        self.assertEqual(relevance, rp.RELEVANCE_TARGET)
        self.assertTrue(rp.can_analyze(relevance))

    def test_unrelated_subject_without_target_keywords_is_unknown(self) -> None:
        # 対象外にも対象にも一致しない件名は判定不能となり、ユーザーが手動で
        # 解析を試せる。
        relevance = rp.classify_candidate("スマートEX", "【スマートEX】パスワード再設定について")
        self.assertEqual(relevance, rp.RELEVANCE_UNKNOWN)
        self.assertTrue(rp.can_analyze(relevance))

    def test_shinkansen_reservation_content_subject_is_target(self) -> None:
        # Phase D実機確認（スマートEX2回目）で確認できた、実際の予約メール
        # 件名に含まれる語「新幹線予約内容」がTARGETに分類されることを確認する。
        relevance = rp.classify_candidate("スマートEX", "【スマートEX】新幹線予約内容")
        self.assertEqual(relevance, rp.RELEVANCE_TARGET)
        self.assertTrue(rp.can_analyze(relevance))

    def test_sale_and_sightseeing_emails_remain_excluded(self) -> None:
        # 実機確認で、スマートEX関連のセール・観光プランメールが正しく
        # 対象外と判定されたことを確認済み。この挙動が壊れていないことを
        # 回帰確認する。
        relevance_sale = rp.classify_candidate("スマートEX", "【スマートEX】早期予約セールのご案内")
        self.assertEqual(relevance_sale, rp.RELEVANCE_EXCLUDED)

        relevance_campaign = rp.classify_candidate(
            "スマートEX", "新幹線で行く観光プランキャンペーン"
        )
        self.assertEqual(relevance_campaign, rp.RELEVANCE_EXCLUDED)

    def test_service_name_alone_does_not_force_target(self) -> None:
        # 「スマートEX」という文字があるだけで対象にしないことの確認
        # （EXCLUDEDキーワードを含む場合は対象にならない）。
        relevance = rp.classify_candidate("スマートEX", "スマートEXからの重要なお知らせ")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_ic_card_designation_email_is_supplementary(self) -> None:
        # 実機確認（3回目）で判明した「乗車用ICカード指定内容」メールは、
        # 対象外ではなく予約補完メール（RELEVANCE_SUPPLEMENTARY）に分類する。
        # えきねっとの「座席番号のご案内」と同じ考え方。
        relevance = rp.classify_candidate("スマートEX", "【スマートEX】乗車用ICカード指定内容")
        self.assertEqual(relevance, rp.RELEVANCE_SUPPLEMENTARY)
        self.assertTrue(rp.can_analyze(relevance))


class ClassifySkymarkTests(unittest.TestCase):
    def test_campaign_email_is_excluded(self) -> None:
        relevance = rp.classify_candidate("スカイマーク", "夏の早期予約セール開催中")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_review_request_is_excluded(self) -> None:
        relevance = rp.classify_candidate("スカイマーク", "ご搭乗後アンケートのお願い")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_unknown_subject_without_target_keywords_is_unknown(self) -> None:
        relevance = rp.classify_candidate("スカイマーク", "【スカイマーク】ご予約内容")
        self.assertEqual(relevance, rp.RELEVANCE_UNKNOWN)
        self.assertTrue(rp.can_analyze(relevance))

    def test_card_payment_completed_purchased_is_target(self) -> None:
        # 実機確認で判明した件名種別①：カード決済完了【購入済】
        relevance = rp.classify_candidate("スカイマーク", "スカイマーク カード決済完了【購入済】")
        self.assertEqual(relevance, rp.RELEVANCE_TARGET)
        self.assertTrue(rp.can_analyze(relevance))

    def test_payment_information_confirmation_is_target(self) -> None:
        # 実機確認で判明した件名種別②：確認メール【お支払情報】
        relevance = rp.classify_candidate("スカイマーク", "スカイマーク 確認メール【お支払情報】")
        self.assertEqual(relevance, rp.RELEVANCE_TARGET)
        self.assertTrue(rp.can_analyze(relevance))

    def test_seat_designation_completed_is_supplementary(self) -> None:
        # 実機確認で判明した件名種別③：【座席指定完了のご案内】
        relevance = rp.classify_candidate("スカイマーク", "スカイマーク【座席指定完了のご案内】")
        self.assertEqual(relevance, rp.RELEVANCE_SUPPLEMENTARY)
        self.assertTrue(rp.can_analyze(relevance))

    def test_unpurchased_reservation_completed_remains_unknown(self) -> None:
        # 実機確認で判明した件名種別④：予約完了【未購入】。
        # 未購入・支払い待ち状態を安全に表現する仕組みがまだ無いため、
        # 今回はあえてTARGETに追加せず判定不能のまま維持する
        # （ユーザーが手動で解析を試すことは引き続き可能）。
        relevance = rp.classify_candidate("スカイマーク", "スカイマーク 予約完了【未購入】")
        self.assertEqual(relevance, rp.RELEVANCE_UNKNOWN)
        self.assertTrue(rp.can_analyze(relevance))

    def test_day_before_boarding_notice_is_excluded(self) -> None:
        # 実機確認で判明した件名種別⑤：搭乗日前日のお知らせ。
        # 既存の「お知らせ」キーワードで既にEXCLUDEDになっており、
        # 変更していないことの回帰確認。
        relevance = rp.classify_candidate("スカイマーク", "スカイマーク 搭乗日前日のお知らせ")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_service_name_alone_does_not_force_target(self) -> None:
        relevance = rp.classify_candidate("スカイマーク", "スカイマークからの重要なお知らせ")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)


class ExtractSmartExTests(unittest.TestCase):
    """架空データによる、ラベル形式の汎用抽出（土台実装）の確認。"""

    def test_extracts_labeled_fields(self) -> None:
        body = (
            "ご乗車日：2026年10月05日\n"
            "出発駅：サンプル駅　出発時刻：08:00\n"
            "到着駅：見本駅　到着時刻：09:30\n"
            "列車名：サンプル3号\n"
            "号車：7号車\n"
            "座席番号：12A\n"
            "予約番号：SE-0001234\n"
        )
        candidate = rp.extract_smart_ex(
            "msg-smartex-1", rp.RELEVANCE_TARGET, "【スマートEX】ご予約内容", body
        )

        self.assertEqual(candidate.service, "スマートEX")
        self.assertEqual(candidate.reservation_type, "電車")
        self.assertEqual(candidate.date, date(2026, 10, 5))
        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")
        self.assertEqual(candidate.train_name, "サンプル3号")
        self.assertEqual(candidate.car_number, "7号車")
        self.assertEqual(candidate.seat_number, "12A")
        self.assertEqual(candidate.reservation_reference, "SE-0001234")
        self.assertEqual(candidate.confidence, "高")
        self.assertIsNone(candidate.flight_number)

    def test_empty_body_returns_all_none_and_low_confidence(self) -> None:
        candidate = rp.extract_smart_ex(
            "msg-smartex-2", rp.RELEVANCE_UNKNOWN, "件名", ""
        )

        self.assertIsNone(candidate.date)
        self.assertIsNone(candidate.origin)
        self.assertIsNone(candidate.destination)
        self.assertIsNone(candidate.train_name)
        self.assertIsNone(candidate.reservation_reference)
        self.assertEqual(candidate.confidence, "低")
        self.assertEqual(len(candidate.missing_fields), len(rp._SMART_EX_FIELD_LABELS))

    def test_station_time_route_structure_is_now_supported(self) -> None:
        # Phase D実機確認（スマートEX1回目）により、えきねっとと同じ
        # 「駅名(時刻) → 駅名(時刻)」構造が実際に使われていることが確認
        # できたため、この構造からの抽出をスマートEXでも有効にした。
        # 駅名・時刻とも固定値ではなく、構造そのものから抽出する。
        body = "サンプル駅(08時00分) → 見本駅(09時30分)\n"
        candidate = rp.extract_smart_ex(
            "msg-smartex-3", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")

    def test_station_time_route_different_stations_not_hardcoded(self) -> None:
        # 別の駅名・時刻でも動作することの確認（駅名をハードコードしていない）。
        body = "出発地(07時05分) → 到着地(21時40分)\n"
        candidate = rp.extract_smart_ex(
            "msg-smartex-3b", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "出発地")
        self.assertEqual(candidate.destination, "到着地")
        self.assertEqual(candidate.start_time, "07:05")
        self.assertEqual(candidate.end_time, "21:40")

    def test_train_name_recognized_without_explicit_label(self) -> None:
        # 「列車名：」ラベルが無くても、公表されている列車種別名（公開情報）
        # ＋「号」の構造から列車名を認識できることを確認する。
        body = "サンプル駅(08時00分) → 見本駅(09時30分)\nのぞみ99号\n"
        candidate = rp.extract_smart_ex(
            "msg-smartex-4", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.train_name, "のぞみ99号")

    def test_train_name_does_not_swallow_adjacent_arrow(self) -> None:
        # 回帰テスト：列車名の直前に矢印が空白無しで隣接する構造
        # （「→のぞみ99号」等）で、矢印自体を列車名に取り込まないことを確認する
        # （3区間構造のテスト作成中にコード調査で発見した不具合の再発防止）。
        body = "サンプル駅(08時00分)\n→のぞみ99号→\n見本駅(09時30分)\n"
        candidate = rp.extract_smart_ex(
            "msg-smartex-4b", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.train_name, "のぞみ99号")
        self.assertNotIn("→", candidate.train_name)

    def test_standalone_seat_number_without_label_or_car_adjacency(self) -> None:
        # 「座席番号：」「座席」のようなラベルが一切無く、かつ「号車」に直接
        # 隣接してもいない「M番X席」という単独の構造からも座席番号を
        # 取得できることを確認する（ラベル方式では拾えないケース）。
        body = "号車：8号車\n\n19番A席\n"
        candidate = rp.extract_smart_ex(
            "msg-smartex-5", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.car_number, "8号車")
        self.assertEqual(candidate.seat_number, "19番A席")

    def test_standalone_seat_number_with_whitespace_variations(self) -> None:
        # 空白・改行の揺れ（全角スペース、改行を挟む等）があっても
        # 座席番号を取得できることを確認する。
        body = "19　番　A　席\n"  # 全角スペースを挟む
        candidate = rp.extract_smart_ex(
            "msg-smartex-6", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.seat_number, "19番A席")

    def test_standalone_seat_number_with_fullwidth_letter(self) -> None:
        # 座席アルファベットが全角文字（Ａ-Ｚ）の場合も取得できることを確認する。
        body = "19番Ａ席\n"
        candidate = rp.extract_smart_ex(
            "msg-smartex-7", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.seat_number, "19番Ａ席")

    def test_reservation_reference_via_deposit_number_label(self) -> None:
        # 実機確認で判明した「お預かり番号」ラベルからの予約識別情報取得を確認する。
        body = "お預かり番号：EX1234567\n"
        candidate = rp.extract_smart_ex(
            "msg-smartex-8", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.reservation_reference, "EX1234567")

    def test_amount_extraction(self) -> None:
        # ReservationCandidateに既存のamountフィールドをそのまま再利用する。
        # 既存のラベル形式（「運賃：」等）が引き続き動作することの確認。
        body = "運賃：12,000円\n"
        candidate = rp.extract_smart_ex(
            "msg-smartex-9", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.amount, 12000)

    def test_full_confirmed_structure_yields_high_confidence(self) -> None:
        # 実機確認で判明した一連の構造（乗車日→区間(時刻)→列車名→号車→
        # 座席→お預かり番号）をまとめて再現したケース。
        body = (
            "乗車日：2026年10月05日\n"
            "サンプル駅(08時00分) → 見本駅(09時30分)\n"
            "のぞみ99号\n"
            "8号車\n"
            "19番A席\n"
            "お預かり番号：EX1234567\n"
        )
        candidate = rp.extract_smart_ex(
            "msg-smartex-10", rp.RELEVANCE_TARGET, "【スマートEX】ご予約内容", body
        )

        self.assertEqual(candidate.date, date(2026, 10, 5))
        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")
        self.assertEqual(candidate.train_name, "のぞみ99号")
        self.assertEqual(candidate.car_number, "8号車")
        self.assertEqual(candidate.seat_number, "19番A席")
        self.assertEqual(candidate.reservation_reference, "EX1234567")
        self.assertEqual(candidate.confidence, "高")


class ExtractSmartExThreeHopRouteTests(unittest.TestCase):
    """Phase D実機再確認（スマートEX2回目）で判明した「駅名(時刻) → 列車名 →
    駅名(時刻)」構造（架空データで再現）。実メール本文・実在の駅名・
    列車番号・座席番号は使用しない。
    """

    def test_three_hop_structure_extracts_stations_and_times(self) -> None:
        # 駅名・時刻・列車名とも固定値ではなく、構造そのものから抽出する。
        body = "サンプル駅(08時00分) → のぞみ99号 → 見本駅(09時30分)\n"
        candidate = rp.extract_smart_ex(
            "msg-3hop-1", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")

    def test_three_hop_structure_different_stations_and_train(self) -> None:
        # 別の駅名・列車名でも動作することの確認（ハードコードしていない）。
        body = "出発地(07時05分) → ひかり1号 → 到着地(21時40分)\n"
        candidate = rp.extract_smart_ex(
            "msg-3hop-2", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "出発地")
        self.assertEqual(candidate.destination, "到着地")
        self.assertEqual(candidate.start_time, "07:05")
        self.assertEqual(candidate.end_time, "21:40")

    def test_two_hop_direct_adjacency_pattern_still_supported(self) -> None:
        # 「駅名(時刻) → 駅名(時刻)」という直接隣接構造（既存パターン）が
        # 引き続き動作することを確認する（1. 既存パターンを維持する）。
        body = "サンプル駅(08時00分) → 見本駅(09時30分)\n"
        candidate = rp.extract_smart_ex(
            "msg-3hop-3", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")

    def test_three_hop_structure_with_linebreaks(self) -> None:
        # HTML→text変換由来の改行が各区間の間に入るケース。
        body = "サンプル駅(08時00分)\n→\nのぞみ99号\n→\n見本駅(09時30分)\n"
        candidate = rp.extract_smart_ex(
            "msg-3hop-4", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")

    def test_three_hop_structure_with_extra_whitespace(self) -> None:
        # 全角スペースを含む余分な空白があるケース。
        body = "サンプル駅(08時00分)　→　のぞみ99号　→　見本駅(09時30分)\n"
        candidate = rp.extract_smart_ex(
            "msg-3hop-5", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")

    def test_three_hop_structure_does_not_override_labeled_values(self) -> None:
        # ラベル形式で明示的に取得できた値は、構造パターンによる補完で
        # 上書きしない。
        body = (
            "出発駅：ラベル駅　出発時刻：10:00\n"
            "到着駅：ラベル到着駅　到着時刻：11:20\n"
            "ラベル駅(08時00分) → のぞみ99号 → ラベル到着駅(09時30分)\n"
        )
        candidate = rp.extract_smart_ex(
            "msg-3hop-6", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.start_time, "10:00")
        self.assertEqual(candidate.end_time, "11:20")

    def test_full_confirmed_three_hop_structure_yields_high_confidence_and_amount(
        self,
    ) -> None:
        # 実機確認で判明した3区間構造（乗車日→駅名(時刻)→列車名→駅名(時刻)→
        # 号車→座席→お預かり番号→料金）をまとめて再現したケース。
        body = (
            "乗車日：2026年10月05日\n"
            "サンプル駅(08時00分) → のぞみ99号 → 見本駅(09時30分)\n"
            "8号車\n"
            "19番A席\n"
            "お預かり番号：EX1234567\n"
            "運賃：12,000円\n"
        )
        candidate = rp.extract_smart_ex(
            "msg-3hop-7", rp.RELEVANCE_TARGET, "【スマートEX】新幹線予約内容", body
        )

        self.assertEqual(candidate.date, date(2026, 10, 5))
        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")
        self.assertEqual(candidate.train_name, "のぞみ99号")
        self.assertEqual(candidate.car_number, "8号車")
        self.assertEqual(candidate.seat_number, "19番A席")
        self.assertEqual(candidate.reservation_reference, "EX1234567")
        self.assertEqual(candidate.amount, 12000)
        self.assertEqual(candidate.confidence, "高")


class ExtractSmartExColonTimeRouteTests(unittest.TestCase):
    """Phase D実機再確認（スマートEX3回目）で判明した構造の回帰テスト。

    「駅名(時刻) → 列車名 → 駅名(時刻)」自体は2回目の実機確認で判明した
    構造だが、3回目の実機確認では、時刻表記が「○時○分」ではなく
    「○:○」（コロン区切り）だった場合に一致しないという不具合が
    コード調査により判明した（原因の詳細はclaude_report.md参照）。
    実メール本文・実在の駅名・列車番号・座席番号は使用しない。
    """

    def test_two_hop_route_with_colon_time(self) -> None:
        body = "サンプル駅(08:00) → 見本駅(09:30)\n"
        candidate = rp.extract_smart_ex(
            "msg-colon-1", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")

    def test_three_hop_route_with_colon_time(self) -> None:
        # 実機確認で報告された「→列車名→」が改行を挟んで隣接する構造
        # （矢印と列車名の間に空白が無い）を、コロン区切り時刻とあわせて再現する。
        body = "サンプル駅(08:00)\n→のぞみ99号→\n見本駅(09:30)\n"
        candidate = rp.extract_smart_ex(
            "msg-colon-2", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")

    def test_three_hop_route_with_colon_time_different_stations(self) -> None:
        # 別の駅名・時刻・列車名でも動作することの確認（ハードコードしていない）。
        body = "出発地(23:55)\n→ひかり1号→\n到着地(01:10)\n"
        candidate = rp.extract_smart_ex(
            "msg-colon-3", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.origin, "出発地")
        self.assertEqual(candidate.destination, "到着地")
        self.assertEqual(candidate.start_time, "23:55")
        self.assertEqual(candidate.end_time, "01:10")

    def test_colon_time_with_fullwidth_colon(self) -> None:
        # 全角コロン（：）による時刻表記のケース。
        body = "サンプル駅(08：00) → 見本駅(09：30)\n"
        candidate = rp.extract_smart_ex(
            "msg-colon-4", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")

    def test_kanji_time_route_still_takes_priority_when_present(self) -> None:
        # 既存の「○時○分」形式（えきねっとと共用のパターン）が引き続き
        # 最優先で使われることの確認（1. 既存パターンを維持する）。
        body = "サンプル駅(08時00分) → 見本駅(09時30分)\n"
        candidate = rp.extract_smart_ex(
            "msg-colon-5", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")

    def test_colon_time_does_not_override_labeled_values(self) -> None:
        body = (
            "出発時刻：10:00\n"
            "到着時刻：11:20\n"
            "ラベル駅(08:00) → 見本駅(09:30)\n"
        )
        candidate = rp.extract_smart_ex(
            "msg-colon-6", rp.RELEVANCE_TARGET, "件名", body
        )

        self.assertEqual(candidate.start_time, "10:00")
        self.assertEqual(candidate.end_time, "11:20")

    def test_full_confirmed_structure_with_colon_time_yields_high_confidence(
        self,
    ) -> None:
        # 実機確認で判明した一連の構造を、コロン区切り時刻で再現したケース。
        body = (
            "乗車日：2026年10月05日\n"
            "サンプル駅(08:00)\n→のぞみ99号→\n見本駅(09:30)\n"
            "8号車\n"
            "19番A席\n"
            "お預かり番号：EX1234567\n"
        )
        candidate = rp.extract_smart_ex(
            "msg-colon-7", rp.RELEVANCE_TARGET, "【スマートEX】新幹線予約内容", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")
        self.assertEqual(candidate.train_name, "のぞみ99号")
        self.assertEqual(candidate.confidence, "高")


class ExtractSmartExSentenceFormAmountTests(unittest.TestCase):
    """Phase D実機再確認（スマートEX4回目）で判明した、料金が文章形式
    （「領収額は、合計XXXX円です。」）で表示される構造の回帰テスト。
    実メール本文・実際の金額は使用しない（架空の金額のみ）。
    """

    def test_sentence_form_amount_baseline(self) -> None:
        body = "領収額は、合計12,345円です。"
        candidate = rp.extract_smart_ex(
            "msg-amount-1", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.amount, 12345)

    def test_sentence_form_amount_without_comma(self) -> None:
        body = "領収額は、合計999円です。"
        candidate = rp.extract_smart_ex(
            "msg-amount-2", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.amount, 999)

    def test_sentence_form_amount_with_fullwidth_space(self) -> None:
        # 「合計」と金額の間に全角スペースが入るケース。
        body = "領収額は、合計　12,345円です。"
        candidate = rp.extract_smart_ex(
            "msg-amount-3", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.amount, 12345)

    def test_sentence_form_amount_with_halfwidth_space(self) -> None:
        body = "領収額は、合計 12,345円です。"
        candidate = rp.extract_smart_ex(
            "msg-amount-4", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.amount, 12345)

    def test_existing_labeled_amount_still_works(self) -> None:
        # 既存のラベル形式（「料金：」等）を壊していないことの回帰確認。
        for label in ("運賃", "料金", "合計金額", "合計料金", "お支払い金額"):
            with self.subTest(label=label):
                body = f"{label}：8,800円\n"
                candidate = rp.extract_smart_ex(
                    f"msg-amount-label-{label}", rp.RELEVANCE_TARGET, "件名", body
                )
                self.assertEqual(candidate.amount, 8800)

    def test_unrelated_numbers_are_not_captured_as_amount(self) -> None:
        # 「領収額」「合計」という語の近接がなければ、本文中の他の数字
        # （会員番号・予約番号・列車番号・日付・時刻・ICカード番号等）を
        # 料金として誤って取得しないことを確認する。
        body = (
            "会員番号：1234567890\n"
            "予約番号：AB1234567\n"
            "のぞみ123号\n"
            "乗車日：2026年10月05日\n"
            "出発時刻：08:00\n"
            "ICカード番号：9999888877776666\n"
        )
        candidate = rp.extract_smart_ex(
            "msg-amount-5", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertIsNone(candidate.amount)

    def test_amount_word_without_total_word_is_not_captured(self) -> None:
        # 「領収額」はあるが「合計」が近くにない場合は誤って取得しない
        # （構造の一部だけが偶然一致しても採用しないことの確認）。
        body = "領収額に関するお問い合わせはこちらのメールアドレスまでご連絡ください。12345\n"
        candidate = rp.extract_smart_ex(
            "msg-amount-6", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertIsNone(candidate.amount)

    def test_total_word_without_amount_word_is_not_captured(self) -> None:
        # 「合計」はあるが「領収額」が近くにない場合は誤って取得しない。
        body = "合計12,345円のお買い物でポイント進呈中のキャンペーンです。\n"
        candidate = rp.extract_smart_ex(
            "msg-amount-7", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertIsNone(candidate.amount)

    def test_full_confirmed_structure_with_sentence_form_amount(self) -> None:
        # 実機確認で判明した一連の構造を、文章形式の料金とあわせて再現する。
        body = (
            "乗車日：2026年10月05日\n"
            "サンプル駅(08:00)\n→のぞみ99号→\n見本駅(09:30)\n"
            "8号車\n"
            "19番A席\n"
            "お預かり番号：EX1234567\n"
            "領収額は、合計12,345円です。\n"
        )
        candidate = rp.extract_smart_ex(
            "msg-amount-8", rp.RELEVANCE_TARGET, "【スマートEX】新幹線予約内容", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "08:00")
        self.assertEqual(candidate.end_time, "09:30")
        self.assertEqual(candidate.train_name, "のぞみ99号")
        self.assertEqual(candidate.car_number, "8号車")
        self.assertEqual(candidate.seat_number, "19番A席")
        self.assertEqual(candidate.reservation_reference, "EX1234567")
        self.assertEqual(candidate.amount, 12345)
        self.assertEqual(candidate.confidence, "高")


class ExtractSkymarkTests(unittest.TestCase):
    """架空データによる、ラベル形式の汎用抽出（土台実装）の確認。"""

    def test_extracts_labeled_fields(self) -> None:
        body = (
            "ご搭乗日：2026年11月01日\n"
            "出発空港：サンプル空港　出発時刻：07:15\n"
            "到着空港：見本空港　到着時刻：08:45\n"
            "便名：BC123\n"
            "予約番号：SK-0009876\n"
        )
        candidate = rp.extract_skymark(
            "msg-skymark-1", rp.RELEVANCE_TARGET, "【スカイマーク】ご予約完了", body
        )

        self.assertEqual(candidate.service, "スカイマーク")
        self.assertEqual(candidate.reservation_type, "飛行機")
        self.assertEqual(candidate.date, date(2026, 11, 1))
        self.assertEqual(candidate.origin, "サンプル空港")
        self.assertEqual(candidate.destination, "見本空港")
        self.assertEqual(candidate.start_time, "07:15")
        self.assertEqual(candidate.end_time, "08:45")
        self.assertEqual(candidate.flight_number, "BC123")
        self.assertEqual(candidate.reservation_reference, "SK-0009876")
        self.assertEqual(candidate.confidence, "高")
        self.assertIsNone(candidate.train_name)
        self.assertIsNone(candidate.car_number)
        self.assertIsNone(candidate.seat_number)

    def test_empty_body_returns_all_none_and_low_confidence(self) -> None:
        candidate = rp.extract_skymark(
            "msg-skymark-2", rp.RELEVANCE_UNKNOWN, "件名", ""
        )

        self.assertIsNone(candidate.date)
        self.assertIsNone(candidate.origin)
        self.assertIsNone(candidate.destination)
        self.assertIsNone(candidate.flight_number)
        self.assertIsNone(candidate.reservation_reference)
        self.assertEqual(candidate.confidence, "低")
        self.assertEqual(len(candidate.missing_fields), len(rp._SKYMARK_FIELD_LABELS))


class ExtractSkymarkConfirmedStructureTests(unittest.TestCase):
    """Phase D後半の実機確認で判明した、スカイマーク実メールの構造
    （架空データで再現）。実メール本文・実在の予約番号・便名・搭乗日・
    時刻は使用しない。
    """

    def test_bare_date_without_label(self) -> None:
        # 「YYYY年MM月DD日(曜日)」というラベル無し構造からの搭乗日抽出。
        body = "2026年09月10日(木)\n"
        candidate = rp.extract_skymark(
            "msg-sky-date-1", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.date, date(2026, 9, 10))

    def test_bare_date_without_weekday(self) -> None:
        body = "2026年9月10日\n"
        candidate = rp.extract_skymark(
            "msg-sky-date-2", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.date, date(2026, 9, 10))

    def test_bare_date_with_fullwidth_parentheses_weekday(self) -> None:
        body = "2026年09月10日（木）\n"
        candidate = rp.extract_skymark(
            "msg-sky-date-3", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.date, date(2026, 9, 10))

    def test_flight_number_with_sky_prefix(self) -> None:
        # 「SKY 123便」構造からの便名抽出。便番号は固定値にしない
        # （別の番号でも動作することを別テストで確認する）。
        body = "SKY 123便\n"
        candidate = rp.extract_skymark(
            "msg-sky-flight-1", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.flight_number, "SKY 123便")

    def test_flight_number_with_sky_prefix_different_number(self) -> None:
        body = "SKY 456便\n"
        candidate = rp.extract_skymark(
            "msg-sky-flight-2", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.flight_number, "SKY 456便")

    def test_flight_number_without_sky_prefix(self) -> None:
        # "SKY"表記が無い場合でも「数字＋便」の構造から取得できることの確認。
        body = "789便\n"
        candidate = rp.extract_skymark(
            "msg-sky-flight-3", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.flight_number, "789便")

    def test_route_extracts_airports_and_times(self) -> None:
        # 「空港名 発 HH:MM → 空港名 着 HH:MM」構造からの区間・時刻抽出。
        body = "サンプル空港 発 08:15 → 見本空港 着 10:10\n"
        candidate = rp.extract_skymark(
            "msg-sky-route-1", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.origin, "サンプル空港")
        self.assertEqual(candidate.destination, "見本空港")
        self.assertEqual(candidate.start_time, "08:15")
        self.assertEqual(candidate.end_time, "10:10")

    def test_route_different_airports_not_hardcoded(self) -> None:
        # 別の空港名でも動作することの確認。空港名自体に「発」「着」の
        # 文字を含めない（航空券の実際の空港名には通常含まれないため）。
        body = "ワンダー空港 発 23:55 → トゥエルブ空港 着 01:10\n"
        candidate = rp.extract_skymark(
            "msg-sky-route-2", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.origin, "ワンダー空港")
        self.assertEqual(candidate.destination, "トゥエルブ空港")
        self.assertEqual(candidate.start_time, "23:55")
        self.assertEqual(candidate.end_time, "01:10")

    def test_route_with_fullwidth_space_and_colon(self) -> None:
        body = "サンプル空港　発　08：15\n→\n見本空港　着　10：10\n"
        candidate = rp.extract_skymark(
            "msg-sky-route-3", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.origin, "サンプル空港")
        self.assertEqual(candidate.destination, "見本空港")
        self.assertEqual(candidate.start_time, "08:15")
        self.assertEqual(candidate.end_time, "10:10")

    def test_route_with_linebreaks_and_no_space_around_arrow(self) -> None:
        body = "サンプル空港\n発\n08:15\n→\n見本空港\n着\n10:10\n"
        candidate = rp.extract_skymark(
            "msg-sky-route-4", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.origin, "サンプル空港")
        self.assertEqual(candidate.destination, "見本空港")
        self.assertEqual(candidate.start_time, "08:15")
        self.assertEqual(candidate.end_time, "10:10")

    def test_route_does_not_override_labeled_values(self) -> None:
        body = (
            "出発空港：ラベル空港　出発時刻：10:00\n"
            "到着空港：ラベル到着空港　到着時刻：11:20\n"
            "ラベル空港 発 08:15 → ラベル到着空港 着 09:30\n"
        )
        candidate = rp.extract_skymark(
            "msg-sky-route-5", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.start_time, "10:00")
        self.assertEqual(candidate.end_time, "11:20")

    def test_reservation_reference_in_brackets(self) -> None:
        # 「[予約番号：XXXX]」のように角括弧で囲まれていても取得できることの確認。
        body = "[予約番号：5678]\n"
        candidate = rp.extract_skymark(
            "msg-sky-ref-1", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertEqual(candidate.reservation_reference, "5678")

    def test_fare_type_field_exists_but_is_not_extracted(self) -> None:
        # fare_typeフィールドは追加したが、抽出は今回保留している
        # （安全に判断できるラベル・構造上の目印が無いため）。
        body = "いま得\n"
        candidate = rp.extract_skymark(
            "msg-sky-fare-1", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertIsNone(candidate.fare_type)

    def test_full_confirmed_structure_yields_high_confidence(self) -> None:
        # 実機確認で判明した一連の構造をまとめて再現したケース。
        body = (
            "2026年09月10日(木)\n"
            "SKY 123便\n"
            "[予約番号：5678]\n"
            "サンプル空港 発 08:15 → 見本空港 着 10:10\n"
            "いま得\n"
        )
        candidate = rp.extract_skymark(
            "msg-sky-full-1", rp.RELEVANCE_TARGET, "スカイマーク カード決済完了【購入済】", body
        )

        self.assertEqual(candidate.date, date(2026, 9, 10))
        self.assertEqual(candidate.flight_number, "SKY 123便")
        self.assertEqual(candidate.reservation_reference, "5678")
        self.assertEqual(candidate.origin, "サンプル空港")
        self.assertEqual(candidate.destination, "見本空港")
        self.assertEqual(candidate.start_time, "08:15")
        self.assertEqual(candidate.end_time, "10:10")
        self.assertEqual(candidate.confidence, "高")
        self.assertIsNone(candidate.fare_type)


class AnalyzeEmailDispatchPhaseDTests(unittest.TestCase):
    def test_dispatches_to_smart_ex(self) -> None:
        candidate = rp.analyze_email(
            service="スマートEX",
            message_id="msg-dispatch-1",
            relevance=rp.RELEVANCE_TARGET,
            subject="件名",
            text_plain="出発駅：サンプル駅\n",
            text_html="",
        )
        self.assertEqual(candidate.service, "スマートEX")
        self.assertEqual(candidate.reservation_type, "電車")

    def test_dispatches_to_skymark(self) -> None:
        candidate = rp.analyze_email(
            service="スカイマーク",
            message_id="msg-dispatch-2",
            relevance=rp.RELEVANCE_TARGET,
            subject="件名",
            text_plain="出発空港：サンプル空港\n",
            text_html="",
        )
        self.assertEqual(candidate.service, "スカイマーク")
        self.assertEqual(candidate.reservation_type, "飛行機")


class ExistingServicesUnaffectedTests(unittest.TestCase):
    """Phase D追加（flight_numberフィールド等）が既存のえきねっと・Agoda抽出に
    影響していないことを確認する。
    """

    def test_ekinet_candidate_has_no_flight_number(self) -> None:
        candidate = rp.extract_ekinet(
            "msg-regress-1", rp.RELEVANCE_TARGET, "件名", "ご乗車日：2026年09月10日\n"
        )
        self.assertIsNone(candidate.flight_number)

    def test_agoda_candidate_has_no_flight_number(self) -> None:
        candidate = rp.extract_agoda(
            "msg-regress-2", rp.RELEVANCE_TARGET, "予約確認", "ホテル名：サンプルホテル\n"
        )
        self.assertIsNone(candidate.flight_number)

    def test_ekinet_candidate_has_no_fare_type(self) -> None:
        candidate = rp.extract_ekinet(
            "msg-regress-3", rp.RELEVANCE_TARGET, "件名", "ご乗車日：2026年09月10日\n"
        )
        self.assertIsNone(candidate.fare_type)

    def test_agoda_candidate_has_no_fare_type(self) -> None:
        candidate = rp.extract_agoda(
            "msg-regress-4", rp.RELEVANCE_TARGET, "予約確認", "ホテル名：サンプルホテル\n"
        )
        self.assertIsNone(candidate.fare_type)

    def test_smart_ex_candidate_has_no_fare_type(self) -> None:
        candidate = rp.extract_smart_ex(
            "msg-regress-5", rp.RELEVANCE_TARGET, "件名", "乗車日：2026年09月10日\n"
        )
        self.assertIsNone(candidate.fare_type)


class NoPersonalInfoLeakPhaseDTests(unittest.TestCase):
    def test_smart_ex_does_not_capture_member_or_phone(self) -> None:
        body = (
            "ご乗車日：2026年10月05日\n"
            "お客様氏名：山田 太郎\n会員番号：9999888877\n電話番号：090-1234-5678\n"
        )
        candidate = rp.extract_smart_ex("msg-pii-1", rp.RELEVANCE_TARGET, "件名", body)

        for value in (
            candidate.title,
            candidate.origin,
            candidate.destination,
            candidate.train_name,
            candidate.reservation_reference,
        ):
            if value is not None:
                self.assertNotIn("山田", value)
                self.assertNotIn("9999888877", value)
                self.assertNotIn("090-1234-5678", value)

    def test_skymark_does_not_capture_member_or_phone(self) -> None:
        body = (
            "ご搭乗日：2026年11月01日\n"
            "お客様氏名：山田 太郎\n会員番号：9999888877\n電話番号：090-1234-5678\n"
        )
        candidate = rp.extract_skymark("msg-pii-2", rp.RELEVANCE_TARGET, "件名", body)

        for value in (
            candidate.title,
            candidate.origin,
            candidate.destination,
            candidate.flight_number,
            candidate.reservation_reference,
        ):
            if value is not None:
                self.assertNotIn("山田", value)
                self.assertNotIn("9999888877", value)
                self.assertNotIn("090-1234-5678", value)


if __name__ == "__main__":
    unittest.main()
