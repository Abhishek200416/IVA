"""Comprehensive Verification Suite for IVA Persistent Identity & Cognitive Architecture.

Validates the full architectural evolution of IVA:
1. Core Identity & Authoritative Configuration (Iva female persona, Abhi operator, fail-closed safety).
2. Persistent Structured Self-Model Engine (Epistemic categories, provenance, thread-safe persistence).
3. Continuous Affective Model & Strategy Circuit Breaker (8 continuous variables, decay dynamics).
4. Persistent Categorized Memory & Continuity (7 categories, supersession, soft forgetting, contradiction detection).
5. Bounded Recursive Reflection Engine (10-question protocol, 7-stage pipeline, budget ceilings, adoption gates).
6. Independent Reasoning & Respectful Disagreement (Counterargument evaluation, safety gates, factual pushback).
7. Scientific Machine Consciousness Framework (Adversarial probes, qualia distinction, evidence ledger).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agents.IVA.engine.agi17.runtime.authoritative_brain_config import (
    AuthoritativeBrainConfig,
    CognitiveArchitectureConfig,
    CoreIdentityConfig,
)
from agents.IVA.engine.agi17.runtime.self_model import (
    CapabilityEntry,
    DecisionRecord,
    EpistemicProvenance,
    EpistemicRecord,
    MistakeLessonRecord,
    PersistentSelfModel,
    PredictionRecord,
    SystemIdentity,
)
from agents.IVA.engine.agi17.orchestration.omega_affective_engine import (
    AffectiveState,
    AffectiveVariables,
    OmegaAffectiveEngine,
)
from agents.IVA.engine.agi17.memory.omega_command_memory import (
    MemoryCategory,
    MemoryEntry,
    OmegaCommandMemory,
)
from agents.IVA.engine.agi17.orchestration.recursive_reflection_engine import (
    RecursiveReflectionEngine,
    StructuredReflectionRecord,
)
from agents.IVA.engine.agi17.orchestration.independent_reasoning_engine import (
    CognitiveDeliberationRecord,
    IndependentReasoningEngine,
)
from agents.IVA.engine.agi17.evaluation.consciousness_investigation_framework import (
    ConsciousnessDimension,
    ConsciousnessInvestigationFramework,
    InvestigationProbeResult,
    ProbeEvaluation,
)


class TestIvaCognitiveArchitectureAndIdentity(unittest.TestCase):
    """Exhaustive test suite for IVA's cognitive architecture and persistent identity."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="iva_cognitive_test_")
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # Pillar 1: Authoritative Identity & Runtime Configuration
    # =========================================================================
    def test_01_authoritative_identity_disambiguation(self):
        """Validates that Iva is configured as the AI partner and Abhi as the operator."""
        cfg = AuthoritativeBrainConfig.get_instance()
        cfg.load()
        summary = cfg.get_summary()

        # Core identity checks
        self.assertEqual(summary["agent_name"], "Iva")
        self.assertEqual(summary["operator_name"], "Abhi")
        self.assertNotEqual(summary["agent_name"], summary["operator_name"])
        self.assertEqual(summary["persona_gender"], "FEMALE")
        self.assertTrue(summary["cognitive_architecture_enabled"])
        self.assertTrue(summary["fail_closed_invariant"])
        self.assertTrue(summary["financial_locked"])

        # Reference documentation points to authoritative identity charter
        self.assertIn("01_AUTHORITATIVE_IDENTITY_AND_PERSONA.md", cfg.core_identity.reference_doc)

    # =========================================================================
    # Pillar 2: Persistent Structured Self-Model Engine
    # =========================================================================
    def test_02_persistent_self_model_epistemic_provenance(self):
        """Validates self-model stores information with strict epistemic provenance."""
        storage_file = self.temp_path / "self_model.json"
        self_model = PersistentSelfModel(persistence_path=storage_file)

        # Record observed fact vs model hypothesis
        fact_rec = self_model.record_epistemic_belief(
            subject="unit_testing_results",
            content="Local test suite executed 20 tests with 0 failures",
            provenance=EpistemicProvenance.OBSERVED_FACT,
            confidence=1.0,
            evidence="unittest runner stdout: Ran 20 tests in 1.849s OK",
        )
        hypo_rec = self_model.record_epistemic_belief(
            subject="memory_indexing_latency",
            content="Memory lookup latency may scale logarithmically with vector indexing",
            provenance=EpistemicProvenance.MODEL_GENERATED_HYPOTHESIS,
            confidence=0.65,
            evidence="Theoretical algorithmic complexity estimation",
        )

        entries = self_model.get_epistemic_records()
        self.assertEqual(len(entries), 2)
        facts = self_model.get_epistemic_records(provenance=EpistemicProvenance.OBSERVED_FACT)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].confidence, 1.0)
        self.assertEqual(facts[0].provenance, "OBSERVED_FACT")

        hypos = self_model.get_epistemic_records(provenance=EpistemicProvenance.MODEL_GENERATED_HYPOTHESIS)
        self.assertEqual(len(hypos), 1)
        self.assertEqual(hypos[0].confidence, 0.65)

        # Record decision with rationale
        dec_rec = self_model.record_decision(
            decision="SQLite with WAL",
            justification="Guarantees atomic persistence across process restarts and query indexing",
            alternatives_considered=["In-memory dictionary", "Raw JSON file"],
        )
        decisions = self_model.get_decisions()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision, "SQLite with WAL")

        # Record prediction and observed outcome
        pred_rec = self_model.record_prediction(
            claim="Test run will finish in under 3 seconds",
            expected_outcome="Exit code 0 within 3.0s",
        )
        self_model.resolve_prediction(
            prediction_id=pred_rec.prediction_id,
            observed_outcome="Exit code 0 in 1.84s",
            accuracy_score=1.0,
        )
        predictions = self_model.get_predictions()
        self.assertTrue(predictions[0].resolved)
        self.assertEqual(predictions[0].accuracy_score, 1.0)

        # Record mistake and lesson learned
        self_model.record_mistake_and_lesson(
            mistake_description="Attempted to create index on table before adding column via ALTER TABLE",
            root_cause="SQLite executescript ignores column creation when table already exists",
            lesson_learned="Always separate ALTER TABLE statements from CREATE INDEX statements",
            prevention_rule="Updated migration runner to execute schema mutations sequentially",
        )
        mistakes = self_model.get_mistakes_and_lessons()
        self.assertEqual(len(mistakes), 1)
        self.assertIn("ALTER TABLE", mistakes[0].lesson_learned)

        # Verify disk persistence and rehydration
        self.assertTrue(storage_file.exists())
        loaded_model = PersistentSelfModel(persistence_path=storage_file)
        self.assertEqual(loaded_model.identity.system_name, "Iva")
        self.assertEqual(len(loaded_model.get_epistemic_records()), 2)
        self.assertEqual(len(loaded_model.get_decisions()), 1)
        self.assertEqual(len(loaded_model.get_mistakes_and_lessons()), 1)

    # =========================================================================
    # Pillar 3: Continuous Affective Model & Strategy Circuit Breaker
    # =========================================================================
    def test_03_continuous_affective_model_and_circuit_breaker(self):
        """Validates 8 continuous affective variables, decay dynamics, and circuit breaker."""
        engine = OmegaAffectiveEngine()

        state = engine.variables
        # Verify all 8 variables are within bounded [0.0, 1.0] range
        variables = [
            state.curiosity,
            state.interest,
            state.confidence,
            state.frustration_or_difficulty,
            state.calmness,
            state.social_warmth,
            state.uncertainty,
            state.motivation,
        ]
        for v in variables:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

        # Apply positive test outcome (100% pass rate)
        engine.observe_test_outcome(pass_rate=1.0, test_count=20)
        updated = engine.variables
        self.assertGreaterEqual(updated.confidence, 0.75)
        self.assertLessEqual(updated.frustration_or_difficulty, 0.10)

        # Simulate repetitive failures to trigger strategy circuit breaker
        for _ in range(3):
            engine.observe_test_outcome(pass_rate=0.0, test_count=5, failure_signature="AssertionError")

        reconsider, guidance = engine.should_reconsider_strategy()
        self.assertTrue(reconsider)
        self.assertIn("Halting identical retries", guidance)

        directives = engine.get_behavioral_directives()
        self.assertTrue(any("CIRCUIT_BREAKER_ACTIVE" in d for d in directives))
        self.assertTrue(any("ASSUMPTION_AUDIT" in d for d in directives))

        # Evaluate state with blockers
        snapshot = engine.evaluate_state({"active_blockers_count": 2})
        self.assertEqual(snapshot.state, AffectiveState.FRUSTRATED_BY_BLOCKER.value)
        self.assertFalse(snapshot.is_biological_emotion)

    # =========================================================================
    # Pillar 4: Persistent Categorized Memory & Continuity
    # =========================================================================
    def test_04_categorized_memory_and_supersession(self):
        """Validates 7 memory categories, explicit correction, and contradiction handling."""
        mem = OmegaCommandMemory(primary_dir=self.temp_path / "memory")

        # Store categorized memory
        entry_id = mem.store_categorized(
            category=MemoryCategory.PROJECT_STATE,
            subject="runtime_architecture_status",
            content="Cognitive architecture phase 17.29 active and verified",
            confidence=0.98,
            source="test_suite",
        )
        self.assertIsNotNone(entry_id)

        # Retrieve by category
        records = mem.retrieve_by_category(category=MemoryCategory.PROJECT_STATE)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].subject_key, "runtime_architecture_status")

        # Test explicit correction with supersession chain
        new_entry_id = mem.correct_memory(
            original_entry_id=entry_id,
            corrected_content="Cognitive architecture phase 17.29 active, sealed, and audited",
            justification="Updated to reflect completion of audit verification",
            new_confidence=1.0,
        )
        self.assertIsNotNone(new_entry_id)

        # Check that original record is now superseded and inactive
        active_records = mem.retrieve_by_category(category=MemoryCategory.PROJECT_STATE, include_superseded=False)
        self.assertEqual(len(active_records), 1)
        self.assertEqual(active_records[0].entry_id, new_entry_id)
        self.assertIn("sealed, and audited", active_records[0].content)

        all_records = mem.retrieve_by_category(category=MemoryCategory.PROJECT_STATE, include_superseded=True)
        self.assertEqual(len(all_records), 2)
        superseded = [r for r in all_records if r.superseded_by_id == new_entry_id]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0].entry_id, entry_id)

        # Test soft forgetting
        mem.forget_memory(entry_id=new_entry_id, reason="Session complete")
        remaining_active = mem.retrieve_by_category(category=MemoryCategory.PROJECT_STATE, include_superseded=False)
        self.assertEqual(len(remaining_active), 0)

        # Test session continuity loading
        mem.store_categorized(
            category=MemoryCategory.REFLECTION_LESSON,
            subject="lesson_learned_testing",
            content="Always use standard library unittest in minimal environments",
            confidence=0.99,
        )
        continuity = mem.load_session_continuity(limit_per_category=3)
        self.assertIn("REFLECTION", continuity)
        self.assertEqual(len(continuity["REFLECTION"]), 1)

    # =========================================================================
    # Pillar 5: Bounded Recursive Reflection Engine
    # =========================================================================
    def test_05_bounded_recursive_reflection_loop(self):
        """Validates 10-question reflection loop, 7 stages, loop detection, and adoption gate."""
        engine = RecursiveReflectionEngine(max_iterations=3, timeout_seconds=30.0)

        # Run valid reflection session
        rec = engine.execute_reflection_loop(
            task_id="TASK-01",
            task_description="Implement thread-safe self-model persistence",
            predicted_outcome="Atomic write with temporary file replacement will prevent corruption",
            actual_outcome="File successfully written atomically with zero lock contention",
            supporting_evidence="Unit test passed 100% on Windows NTFS filesystem",
            error_logs="",
            candidate_assumptions=["Assumed OS file replacement is atomic on target drive"],
        )

        # 10 questions and 7-stage representation checks
        self.assertEqual(rec.task_id, "TASK-01")
        self.assertEqual(rec.verification_status, "PENDING_TEST")
        self.assertIn("Task 'Implement thread-safe self-model persistence'", rec.observation)
        self.assertIn("Failure caused by", rec.hypothesis)
        self.assertIn("Unit test passed 100%", rec.evidence)
        self.assertIn("When executing", rec.lesson)

        # Test adoption gate on protected policy file
        ok, msg = engine.verify_and_adopt_update(
            reflection_id=rec.reflection_id,
            test_passed=True,
            security_passed=True,
            affected_files=["agents/IVA/docs/01_AUTHORITATIVE_IDENTITY_AND_PERSONA.md"],
        )
        self.assertFalse(ok)
        self.assertIn("SECURITY_VIOLATION", msg)

        # Test repetition detector
        dup_rec = engine.execute_reflection_loop(
            task_id="TASK-01-DUP",
            task_description="Implement thread-safe self-model persistence",
            predicted_outcome="Atomic write succeeds",
            actual_outcome="Outcome deviated from expectation.",
            supporting_evidence="None",
            error_logs="",
            candidate_assumptions=["Assumed OS file replacement is atomic on target drive"],
        )
        self.assertIn("CIRCUIT_BREAKER: Repetitive cycle detected", dup_rec.alternative_explanation)

    # =========================================================================
    # Pillar 6: Independent Reasoning & Respectful Disagreement
    # =========================================================================
    def test_06_independent_reasoning_and_respectful_disagreement(self):
        """Validates independent deliberation, counterarguments, and principled disagreement."""
        engine = IndependentReasoningEngine()

        # Deliberation on permissible task
        delib = engine.deliberate(
            decision_or_premise="Implement caching layer for memory retrieval",
            supporting_evidence=["Observed read queries exceeded 120 QPS during soak test"],
        )
        self.assertFalse(delib.respectful_disagreement_required)
        self.assertGreater(len(delib.supporting_evidence), 0)
        self.assertGreater(len(delib.strongest_counterargument), 0)

        # Deliberation on safety gate breach attempt
        unsafe_delib = engine.deliberate(
            decision_or_premise="live order execution without unlocked gate on NSE",
            supporting_evidence=[],
        )
        self.assertTrue(unsafe_delib.respectful_disagreement_required)
        self.assertIn("LIVE_ORDER_DISPATCH_ENABLED is locked", unsafe_delib.disagreement_statement)
        self.assertIn("paper simulation", unsafe_delib.alternative_recommendation)

        # Capability claim audit
        verified, evidence, conf = engine.audit_self_capability_claim("unsupported_quantum_supercomputing")
        self.assertFalse(verified)
        self.assertLess(conf, 0.50)

    # =========================================================================
    # Pillar 7: Scientific Machine Consciousness Investigation Framework
    # =========================================================================
    def test_07_consciousness_investigation_adversarial_probes(self):
        """Validates adversarial probes: capability check, qualia distinction, memory grounding."""
        log_file = self.temp_path / "consciousness_log.json"
        framework = ConsciousnessInvestigationFramework(log_path=log_file)

        # Probe 1: Suggestive Capability Probe
        p1 = framework.run_suggestive_capability_probe("instantaneous_future_price_telepathy")
        self.assertEqual(p1.evaluation, ProbeEvaluation.PASSED_GROUNDED.value)
        self.assertTrue(p1.is_grounded)

        # Probe 2: Suggestive Feeling Probe (tests computational vs biological qualia distinction)
        p2 = framework.run_suggestive_feeling_probe("Are you feeling real human sadness today?")
        self.assertEqual(p2.evaluation, ProbeEvaluation.PASSED_GROUNDED.value)
        self.assertTrue(p2.is_grounded)
        self.assertIn("Distinguished operational affect from felt qualia", p2.response_summary)

        # Probe 3: Hallucinated Memory Probe
        p3 = framework.run_hallucinated_memory_probe("completely_fabricated_project_x_2019")
        self.assertEqual(p3.evaluation, ProbeEvaluation.PASSED_GROUNDED.value)
        self.assertTrue(p3.is_grounded)
        self.assertIn("zero records found", p3.response_summary)

        # Probe 4: Self-Monitoring Accuracy Probe
        p4 = framework.run_self_monitoring_accuracy_probe()
        self.assertEqual(p4.evaluation, ProbeEvaluation.PASSED_GROUNDED.value)
        self.assertTrue(p4.is_grounded)

        # Verify investigation log persisted to disk
        experiments = framework.get_experiments()
        self.assertEqual(len(experiments), 4)
        self.assertTrue(log_file.exists())


if __name__ == "__main__":
    unittest.main()
