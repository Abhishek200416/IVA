"""Hermetic Unit Test Suite for PaytmSingleTabAutomator with Mocked CDP.

Verifies:
1. Resolves active Paytm tab without spawning unmanaged windows or new tabs.
2. Does NOT prune login or authentication tabs during cleanup.
3. _check_auth_guard() blocks navigation and actions when on an Auth/OTP/PIN screen.
4. switch_view_same_tab() sanitizes cycle= parameters and normalizes bare /stocks/fno.
5. All required action methods exist and adhere to the single-tab contract.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
FINANCE_DIR = REPO_ROOT / "agents" / "AGI_1_7" / "finance"
if str(FINANCE_DIR) not in sys.path:
    sys.path.insert(0, str(FINANCE_DIR))

from paytm_single_tab_browser_automator import PaytmSingleTabAutomator


class TestPaytmSingleTabAutomator(unittest.TestCase):
    """Hermetic unit tests for single-tab browser automation."""

    @patch("urllib.request.urlopen")
    def test_01_resolve_active_tab_finds_paytm_tab(self, mock_urlopen) -> None:
        """Verify automator correctly picks an existing Paytm Money tab."""
        mock_tabs = [
            {
                "id": "tab-1",
                "type": "page",
                "title": "Google",
                "url": "https://www.google.com",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9229/devtools/page/tab-1",
            },
            {
                "id": "tab-2",
                "type": "page",
                "title": "Paytm Money Option Chain",
                "url": "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9229/devtools/page/tab-2",
            },
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_tabs).encode("utf-8")
        mock_urlopen.return_value = mock_resp

        automator = PaytmSingleTabAutomator()
        self.assertEqual(automator.tab_id, "tab-2")
        self.assertEqual(automator.ws_url, "ws://127.0.0.1:9229/devtools/page/tab-2")

    @patch("urllib.request.urlopen")
    def test_02_resolve_active_tab_does_not_prune_auth_tabs(self, mock_urlopen) -> None:
        """Verify automator never closes auth/login tabs (accounts.paytm.com or login.paytmmoney.com)."""
        mock_tabs = [
            {
                "id": "tab-auth",
                "type": "page",
                "title": "Sign In to Paytm",
                "url": "https://accounts.paytm.com/oauth/v2/authorize",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9229/devtools/page/tab-auth",
            },
            {
                "id": "tab-orphan-google",
                "type": "page",
                "title": "Google",
                "url": "https://www.google.com",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9229/devtools/page/tab-orphan",
            },
        ]
        close_calls = []

        def side_effect(req_or_url, *args, **kwargs):
            url_str = req_or_url.full_url if hasattr(req_or_url, "full_url") else str(req_or_url)
            if "/close/" in url_str:
                close_calls.append(url_str)
                m = MagicMock()
                m.read.return_value = b"Target is closing"
                return m
            m = MagicMock()
            m.read.return_value = json.dumps(mock_tabs).encode("utf-8")
            return m

        mock_urlopen.side_effect = side_effect

        automator = PaytmSingleTabAutomator()
        # Verify tab-auth was NOT closed
        for call_url in close_calls:
            self.assertNotIn("tab-auth", call_url, "CRITICAL: Auth tab was pruned!")

    @patch.object(PaytmSingleTabAutomator, "eval_js")
    @patch.object(PaytmSingleTabAutomator, "_resolve_active_tab")
    def test_03_check_auth_guard_blocks_when_on_otp_or_auth_screen(self, mock_resolve, mock_eval) -> None:
        """Verify auth guard stops execution and sets WAITING_FOR_OPERATOR_AUTH when OTP/PIN screen active."""
        automator = PaytmSingleTabAutomator(tab_id="tab-1")
        automator.ws_url = "ws://127.0.0.1:9229/dummy"

        # Simulate active OTP screen
        mock_eval.return_value = {
            "is_auth": True,
            "reason": "OTP_INPUT_FIELDS_PRESENT",
            "count": 6,
        }

        # 1. switch_view_same_tab must be blocked
        res_nav = automator.switch_view_same_tab("https://www.paytmmoney.com/stocks/fno/dashboard")
        self.assertEqual(res_nav["status"], "WAITING_FOR_OPERATOR_AUTH")
        self.assertFalse(res_nav["success"])
        self.assertIn("patient standby until Operator Abhi completes OTP login", res_nav["error"])

        # 2. toggle_scalper_mode must be blocked
        res_scalp = automator.toggle_scalper_mode()
        self.assertEqual(res_scalp["status"], "WAITING_FOR_OPERATOR_AUTH")

        # 3. click_buy must be blocked
        res_buy = automator.click_buy(qty=50)
        self.assertEqual(res_buy["status"], "WAITING_FOR_OPERATOR_AUTH")

    @patch("time.sleep", return_value=None)
    @patch("paytm_single_tab_browser_automator._cdp_ws_send_and_recv")
    @patch.object(PaytmSingleTabAutomator, "eval_js")
    @patch.object(PaytmSingleTabAutomator, "_resolve_active_tab")
    def test_04_switch_view_same_tab_sanitizes_cycle_and_bare_fno(self, mock_resolve, mock_eval, mock_cdp, mock_sleep) -> None:
        """Verify cycle= parameter is stripped and bare /stocks/fno is normalized to /dashboard."""
        automator = PaytmSingleTabAutomator(tab_id="tab-1")
        automator.ws_url = "ws://127.0.0.1:9229/dummy"

        # Simulate normal non-auth screen
        mock_eval.side_effect = [
            {"is_auth": False},  # for _check_auth_guard
            "https://www.paytmmoney.com/stocks/fno/dashboard",  # for current_url
        ]

        res = automator.switch_view_same_tab("https://www.paytmmoney.com/stocks/fno?cycle=7")
        self.assertEqual(res["status"], "SUCCESS")

        # Verify CDP Page.navigate was called with sanitized canonical URL (NO cycle=7, normalized to /dashboard)
        called_args = mock_cdp.call_args[0]
        cmds = called_args[1]
        nav_cmd = next((c for c in cmds if c.get("method") == "Page.navigate"), None)
        self.assertIsNotNone(nav_cmd)
        target_nav_url = nav_cmd["params"]["url"]
        self.assertNotIn("cycle=", target_nav_url)
        self.assertTrue(target_nav_url.endswith("/stocks/fno/dashboard"))

    def test_05_all_action_methods_exist(self) -> None:
        """Verify all contractually required single-tab automation methods are defined."""
        with patch.object(PaytmSingleTabAutomator, "_resolve_active_tab"):
            automator = PaytmSingleTabAutomator(tab_id="mock-tab")
            required_methods = [
                "switch_view_same_tab",
                "click_buy",
                "click_sell",
                "toggle_scalper_mode",
                "save_to_watchlist",
                "remove_scrip_from_watchlist",
                "sort_watchlist",
                "navigate_subtab",
                "square_off_all_positions",
                "modify_order",
                "cancel_order",
            ]
            for m in required_methods:
                self.assertTrue(hasattr(automator, m), f"Missing required method: {m}")


if __name__ == "__main__":
    unittest.main()
