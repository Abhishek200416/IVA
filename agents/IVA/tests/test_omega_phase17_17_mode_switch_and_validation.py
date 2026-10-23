"""Phase 17.17 Mode Switch, Live Data Validation & Production Readiness Test Suite.

Verifies:
1. Four Authoritative Operating Modes (BACKTEST, PAPER, LIVE_DATA_VALIDATION, LIVE_EXECUTION).
2. Safe Startup Recovery: Always defaults to PAPER mode and live execution disabled.
3. Live Execution Lockout: Transition to Mode D rejected fail-closed with 403 and missing prerequisites.
4. Valid Transitions between Backtest, Paper, and Live Data Validation.
5. Invalidation of Pending Approvals on any mode shift.
6. Emergency Stop & Disarm: Immediate reversion to PAPER mode, execution lock.
7. Real-Time Market Data Feed Diagnostic & Sanity Checks (stale data, spread inversion, volume).
8. Real-Time Account Reconciliation & Zero Discrepancy Gate.
9. Dual-Key Order Intent TTL (60s window) & Signature Validation.
10. Dashboard Server HTTP Endpoints Integration.
"""

from __future__ import annotations

import datetime
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict

from agents.AGI_1_7.engine.agi17.finance.operating_mode_service import (
    DataFeedProvenance,
    LiveReadinessStatus,
    OperatingMode,
    OperatingModeService,
    OrderApprovalIntent,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import (
    LIVE_ORDER_DISPATCH_ENABLED,
    StandaloneDashboardServer,
)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestOperatingModeServiceCore(unittest.TestCase):
    """Unit tests for the authoritative OperatingModeService."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        OperatingModeService.reset_instance_for_testing()
        self.svc = OperatingModeService(storage_dir=self.storage_dir)

    def tearDown(self) -> None:
        OperatingModeService.reset_instance_for_testing()
        self.temp_dir.cleanup()

    def test_01_mode_enumeration_and_safe_startup(self) -> None:
        """OperatingMode defines 4 authoritative modes and startup defaults safely to PAPER."""
        modes = [m.value for m in OperatingMode]
        self.assertEqual(len(modes), 4)
        self.assertIn("BACKTEST", modes)
        self.assertIn("PAPER", modes)
        self.assertIn("LIVE_DATA_VALIDATION", modes)
        self.assertIn("LIVE_EXECUTION", modes)

        # Invariant: startup defaults to PAPER with live execution disallowed
        status = self.svc.get_mode_status()
        self.assertEqual(status["current_mode"], "PAPER")
        self.assertFalse(status["live_execution_allowed"])
        self.assertFalse(status["emergency_stop_active"])
        self.assertIn("PAPER MODE ACTIVE", status["ui_status_badge"])

    def test_02_invalid_mode_request_rejected(self) -> None:
        """Requesting an undefined or unrecognized mode returns False and logs rejection."""
        ok, msg, status = self.svc.request_mode_change("SUPER_LIVE")
        self.assertFalse(ok)
        self.assertIn("Invalid mode", msg)
        self.assertEqual(status["current_mode"], "PAPER")

        # Check audit entry
        last_audit = self.svc.transition_history[-1]
        self.assertEqual(last_audit["action"], "MODE_CHANGE_REJECTED")
        self.assertFalse(last_audit["success"])

    def test_03_live_execution_lockout_enforced(self) -> None:
        """Attempting to switch to LIVE_EXECUTION fails closed because prerequisites are unmet."""
        readiness = self.svc.evaluate_live_readiness_checklist()
        self.assertFalse(readiness["is_all_passed"])
        # Default disconnected telemetry blocks 5 gates (4, 5, 6, 9, 11)
        self.assertIn(readiness["blocked_count"], (4, 5))
        self.assertEqual(readiness["overall_status"], LiveReadinessStatus.LOCKED_PREREQUISITES_UNMET.value)

        # Ingesting authentic live quote dynamically clears Gate 6
        self.svc.update_telemetry_quote("NIFTY 50", 22600.0, DataFeedProvenance.AUTHENTIC_LIVE)
        readiness_with_feed = self.svc.evaluate_live_readiness_checklist()
        self.assertEqual(readiness_with_feed["blocked_count"], 4)

        ok, msg, status = self.svc.request_mode_change("LIVE_EXECUTION")
        self.assertFalse(ok)
        self.assertIn("LIVE EXECUTION LOCKED", msg)
        self.assertIn("prerequisites blocked", msg)
        self.assertEqual(status["current_mode"], "PAPER")
        self.assertFalse(status["live_execution_allowed"])

    def test_04_valid_transitions_between_eligible_modes(self) -> None:
        """Operator can switch cleanly between BACKTEST, LIVE_DATA_VALIDATION, and PAPER."""
        # Switch to BACKTEST
        ok, msg, status = self.svc.request_mode_change("BACKTEST")
        self.assertTrue(ok)
        self.assertEqual(self.svc.current_mode, OperatingMode.BACKTEST)
        self.assertFalse(self.svc.live_execution_allowed)
        self.assertIn("BACKTEST MODE ACTIVE", status["ui_status_badge"])

        # Switch to LIVE_DATA_VALIDATION
        ok, msg, status = self.svc.request_mode_change("LIVE_DATA_VALIDATION")
        self.assertTrue(ok)
        self.assertEqual(self.svc.current_mode, OperatingMode.LIVE_DATA_VALIDATION)
        self.assertFalse(self.svc.live_execution_allowed)

        # Switch back to PAPER
        ok, msg, status = self.svc.request_mode_change("PAPER")
        self.assertTrue(ok)
        self.assertEqual(self.svc.current_mode, OperatingMode.PAPER)
        self.assertFalse(self.svc.live_execution_allowed)

    def test_05_approval_invalidation_on_mode_shift(self) -> None:
        """Switching away from a live or armed state invalidates pending order approvals."""
        # Simulate an order intent
        self.svc.current_mode = OperatingMode.LIVE_EXECUTION
        self.svc.live_execution_allowed = True

        ok, msg, intent = self.svc.propose_live_order({
            "symbol": "NIFTY26OCT22600CE",
            "side": "BUY",
            "quantity": 50,
            "price": 125.50,
            "stop_loss": 95.00,
        })
        self.assertTrue(ok)
        self.assertIsNotNone(intent)
        self.assertTrue(intent.is_valid)

        # Switch to PAPER mode
        ok, msg, status = self.svc.request_mode_change("PAPER")
        self.assertTrue(ok)
        self.assertEqual(self.svc.current_mode, OperatingMode.PAPER)
        self.assertFalse(self.svc.live_execution_allowed)

        # Confirm intent was invalidated
        reviews = self.svc.get_pending_reviews()
        self.assertEqual(len(reviews), 1)
        self.assertFalse(reviews[0]["is_valid"])
        self.assertEqual(reviews[0]["execution_status"], "INVALIDATED")

    def test_06_emergency_stop_tripping_and_blocking(self) -> None:
        """Emergency stop immediately returns to PAPER and prevents live escalation."""
        res = self.svc.trigger_emergency_stop("Operator hit kill switch")
        self.assertEqual(res["status"], "EMERGENCY_STOP_ACTIVE")
        self.assertEqual(self.svc.current_mode, OperatingMode.PAPER)
        self.assertTrue(self.svc.emergency_stop_active)
        self.assertFalse(self.svc.live_execution_allowed)

        # Attempt to escalate to LIVE_EXECUTION while emergency stop is active
        ok, msg, status = self.svc.request_mode_change("LIVE_EXECUTION")
        self.assertFalse(ok)
        self.assertIn("Emergency Stop is ACTIVE", msg)

    def test_07_disarm_live_execution(self) -> None:
        """Disarm resets live execution allowed and safely defaults to PAPER."""
        self.svc.live_execution_allowed = True
        res = self.svc.disarm_live_execution("Routine operator disarm")
        self.assertEqual(res["status"], "DISARMED_TO_PAPER")
        self.assertEqual(self.svc.current_mode, OperatingMode.PAPER)
        self.assertFalse(self.svc.live_execution_allowed)

    def test_08_live_data_feed_validation_sanity_checks(self) -> None:
        """Live market data feed validator identifies stale data, spread inversion, and volume errors."""
        # 1. Disconnected feed
        diag1 = self.svc.validate_live_data_feed()
        self.assertFalse(diag1["is_healthy"])
        self.assertIn("not currently connected", " ".join(diag1["rejection_reasons"]))

        # 2. Connected feed with valid quotes
        self.svc.update_telemetry_quote("NIFTY 50", 22600.0, DataFeedProvenance.AUTHENTIC_LIVE_FEED)
        sample_valid = [
            {"symbol": "NIFTY 50", "bid": 22598.0, "ask": 22602.0, "ltp": 22600.0, "day_high": 22700.0, "day_low": 22500.0, "volume": 1000000}
        ]
        conn_ok = {"authenticated_api_verified": True}
        diag2 = self.svc.validate_live_data_feed(conn_details=conn_ok, sample_quotes=sample_valid)
        self.assertTrue(diag2["integrity_checks_passed"])
        self.assertEqual(diag2["feed_health_score_pct"], 100.0)

        # 3. Spread inversion sanity check: bid > ask
        sample_inverted = [
            {"symbol": "NIFTY 50", "bid": 22610.0, "ask": 22590.0, "ltp": 22600.0, "day_high": 22700.0, "day_low": 22500.0, "volume": 1000}
        ]
        diag3 = self.svc.validate_live_data_feed(conn_details=conn_ok, sample_quotes=sample_inverted)
        self.assertFalse(diag3["integrity_checks_passed"])
        self.assertIn("Spread inverted", " ".join(diag3["rejection_reasons"]))

        # 4. Out of range LTP check
        sample_oor = [
            {"symbol": "NIFTY 50", "bid": 22598.0, "ask": 22602.0, "ltp": 23000.0, "day_high": 22700.0, "day_low": 22500.0, "volume": 1000}
        ]
        diag4 = self.svc.validate_live_data_feed(conn_details=conn_ok, sample_quotes=sample_oor)
        self.assertFalse(diag4["integrity_checks_passed"])
        self.assertIn("outside day range", " ".join(diag4["rejection_reasons"]))

    def test_09_account_reconciliation_gate(self) -> None:
        """Account reconciliation passes on ₹0.00 discrepancy and blocks on mismatch."""
        # 1. Matching ledger (₹10,000 equity)
        rec_ok = self.svc.reconcile_account(
            broker_data={"cash": 10000.0, "equity": 10000.0},
            ledger_id="epoch_10k",
            starting_capital=10000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )
        self.assertTrue(rec_ok["is_reconciled"])
        self.assertEqual(rec_ok["discrepancy_inr"], 0.0)
        self.assertTrue(rec_ok["can_escalate_mode"])

        # 2. Mismatched equity (₹10,000 internal vs ₹9,950 broker)
        rec_mismatch = self.svc.reconcile_account(
            broker_data={"cash": 9950.0, "equity": 9950.0},
            ledger_id="epoch_10k",
            starting_capital=10000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
        )
        self.assertFalse(rec_mismatch["is_reconciled"])
        self.assertEqual(rec_mismatch["discrepancy_inr"], 50.0)
        self.assertFalse(rec_mismatch["can_escalate_mode"])
        self.assertIn("exceeds ₹0.00 zero-tolerance threshold", rec_mismatch["blocking_reasons"][0])

    def test_10_order_approval_ttl_and_signature_gate(self) -> None:
        """Dual-key order approval enforces valid signature and expires after 60-second TTL."""
        self.svc.current_mode = OperatingMode.LIVE_EXECUTION
        self.svc.live_execution_allowed = True

        ok, msg, intent = self.svc.propose_live_order({
            "symbol": "NIFTY26OCT22600CE",
            "side": "BUY",
            "quantity": 50,
            "price": 120.0,
            "stop_loss": 90.0,
        })
        self.assertTrue(ok)
        self.assertIsNotNone(intent)

        # 1. Approval without signature fails
        ok_app, msg_app, _ = self.svc.approve_live_order(intent.intent_id, "")
        self.assertFalse(ok_app)
        self.assertIn("signature required", msg_app)

        # 2. Approval with short signature fails
        ok_app2, msg_app2, _ = self.svc.approve_live_order(intent.intent_id, "AB")
        self.assertFalse(ok_app2)

        # 3. Simulated expired TTL fails
        intent.expires_at_timestamp = time.time() - 10.0  # Force expired
        ok_app3, msg_app3, _ = self.svc.approve_live_order(intent.intent_id, "SIGN-ABHI-AUTHORIZED")
        self.assertFalse(ok_app3)
        self.assertIn("expired", msg_app3)
        self.assertEqual(intent.execution_status, "EXPIRED")


class TestDashboardServerOperatingModeEndpoints(unittest.TestCase):
    """Integration tests verifying HTTP endpoints on StandaloneDashboardServer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = find_free_port()
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.port,
            storage_dir=Path(cls.temp_dir.name) / "runtime_storage",
            starting_capital=10000.0,
            epoch_id="epoch_10k",
        )
        cls.server.start_background()

        # Wait for server ready
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass


    def _http_get(self, path: str) -> Tuple[int, Dict[str, Any]]:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            data = json.loads(e.read().decode("utf-8"))
            return e.code, data

    def _http_post(self, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        url = f"http://127.0.0.1:{self.port}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            data = json.loads(e.read().decode("utf-8"))
            return e.code, data

    def test_11_get_mode_status(self) -> None:
        """GET /api/mode/status returns 200 with current mode and readiness."""
        status_code, body = self._http_get("/api/mode/status")
        self.assertEqual(status_code, 200)
        self.assertIn("current_mode", body)
        self.assertEqual(body["current_mode"], "PAPER")
        self.assertFalse(body["live_execution_allowed"])
        self.assertIn("live_readiness", body)

    def test_12_get_mode_readiness(self) -> None:
        """GET /api/mode/readiness returns 200 with 12-item checklist."""
        status_code, body = self._http_get("/api/mode/readiness")
        self.assertEqual(status_code, 200)
        self.assertEqual(body["total_gates"], 12)
        self.assertIn(body["blocked_count"], (4, 5))
        self.assertFalse(body["is_all_passed"])
        self.assertEqual(body["overall_status"], "LOCKED_PREREQUISITES_UNMET")

    def test_13_get_live_data_validation(self) -> None:
        """GET /api/live_data/validation returns 200 diagnostic report."""
        status_code, body = self._http_get("/api/live_data/validation")
        self.assertEqual(status_code, 200)
        self.assertIn("provider", body)
        self.assertIn("feed_connection_status", body)
        self.assertIn("feed_health_score_pct", body)

    def test_14_post_mode_set_live_execution_rejected_403(self) -> None:
        """POST /api/mode/set with mode=LIVE_EXECUTION returns 403 Forbidden with exact missing requirements."""
        status_code, body = self._http_post("/api/mode/set", {"mode": "LIVE_EXECUTION"})
        self.assertEqual(status_code, 403)
        self.assertIn("error", body)
        self.assertIn("LIVE EXECUTION LOCKED", body["error"])
        self.assertIn("missing_requirements", body)
        self.assertGreaterEqual(len(body["missing_requirements"]), 4)

    def test_15_post_mode_set_valid_modes(self) -> None:
        """POST /api/mode/set with BACKTEST and PAPER succeeds."""
        # 1. Switch to BACKTEST
        status_code, body = self._http_post("/api/mode/set", {"mode": "BACKTEST"})
        self.assertEqual(status_code, 200)
        self.assertEqual(body["current_mode"], "BACKTEST")

        # 2. Switch back to PAPER
        status_code, body = self._http_post("/api/mode/set", {"mode": "PAPER"})
        self.assertEqual(status_code, 200)
        self.assertEqual(body["current_mode"], "PAPER")

    def test_16_post_mode_emergency_stop_and_reconcile(self) -> None:
        """POST /api/mode/emergency_stop and /api/account/reconcile operate correctly."""
        # Test account reconcile
        status_code, rec_body = self._http_post("/api/account/reconcile", {"ledger_id": "epoch_10k"})
        self.assertEqual(status_code, 200)
        self.assertTrue(rec_body["is_reconciled"])
        self.assertEqual(rec_body["discrepancy_inr"], 0.0)
        self.assertEqual(rec_body["paper_ledger_status"], "PAPER_LEDGER_RECONCILED")
        self.assertEqual(rec_body["broker_account_status"], "RECONCILIATION_UNAVAILABLE")

        # Test emergency stop
        status_code, stop_body = self._http_post("/api/mode/emergency_stop", {"reason": "Integration test stop"})
        self.assertEqual(status_code, 200)
        self.assertEqual(stop_body["status"], "EMERGENCY_STOP_ACTIVE")
        self.assertEqual(stop_body["current_mode"], "PAPER")

    def test_17_security_boundary_live_order_rejection(self) -> None:
        """Direct live order placement paths remain strictly 403 Forbidden fail-closed."""
        status_code, body = self._http_post("/api/orders", {"symbol": "NIFTY 50", "side": "BUY", "quantity": 50})
        self.assertEqual(status_code, 403)
        self.assertIn("LIVE trading is strictly prohibited", body["error"])
        self.assertEqual(body["mode"], "PAPER")
        self.assertEqual(body["execution_boundary"], "STRICTLY_GROUNDED_PAPER_ONLY")


if __name__ == "__main__":
    unittest.main()
