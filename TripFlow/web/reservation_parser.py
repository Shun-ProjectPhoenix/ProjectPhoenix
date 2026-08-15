"""Gmail予約メール候補の分類・本文解析（Web v0.4 Phase C）。

このモジュールはネットワークI/Oを一切行わない純粋なロジックのみを持つ。
Gmail APIの呼び出し（候補一覧の取得・本文取得）はgmail_service.pyが担当し、
このモジュールはgmail_service側で取得済みの件名・本文テキストを受け取って
「分類」「抽出」だけを行う。テスト容易性（実Gmailにアクセスせずテストできる
こと）のため、この責務分離を維持すること。

Phase Cではメール本文全文・access token・氏名・会員番号・電話番号・住所などの
個人情報は、一切この先（session_state・ログ・戻り値）へ渡さない。抽出対象は
design.md 13章で定めた予約関連項目（乗車日・出発時刻・到着時刻・出発駅・到着駅・
列車名・号車・座席番号・予約/申込番号、および宿泊関連の同等項目）のみ。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

# --------------------------------------------------
# 分類（フィルタリング）
# --------------------------------------------------
# Phase Bの実機確認により、複数段階に分類できる構造が必要だと判明した
# （docs/design.md 13.3参照）。
# Phase Cの実機確認では、さらに「えきねっとの『座席番号のご案内』メールには
# 列車名・区間・時刻・号車・座席番号が単独で含まれている」ことが判明したため、
# 「対象外」から切り出して RELEVANCE_SUPPLEMENTARY（予約補完メール）を追加した。
# あくまで「このメール1件だけでも独立して解析できる」という意味であり、
# 複数メールを自動で結合・統合する処理はPhase Cでは行わない（design.md 14.8参照）。
RELEVANCE_TARGET = "予約情報抽出対象"
RELEVANCE_SUPPLEMENTARY = "予約補完メール"
RELEVANCE_EXCLUDED = "対象外"
RELEVANCE_UNKNOWN = "判定不能"


@dataclass(frozen=True)
class ClassificationRule:
    """件名に対するキーワードマッチ1件分のルール。"""

    relevance: str
    keywords: tuple[str, ...]


# サービスごとの件名分類ルール。上から順に評価し、最初にマッチしたルールを採用する。
# 対象外(EXCLUDED)ルールを対象(TARGET)ルールより先に評価することで、「申込」等の
# 語を含みつつ実際は案内・レビュー依頼であるメールを誤って対象にしにくくしている。
#
# 重要：ここに列挙したキーワードは、Web v0.4 Phase Bの実機確認でユーザーから
# 報告された「メール種別のカテゴリ」（申込内容／出発前案内／座席番号案内／
# その他案内、予約確認関連／宿泊関連／レビュー依頼／その他案内）をもとにした
# 初期案であり、実際の件名文言を1件ずつ確認して決めたものではない。
# どちらにも一致しない件名は無理に分類せず RELEVANCE_UNKNOWN とし、ユーザーが
# 手動で解析を試せるようにする（13章「実メール確認」で見直す前提）。
# キーワードの追加・変更だけで調整できるよう、判定ロジック本体
# （classify_candidate）はこのテーブルの中身に一切依存しない形にしている。
SUBJECT_CLASSIFICATION_RULES: dict[str, list[ClassificationRule]] = {
    "えきねっと": [
        # 「座席番号のご案内」は対象外ではなく、単独でも解析する価値がある
        # 予約補完メール（RELEVANCE_SUPPLEMENTARY）として扱う。他の対象外・
        # 対象ルールより先に評価する。
        ClassificationRule(
            RELEVANCE_SUPPLEMENTARY,
            ("座席番号",),
        ),
        ClassificationRule(
            RELEVANCE_EXCLUDED,
            ("出発前", "レビュー", "アンケート"),
        ),
        ClassificationRule(
            RELEVANCE_TARGET,
            ("申込", "予約確認", "ご予約内容", "購入完了"),
        ),
    ],
    "Agoda": [
        ClassificationRule(
            RELEVANCE_EXCLUDED,
            ("レビュー", "Review", "感想", "アンケート", "Survey"),
        ),
        ClassificationRule(
            RELEVANCE_TARGET,
            (
                "予約確認",
                "ご予約",
                "予約完了",
                "Booking Confirmation",
                "Booking Confirmed",
                "Confirmation",
            ),
        ),
    ],
    # Web v0.4 Phase D：スマートEXは実機確認（2回目）により、実際の予約
    # メールの件名に「新幹線予約内容」という予約内容を示す語が含まれる
    # ことを確認できたため、これをTARGETキーワードに追加した。それに加えて、
    # えきねっと・Agodaの両方で実際に効果があった汎用的な予約確認語彙
    # （"予約確認"等）も引き続き流用している。いずれも「スマートEX」という
    # サービス名の語だけではTARGETにならない（対象外キーワードを先に評価
    # するため、広告・セール・観光案内等は引き続き対象外になる）。
    # スカイマークは実際の件名文言をまだ一度も確認していないため、
    # 対象(TARGET)ルールはまだ置かず、広告・キャンペーン・お知らせ・
    # レビュー等の一般的なマーケティングメールに共通しがちなキーワードのみを
    # 対象外(EXCLUDED)として登録する。これにより、少なくとも明らかな広告・
    # レビュー依頼は誤って対象にしない。それ以外の件名は判定不能(UNKNOWN)
    # となり、ユーザーが手動で解析を試せる（13章「実メール確認」を経て
    # TARGETルールを追加する前提）。
    "スマートEX": [
        # 実機確認（3回目）で、「乗車用ICカード指定内容」という別メールが
        # 存在することを確認した。予約本体（新幹線予約内容）とは別のメール
        # だが、将来的に予約情報を補完するメールとして扱える可能性があるため、
        # えきねっとの「座席番号のご案内」と同じ考え方（RELEVANCE_SUPPLEMENTARY
        # ＝予約補完メール）で分類する。対象外・対象ルールより先に評価する。
        # 複数メールの自動統合は今回も実装しない（分類のみ）。
        ClassificationRule(
            RELEVANCE_SUPPLEMENTARY,
            ("乗車用ICカード指定内容",),
        ),
        ClassificationRule(
            RELEVANCE_EXCLUDED,
            ("レビュー", "アンケート", "キャンペーン", "広告", "セール", "お知らせ"),
        ),
        ClassificationRule(
            RELEVANCE_TARGET,
            ("新幹線予約内容", "申込", "予約確認", "ご予約内容", "予約完了", "購入完了"),
        ),
    ],
    # Web v0.4 Phase D後半：スカイマークの実機確認で、複数種別のメールが
    # 同一予約について送られてくることが判明した（design.md 22章参照）。
    # 新しい分類定数は増やさず、既存の4分類（対象／予約補完メール／対象外／
    # 判定不能）の枠内で「正本メール（主メール）」の考え方を表現している。
    #
    # ・「カード決済完了【購入済】」＝PRIMARY（正本メール）：実機確認で
    #   搭乗日・区間・便名・時刻・予約番号・座席番号のすべてが取得でき、
    #   confidence「高」になることを確認できた、最も情報が揃ったメール。
    #   将来、同一予約の複数メールを自動統合する際にも、この正本メールを
    #   基準にする設計方針とした（design.md参照）。分類上はTARGETのまま
    # ・「座席指定完了のご案内」＝SUPPLEMENTARY（予約補完メール）：えきねっと
    #   「座席番号のご案内」・スマートEX「乗車用ICカード指定内容」と同じ
    #   位置づけ。変更していない
    # ・「確認メール【お支払情報】」＝SECONDARY（予備候補）：正本メールと
    #   同じ予約情報を含む可能性があるが、実機確認で座席番号を含まない
    #   ケースが確認された。正本メールほど情報が揃っていないうえ、正本
    #   メールと同格にTARGET扱いすると、将来DB自動登録を実装した際に
    #   同一予約が重複登録される危険がある。そのため今回、TARGETキーワード
    #   から「お支払情報」を外し、判定不能(UNKNOWN)へ変更した。UNKNOWNでも
    #   ユーザーが手動で「予約情報を解析」できる点は変わらない（can_analyze()
    #   はEXCLUDED以外すべてTrueを返す既存の仕組みをそのまま使う）
    # ・「予約完了【未購入】」＝UNKNOWN：変更なし。未購入・支払い待ち状態を
    #   安全に表現する仕組みが無いため、引き続き判定不能のまま維持する
    #   （reservation_status等の設計時に改めて対応する）
    # ・「搭乗日前日のお知らせ」＝EXCLUDED：既存の「お知らせ」キーワードで
    #   既に対象外になっており、変更していない
    "スカイマーク": [
        ClassificationRule(
            RELEVANCE_SUPPLEMENTARY,
            ("座席指定完了",),
        ),
        ClassificationRule(
            RELEVANCE_EXCLUDED,
            ("レビュー", "アンケート", "キャンペーン", "広告", "セール", "お知らせ"),
        ),
        # 「決済完了」「購入済」のみをTARGET（正本メール＝PRIMARY）とする。
        # 「お支払情報」はTARGETから外し、判定不能(UNKNOWN)へ委ねる
        # （SECONDARY＝予備候補。今回の分類整理で変更した点）。
        ClassificationRule(
            RELEVANCE_TARGET,
            ("決済完了", "購入済"),
        ),
    ],
}


def classify_candidate(service: str, subject: str) -> str:
    """件名だけを見て、本文取得前の分類（対象／対象外／判定不能）を返す。

    本文を取得しなくても判定できる範囲に留めることで、「対象外」と判定した
    メールについては本文取得（Gmail API呼び出し）自体を発生させない。
    """
    subject = subject or ""
    for rule in SUBJECT_CLASSIFICATION_RULES.get(service, []):
        if any(keyword in subject for keyword in rule.keywords):
            return rule.relevance
    return RELEVANCE_UNKNOWN


def can_analyze(relevance: str) -> bool:
    """本文解析（Gmail APIでの本文取得）を許可してよい分類かどうか。

    対象外(EXCLUDED)と判定されたメールは、ユーザーが個別に望まない限り
    本文を取得しない（全候補メールの本文を無条件に取得しないため）。
    対象(TARGET)・予約補完メール(SUPPLEMENTARY)・判定不能(UNKNOWN)は、
    いずれもユーザーが個別に解析ボタンを押せば1件ずつ解析できる。
    """
    return relevance != RELEVANCE_EXCLUDED


def can_register(relevance: str) -> bool:
    """「TripFlowに登録」ボタンを表示してよい分類かどうか（Phase E-2B）。

    can_analyze()とは別の、より厳しい判定。予約情報抽出対象(TARGET)と
    判定されたメールのみを登録対象とする。予約補完メール(SUPPLEMENTARY)・
    判定不能(UNKNOWN)は、単独では登録候補にせず、従来通り手動解析のみ
    許可する（can_analyze()の挙動は変更しない）。対象外(EXCLUDED)は
    そもそも本文解析自体を行わないため、登録候補にもなり得ない。
    """
    return relevance == RELEVANCE_TARGET


# --------------------------------------------------
# 本文テキストの正規化（multipart / text/plain / text/html対応）
# --------------------------------------------------
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_BREAK_RE = re.compile(
    r"<(br|/p|/div|/tr|/li|/h[1-6]|/table)\s*/?>", re.IGNORECASE
)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
# &nbsp;（\xa0）・全角スペース（　）も、通常の半角スペースへ正規化する。
# HTMLメールではラベルと値の間にこれらが使われることが多く、正規化しないと
# 後続の正規表現（\s*等）での抽出に影響しうるため。
_INLINE_WS_RE = re.compile(r"[ \t\xa0　]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def html_to_text(raw_html: str) -> str:
    """HTMLしか存在しないメール本文を、正規表現ベース抽出に使えるテキストへ変換する。

    完全なHTMLパーサーではなく、複雑なレイアウトの完全な再現はしないが、
    タグ除去・改行変換・実体参照デコードにより「ラベル：値」形式の情報抽出には
    十分な精度を狙う簡易変換とする。
    """
    if not raw_html:
        return ""

    import html as html_module

    text = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _ANY_TAG_RE.sub(" ", text)
    text = html_module.unescape(text)
    text = _INLINE_WS_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def resolve_body_text(text_plain: str, text_html: str) -> str:
    """text/plainがあればそれを優先し、無ければtext/htmlをテキスト化する。

    どちらも空の場合は空文字列を返す（想定外メール形式でもクラッシュしない）。
    """
    if text_plain and text_plain.strip():
        return text_plain
    if text_html and text_html.strip():
        return html_to_text(text_html)
    return ""


# --------------------------------------------------
# 登録候補データ構造
# --------------------------------------------------
@dataclass(frozen=True)
class ReservationCandidate:
    """本文解析結果を「登録候補」として保持するデータ構造（Phase C。Phase Dで
    飛行機（スカイマーク）用にflight_number・fare_typeを追加）。

    DBへの保存はまだ行わない。この構造は登録候補プレビュー表示専用であり、
    現行のreservationsテーブルのスキーマとは1対1で対応しない（train_name・
    car_number・seat_number・flight_number等、現行スキーマに無い項目を含む）。
    reservationsテーブルへの保存方法・スキーマ拡張の要否はPhase D以降で
    改めて検討する。メール本文全文・access token・氏名・会員番号・電話番号・
    住所は一切含めない。

    origin/destinationは、列車の出発/到着駅・飛行機の出発/到着空港の
    いずれにも使う汎用フィールドとして扱う（「出発地/到着地」という
    概念自体は交通手段によらず共通のため、専用フィールドを増やさない）。
    """

    service: str
    message_id: str
    relevance: str
    reservation_type: str  # "電車" / "ホテル" / "飛行機" / "その他"
    confidence: str  # "高" / "中" / "低"（予約として重要な項目の充足度）
    title: str | None
    date: date | None
    start_time: str | None
    end_time: str | None
    origin: str | None
    destination: str | None
    train_name: str | None
    car_number: str | None
    seat_number: str | None
    hotel_name: str | None
    checkin_date: date | None
    checkout_date: date | None
    amount: int | None
    reservation_reference: str | None
    flight_number: str | None = None
    # 運賃種別（例：スカイマークの「いま得」等）。Phase D後半でフィールドの
    # みを追加し、抽出実装は保留している（理由はextract_skymark()のコメント
    # 参照）。実際の運賃種別名を列挙して判定する実装にはしない。
    fare_type: str | None = None
    missing_fields: tuple[str, ...] = ()
    # GmailMessageCandidate.thread_idから伝播するスレッドID（Phase E-2B）。
    # 既存フィールドの意味・順番を変えないよう末尾にデフォルト値ありで
    # 追加した。analyze_email()がthread_id引数を受け取った場合のみ設定され、
    # 従来通りthread_idを渡さない呼び出しはNoneのままで変わらない。
    thread_id: str | None = None


# --------------------------------------------------
# 抽出共通ヘルパー
# --------------------------------------------------
def _search_first(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None


_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# 日付の数字と年/月/日の間に、全角/半角スペースや改行が挟まる実メールが
# あったため、区切り文字の前後に\s*を許容する（例："2026 年 7 月 10 日"）。
_DATE_YMD_RE = re.compile(r"(\d{4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?")
_DATE_ENGLISH_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})|([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})"
)


def _parse_date_value(raw: str | None) -> date | None:
    """メールに存在する日付表記だけを解釈する。存在しない値は推測で補わずNone。"""
    if not raw:
        return None

    match = _DATE_YMD_RE.search(raw)
    if match:
        year, month, day = (int(x) for x in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    match = _DATE_ENGLISH_RE.search(raw)
    if match:
        if match.group(2):
            day, month_name, year = match.group(1), match.group(2), match.group(3)
        else:
            month_name, day, year = match.group(4), match.group(5), match.group(6)
        month = _MONTH_NAMES.get(month_name.lower()[:3])
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                return None

    return None


def _find_date_raw_near(text: str, *, window: int = 80) -> str | None:
    """textの先頭付近（windowで指定した範囲）から、最初に見つかった日付表記の
    生の文字列を返す（曜日等、日付以外の前置き文字は無視する）。
    """
    window_text = text[:window]

    candidates: list[tuple[int, str]] = []
    match = _DATE_YMD_RE.search(window_text)
    if match:
        candidates.append((match.start(), match.group(0)))
    match = _DATE_ENGLISH_RE.search(window_text)
    if match:
        candidates.append((match.start(), match.group(0)))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _find_date_near_label(text: str, label_pattern: str, *, window: int = 80) -> str | None:
    """ラベル（例：チェックイン日）の直後、指定した範囲内にある日付表記を探す。

    実メールでは「チェックイン日：」の値が同じ行ではなく、改行を挟んだ
    別の行（例：「曜日 2026年7月10日」）に書かれている場合があるため、
    ラベルと値が同じ行にあることを前提にしない。曜日等の前置き文字が
    あっても、日付パターンだけを拾う。
    """
    label_match = re.search(label_pattern, text)
    if not label_match:
        return None
    return _find_date_raw_near(text[label_match.end():], window=window)


_AMOUNT_RE = re.compile(r"[¥$]?\s*([0-9][0-9,]{2,})\s*円?")


def _parse_amount(raw: str | None) -> int | None:
    if not raw:
        return None
    match = _AMOUNT_RE.search(raw)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _search_label_value(labels: list[str], text: str, *, lookahead_lines: int = 5) -> str | None:
    """「ラベル：値」を探す。値がラベルと同じ行に無い場合、続く数行のうち
    最初の非空行を値として扱う。

    実メールでは、HTML→text変換やレイアウトの都合で、ラベルと値が改行や
    別のブロック要素で分かれている場合がある（Agodaのホテル名・チェックイン日等
    で実際に確認された）。そのため、同じ行に値が無くてもすぐに諦めず、
    直後の数行までは値の候補として探索する。

    ラベルの直後に区切り文字（コロン・空白・改行・文字列終端）が続く場合の
    みラベルとして採用する。この境界チェックが無いと、例えば「ホテル名」が
    「…ホテル名古屋…」のような値そのものの一部と偶然一致してしまう。
    """
    for label in labels:
        match = re.search(rf"{label}(?=[:：\s]|$)", text)
        if not match:
            continue

        after_label = re.sub(r"^[:：]?[ \t]*", "", text[match.end():])

        same_line_value = after_label.split("\n", 1)[0].strip()
        if same_line_value:
            return same_line_value

        for line in after_label.split("\n")[1 : 1 + lookahead_lines]:
            stripped = line.strip()
            if stripped:
                return stripped

    return None


def _confidence_from_core(core_flags: dict[str, bool]) -> str:
    """予約として重要な項目（core_flags）の充足度からconfidenceを決める。

    missing_fieldsの件数だけで機械的に高/低を決めると、号車・座席番号のような
    副次的な項目が欠けただけでも「低」になってしまい、乗車日・区間・列車名・
    時刻（またはホテル名・チェックイン日・チェックアウト日）がそろっているのに
    確度が低く見えてしまう問題があった。ここでは「予約として重要な項目」だけを
    基準にする（Phase C実機確認でのユーザーからの指摘を反映）。
    """
    total = len(core_flags)
    present = sum(1 for value in core_flags.values() if value)

    if total and present == total:
        return "高"
    if present >= 2:
        return "中"
    return "低"


# --------------------------------------------------
# えきねっと（列車予約）の抽出
# --------------------------------------------------
_EKINET_FIELD_LABELS = {
    "ride_date": "乗車日",
    "start_time": "出発時刻",
    "end_time": "到着時刻",
    "origin": "出発駅",
    "destination": "到着駅",
    "train_name": "列車名",
    "car_number": "号車",
    "seat_number": "座席番号",
    "reservation_reference": "予約/申込番号",
}


# 実メールでは「駅名(16時32分) → 駅名(18時07分)」のように、区間と出発/到着
# 時刻が1つの構造としてまとまっている場合がある（Phase C実機確認で判明）。
# 駅名・時刻とも固定値ではなく、この「駅名(○時○分) → 駅名(○時○分)」という
# 構造そのものをパターンとして抽出する。
_STATION_TIME_ROUTE_RE = re.compile(
    r"([^\s\n（(→]{1,20})[（(]\s*(\d{1,2})\s*時\s*(\d{1,2})\s*分\s*[）)]"
    r"\s*→\s*"
    r"([^\s\n（(→]{1,20})[（(]\s*(\d{1,2})\s*時\s*(\d{1,2})\s*分\s*[）)]"
)

# 実メールでは「8号車 19番A席」のように、号車・座席番号・座席アルファベットが
# ラベル無しで1つの構造としてまとまっている場合がある（Phase C実機再確認で判明）。
# 号車・座席番号・アルファベットとも固定値ではなく、「N号車 M番X席」という
# 構造そのものをパターンとして抽出する。数字は1桁・2桁以上どちらも許容し、
# 全角/半角スペースやHTML→text変換由来の改行が間に挟まる可能性も考慮して
# \sで空白を許容する。
_CAR_SEAT_COMBINED_RE = re.compile(
    r"(\d+)\s*号車\s*(\d+)\s*番\s*([A-Za-zＡ-Ｚａ-ｚ])\s*席"
)


def extract_ekinet(
    message_id: str, relevance: str, subject: str, body_text: str
) -> ReservationCandidate:
    """えきねっとの本文テキストから、取得できた範囲の予約情報のみを抽出する。

    メールに存在しない項目を推測で補完することはせず、見つからなければNoneのまま扱う。
    """
    ride_date_raw = _search_first(
        [r"(?:ご乗車日|乗車日|利用日)[:：]?\s*([0-9]{4}[年/\-][0-9]{1,2}[月/\-][0-9]{1,2}日?)"],
        body_text,
    )
    start_time = _search_first([r"(?:出発時刻|発時刻)[:：]?\s*(\d{1,2}:\d{2})"], body_text)
    end_time = _search_first([r"(?:到着時刻|着時刻)[:：]?\s*(\d{1,2}:\d{2})"], body_text)
    origin = _search_first([r"(?:出発駅|乗車駅)[:：]?\s*([^\s\n（(]+)"], body_text)
    destination = _search_first([r"(?:到着駅|降車駅)[:：]?\s*([^\s\n（(]+)"], body_text)

    # ラベル形式で見つからなかった項目だけを「駅名(時刻) → 駅名(時刻)」の
    # 構造から補う（ラベル形式で既に取得できた値は上書きしない）。
    route_match = _STATION_TIME_ROUTE_RE.search(body_text)
    if route_match:
        route_origin, start_h, start_m, route_destination, end_h, end_m = (
            route_match.groups()
        )
        origin = origin or route_origin.strip()
        destination = destination or route_destination.strip()
        start_time = start_time or f"{int(start_h):02d}:{int(start_m):02d}"
        end_time = end_time or f"{int(end_h):02d}:{int(end_m):02d}"

    if not (origin and destination):
        section_match = re.search(r"([^\s\n→]{2,})\s*→\s*([^\s\n（(]{2,})", body_text)
        if section_match:
            origin = origin or section_match.group(1).strip()
            destination = destination or section_match.group(2).strip()

    train_name = _search_first(
        [
            r"(?:列車名)[:：]?\s*([^\n]*?号)",
            r"([^\s\n]*?(?:のぞみ|ひかり|こだま|はやぶさ|やまびこ|つばさ|とき|かがやき|さくら|みずほ|つるぎ)[^\s\n]*号)",
        ],
        body_text,
    )

    car_number = _search_first([r"(\d+)[ \t]*号車"], body_text)
    if car_number:
        car_number = f"{car_number}号車"

    seat_number = _search_first(
        [r"(?:座席番号|座席)[:：]?\s*([0-9]+[A-Za-zＡ-Ｚ]?番?[A-Za-zＡ-Ｚ]?席?)"], body_text
    )

    # ラベル形式（「座席番号：」等）で見つからなかった場合、「N号車 M番X席」
    # という構造から補う（ラベル形式で既に取得できた値は上書きしない）。
    if not seat_number:
        car_seat_match = _CAR_SEAT_COMBINED_RE.search(body_text)
        if car_seat_match:
            matched_car, seat_num, seat_letter = car_seat_match.groups()
            seat_number = f"{seat_num}番{seat_letter}席"
            car_number = car_number or f"{matched_car}号車"

    reservation_reference = _search_first(
        [r"(?:申込番号|予約番号|受付番号)[:：]?\s*([A-Za-z0-9\-]+)"], body_text
    )

    # confidence判定は、missing_fields（9項目の単純カウント）ではなく、
    # 「予約として重要な項目」（乗車日・区間・列車名・出発/到着時刻）だけを
    # 基準にする（Phase C実機確認でのユーザーからの指摘を反映）。
    core_flags = {
        "ride_date": bool(ride_date_raw),
        "route": bool(origin) and bool(destination),
        "train_name": bool(train_name),
        "times": bool(start_time) and bool(end_time),
    }
    confidence = _confidence_from_core(core_flags)

    values = {
        "ride_date": ride_date_raw,
        "start_time": start_time,
        "end_time": end_time,
        "origin": origin,
        "destination": destination,
        "train_name": train_name,
        "car_number": car_number,
        "seat_number": seat_number,
        "reservation_reference": reservation_reference,
    }
    missing = [label for key, label in _EKINET_FIELD_LABELS.items() if not values.get(key)]

    return ReservationCandidate(
        service="えきねっと",
        message_id=message_id,
        relevance=relevance,
        reservation_type="電車",
        confidence=confidence,
        title=train_name or (subject.strip() or None),
        date=_parse_date_value(ride_date_raw),
        start_time=start_time,
        end_time=end_time,
        origin=origin,
        destination=destination,
        train_name=train_name,
        car_number=car_number,
        seat_number=seat_number,
        hotel_name=None,
        checkin_date=None,
        checkout_date=None,
        amount=None,
        reservation_reference=reservation_reference,
        missing_fields=tuple(missing),
    )


# --------------------------------------------------
# スマートEX（列車予約）の抽出（Web v0.4 Phase D）
#
# Phase D実機確認（スマートEX1回目）により、以下が判明した。
# - 区間・時刻は、えきねっとと同じ「駅名(○時○分) → 駅名(○時○分)」構造
#   （_STATION_TIME_ROUTE_RE、モジュール冒頭のえきねっとセクションで定義）
#   で書かれている。この構造自体は特定サービスに固有のものではないことが
#   2社で確認できたため、ここでも再利用する
# - 号車・座席は、えきねっとの「N号車 M番X席」ほど密着した1つの構造とまでは
#   確認できていない（「号車」「座席」がそれぞれ別の行として現れる構造）。
#   そのため号車は既存の汎用パターンをそのまま使い、座席は「M番X席」という
#   単独の構造（号車との隣接を前提にしない）を新たに追加する
# - 予約識別情報は「お預かり番号」というラベルで表示される
# 引き続き、実際の駅名・列車名・号車・座席番号・予約番号・金額を固定値として
# ハードコードすることはしない。
# --------------------------------------------------
_SMART_EX_FIELD_LABELS = {
    "ride_date": "乗車日",
    "start_time": "出発時刻",
    "end_time": "到着時刻",
    "origin": "出発駅",
    "destination": "到着駅",
    "train_name": "列車名",
    "car_number": "号車",
    "seat_number": "座席番号",
    "reservation_reference": "予約/申込番号",
}

# スマートEX（東海道・山陽・九州新幹線のネット予約サービス）が対象とする
# 新幹線の列車名。実際の列車番号・便名等の個別情報ではなく、各社が公表して
# いる列車種別名（公開情報）であり、実メールから推測したものではない。
_SMART_EX_TRAIN_NAME_KEYWORDS = (
    "のぞみ", "ひかり", "こだま", "みずほ", "さくら", "つばめ",
)

# Phase D実機再確認（スマートEX3回目）で判明したこと：3回目の実機確認でも、
# 「駅名(時刻) → 列車名 → 駅名(時刻)」構造を想定した_SMART_EX_STATION_TRAIN_STATION_RE
# （当初はえきねっとと同じ「○時○分」＝漢字表記の時刻のみを想定）が一致しな
# かった。原因をコード上で特定するため、確認できている構造情報（駅名(時刻)→
# 列車名→駅名(時刻)という並び）はそのままに、時刻部分の表記だけを変えた
# 架空データで機械的に検証したところ、「○時○分」形式では一致する一方、
# 「○:○」（コロン区切り）形式では一致しないことを確認した。コロン区切りの
# 時刻表記は、このモジュール内の他のラベルベース抽出（出発時刻・到着時刻の
# ラベル検索）でも既に採用している一般的な時刻表記であり、実メールからの
# 新たな推測ではなく、既存の許容範囲を時刻部分に拡張したものである。
# 「○時○分」「○:○」のどちらの時刻表記であっても一致するよう、時刻部分の
# サブパターンを共通化した（_SMART_EX_TIME_TOKEN_RE）。
_SMART_EX_TIME_TOKEN_RE = r"(\d{1,2}\s*時\s*\d{1,2}\s*分|\d{1,2}\s*[:：]\s*\d{2})"


def _parse_smart_ex_time_token(raw: str | None) -> str | None:
    """_SMART_EX_TIME_TOKEN_REで取得した時刻表記（○時○分 or ○:○）を
    HH:MM形式へ変換する。どちらの形式にも一致しなければNoneを返す。
    """
    if not raw:
        return None

    match = re.match(r"\s*(\d{1,2})\s*時\s*(\d{1,2})\s*分\s*$", raw)
    if match:
        hour, minute = match.groups()
        return f"{int(hour):02d}:{int(minute):02d}"

    match = re.match(r"\s*(\d{1,2})\s*[:：]\s*(\d{2})\s*$", raw)
    if match:
        hour, minute = match.groups()
        return f"{int(hour):02d}:{int(minute):02d}"

    return None


# スマートEX専用の区間構造（直接隣接／列車名を挟む3区間、いずれも時刻表記は
# 「○時○分」「○:○」の両方を許容する）。えきねっとと共用の
# _STATION_TIME_ROUTE_RE（「○時○分」のみ、直接隣接のみ）はそのまま維持し、
# そちらで一致しなかった場合の追加候補として、この2つを順に試す。
_SMART_EX_STATION_TIME_ROUTE_RE = re.compile(
    r"([^\s\n（(→]{1,20})[（(]\s*" + _SMART_EX_TIME_TOKEN_RE + r"\s*[）)]"
    r"\s*→\s*"
    r"([^\s\n（(→]{1,20})[（(]\s*" + _SMART_EX_TIME_TOKEN_RE + r"\s*[）)]"
)

# 列車名部分の判定は、列車名抽出（train_name）と同じ列車種別キーワード
# リスト（_SMART_EX_TRAIN_NAME_KEYWORDS）を再利用し、ロジックの重複・
# 食い違いを避ける。駅名・時刻・列車名とも固定値ではなく、構造として抽出する。
_SMART_EX_STATION_TRAIN_STATION_RE = re.compile(
    r"([^\s\n（(→]{1,20})[（(]\s*" + _SMART_EX_TIME_TOKEN_RE + r"\s*[）)]"
    r"\s*→\s*"
    r"[^\s\n（(→]{0,10}(?:" + "|".join(_SMART_EX_TRAIN_NAME_KEYWORDS) + r")[^\s\n（(→]{0,10}号"
    r"\s*→\s*"
    r"([^\s\n（(→]{1,20})[（(]\s*" + _SMART_EX_TIME_TOKEN_RE + r"\s*[）)]"
)

# 「M番X席」（号車との隣接を前提にしない、単独の座席表記）。
# 数字・アルファベットとも固定値ではなく構造として抽出する。
_SMART_EX_STANDALONE_SEAT_RE = re.compile(
    r"(\d+)\s*番\s*([A-Za-zＡ-Ｚａ-ｚ])\s*席"
)


def extract_smart_ex(
    message_id: str, relevance: str, subject: str, body_text: str
) -> ReservationCandidate:
    """スマートEXの本文テキストから、取得できた範囲の予約情報のみを抽出する。

    メールに存在しない項目を推測で補完することはせず、見つからなければNoneのまま扱う。
    """
    ride_date_raw = _search_first(
        [r"(?:ご乗車日|乗車日|利用日)[:：]?\s*([0-9]{4}[年/\-][0-9]{1,2}[月/\-][0-9]{1,2}日?)"],
        body_text,
    )
    start_time = _search_first([r"(?:出発時刻|発時刻)[:：]?\s*(\d{1,2}:\d{2})"], body_text)
    end_time = _search_first([r"(?:到着時刻|着時刻)[:：]?\s*(\d{1,2}:\d{2})"], body_text)
    origin = _search_first([r"(?:出発駅|乗車駅)[:：]?\s*([^\s\n（(]+)"], body_text)
    destination = _search_first([r"(?:到着駅|降車駅)[:：]?\s*([^\s\n（(]+)"], body_text)

    # ラベル形式で見つからなかった項目だけを、区間の構造から補う
    # （ラベル形式で既に取得できた値は上書きしない）。
    # 1. まず「駅名(○時○分) → 駅名(○時○分)」の直接隣接構造（えきねっとと
    #    共用、時刻は漢字表記のみ）を試す
    # 2. 一致しなければ、時刻表記が「○:○」の場合にも対応した、スマートEX
    #    専用の直接隣接構造を試す
    # 3. それでも一致しなければ、「駅名(時刻) → 列車名 → 駅名(時刻)」という
    #    3区間構造（時刻表記はどちらも許容）を試す
    route_match = _STATION_TIME_ROUTE_RE.search(body_text)
    if route_match:
        route_origin, start_h, start_m, route_destination, end_h, end_m = (
            route_match.groups()
        )
        origin = origin or route_origin.strip()
        destination = destination or route_destination.strip()
        start_time = start_time or f"{int(start_h):02d}:{int(start_m):02d}"
        end_time = end_time or f"{int(end_h):02d}:{int(end_m):02d}"
    else:
        for flexible_pattern in (
            _SMART_EX_STATION_TIME_ROUTE_RE,
            _SMART_EX_STATION_TRAIN_STATION_RE,
        ):
            flexible_match = flexible_pattern.search(body_text)
            if not flexible_match:
                continue

            route_origin, start_raw, route_destination, end_raw = (
                flexible_match.groups()
            )
            origin = origin or route_origin.strip()
            destination = destination or route_destination.strip()
            start_time = start_time or _parse_smart_ex_time_token(start_raw)
            end_time = end_time or _parse_smart_ex_time_token(end_raw)
            break

    train_name = _search_first(
        [
            r"(?:列車名)[:：]?\s*([^\n]*?号)",
            # 実機確認（3回目）で判明した「→列車名→」のように、列車名の
            # 直前に矢印が空白無しで隣接する構造があったため、矢印を
            # 手前の文字クラスから除外する（矢印を列車名に取り込まないため）。
            r"([^\s\n→]*?(?:"
            + "|".join(_SMART_EX_TRAIN_NAME_KEYWORDS)
            + r")[^\s\n→]*号)",
        ],
        body_text,
    )

    # 「N号車」は日本語の助数詞（数詞＋号車）としての一般的な表記であり、
    # 特定サービスの実メール構造から発見したものではないため、ラベルに
    # 依存しないこの汎用パターンは流用してよいと判断した。
    car_number = _search_first([r"(\d+)[ \t]*号車"], body_text)
    if car_number:
        car_number = f"{car_number}号車"

    seat_number = _search_first(
        [r"(?:座席番号|座席)[:：]?\s*([0-9]+[A-Za-zＡ-Ｚ]?番?[A-Za-zＡ-Ｚ]?席?)"], body_text
    )
    if not seat_number:
        seat_match = _SMART_EX_STANDALONE_SEAT_RE.search(body_text)
        if seat_match:
            seat_num, seat_letter = seat_match.groups()
            seat_number = f"{seat_num}番{seat_letter}席"

    reservation_reference = _search_first(
        [r"(?:お預かり番号|申込番号|予約番号|受付番号)[:：]?\s*([A-Za-z0-9\-]+)"], body_text
    )

    # 実機確認（4回目）で判明した構造：料金はラベル形式（「料金：」等）ではなく、
    # 「領収額は、合計XXXX円です。」という文章の中に埋め込まれている。
    # 「領収額」と「合計」という2つの語が近接して現れ、その直後に金額＋「円」が
    # 続く、という構造そのものをパターン化する（間の「は、」等の助詞・読点は
    # 固定文言としてハードコードせず、10文字以内の任意の文字として許容する）。
    # 「領収額」「合計」の両方が近接して現れない限り一致しないため、本文中の
    # 無関係な数字（会員番号・予約番号・列車番号・日付・時刻・ICカード番号等）
    # を誤って金額として取得するリスクは低い。
    amount_raw = _search_first(
        [
            r"(?:運賃|料金|合計金額|合計料金|お支払い金額)[:：]?\s*([¥$]?\s*[0-9][0-9,]*\s*円?)",
            r"領収額[^\n]{0,10}合計[ \t　]*([0-9][0-9,]*)[ \t　]*円",
        ],
        body_text,
    )
    amount = _parse_amount(amount_raw)

    core_flags = {
        "ride_date": bool(ride_date_raw),
        "route": bool(origin) and bool(destination),
        "train_name": bool(train_name),
        "times": bool(start_time) and bool(end_time),
    }
    confidence = _confidence_from_core(core_flags)

    values = {
        "ride_date": ride_date_raw,
        "start_time": start_time,
        "end_time": end_time,
        "origin": origin,
        "destination": destination,
        "train_name": train_name,
        "car_number": car_number,
        "seat_number": seat_number,
        "reservation_reference": reservation_reference,
    }
    missing = [
        label for key, label in _SMART_EX_FIELD_LABELS.items() if not values.get(key)
    ]

    return ReservationCandidate(
        service="スマートEX",
        message_id=message_id,
        relevance=relevance,
        reservation_type="電車",
        confidence=confidence,
        title=train_name or (subject.strip() or None),
        date=_parse_date_value(ride_date_raw),
        start_time=start_time,
        end_time=end_time,
        origin=origin,
        destination=destination,
        train_name=train_name,
        car_number=car_number,
        seat_number=seat_number,
        hotel_name=None,
        checkin_date=None,
        checkout_date=None,
        amount=amount,
        reservation_reference=reservation_reference,
        missing_fields=tuple(missing),
    )


# --------------------------------------------------
# Agoda（宿泊予約）の抽出
# --------------------------------------------------
_AGODA_FIELD_LABELS = {
    "hotel_name": "ホテル名",
    "checkin_date": "チェックイン日",
    "checkout_date": "チェックアウト日",
    "reservation_reference": "予約ID",
    "amount": "料金",
}


# ホテル名のラベル候補。実メールにはこの形の明示的なラベルが無い場合が
# あることが分かっているため（design.md 14.8参照）、見つからなければ
# 下の「見出し語」方式（_extract_hotel_name_after_anchor）を試す。
_AGODA_HOTEL_NAME_LABELS = [
    r"ホテル名",
    r"宿泊施設名",
    r"宿泊施設",
    r"施設名",
    r"宿泊先",
    r"物件名",
    r"Hotel\s*Name",
    r"Property\s*Name",
    r"Property",
]

# Phase C実機確認（Agoda3回目）で判明した構造：実メールでは「予約確認」等の
# 見出し語に続けてホテル名（英語名＋日本語名が連続する場合もある）が
# 記載されている。これらの語は分類ロジック（SUBJECT_CLASSIFICATION_RULES の
# Agoda対象キーワード）と同じものを流用しており、特定のホテル名・件名文言を
# ハードコードしているわけではない。
_AGODA_HOTEL_NAME_ANCHORS = (
    "予約確認",
    "ご予約",
    "予約完了",
    "Booking Confirmation",
    "Booking Confirmed",
    "Confirmation",
)

# 見出し語の直後に続くテキストをホテル名候補として採用してよいかの安全弁。
# 極端に長い、または文章らしい記号・語（句点・感謝の言葉・他項目のラベル等）
# を含む場合は、後続の文章まで誤って取り込んだ可能性が高いためNoneを維持する。
_HOTEL_NAME_MAX_LENGTH = 80
_HOTEL_NAME_REJECT_MARKERS = (
    "。", "！", "？", "!", "?",
    "ありがとう", "様", "円",
    "チェックイン", "チェックアウト", "Check-in", "Check-out",
    "予約ID", "Booking ID", "予約番号",
)


# 実機確認で判明したバグ：HTML→text変換後の本文では、「予約確認」等の
# 見出し語がバナー見出しと本文セクション見出しの2箇所に続けて現れることが
# あり、1つ目の見出し語の直後（空行を挟んだ次のまとまり）が2つ目の見出し語
# そのものになる場合がある。この場合、見出し語自体をホテル名として誤って
# 返してしまっていた。そのため、切り出した値が見出し語そのものと一致する
# 場合は明示的に却下する（_is_plausible_hotel_name）。加えて、1回目の
# 見出し語出現が別の見出し語の重複だった場合に備え、同じ見出し語の
# 2回目以降の出現（上限あり）も順に試す（_extract_hotel_name_after_anchor）。
_MAX_ANCHOR_OCCURRENCES_TO_TRY = 5


def _is_plausible_hotel_name(candidate: str | None) -> bool:
    if not candidate:
        return False
    if len(candidate) > _HOTEL_NAME_MAX_LENGTH:
        return False
    if any(marker in candidate for marker in _HOTEL_NAME_REJECT_MARKERS):
        return False

    # 見出し語（「予約確認」等）自体がそのままホテル名として返らないように
    # する。見出し語はホテル名を探すための手がかりであり、それ自体が
    # ホテル名であることはない。大文字小文字を無視して比較する
    # （英語見出し語"Confirmation"等のため）。
    normalized = candidate.strip().casefold()
    if any(normalized == anchor.casefold() for anchor in _AGODA_HOTEL_NAME_ANCHORS):
        return False

    return True


def _extract_hotel_name_after_anchor(text: str) -> str | None:
    """「予約確認」等の見出し語の直後に続くテキストをホテル名候補として取り出す。

    見出し語自体は固定のホテル名ではなく、Agodaの予約確認メールに共通して
    現れる語（分類ロジックの対象キーワードと同じ）を手がかりにしている。
    改行をまたいだ範囲は候補にせず（同じ行のみ）、直後のテキストが長すぎる・
    文章らしい記号を含む・見出し語自体と一致する等、ホテル名としての妥当性が
    疑わしい場合は、無理に切り出さずNoneを返す（安全側の設計）。

    見出し語の直後に区切り文字（コロン・空白・改行・文字列終端等）が続く
    場合のみ見出し語として採用する。この境界チェックが無いと、見出し語が
    ホテル名自体の一部と偶然一致するケースを誤って拾ってしまう。

    同じ見出し語が複数回出現する場合（例：バナー見出しと本文セクション
    見出しで2回現れる等）、1回目の出現の直後が見出し語自体でホテル名として
    妥当でなければ、2回目以降の出現も順に試す（上限あり）。
    """
    if not text:
        return None

    for anchor in _AGODA_HOTEL_NAME_ANCHORS:
        # 英語見出し語（Confirmation等）は実メールでの大文字小文字表記が
        # 完全に一致しない可能性があるため、大文字小文字を無視して照合する
        # （日本語の見出し語には影響しない）。
        pattern = re.compile(rf"{re.escape(anchor)}(?=[\s:：\-－|｜]|$)", re.IGNORECASE)

        for occurrence, match in enumerate(pattern.finditer(text)):
            if occurrence >= _MAX_ANCHOR_OCCURRENCES_TO_TRY:
                break

            remainder = text[match.end():]
            # 見出し語直後の区切り記号（コロン・ダッシュ・スペース類）を読み飛ばす。
            remainder = re.sub(r"^[\s:：\-－|｜]+", "", remainder)

            same_line = remainder.split("\n", 1)[0].strip()

            if _is_plausible_hotel_name(same_line):
                return same_line

    return None


def _extract_agoda_hotel_name(body_text: str, subject: str, snippet: str) -> str | None:
    """ホテル名を、信頼度の高い手がかりから順に試す。

    1. 明示的なラベル（「ホテル名：」等）があれば最優先する
    2. 件名（1行で完結しており誤抽出のリスクが低い）から見出し語の直後を試す
    3. 本文中の見出し語の直後を試す
    4. Gmail snippet（検索結果に表示済みの短い抜粋）を最後の手がかりとして試す

    いずれも見つからない、または妥当性が疑わしい場合はNoneのまま返す
    （メールに存在しない値を推測で生成しない）。
    """
    labeled = _search_label_value(_AGODA_HOTEL_NAME_LABELS, body_text)
    if _is_plausible_hotel_name(labeled):
        return labeled

    subject_based = _extract_hotel_name_after_anchor(subject)
    if subject_based:
        return subject_based

    body_based = _extract_hotel_name_after_anchor(body_text)
    if body_based:
        return body_based

    snippet_based = _extract_hotel_name_after_anchor(snippet)
    if snippet_based:
        return snippet_based

    return None


def extract_agoda(
    message_id: str,
    relevance: str,
    subject: str,
    body_text: str,
    *,
    snippet: str = "",
) -> ReservationCandidate:
    """Agodaの本文テキストから、取得できた範囲の宿泊予約情報のみを抽出する。

    メールに存在しない項目を推測で補完することはせず、見つからなければNoneのまま扱う。
    snippetは、Phase Bの候補一覧取得時点で既に取得済みのGmail生成の短い抜粋
    （本文全文ではない）。ホテル名抽出の最後の手がかりとしてのみ使う。
    """
    hotel_name = _extract_agoda_hotel_name(body_text, subject, snippet)

    # チェックイン/チェックアウト日は、実メールでは「チェックイン日：」の
    # すぐ後ろではなく、曜日を挟んだ別の行に日付が書かれている場合がある
    # （例：「チェックイン日：\n水 2026年7月10日\n（15:00以降）」）。
    # ラベル直後の値を同じ行で厳密にキャプチャするのではなく、ラベルの
    # 近く（既定80文字）から日付パターンだけを探すことで、曜日等の
    # 前置き文字があっても日付を取得できるようにしている。
    checkin_raw = _find_date_near_label(body_text, r"(?:チェックイン(?:日)?|Check-?in)")
    checkout_raw = _find_date_near_label(body_text, r"(?:チェックアウト(?:日)?|Check-?out)")
    checkin_date = _parse_date_value(checkin_raw)
    checkout_date = _parse_date_value(checkout_raw)

    reservation_reference = _search_first(
        [r"(?:予約ID|Booking\s*ID|予約番号)[:：]?\s*([A-Za-z0-9\-]+)"], body_text
    )

    amount_raw = _search_first(
        [
            r"(?:合計金額|合計料金|お支払い金額|料金|Total\s*Price)[:：]?\s*([¥$]?\s*[0-9][0-9,]*\s*円?)"
        ],
        body_text,
    )
    amount = _parse_amount(amount_raw)

    # confidence判定は、missing_fields（5項目の単純カウント）ではなく、
    # 「予約として重要な項目」（ホテル名・チェックイン日・チェックアウト日）
    # だけを基準にする（Phase C実機確認でのユーザーからの指摘を反映）。
    core_flags = {
        "hotel_name": bool(hotel_name),
        "checkin_date": bool(checkin_date),
        "checkout_date": bool(checkout_date),
    }
    confidence = _confidence_from_core(core_flags)

    values = {
        "hotel_name": hotel_name,
        "checkin_date": checkin_raw,
        "checkout_date": checkout_raw,
        "reservation_reference": reservation_reference,
        "amount": amount_raw,
    }
    missing = [label for key, label in _AGODA_FIELD_LABELS.items() if not values.get(key)]

    return ReservationCandidate(
        service="Agoda",
        message_id=message_id,
        relevance=relevance,
        reservation_type="ホテル",
        confidence=confidence,
        title=hotel_name or (subject.strip() or None),
        date=checkin_date,
        start_time=None,
        end_time=None,
        origin=None,
        destination=None,
        train_name=None,
        car_number=None,
        seat_number=None,
        hotel_name=hotel_name,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        amount=amount,
        reservation_reference=reservation_reference,
        missing_fields=tuple(missing),
    )


# --------------------------------------------------
# スカイマーク（飛行機予約）の抽出（Web v0.4 Phase D）
#
# Phase D後半の実機確認により、以下の構造が判明した（design.md参照）。
#
#   2026年09月10日(木)
#   SKY 123便
#   [予約番号：5678]
#   羽田 発 08:15 → 福岡 着 10:10
#   いま得
#
# 搭乗日・便名・区間/時刻はいずれもラベル（「搭乗日：」等）を伴わない
# 構造で書かれている。既存のラベル形式抽出はそのまま残し、見つからない
# 場合の構造依存フォールバックとして以下を追加する。予約番号のみ既存の
# ラベル形式（「予約番号：」）と一致するため、変更していない。
# --------------------------------------------------
_SKYMARK_FIELD_LABELS = {
    "boarding_date": "搭乗日",
    "start_time": "出発時刻",
    "end_time": "到着時刻",
    "origin": "出発空港",
    "destination": "到着空港",
    "flight_number": "便名",
    "reservation_reference": "予約/申込番号",
    "seat_number": "座席番号",
}

# ラベルの無い「YYYY年MM月DD日(曜日)」構造。曜日部分は半角/全角括弧、
# 1〜4文字程度（例："木"・"水曜"）を許容し、曜日自体の有無は問わない。
# 日付そのものはハードコードせず、パターンとして抽出する。
_SKYMARK_BARE_DATE_RE = re.compile(
    r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"
    r"(?:\s*[（(][^）)\n]{1,4}[）)])?"
)

# 「SKY 123便」のように、数字の後ろに助数詞「便」が続く構造
# （えきねっとの「N号車」と同じ発想）。"SKY"はスカイマークの公表されている
# 便名の接頭辞（公開情報）であり任意とし、実際の便番号は固定値にしない。
_SKYMARK_FLIGHT_NUMBER_RE = re.compile(r"(SKY)?\s*(\d{2,4})\s*便", re.IGNORECASE)


def _extract_skymark_flight_number(body_text: str) -> str | None:
    """「SKY 123便」のような構造から便名を抽出する。

    "SKY"が実際に本文にあればそれを含めて再構成し（"SKY 123便"）、
    無ければ数字＋便のみを返す（"123便"）。既存flight_numberフィールドの
    表示（登録候補プレビュー）で、サービスを識別できる自然な形になるよう
    にしている。
    """
    match = _SKYMARK_FLIGHT_NUMBER_RE.search(body_text)
    if not match:
        return None

    prefix, number = match.groups()
    if prefix:
        return f"SKY {number}便"
    return f"{number}便"


# 「空港名 発 HH:MM → 空港名 着 HH:MM」というスカイマーク固有の構造。
# スマートEX用の正規表現（駅名(時刻)構造）とは異なるため流用せず、
# スカイマーク専用パターンとして実装する。全角/半角スペース・改行・
# 全角/半角コロンの揺れを許容する。えきねっとの列車名が矢印を取り込んで
# しまった過去の不具合を踏まえ、空港名の文字クラスから「発」「着」「→」を
# 除外し、区切り文字を誤って空港名に取り込まないようにしている。
_SKYMARK_ROUTE_RE = re.compile(
    r"([^\s\n→発着]{1,10})\s*発\s*(\d{1,2}\s*[:：]\s*\d{2})"
    r"\s*→\s*"
    r"([^\s\n→発着]{1,10})\s*着\s*(\d{1,2}\s*[:：]\s*\d{2})"
)


def _parse_skymark_time_token(raw: str | None) -> str | None:
    """_SKYMARK_ROUTE_REで取得した時刻表記をHH:MM形式へ変換する。

    全角コロン・区切り文字前後の空白を許容する。一致しなければNoneを返す。
    """
    if not raw:
        return None

    match = re.match(r"\s*(\d{1,2})\s*[:：]\s*(\d{2})\s*$", raw)
    if not match:
        return None

    hour, minute = match.groups()
    return f"{int(hour):02d}:{minute}"


# Phase D後半（座席番号対応）で実機確認された、座席番号の2つの表現パターン。
#
# パターンA：決済済み系メール本文の「座席番号：17H」のような、明確な
# ラベル形式（空白・半角/全角コロンの揺れを許容）。extract_skymark()内で
# _search_firstへ直接渡すため、ここでは定数化していない。
#
# パターンB：座席指定完了メール本文の「ご搭乗者／座席番号」という見出しの
# 下に、「架空 太郎 様（大人）/19C」のように搭乗者情報の末尾へ座席番号が
# 付く形式。本文中の「/[数字][アルファベット]」を無条件に拾うと、URL・
# 日付・予約番号等を誤って座席番号として取得してしまう恐れがあるため、
# 以下の2つを両方満たす場合のみ採用する。
# (1) 「搭乗者」「座席番号」という語が近接して現れる見出し文脈があること
# (2) その見出しより後ろで、氏名の敬称「様」に続けて「/座席コード」という
#     構造が見つかること
# 見出し文脈が確認できない場合は一切抽出しない（安全側の設計）。
_SKYMARK_SEAT_CONTEXT_RE = re.compile(r"搭乗者[^\n]{0,20}座席番号")
_SKYMARK_PASSENGER_SEAT_RE = re.compile(r"様[^\n]{0,10}/\s*([0-9]{1,3}[A-Za-z])")


def _extract_skymark_passenger_seat(body_text: str) -> str | None:
    """「ご搭乗者／座席番号」という見出し文脈が確認できる場合に限り、
    搭乗者情報末尾の「/19C」のような座席番号を抽出する。
    """
    context_match = _SKYMARK_SEAT_CONTEXT_RE.search(body_text)
    if not context_match:
        return None

    passenger_match = _SKYMARK_PASSENGER_SEAT_RE.search(body_text[context_match.end():])
    if not passenger_match:
        return None

    return passenger_match.group(1)


def extract_skymark(
    message_id: str, relevance: str, subject: str, body_text: str
) -> ReservationCandidate:
    """スカイマークの本文テキストから、取得できた範囲の予約情報のみを抽出する。

    メールに存在しない項目を推測で補完することはせず、見つからなければNoneのまま扱う。
    """
    boarding_date_raw = _search_first(
        [
            r"(?:ご搭乗日|搭乗日|利用日)[:：]?\s*([0-9]{4}[年/\-][0-9]{1,2}[月/\-][0-9]{1,2}日?)",
        ],
        body_text,
    )
    if not boarding_date_raw:
        bare_date_match = _SKYMARK_BARE_DATE_RE.search(body_text)
        if bare_date_match:
            boarding_date_raw = bare_date_match.group(1)

    start_time = _search_first([r"(?:出発時刻)[:：]?\s*(\d{1,2}:\d{2})"], body_text)
    end_time = _search_first([r"(?:到着時刻)[:：]?\s*(\d{1,2}:\d{2})"], body_text)
    origin = _search_first([r"(?:出発空港)[:：]?\s*([^\s\n（(]+)"], body_text)
    destination = _search_first([r"(?:到着空港)[:：]?\s*([^\s\n（(]+)"], body_text)

    # ラベル形式で見つからなかった項目だけを、「空港名 発 HH:MM → 空港名
    # 着 HH:MM」という構造から補う（ラベル形式で既に取得できた値は
    # 上書きしない）。
    if not (origin and destination and start_time and end_time):
        route_match = _SKYMARK_ROUTE_RE.search(body_text)
        if route_match:
            route_origin, start_raw, route_destination, end_raw = route_match.groups()
            origin = origin or route_origin.strip()
            destination = destination or route_destination.strip()
            start_time = start_time or _parse_skymark_time_token(start_raw)
            end_time = end_time or _parse_skymark_time_token(end_raw)

    flight_number = _search_first([r"(?:便名|便)[:：]?\s*([A-Za-z0-9\-]+)"], body_text)
    if not flight_number:
        flight_number = _extract_skymark_flight_number(body_text)

    reservation_reference = _search_first(
        [r"(?:予約番号|申込番号|受付番号)[:：]?\s*([A-Za-z0-9\-]+)"], body_text
    )

    # パターンA（「座席番号：17H」等の明確なラベル）を優先し、無ければ
    # パターンB（「ご搭乗者／座席番号」の見出し文脈がある場合の
    # 「様.../19C」構造）を試す。座席番号は予約として重要な項目とは
    # 別枠の付随情報のため、confidence判定（core_flags）には含めない
    # （えきねっとの座席番号と同じ扱い）。
    seat_number = _search_first(
        [r"座席番号\s*[:：]\s*([0-9]{1,3}[A-Za-z])"], body_text
    )
    if not seat_number:
        seat_number = _extract_skymark_passenger_seat(body_text)

    core_flags = {
        "boarding_date": bool(boarding_date_raw),
        "route": bool(origin) and bool(destination),
        "flight_number": bool(flight_number),
        "times": bool(start_time) and bool(end_time),
    }
    confidence = _confidence_from_core(core_flags)

    values = {
        "boarding_date": boarding_date_raw,
        "start_time": start_time,
        "end_time": end_time,
        "origin": origin,
        "destination": destination,
        "flight_number": flight_number,
        "reservation_reference": reservation_reference,
        "seat_number": seat_number,
    }
    missing = [
        label for key, label in _SKYMARK_FIELD_LABELS.items() if not values.get(key)
    ]

    return ReservationCandidate(
        service="スカイマーク",
        message_id=message_id,
        relevance=relevance,
        reservation_type="飛行機",
        confidence=confidence,
        title=flight_number or (subject.strip() or None),
        date=_parse_date_value(boarding_date_raw),
        start_time=start_time,
        end_time=end_time,
        origin=origin,
        destination=destination,
        train_name=None,
        car_number=None,
        seat_number=seat_number,
        hotel_name=None,
        checkin_date=None,
        checkout_date=None,
        amount=None,
        reservation_reference=reservation_reference,
        flight_number=flight_number,
        fare_type=None,
        missing_fields=tuple(missing),
    )


# --------------------------------------------------
# エントリポイント
# --------------------------------------------------
def analyze_email(
    *,
    service: str,
    message_id: str,
    relevance: str,
    subject: str,
    text_plain: str,
    text_html: str,
    snippet: str = "",
    thread_id: str | None = None,
) -> ReservationCandidate:
    """本文テキスト（plain/html）から登録候補を抽出する。サービスごとに処理を振り分ける。

    snippetは省略可能（Phase Bの候補一覧取得時点で既に取得済みのGmail生成の
    短い抜粋）。Agodaのホテル名抽出で、本文・件名から取得できなかった場合の
    最後の手がかりとしてのみ使う。

    thread_idも省略可能（Phase E-2B。GmailMessageCandidate.thread_idを
    そのまま渡す想定）。各extract_*()関数自体は変更せず、結果の
    ReservationCandidateへdataclasses.replace()でthread_idだけを
    後付けする形にすることで、既存の抽出ロジック・既存の呼び出し
    （thread_idを渡さない呼び出し）には一切影響しない。
    """
    body_text = resolve_body_text(text_plain, text_html)

    if service == "えきねっと":
        candidate = extract_ekinet(message_id, relevance, subject, body_text)
    elif service == "スマートEX":
        candidate = extract_smart_ex(message_id, relevance, subject, body_text)
    elif service == "Agoda":
        candidate = extract_agoda(message_id, relevance, subject, body_text, snippet=snippet)
    elif service == "スカイマーク":
        candidate = extract_skymark(message_id, relevance, subject, body_text)
    else:
        raise ValueError(f"未対応のサービスです: {service}")

    if thread_id:
        candidate = replace(candidate, thread_id=thread_id)

    return candidate


# --------------------------------------------------
# 登録内容（title / memo）の組み立て（Phase E-2B）
#
# reservationsテーブルには、origin/destination/start_time/end_time/
# train_name/flight_number/car_number/seat_number/fare_typeに対応する
# 専用列がまだ無い（claude_report.md「Phase E-2A」参照）。今回はDB列を
# 追加せず、これらの情報をtitle（区間つきの短い予約名）とmemo（固定
# ラベル形式の一覧）へ変換して保存する。メールに存在しない値を推測で
# 補うことはしない（値がNoneの項目はtitle/memoのいずれからも省略する）。
# --------------------------------------------------
def build_reservation_title(candidate: ReservationCandidate) -> str | None:
    """登録候補から、TripFlow予約の「予約名」を組み立てる。

    えきねっと/スマートEX：列車名 + 区間（例：「のぞみ1号 東京→新大阪」）
    スカイマーク：便名 + 区間（例：「SKY123便 羽田→福岡」）
    Agoda：ホテル名のみ

    区間（origin/destination）が無ければ列車名/便名のみを使い、
    列車名/便名自体も無ければ、既存のcandidate.title
    （件名等へのフォールバックを含む、extract_*()側で既に組み立て済みの値）
    をそのまま使う。
    """
    if candidate.service in ("えきねっと", "スマートEX"):
        name = candidate.train_name
    elif candidate.service == "スカイマーク":
        name = candidate.flight_number
    elif candidate.service == "Agoda":
        return candidate.hotel_name or candidate.title
    else:
        return candidate.title

    if name and candidate.origin and candidate.destination:
        return f"{name} {candidate.origin}→{candidate.destination}"
    if name:
        return name
    return candidate.title


def build_reservation_memo(candidate: ReservationCandidate) -> str:
    """登録候補から、DBに専用列が無い情報をmemoへ整形する。

    1行1項目・固定ラベル・固定順序とし、値がNoneの項目は行ごと省略する。
    自由文章は混在させない（将来DB列を追加した際に、可能な範囲で機械的に
    読み取れる形式を保つため）。
    """
    lines: list[str] = []

    if candidate.origin:
        lines.append(f"出発：{candidate.origin}")
    if candidate.destination:
        lines.append(f"到着：{candidate.destination}")
    if candidate.start_time and candidate.end_time:
        lines.append(f"時刻：{candidate.start_time} → {candidate.end_time}")
    if candidate.train_name:
        lines.append(f"列車：{candidate.train_name}")
    if candidate.flight_number:
        lines.append(f"便名：{candidate.flight_number}")
    if candidate.car_number:
        lines.append(f"号車：{candidate.car_number}")
    if candidate.seat_number:
        lines.append(f"座席：{candidate.seat_number}")
    if candidate.fare_type:
        lines.append(f"運賃種別：{candidate.fare_type}")

    return "\n".join(lines)
