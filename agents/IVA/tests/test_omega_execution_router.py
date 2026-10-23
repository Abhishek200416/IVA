"""Acceptance tests for Unified Algorithmic Execution Router & Trade Lifecycle State Machine.

TASK-BN-22:
Covers:
1. End-to-end execution pipeline from signal ingestion to simulated fill.
2. Dialectical consensus gating (abort on low conviction / neutral debate).
3. Order Flow Imbalance (OFI) false breakout / absorption rejection.
4. Pre-trade Risk Management (RMS) & Drawdown Kill-Switch rejection.
5. Almgren-Chriss Square-Root Law slippage budget gating (rejection on > 50 bps).
6. Lifecycle position tracking: Stop Loss, Take Profit, and Trailing Stop profit-locking ratchets.
7. Mandatory 15:15 IST intraday session auto square-off.
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide
from agents.AGI_1_7.engine.agi17.finance.execution_router import (
    ExecutionLifecycleState,
    ExecutionPipelineRequest,
    ExecutionPipelineResult,
    LifecyclePosition,
    UnifiedAlgorithmicExecutionRouter,
)
from agents.AGI_1_7.engine.agi17.finance.pre_trade_risk_killswitch import (
    PortfolioKillSwitch,
    PreTradeRiskEngine,
)
from agents.AGI_1_7.engine.agi17.finance.trading_agents_debate import StrategyType


class TestOmegaExecutionRouter(unittest.TestCase):
    """Test suite for Unified Algorithmic Execution Router & Lifecycle State Machine."""

    def setUp(self) -> None:
        self.router = UnifiedAlgorithmicExecutionRouter()

    def test_01_full_pipeline_success_to_simulated_fill(self) -> None:
        """Verifies clean end-to-end pipeline execution from signal to simulated fill."""
        req = ExecutionPipelineRequest(
            trade_id="TRD-001",
            spot_price=50250.0,
            vwap=50100.0,
            ema20=50150.0,
            iv=0.16,
            call_oi_change_pct=5.0,
            put_oi_change_pct=25.0,
            account_equity=1_000_000.0,
            account_drawdown_pct=0.01,
            existing_portfolio_exposure=500_000.0,
            quoted_bid=420.0,
            quoted_ask=420.50,
            prev_bid_price=419.0,
            prev_bid_units=200,
            curr_bid_price=420.0,
            curr_bid_units=350,
            prev_ask_price=420.0,
            prev_ask_units=200,
            curr_ask_price=420.50,
            curr_ask_units=150,
            order_lots=2,
        )

        res = self.router.route_and_execute(req)

        self.assertIsInstance(res, ExecutionPipelineResult)
        self.assertTrue(res.is_executed)
        self.assertEqual(res.final_state, ExecutionLifecycleState.LIFECYCLE_TRACKED)
        self.assertIsNone(res.rejection_reason)

        # Verify position attributes
        pos = res.position
        self.assertIsNotNone(pos)
        self.assertEqual(pos.units, 30)  # 2 lots * 15 units
        self.assertEqual(pos.strategy, StrategyType.BULL_CALL_SPREAD)
        self.assertGreater(pos.take_profit, pos.entry_price)
        self.assertLess(pos.stop_loss, pos.entry_price)
        self.assertEqual(pos.trailing_stop, pos.stop_loss)

        # Verify audit trail contains all lifecycle stages
        stages = [a["stage"] for a in res.audit_trail]
        self.assertIn(ExecutionLifecycleState.SIGNAL_GENERATED.value, stages)
        self.assertIn(ExecutionLifecycleState.DEBATE_RESOLVED.value, stages)
        self.assertIn(ExecutionLifecycleState.OFI_CONFIRMED.value, stages)
        self.assertIn(ExecutionLifecycleState.PRE_TRADE_RMS_APPROVED.value, stages)
        self.assertIn(ExecutionLifecycleState.SLIPPAGE_CALIBRATED.value, stages)
        self.assertIn(ExecutionLifecycleState.SIMULATED_FILL.value, stages)

    def test_02_pipeline_abort_on_neutral_debate(self) -> None:
        """Verifies execution pipeline aborts when multi-agent debate produces no conviction."""
        req = ExecutionPipelineRequest(
            trade_id="TRD-002",
            spot_price=50000.0,
            vwap=50000.0,
            ema20=50000.0,
            iv=0.09,  # Low IV below 12% chop floor
            call_oi_change_pct=2.0,
            put_oi_change_pct=2.0,
            account_equity=1_000_000.0,
            account_drawdown_pct=0.005,
            existing_portfolio_exposure=0.0,
            quoted_bid=250.0,
            quoted_ask=250.50,
            prev_bid_price=250.0,
            prev_bid_units=100,
            curr_bid_price=250.0,
            curr_bid_units=100,
            prev_ask_price=250.50,
            prev_ask_units=100,
            curr_ask_price=250.50,
            curr_ask_units=100,
        )

        res = self.router.route_and_execute(req)
        self.assertFalse(res.is_executed)
        self.assertEqual(res.final_state, ExecutionLifecycleState.ABORTED_NO_CONVICTION)
        self.assertIsNone(res.position)

    def test_03_pipeline_rejection_on_ofi_absorption_contradiction(self) -> None:
        """Verifies pipeline rejects a false breakout when order flow shows aggressive absorption."""
        # Bullish price indicators, but aggressive sellers dropping bids (heavily negative OFI)
        req = ExecutionPipelineRequest(
            trade_id="TRD-003",
            spot_price=50300.0,
            vwap=50100.0,
            ema20=50150.0,
            iv=0.16,
            call_oi_change_pct=5.0,
            put_oi_change_pct=30.0,
            account_equity=1_000_000.0,
            account_drawdown_pct=0.01,
            existing_portfolio_exposure=0.0,
            quoted_bid=420.0,
            quoted_ask=421.0,
            prev_bid_price=422.0,
            prev_bid_units=500,
            curr_bid_price=420.0,   # Bid dropped sharply
            curr_bid_units=100,
            prev_ask_price=423.0,
            prev_ask_units=100,
            curr_ask_price=421.0,   # Heavy seller dropped ask
            curr_ask_units=800,
        )

        res = self.router.route_and_execute(req)
        self.assertFalse(res.is_executed)
        self.assertEqual(res.final_state, ExecutionLifecycleState.REJECTED_OFI_CONTRADICTION)
        self.assertIn("OFI ABSORPTION REJECTION", res.rejection_reason)

    def test_04_pipeline_rejection_on_rms_drawdown_or_killswitch(self) -> None:
        """Verifies pipeline rejects orders when portfolio drawdown exceeds limits."""
        ks = PortfolioKillSwitch(initial_capital=1_000_000.0, max_drawdown_pct=0.03)
        ks.trip("Simulated drawdown breach")
        router_with_ks = UnifiedAlgorithmicExecutionRouter(kill_switch=ks)

        req = ExecutionPipelineRequest(
            trade_id="TRD-004",
            spot_price=50250.0,
            vwap=50100.0,
            ema20=50150.0,
            iv=0.16,
            call_oi_change_pct=5.0,
            put_oi_change_pct=25.0,
            account_equity=960_000.0,
            account_drawdown_pct=0.04,  # 4% drawdown exceeds 3%
            existing_portfolio_exposure=0.0,
            quoted_bid=420.0,
            quoted_ask=420.50,
            prev_bid_price=419.0,
            prev_bid_units=200,
            curr_bid_price=420.0,
            curr_bid_units=300,
            prev_ask_price=420.0,
            prev_ask_units=200,
            curr_ask_price=420.50,
            curr_ask_units=150,
        )

        res = router_with_ks.route_and_execute(req)
        self.assertFalse(res.is_executed)
        # Should be aborted or rejected by RMS
        self.assertIn(
            res.final_state,
            (ExecutionLifecycleState.ABORTED_NO_CONVICTION, ExecutionLifecycleState.REJECTED_RMS_RISK),
        )

    def test_05_pipeline_rejection_on_excessive_slippage(self) -> None:
        """Verifies pipeline gates execution when quoted spread causes slippage to breach 50 bps."""
        req = ExecutionPipelineRequest(
            trade_id="TRD-005",
            spot_price=50250.0,
            vwap=50100.0,
            ema20=50150.0,
            iv=0.16,
            call_oi_change_pct=5.0,
            put_oi_change_pct=25.0,
            account_equity=1_000_000.0,
            account_drawdown_pct=0.01,
            existing_portfolio_exposure=0.0,
            # Extremely wide spread (bid 400, ask 450 = 50 pt spread on 425 mid = ~588 bps!)
            quoted_bid=400.0,
            quoted_ask=450.0,
            prev_bid_price=399.0,
            prev_bid_units=100,
            curr_bid_price=400.0,
            curr_bid_units=200,
            prev_ask_price=450.0,
            prev_ask_units=100,
            curr_ask_price=450.0,
            curr_ask_units=100,
            order_lots=2,
        )

        res = self.router.route_and_execute(req)
        self.assertFalse(res.is_executed)
        self.assertEqual(res.final_state, ExecutionLifecycleState.REJECTED_SLIPPAGE_EXCESSIVE)
        self.assertIn("SLIPPAGE REJECTION", res.rejection_reason)

    def test_06_lifecycle_tracking_take_profit_and_stop_loss(self) -> None:
        """Verifies lifecycle state machine transitions upon Stop Loss and Take Profit hits."""
        pos = LifecyclePosition(
            position_id="POS-100",
            trade_id="TRD-100",
            symbol="BANKNIFTY26OCT50000CE",
            strategy=StrategyType.BULL_CALL_SPREAD,
            side=OrderSide.BUY,
            units=30,
            lots=2,
            entry_price=500.0,
            stop_loss=350.0,
            take_profit=750.0,
            trailing_stop=350.0,
            highest_favorable_price=500.0,
            lowest_favorable_price=500.0,
            state=ExecutionLifecycleState.LIFECYCLE_TRACKED,
        )

        # 1. Price drops to Stop Loss (340 <= 350)
        closed_sl = self.router.update_lifecycle_tick(pos, current_market_price=340.0)
        self.assertEqual(closed_sl.state, ExecutionLifecycleState.CLOSED_STOP_LOSS)
        self.assertEqual(closed_sl.exit_price, 340.0)
        self.assertEqual(closed_sl.realized_pnl, (340.0 - 500.0) * 30)

        # 2. Reset position and test Take Profit (760 >= 750)
        pos2 = LifecyclePosition(
            position_id="POS-101",
            trade_id="TRD-101",
            symbol="BANKNIFTY26OCT50000CE",
            strategy=StrategyType.BULL_CALL_SPREAD,
            side=OrderSide.BUY,
            units=30,
            lots=2,
            entry_price=500.0,
            stop_loss=350.0,
            take_profit=750.0,
            trailing_stop=350.0,
            highest_favorable_price=500.0,
            lowest_favorable_price=500.0,
            state=ExecutionLifecycleState.LIFECYCLE_TRACKED,
        )
        closed_tp = self.router.update_lifecycle_tick(pos2, current_market_price=760.0)
        self.assertEqual(closed_tp.state, ExecutionLifecycleState.CLOSED_TAKE_PROFIT)
        self.assertEqual(closed_tp.exit_price, 760.0)
        self.assertEqual(closed_tp.realized_pnl, (760.0 - 500.0) * 30)

    def test_07_lifecycle_tracking_trailing_stop_ratchet_and_squareoff(self) -> None:
        """Verifies trailing stop locks profits and mandatory 15:15 IST closes position."""
        pos = LifecyclePosition(
            position_id="POS-102",
            trade_id="TRD-102",
            symbol="BANKNIFTY26OCT50000CE",
            strategy=StrategyType.BULL_CALL_SPREAD,
            side=OrderSide.BUY,
            units=30,
            lots=2,
            entry_price=500.0,
            stop_loss=350.0,
            take_profit=800.0,
            trailing_stop=350.0,
            highest_favorable_price=500.0,
            lowest_favorable_price=500.0,
            state=ExecutionLifecycleState.LIFECYCLE_TRACKED,
        )

        # Market advances favorably to 600.0 (+100 pt gain)
        # Trailing stop ratchets to entry + 100 * (1 - 0.15) = 500 + 85 = 585
        pos = self.router.update_lifecycle_tick(pos, current_market_price=600.0)
        self.assertEqual(pos.state, ExecutionLifecycleState.LIFECYCLE_TRACKED)
        self.assertGreater(pos.trailing_stop, 550.0)

        # Market pulls back to 580 (breaching ratcheted trailing stop)
        closed_trail = self.router.update_lifecycle_tick(pos, current_market_price=580.0)
        self.assertEqual(closed_trail.state, ExecutionLifecycleState.CLOSED_TRAILING_STOP)
        self.assertGreater(closed_trail.realized_pnl, 0.0)  # Locked positive gain!

        # Test mandatory intraday 15:15 IST square-off
        pos3 = LifecyclePosition(
            position_id="POS-103",
            trade_id="TRD-103",
            symbol="BANKNIFTY26OCT50000CE",
            strategy=StrategyType.BULL_CALL_SPREAD,
            side=OrderSide.BUY,
            units=30,
            lots=2,
            entry_price=500.0,
            stop_loss=350.0,
            take_profit=800.0,
            trailing_stop=350.0,
            highest_favorable_price=500.0,
            lowest_favorable_price=500.0,
            state=ExecutionLifecycleState.LIFECYCLE_TRACKED,
        )
        closed_sq = self.router.update_lifecycle_tick(pos3, current_market_price=520.0, is_intraday_square_off=True)
        self.assertEqual(closed_sq.state, ExecutionLifecycleState.CLOSED_SQUARE_OFF)
        self.assertEqual(closed_sq.exit_price, 520.0)
        self.assertIn("15:15 IST", closed_sq.close_reason)

    def test_07_rejection_on_kill_switch_engaged(self) -> None:
        """Verifies pipeline rejects order immediately when kill switch is tripped."""
        self.router.kill_switch.trip(reason="Peak drawdown circuit breaker triggered")
        req = ExecutionPipelineRequest(
            trade_id="TRD-KS-007",
            spot_price=50250.0,
            vwap=50100.0,
            ema20=50150.0,
            iv=0.16,
            call_oi_change_pct=5.0,
            put_oi_change_pct=25.0,
        )
        res = self.router.route_and_execute(req)
        self.assertFalse(res.is_executed)
        self.assertEqual(res.final_state, ExecutionLifecycleState.REJECTED_RMS_RISK)
        self.assertIn("Kill switch active", res.rejection_reason)


if __name__ == "__main__":
    unittest.main()

