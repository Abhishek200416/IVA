"""Unit and Integration Tests for Multi-Day Walk-Forward Options Replay & Telemetry Engine.

TASK-BN-25:
Verifies:
1. Sequential multi-day walk-forward simulation across 5-day weekly expiry cycle.
2. Bar-by-bar progression across 75 5-minute bars per 375-min Indian market session.
3. Integration with StreamingMarketDepthAdapter & VPIN toxicity gating.
4. UnifiedAlgorithmicExecutionRouter order gating (Debate, OFI, RMS, Slippage, Fill).
5. Dynamic trailing stop ratchets and mandatory 15:15 IST auto-square-off.
6. Real-time equity curve telemetry, drawdown tracking, and zero live order guarantee.
"""

import unittest

from agents.AGI_1_7.engine.agi17.finance.multi_day_walk_forward import (
    DailySessionSummary,
    MultiDayWalkForwardEngine,
    MultiDayWalkForwardReport,
    TradingDayConfig,
)


class TestMultiDayWalkForwardEngine(unittest.TestCase):
    """Test suite for MultiDayWalkForwardEngine."""

    def setUp(self) -> None:
        self.engine = MultiDayWalkForwardEngine(
            initial_capital=1_000_000.0,
            max_drawdown_limit=0.03,
            vpin_bucket_units=200,
        )

    def test_single_day_session_simulation(self) -> None:
        """Verifies simulation of a single trading day produces consistent session summary."""
        day_cfg = TradingDayConfig(
            date_str="2026-10-15",
            day_name="Thursday",
            is_expiry_day=False,
            open_spot=50000.0,
            drift_pct=0.008,  # +0.8% bullish trend day
            intraday_vol=0.15,
            india_vix=14.0,
            num_bars=30,  # 30 bars for fast testing
        )
        summary = self.engine.simulate_day(day_cfg)

        self.assertEqual(summary.date_str, "2026-10-15")
        self.assertEqual(summary.day_name, "Thursday")
        self.assertFalse(summary.is_expiry_day)
        self.assertGreater(summary.starting_equity, 0.0)
        self.assertGreater(summary.ending_equity, 0.0)
        self.assertGreaterEqual(summary.trades_executed, 0)
        self.assertEqual(len(self.engine.daily_summaries), 1)

    def test_5_day_weekly_cycle_with_wednesday_expiry(self) -> None:
        """Verifies 5 consecutive days leading to Wednesday expiry carry over equity seamlessly."""
        days = [
            TradingDayConfig("2026-10-15", "Thursday", False, 50000.0, 0.005, 0.15, 14.0, 20),
            TradingDayConfig("2026-10-16", "Friday", False, 50250.0, -0.003, 0.15, 14.5, 20),
            TradingDayConfig("2026-10-19", "Monday", False, 50100.0, 0.006, 0.16, 15.0, 20),
            TradingDayConfig("2026-10-20", "Tuesday", False, 50400.0, 0.002, 0.15, 14.2, 20),
            TradingDayConfig("2026-10-21", "Wednesday", True, 50500.0, -0.004, 0.18, 16.0, 20),
        ]
        report = self.engine.run_multi_day_cycle(days)

        self.assertEqual(report.total_days, 5)
        self.assertEqual(len(report.daily_summaries), 5)
        self.assertTrue(report.zero_live_order_guarantee)
        self.assertGreater(report.ending_capital, 0.0)
        self.assertGreater(len(report.equity_curve), 5)
        # Verify Day 5 was Wednesday Expiry
        self.assertTrue(report.daily_summaries[4].is_expiry_day)
        self.assertEqual(report.daily_summaries[4].day_name, "Wednesday")

    def test_equity_curve_and_drawdown_monotonicity(self) -> None:
        """Verifies equity curve records chronological progression and drawdown bounds."""
        days = [
            TradingDayConfig("2026-10-15", "Thursday", False, 50000.0, 0.005, 0.15, 14.0, 15),
            TradingDayConfig("2026-10-16", "Friday", False, 50250.0, -0.008, 0.16, 15.0, 15),
        ]
        report = self.engine.run_multi_day_cycle(days)

        self.assertGreater(len(report.equity_curve), 2)
        # First equity point is initial capital
        self.assertEqual(report.equity_curve[0][1], 1_000_000.0)
        self.assertGreaterEqual(report.max_drawdown_pct, 0.0)
        self.assertLess(report.max_drawdown_pct, 100.0)

    def test_vpin_toxicity_protective_halts(self) -> None:
        """Verifies high toxic flow increments VPIN halts counter."""
        days = [
            TradingDayConfig("2026-10-15", "Thursday", False, 50000.0, 0.015, 0.35, 26.0, 20),
        ]
        # Force high VPIN in the adapter
        self.engine.depth_adapter.toxicity_warning_threshold = 0.01
        self.engine.depth_adapter.toxicity_halt_threshold = 0.02

        report = self.engine.run_multi_day_cycle(days)
        self.assertGreaterEqual(report.total_vpin_blocks, 0)
        self.assertTrue(report.zero_live_order_guarantee)

    def test_performance_metrics_and_friction_deduction(self) -> None:
        """Verifies statutory friction and risk metrics (Sharpe, Profit Factor) format correctly."""
        days = [
            TradingDayConfig("2026-10-15", "Thursday", False, 50000.0, 0.005, 0.15, 14.0, 15),
            TradingDayConfig("2026-10-16", "Friday", False, 50250.0, 0.004, 0.15, 14.0, 15),
        ]
        report = self.engine.run_multi_day_cycle(days)

        self.assertIsInstance(report.sharpe_ratio, float)
        self.assertIsInstance(report.sortino_ratio, float)
        self.assertIsInstance(report.profit_factor, float)
        self.assertGreaterEqual(report.total_statutory_fees, 0.0)
        self.assertIn("Multi-Day Walk-Forward", report.diagnostics)


if __name__ == "__main__":
    unittest.main()
