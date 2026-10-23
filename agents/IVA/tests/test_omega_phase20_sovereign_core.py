"""AGI 1.7 OMEGA COMMAND — Phase 20 Sovereign Core & Intrinsic Motivation Test Suite.

Verifies:
1. AutonomousIntrinsicDriveEngine initialization and singleton resolution.
2. 4-Drive Potential evaluation:
   - Drive A: MASTERY_COMPRESSION
   - Drive B: EPISTEMIC_EXPANSION
   - Drive C: INVARIANT_PRESERVATION
   - Drive D: COLLABORATIVE_AUTOPOIESIS
3. Self-aim formulation and priority weighting.
4. Materialization into AutonomousGoalStore with deduplication.
5. UnifiedCapabilityRegistry registration of svc_intrinsic_drive_engine.
6. OmegaControlCenter accessor integration.
7. AutonomousGoalRunner auto_aims selection and execution.
8. Execution and empirical verification of AIM-MASTERY-AST-COMPACT.
9. Execution and empirical verification of AIM-EPISTEMIC-SABR-SVI.
10. Execution and empirical verification of AIM-PRESERVE-CRYPTO-LEDGER and AIM-AUTOPOIESIS-CONTEXT-ADAPT.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.capabilities.unified_capability_registry import (
    CapabilityDomain,
    CapabilityState,
    UnifiedCapabilityRegistry,
    get_unified_capability_registry,
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
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_intrinsic_drive_engine import (
    AutonomousIntrinsicDriveEngine,
    DrivePotential,
    IntrinsicDriveType,
    SelfAim,
    get_intrinsic_drive_engine,
)
from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    get_intrinsic_drive_engine as get_intrinsic_drive_from_control_center,
)


class TestOmegaPhase20SovereignCore(unittest.TestCase):
    """Unit and integration tests for Phase 20 Sovereign Core and Intrinsic Self-Aims."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_phase20_sovereign_")
        self.db_path = os.path.join(self.temp_dir, "test_sovereign_goals.db")
        self.scratch_dir = Path(self.temp_dir) / "scratch"
        self.scratch_dir.mkdir(parents=True, exist_ok=True)

        self.store = AutonomousGoalStore(db_path=self.db_path, fallback_dir=self.temp_dir)
        # Mark seeded foundational goals as completed for test isolation
        for g in self.store.list_goals():
            if g.status != GoalStatus.COMPLETED.value:
                self.store.transition_status(g.goal_id, GoalStatus.COMPLETED.value, evidence="Isolated in setUp")

        self.drive_engine = AutonomousIntrinsicDriveEngine(goal_store=self.store)
        self.runner = AutonomousGoalRunner(
            goal_store=self.store,
            scratch_dir=self.scratch_dir,
        )

    def tearDown(self):
        self.runner.stop_background_daemon()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_intrinsic_drive_engine_initialization_and_singletons(self):
        """Verify initialization and singleton instance pattern."""
        self.assertIsNotNone(self.drive_engine)
        s1 = get_intrinsic_drive_engine()
        s2 = get_intrinsic_drive_engine()
        self.assertIs(s1, s2)

    def test_02_drive_potentials_evaluation(self):
        """Verify evaluate_drive_potentials computes potentials for all 4 drives."""
        potentials = self.drive_engine.evaluate_drive_potentials()
        self.assertIsInstance(potentials, dict)
        self.assertEqual(len(potentials), 4)

        expected_drives = {
            IntrinsicDriveType.MASTERY_COMPRESSION.value,
            IntrinsicDriveType.EPISTEMIC_EXPANSION.value,
            IntrinsicDriveType.INVARIANT_PRESERVATION.value,
            IntrinsicDriveType.COLLABORATIVE_AUTOPOIESIS.value,
        }
        self.assertEqual(set(potentials.keys()), expected_drives)

        for drive_name, p in potentials.items():
            self.assertIsInstance(p, DrivePotential)
            self.assertEqual(p.drive_type, drive_name)
            self.assertGreaterEqual(p.potential_score, 0.0)
            self.assertLessEqual(p.potential_score, 10.0)
            self.assertTrue(len(p.tension_reason) > 0)
            self.assertTrue(len(p.target_metric) > 0)

    def test_03_formulate_self_aims(self):
        """Verify formulate_self_aims produces concrete, well-formed SelfAim instances."""
        aims = self.drive_engine.formulate_self_aims()
        self.assertIsInstance(aims, list)
        self.assertGreaterEqual(len(aims), 4)

        aim_ids = {a.aim_id for a in aims}
        expected_ids = {
            "AIM-MASTERY-AST-COMPACT",
            "AIM-EPISTEMIC-SABR-SVI",
            "AIM-PRESERVE-CRYPTO-LEDGER",
            "AIM-AUTOPOIESIS-CONTEXT-ADAPT",
        }
        self.assertTrue(expected_ids.issubset(aim_ids))

        for aim in aims:
            self.assertTrue(aim.aim_id.startswith("AIM-"))
            self.assertIn(aim.priority, [1, 2, 3])
            self.assertGreaterEqual(aim.urgency_weight, 1.0)
            self.assertTrue(len(aim.verification_criteria) > 0)
            self.assertTrue(len(aim.evidence_archetype) > 0)

    def test_04_materialize_aims_into_goals(self):
        """Verify materializing self-aims into Goal store records with deduplication."""
        initial_ready = self.store.list_goals(status="READY")
        self.assertEqual(len(initial_ready), 0)

        materialized = self.drive_engine.materialize_aims_into_goals(max_aims=2)
        self.assertEqual(len(materialized), 2)

        ready_goals = self.store.list_goals(status="READY")
        ready_ids = {g.goal_id for g in ready_goals}
        for mid in materialized:
            self.assertIn(mid, ready_ids)

        # Deduplication check
        second_run = self.drive_engine.materialize_aims_into_goals(max_aims=2)
        for mid in materialized:
            self.assertNotIn(mid, second_run)

    def test_05_capability_registry_reflection(self):
        """Verify svc_intrinsic_drive_engine is registered in UnifiedCapabilityRegistry."""
        reg = get_unified_capability_registry()
        cap = reg.get_capability("svc_intrinsic_drive_engine")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.domain, CapabilityDomain.AGENT_ORCHESTRATION.value)
        self.assertEqual(cap.state, CapabilityState.CALLABLE.value)
        self.assertIn("Phase 20", cap.description)

    def test_06_control_center_accessor(self):
        """Verify omega_control_center provides accessor for intrinsic drive engine."""
        engine = get_intrinsic_drive_from_control_center()
        self.assertIsNotNone(engine)
        self.assertIsInstance(engine, AutonomousIntrinsicDriveEngine)

    def test_07_runner_auto_aims_integration(self):
        """Verify runner select_next_goal materializes aims when queue is empty."""
        # Queue starts empty of READY goals
        ready = self.store.list_goals(status="READY")
        self.assertEqual(len(ready), 0)

        goal = self.runner.select_next_goal(auto_aims=True)
        self.assertIsNotNone(goal)
        self.assertTrue(goal.goal_id.startswith("AIM-"))
        self.assertEqual(goal.status, GoalStatus.READY.value)

    def test_08_execute_and_verify_mastery_aim(self):
        """Verify AutonomousGoalRunner executes and verifies AIM-MASTERY-AST-COMPACT."""
        aims = [a for a in self.drive_engine.formulate_self_aims() if a.aim_id == "AIM-MASTERY-AST-COMPACT"]
        self.assertEqual(len(aims), 1)
        aim = aims[0]

        g = Goal(
            goal_id=aim.aim_id,
            title=aim.title,
            description=aim.intent,
            why_it_matters="Mastery drive",
            baseline="Pre-drive baseline",
            target_outcome=aim.target_outcome,
            priority=aim.priority,
            status=GoalStatus.READY.value,
            verification_criteria=aim.verification_criteria,
        )
        self.store.create_goal(g)

        result = self.runner.run_goal_cycle()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.goal_id, "AIM-MASTERY-AST-COMPACT")
        self.assertGreater(len(result.evidence_references), 0)
        self.assertTrue(any("AST hot-path" in ev for ev in result.evidence_references))

        updated = self.store.get_goal("AIM-MASTERY-AST-COMPACT")
        self.assertEqual(updated.status, GoalStatus.COMPLETED.value)

    def test_09_execute_and_verify_epistemic_aim(self):
        """Verify AutonomousGoalRunner executes and verifies AIM-EPISTEMIC-SABR-SVI."""
        aims = [a for a in self.drive_engine.formulate_self_aims() if a.aim_id == "AIM-EPISTEMIC-SABR-SVI"]
        self.assertEqual(len(aims), 1)
        aim = aims[0]

        g = Goal(
            goal_id=aim.aim_id,
            title=aim.title,
            description=aim.intent,
            why_it_matters="Epistemic drive",
            baseline="Pre-drive baseline",
            target_outcome=aim.target_outcome,
            priority=aim.priority,
            status=GoalStatus.READY.value,
            verification_criteria=aim.verification_criteria,
        )
        self.store.create_goal(g)

        result = self.runner.run_goal_cycle()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.goal_id, "AIM-EPISTEMIC-SABR-SVI")
        self.assertGreater(len(result.evidence_references), 0)
        self.assertTrue(any("Gatheral SVI parameters verified" in ev for ev in result.evidence_references))
        self.assertTrue(any("Roger Lee wing slope condition satisfied" in ev for ev in result.evidence_references))

        updated = self.store.get_goal("AIM-EPISTEMIC-SABR-SVI")
        self.assertEqual(updated.status, GoalStatus.COMPLETED.value)

    def test_10_execute_and_verify_preserve_and_autopoiesis_aims(self):
        """Verify execution and verification of Invariant Preservation and Autopoiesis aims."""
        aims = {a.aim_id: a for a in self.drive_engine.formulate_self_aims()}
        for aim_id in ["AIM-PRESERVE-CRYPTO-LEDGER", "AIM-AUTOPOIESIS-CONTEXT-ADAPT"]:
            aim = aims[aim_id]
            g = Goal(
                goal_id=aim.aim_id,
                title=aim.title,
                description=aim.intent,
                why_it_matters="Sovereign drive",
                baseline="Pre-drive baseline",
                target_outcome=aim.target_outcome,
                priority=aim.priority,
                status=GoalStatus.READY.value,
                verification_criteria=aim.verification_criteria,
            )
            self.store.create_goal(g)

            result = self.runner.run_goal_cycle()
            self.assertEqual(result.status, "SUCCESS")
            self.assertEqual(result.goal_id, aim_id)
            self.assertGreater(len(result.evidence_references), 0)

            updated = self.store.get_goal(aim_id)
            self.assertEqual(updated.status, GoalStatus.COMPLETED.value)


if __name__ == "__main__":
    unittest.main()
