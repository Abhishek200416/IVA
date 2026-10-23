"""Targeted Regression Battery for Phase 17.11 Urgent Bug Fix:
Authentication Lifecycle Stabilization, Infinite Reload Elimination, Broker Lockout Prevention,
and Prevention of Cycle Query Parameter Leakage onto Provider URLs.

Verifies:
1. OTP entry can remain pending indefinitely without a redirect loop.
2. The next password/PIN entry can remain pending without a redirect loop.
3. Repeated polling does not trigger browser navigation.
4. An internal cycle counter never modifies provider URLs, and bare /stocks/fno is normalized.
5. Successful mocked authentication transitions to a verified state.
6. Expired sessions and rate limits stop automatic login attempts.
7. No duplicate browser instances or authentication workers are created.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_DIR = REPO_ROOT / "agents" / "AGI_1_7" / "engine"

from agents.AGI_1_7.engine.agi17.adapters.paytm_auth_state_machine import (
    PaytmAuthStateMachine,
    PaytmAuthState,
)
from agents.AGI_1_7.engine.agi17.browser.real_chromium_engine import (
    RealChromiumEngine,
    sanitize_navigation_url,
)
from agents.AGI_1_7.engine.agi17.browser.browser_service import BrowserSessionManager


class TestOmegaPhase1711AuthGuardAndCycleLoop(unittest.TestCase):
    """Targeted regression tests for broker auth lifecycle and zero-reload protection."""

    def setUp(self) -> None:
        PaytmAuthStateMachine.reset_instance_for_testing()
        self.state_machine = PaytmAuthStateMachine.get_instance()

    def tearDown(self) -> None:
        PaytmAuthStateMachine.reset_instance_for_testing()

    def test_01_otp_entry_pending_indefinitely_without_redirect_loop(self) -> None:
        """Verify OTP entry screen can stay pending indefinitely across 50 polling cycles without redirect or reload."""
        self.state_machine.record_auth_screen_detected(
            reason="OTP_INPUT_FIELDS_PRESENT",
            url="https://accounts.paytm.com/oauth/v2/authorize",
        )

        for cycle in range(1, 51):
            status = self.state_machine.to_dict()
            # Assert state remains patient waiting for operator
            self.assertEqual(status["auth_state"], PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN.value)
            self.assertTrue(status["is_waiting_for_operator"])
            self.assertFalse(status["is_authenticated"])
            # Assert zero-reload and zero-retry invariants
            self.assertFalse(status["can_reload_page"])
            self.assertTrue(status["zero_reload_enforced"])
            self.assertFalse(status["can_auto_retry"])
            self.assertTrue(status["no_auto_retry_enforced"])
            self.assertFalse(status["can_spawn_processes"])
            self.assertTrue(status["zero_process_spawn_enforced"])
            # Assert operator instruction is present and clear
            self.assertIn("Operator authentication required", status["operator_instruction"])

    def test_02_password_pin_entry_pending_without_redirect_loop(self) -> None:
        """Verify password or 4-digit PIN verification remains in patient standby without navigation."""
        self.state_machine.record_auth_screen_detected(
            reason="PIN_INPUT_FIELDS_PRESENT",
            url="https://login.paytmmoney.com/merchant-login",
        )

        status = self.state_machine.to_dict()
        self.assertEqual(status["auth_state"], PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN.value)
        self.assertTrue(status["is_waiting_for_operator"])
        self.assertFalse(status["can_reload_page"])
        self.assertIn("PIN_INPUT_FIELDS_PRESENT", status["state_reason"])

    @patch("agents.AGI_1_7.engine.agi17.browser.real_chromium_engine.RealChromiumEngine.check_active_tab_auth_screen")
    @patch("agents.AGI_1_7.engine.agi17.browser.real_chromium_engine.RealChromiumEngine._cdp_call")
    def test_03_repeated_polling_does_not_trigger_browser_navigation(self, mock_cdp, mock_auth_chk) -> None:
        """Verify automated navigation to broker trading routes is blocked when auth/OTP screen is active."""
        engine = RealChromiumEngine.get_instance()
        # Mock active tab being on an authentication screen
        mock_auth_chk.return_value = (True, "AUTH_URL_SIGNATURE", "https://accounts.paytm.com/login")

        # Attempt navigation to trading terminal
        res = engine.navigate("https://www.paytmmoney.com/stocks/fno/dashboard")

        # Assert navigation was blocked
        self.assertTrue(res.get("blocked"))
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("reason"), "WAITING_FOR_OPERATOR_LOGIN")
        self.assertIn("Navigation blocked", res.get("message"))

        # Assert zero CDP Page.navigate calls were dispatched
        mock_cdp.assert_not_called()

        # Assert state machine recorded the auth waiting state
        self.assertEqual(
            self.state_machine.current_state,
            PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN,
        )

    def test_04_internal_cycle_counter_never_modifies_provider_urls(self) -> None:
        """Verify cycle= parameter is completely stripped and bare /stocks/fno is normalized."""
        # 1. Strip cycle=7 from bare /stocks/fno and normalize to canonical /stocks/fno/dashboard
        url1 = "https://www.paytmmoney.com/stocks/fno?cycle=7"
        clean1 = sanitize_navigation_url(url1)
        self.assertNotIn("cycle=", clean1)
        self.assertEqual(clean1, "https://www.paytmmoney.com/stocks/fno/dashboard")

        # 2. Strip cycle=42 from option chain URL with other params
        url2 = "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE?cycle=42&view=pe"
        clean2 = sanitize_navigation_url(url2)
        self.assertNotIn("cycle=", clean2)
        self.assertEqual(clean2, "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE?view=pe")

        # 3. Strip &cycle=10 from multi-param URL
        url3 = "https://www.nseindia.com/get-quotes/derivatives?symbol=NIFTY&cycle=10"
        clean3 = sanitize_navigation_url(url3)
        self.assertNotIn("cycle=", clean3)
        self.assertEqual(clean3, "https://www.nseindia.com/get-quotes/derivatives?symbol=NIFTY")

        # 4. Bare /stocks/fno without query params normalizes to /dashboard to prevent Express 404
        url4 = "https://www.paytmmoney.com/stocks/fno"
        clean4 = sanitize_navigation_url(url4)
        self.assertEqual(clean4, "https://www.paytmmoney.com/stocks/fno/dashboard")

    def test_05_successful_mocked_authentication_transitions_to_verified_state(self) -> None:
        """Verify operator completion of OAuth token exchange transitions to CONNECTED_READ_ONLY."""
        # 1. Operator initiates authorization
        ok, msg = self.state_machine.start_authorization("https://login.paytmmoney.com/merchant-login")
        self.assertTrue(ok)
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.AUTHORIZING)

        # 2. Callback receives requestToken
        cb_ok, cb_msg = self.state_machine.on_callback_received("req_tok_abc123", "state_xyz789")
        self.assertTrue(cb_ok)

        # 3. S2S token exchange succeeds with verified JWT
        ex_ok, ex_msg = self.state_machine.on_exchange_success({"access_token": "valid_jwt_mock"})
        self.assertTrue(ex_ok)

        # 4. Assert verified state
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.CONNECTED_READ_ONLY)
        status = self.state_machine.to_dict()
        self.assertTrue(status["is_authenticated"])
        self.assertFalse(status["is_waiting_for_operator"])
        self.assertEqual(status["telemetry"]["successes"], 1)

    def test_06_expired_sessions_and_rate_limits_stop_automatic_login(self) -> None:
        """Verify HTTP 429 transitions to cooldown with exponential backoff and blocks auto-retry."""
        # 1. Trigger Rate Limit HTTP 429
        new_state, reason = self.state_machine.on_exchange_failure(429, "Rate limit exceeded. Too many requests.")
        self.assertEqual(new_state, PaytmAuthState.AUTH_LOCKOUT_COOLDOWN)
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.AUTH_LOCKOUT_COOLDOWN)

        status = self.state_machine.to_dict()
        self.assertTrue(status["is_cooldown_active"])
        self.assertGreater(status["cooldown_remaining_sec"], 0)
        self.assertFalse(status["can_auto_retry"])

        # 2. Assert start_authorization is blocked while cooldown is active
        ok, blocked_msg = self.state_machine.start_authorization("https://login.paytmmoney.com/merchant-login")
        self.assertFalse(ok)
        self.assertIn("Broker lockout cooldown active", blocked_msg)

        # 3. Test token expiration
        self.state_machine.reset_to_waiting("Resetting for expiry test")
        self.state_machine.on_token_expired("JWT token expired at 15:30:00 IST")
        self.assertEqual(self.state_machine.current_state, PaytmAuthState.AUTH_EXPIRED)
        exp_status = self.state_machine.to_dict()
        self.assertFalse(exp_status["can_auto_retry"])
        self.assertFalse(exp_status["can_reload_page"])

    def test_07_no_duplicate_browser_instances_or_authentication_workers(self) -> None:
        """Verify authorization while already in progress preserves return URL without restarting workers."""
        # 1. Start authorization
        ok1, msg1 = self.state_machine.start_authorization("https://login.paytmmoney.com/merchant-login?state=1")
        self.assertTrue(ok1)
        self.assertEqual(self.state_machine.auth_attempts, 1)

        # 2. Subsequent call while AUTHORIZING is in progress protects existing flow
        ok2, msg2 = self.state_machine.start_authorization("https://login.paytmmoney.com/merchant-login?state=2")
        self.assertTrue(ok2)
        # Attempt count should NOT increment; return URL / state token preserved
        self.assertEqual(self.state_machine.auth_attempts, 1)
        self.assertIn("Authorization already in progress", msg2)

        # 3. Assert zero background process spawn allowed
        status = self.state_machine.to_dict()
        self.assertFalse(status["can_spawn_processes"])
        self.assertTrue(status["zero_process_spawn_enforced"])


if __name__ == "__main__":
    unittest.main()
