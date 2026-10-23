"""AGI 1.7 OMEGA COMMAND — Test Suite for Recursive Metaprogramming & Autonomous Self-Benchmark Engine.

Verifies:
1. SelfBenchmarkSuite: Runs AST, memory, trajectory evaluation, and safety probes.
2. RecursiveMetaprogrammingOptimizer:
   - Proposes valid AST mutations with atomic .bak creation.
   - Rejects illegal mutations targeting protected safety gates (GATE_01).
   - Commits successful, verified mutations cleanly.
   - Automatically rolls back broken or regressing mutations and records verbal reflection.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from agents.AGI_1_7.engine.agi17.orchestration.recursive_metaprogramming_engine import (
    BenchmarkResult,
    SelfBenchmarkSuite,
    RecursiveMetaprogrammingOptimizer,
    ASTMutationRecord,
)
from agents.AGI_1_7.engine.agi17.capabilities.unified_capability_registry import (
    UnifiedCapabilityRegistry,
)


class TestSelfBenchmarkSuite:
    """Verifies that the autonomous capability benchmark executes reliably."""

    def test_run_all_probes(self):
        suite = SelfBenchmarkSuite()
        res = suite.run_all_probes()

        assert res.suite_name == "AGI_1_7_SELF_CAPABILITY_INDEX"
        assert res.total_tests == 4
        assert res.passed_tests == 4
        assert res.score == 100.0
        assert res.duration_sec >= 0.0

        details = res.details
        assert details["ast_code_generation"]["passed"] is True
        assert details["associative_memory"]["passed"] is True
        assert details["trajectory_evaluation"]["passed"] is True
        assert details["security_invariants"]["passed"] is True


class TestRecursiveMetaprogrammingOptimizer:
    """Verifies safe AST mutation, atomic rollback, and safety boundaries."""

    def test_security_guard_blocks_protected_files(self, tmp_path):
        optimizer = RecursiveMetaprogrammingOptimizer(workspace_root=tmp_path)
        fake_gate = tmp_path / "gate_01_user_authorized_capital_and_risk.py"
        fake_gate.write_text("GATE = True", encoding="utf-8")

        ok, msg, rec = optimizer.propose_and_apply_mutation(
            target_file=fake_gate,
            transformation_fn=lambda c: c + "\n# illegal edit",
            rationale="Attempt to modify protected gate",
        )

        assert ok is False
        assert "Security Violation" in msg
        assert rec is None

    def test_successful_mutation_commit_cycle(self, tmp_path):
        optimizer = RecursiveMetaprogrammingOptimizer(workspace_root=tmp_path)
        target = tmp_path / "math_helper.py"
        target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        def add_multiply(code: str) -> str:
            return code + "\ndef multiply(a, b):\n    '''Multiplies two numbers.'''\n    return a * b\n"

        ok, msg, record = optimizer.propose_and_apply_mutation(
            target_file=target,
            transformation_fn=add_multiply,
            rationale="Add verified multiply helper",
        )

        assert ok is True
        assert record is not None
        assert record.status == "EVALUATING"
        assert Path(record.backup_file).exists()

        # Decide: commit
        decided, dec_msg = optimizer.evaluate_and_decide(record, target_test_file=None)
        assert decided is True
        assert record.status == "COMMITTED"
        assert not Path(record.backup_file).exists()  # Backup deleted on commit

        # Verify new content persisted
        content = target.read_text(encoding="utf-8")
        assert "def multiply" in content

    def test_failing_mutation_triggers_atomic_rollback(self, tmp_path):
        optimizer = RecursiveMetaprogrammingOptimizer(workspace_root=tmp_path)
        target = tmp_path / "critical_routine.py"
        original_code = "def stable_func():\n    return 100\n"
        target.write_text(original_code, encoding="utf-8")

        # Fake a test file that expects stable_func to return 100
        test_file = tmp_path / "test_critical.py"
        test_file.write_text(
            f"import sys\nsys.path.insert(0, r'{tmp_path}')\n"
            "from critical_routine import stable_func\n"
            "def test_stable(): assert stable_func() == 100\n",
            encoding="utf-8"
        )

        # Mutate stable_func to return 999 (which will fail the test)
        def breaking_mutation(code: str) -> str:
            return "def stable_func():\n    return 999\n"

        ok, msg, record = optimizer.propose_and_apply_mutation(
            target_file=target,
            transformation_fn=breaking_mutation,
            rationale="Breaking change to test rollback",
        )

        assert ok is True
        assert record.status == "EVALUATING"

        # Evaluate against the failing test
        decided, dec_msg = optimizer.evaluate_and_decide(record, target_test_file=str(test_file.relative_to(tmp_path)))
        assert decided is False
        assert record.status == "ROLLED_BACK"
        assert record.reflection_notes != ""

        # Content must be 100% restored to original
        restored_content = target.read_text(encoding="utf-8")
        assert restored_content == original_code
        assert "return 100" in restored_content


class TestCapabilityRegistryIncludesMetaprogramming:
    """Verifies that UnifiedCapabilityRegistry reflects the new metaprogramming engine."""

    def test_registry_has_metaprogramming_callable(self):
        reg = UnifiedCapabilityRegistry()
        inv = reg.get_canonical_inventory()
        callable_ids = [c["capability_id"] for c in inv["callable"]]
        assert "capability_recursive_metaprogramming" in callable_ids
