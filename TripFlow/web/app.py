from __future__ import annotations

from datetime import date

import streamlit as st


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
# SQLite接続前の仮データです
# --------------------------------------------------
today = date.today()

monthly_cost = 0
trip_count = 0
reservation_count = 0
attention_count = 0


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
# ホーム画面
# --------------------------------------------------
with home_tab:
    st.subheader(f"{today.year}年{today.month}月")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("今月の費用", f"¥{monthly_cost:,}")
    col2.metric("出張予定", f"{trip_count}件")
    col3.metric("予約", f"{reservation_count}件")
    col4.metric("確認が必要", f"{attention_count}件")

    st.markdown("### 直近の出張")

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
# 出張画面
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
            ["業務", "プライベート", "未分類"],
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
            st.success(
                f"「{trip_name}」の入力を確認しました。"
                "次の工程でSQLiteへ保存できるようにします。"
            )

    st.divider()
    st.subheader("登録済みの出張")
    st.caption("SQLite接続後、ここに登録した出張を表示します。")


# --------------------------------------------------
# カレンダー画面
# --------------------------------------------------
with calendar_tab:
    st.subheader("出張カレンダー")

    st.info(
        "次の工程で、出張期間と予約情報を"
        "カレンダーに表示できるようにします。"
    )

    st.calendar if False else None