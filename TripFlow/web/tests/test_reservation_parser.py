"""reservation_parser.py（Web v0.4 Phase C）のテスト。

ここで使うメール本文は、すべて実際のメールとは無関係な人工的なサンプルである。
実際の個人メール本文・氏名・会員番号・予約番号等はテストにも記載しない。
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reservation_parser as rp


class ClassifyEkinetTests(unittest.TestCase):
    def test_application_email_is_target(self) -> None:
        relevance = rp.classify_candidate("えきねっと", "【えきねっと】申込内容のご案内")
        self.assertEqual(relevance, rp.RELEVANCE_TARGET)

    def test_reservation_confirmation_is_target(self) -> None:
        relevance = rp.classify_candidate("えきねっと", "ご予約内容の確認")
        self.assertEqual(relevance, rp.RELEVANCE_TARGET)

    def test_departure_guide_is_excluded(self) -> None:
        relevance = rp.classify_candidate("えきねっと", "【えきねっと】出発前のご案内")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_seat_number_guide_is_supplementary(self) -> None:
        # Phase C実機確認：「座席番号のご案内」メールは単独でも列車名・区間・
        # 時刻・号車・座席番号を含んでいたため、対象外ではなく予約補完メール
        # として扱う（design.md 14.8参照）。
        relevance = rp.classify_candidate("えきねっと", "座席番号のお知らせ")
        self.assertEqual(relevance, rp.RELEVANCE_SUPPLEMENTARY)
        self.assertTrue(rp.can_analyze(relevance))

    def test_unrelated_subject_is_unknown(self) -> None:
        relevance = rp.classify_candidate("えきねっと", "【えきねっと】メンテナンスのお知らせ")
        self.assertEqual(relevance, rp.RELEVANCE_UNKNOWN)


class ClassifyAgodaTests(unittest.TestCase):
    def test_booking_confirmation_is_target(self) -> None:
        relevance = rp.classify_candidate("Agoda", "予約確認：サンプルホテル")
        self.assertEqual(relevance, rp.RELEVANCE_TARGET)

    def test_english_booking_confirmation_is_target(self) -> None:
        relevance = rp.classify_candidate("Agoda", "Booking Confirmation - Sample Hotel")
        self.assertEqual(relevance, rp.RELEVANCE_TARGET)

    def test_review_request_is_excluded(self) -> None:
        relevance = rp.classify_candidate("Agoda", "ご滞在はいかがでしたか？レビューのお願い")
        self.assertEqual(relevance, rp.RELEVANCE_EXCLUDED)

    def test_unrelated_subject_is_unknown(self) -> None:
        relevance = rp.classify_candidate("Agoda", "Agodaからの特別なお知らせ")
        self.assertEqual(relevance, rp.RELEVANCE_UNKNOWN)


class CanAnalyzeTests(unittest.TestCase):
    def test_excluded_cannot_be_analyzed(self) -> None:
        self.assertFalse(rp.can_analyze(rp.RELEVANCE_EXCLUDED))

    def test_target_and_unknown_can_be_analyzed(self) -> None:
        self.assertTrue(rp.can_analyze(rp.RELEVANCE_TARGET))
        self.assertTrue(rp.can_analyze(rp.RELEVANCE_UNKNOWN))


# サンプルの「申込内容」メール本文（架空のデータ）。
SAMPLE_EKINET_BODY = """\
いつもえきねっとをご利用いただきありがとうございます。
お申込み内容は以下のとおりです。

■ご乗車内容
ご乗車日：2026年09月10日
列車名：サンプル1号
出発駅：サンプル駅　出発時刻：09:00
到着駅：見本駅　到着時刻：11:30
号車：3号車
座席番号：5A

申込番号：AB12345678
"""

SAMPLE_AGODA_BODY = """\
Your booking is confirmed.

ホテル名：サンプルホテル東京
チェックイン日：2026年09月10日
チェックアウト日：2026年09月12日
予約ID：AG-0001234
合計金額：15,000円
"""


class ExtractEkinetTests(unittest.TestCase):
    def test_extracts_available_fields(self) -> None:
        candidate = rp.extract_ekinet(
            "msg-1", rp.RELEVANCE_TARGET, "【えきねっと】申込内容のご案内", SAMPLE_EKINET_BODY
        )

        self.assertEqual(candidate.service, "えきねっと")
        self.assertEqual(candidate.reservation_type, "電車")
        self.assertEqual(candidate.date, date(2026, 9, 10))
        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "09:00")
        self.assertEqual(candidate.end_time, "11:30")
        self.assertEqual(candidate.train_name, "サンプル1号")
        self.assertEqual(candidate.car_number, "3号車")
        self.assertEqual(candidate.seat_number, "5A")
        self.assertEqual(candidate.reservation_reference, "AB12345678")
        self.assertEqual(candidate.confidence, "高")
        self.assertEqual(candidate.missing_fields, ())

    def test_missing_fields_are_none_not_guessed(self) -> None:
        sparse_body = "ご乗車日：2026年09月10日\n"
        candidate = rp.extract_ekinet("msg-2", rp.RELEVANCE_UNKNOWN, "件名不明", sparse_body)

        self.assertEqual(candidate.date, date(2026, 9, 10))
        self.assertIsNone(candidate.origin)
        self.assertIsNone(candidate.destination)
        self.assertIsNone(candidate.train_name)
        self.assertIsNone(candidate.seat_number)
        self.assertEqual(candidate.confidence, "低")
        self.assertIn("出発駅", candidate.missing_fields)
        self.assertIn("座席番号", candidate.missing_fields)

    def test_completely_unparseable_body_returns_all_none(self) -> None:
        candidate = rp.extract_ekinet("msg-3", rp.RELEVANCE_UNKNOWN, "件名", "本文が空です。")

        self.assertIsNone(candidate.date)
        self.assertIsNone(candidate.origin)
        self.assertIsNone(candidate.destination)
        self.assertIsNone(candidate.reservation_reference)
        self.assertEqual(candidate.confidence, "低")
        self.assertEqual(len(candidate.missing_fields), len(rp._EKINET_FIELD_LABELS))

    def test_station_time_route_extracts_stations_and_times(self) -> None:
        # Phase C実機確認で判明した実メールの構造：
        # 「駅名(16時32分) → 駅名(18時07分)」。駅名・時刻とも固定値では
        # なく、この構造から動的に抽出できることを確認する。
        body = (
            "ご乗車日：2026年07月10日\n"
            "サンプル駅(16時32分) → 見本駅(18時07分)\n"
            "列車名：サンプル2号\n"
        )
        candidate = rp.extract_ekinet(
            "msg-route-1", rp.RELEVANCE_TARGET, "申込内容のご案内", body
        )

        self.assertEqual(candidate.origin, "サンプル駅")
        self.assertEqual(candidate.destination, "見本駅")
        self.assertEqual(candidate.start_time, "16:32")
        self.assertEqual(candidate.end_time, "18:07")
        self.assertEqual(candidate.confidence, "高")

    def test_station_time_route_different_station_names(self) -> None:
        # 駅名をハードコードしていないことの確認（別の駅名・時刻でも動作する）。
        body = "ご乗車日：2026年08月01日\n出発地(07時05分) → 到着地(09時40分)\n"
        candidate = rp.extract_ekinet("msg-route-2", rp.RELEVANCE_TARGET, "件名", body)

        self.assertEqual(candidate.origin, "出発地")
        self.assertEqual(candidate.destination, "到着地")
        self.assertEqual(candidate.start_time, "07:05")
        self.assertEqual(candidate.end_time, "09:40")

    def test_station_time_route_does_not_override_labeled_values(self) -> None:
        # ラベル形式で明示的に取得できた値は、構造パターンによる補完で上書きしない。
        body = (
            "出発駅：ラベル駅　出発時刻：09:15\n"
            "到着駅：ラベル到着駅　到着時刻：11:45\n"
            "ラベル駅(16時32分) → ラベル到着駅(18時07分)\n"
        )
        candidate = rp.extract_ekinet("msg-route-3", rp.RELEVANCE_TARGET, "件名", body)

        self.assertEqual(candidate.start_time, "09:15")
        self.assertEqual(candidate.end_time, "11:45")

    def test_confidence_medium_when_train_name_missing(self) -> None:
        body = "ご乗車日：2026年07月10日\nサンプル駅(16時32分) → 見本駅(18時07分)\n"
        candidate = rp.extract_ekinet("msg-medium-1", rp.RELEVANCE_TARGET, "件名", body)

        self.assertIsNone(candidate.train_name)
        self.assertEqual(candidate.confidence, "中")


class ExtractEkinetSeatNumberStructureTests(unittest.TestCase):
    """Phase C実機再確認で判明した「N号車 M番X席」形式（架空データで再現）。

    号車番号・座席番号・座席アルファベットはいずれもハードコードせず、
    構造（数字＋号車＋数字＋番＋アルファベット＋席）としてテストする。
    """

    def test_two_digit_car_two_digit_seat(self) -> None:
        body = "8号車 19番A席\n"
        candidate = rp.extract_ekinet("msg-seat-1", rp.RELEVANCE_SUPPLEMENTARY, "件名", body)

        self.assertEqual(candidate.car_number, "8号車")
        self.assertEqual(candidate.seat_number, "19番A席")

    def test_single_digit_car_single_digit_seat(self) -> None:
        body = "5号車 3番C席\n"
        candidate = rp.extract_ekinet("msg-seat-2", rp.RELEVANCE_SUPPLEMENTARY, "件名", body)

        self.assertEqual(candidate.car_number, "5号車")
        self.assertEqual(candidate.seat_number, "3番C席")

    def test_two_digit_car_two_digit_seat_different_letter(self) -> None:
        body = "10号車 12番D席\n"
        candidate = rp.extract_ekinet("msg-seat-3", rp.RELEVANCE_SUPPLEMENTARY, "件名", body)

        self.assertEqual(candidate.car_number, "10号車")
        self.assertEqual(candidate.seat_number, "12番D席")

    def test_extra_whitespace_between_car_and_seat(self) -> None:
        body = "8号車　　19番A席\n"  # 全角スペース2つ
        candidate = rp.extract_ekinet("msg-seat-4", rp.RELEVANCE_SUPPLEMENTARY, "件名", body)

        self.assertEqual(candidate.car_number, "8号車")
        self.assertEqual(candidate.seat_number, "19番A席")

    def test_no_whitespace_between_car_and_seat(self) -> None:
        body = "8号車19番A席\n"
        candidate = rp.extract_ekinet("msg-seat-5", rp.RELEVANCE_SUPPLEMENTARY, "件名", body)

        self.assertEqual(candidate.car_number, "8号車")
        self.assertEqual(candidate.seat_number, "19番A席")

    def test_linebreak_from_html_to_text_conversion(self) -> None:
        # HTML→text変換により、号車と座席番号の間に改行が入るケースを再現する。
        html_body = "<div>8号車</div><div>19番A席</div>"
        body = rp.html_to_text(html_body)
        candidate = rp.extract_ekinet("msg-seat-6", rp.RELEVANCE_SUPPLEMENTARY, "件名", body)

        self.assertEqual(candidate.car_number, "8号車")
        self.assertEqual(candidate.seat_number, "19番A席")

    def test_labeled_seat_number_takes_priority_over_structure(self) -> None:
        # ラベル形式（「座席番号：」）で既に取得できている場合は、構造パターン
        # による補完で上書きしない。
        body = "座席番号：5A\n9号車 20番B席\n"
        candidate = rp.extract_ekinet("msg-seat-7", rp.RELEVANCE_SUPPLEMENTARY, "件名", body)

        self.assertEqual(candidate.seat_number, "5A")

    def test_seat_number_missing_when_no_structure_present(self) -> None:
        # 座席情報が本文に無い場合は推測で補完せずNoneのまま。
        body = "列車名：サンプル1号\n"
        candidate = rp.extract_ekinet("msg-seat-8", rp.RELEVANCE_TARGET, "件名", body)

        self.assertIsNone(candidate.seat_number)

    def test_ride_date_is_not_guessed_when_missing_from_supplementary_mail(self) -> None:
        # 座席番号案内メールに乗車日の記載が無い場合、件名等から推測で
        # 補完しない（主メールとの統合はPhase Dで検討）。
        body = (
            "8号車 19番A席\n"
            "サンプル駅(16時32分) → 見本駅(18時07分)\n"
            "列車名：サンプル1号\n"
        )
        candidate = rp.extract_ekinet(
            "msg-seat-9", rp.RELEVANCE_SUPPLEMENTARY, "【えきねっと】座席番号のご案内", body
        )

        self.assertIsNone(candidate.date)
        self.assertEqual(candidate.seat_number, "19番A席")


class ExtractAgodaTests(unittest.TestCase):
    def test_extracts_available_fields(self) -> None:
        candidate = rp.extract_agoda(
            "msg-4", rp.RELEVANCE_TARGET, "予約確認：サンプルホテル東京", SAMPLE_AGODA_BODY
        )

        self.assertEqual(candidate.service, "Agoda")
        self.assertEqual(candidate.reservation_type, "ホテル")
        self.assertEqual(candidate.hotel_name, "サンプルホテル東京")
        self.assertEqual(candidate.checkin_date, date(2026, 9, 10))
        self.assertEqual(candidate.checkout_date, date(2026, 9, 12))
        self.assertEqual(candidate.reservation_reference, "AG-0001234")
        self.assertEqual(candidate.amount, 15000)
        self.assertEqual(candidate.confidence, "高")
        self.assertEqual(candidate.missing_fields, ())

    def test_missing_fields_are_none_not_guessed(self) -> None:
        sparse_body = "ホテル名：サンプルホテル\n"
        candidate = rp.extract_agoda("msg-5", rp.RELEVANCE_UNKNOWN, "件名不明", sparse_body)

        self.assertEqual(candidate.hotel_name, "サンプルホテル")
        self.assertIsNone(candidate.checkin_date)
        self.assertIsNone(candidate.checkout_date)
        self.assertIsNone(candidate.amount)
        self.assertEqual(candidate.confidence, "低")
        self.assertIn("チェックイン日", candidate.missing_fields)
        self.assertIn("料金", candidate.missing_fields)


class ExtractAgodaRealMailStructureTests(unittest.TestCase):
    """Phase C実機確認で判明したAgoda実メールの「構造」だけを、架空データで
    再現したテスト。実メール本文・実在の予約番号・氏名等は使用しない。
    """

    def test_checkin_checkout_date_with_weekday_and_linebreak(self) -> None:
        # 実メールでは「チェックイン日：」の値が同じ行になく、曜日を挟んだ
        # 別の行に日付が書かれている（例：「チェックイン日：\n水 2026年7月10日
        # \n（15:00以降）」）。曜日は固定値として扱わずYYYY年M月D日を抽出する。
        body = (
            "チェックイン日：\n"
            "水 2026年7月10日\n"
            "（15:00以降）\n"
            "チェックアウト日：\n"
            "木 2026年7月11日\n"
            "（11:00まで）\n"
        )
        candidate = rp.extract_agoda("msg-agoda-date-1", rp.RELEVANCE_TARGET, "予約確認", body)

        self.assertEqual(candidate.checkin_date, date(2026, 7, 10))
        self.assertEqual(candidate.checkout_date, date(2026, 7, 11))

    def test_checkin_date_with_html_derived_whitespace(self) -> None:
        # &nbsp;・全角スペースがHTML→text変換経由で本文に混入するケースを再現する。
        html_body = (
            "<div>チェックイン日：</div>"
            "<div>水&nbsp;2026年7月10日</div>"
            "<div>（15:00以降）</div>"
            "<div>チェックアウト日：</div>"
            "<div>木&nbsp;2026年7月11日</div>"
        )
        body = rp.html_to_text(html_body)
        candidate = rp.extract_agoda("msg-agoda-date-2", rp.RELEVANCE_TARGET, "予約確認", body)

        self.assertEqual(candidate.checkin_date, date(2026, 7, 10))
        self.assertEqual(candidate.checkout_date, date(2026, 7, 11))

    def test_ymd_date_format_with_internal_spaces(self) -> None:
        body = "チェックイン日：2026 年 7 月 10 日\n"
        candidate = rp.extract_agoda("msg-agoda-date-3", rp.RELEVANCE_TARGET, "予約確認", body)

        self.assertEqual(candidate.checkin_date, date(2026, 7, 10))

    def test_hotel_name_on_line_after_label(self) -> None:
        body = "宿泊施設名：\nサンプルホテル大阪\n"
        candidate = rp.extract_agoda("msg-agoda-hotel-1", rp.RELEVANCE_TARGET, "予約確認", body)

        self.assertEqual(candidate.hotel_name, "サンプルホテル大阪")

    def test_hotel_name_without_label_is_none_not_guessed(self) -> None:
        # 実メールにはホテル名の直前に明示的なラベルが無い可能性が高いことが
        # 分かっている。ラベルが見つからない場合、誤ったホテル名を推測で
        # 生成せずNoneのままにする。
        body = "Sample Hotel Osaka\nサンプルホテル大阪\n大阪府大阪市中央区サンプル1-2-3\n"
        candidate = rp.extract_agoda("msg-agoda-hotel-2", rp.RELEVANCE_UNKNOWN, "件名", body)

        self.assertIsNone(candidate.hotel_name)

    def test_label_does_not_match_as_substring_of_hotel_name_itself(self) -> None:
        # 「ホテル名」というラベル文字列が、値であるホテル名自体の一部
        # （例：「…ホテル名古屋…」）に偶然含まれてしまうケース。ラベルの
        # 直後に区切り文字（コロン等）が無ければラベルとして扱わないことを
        # 確認する（開発中に発見した実際の誤抽出バグの回帰テスト）。
        body = "ホテル名：サンプルホテル名古屋\n"
        candidate = rp.extract_agoda(
            "msg-agoda-hotel-3", rp.RELEVANCE_TARGET, "予約確認", body
        )

        self.assertEqual(candidate.hotel_name, "サンプルホテル名古屋")

    def test_amount_extraction_regression(self) -> None:
        body = "合計金額：22,800円\n"
        candidate = rp.extract_agoda("msg-agoda-amount-1", rp.RELEVANCE_TARGET, "予約確認", body)

        self.assertEqual(candidate.amount, 22800)

    def test_confidence_high_when_core_fields_all_present(self) -> None:
        body = (
            "宿泊施設名：\nサンプルホテル大阪\n"
            "チェックイン日：\n水 2026年7月10日\n（15:00以降）\n"
            "チェックアウト日：\n木 2026年7月11日\n（11:00まで）\n"
        )
        candidate = rp.extract_agoda(
            "msg-agoda-confidence-1", rp.RELEVANCE_TARGET, "予約確認", body
        )

        self.assertEqual(candidate.confidence, "高")

    def test_confidence_medium_when_checkout_missing(self) -> None:
        body = "宿泊施設名：\nサンプルホテル大阪\nチェックイン日：\n水 2026年7月10日\n"
        candidate = rp.extract_agoda(
            "msg-agoda-confidence-2", rp.RELEVANCE_TARGET, "予約確認", body
        )

        self.assertEqual(candidate.confidence, "中")


class ExtractAgodaHotelNameAnchorTests(unittest.TestCase):
    """Phase C実機確認（Agoda3回目）で判明した、「予約確認」等の見出し語に
    続けてホテル名が記載される構造（架空のホテル名で再現）。実メール本文・
    実在のホテル名・氏名・予約番号は使用しない。
    """

    def test_english_hotel_name_after_anchor_in_subject(self) -> None:
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-1",
            rp.RELEVANCE_TARGET,
            "予約確認 Sample Hotel Tokyo",
            "",
        )
        self.assertEqual(candidate.hotel_name, "Sample Hotel Tokyo")

    def test_japanese_hotel_name_after_anchor_in_subject(self) -> None:
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-2",
            rp.RELEVANCE_TARGET,
            "予約確認 サンプルホテル大阪",
            "",
        )
        self.assertEqual(candidate.hotel_name, "サンプルホテル大阪")

    def test_english_and_japanese_hotel_name_together(self) -> None:
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-3",
            rp.RELEVANCE_TARGET,
            "予約確認 Sample Hotel Tokyo サンプルホテル東京",
            "",
        )
        self.assertEqual(candidate.hotel_name, "Sample Hotel Tokyo サンプルホテル東京")

    def test_anchor_in_body_when_subject_has_no_anchor(self) -> None:
        body = "予約確認\nSample Hotel Nagoya サンプルホテル名古屋\nチェックイン日：2026年7月10日\n"
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-4", rp.RELEVANCE_TARGET, "件名（見出し語なし）", body
        )
        self.assertEqual(candidate.hotel_name, "Sample Hotel Nagoya サンプルホテル名古屋")

    def test_anchor_in_snippet_as_last_resort(self) -> None:
        # 件名・本文からは取得できず、Gmail snippet（検索結果に表示済みの
        # 短い抜粋）からのみ取得できるケース。
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-5",
            rp.RELEVANCE_TARGET,
            "件名（見出し語なし）",
            "本文にも見出し語がありません。",
            snippet="予約確認 Sample Hotel Sapporo サンプルホテル札幌",
        )
        self.assertEqual(candidate.hotel_name, "Sample Hotel Sapporo サンプルホテル札幌")

    def test_labeled_value_takes_priority_over_anchor(self) -> None:
        body = "ホテル名：ラベル優先ホテル\n予約確認 見出し語経由ホテル\n"
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-6", rp.RELEVANCE_TARGET, "予約確認", body
        )
        self.assertEqual(candidate.hotel_name, "ラベル優先ホテル")

    def test_hotel_name_none_when_no_anchor_or_label_anywhere(self) -> None:
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-7",
            rp.RELEVANCE_UNKNOWN,
            "Agodaからのお知らせ",
            "本日は季節のキャンペーンのご案内です。",
            snippet="今だけのお得な情報をお届けします。",
        )
        self.assertIsNone(candidate.hotel_name)

    def test_review_request_does_not_yield_hotel_name(self) -> None:
        # レビュー依頼メールは分類上EXCLUDEDとなり解析対象外になるが、万一
        # 手動で解析された場合でも、見出し語が無いためホテル名は生成しない。
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-8",
            rp.RELEVANCE_EXCLUDED,
            "ご滞在はいかがでしたか？レビューのお願い",
            "この度はご宿泊いただきありがとうございました。レビューをお願いします。",
        )
        self.assertIsNone(candidate.hotel_name)

    def test_advertisement_email_does_not_yield_hotel_name(self) -> None:
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-9",
            rp.RELEVANCE_UNKNOWN,
            "夏の特別セール開催中",
            "対象施設が最大30%オフになるキャンペーンを実施中です。",
        )
        self.assertIsNone(candidate.hotel_name)

    def test_does_not_capture_full_sentence_after_anchor(self) -> None:
        # 見出し語の直後に改行が無く、そのまま文章が続く場合、後続の文章まで
        # ホテル名として取り込まずNoneを維持する（句点等の目印で検知）。
        body = "予約確認 この度はご予約いただきありがとうございます。今後ともよろしくお願いいたします。"
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-10", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertIsNone(candidate.hotel_name)

    def test_does_not_capture_across_newline(self) -> None:
        # 改行をまたいだ範囲はホテル名候補にしない（同じ行のみを見る）。
        body = "予約確認\n\nチェックイン日：2026年7月10日\nチェックアウト日：2026年7月11日\n"
        candidate = rp.extract_agoda(
            "msg-hotel-anchor-11", rp.RELEVANCE_TARGET, "件名", body
        )
        self.assertIsNone(candidate.hotel_name)


class ExtractAgodaHotelNameAnchorEchoTests(unittest.TestCase):
    """Phase C実機再確認（Agoda4回目）で判明したバグの回帰テスト。

    見出し語（「予約確認」等）がバナー見出しと本文セクション見出しのように
    2箇所に続けて現れる構造（架空データで再現）で、1つ目の見出し語の直後が
    2つ目の見出し語そのものだった場合に、見出し語自体を誤ってホテル名として
    返していた。実メール本文・実在ホテル名は使用しない。
    """

    def test_anchor_word_alone_never_becomes_hotel_name(self) -> None:
        candidate = rp.extract_agoda(
            "msg-echo-1", rp.RELEVANCE_TARGET, "予約確認", ""
        )
        self.assertIsNone(candidate.hotel_name)

    def test_duplicate_anchor_heading_with_nothing_after_returns_none(self) -> None:
        # 見出し語が2回連続で現れ、その後に何も続かない場合はNoneを維持する。
        body = "予約確認\n\n予約確認\n"
        candidate = rp.extract_agoda("msg-echo-2", rp.RELEVANCE_TARGET, "予約確認", body)
        self.assertIsNone(candidate.hotel_name)

    def test_duplicate_anchor_heading_then_hotel_name_is_recovered(self) -> None:
        # 見出し語がバナーとセクション見出しで2回現れ、3番目のまとまりに
        # 実際のホテル名がある構造。1回目の直後が見出し語自体でも、
        # 見出し語ではない値を返す。
        body = "予約確認\n\n予約確認\n\nSample Hotel Tokyo サンプルホテル東京\n"
        candidate = rp.extract_agoda("msg-echo-3", rp.RELEVANCE_TARGET, "予約確認", body)
        self.assertEqual(candidate.hotel_name, "Sample Hotel Tokyo サンプルホテル東京")

    def test_no_anchor_keyword_is_ever_returned_as_hotel_name(self) -> None:
        # 見出し語そのもの（大文字小文字違いを含む）がhotel_nameとして
        # 返らないことを、全見出し語について確認する。
        for anchor in rp._AGODA_HOTEL_NAME_ANCHORS:
            with self.subTest(anchor=anchor):
                body = f"{anchor}\n\n{anchor}\n"
                candidate = rp.extract_agoda(
                    f"msg-echo-anchor-{anchor}", rp.RELEVANCE_TARGET, anchor, body
                )
                self.assertIsNone(candidate.hotel_name)

    def test_english_anchor_case_variation_never_becomes_hotel_name(self) -> None:
        # 英語見出し語は大文字小文字が実メールと完全一致しない可能性があるため、
        # 大文字小文字を無視した比較でも見出し語自体が返らないことを確認する。
        body = "confirmation\n\nCONFIRMATION\n"
        candidate = rp.extract_agoda(
            "msg-echo-4", rp.RELEVANCE_TARGET, "confirmation", body
        )
        self.assertIsNone(candidate.hotel_name)

    def test_subject_and_snippet_have_different_structures(self) -> None:
        # 件名は見出し語のみ、snippetには見出し語＋ホテル名が含まれる構造
        # （snippetがホテル名の直後で途切れているケース）。件名からは
        # 取得できず、snippetから取得できることを確認する。
        candidate = rp.extract_agoda(
            "msg-echo-5",
            rp.RELEVANCE_TARGET,
            "予約確認",
            "",
            snippet="予約確認 Sample Hotel Kyoto サンプルホテル京都",
        )
        self.assertEqual(candidate.hotel_name, "Sample Hotel Kyoto サンプルホテル京都")

    def test_snippet_with_trailing_text_after_hotel_name_returns_none_safely(self) -> None:
        # Gmail snippetは改行の無い単一行の抜粋であることが多く、ホテル名の
        # 直後に別の文言（チェックイン時間の案内等）が続く場合、どこまでが
        # ホテル名か機械的に判断できない。この場合は無理に切り出さず、
        # 安全側でNoneを維持する。
        candidate = rp.extract_agoda(
            "msg-echo-5b",
            rp.RELEVANCE_TARGET,
            "予約確認",
            "",
            snippet="予約確認 Sample Hotel Kyoto サンプルホテル京都 チェックインは15時から",
        )
        self.assertIsNone(candidate.hotel_name)

    def test_hotel_name_candidate_only_in_body(self) -> None:
        # 件名・snippetには見出し語が無く、本文にのみホテル名候補があるケース。
        candidate = rp.extract_agoda(
            "msg-echo-6",
            rp.RELEVANCE_TARGET,
            "件名（見出し語なし）",
            "予約確認\nSample Hotel Fukuoka サンプルホテル福岡\n",
            snippet="見出し語のないsnippetです。",
        )
        self.assertEqual(candidate.hotel_name, "Sample Hotel Fukuoka サンプルホテル福岡")

    def test_cannot_safely_determine_hotel_name_returns_none(self) -> None:
        # 見出し語が繰り返し現れるが、いずれの直後もホテル名として妥当と
        # 判断できない（安全に特定できない）場合はNoneを維持する。
        body = "予約確認\n\n予約確認\n\nご予約\n\n予約完了\n"
        candidate = rp.extract_agoda("msg-echo-7", rp.RELEVANCE_TARGET, "予約確認", body)
        self.assertIsNone(candidate.hotel_name)

    def test_review_request_still_does_not_yield_hotel_name(self) -> None:
        # 既存成功機能（分類との整合性）を壊していないことの確認。
        candidate = rp.extract_agoda(
            "msg-echo-8",
            rp.RELEVANCE_EXCLUDED,
            "ご滞在はいかがでしたか？レビューのお願い",
            "この度はご宿泊いただきありがとうございました。",
        )
        self.assertIsNone(candidate.hotel_name)

    def test_advertisement_email_still_does_not_yield_hotel_name(self) -> None:
        candidate = rp.extract_agoda(
            "msg-echo-9",
            rp.RELEVANCE_UNKNOWN,
            "夏の特別セール開催中",
            "対象施設が最大30%オフになるキャンペーンを実施中です。",
        )
        self.assertIsNone(candidate.hotel_name)


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags_and_converts_breaks(self) -> None:
        html_body = (
            "<html><body><p>ご乗車日：2026年09月10日</p>"
            "<p>出発駅：サンプル駅<br>到着駅：見本駅</p>"
            "<script>var x = 1;</script>"
            "</body></html>"
        )
        text = rp.html_to_text(html_body)

        self.assertIn("ご乗車日：2026年09月10日", text)
        self.assertIn("出発駅：サンプル駅", text)
        self.assertIn("到着駅：見本駅", text)
        self.assertNotIn("<p>", text)
        self.assertNotIn("var x", text)

    def test_empty_html_returns_empty_string(self) -> None:
        self.assertEqual(rp.html_to_text(""), "")


class ResolveBodyTextTests(unittest.TestCase):
    def test_prefers_plain_text(self) -> None:
        text = rp.resolve_body_text("プレーンテキスト本文", "<p>HTML本文</p>")
        self.assertEqual(text, "プレーンテキスト本文")

    def test_falls_back_to_html_when_plain_missing(self) -> None:
        text = rp.resolve_body_text("", "<p>ご乗車日：2026年09月10日</p>")
        self.assertIn("ご乗車日：2026年09月10日", text)

    def test_both_missing_returns_empty_string(self) -> None:
        self.assertEqual(rp.resolve_body_text("", ""), "")


class AnalyzeEmailDispatchTests(unittest.TestCase):
    def test_dispatches_to_ekinet(self) -> None:
        candidate = rp.analyze_email(
            service="えきねっと",
            message_id="msg-6",
            relevance=rp.RELEVANCE_TARGET,
            subject="申込内容のご案内",
            text_plain=SAMPLE_EKINET_BODY,
            text_html="",
        )
        self.assertEqual(candidate.reservation_type, "電車")

    def test_dispatches_to_agoda(self) -> None:
        candidate = rp.analyze_email(
            service="Agoda",
            message_id="msg-7",
            relevance=rp.RELEVANCE_TARGET,
            subject="予約確認",
            text_plain=SAMPLE_AGODA_BODY,
            text_html="",
        )
        self.assertEqual(candidate.reservation_type, "ホテル")

    def test_unsupported_service_raises(self) -> None:
        with self.assertRaises(ValueError):
            rp.analyze_email(
                service="未対応サービス",
                message_id="msg-8",
                relevance=rp.RELEVANCE_UNKNOWN,
                subject="件名",
                text_plain="本文",
                text_html="",
            )


class NoPersonalInfoLeakTests(unittest.TestCase):
    """個人情報（氏名・会員番号・電話番号・住所）を抽出対象にしていないことの確認。"""

    def test_member_and_phone_like_values_are_not_captured(self) -> None:
        body = (
            SAMPLE_EKINET_BODY
            + "\nお客様氏名：山田 太郎\n会員番号：9999888877\n電話番号：090-1234-5678\n"
        )
        candidate = rp.extract_ekinet("msg-9", rp.RELEVANCE_TARGET, "申込内容のご案内", body)

        for value in (
            candidate.title,
            candidate.origin,
            candidate.destination,
            candidate.train_name,
            candidate.car_number,
            candidate.seat_number,
            candidate.reservation_reference,
        ):
            if value is not None:
                self.assertNotIn("山田", value)
                self.assertNotIn("9999888877", value)
                self.assertNotIn("090-1234-5678", value)


if __name__ == "__main__":
    unittest.main()
