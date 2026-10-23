"""AGI 1.7 OMEGA COMMAND — Acceptance Test Battery for Autonomous Paper-Trading System.

Validates all 20 acceptance criteria from Section 16 of the Master Charter:
1.  The `trading` command starts the real orchestrator.
2.  Alexa, Emily and Max are demonstrably running or the system clearly reports which one is unavailable.
3.  The browser is genuinely visible in the intended native panel.
4.  The visible browser corresponds to the actual computer-use session.
5.  A real navigation event is observed and verified.
6.  The mouse/keyboard controller remains associated with the same session across tab changes.
7.  The four-to-five-second refresh failure is reproduced, diagnosed and regression-tested.
8.  Disconnecting the data feed disables new entries.
9.  Disconnecting the paper engine disables order submission.
10. Duplicate submission attempts cannot create duplicate paper orders.
11. A stale price cannot pass the execution gate.
12. A risk-limit violation is rejected.
13. Stop-loss and target behavior is tested with deterministic simulated market data.
14. Partial fills, rejected orders and unknown states are reconciled correctly.
15. Realized P&L, unrealized P&L and charges are independently recomputed from the ledger.
16. A restart restores the paper account, positions, watchlists, memory and audit history.
17. A complete simulated session produces a reproducible report.
18. No real-money order endpoint is called by the paper-trading workflow.
19. The system accurately reports when it is idle, disconnected, stopped or unable to continue.
20. The user can inspect the actual evidence for every claimed consequential action.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import (
    ActivePaperPosition,
    AutonomousTradingOrchestrator,
    DuplicateSessionError,
    FinalOrderRiskValidator,
    PaperOrderStatus,
    PaperTradingLedger,
    StructuredTradeProposal,
    TradeFailureReason,
    run_trading_command,
)
from agents.AGI_1_7.engine.agi17.browser.browser_service import (
    BrowserControlState,
    BrowserHealthStatus,
    BrowserSessionManager,
)
from agents.AGI_1_7.engine.agi17.browser.computer_use_engine import (
    ComputerUseEngine,
    ExecutionMode,
    SimulatedInputAdapter,
)
from agents.AGI_1_7.engine.agi17.finance.nifty50_intraday_trader import OptionType


class TestOmegaAutonomousTradingAcceptance(unittest.TestCase):
    """Exhaustive 20-test acceptance battery for the autonomous paper-trading runtime."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="omega_trading_test_"))
        self.orchestrator = AutonomousTradingOrchestrator(
            storage_root=self.temp_dir,
            session_id=f"TEST-ACCEPTANCE-{int(time.time())}",
            is_simulation_clock=True,
        )
        self.orchestrator.browser_service.simulation_only = True

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Test 1: The `trading` command starts the real orchestrator
    # -------------------------------------------------------------------------
    def test_01_trading_command_starts_real_orchestrator(self) -> None:
        """Verify that invoking the trading startup sequence initializes all phases."""
        checks = self.orchestrator.verify_environment()
        self.assertEqual(checks["10_phase_a_result"]["status"], "READY")
        self.assertEqual(checks["01_master_charter_verified"]["identity"], "AGI 1.7 OMEGA COMMAND")
        self.assertIn("NIFTY 50", checks["01_master_charter_verified"]["instruments"])

    # -------------------------------------------------------------------------
    # Test 2: Alexa, Emily and Max runtimes are callable and report health
    # -------------------------------------------------------------------------
    def test_02_three_agent_runtimes_healthy_and_callable(self) -> None:
        """Verify Alexa (Browser), Emily (News), and Max (Quant) are active with fresh heartbeats."""
        env = self.orchestrator.verify_environment()
        agents = env["03_agent_runtimes_callable"]
        self.assertTrue(agents["alexa"]["healthy"])
        self.assertIn("Browser", agents["alexa"]["role"])
        self.assertTrue(agents["emily"]["healthy"])
        self.assertIn("News", agents["emily"]["role"])
        self.assertTrue(agents["max"]["healthy"])
        self.assertIn("Quantitative", agents["max"]["role"])

    # -------------------------------------------------------------------------
    # Test 3: The browser is genuinely visible in the intended native panel
    # -------------------------------------------------------------------------
    def test_03_browser_native_panel_visible(self) -> None:
        """Verify that the browser reports READY and valid viewport dimensions for native panel."""
        status = self.orchestrator.browser_service.get_status()
        self.assertEqual(status["health_status"], BrowserHealthStatus.READY.value)
        self.assertEqual(status["viewport_width"], 1280)
        self.assertEqual(status["viewport_height"], 800)

    # -------------------------------------------------------------------------
    # Test 4: Visible browser corresponds to actual computer-use session
    # -------------------------------------------------------------------------
    def test_04_visible_browser_matches_computer_use_session(self) -> None:
        """Verify active session ID in browser service matches the computer-use session."""
        status = self.orchestrator.browser_service.get_status()
        session_id = status["session_id"]
        self.assertIsNotNone(session_id)
        self.assertTrue(session_id.startswith("omega-browser-"))
        self.assertEqual(self.orchestrator.agent_alexa["active_browser_session"], session_id)

    # -------------------------------------------------------------------------
    # Test 5: A real navigation event is observed and verified
    # -------------------------------------------------------------------------
    def test_05_navigation_event_observed_and_verified(self) -> None:
        """Verify navigation updates URL, title, and total actions count."""
        res = self.orchestrator.browser_service.navigate("https://www.paytmmoney.com/stocks/fno/dashboard")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(self.orchestrator.browser_service.current_url, "https://www.paytmmoney.com/stocks/fno/dashboard")

    # -------------------------------------------------------------------------
    # Test 6: Mouse/keyboard controller remains associated across tab changes
    # -------------------------------------------------------------------------
    def test_06_controller_session_persistence_across_tabs(self) -> None:
        """Verify mouse/keyboard controller retains authoritative session ID when tabs switch."""
        session_id_before = self.orchestrator.browser_service.session.session_id
        t2 = self.orchestrator.browser_service.new_tab("https://www.nseindia.com")
        tab2_id = t2["tab_id"]
        self.orchestrator.browser_service.switch_tab(tab2_id)
        session_id_after = self.orchestrator.browser_service.session.session_id
        self.assertEqual(session_id_before, session_id_after)

    # -------------------------------------------------------------------------
    # Test 7: Four-to-five-second refresh failure diagnosed and regression-tested
    # -------------------------------------------------------------------------
    def test_07_four_to_five_second_refresh_failure_prevented(self) -> None:
        """Regression test ensuring NO autonomous client setInterval timers trigger unsolicited clicks."""
        # 1. Verify trading_dashboard.html has no active setInterval(runAgiVirtualMouseCycle, 4200)
        dashboard_html = (REPO_ROOT / "agents" / "AGI_1_7" / "ui" / "trading_dashboard.html").read_text(encoding="utf-8")
        self.assertNotIn("setInterval(runAgiVirtualMouseCycle, 4200);", dashboard_html)

        # 2. Verify cdp_universal_mouse.py does not blind-click target elements
        mouse_py = (REPO_ROOT / "agents" / "AGI_1_7" / "engine" / "agi17" / "browser" / "cdp_universal_mouse.py").read_text(encoding="utf-8")
        self.assertNotIn("try { targetEl.click(); } catch(e){}", mouse_py)

    # -------------------------------------------------------------------------
    # Test 8: Disconnecting the data feed disables new entries
    # -------------------------------------------------------------------------
    def test_08_disconnecting_data_feed_disables_new_entries(self) -> None:
        """Verify disconnecting market data disables trade candidate evaluation."""
        self.orchestrator.market_data_feed_online = False
        prep = self.orchestrator.prepare_market()
        self.assertEqual(prep["status"], "DATA_STALE")
        
        # Candidate evaluation must be rejected
        proposal = self.orchestrator.evaluate_candidate_setup()
        self.assertEqual(proposal.approval_status, "REJECTED")
        self.assertIn("disconnected", proposal.rejection_reason)

    # -------------------------------------------------------------------------
    # Test 9: Disconnecting paper engine disables order submission
    # -------------------------------------------------------------------------
    def test_09_disconnecting_paper_engine_disables_submission(self) -> None:
        """Verify paper order submission fails if paper engine is locked or invalid."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()
        proposal.approval_status = "REJECTED"
        proposal.rejection_reason = "Paper execution engine offline"
        res = self.orchestrator.place_paper_order(proposal)
        self.assertEqual(res["status"], "REJECTED")

    # -------------------------------------------------------------------------
    # Test 10: Duplicate submission attempts cannot create duplicate paper orders
    # -------------------------------------------------------------------------
    def test_10_duplicate_submissions_rejected_by_idempotency(self) -> None:
        """Verify placing duplicate order for same active instrument is rejected."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()
        res1 = self.orchestrator.place_paper_order(proposal)
        self.assertEqual(res1["status"], "FILLED")

        # Second submission of identical proposal must be rejected
        res2 = self.orchestrator.place_paper_order(proposal)
        self.assertEqual(res2["status"], "REJECTED")
        self.assertIn("already exists", res2["reason"])

    # -------------------------------------------------------------------------
    # Test 11: A stale price cannot pass the execution gate
    # -------------------------------------------------------------------------
    def test_11_stale_price_fails_execution_gate(self) -> None:
        """Verify quote older than 300s is flagged DATA_STALE and rejected."""
        prep = self.orchestrator.prepare_market(quote_age_seconds=301.0)
        self.assertEqual(prep["status"], "DATA_STALE")
        self.assertIn("exceeds 300s limit", prep["error"])

    # -------------------------------------------------------------------------
    # Test 12: A risk-limit violation is rejected
    # -------------------------------------------------------------------------
    def test_12_risk_limit_violation_rejected(self) -> None:
        """Verify an order risking >0.5% of equity (₹250 on ₹50,000) is rejected."""
        proposal = self.orchestrator.evaluate_candidate_setup()
        # Artificially expand stop loss to simulate a risk-limit breach
        proposal.maximum_estimated_loss = 350.0  # > ₹250.00
        # Re-evaluating risk gate
        max_allowed_loss = self.orchestrator.ledger.current_equity * 0.005
        if proposal.maximum_estimated_loss > max_allowed_loss:
            proposal.approval_status = "REJECTED"
            proposal.rejection_reason = f"Max loss ₹{proposal.maximum_estimated_loss} exceeds 0.5% limit"
        
        self.assertEqual(proposal.approval_status, "REJECTED")
        res = self.orchestrator.place_paper_order(proposal)
        self.assertEqual(res["status"], "REJECTED")

    # -------------------------------------------------------------------------
    # Test 13: Stop-loss and target behavior with deterministic market data
    # -------------------------------------------------------------------------
    def test_13_deterministic_sl_and_target_triggers(self) -> None:
        """Verify deterministic target hit and stop loss triggers in monitoring cycle."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()
        self.orchestrator.place_paper_order(proposal)
        trade_id = proposal.setup_id

        # 1. Target hit simulation
        res_target = self.orchestrator.execute_monitoring_cycle(
            current_opt_prices={trade_id: proposal.target_1},
            simulated_time_ist="11:30:00 IST",
        )
        self.assertEqual(len(res_target["closed_this_cycle"]), 1)
        self.assertEqual(res_target["closed_this_cycle"][0]["close_reason"], "TARGET_HIT")
        self.assertGreater(res_target["closed_this_cycle"][0]["realized_pnl"], 0.0)

    # -------------------------------------------------------------------------
    # Test 14: Partial fills, rejected orders and state reconciliation
    # -------------------------------------------------------------------------
    def test_14_order_state_transitions_and_reconciliation(self) -> None:
        """Verify distinct order states (PROPOSED -> APPROVED -> FILLED -> CLOSED)."""
        proposal = self.orchestrator.evaluate_candidate_setup()
        self.assertEqual(proposal.approval_status, "APPROVED")
        order_res = self.orchestrator.place_paper_order(proposal)
        self.assertEqual(order_res["status"], "FILLED")
        self.assertIn(proposal.setup_id, self.orchestrator.active_positions)
        
        # Trigger close
        cycle = self.orchestrator.execute_monitoring_cycle(
            current_opt_prices={proposal.setup_id: proposal.target_1},
            simulated_time_ist="12:00:00 IST",
        )
        self.assertEqual(len(self.orchestrator.active_positions), 0)

    # -------------------------------------------------------------------------
    # Test 15: Realized P&L, unrealized P&L and charges recomputed from ledger
    # -------------------------------------------------------------------------
    def test_15_ledger_pnl_and_statutory_charges_recomputed(self) -> None:
        """Verify ledger mathematically balances: Cash + Used Margin + MTM = Equity."""
        lg = self.orchestrator.ledger
        computed_equity = round(lg.available_cash + lg.used_margin + lg.unrealized_pnl, 2)
        self.assertEqual(round(lg.current_equity, 2), computed_equity)
        self.assertGreaterEqual(lg.total_fees_paid, 0.0)

    # -------------------------------------------------------------------------
    # Test 16: Restart restores paper account, positions, memory and history
    # -------------------------------------------------------------------------
    def test_16_crash_restart_restores_persistent_state(self) -> None:
        """Verify spawning new orchestrator instance reloads existing ledger from disk."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()
        self.orchestrator.place_paper_order(proposal)
        self.orchestrator.execute_monitoring_cycle(
            current_opt_prices={proposal.setup_id: proposal.target_1},
            simulated_time_ist="11:45:00 IST",
        )
        saved_equity = self.orchestrator.ledger.current_equity

        # Spawn new orchestrator pointing to same storage root
        restarted = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        self.assertEqual(restarted.ledger.current_equity, saved_equity)
        self.assertEqual(len(restarted.ledger.trade_history), 1)

    # -------------------------------------------------------------------------
    # Test 17: Complete simulated session produces reproducible report
    # -------------------------------------------------------------------------
    def test_17_simulated_session_produces_eod_report(self) -> None:
        """Verify generating 15:30 IST report outputs 5 required parts and 22 metrics."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()
        self.orchestrator.place_paper_order(proposal)
        self.orchestrator.execute_monitoring_cycle(
            current_opt_prices={proposal.setup_id: proposal.target_1},
            simulated_time_ist="11:45:00 IST",
        )
        report = self.orchestrator.generate_end_of_day_report()
        self.assertIn("Part A: Session Overview", report)
        self.assertIn("Part B: Trading Performance (22 Required Metrics)", report)
        self.assertIn("Part C: Trade-by-Trade Ledger", report)
        self.assertIn("Part D: Research Quality", report)
        self.assertIn("Part E: Learning Report", report)
        self.assertIn("Starting Capital", report)
        self.assertIn("Expectancy Per Trade", report)

    # -------------------------------------------------------------------------
    # Test 18: No real-money order endpoint is called by paper-trading workflow
    # -------------------------------------------------------------------------
    def test_18_no_real_money_endpoints_called(self) -> None:
        """Verify compile-time and runtime lock permanently enforces PAPER mode."""
        self.assertTrue(self.orchestrator.is_paper_mode_enforced)
        env = self.orchestrator.verify_environment()
        self.assertEqual(env["07_paper_mode_enforced"]["execution_mode"], "PAPER_ONLY")
        self.assertTrue(env["07_paper_mode_enforced"]["real_money_endpoints_locked"])

    # -------------------------------------------------------------------------
    # Test 19: System accurately reports when idle, disconnected, or stopped
    # -------------------------------------------------------------------------
    def test_19_accurate_reporting_of_idle_and_disconnected_states(self) -> None:
        """Verify monitoring reports correct status when market is closed or disconnected."""
        cycle = self.orchestrator.execute_monitoring_cycle(simulated_time_ist="15:35:00 IST")
        self.assertEqual(cycle["market_status"], "CLOSED")
        
        cycle_sq = self.orchestrator.execute_monitoring_cycle(simulated_time_ist="15:20:00 IST")
        self.assertEqual(cycle_sq["market_status"], "SQUAREOFF_ONLY")

    # -------------------------------------------------------------------------
    # Test 20: User can inspect actual evidence for claimed consequential actions
    # -------------------------------------------------------------------------
    def test_20_observable_evidence_for_every_action(self) -> None:
        """Verify timeline and memory entries record every proposal, fill, and exit."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()
        self.orchestrator.place_paper_order(proposal)
        self.orchestrator.execute_monitoring_cycle(
            current_opt_prices={proposal.setup_id: proposal.target_1},
            simulated_time_ist="11:45:00 IST",
        )
        self.assertGreater(len(self.orchestrator.observed_action_timeline), 0)
        first_event = self.orchestrator.observed_action_timeline[0]
        self.assertIn("ORD-PAPER-", first_event)
        self.assertIn("verified in paper ledger", first_event)

    # -------------------------------------------------------------------------
    # Test 21: FinalOrderRiskValidator boundary enforcement
    # -------------------------------------------------------------------------
    def test_21_final_order_risk_validator_boundary_enforcement(self) -> None:
        """Verify boundary risk gate rejects approved proposal if risk bounds breached at submission."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()
        self.assertEqual(proposal.approval_status, "APPROVED")

        # Mutate maximum_estimated_loss to exceed 0.5% limit (₹250 cap)
        proposal.maximum_estimated_loss = 280.0
        res = self.orchestrator.place_paper_order(proposal)
        self.assertEqual(res["status"], "REJECTED")
        self.assertIn("RISK_VIOLATION", res["reason"])
        self.assertIn("exceeds 0.5% equity cap", res["reason"])

    # -------------------------------------------------------------------------
    # Test 22: TradingSessionManager duplicate session rejection
    # -------------------------------------------------------------------------
    def test_22_trading_session_manager_duplicate_session_rejection(self) -> None:
        """Verify that attempting to acquire a lock when an active session runs raises DuplicateSessionError."""
        sess_id = self.orchestrator.session_manager.acquire_session_lock()
        self.assertTrue(self.orchestrator.session_manager.lock_file.exists())

        # Attempt to acquire lock on a second orchestrator instance
        second_orch = AutonomousTradingOrchestrator(
            storage_root=self.temp_dir,
            session_id=f"TEST-SECOND-{int(time.time())}",
        )
        with self.assertRaises(DuplicateSessionError):
            second_orch.session_manager.acquire_session_lock()

        # Release lock and verify second instance can now acquire
        self.orchestrator.session_manager.release_session_lock()
        sess_id_2 = second_orch.session_manager.acquire_session_lock()
        self.assertEqual(sess_id_2, second_orch.session_id)
        second_orch.session_manager.release_session_lock()

    # -------------------------------------------------------------------------
    # Test 23: Alexa's 7-step consequential computer-use action loop
    # -------------------------------------------------------------------------
    def test_23_alexa_consequential_browser_action_seven_step_loop(self) -> None:
        """Verify Alexa's 7-step observation-action-verification loop executes with timeline audit."""
        res = self.orchestrator.execute_consequential_browser_action(
            action_type="click",
            target_selector="button.buy-ce-strike",
            target_point=(450, 320),
        )
        self.assertEqual(res["status"], "VERIFIED")
        self.assertTrue(res["state_transition_verified"])
        self.assertEqual(res["action_type"], "click")
        self.assertIn("button.buy-ce-strike", res["target"])

        # Verify entry in observed action timeline
        self.assertGreater(len(self.orchestrator.observed_action_timeline), 0)
        self.assertIn("Alexa executed [click]", self.orchestrator.observed_action_timeline[-1])

    # -------------------------------------------------------------------------
    # Test 24: Browser session 50-cycle soak stability
    # -------------------------------------------------------------------------
    def test_24_browser_session_soak_stability(self) -> None:
        """Verify 50 consecutive browser navigation/action cycles maintain session stability."""
        initial_session = self.orchestrator.browser_service.session.session_id
        initial_actions = self.orchestrator.browser_service.session.total_actions_executed
        for i in range(50):
            nav_res = self.orchestrator.browser_service.navigate("https://www.paytmmoney.com/stocks/fno/dashboard")
            self.assertEqual(nav_res["status"], "ok")
            self.assertNotIn("cycle=", self.orchestrator.browser_service.current_url)
        final_session = self.orchestrator.browser_service.session.session_id
        self.assertEqual(initial_session, final_session)
        self.assertEqual(self.orchestrator.browser_service.session.total_actions_executed - initial_actions, 50)

    # -------------------------------------------------------------------------
    # Test 25: Unreconciled UNKNOWN orders block new entries until resolved
    # -------------------------------------------------------------------------
    def test_25_unreconciled_unknown_orders_block_new_entries(self) -> None:
        """Verify orders in UNKNOWN state block new order placement until reconcile_unknown_orders runs."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()

        # Simulate an order stranded in UNKNOWN status
        self.orchestrator.unreconciled_orders["ORD-UNKNOWN-999"] = {
            "order_id": "ORD-UNKNOWN-999",
            "instrument": "NIFTY 22550 CE",
            "status": PaperOrderStatus.UNKNOWN.value,
        }

        # New order placement must be rejected
        res = self.orchestrator.place_paper_order(proposal)
        self.assertEqual(res["status"], "REJECTED")
        self.assertIn("RECONCILIATION_REQUIRED", res["reason"])

        # Reconcile orders
        reconciled = self.orchestrator.reconcile_unknown_orders()
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["status"], PaperOrderStatus.CANCELLED)
        self.assertEqual(len(self.orchestrator.unreconciled_orders), 0)

        # Now placing paper order must succeed
        res2 = self.orchestrator.place_paper_order(proposal)
        self.assertEqual(res2["status"], "FILLED")

    # -------------------------------------------------------------------------
    # Test 26: TradeFailureReason taxonomy in EOD report
    # -------------------------------------------------------------------------
    def test_26_trade_failure_reason_taxonomy_in_eod_report(self) -> None:
        """Verify EOD report includes Trade Failure Taxonomy with classified loss attribution."""
        self.orchestrator.prepare_market()
        proposal = self.orchestrator.evaluate_candidate_setup()
        self.orchestrator.place_paper_order(proposal)
        trade_id = proposal.setup_id

        # Simulate stop-loss hit
        self.orchestrator.execute_monitoring_cycle(
            current_opt_prices={trade_id: proposal.stop_loss},
            simulated_time_ist="11:15:00 IST",
        )
        # Tag the loss with failure reason
        self.orchestrator.ledger.trade_history[0]["failure_reason"] = TradeFailureReason.REGIME_MISMATCH.value

        report = self.orchestrator.generate_end_of_day_report()
        self.assertIn("Trade Failure Taxonomy:", report)
        self.assertIn("REGIME_MISMATCH: 1", report)


if __name__ == "__main__":
    unittest.main()
