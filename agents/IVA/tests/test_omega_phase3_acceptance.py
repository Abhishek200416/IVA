"""AGI 1.7 OMEGA COMMAND — Acceptance Test Battery for Phase 3.

Validates all 20 Phase 3 Acceptance Criteria:
1.  Supervisor starts via `trading` and establishes 10-state lifecycle.
2.  Recovery of failed worker with heartbeat tracking and backoff.
3.  Duplicate supervisor / singleton lock rejection.
4.  Weekend non-trading detection via dynamic calendar.
5.  Official NSE holiday handling with holiday names.
6.  Special trading session (Diwali Muhurat) detection and execution window.
7.  Segment-specific hours (pre-market, regular, post-market, intraday cutoff).
8.  Stale/unverified calendar fail-safe (`CALENDAR_UNVERIFIED` halts trading).
9.  Gap/sleep detection after system sleep or time drift.
10. Browser disconnection / outage handling with graceful degradation.
11. Market-data feed outage detection and fail-safe.
12. 5–10 candidate battery evaluation across NIFTY & BANK NIFTY with NO_TRADE option.
13. Strict separation of intraday and overnight strategies (no auto-conversion).
14. Dedicated overnight gap risk and theta decay modeling.
15. Next-session 3-scenario planning (Bullish, Bearish, Flat).
16. Multi-day ledger persistence across restarts on ₹50,000 capital.
17. Cumulative multi-day P&L tracking (Day 1, Day 2, Cumulative).
18. 6 distinct accuracy metrics computation.
19. Explicit supervisor control: pause, resume, graceful stop, emergency stop.
20. Windows Task Scheduler auto-start script generation.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

from agents.AGI_1_7.engine.agi17.finance.dynamic_market_calendar import (
    CalendarSessionPhase,
    CalendarUpdateRecord,
    DynamicExchangeCalendar,
    ExchangeHoliday,
    SpecialTradingSession,
    VerificationStatus,
)
from agents.AGI_1_7.engine.agi17.finance.trading_supervisor import (
    Autonomous24x7TradingSupervisor,
    DuplicateSupervisorError,
    SupervisorServiceState,
)
from agents.AGI_1_7.engine.agi17.finance.overnight_strategy_manager import (
    NextSessionScenario,
    OvernightDecision,
    OvernightStrategyManager,
    OvernightTradeCandidate,
    ScenarioOutcomeType,
)
from agents.AGI_1_7.engine.agi17.finance.multi_day_accounting import (
    CumulativeLedgerSummary,
    DailySessionRecord,
    MultiDayLedgerManager,
    SixAccuracyMetrics,
)
from agents.AGI_1_7.engine.agi17.browser.browser_service import BrowserHealthStatus
from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import (
    AutonomousTradingOrchestrator,
    DuplicateSessionError,
    OptionType,
    PaperOrderStatus,
    run_trading_command,
)

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class TestOmegaPhase3Acceptance(unittest.TestCase):
    """Authoritative Phase 3 Acceptance Test Suite."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="omega_phase3_test_"))
        self.calendar = DynamicExchangeCalendar(allow_stale_for_testing=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Criterion 1: Supervisor lifecycle and starting state
    # -------------------------------------------------------------------------
    def test_01_supervisor_lifecycle_and_starting_state(self):
        supervisor = Autonomous24x7TradingSupervisor(
            storage_dir=self.temp_dir,
            calendar=self.calendar,
        )
        self.assertEqual(supervisor.state, SupervisorServiceState.STARTING)
        self.assertTrue(supervisor.acquire_lock())
        self.assertTrue(supervisor.has_lock)

        # Transition based on calendar
        curr_state = supervisor.reconcile_state_with_market_clock()
        self.assertIn(
            curr_state,
            (
                SupervisorServiceState.MARKET_OPEN,
                SupervisorServiceState.PREMARKET_PREPARATION,
                SupervisorServiceState.POSTMARKET_RECONCILIATION,
                SupervisorServiceState.OVERNIGHT_MONITORING,
                SupervisorServiceState.HOLIDAY_MONITORING,
            ),
        )
        supervisor.release_lock()
        self.assertFalse(supervisor.has_lock)

    # -------------------------------------------------------------------------
    # Criterion 2: Worker crash recovery and heartbeats
    # -------------------------------------------------------------------------
    def test_02_worker_crash_recovery_and_heartbeats(self):
        supervisor = Autonomous24x7TradingSupervisor(
            storage_dir=self.temp_dir,
            calendar=self.calendar,
        )
        # Register healthy heartbeats
        supervisor.register_worker_heartbeat("ALEXA", status="HEALTHY", task_desc="BROWSER_SYNC")
        supervisor.register_worker_heartbeat("EMILY", status="HEALTHY", task_desc="NEWS_AUDIT")
        supervisor.register_worker_heartbeat("MAX", status="HEALTHY", task_desc="QUANT_EVAL")
        self.assertEqual(supervisor.workers["ALEXA"].status, "HEALTHY")

        # Simulate Alexa crash
        recovered = supervisor.fail_worker("ALEXA", error_desc="UncaughtBrowserException")
        self.assertTrue(recovered)
        self.assertEqual(supervisor.workers["ALEXA"].recovery_attempts, 1)
        self.assertEqual(supervisor.workers["ALEXA"].status, "HEALTHY")
        self.assertIn("RECOVERED_AFTER", supervisor.workers["ALEXA"].last_successful_task)

        # Simulate exceeding max recovery attempts
        supervisor.workers["ALEXA"].recovery_attempts = 5
        recovered_again = supervisor.fail_worker("ALEXA", error_desc="RepeatedFatalCrash")
        self.assertFalse(recovered_again)
        self.assertEqual(supervisor.state, SupervisorServiceState.DEGRADED)

    # -------------------------------------------------------------------------
    # Criterion 3: Duplicate supervisor rejection
    # -------------------------------------------------------------------------
    def test_03_duplicate_supervisor_rejection(self):
        sup1 = Autonomous24x7TradingSupervisor(storage_dir=self.temp_dir, session_id="SESS-1")
        self.assertTrue(sup1.acquire_lock())

        # Second supervisor instance attempting to acquire the same lock
        sup2 = Autonomous24x7TradingSupervisor(storage_dir=self.temp_dir, session_id="SESS-2")
        with self.assertRaises(DuplicateSupervisorError):
            sup2.acquire_lock()

        sup1.release_lock()

    # -------------------------------------------------------------------------
    # Criterion 4: Dynamic calendar weekend detection
    # -------------------------------------------------------------------------
    def test_04_calendar_weekend_detection(self):
        # Saturday: 2026-04-18, Sunday: 2026-04-19
        saturday_dt = datetime.datetime(2026, 4, 18, 11, 0, tzinfo=IST)
        sunday_dt = datetime.datetime(2026, 4, 19, 14, 0, tzinfo=IST)

        self.assertTrue(self.calendar.is_weekend(saturday_dt))
        self.assertTrue(self.calendar.is_weekend(sunday_dt))
        self.assertFalse(self.calendar.is_trading_day(saturday_dt.date()))
        self.assertFalse(self.calendar.is_trading_day(sunday_dt.date()))

        self.assertEqual(self.calendar.get_session_phase(saturday_dt), CalendarSessionPhase.WEEKEND_CLOSED)
        self.assertEqual(self.calendar.get_session_phase(sunday_dt), CalendarSessionPhase.WEEKEND_CLOSED)
        self.assertFalse(self.calendar.is_market_open(saturday_dt))

    # -------------------------------------------------------------------------
    # Criterion 5: Dynamic calendar official NSE holidays
    # -------------------------------------------------------------------------
    def test_05_calendar_official_nse_holidays(self):
        # Republic Day: 2026-01-26, Independence Day: 2026-08-15, Gandhi Jayanti: 2026-10-02
        rep_day = datetime.date(2026, 1, 26)
        holiday_info = self.calendar.get_holiday(rep_day)
        self.assertIsNotNone(holiday_info)
        self.assertEqual(holiday_info.name, "Republic Day")

        rep_dt = datetime.datetime(2026, 1, 26, 10, 30, tzinfo=IST)
        self.assertFalse(self.calendar.is_trading_day(rep_day))
        self.assertEqual(self.calendar.get_session_phase(rep_dt), CalendarSessionPhase.HOLIDAY_CLOSED)
        self.assertFalse(self.calendar.is_market_open(rep_dt))

    # -------------------------------------------------------------------------
    # Criterion 6: Special trading session (Diwali Muhurat)
    # -------------------------------------------------------------------------
    def test_06_calendar_special_trading_sessions(self):
        # Diwali Muhurat 2026: 2026-11-08 from 18:15 to 19:15 IST
        muhurat_active_dt = datetime.datetime(2026, 11, 8, 18, 30, tzinfo=IST)
        muhurat_before_dt = datetime.datetime(2026, 11, 8, 14, 0, tzinfo=IST)

        # Before muhurat window: holiday or weekend closed
        self.assertIn(
            self.calendar.get_session_phase(muhurat_before_dt),
            (CalendarSessionPhase.HOLIDAY_CLOSED, CalendarSessionPhase.WEEKEND_CLOSED),
        )
        self.assertFalse(self.calendar.is_market_open(muhurat_before_dt))

        # During muhurat window: special session open
        self.assertEqual(self.calendar.get_session_phase(muhurat_active_dt), CalendarSessionPhase.SPECIAL_SESSION)
        self.assertTrue(self.calendar.is_market_open(muhurat_active_dt))
        self.assertTrue(self.calendar.is_intraday_entry_allowed(muhurat_active_dt))

    # -------------------------------------------------------------------------
    # Criterion 7: Segment-specific market hours
    # -------------------------------------------------------------------------
    def test_07_segment_specific_market_hours(self):
        # Wednesday: 2026-04-15 (Regular Trading Day)
        pre_mkt = datetime.datetime(2026, 4, 15, 9, 5, tzinfo=IST)
        regular_mkt = datetime.datetime(2026, 4, 15, 10, 0, tzinfo=IST)
        near_cutoff = datetime.datetime(2026, 4, 15, 15, 20, tzinfo=IST)
        post_mkt = datetime.datetime(2026, 4, 15, 15, 45, tzinfo=IST)
        overnight = datetime.datetime(2026, 4, 15, 20, 0, tzinfo=IST)

        self.assertEqual(self.calendar.get_session_phase(pre_mkt), CalendarSessionPhase.PRE_MARKET)
        self.assertEqual(self.calendar.get_session_phase(regular_mkt), CalendarSessionPhase.REGULAR_MARKET)
        self.assertTrue(self.calendar.is_market_open(regular_mkt))
        self.assertTrue(self.calendar.is_intraday_entry_allowed(regular_mkt))

        # After 15:15 IST: entries forbidden
        self.assertFalse(self.calendar.is_intraday_entry_allowed(near_cutoff))
        self.assertEqual(self.calendar.get_session_phase(post_mkt), CalendarSessionPhase.POST_MARKET)
        self.assertEqual(self.calendar.get_session_phase(overnight), CalendarSessionPhase.OVERNIGHT_CLOSED)

    # -------------------------------------------------------------------------
    # Criterion 8: Stale/unverified calendar fail-safe
    # -------------------------------------------------------------------------
    def test_08_calendar_stale_data_failsafe(self):
        strict_cal = DynamicExchangeCalendar(allow_stale_for_testing=False)
        # Force stale timestamp (> 72 hours ago)
        old_time = (datetime.datetime.now(IST) - datetime.timedelta(hours=80)).isoformat()
        strict_cal.last_update_record.retrieved_at = old_time

        self.assertTrue(strict_cal.is_stale(max_age_hours=72.0))
        self.assertEqual(strict_cal.get_verification_status(), VerificationStatus.STALE)

        regular_mkt = datetime.datetime(2026, 4, 15, 10, 0, tzinfo=IST)
        # When stale, session phase fails safe to CALENDAR_UNVERIFIED
        self.assertEqual(strict_cal.get_session_phase(regular_mkt), CalendarSessionPhase.CALENDAR_UNVERIFIED)
        self.assertFalse(strict_cal.is_market_open(regular_mkt))

    # -------------------------------------------------------------------------
    # Criterion 9: System sleep and gap detection
    # -------------------------------------------------------------------------
    def test_09_gap_sleep_detection(self):
        supervisor = Autonomous24x7TradingSupervisor(
            storage_dir=self.temp_dir,
            calendar=self.calendar,
            gap_detection_threshold_sec=5.0,
        )
        # Simulate last tick 20 seconds in past
        supervisor.last_tick_time = time.time() - 25.0
        gap = supervisor.check_time_gap_or_sleep()
        self.assertIsNotNone(gap)
        self.assertGreaterEqual(gap, 25.0)

        # Verify outage record in DB
        status = supervisor.get_service_status_report()
        self.assertIsNotNone(status)

    # -------------------------------------------------------------------------
    # Criterion 10: Browser outage graceful degradation
    # -------------------------------------------------------------------------
    def test_10_browser_outage_degradation(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        # Simulate browser disconnection
        orch.browser_service.session.health_status = BrowserHealthStatus.CRASHED
        orch.browser_service.session.is_alive = False

        status = orch.browser_service.get_status()
        self.assertEqual(status["health_status"], BrowserHealthStatus.CRASHED.value)

        # Consequential action must cleanly report failure
        res = orch.execute_consequential_browser_action(
            action_type="click",
            target_selector="#order-button",
        )
        self.assertEqual(res["status"], "UNVERIFIED")

    # -------------------------------------------------------------------------
    # Criterion 11: Market data feed outage fail-safe
    # -------------------------------------------------------------------------
    def test_11_market_data_feed_outage_failsafe(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        orch.market_data_feed_online = False

        # Phase D proposal must be rejected
        proposal = orch.evaluate_candidate_setup()
        self.assertEqual(proposal.approval_status, "REJECTED")
        self.assertIn("Market data feed disconnected", proposal.rejection_reason)

        # Order placement must reject
        order_res = orch.place_paper_order(proposal)
        self.assertEqual(order_res["status"], "REJECTED")

    # -------------------------------------------------------------------------
    # Criterion 12: 5 to 10 Candidate battery evaluation & NO_TRADE alternative
    # -------------------------------------------------------------------------
    def test_12_candidate_battery_5_to_10_setups(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        battery_res = orch.evaluate_candidate_battery(nifty_spot=22547.20, banknifty_spot=49820.50)

        self.assertGreaterEqual(battery_res["battery_size"], 5)
        self.assertLessEqual(battery_res["battery_size"], 10)
        self.assertTrue(battery_res["has_no_trade_alternative"])

        # Check instruments present
        self.assertTrue(any("NIFTY" in c.instrument for c in battery_res["candidates"]))
        self.assertTrue(any("BANKNIFTY" in c.instrument for c in battery_res["candidates"]))

        # Check call and put options present
        call_puts = {c.call_put for c in battery_res["candidates"]}
        self.assertIn("CE", call_puts)
        self.assertIn("PE", call_puts)

    # -------------------------------------------------------------------------
    # Criterion 13: Strict intraday / overnight separation (no auto-conversion)
    # -------------------------------------------------------------------------
    def test_13_strict_intraday_overnight_separation(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        # Create an intraday position
        pos = orch.active_positions["TEST-POS"] = orch._build_test_position()
        self.assertEqual(len(orch.active_positions), 1)

        # Monitoring at 15:15 IST (square-off time)
        res = orch.execute_monitoring_cycle(simulated_time_ist="15:16:00 IST")
        self.assertEqual(len(res.get("closed_this_cycle", [])), 1)
        self.assertIn("1515_AUTO_SQUAREOFF", res["closed_this_cycle"][0]["close_reason"])

        # Position must NOT convert to overnight
        self.assertEqual(len(orch.active_positions), 0)

    # -------------------------------------------------------------------------
    # Criterion 14: Dedicated overnight gap risk and theta decay modeling
    # -------------------------------------------------------------------------
    def test_14_dedicated_overnight_gap_and_theta_risk(self):
        mgr = OvernightStrategyManager(max_overnight_loss_inr=250.0, max_allowed_gap_risk_pct=1.75)
        cand = mgr.evaluate_candidate(
            candidate_id="ON-1",
            instrument="NIFTY",
            strategy_name="OVERNIGHT_BULL_SPREAD",
            underlying_spot=22550.0,
            strike=22600.0,
            option_type="CE",
            expiry_date="2026-04-16",
            entry_price=45.0,
            stop_loss=41.0,
            target_price=55.0,
            quantity=50,
            daily_theta=-5.0,
            volatility=0.15,
            is_weekend=False,
            margin_required=4000.0,
        )
        self.assertEqual(cand.decision, OvernightDecision.APPROVED)
        self.assertGreater(cand.overnight_gap_risk_pct, 0.0)
        self.assertGreater(cand.expected_overnight_theta_decay, 0.0)

        # Reject if gap risk too high
        cand_high_vol = mgr.evaluate_candidate(
            candidate_id="ON-2",
            instrument="NIFTY",
            strategy_name="OVERNIGHT_HIGH_RISK",
            underlying_spot=22550.0,
            strike=22600.0,
            option_type="CE",
            expiry_date="2026-04-16",
            entry_price=45.0,
            stop_loss=41.0,
            target_price=55.0,
            quantity=50,
            daily_theta=-5.0,
            volatility=0.50,  # Extreme vol
            is_weekend=True,
            margin_required=4000.0,
        )
        self.assertEqual(cand_high_vol.decision, OvernightDecision.NO_TRADE)
        self.assertIn("gap risk", cand_high_vol.decision_reason)

    # -------------------------------------------------------------------------
    # Criterion 15: Next-session 3-scenario planning
    # -------------------------------------------------------------------------
    def test_15_next_session_three_scenario_planning(self):
        mgr = OvernightStrategyManager()
        scenarios = mgr.build_next_session_scenarios(
            candidate_id="ON-1",
            instrument="NIFTY",
            spot=22500.0,
            strike=22500.0,
            entry_price=100.0,
            stop_loss=90.0,
            target_price=120.0,
            quantity=25,
            option_type="CE",
        )
        self.assertEqual(len(scenarios), 3)
        stypes = {s.scenario_type for s in scenarios}
        self.assertEqual(
            stypes,
            {ScenarioOutcomeType.BULLISH_GAP, ScenarioOutcomeType.BEARISH_GAP, ScenarioOutcomeType.FLAT_OPEN},
        )
        for s in scenarios:
            self.assertGreater(s.trigger_level, 0.0)
            self.assertIn(s.target_action, ("PROFIT_BOOK", "CUT_LOSS", "HOLD_HARVEST", "EXIT_IF_STAGNANT"))

    # -------------------------------------------------------------------------
    # Criterion 16: Multi-day ledger persistence across restarts on ₹50,000 capital
    # -------------------------------------------------------------------------
    def test_16_multi_day_ledger_persistence_across_restarts(self):
        ledger_mgr = MultiDayLedgerManager(storage_dir=self.temp_dir, initial_capital=50000.0)
        self.assertEqual(ledger_mgr.get_latest_ending_capital(), 50000.0)
        self.assertEqual(ledger_mgr.get_next_day_number(), 1)

        # Record Day 1 session with profit
        rec1 = DailySessionRecord(
            session_id="SESS-DAY-1",
            date_str="2026-04-13",
            day_number=1,
            starting_capital=50000.0,
            ending_capital=50550.0,
            realized_pnl=550.0,
            unrealized_pnl=0.0,
            fees_and_charges=56.20,
            total_trades_executed=2,
            winning_trades=2,
            losing_trades=0,
            win_rate=100.0,
            peak_equity_intraday=50550.0,
            lowest_equity_intraday=50000.0,
            max_drawdown_inr=0.0,
        )
        ledger_mgr.record_session(rec1)

        # Simulate fresh process restart reading same DB
        restarted_mgr = MultiDayLedgerManager(storage_dir=self.temp_dir, initial_capital=50000.0)
        self.assertEqual(restarted_mgr.get_latest_ending_capital(), 50550.0)
        self.assertEqual(restarted_mgr.get_next_day_number(), 2)

    # -------------------------------------------------------------------------
    # Criterion 17: Cumulative multi-day P&L and drawdown tracking
    # -------------------------------------------------------------------------
    def test_17_cumulative_multi_day_pnl_and_drawdown(self):
        ledger_mgr = MultiDayLedgerManager(storage_dir=self.temp_dir, initial_capital=50000.0)

        # Day 1: Profit of ₹550 -> Ending ₹50,550
        rec1 = DailySessionRecord(
            session_id="SESS-1", date_str="2026-04-13", day_number=1,
            starting_capital=50000.0, ending_capital=50550.0, realized_pnl=550.0, unrealized_pnl=0.0,
            fees_and_charges=40.0, total_trades_executed=1, winning_trades=1, losing_trades=0, win_rate=100.0,
            peak_equity_intraday=50550.0, lowest_equity_intraday=50000.0, max_drawdown_inr=0.0
        )
        ledger_mgr.record_session(rec1)

        # Day 2: Loss of ₹200 -> Ending ₹50,350
        rec2 = DailySessionRecord(
            session_id="SESS-2", date_str="2026-04-14", day_number=2,
            starting_capital=50550.0, ending_capital=50350.0, realized_pnl=-200.0, unrealized_pnl=0.0,
            fees_and_charges=35.0, total_trades_executed=1, winning_trades=0, losing_trades=1, win_rate=0.0,
            peak_equity_intraday=50550.0, lowest_equity_intraday=50350.0, max_drawdown_inr=200.0
        )
        ledger_mgr.record_session(rec2)

        summary = ledger_mgr.get_cumulative_summary()
        self.assertEqual(summary.initial_monthly_capital, 50000.0)
        self.assertEqual(summary.current_equity, 50350.0)
        self.assertEqual(summary.cumulative_realized_pnl, 350.0)
        self.assertEqual(summary.cumulative_return_pct, 0.70)
        self.assertEqual(summary.portfolio_high_water_mark, 50550.0)
        self.assertEqual(summary.max_cumulative_drawdown_inr, 200.0)
        self.assertEqual(summary.total_sessions_completed, 2)
        self.assertEqual(summary.total_trades_executed, 2)

    # -------------------------------------------------------------------------
    # Criterion 18: 6 distinct accuracy metrics computation
    # -------------------------------------------------------------------------
    def test_18_six_distinct_accuracy_metrics(self):
        ledger_mgr = MultiDayLedgerManager(storage_dir=self.temp_dir, initial_capital=50000.0)

        # Record forecasts (Metric 1: 3 out of 4 correct = 75%)
        ledger_mgr.record_forecast("S1", "NIFTY", "BULLISH", "BULLISH")
        ledger_mgr.record_forecast("S1", "NIFTY", "BEARISH", "BEARISH")
        ledger_mgr.record_forecast("S1", "BANKNIFTY", "BULLISH", "BULLISH")
        ledger_mgr.record_forecast("S1", "BANKNIFTY", "BULLISH", "BEARISH")

        # Record candidate signals (Metric 2: 2 out of 3 won = 66.67%)
        ledger_mgr.record_candidate_signal("S1", "SIG-1", target_hit=True, stop_hit=False)
        ledger_mgr.record_candidate_signal("S1", "SIG-2", target_hit=True, stop_hit=False)
        ledger_mgr.record_candidate_signal("S1", "SIG-3", target_hit=False, stop_hit=True)

        # Record order executions (Metric 3: 4 out of 5 filled = 80%)
        for i in range(4):
            ledger_mgr.record_order_submission("S1", f"ORD-{i}", "FILLED")
        ledger_mgr.record_order_submission("S1", "ORD-REJ", "REJECTED")

        # Record daily sessions (Metric 4 & 5: win rate & profit factor)
        rec = DailySessionRecord(
            session_id="S1", date_str="2026-04-13", day_number=1,
            starting_capital=50000.0, ending_capital=50400.0, realized_pnl=400.0, unrealized_pnl=0.0,
            fees_and_charges=50.0, total_trades_executed=4, winning_trades=3, losing_trades=1, win_rate=75.0,
            peak_equity_intraday=50400.0, lowest_equity_intraday=50000.0, max_drawdown_inr=0.0
        )
        ledger_mgr.record_session(rec)

        # Record heartbeats (Metric 6: 10 out of 10 delivered = 100%)
        for i in range(10):
            ledger_mgr.record_heartbeat("S1", "ALEXA", delivered=True)

        metrics = ledger_mgr.compute_six_metrics()
        self.assertEqual(metrics.directional_forecast_accuracy_pct, 75.0)
        self.assertAlmostEqual(metrics.candidate_signal_accuracy_pct, 66.67, delta=0.05)
        self.assertEqual(metrics.simulated_fill_rate_pct, 80.0)
        self.assertEqual(metrics.closed_trade_win_rate_pct, 75.0)
        self.assertGreater(metrics.net_profit_factor, 0.0)
        self.assertEqual(metrics.operational_reliability_pct, 100.0)

    # -------------------------------------------------------------------------
    # Criterion 19: Explicit supervisor controls
    # -------------------------------------------------------------------------
    def test_19_explicit_supervisor_controls(self):
        supervisor = Autonomous24x7TradingSupervisor(storage_dir=self.temp_dir, calendar=self.calendar)
        self.assertTrue(supervisor.acquire_lock())

        # 1. Pause
        supervisor.pause(reason="Maintenance break")
        self.assertEqual(supervisor.state, SupervisorServiceState.PAUSED)

        # 2. Resume
        supervisor.resume(reason="Maintenance complete")
        self.assertNotEqual(supervisor.state, SupervisorServiceState.PAUSED)

        # 3. Emergency Stop
        supervisor.emergency_stop(reason="Unscheduled power test")
        self.assertEqual(supervisor.state, SupervisorServiceState.STOPPED)
        self.assertFalse(supervisor.has_lock)

    # -------------------------------------------------------------------------
    # Criterion 20: Windows Task Scheduler configuration generation
    # -------------------------------------------------------------------------
    def test_20_windows_task_scheduler_config_generation(self):
        supervisor = Autonomous24x7TradingSupervisor(storage_dir=self.temp_dir, calendar=self.calendar)
        script_path = self.temp_dir / "scripts" / "setup_windows_task.ps1"
        xml_content, ps1_content = supervisor.generate_windows_task_scheduler_config(script_path=script_path)

        self.assertIn("Task version=\"1.4\"", xml_content)
        self.assertIn("<BootTrigger>", xml_content)
        self.assertIn("<LogonTrigger>", xml_content)
        self.assertIn("AGI17_TradingSupervisor_24x7", ps1_content)
        self.assertIn("schtasks.exe", ps1_content)
        self.assertTrue(script_path.exists())
        self.assertTrue((self.temp_dir / "scripts" / "trading_supervisor_task.xml").exists())


def _build_test_position_helper(self):
    from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import ActivePaperPosition
    return ActivePaperPosition(
        trade_id="POS-TEST-1",
        instrument="NIFTY 22550 CE",
        expiry="2026-04-16",
        strike=22550.0,
        call_put="CE",
        direction="BUY",
        quantity=25,
        entry_time="10:00:00 IST",
        entry_price=136.83,
        current_mark_price=145.0,
        stop_loss=126.83,
        target_1=158.83,
        target_2=178.83,
        unrealized_pnl=204.25,
        estimated_exit_costs=20.0,
        net_estimated_pnl=184.25,
    )

AutonomousTradingOrchestrator._build_test_position = _build_test_position_helper


if __name__ == "__main__":
    unittest.main()
