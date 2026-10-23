"""Unit test battery for Asynchronous Cross-Asset Lead-Lag Arbitrage Engine.

Wave 34 Verification Suite (TASK-BN-44):
Validates:
1. Indian SEBI lot size quantization (Bank Nifty = 15, Nifty = 25).
2. NIFTY 50 leads BANK NIFTY: positive spread generates lot-quantized BUY_LAGGING execution.
3. BANK NIFTY leads NIFTY 50: negative spread generates lot-quantized SELL_LAGGING execution.
4. Friction barrier: trades where net edge is below hurdle are rejected with FRICTION_BARRIER_REJECTED.
5. Insufficient correlation yields HOLD_NEUTRAL / CONFIDENCE_TOO_LOW.
6. Capital constraints trigger CAPITAL_INSUFFICIENT safely.
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.cross_impact_matrix import (
    AsynchronousTick,
    MarketIndex,
)
from agents.AGI_1_7.engine.agi17.finance.lead_lag_arbitrage_engine import (
    ArbitrageAction,
    ArbitrageExecutionStatus,
    ArbitrageOrderLeg,
    AsynchronousLeadLagArbitrageEngine,
    LeadLagArbitrageExecution,
    LeadLagArbitrageSignal,
)


class TestOmegaLeadLagArbitrageEngine(unittest.TestCase):
    """Test suite for Wave 34 Asynchronous Lead-Lag Arbitrage Engine."""

    def setUp(self) -> None:
        self.engine = AsynchronousLeadLagArbitrageEngine(
            min_correlation_threshold=0.35,
            min_net_edge_inr=150.0,
            spread_bps_friction=0.5,
            statutory_rate=0.0002,
            max_lots=5,
            half_life_multiplier=1.5,
        )

    def test_lot_size_quantization(self) -> None:
        """Verify Indian index derivative discrete lot sizes."""
        self.assertEqual(AsynchronousLeadLagArbitrageEngine.get_lot_size(MarketIndex.BANK_NIFTY), 15)
        self.assertEqual(AsynchronousLeadLagArbitrageEngine.get_lot_size(MarketIndex.NIFTY_50), 25)

    def test_nifty_leads_bank_nifty_arbitrage_execution(self) -> None:
        """NIFTY 50 leads BANK NIFTY by 1.0s; positive forecast prompts Bank Nifty catch-up BUY."""
        # Synthesize asynchronous ticks where Nifty ticks at t, Bank Nifty responds at t + 1.0
        nifty_ticks: list[AsynchronousTick] = []
        bank_ticks: list[AsynchronousTick] = []

        # 10 correlated ticks
        for i in range(12):
            t_n = float(i * 2)
            t_b = t_n + 1.0
            move = 15.0 if i % 2 == 0 else -8.0

            nifty_ticks.append(
                AsynchronousTick(
                    index=MarketIndex.NIFTY_50,
                    start_time=t_n,
                    end_time=t_n + 0.8,
                    price=24000.0 + i * 10,
                    price_change=move,
                    volume=500.0,
                )
            )
            # Bank Nifty follows with beta ~ 1.8
            bank_ticks.append(
                AsynchronousTick(
                    index=MarketIndex.BANK_NIFTY,
                    start_time=t_b,
                    end_time=t_b + 0.8,
                    price=51000.0 + i * 20,
                    price_change=move * 1.8,
                    volume=300.0,
                )
            )

        # Force recent leader move to be strongly positive, while lagging hasn't moved yet
        nifty_ticks.append(
            AsynchronousTick(
                index=MarketIndex.NIFTY_50,
                start_time=25.0,
                end_time=25.5,
                price=24150.0,
                price_change=80.0,
                volume=800.0,
            )
        )
        bank_ticks.append(
            AsynchronousTick(
                index=MarketIndex.BANK_NIFTY,
                start_time=25.2,
                end_time=25.6,
                price=51200.0,
                price_change=2.0,  # Lagging: barely moved
                volume=200.0,
            )
        )

        signal = self.engine.evaluate_signal(nifty_ticks, bank_ticks, lookback_ticks=2)
        self.assertEqual(signal.leading_asset, MarketIndex.NIFTY_50)
        self.assertEqual(signal.lagging_asset, MarketIndex.BANK_NIFTY)
        self.assertEqual(signal.action, ArbitrageAction.BUY_LAGGING)
        self.assertGreater(signal.signal_spread_pts, 5.0)

        execution = self.engine.generate_arbitrage_orders(
            signal=signal,
            current_lagging_price=51200.0,
            available_capital_inr=600000.0,
            timestamp=25.6,
        )

        self.assertEqual(execution.status, ArbitrageExecutionStatus.SIGNAL_TRIGGERED)
        self.assertIsNotNone(execution.order_leg)
        leg = execution.order_leg
        self.assertEqual(leg.target_asset, MarketIndex.BANK_NIFTY)
        self.assertEqual(leg.action, "BUY")
        self.assertEqual(leg.lot_size, 15)
        self.assertEqual(leg.contracts, leg.lots * 15)
        self.assertGreaterEqual(leg.net_edge_inr, 150.0)

    def test_bank_nifty_leads_nifty_arbitrage_execution(self) -> None:
        """BANK NIFTY leads NIFTY 50 by 1.0s; negative forecast prompts Nifty SELL catch-up."""
        nifty_ticks: list[AsynchronousTick] = []
        bank_ticks: list[AsynchronousTick] = []

        # Bank Nifty ticks at t, Nifty follows at t + 1.0
        for i in range(12):
            t_b = float(i * 2)
            t_n = t_b + 1.0
            move = -20.0 if i % 2 == 0 else 10.0

            bank_ticks.append(
                AsynchronousTick(
                    index=MarketIndex.BANK_NIFTY,
                    start_time=t_b,
                    end_time=t_b + 0.8,
                    price=51000.0 - i * 15,
                    price_change=move,
                    volume=400.0,
                )
            )
            nifty_ticks.append(
                AsynchronousTick(
                    index=MarketIndex.NIFTY_50,
                    start_time=t_n,
                    end_time=t_n + 0.8,
                    price=24000.0 - i * 7,
                    price_change=move * 0.5,
                    volume=600.0,
                )
            )

        # Recent Bank Nifty drop
        bank_ticks.append(
            AsynchronousTick(
                index=MarketIndex.BANK_NIFTY,
                start_time=25.0,
                end_time=25.5,
                price=50800.0,
                price_change=-100.0,
                volume=900.0,
            )
        )
        nifty_ticks.append(
            AsynchronousTick(
                index=MarketIndex.NIFTY_50,
                start_time=25.2,
                end_time=25.6,
                price=23950.0,
                price_change=-1.0,
                volume=300.0,
            )
        )

        signal = self.engine.evaluate_signal(nifty_ticks, bank_ticks, lookback_ticks=2)
        self.assertEqual(signal.leading_asset, MarketIndex.BANK_NIFTY)
        self.assertEqual(signal.lagging_asset, MarketIndex.NIFTY_50)
        self.assertEqual(signal.action, ArbitrageAction.SELL_LAGGING)

        execution = self.engine.generate_arbitrage_orders(
            signal=signal,
            current_lagging_price=23950.0,
            available_capital_inr=400000.0,
            timestamp=25.6,
        )

        self.assertEqual(execution.status, ArbitrageExecutionStatus.SIGNAL_TRIGGERED)
        self.assertIsNotNone(execution.order_leg)
        leg = execution.order_leg
        self.assertEqual(leg.target_asset, MarketIndex.NIFTY_50)
        self.assertEqual(leg.action, "SELL")
        self.assertEqual(leg.lot_size, 25)
        self.assertEqual(leg.contracts, leg.lots * 25)
        self.assertGreaterEqual(leg.net_edge_inr, 150.0)

    def test_friction_barrier_rejection(self) -> None:
        """Tiny discrepancy where gross edge is lower than transaction friction."""
        signal = LeadLagArbitrageSignal(
            leading_asset=MarketIndex.NIFTY_50,
            lagging_asset=MarketIndex.BANK_NIFTY,
            optimal_lag_seconds=1.0,
            peak_correlation=0.75,
            high_freq_beta=1.5,
            leader_recent_move=2.0,
            lagging_recent_move=1.8,
            forecasted_lagging_move=3.0,
            signal_spread_pts=0.40,  # 0.40 Bank Nifty points = 6.0 INR per lot of 15
            action=ArbitrageAction.BUY_LAGGING,
            is_statistically_significant=True,
        )

        # 51,000 Bank Nifty price, notional per lot = 765,000 INR
        # Friction = ~765 INR per lot; Gross edge = 0.4 * 15 = 6 INR -> Net edge is strongly negative!
        execution = self.engine.generate_arbitrage_orders(
            signal=signal,
            current_lagging_price=51000.0,
            available_capital_inr=500000.0,
            timestamp=10.0,
        )

        self.assertEqual(execution.status, ArbitrageExecutionStatus.FRICTION_BARRIER_REJECTED)
        self.assertIsNotNone(execution.order_leg)
        self.assertLess(execution.order_leg.net_edge_inr, 150.0)

    def test_confidence_too_low_on_neutral_signal(self) -> None:
        """Neutral signal generates CONFIDENCE_TOO_LOW without order leg."""
        signal = LeadLagArbitrageSignal(
            leading_asset=MarketIndex.NIFTY_50,
            lagging_asset=MarketIndex.BANK_NIFTY,
            optimal_lag_seconds=0.0,
            peak_correlation=0.15,
            high_freq_beta=0.2,
            leader_recent_move=0.5,
            lagging_recent_move=0.4,
            forecasted_lagging_move=0.1,
            signal_spread_pts=0.05,
            action=ArbitrageAction.HOLD_NEUTRAL,
            is_statistically_significant=False,
        )

        execution = self.engine.generate_arbitrage_orders(
            signal=signal,
            current_lagging_price=50000.0,
            available_capital_inr=500000.0,
        )

        self.assertEqual(execution.status, ArbitrageExecutionStatus.CONFIDENCE_TOO_LOW)
        self.assertIsNone(execution.order_leg)

    def test_capital_insufficient_handling(self) -> None:
        """Capital insufficient to cover 1 lot margin produces CAPITAL_INSUFFICIENT."""
        signal = LeadLagArbitrageSignal(
            leading_asset=MarketIndex.NIFTY_50,
            lagging_asset=MarketIndex.BANK_NIFTY,
            optimal_lag_seconds=1.0,
            peak_correlation=0.80,
            high_freq_beta=2.0,
            leader_recent_move=25.0,
            lagging_recent_move=0.0,
            forecasted_lagging_move=50.0,
            signal_spread_pts=50.0,
            action=ArbitrageAction.BUY_LAGGING,
            is_statistically_significant=True,
        )

        execution = self.engine.generate_arbitrage_orders(
            signal=signal,
            current_lagging_price=50000.0,
            available_capital_inr=500.0,  # Far below margin of ~112,500 INR
        )

        self.assertEqual(execution.status, ArbitrageExecutionStatus.CAPITAL_INSUFFICIENT)
        self.assertIsNone(execution.order_leg)


if __name__ == "__main__":
    unittest.main()
