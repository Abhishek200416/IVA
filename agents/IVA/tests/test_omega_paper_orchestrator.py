"""Acceptance tests for Full-Stack Paper Trading Engine Orchestrator & Quantitative Performance Teardown.

TASK-BN-27:
Covers:
1. Full-stack initialization, capital baseline, and safe harbor invariants.
2. Real-time VPIN adverse selection halt gating.
3. End-to-end execution routing from dialectical debate to paper fill.
4. Active position lifecycle management and monotonic trailing stop ratchet exits.
5. Mandatory 15:15 IST intraday auto-square-off enforcement.
6. QuantitativePerformanceTearSheet metrics computation and Markdown report generation.
"""

from __future__ import annotations

import unittest
from typing import List

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide
from agents.AGI_1_7.engine.agi17.finance.market_depth_streaming import (
    MarketDepthTick,
    TradeTick,
)
from agents.AGI_1_7.engine.agi17.finance.order_book_simulator import BookLevel
from agents.AGI_1_7.engine.agi17.finance.paper_orchestrator import (
    PaperTradingOrchestrator,
    QuantitativePerformanceTearSheet,
)


class TestOmegaPaperOrchestrator(unittest.TestCase):
    """Test suite for top-level full-stack paper trading orchestrator and tear-sheet teardown."""

    def setUp(self) -> None:
        self.initial_capital = 1_000_000.0
        self.orchestrator = PaperTradingOrchestrator(
            initial_capital=self.initial_capital,
            max_drawdown_pct=0.03,
            vpin_bucket_size=75,
        )

    def test_orchestrator_initialization_and_capital(self) -> None:
        """Verify initial state, capital tracking, and empty state invariants."""
        self.assertEqual(self.orchestrator.initial_capital, 1_000_000.0)
        self.assertEqual(self.orchestrator.paper_trader.cash, 1_000_000.0)
        self.assertEqual(len(self.orchestrator.closed_trades), 0)
        self.assertEqual(len(self.orchestrator.router.active_positions), 0)
        self.assertEqual(self.orchestrator.vpin_halts_count, 0)
        self.assertEqual(self.orchestrator.ofi_rejections_count, 0)

    def test_vpin_adverse_selection_protection(self) -> None:
        """Verify orchestrator halts trade entry when VPIN signals toxic informed flow."""
        # Synthesize extreme one-sided toxic depth tick
        bids = [BookLevel(price=50000.0 - (l * 0.5), units=15) for l in range(5)]
        asks = [BookLevel(price=50000.5 + (l * 0.5), units=15) for l in range(5)]

        # Feed 10 consecutive massive aggressive buyer trades (each 300 units) to push VPIN >= 0.35
        for i in range(10):
            depth_tick = MarketDepthTick(
                timestamp_iso="2026-10-11T10:00:00Z",
                symbol="BANKNIFTY",
                bids=bids,
                asks=asks,
                last_trade=TradeTick(
                    timestamp_iso="2026-10-11T10:00:00Z",
                    price=50000.5,
                    units=300,
                    side=OrderSide.BUY,
                ),
            )
            res = self.orchestrator.evaluate_tick(
                trade_id=f"TRD-TOXIC-{i}",
                spot_price=50000.0,
                vwap=49950.0,
                ema20=49900.0,
                iv=0.15,
                call_oi_change_pct=-0.10,
                put_oi_change_pct=0.25,
                depth_tick=depth_tick,
                current_time_ist="10:00:00",
            )

        # After toxic trades, VPIN should trigger halt
        self.assertGreater(self.orchestrator.vpin_halts_count, 0)
        self.assertEqual(res["status"], "HALTED_BY_VPIN")

    def test_end_to_end_tick_pipeline_execution(self) -> None:
        """Verify successful signal derivation, dialectical debate, RMS approval, and fill."""
        res = self.orchestrator.evaluate_tick(
            trade_id="TRD-BULL-001",
            spot_price=50500.0,
            vwap=50450.0,
            ema20=50400.0,
            iv=0.15,
            call_oi_change_pct=-0.15,
            put_oi_change_pct=0.30,
            quoted_bid=400.0,
            quoted_ask=400.50,
            current_time_ist="10:15:00",
            order_lots=1,
        )

        self.assertTrue(res["is_executed"])
        self.assertEqual(res["status"], "LIFECYCLE_TRACKED")
        self.assertEqual(len(self.orchestrator.router.active_positions), 1)
        self.assertIn("TRD-BULL-001", [p.trade_id for p in self.orchestrator.router.active_positions.values()])

    def test_trailing_stop_ratchet_and_exit(self) -> None:
        """Verify monotonic profit-locking trailing stop ratchets and triggers clean exit."""
        # 1. Enter long position at 400.0
        self.orchestrator.evaluate_tick(
            trade_id="TRD-TRAIL-001",
            spot_price=50500.0,
            vwap=50450.0,
            ema20=50400.0,
            iv=0.15,
            call_oi_change_pct=-0.15,
            put_oi_change_pct=0.30,
            quoted_bid=400.0,
            quoted_ask=400.50,
            current_time_ist="10:15:00",
            order_lots=1,
        )

        self.assertEqual(len(self.orchestrator.router.active_positions), 1)

        # 2. Advance option price favorably to 420.0 (+20 points gain)
        # Trailing stop ratchets upward
        self.orchestrator.evaluate_tick(
            trade_id="TRD-ADVANCE-001",
            spot_price=50600.0,
            vwap=50500.0,
            ema20=50450.0,
            iv=0.15,
            call_oi_change_pct=-0.15,
            put_oi_change_pct=0.30,
            quoted_bid=420.0,
            quoted_ask=420.50,
            current_time_ist="10:30:00",
        )

        pos = [p for p in self.orchestrator.router.active_positions.values() if p.trade_id == "TRD-TRAIL-001"][0]
        self.assertGreater(pos.trailing_stop_price, 400.0)

        # 3. Pull back price sharply below trailing stop (e.g., 405.0)
        self.orchestrator.evaluate_tick(
            trade_id="TRD-PULLBACK-001",
            spot_price=50450.0,
            vwap=50480.0,
            ema20=50450.0,
            iv=0.16,
            call_oi_change_pct=0.05,
            put_oi_change_pct=-0.05,
            quoted_bid=405.0,
            quoted_ask=405.50,
            current_time_ist="10:45:00",
        )

        # Position should have closed via trailing stop
        self.assertEqual(len(self.orchestrator.router.active_positions), 0)
        self.assertEqual(len(self.orchestrator.closed_trades), 1)
        self.assertEqual(self.orchestrator.trailing_stop_exits_count, 1)
        self.assertGreater(self.orchestrator.closed_trades[0]["realized_pnl"], 0.0)

    def test_mandatory_intraday_square_off(self) -> None:
        """Verify mandatory 15:15 IST auto-square-off closes active positions."""
        # Enter position
        self.orchestrator.evaluate_tick(
            trade_id="TRD-SQOFF-001",
            spot_price=50500.0,
            vwap=50450.0,
            ema20=50400.0,
            iv=0.15,
            call_oi_change_pct=-0.15,
            put_oi_change_pct=0.30,
            quoted_bid=400.0,
            quoted_ask=400.50,
            current_time_ist="14:00:00",
            order_lots=1,
        )

        self.assertEqual(len(self.orchestrator.router.active_positions), 1)

        # Advance time to 15:15:00 IST
        self.orchestrator.evaluate_tick(
            trade_id="TRD-TIME-CHECK",
            spot_price=50500.0,
            vwap=50450.0,
            ema20=50400.0,
            iv=0.15,
            call_oi_change_pct=0.0,
            put_oi_change_pct=0.0,
            quoted_bid=401.0,
            quoted_ask=401.50,
            current_time_ist="15:15:00",
        )

        # Position must be closed automatically
        self.assertEqual(len(self.orchestrator.router.active_positions), 0)
        self.assertEqual(len(self.orchestrator.closed_trades), 1)
        self.assertEqual(self.orchestrator.closed_trades[0]["close_reason"], "CLOSED_SQUARE_OFF")

    def test_tear_sheet_generation_and_markdown(self) -> None:
        """Verify quantitative performance tear-sheet computation and Markdown export."""
        # Execute trade cycle
        self.orchestrator.evaluate_tick(
            trade_id="TRD-TEAR-001",
            spot_price=50500.0,
            vwap=50450.0,
            ema20=50400.0,
            iv=0.15,
            call_oi_change_pct=-0.15,
            put_oi_change_pct=0.30,
            quoted_bid=400.0,
            quoted_ask=400.50,
            current_time_ist="10:00:00",
            order_lots=1,
        )

        # Exit at 15:15 IST
        self.orchestrator.evaluate_tick(
            trade_id="TRD-TEAR-EXIT",
            spot_price=50600.0,
            vwap=50500.0,
            ema20=50450.0,
            iv=0.15,
            call_oi_change_pct=0.0,
            put_oi_change_pct=0.0,
            quoted_bid=410.0,
            quoted_ask=410.50,
            current_time_ist="15:15:00",
        )

        tear_sheet: QuantitativePerformanceTearSheet = self.orchestrator.generate_tear_sheet(
            session_id="SESSION-BENCHMARK-TEST"
        )

        self.assertIsInstance(tear_sheet, QuantitativePerformanceTearSheet)
        self.assertEqual(tear_sheet.session_id, "SESSION-BENCHMARK-TEST")
        self.assertEqual(tear_sheet.total_trades, 1)
        self.assertGreaterEqual(tear_sheet.win_rate_pct, 0.0)
        self.assertGreaterEqual(tear_sheet.peak_capital_inr, self.initial_capital)

        # Verify friction deduction
        self.assertGreater(tear_sheet.total_friction_inr, 0.0)
        self.assertGreater(tear_sheet.total_stt_inr, 0.0)
        self.assertGreater(tear_sheet.total_brokerage_inr, 0.0)

        # Verify Markdown export
        md_report = tear_sheet.to_markdown()
        self.assertIn("# Quantitative Performance Tear-Sheet", md_report)
        self.assertIn("Sharpe Ratio", md_report)
        self.assertIn("Securities Transaction Tax (STT)", md_report)
        self.assertIn("Microstructure & Pre-Trade Risk Shields", md_report)


if __name__ == "__main__":
    unittest.main()
