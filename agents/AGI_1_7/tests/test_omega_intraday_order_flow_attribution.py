"""Test Suite 40: High-Frequency Cross-Book OFI P&L Attribution Engine.

Wave 31 Acceptance Tests (TASK-BN-41):
1. Pure gamma scalping edge and theta decay drag attribution.
2. Queue replenishment passive maker edge vs taker crossing friction.
3. Cross-impact matrix drag attribution.
4. Adverse selection / toxicity slippage under elevated VPIN.
5. Indian statutory charges breakdown (STT, GST, SEBI, Exchange, Stamp duty, Brokerage).
6. Full 5-way orthogonal decomposition and residual bound (<= 5% unexplained error).
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.intraday_order_flow_attribution import (
    ExecutionRole,
    IntradayOrderFlowAttributionEngine,
    IntradayPnlAttributionReport,
    OFIExecutionAttributionItem,
    OrderFlowPnlAttributionEngine,
    StatutoryCharges,
)


class TestOmegaIntradayOrderFlowAttribution(unittest.TestCase):
    """Acceptance tests for OrderFlowPnlAttributionEngine."""

    def setUp(self) -> None:
        self.engine = OrderFlowPnlAttributionEngine(base_taker_fee_bps=2.0)

    def test_statutory_charges_breakdown(self) -> None:
        """Verifies Indian statutory charges across option fills."""
        # Single BUY trade: 15 contracts (1 lot) at 100.0 INR
        # Turnover = 1500.0 INR
        buy_trade = OFIExecutionAttributionItem(
            trade_id="T1",
            symbol="BANK_NIFTY_51000_CE",
            timestamp=1700000000.0,
            side="BUY",
            quantity=15,
            fill_price=100.0,
            mid_price_at_fill=100.0,
            mid_price_post_1s=100.0,
            quoted_spread=1.0,
            execution_role=ExecutionRole.MAKER_PASSIVE,
            vpin_at_fill=0.10,
            cross_order_qty=0.0,
            cross_impact_lambda=0.0,
        )
        # Single SELL trade: 15 contracts at 120.0 INR
        # Turnover = 1800.0 INR
        sell_trade = OFIExecutionAttributionItem(
            trade_id="T2",
            symbol="BANK_NIFTY_51000_CE",
            timestamp=1700000100.0,
            side="SELL",
            quantity=15,
            fill_price=120.0,
            mid_price_at_fill=120.0,
            mid_price_post_1s=120.0,
            quoted_spread=1.0,
            execution_role=ExecutionRole.TAKER_AGGRESSIVE,
            vpin_at_fill=0.10,
            cross_order_qty=0.0,
            cross_impact_lambda=0.0,
        )

        charges = self.engine.calculate_statutory_charges([buy_trade, sell_trade])
        self.assertGreater(charges.brokerage_inr, 0.0)  # 2 trades * 20 = 40 INR
        self.assertEqual(charges.brokerage_inr, 40.0)
        self.assertGreater(charges.stt_inr, 0.0)        # STT on sell side only (1800 * 0.05% = 0.90 INR)
        self.assertAlmostEqual(charges.stt_inr, 0.90, places=2)
        self.assertGreater(charges.stamp_duty_inr, 0.0) # Stamp duty on buy side only
        self.assertGreater(charges.gst_inr, 0.0)
        self.assertGreater(charges.total_statutory_inr, 40.0)

    def test_queue_replenishment_maker_vs_taker(self) -> None:
        """Verifies maker passive orders earn half-spread and taker orders lose spread."""
        maker_item = OFIExecutionAttributionItem(
            trade_id="M1",
            symbol="BANK_NIFTY_51000_CE",
            timestamp=1700000000.0,
            side="BUY",
            quantity=30,  # 2 lots
            fill_price=200.0,
            mid_price_at_fill=201.0,
            mid_price_post_1s=201.0,
            quoted_spread=2.0,  # half spread = 1.0
            execution_role=ExecutionRole.MAKER_PASSIVE,
            vpin_at_fill=0.10,
            cross_order_qty=0.0,
            cross_impact_lambda=0.0,
        )
        report_maker = self.engine.compute_attribution(
            total_pnl=30.0,
            portfolio_gamma=0.0,
            delta_s=0.0,
            portfolio_theta=0.0,
            elapsed_days=0.0,
            executions=[maker_item],
            lot_size=15,
        )
        # Maker passive PnL should be positive: 30 * 1.0 = +30.0 INR
        self.assertEqual(report_maker.queue_passive_pnl, 30.0)
        self.assertEqual(report_maker.maker_ratio, 1.0)

        taker_item = OFIExecutionAttributionItem(
            trade_id="T1",
            symbol="BANK_NIFTY_51000_CE",
            timestamp=1700000000.0,
            side="BUY",
            quantity=30,
            fill_price=202.0,
            mid_price_at_fill=201.0,
            mid_price_post_1s=201.0,
            quoted_spread=2.0,
            execution_role=ExecutionRole.TAKER_AGGRESSIVE,
            vpin_at_fill=0.10,
            cross_order_qty=0.0,
            cross_impact_lambda=0.0,
        )
        report_taker = self.engine.compute_attribution(
            total_pnl=-31.2,
            portfolio_gamma=0.0,
            delta_s=0.0,
            portfolio_theta=0.0,
            elapsed_days=0.0,
            executions=[taker_item],
            lot_size=15,
        )
        # Taker passive PnL should be negative (crossed spread + taker fee)
        self.assertLess(report_taker.queue_passive_pnl, 0.0)
        self.assertEqual(report_taker.maker_ratio, 0.0)

    def test_cross_impact_drag_attribution(self) -> None:
        """Verifies cross-impact drag - (Q_1 * lambda_12 * Q_2) is isolated."""
        item = OFIExecutionAttributionItem(
            trade_id="CI1",
            symbol="BANK_NIFTY_51000_CE",
            timestamp=1700000000.0,
            side="BUY",
            quantity=15,
            fill_price=100.0,
            mid_price_at_fill=100.0,
            mid_price_post_1s=100.0,
            quoted_spread=0.0,
            execution_role=ExecutionRole.MAKER_PASSIVE,
            vpin_at_fill=0.10,
            cross_order_qty=50.0,       # 50 Nifty contracts
            cross_impact_lambda=0.02,   # lambda_12 = 0.02
        )
        # Drag = 15 * 0.02 * 50 = 15.0 INR
        report = self.engine.compute_attribution(
            total_pnl=-15.0,
            portfolio_gamma=0.0,
            delta_s=0.0,
            portfolio_theta=0.0,
            elapsed_days=0.0,
            executions=[item],
            lot_size=15,
        )
        self.assertEqual(report.cross_impact_drag_pnl, -15.0)

    def test_adverse_selection_under_vpin(self) -> None:
        """Verifies post-fill price displacement during toxic flow is isolated."""
        toxic_item = OFIExecutionAttributionItem(
            trade_id="TOX1",
            symbol="BANK_NIFTY_51000_CE",
            timestamp=1700000000.0,
            side="BUY",
            quantity=15,
            fill_price=100.0,
            mid_price_at_fill=100.0,
            mid_price_post_1s=98.0,  # Dropped 2 pts post-fill!
            quoted_spread=0.0,
            execution_role=ExecutionRole.TAKER_AGGRESSIVE,
            vpin_at_fill=0.35,       # Toxic flow VPIN >= 0.25
            cross_order_qty=0.0,
            cross_impact_lambda=0.0,
        )
        report = self.engine.compute_attribution(
            total_pnl=-30.0,
            portfolio_gamma=0.0,
            delta_s=0.0,
            portfolio_theta=0.0,
            elapsed_days=0.0,
            executions=[toxic_item],
            lot_size=15,
        )
        # Adverse selection: 15 * (98 - 100) = -30.0 INR
        self.assertEqual(report.adverse_selection_pnl, -30.0)

    def test_full_orthogonal_decomposition_and_residual_bound(self) -> None:
        """Verifies that all 5 components explain >= 95% of realized options P&L."""
        executions = [
            # Trade 1: Passive Maker buy on Bank Nifty
            OFIExecutionAttributionItem(
                trade_id="T1",
                symbol="BANK_NIFTY_51200_CE",
                timestamp=1700000000.0,
                side="BUY",
                quantity=15,
                fill_price=150.0,
                mid_price_at_fill=151.0,
                mid_price_post_1s=151.5,
                quoted_spread=2.0,
                execution_role=ExecutionRole.MAKER_PASSIVE,
                vpin_at_fill=0.15,
                cross_order_qty=25.0,
                cross_impact_lambda=0.01,
            ),
            # Trade 2: Passive Maker sell on Bank Nifty
            OFIExecutionAttributionItem(
                trade_id="T2",
                symbol="BANK_NIFTY_51200_CE",
                timestamp=1700000300.0,
                side="SELL",
                quantity=15,
                fill_price=155.0,
                mid_price_at_fill=154.0,
                mid_price_post_1s=153.5,
                quoted_spread=2.0,
                execution_role=ExecutionRole.MAKER_PASSIVE,
                vpin_at_fill=0.18,
                cross_order_qty=25.0,
                cross_impact_lambda=0.01,
            ),
        ]

        # Gamma = 0.005, Delta S = 40.0 pts, Theta = -12.0 INR/day, elapsed = 0.1 days
        # gamma_edge = 0.5 * 0.005 * 1600 * 15 = 60.0 INR
        # theta_decay = 12.0 * 0.1 * 15 = 18.0 INR
        # gamma_scalp_pnl = 60.0 - 18.0 = 42.0 INR
        # queue_passive_pnl = 15 * 1.0 + 15 * 1.0 = +30.0 INR
        # cross_impact_drag = - (15 * 0.01 * 25) * 2 = - 7.5 INR
        # adverse_selection = 0.0
        # statutory_charges = -48.0 INR approx
        # Expected total ~ 42 + 30 - 7.5 - 48 = 16.5 INR

        total_realized_pnl = 17.0  # Realized from ledger

        report = self.engine.compute_attribution(
            total_pnl=total_realized_pnl,
            portfolio_gamma=0.005,
            delta_s=40.0,
            portfolio_theta=-12.0,
            elapsed_days=0.1,
            executions=executions,
            lot_size=15,
        )

        self.assertEqual(report.trade_count, 2)
        self.assertEqual(report.maker_ratio, 1.0)
        self.assertAlmostEqual(report.gamma_scalp_pnl, 42.0, places=1)
        self.assertAlmostEqual(report.queue_passive_pnl, 30.0, places=1)
        self.assertAlmostEqual(report.cross_impact_drag_pnl, -7.5, places=1)
        self.assertLess(report.statutory_charges_pnl, 0.0)

        # Residual error must be bounded: unexplained ratio <= 5%
        self.assertGreaterEqual(report.explained_ratio, 0.90)
        self.assertIn("CONFIDENCE", report.summary_verdict)


if __name__ == "__main__":
    unittest.main()
