"""Gmail APIの読み取り専用呼び出しをまとめたモジュール（Web v0.4 Phase B/C）。

Phase Bまでは「予約メール候補の検索と、一覧表示に必要な最低限のメタデータ取得」
までだった。Phase Cでは、それに加えて「予約情報抽出対象」と判定された1件の
メールについてのみ、本文（text/plain・text/html）を取得する関数を追加する。
本文の解析（分類・項目抽出）自体はこのモジュールでは行わず、reservation_parser.py
に委ねる（責務分離。本文取得＝Gmail API呼び出しの詳細と、解析ロジックを
混在させない）。

- access tokenは呼び出し元（app.py）から引数として都度受け取るだけで、
  このモジュール内で保持・キャッシュ・ログ出力は一切しない。
- Gmail API呼び出しは既存依存のhttpxで直接REST APIを叩く（新規ライブラリを
  追加しない方針のため）。
- 候補一覧の取得では、メール本文（payload.body等）は取得しない。取得するのは
  ヘッダー（件名・送信元・日付）とsnippet（Gmail側が生成する短い抜粋）のみ。
  本文取得は、ユーザーが個別のメールに対して解析を指示したときのみ行う
  （全候補メールの本文を無条件に取得することはしない）。
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
DEFAULT_SEARCH_MONTHS = 3
DEFAULT_MAX_RESULTS_PER_SERVICE = 20
REQUEST_TIMEOUT_SECONDS = 15.0

# サービスごとの検索条件（送信元ドメイン・件名キーワード）。
#
# 重要：ここに書いたドメイン・キーワードは、実際に届いているメールを
# まだ確認していない段階での「広めの初期案」であり、確定仕様ではない。
# Phase Bで実際にログイン中ユーザーのGmailを検索し、取得できたメールの
# 送信元・件名を確認したうえで、このルールを見直すことを前提にしている。
SERVICE_SEARCH_RULES: dict[str, dict[str, list[str]]] = {
    "えきねっと": {
        "from_domains": ["eki-net.com"],
        "subject_keywords": ["えきねっと"],
    },
    "Agoda": {
        "from_domains": ["agoda.com"],
        "subject_keywords": ["Agoda"],
    },
}

SUPPORTED_SERVICES = tuple(SERVICE_SEARCH_RULES.keys())


class GmailAPIError(Exception):
    """Gmail API呼び出しに関する既知のエラー。画面表示用の日本語メッセージを保持する。"""

    def __init__(self, user_message: str, *, status_code: int | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code


@dataclass(frozen=True)
class GmailMessageCandidate:
    """候補一覧表示に必要な最低限の情報のみを保持する（本文全文は含まない）。"""

    message_id: str
    thread_id: str
    subject: str
    sender: str
    received_at: str
    snippet: str
    service: str
    internal_date_ms: int


def build_search_query(service: str, *, months: int = DEFAULT_SEARCH_MONTHS) -> str:
    """指定した1サービス分のGmail検索クエリ（qパラメータ）を組み立てる。"""
    rule = SERVICE_SEARCH_RULES.get(service)
    if not rule:
        raise ValueError(f"未対応のサービスです: {service}")

    clauses: list[str] = []
    for domain in rule.get("from_domains", []):
        clauses.append(f"from:{domain}")
    for keyword in rule.get("subject_keywords", []):
        clauses.append(f"subject:{keyword}")

    if not clauses:
        raise ValueError(f"サービス「{service}」の検索条件が設定されていません。")

    query = "(" + " OR ".join(clauses) + ")"

    after_date = date.today() - timedelta(days=30 * months)
    query += f" after:{after_date.strftime('%Y/%m/%d')}"

    return query


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _translate_http_status_error(exc: httpx.HTTPStatusError) -> GmailAPIError:
    status = exc.response.status_code

    if status == 401:
        return GmailAPIError(
            "Gmail連携の認証期限が切れました。ログアウト後、再ログインしてください。",
            status_code=401,
        )
    if status == 403:
        return GmailAPIError(
            "Gmail APIへのアクセスが許可されませんでした。Google Cloud側の設定"
            "（Gmail APIの有効化・gmail.readonlyスコープ・テストユーザー登録）を"
            "ご確認ください。",
            status_code=403,
        )
    if status == 429:
        return GmailAPIError(
            "Gmail APIへのリクエストが混み合っています。しばらく時間をおいて"
            "再度お試しください。",
            status_code=429,
        )

    return GmailAPIError(
        f"Gmail APIの呼び出し中にエラーが発生しました（status={status}）。"
        "時間をおいて再度お試しください。",
        status_code=status,
    )


def _get(url: str, *, access_token: str, params: dict) -> dict:
    """Gmail APIへGETリクエストを送り、JSONを返す。既知のエラーはGmailAPIErrorへ変換する。

    access_tokenはヘッダー生成にのみ使い、例外メッセージには絶対に含めない。
    """
    try:
        response = httpx.get(
            url,
            headers=_auth_headers(access_token),
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise _translate_http_status_error(exc) from None
    except httpx.TimeoutException:
        raise GmailAPIError(
            "Gmail APIへの接続がタイムアウトしました。時間をおいて再度お試しください。"
        ) from None
    except httpx.RequestError:
        raise GmailAPIError(
            "Gmail APIへの接続に失敗しました。ネットワーク状況をご確認のうえ、"
            "再度お試しください。"
        ) from None

    return response.json()


def _search_message_ids(
    access_token: str, query: str, *, max_results: int
) -> list[str]:
    payload = _get(
        f"{GMAIL_API_BASE}/users/me/messages",
        access_token=access_token,
        params={"q": query, "maxResults": max_results},
    )
    return [item["id"] for item in payload.get("messages", [])]


def _extract_header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _format_received_at(internal_date_ms: int) -> str:
    if not internal_date_ms:
        return "(受信日時不明)"
    dt = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y/%m/%d %H:%M")


def _fetch_message_summary(
    access_token: str, message_id: str, *, service: str
) -> GmailMessageCandidate:
    """件名・送信元・日付・snippetのみ取得する（本文本体は取得しない）。"""
    raw = _get(
        f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
        access_token=access_token,
        params={
            "format": "metadata",
            "metadataHeaders": ["Subject", "From", "Date"],
        },
    )

    headers = raw.get("payload", {}).get("headers", [])
    internal_date_ms = int(raw.get("internalDate") or 0)

    return GmailMessageCandidate(
        message_id=raw.get("id", message_id),
        thread_id=raw.get("threadId", ""),
        subject=_extract_header(headers, "Subject") or "(件名なし)",
        sender=_extract_header(headers, "From") or "(送信元不明)",
        received_at=_format_received_at(internal_date_ms),
        snippet=raw.get("snippet", ""),
        service=service,
        internal_date_ms=internal_date_ms,
    )


def search_reservation_candidates(
    access_token: str,
    services: list[str],
    *,
    months: int = DEFAULT_SEARCH_MONTHS,
    max_results_per_service: int = DEFAULT_MAX_RESULTS_PER_SERVICE,
) -> list[GmailMessageCandidate]:
    """指定サービスの予約メール候補を検索し、新しい順に並べて返す。

    全メールを無制限に走査することはせず、サービスごとにqパラメータで
    絞り込んだうえ、maxResultsで件数を制限する。
    """
    candidates: dict[str, GmailMessageCandidate] = {}

    for service in services:
        query = build_search_query(service, months=months)
        message_ids = _search_message_ids(
            access_token, query, max_results=max_results_per_service
        )
        for message_id in message_ids:
            if message_id in candidates:
                continue
            candidates[message_id] = _fetch_message_summary(
                access_token, message_id, service=service
            )

    return sorted(
        candidates.values(), key=lambda c: c.internal_date_ms, reverse=True
    )


# --------------------------------------------------
# Web v0.4 Phase C: 個別メールの本文取得。
# 「予約情報抽出対象」と判定された1件について、ユーザーが解析を指示した
# ときにだけ呼び出す想定（候補一覧全件への自動呼び出しはしない）。
# --------------------------------------------------
@dataclass(frozen=True)
class GmailMessageBody:
    """解析対象メール1件分の本文（プレーンテキスト・HTML）。

    件名・送信元等のヘッダーは候補一覧（GmailMessageCandidate）に既に
    保持しているため、ここでは本文のみを保持する。
    """

    message_id: str
    text_plain: str
    text_html: str


def _decode_body_data(data: str | None) -> str:
    """Gmail APIのbase64url（パディング省略あり）本文データをデコードする。

    想定外の形式（デコード不能なデータ）が来てもcrashさせず、空文字列を返す。
    """
    if not data:
        return ""

    padded = data + "=" * (-len(data) % 4)

    try:
        raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError, binascii.Error):
        return ""

    return raw_bytes.decode("utf-8", errors="replace")


def _collect_body_parts(
    payload: dict, plain_chunks: list[str], html_chunks: list[str]
) -> None:
    """payloadを再帰的にたどり、text/plainとtext/htmlの本文を集める。

    multipart/alternative・multipart/mixed・multipart/related等、ネストした
    partsを持つメールにも対応する。添付ファイル（attachmentIdのみを持ち、
    dataを持たないパート）は本文として扱わず無視する。
    """
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data")

    if data and "attachmentId" not in body:
        decoded = _decode_body_data(data)
        if decoded:
            if mime_type == "text/plain":
                plain_chunks.append(decoded)
            elif mime_type == "text/html":
                html_chunks.append(decoded)

    for part in payload.get("parts", []) or []:
        _collect_body_parts(part, plain_chunks, html_chunks)


def fetch_message_body(access_token: str, message_id: str) -> GmailMessageBody:
    """指定した1件のメールの本文（text/plain・text/html）を取得する。

    「予約情報抽出対象」と判定されたメールについて、ユーザーが解析ボタンを
    押したときに1件ずつ呼び出す想定であり、候補一覧の全件に対して自動的に
    呼び出すことはしない。取得した本文はここでは一切ログ出力しない。
    """
    raw = _get(
        f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
        access_token=access_token,
        params={"format": "full"},
    )

    plain_chunks: list[str] = []
    html_chunks: list[str] = []
    _collect_body_parts(raw.get("payload", {}) or {}, plain_chunks, html_chunks)

    return GmailMessageBody(
        message_id=raw.get("id", message_id),
        text_plain="\n".join(chunk for chunk in plain_chunks if chunk),
        text_html="\n".join(chunk for chunk in html_chunks if chunk),
    )
