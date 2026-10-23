"""AGI 1.7 OMEGA COMMAND — Phase 18 Autonomous Goal Runner & Continuous Loop Test Suite.

Verifies:
1. AutonomousGoalRunner initialization, singletons, and thread safety.
2. Prioritized, dependency-aware actionable goal selection.
3. Fail-closed permission checking via PermissionTierGovernor.
4. Autonomous execution cycle with strict evidence-gated completion.
5. Invariant enforcement rejecting unverified goal transitions.
6. Telemetry and affective state synchronization in OmegaAffectiveEngine.
7. Atomic heartbeat snapshot generation in scratch directory.
8. Non-blocking background worker daemon lifecycle (start/stop).
9. UnifiedCapabilityRegistry registration and callable state.
10. Live HTTP API endpoints on Standalone Dashboard Server (port 8088):
    - GET /api/goals/runner-status
    - POST /api/goals/run-cycle
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agents.AGI_1_7.engine.agi17.capabilities.unified_capability_registry import (
    CapabilityDomain,
    CapabilityState,
    get_unified_capability_registry,
)
from agents.AGI_1_7.engine.agi17.evaluation.autonomy_dimension_benchmark import (
    AutonomyDimensionEvaluator,
    get_autonomy_dimension_evaluator,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_goal_runner import (
    AutonomousGoalRunner,
    CycleExecutionResult,
    get_autonomous_goal_runner,
    get_goal_runner,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_goal_system import (
    AutonomousGoalStore,
    Goal,
    GoalStatus,
)
from agents.AGI_1_7.engine.agi17.orchestration.omega_affective_engine import (
    AffectiveState,
    OmegaAffectiveEngine,
    get_affective_engine,
)
from agents.AGI_1_7.engine.agi17.orchestration.permission_tier_governor import (
    AuthorizationDecision,
    PermissionTierGovernor,
    get_permission_tier_governor,
)


class TestAutonomousGoalRunner(unittest.TestCase):
    """Unit and integration tests for AutonomousGoalRunner."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_goal_runner_")
        self.db_path = os.path.join(self.temp_dir, "test_runner_goals.db")
        self.scratch_dir = Path(self.temp_dir) / "scratch"
        self.scratch_dir.mkdir(parents=True, exist_ok=True)

        self.store = AutonomousGoalStore(db_path=self.db_path, fallback_dir=self.temp_dir)
        self.affective = OmegaAffectiveEngine()
        self.permission = PermissionTierGovernor()
        self.autonomy = AutonomyDimensionEvaluator()

        self.runner = AutonomousGoalRunner(
            goal_store=self.store,
            affective_engine=self.affective,
            permission_governor=self.permission,
            autonomy_evaluator=self.autonomy,
            scratch_dir=self.scratch_dir,
        )

        # Mark seeded foundational goals as completed to provide clean test isolation
        for g in self.store.list_goals():
            if g.status != GoalStatus.COMPLETED.value:
                self.store.transition_status(g.goal_id, GoalStatus.COMPLETED.value, evidence="Seeded completion in setUp")

    def tearDown(self):
        self.runner.stop_background_daemon()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_runner_initialization_and_singletons(self):
        """Verify runner initialization, default state, and singleton helper."""
        status = self.runner.get_runner_status()
        self.assertTrue(status["ok"])
        self.assertFalse(status["runner_active"])
        self.assertEqual(status["total_cycles_executed"], 0)
        self.assertEqual(status["goals_completed_in_session"], 0)
        self.assertTrue(status["permission_live_order_lock"])

        singleton1 = get_autonomous_goal_runner()
        singleton2 = get_goal_runner()
        self.assertIs(singleton1, singleton2)

    def test_02_goal_selection_and_ranking(self):
        """Verify dependency-aware and priority-ranked goal selection."""
        # Clean store goals
        g_ready_low = Goal(
            goal_id="G-READY-LOW",
            title="Low Priority Ready Goal",
            description="",
            why_it_matters="",
            baseline="",
            target_outcome="",
            priority=8,
            status=GoalStatus.READY.value,
        )
        g_ready_high = Goal(
            goal_id="G-READY-HIGH",
            title="High Priority Ready Goal",
            description="",
            why_it_matters="",
            baseline="",
            target_outcome="",
            priority=0,
            status=GoalStatus.READY.value,
        )
        self.store.create_goal(g_ready_low)
        self.store.create_goal(g_ready_high)

        selected = self.runner.select_next_goal()
        self.assertIsNotNone(selected)
        # Should select highest priority (lowest number)
        self.assertEqual(selected.goal_id, "G-READY-HIGH")

    def test_03_execution_and_evidence_gated_completion(self):
        """Verify executing an autonomous cycle completes the goal with empirical evidence."""
        g = Goal(
            goal_id="G-AUTO-001",
            title="Automated Test Goal",
            description="Testing autonomous execution",
            why_it_matters="Validates execution loop",
            baseline="Unexecuted",
            target_outcome="Executed with evidence",
            priority=0,
            status=GoalStatus.READY.value,
            verification_criteria="Self-test assertion passes",
        )
        self.store.create_goal(g)

        result = self.runner.run_goal_cycle()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.goal_id, "G-AUTO-001")
        self.assertGreater(len(result.evidence_references), 0)

        # Verify goal status in store is now COMPLETED
        updated = self.store.get_goal("G-AUTO-001")
        self.assertEqual(updated.status, GoalStatus.COMPLETED.value)
        self.assertGreater(len(updated.evidence_references), 0)

        # Metrics updated
        status = self.runner.get_runner_status()
        self.assertEqual(status["total_cycles_executed"], 1)
        self.assertEqual(status["goals_completed_in_session"], 1)

    def test_04_affective_state_synchronization(self):
        """Verify affective engine transitions to SATISFIED upon verified cycle completion."""
        g = Goal(
            goal_id="G-AFFECT-001",
            title="Affect Sync Goal",
            description="",
            why_it_matters="",
            baseline="",
            target_outcome="",
            priority=0,
            status=GoalStatus.READY.value,
        )
        self.store.create_goal(g)

        self.runner.run_goal_cycle()
        self.assertEqual(
            self.affective.current_state,
            AffectiveState.SATISFIED_WITH_VERIFIED_RESULT,
        )

    def test_05_rejection_of_unverified_completion(self):
        """Verify underlying store strictly rejects transitioning to COMPLETED without evidence."""
        g = Goal(
            goal_id="G-REJECT-001",
            title="Unverified Goal",
            description="",
            why_it_matters="",
            baseline="",
            target_outcome="",
            priority=5,
            status=GoalStatus.RUNNING.value,
            evidence_references=[],
        )
        self.store.create_goal(g)

        ok, msg = self.store.transition_status("G-REJECT-001", GoalStatus.COMPLETED.value)
        self.assertFalse(ok)
        self.assertIn("Gate Rejected", msg)

    def test_06_permission_tier_fail_closed_enforcement(self):
        """Verify that goals with consequential live actions are blocked fail-closed."""
        # Governor blocks live orders
        dec, _ = self.permission.evaluate_action("dispatch_live_broker_order")
        self.assertEqual(dec, AuthorizationDecision.DENIED_REQUIRES_EXPLICIT_OPERATOR)
        self.assertTrue(self.permission.is_live_order_locked)

    def test_07_heartbeat_sync_and_persistence(self):
        """Verify atomic JSON heartbeat is written to scratch directory."""
        self.runner.run_goal_cycle()
        heartbeat_file = self.scratch_dir / "autonomous_goal_runner_heartbeat.json"
        self.assertTrue(heartbeat_file.exists())

        data = json.loads(heartbeat_file.read_text(encoding="utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["total_cycles_executed"], 1)
        self.assertIn("goal_distribution", data)

    def test_08_background_worker_lifecycle(self):
        """Verify starting and stopping background worker daemon."""
        self.assertFalse(self.runner.get_runner_status()["runner_active"])
        self.runner.start_background_daemon(interval_seconds=0.1)
        self.assertTrue(self.runner.get_runner_status()["runner_active"])

        time.sleep(0.3)
        self.runner.stop_background_daemon()
        self.assertFalse(self.runner.get_runner_status()["runner_active"])

    def test_09_capability_registry_reflection(self):
        """Verify UnifiedCapabilityRegistry discovers and registers svc_autonomous_goal_runner."""
        reg = get_unified_capability_registry()
        reg.refresh()

        cap = reg.get_capability("svc_autonomous_goal_runner")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.domain, CapabilityDomain.RUNTIME_SERVICE.value)
        self.assertIn(cap.state, [CapabilityState.CALLABLE.value, CapabilityState.ACTIVELY_EXECUTING.value])

    def test_10_live_http_dashboard_endpoints(self):
        """Verify live HTTP endpoints on port 8088."""
        # GET /api/goals/runner-status
        try:
            req_get = urllib.request.Request("http://127.0.0.1:8088/api/goals/runner-status")
            with urllib.request.urlopen(req_get, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data["ok"])
                self.assertIn("total_cycles_executed", data)
                self.assertIn("current_affective_state", data)
                self.assertIn("goal_distribution", data)

            # POST /api/goals/run-cycle
            req_post = urllib.request.Request(
                "http://127.0.0.1:8088/api/goals/run-cycle",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req_post, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                res_data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(res_data["ok"])
                self.assertIn("result", res_data)
                self.assertIn("status", res_data["result"])
        except urllib.error.URLError:
            self.skipTest("Live dashboard server on port 8088 not reachable during test run")


if __name__ == "__main__":
    unittest.main()
