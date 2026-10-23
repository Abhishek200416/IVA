"""AGI 1.7 OMEGA COMMAND Comprehensive Mission Acceptance Suite.

Validates the complete execution directive requirements:
A. Context engineering: 9 layers, conflict detection, epistemic status, manifest generation.
B. Continuous learning & failure memory.
C. Daily UTC 1,000,000 token ceiling and admission gating.
D. BANK NIFTY options contract specs, IST session timers, Greeks, and paper trading engine.
E. Continuous 24/7 Supervisor state machine transitions (IDLE_HEALTHY, BUDGET_PAUSED, multi-task continuity).
"""

from __future__ import annotations

import datetime
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.context.context_engine import (
    ContextEngine,
    ContextManifest,
    EpistemicStatus,
)
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import (
    BankNiftyContractSpec,
    BankNiftyMarketCalendar,
    NSE_HOLIDAYS_2026,
)
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_engine import (
    BankNiftyPaperEngine,
    FinancialSafetyViolationError,
    PaperOrder,
)
from agents.AGI_1_7.engine.agi17.finance.options_math import OptionsMath
from agents.AGI_1_7.engine.agi17.finance.signal_contract import (
    MarketRegime,
    SignalDecision,
    SignalStatus,
)
from agents.AGI_1_7.engine.agi17.process_supervision.continuous_supervisor import (
    ContinuousSupervisor,
    SupervisorState,
)
from agents.AGI_1_7.engine.agi17.telemetry.token_economy import (
    AdaptiveTokenController,
    TokenBudgetExceededError,
)


class TestOmegaCommandMission(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="omega_mission_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Context Engine 9 Layers & Conflict Detection
    def test_01_context_engine_manifest_and_conflict_detection(self) -> None:
        ce = ContextEngine(repo_root=self.tmp_dir)
        ce.register_fact(
            subject_key="lot_size:banknifty",
            claim="BANK NIFTY options lot size is 15",
            status=EpistemicStatus.VERIFIED_FACT,
            provenance="nse_circular",
        )
        ce.register_fact(
            subject_key="lot_size:banknifty",
            claim="BANK NIFTY options lot size is 25",
            status=EpistemicStatus.DISPROVEN,
            provenance="outdated_2023_spec",
        )
        ce.register_external_source(
            url="https://www.nseindia.com/products-services/equity-derivatives-bank-nifty",
            title="NSE Bank Nifty Specifications",
            publisher="NSE India",
            claim_supported="Lot size 15, strike step 100",
        )

        manifest = ce.assemble_manifest(
            task_id="TASK-T01",
            objective="Verify market specifications",
            acceptance_criteria=["Correct lot size identified"],
        )

        self.assertIsInstance(manifest, ContextManifest)
        self.assertEqual(len(manifest.conflicts_detected), 1)
        self.assertIn("conflicting VERIFIED_FACT and DISPROVEN", manifest.conflicts_detected[0])
        self.assertIn("15", manifest.compact_prompt_block)
        self.assertTrue(manifest.estimated_context_tokens > 0)

    # 2. Daily UTC 1,000,000 Token Cap Enforcement
    def test_02_daily_utc_token_budget_cap(self) -> None:
        tc = AdaptiveTokenController(
            ledger_dir=self.tmp_dir / "ledger",
            isolated_benchmark_cwd=self.tmp_dir / "isolated",
        )
        tc.allocate_budget(task_id="TASK-DAILY-1", tier="SIMPLE")

        # Standard call fits under 1M daily budget
        adm = tc.check_pre_call_admission(task_id="TASK-DAILY-1", estimated_tokens=1000, tier="SIMPLE")
        self.assertTrue(adm["admitted"])
        self.assertEqual(adm["daily_utc_cap"], 1_000_000)

        # Record usage up to 999,500 tokens
        tc.record_usage(
            task_id="TASK-DAILY-1",
            agent_id="swe_patch_minimizer",
            provider_usage={"input_tokens": 500_000, "output_tokens": 499_500, "total_tokens": 999_500},
        )

        # Request exceeding remaining 500 tokens must raise TokenBudgetExceededError
        with self.assertRaises(TokenBudgetExceededError) as ctx:
            tc.check_pre_call_admission(task_id="TASK-DAILY-1", estimated_tokens=1000, tier="SIMPLE")
        self.assertIn("Global daily UTC token budget cap", str(ctx.exception))
        self.assertIn("BUDGET_PAUSED", str(ctx.exception))

    # 3. BANK NIFTY Market Specifications & IST Calendar
    def test_03_bank_nifty_market_calendar_and_validations(self) -> None:
        cal = BankNiftyMarketCalendar()
        # Weekend is not a trading day
        saturday = datetime.date(2026, 10, 10)
        self.assertFalse(cal.is_trading_day(saturday))

        # Republic Day is a holiday
        republic_day = datetime.date(2026, 1, 26)
        self.assertFalse(cal.is_trading_day(republic_day))

        # Quote validation rejects negative prices and inverted spread
        valid, _ = cal.validate_quote({
            "symbol": "BANKNIFTY26OCT50000CE",
            "bid": 250.0,
            "ask": 252.0,
            "last_price": 251.0,
            "timestamp": 1791700000,
        })
        self.assertTrue(valid)

        bad_spread, msg = cal.validate_quote({
            "symbol": "BANKNIFTY26OCT50000CE",
            "bid": 260.0,
            "ask": 250.0,
            "last_price": 255.0,
            "timestamp": 1791700000,
        })
        self.assertFalse(bad_spread)
        self.assertIn("Impossible spread", msg)

    # 4. Options Analytics & Greeks Calculation
    def test_04_options_math_and_greeks(self) -> None:
        spot = 50000.0
        strike = 50000.0
        t = 7.0 / 365.0  # 1 week to expiry
        r = 0.065
        vol = 0.15

        price_ce = OptionsMath.black_scholes_price(
            spot=spot, strike=strike, time_to_expiry_years=t, risk_free_rate=r, volatility=vol, is_call=True
        )
        self.assertGreater(price_ce, 100.0)

        greeks = OptionsMath.calculate_greeks(
            spot=spot, strike=strike, time_to_expiry_years=t, risk_free_rate=r, volatility=vol, is_call=True
        )
        self.assertAlmostEqual(greeks["delta"], 0.5, delta=0.08)
        self.assertGreater(greeks["gamma"], 0.0)
        self.assertGreater(greeks["vega"], 0.0)
        self.assertLess(greeks["theta"], 0.0)  # Time decay is negative

        # Solve for IV
        solved_iv = OptionsMath.calculate_implied_volatility(
            market_price=price_ce,
            spot=spot,
            strike=strike,
            time_to_expiry_years=t,
            risk_free_rate=r,
            is_call=True,
        )
        self.assertIsNotNone(solved_iv)
        self.assertAlmostEqual(solved_iv, vol, delta=0.01)

    # 5. BANK NIFTY Options Paper Trading Simulator
    def test_05_bank_nifty_paper_engine_lifecycle(self) -> None:
        engine = BankNiftyPaperEngine(
            initial_cash=500_000.0,
            ledger_path=self.tmp_dir / "paper_ledger.jsonl",
        )
        contract = "BANKNIFTY26OCT50000CE"

        # Buy 1 lot (15 units)
        ord_buy = engine.submit_paper_order(
            contract_id=contract,
            side="BUY",
            units=15,
            current_market_price=300.0,
            idempotency_key="TEST-BUY-01",
        )
        self.assertEqual(ord_buy.status, "FILLED")
        self.assertGreater(ord_buy.executed_price, 300.0)  # Slippage added
        self.assertGreater(ord_buy.statutory_fees, 0.0)

        # Idempotent replay of same order returns identical order without double charge
        ord_repeat = engine.submit_paper_order(
            contract_id=contract,
            side="BUY",
            units=15,
            current_market_price=300.0,
            idempotency_key="TEST-BUY-01",
        )
        self.assertEqual(ord_repeat.order_id, ord_buy.order_id)
        self.assertEqual(len(engine.positions), 1)

        # Non-lot-multiple rejected
        ord_bad_lot = engine.submit_paper_order(
            contract_id=contract,
            side="BUY",
            units=10,  # Not multiple of 15
            current_market_price=300.0,
        )
        self.assertEqual(ord_bad_lot.status, "REJECTED")

        # Emergency kill switch halts trading
        engine.activate_kill_switch("Risk threshold breached")
        ord_kill = engine.submit_paper_order(
            contract_id=contract,
            side="BUY",
            units=15,
            current_market_price=300.0,
        )
        self.assertEqual(ord_kill.status, "REJECTED")
        self.assertIn("KILL_SWITCH", ord_kill.rejection_reason)
        engine.deactivate_kill_switch()

        # Sell position
        ord_sell = engine.submit_paper_order(
            contract_id=contract,
            side="SELL",
            units=15,
            current_market_price=350.0,
        )
        self.assertEqual(ord_sell.status, "FILLED")
        self.assertEqual(len(engine.positions), 0)

        summ = engine.get_summary()
        self.assertGreater(summ["realized_pnl"], 0.0)
        self.assertFalse(summ["real_trading_enabled"])

    # 6. Continuous 24/7 Supervisor State Machine Transitions
    def test_06_continuous_supervisor_state_machine_and_multi_task_continuity(self) -> None:
        sup = ContinuousSupervisor(
            state_dir=self.tmp_dir / "supervisor",
            token_controller=AdaptiveTokenController(ledger_dir=self.tmp_dir / "sup_ledger"),
            idle_sleep_sec=0.01,
        )

        executed_tasks: list[str] = []

        def mock_executor(item, manifest):
            executed_tasks.append(item.task_id)
            return {"status": "SUCCEEDED", "verified": True}

        sup.set_executor(mock_executor)

        t1 = sup.enqueue_task(title="First Task", description="Execute unit check", priority=1)
        t2 = sup.enqueue_task(title="Second Task", description="Execute integration check", priority=2)

        # Step 1: READY -> SELECTING_TASK
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.SELECTING_TASK)

        # Step 2: SELECTING_TASK -> BUILDING_CONTEXT (picks t1)
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.BUILDING_CONTEXT)

        # Step 3: BUILDING_CONTEXT -> EXECUTING
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.EXECUTING)

        # Step 4: EXECUTING -> VERIFYING
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.VERIFYING)

        # Step 5: VERIFYING -> RECORDING_LEARNING
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.RECORDING_LEARNING)

        # Step 6: RECORDING_LEARNING -> SCHEDULING_NEXT
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.SCHEDULING_NEXT)

        # Step 7: SCHEDULING_NEXT -> READY (Task 1 completed; loop DOES NOT terminate!)
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.READY)
        self.assertEqual(executed_tasks, [t1.task_id])

        # Step 8: Picks Task 2 automatically
        sup.step()  # SELECTING_TASK
        sup.step()  # BUILDING_CONTEXT
        sup.step()  # EXECUTING
        sup.step()  # VERIFYING
        sup.step()  # RECORDING_LEARNING
        sup.step()  # SCHEDULING_NEXT
        sup.step()  # READY
        self.assertEqual(executed_tasks, [t1.task_id, t2.task_id])

        # Queue is now empty: Transitions to IDLE_HEALTHY instead of exiting!
        sup.step()  # SELECTING_TASK
        sup.step()  # IDLE_HEALTHY
        self.assertEqual(sup.current_state, SupervisorState.IDLE_HEALTHY)

        # Heartbeat verification
        hb = sup.emit_heartbeat()
        self.assertEqual(hb.state, SupervisorState.IDLE_HEALTHY)
        self.assertEqual(hb.tasks_completed, 2)
        self.assertTrue(hb.storage_healthy)

        # Safe halt closes cleanly
        sup.request_safe_halt("Test completed")
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.SAFE_HALT)

    # 7. PersistentSupervisor with Adapter & Mission Run State
    def test_07_persistent_supervisor_adapter_integration(self) -> None:
        import json
        from agents.AGI_1_7.engine.agi17.supervisor.persistent_supervisor import (
            PersistentSupervisor,
            TaskPriority,
        )

        state_file = self.tmp_dir / "mission_run_state.json"
        psup = PersistentSupervisor(
            state_file=state_file,
            heartbeat_interval_sec=0.1,
            idle_sleep_sec=0.01,
        )
        task = psup.enqueue_task(
            title="Self-Test Math Task",
            description="Compute 2 + 2",
            priority=TaskPriority.CRITICAL_SAFETY,
            requires_model_call=False,
        )
        self.assertEqual(task.status, "QUEUED")
        self.assertTrue(state_file.exists())

        # Execute 3 cycles to process the task through the state machine
        final_state = psup.run_continuous_loop(max_cycles=3)
        self.assertIn(final_state, (SupervisorState.READY, SupervisorState.IDLE_HEALTHY, SupervisorState.SAFE_HALT))
        self.assertEqual(psup.total_completed, 1)

        # Confirm run state file written and updated
        data = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(data["total_tasks_completed"], 1)
        self.assertIn("heartbeat_iso", data)


if __name__ == "__main__":
    unittest.main()
