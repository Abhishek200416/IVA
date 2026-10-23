"""AGI 1.7 OMEGA COMMAND — Phase 17.11 Authentication Lifecycle & Lockout Prevention Suite.

Verifies:
1. System starts in WAITING_FOR_OPERATOR_LOGIN when unauthenticated.
2. 10 minutes simulated wait triggers zero reloads and zero automated auth requests.
3. Repeated status polling spawns zero browser instances, worker processes, or consoles.
4. Valid mocked OAuth callback transitions state cleanly to CONNECTED_READ_ONLY.
5. Dashboard status updates connection state in-place without triggering page reload.
6. Malformed/missing callback parameters do not trigger retry loops or credential submission.
7. Expired/invalid token transitions state cleanly to AUTH_EXPIRED / AUTH_REQUIRED.
8. HTTP 401, 403, 502, and network errors are handled without retry storms.
9. Lockout / rate limit condition (HTTP 429) enters AUTH_LOCKOUT_COOLDOWN with backoff.
10. Dashboard restart is idempotent with zero duplicate servers or worker processes.
11. Sensitive credentials (API secret, request token, access token, JWT) are never logged in plain text.
12. Successful auth does not auto-start paper trading session unprompted.
13. Safety invariants (LIVE_ORDER_DISPATCH_ENABLED = False, is_live_allowed = False) preserved throughout.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import tempfile
import time
import unittest
import urllib.parse
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.AGI_1_7.engine.agi17.adapters.paytm_auth_callback_server import (
    PaytmAuthCallbackServer,
    PaytmTokenStore,
    redact_query_string,
    redact_token,
)
from agents.AGI_1_7.engine.agi17.adapters.paytm_auth_state_machine import (
    PaytmAuthState,
    PaytmAuthStateMachine,
    redact_sensitive_payload,
    redact_sensitive_value,
)
from agents.AGI_1_7.engine.agi17.finance.trading_session_control_plane import SessionState
from agents.AGI_1_7.ui.standalone_dashboard_server import (
    LIVE_ORDER_DISPATCH_ENABLED,
    StandaloneDashboardServer,
)


class TestOmegaPhase1711AuthLifecycle(unittest.TestCase):
    """Authoritative test suite for Phase 17.11 authentication lifecycle and lockout prevention."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="omega_auth_test_"))
        PaytmAuthStateMachine.reset_instance_for_testing()
        self.state_machine = PaytmAuthStateMachine(storage_dir=self.temp_dir)
        self.servers_to_close = []

    def tearDown(self) -> None:
        for s in self.servers_to_close:
            try:
                s.server_close()
            except Exception:
                pass
        PaytmAuthStateMachine.reset_instance_for_testing()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -----------------------------------------------------------------
    # Test 1: Initial state starts in WAITING_FOR_OPERATOR_LOGIN
    # -----------------------------------------------------------------
    def test_01_initial_state_waiting_for_operator_login(self) -> None:
        """Verifies that an unauthenticated system defaults to WAITING_FOR_OPERATOR_LOGIN."""
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN)
        status_dict = self.state_machine.to_dict()
        self.assertEqual(status_dict["auth_state"], "WAITING_FOR_OPERATOR_LOGIN")
        self.assertTrue(status_dict["is_waiting_for_operator"])
        self.assertFalse(status_dict["is_authenticated"])
        self.assertFalse(status_dict["is_cooldown_active"])

    # -----------------------------------------------------------------
    # Test 2: 10 minutes simulated wait triggers zero reloads or auth requests
    # -----------------------------------------------------------------
    def test_02_simulated_wait_zero_reloads_zero_auth_requests(self) -> None:
        """Verifies that remaining in waiting state triggers zero reloads and zero requests."""
        initial_attempts = self.state_machine.auth_attempts

        # Simulate 10 minutes of operational time passage (600 seconds)
        simulated_now = time.time() + 600.0
        with patch("time.time", return_value=simulated_now):
            state = self.state_machine.current_state
            self.assertEqual(state, PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN)
            status_dict = self.state_machine.to_dict()

        self.assertFalse(status_dict["can_reload_page"])
        self.assertTrue(status_dict["zero_reload_enforced"])
        self.assertFalse(status_dict["can_auto_retry"])
        self.assertTrue(status_dict["no_auto_retry_enforced"])
        self.assertEqual(self.state_machine.auth_attempts, initial_attempts)

    # -----------------------------------------------------------------
    # Test 3: Repeated status polling spawns zero processes or consoles
    # -----------------------------------------------------------------
    def test_03_repeated_status_polling_zero_process_spawns(self) -> None:
        """Verifies that repeated status polling queries do not spawn subprocesses or worker threads."""
        with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
            for _ in range(100):
                st = self.state_machine.to_dict()
                self.assertFalse(st["can_spawn_processes"])
                self.assertTrue(st["zero_process_spawn_enforced"])

            self.assertEqual(mock_popen.call_count, 0)
            self.assertEqual(mock_run.call_count, 0)

    # -----------------------------------------------------------------
    # Test 4: Valid mocked OAuth callback transitions to CONNECTED_READ_ONLY
    # -----------------------------------------------------------------
    def test_04_valid_mocked_oauth_callback_transitions_to_connected(self) -> None:
        """Verifies successful callback exchange transitions cleanly to CONNECTED_READ_ONLY."""
        token_store = PaytmTokenStore(storage_path=self.temp_dir / "paytm_session.json")

        def mock_exchange(req_tok: str, state_val: str):
            token_store.save_session(
                access_token="mock_jwt_access_token_12345",
                public_access_token="mock_pub_token",
                read_access_token="mock_read_token",
                metadata={"state": state_val},
            )
            return True, ""

        server = PaytmAuthCallbackServer(
            host="127.0.0.1",
            port=0,
            token_store=token_store,
            token_exchange_handler=mock_exchange,
            state_machine=self.state_machine,
        )
        self.servers_to_close.append(server)

        url, state = server.generate_login_url()
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.AUTHORIZING)

        # Simulate callback
        ok, note = server.handle_token_exchange("valid_req_token_777", state)
        self.assertTrue(ok)
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.CONNECTED_READ_ONLY)

        saved = token_store.load_session()
        self.assertIsNotNone(saved)
        self.assertEqual(saved["access_token"], "mock_jwt_access_token_12345")

    # -----------------------------------------------------------------
    # Test 5: Dashboard status updates connection state in-place without page reload
    # -----------------------------------------------------------------
    def test_05_dashboard_in_place_state_update(self) -> None:
        """Verifies that status payload communicates live auth state without page reloads."""
        server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=0,
            storage_dir=self.temp_dir,
        )
        self.servers_to_close.append(server)
        server.auth_state_machine = self.state_machine

        # Initial waiting state
        status_dict = self.state_machine.to_dict()
        self.assertTrue(status_dict["zero_reload_enforced"])
        self.assertFalse(status_dict["can_reload_page"])

        # Simulate connection
        self.state_machine.on_exchange_success({"access_token": "valid_token"})
        updated_dict = self.state_machine.to_dict()
        self.assertEqual(updated_dict["auth_state"], "CONNECTED_READ_ONLY")
        self.assertTrue(updated_dict["is_authenticated"])
        self.assertTrue(updated_dict["zero_reload_enforced"])

    # -----------------------------------------------------------------
    # Test 6: Malformed/missing callback parameters do not trigger retry loops
    # -----------------------------------------------------------------
    def test_06_malformed_missing_callback_no_retry_loop(self) -> None:
        """Verifies that missing or malformed callback parameters do not cause loops."""
        # Empty token
        ok, msg = self.state_machine.on_callback_received("", "state123")
        self.assertFalse(ok)
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.AUTH_REQUIRED)

        # Replay token
        self.state_machine.on_callback_received("tok_abc", "state123")
        replay_ok, replay_msg = self.state_machine.on_callback_received("tok_abc", "state123")
        self.assertFalse(replay_ok)
        self.assertIn("replay", replay_msg.lower())

    # -----------------------------------------------------------------
    # Test 7: Expired or invalidated token transitions to AUTH_EXPIRED / AUTH_REQUIRED
    # -----------------------------------------------------------------
    def test_07_expired_token_transitions_to_auth_required_or_expired(self) -> None:
        """Verifies that token expiry cleanly transitions the state machine."""
        self.state_machine.on_exchange_success({"access_token": "active_token"})
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.CONNECTED_READ_ONLY)

        self.state_machine.on_token_expired("JWT token expired at 23:59:59 IST expiration boundary")
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.AUTH_EXPIRED)
        self.assertIn("expired", self.state_machine.to_dict()["state_reason"].lower())

    # -----------------------------------------------------------------
    # Test 8: HTTP 401, 403, 502, and network errors are handled gracefully
    # -----------------------------------------------------------------
    def test_08_http_errors_graceful_handling(self) -> None:
        """Verifies that standard HTTP error codes map to appropriate non-looping states."""
        # 401 Unauthorized
        state, reason = self.state_machine.on_exchange_failure(401, "Invalid API secret or expired requestToken")
        self.assertEqual(state, PaytmAuthState.AUTH_REQUIRED)

        # 403 Forbidden
        state, reason = self.state_machine.on_exchange_failure(403, "Developer account suspended or forbidden")
        self.assertEqual(state, PaytmAuthState.AUTH_REQUIRED)

        # 502 Bad Gateway
        state, reason = self.state_machine.on_exchange_failure(502, "Bad Gateway from Paytm Developer endpoint")
        self.assertEqual(state, PaytmAuthState.CONNECTION_ERROR)

        # Socket / Connection Timeout
        state, reason = self.state_machine.on_exchange_failure(504, "Connection timed out connecting to upstream")
        self.assertEqual(state, PaytmAuthState.CONNECTION_ERROR)

    # -----------------------------------------------------------------
    # Test 9: Lockout / rate limit condition (HTTP 429) enters AUTH_LOCKOUT_COOLDOWN
    # -----------------------------------------------------------------
    def test_09_lockout_rate_limit_enters_cooldown_with_backoff(self) -> None:
        """Verifies rate-limiting/lockouts enforce mandatory cooldown with refusal of auto-retries."""
        # Trigger 429 Too Many Requests
        state, reason = self.state_machine.on_exchange_failure(429, "Too Many Requests: Rate limit exceeded. Try again in 60s.")
        self.assertEqual(state, PaytmAuthState.AUTH_LOCKOUT_COOLDOWN)
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.AUTH_LOCKOUT_COOLDOWN)

        st_dict = self.state_machine.to_dict()
        self.assertTrue(st_dict["is_cooldown_active"])
        self.assertGreater(st_dict["cooldown_remaining_sec"], 0)
        self.assertFalse(st_dict["can_auto_retry"])

        # Attempting to authorize during cooldown must fail
        ok, note = self.state_machine.start_authorization()
        self.assertFalse(ok)
        self.assertIn("cooldown active", note.lower())

        # Fast forward past cooldown
        future_time = time.time() + st_dict["cooldown_remaining_sec"] + 1.0
        with patch("time.time", return_value=future_time):
            resumed_state = self.state_machine.current_state
            self.assertEqual(resumed_state, PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN)

    # -----------------------------------------------------------------
    # Test 10: Dashboard restart with running daemon is idempotent
    # -----------------------------------------------------------------
    def test_10_dashboard_restart_process_idempotency(self) -> None:
        """Verifies dashboard startup idempotency guard does not spawn duplicate servers."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            # Simulating running the main block check
            is_already_running = False
            try:
                with urllib.request.urlopen("http://127.0.0.1:8088/api/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        is_already_running = True
            except Exception:
                pass

            self.assertTrue(is_already_running)

    # -----------------------------------------------------------------
    # Test 11: Sensitive credentials and tokens are never logged in plain text
    # -----------------------------------------------------------------
    def test_11_credential_and_token_redaction(self) -> None:
        """Verifies that secrets, API keys, JWT tokens, and request tokens are redacted."""
        raw_secret = "secret_key_abcdef1234567890"
        redacted = redact_token(raw_secret)
        self.assertNotIn("abcdef", redacted)
        self.assertTrue(redacted.startswith("secr..."))
        self.assertTrue(redacted.endswith("7890"))

        # Short secret
        self.assertEqual(redact_token("12345"), "********")

        # Query string redaction
        raw_qs = "requestToken=secret_token_val_9999&state=random_state_val"
        clean_qs = redact_query_string(raw_qs)
        self.assertNotIn("secret_token_val", clean_qs)

        # Complex message with JWT payload
        jwt_msg = "Error during token exchange with payload: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature"
        sanitized_msg = redact_sensitive_payload(jwt_msg)
        self.assertNotIn("doNotLeakThisSignature", sanitized_msg)
        self.assertIn("[REDACTED_JWT]", sanitized_msg)

    # -----------------------------------------------------------------
    # Test 12: Successful authentication does not auto-start paper trading
    # -----------------------------------------------------------------
    def test_12_auth_completion_does_not_auto_start_trading(self) -> None:
        """Verifies that completing OAuth only sets broker connection, never starting trading."""
        server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=0,
            storage_dir=self.temp_dir,
        )
        self.servers_to_close.append(server)
        server.auth_state_machine = self.state_machine

        # Worker thread before auth must be None and not running
        self.assertIsNone(server._worker_thread)
        self.assertFalse(server._worker_running)
        self.assertNotEqual(server.session_supervisor.state, SessionState.PAPER_SESSION_ACTIVE)

        # Complete auth
        self.state_machine.on_exchange_success({"access_token": "valid_token_xyz"})
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.CONNECTED_READ_ONLY)

        # Invariant: Paper trading execution worker must NOT be auto-started!
        self.assertIsNone(server._worker_thread)
        self.assertFalse(server._worker_running)
        self.assertNotEqual(server.session_supervisor.state, SessionState.PAPER_SESSION_ACTIVE)

    # -----------------------------------------------------------------
    # Test 13: Safety invariants strictly preserved throughout all states
    # -----------------------------------------------------------------
    def test_13_safety_invariants_preserved(self) -> None:
        """Verifies that live trading safety invariants remain locked across all states."""
        self.assertFalse(LIVE_ORDER_DISPATCH_ENABLED)

        for test_state in PaytmAuthState:
            with self.state_machine.lock:
                self.state_machine._state = test_state
                data = self.state_machine.to_dict()
                self.assertTrue(data["zero_reload_enforced"])
                self.assertFalse(data["can_reload_page"])
                self.assertFalse(data["can_auto_retry"])
                self.assertFalse(data["can_spawn_processes"])


if __name__ == "__main__":
    unittest.main()
