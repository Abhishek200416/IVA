"""Phase 12.6A Financial Truth, Data Integrity & Execution-Safety Audit Test Suite.

Verifies:
1. Hard execution-safety invariants (STRICT PAPER ONLY, live dispatch blocked).
2. Authoritative epoch isolation (₹10k sandbox, ₹50k demo, ₹100k milestone).
3. Data provenance truthfulness (no false LIVE_OBSERVED flags when broker session inactive).
4. News intelligence source integrity (elimination of unverified DOM scrape claims).
5. Daemon safety boundaries (BROWSER_DOM_EXTRACTION_ENABLED is False).
6. Accounting identity reconciliations across all defined portfolio epochs.
"""

import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

from agents.AGI_1_7.finance.paytm_persistent_overlay_daemon import (
    BROWSER_DOM_EXTRACTION_ENABLED,
    main as daemon_main,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase126ATruthAndSafety(unittest.TestCase):
    """Authoritative test suite for Phase 12.6A verification criteria."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.storage_dir = Path(cls.temp_dir.name)
        cls.server_port = 8328
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
    # 1. HARD EXECUTION SAFETY INVARIANTS
    # =========================================================================

    def test_01_strict_paper_only_invariant(self):
        """Status endpoint strictly declares mode=PAPER and is_live_allowed=False."""
        status_code, body = self._http_get("/api/status")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        self.assertEqual(data.get("mode"), "PAPER")
        self.assertFalse(data.get("is_live_allowed"))

    def test_02_live_order_dispatch_blocked(self):
        """Attempt to access live order dispatch is rejected with 403 Forbidden."""
        status_code, body = self._http_post(
            "/api/live_order",
            {"instrument": "NIFTY", "action": "BUY", "quantity": 50},
        )
        self.assertEqual(status_code, HTTPStatus.FORBIDDEN)
        data = json.loads(body)
        err = data.get("error", "").upper()
        self.assertTrue(any(w in err for w in ["PROHIBITED", "REJECTED", "PAPER ONLY"]))

    def test_03_daemon_dom_extraction_disabled(self):
        """Daemon has BROWSER_DOM_EXTRACTION_ENABLED = False and main() exits safely."""
        self.assertFalse(BROWSER_DOM_EXTRACTION_ENABLED)
        # Calling daemon_main should return immediately without hanging or crashing
        daemon_main()

    # =========================================================================
    # 2. DATA PROVENANCE & TRUTHFULNESS
    # =========================================================================

    def test_04_provenance_truth_when_broker_session_retired(self):
        """Status does not falsely report LIVE_OBSERVED when broker session is retired."""
        status_code, body = self._http_get("/api/status")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        # Because Paytm session is retired awaiting rotation, data_provenance must be SYNTHETIC_FIXTURE
        self.assertEqual(data.get("data_provenance"), "SYNTHETIC_FIXTURE")

    def test_05_news_intel_source_truthfulness(self):
        """News intelligence documents have truthful sources without Port 9229 DOM claims."""
        status_code, body = self._http_get("/api/news_intel")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        docs = data.get("documents", [])
        self.assertGreater(len(docs), 0)
        for doc in docs:
            source = doc.get("source", "")
            self.assertNotIn("Port 9229 DOM", source)
            self.assertNotIn("Paytm Money Live DOM Stream", source)

    # =========================================================================
    # 3. AUTHORITATIVE EPOCH ISOLATION
    # =========================================================================

    def test_06_epoch_10k_sandbox_isolation(self):
        """Epoch 10k query returns active sandbox starting capital of 10000.0."""
        status_code, body = self._http_get("/api/live_portfolio?epoch=epoch_10k")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        cap_mgmt = data.get("capital_management", {})
        self.assertEqual(cap_mgmt.get("starting_capital_inr"), 10000.0)
        self.assertEqual(data.get("status"), "ACTIVE_EVALUATION")
        self.assertEqual(data.get("provenance"), "SIMULATED_PAPER_LEDGER")

    def test_07_epoch_50k_demo_isolation(self):
        """Epoch 50k query returns historical demo baseline with starting capital 50000.0."""
        status_code, body = self._http_get("/api/live_portfolio?epoch=epoch_50k")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        cap_mgmt = data.get("capital_management", {})
        self.assertEqual(cap_mgmt.get("starting_capital_inr"), 50000.0)
        self.assertEqual(data.get("status"), "ARCHIVED_BASELINE")
        self.assertEqual(data.get("provenance"), "HISTORICAL_DEMO_FIXTURE")

    def test_08_epoch_100k_milestone_isolation(self):
        """Epoch 100k query returns milestone fixture with starting capital 100000.0."""
        status_code, body = self._http_get("/api/live_portfolio?epoch=epoch_100k")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        cap_mgmt = data.get("capital_management", {})
        self.assertEqual(cap_mgmt.get("starting_capital_inr"), 100000.0)
        self.assertEqual(data.get("status"), "ARCHIVED_MILESTONE")
        self.assertEqual(data.get("provenance"), "HISTORICAL_MILESTONE_FIXTURE")

    def test_09_paper_positions_10k_returns_empty_active(self):
        """Paper positions query for epoch_10k returns 0 active positions for fresh sandbox."""
        status_code, body = self._http_get("/api/paper_positions?epoch=epoch_10k")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        positions = data.get("positions", [])
        self.assertEqual(len(positions), 0)
        self.assertEqual(data.get("total_exposure_inr"), 0.0)

    # =========================================================================
    # 4. ACCOUNTING RECONCILIATION INVARIANTS
    # =========================================================================

    def test_10_accounting_identity_formula(self):
        """Status endpoint accounting identity holds exactly."""
        status_code, body = self._http_get("/api/status")
        self.assertEqual(status_code, HTTPStatus.OK)
        data = json.loads(body)
        acct = data.get("accounting", {})
        starting = acct.get("starting_capital", 0.0)
        realized = acct.get("realized_net_pnl", 0.0)
        unrealized = acct.get("unrealized_net_pnl", 0.0)
        ending = acct.get("ending_equity", 0.0)
        self.assertAlmostEqual(ending, starting + realized + unrealized, places=2)
        self.assertTrue(acct.get("is_reconciled"))
        self.assertEqual(acct.get("reconciliation_status"), "RECONCILED")


if __name__ == "__main__":
    unittest.main()
