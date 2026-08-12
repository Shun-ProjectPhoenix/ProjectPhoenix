from __future__ import annotations

import calendar
import html
import sqlite3
from datetime import date, timedelta
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st

from database import (
    delete_reservation,
    delete_trip,
    fetch_reservation,
    fetch_reservations_by_trip,
    fetch_reservations_in_range,
    fetch_trip,
    fetch_trips,
    fetch_trips_in_range,
    fetch_upcoming_trips,
    get_reservation_status,
    init_db,
    insert_reservation,
    insert_trip,
    update_reservation,
    update_trip,
)

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
SERVICE_ICONS = {
    "えきねっと": "🚄",
    "スマートEX": "🚄",
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


def _shift_month(target_date: date, delta: int) -> date:
    month_index = target_date.month - 1 + delta
    year = target_date.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _month_bounds(target_date: date) -> tuple[date, date]:
    month_start = date(target_date.year, target_date.month, 1)
    _, last_day_num = calendar.monthrange(target_date.year, target_date.month)
    month_end = date(target_date.year, target_date.month, last_day_num)
    return month_start, month_end


# --------------------------------------------------
# ページの基本設定
# --------------------------------------------------
st.set_page_config(
    page_title="TripFlow",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------
# データベース初期化
# --------------------------------------------------
init_db()


# --------------------------------------------------
# デザイン
# --------------------------------------------------
st.markdown(
    """
    <style>
    .block-container {
        max-width: 1100px;
        padding-top: 1.2rem;
        padding-bottom: 5rem;
    }

    .tripflow-header {
        padding: 22px;
        margin-bottom: 20px;
        border-radius: 20px;
        color: white;
        background: linear-gradient(135deg, #082653, #1857a7);
        box-shadow: 0 8px 24px rgba(8, 38, 83, 0.16);
    }

    .tripflow-header h1 {
        margin: 0;
        font-size: 2rem;
    }

    .tripflow-header p {
        margin: 8px 0 0;
        opacity: 0.9;
    }

    [data-testid="stMetric"] {
        padding: 15px;
        border: 1px solid #e4e8ef;
        border-radius: 16px;
        background-color: white;
        box-shadow: 0 4px 16px rgba(15, 35, 70, 0.05);
    }
    [data-testid="stMetric"] label,
    [data-testid="stMetric"] [data-testid="stMetricValue"],
    [data-testid="stMetric"] [data-testid="stMetricDelta"] {
    color: #111827 !important;
    }

    div.stButton > button {
        width: 100%;
        border-radius: 12px;
    }

    .cal-wrapper {
        overflow-x: auto;
        margin-top: 10px;
        padding-bottom: 6px;
    }

    .cal-grid {
        display: grid;
        grid-template-columns: repeat(7, minmax(88px, 1fr));
        gap: 6px;
        min-width: 630px;
    }

    .cal-weekday {
        text-align: center;
        font-weight: 600;
        font-size: 0.8rem;
        color: #4b5563;
        padding: 4px 0;
    }

    .cal-cell {
        background-color: white;
        border: 1px solid #e4e8ef;
        border-radius: 10px;
        min-height: 78px;
        padding: 6px;
    }

    .cal-cell-other-month {
        opacity: 0.4;
    }

    .cal-cell-today {
        border: 2px solid #1857a7;
    }

    .cal-daynum {
        font-size: 0.78rem;
        font-weight: 600;
        color: #111827;
        margin-bottom: 4px;
    }

    /* カレンダーのバー共通スタイル。種別・サービスごとに
       下の色違いクラスを組み合わせて使う。 */
    .cal-bar {
        font-size: 0.7rem;
        padding: 2px 6px;
        border-radius: 6px;
        color: white;
        margin-bottom: 3px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* 出張期間：黒系 */
    .cal-bar-trip {
        background-color: #1f2937;
    }

    /* 予約サービスごとの色分け。サービスが増えたら
       ここに1行追加するだけで対応できる。 */
    .cal-bar-ekinet {
        background-color: #2f9e44;
    }

    .cal-bar-smartex {
        background-color: #22b8cf;
    }

    .cal-bar-skymark {
        background-color: #f2c744;
        color: #1f2937;
    }

    .cal-bar-agoda {
        background-color: #e03131;
    }

    .cal-bar-other {
        background-color: #868e96;
    }

    /* キャンセル済みの予約：取り消し線＋薄く表示 */
    .cal-bar-cancelled {
        text-decoration: line-through;
        opacity: 0.55;
    }

    /* まだ未予約の予約：破線枠で「未確定」を示す */
    .cal-bar-unconfirmed {
        opacity: 0.8;
        border: 1px dashed rgba(255, 255, 255, 0.85);
    }

    @media (max-width: 700px) {
        .block-container {
            padding-left: 0.8rem;
            padding-right: 0.8rem;
        }

        .tripflow-header h1 {
            font-size: 1.55rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------
# 初期データ
# --------------------------------------------------
today = date.today()


# --------------------------------------------------
# ヘッダー
# --------------------------------------------------
st.markdown(
    """
    <div class="tripflow-header">
        <h1>✈️ TripFlow</h1>
        <p>出張の予約・費用・予定を、ひとつの画面で。</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------
# メニュー
# --------------------------------------------------
home_tab, trips_tab, calendar_tab = st.tabs(
    ["🏠 ホーム", "🧳 出張", "📅 カレンダー"]
)


# --------------------------------------------------
# 出張画面
# タブ切り替えは画面の再実行を伴わないため、ホーム画面より
# 先に処理し、登録結果をホーム画面の集計にも反映させます。
# --------------------------------------------------
with trips_tab:
    st.subheader("出張を登録")

    with st.form("trip_form"):
        trip_name = st.text_input(
            "出張名",
            placeholder="例：福岡出張",
        )

        destination = st.text_input(
            "行き先",
            placeholder="例：福岡県福岡市",
        )

        date_col1, date_col2 = st.columns(2)

        with date_col1:
            start_date = st.date_input(
                "開始日",
                value=today,
            )

        with date_col2:
            end_date = st.date_input(
                "終了日",
                value=today,
            )

        category = st.selectbox(
            "分類",
            CATEGORY_OPTIONS,
        )

        memo = st.text_area(
            "メモ",
            placeholder="出張目的や予定など",
        )

        submitted = st.form_submit_button(
            "出張を登録",
            use_container_width=True,
        )

    if submitted:
        if not trip_name.strip():
            st.error("出張名を入力してください。")

        elif end_date < start_date:
            st.error("終了日は開始日以降にしてください。")

        else:
            try:
                insert_trip(
                    name=trip_name.strip(),
                    start_date=start_date,
                    end_date=end_date,
                    destination=destination.strip(),
                    category=category,
                    memo=memo.strip(),
                )

            except sqlite3.Error:
                st.error("出張の保存に失敗しました。時間をおいて再度お試しください。")

            else:
                st.success(f"「{trip_name}」を保存しました。")

    all_trips = fetch_trips()

    st.divider()
    st.subheader("出張の編集・削除")

    if not all_trips:
        st.caption("編集できる出張がまだありません。")

    else:
        trip_options = {
            trip["id"]: (
                f"{trip['name']}"
                f"（{_format_date(trip['start_date'])}"
                f"〜{_format_date(trip['end_date'])}）"
            )
            for trip in all_trips
        }

        selected_id = st.selectbox(
            "編集する出張を選択",
            options=list(trip_options.keys()),
            format_func=lambda trip_id: trip_options[trip_id],
        )

        selected_trip = fetch_trip(selected_id)

        with st.form(f"edit_trip_form_{selected_id}"):
            edit_name = st.text_input(
                "出張名",
                value=selected_trip["name"],
                key=f"edit_name_{selected_id}",
            )

            edit_destination = st.text_input(
                "行き先",
                value=selected_trip["destination"] or "",
                key=f"edit_destination_{selected_id}",
            )

            edit_date_col1, edit_date_col2 = st.columns(2)

            with edit_date_col1:
                edit_start_date = st.date_input(
                    "開始日",
                    value=date.fromisoformat(selected_trip["start_date"]),
                    key=f"edit_start_date_{selected_id}",
                )

            with edit_date_col2:
                edit_end_date = st.date_input(
                    "終了日",
                    value=date.fromisoformat(selected_trip["end_date"]),
                    key=f"edit_end_date_{selected_id}",
                )

            category_index = (
                CATEGORY_OPTIONS.index(selected_trip["category"])
                if selected_trip["category"] in CATEGORY_OPTIONS
                else 0
            )

            edit_category = st.selectbox(
                "分類",
                CATEGORY_OPTIONS,
                index=category_index,
                key=f"edit_category_{selected_id}",
            )

            edit_memo = st.text_area(
                "メモ",
                value=selected_trip["memo"] or "",
                key=f"edit_memo_{selected_id}",
            )

            edit_submitted = st.form_submit_button(
                "この内容で更新",
                use_container_width=True,
            )

        if edit_submitted:
            if not edit_name.strip():
                st.error("出張名を入力してください。")

            elif edit_end_date < edit_start_date:
                st.error("終了日は開始日以降にしてください。")

            else:
                try:
                    update_trip(
                        trip_id=selected_id,
                        name=edit_name.strip(),
                        start_date=edit_start_date,
                        end_date=edit_end_date,
                        destination=edit_destination.strip(),
                        category=edit_category,
                        memo=edit_memo.strip(),
                    )

                except sqlite3.Error:
                    st.error("出張の更新に失敗しました。時間をおいて再度お試しください。")

                else:
                    st.success(f"「{edit_name}」を更新しました。")
                    all_trips = fetch_trips()

        confirm_key = f"confirm_delete_{selected_id}"

        if confirm_key not in st.session_state:
            st.session_state[confirm_key] = False

        if st.button("🗑️ この出張を削除", key=f"delete_button_{selected_id}"):
            st.session_state[confirm_key] = True

        if st.session_state[confirm_key]:
            st.warning(
                f"「{selected_trip['name']}」を削除します。"
                "この操作は取り消せません。よろしいですか？"
            )

            confirm_col1, confirm_col2 = st.columns(2)

            with confirm_col1:
                if st.button(
                    "はい、削除する",
                    key=f"confirm_delete_yes_{selected_id}",
                    use_container_width=True,
                ):
                    try:
                        delete_trip(selected_id)

                    except sqlite3.Error:
                        st.error("出張の削除に失敗しました。時間をおいて再度お試しください。")

                    else:
                        st.session_state[confirm_key] = False
                        st.success(f"「{selected_trip['name']}」を削除しました。")
                        all_trips = fetch_trips()

            with confirm_col2:
                if st.button(
                    "キャンセル",
                    key=f"confirm_delete_no_{selected_id}",
                    use_container_width=True,
                ):
                    st.session_state[confirm_key] = False

        st.divider()
        st.subheader(f"予約管理：{selected_trip['name']}")

        # フォーム内では選んだ項目に応じた即時の出し分けができないため、
        # 「種類」だけはフォームの外に置き、ホテル選択時にチェックイン/
        # チェックアウト欄が動的に表示されるようにする。
        reservation_type = st.selectbox(
            "種類",
            RESERVATION_TYPE_OPTIONS,
            key=f"res_type_select_{selected_id}",
        )

        with st.form(f"reservation_form_{selected_id}", clear_on_submit=True):
            reservation_service = st.selectbox(
                "サービス",
                RESERVATION_SERVICE_OPTIONS,
                key=f"res_service_{selected_id}",
            )

            reservation_title = st.text_input(
                "予約名",
                placeholder="例：のぞみ123号",
                key=f"res_title_{selected_id}",
            )

            if reservation_type == "ホテル":
                res_checkin_col, res_checkout_col = st.columns(2)

                with res_checkin_col:
                    reservation_check_in = st.date_input(
                        "チェックイン日",
                        value=date.fromisoformat(selected_trip["start_date"]),
                        key=f"res_checkin_{selected_id}",
                    )

                with res_checkout_col:
                    reservation_check_out = st.date_input(
                        "チェックアウト日",
                        value=date.fromisoformat(selected_trip["start_date"])
                        + timedelta(days=1),
                        key=f"res_checkout_{selected_id}",
                    )

                reservation_amount = st.number_input(
                    "金額（円）",
                    min_value=0,
                    step=100,
                    value=0,
                    key=f"res_amount_{selected_id}",
                )

            else:
                reservation_date_col, reservation_amount_col = st.columns(2)

                with reservation_date_col:
                    reservation_date = st.date_input(
                        "利用日",
                        value=date.fromisoformat(selected_trip["start_date"]),
                        key=f"res_date_{selected_id}",
                    )

                with reservation_amount_col:
                    reservation_amount = st.number_input(
                        "金額（円）",
                        min_value=0,
                        step=100,
                        value=0,
                        key=f"res_amount_{selected_id}",
                    )

            reservation_number = st.text_input(
                "予約番号",
                placeholder="任意",
                key=f"res_number_{selected_id}",
            )

            reservation_url = st.text_input(
                "予約確認URL",
                placeholder="任意（https://...）",
                key=f"res_url_{selected_id}",
            )

            reservation_status = st.selectbox(
                "状態",
                RESERVATION_STATUS_OPTIONS,
                key=f"res_status_{selected_id}",
            )

            reservation_memo = st.text_area(
                "メモ",
                placeholder="任意",
                key=f"res_memo_{selected_id}",
            )

            reservation_submitted = st.form_submit_button(
                "予約を追加",
                use_container_width=True,
            )

        if reservation_submitted:
            if not reservation_title.strip():
                st.error("予約名を入力してください。")

            elif (
                reservation_type == "ホテル"
                and reservation_check_out <= reservation_check_in
            ):
                st.error("チェックアウト日はチェックイン日より後にしてください。")

            else:
                try:
                    if reservation_type == "ホテル":
                        insert_reservation(
                            trip_id=selected_id,
                            reservation_type=reservation_type,
                            reservation_service=reservation_service,
                            title=reservation_title.strip(),
                            reservation_date=reservation_check_in,
                            amount=int(reservation_amount),
                            reservation_number=reservation_number.strip(),
                            reservation_url=reservation_url.strip(),
                            status=reservation_status,
                            memo=reservation_memo.strip(),
                            check_in_date=reservation_check_in,
                            check_out_date=reservation_check_out,
                        )

                    else:
                        insert_reservation(
                            trip_id=selected_id,
                            reservation_type=reservation_type,
                            reservation_service=reservation_service,
                            title=reservation_title.strip(),
                            reservation_date=reservation_date,
                            amount=int(reservation_amount),
                            reservation_number=reservation_number.strip(),
                            reservation_url=reservation_url.strip(),
                            status=reservation_status,
                            memo=reservation_memo.strip(),
                        )

                except sqlite3.Error:
                    st.error("予約の保存に失敗しました。時間をおいて再度お試しください。")

                else:
                    st.success(f"「{reservation_title}」を追加しました。")

        reservations = fetch_reservations_by_trip(selected_id)

        st.markdown("#### 予約の編集・削除")

        if not reservations:
            st.caption("編集できる予約がまだありません。")

        else:
            reservation_options = {
                reservation["id"]: (
                    f"{reservation['reservation_type']}｜{reservation['reservation_service']}｜"
                    f"{_reservation_period_display(reservation)}｜"
                    f"{_format_amount(reservation['amount'])}"
                )
                for reservation in reservations
            }

            selected_reservation_id = st.selectbox(
                "編集する予約を選択",
                options=list(reservation_options.keys()),
                format_func=lambda reservation_id: reservation_options[reservation_id],
                key=f"select_reservation_{selected_id}",
            )

            selected_reservation = fetch_reservation(selected_reservation_id)

            # 「種類」はフォームの外に置き、ホテルを選んだ瞬間に
            # チェックイン/チェックアウト欄へ切り替わるようにする。
            res_type_index = (
                RESERVATION_TYPE_OPTIONS.index(selected_reservation["reservation_type"])
                if selected_reservation["reservation_type"] in RESERVATION_TYPE_OPTIONS
                else 0
            )
            edit_reservation_type = st.selectbox(
                "種類",
                RESERVATION_TYPE_OPTIONS,
                index=res_type_index,
                key=f"edit_res_type_select_{selected_reservation_id}",
            )

            with st.form(f"edit_reservation_form_{selected_reservation_id}"):
                res_service_index = (
                    RESERVATION_SERVICE_OPTIONS.index(
                        selected_reservation["reservation_service"]
                    )
                    if selected_reservation["reservation_service"]
                    in RESERVATION_SERVICE_OPTIONS
                    else 0
                )
                edit_reservation_service = st.selectbox(
                    "サービス",
                    RESERVATION_SERVICE_OPTIONS,
                    index=res_service_index,
                    key=f"edit_res_service_{selected_reservation_id}",
                )

                edit_reservation_title = st.text_input(
                    "予約名",
                    value=selected_reservation["title"],
                    key=f"edit_res_title_{selected_reservation_id}",
                )

                if edit_reservation_type == "ホテル":
                    default_check_in = date.fromisoformat(
                        selected_reservation["check_in_date"]
                        or selected_reservation["reservation_date"]
                    )
                    default_check_out = (
                        date.fromisoformat(selected_reservation["check_out_date"])
                        if selected_reservation["check_out_date"]
                        else default_check_in + timedelta(days=1)
                    )

                    edit_checkin_col, edit_checkout_col = st.columns(2)

                    with edit_checkin_col:
                        edit_reservation_check_in = st.date_input(
                            "チェックイン日",
                            value=default_check_in,
                            key=f"edit_res_checkin_{selected_reservation_id}",
                        )

                    with edit_checkout_col:
                        edit_reservation_check_out = st.date_input(
                            "チェックアウト日",
                            value=default_check_out,
                            key=f"edit_res_checkout_{selected_reservation_id}",
                        )

                    edit_reservation_amount = st.number_input(
                        "金額（円）",
                        min_value=0,
                        step=100,
                        value=int(selected_reservation["amount"]),
                        key=f"edit_res_amount_{selected_reservation_id}",
                    )

                else:
                    edit_res_date_col, edit_res_amount_col = st.columns(2)

                    with edit_res_date_col:
                        edit_reservation_date = st.date_input(
                            "利用日",
                            value=date.fromisoformat(
                                selected_reservation["reservation_date"]
                            ),
                            key=f"edit_res_date_{selected_reservation_id}",
                        )

                    with edit_res_amount_col:
                        edit_reservation_amount = st.number_input(
                            "金額（円）",
                            min_value=0,
                            step=100,
                            value=int(selected_reservation["amount"]),
                            key=f"edit_res_amount_{selected_reservation_id}",
                        )

                edit_reservation_number = st.text_input(
                    "予約番号",
                    value=selected_reservation["reservation_number"] or "",
                    key=f"edit_res_number_{selected_reservation_id}",
                )

                edit_reservation_url = st.text_input(
                    "予約確認URL",
                    value=selected_reservation["reservation_url"] or "",
                    key=f"edit_res_url_{selected_reservation_id}",
                )

                res_status_index = (
                    RESERVATION_STATUS_OPTIONS.index(selected_reservation["status"])
                    if selected_reservation["status"] in RESERVATION_STATUS_OPTIONS
                    else 0
                )
                edit_reservation_status = st.selectbox(
                    "状態",
                    RESERVATION_STATUS_OPTIONS,
                    index=res_status_index,
                    key=f"edit_res_status_{selected_reservation_id}",
                )

                edit_reservation_memo = st.text_area(
                    "メモ",
                    value=selected_reservation["memo"] or "",
                    key=f"edit_res_memo_{selected_reservation_id}",
                )

                edit_reservation_submitted = st.form_submit_button(
                    "この内容で更新",
                    use_container_width=True,
                )

            if edit_reservation_submitted:
                if not edit_reservation_title.strip():
                    st.error("予約名を入力してください。")

                elif (
                    edit_reservation_type == "ホテル"
                    and edit_reservation_check_out <= edit_reservation_check_in
                ):
                    st.error("チェックアウト日はチェックイン日より後にしてください。")

                else:
                    try:
                        if edit_reservation_type == "ホテル":
                            update_reservation(
                                reservation_id=selected_reservation_id,
                                reservation_type=edit_reservation_type,
                                reservation_service=edit_reservation_service,
                                title=edit_reservation_title.strip(),
                                reservation_date=edit_reservation_check_in,
                                amount=int(edit_reservation_amount),
                                reservation_number=edit_reservation_number.strip(),
                                reservation_url=edit_reservation_url.strip(),
                                status=edit_reservation_status,
                                memo=edit_reservation_memo.strip(),
                                check_in_date=edit_reservation_check_in,
                                check_out_date=edit_reservation_check_out,
                            )

                        else:
                            update_reservation(
                                reservation_id=selected_reservation_id,
                                reservation_type=edit_reservation_type,
                                reservation_service=edit_reservation_service,
                                title=edit_reservation_title.strip(),
                                reservation_date=edit_reservation_date,
                                amount=int(edit_reservation_amount),
                                reservation_number=edit_reservation_number.strip(),
                                reservation_url=edit_reservation_url.strip(),
                                status=edit_reservation_status,
                                memo=edit_reservation_memo.strip(),
                                check_in_date=None,
                                check_out_date=None,
                            )

                    except sqlite3.Error:
                        st.error("予約の更新に失敗しました。時間をおいて再度お試しください。")

                    else:
                        st.toast(f"「{edit_reservation_title}」を更新しました。", icon="✅")
                        st.rerun()

            reservation_confirm_key = f"confirm_delete_reservation_{selected_reservation_id}"

            if reservation_confirm_key not in st.session_state:
                st.session_state[reservation_confirm_key] = False

            if st.button(
                "🗑️ この予約を削除",
                key=f"delete_reservation_button_{selected_reservation_id}",
            ):
                st.session_state[reservation_confirm_key] = True

            if st.session_state[reservation_confirm_key]:
                st.warning(
                    "以下の予約を削除します。よろしいですか？"
                    "この操作は取り消せません。\n\n"
                    f"- 種類：{selected_reservation['reservation_type']}\n"
                    f"- サービス：{selected_reservation['reservation_service']}\n"
                    f"- 予約名：{selected_reservation['title']}\n"
                    f"- 日付／宿泊期間：{_reservation_period_display(selected_reservation)}\n"
                    f"- 金額：{_format_amount(selected_reservation['amount'])}"
                )

                res_confirm_col1, res_confirm_col2 = st.columns(2)

                with res_confirm_col1:
                    if st.button(
                        "はい、削除する",
                        key=f"confirm_delete_reservation_yes_{selected_reservation_id}",
                        use_container_width=True,
                    ):
                        try:
                            delete_reservation(selected_reservation_id)

                        except sqlite3.Error:
                            st.error(
                                "予約の削除に失敗しました。時間をおいて再度お試しください。"
                            )

                        else:
                            st.session_state[reservation_confirm_key] = False
                            st.toast(
                                f"「{selected_reservation['title']}」を削除しました。",
                                icon="🗑️",
                            )
                            st.rerun()

                with res_confirm_col2:
                    if st.button(
                        "キャンセル",
                        key=f"confirm_delete_reservation_no_{selected_reservation_id}",
                        use_container_width=True,
                    ):
                        st.session_state[reservation_confirm_key] = False

        if reservations:
            reservations_df = pd.DataFrame(
                [
                    {
                        "種類": reservation["reservation_type"],
                        "サービス": reservation["reservation_service"],
                        "予約名": reservation["title"],
                        "利用日／宿泊期間": _reservation_period_display(reservation),
                        "金額": _format_amount(reservation["amount"]),
                        "状態": reservation["status"],
                        "予約番号": reservation["reservation_number"] or "",
                        "メモ": reservation["memo"] or "",
                        "予約確認URL": _safe_reservation_url(
                            reservation["reservation_url"]
                        )
                        or "",
                    }
                    for reservation in reservations
                ]
            )

            st.dataframe(
                reservations_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "予約確認URL": st.column_config.LinkColumn(
                        "予約確認URL",
                        display_text="開く",
                    ),
                },
            )

        else:
            st.caption("この出張にはまだ予約が登録されていません。")

    st.divider()
    st.subheader("登録済みの出張")

    if all_trips:
        trips_df = pd.DataFrame(
            [
                {
                    "出張名": trip["name"],
                    "行き先": trip["destination"],
                    "開始日": _format_date(trip["start_date"]),
                    "終了日": _format_date(trip["end_date"]),
                    "分類": trip["category"],
                    "予約状況": (
                        "✅ 予約完了"
                        if get_reservation_status(trip["id"])["complete"]
                        else "⚠️ 確認が必要"
                    ),
                }
                for trip in all_trips
            ]
        )
        st.dataframe(trips_df, hide_index=True, use_container_width=True)

    else:
        st.caption("まだ登録済みの出張がありません。上のフォームから登録しましょう。")


# --------------------------------------------------
# ホーム画面
# --------------------------------------------------
with home_tab:
    upcoming_trips = fetch_upcoming_trips(today, limit=3)

    this_month_start, this_month_end = _month_bounds(today)
    this_month_trips = fetch_trips_in_range(this_month_start, this_month_end)
    this_month_reservations = fetch_reservations_in_range(
        this_month_start, this_month_end
    )

    monthly_cost = sum(
        reservation["amount"]
        for reservation in this_month_reservations
        if reservation["status"] == "予約済み"
    )
    trip_count = len(this_month_trips)
    reservation_count = len(this_month_reservations)
    attention_count = sum(
        1
        for trip in this_month_trips
        if not get_reservation_status(trip["id"])["complete"]
    )

    st.subheader(f"{today.year}年{today.month}月")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("今月の費用", f"¥{monthly_cost:,}")
    col2.metric("出張予定", f"{trip_count}件")
    col3.metric("予約", f"{reservation_count}件")
    col4.metric("確認が必要", f"{attention_count}件")

    incomplete_month_trips = [
        trip
        for trip in this_month_trips
        if not get_reservation_status(trip["id"])["complete"]
    ]

    with st.expander(f"🧳 出張予定：{trip_count}件の内訳"):
        if this_month_trips:
            for trip in this_month_trips:
                st.markdown(
                    f"- **{trip['name']}**　"
                    f"{_format_date(trip['start_date'])} 〜 {_format_date(trip['end_date'])}"
                    f"　／　{trip['destination']}"
                )
        else:
            st.caption("今月の出張はありません。")

    with st.expander(f"🎫 予約：{reservation_count}件の内訳"):
        if this_month_reservations:
            for reservation in this_month_reservations:
                icon = SERVICE_ICONS.get(reservation["reservation_service"], "📌")
                status_suffix = _reservation_status_suffix(reservation["status"])
                st.markdown(
                    f"- {icon} {reservation['reservation_type']}・"
                    f"{reservation['reservation_service']}／{reservation['title']}／"
                    f"{_reservation_period_display(reservation)}／"
                    f"{_format_amount(reservation['amount'])}{status_suffix}"
                )
        else:
            st.caption("今月の予約はありません。")

    with st.expander(f"⚠️ 確認が必要：{attention_count}件の内訳"):
        if incomplete_month_trips:
            for trip in incomplete_month_trips:
                status = get_reservation_status(trip["id"])
                st.markdown(
                    f"**{trip['name']}**　"
                    f"{_format_date(trip['start_date'])} 〜 {_format_date(trip['end_date'])}"
                )
                st.markdown(
                    _status_line("往路", status["outbound"])
                    + "　"
                    + _status_line("ホテル", status["hotel"])
                    + "　"
                    + _status_line("復路", status["return"])
                )
        else:
            st.caption("今月、確認が必要な出張はありません。")

    st.markdown("### 直近の出張")

    if upcoming_trips:
        for trip in upcoming_trips:
            status = get_reservation_status(trip["id"])
            trip_reservations = fetch_reservations_by_trip(trip["id"])

            with st.expander(
                f"{trip['name']}　"
                f"{_format_date(trip['start_date'])} 〜 {_format_date(trip['end_date'])}"
            ):
                st.markdown(f"行き先：{trip['destination']}")
                st.markdown(
                    _status_line("往路", status["outbound"])
                    + "　"
                    + _status_line("ホテル", status["hotel"])
                    + "　"
                    + _status_line("復路", status["return"])
                )

                st.markdown("##### 予約一覧")

                if trip_reservations:
                    for reservation in trip_reservations:
                        icon = SERVICE_ICONS.get(
                            reservation["reservation_service"], "📌"
                        )
                        status_suffix = _reservation_status_suffix(
                            reservation["status"]
                        )
                        st.markdown(
                            f"- {icon} {reservation['reservation_type']}・"
                            f"{reservation['reservation_service']}／"
                            f"{reservation['title']}／"
                            f"{_reservation_period_display(reservation)}／"
                            f"{_format_amount(reservation['amount'])}{status_suffix}"
                        )
                else:
                    st.caption("この出張にはまだ予約が登録されていません。")

    else:
        st.info(
            "まだ出張予定がありません。"
            "「出張」タブから最初の出張を登録しましょう。"
        )

    st.markdown("### TripFlowで確認できること")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.success("✅ 往路の予約")

    with col2:
        st.success("✅ ホテルの予約")

    with col3:
        st.warning("⚠️ 復路の予約")


# --------------------------------------------------
# カレンダー画面
# --------------------------------------------------
with calendar_tab:
    st.subheader("出張カレンダー")

    if "calendar_month" not in st.session_state:
        st.session_state["calendar_month"] = date(today.year, today.month, 1)

    display_month = st.session_state["calendar_month"]

    nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])

    with nav_col1:
        if st.button("◀ 前月", use_container_width=True):
            st.session_state["calendar_month"] = _shift_month(display_month, -1)
            display_month = st.session_state["calendar_month"]

    with nav_col3:
        if st.button("翌月 ▶", use_container_width=True):
            st.session_state["calendar_month"] = _shift_month(display_month, 1)
            display_month = st.session_state["calendar_month"]

    with nav_col2:
        st.markdown(
            f"<h3 style='text-align:center;margin:6px 0;'>"
            f"{display_month.year}年{display_month.month}月</h3>",
            unsafe_allow_html=True,
        )

    month_calendar = calendar.Calendar(firstweekday=6)
    month_dates = list(
        month_calendar.itermonthdates(display_month.year, display_month.month)
    )

    range_start = month_dates[0]
    range_end = month_dates[-1]

    _, last_day_num = calendar.monthrange(display_month.year, display_month.month)
    last_day_of_month = date(display_month.year, display_month.month, last_day_num)

    range_trips = fetch_trips_in_range(range_start, range_end)
    range_reservations = fetch_reservations_in_range(range_start, range_end)

    weekday_labels = ["日", "月", "火", "水", "木", "金", "土"]
    header_html = "".join(
        f'<div class="cal-weekday">{label}</div>' for label in weekday_labels
    )

    cell_html_parts = []

    for day in month_dates:
        day_trips = [
            trip
            for trip in range_trips
            if date.fromisoformat(trip["start_date"])
            <= day
            <= date.fromisoformat(trip["end_date"])
        ]

        day_reservations = [
            reservation
            for reservation in range_reservations
            if _reservation_matches_day(reservation, day)
        ]

        cell_classes = ["cal-cell"]

        if day.month != display_month.month:
            cell_classes.append("cal-cell-other-month")

        if day == today:
            cell_classes.append("cal-cell-today")

        bar_html_parts = []

        for trip in day_trips:
            title_text = (
                f"{trip['name']}"
                f"（{_format_date(trip['start_date'])}〜{_format_date(trip['end_date'])}）"
            )
            bar_html_parts.append(
                f'<div class="cal-bar cal-bar-trip" title="{html.escape(title_text)}">'
                f'{html.escape(trip["name"])}</div>'
            )

        for reservation in day_reservations:
            service = reservation["reservation_service"]
            service_class = SERVICE_CSS_CLASSES.get(service, "cal-bar-other")

            bar_classes = ["cal-bar", service_class]

            if reservation["status"] == "キャンセル":
                bar_classes.append("cal-bar-cancelled")
            elif reservation["status"] == "未予約":
                bar_classes.append("cal-bar-unconfirmed")

            bar_label = _reservation_bar_label(reservation, day)
            title_text = (
                f"{reservation['title']}　{bar_label}　"
                f"{reservation['status']}"
            )

            bar_html_parts.append(
                f'<div class="{" ".join(bar_classes)}" title="{html.escape(title_text)}">'
                f"{html.escape(bar_label)}</div>"
            )

        cell_html_parts.append(
            f'<div class="{" ".join(cell_classes)}">'
            f'<div class="cal-daynum">{day.day}</div>'
            f'{"".join(bar_html_parts)}'
            f"</div>"
        )

    grid_html = (
        '<div class="cal-wrapper"><div class="cal-grid">'
        + header_html
        + "".join(cell_html_parts)
        + "</div></div>"
    )

    st.markdown(grid_html, unsafe_allow_html=True)

    st.markdown("#### 📅 日付を選んで詳細を見る")

    default_selected_day = (
        today if range_start <= today <= range_end else display_month
    )

    selected_day = st.date_input(
        "日付を選択",
        value=default_selected_day,
        min_value=range_start,
        max_value=range_end,
        key=f"calendar_selected_day_{display_month.isoformat()}",
    )

    day_detail_trips = [
        trip
        for trip in range_trips
        if date.fromisoformat(trip["start_date"])
        <= selected_day
        <= date.fromisoformat(trip["end_date"])
    ]
    day_detail_reservations = [
        reservation
        for reservation in range_reservations
        if _reservation_matches_day(reservation, selected_day)
    ]

    st.markdown(
        f"##### {selected_day.year}年{selected_day.month}月{selected_day.day}日の詳細"
    )

    if not day_detail_trips and not day_detail_reservations:
        st.caption("この日に該当する出張・予約はありません。")

    else:
        for trip in day_detail_trips:
            st.markdown(
                f"🧳 **{trip['name']}**　"
                f"{_format_date(trip['start_date'])} 〜 {_format_date(trip['end_date'])}"
                f"　／　{trip['destination']}"
            )

        for reservation in day_detail_reservations:
            bar_label = _reservation_bar_label(reservation, selected_day)

            st.markdown(
                f"{bar_label}／{reservation['title']}／"
                f"{_reservation_period_display(reservation)}／"
                f"{_format_amount(reservation['amount'])}"
            )

            detail_info_col, detail_link_col = st.columns([2, 1])

            with detail_info_col:
                if reservation["reservation_number"]:
                    st.caption(f"予約番号：{reservation['reservation_number']}")

            with detail_link_col:
                safe_url = _safe_reservation_url(reservation["reservation_url"])

                if safe_url:
                    st.link_button(
                        "予約確認ページを開く",
                        safe_url,
                        use_container_width=True,
                    )

    st.divider()

    st.markdown("### この月の出張一覧")

    month_trips = [
        trip
        for trip in range_trips
        if not (
            date.fromisoformat(trip["end_date"]) < display_month
            or date.fromisoformat(trip["start_date"]) > last_day_of_month
        )
    ]

    if month_trips:
        for trip in month_trips:
            st.markdown(
                f"- **{trip['name']}**　"
                f"{_format_date(trip['start_date'])} 〜 {_format_date(trip['end_date'])}"
                f"　／　{trip['destination']}"
            )

    else:
        st.caption("この月に出張はありません。")

    st.markdown("### この月の予約一覧")

    month_reservations = [
        reservation
        for reservation in range_reservations
        if _reservation_overlaps_range(reservation, display_month, last_day_of_month)
    ]

    if month_reservations:
        for reservation in month_reservations:
            service = reservation["reservation_service"]
            icon = SERVICE_ICONS.get(service, "📌")
            status_suffix = _reservation_status_suffix(reservation["status"])

            st.markdown(
                f"- {_reservation_period_display(reservation)}　"
                f"{icon} {reservation['reservation_type']}・{service}　"
                f"{reservation['title']}{status_suffix}"
            )

    else:
        st.caption("この月に予約はありません。")