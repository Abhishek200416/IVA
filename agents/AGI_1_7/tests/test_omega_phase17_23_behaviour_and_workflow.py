"""AGI 1.7 OMEGA COMMAND — Behavioral Routing & 10-Stage Self-Improvement Regression Suite (Phase 17.23).

Verifies Section 9 requirements:
1. "Update yourself." -> Routes to IMPROVE_YOURSELF without consciousness disclaimers.
2. "Research 50 improvements to your architecture." -> Routes to IMPROVE_YOURSELF.
3. "Study research papers and implement the useful ideas." -> Routes to IMPROVE_YOURSELF.
4. "Improve AGI 1.7 without asking me about every small decision." -> Routes to IMPROVE_YOURSELF.
5. "Explain whether you can modify your underlying model weights." -> Factual technical explanation.
6. "Why did the self-improvement task fail?" -> Diagnostic triage without unneeded start loops.
7. 10-Stage Workflow verification: INTERPRET, AUDIT, RESEARCH, PRIORITIZE, IMPLEMENT, TEST, EVALUATE, CORRECT, RECORD, CONTINUE.
8. Capability registry verification: workflow_omega_self_improvement registered and callable.
9. Safety and live order locking preservation (GATE_01).
"""

import time
import pytest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.runtime.command_router import (
    CommandIntent,
    CommandRouter,
    TradingProfile,
)
from agents.AGI_1_7.engine.agi17.orchestration.omega_self_improvement_workflow import (
    ImprovementObjective,
    OmegaSelfImprovementWorkflow,
    UpgradeTrackRecord,
    WorkflowStage,
    get_omega_self_improvement_workflow,
)
from agents.AGI_1_7.engine.agi17.capabilities.unified_capability_registry import (
    CapabilityDomain,
    CapabilityState,
    get_unified_capability_registry,
)


@pytest.fixture
def router(tmp_path):
    return CommandRouter(storage_dir=tmp_path)


@pytest.fixture
def workflow(tmp_path):
    return OmegaSelfImprovementWorkflow(workspace_root=Path(__file__).resolve().parents[4])


class TestPhase1723BehavioralRouting:
    """Verifies that direct operator commands trigger the appropriate workflow without disclaimers."""

    def test_update_yourself_routes_to_self_improvement(self, router):
        res = router.handle_command("Update yourself.")
        assert res["intent"] == CommandIntent.IMPROVE_YOURSELF.value
        assert res["action"] == "TRIGGER_SELF_IMPROVEMENT"
        assert res["workflow"] == "OMEGA_SELF_IMPROVEMENT"
        # Must start with the affirmative commitment, never passive disclaimers
        assert "Yes. I'll treat this as an autonomous engineering-improvement mission" in res["message"]
        assert "cannot modify" not in res["message"]
        assert "consciousness" not in res["message"]
        assert res["routing_latency_ms"] < 50.0

    def test_research_50_improvements_routes_to_self_improvement(self, router):
        res = router.handle_command("Research 50 improvements to your architecture.")
        assert res["intent"] == CommandIntent.IMPROVE_YOURSELF.value
        assert res["action"] == "TRIGGER_SELF_IMPROVEMENT"
        assert res["workflow"] == "OMEGA_SELF_IMPROVEMENT"
        assert res["routing_latency_ms"] < 50.0

    def test_study_research_papers_routes_to_self_improvement(self, router):
        res = router.handle_command("Study research papers and implement the useful ideas.")
        assert res["intent"] == CommandIntent.IMPROVE_YOURSELF.value
        assert res["action"] == "TRIGGER_SELF_IMPROVEMENT"
        assert res["workflow"] == "OMEGA_SELF_IMPROVEMENT"
        assert res["routing_latency_ms"] < 50.0

    def test_improve_without_asking_routes_to_self_improvement(self, router):
        res = router.handle_command("Improve AGI 1.7 without asking me about every small decision.")
        assert res["intent"] == CommandIntent.IMPROVE_YOURSELF.value
        assert res["action"] == "TRIGGER_SELF_IMPROVEMENT"
        assert res["workflow"] == "OMEGA_SELF_IMPROVEMENT"
        assert res["routing_latency_ms"] < 50.0

    def test_model_weights_question_gives_technical_explanation(self, router):
        res = router.handle_command("Explain whether you can modify your underlying model weights.")
        assert res["intent"] == CommandIntent.EXPLAIN_MODEL_WEIGHTS.value
        assert res["action"] == "EXPLAIN_TECHNICAL_ARCHITECTURE"
        assert res["can_modify_weights"] is False
        assert res["can_modify_codebase"] is True
        assert res["can_modify_memory"] is True
        assert "frozen" in res["message"].lower()
        assert "ast refactoring" in res["message"].lower()

    def test_diagnose_failure_routes_to_triage(self, router):
        res = router.handle_command("Why did the self-improvement task fail?")
        assert res["intent"] == CommandIntent.DIAGNOSE_IMPROVEMENT_FAILURE.value
        assert res["action"] == "DIAGNOSE_FAILURE"
        assert res["diagnostic_target"] == "OMEGA_SELF_IMPROVEMENT"


class TestOmegaSelfImprovementWorkflowStages:
    """Verifies each of the 10 stages in OMEGA_SELF_IMPROVEMENT."""

    def test_stage_a_interpret_comprehensive_command(self, workflow):
        res = workflow.stage_interpret("Research 50 improvements to your architecture and implement them.")
        assert res["stage"] == WorkflowStage.INTERPRET.value
        assert res["objective"] == ImprovementObjective.FULL_CYCLE.value
        assert res["requires_operator_input"] is False

    def test_stage_b_audit_returns_callable_capabilities(self, workflow):
        res = workflow.stage_audit()
        assert res["stage"] == WorkflowStage.AUDIT.value
        assert res["callable_capabilities"] > 100
        assert res["baseline_healthy"] is True
        assert res["active_python"] == "py -3.11"

    def test_stage_c_research_retrieves_primary_citations(self, workflow):
        # ReAct
        c_react = workflow.stage_research("T01")
        assert c_react is not None
        assert "arxiv.org/abs/2210.03629" in c_react.source_url
        assert "ReAct" in c_react.paper_title

        # Reflexion
        c_refl = workflow.stage_research("T23")
        assert c_refl is not None
        assert "arxiv.org/abs/2303.11366" in c_refl.source_url
        assert "Reflexion" in c_refl.paper_title

        # SWE-bench
        c_swe = workflow.stage_research("T41")
        assert c_swe is not None
        assert "arxiv.org/abs/2310.06770" in c_swe.source_url

    def test_stage_d_prioritize_formula_ranking(self, workflow):
        proposals = [
            {"upgrade_id": "T01", "impact": 5.0, "severity": 4.0, "evidence": 5.0, "cost": 1.0, "reversibility": 5.0},
            {"upgrade_id": "T02", "impact": 2.0, "severity": 1.0, "evidence": 2.0, "cost": 4.0, "reversibility": 2.0},
        ]
        ranked = workflow.stage_prioritize(proposals)
        assert len(ranked) == 2
        assert ranked[0]["upgrade_id"] == "T01"
        assert ranked[0]["priority_score"] > ranked[1]["priority_score"]

    def test_stage_e_through_j_execution_cycle(self, workflow):
        track_data = [
            {
                "upgrade_id": "T01",
                "title": "Entry-point Routing Hardening",
                "domain": "A",
                "description": "Zero-disclaimer fast-path router",
                "impact": 5.0,
                "severity": 4.0,
                "evidence": 5.0,
                "cost": 1.0,
                "reversibility": 5.0,
                "files_modified": ["agents/AGI_1_7/engine/agi17/runtime/command_router.py"],
                "acceptance_criteria": ["Deterministic routing < 50ms"],
            }
        ]
        cycle_res = workflow.execute_full_cycle("Update yourself.", track_data)
        assert cycle_res["workflow"] == "OMEGA_SELF_IMPROVEMENT"
        assert cycle_res["status"] == "COMPLETED"
        assert cycle_res["tracks_processed_count"] == 1
        assert len(cycle_res["stages_executed"]) == 10


class TestCapabilityRegistryWorkflowRegistration:
    """Verifies that OMEGA_SELF_IMPROVEMENT is discoverable through UnifiedCapabilityRegistry."""

    def test_workflow_registered_and_callable(self):
        reg = get_unified_capability_registry()
        reg.refresh()
        cap = reg.get_canonical_inventory()
        wf_caps = [c for c in cap["callable"] if c["capability_id"] == "workflow_omega_self_improvement"]
        assert len(wf_caps) == 1
        wf = wf_caps[0]
        assert wf["state"] == CapabilityState.CALLABLE.value
        assert "10-stage" in wf["description"]
        assert "INTERPRET" in wf["metadata"]["stages"]


class TestExistingTradingSafetyPreserved:
    """Ensures Phase 17.20/17.21 trading runtime and GATE_01 invariants are untouched."""

    def test_start_trading_retains_dialogue(self, router):
        res = router.handle_command("Start trading")
        assert res["intent"] == CommandIntent.START_TRADING.value
        assert "Ready to Start Trading System" in res["dialog"]
        assert "Use this configuration" in res["dialog"]

    def test_live_gate_lock_remains_active(self, router):
        profile = router.profile
        assert profile.live_gate_locked is True
        assert profile.is_simulated_capital is True
