from __future__ import annotations

import calendar
import html
import sqlite3
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import gmail_service
import reservation_parser
from components import (
    CATEGORY_OPTIONS,
    EDIT_TRIP_SELECT_KEY,
    RESERVATION_SERVICE_OPTIONS,
    RESERVATION_STATUS_OPTIONS,
    RESERVATION_TYPE_OPTIONS,
    SERVICE_CSS_CLASSES,
    SERVICE_ICONS,
    _format_amount,
    _format_date,
    _month_bounds,
    _reservation_bar_label,
    _reservation_matches_day,
    _reservation_overlaps_range,
    _reservation_period_display,
    _safe_reservation_url,
    _shift_month,
    _status_line,
    clear_stale_selection,
    format_reservation_line,
    format_reservation_month_line,
    format_trip_line,
    pop_trip_jump,
    render_registration_candidate_card,
    render_reservation_card,
    render_trip_card,
    render_trip_jump_button,
    safe_fetch,
)
from database import (
    OwnershipError,
    delete_reservation,
    delete_trip,
    fetch_reservation,
    fetch_reservations_by_trip,
    fetch_reservations_in_range,
    fetch_trip,
    fetch_trips,
    fetch_trips_in_range,
    fetch_upcoming_trips,
    get_or_create_user,
    get_reservation_status,
    init_db,
    insert_reservation,
    insert_trip,
    update_reservation,
    update_trip,
)

# 所有者チェックに失敗した（他ユーザーのデータを操作しようとした）場合や、
# 対象が既に削除されている場合に共通で表示するメッセージ。
# 「他人のものだから失敗した」と推測できる情報は出さない。
OWNERSHIP_ERROR_MESSAGE = "対象データが見つからないか、操作する権限がありません。"


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

    /* 予約詳細カードの項目行：「ラベル」を上、「値」を下に積む。
       横並びの「ラベル：値」だと、スマホで値が長いときに詰まったり
       折り返して読みにくくなるため、幅に関わらず常に縦積みにしている。 */
    .rescard-fields {
        display: flex;
        flex-direction: column;
        gap: 10px;
        margin: 10px 0;
    }

    .rescard-field {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    /* ライト／ダークどちらのStreamlitテーマでも読めるよう、
       色は指定せずopacityだけで「ラベル」を薄く見せる
       （文字色そのものはテーマの既定色を継承する）。 */
    .rescard-label {
        font-size: 0.72rem;
        font-weight: 600;
        opacity: 0.65;
    }

    .rescard-label-url {
        margin-top: 10px;
        margin-bottom: 4px;
    }

    .rescard-value {
        font-size: 0.95rem;
        word-break: break-word;
        overflow-wrap: anywhere;
    }

    .rescard-value-muted {
        opacity: 0.55;
    }

    /* スマホ幅（700px以下）向けの調整。
       PC向けレイアウト（wide、横並びカラム等）はそのまま維持し、
       ここでは余白・文字サイズ・カレンダーの詰まり具合のみを調整する。 */
    @media (max-width: 700px) {
        .block-container {
            padding-left: 0.7rem;
            padding-right: 0.7rem;
        }

        .tripflow-header {
            padding: 16px;
        }

        .tripflow-header h1 {
            font-size: 1.4rem;
        }

        .tripflow-header p {
            font-size: 0.82rem;
        }

        [data-testid="stMetric"] {
            padding: 10px;
        }

        div.stButton > button,
        div.stLinkButton > a {
            font-size: 0.85rem;
            padding: 0.5rem 0.6rem;
            min-height: 2.4rem;
        }

        .rescard-label {
            font-size: 0.68rem;
        }

        .rescard-value {
            font-size: 0.9rem;
        }

        /* カレンダーは作り直さず、構造（グリッド／日付選択詳細）は
           そのまま維持する。スマホでは「横スクロールで7列目まで見に行く」
           操作が発生しないよう、固定のmin-widthを解除し、7列を常に
           画面幅いっぱいに収める（minmax(0, 1fr)）。 */
        .cal-grid {
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 3px;
            min-width: 0;
            width: 100%;
        }

        .cal-cell {
            min-height: 48px;
            padding: 3px 2px;
            border-radius: 6px;
            overflow: hidden;
        }

        .cal-daynum {
            font-size: 0.68rem;
            margin-bottom: 1px;
        }

        /* セル幅が非常に狭くなるため、バーはさらに小さく。
           長い出張名・予約名は.cal-bar側の
           white-space:nowrap/overflow:hidden/text-overflow:ellipsis
           （共通スタイルで定義済み）により自動的に「…」で省略される。 */
        .cal-bar {
            font-size: 0.56rem;
            padding: 1px 3px;
            margin-bottom: 1px;
            border-radius: 4px;
        }

        .cal-weekday {
            font-size: 0.66rem;
            padding: 2px 0;
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
# ログインゲート
# 未ログイン状態では、TripFlow本体（出張・予約・カレンダー等の
# データ画面）を一切表示しない。st.user.is_logged_inは
# .streamlit/secrets.tomlに[auth]設定が無い場合AttributeErrorになる
# ため、安全側に倒して「未ログイン」として扱う。
# --------------------------------------------------
def _is_logged_in() -> bool:
    try:
        return bool(st.user.is_logged_in)
    except AttributeError:
        return False


if not _is_logged_in():
    st.markdown(
        """
        <div class="tripflow-header">
            <h1>✈️ TripFlow</h1>
            <p>出張の予約・費用・予定を、ひとつの画面で。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write(
        "出張の予約状況・費用・予定をまとめて確認できるアプリです。"
        "利用を続けるには、Googleアカウントでログインしてください。"
    )

    if st.button("🔐 Googleでログイン", use_container_width=True):
        st.login()

    st.stop()


# --------------------------------------------------
# ログインユーザーの取得・登録
# user_idは必ずGoogleの認証情報（st.user.sub）から特定する。
# 画面からの入力やsession_stateの値だけを信用してuser_idを
# 決めることは絶対に行わない。
# --------------------------------------------------
current_user = get_or_create_user(
    google_sub=st.user.sub,
    email=st.user.email or "",
    display_name=st.user.name,
)
user_id = current_user["id"]
display_name = current_user["display_name"] or current_user["email"] or "ゲスト"


def _clear_tripflow_session_state() -> None:
    """ログアウト時、TripFlow固有の一時状態を破棄する。

    出張・予約の選択ID、ホームからのジャンプ先、削除確認フラグ、
    カレンダーの選択日など、動的なキー名（出張IDや予約IDを含むもの）
    まで含めて確実に消すため、session_state全体をクリアする。
    Streamlit自体の認証情報はsession_stateではなく署名付きCookieで
    管理されているため、ここでは触れず st.logout() に処理を任せる。
    """
    st.session_state.clear()


def _gmail_access_available() -> bool:
    """Gmail API用のaccess tokenを取得できるかどうかだけを判定する。

    Web v0.4 Phase A時点ではGmail APIを実際には呼び出さない。
    token本体は変数にも画面にもログにも一切残さず、真偽値のみを返す。
    secrets.tomlにexpose_tokensが未設定、またはaccess tokenが
    失効している場合はAttributeError/Noneになるため、安全側に倒して
    「利用不可（再ログインが必要）」として扱う。
    """
    try:
        return bool(st.user.tokens.access)
    except AttributeError:
        return False


# --------------------------------------------------
# Web v0.4 Phase B: Gmailから予約メール候補を検索・一覧表示する。
# 本文の本格解析・予約登録・DB保存はまだ行わない（候補の検索・一覧表示まで）。
# --------------------------------------------------
GMAIL_SEARCH_SERVICE_OPTIONS = ["えきねっと", "Agoda", "スマートEX", "スカイマーク", "すべて"]
GMAIL_SEARCH_PERIOD_OPTIONS = [1, 3, 6, 12]
GMAIL_CANDIDATES_SESSION_KEY = "tripflow_gmail_candidates"
GMAIL_SEARCH_ERROR_SESSION_KEY = "tripflow_gmail_search_error"

# Web v0.4 Phase C: 本文解析結果（登録候補）・解析エラーをmessage_idごとに
# 保持する。ここに保存するのは抽出済みの構造化データ（ReservationCandidate）
# とエラーメッセージ文字列のみで、メール本文全文・access tokenは含めない。
# ログアウト時は既存の_clear_tripflow_session_state()（session_state.clear()）
# でまとめて破棄される。
GMAIL_ANALYSIS_RESULTS_SESSION_KEY = "tripflow_gmail_analysis_results"
GMAIL_ANALYSIS_ERROR_SESSION_KEY = "tripflow_gmail_analysis_errors"

_RELEVANCE_BADGES = {
    reservation_parser.RELEVANCE_TARGET: "🟢 予約情報抽出対象",
    reservation_parser.RELEVANCE_SUPPLEMENTARY: "🔵 予約補完メール（座席等の追加情報を含む可能性）",
    reservation_parser.RELEVANCE_EXCLUDED: "⚪ 対象外（案内・レビュー依頼等の可能性）",
    reservation_parser.RELEVANCE_UNKNOWN: "🟡 判定不能（手動で解析を試せます）",
}


def _gmail_selected_services(choice: str) -> list[str]:
    if choice == "すべて":
        return list(gmail_service.SUPPORTED_SERVICES)
    return [choice]


def _render_gmail_search_section() -> None:
    """Gmail検索フォームと候補一覧を描画する。

    access tokenはこの関数のローカル変数（関数呼び出しの引数）としてのみ
    扱い、session_stateやログ・画面には一切出さない。session_stateへ
    保存するのは、検索結果（件名・送信元・受信日時・snippetのみを持つ
    候補オブジェクト）、Phase Cで追加した本文解析結果（抽出済みの構造化
    データ＝ReservationCandidate）、エラーメッセージ文字列だけであり、
    本文全文やaccess tokenは保持しない。本文取得（Gmail API呼び出し）は
    ユーザーが「予約情報を解析」ボタンを押した1件についてのみ行い、
    候補一覧全件に対して自動的には行わない。ログアウト時は既存の
    _clear_tripflow_session_state()（session_state.clear()）で
    まとめて破棄される。
    """
    if not _gmail_access_available():
        st.caption("📧 Gmail連携：再ログインが必要です")
        st.info(
            "Gmailから予約を検索するには、一度ログアウトしてから"
            "再度ログインしてください。"
        )
        return

    st.caption("📧 Gmail連携：利用可能")

    service_choice = st.radio(
        "対象サービス",
        GMAIL_SEARCH_SERVICE_OPTIONS,
        horizontal=True,
        key="gmail_search_service_choice",
    )
    period_months = st.selectbox(
        "検索期間",
        GMAIL_SEARCH_PERIOD_OPTIONS,
        index=1,
        format_func=lambda m: f"直近{m}か月",
        key="gmail_search_period_months",
    )

    if st.button("Gmailから検索", key="gmail_search_button"):
        selected_services = _gmail_selected_services(service_choice)
        with st.spinner("Gmailを検索しています..."):
            try:
                candidates = gmail_service.search_reservation_candidates(
                    st.user.tokens.access,
                    selected_services,
                    months=period_months,
                )
            except gmail_service.GmailAPIError as e:
                st.session_state[GMAIL_SEARCH_ERROR_SESSION_KEY] = e.user_message
                st.session_state.pop(GMAIL_CANDIDATES_SESSION_KEY, None)
            except AttributeError:
                # 検索ボタンを押した瞬間にaccess tokenが失効していた場合。
                st.session_state[GMAIL_SEARCH_ERROR_SESSION_KEY] = (
                    "Gmail連携の認証期限が切れました。"
                    "ログアウト後、再ログインしてください。"
                )
                st.session_state.pop(GMAIL_CANDIDATES_SESSION_KEY, None)
            except Exception:
                st.session_state[GMAIL_SEARCH_ERROR_SESSION_KEY] = (
                    "予期しないエラーによりGmail検索に失敗しました。"
                    "時間をおいて再度お試しください。"
                )
                st.session_state.pop(GMAIL_CANDIDATES_SESSION_KEY, None)
            else:
                st.session_state[GMAIL_CANDIDATES_SESSION_KEY] = candidates
                st.session_state.pop(GMAIL_SEARCH_ERROR_SESSION_KEY, None)

    search_error = st.session_state.get(GMAIL_SEARCH_ERROR_SESSION_KEY)
    if search_error:
        st.error(search_error)

    candidates = st.session_state.get(GMAIL_CANDIDATES_SESSION_KEY)
    if candidates is not None:
        st.write(f"候補：{len(candidates)}件")

        if not candidates:
            st.caption("条件に一致するメールが見つかりませんでした。")
        else:
            analysis_results = st.session_state.setdefault(
                GMAIL_ANALYSIS_RESULTS_SESSION_KEY, {}
            )
            analysis_errors = st.session_state.setdefault(
                GMAIL_ANALYSIS_ERROR_SESSION_KEY, {}
            )

            for candidate in candidates:
                relevance = reservation_parser.classify_candidate(
                    candidate.service, candidate.subject
                )

                with st.container(border=True):
                    st.markdown(f"**{candidate.subject}**")
                    service_icon = SERVICE_ICONS.get(candidate.service, "📌")
                    st.caption(
                        f"{service_icon} {candidate.service}｜{candidate.received_at}"
                    )
                    st.caption(candidate.sender)
                    if candidate.snippet:
                        st.write(candidate.snippet)

                    st.caption(
                        _RELEVANCE_BADGES.get(relevance, relevance)
                    )

                    if reservation_parser.can_analyze(relevance):
                        if st.button(
                            "🔍 予約情報を解析",
                            key=f"gmail_analyze_{candidate.message_id}",
                        ):
                            with st.spinner("メール本文を解析しています..."):
                                try:
                                    body = gmail_service.fetch_message_body(
                                        st.user.tokens.access, candidate.message_id
                                    )
                                except gmail_service.GmailAPIError as e:
                                    analysis_errors[candidate.message_id] = e.user_message
                                    analysis_results.pop(candidate.message_id, None)
                                except AttributeError:
                                    # 解析ボタンを押した瞬間にaccess tokenが失効していた場合。
                                    analysis_errors[candidate.message_id] = (
                                        "Gmail連携の認証期限が切れました。"
                                        "ログアウト後、再ログインしてください。"
                                    )
                                    analysis_results.pop(candidate.message_id, None)
                                except Exception:
                                    analysis_errors[candidate.message_id] = (
                                        "メール本文の取得に失敗しました。"
                                        "時間をおいて再度お試しください。"
                                    )
                                    analysis_results.pop(candidate.message_id, None)
                                else:
                                    try:
                                        result = reservation_parser.analyze_email(
                                            service=candidate.service,
                                            message_id=candidate.message_id,
                                            relevance=relevance,
                                            subject=candidate.subject,
                                            text_plain=body.text_plain,
                                            text_html=body.text_html,
                                            snippet=candidate.snippet,
                                        )
                                    except Exception:
                                        analysis_errors[candidate.message_id] = (
                                            "このメールは想定外の形式のため、"
                                            "自動解析に対応していません。"
                                        )
                                        analysis_results.pop(candidate.message_id, None)
                                    else:
                                        analysis_results[candidate.message_id] = result
                                        analysis_errors.pop(candidate.message_id, None)
                    else:
                        st.caption(
                            "このメールは予約情報の抽出対象外と判定されたため、"
                            "解析ボタンは表示していません。"
                        )

                    if candidate.message_id in analysis_errors:
                        st.error(analysis_errors[candidate.message_id])

                    if candidate.message_id in analysis_results:
                        render_registration_candidate_card(
                            analysis_results[candidate.message_id]
                        )


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

user_info_col, logout_col = st.columns([4, 1])

with user_info_col:
    st.markdown(f"ようこそ、**{display_name}** さん")

with logout_col:
    if st.button("ログアウト", use_container_width=True):
        _clear_tripflow_session_state()
        st.logout()
        # st.logout()はリダイレクトを予約するだけで、このスクリプト実行
        # 自体は止まらない。ここで停止しないと、クリア直後に以降のUIが
        # そのまま再描画され、ウィジェットのkeyがsession_stateに再生成
        # されてしまう（せっかくクリアした意味が薄れるうえ、ログアウト
        # 完了までの一瞬、UIがちらつく）。
        st.stop()


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
    # Web v0.4 Phase B: メール検索・候補一覧表示まで。
    # 本文の本格解析・予約登録・DB保存はまだ行わない（Phase C以降）。
    with st.expander("📧 Gmailから予約を探す", expanded=False):
        _render_gmail_search_section()

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
                    user_id=user_id,
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

    all_trips = safe_fetch(
        fetch_trips,
        user_id,
        default=[],
        error_message="出張データの読み込みに失敗しました。時間をおいて再度お試しください。",
    )

    # ホーム画面の各項目からの「ジャンプ」を、あればここで1回だけ受け取る。
    # 出張が無い場合でも呼び出し、古い移動要求がsession_stateに残らないようにする。
    jump_trip_id, jump_reservation_id, jump_source_label = pop_trip_jump()

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

        if jump_trip_id is not None and jump_trip_id in trip_options:
            st.session_state[EDIT_TRIP_SELECT_KEY] = jump_trip_id
            if jump_source_label:
                st.info(
                    f"「{jump_source_label}」から移動しました。"
                    "該当の出張を選択しています。"
                )
        else:
            jump_reservation_id = None

        # 削除やログインユーザーの切り替え等で、選択中の出張IDが
        # もう存在しない（または自分の所有物ではない）場合、
        # そのままだと下のselectboxのformat_funcでKeyErrorになるため、
        # 事前に安全へクリアしておく。
        clear_stale_selection(EDIT_TRIP_SELECT_KEY, trip_options.keys())

        selected_id = st.selectbox(
            "編集する出張を選択",
            options=list(trip_options.keys()),
            format_func=lambda trip_id: trip_options[trip_id],
            key=EDIT_TRIP_SELECT_KEY,
        )

        selected_trip = fetch_trip(user_id, selected_id)

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
                    affected_rows = update_trip(
                        user_id=user_id,
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
                    if affected_rows == 0:
                        st.error(OWNERSHIP_ERROR_MESSAGE)
                    else:
                        st.success(f"「{edit_name}」を更新しました。")
                        all_trips = safe_fetch(
                            fetch_trips,
                            user_id,
                            default=[],
                            error_message="出張データの読み込みに失敗しました。時間をおいて再度お試しください。",
                        )

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
                        affected_rows = delete_trip(user_id=user_id, trip_id=selected_id)

                    except sqlite3.Error:
                        st.error("出張の削除に失敗しました。時間をおいて再度お試しください。")

                    else:
                        st.session_state[confirm_key] = False

                        if affected_rows == 0:
                            st.error(OWNERSHIP_ERROR_MESSAGE)
                        else:
                            # 削除した出張のIDがセレクトボックスの状態に残ったままだと、
                            # 次の描画でoptionsに存在しないIDのformat_funcが呼ばれて
                            # KeyErrorになるため、選択状態もあわせてリセットする。
                            st.session_state.pop(EDIT_TRIP_SELECT_KEY, None)
                            st.toast(
                                f"「{selected_trip['name']}」を削除しました。", icon="🗑️"
                            )
                            st.rerun()

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
                            user_id=user_id,
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
                            user_id=user_id,
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

                except OwnershipError:
                    st.error(OWNERSHIP_ERROR_MESSAGE)

                except sqlite3.Error:
                    st.error("予約の保存に失敗しました。時間をおいて再度お試しください。")

                else:
                    st.success(f"「{reservation_title}」を追加しました。")

        reservations = safe_fetch(
            fetch_reservations_by_trip,
            user_id,
            selected_id,
            default=[],
            error_message="予約データの読み込みに失敗しました。時間をおいて再度お試しください。",
        )

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

            if (
                jump_reservation_id is not None
                and jump_reservation_id in reservation_options
            ):
                st.session_state[f"select_reservation_{selected_id}"] = (
                    jump_reservation_id
                )

            # 出張IDと同様、選択中の予約IDがもう存在しない
            # （または自分の所有物ではない）場合に備えて事前にクリアする。
            clear_stale_selection(
                f"select_reservation_{selected_id}", reservation_options.keys()
            )

            selected_reservation_id = st.selectbox(
                "編集する予約を選択",
                options=list(reservation_options.keys()),
                format_func=lambda reservation_id: reservation_options[reservation_id],
                key=f"select_reservation_{selected_id}",
            )

            selected_reservation = fetch_reservation(user_id, selected_reservation_id)

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
                            affected_rows = update_reservation(
                                user_id=user_id,
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
                            affected_rows = update_reservation(
                                user_id=user_id,
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
                        if affected_rows == 0:
                            st.error(OWNERSHIP_ERROR_MESSAGE)
                        else:
                            st.toast(
                                f"「{edit_reservation_title}」を更新しました。", icon="✅"
                            )
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
                            affected_rows = delete_reservation(
                                user_id=user_id,
                                reservation_id=selected_reservation_id,
                            )

                        except sqlite3.Error:
                            st.error(
                                "予約の削除に失敗しました。時間をおいて再度お試しください。"
                            )

                        else:
                            st.session_state[reservation_confirm_key] = False

                            if affected_rows == 0:
                                st.error(OWNERSHIP_ERROR_MESSAGE)
                            else:
                                # 削除した予約のIDがセレクトボックスの状態に残ったままだと、
                                # 次の描画でoptionsに存在しないIDのformat_funcが呼ばれて
                                # KeyErrorになるため、選択状態もあわせてリセットする。
                                st.session_state.pop(
                                    f"select_reservation_{selected_id}", None
                                )
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

        st.markdown("#### 予約の詳細")

        if reservations:
            for reservation in reservations:
                icon = SERVICE_ICONS.get(reservation["reservation_service"], "📌")

                with st.expander(
                    f"{icon} {reservation['reservation_type']}・"
                    f"{reservation['reservation_service']}：{reservation['title']}"
                ):
                    render_reservation_card(reservation)

            st.markdown("#### 予約一覧（表）")

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
                        if get_reservation_status(user_id, trip["id"])["complete"]
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
    upcoming_trips = safe_fetch(
        fetch_upcoming_trips,
        user_id,
        today,
        limit=3,
        default=[],
        error_message="出張データの読み込みに失敗しました。時間をおいて再度お試しください。",
    )

    this_month_start, this_month_end = _month_bounds(today)
    this_month_trips = safe_fetch(
        fetch_trips_in_range,
        user_id,
        this_month_start,
        this_month_end,
        default=[],
        error_message="出張データの読み込みに失敗しました。時間をおいて再度お試しください。",
    )
    this_month_reservations = safe_fetch(
        fetch_reservations_in_range,
        user_id,
        this_month_start,
        this_month_end,
        default=[],
        error_message="予約データの読み込みに失敗しました。時間をおいて再度お試しください。",
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
        if not get_reservation_status(user_id, trip["id"])["complete"]
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
        if not get_reservation_status(user_id, trip["id"])["complete"]
    ]

    with st.expander(f"🧳 出張予定：{trip_count}件の内訳"):
        if this_month_trips:
            for trip in this_month_trips:
                line_col, button_col = st.columns([4, 1])
                with line_col:
                    st.markdown(format_trip_line(trip))
                with button_col:
                    render_trip_jump_button(
                        "詳細へ",
                        trip["id"],
                        f"出張予定：{trip['name']}",
                        key=f"jump_trip_month_{trip['id']}",
                    )
        else:
            st.caption("今月の出張はありません。")

    with st.expander(f"🎫 予約：{reservation_count}件の内訳"):
        if this_month_reservations:
            for reservation in this_month_reservations:
                line_col, button_col = st.columns([4, 1])
                with line_col:
                    st.markdown(format_reservation_line(reservation))
                with button_col:
                    render_trip_jump_button(
                        "詳細へ",
                        reservation["trip_id"],
                        f"予約：{reservation['title']}",
                        key=f"jump_reservation_month_{reservation['id']}",
                        reservation_id=reservation["id"],
                    )
        else:
            st.caption("今月の予約はありません。")

    with st.expander(f"⚠️ 確認が必要：{attention_count}件の内訳"):
        if incomplete_month_trips:
            for trip in incomplete_month_trips:
                status = get_reservation_status(user_id, trip["id"])
                info_col, button_col = st.columns([4, 1])
                with info_col:
                    st.markdown(
                        f"**{trip['name']}**　"
                        f"{_format_date(trip['start_date'])} 〜 "
                        f"{_format_date(trip['end_date'])}"
                    )
                    st.markdown(
                        _status_line("往路", status["outbound"])
                        + "　"
                        + _status_line("ホテル", status["hotel"])
                        + "　"
                        + _status_line("復路", status["return"])
                    )
                with button_col:
                    render_trip_jump_button(
                        "予約を追加",
                        trip["id"],
                        f"確認が必要：{trip['name']}",
                        key=f"jump_trip_attention_{trip['id']}",
                    )
        else:
            st.caption("今月、確認が必要な出張はありません。")

    st.markdown("### 直近の出張")

    if upcoming_trips:
        for trip in upcoming_trips:
            status = get_reservation_status(user_id, trip["id"])
            trip_reservations = safe_fetch(
                fetch_reservations_by_trip,
                user_id,
                trip["id"],
                default=[],
                error_message="予約データの読み込みに失敗しました。時間をおいて再度お試しください。",
            )

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

                render_trip_jump_button(
                    "🧳 出張タブでこの出張を編集する",
                    trip["id"],
                    f"直近の出張：{trip['name']}",
                    key=f"jump_trip_upcoming_{trip['id']}",
                )

                st.markdown("##### 予約一覧")

                if trip_reservations:
                    for reservation in trip_reservations:
                        st.markdown(format_reservation_line(reservation))
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

    range_trips = safe_fetch(
        fetch_trips_in_range,
        user_id,
        range_start,
        range_end,
        default=[],
        error_message="出張データの読み込みに失敗しました。時間をおいて再度お試しください。",
    )
    range_reservations = safe_fetch(
        fetch_reservations_in_range,
        user_id,
        range_start,
        range_end,
        default=[],
        error_message="予約データの読み込みに失敗しました。時間をおいて再度お試しください。",
    )

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
        if day_detail_trips:
            st.markdown("###### 🧳 出張")
            for trip in day_detail_trips:
                render_trip_card(trip)

        reservation_type_labels = {
            "往路": "🚄 往路",
            "ホテル": "🏨 ホテル",
            "復路": "🚄 復路",
            "その他": "📌 その他予約",
        }

        for reservation_type, section_label in reservation_type_labels.items():
            type_reservations = [
                reservation
                for reservation in day_detail_reservations
                if reservation["reservation_type"] == reservation_type
            ]

            if not type_reservations:
                continue

            st.markdown(f"###### {section_label}")

            for reservation in type_reservations:
                render_reservation_card(reservation, context_day=selected_day)

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
            st.markdown(format_trip_line(trip))

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
            st.markdown(format_reservation_month_line(reservation))

    else:
        st.caption("この月に予約はありません。")