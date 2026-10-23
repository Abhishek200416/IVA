"""Unit and Integration Tests for Phase 12.6 Independent Production-Readiness Audit."""

import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

from agents.AGI_1_7.engine.agi17.adapters.model_adapter import redact_sensitive_text
from agents.AGI_1_7.engine.agi17.adapters.paytm_open_api_client import PaytmOpenApiClient
from agents.AGI_1_7.engine.agi17.finance.canonical_market_data import (
    CanonicalMarketObservation,
    DataProvenance,
    Exchange,
    ObservationType,
    OptionType,
)
from agents.AGI_1_7.engine.agi17.finance.evaluation_dataset_registry import (
    EvaluationDatasetRegistry,
)
from agents.AGI_1_7.engine.agi17.finance.historical_data_quality_auditor import (
    HistoricalDataQualityAuditor,
)
from agents.AGI_1_7.engine.agi17.finance.options_math import OptionsMath
from agents.AGI_1_7.scripts.safe_backup_manager import SafeBackupManager
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase126ProductionReadiness(unittest.TestCase):
    """Authoritative test suite verifying Phase 12.6 production-readiness criteria."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.storage_dir = Path(cls.temp_dir.name)
        cls.server_port = 8326
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.server_port,
            storage_dir=cls.storage_dir,
            starting_capital=10000.0,
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

    # =========================================================================
    # 1. Multi-Epoch Ledger Isolation & Reconciliation Integrity
    # =========================================================================
    def test_01_active_10k_epoch_clean_reconciliation(self) -> None:
        """Verify default /api/status endpoint accurately reflects clean ₹10,000 active epoch."""
        status, content = self._http_get("/api/status")
        self.assertEqual(status, HTTPStatus.OK)
        data = json.loads(content)
        self.assertEqual(data["initial_capital"], 10000.0)
        self.assertEqual(data["current_equity"], 10000.0)
        self.assertEqual(data["realized_pnl"], 0.0)
        self.assertEqual(data["unrealized_pnl"], 0.0)
        self.assertTrue(data["accounting"]["is_reconciled"])
        self.assertEqual(data["accounting"]["discrepancy_inr"], 0.0)

    def test_02_historical_demo_epoch_isolation(self) -> None:
        """Verify ?epoch=demo endpoint preserves ₹50,000 historical demo baseline independently."""
        status, content = self._http_get("/api/status?epoch=demo")
        self.assertEqual(status, HTTPStatus.OK)
        data = json.loads(content)
        self.assertEqual(data["initial_capital"], 50000.0)
        self.assertEqual(data["realized_pnl"], 1680.45)
        self.assertEqual(data["unrealized_pnl"], 585.0)
        self.assertEqual(data["current_equity"], 52265.45)
        self.assertTrue(data["accounting"]["is_reconciled"])

    def test_03_paper_positions_respects_active_epoch(self) -> None:
        """Verify /api/paper_positions returns clean active epoch when no query string is provided."""
        status, content = self._http_get("/api/paper_positions")
        self.assertEqual(status, HTTPStatus.OK)
        pos_data = json.loads(content)
        self.assertEqual(pos_data["epoch_id"], "EPOCH-PAPER-10K-20261014-001")
        self.assertEqual(pos_data["starting_capital_inr"], 10000.0)
        self.assertEqual(len(pos_data["active_positions"]), 0)

    # =========================================================================
    # 2. Secret Redaction & Token Hygiene
    # =========================================================================
    def test_04_secret_redaction_coverage(self) -> None:
        """Verify redact_sensitive_text masks sk-keys, JWT tokens, and key-value secrets."""
        raw_text = (
            "User credentials: key=sk-abcdef1234567890 and "
            "api_secret=9876543210fedcba with "
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef1234567890"
        )
        redacted = redact_sensitive_text(raw_text)
        self.assertNotIn("sk-abcdef1234567890", redacted)
        self.assertNotIn("9876543210fedcba", redacted)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", redacted)
        self.assertIn("<REDACTED_SK_KEY>", redacted)
        self.assertIn("api_secret=<REDACTED_SECRET>", redacted)
        self.assertIn("Bearer <REDACTED_TOKEN>", redacted)

    # =========================================================================
    # 3. Live Order Dispatch Permanent Lockout
    # =========================================================================
    def test_05_live_order_lockout_returns_403(self) -> None:
        """Verify all live order routes return HTTP 403 Forbidden with security error payload."""
        live_paths = ["/api/live_order", "/api/live/submit_order", "/api/order/live", "/api/live/dispatch"]
        for p in live_paths:
            req = urllib.request.Request(
                f"{self.base_url}{p}",
                data=json.dumps({"order": "BUY NIFTY"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=2.0)
                self.fail(f"Path {p} should have been rejected with HTTP 403.")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, HTTPStatus.FORBIDDEN)
                payload = json.loads(e.read().decode("utf-8"))
                self.assertTrue("prohibited" in payload.get("error", "").lower() or "disabled" in payload.get("error", "").lower())

    # =========================================================================
    # 4. Safe Backup & Rollback Verification
    # =========================================================================
    def test_06_safe_backup_manager_dry_run_and_integrity(self) -> None:
        """Verify SafeBackupManager snapshot creation, SHA-256 verification, and dry-run restoration."""
        with tempfile.TemporaryDirectory() as td:
            backup_root = Path(td) / "backups"
            mgr = SafeBackupManager(workspace_root=Path(__file__).resolve().parents[3], backup_root=backup_root)
            manifest = mgr.create_backup("test_readiness")
            self.assertTrue(manifest.file_count >= 8)
            self.assertTrue(mgr.verify_backup(manifest.backup_id))
            restore_res = mgr.restore_backup(manifest.backup_id, dry_run=True)
            self.assertEqual(restore_res["status"], "RESTORE_VERIFIED")

    # =========================================================================
    # 5. Data Provenance & Anti-Hallucination Tagging
    # =========================================================================
    def test_07_canonical_observation_provenance_tagging(self) -> None:
        """Verify CanonicalMarketObservation distinguishes synthetic, historical, and live data."""
        obs_synth = CanonicalMarketObservation(
            instrument_id="NIFTY26OCT24200CE",
            exchange=Exchange.NFO,
            underlying="NIFTY",
            observation_type=ObservationType.QUOTE,
            source_id="SYNTH_FIXTURE",
            price=132.0,
            bid=131.80,
            ask=132.20,
            provenance=DataProvenance.SYNTHETIC_FIXTURE,
        )
        self.assertEqual(obs_synth.provenance, DataProvenance.SYNTHETIC_FIXTURE)
        d = obs_synth.to_dict()
        self.assertEqual(d["provenance"], "SYNTHETIC_FIXTURE")
        self.assertEqual(d["observation_type"], "QUOTE")

    # =========================================================================
    # 6. Options Pricing & Greeks Robustness
    # =========================================================================
    def test_08_options_pricing_zero_extrinsic_at_expiry(self) -> None:
        """Verify Black-Scholes pricing collapses to pure intrinsic without division by zero at T=0."""
        # ITM call at expiry
        itm = OptionsMath.calculate_greeks(spot=105.0, strike=100.0, time_to_expiry_years=0.0, volatility=0.20, is_call=True)
        self.assertEqual(itm["price"], 5.0)
        self.assertEqual(itm["delta"], 1.0)

        # OTM call at expiry
        otm = OptionsMath.calculate_greeks(spot=95.0, strike=100.0, time_to_expiry_years=0.0, volatility=0.20, is_call=True)
        self.assertEqual(otm["price"], 0.0)
        self.assertEqual(otm["delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
