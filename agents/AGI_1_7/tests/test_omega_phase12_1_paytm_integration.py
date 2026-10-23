"""Comprehensive Acceptance Test Suite for Phase 12.1:
Paytm Money App Registration, Local Callback and Secure API Integration.

Covers:
1. Callback route and parameter validation (requestToken, state).
2. CSRF / state nonce generation and verification.
3. Replay attack rejection (HTTP 409 Conflict).
4. Missing parameter rejection (HTTP 400 Bad Request).
5. Token and secret redaction across log helpers and query strings.
6. Health and readiness endpoints (/health, /ready) with zero secret leakage.
7. Local session token storage, persistence, and expiration.
8. Account details and margin limits API parsing.
9. Market-data REST quote snapshots and validation.
10. WebSocket streaming connection URL and subscription packet structure.
11. Strict fail-closed live order dispatch boundary (LiveTradingDisabledError).
12. Paper/live ledger separation and epoch integrity.
13. Git secret scanning ensuring no API secrets or .env files are tracked.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, Tuple
from unittest.mock import MagicMock, patch

from agents.AGI_1_7.engine.agi17.adapters.paytm_auth_callback_server import (
    PaytmAuthCallbackServer,
    PaytmTokenStore,
    redact_query_string,
    redact_token,
)
from agents.AGI_1_7.engine.agi17.adapters.paytm_open_api_client import (
    AccountDetails,
    LiveTradingDisabledError,
    MarginLimits,
    PaytmApiError,
    PaytmOpenApiClient,
    QuoteSnapshot,
)


class TestOmegaPhase121PaytmIntegration(unittest.TestCase):
    """Authoritative Test Suite for Phase 12.1 Paytm Money Integration."""

    TEST_PORT = 8912
    BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.storage_dir = Path(cls.temp_dir.name)
        cls.token_store = PaytmTokenStore(cls.storage_dir / "test_paytm_session.json")

        # Mock token exchange handler to avoid hitting external Paytm servers during tests
        def mock_exchange(request_token: str, state: str) -> Tuple[bool, str]:
            if request_token == "TRIGGER_EXCHANGE_ERROR":
                return False, "Simulated upstream gateway timeout"
            cls.token_store.save_session(
                access_token="JWT_TEST_ACCESS_TOKEN_123456",
                public_access_token="JWT_TEST_PUBLIC_TOKEN_789",
                read_access_token="JWT_TEST_READ_TOKEN_012",
                metadata={"request_token": redact_token(request_token), "state": state},
            )
            return True, ""

        cls.server = PaytmAuthCallbackServer(
            host="127.0.0.1",
            port=cls.TEST_PORT,
            callback_path="/paytm/callback",
            api_key="TEST_API_KEY_ABCD",
            api_secret="TEST_API_SECRET_WXYZ",
            token_store=cls.token_store,
            enforce_state_check=True,
            token_exchange_handler=mock_exchange,
        )
        cls.server.start_background()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def _http_get(self, path: str) -> Tuple[int, str, Dict[str, str]]:
        req = urllib.request.Request(f"{self.BASE_URL}{path}")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                status = resp.status
                content = resp.read().decode("utf-8")
                headers = dict(resp.getheaders())
                return status, content, headers
        except urllib.error.HTTPError as e:
            content = e.read().decode("utf-8") if e.fp else ""
            headers = dict(e.headers) if e.headers else {}
            return e.code, content, headers

    # =========================================================================
    # 1. Callback Route & Parameter Validation
    # =========================================================================

    def test_callback_server_accepts_valid_request_token(self) -> None:
        """Verify callback successfully accepts valid requestToken with valid state nonce."""
        _, state = self.server.generate_login_url()
        status, html, _ = self._http_get(f"/paytm/callback?requestToken=REQ_TOK_9999&state={state}")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("Authentication Complete", html)
        self.assertIn("Operator Console", html)
        # Ensure secret request token is never rendered in HTML response
        self.assertNotIn("REQ_TOK_9999", html)

        # Verify session token was stored safely
        session = self.token_store.load_session()
        self.assertIsNotNone(session)
        self.assertEqual(session["access_token"], "JWT_TEST_ACCESS_TOKEN_123456")

    def test_callback_server_rejects_missing_request_token(self) -> None:
        """Verify callback returns HTTP 400 Bad Request when requestToken is omitted."""
        _, state = self.server.generate_login_url()
        status, html, _ = self._http_get(f"/paytm/callback?state={state}")

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIn("Invalid Callback Payload", html)
        self.assertIn("Missing Token", html)

    def test_callback_server_rejects_invalid_csrf_state(self) -> None:
        """Verify callback returns HTTP 403 Forbidden on forged or missing state nonce."""
        status, html, _ = self._http_get("/paytm/callback?requestToken=REQ_TOK_FORGED&state=INVALID_NONCE")

        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertIn("Security Validation Failed", html)

    def test_callback_server_prevents_replay_attacks(self) -> None:
        """Verify consuming the same requestToken twice returns HTTP 409 Conflict."""
        _, state1 = self.server.generate_login_url()
        _, state2 = self.server.generate_login_url()
        unique_token = "REPLAY_TEST_TOKEN_UNIQUE_1"

        # First consumption
        status1, _, _ = self._http_get(f"/paytm/callback?requestToken={unique_token}&state={state1}")
        self.assertEqual(status1, HTTPStatus.OK)

        # Replay attempt
        status2, html2, _ = self._http_get(f"/paytm/callback?requestToken={unique_token}&state={state2}")
        self.assertEqual(status2, HTTPStatus.CONFLICT)
        self.assertIn("Token Already Consumed", html2)

    def test_callback_server_handles_exchange_error(self) -> None:
        """Verify callback returns HTTP 500 when upstream S2S token exchange fails."""
        _, state = self.server.generate_login_url()
        status, html, _ = self._http_get(f"/paytm/callback?requestToken=TRIGGER_EXCHANGE_ERROR&state={state}")

        self.assertEqual(status, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.assertIn("Token Exchange Failed", html)

    # =========================================================================
    # 2. Token Redaction & Safe Endpoints
    # =========================================================================

    def test_secret_redaction_utilities(self) -> None:
        """Verify tokens and secrets are redacted properly without leaking full strings."""
        raw_secret = "secret_key_1234567890abcdef"
        redacted = redact_token(raw_secret)
        self.assertEqual(redacted, "secr...cdef")
        self.assertNotIn("1234567890", redacted)

        self.assertEqual(redact_token(None), "[NONE]")
        self.assertEqual(redact_token("short"), "********")

        raw_query = "requestToken=secret12345678&apiKey=my_key_9999&normal_param=hello"
        sanitized_query = redact_query_string(raw_query)
        self.assertNotIn("secret12345678", sanitized_query)
        self.assertIn("normal_param=hello", sanitized_query)

    def test_health_and_readiness_endpoints_leak_no_secrets(self) -> None:
        """Verify /health and /ready endpoints disclose operational status with zero secrets."""
        status_health, body_health, _ = self._http_get("/health")
        self.assertEqual(status_health, HTTPStatus.OK)
        data_health = json.loads(body_health)
        self.assertEqual(data_health["status"], "HEALTHY")
        self.assertEqual(data_health["service"], "PaytmAuthCallbackServer")
        self.assertIn("session_active", data_health)
        self.assertNotIn("JWT_TEST_ACCESS_TOKEN", body_health)

        status_ready, body_ready, _ = self._http_get("/ready")
        self.assertEqual(status_ready, HTTPStatus.OK)
        data_ready = json.loads(body_ready)
        self.assertTrue(data_ready["ready"])
        self.assertEqual(data_ready["callback_path"], "/paytm/callback")

    # =========================================================================
    # 3. Token Storage & Session Expiration
    # =========================================================================

    def test_token_store_persistence_and_expiration(self) -> None:
        """Verify token storage saves, loads, expires at midnight, and clears cleanly."""
        temp_store_file = self.storage_dir / "temp_session.json"
        store = PaytmTokenStore(temp_store_file)

        store.save_session(
            access_token="MY_ACTIVE_TOKEN_ABC",
            public_access_token="MY_PUB_TOKEN_DEF",
        )
        loaded = store.load_session()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["access_token"], "MY_ACTIVE_TOKEN_ABC")

        # Simulate expired session
        yesterday = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
        loaded["expires_at"] = yesterday
        temp_store_file.write_text(json.dumps(loaded), encoding="utf-8")

        expired_load = store.load_session()
        self.assertIsNone(expired_load)

        # Clear session
        store.clear_session()
        self.assertFalse(temp_store_file.exists())

    # =========================================================================
    # 4. PaytmOpenApiClient & Read-Only APIs (Mocked Transport)
    # =========================================================================

    def test_client_authentication_state(self) -> None:
        """Verify client authentication checks and login URL generation."""
        client = PaytmOpenApiClient(
            api_key="DEMO_API_KEY",
            api_secret="DEMO_SECRET",
            token_store=self.token_store,
        )
        self.assertTrue(client.is_authenticated())

        login_url = client.get_login_url(state_key="TEST_STATE_KEY")
        self.assertIn("https://login.paytmmoney.com/merchant-login", login_url)
        self.assertIn("apiKey=DEMO_API_KEY", login_url)
        self.assertIn("state=TEST_STATE_KEY", login_url)

    @patch("urllib.request.urlopen")
    def test_get_user_details_parsing(self, mock_urlopen: MagicMock) -> None:
        """Verify parsing of /accounts/v1/user/details response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "success",
            "data": {
                "client_id": "PM_CLIENT_007",
                "user_name": "Test Trader",
                "kyc_status": "VERIFIED",
                "email": "trader@example.com",
                "fno_enabled": True,
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = PaytmOpenApiClient(
            access_token="MOCK_JWT",
            token_store=self.token_store,
        )
        details = client.get_user_details()
        self.assertIsInstance(details, AccountDetails)
        self.assertEqual(details.client_id, "PM_CLIENT_007")
        self.assertEqual(details.user_name, "Test Trader")
        self.assertTrue(details.is_fno_enabled)

    @patch("urllib.request.urlopen")
    def test_get_funds_and_margins_parsing(self, mock_urlopen: MagicMock) -> None:
        """Verify parsing of /accounts/v1/user/limits response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "success",
            "data": {
                "available_margin": 150000.50,
                "utilized_margin": 24500.00,
                "net_cash_balance": 125500.50,
                "collateral_amount": 0.0,
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = PaytmOpenApiClient(access_token="MOCK_JWT")
        limits = client.get_funds_and_margins()
        self.assertIsInstance(limits, MarginLimits)
        self.assertEqual(limits.available_margin, 150000.50)
        self.assertEqual(limits.utilized_margin, 24500.00)

    @patch("urllib.request.urlopen")
    def test_get_live_quotes_parsing(self, mock_urlopen: MagicMock) -> None:
        """Verify parsing of /data/v1/quotes response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "success",
            "data": [
                {
                    "security_id": "2000000011",
                    "exchange": "NSE",
                    "last_price": 24250.00,
                    "bid": 24249.95,
                    "ask": 24250.05,
                    "volume": 1250000,
                    "open_interest": 8500000,
                }
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = PaytmOpenApiClient(access_token="MOCK_JWT")
        quotes = client.get_live_quotes(mode="FULL", preferences=[{"security_id": "2000000011"}])
        self.assertEqual(len(quotes), 1)
        q = quotes[0]
        self.assertIsInstance(q, QuoteSnapshot)
        self.assertEqual(q.security_id, "2000000011")
        self.assertEqual(q.last_price, 24250.00)

    def test_websocket_url_and_subscription_packet(self) -> None:
        """Verify WebSocket connection URL and subscription packet structure."""
        client = PaytmOpenApiClient(access_token="JWT_SOCKET_TEST")
        ws_url = client.get_websocket_connection_url()
        self.assertEqual(ws_url, "wss://developer-ws.paytmmoney.com/broadcast/user/v1/data?x_jwt_token=JWT_SOCKET_TEST")

        packet = client.build_websocket_subscription_packet(
            action="subscribe",
            mode="FULL",
            preferences=[{"action_type": "ADD", "mode_type": "FULL", "scrip_type": "INDEX", "security_id": "2000000011"}]
        )
        self.assertEqual(packet["action"], "subscribe")
        self.assertEqual(packet["mode"], "FULL")
        self.assertEqual(len(packet["preferences"]), 1)

    # =========================================================================
    # 5. Strict Fail-Closed Live Order Protection
    # =========================================================================

    def test_prevention_of_unauthorized_live_order_dispatch(self) -> None:
        """Verify client strictly refuses live order dispatch when disabled."""
        client = PaytmOpenApiClient(
            access_token="MOCK_JWT",
            live_order_dispatch_enabled=False,
        )
        self.assertFalse(client.live_order_dispatch_enabled)

        # Order placement must raise LiveTradingDisabledError without making network calls
        with self.assertRaises(LiveTradingDisabledError):
            client.place_order({
                "txn_type": "B",
                "exchange": "NSE",
                "segment": "E",
                "product": "I",
                "security_id": "2000000011",
                "quantity": 65,
                "price": 100.0,
                "order_type": "LMT",
            })

        # Order modification must also be blocked
        with self.assertRaises(LiveTradingDisabledError):
            client.modify_order({"order_no": "ORD12345", "price": 105.0})

        # Order cancellation must also be blocked
        with self.assertRaises(LiveTradingDisabledError):
            client.cancel_order("ORD12345")

    # =========================================================================
    # 6. Paper/Live Ledger Separation & Git Secret Scanning
    # =========================================================================

    def test_paper_live_ledger_isolation(self) -> None:
        """Verify paper ledger remains paper-only with zero live broker records."""
        ledger_path = Path(__file__).resolve().parents[1] / "ui" / "runtime_storage" / "monthly_paper_ledger.json"
        self.assertTrue(ledger_path.exists())

        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertIn("PAPER ONLY", ledger["mode"])
        self.assertIn("epoch_id", ledger)
        # Ensure no live broker order IDs exist in positions
        for pos in ledger.get("active_positions", []) + ledger.get("closed_positions", []):
            self.assertNotIn("broker_order_id", pos)
            self.assertNotIn("PM_", str(pos.get("order_id", "")))

    def test_git_secret_scanning_verifies_clean_repo(self) -> None:
        """Verify that .env and real credentials are not tracked in Git."""
        repo_root = Path(__file__).resolve().parents[3]
        gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore)
        self.assertIn("*.token", gitignore)
        self.assertIn("credentials.json", gitignore)

        # Run git status to verify .env is untracked
        res = subprocess.run(
            ["git", "status", "--porcelain", ".env"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
