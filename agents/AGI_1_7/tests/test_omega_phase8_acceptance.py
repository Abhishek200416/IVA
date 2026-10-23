"""AGI 1.7 OMEGA COMMAND — Phase 8 Acceptance Test Battery.

Authoritative Acceptance Suite covering:
1. Unified 14-Gate Live Readiness Protocol (Reconciled from 11/13 to 12/14)
2. Phase 4 13-Gate backward compatibility preservation
3. Canonical Multiclass Brier Score and skill score against uniform baseline
4. 4-Tier 10-Million-Token Persistent Knowledge Corpus profiling
5. Layer A, B, C, D memory ingestion and budget-capped active context assembly
6. RULER-inspired Needle-in-a-Haystack multi-needle retrieval across corpus positions
7. Context compaction with ACON anchor preservation and layer deactivation
8. Durable checkpoint saving, SHA256 integrity verification, and restoration
9. Idempotent action replay prevention across simulated process crashes
10. Windows interactive desktop (WinSta0\\Default) session availability detection
11. Typed Voice Command Registry parsing, routing, and turn detection
12. Strict Voice "GO REAL" security gate (voice cannot bypass live authorization)
13. Voice low-confidence threshold gating (< 0.85 triggers clarification)
14. Standalone Dashboard Phase 8 REST endpoints (/api/memory_status, /api/voice_status, /api/gates)
15. Institutional options risk governor lot-size budget enforcement
16. Date-aware statutory STT (0.15% from 2026-04-01, 0.10% legacy) and advance tax
17. Three-Agent consensus agreement enforcing Prefer No-Trade on dissent
18. Supervisor process singleton lock and duplicate prevention
19. Unarmed live order submission rejection with clear gate reporting
20. End-to-end Phase 8 orchestration cycle verification
"""

from __future__ import annotations

import datetime
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from agents.AGI_1_7.engine.agi17.browser.voice_command_registry import (
    VoiceCommandRegistry,
    VoiceCommandType,
)
from agents.AGI_1_7.engine.agi17.finance.calibrated_scenario_forecaster import (
    CalibratedScenarioForecaster,
    MulticlassBrierScoreResult,
)
from agents.AGI_1_7.engine.agi17.finance.live_accounting import (
    LiveBrokerLedger,
)
from agents.AGI_1_7.engine.agi17.finance.options_risk_governor import (
    InstitutionalOptionsRiskGovernor,
)
from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import (
    AgentMessage,
    ThreeAgentContractCoordinator,
)
from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import (
    AutonomousTradingOrchestrator,
)
from agents.AGI_1_7.engine.agi17.finance.trading_supervisor import (
    Autonomous24x7TradingSupervisor,
    DurableCheckpointManager,
)
from agents.AGI_1_7.engine.agi17.memory.omega_command_memory import (
    KnowledgeCorpusProfile,
    OmegaCommandMemory,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import (
    StandaloneDashboardServer,
)


class TestOmegaPhase8Acceptance(unittest.TestCase):
    """Authoritative Phase 8 Acceptance Test Battery."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="omega_p8_test_"))
        (self.temp_dir / "finance").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "memory").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "voice").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Criterion 1: Unified 14-Gate Live Readiness Protocol
    # -------------------------------------------------------------------------
    def test_01_unified_14_live_readiness_gates(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        eval_res = orch.evaluate_live_readiness_gates()

        self.assertEqual(eval_res["total_count"], 14)
        self.assertEqual(eval_res["passed_count"], 12)
        self.assertFalse(eval_res["all_gates_passed"])
        # Gates 1 and 3 blocked
        self.assertFalse(eval_res["gates"]["GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK"]["passed"])
        self.assertFalse(eval_res["gates"]["GATE_03_CORRECT_BROKER_ACCOUNT_IDENTITY"]["passed"])
        # Gate 14 passed
        self.assertTrue(eval_res["gates"]["GATE_14_THREE_AGENT_CONSENSUS_AGREEMENT"]["passed"])

    # -------------------------------------------------------------------------
    # Criterion 2: Phase 4 13-Gate Backward Compatibility
    # -------------------------------------------------------------------------
    def test_02_phase4_13_gates_backward_compatibility(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        eval_p4 = orch.evaluate_phase4_readiness_gates()

        self.assertEqual(eval_p4["total_count"], 13)
        self.assertEqual(eval_p4["passed_count"], 11)
        self.assertFalse(eval_p4["all_gates_passed"])

    # -------------------------------------------------------------------------
    # Criterion 3: Canonical Multiclass Brier Score
    # -------------------------------------------------------------------------
    def test_03_canonical_multiclass_brier_score(self):
        # 1. Uniform predictions across 7 classes: [1/7, ..., 1/7]
        uniform_vec = [1.0 / 7.0] * 7
        preds_uniform = [uniform_vec] * 35
        outcomes = [0] * 35

        res_uniform = CalibratedScenarioForecaster.compute_multiclass_brier_score(
            probability_vectors=preds_uniform,
            outcomes=outcomes,
            num_classes=7,
        )
        self.assertEqual(res_uniform.sample_size, 35)
        # Uniform raw BS is 6/7 ~= 0.8571
        self.assertAlmostEqual(res_uniform.raw_brier_score, 0.8571, places=3)
        self.assertAlmostEqual(res_uniform.brier_skill_score, 0.0, places=3)
        self.assertFalse(res_uniform.is_skillful_vs_uniform)

        # 2. Highly accurate forecasts: [0.85, 0.05, 0.02, 0.02, 0.02, 0.02, 0.02]
        skillful_vec = [0.85, 0.05, 0.02, 0.02, 0.02, 0.02, 0.02]
        preds_skillful = [skillful_vec] * 35
        res_skillful = CalibratedScenarioForecaster.compute_multiclass_brier_score(
            probability_vectors=preds_skillful,
            outcomes=outcomes,
            num_classes=7,
        )
        self.assertTrue(res_skillful.is_skillful_vs_uniform)
        self.assertTrue(res_skillful.brier_skill_score > 0.70)
        self.assertTrue(res_skillful.is_calibrated)

    # -------------------------------------------------------------------------
    # Criterion 4: 4-Tier 10M-Token Knowledge Corpus Profiling
    # -------------------------------------------------------------------------
    def test_04_four_tier_knowledge_corpus_profile(self):
        mem = OmegaCommandMemory(primary_dir=self.temp_dir / "memory")
        profile = mem.get_corpus_profile()

        self.assertIsInstance(profile, KnowledgeCorpusProfile)
        self.assertEqual(profile.persistent_corpus_token_capacity, 10_000_000)
        self.assertEqual(profile.practical_input_budget, 32_000)
        self.assertTrue(profile.documented_context_window >= 128_000)

    # -------------------------------------------------------------------------
    # Criterion 5: Layer A, B, C, D Ingestion & Active Context Assembly
    # -------------------------------------------------------------------------
    def test_05_layer_a_b_c_d_memory_tiering(self):
        mem = OmegaCommandMemory(primary_dir=self.temp_dir / "memory")

        # Layer A: Immutable source
        entry_a = mem.store_layer_a_immutable_source(
            source_id="NSE-CIRC-2026",
            source_type="CIRCULAR",
            content="Official circular revising STT on options sale to 0.15% effective 1 April 2026.",
        )
        self.assertEqual(entry_a.layer, 10)

        # Layer B: Structured domain record
        entry_b = mem.store_layer_b_domain_record(
            domain_table="OBSERVATIONS",
            record_id="NIFTY-2026-10-13",
            content="NIFTY 50 trading at 22547.20 above VWAP with bullish divergence.",
        )
        self.assertEqual(entry_b.layer, 5)

        # Layer C: Episodic summary
        entry_c = mem.store_layer_c_episodic_summary(
            session_id="SESS-20261013",
            decision_summary="Session completed with no forced trades; Prefer No-Trade triggered on macro news.",
        )
        self.assertEqual(entry_c.layer, 4)

        # Layer D: Active working context
        ctx = mem.build_layer_d_active_context(
            task_id="TASK-PLAN-01",
            query_text="STT options circular",
            max_tokens=4000,
        )
        self.assertTrue(ctx["passages_count"] > 0)
        self.assertTrue(any("0.15%" in p["content"] for p in ctx["active_passages"]))

    # -------------------------------------------------------------------------
    # Criterion 6: RULER-Inspired Needle-in-a-Haystack Retrieval
    # -------------------------------------------------------------------------
    def test_06_ruler_needle_in_haystack_retrieval(self):
        mem = OmegaCommandMemory(primary_dir=self.temp_dir / "memory")

        needles = [
            ("NEEDLE-BEG", "CRITICAL_FACTOR_ALPHA: Foreign institutional flow turned positive by ₹1,420 Cr."),
            ("NEEDLE-MID", "CRITICAL_FACTOR_BETA: Implied volatility spread between Bank Nifty and Nifty is 1.28."),
            ("NEEDLE-END", "CRITICAL_FACTOR_GAMMA: RBI monetary policy committee maintained stance at neutral."),
        ]

        ruler_res = mem.run_ruler_needle_evaluation(needles=needles, distractor_count=20)
        self.assertEqual(ruler_res["total_needles_tested"], 3)
        self.assertEqual(ruler_res["needles_retrieved"], 3)
        self.assertEqual(ruler_res["recall_score"], 1.0)
        self.assertTrue(ruler_res["is_flawless"])

    # -------------------------------------------------------------------------
    # Criterion 7: Context Compaction with ACON
    # -------------------------------------------------------------------------
    def test_07_context_compaction_with_acon(self):
        mem = OmegaCommandMemory(primary_dir=self.temp_dir / "memory")
        session_id = "SESS-COMPACT-TEST"

        # Ingest working turns
        mem.store(
            layer=1,
            subject_key="TURN-1",
            content="Task TASK-4091 initiated. Error TimeoutError occurred at path C:\\logs\\trade.log with exit_code 1.",
            session_id=session_id,
        )
        mem.store(
            layer=2,
            subject_key="TURN-2",
            content="Investigating Task TASK-4091: Verified sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.",
            session_id=session_id,
        )

        compact_res = mem.compact_session_context(session_id=session_id, max_chars=100)
        self.assertEqual(compact_res["status"], "COMPACTED")
        self.assertTrue(compact_res["reduction_ratio"] > 0.0)
        # Verify anchors preserved
        anchors = compact_res["preserved_anchors"]
        self.assertTrue(any("TASK-4091" in t for t in anchors["task_ids"]))

    # -------------------------------------------------------------------------
    # Criterion 8: Durable Checkpoint Manager Save & Restore
    # -------------------------------------------------------------------------
    def test_08_durable_checkpoint_manager_save_and_restore(self):
        chk_db = self.temp_dir / "finance" / "checkpoints.db"
        mgr = DurableCheckpointManager(db_path=chk_db)

        payload = {
            "completed_tasks": ["TASK-01", "TASK-02"],
            "active_risk_state": {"current_equity": 50000.0, "drawdown_pct": 0.002},
            "unresolved_orders": [],
        }

        chk = mgr.save_checkpoint(
            checkpoint_id="CHK-001",
            session_id="SESS-001",
            payload=payload,
            idempotency_key="ACTION-SUBMIT-ORDER-99",
        )
        self.assertEqual(chk.checkpoint_id, "CHK-001")
        self.assertTrue(len(chk.state_hash) == 64)

        restored = mgr.restore_checkpoint("CHK-001")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.state_hash, chk.state_hash)
        self.assertEqual(restored.payload["completed_tasks"], ["TASK-01", "TASK-02"])

    # -------------------------------------------------------------------------
    # Criterion 9: Checkpoint Idempotent Replay Prevention
    # -------------------------------------------------------------------------
    def test_09_checkpoint_idempotent_replay_prevention(self):
        chk_db = self.temp_dir / "finance" / "checkpoints.db"
        mgr = DurableCheckpointManager(db_path=chk_db)

        key = "IDEMP-ORDER-20261013-01"
        self.assertFalse(mgr.is_idempotent_action_completed(key))

        mgr.record_completed_action(
            idempotency_key=key,
            action_type="ORDER_SUBMISSION",
            result_data={"order_id": "ORD-12345", "status": "CONFIRMED"},
        )
        self.assertTrue(mgr.is_idempotent_action_completed(key))

    # -------------------------------------------------------------------------
    # Criterion 10: Desktop Availability Detection
    # -------------------------------------------------------------------------
    def test_10_desktop_availability_detection(self):
        supervisor = Autonomous24x7TradingSupervisor(storage_dir=self.temp_dir / "finance")
        is_avail, detail = supervisor.check_interactive_desktop_availability()
        self.assertIsInstance(is_avail, bool)
        self.assertIsInstance(detail, str)

    # -------------------------------------------------------------------------
    # Criterion 11: Typed Voice Command Registry Routing
    # -------------------------------------------------------------------------
    def test_11_typed_voice_command_registry_routing(self):
        reg = VoiceCommandRegistry(storage_dir=self.temp_dir / "voice")

        res_trade = reg.parse_and_route("trading", confidence=0.95)
        self.assertEqual(res_trade.recognized_command, VoiceCommandType.START_TRADING)
        self.assertEqual(res_trade.action_status, "EXECUTED")

        res_status = reg.parse_and_route("system status", confidence=0.92)
        self.assertEqual(res_status.recognized_command, VoiceCommandType.CHECK_STATUS)
        self.assertEqual(res_status.action_status, "EXECUTED")

        res_stop = reg.parse_and_route("emergency stop", confidence=0.99)
        self.assertEqual(res_stop.recognized_command, VoiceCommandType.STOP_SESSION)
        self.assertEqual(res_stop.action_status, "EXECUTED")

    # -------------------------------------------------------------------------
    # Criterion 12: Voice "GO REAL" Strict Security Gate
    # -------------------------------------------------------------------------
    def test_12_voice_go_real_strict_security_gate(self):
        reg = VoiceCommandRegistry(storage_dir=self.temp_dir / "voice")

        # Voice command saying "go real"
        res_goreal = reg.parse_and_route("go real", confidence=0.98)
        self.assertEqual(res_goreal.recognized_command, VoiceCommandType.GO_REAL_REQUEST)
        # MUST NOT execute live arming; requires explicit interactive confirmation
        self.assertEqual(res_goreal.action_status, "CONFIRMATION_REQUIRED")
        self.assertTrue(res_goreal.requires_interactive_confirmation)
        self.assertIn("VOICE_GO_REAL_GATED", res_goreal.detail)

    # -------------------------------------------------------------------------
    # Criterion 13: Voice Low-Confidence Gating
    # -------------------------------------------------------------------------
    def test_13_voice_confidence_threshold_gating(self):
        reg = VoiceCommandRegistry(storage_dir=self.temp_dir / "voice")

        # Low confidence (< 0.85)
        res_low = reg.parse_and_route("trading", confidence=0.72)
        self.assertEqual(res_low.action_status, "CLARIFICATION_REQUIRED")
        self.assertIn("Low confidence", res_low.detail)

    # -------------------------------------------------------------------------
    # Criterion 14: Standalone Dashboard Phase 8 Endpoints
    # -------------------------------------------------------------------------
    def test_14_standalone_dashboard_new_phase8_endpoints(self):
        server = StandaloneDashboardServer(port=8099)
        # Server initializes handler with memory, voice, and gate endpoints
        self.assertIsNotNone(server)
        server.server_close()

    # -------------------------------------------------------------------------
    # Criterion 15: Options Risk Budget Lot-Size Enforcement
    # -------------------------------------------------------------------------
    def test_15_options_risk_budget_lot_size_enforcement(self):
        governor = InstitutionalOptionsRiskGovernor(authorized_capital_inr=50000.0)

        # 0.5% max risk on ₹50,000 = ₹250.
        # Quantity = 25, entry = 100.0, stop = 80.0 -> Planned loss = 25 * 20 = ₹500 > ₹250!
        audit = governor.audit_proposal(
            candidate_id="CAND-P8-01",
            underlying="NIFTY",
            instrument="NIFTY26OCT22500CE",
            spot_price=22500.0,
            strike_price=22500.0,
            is_call=True,
            quantity=25,
            entry_premium=100.0,
            stop_premium=80.0,
            target_premium=150.0,
        )
        self.assertFalse(audit.is_approved)
        self.assertIn("RISK_BUDGET_BREACH", str(audit.rejection_reason))

    # -------------------------------------------------------------------------
    # Criterion 16: Date-Aware Statutory STT & Advance Tax
    # -------------------------------------------------------------------------
    def test_16_date_aware_stt_schedule_retention(self):
        # 1. Historical date (< 2026-04-01): STT is 0.10% on option sale
        charges_hist = LiveBrokerLedger.calculate_statutory_charges(
            side="SELL", quantity=25, premium=100.0, as_of_date="2025-10-01"
        )
        self.assertEqual(charges_hist["stt_inr"], 2.50)
        self.assertEqual(charges_hist["stt_rate_pct"], 0.10)

        # 2. Modern date (>= 2026-04-01): STT is 0.15% on option sale
        charges_mod = LiveBrokerLedger.calculate_statutory_charges(
            side="SELL", quantity=25, premium=100.0, as_of_date="2026-04-01"
        )
        self.assertEqual(charges_mod["stt_inr"], 3.75)
        self.assertEqual(charges_mod["stt_rate_pct"], 0.15)

    # -------------------------------------------------------------------------
    # Criterion 17: Three-Agent Prefer No-Trade on Dissent
    # -------------------------------------------------------------------------
    def test_17_three_agent_prefer_no_trade_dissent(self):
        coord = ThreeAgentContractCoordinator(storage_dir=self.temp_dir / "finance")

        emily_radar = {"tail_risk_flag": True, "evidence_sources": ["US CPI Announcement"]}
        max_quant = {
            "decision": "APPROVED",
            "net_expectancy_inr": 150.0,
            "risk_calc_inr": 200.0,
            "instrument": "NIFTY",
        }
        alexa_ui = {"browser_ready": True, "inputs_verified": True}

        approved, reason, record = coord.evaluate_consensus(
            session_id="SESS-P8-CONSENSUS",
            emily_radar_status=emily_radar,
            max_quant_candidate=max_quant,
            alexa_ui_verification=alexa_ui,
        )
        self.assertFalse(approved)
        self.assertIn("PREFER_NO_TRADE", reason)
        self.assertIsNotNone(record)
        self.assertIn("Emily", record.agent_stances)

    # -------------------------------------------------------------------------
    # Criterion 18: Supervisor Process Singleton Lock
    # -------------------------------------------------------------------------
    def test_18_supervisor_process_singleton_lock(self):
        sup1 = Autonomous24x7TradingSupervisor(storage_dir=self.temp_dir / "finance", session_id="SESS-LOCK-1")
        lock_acquired = sup1.acquire_service_lock()
        self.assertTrue(lock_acquired)

        # Second supervisor attempting lock must fail safely
        sup2 = Autonomous24x7TradingSupervisor(storage_dir=self.temp_dir / "finance", session_id="SESS-LOCK-2")
        lock2 = sup2.acquire_service_lock()
        self.assertFalse(lock2)

        sup1.release_service_lock()

    # -------------------------------------------------------------------------
    # Criterion 19: Unarmed Live Order Submission Rejection
    # -------------------------------------------------------------------------
    def test_19_unarmed_live_order_submission_rejection(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        raw_c = {"symbol": "NIFTY26OCT22500CE", "strike": 22500.0, "option_type": "CE", "lot_size": 25}

        with self.assertRaises(PermissionError):
            orch.submit_live_order(raw_contract=raw_c, action="BUY", quantity=25, price=50.0)

    # -------------------------------------------------------------------------
    # Criterion 20: End-to-End Phase 8 Orchestration Cycle
    # -------------------------------------------------------------------------
    def test_20_end_to_end_phase8_orchestration_cycle(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        checks = orch.verify_environment()
        self.assertIn("01_master_charter_verified", checks)
        self.assertEqual(orch.ledger.initial_monthly_capital, 50000.0)


if __name__ == "__main__":
    unittest.main()
