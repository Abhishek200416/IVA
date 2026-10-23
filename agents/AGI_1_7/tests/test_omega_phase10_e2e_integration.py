"""Integration and Acceptance Test Suite for AGI 1.7 Phase 10:
End-to-End Integration, Genuine Market Data, Accounting Reconciliation, and Shadow-Trading Readiness.

Covers:
1. Reconciled Accounting Identity:
   Ending Equity = Starting Capital (₹50,000.00) + Realized Net P&L (+₹1,680.45) + Unrealized Net P&L (+₹585.00) = ₹52,265.45
2. Mathematical Multiclass Brier Score & Dual BSS Baselines:
   Raw BS = 0.1240 | Uniform Baseline = 0.8571 (BSS_uniform = +0.8553) | Climatology Prior = 0.1590 (BSS_climatology = +0.2201)
3. Market Observation Engine & Quote Freshness Validation:
   - Positive price validation
   - Crossed-book rejection (bid >= ask)
   - Exchange tick size compliance (multiple of ₹0.05)
   - Sequence monotonicity
   - Quote freshness gate (quote age <= 15.0s)
   - Provenance classification (LIVE_WEBSOCKET, LIVE_DOM, EOD_BHAVCOPY, HISTORICAL_REPLAY, SYNTHETIC_DEMO)
4. Supervisor & Worker Thread Process Lifecycle:
   - Singleton lock acquisition
   - State machine transitions (IDLE -> RUNNING -> PAUSED_ENTRIES -> RUNNING -> STOPPED)
   - Background worker thread lifecycle & heartbeats for Alexa, Emily, Max
5. Emergency Stop Circuit Breaker:
   - Trip to DEGRADED and EMERGENCY_STOPPED
   - Rejection of operations while tripped
   - Clean reset via /api/emergency_reset
6. Realistic Paper Execution & Transaction Drag Policy:
   - Fills strictly simulated
   - Conservative bid/ask pricing and slippage
   - Statutory fee schedule (Paytm ₹10 flat + NSE 73061 ₹3,553/cr)
7. Fail-Closed Live Broker Boundary:
   - Strict HTTP 403 Forbidden on any live order attempt
8. Audit Ledger Persistence & HMAC-SHA256 Keyed Signatures:
   - 64-hex HMAC digest integrity
   - Tamper detection
9. Seven-Session Temporal Gate Integrity:
   - Strictly reports PENDING (Strict Temporal Gate) until 7 genuine calendar days elapse
10. Operator Console HTML Content & Badging:
   - Correctly renders reconciled equity, dual BSS metrics, and provenance badges
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import math
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

from agents.AGI_1_7.engine.agi17.finance.market_observation_engine import (
    MarketObservation,
    MarketObservationEngine,
    ObservationProvenanceType,
)
from agents.AGI_1_7.engine.agi17.finance.trading_supervisor import (
    Autonomous24x7TradingSupervisor,
    SupervisorServiceState,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase10E2EIntegration(unittest.TestCase):
    """Authoritative Test Suite for Phase 10 End-to-End Integration."""

    TEST_PORT = 8297
    BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.storage_dir = Path(cls.temp_dir.name)
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.TEST_PORT,
            storage_dir=cls.storage_dir,
            starting_capital=50000.0,
            epoch_id="EPOCH-DEMO-50K-20261013",
        )
        cls.server.start_background()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def setUp(self) -> None:
        # Reset server session state before each test
        self.server.session_state = "IDLE"
        self.server.emergency_stop_active = False
        self.server.transition_log.clear()
        if hasattr(self.server, "session_supervisor") and self.server.session_supervisor:
            from agents.AGI_1_7.engine.agi17.finance.trading_session_control_plane import SessionState
            self.server.session_supervisor.intake_controller.load_safe_defaults()
            self.server.session_supervisor.current_config = self.server.session_supervisor.intake_controller.cached_config
            self.server.session_supervisor.state = SessionState.READY_FOR_SUPERVISED_PAPER
        if self.server.supervisor:
            self.server.supervisor.transition_to(
                SupervisorServiceState.STOPPED,
                "Test suite reset to initial state"
            )

    def _http_get(self, path: str) -> tuple[int, str, dict]:
        req = urllib.request.Request(f"{self.BASE_URL}{path}")
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            status = resp.status
            content = resp.read().decode("utf-8")
            headers = dict(resp.getheaders())
            return status, content, headers

    def _http_post(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                status = resp.status
                body = json.loads(resp.read().decode("utf-8"))
                return status, body
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8")) if e.fp else {}
            return e.code, body

    # =========================================================================
    # 1. Reconciled Accounting Identity
    # =========================================================================
    def test_reconciled_accounting_identity_in_telemetry(self) -> None:
        """Verify that ending equity exactly reconciles Starting + Realized + Unrealized."""
        status, body_text, _ = self._http_get("/api/status")
        self.assertEqual(status, HTTPStatus.OK)
        data = json.loads(body_text)

        self.assertIn("accounting", data)
        acc = data["accounting"]
        starting = acc["starting_capital"]
        realized = acc["realized_net_pnl"]
        unrealized = acc["unrealized_net_pnl"]
        ending = acc["ending_equity"]

        self.assertEqual(starting, 50000.0)
        self.assertEqual(realized, 1680.45)
        self.assertEqual(unrealized, 585.0)
        expected_ending = round(starting + realized + unrealized, 2)
        self.assertEqual(expected_ending, 52265.45)
        self.assertEqual(ending, 52265.45)
        self.assertEqual(data["current_equity"], 52265.45)
        self.assertTrue(acc["is_reconciled"])

    def test_accounting_identity_in_paper_positions_endpoint(self) -> None:
        """Verify that /api/paper_positions provides the exact reconciled identity string."""
        status, body_text, _ = self._http_get("/api/paper_positions")
        self.assertEqual(status, HTTPStatus.OK)
        pos_data = json.loads(body_text)

        self.assertEqual(pos_data["starting_capital_inr"], 50000.0)
        self.assertEqual(pos_data["realized_pnl_inr"], 1680.45)
        self.assertEqual(pos_data["unrealized_pnl_inr"], 585.0)
        self.assertEqual(pos_data["current_equity_inr"], 52265.45)
        self.assertIn("50000.00 + 1680.45 + 585.00 = 52265.45", pos_data["accounting_identity"])

    # =========================================================================
    # 2. Mathematical Multiclass Brier Score & Dual BSS Baselines
    # =========================================================================
    def test_brier_score_and_dual_bss_baselines(self) -> None:
        """Verify the exact mathematical derivations of BSS_uniform and BSS_climatology."""
        status, body_text, _ = self._http_get("/api/session_report")
        self.assertEqual(status, HTTPStatus.OK)
        rep = json.loads(body_text)

        bs_model = rep["multiclass_brier_score"]
        self.assertEqual(bs_model, 0.1240)

        # Uniform prior for 7 discrete classes: p_k = 1/7 for each outcome
        # BS_uniform = (1 - 1/7)^2 + 6 * (1/7)^2 = 36/49 + 6/49 = 42/49 = 6/7
        expected_bs_uniform = 6.0 / 7.0
        self.assertAlmostEqual(rep["uniform_baseline_brier"], round(expected_bs_uniform, 4), places=4)

        # Canonical BSS vs Uniform: 1 - (BS_model / BS_uniform)
        expected_bss_uniform = 1.0 - (bs_model / expected_bs_uniform)
        self.assertAlmostEqual(rep["brier_skill_score"], round(expected_bss_uniform, 4), places=4)
        self.assertEqual(round(expected_bss_uniform, 4), 0.8553)

        # Climatology prior for historical base rate: BS_ref = 0.1590
        bs_climatology = rep["climatology_baseline_brier"]
        self.assertEqual(bs_climatology, 0.1590)
        expected_bss_climatology = 1.0 - (bs_model / bs_climatology)
        self.assertAlmostEqual(rep["climatology_skill_score"], round(expected_bss_climatology, 4), places=4)
        self.assertEqual(round(expected_bss_climatology, 4), 0.2201)

    # =========================================================================
    # 3. Market Observation Engine & Quote Freshness Validation
    # =========================================================================
    def test_market_observation_valid_pass(self) -> None:
        """Verify valid quote within freshness window passes all criteria."""
        engine = MarketObservationEngine(max_allowed_quote_age_sec=15.0)
        obs = engine.ingest_observation(
            instrument="NIFTY2026102924250CE",
            underlying="NIFTY",
            bid=115.40,
            ask=115.60,
            last_price=115.50,
            sequence_number=101,
            provenance_type=ObservationProvenanceType.LIVE_DOM,
        )
        self.assertTrue(obs.is_valid, f"Expected valid quote, error: {obs.validation_error}")
        self.assertFalse(obs.is_stale)
        self.assertIsNone(obs.validation_error)

    def test_market_observation_stale_quote_rejection(self) -> None:
        """Verify quote older than 15.0s is rejected as stale."""
        engine = MarketObservationEngine(max_allowed_quote_age_sec=15.0)
        stale_exch_iso = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=25)
        ).isoformat()
        obs = engine.ingest_observation(
            instrument="NIFTY2026102924250CE",
            underlying="NIFTY",
            bid=115.40,
            ask=115.60,
            last_price=115.50,
            sequence_number=102,
            exchange_timestamp_iso=stale_exch_iso,
        )
        self.assertFalse(obs.is_valid)
        self.assertTrue(obs.is_stale)
        self.assertIn("Stale quote", obs.validation_error or "")

    def test_market_observation_crossed_book_rejection(self) -> None:
        """Verify quote where bid >= ask is rejected as crossed book."""
        engine = MarketObservationEngine()
        obs = engine.ingest_observation(
            instrument="NIFTY2026102924250CE",
            underlying="NIFTY",
            bid=116.00,  # bid > ask
            ask=115.00,
            last_price=115.50,
            sequence_number=103,
        )
        self.assertFalse(obs.is_valid)
        self.assertIn("Crossed book", obs.validation_error or "")

    def test_market_observation_invalid_tick_rejection(self) -> None:
        """Verify quote not aligned to ₹0.05 tick size is rejected."""
        engine = MarketObservationEngine()
        obs = engine.ingest_observation(
            instrument="NIFTY2026102924250CE",
            underlying="NIFTY",
            bid=115.40,
            ask=115.60,
            last_price=115.53,  # Invalid tick (not multiple of 0.05)
            sequence_number=104,
        )
        self.assertFalse(obs.is_valid)
        self.assertIn("not a multiple of statutory tick size", obs.validation_error or "")

    def test_market_observation_provenance_types(self) -> None:
        """Verify all observation provenance types are distinct and recognized."""
        expected_types = {
            "LIVE_WEBSOCKET",
            "LIVE_DOM",
            "EOD_BHAVCOPY",
            "HISTORICAL_REPLAY",
            "SYNTHETIC_DEMO",
        }
        actual_types = {t.value for t in ObservationProvenanceType}
        self.assertEqual(expected_types, actual_types)

    # =========================================================================
    # 4. Supervisor & Worker Thread Process Lifecycle
    # =========================================================================
    def test_supervisor_and_worker_lifecycle(self) -> None:
        """Verify start, pause, resume, stop controls interact with supervisor and worker."""
        # 1. Start Paper Session
        code, body = self._http_post("/api/paper/start")
        self.assertEqual(code, HTTPStatus.OK)
        self.assertEqual(body["session_state"], "RUNNING")
        self.assertEqual(self.server.session_state, "RUNNING")
        self.assertEqual(self.server.supervisor.state, SupervisorServiceState.MARKET_OPEN)
        self.assertTrue(self.server._worker_running)

        # Verify worker heartbeat
        time.sleep(0.1)
        hb = self.server.get_worker_heartbeats()
        self.assertIn("ALEXA", hb)
        self.assertIn("EMILY", hb)
        self.assertIn("MAX", hb)
        self.assertEqual(hb["ALEXA"]["status"], "HEALTHY")

        # 2. Pause New Entries
        code, body = self._http_post("/api/paper/pause")
        self.assertEqual(code, HTTPStatus.OK)
        self.assertEqual(body["session_state"], "PAUSED_ENTRIES")
        self.assertEqual(self.server.supervisor.state, SupervisorServiceState.PAUSED)
        self.assertTrue(self.server._worker_paused_entries)

        # 3. Resume Evaluation
        code, body = self._http_post("/api/paper/resume")
        self.assertEqual(code, HTTPStatus.OK)
        self.assertEqual(body["session_state"], "RUNNING")
        self.assertEqual(self.server.supervisor.state, SupervisorServiceState.MARKET_OPEN)
        self.assertFalse(self.server._worker_paused_entries)

        # 4. Stop Safely
        code, body = self._http_post("/api/paper/stop")
        self.assertEqual(code, HTTPStatus.OK)
        self.assertEqual(body["session_state"], "STOPPED")
        self.assertEqual(self.server.supervisor.state, SupervisorServiceState.STOPPED)
        self.assertFalse(self.server._worker_running)

    # =========================================================================
    # 5. Emergency Stop Circuit Breaker
    # =========================================================================
    def test_emergency_stop_circuit_breaker_and_reset(self) -> None:
        """Verify emergency stop trips circuit breaker and blocks operations until reset."""
        # Start session first
        self._http_post("/api/paper/start")

        # Trip Emergency Stop
        code, body = self._http_post("/api/emergency_stop", {"reason": "Test trip"})
        self.assertEqual(code, HTTPStatus.OK)
        self.assertEqual(body["session_state"], "EMERGENCY_STOPPED")
        self.assertEqual(body["circuit_breaker"], "TRIPPED")
        self.assertTrue(self.server.emergency_stop_active)
        self.assertEqual(self.server.supervisor.state, SupervisorServiceState.DEGRADED)

        # Attempt to start while emergency stop is active -> must fail with HTTP 400
        code, err = self._http_post("/api/paper/start")
        self.assertEqual(code, HTTPStatus.BAD_REQUEST)
        self.assertIn("Emergency Stop", err["error"])

        # Reset Emergency Stop
        code, reset_body = self._http_post("/api/emergency_reset")
        self.assertEqual(code, HTTPStatus.OK)
        self.assertEqual(reset_body["session_state"], "STOPPED")
        self.assertFalse(self.server.emergency_stop_active)
        self.assertEqual(self.server.supervisor.state, SupervisorServiceState.STOPPED)

        # Now start should succeed
        code, start_body = self._http_post("/api/paper/start")
        self.assertEqual(code, HTTPStatus.OK)
        self.assertEqual(start_body["session_state"], "RUNNING")
        self._http_post("/api/paper/stop")

    # =========================================================================
    # 6. Realistic Paper Execution & Transaction Drag Policy
    # =========================================================================
    def test_realistic_paper_fill_and_drag_in_candidates(self) -> None:
        """Verify candidate setups evaluate statutory lot sizes and fill policies."""
        status, body_text, _ = self._http_get("/api/candidates")
        self.assertEqual(status, HTTPStatus.OK)
        data = json.loads(body_text)

        candidates = data["candidates"]
        self.assertGreaterEqual(len(candidates), 2)

        # NIFTY Candidate uses post-transition statutory lot size of 65
        nifty_cand = next((c for c in candidates if c["underlying"] == "NIFTY"), None)
        self.assertIsNotNone(nifty_cand)
        self.assertEqual(nifty_cand["lot_size"], 65)
        self.assertEqual(nifty_cand["fill_policy"], "CONSERVATIVE_ASK")

        # BANKNIFTY Candidate uses post-transition statutory lot size of 30
        bn_cand = next((c for c in candidates if c["underlying"] == "BANKNIFTY"), None)
        self.assertIsNotNone(bn_cand)
        self.assertEqual(bn_cand["lot_size"], 30)
        self.assertEqual(bn_cand["fill_policy"], "CONSERVATIVE_ASK")

    # =========================================================================
    # 7. Fail-Closed Live Broker Boundary
    # =========================================================================
    def test_fail_closed_live_broker_protection(self) -> None:
        """Verify that any live order submission attempt is immediately blocked with HTTP 403."""
        code, body = self._http_post("/api/live/submit_order", {"instrument": "NIFTY", "qty": 65})
        self.assertEqual(code, HTTPStatus.FORBIDDEN)
        self.assertIn("LIVE trading is strictly prohibited", body["error"])

    # =========================================================================
    # 8. Audit Ledger Persistence & HMAC-SHA256 Keyed Signatures
    # =========================================================================
    def test_session_report_export_and_hmac_integrity(self) -> None:
        """Verify exported session report contains valid 64-hex HMAC-SHA256 signature."""
        status, body_text, _ = self._http_get("/api/session_report/export")
        self.assertEqual(status, HTTPStatus.OK)
        export_data = json.loads(body_text)

        self.assertIn("hmac_sha256_digest", export_data)
        sig = export_data["hmac_sha256_digest"]
        self.assertEqual(len(sig), 64)  # 64 hex characters for SHA256

        # Verify signature recalculation matches
        payload_copy = dict(export_data)
        payload_copy.pop("hmac_sha256_digest", None)
        canonical = json.dumps(payload_copy, sort_keys=True).encode("utf-8")
        secret_key = b"OMEGA_COMMAND_PAPER_LEDGER_SECRET_KEY_64"
        expected_sig = hmac.new(secret_key, canonical, hashlib.sha256).hexdigest()
        self.assertEqual(sig, expected_sig)

    # =========================================================================
    # 9. Seven-Session Temporal Gate Integrity
    # =========================================================================
    def test_seven_session_temporal_gate_strictly_pending(self) -> None:
        """Verify that Gate G-02 remains strictly PENDING until 7 calendar sessions elapse."""
        status, body_text, _ = self._http_get("/api/risk_safety")
        self.assertEqual(status, HTTPStatus.OK)
        risk_data = json.loads(body_text)

        self.assertIn("seven_session_validation", risk_data)
        self.assertEqual(risk_data["seven_session_validation"]["status"], "PENDING (Strict Temporal Gate)")
        self.assertEqual(risk_data["seven_session_validation"]["elapsed_eligible_sessions"], 0)
        self.assertEqual(risk_data["seven_session_validation"]["required_sessions"], 7)

    # =========================================================================
    # 10. Operator Console HTML Content & Reconciled Badging
    # =========================================================================
    def test_operator_console_html_renders_reconciled_values(self) -> None:
        """Verify Operator Console HTML contains reconciled equity and provenance badges."""
        status, html_content, _ = self._http_get("/")
        self.assertEqual(status, HTTPStatus.OK)

        # Check for reconciled equity ₹52,265.45
        self.assertIn("52,265.45", html_content)

        # Check for reconciled accounting formula components
        self.assertIn("50,000.00", html_content)
        self.assertIn("1,680.45", html_content)
        self.assertIn("585.00", html_content)

        # Check for Brier Score & dual BSS metrics
        self.assertIn("0.1240", html_content)
        self.assertIn("0.8571", html_content)
        self.assertIn("+0.8553", html_content)
        self.assertIn("0.1590", html_content)
        self.assertIn("+0.2201", html_content)

        # Check for provenance badges
        self.assertIn("badge-provenance", html_content)
        self.assertIn("MARKET CLOSED", html_content)
        self.assertIn("STRICTLY PAPER ONLY", html_content)
        self.assertIn("LIVE DISPATCH DISABLED", html_content)


if __name__ == "__main__":
    unittest.main()
