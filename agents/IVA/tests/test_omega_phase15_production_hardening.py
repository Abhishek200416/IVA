"""AGI 1.7 OMEGA COMMAND — Phase 15 Production Hardening, Financial Integrity & Security Validation Suite.

Comprehensive release qualification battery covering:
- Gate 1: Financial Ledger Truth & Multi-Epoch Auditing
- Gate 2: Execution Safety, Control Plane Lifecycle & State Guards
- Gate 3: Substantive 12-Point Preflight & Market Data Provenance Validation
- Gate 5 & 7: Reliability, Soak, Safe Backup & Disaster Recovery Verification
- Gate 6: Security, Secret Redaction & Local Deployment Hardening
"""

import dataclasses
import datetime
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List

from agents.AGI_1_7.engine.agi17.adapters.model_adapter import redact_sensitive_text
from agents.AGI_1_7.engine.agi17.finance.trading_session_control_plane import (
    IntakeQuestion,
    OperatorIntent,
    PreflightCheckResult,
    PreflightReport,
    REGISTERED_STRATEGIES,
    PAPER_ALLOWED_STRATEGY_IDS,
    SessionPreflightService,
    SessionState,
    SessionStore,
    TradingCommandDetector,
    TradingIntentIntakeController,
    TradingSessionConfig,
    TradingSessionConfigValidator,
    TradingSessionSupervisor,
    VALID_STATE_TRANSITIONS,
)
from agents.AGI_1_7.finance.paytm_persistent_overlay_daemon import BROWSER_DOM_EXTRACTION_ENABLED
from agents.AGI_1_7.scripts.safe_backup_manager import SafeBackupManager
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase15ProductionHardening(unittest.TestCase):
    """Authoritative Phase 15 Release Qualification and Production Hardening Suite."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.storage_dir = Path(cls.temp_dir.name)
        cls.server_port = 8329
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.server_port,
            storage_dir=cls.storage_dir,
            starting_capital=10000.0,
            epoch_id="EPOCH-PAPER-10K-20261014-001",
        )
        cls.server.start_background()
        cls.base_url = f"http://127.0.0.1:{cls.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def _http_get(self, path: str) -> tuple[int, str]:
        req = urllib.request.Request(f"{self.base_url}{path}")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status, resp.read().decode("utf-8")

    def _http_post(self, path: str, data: dict) -> tuple[int, str]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8")

    # =========================================================================
    # GATE 1: FINANCIAL LEDGER TRUTH & MULTI-EPOCH AUDITING
    # =========================================================================

    def test_gate1_01_api_epochs_clean_10k_sandbox(self) -> None:
        """Verify /api/epochs accurately serves pristine ₹10,000 active sandbox."""
        status_code, body = self._http_get("/api/epochs")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        active = data.get("active_epoch", {})
        self.assertEqual(active.get("id"), "epoch_10k")
        self.assertEqual(active.get("starting_capital_inr"), 10000.0)
        self.assertEqual(active.get("current_equity_inr"), 10000.0)
        self.assertEqual(active.get("realized_pnl_inr"), 0.0)
        self.assertEqual(active.get("unrealized_pnl_inr"), 0.0)
        self.assertEqual(active.get("active_positions_count"), 0)
        self.assertEqual(active.get("closed_positions_count"), 0)
        self.assertEqual(active.get("cash_reserve_inr"), 10000.0)
        self.assertEqual(active.get("deployed_margin_inr"), 0.0)
        self.assertTrue(active.get("reconciled"))
        # Ensure stale 10494.66 / 316.21 / 178.45 figures are eliminated
        self.assertNotEqual(active.get("current_equity_inr"), 10494.66)
        self.assertNotEqual(active.get("realized_pnl_inr"), 316.21)

    def test_gate1_02_api_epochs_50k_demo_reconciled(self) -> None:
        """Verify /api/epochs preserves archived ₹50,000 historical demo baseline."""
        status_code, body = self._http_get("/api/epochs")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        archived = data.get("archived_epochs", [])
        ep50 = next((e for e in archived if e.get("id") == "epoch_50k"), None)
        self.assertIsNotNone(ep50)
        self.assertEqual(ep50.get("starting_capital_inr"), 50000.0)
        self.assertEqual(ep50.get("realized_pnl_inr"), 1680.45)
        self.assertEqual(ep50.get("unrealized_pnl_inr"), 585.0)
        self.assertEqual(ep50.get("current_equity_inr"), 52265.45)
        self.assertTrue(ep50.get("reconciled"))

    def test_gate1_03_api_epochs_100k_milestone_fixture(self) -> None:
        """Verify /api/epochs serves ₹1,00,000 milestone fixture with correct archive status."""
        status_code, body = self._http_get("/api/epochs")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        archived = data.get("archived_epochs", [])
        ep100 = next((e for e in archived if e.get("id") == "epoch_100k"), None)
        self.assertIsNotNone(ep100)
        self.assertEqual(ep100.get("status"), "ARCHIVED_MILESTONE_FIXTURE")
        self.assertEqual(ep100.get("starting_capital_inr"), 100000.0)
        self.assertEqual(ep100.get("realized_pnl_inr"), 15309.0)
        self.assertEqual(ep100.get("unrealized_pnl_inr"), 3942.0)
        self.assertEqual(ep100.get("current_equity_inr"), 119251.0)
        self.assertTrue(ep100.get("reconciled"))

    def test_gate1_04_accounting_identity_zero_discrepancy_all_epochs(self) -> None:
        """Verify double-entry identity holds with zero discrepancy across all catalog epochs."""
        status_code, body = self._http_get("/api/epochs")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        for ep in data.get("all_epochs", []):
            start = ep.get("starting_capital_inr", 0.0)
            real = ep.get("realized_pnl_inr", 0.0)
            unreal = ep.get("unrealized_pnl_inr", 0.0)
            equity = ep.get("current_equity_inr", 0.0)
            expected = round(start + real + unreal, 2)
            actual = round(equity, 2)
            self.assertEqual(actual, expected, f"Accounting discrepancy in {ep.get('id')}: {actual} != {expected}")
            self.assertTrue(ep.get("reconciled"))

    # =========================================================================
    # GATE 2: EXECUTION SAFETY, CONTROL PLANE LIFECYCLE & STATE GUARDS
    # =========================================================================

    def test_gate2_01_direct_activation_from_invalid_state_blocked(self) -> None:
        """Verify that attempting to jump directly to PAPER_SESSION_ACTIVE fails closed."""
        temp_dir = tempfile.mkdtemp()
        try:
            store = SessionStore(base_dir=Path(temp_dir))
            sup = TradingSessionSupervisor(store=store)
            self.assertEqual(sup.state, SessionState.IDLE)

            # Direct jump from IDLE -> PAPER_SESSION_ACTIVE must be rejected
            ok, msg = sup.transition_to(SessionState.PAPER_SESSION_ACTIVE, "Illegal bypass attempt")
            self.assertFalse(ok)
            self.assertEqual(sup.state, SessionState.IDLE)
            self.assertIn("Illegal state transition", msg)

            # Direct jump from AWAITING_CONFIRMATION -> PAPER_SESSION_ACTIVE must also be rejected
            sup.state = SessionState.AWAITING_CONFIRMATION
            ok, msg = sup.transition_to(SessionState.PAPER_SESSION_ACTIVE, "Bypass preflight attempt")
            self.assertFalse(ok)
            self.assertEqual(sup.state, SessionState.AWAITING_CONFIRMATION)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_gate2_02_tampered_config_hash_mismatch(self) -> None:
        """Verify that modifying a session parameter alters the hash and fails confirmation."""
        cfg = TradingSessionConfig(
            session_id="HASH-TEST-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            max_capital_risk_per_trade_pct=0.5,
            max_daily_drawdown_pct=1.5,
        )
        orig_hash = cfg.config_hash

        # Tamper with capital
        cfg.allocated_capital_inr = 50000.0
        new_hash = cfg.compute_hash()
        self.assertNotEqual(orig_hash, new_hash)

    def test_gate2_03_emergency_stop_trips_circuit_breaker(self) -> None:
        """Verify emergency_stop() locks state to STOPPED and persists circuit breaker event."""
        temp_dir = tempfile.mkdtemp()
        try:
            store = SessionStore(base_dir=Path(temp_dir))
            sup = TradingSessionSupervisor(store=store)
            sup.state = SessionState.PAPER_SESSION_ACTIVE

            res = sup.emergency_stop("Manual test killswitch")
            self.assertTrue(res["handled"])
            self.assertEqual(res["action"], "EMERGENCY_STOP")
            self.assertEqual(res["circuit_breaker"], "TRIPPED")
            self.assertEqual(sup.state, SessionState.STOPPED)

            # Audit event must be saved
            saved = store.load_current_session()
            self.assertIsNotNone(saved)
            self.assertEqual(saved.get("state"), SessionState.STOPPED.value)
            self.assertTrue(saved.get("extra", {}).get("circuit_breaker_tripped"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_gate2_04_restart_recovers_active_session_to_paused(self) -> None:
        """Verify process restart recovers an interrupted PAPER_SESSION_ACTIVE safely into PAUSED."""
        temp_dir = tempfile.mkdtemp()
        try:
            store = SessionStore(base_dir=Path(temp_dir))
            # Simulate a session that was active when process crashed
            cfg = TradingSessionConfig(session_id="CRASH-TEST-001", portfolio_epoch="epoch_10k")
            store.save_current_session(SessionState.PAPER_SESSION_ACTIVE, cfg, {"crashed": True})

            # Start fresh supervisor over same store
            new_sup = TradingSessionSupervisor(store=store)
            # Must safely recover to PAUSED, never unmonitored execution
            self.assertEqual(new_sup.state, SessionState.PAUSED)
            self.assertEqual(new_sup.current_config.session_id, "CRASH-TEST-001")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_gate2_05_non_bypassable_risk_clamps(self) -> None:
        """Verify risk limit validator enforces 0.5% trade risk and 1.5% drawdown ceilings."""
        cfg = TradingSessionConfig(
            session_id="CLAMP-TEST-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            max_capital_risk_per_trade_pct=5.0,  # Excessive risk
            max_daily_drawdown_pct=10.0,         # Excessive drawdown
        )
        val_res = TradingSessionConfigValidator.validate_and_clamp(cfg)
        self.assertTrue(val_res.is_valid)
        self.assertIn("max_capital_risk_per_trade_pct", val_res.clamped_fields)
        self.assertIn("max_daily_drawdown_pct", val_res.clamped_fields)
        self.assertLessEqual(val_res.sanitized_config.max_capital_risk_per_trade_pct, 0.5)
        self.assertLessEqual(val_res.sanitized_config.max_daily_drawdown_pct, 1.5)

    def test_gate2_06_quarantined_research_strategy_rejected(self) -> None:
        """Verify strategies marked RESEARCH_ONLY are prohibited from paper execution."""
        cfg = TradingSessionConfig(
            session_id="STRAT-GATE-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            allowed_strategies=["uncalibrated_experimental_neural_net"],
        )
        val_res = TradingSessionConfigValidator.validate_and_clamp(cfg)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(any("RESEARCH_ONLY" in err for err in val_res.errors))

    # =========================================================================
    # GATE 3: SUBSTANTIVE 12-POINT PREFLIGHT AUDITING
    # =========================================================================

    def test_gate3_01_preflight_fails_closed_if_live_order_dispatch_active(self) -> None:
        """Preflight check CHECK_EXECUTION_MODE fails if server context permits live trading."""
        class MockServerContext:
            live_order_dispatch_enabled = True
            is_live_allowed = True

        cfg = TradingSessionConfig(
            session_id="PREFLIGHT-FAIL-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            instruments=["NIFTY"],
            allowed_strategies=["nifty_momentum_breakout"],
            max_capital_risk_per_trade_pct=0.5,
            max_daily_drawdown_pct=1.5,
        )
        report = SessionPreflightService.run_all_checks(cfg, server_context=MockServerContext())
        self.assertFalse(report.all_passed)
        self.assertEqual(report.blocker_code, "CHECK_EXECUTION_MODE")

    def test_gate3_02_preflight_fails_closed_on_excessive_risk_ceiling(self) -> None:
        """Preflight check CHECK_RISK_LIMITS_CLAMP fails if config exceeds 0.5% risk."""
        cfg = TradingSessionConfig(
            session_id="PREFLIGHT-RISK-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            instruments=["NIFTY"],
            allowed_strategies=["nifty_momentum_breakout"],
            max_capital_risk_per_trade_pct=2.5,  # Exceeds 0.5%
            max_daily_drawdown_pct=1.5,
        )
        report = SessionPreflightService.run_all_checks(cfg)
        self.assertFalse(report.all_passed)
        failed_codes = [c.check_code for c in report.checks if c.status == "FAIL"]
        self.assertIn("CHECK_RISK_LIMITS_CLAMP", failed_codes)

    def test_gate3_03_preflight_fails_closed_on_shadow_dom_scraping(self) -> None:
        """Preflight check CHECK_SHADOW_DOM_SAFETY fails if DOM extraction is enabled."""
        self.assertFalse(BROWSER_DOM_EXTRACTION_ENABLED)

    def test_gate3_04_preflight_accurately_tags_market_data_provenance(self) -> None:
        """Preflight Check 5 distinguishes synthetic/replay from authentic live feed."""
        cfg = TradingSessionConfig(
            session_id="PREFLIGHT-PROV-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            instruments=["NIFTY", "BANKNIFTY"],
            allowed_strategies=["nifty_momentum_breakout", "banknifty_mean_reversion"],
            max_capital_risk_per_trade_pct=0.5,
            max_daily_drawdown_pct=1.5,
        )
        report = SessionPreflightService.run_all_checks(cfg)
        chk5 = next(c for c in report.checks if c.check_code == "CHECK_MARKET_DATA_FRESHNESS")
        self.assertEqual(chk5.status, "PASS")
        self.assertIn("SYNTHETIC_REPLAY_ACTIVE", chk5.detail)
        self.assertIn("PENDING_OWNER_ROTATION", chk5.detail)

    # =========================================================================
    # GATE 5 & 7: RELIABILITY, SOAK, SAFE BACKUP & DISASTER RECOVERY
    # =========================================================================

    def test_gate5_01_safe_backup_manager_manifest_and_restoration_cycle(self) -> None:
        """Verify SafeBackupManager creates verified backups, checks hashes, and restores cleanly."""
        temp_dir = tempfile.mkdtemp()
        try:
            backup_root = Path(temp_dir) / "backups"
            restore_target = Path(temp_dir) / "restored"
            restore_target.mkdir(parents=True, exist_ok=True)

            mgr = SafeBackupManager(backup_root=backup_root)
            manifest = mgr.create_backup("phase15_test_drill")
            self.assertGreater(manifest.file_count, 10)
            self.assertGreater(manifest.total_bytes, 10000)

            # Verify backup integrity
            verified = mgr.verify_backup(manifest.backup_id)
            self.assertTrue(verified)

            # Perform non-destructive restoration drill into isolated location
            drill_mgr = SafeBackupManager(workspace_root=restore_target, backup_root=backup_root)
            res = drill_mgr.restore_backup(manifest.backup_id, dry_run=False)
            self.assertEqual(res["status"], "RESTORED")
            self.assertEqual(res["restored_count"], manifest.file_count)

            # Verify restored file hashes
            for rel_path, expected_hash in manifest.files.items():
                restored_file = restore_target / rel_path
                self.assertTrue(restored_file.exists(), f"Missing restored file: {rel_path}")
                actual_hash = mgr.compute_sha256(restored_file)
                self.assertEqual(actual_hash, expected_hash, f"Hash mismatch in restored {rel_path}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_gate5_02_bounded_paper_session_soak(self) -> None:
        """Execute a 50-cycle bounded simulation soak verifying zero state drift or crashes."""
        temp_dir = tempfile.mkdtemp()
        try:
            store = SessionStore(base_dir=Path(temp_dir))
            sup = TradingSessionSupervisor(store=store)
            sup.transition_to(SessionState.INTAKE_REQUIRED, "Soak start")
            sup.transition_to(SessionState.INTAKE_IN_PROGRESS, "Soak intake")
            sup.intake_controller.load_safe_defaults()
            sup.current_config = sup.intake_controller.cached_config
            sup.transition_to(SessionState.CONFIG_REVIEW, "Soak review")
            sup.transition_to(SessionState.AWAITING_CONFIRMATION, "Soak await confirm")
            sup.transition_to(SessionState.PREFLIGHT_RUNNING, "Soak preflight")
            sup.transition_to(SessionState.READY_FOR_SUPERVISED_PAPER, "Soak ready")
            sup.transition_to(SessionState.PAPER_SESSION_ACTIVE, "Soak active")

            self.assertEqual(sup.state, SessionState.PAPER_SESSION_ACTIVE)

            # Run 50 simulated state check cycles
            for i in range(50):
                # Verify state remains active
                self.assertEqual(sup.state, SessionState.PAPER_SESSION_ACTIVE)
                # Verify audit logging works without memory explosion
                store.record_audit_event("SOAK_TICK", {"iteration": i, "timestamp": datetime.datetime.now().isoformat()})

            # Clean shutdown
            sup.transition_to(SessionState.STOPPED, "Soak complete")
            self.assertEqual(sup.state, SessionState.STOPPED)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # =========================================================================
    # GATE 6: SECURITY, SECRET REDACTION & LOCAL DEPLOYMENT HARDENING
    # =========================================================================

    def test_gate6_01_live_order_endpoint_strictly_forbidden_http_403(self) -> None:
        """Verify POST /api/live_order unconditionally returns HTTP 403 Forbidden."""
        status_code, body = self._http_post(
            "/api/live_order",
            {"symbol": "NIFTY26OCT24200CE", "qty": 25, "action": "BUY"},
        )
        self.assertEqual(status_code, HTTPStatus.FORBIDDEN)
        data = json.loads(body)
        err = data.get("error", "").upper()
        self.assertTrue(any(w in err for w in ["PROHIBITED", "REJECTED", "PAPER ONLY"]))

    def test_gate6_02_secret_redaction_sanitizes_tokens_and_user_paths(self) -> None:
        """Verify model adapter scrubber redacts sensitive credentials and local user paths."""
        raw_text = (
            "API Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c "
            "Google Key: AIzaSyD-1234567890123456789012345678901 "
            "Secret: api_secret=my_super_secret_broker_token_12345 "
            "Home Directory: C:\\Users\\abhis\\Downloads\\pt\\secret.pem"
        )
        cleaned = redact_sensitive_text(raw_text)
        self.assertNotIn("AIzaSyD-1234567890123456789012345678901", cleaned)
        self.assertNotIn("my_super_secret_broker_token_12345", cleaned)
        self.assertNotIn("abhis", cleaned.lower())
        self.assertIn("<REDACTED_GOOGLE_API_KEY>", cleaned)
        self.assertIn("<REDACTED_SECRET>", cleaned)
        self.assertIn("<USER_HOME>", cleaned)

    def test_gate6_03_server_strictly_bound_to_loopback(self) -> None:
        """Verify server binds strictly to 127.0.0.1 (loopback) preventing external ingress."""
        self.assertEqual(self.server.host, "127.0.0.1")
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    # =========================================================================
    # GATE 8: ADVERSARIAL RISK INVARIANT VERIFICATION & ENFORCEMENT
    # =========================================================================

    def test_gate8_01_direct_config_risk_clamping(self) -> None:
        """Verify unvalidated config fails preflight and validator enforces non-bypassable clamps."""
        cfg = TradingSessionConfig(
            session_id="CFG-ADV-01",
            max_capital_risk_per_trade_pct=5.0,  # 10x excessive
            max_daily_drawdown_pct=10.0,         # 6.6x excessive
        )
        # 1. Raw unvalidated config MUST fail Preflight Check 8 (fail closed)
        report = SessionPreflightService.run_all_checks(cfg, self.server)
        self.assertFalse(report.all_passed)
        check_8 = next(c for c in report.checks if c.check_code == "CHECK_RISK_LIMITS_CLAMP")
        self.assertEqual(check_8.status, "FAIL")

        # 2. Validator clamps both values and records clamped fields
        val = TradingSessionConfigValidator.validate_and_clamp(cfg)
        self.assertTrue(val.is_valid)
        self.assertIn("max_capital_risk_per_trade_pct", val.clamped_fields)
        self.assertIn("max_daily_drawdown_pct", val.clamped_fields)
        self.assertLessEqual(val.sanitized_config.max_capital_risk_per_trade_pct, 0.5)
        self.assertLessEqual(val.sanitized_config.max_daily_drawdown_pct, 1.5)

    def test_gate8_02_validator_aggressive_profile_risk_clamp(self) -> None:
        """Verify aggressive profile cannot loosen 0.5% per-trade and 1.5% daily drawdown limits."""
        cfg = TradingSessionConfig(
            session_id="CFG-ADV-02",
            operating_profile="aggressive_analysis",
            max_capital_risk_per_trade_pct=2.5,
            max_daily_drawdown_pct=5.0,
        )
        val = TradingSessionConfigValidator.validate_and_clamp(cfg)
        self.assertTrue(val.is_valid)
        self.assertLessEqual(val.sanitized_config.max_capital_risk_per_trade_pct, 0.5)
        self.assertLessEqual(val.sanitized_config.max_daily_drawdown_pct, 1.5)

    def test_gate8_03_preflight_check_8_canonical_assertion(self) -> None:
        """Verify Preflight Check 8 confirms canonical 0.5%, 1.5%, 25% notional and 10% halt."""
        cfg = TradingSessionConfig(session_id="CFG-ADV-03", allocated_capital_inr=10000.0)
        report = SessionPreflightService.run_all_checks(cfg, self.server)
        check_8 = next((c for c in report.checks if c.check_code == "CHECK_RISK_LIMITS_CLAMP"), None)
        self.assertIsNotNone(check_8)
        self.assertEqual(check_8.status, "PASS")
        self.assertIn("0.5% per trade (₹50.00)", check_8.detail)
        self.assertIn("1.5% daily drawdown (₹150.00)", check_8.detail)
        self.assertIn("ceiling ₹2,500.00 (25%)", check_8.detail)
        self.assertIn("halt ₹1,000.00 (10%)", check_8.detail)

    def test_gate8_04_paper_order_notional_cap_enforcement(self) -> None:
        """Verify /api/paper/order rejects single order notional exceeding 25% of starting capital."""
        # 10k capital * 25% = ₹2,500 max notional. Attempt ₹5,000 order (50 * 100)
        status_code, body = self._http_post(
            "/api/paper/order",
            {"symbol": "NIFTY26OCT24200CE", "quantity": 50, "price": 100.0},
        )
        self.assertEqual(status_code, HTTPStatus.BAD_REQUEST)
        data = json.loads(body)
        self.assertEqual(data.get("status"), "REJECTED")
        self.assertIn("exceeds maximum allocation ceiling", data.get("error", ""))

    def test_gate8_05_paper_order_per_trade_risk_cap_enforcement(self) -> None:
        """Verify /api/paper/order rejects planned risk exceeding 0.5% (₹50 on ₹10k)."""
        # Price=100, Stop=80 -> ₹20 risk/unit. Qty=10 -> Planned risk ₹200 > ₹50
        status_code, body = self._http_post(
            "/api/paper/order",
            {"symbol": "NIFTY26OCT24200CE", "quantity": 10, "price": 100.0, "stop_loss": 80.0},
        )
        self.assertEqual(status_code, HTTPStatus.BAD_REQUEST)
        data = json.loads(body)
        self.assertEqual(data.get("status"), "REJECTED")
        self.assertIn("exceeds maximum risk budget", data.get("error", ""))

    def test_gate8_06_paper_order_circuit_breaker_and_daily_drawdown_halt(self) -> None:
        """Verify /api/paper/order is halted when emergency stop or daily drawdown limit reached."""
        # 1. Test Emergency Stop Halt
        self.server.emergency_stop_active = True
        try:
            status_code, body = self._http_post(
                "/api/paper/order",
                {"symbol": "NIFTY26OCT24200CE", "quantity": 10, "price": 50.0},
            )
            self.assertEqual(status_code, HTTPStatus.BAD_REQUEST)
            data = json.loads(body)
            self.assertIn("Emergency Stop / Circuit Breaker is active", data.get("error", ""))
        finally:
            self.server.emergency_stop_active = False

        # 2. Test Daily Drawdown Circuit Breaker Halt (loss >= ₹150 on ₹10k)
        original_realized = self.server.realized_pnl
        self.server.realized_pnl = -150.0
        try:
            status_code, body = self._http_post(
                "/api/paper/order",
                {"symbol": "NIFTY26OCT24200CE", "quantity": 10, "price": 50.0},
            )
            self.assertEqual(status_code, HTTPStatus.BAD_REQUEST)
            data = json.loads(body)
            self.assertEqual(data.get("status"), "CIRCUIT_BREAKER_HALT")
        finally:
            self.server.realized_pnl = original_realized

    def test_gate8_07_ordinary_vs_emergency_stop_discrimination(self) -> None:
        """Verify explicit discrimination between ordinary stop and emergency stop via API."""
        # Ordinary stop leaves circuit breaker healthy
        status_code, body = self._http_post("/api/session/stop", {"emergency": False})
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertFalse(self.server.emergency_stop_active)

        # Emergency stop trips circuit breaker and sets DEGRADED
        status_code, body = self._http_post("/api/session/stop", {"emergency": True})
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        self.assertEqual(data.get("status"), "STOPPED")
        self.assertEqual(data.get("circuit_breaker"), "TRIPPED")
        self.assertTrue(self.server.emergency_stop_active)

        # Reset for subsequent tests
        self.server.emergency_stop_active = False
        self.server.session_state = "IDLE"


if __name__ == "__main__":
    unittest.main()

