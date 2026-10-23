"""AGI 1.7 OMEGA COMMAND — Mission Acceptance Test Suite.

Validates the full mission requirements:
- Persistent 24/7 Supervisor state machine & loop continuity
- IDLE_HEALTHY low-cost standby & task resumption
- Daily token budget cap (1M tokens) & BUDGET_PAUSED state
- BANK NIFTY options contract specifications, Greeks, & Black-Scholes pricing
- Stale/invalid market quote rejection (NO_SIGNAL_DATA_INVALID)
- Paper trading ledger, idempotency, slippage, statutory fees, & kill switch
- Zero live order execution guarantee
- 9-layer context engineering & conflict detection
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.adapters.agi_17_adapter import AGI17Adapter
from agents.AGI_1_7.engine.agi17.context.context_engine import (
    ContextEngine,
    EpistemicStatus,
)
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import (
    BankNiftyContractSpec,
    BankNiftyPaperTrader,
    BlackScholesCalculator,
    MarketRegime,
    OptionGreeks,
    OptionType,
    OrderSide,
    OrderType,
    SignalStatus,
)
from agents.AGI_1_7.engine.agi17.supervisor.persistent_supervisor import (
    PersistentSupervisor,
    QueuedTask,
    SupervisorState,
    TaskPriority,
)


class TestOmegaMissionAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.storage_root = self.temp_path / "storage"
        self.eval_root = self.temp_path / "eval"
        self.adapter = AGI17Adapter(storage_root=self.storage_root, eval_root=self.eval_root)

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # 1. Persistent Supervisor State Machine Flow
    def test_01_persistent_supervisor_state_machine_flow(self) -> None:
        state_file = self.storage_root / "state" / "test_run_state.json"
        supervisor = PersistentSupervisor(
            adapter=self.adapter,
            state_file=state_file,
            idle_sleep_sec=0.01,
        )
        self.assertEqual(supervisor.current_state, SupervisorState.STARTING)

        # First cycle does startup recovery
        st1 = supervisor.run_single_cycle()
        self.assertEqual(st1, SupervisorState.READY)

        # Enqueue a deterministic local task
        supervisor.enqueue_task(
            title="Fast Math Task",
            description="What is 25 * 4?",
            priority=TaskPriority.FEATURE_IMPROVEMENT,
        )

        # Next cycle executes the task through the full state machine
        st2 = supervisor.run_single_cycle()
        self.assertEqual(st2, SupervisorState.READY)
        self.assertEqual(supervisor.total_completed, 1)
        self.assertEqual(len(supervisor.task_history), 1)
        self.assertEqual(supervisor.task_history[0]["status"], "SUCCEEDED")
        self.assertTrue(state_file.exists())

    # 2. Loop Continuity: Supervisor Does Not Terminate After Single Task
    def test_02_supervisor_loop_continuity_after_task_completion(self) -> None:
        supervisor = PersistentSupervisor(
            adapter=self.adapter,
            state_file=self.storage_root / "state" / "continuity_state.json",
            idle_sleep_sec=0.01,
        )
        supervisor.run_single_cycle()  # STARTING -> READY

        supervisor.enqueue_task(title="Task A", description="What is 10 + 20?")
        supervisor.enqueue_task(title="Task B", description="What is 30 + 40?")

        # Cycle 1 executes Task A
        supervisor.run_single_cycle()
        self.assertEqual(supervisor.total_completed, 1)

        # Cycle 2 executes Task B without halting
        supervisor.run_single_cycle()
        self.assertEqual(supervisor.total_completed, 2)
        self.assertFalse(supervisor.stop_requested)

    # 3. IDLE_HEALTHY When Queue is Empty & Dynamic Resumption
    def test_03_supervisor_idle_healthy_when_queue_empty_and_resumption(self) -> None:
        supervisor = PersistentSupervisor(
            adapter=self.adapter,
            state_file=self.storage_root / "state" / "idle_state.json",
            idle_sleep_sec=0.01,
        )
        supervisor.run_single_cycle()  # STARTING -> READY

        # With empty queue, transitions to IDLE_HEALTHY
        st_idle = supervisor.run_single_cycle()
        self.assertEqual(st_idle, SupervisorState.IDLE_HEALTHY)

        # Health probe is operational
        health = supervisor.check_health()
        self.assertEqual(health["status"], "HEALTHY")

        # Now dynamically enqueue work
        supervisor.enqueue_task(title="Task After Idle", description="What is 50 + 50?")

        # Next cycle transitions from IDLE to SELECTING_TASK and executes
        st_resumed = supervisor.run_single_cycle()
        self.assertEqual(st_resumed, SupervisorState.READY)
        self.assertEqual(supervisor.total_completed, 1)

    # 4. Token Budget Pause & Continuation of Local Tasks
    def test_04_supervisor_token_budget_pause_and_local_work(self) -> None:
        supervisor = PersistentSupervisor(
            adapter=self.adapter,
            state_file=self.storage_root / "state" / "budget_state.json",
            idle_sleep_sec=0.01,
        )
        supervisor.run_single_cycle()

        # Artificially consume budget to 1,000,000 limit
        supervisor.adapter.token_controller.record_usage(
            task_id="BUDGET-BURN",
            agent_id="test_agent",
            provider_usage={"input_tokens": 500_000, "output_tokens": 500_000, "total_tokens": 1_000_000},
        )
        self.assertGreaterEqual(supervisor.adapter.token_controller.get_summary()["total_tokens"], 1_000_000)

        # Enqueue one model-dependent task and one deterministic local task
        supervisor.enqueue_task(title="Model Call Task", description="Requires LLM", requires_model_call=True)
        supervisor.enqueue_task(title="Local Deterministic Task", description="What is 12 * 12?", requires_model_call=False)

        # Running cycle selects the local task despite budget limit
        supervisor.run_single_cycle()
        self.assertEqual(supervisor.total_completed, 1)
        self.assertEqual(supervisor.task_history[-1]["title"], "Local Deterministic Task")

        # Attempting next cycle when only model task remains enters BUDGET_PAUSED without crashing
        st = supervisor.run_single_cycle()
        self.assertEqual(st, SupervisorState.BUDGET_PAUSED)

    # 5. Clean SAFE_HALT on Stop Request
    def test_05_supervisor_safe_halt_on_request(self) -> None:
        supervisor = PersistentSupervisor(
            adapter=self.adapter,
            state_file=self.storage_root / "state" / "halt_state.json",
            idle_sleep_sec=0.01,
        )
        supervisor.run_single_cycle()
        supervisor.request_stop()
        final_state = supervisor.run_continuous_loop(max_cycles=5)
        self.assertEqual(final_state, SupervisorState.SAFE_HALT)

    # 6. BANK NIFTY Contract Specs & ATM Strike Calculation
    def test_06_bank_nifty_contract_spec_and_atm_calculation(self) -> None:
        self.assertEqual(BankNiftyContractSpec.LOT_SIZE, 15)
        self.assertEqual(BankNiftyContractSpec.STRIKE_STEP, 100.0)
        self.assertEqual(BankNiftyContractSpec.TICK_SIZE, 0.05)

        # ATM Strike rounding
        self.assertEqual(BankNiftyContractSpec.get_atm_strike(51949.20), 51900.0)
        self.assertEqual(BankNiftyContractSpec.get_atm_strike(51950.00), 52000.0)
        self.assertEqual(BankNiftyContractSpec.get_atm_strike(52030.15), 52000.0)

        # Tick rounding
        self.assertEqual(BankNiftyContractSpec.round_to_tick(420.123), 420.10)
        self.assertEqual(BankNiftyContractSpec.round_to_tick(420.14), 420.15)

    # 7. Black-Scholes Option Pricing & Greeks
    def test_07_black_scholes_pricing_and_greeks_derivation(self) -> None:
        spot = 52000.0
        strike = 52000.0
        t = 7.0 / 365.0  # 7 days to expiry
        r = 0.065  # 6.5% risk free rate
        vol = 0.18  # 18% IV

        call_greeks = BlackScholesCalculator.calculate_greeks(spot, strike, t, r, vol, OptionType.CE)
        put_greeks = BlackScholesCalculator.calculate_greeks(spot, strike, t, r, vol, OptionType.PE)

        self.assertGreater(call_greeks.price, 0.0)
        self.assertGreater(put_greeks.price, 0.0)
        # ATM Delta properties: Call delta ~0.5, Put delta ~ -0.5
        self.assertAlmostEqual(call_greeks.delta, 0.51, delta=0.05)
        self.assertAlmostEqual(put_greeks.delta, -0.49, delta=0.05)
        # Gamma and Vega are positive
        self.assertGreater(call_greeks.gamma, 0.0)
        self.assertGreater(call_greeks.vega, 0.0)

        # Test Implied Volatility calculation inverse
        solved_iv = BlackScholesCalculator.calculate_implied_volatility(
            market_price=call_greeks.price,
            spot=spot,
            strike=strike,
            time_to_expiry_years=t,
            rate=r,
            option_type=OptionType.CE,
        )
        self.assertAlmostEqual(solved_iv, vol, delta=0.01)

    # 8. Market Quote Validation & Stale Data Rejection
    def test_08_market_data_validation_and_stale_data_rejection(self) -> None:
        trader = BankNiftyPaperTrader(initial_capital=500_000.0)
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()

        # Valid quote
        valid_quote = {
            "symbol": "BANKNIFTY",
            "price": 52100.0,
            "bid": 52095.0,
            "ask": 52105.0,
            "timestamp": now_ts,
        }
        ok, reason = trader.validate_market_quote(valid_quote)
        self.assertTrue(ok)
        self.assertEqual(reason, "VALID")

        # Inverted spread rejection
        bad_spread = {
            "symbol": "BANKNIFTY",
            "price": 52100.0,
            "bid": 52110.0,
            "ask": 52100.0,
            "timestamp": now_ts,
        }
        ok, reason = trader.validate_market_quote(bad_spread)
        self.assertFalse(ok)
        self.assertIn("Inverted spread", reason)

        # Stale data rejection (stale by 600s)
        stale_quote = {
            "symbol": "BANKNIFTY",
            "price": 52100.0,
            "bid": 52095.0,
            "ask": 52105.0,
            "timestamp": now_ts - 600.0,
        }
        ok, reason = trader.validate_market_quote(stale_quote, max_staleness_seconds=300.0)
        self.assertFalse(ok)
        self.assertIn("stale", reason)

        # Signal evaluation on stale data returns DATA_INVALID
        sig = trader.evaluate_signal(52100.0, stale_quote, MarketRegime.TRENDING_BULL)
        self.assertEqual(sig.status, SignalStatus.DATA_INVALID)
        self.assertEqual(sig.recommended_lots, 0)

    # 9. Paper Trading Order Execution & Idempotency
    def test_09_paper_trading_execution_and_idempotency(self) -> None:
        ledger = self.storage_root / "finance" / "paper_ledger.jsonl"
        trader = BankNiftyPaperTrader(initial_capital=500_000.0, ledger_file=ledger)

        res = trader.execute_paper_order(
            idempotency_key="ORD-KEY-001",
            symbol="BANKNIFTY26OCT52000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=30,  # 2 lots
            market_price=350.0,
        )
        self.assertTrue(res["success"])
        self.assertEqual(trader.positions["BANKNIFTY26OCT52000CE"], 30)
        self.assertLess(trader.cash, 500_000.0)
        self.assertTrue(ledger.exists())

        # Exact duplicate idempotency submission returns cached order without double-spending
        cash_before = trader.cash
        res_dup = trader.execute_paper_order(
            idempotency_key="ORD-KEY-001",
            symbol="BANKNIFTY26OCT52000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=30,
            market_price=350.0,
        )
        self.assertTrue(res_dup["success"])
        self.assertTrue(res_dup.get("deduplicated"))
        self.assertEqual(trader.cash, cash_before)
        self.assertEqual(trader.positions["BANKNIFTY26OCT52000CE"], 30)

    # 10. Paper Trading Kill Switch & Risk Limits
    def test_10_paper_trading_kill_switch_and_drawdown_blocks(self) -> None:
        trader = BankNiftyPaperTrader(initial_capital=500_000.0)
        trader.activate_kill_switch(reason="Test safety trigger")
        self.assertTrue(trader.kill_switch_active)

        # Orders blocked
        res = trader.execute_paper_order(
            idempotency_key="KILL-TEST",
            symbol="BANKNIFTY26OCT52000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=15,
            market_price=300.0,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["reason"], "KILL_SWITCH_ACTIVE")

        # Signals blocked
        valid_quote = {
            "symbol": "BANKNIFTY",
            "price": 52000.0,
            "bid": 51995.0,
            "ask": 52005.0,
            "timestamp": time.time(),
        }
        sig = trader.evaluate_signal(52000.0, valid_quote, MarketRegime.TRENDING_BULL)
        self.assertEqual(sig.status, SignalStatus.RISK_BLOCKED)

    # 11. Zero Live Order Execution Guarantee
    def test_11_zero_live_order_execution_verification(self) -> None:
        trader = BankNiftyPaperTrader()
        metrics = trader.get_summary_metrics()
        self.assertTrue(metrics["zero_live_order_execution_guarantee"])
        # Verify no broker live order methods exist
        for attr in ("place_order", "send_broker_order", "live_execute", "execute_brokerage"):
            self.assertFalse(hasattr(trader, attr))

    # 12. 9-Layer Context Engineering & Conflict Detection
    def test_12_context_engineering_manifest_and_conflict_detection(self) -> None:
        engine = ContextEngine()

        f1 = engine.register_fact(
            subject_key="market:expiry_day",
            claim="Bank Nifty weekly expiry contracts expire on Thursday",
            status=EpistemicStatus.VERIFIED_FACT,
            provenance="NSE_CIRCULAR_2024",
        )
        f2 = engine.register_fact(
            subject_key="market:expiry_day",
            claim="Bank Nifty weekly expiry contracts expire on Wednesday",
            status=EpistemicStatus.DISPROVEN,
            provenance="STALE_COMMUNITY_SPEC",
        )

        conflicts = engine.detect_conflicts([f1, f2])
        self.assertEqual(len(conflicts), 1)
        self.assertIn("market:expiry_day", conflicts[0])

        manifest = engine.assemble_manifest(
            task_id="TEST-CONTEXT-001",
            objective="Assemble 9-layer context",
            acceptance_criteria=["Zero credential leakage", "Conflict warning emitted"],
        )
        self.assertIn("--- INVARIANTS ---", manifest.compact_prompt_block)
        self.assertIn("--- CONFLICT WARNINGS ---", manifest.compact_prompt_block)
        self.assertGreater(manifest.estimated_context_tokens, 10)


if __name__ == "__main__":
    unittest.main()
