"""AGI 1.7 OMEGA COMMAND — Phase 14 Production Control Plane Verification Suite.

Validates:
- Category A: Trading Command Intent Detection & Conversational Disambiguation
- Category B: Universal 10-Question Trading Intent Intake Questionnaire Workflow
- Category C: Financial Safety, Risk Limits Clamping & Strategy Permission Invariants
- Category D: 11-State Formal Lifecycle State Machine & Transition Guards
- Category E: Comprehensive 12-Point System & Market Data Preflight Auditor
- Category F: Persistence, Audit Trail Logging, and Process Crash Recovery
- Category G: Standalone Dashboard Server Control Plane REST Endpoints & Chat Delegation
"""

import dataclasses
import datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from agents.AGI_1_7.engine.agi17.finance.trading_session_control_plane import (
    SessionState,
    OperatorIntent,
    VALID_STATE_TRANSITIONS,
    TradingCommandDetector,
    TradingSessionConfig,
    TradingSessionConfigValidator,
    IntakeQuestion,
    INTAKE_QUESTIONS,
    TradingIntentIntakeController,
    PreflightCheckResult,
    PreflightReport,
    SessionPreflightService,
    SessionStore,
    TradingSessionSupervisor,
    REGISTERED_STRATEGIES,
    PAPER_ALLOWED_STRATEGY_IDS,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestPhase14ControlPlane(unittest.TestCase):
    """Phase 14 Master Control Plane Test Suite."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SessionStore(base_dir=Path(self.temp_dir))
        self.supervisor = TradingSessionSupervisor(store=self.store)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Category A: Command Intent Detection & Disambiguation
    # -------------------------------------------------------------------------

    def test_start_session_intents_detected(self):
        start_phrases = [
            "Start trading",
            "start paper trading",
            "Begin today's session",
            "Start using maximum capabilities",
            "launch paper trading",
            "deploy agents",
            "begin paper trading",
            "run paper trading",
            "I want you to start trading",
            "Please start trading",
            "let's start trading",
        ]
        for phrase in start_phrases:
            intent, params = TradingCommandDetector.detect_intent(phrase, SessionState.IDLE)
            self.assertEqual(
                intent,
                OperatorIntent.START_SESSION,
                f"Failed to detect START_SESSION for phrase: '{phrase}'"
            )

    def test_aggressive_flag_captured_on_start(self):
        phrase = "Start using maximum capabilities and full capital"
        intent, params = TradingCommandDetector.detect_intent(phrase, SessionState.IDLE)
        self.assertEqual(intent, OperatorIntent.START_SESSION)
        self.assertTrue(params.get("aggressive_flag"))

    def test_conversational_questions_do_not_trigger_start(self):
        inquiries = [
            "What is the purpose of trading options?",
            "Why do we need a Paytm API key?",
            "How does Kelly sizing work in this system?",
            "Can you explain your algorithms and memory catalog?",
            "What happens if there are mistakes?",
            "Tell me about the market depth?",
        ]
        for query in inquiries:
            intent, _ = TradingCommandDetector.detect_intent(query, SessionState.IDLE)
            self.assertEqual(
                intent,
                OperatorIntent.CONVERSATIONAL_ONLY,
                f"Conversational query was mistakenly classified: '{query}' -> {intent}"
            )

    def test_operational_control_intents_detected(self):
        controls = {
            "pause trading": OperatorIntent.PAUSE_SESSION,
            "pause session": OperatorIntent.PAUSE_SESSION,
            "pause": OperatorIntent.PAUSE_SESSION,
            "resume trading": OperatorIntent.RESUME_SESSION,
            "resume": OperatorIntent.RESUME_SESSION,
            "stop trading": OperatorIntent.STOP_SESSION,
            "stop session": OperatorIntent.STOP_SESSION,
            "emergency stop": OperatorIntent.EMERGENCY_STOP,
            "panic stop": OperatorIntent.EMERGENCY_STOP,
            "kill all": OperatorIntent.EMERGENCY_STOP,
            "confirm paper session": OperatorIntent.CONFIRMATION,
            "CONFIRM PAPER SESSION": OperatorIntent.CONFIRMATION,
            "confirm research session": OperatorIntent.CONFIRMATION,
            "use defaults": OperatorIntent.LOAD_DEFAULTS,
            "load defaults": OperatorIntent.LOAD_DEFAULTS,
            "session status": OperatorIntent.STATUS_QUERY,
            "edit 3": OperatorIntent.EDIT_SETTING,
            "change question 5": OperatorIntent.EDIT_SETTING,
        }
        for text, expected in controls.items():
            intent, _ = TradingCommandDetector.detect_intent(text, SessionState.IDLE)
            self.assertEqual(intent, expected, f"Failed for '{text}': expected {expected}, got {intent}")

    # -------------------------------------------------------------------------
    # Category B: 10-Question Intake Questionnaire Engine
    # -------------------------------------------------------------------------

    def test_all_10_questions_defined_with_defaults(self):
        self.assertEqual(len(INTAKE_QUESTIONS), 10)
        expected_keys = [
            "session_type",
            "operation_schedule",
            "instruments_and_strategies",
            "trade_caps",
            "portfolio_epoch",
            "operating_profile",
            "risk_limits",
            "profit_objective",
            "failure_behavior",
            "reporting_preference",
        ]
        actual_keys = [q.key for q in INTAKE_QUESTIONS]
        self.assertEqual(actual_keys, expected_keys)
        for q in INTAKE_QUESTIONS:
            self.assertIsNotNone(q.default_value)
            self.assertTrue(len(q.options) >= 2)

    def test_progressive_answering_workflow(self):
        controller = TradingIntentIntakeController()
        self.assertEqual(controller.current_question_index, 0)
        self.assertFalse(controller.is_completed)

        # Answer Q1 through Q9
        for i in range(9):
            q_info = controller.get_current_question()
            self.assertEqual(q_info["question_index"], i + 1)
            res = controller.process_answer("1")  # select option 1
            self.assertEqual(res["status"], "ADVANCED")

        # Answer Q10
        q10_info = controller.get_current_question()
        self.assertEqual(q10_info["question_index"], 10)
        res10 = controller.process_answer("1")
        self.assertEqual(res10["status"], "COMPLETED")
        self.assertTrue(controller.is_completed)
        self.assertIsNotNone(controller.cached_config)
        self.assertTrue(len(controller.cached_config.config_hash) > 20)

    def test_safe_defaults_loader(self):
        controller = TradingIntentIntakeController()
        res = controller.load_safe_defaults()
        self.assertEqual(res["status"], "COMPLETED")
        self.assertTrue(controller.is_completed)
        cfg = controller.cached_config
        self.assertEqual(cfg.portfolio_epoch, "epoch_10k")
        self.assertEqual(cfg.allocated_capital_inr, 10000.0)
        self.assertEqual(cfg.max_capital_risk_per_trade_pct, 0.5)
        self.assertEqual(cfg.max_daily_drawdown_pct, 1.5)

    def test_edit_specific_question(self):
        controller = TradingIntentIntakeController()
        controller.load_safe_defaults()
        self.assertTrue(controller.is_completed)

        # Edit question 5 (portfolio_epoch)
        jump_res = controller.edit_question(5)
        self.assertEqual(jump_res["status"], "JUMPED")
        self.assertFalse(controller.is_completed)
        self.assertEqual(controller.current_question_index, 4)
        self.assertEqual(controller.get_current_question()["key"], "portfolio_epoch")

    # -------------------------------------------------------------------------
    # Category C: Financial Safety & Risk Invariants Clamping
    # -------------------------------------------------------------------------

    def test_risk_limits_clamped_to_system_ceilings(self):
        # Operator tries to request 2.0% per trade risk and 5.0% daily drawdown
        unsafe_cfg = TradingSessionConfig(
            session_id="TEST-UNSAFE-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            max_capital_risk_per_trade_pct=2.0,
            max_daily_drawdown_pct=5.0,
        )
        val_res = TradingSessionConfigValidator.validate_and_clamp(unsafe_cfg)
        self.assertTrue(val_res.is_valid)
        sanitized = val_res.sanitized_config
        self.assertEqual(sanitized.max_capital_risk_per_trade_pct, 0.5)
        self.assertEqual(sanitized.max_daily_drawdown_pct, 1.5)
        self.assertIn("max_capital_risk_per_trade_pct", val_res.clamped_fields)
        self.assertIn("max_daily_drawdown_pct", val_res.clamped_fields)

    def test_aggressive_profile_preserves_strict_risk_clamps(self):
        aggressive_cfg = TradingSessionConfig(
            session_id="TEST-AGG-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            operating_profile="aggressive_analysis",
            max_capital_risk_per_trade_pct=0.8,
            max_daily_drawdown_pct=2.5,
        )
        val_res = TradingSessionConfigValidator.validate_and_clamp(aggressive_cfg)
        self.assertTrue(val_res.is_valid)
        sanitized = val_res.sanitized_config
        self.assertEqual(sanitized.operating_profile, "aggressive_analysis")
        # Risk must be clamped despite aggressive analysis mode
        self.assertEqual(sanitized.max_capital_risk_per_trade_pct, 0.5)
        self.assertEqual(sanitized.max_daily_drawdown_pct, 1.5)

    def test_research_only_strategy_rejected_for_paper_trading(self):
        # Attempting to assign uncalibrated exotic arbitrage to paper execution
        bad_strat_cfg = TradingSessionConfig(
            session_id="TEST-BAD-STRAT-001",
            session_type="supervised_paper_trading",
            allowed_strategies=["nifty_momentum_breakout", "uncalibrated_exotic_arbitrage"],
        )
        val_res = TradingSessionConfigValidator.validate_and_clamp(bad_strat_cfg)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(any("RESEARCH_ONLY" in err for err in val_res.errors))

    def test_trade_caps_clamped_to_safe_bounds(self):
        high_caps_cfg = TradingSessionConfig(
            session_id="TEST-CAPS-001",
            max_new_entries_per_day=500,
            max_concurrent_positions=25,
        )
        val_res = TradingSessionConfigValidator.validate_and_clamp(high_caps_cfg)
        self.assertTrue(val_res.is_valid)
        self.assertEqual(val_res.sanitized_config.max_new_entries_per_day, 50)
        self.assertEqual(val_res.sanitized_config.max_concurrent_positions, 10)

    # -------------------------------------------------------------------------
    # Category D: 11-State Formal Lifecycle State Machine
    # -------------------------------------------------------------------------

    def test_valid_lifecycle_transitions(self):
        sup = self.supervisor
        self.assertEqual(sup.state, SessionState.IDLE)

        # 1. IDLE -> INTAKE_REQUIRED
        ok, _ = sup.transition_to(SessionState.INTAKE_REQUIRED, "User triggered start")
        self.assertTrue(ok)

        # 2. INTAKE_REQUIRED -> INTAKE_IN_PROGRESS
        ok, _ = sup.transition_to(SessionState.INTAKE_IN_PROGRESS, "Started intake")
        self.assertTrue(ok)

        # 3. INTAKE_IN_PROGRESS -> CONFIG_REVIEW
        ok, _ = sup.transition_to(SessionState.CONFIG_REVIEW, "Intake finished")
        self.assertTrue(ok)

        # 4. CONFIG_REVIEW -> AWAITING_CONFIRMATION
        ok, _ = sup.transition_to(SessionState.AWAITING_CONFIRMATION, "Summary presented")
        self.assertTrue(ok)

        # 5. AWAITING_CONFIRMATION -> PREFLIGHT_RUNNING
        ok, _ = sup.transition_to(SessionState.PREFLIGHT_RUNNING, "Confirmation entered")
        self.assertTrue(ok)

        # 6. PREFLIGHT_RUNNING -> READY_FOR_SUPERVISED_PAPER
        ok, _ = sup.transition_to(SessionState.READY_FOR_SUPERVISED_PAPER, "Checks passed")
        self.assertTrue(ok)

        # 7. READY_FOR_SUPERVISED_PAPER -> PAPER_SESSION_ACTIVE
        ok, _ = sup.transition_to(SessionState.PAPER_SESSION_ACTIVE, "Session launched")
        self.assertTrue(ok)

        # 8. PAPER_SESSION_ACTIVE -> PAUSED
        ok, _ = sup.transition_to(SessionState.PAUSED, "Operator paused")
        self.assertTrue(ok)

        # 9. PAUSED -> PAPER_SESSION_ACTIVE
        ok, _ = sup.transition_to(SessionState.PAPER_SESSION_ACTIVE, "Operator resumed")
        self.assertTrue(ok)

        # 10. PAPER_SESSION_ACTIVE -> STOPPED
        ok, _ = sup.transition_to(SessionState.STOPPED, "Session ended")
        self.assertTrue(ok)

        # 11. STOPPED -> IDLE
        ok, _ = sup.transition_to(SessionState.IDLE, "Reset")
        self.assertTrue(ok)

    def test_illegal_transitions_denied_by_guards(self):
        sup = self.supervisor
        self.assertEqual(sup.state, SessionState.IDLE)

        # Invariant: Cannot jump directly from IDLE to PAPER_SESSION_ACTIVE
        ok, msg = sup.transition_to(SessionState.PAPER_SESSION_ACTIVE, "Bypass attempt")
        self.assertFalse(ok)
        self.assertEqual(sup.state, SessionState.IDLE)

        # Invariant: Cannot jump directly from INTAKE_IN_PROGRESS to READY_FOR_SUPERVISED_PAPER
        sup.transition_to(SessionState.INTAKE_REQUIRED)
        sup.transition_to(SessionState.INTAKE_IN_PROGRESS)
        ok, _ = sup.transition_to(SessionState.READY_FOR_SUPERVISED_PAPER, "Premature ready")
        self.assertFalse(ok)
        self.assertEqual(sup.state, SessionState.INTAKE_IN_PROGRESS)

    def test_emergency_stop_trips_from_active_state(self):
        sup = self.supervisor
        sup.state = SessionState.PAPER_SESSION_ACTIVE
        res = sup.handle_operator_chat_directive("EMERGENCY STOP")
        self.assertTrue(res["handled"])
        self.assertEqual(res["action"], "EMERGENCY_STOP")
        self.assertEqual(sup.state, SessionState.STOPPED)

    # -------------------------------------------------------------------------
    # Category E: 12-Point System & Market Data Preflight Auditor
    # -------------------------------------------------------------------------

    def test_preflight_checks_pass_under_valid_configuration(self):
        cfg = TradingSessionConfig(
            session_id="PREFLIGHT-PASS-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
            instruments=["NIFTY", "BANKNIFTY"],
            allowed_strategies=["nifty_momentum_breakout", "banknifty_mean_reversion"],
            max_capital_risk_per_trade_pct=0.5,
            max_daily_drawdown_pct=1.5,
        )
        report = SessionPreflightService.run_all_checks(cfg)
        self.assertEqual(len(report.checks), 12)
        self.assertTrue(report.all_passed)
        self.assertIsNone(report.blocker_code)

        codes = [c.check_code for c in report.checks]
        self.assertIn("CHECK_EXECUTION_MODE", codes)
        self.assertIn("CHECK_EPOCH_ISOLATION", codes)
        self.assertIn("CHECK_CAPITAL_ADEQUACY", codes)
        self.assertIn("CHECK_EXCHANGE_CALENDAR", codes)
        self.assertIn("CHECK_MARKET_DATA_FRESHNESS", codes)
        self.assertIn("CHECK_INSTRUMENT_CATALOG", codes)
        self.assertIn("CHECK_STRATEGY_PERMISSIONS", codes)
        self.assertIn("CHECK_RISK_LIMITS_CLAMP", codes)
        self.assertIn("CHECK_DECISION_TRACE_RECORDER", codes)
        self.assertIn("CHECK_SUPERVISOR_LOCK", codes)
        self.assertIn("CHECK_CREDENTIAL_SAFETY", codes)
        self.assertIn("CHECK_SHADOW_DOM_SAFETY", codes)

    def test_preflight_fails_and_blocks_on_live_dispatch_active(self):
        cfg = TradingSessionConfig(session_id="PREFLIGHT-FAIL-001")
        class MockServerContext:
            live_order_dispatch_enabled = True
            is_live_allowed = True

        report = SessionPreflightService.run_all_checks(cfg, server_context=MockServerContext())
        self.assertFalse(report.all_passed)
        self.assertEqual(report.blocker_code, "CHECK_EXECUTION_MODE")

    # -------------------------------------------------------------------------
    # Category F: Persistence, Audit Trail Logging & Crash Recovery
    # -------------------------------------------------------------------------

    def test_session_persistence_and_audit_event_logging(self):
        cfg = TradingSessionConfig(
            session_id="PERSIST-001",
            portfolio_epoch="epoch_10k",
            allocated_capital_inr=10000.0,
        )
        self.store.save_current_session(SessionState.PAPER_SESSION_ACTIVE, cfg)
        self.store.record_audit_event("ORDER_SIMULATED", {"order_id": "ORD-001", "price": 125.0})

        # Verify files exist
        self.assertTrue(self.store.current_session_file.exists())
        self.assertTrue(self.store.audit_events_file.exists())

        loaded = self.store.load_current_session()
        self.assertEqual(loaded["state"], "PAPER_SESSION_ACTIVE")
        self.assertEqual(loaded["config"]["session_id"], "PERSIST-001")

    def test_crash_recovery_resets_interrupted_session_to_paused(self):
        cfg = TradingSessionConfig(session_id="CRASH-001")
        # Simulate active session when process was terminated abruptly
        self.store.save_current_session(SessionState.PAPER_SESSION_ACTIVE, cfg)

        # Create new supervisor instance loading the same store
        new_supervisor = TradingSessionSupervisor(store=self.store)
        # Invariant: Must safely pause rather than blindly running unmonitored
        self.assertEqual(new_supervisor.state, SessionState.PAUSED)
        self.assertEqual(new_supervisor.current_config.session_id, "CRASH-001")

    # -------------------------------------------------------------------------
    # Category G: Full End-to-End Chat Intake to Session Activation
    # -------------------------------------------------------------------------

    def test_end_to_end_chat_intake_to_activation(self):
        sup = self.supervisor
        self.assertEqual(sup.state, SessionState.IDLE)

        # Step 1: User says "Start trading"
        r1 = sup.handle_operator_chat_directive("Start trading")
        self.assertTrue(r1["handled"])
        self.assertEqual(r1["action"], "INTAKE_STARTED")
        self.assertEqual(sup.state, SessionState.INTAKE_IN_PROGRESS)

        # Step 2: User says "use defaults"
        r2 = sup.handle_operator_chat_directive("use defaults")
        self.assertTrue(r2["handled"])
        self.assertEqual(r2["action"], "DEFAULTS_APPLIED")
        self.assertEqual(sup.state, SessionState.AWAITING_CONFIRMATION)
        self.assertIsNotNone(sup.current_config)

        # Step 3: User confirms with canonical phrase
        r3 = sup.handle_operator_chat_directive("CONFIRM PAPER SESSION")
        self.assertTrue(r3["handled"])
        self.assertEqual(r3["action"], "SESSION_ACTIVATED")
        self.assertEqual(sup.state, SessionState.PAPER_SESSION_ACTIVE)
        self.assertTrue(sup.latest_preflight_report.all_passed)

        # Step 4: User pauses session
        r4 = sup.handle_operator_chat_directive("pause")
        self.assertTrue(r4["handled"])
        self.assertEqual(r4["action"], "SESSION_PAUSED")
        self.assertEqual(sup.state, SessionState.PAUSED)

        # Step 5: User resumes session
        r5 = sup.handle_operator_chat_directive("resume")
        self.assertTrue(r5["handled"])
        self.assertEqual(r5["action"], "SESSION_RESUMED")
        self.assertEqual(sup.state, SessionState.PAPER_SESSION_ACTIVE)

        # Step 6: User stops session
        r6 = sup.handle_operator_chat_directive("stop")
        self.assertTrue(r6["handled"])
        self.assertEqual(r6["action"], "SESSION_STOPPED")
        self.assertEqual(sup.state, SessionState.STOPPED)


if __name__ == "__main__":
    unittest.main()
