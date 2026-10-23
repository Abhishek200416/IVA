"""AGI 1.7 OMEGA COMMAND — Phase 19 Autonomous Goal Discovery & Synthesis Test Suite.

Verifies:
1. AutonomousGoalDiscoveryEngine initialization and singleton resolution.
2. Multi-vector audit discovery:
   - Vector A: Codebase & Test Coverage Gaps.
   - Vector B: Runtime Performance & SQLite WAL Health.
   - Vector C: Quantitative Strategy Microstructure & Hawkes Invariants.
   - Vector D: Security Boundaries & Secrets Hygiene.
3. Goal candidate deduplication against existing goal store records.
4. Auto-seeding and seamless continuation of the cognitive loop in AutonomousGoalRunner.
5. SecretsHygieneAuditor workspace environmental scanning.
6. Live HTTP API execution on Port 8088 with auto_discover=True.
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

from agents.AGI_1_7.engine.agi17.orchestration.autonomous_goal_discovery_engine import (
    AutonomousGoalDiscoveryEngine,
    DiscoveredGoalCandidate,
    get_goal_discovery_engine,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_goal_runner import (
    AutonomousGoalRunner,
    get_autonomous_goal_runner,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_goal_system import (
    AutonomousGoalStore,
    Goal,
    GoalStatus,
)
from agents.AGI_1_7.engine.agi17.security.least_privilege_enforcer import SecretsHygieneAuditor


class TestAutonomousGoalDiscoveryEngine(unittest.TestCase):
    """Unit and integration tests for the Phase 19 Autonomous Goal Discovery Engine."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_discovery_")
        self.db_path = os.path.join(self.temp_dir, "test_discovery_goals.db")
        self.scratch_dir = Path(self.temp_dir) / "scratch"
        self.scratch_dir.mkdir(parents=True, exist_ok=True)

        self.store = AutonomousGoalStore(db_path=self.db_path, fallback_dir=self.temp_dir)
        # Mark seeded foundational goals as completed for test isolation
        for g in self.store.list_goals():
            if g.status != GoalStatus.COMPLETED.value:
                self.store.transition_status(g.goal_id, GoalStatus.COMPLETED.value, evidence="Isolated in setUp")

        self.discovery = AutonomousGoalDiscoveryEngine(goal_store=self.store)
        self.runner = AutonomousGoalRunner(
            goal_store=self.store,
            scratch_dir=self.scratch_dir,
        )

    def tearDown(self):
        self.runner.stop_background_daemon()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_discovery_engine_initialization_and_singletons(self):
        """Verify initialization and singleton instance pattern."""
        self.assertIsNotNone(self.discovery)
        s1 = get_goal_discovery_engine()
        s2 = get_goal_discovery_engine()
        self.assertIs(s1, s2)

    def test_02_audit_codebase_coverage_vector(self):
        """Verify Vector A audits codebase and generates coverage goal candidates."""
        candidates = self.discovery._audit_codebase_coverage()
        self.assertIsInstance(candidates, list)
        for c in candidates:
            self.assertEqual(c.vector, "CODE_COVERAGE")
            self.assertTrue(c.candidate_id.startswith("GOAL-COV-"))
            self.assertGreaterEqual(c.priority, 1)

    def test_03_audit_runtime_health_vector(self):
        """Verify Vector B audits memory and produces performance/indexing candidates."""
        candidates = self.discovery._audit_runtime_health()
        self.assertGreater(len(candidates), 0)
        self.assertEqual(candidates[0].vector, "PERFORMANCE")
        self.assertIn("GOAL-", candidates[0].candidate_id)

    def test_04_audit_quantitative_models_vector(self):
        """Verify Vector C produces quantitative research and microstructure probe candidates."""
        candidates = self.discovery._audit_quantitative_models()
        self.assertGreater(len(candidates), 0)
        c = candidates[0]
        self.assertEqual(c.vector, "QUANT_RESEARCH")
        self.assertIn("MICROSTRUCTURE", c.candidate_id)
        self.assertIn("Hawkes", c.description)

    def test_05_audit_security_boundaries_vector(self):
        """Verify Vector D produces security and secrets hygiene probe candidates."""
        candidates = self.discovery._audit_security_boundaries()
        self.assertGreater(len(candidates), 0)
        c = candidates[0]
        self.assertEqual(c.vector, "SECURITY")
        self.assertIn("SECRETS", c.candidate_id)

    def test_06_synthesize_and_seed_goals(self):
        """Verify synthesizing and seeding new goals into AutonomousGoalStore."""
        initial_goals = self.store.list_goals(status="READY")
        self.assertEqual(len(initial_goals), 0)

        seeded_ids = self.discovery.synthesize_and_seed_goals(max_goals_to_seed=2)
        self.assertEqual(len(seeded_ids), 2)

        ready_goals = self.store.list_goals(status="READY")
        ready_ids = {g.goal_id for g in ready_goals}
        for sid in seeded_ids:
            self.assertIn(sid, ready_ids)

        # Deduplication check: seeding again immediately should not duplicate
        second_seeded = self.discovery.synthesize_and_seed_goals(max_goals_to_seed=2)
        self.assertNotIn(seeded_ids[0], second_seeded)

    def test_07_auto_discovery_integration_in_runner(self):
        """Verify AutonomousGoalRunner transparently triggers discovery when queue is empty."""
        # Queue starts empty of READY goals
        ready = self.store.list_goals(status="READY")
        self.assertEqual(len(ready), 0)

        # Calling select_next_goal with auto_discover=True synthesizes and returns a goal
        goal = self.runner.select_next_goal(auto_discover=True)
        self.assertIsNotNone(goal)
        self.assertEqual(goal.status, GoalStatus.READY.value)

    def test_08_secrets_hygiene_auditor_scan(self):
        """Verify SecretsHygieneAuditor scan runs and accurately reports workspace hygiene."""
        audit_res = SecretsHygieneAuditor.audit_environment()
        self.assertIn("files_scanned", audit_res)
        self.assertIn("secrets_leak_detected", audit_res)
        self.assertGreater(audit_res["files_scanned"], 0)

    def test_09_continuous_discovery_and_execution_cycle(self):
        """Verify full continuous loop: auto-discovery -> execution -> verification -> completion."""
        # Run goal cycle with auto_discover=True
        result = self.runner.run_goal_cycle(auto_discover=True)
        self.assertEqual(result.status, "SUCCESS")
        self.assertIsNotNone(result.goal_id)
        self.assertGreater(len(result.evidence_references), 0)

        # Confirm goal is completed in store
        completed_goal = self.store.get_goal(result.goal_id)
        self.assertIsNotNone(completed_goal)
        self.assertEqual(completed_goal.status, GoalStatus.COMPLETED.value)

    def test_10_live_http_auto_discovery_endpoint(self):
        """Verify live POST /api/goals/run-cycle with auto_discover=True on port 8088."""
        try:
            payload = json.dumps({"auto_discover": True}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8088/api/goals/run-cycle",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data["ok"])
                self.assertIn("result", data)
                self.assertIn(data["result"]["status"], ["SUCCESS", "NO_GOALS"])
        except urllib.error.URLError:
            self.skipTest("Live dashboard on port 8088 not reachable")


if __name__ == "__main__":
    unittest.main()
