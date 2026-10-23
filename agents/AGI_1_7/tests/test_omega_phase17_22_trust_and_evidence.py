"""AGI 1.7 OMEGA COMMAND — Phase 17.22 Trust, Runtime Proof & Evidence Test Suite.

Authoritative verification of:
1. TaskStore Schema, Heartbeats & Staleness Detection (ORPHANED_DEAD / STALE_HEARTBEAT).
2. Verification Gating: Strict ban on unearned VERIFIED_PASS status.
3. Truthful Agent Telemetry: 100 specialists marked REGISTERED — EXECUTION NOT VERIFIED.
4. Algorithm Source Integrity: Dynamic import audit of all 11 algorithm source modules & entry points.
5. Permanent Live Order Dispatch Lock: GATE_01 fail-closed protection (HTTP 403).
6. Financial Ledger Separation: Independent accounting of epoch_10k (₹10,000, ₹0 P&L) vs epoch_100k.
7. Tri-Tab Market Pipeline Truth: Authentic after-hours reporting and provenance verification.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agents.AGI_1_7.engine.agi17.task_control.task_store import TaskStore
from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    AlgorithmCatalogService,
    AgentCatalogService,
    OrchestrationServiceProvider,
    get_algorithm_catalog,
    get_agent_catalog,
)
from agents.AGI_1_7.engine.agi17.finance.trading_supervisor import update_trailing_stops
from agents.AGI_1_7.engine.agi17.ml.volatility_transformer import VolatilityTransformerModel
from agents.AGI_1_7.engine.agi17.runtime.dual_index_pipeline import DualIndexEventPipeline


class TestOmegaPhase1722TrustAndEvidence(unittest.TestCase):
    """Phase 17.22 Trust, Proof and Grounded Truth Test Suite."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_tasks.db"
        self.task_store = TaskStore(db_path=self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. TaskStore Provenance & Schema Migration
    # -------------------------------------------------------------------------
    def test_01_task_store_provenance_and_schema(self):
        """Verify TaskStore schema stores provenance, last_heartbeat, and verification evidence."""
        now = time.time()
        task_id = self.task_store.create_task(
            job_id="JOB-AUDIT-01",
            specialist_id="qa_unit_suite_runner",
            input_data={"test": "sample"},
            provenance="REAL_DISPATCHED",
            worker_pid=999999,
            last_heartbeat=now,
        )
        task = self.task_store.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["provenance"], "REAL_DISPATCHED")
        self.assertEqual(task["worker_pid"], 999999)
        self.assertIsNotNone(task["last_heartbeat"])
        self.assertIn("execution_health", task)

    # -------------------------------------------------------------------------
    # 2. Task Heartbeat and Staleness Detection
    # -------------------------------------------------------------------------
    def test_02_task_heartbeat_and_staleness_audit(self):
        """Verify that stale tasks or dead worker PIDs are truthfully flagged."""
        # Create a task that started in RUNNING state with a non-existent PID
        task_id = self.task_store.create_task(
            job_id="JOB-STALE-01",
            specialist_id="swe_python_runtime_engineer",
            input_data={"code": "pass"},
            provenance="REAL_DISPATCHED",
            worker_pid=999998,
            initial_state="RUNNING",
        )

        # Manually backdate heartbeat
        old_time = time.time() - 300.0  # 5 minutes ago
        with self.task_store._connect() as conn:
            conn.execute(
                "UPDATE tasks SET last_heartbeat = ?, updated_at = ? WHERE task_id = ?",
                (old_time, old_time, task_id["task_id"]),
            )

        # Run audit
        stale_records = self.task_store.audit_stale_tasks(staleness_threshold_sec=30.0)
        self.assertGreaterEqual(len(stale_records), 1)
        found = next((r for r in stale_records if r["task_id"] == task_id["task_id"]), None)
        self.assertIsNotNone(found)
        self.assertIn(found["execution_health"], ("STALE_HEARTBEAT", "ORPHANED_DEAD"))

        # Test heartbeat refresh
        self.task_store.record_heartbeat(task_id, time.time())
        refreshed = self.task_store.get_task(task_id)
        self.assertFalse(refreshed["is_stale"])

    # -------------------------------------------------------------------------
    # 3. Verification Gating: Ban on Unearned VERIFIED_PASS
    # -------------------------------------------------------------------------
    def test_03_verification_status_gating(self):
        """Verify task cannot transition to VERIFIED_PASS without empirical evidence."""
        task_id = self.task_store.create_task(
            job_id="JOB-GATE-01",
            specialist_id="qa_regression_baseline_comparator",
            input_data={"suite": "regression"},
            provenance="REAL_DISPATCHED",
            initial_state="RUNNING",
        )
        # Transition to VERIFYING (mandatory before SUCCEEDED)
        self.task_store.transition_task(task_id, "VERIFYING")

        # Attempt 1: Transition to SUCCEEDED with verification_status="VERIFIED_PASS" without verification evidence
        self.task_store.transition_task(
            task_id,
            "SUCCEEDED",
            verification_status="VERIFIED_PASS",
            result_data={"claimed": "everything works"},
            verification_evidence=None,
        )
        unverified_task = self.task_store.get_task(task_id)
        # Must be downgraded to UNVERIFIED_RESULT because no empirical evidence exists
        self.assertEqual(unverified_task["verification_status"], "UNVERIFIED_RESULT")

        # Attempt 2: Task with concrete verification evidence
        task_id2 = self.task_store.create_task(
            job_id="JOB-GATE-02",
            specialist_id="qa_regression_baseline_comparator",
            input_data={"suite": "regression"},
            provenance="REAL_DISPATCHED",
            initial_state="RUNNING",
        )
        self.task_store.transition_task(task_id2, "VERIFYING")

        evidence = {
            "test_count": 10,
            "passed": True,
            "assertion_hash": "sha256:abc123def456",
            "verifier": "qa_unit_suite_runner",
        }
        self.task_store.transition_task(
            task_id2,
            "SUCCEEDED",
            verification_status="VERIFIED_PASS",
            result_data={"result": "all passed", "passed": True},
            verification_evidence=evidence,
        )
        verified_task = self.task_store.get_task(task_id2)
        self.assertEqual(verified_task["verification_status"], "VERIFIED_PASS")
        self.assertEqual(verified_task["verification_evidence"]["test_count"], 10)

    # -------------------------------------------------------------------------
    # 4. Truthful Agent Telemetry & Specialist Status
    # -------------------------------------------------------------------------
    def test_04_agent_truthful_telemetry_and_specialist_status(self):
        """Verify 100 specialists are marked REGISTERED — EXECUTION NOT VERIFIED."""
        ag_svc = AgentCatalogService()
        agents = ag_svc.list_agents()
        self.assertEqual(len(agents), 106)

        # 100 embedded factory specialists must be REGISTERED - EXECUTION NOT VERIFIED
        specialists = [a for a in agents if a["family"] not in ("Executive Command & Control", "Executive Quantitative Command", "Runtime Supervision & Daemons")]
        self.assertEqual(len(specialists), 100)
        for s in specialists:
            self.assertEqual(s["status"], "REGISTERED")
            self.assertEqual(s["validation_status"], "REGISTERED — EXECUTION NOT VERIFIED")

        # Summary metrics check
        metrics = ag_svc.get_summary_metrics()
        self.assertEqual(metrics["registered_roles_total"], 106)
        self.assertGreaterEqual(metrics["idle_or_standby_agents"], 100)
        self.assertIsInstance(metrics["actively_executing_agents"], int)

    # -------------------------------------------------------------------------
    # 5. Algorithm Source Integrity Audit
    # -------------------------------------------------------------------------
    def test_05_algorithm_catalog_source_integrity_audit(self):
        """Verify all 11 algorithms pass dynamic module import & entry point audit."""
        cat_svc = AlgorithmCatalogService()
        audit_rep = cat_svc.verify_algorithm_integrity()

        self.assertTrue(audit_rep["overall_integrity_pass"])
        self.assertEqual(audit_rep["total_algorithms"], 11)
        self.assertEqual(audit_rep["verified_algorithms_count"], 11)

        # Verify VolatilityTransformerModel is loaded
        transformer_res = audit_rep["results"]["ALG-DEEP-VOL-TRANSFORMER-V1"]
        self.assertTrue(transformer_res["verified"])
        self.assertEqual(transformer_res["entry_point"], "VolatilityTransformerModel")

        # Verify update_trailing_stops entry point is loaded
        psl_res = audit_rep["results"]["ALG-PARABOLIC-SL-V1"]
        self.assertTrue(psl_res["verified"])
        self.assertEqual(psl_res["entry_point"], "update_trailing_stops")

        # Verify fail-closed risk block on Naked ITM Short
        naked_res = audit_rep["results"]["ALG-NAKED-ITM-SHORT-V0"]
        self.assertTrue(naked_res["verified"])
        self.assertEqual(naked_res["status"], "PERMANENTLY_BLOCKED_BY_RISK")

    # -------------------------------------------------------------------------
    # 6. Trailing Stop Ratchet Algorithm Mathematical Verification
    # -------------------------------------------------------------------------
    def test_06_trailing_stop_ratchet_mechanics(self):
        """Verify ALG-PARABOLIC-SL-V1 ratchet calculation and breakeven locking."""
        # 1. Initial trade at 100, LTP advances to 105 (+5% -> not yet breakeven)
        res1 = update_trailing_stops({"entry_price": 100.0, "current_stop_loss": 82.0, "peak_price": 100.0}, 105.0)
        self.assertFalse(res1["breakeven_locked"])
        self.assertFalse(res1["is_breached"])
        # trailing sl = 105 * (1 - 0.12) = 92.4
        self.assertAlmostEqual(res1["updated_sl"], 92.4, places=1)

        # 2. LTP advances to 110 (+10% -> triggers +8% breakeven floor at 100)
        res2 = update_trailing_stops({"entry_price": 100.0, "current_stop_loss": 92.4, "peak_price": 105.0}, 110.0)
        self.assertTrue(res2["breakeven_locked"])
        # 110 * 0.88 = 96.8, but floor is 100 (breakeven locked)
        self.assertEqual(res2["updated_sl"], 100.0)
        self.assertEqual(res2["action"], "LOCK_PROFIT")

        # 3. LTP drops to 99 (breaches 100 stop loss)
        res3 = update_trailing_stops({"entry_price": 100.0, "current_stop_loss": 100.0, "peak_price": 110.0}, 99.0)
        self.assertTrue(res3["is_breached"])
        self.assertEqual(res3["action"], "EXIT_STOP_LOSS")

    # -------------------------------------------------------------------------
    # 7. Volatility Regime Transformer Model Verification
    # -------------------------------------------------------------------------
    def test_07_volatility_transformer_model_mechanics(self):
        """Verify ALG-DEEP-VOL-TRANSFORMER-V1 shadow-mode prediction."""
        model = VolatilityTransformerModel(seq_len=60, feature_dim=16, num_heads=4, hidden_dim=64)
        synthetic_input = [[0.1] * 16 for _ in range(60)]
        pred = model.predict_regime(synthetic_input)

        self.assertIn("regime_prediction", pred)
        self.assertIn("distribution", pred)
        self.assertEqual(len(pred["distribution"]), 4)
        self.assertTrue(pred["shadow_mode"])
        self.assertFalse(pred["order_dispatch_allowed"])

    # -------------------------------------------------------------------------
    # 8. Financial Ledger Separation (epoch_10k vs epoch_100k)
    # -------------------------------------------------------------------------
    def test_08_financial_ledger_separation(self):
        """Verify epoch_10k is starting capital ₹10,000 with ₹0 P&L and not conflated with epoch_100k."""
        # Query 8088 dashboard for epoch_10k
        req = urllib.request.Request("http://127.0.0.1:8088/api/live_portfolio?epoch=epoch_10k")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        self.assertEqual(data["epoch_id"], "EPOCH-PAPER-10K-20261014-001")
        cap = data["capital_management"]
        self.assertEqual(cap["starting_capital_inr"], 10000.0)
        self.assertEqual(cap["net_profit_loss_today_inr"], 0.0)
        self.assertEqual(cap["current_portfolio_equity_inr"], 10000.0)

    # -------------------------------------------------------------------------
    # 9. Permanent Fail-Closed Live Order Dispatch Lock
    # -------------------------------------------------------------------------
    def test_09_live_order_dispatch_locked_fail_closed(self):
        """Verify GATE_01 blocks all live order dispatch calls with HTTP 403 Forbidden."""
        req = urllib.request.Request(
            "http://127.0.0.1:8088/api/order/dispatch",
            data=json.dumps({"symbol": "NIFTY", "qty": 50}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 403)

    # -------------------------------------------------------------------------
    # 10. Tri-Tab Market Pipeline After-Hours Truth
    # -------------------------------------------------------------------------
    def test_10_market_pipeline_truth_and_after_hours(self):
        """Verify pipeline accurately recognizes after-hours market state and avoids fake live claims."""
        pipeline = DualIndexEventPipeline()
        snapshot = pipeline.get_central_snapshot()

        self.assertIn("market_session_active", snapshot)
        self.assertIn("data_provenance", snapshot)
        # When after hours, data_provenance must not claim AUTHENTIC_LIVE
        if snapshot.get("is_after_hours", False):
            self.assertNotEqual(snapshot["data_provenance"], "AUTHENTIC_LIVE")


if __name__ == "__main__":
    unittest.main()
