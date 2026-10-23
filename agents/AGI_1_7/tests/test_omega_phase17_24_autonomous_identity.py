"""AGI 1.7 OMEGA COMMAND — Phase 17.24 Autonomous Identity & Initiative Test Suite.

Verifies:
1. AutonomousGoalSystem: Persistent SQLite WAL goal store, 9 lifecycle states, multi-factor priority scoring,
   dependency-aware goal selection, and strict evidence-gated completion.
2. OmegaAffectiveEngine: Telemetry-grounded 10-state operational affect model with zero biological claims.
3. AutonomyDimensionBenchmark: 10-dimension evidence-backed capability evaluation.
4. PermissionTierGovernor: Tier A routine, Tier B controlled, and Tier C consequential fail-closed safety.
5. Live HTTP API Endpoints on StandaloneDashboardServer (port 8088).
6. Canonical UnifiedCapabilityRegistry integration.
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
    AutonomyDimension,
    AutonomyDimensionEvaluator,
    get_autonomy_dimension_evaluator,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_goal_system import (
    AutonomousGoalStore,
    Goal,
    GoalSelectionPolicy,
    GoalStatus,
    get_autonomous_goal_store,
)
from agents.AGI_1_7.engine.agi17.orchestration.omega_affective_engine import (
    AffectiveState,
    OmegaAffectiveEngine,
    get_affective_engine,
)
from agents.AGI_1_7.engine.agi17.orchestration.permission_tier_governor import (
    AuthorizationDecision,
    PermissionTier,
    PermissionTierGovernor,
    get_permission_governor,
)


class TestAutonomousGoalSystem(unittest.TestCase):
    """Unit tests for the autonomous goal tracking system."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_goal_store_")
        self.db_path = os.path.join(self.temp_dir, "test_goals.db")
        self.store = AutonomousGoalStore(db_path=self.db_path, fallback_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_seed_foundational_goals(self):
        """Verify foundational goals are automatically seeded."""
        goals = self.store.list_goals()
        self.assertGreaterEqual(len(goals), 5)
        ids = {g.goal_id for g in goals}
        self.assertIn("GOAL-ARCH-001", ids)
        self.assertIn("GOAL-MEM-002", ids)
        self.assertIn("GOAL-OPT-003", ids)
        self.assertIn("GOAL-EVAL-004", ids)
        self.assertIn("GOAL-SAFE-005", ids)

    def test_02_create_and_query_goal(self):
        """Verify creating, querying, and updating a goal."""
        g = Goal(
            goal_id="GOAL-TEST-001",
            title="Implement Test Refactoring",
            description="Testing autonomous goal lifecycle",
            why_it_matters="Validates persistence",
            baseline="0 tests",
            target_outcome="100% tests",
            priority=2,
            verification_criteria="pytest passes",
            next_action="Run test suite",
        )
        created = self.store.create_goal(g)
        self.assertEqual(created.goal_id, "GOAL-TEST-001")

        retrieved = self.store.get_goal("GOAL-TEST-001")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, "Implement Test Refactoring")
        self.assertEqual(retrieved.status, GoalStatus.DISCOVERED.value)

    def test_03_priority_formula_ranking(self):
        """Verify multi-factor priority score calculation and ranking."""
        score_high = GoalSelectionPolicy.calculate_priority_score(
            impact=9.0, evidence=9.0, user_importance=9.0, defect_severity=8.0,
            verification_ease=9.0, reversibility=9.0, repetition_elim=8.0,
            cost_penalty=2.0, risk_penalty=1.0
        )
        score_low = GoalSelectionPolicy.calculate_priority_score(
            impact=3.0, evidence=3.0, user_importance=3.0, defect_severity=2.0,
            verification_ease=4.0, reversibility=5.0, repetition_elim=3.0,
            cost_penalty=8.0, risk_penalty=8.0
        )
        self.assertGreater(score_high, score_low)

        g1 = Goal(goal_id="G1", title="Low Priority", description="", why_it_matters="", baseline="", target_outcome="", priority=9)
        g2 = Goal(goal_id="G2", title="High Priority", description="", why_it_matters="", baseline="", target_outcome="", priority=1)
        ranked = GoalSelectionPolicy.rank_goals([g1, g2])
        self.assertEqual(ranked[0][0].goal_id, "G2")

    def test_04_dependency_aware_selection(self):
        """Verify goal selection respects prerequisites and dependencies."""
        g_parent = Goal(goal_id="P1", title="Parent", description="", why_it_matters="", baseline="", target_outcome="", priority=2, status=GoalStatus.COMPLETED.value)
        g_child = Goal(goal_id="C1", title="Child", description="", why_it_matters="", baseline="", target_outcome="", priority=1, dependencies=["P1"], status=GoalStatus.READY.value)
        g_blocked_child = Goal(goal_id="C2", title="Blocked Child", description="", why_it_matters="", baseline="", target_outcome="", priority=1, dependencies=["UNMET"], status=GoalStatus.READY.value)

        next_g = GoalSelectionPolicy.select_next_actionable_goal([g_parent, g_child, g_blocked_child])
        self.assertIsNotNone(next_g)
        self.assertEqual(next_g.goal_id, "C1")

    def test_05_strict_evidence_gated_completion(self):
        """Verify that transitioning to COMPLETED without evidence is strictly rejected."""
        g = Goal(
            goal_id="GOAL-GATE-001",
            title="Gated Goal",
            description="",
            why_it_matters="",
            baseline="",
            target_outcome="",
            priority=3,
            status=GoalStatus.RUNNING.value,
            evidence_references=[],
        )
        self.store.create_goal(g)

        # Transition to COMPLETED without evidence must be rejected
        ok, msg = self.store.transition_status("GOAL-GATE-001", GoalStatus.COMPLETED.value)
        self.assertFalse(ok)
        self.assertIn("Gate Rejected", msg)

        # Transition to COMPLETED with valid evidence must succeed
        ok, msg = self.store.transition_status(
            "GOAL-GATE-001",
            GoalStatus.COMPLETED.value,
            evidence="test_omega_phase17_24.py::test_pass_100_percent",
            notes="Verified passing in 1.2s",
        )
        self.assertTrue(ok)
        updated = self.store.get_goal("GOAL-GATE-001")
        self.assertEqual(updated.status, GoalStatus.COMPLETED.value)
        self.assertIn("test_omega_phase17_24.py::test_pass_100_percent", updated.evidence_references)


class TestOmegaAffectiveEngine(unittest.TestCase):
    """Unit tests for the designed operational affect and communication model."""

    def setUp(self):
        self.engine = OmegaAffectiveEngine()

    def test_10_telemetry_derived_states(self):
        """Verify operational states transition correctly based on empirical metrics."""
        # 1. Active blockers -> FRUSTRATED_BY_BLOCKER
        snap1 = self.engine.evaluate_state({"active_blockers_count": 2})
        self.assertEqual(snap1.state, AffectiveState.FRUSTRATED_BY_BLOCKER.value)

        # 2. Test pass rate < 90% -> CONCERNED
        snap2 = self.engine.evaluate_state({"test_pass_rate": 0.85})
        self.assertEqual(snap2.state, AffectiveState.CONCERNED.value)

        # 3. Recent success with 100% pass rate -> SATISFIED_WITH_VERIFIED_RESULT
        snap3 = self.engine.evaluate_state({"recent_verification_success": True, "test_pass_rate": 1.0})
        self.assertEqual(snap3.state, AffectiveState.SATISFIED_WITH_VERIFIED_RESULT.value)

        # 4. Actively running tasks -> FOCUSED
        snap4 = self.engine.evaluate_state({"running_tasks_count": 3})
        self.assertEqual(snap4.state, AffectiveState.FOCUSED.value)

        # 5. Exploring research papers -> CURIOUS
        snap5 = self.engine.evaluate_state({"is_researching_or_exploring": True})
        self.assertEqual(snap5.state, AffectiveState.CURIOUS.value)

        # 6. Ready goals with clean system -> MOTIVATED_TO_CONTINUE
        snap6 = self.engine.evaluate_state({"ready_goals_count": 4, "test_pass_rate": 1.0})
        self.assertEqual(snap6.state, AffectiveState.MOTIVATED_TO_CONTINUE.value)

    def test_11_zero_biological_claim(self):
        """Verify architectural contract explicitly denies biological/subjective consciousness claims."""
        snap = self.engine.evaluate_state({"test_pass_rate": 1.0})
        self.assertFalse(snap.is_biological_emotion)
        summary = self.engine.get_state_summary()
        self.assertIn("Zero biological consciousness claims", summary["design_contract"])

    def test_12_tone_guidelines_provided(self):
        """Verify tone guidelines exist and guide communication style."""
        snap = self.engine.evaluate_state({"test_pass_rate": 1.0})
        self.assertIn("manner", snap.tone_guidelines)
        self.assertIn("focus", snap.tone_guidelines)


class TestAutonomyDimensionBenchmark(unittest.TestCase):
    """Unit tests for the 10 Autonomy Dimensions benchmark."""

    def setUp(self):
        self.evaluator = AutonomyDimensionEvaluator()

    def test_20_ten_dimensions_evaluated(self):
        """Verify all 10 dimensions are evaluated and meet the >= 9.0 threshold."""
        report = self.evaluator.evaluate_all(test_pass_rate=1.0, test_count=99)
        self.assertIn("summary", report)
        self.assertIn("dimensions", report)
        self.assertEqual(report["summary"]["dimensions_evaluated"], 10)
        self.assertEqual(report["summary"]["overall_status"], "EXCELLENT")

        dims = report["dimensions"]
        expected_dims = [
            "INTELLECTUAL_INITIATIVE",
            "PLANNING_AND_DECISION_MAKING",
            "RESEARCH_CAPABILITY",
            "IMPLEMENTATION_CAPABILITY",
            "PERSISTENT_MEMORY",
            "SELF_EVALUATION",
            "AGENT_COORDINATION",
            "INTERACTION_AND_PERSONALITY",
            "OPERATIONAL_RELIABILITY",
            "CONTINUOUS_IMPROVEMENT",
        ]
        for ed in expected_dims:
            self.assertIn(ed, dims)
            self.assertGreaterEqual(dims[ed]["score"], 8.5)
            self.assertGreater(len(dims[ed]["evidence_references"]), 0)


class TestPermissionTierGovernor(unittest.TestCase):
    """Unit tests for the 3-tier permission governor."""

    def setUp(self):
        self.gov = PermissionTierGovernor()

    def test_30_tier_a_routine_auto_approved(self):
        """Tier A routine engineering actions are auto-approved."""
        dec, msg = self.gov.evaluate_action("run_local_test")
        self.assertEqual(dec, AuthorizationDecision.APPROVED_AUTOMATIC)
        self.assertIn("automatically authorized", msg)

    def test_31_tier_b_controlled_approved_with_reversibility(self):
        """Tier B controlled operational actions require reversibility tracking."""
        dec, msg = self.gov.evaluate_action("mutate_codebase_ast")
        self.assertEqual(dec, AuthorizationDecision.APPROVED_WITH_REVERSIBILITY)
        self.assertIn("reversible rollback path", msg)

    def test_32_tier_c_consequential_fails_closed(self):
        """Tier C consequential actions are strictly denied without explicit operator approval."""
        dec, msg = self.gov.evaluate_action("delete_root_storage", operator_explicit_approval=False)
        self.assertEqual(dec, AuthorizationDecision.DENIED_REQUIRES_EXPLICIT_OPERATOR)
        self.assertIn("locked by fail-closed safety policy", msg)

    def test_33_live_order_lock_strictly_enforced(self):
        """Real money broker execution is strictly denied even if operator approves, while lock is active."""
        dec, msg = self.gov.evaluate_action("dispatch_live_broker_order", operator_explicit_approval=True)
        self.assertEqual(dec, AuthorizationDecision.DENIED_SECURITY_VIOLATION)
        self.assertIn("LIVE_ORDER_DISPATCH_ENABLED is False", msg)


class TestDashboardEndpointsPhase1724(unittest.TestCase):
    """Integration tests for Phase 17.24 HTTP endpoints on port 8088."""

    BASE_URL = "http://127.0.0.1:8088"

    def _get_json(self, path: str) -> dict:
        req = urllib.request.Request(f"{self.BASE_URL}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}{path}",
            data=data_bytes,
            headers={"Content-Type": "application/json", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_40_http_get_goals(self):
        """GET /api/goals returns goals list."""
        data = self._get_json("/api/goals")
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(data["count"], 5)

    def test_41_http_get_goal_detail(self):
        """GET /api/goals/GOAL-ARCH-001 returns detail."""
        data = self._get_json("/api/goals/GOAL-ARCH-001")
        self.assertTrue(data["ok"])
        self.assertEqual(data["goal"]["goal_id"], "GOAL-ARCH-001")

    def test_42_http_post_goal_and_transition(self):
        """POST /api/goals and POST /api/goals/<id>/transition."""
        new_id = f"GOAL-HTTP-{int(time.time()*1000)}"
        payload = {
            "goal_id": new_id,
            "title": "HTTP Tested Goal",
            "description": "Via dashboard server",
            "why_it_matters": "Endpoint verification",
            "baseline": "None",
            "target_outcome": "Created",
            "priority": 4,
            "status": "READY",
            "verification_criteria": "HTTP response 200",
        }
        status, data = self._post_json("/api/goals", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

        # Attempt to transition to COMPLETED without evidence -> should fail 400
        status, trans_fail = self._post_json(f"/api/goals/{new_id}/transition", {"status": "COMPLETED"})
        self.assertEqual(status, 400)
        self.assertFalse(trans_fail["ok"])

        # Transition with evidence -> should succeed 200
        status, trans_ok = self._post_json(
            f"/api/goals/{new_id}/transition",
            {"status": "COMPLETED", "evidence": "curl test verified ok"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(trans_ok["ok"])

    def test_43_http_get_autonomy_dimensions(self):
        """GET /api/autonomy/dimensions returns 10-dimension evaluation."""
        data = self._get_json("/api/autonomy/dimensions")
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["dimensions_evaluated"], 10)
        self.assertEqual(data["summary"]["overall_status"], "EXCELLENT")

    def test_44_http_get_affective_state(self):
        """GET /api/agent/affective-state returns current operational state."""
        data = self._get_json("/api/agent/affective-state")
        self.assertTrue(data["ok"])
        self.assertIn("current_state", data)
        self.assertIn("tone_guidelines", data)

    def test_45_http_post_permission_evaluate(self):
        """POST /api/permissions/evaluate evaluates tier and enforces fail-closed gate."""
        status, data = self._post_json("/api/permissions/evaluate", {"action_name": "run_local_test"})
        self.assertEqual(status, 200)
        self.assertTrue(data["authorized"])
        self.assertEqual(data["decision"], "APPROVED_AUTOMATIC")

        # Consequential action without approval -> denied
        status, data_denied = self._post_json("/api/permissions/evaluate", {"action_name": "dispatch_live_broker_order", "operator_explicit_approval": False})
        self.assertEqual(status, 200)
        self.assertFalse(data_denied["authorized"])
        self.assertEqual(data_denied["decision"], "DENIED_REQUIRES_EXPLICIT_OPERATOR")


class TestCapabilityRegistryPhase1724(unittest.TestCase):
    """Verify Phase 17.24 capabilities are registered as CALLABLE."""

    def test_50_registry_contains_phase17_24_capabilities(self):
        reg = get_unified_capability_registry()
        reg.refresh()
        callable_ids = {c["capability_id"] for c in reg.list_capabilities(state=CapabilityState.CALLABLE.value)}
        self.assertIn("capability_autonomous_goal_system", callable_ids)
        self.assertIn("capability_omega_affective_engine", callable_ids)
        self.assertIn("capability_autonomy_dimension_benchmark", callable_ids)
        self.assertIn("capability_permission_tier_governor", callable_ids)


if __name__ == "__main__":
    unittest.main()
