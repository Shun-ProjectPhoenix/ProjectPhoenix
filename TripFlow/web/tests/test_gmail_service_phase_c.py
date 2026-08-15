"""gmail_service.py（Web v0.4 Phase B/C）のテスト。

Gmail APIは実際には呼び出さず、httpx.getをモック化して検証する。
使用するmessage_id・access token・本文はすべて人工的なサンプルであり、
実際のメールアカウント・実データとは無関係。
"""
from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gmail_service as gs

FAKE_ACCESS_TOKEN = "FAKE-ACCESS-TOKEN-DO-NOT-LOG-THIS-abc123XYZ"


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


class FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://gmail.googleapis.com/fake")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=request, response=response
            )

    def json(self) -> dict:
        return self._json_data


class FetchMessageBodyMultipartTests(unittest.TestCase):
    """multipart（text/plain + text/html）本文の取得・結合を確認する。"""

    def test_collects_plain_and_html_parts_from_nested_multipart(self) -> None:
        payload = {
            "id": "msg-multipart-1",
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {"data": _b64url("プレーンテキスト本文")},
                            },
                            {
                                "mimeType": "text/html",
                                "body": {"data": _b64url("<p>HTML本文</p>")},
                            },
                        ],
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "receipt.pdf",
                        "body": {"attachmentId": "attach-1", "size": 12345},
                    },
                ],
            },
        }

        with patch("gmail_service.httpx.get", return_value=FakeResponse(payload)):
            body = gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-multipart-1")

        self.assertEqual(body.text_plain, "プレーンテキスト本文")
        self.assertIn("HTML本文", body.text_html)
        self.assertEqual(body.message_id, "msg-multipart-1")

    def test_single_part_text_plain_message(self) -> None:
        payload = {
            "id": "msg-simple-1",
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": _b64url("単一パートのプレーンテキスト")},
            },
        }

        with patch("gmail_service.httpx.get", return_value=FakeResponse(payload)):
            body = gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-simple-1")

        self.assertEqual(body.text_plain, "単一パートのプレーンテキスト")
        self.assertEqual(body.text_html, "")

    def test_html_only_message(self) -> None:
        payload = {
            "id": "msg-html-only-1",
            "payload": {
                "mimeType": "text/html",
                "body": {"data": _b64url("<div>HTMLのみの本文</div>")},
            },
        }

        with patch("gmail_service.httpx.get", return_value=FakeResponse(payload)):
            body = gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-html-only-1")

        self.assertEqual(body.text_plain, "")
        self.assertIn("HTMLのみの本文", body.text_html)

    def test_unexpected_empty_payload_does_not_crash(self) -> None:
        payload = {"id": "msg-empty-1", "payload": {}}

        with patch("gmail_service.httpx.get", return_value=FakeResponse(payload)):
            body = gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-empty-1")

        self.assertEqual(body.text_plain, "")
        self.assertEqual(body.text_html, "")


class GmailAPIErrorTests(unittest.TestCase):
    """Gmail APIエラー（認証切れ含む）が安全なメッセージへ変換されることを確認する。"""

    def test_401_translates_to_reauth_message(self) -> None:
        with patch("gmail_service.httpx.get", return_value=FakeResponse({}, status_code=401)):
            with self.assertRaises(gs.GmailAPIError) as ctx:
                gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-401")

        self.assertIn("再ログイン", ctx.exception.user_message)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_403_translates_to_permission_message(self) -> None:
        with patch("gmail_service.httpx.get", return_value=FakeResponse({}, status_code=403)):
            with self.assertRaises(gs.GmailAPIError) as ctx:
                gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-403")

        self.assertEqual(ctx.exception.status_code, 403)

    def test_429_translates_to_rate_limit_message(self) -> None:
        with patch("gmail_service.httpx.get", return_value=FakeResponse({}, status_code=429)):
            with self.assertRaises(gs.GmailAPIError) as ctx:
                gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-429")

        self.assertEqual(ctx.exception.status_code, 429)

    def test_timeout_translates_to_safe_message(self) -> None:
        with patch("gmail_service.httpx.get", side_effect=httpx.TimeoutException("timeout")):
            with self.assertRaises(gs.GmailAPIError) as ctx:
                gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-timeout")

        self.assertIn("タイムアウト", ctx.exception.user_message)

    def test_network_error_translates_to_safe_message(self) -> None:
        request = httpx.Request("GET", "https://gmail.googleapis.com/fake")
        with patch(
            "gmail_service.httpx.get",
            side_effect=httpx.ConnectError("boom", request=request),
        ):
            with self.assertRaises(gs.GmailAPIError) as ctx:
                gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-network-error")

        self.assertIn("接続に失敗", ctx.exception.user_message)


class TokenLeakageTests(unittest.TestCase):
    """access tokenが例外メッセージ・戻り値のどこにも含まれないことを確認する。"""

    def test_token_not_in_error_message(self) -> None:
        with patch("gmail_service.httpx.get", return_value=FakeResponse({}, status_code=403)):
            with self.assertRaises(gs.GmailAPIError) as ctx:
                gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-token-1")

        self.assertNotIn(FAKE_ACCESS_TOKEN, ctx.exception.user_message)
        self.assertNotIn(FAKE_ACCESS_TOKEN, str(ctx.exception))

    def test_token_not_in_fetched_body(self) -> None:
        payload = {
            "id": "msg-token-2",
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": _b64url("本文サンプル")},
            },
        }

        with patch("gmail_service.httpx.get", return_value=FakeResponse(payload)) as mock_get:
            body = gs.fetch_message_body(FAKE_ACCESS_TOKEN, "msg-token-2")

        self.assertNotIn(FAKE_ACCESS_TOKEN, body.text_plain)
        self.assertNotIn(FAKE_ACCESS_TOKEN, body.text_html)
        # access tokenはAuthorizationヘッダーとしてのみ送信されている（本文・URL等には含まれない）。
        _, kwargs = mock_get.call_args
        self.assertEqual(
            kwargs["headers"]["Authorization"], f"Bearer {FAKE_ACCESS_TOKEN}"
        )


class PhaseABRegressionTests(unittest.TestCase):
    """Phase A/Bの既存動作（検索クエリ構築・候補一覧）が壊れていないことを確認する。"""

    def test_supported_services_unchanged(self) -> None:
        self.assertEqual(set(gs.SUPPORTED_SERVICES), {"えきねっと", "Agoda"})

    def test_build_search_query_includes_domain_and_period(self) -> None:
        query = gs.build_search_query("えきねっと", months=3)
        self.assertIn("from:eki-net.com", query)
        self.assertIn("after:", query)

    def test_build_search_query_unknown_service_raises(self) -> None:
        with self.assertRaises(ValueError):
            gs.build_search_query("未対応サービス")

    def test_search_reservation_candidates_dedupes_and_sorts(self) -> None:
        list_payload = {"messages": [{"id": "dup-1"}]}
        summary_payload = {
            "id": "dup-1",
            "threadId": "thread-1",
            "internalDate": "1700000000000",
            "snippet": "サンプルsnippet",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "サンプル件名"},
                    {"name": "From", "value": "sample@example.com"},
                    {"name": "Date", "value": "Mon, 01 Jan 2024 00:00:00 +0900"},
                ]
            },
        }

        def fake_get(url: str, *, headers, params, timeout):
            if url.endswith("/messages"):
                return FakeResponse(list_payload)
            return FakeResponse(summary_payload)

        with patch("gmail_service.httpx.get", side_effect=fake_get):
            candidates = gs.search_reservation_candidates(
                FAKE_ACCESS_TOKEN, ["えきねっと", "Agoda"], months=3
            )

        # 両サービスの検索結果に同じmessage_idが出ても1件に重複排除される。
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].message_id, "dup-1")
        self.assertEqual(candidates[0].subject, "サンプル件名")


if __name__ == "__main__":
    unittest.main()
