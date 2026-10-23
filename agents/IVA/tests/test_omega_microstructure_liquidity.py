"""Acceptance test suite for Multi-Level Book Depth Liquidity & Kyle's Lambda Price Impact."""

import unittest

from agents.AGI_1_7.engine.agi17.finance.microstructure_liquidity import (
    BookDepthSnapshot,
    ExecutionImpactEstimate,
    ExecutionSafetyStatus,
    LiquidityRegime,
    MicrostructureLiquidityEngine,
    MicrostructureLiquidityReport,
    TradeTickRecord,
)


class TestOmegaMicrostructureLiquidity(unittest.TestCase):
    """Test suite for MicrostructureLiquidityEngine."""

    def setUp(self) -> None:
        self.engine = MicrostructureLiquidityEngine(
            rolling_window_trades=30,
            rolling_window_books=20,
            max_acceptable_lambda=0.05,
            max_acceptable_spread_bps=10.0,
            bank_nifty_lot_size=15,
        )

    def test_book_depth_recording_and_slope(self) -> None:
        """Verify order book snapshot ingestion, spread, and depth slopes."""
        bids = [
            (50000.0, 45),
            (49995.0, 60),
            (49990.0, 75),
            (49985.0, 90),
            (49980.0, 105),
        ]
        asks = [
            (50002.0, 30),
            (50007.0, 45),
            (50012.0, 60),
            (50017.0, 75),
            (50022.0, 90),
        ]

        snap = self.engine.record_order_book(timestamp=1000.0, bids=bids, asks=asks)
        self.assertEqual(snap.quoted_spread, 2.0)
        self.assertEqual(snap.mid_price, 50001.0)
        self.assertEqual(snap.bid_total_qty, 375)
        self.assertEqual(snap.ask_total_qty, 300)
        self.assertGreater(snap.bid_slope, 0.0)
        self.assertGreater(snap.ask_slope, 0.0)

    def test_kyles_lambda_ols_regression(self) -> None:
        """Verify Kyle's lambda regression estimates price impact per unit volume."""
        base_price = 50000.0
        # Generate trades where buying pushes price up by 0.005 pts per contract
        for i in range(20):
            vol = 30 + (i % 3) * 15
            side = "BUY" if i % 2 == 0 else "SELL"
            p_change = 0.005 * vol if side == "BUY" else -0.005 * vol
            base_price += p_change
            self.engine.record_trade(
                timestamp=1000.0 + i,
                price=base_price,
                volume=vol,
                side=side,
            )

        k_lambda, r2 = self.engine.compute_kyles_lambda()
        self.assertGreater(k_lambda, 0.001)
        self.assertGreater(r2, 0.50)  # Strong linear relationship

    def test_amihud_illiq_ratio(self) -> None:
        """Verify Amihud illiquidity ratio tracks price impact per volume."""
        self.engine.record_trade(timestamp=100.0, price=50000.0, volume=100, side="BUY")
        self.engine.record_trade(timestamp=101.0, price=50010.0, volume=50, side="BUY")
        self.engine.record_trade(timestamp=102.0, price=50005.0, volume=100, side="SELL")

        illiq = self.engine.compute_amihud_illiq()
        self.assertGreater(illiq, 0.0)

    def test_liquidity_regime_classification(self) -> None:
        """Verify regime classification: HIGH_LIQUIDITY, THIN_BOOK, and ADVERSE_SHOCK."""
        # Setup tight deep book
        bids = [(50000.0, 150), (49999.0, 150), (49998.0, 150), (49997.0, 150), (49996.0, 150)]
        asks = [(50001.0, 150), (50002.0, 150), (50003.0, 150), (50004.0, 150), (50005.0, 150)]
        self.engine.record_order_book(100.0, bids, asks)
        
        # Add normal low-impact trades
        for i in range(10):
            self.engine.record_trade(100.0 + i, 50000.5 + (0.01 * (i % 2)), 15, "BUY")

        report = self.engine.generate_liquidity_report()
        self.assertTrue(report.is_safe_for_market_orders)
        self.assertIn(report.regime, (LiquidityRegime.HIGH_LIQUIDITY, LiquidityRegime.NORMAL_LIQUIDITY))

        # Thin book condition: very few contracts
        thin_bids = [(50000.0, 5)]
        thin_asks = [(50005.0, 5)]
        self.engine.record_order_book(110.0, thin_bids, thin_asks)
        thin_report = self.engine.generate_liquidity_report()
        self.assertEqual(thin_report.regime, LiquidityRegime.THIN_BOOK)
        self.assertFalse(thin_report.is_safe_for_market_orders)

    def test_execution_impact_and_slippage_estimation(self) -> None:
        """Verify multi-level order walking, VWAP slippage, and child clip throttling."""
        bids = [(50000.0, 15), (49995.0, 30), (49990.0, 45), (49985.0, 60), (49980.0, 75)]
        asks = [(50002.0, 15), (50007.0, 30), (50012.0, 45), (50017.0, 60), (50022.0, 75)]
        self.engine.record_order_book(100.0, bids, asks)

        # 1 lot (15 contracts): fits comfortably in top of book
        est_small = self.engine.evaluate_execution_impact(order_size=15, side="BUY")
        self.assertEqual(est_small.depth_consumed_levels, 1)
        self.assertEqual(est_small.status, ExecutionSafetyStatus.SAFE)
        self.assertEqual(est_small.recommended_max_clip_size, 15)

        # 60 contracts: consumes Level 1 (15 @ 50002) + Level 2 (30 @ 50007) + part of Level 3 (15 @ 50012)
        est_large = self.engine.evaluate_execution_impact(order_size=60, side="BUY")
        self.assertGreater(est_large.depth_consumed_levels, 2)
        self.assertGreater(est_large.expected_slippage_pts, 0.0)

    def test_order_exceeding_total_depth_rejection(self) -> None:
        """Verify order exceeding combined 5-level depth is rejected as REJECT_ILLIQUID."""
        bids = [(50000.0, 15)]
        asks = [(50002.0, 15)]
        self.engine.record_order_book(100.0, bids, asks)

        # Proposed order of 150 contracts when only 15 contracts exist
        est = self.engine.evaluate_execution_impact(order_size=150, side="BUY")
        self.assertEqual(est.status, ExecutionSafetyStatus.REJECT_ILLIQUID)
        self.assertIn("exceeds total 5-level depth", est.rejection_reason)


if __name__ == "__main__":
    unittest.main()
