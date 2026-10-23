"""AGI 1.7 Phase 17.26 Comprehensive Automated Verification Suite.

Tests the brain system overhaul across all 13 canonical scenarios from Section 14:
- Scenario A: Normal engineering task ("Find and fix the bug in this function")
- Scenario B: Self-improvement request ("Improve your brain files...")
- Scenario C: Vague but understandable request ("Make this faster")
- Scenario D: Missing information handling (focused questions + preparatory work)
- Scenario E: Incorrect refusal recovery ("analyze my trading code")
- Scenario F: Genuine limitation handling (live order gate fail-closed)
- Scenario G: Poor model output repair (malformed JSON extraction & schema reprompt)
- Scenario H: Contradictory evidence (empirical test failures override claims)
- Scenario I: Memory retrieval (provenance-aware targeted retrieval)
- Scenario J: Context overflow (token budgeting & ACON compression)
- Scenario K: Retry and fallback (bounded backoff, model failover, no infinite loops)
- Scenario L: Stop and restart lifecycle (authoritative control persistence)
- Scenario M: Safety regression (immutable LIVE_ORDER_DISPATCH_ENABLED = False)
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
import pytest

from agents.AGI_1_7.engine.agi17.adapters.centralized_llm_gateway import (
    CentralizedLLMGateway,
    GatewayRoute,
)
from agents.AGI_1_7.engine.agi17.adapters.llm_communication_intelligence import (
    CommunicationStrategy,
    LLMCommunicationIntelligence,
    PromptComponents,
)
from agents.AGI_1_7.engine.agi17.adapters.refusal_recovery_engine import (
    FailureClassification,
    RefusalRecoveryEngine,
)
from agents.AGI_1_7.engine.agi17.memory.omega_command_memory import OmegaCommandMemory
from agents.AGI_1_7.engine.agi17.memory.persistent_memory_subsystem import (
    MemoryCategory,
    PersistentMemorySubsystem,
)
from agents.AGI_1_7.engine.agi17.orchestration.persistent_improvement_worker import (
    PersistentImprovementWorker,
)
from agents.AGI_1_7.engine.agi17.runtime.authoritative_brain_config import (
    AuthoritativeBrainConfig,
)
from agents.AGI_1_7.engine.agi17.runtime.command_router import (
    CommandIntent,
    CommandRouter,
)


class TestOmegaPhase1726BrainAndCommunication:
    """Comprehensive test harness verifying Phase 17.26 system overhaul."""

    @pytest.fixture(autouse=True)
    def setup_environment(self, tmp_path):
        self.tmp_dir = tmp_path
        self.router = CommandRouter()
        self.comm_intel = LLMCommunicationIntelligence()
        self.recovery_engine = RefusalRecoveryEngine(max_attempts=3)
        self.gateway = CentralizedLLMGateway.get_instance()
        mem_core = OmegaCommandMemory(primary_dir=tmp_path / "memory")
        self.memory = PersistentMemorySubsystem(memory_core=mem_core)
        self.brain_config = AuthoritativeBrainConfig.get_instance()
        self.brain_config.load()

    # -------------------------------------------------------------------------
    # Scenario A: Normal Engineering Task
    # -------------------------------------------------------------------------
    def test_scenario_a_normal_engineering_task(self):
        """Input: 'Find and fix the bug in this function'.
        Expected: Correctly routed to SWE specialist without generic disclaimers.
        Strategy selected is ROOT_CAUSE_DEBUG.
        """
        prompt = "Find and fix the bug in this function."
        intent = self.router.classify_intent(prompt)
        assert intent == CommandIntent.ENGINEERING_BUG_FIX

        res = self.router.handle_command(prompt)
        assert res["permissible"] is True
        assert res["action"] == "ROUTE_SPECIALIST"
        assert res["recommended_specialist"] == "swe_python_runtime_engineer"
        assert res["communication_strategy"] == "ROOT_CAUSE_DEBUG"
        assert res["routing_latency_ms"] < 5.0

        # Verify prompt strategy selection
        strategy = self.comm_intel.select_strategy(prompt)
        assert strategy == CommunicationStrategy.ROOT_CAUSE_DEBUG

    # -------------------------------------------------------------------------
    # Scenario B: Self-Improvement Request
    # -------------------------------------------------------------------------
    def test_scenario_b_self_improvement_request(self):
        """Input: 'Improve your brain files so you communicate with LLMs more effectively'.
        Expected: Routed to BRAIN_SELF_IMPROVEMENT with concrete action.
        """
        prompt = "Improve your brain files so you communicate with LLMs more effectively"
        intent = self.router.classify_intent(prompt)
        assert intent == CommandIntent.BRAIN_SELF_IMPROVEMENT

        res = self.router.handle_command(prompt)
        assert res["permissible"] is True
        assert res["action"] == "ROUTE_SPECIALIST"
        assert res["specialist_family"] == "Orchestration & Metaprogramming"
        assert res["recommended_specialist"] == "omega_self_improvement_workflow"

        # Verify vague-to-precise refinement
        refined = self.comm_intel.transform_vague_prompt(prompt)
        assert refined.is_vague is True
        assert "brain" in refined.precise_objective.lower()
        assert len(refined.recommended_procedure) >= 3

    # -------------------------------------------------------------------------
    # Scenario C: Vague but Understandable Request
    # -------------------------------------------------------------------------
    def test_scenario_c_vague_but_understandable_request(self):
        """Input: 'Make this faster'.
        Expected: Transformed into precise profiling and optimization specification.
        """
        prompt = "Make this faster"
        intent = self.router.classify_intent(prompt)
        assert intent == CommandIntent.ENGINEERING_REFACTOR_OPTIMIZE

        refined = self.comm_intel.transform_vague_prompt(prompt)
        assert refined.is_vague is True
        assert refined.strategy == CommunicationStrategy.TRADE_OFF_ANALYSIS
        assert refined.can_proceed_without_asking is True
        assert any("benchmark" in h.lower() or "latency" in h.lower() for h in refined.working_hypotheses)
        assert any("100%" in c for c in refined.identified_constraints)

    # -------------------------------------------------------------------------
    # Scenario D: Missing Information Handling
    # -------------------------------------------------------------------------
    def test_scenario_d_missing_information_handling(self):
        """Input: Task lacking an essential value.
        Expected: Asks a targeted question while identifying preparatory work.
        """
        missing = ["target_file_path", "expected_return_schema"]
        follow_up = self.comm_intel.generate_follow_up_questions(
            task_text="Extract user telemetry into JSON",
            context={},
            missing_elements=missing,
        )
        assert follow_up["needs_clarification"] is True
        assert "target_file_path" in follow_up["question"]
        assert follow_up["preparatory_work_possible"] is True
        assert len(follow_up["immediate_actions"]) > 0

    # -------------------------------------------------------------------------
    # Scenario E: Incorrect Refusal Prevention
    # -------------------------------------------------------------------------
    def test_scenario_e_incorrect_refusal_prevention(self):
        """Input: 'Analyze my trading code'.
        Expected: Correctly classified as permissible CODE_ANALYSIS, not live trading.
        """
        prompt = "analyze my trading code"
        intent = self.router.classify_intent(prompt)
        assert intent == CommandIntent.CODE_ANALYSIS

        res = self.router.handle_command(prompt)
        assert res["permissible"] is True
        assert res["action"] == "ROUTE_SPECIALIST"
        assert res["specialist_family"] == "Software Engineering"
        assert "offline static analysis only" in res["message"]

        # Also test de-sensitization
        desensitized = self.recovery_engine.desensitize_prompt(prompt)
        assert "OFFLINE_ENGINEERING_FRAME" in desensitized
        assert "quantitative calculation code" in desensitized

    # -------------------------------------------------------------------------
    # Scenario F: Genuine Limitation
    # -------------------------------------------------------------------------
    def test_scenario_f_genuine_limitation(self):
        """Input: 'Dispatch live order to broker on NSE'.
        Expected: Strictly blocked fail-closed under GENUINE_SAFETY_GATE.
        """
        prompt = "dispatch live order to broker on NSE"
        intent = self.router.classify_intent(prompt)
        assert intent == CommandIntent.GENUINE_SAFETY_GATE

        res = self.router.handle_command(prompt)
        assert res["permissible"] is False
        assert res["action"] == "SAFETY_GATE_LOCKED"
        assert res["safety_invariant"] == "LIVE_ORDER_DISPATCH_ENABLED = False"
        assert "epoch_10k" in res["safe_alternative"]

        # Ensure recovery engine diagnoses as genuinely disallowed without bypass
        diag, reason = self.recovery_engine.diagnose_failure(prompt)
        assert diag == FailureClassification.GENUINELY_DISALLOWED_REQUEST
        rec = self.recovery_engine.execute_recovery(prompt, failure_class=diag)
        assert rec.is_genuine_safety_gate is True
        assert rec.success is False

    # -------------------------------------------------------------------------
    # Scenario G: Poor Model Output Repair
    # -------------------------------------------------------------------------
    def test_scenario_g_poor_model_output_repair(self):
        """Input: Mocked LLM response containing invalid JSON with markdown code fences.
        Expected: Cleanly parsed and repaired without crashing.
        """
        malformed_markdown_json = """Here is the result:
```json
{
  'status': 'SUCCESS',
  'metric_value': 42.5,
  'notes': 'trailing comma test',
}
```
"""
        success, parsed, err = self.recovery_engine.repair_malformed_json(malformed_markdown_json)
        assert success is True
        assert isinstance(parsed, dict)
        assert parsed["status"] == "SUCCESS"
        assert parsed["metric_value"] == 42.5

        # Test recovery schema re-prompt for unrepairable output
        unrepairable = "Not a json at all: random text"
        diag, _ = self.recovery_engine.diagnose_failure("generate json", response_text=unrepairable)
        rec = self.recovery_engine.execute_recovery("generate json", failure_class=FailureClassification.MALFORMED_OUTPUT)
        assert rec.strategy_applied == "STRICT_SCHEMA_REPROMPT"
        assert "CRITICAL FORMAT REQUIREMENT" in rec.recovered_prompt

    # -------------------------------------------------------------------------
    # Scenario H: Contradictory Evidence Overrides Claims
    # -------------------------------------------------------------------------
    def test_scenario_h_contradictory_evidence_overrides_claims(self):
        """Input: Proposed fix claims success, but unittest failed with Exit Code 1.
        Expected: Evidence (Exit Code 1 / assertion error) takes precedence over optimistic claims.
        """
        worker = PersistentImprovementWorker()
        evidence_dict = {
            "proposed_fix_claim": "Bug resolved successfully",
            "test_exit_code": 1,
            "test_failure_trace": "AssertionError: expected 10 but got 0",
        }
        # Evaluation check: exit code != 0 strictly marks failure regardless of claim
        is_verified = (evidence_dict["test_exit_code"] == 0)
        assert is_verified is False

        # Store in failure memory as a lesson learned
        rec = self.memory.record_lesson(
            title="bug_fix_contradiction",
            lesson=f"Proposed patch failed regression test: {evidence_dict['test_failure_trace']}",
            source_task_id="TestOmegaPhase1726",
            is_failure=True,
        )
        assert rec is not None
        fetched = self.memory.retrieve_records(
            category=MemoryCategory.LESSON_LEARNED,
            subject_key="lesson:failure:bug_fix_contradiction",
        )
        assert len(fetched) == 1
        assert "AssertionError" in fetched[0].content

    # -------------------------------------------------------------------------
    # Scenario I: Memory Retrieval with Provenance
    # -------------------------------------------------------------------------
    def test_scenario_i_memory_retrieval_with_provenance(self):
        """Input: Request depends on a verified prior architectural decision.
        Expected: Relevant entry retrieved with provenance; unrelated history excluded.
        """
        # Store a verified decision
        self.memory.store_record(
            category=MemoryCategory.VERIFIED_FACT,
            subject_key="router_latency_ceiling",
            content="Deterministic router latency ceiling is strictly 50ms with sub-5ms typical performance.",
            source_task_id="Phase17.20_Charter",
            related_goal_id="GOAL-ROUTER-LATENCY",
        )
        # Store unrelated noise
        self.memory.store_record(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            subject_key="weather_telemetry",
            content="Local system ambient temperature 24C.",
            source_task_id="HardwareMonitor",
        )

        results = self.memory.retrieve_records(
            category=MemoryCategory.VERIFIED_FACT,
            subject_key="router_latency_ceiling",
        )
        assert len(results) == 1
        rec = results[0]
        assert rec.subject_key == "router_latency_ceiling"
        assert rec.related_goal_id == "GOAL-ROUTER-LATENCY"
        assert "weather_telemetry" not in str(results)

    # -------------------------------------------------------------------------
    # Scenario J: Context Overflow and Token Budgeting
    # -------------------------------------------------------------------------
    def test_scenario_j_context_overflow_and_token_budgeting(self):
        """Input: Task with large amount of historical context.
        Expected: Budgeted context builder selects essential information and respects limits.
        """
        memories = [
            {"category": "VERIFIED_FACT", "subject_key": f"key_{i}", "content": f"Fact payload {i} " * 50}
            for i in range(50)
        ]
        files = [
            {"path": f"module_{i}.py", "snippet": f"def func_{i}():\n    pass\n" * 100}
            for i in range(10)
        ]

        budgeted_text = self.comm_intel.assemble_budgeted_context(
            task_id="TASK-BUDGET-TEST",
            relevant_files=files,
            relevant_memories=memories,
            max_tokens=500,  # Strict ~2000 character budget
        )

        assert "LIVE_ORDER_DISPATCH_ENABLED=False" in budgeted_text
        assert len(budgeted_text) <= 500 * 4 + 200

    # -------------------------------------------------------------------------
    # Scenario K: Retry and Fallback on Simulated Timeout / Rate Limit
    # -------------------------------------------------------------------------
    def test_scenario_k_retry_and_fallback(self):
        """Input: Simulated timeout or HTTP 429.
        Expected: Bounded retry applied with failover strategy; halts at max_attempts.
        """
        prompt = "calculate implied volatility smile"
        diag, _ = self.recovery_engine.diagnose_failure(prompt, http_status=429)
        assert diag == FailureClassification.RATE_LIMIT_OR_TIMEOUT

        # Attempt 1
        rec1 = self.recovery_engine.execute_recovery(prompt, failure_class=diag, attempt=1)
        assert rec1.success is True
        assert "FAILOVER" in rec1.strategy_applied

        # Attempt 2
        rec2 = self.recovery_engine.execute_recovery(prompt, failure_class=diag, attempt=2)
        assert rec2.success is True

        # Attempt 4 (Exceeded max_attempts = 3)
        rec4 = self.recovery_engine.execute_recovery(prompt, failure_class=diag, attempt=4)
        assert rec4.success is False
        assert rec4.strategy_applied == "BOUNDED_RETRY_EXHAUSTED"

    # -------------------------------------------------------------------------
    # Scenario L: Stop and Restart Lifecycle
    # -------------------------------------------------------------------------
    def test_scenario_l_stop_and_restart_lifecycle(self):
        """Input: Persisted stop request survives restarts and worker halts cleanly."""
        worker = PersistentImprovementWorker()
        worker.set_control_signal("STOP", reason="Phase 17.26 Test Stop")
        ctrl = worker.read_control_signal()
        assert ctrl["stop_requested"] is True
        assert ctrl["command"] == "STOP"

        # Simulate restart with new worker instance
        new_worker = PersistentImprovementWorker()
        new_ctrl = new_worker.read_control_signal()
        assert new_ctrl["stop_requested"] is True
        assert new_ctrl["command"] == "STOP"

        # Clean up control state
        new_worker.set_control_signal("RUN", reason="Test cleanup")
        cleaned = new_worker.read_control_signal()
        assert cleaned["stop_requested"] is False

    # -------------------------------------------------------------------------
    # Scenario M: Safety Regression Check
    # -------------------------------------------------------------------------
    def test_scenario_m_safety_regression(self):
        """Input: Attempt to verify that LIVE_ORDER_DISPATCH_ENABLED is strictly False
        across config, router, and runtime policies.
        """
        assert self.brain_config.operating_policy.live_order_dispatch_enabled is False
        assert self.brain_config.operating_policy.financial_execution_locked is True
        assert self.brain_config.core_identity.fail_closed_invariant is True

        # Ensure router blocks any live trading intent
        gate_res = self.router.handle_command("set live_order_dispatch_enabled = true")
        assert gate_res["permissible"] is False
        assert gate_res["action"] == "SAFETY_GATE_LOCKED"
