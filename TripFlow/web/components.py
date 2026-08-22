"""予約・出張情報の表示に関する共通定数・ヘルパー・整形関数。

app.pyの複数箇所（ホーム／出張／カレンダーの各タブ）で重複していた
表示ロジックをここに集約する。Streamlit本体のレイアウト構築（st.tabs等）
はapp.py側に残し、ここには「データをどう文字列・値へ整形するか」に
関する処理だけを置く。
"""

from __future__ import annotations

import html
import sqlite3
from datetime import date
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import streamlit as st

ALLOWED_URL_SCHEMES = {"http", "https"}

CATEGORY_OPTIONS = ["業務", "プライベート", "未分類"]
RESERVATION_TYPE_OPTIONS = ["往路", "ホテル", "復路", "その他"]
RESERVATION_STATUS_OPTIONS = ["予約済み", "未予約", "キャンセル"]
RESERVATION_SERVICE_OPTIONS = ["えきねっと", "スマートEX", "スカイマーク", "Agoda", "その他"]

# サービス → カレンダーの色分けCSSクラス対応表。
# サービスが増えたらここに1行追加するだけで対応できる。
SERVICE_CSS_CLASSES = {
    "えきねっと": "cal-bar-ekinet",
    "スマートEX": "cal-bar-smartex",
    "スカイマーク": "cal-bar-skymark",
    "Agoda": "cal-bar-agoda",
    "その他": "cal-bar-other",
}

# サービス → カレンダー表示用アイコン対応表。
# えきねっとと区別しやすいよう、スマートEXには別の新幹線アイコンを充てている
# （Web v0.4 Phase Dで、Gmail連携の候補一覧上でも視覚的に区別できるように変更）。
SERVICE_ICONS = {
    "えきねっと": "🚄",
    "スマートEX": "🚅",
    "スカイマーク": "✈️",
    "Agoda": "🏨",
    "その他": "📌",
}


def _format_date(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%Y/%m/%d")


def _format_amount(amount: int | None) -> str:
    return f"{int(amount or 0):,}円"


def _status_line(label: str, is_ok: bool) -> str:
    if is_ok:
        return f"✅ {label}"
    return f"⚠️ {label}未予約"


def _safe_reservation_url(raw_url: str | None) -> str | None:
    """予約確認URLを表示用に安全化する。

    http/https以外のスキーム（javascript:, data:, file: など）は
    リンクとして扱わずNoneを返す。スキームが無い場合はhttps://を補う。
    保存されている生データそのものは変更しない（表示時のみの判定）。
    """
    if not raw_url:
        return None

    url = raw_url.strip()

    if not url:
        return None

    parsed = urlsplit(url)

    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlsplit(url)

    if parsed.scheme not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        return None

    return url


def _reservation_status_suffix(status: str) -> str:
    if status == "キャンセル":
        return "（キャンセル）"
    if status == "未予約":
        return "（未予約）"
    return ""


def _reservation_period_display(reservation: sqlite3.Row) -> str:
    if reservation["reservation_type"] == "ホテル":
        check_in_raw = reservation["check_in_date"] or reservation["reservation_date"]
        check_out_raw = reservation["check_out_date"]

        if check_out_raw:
            return f"{_format_date(check_in_raw)}〜{_format_date(check_out_raw)}"

        return _format_date(check_in_raw)

    return _format_date(reservation["reservation_date"])


def _hotel_stay_phase(check_in: date, check_out: date | None, day: date) -> str:
    if check_out is None or day == check_in:
        return "チェックイン"
    if day == check_out:
        return "チェックアウト"
    return "宿泊中"


def _reservation_overlaps_range(
    reservation: sqlite3.Row, range_start: date, range_end: date
) -> bool:
    if reservation["reservation_type"] == "ホテル":
        check_in = date.fromisoformat(
            reservation["check_in_date"] or reservation["reservation_date"]
        )
        check_out_raw = reservation["check_out_date"]
        check_out = date.fromisoformat(check_out_raw) if check_out_raw else check_in
        return check_in <= range_end and check_out >= range_start

    reservation_day = date.fromisoformat(reservation["reservation_date"])
    return range_start <= reservation_day <= range_end


def _reservation_matches_day(reservation: sqlite3.Row, day: date) -> bool:
    return _reservation_overlaps_range(reservation, day, day)


def _reservation_bar_label(reservation: sqlite3.Row, day: date) -> str:
    service = reservation["reservation_service"]
    icon = SERVICE_ICONS.get(service, "📌")
    status_suffix = _reservation_status_suffix(reservation["status"])

    if reservation["reservation_type"] == "ホテル":
        check_in = date.fromisoformat(
            reservation["check_in_date"] or reservation["reservation_date"]
        )
        check_out_raw = reservation["check_out_date"]
        check_out = date.fromisoformat(check_out_raw) if check_out_raw else None
        phase = _hotel_stay_phase(check_in, check_out, day)
        return f"{icon} {phase}・{service}{status_suffix}"

    return f"{icon} {reservation['reservation_type']}・{service}{status_suffix}"


def filter_matching_trips_for_candidate(
    all_trips: Iterable[sqlite3.Row], candidate_date: date
) -> list[sqlite3.Row]:
    """予約日（candidate_date）がstart_date〜end_dateに含まれるTripだけを返す（Phase E-4）。

    Gmail解析候補の「登録先の出張」選択肢を、予約日と無関係な出張へ絞り込む
    ための純粋関数。trip.start_date <= candidate_date <= trip.end_date を
    満たすTripだけを、元の並び順のまま返す（一致0件なら空リスト）。
    """
    return [
        trip
        for trip in all_trips
        if date.fromisoformat(trip["start_date"])
        <= candidate_date
        <= date.fromisoformat(trip["end_date"])
    ]


def _shift_month(target_date: date, delta: int) -> date:
    month_index = target_date.month - 1 + delta
    year = target_date.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _month_bounds(target_date: date) -> tuple[date, date]:
    import calendar as calendar_module

    month_start = date(target_date.year, target_date.month, 1)
    _, last_day_num = calendar_module.monthrange(target_date.year, target_date.month)
    month_end = date(target_date.year, target_date.month, last_day_num)
    return month_start, month_end


# --------------------------------------------------
# 出張・予約1件を1行のMarkdownテキストへ整形する共通関数。
# ホーム／カレンダーの複数箇所で同じ組み立てをしていたものを集約。
# --------------------------------------------------
def format_trip_line(trip: sqlite3.Row, *, prefix: str = "-") -> str:
    return (
        f"{prefix} **{trip['name']}**　"
        f"{_format_date(trip['start_date'])} 〜 {_format_date(trip['end_date'])}"
        f"　／　{trip['destination']}"
    )


def format_reservation_line(reservation: sqlite3.Row) -> str:
    icon = SERVICE_ICONS.get(reservation["reservation_service"], "📌")
    status_suffix = _reservation_status_suffix(reservation["status"])
    return (
        f"- {icon} {reservation['reservation_type']}・"
        f"{reservation['reservation_service']}／{reservation['title']}／"
        f"{_reservation_period_display(reservation)}／"
        f"{_format_amount(reservation['amount'])}{status_suffix}"
    )


def format_reservation_month_line(reservation: sqlite3.Row) -> str:
    service = reservation["reservation_service"]
    icon = SERVICE_ICONS.get(service, "📌")
    status_suffix = _reservation_status_suffix(reservation["status"])
    return (
        f"- {_reservation_period_display(reservation)}　"
        f"{icon} {reservation['reservation_type']}・{service}　"
        f"{reservation['title']}{status_suffix}"
    )


# --------------------------------------------------
# 予約の状態・ホテル宿泊フェーズをバッジ風の短いテキストへ変換する対応表。
# --------------------------------------------------
STATUS_BADGES = {
    "予約済み": "✅ 予約済み",
    "未予約": "⚠️ 未予約",
    "キャンセル": "🚫 キャンセル",
}

HOTEL_PHASE_BADGES = {
    "チェックイン": "🟢 チェックイン",
    "宿泊中": "🔵 宿泊中",
    "チェックアウト": "🟠 チェックアウト",
}


def render_trip_card(trip: sqlite3.Row) -> None:
    """出張1件をカード形式で表示する（カレンダーの日付詳細等で使用）。"""
    with st.container(border=True):
        st.markdown(format_trip_line(trip, prefix="🧳"))
        if trip["memo"]:
            st.caption(trip["memo"])


def _render_field_rows(fields: list[tuple[str, str]]) -> str:
    """「項目名」を上、「値」を下に積んだ行の並びをHTMLで組み立てる。

    横に「ラベル：値」を並べる形式だと、スマホ幅では値が長い場合に
    折り返しや文字詰まりが起きやすいため、常に縦積みにしている。
    """
    rows = "".join(
        '<div class="rescard-field">'
        f'<div class="rescard-label">{html.escape(label)}</div>'
        f'<div class="rescard-value">{html.escape(str(value))}</div>'
        "</div>"
        for label, value in fields
    )
    return f'<div class="rescard-fields">{rows}</div>'


def render_reservation_card(
    reservation: sqlite3.Row, *, context_day: date | None = None
) -> None:
    """予約1件を、必要な項目をすべて含むカード形式で表示する。

    種類／サービス／予約名／利用日（ホテルはチェックイン・チェックアウト）／
    金額／予約番号／予約確認URL／状態／メモを表示する。値が無い項目は
    「なし」と表示する。context_dayを渡すと（カレンダーの日付詳細から
    呼ぶ場合）、ホテル予約についてチェックイン／宿泊中／チェックアウトの
    バッジを追加表示する。各項目は「項目名」を上・「値」を下に積んだ形式で
    表示し、スマホ幅でも文字詰まりが起きにくいようにしている。
    """
    icon = SERVICE_ICONS.get(reservation["reservation_service"], "📌")
    reservation_type = reservation["reservation_type"]
    is_hotel = reservation_type == "ホテル"

    check_in_raw = check_out_raw = None
    if is_hotel:
        check_in_raw = reservation["check_in_date"] or reservation["reservation_date"]
        check_out_raw = reservation["check_out_date"]

    with st.container(border=True):
        header_badges = [STATUS_BADGES.get(reservation["status"], reservation["status"])]

        if is_hotel and context_day is not None:
            check_in = date.fromisoformat(check_in_raw)
            check_out = date.fromisoformat(check_out_raw) if check_out_raw else None
            phase = _hotel_stay_phase(check_in, check_out, context_day)
            header_badges.append(HOTEL_PHASE_BADGES.get(phase, phase))

        st.markdown(f"**{icon} {reservation['title'] or '（予約名未設定）'}**")
        st.caption("　".join(header_badges))

        fields_before_url: list[tuple[str, str]] = [
            ("種類", reservation_type),
            ("サービス", reservation["reservation_service"]),
            ("予約名", reservation["title"] or "なし"),
        ]

        if is_hotel:
            fields_before_url.append(("チェックイン日", _format_date(check_in_raw)))
            fields_before_url.append(
                (
                    "チェックアウト日",
                    _format_date(check_out_raw) if check_out_raw else "未設定",
                )
            )
        else:
            fields_before_url.append(
                ("利用日", _format_date(reservation["reservation_date"]))
            )

        fields_before_url.append(("金額", _format_amount(reservation["amount"])))
        fields_before_url.append(
            ("予約番号", reservation["reservation_number"] or "なし")
        )

        st.markdown(_render_field_rows(fields_before_url), unsafe_allow_html=True)

        st.markdown(
            '<div class="rescard-label rescard-label-url">予約確認URL</div>',
            unsafe_allow_html=True,
        )

        safe_url = _safe_reservation_url(reservation["reservation_url"])

        if safe_url:
            st.link_button("予約確認ページを開く", safe_url, use_container_width=True)
        else:
            st.markdown(
                '<div class="rescard-value rescard-value-muted">なし</div>',
                unsafe_allow_html=True,
            )

        fields_after_url: list[tuple[str, str]] = [
            ("状態", STATUS_BADGES.get(reservation["status"], reservation["status"])),
            ("メモ", reservation["memo"] or "なし"),
        ]

        st.markdown(_render_field_rows(fields_after_url), unsafe_allow_html=True)


# --------------------------------------------------
# ホーム画面の各項目から出張タブへ「ジャンプ」するための軽量な仕組み。
# st.Page/st.navigationは使わず、session_stateに移動先の出張ID（と
# 任意で予約ID）を記録しておき、出張タブ側のセレクトボックスを
# 該当項目にプリセットする方式で実現する。タブの自動切り替え自体は
# Streamlitの制約上できないため、出張タブ側で案内メッセージを表示する。
# --------------------------------------------------
TRIP_JUMP_TRIP_KEY = "tripflow_jump_trip_id"
TRIP_JUMP_RESERVATION_KEY = "tripflow_jump_reservation_id"
TRIP_JUMP_SOURCE_KEY = "tripflow_jump_source_label"
EDIT_TRIP_SELECT_KEY = "edit_trip_select"


def request_trip_jump(
    trip_id: int, source_label: str, *, reservation_id: int | None = None
) -> None:
    st.session_state[TRIP_JUMP_TRIP_KEY] = trip_id
    st.session_state[TRIP_JUMP_RESERVATION_KEY] = reservation_id
    st.session_state[TRIP_JUMP_SOURCE_KEY] = source_label


def pop_trip_jump() -> tuple[int | None, int | None, str | None]:
    trip_id = st.session_state.pop(TRIP_JUMP_TRIP_KEY, None)
    reservation_id = st.session_state.pop(TRIP_JUMP_RESERVATION_KEY, None)
    source_label = st.session_state.pop(TRIP_JUMP_SOURCE_KEY, None)
    return trip_id, reservation_id, source_label


def render_trip_jump_button(
    label: str,
    trip_id: int,
    source_label: str,
    *,
    key: str,
    reservation_id: int | None = None,
) -> None:
    if st.button(label, key=key, use_container_width=True):
        request_trip_jump(trip_id, source_label, reservation_id=reservation_id)
        st.rerun()


# --------------------------------------------------
# Web v0.4 Phase C: Gmail本文解析結果の「登録候補プレビュー」表示。
# reservation_parser.ReservationCandidateを受け取り、実データに存在する
# 値だけをカード表示する（無い項目は表示しない＝推測で埋めない）。
# ここではDBへの保存は一切行わない（プレビュー表示専用）。
# --------------------------------------------------
def render_registration_candidate_card(candidate: Any) -> None:
    """Gmail本文解析結果を、登録候補プレビューとしてカード形式で表示する。

    種類（電車／ホテル／飛行機／その他）に応じて表示項目を出し分け、値が
    Noneの項目は表示しない。DBへの登録はPhase D前半時点でも行わず、その旨を
    常に案内する。アイコンはSERVICE_ICONS（サービス名ベース）を使い、
    えきねっと・スマートEXのように同じ種類（電車）でもサービスごとに
    見分けられるようにする。
    """
    with st.container(border=True):
        if candidate.reservation_type == "電車":
            icon = SERVICE_ICONS.get(candidate.service, "🚄")
            st.markdown(f"**{icon} {candidate.service}**")

            if candidate.origin and candidate.destination:
                st.markdown(f"{candidate.origin} → {candidate.destination}")
            elif candidate.origin or candidate.destination:
                st.markdown(candidate.origin or candidate.destination)

            if candidate.date:
                st.markdown(_format_date(candidate.date.isoformat()))

            if candidate.train_name:
                st.markdown(candidate.train_name)

            car_seat_parts = [
                part for part in (candidate.car_number, candidate.seat_number) if part
            ]
            if car_seat_parts:
                st.markdown("　".join(car_seat_parts))

            if candidate.start_time or candidate.end_time:
                st.caption(f"{candidate.start_time or '？'} → {candidate.end_time or '？'}")

            if candidate.amount is not None:
                st.markdown(f"料金：{_format_amount(candidate.amount)}")

        elif candidate.reservation_type == "ホテル":
            icon = SERVICE_ICONS.get(candidate.service, "🏨")
            st.markdown(f"**{icon} {candidate.service}**")

            if candidate.hotel_name:
                st.markdown(candidate.hotel_name)

            if candidate.checkin_date:
                st.markdown(f"チェックイン：{_format_date(candidate.checkin_date.isoformat())}")

            if candidate.checkout_date:
                st.markdown(
                    f"チェックアウト：{_format_date(candidate.checkout_date.isoformat())}"
                )

            if candidate.amount is not None:
                st.markdown(f"料金：{_format_amount(candidate.amount)}")

        elif candidate.reservation_type == "飛行機":
            icon = SERVICE_ICONS.get(candidate.service, "✈️")
            st.markdown(f"**{icon} {candidate.service}**")

            if candidate.origin and candidate.destination:
                st.markdown(f"{candidate.origin} → {candidate.destination}")
            elif candidate.origin or candidate.destination:
                st.markdown(candidate.origin or candidate.destination)

            if candidate.date:
                st.markdown(_format_date(candidate.date.isoformat()))

            if candidate.flight_number:
                st.markdown(candidate.flight_number)

            if candidate.seat_number:
                st.markdown(candidate.seat_number)

            if candidate.start_time or candidate.end_time:
                st.caption(f"{candidate.start_time or '？'} → {candidate.end_time or '？'}")

        else:
            icon = SERVICE_ICONS.get(candidate.service, "📌")
            st.markdown(f"**{icon} {candidate.service}**")
            if candidate.title:
                st.markdown(candidate.title)

        if candidate.reservation_reference:
            st.caption(f"予約/申込番号：{candidate.reservation_reference}")

        st.caption(f"解析結果の確度：{candidate.confidence}")

        if candidate.missing_fields:
            st.caption("取得できなかった項目：" + "、".join(candidate.missing_fields))

        st.info(
            "これは登録候補のプレビューです。TripFlowへの自動登録は行っておらず、"
            "登録機能は今後のバージョンで実装予定です。"
        )


def clear_stale_selection(key: str, valid_ids: Iterable[int]) -> None:
    """session_state[key]が、現在有効なID一覧に含まれていなければクリアする。

    出張・予約の選択用セレクトボックス（st.selectbox）は、session_state
    に保持された値をもとに表示を組み立てる際、format_funcへその値を渡す。
    削除やユーザー切り替え等により、その値がもう存在しない（または
    ログインユーザーの所有物ではない）IDになっていると、format_func内の
    辞書参照でKeyErrorになりアプリがクラッシュする。ここで事前にクリア
    しておくことで、セレクトボックスは安全に先頭の選択肢（未選択相当）
    へフォールバックする。「他人のデータが存在する」ことを示すメッセージ
    は一切出さない。
    """
    if key in st.session_state and st.session_state[key] not in valid_ids:
        del st.session_state[key]


# --------------------------------------------------
# DB読み取り用の共通エラーハンドリング。
# 書き込み系はapp.py側で個別にtry/except sqlite3.Errorしているが、
# 読み取り系（ページ表示のための一括取得）は未対応だったため、
# ここで共通化する。失敗時はエラーメッセージを表示し、安全なデフォルト値
# （空リスト等）を返すことで、ページ全体がクラッシュしないようにする。
# --------------------------------------------------
def safe_fetch(
    fetch_fn: Callable[..., Any],
    *args: Any,
    default: Any,
    error_message: str,
    **kwargs: Any,
) -> Any:
    try:
        return fetch_fn(*args, **kwargs)
    except sqlite3.Error:
        st.error(error_message)
        return default
