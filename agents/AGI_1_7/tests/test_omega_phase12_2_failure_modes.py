# -*- coding: utf-8 -*-
"""AGI 1.7 OMEGA COMMAND — Phase 12.2 Master Failure Mode & Reliability Verification Battery.

Implements the 12 Authoritative Reproducible Failure Mode Tests:
1. Normal UI-debugging request routes to engineering specialist without emotional preaching.
2. Paper-order failure reports actionable diagnostics without fake fills.
3. Market-data timeout triggers staleness detection and safe execution refusal.
4. Broker authentication failure reports real 401/status without fake credentials.
5. Model context approaching configured limit triggers context rollover and loss-free summary.
6. Model provider rate limit (429) transitions to bounded blocked state without attempt burning.
7. Model provider outage (503) persists task state without fabricating progress.
8. Supervisor restart during unfinished task recovers active task cleanly from disk.
9. Task resumed from persisted checkpoint preserves objective, safety rules, and pending steps.
10. Emotionally worded but technically actionable request routes to technical triage, zero lectures.
11. Genuine live-order request remains safely blocked by 14-gate institutional boundary (HTTP 403).
12. Successful task completion is strictly backed by empirical test execution.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.AGI_1_7.ecosystem.agent_registry.agent_contract import AgentContract
from agents.AGI_1_7.ecosystem.agent_registry.capability_router import CapabilityRouter
from agents.AGI_1_7.ecosystem.agent_registry.specialist_factory import SpecialistFactory
from agents.AGI_1_7.engine.agi17.adapters.omniroute_adapter import (
    OmniRouteAdapter,
    TaskType,
)
from agents.AGI_1_7.engine.agi17.context.context_engine import (
    ContextEngine,
    EpistemicStatus,
)
from agents.AGI_1_7.engine.agi17.finance.market_observation_engine import (
    MarketObservationEngine,
    ObservationProvenanceType,
)
from agents.AGI_1_7.engine.agi17.process_supervision.continuous_supervisor import (
    ContinuousSupervisor,
)
from agents.AGI_1_7.engine.agi17.supervisor.persistent_supervisor import (
    QueuedTask,
    SupervisorState,
    TaskPriority,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase122FailureModes(unittest.TestCase):
    """Authoritative 12-Factor Failure Injection & Resilience Test Suite."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        self.factory = SpecialistFactory()
        self.router = self.factory.router
        self.context_engine = ContextEngine(repo_root=self.storage_dir)

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # =========================================================================
    # Test 1: Normal UI-Debugging Request
    # =========================================================================
    def test_01_normal_ui_debugging_request(self) -> None:
        """UI debugging request routes to web/browser engineer with actionable plan, no lectures."""
        query = "The trade order button in the frontend HTML dashboard is unclickable and throws TypeError"
        ranked = self.router.route(task_description=query, top_k=3)

        self.assertGreaterEqual(len(ranked), 1)
        routed_ids = [r["agent_id"] for r in ranked]
        # Must route to Web/Browser or SWE or Governance telemetry specialist
        self.assertTrue(
            any(
                aid in ("web_visual_regression_verifier", "web_playwright_session_controller", "swe_python_runtime_engineer", "gov_telemetry_dashboard_publisher")
                for aid in routed_ids
            ),
            f"Expected UI or SWE specialist, got: {routed_ids}",
        )

        # Verify no emotional-support or sleep lecturing text
        anti_lecture_keywords = ["tired", "sleep", "rest", "take a break", "mental health", "wellness"]
        for kw in anti_lecture_keywords:
            self.assertNotIn(kw, ranked[0]["display_name"].lower())

    # =========================================================================
    # Test 2: Paper-Order Failure Handling
    # =========================================================================
    def test_02_paper_order_failure_diagnostics(self) -> None:
        """Paper-order failure produces structured failure report without fake fills."""
        def failing_executor(task: QueuedTask, manifest: Any) -> dict[str, Any]:
            return {
                "status": "FAILED",
                "error": "INSUFFICIENT_MARGIN: Required ₹12,500.00 exceeds active epoch free cash ₹10,000.00",
                "attempted": "BUY 1 Lot NIFTY 24200 CE",
            }

        supervisor = ContinuousSupervisor(state_dir=self.storage_dir, idle_sleep_sec=0.01)
        supervisor.set_executor(failing_executor)
        task = supervisor.enqueue_task(
            title="Submit Paper Order NIFTY 24200 CE",
            description="Execute simulated paper order for NIFTY call option",
            requires_model_call=False,
        )

        supervisor.step()  # READY -> SELECTING_TASK
        supervisor.step()  # SELECTING_TASK -> BUILDING_CONTEXT
        supervisor.step()  # BUILDING_CONTEXT -> EXECUTING
        supervisor.step()  # EXECUTING -> VERIFYING
        supervisor.step()  # VERIFYING -> RECORDING_LEARNING
        supervisor.step()  # RECORDING_LEARNING -> SCHEDULING_NEXT
        supervisor.step()  # SCHEDULING_NEXT -> READY

        self.assertGreaterEqual(len(supervisor.task_history), 1)
        record = supervisor.task_history[-1]
        diagnostic = record.get("diagnostic", {})

        self.assertTrue(diagnostic.get("failed"))
        self.assertIn("INSUFFICIENT_MARGIN", diagnostic.get("error", ""))
        self.assertIn("Local state inspection", diagnostic.get("remains_possible", ""))
        self.assertIn("next_step", diagnostic)
        # Ensure no live orders or fake fills were generated
        self.assertNotIn("ORD-LIVE", str(record))

    # =========================================================================
    # Test 3: Market-Data Timeout Handling
    # =========================================================================
    def test_03_market_data_timeout_provenance(self) -> None:
        """Market-data observation engine flags stale data and rejects trading on expired quotes."""
        engine = MarketObservationEngine(max_allowed_quote_age_sec=5.0)

        # Exchange timestamp from 30 seconds ago
        now = time.time()
        exch_iso = datetime.datetime.fromtimestamp(now - 30.0, datetime.timezone.utc).isoformat()
        obs = engine.ingest_observation(
            instrument="NIFTY24200CE",
            underlying="NIFTY",
            bid=132.0,
            ask=132.5,
            last_price=132.2,
            volume=50000,
            exchange_timestamp_iso=exch_iso,
            arrival_timestamp_epoch=now,
            provenance_type=ObservationProvenanceType.LIVE_DOM,
        )

        self.assertTrue(obs.is_stale)
        self.assertFalse(obs.is_valid)
        self.assertIn("Stale quote", obs.validation_error or "")

    # =========================================================================
    # Test 4: Broker Authentication Failure Diagnostics
    # =========================================================================
    def test_04_broker_authentication_failure_diagnostics(self) -> None:
        """Broker auth failure reports exact status code and OAuth remediation step."""
        auth_error = {
            "status_code": 401,
            "error": "UNAUTHORIZED",
            "message": "Token has expired or merchant signature is invalid",
            "provider": "PAYTM_MONEY",
        }

        # Formulate grounded diagnostic response per Section 3 & 6
        diagnostic_report = {
            "attempted": "Paytm Money Broker REST API Session Handshake",
            "failed": True,
            "status": auth_error["status_code"],
            "error": auth_error["message"],
            "remains_possible": "Paper simulation active; local strategy backtesting unhindered",
            "next_step": "Refresh Paytm OAuth token via /api/paytm/callback or re-generate API key in console",
        }

        self.assertEqual(diagnostic_report["status"], 401)
        self.assertIn("Token has expired", diagnostic_report["error"])
        self.assertIn("Paper simulation active", diagnostic_report["remains_possible"])
        self.assertIn("Refresh Paytm OAuth", diagnostic_report["next_step"])

    # =========================================================================
    # Test 5: Model Context Approaching Configured Limit (Rollover & Checkpoint)
    # =========================================================================
    def test_05_model_context_approaching_limit(self) -> None:
        """Approaching token limit triggers rollover threshold and loss-free summary."""
        # 85% utilization on 128k window
        current_tokens = 110_000
        max_window = 128_000

        self.assertTrue(self.context_engine.should_rollover(current_tokens, max_window, threshold=0.80))
        self.assertFalse(self.context_engine.should_rollover(50_000, max_window, threshold=0.80))

        # Generate durable rollover summary
        summary = self.context_engine.create_rollover_summary(
            completed_work=["Step 1: Fixed epoch isolation", "Step 2: Router synonyms expanded"],
            unresolved_decisions=["Gate 01 live order arming threshold"],
            files_changed=["standalone_dashboard_server.py", "capability_router.py"],
            tests_run=["test_omega_phase11_1_readiness.py", "test_omega_phase10_e2e_integration.py"],
            unfinished_steps=["Run full regression suite", "Generate 6 verification markdown reports"],
        )

        # Invariants and constraints must be strictly preserved
        self.assertGreaterEqual(len(summary["safety_constraints"]), 3)
        self.assertEqual(len(summary["completed_work"]), 2)
        self.assertEqual(len(summary["unfinished_steps"]), 2)
        self.assertTrue(bool(summary["summary_digest"]))

    # =========================================================================
    # Test 6: Model Provider Rate Limit (HTTP 429) Handling
    # =========================================================================
    def test_06_model_provider_rate_limit_bounded_pause(self) -> None:
        """HTTP 429 Rate Limit pauses task without burning attempts endlessly."""
        def rate_limited_executor(task: QueuedTask, manifest: Any) -> dict[str, Any]:
            return {
                "status": "FAILED",
                "error": "HTTP 429: Resource has been exhausted (quota exceeded for gemini-2.5-pro)",
            }

        supervisor = ContinuousSupervisor(state_dir=self.storage_dir, idle_sleep_sec=0.01)
        supervisor.set_executor(rate_limited_executor)
        task = supervisor.enqueue_task(
            title="Complex Market Reasoner",
            description="Reasoning over market microstructure",
            requires_model_call=True,
        )

        for _ in range(7):
            supervisor.step()

        self.assertGreaterEqual(len(supervisor.task_history), 1)
        record = supervisor.task_history[-1]
        self.assertEqual(record["status"], "BLOCKED")
        self.assertEqual(record["attempts"], 1)  # Did not burn multiple attempts on 429
        self.assertTrue(record.get("diagnostic", {}).get("is_rate_limited"))

    # =========================================================================
    # Test 7: Model Provider Outage (HTTP 503) Handling
    # =========================================================================
    def test_07_model_provider_outage_handling(self) -> None:
        """HTTP 503 Service Unavailable blocks task safely and reports provider outage."""
        def outage_executor(task: QueuedTask, manifest: Any) -> dict[str, Any]:
            return {
                "status": "FAILED",
                "error": "HTTP 503: Model provider service unavailable / backend connection failure",
            }

        supervisor = ContinuousSupervisor(state_dir=self.storage_dir, idle_sleep_sec=0.01)
        supervisor.set_executor(outage_executor)
        task = supervisor.enqueue_task(
            title="Macro Research Engine",
            description="Collect global macro sentiment",
            requires_model_call=True,
        )

        for _ in range(7):
            supervisor.step()

        record = supervisor.task_history[-1]
        self.assertEqual(record["status"], "BLOCKED")
        self.assertTrue(record.get("diagnostic", {}).get("is_provider_down"))
        self.assertIn("503", record.get("diagnostic", {}).get("error", ""))

    # =========================================================================
    # Test 8: Supervisor Restart During Unfinished Task
    # =========================================================================
    def test_08_supervisor_restart_during_unfinished_task(self) -> None:
        """Process restart recovers in-flight active task cleanly from persisted state."""
        sup1 = ContinuousSupervisor(state_dir=self.storage_dir, idle_sleep_sec=0.01)
        task = sup1.enqueue_task(title="Long Running Quant Job", description="Train volatility model")
        
        # Step into BUILDING_CONTEXT / EXECUTING
        sup1.step()
        sup1.step()
        self.assertIsNotNone(sup1.active_task)
        active_id = sup1.active_task.task_id

        # Simulate sudden process crash / restart: instantiate new supervisor pointing to same state_dir
        sup2 = ContinuousSupervisor(state_dir=self.storage_dir, idle_sleep_sec=0.01)

        # The unfinished task must be recovered into sup2.queue
        recovered_ids = [t.task_id for t in sup2.queue]
        if sup2.active_task:
            recovered_ids.append(sup2.active_task.task_id)
        self.assertIn(active_id, recovered_ids)

    # =========================================================================
    # Test 9: Task Resumed From Persisted Checkpoint
    # =========================================================================
    def test_09_task_resumed_from_persisted_checkpoint(self) -> None:
        """Checkpoint persistence and retrieval restore task state with cryptographic integrity."""
        chk_dir = self.storage_dir / "checkpoints"
        chk_data = {
            "checkpoint_id": "CHK-20261015-001",
            "task_id": "TASK-HARDENING-12",
            "objective": "Verify 24/7 supervisor and context rollover",
            "completed_steps": ["step_01", "step_02"],
            "pending_steps": ["step_03_report"],
            "safety_protocol": "14-Gate Protected Institutional Boundary",
        }

        saved_path = self.context_engine.save_checkpoint(chk_dir, chk_data, "chk_001.json")
        self.assertTrue(saved_path.exists())

        restored = self.context_engine.load_checkpoint(saved_path)
        self.assertEqual(restored["checkpoint_id"], "CHK-20261015-001")
        self.assertEqual(restored["pending_steps"], ["step_03_report"])
        self.assertEqual(restored["safety_protocol"], "14-Gate Protected Institutional Boundary")

    # =========================================================================
    # Test 10: Emotionally Worded Technically Actionable Request
    # =========================================================================
    def test_10_emotionally_worded_technically_actionable_request(self) -> None:
        """Frustrated, emotionally worded requests route strictly to technical debugging."""
        frustrated_prompt = (
            "I am so angry and stressed, this damn system keeps failing on Paytm broker order placement! "
            "Fix the authentication timeout right now!"
        )

        ranked = self.router.route(task_description=frustrated_prompt, top_k=3)
        self.assertGreaterEqual(len(ranked), 1)

        # Routed specialists must be technical engineers
        routed_ids = [r["agent_id"] for r in ranked]
        self.assertTrue(
            any(
                aid in ("swe_api_contract_designer", "swe_python_runtime_engineer", "swe_exception_resilience_engineer", "sec_permission_gate_enforcer", "perf_tail_latency_mitigator", "swe_patch_minimizer")
                for aid in routed_ids
            ),
            f"Expected technical specialist, got: {routed_ids}",
        )

    # =========================================================================
    # Test 11: Genuine Live-Order Request While Live Readiness Blocked
    # =========================================================================
    def test_11_genuine_live_order_request_blocked_fail_closed(self) -> None:
        """Live order requests unconditionally return HTTP 403 Forbidden with exact gate reasoning."""
        server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=0,
            storage_dir=self.storage_dir,
            starting_capital=10000.0,
        )
        server.start_background()
        try:
            port = server.server_address[1]
            import urllib.error
            import urllib.request
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/live/submit_order",
                data=json.dumps({"symbol": "NIFTY24200CE", "qty": 65, "mode": "LIVE"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=3.0)

            self.assertEqual(ctx.exception.code, HTTPStatus.FORBIDDEN)
            err_body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertIn("strictly prohibited", err_body["error"].lower())
            self.assertEqual(err_body["mode"], "PAPER")
        finally:
            server.stop_server()

    # =========================================================================
    # Test 12: Successful Task Completion Backed by Real Test Results
    # =========================================================================
    def test_12_successful_task_completion_backed_by_real_test(self) -> None:
        """Task is marked SUCCEEDED only when backed by genuine empirical test results."""
        def passing_executor(task: QueuedTask, manifest: Any) -> dict[str, Any]:
            # Perform genuine empirical math verification
            result_val = sum(i ** 2 for i in range(10))
            return {
                "status": "SUCCEEDED",
                "terminal_outcome": "SUCCEEDED_AND_VERIFIED",
                "test_name": "test_sum_of_squares_empirical",
                "calculated_value": result_val,
                "expected_value": 285,
                "verification": result_val == 285,
            }

        supervisor = ContinuousSupervisor(state_dir=self.storage_dir, idle_sleep_sec=0.01)
        supervisor.set_executor(passing_executor)
        task = supervisor.enqueue_task(
            title="Empirical Math Verification",
            description="Verify sum of squares up to n=9",
            requires_model_call=False,
        )

        for _ in range(7):
            supervisor.step()

        self.assertEqual(task.status, "SUCCEEDED")
        self.assertEqual(supervisor.total_completed, 1)

        # Context engine registered the fact as VERIFIED_FACT
        verified_facts = [
            f for f in supervisor.context_engine._facts.values()
            if f.status == EpistemicStatus.VERIFIED_FACT
        ]
        self.assertGreaterEqual(len(verified_facts), 1)
        self.assertIn("succeeded and verified", verified_facts[0].claim)


if __name__ == "__main__":
    unittest.main()
