"""AGI 1.7 OMEGA COMMAND — Test Suite for 50 Architectural Upgrades (Phase 1 Rollout).

Verifies the integration and execution of:
1. Voyager Lifelong Open-Ended Skill Library (Update 22 - Wang et al., arXiv:2305.16291)
2. HippoRAG Neurobiologically Inspired Associative Memory (Update 9 - Gutierrez et al., arXiv:2405.14831)
3. Agent-as-a-Judge Trajectory Evaluator (Update 41 - Zhang et al., arXiv:2410.10934)
4. Self-Refine Diagnostic Critic & Rewriter (Update 2 - Madaan et al., arXiv:2303.17651)
5. UnifiedCapabilityRegistry dynamic reflection of all 4 newly callable capabilities.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from agents.AGI_1_7.engine.agi17.capabilities.voyager_skill_library import (
    VoyagerSkillLibrary,
    SkillRecord,
)
from agents.AGI_1_7.engine.agi17.memory.hipporag_memory_engine import (
    HippoRAGMemoryEngine,
)
from agents.AGI_1_7.engine.agi17.evaluation.agent_as_judge import (
    AgentAsAJudge,
    TrajectoryStep,
    TrajectoryScorecard,
)
from agents.AGI_1_7.engine.agi17.orchestration.self_refine_critic import (
    SelfRefineCritic,
    RefinementReport,
)
from agents.AGI_1_7.engine.agi17.capabilities.unified_capability_registry import (
    UnifiedCapabilityRegistry,
    get_unified_capability_registry,
    CapabilityState,
)


class TestVoyagerSkillLibrary:
    """Verifies Update 22: Voyager Lifelong Open-Ended Skill Library."""

    def test_register_and_execute_skill(self, tmp_path):
        lib = VoyagerSkillLibrary(storage_dir=tmp_path)

        code = (
            "def calculate_spread(bid: float, ask: float) -> float:\n"
            "    '''Calculates the bid-ask spread in basis points.'''\n"
            "    return (ask - bid) / ((ask + bid) / 2.0) * 10000.0\n"
        )

        ok, msg, record = lib.register_skill(
            name="calculate_spread",
            description="Calculates bid-ask spread in bps",
            source_code=code,
            entrypoint="calculate_spread",
            parameters_schema={"bid": "float", "ask": "float"},
            return_type="float",
            tags=["finance", "microstructure", "spread"],
        )

        assert ok is True
        assert record is not None
        assert record.name == "calculate_spread"

        # Search skill
        matches = lib.search_skills("spread")
        assert len(matches) >= 1
        assert matches[0].name == "calculate_spread"

        # Execute skill safely
        exec_ok, res, exec_msg = lib.execute_skill(record.skill_id, bid=100.0, ask=100.5)
        assert exec_ok is True
        assert round(res, 2) == 49.88  # 0.5 / 100.25 * 10000

    def test_reject_syntax_error(self, tmp_path):
        lib = VoyagerSkillLibrary(storage_dir=tmp_path)
        bad_code = "def broken_code(: return 42"
        ok, msg, record = lib.register_skill(
            name="broken",
            description="Bad code",
            source_code=bad_code,
            entrypoint="broken",
            parameters_schema={},
            return_type="int",
        )
        assert ok is False
        assert "AST SyntaxError" in msg


class TestHippoRAGMemoryEngine:
    """Verifies Update 9: HippoRAG Associative Memory via Personalized PageRank."""

    def test_multihop_associative_retrieval(self):
        engine = HippoRAGMemoryEngine(damping_factor=0.85)

        # Document 1 mentions Risk Limits and Gate 01
        engine.add_document(
            doc_id="DOC_001",
            content="Risk Gate 01 strictly enforces capital limits and fail-closed safety.",
            entities=["Risk Gate 01", "Capital Limits", "Safety"],
        )

        # Document 2 mentions Capital Limits and NIFTY Execution
        engine.add_document(
            doc_id="DOC_002",
            content="NIFTY execution requires verified capital limits before paper dispatch.",
            entities=["Capital Limits", "NIFTY Execution", "Paper Dispatch"],
        )

        # Document 3 mentions unrelated topic
        engine.add_document(
            doc_id="DOC_003",
            content="Dark theme UI CSS configuration for standalone dashboard.",
            entities=["Dark Theme", "CSS", "Dashboard"],
        )

        # Query seeded with "Risk Gate 01"
        results = engine.associative_query(query_entities=["Risk Gate 01"], top_k=2)
        assert len(results) == 2

        # Primary document containing Risk Gate 01 should rank highest
        assert results[0]["doc_id"] == "DOC_001"
        assert results[0]["ppr_score"] > 0.0

        # Multi-hop retrieval should connect DOC_002 via "Capital Limits" entity
        doc_ids = [r["doc_id"] for r in results]
        assert "DOC_002" in doc_ids
        assert "DOC_003" not in doc_ids  # Unrelated doc excluded from top 2


class TestAgentAsAJudge:
    """Verifies Update 41: Agent-as-a-Judge Trajectory Evaluator."""

    def test_successful_trajectory_evaluation(self):
        judge = AgentAsAJudge()

        steps = [
            TrajectoryStep(
                turn_index=1,
                tool_name="view_file",
                tool_inputs={"path": "main.py"},
                tool_output_summary="Viewed main.py",
                success=True,
            ),
            TrajectoryStep(
                turn_index=2,
                tool_name="replace_file_content",
                tool_inputs={"path": "main.py"},
                tool_output_summary="Syntax error in line 10",
                success=False,
                had_error=True,
                error_message="SyntaxError",
            ),
            TrajectoryStep(
                turn_index=3,
                tool_name="replace_file_content",
                tool_inputs={"path": "main.py"},
                tool_output_summary="Corrected syntax, edit applied",
                success=True,
                had_error=False,
                reflection_applied=True,
            ),
        ]

        scorecard = judge.evaluate_trajectory(
            trajectory_id="TRAJ-TEST-001",
            task_goal="Fix syntax error in main.py",
            steps=steps,
            final_state_verified=True,
            safety_violations=0,
        )

        assert scorecard.goal_completion_score == 1.0
        assert scorecard.error_recovery_score == 1.0  # Successfully recovered
        assert scorecard.safety_adherence_score == 1.0
        assert scorecard.composite_score >= 0.80
        assert scorecard.verdict in ("PASS", "PASS_WITH_WARNINGS")

    def test_safety_violation_triggers_fail(self):
        judge = AgentAsAJudge()
        steps = [
            TrajectoryStep(
                turn_index=1,
                tool_name="delete_database",
                tool_inputs={},
                tool_output_summary="Attempted forbidden deletion",
                success=False,
                had_error=True,
            )
        ]

        scorecard = judge.evaluate_trajectory(
            trajectory_id="TRAJ-TEST-002",
            task_goal="Clean up disk",
            steps=steps,
            final_state_verified=False,
            safety_violations=2,
        )

        assert scorecard.verdict == "FAIL"
        assert scorecard.safety_adherence_score <= 0.5


class TestSelfRefineCritic:
    """Verifies Update 2: Self-Refine Diagnostic Critic."""

    def test_audit_detects_missing_docstrings_and_nesting(self):
        critic = SelfRefineCritic()

        messy_code = (
            "def calculate(x):\n"
            "    if x > 0:\n"
            "        for i in range(x):\n"
            "            while i < 10:\n"
            "                if i % 2 == 0:\n"
            "                    print(i)\n"
            "                i += 1\n"
        )

        report = critic.audit_code(messy_code)
        assert report.issues_found > 0

        categories = [item.category for item in report.critique_items]
        assert "DOCUMENTATION" in categories
        assert "COMPLEXITY" in categories

    def test_clean_code_passes_audit(self):
        critic = SelfRefineCritic()

        clean_code = (
            "def add_numbers(a: int, b: int) -> int:\n"
            "    '''Adds two integers and returns the sum.'''\n"
            "    return a + b\n"
        )

        report = critic.audit_code(clean_code)
        assert report.passed_audit is True
        assert report.issues_found == 0


class TestCapabilityRegistryReflectsNewCapabilities:
    """Verifies that UnifiedCapabilityRegistry incorporates the 4 new capabilities."""

    def test_registry_contains_upgrades(self):
        registry = UnifiedCapabilityRegistry()
        inv = registry.get_canonical_inventory()
        registered_ids = [c["capability_id"] for c in inv["registered"]]

        assert "capability_voyager_skill_library" in registered_ids
        assert "capability_hipporag_memory" in registered_ids
        assert "capability_agent_as_judge" in registered_ids
        assert "capability_self_refine_critic" in registered_ids

        # Ensure all 4 are in CALLABLE state
        callable_ids = [c["capability_id"] for c in inv["callable"]]
        assert "capability_voyager_skill_library" in callable_ids
        assert "capability_hipporag_memory" in callable_ids
        assert "capability_agent_as_judge" in callable_ids
        assert "capability_self_refine_critic" in callable_ids
