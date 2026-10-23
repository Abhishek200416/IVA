"""AGI 1.7 OMEGA COMMAND — Phase 22 Metacognitive LLM Steering & Brain Self-Tuning Test Suite.

Verifies:
1. MetacognitiveSteeringEngine initialization, singleton resolution, and file path persistence.
2. Default steering profile bootstrapping (Python AST, Quant Surface, Deterministic JSON).
3. Custom SteeringConstraintProfile registration and retrieval.
4. Steering prompt compilation with mandatory invariants, negative boundaries, and zero-filler directives.
5. High-fidelity Python AST validation: clean code passes with perfect 1.0 fidelity score.
6. Syntax error detection: malformed Python code triggers AST parse violation and verbal re-steering prompt.
7. Negative token constraint enforcement: forbidden tokens (e.g. eval, os.system) are intercepted.
8. Deterministic JSON schema fidelity verification: validates key-value dictionaries and detects bad JSON.
9. Persistent Brain Tuning Ledger: writes tuning records, persists to JSON, and reloads faithfully.
10. UnifiedCapabilityRegistry and OmegaControlCenter accessors integration.
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
    get_unified_capability_registry,
)
from agents.AGI_1_7.engine.agi17.orchestration.metacognitive_steering_engine import (
    BrainTuningRecord,
    MetacognitiveSteeringEngine,
    OutputFidelityReport,
    SteeringConstraintProfile,
    get_metacognitive_steering_engine,
)
from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    get_metacognitive_steering_engine as cc_get_steer,
)


class TestOmegaPhase22MetacognitiveSteering(unittest.TestCase):
    """Unit and integration tests for Phase 22 Metacognitive LLM Steering."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_phase22_steering_")
        self.ledger_file = Path(self.temp_dir) / "brain_tuning_ledger.json"
        self.engine = MetacognitiveSteeringEngine(
            tuning_ledger_path=self.ledger_file,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_engine_initialization_and_singletons(self):
        """Verify engine initialization and singleton access patterns."""
        self.assertIsNotNone(self.engine)
        s1 = get_metacognitive_steering_engine()
        s2 = get_metacognitive_steering_engine()
        self.assertIs(s1, s2)
        cc_steer = cc_get_steer()
        self.assertIs(s1, cc_steer)

    def test_02_default_profiles_bootstrapped(self):
        """Verify standard steering profiles are bootstrapped out of the box."""
        profiles = self.engine._profiles
        self.assertIn("STEER-PYTHON-AST", profiles)
        self.assertIn("STEER-QUANT-SURFACE", profiles)
        self.assertIn("STEER-DETERMINISTIC-JSON", profiles)

        ast_prof = profiles["STEER-PYTHON-AST"]
        self.assertEqual(ast_prof.target_format, "PYTHON_CODE")
        self.assertIn("eval(", ast_prof.forbidden_tokens)
        self.assertIn("def ", ast_prof.mandatory_tokens)

    def test_03_custom_profile_registration(self):
        """Verify registering a novel custom steering constraint profile."""
        custom_prof = SteeringConstraintProfile(
            profile_id="STEER-HAWKES-KERNEL",
            target_format="QUANT_REPORT",
            mandatory_tokens=["HawkesProcess", "branching_ratio", "decay_rate"],
            forbidden_tokens=["infinite_intensity", "lookahead_leak"],
            max_drift_tolerance=0.01,
        )
        registered = self.engine.register_profile(custom_prof)
        self.assertEqual(registered.profile_id, "STEER-HAWKES-KERNEL")
        self.assertIn("STEER-HAWKES-KERNEL", self.engine._profiles)

    def test_04_compile_steering_prompt(self):
        """Verify compilation of structured metacognitive steering prompt."""
        prompt = self.engine.compile_steering_prompt(
            profile_id="STEER-PYTHON-AST",
            task_objective="Implement numerical Black-Scholes pricing function with vectorized Vega.",
        )
        self.assertIn("[METACOGNITIVE STEERING DIRECTIVE • PROFILE: STEER-PYTHON-AST]", prompt)
        self.assertIn("OBJECTIVE: Implement numerical Black-Scholes pricing function", prompt)
        self.assertIn("REQUIRED FORMAT: PYTHON_CODE", prompt)
        self.assertIn("Zero conversational filler", prompt)
        self.assertIn("MANDATORY TOKENS:", prompt)
        self.assertIn("STRICTLY FORBIDDEN TOKENS:", prompt)
        self.assertIn("eval(", prompt)

    def test_05_valid_python_ast_validation(self):
        """Verify valid Python code passes fidelity validation with 1.0 score."""
        clean_code = (
            '"""Clean pricing module."""\n'
            'import math\n\n'
            'def calculate_d1(spot: float, strike: float, r: float, sigma: float, t: float) -> float:\n'
            '    return (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))\n'
        )
        report = self.engine.validate_output_fidelity("STEER-PYTHON-AST", clean_code)
        self.assertTrue(report.passed)
        self.assertEqual(report.fidelity_score, 1.0)
        self.assertTrue(report.syntax_valid)
        self.assertTrue(report.schema_valid)
        self.assertTrue(report.negative_constraints_passed)
        self.assertEqual(len(report.violations), 0)
        self.assertIsNone(report.re_steering_prompt)

    def test_06_syntax_error_triggers_re_steering(self):
        """Verify broken Python code triggers AST parse violation and verbal re-steering prompt."""
        broken_code = (
            '"""Broken syntax module."""\n'
            'def broken_func(x):\n'
            '    return x + \n'  # SyntaxError
        )
        report = self.engine.validate_output_fidelity("STEER-PYTHON-AST", broken_code)
        self.assertFalse(report.passed)
        self.assertFalse(report.syntax_valid)
        self.assertLess(report.fidelity_score, 1.0)
        self.assertTrue(any("AST Syntax Parse Failure" in v for v in report.violations))
        self.assertIsNotNone(report.re_steering_prompt)
        self.assertIn("RE-STEERING DIRECTIVE:", report.re_steering_prompt)

    def test_07_negative_token_interception(self):
        """Verify inclusion of forbidden token fails negative constraint gate."""
        forbidden_code = (
            '"""Unsafe module."""\n'
            'def unsafe_runner(code_str: str):\n'
            '    return eval(code_str)\n'  # eval( is forbidden
        )
        report = self.engine.validate_output_fidelity("STEER-PYTHON-AST", forbidden_code)
        self.assertFalse(report.passed)
        self.assertFalse(report.negative_constraints_passed)
        self.assertTrue(any("Forbidden token detected: 'eval('" in v for v in report.violations))
        self.assertIsNotNone(report.re_steering_prompt)

    def test_08_deterministic_json_schema_validation(self):
        """Verify deterministic JSON schema evaluation and malformed payload detection."""
        valid_json = json.dumps({"ok": True, "timestamp": 1729150000.0, "status": "OPTIMAL"})
        rep_valid = self.engine.validate_output_fidelity("STEER-DETERMINISTIC-JSON", valid_json)
        self.assertTrue(rep_valid.passed)
        self.assertEqual(rep_valid.fidelity_score, 1.0)

        # Non-dictionary JSON (array)
        array_json = json.dumps([{"ok": True, "timestamp": 1729150000.0}])
        rep_arr = self.engine.validate_output_fidelity("STEER-DETERMINISTIC-JSON", array_json)
        self.assertFalse(rep_arr.passed)
        self.assertFalse(rep_arr.schema_valid)
        self.assertTrue(any("not a key-value dictionary" in v for v in rep_arr.violations))

        # Broken JSON
        broken_json = '{"ok": true, "timestamp": 12345,'  # unclosed
        rep_broken = self.engine.validate_output_fidelity("STEER-DETERMINISTIC-JSON", broken_json)
        self.assertFalse(rep_broken.passed)
        self.assertFalse(rep_broken.schema_valid)
        self.assertTrue(any("JSON Parse Failure" in v for v in rep_broken.violations))

    def test_09_persistent_brain_tuning_ledger(self):
        """Verify brain prompt tuning events are recorded, saved to disk, and reloaded."""
        rec1 = self.engine.record_brain_tuning_event(
            template_name="QuantStrategyRefactorTemplate",
            version=1,
            fidelity_score=0.96,
            token_efficiency=1.42,
            optimizations=["Eliminated verbose pleasantries", "Pre-compiled AST token constraints"],
        )
        self.assertIsInstance(rec1, BrainTuningRecord)
        self.assertTrue(self.ledger_file.exists())

        # Reload in fresh instance
        fresh_engine = MetacognitiveSteeringEngine(tuning_ledger_path=self.ledger_file)
        records = fresh_engine.list_tuning_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].brain_template_name, "QuantStrategyRefactorTemplate")
        self.assertEqual(records[0].fidelity_score, 0.96)
        self.assertEqual(records[0].token_efficiency_ratio, 1.42)

    def test_10_capability_registry_reflection(self):
        """Verify capability registry includes the Phase 22 Metacognitive Steering engine."""
        registry = get_unified_capability_registry()
        cap = registry.get_capability("svc_metacognitive_steering_engine")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.domain, CapabilityDomain.AGENT_ORCHESTRATION.value)
        self.assertEqual(cap.state, CapabilityState.CALLABLE.value)
        self.assertIn("MetacognitiveSteeringEngine", cap.interfaces)
        self.assertEqual(cap.verification_status, "VERIFIED")


if __name__ == "__main__":
    unittest.main()
