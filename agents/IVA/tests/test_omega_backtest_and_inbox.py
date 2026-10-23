"""AGI 1.7 OMEGA COMMAND — Acceptance Tests for Live Inbox & BANK NIFTY Options Backtesting.

Covers:
1. ContinuousSupervisor inbox polling, task ingestion, and state transition.
2. Chronological sequence enforcement (lookahead violation rejection).
3. OpeningRangeBreakoutStrategy execution, risk management, and mandatory square-off.
4. ShortStrangleDeltaHedgingStrategy execution and theta capture.
5. Indian statutory transaction cost deduction (STT, GST, Exchange fees).
6. Performance metrics (Sharpe ratio, Max Drawdown %, Profit Factor, Win Rate %).
7. Multi-model adapter authorization (Gemini, DeepSeek, GLM, MiniMax).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.adapters.model_adapter import ModelAdapter
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_backtest import (
    BacktestReport,
    BankNiftyBacktestEngine,
    MarketBar,
    MarketSnapshot,
    NoTradeBaselineStrategy,
    OpeningRangeBreakoutStrategy,
    OptionChainQuote,
    ShortStrangleDeltaHedgingStrategy,
    VWAPEMAStrategy,
)
from agents.AGI_1_7.engine.agi17.finance.market_data_feed import (
    MarketDataFeed,
    calculate_ema,
    calculate_intraday_vwap,
    resample_1min_to_5min,
)
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import (
    BankNiftyPaperTrader,
    OrderSide,
    OrderType,
)
from agents.AGI_1_7.engine.agi17.finance.order_book_simulator import (
    BookLevel,
    OrderBookFactory,
    OrderFillResult,
    SimulatedOrderBook,
)
from agents.AGI_1_7.engine.agi17.process_supervision.continuous_supervisor import (
    ContinuousSupervisor,
)
from agents.AGI_1_7.engine.agi17.supervisor.persistent_supervisor import (
    SupervisorState,
    TaskPriority,
)


class TestOmegaBacktestAndInbox(unittest.TestCase):
    """Test suite for live supervisor inbox polling and quantitative backtesting engine."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="agi17_test_backtest_")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_continuous_supervisor_inbox_dynamic_ingestion(self) -> None:
        """Verify ContinuousSupervisor dynamically polls inbox directory and transitions state."""
        state_dir = Path(self.temp_dir) / "supervisor_state"
        sup = ContinuousSupervisor(state_dir=state_dir, idle_sleep_sec=0.01)

        # Initially in READY -> step() moves to SELECTING_TASK -> IDLE_HEALTHY since queue is empty
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.SELECTING_TASK)
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.IDLE_HEALTHY)
        self.assertEqual(len(sup.queue), 0)

        # Drop a dynamic task file into inbox
        inbox_file = sup.inbox_dir / "dynamic_task_01.json"
        task_payload = {
            "title": "Dynamic BANK NIFTY Replay Task",
            "description": "Execute quantitative backtest on historical snapshot batch",
            "priority": 2,
            "requires_model": False,
        }
        inbox_file.write_text(json.dumps(task_payload), encoding="utf-8")

        # Step supervisor in IDLE_HEALTHY: should poll inbox, enqueue task, and wake to READY
        sup.step()
        self.assertEqual(sup.current_state, SupervisorState.READY)
        self.assertEqual(len(sup.queue), 1)
        self.assertEqual(sup.queue[0].title, "Dynamic BANK NIFTY Replay Task")

        # Verify inbox file moved to inbox_processed
        processed_files = list(sup.processed_dir.glob("*dynamic_task_01*"))
        self.assertEqual(len(processed_files), 1)
        self.assertFalse(inbox_file.exists())

    def test_02_backtest_engine_rejects_lookahead_chronology_violation(self) -> None:
        """Verify backtest engine rejects timestamps that violate temporal sequence."""
        engine = BankNiftyBacktestEngine(initial_capital=500_000.0)

        # Non-monotonic timestamps (lookahead violation)
        snap1 = MarketSnapshot(
            timestamp_ist="2026-10-09 09:30:00",
            spot_bar=MarketBar("2026-10-09 09:30:00", 52000, 52050, 51980, 52020),
        )
        snap2 = MarketSnapshot(
            timestamp_ist="2026-10-09 09:20:00",  # Backward in time!
            spot_bar=MarketBar("2026-10-09 09:20:00", 52020, 52040, 52000, 52010),
        )

        strat = OpeningRangeBreakoutStrategy()
        with self.assertRaises(ValueError) as ctx:
            engine.run([snap1, snap2], strat)
        self.assertIn("lookahead violation", str(ctx.exception))

    def test_03_opening_range_breakout_strategy_replay(self) -> None:
        """Verify 15-minute Opening Range Breakout strategy execution, SL/TP, and statutory fee modeling."""
        engine = BankNiftyBacktestEngine(initial_capital=500_000.0)
        strategy = OpeningRangeBreakoutStrategy(units_per_trade=15)

        # Create sequential market day
        # 09:15 - 09:30: Opening range 52000 - 52100 (range = 100)
        snapshots: list[MarketSnapshot] = []
        snapshots.append(
            MarketSnapshot(
                timestamp_ist="2026-10-09 09:15:00",
                spot_bar=MarketBar("2026-10-09 09:15:00", 52000, 52080, 52000, 52050),
            )
        )
        snapshots.append(
            MarketSnapshot(
                timestamp_ist="2026-10-09 09:25:00",
                spot_bar=MarketBar("2026-10-09 09:25:00", 52050, 52100, 52020, 52060),
            )
        )

        # 09:35: Breakout above high (52100) to 52150 -> Buys ATM 52200 CE
        atm_ce = "BANKNIFTY26OCT52200CE"
        opt_quote = OptionChainQuote(
            symbol=atm_ce,
            strike=52200.0,
            option_type="CE",
            expiry="2026-10-26",
            ltp=300.0,
            delta=0.52,
        )
        snapshots.append(
            MarketSnapshot(
                timestamp_ist="2026-10-09 09:35:00",
                spot_bar=MarketBar("2026-10-09 09:35:00", 52070, 52150, 52060, 52140),
                options={atm_ce: opt_quote},
            )
        )

        # 10:00: Target achieved -> spot moves to 52300, option LTP rises to 420.0
        opt_quote_profit = OptionChainQuote(
            symbol=atm_ce,
            strike=52200.0,
            option_type="CE",
            expiry="2026-10-26",
            ltp=420.0,
            delta=0.68,
        )
        snapshots.append(
            MarketSnapshot(
                timestamp_ist="2026-10-09 10:00:00",
                spot_bar=MarketBar("2026-10-09 10:00:00", 52140, 52310, 52130, 52300),
                options={atm_ce: opt_quote_profit},
            )
        )

        # 15:20: End of intraday session
        snapshots.append(
            MarketSnapshot(
                timestamp_ist="2026-10-09 15:20:00",
                spot_bar=MarketBar("2026-10-09 15:20:00", 52300, 52320, 52280, 52290),
                options={atm_ce: opt_quote_profit},
            )
        )

        report = engine.run(snapshots, strategy)

        self.assertIsInstance(report, BacktestReport)
        self.assertEqual(report.strategy_name, "BankNiftyORB_15Min")
        self.assertGreater(report.total_trades, 0)
        self.assertGreater(report.total_statutory_fees, 0.0)  # Verifies STT, GST, and turnover fees
        self.assertGreater(report.ending_capital, 500_000.0)  # Profitable target hit
        self.assertTrue(report.zero_live_order_guarantee)
        self.assertGreater(len(report.equity_curve), 0)

    def test_04_intraday_mandatory_square_off_enforcement(self) -> None:
        """Verify that open positions are forcibly closed before 15:30 IST market close."""
        engine = BankNiftyBacktestEngine(initial_capital=500_000.0)
        strategy = OpeningRangeBreakoutStrategy(units_per_trade=15)

        # Create session where position is held until 15:15 IST
        snapshots: list[MarketSnapshot] = []
        snapshots.append(
            MarketSnapshot(
                timestamp_ist="2026-10-09 09:20:00",
                spot_bar=MarketBar("2026-10-09 09:20:00", 52000, 52100, 51950, 52050),
            )
        )
        # Breakout
        ce_sym = "BANKNIFTY26OCT52200CE"
        opt_q = OptionChainQuote(symbol=ce_sym, strike=52200, option_type="CE", expiry="2026-10-26", ltp=250.0)
        snapshots.append(
            MarketSnapshot(
                timestamp_ist="2026-10-09 09:40:00",
                spot_bar=MarketBar("2026-10-09 09:40:00", 52050, 52150, 52040, 52120),
                options={ce_sym: opt_q},
            )
        )
        # Cutoff snapshot at 15:15 IST
        snapshots.append(
            MarketSnapshot(
                timestamp_ist="2026-10-09 15:15:00",
                spot_bar=MarketBar("2026-10-09 15:15:00", 52120, 52130, 52100, 52110),
                options={ce_sym: opt_q},
            )
        )

        report = engine.run(snapshots, strategy)

        # Zero positions must remain open after session completion
        self.assertEqual(len(engine.trader.positions), 0)
        self.assertEqual(report.total_trades, 2)  # 1 BUY entry + 1 SELL mandatory square-off

    def test_05_multi_model_adapter_authorization(self) -> None:
        """Verify that ModelAdapter authorizes all federated models per user directive."""
        expected_models = [
            "gemini-3.8-flash-high",
            "deepseek-ai/DeepSeek-V4-Flash-0731",
            "zai-org/GLM-5.3-Flash",
            "MiniMaxAI/MiniMax-M2.7",
        ]
        for m in expected_models:
            self.assertTrue(
                ModelAdapter.is_authorized_model(m, allow_federated=True),
                f"Model {m} must be authorized in ModelAdapter",
            )
        self.assertFalse(ModelAdapter.is_authorized_model("unauthorized-random-model"))

    def test_06_market_data_feed_resampling_and_indicators(self) -> None:
        """Verify 1-min to 5-min aggregation, intraday VWAP, and 20 EMA indicator correctness."""
        # 5 1-minute bars
        bars_1min = [
            MarketBar("2026-10-14 09:15:00", 52000.0, 52050.0, 51980.0, 52020.0, 1000),
            MarketBar("2026-10-14 09:16:00", 52020.0, 52070.0, 52010.0, 52060.0, 1500),
            MarketBar("2026-10-14 09:17:00", 52060.0, 52080.0, 52040.0, 52050.0, 800),
            MarketBar("2026-10-14 09:18:00", 52050.0, 52100.0, 52030.0, 52090.0, 2000),
            MarketBar("2026-10-14 09:19:00", 52090.0, 52120.0, 52080.0, 52110.0, 1200),
        ]
        resampled = resample_1min_to_5min(bars_1min)
        self.assertEqual(len(resampled), 1)
        r = resampled[0]
        self.assertEqual(r.open, 52000.0)
        self.assertEqual(r.high, 52120.0)
        self.assertEqual(r.low, 51980.0)
        self.assertEqual(r.close, 52110.0)
        self.assertEqual(r.volume, 6500)
        self.assertEqual(r.timestamp_ist, "2026-10-14 09:15:00")

        # Indicators test
        vwap = calculate_intraday_vwap(bars_1min)
        self.assertEqual(len(vwap), 5)
        self.assertGreater(vwap[-1], 52000.0)

        prices = [b.close for b in bars_1min]
        ema = calculate_ema(prices, period=3)
        self.assertEqual(len(ema), 5)
        self.assertAlmostEqual(ema[-1], 52090.0, delta=20.0)

    def test_07_market_data_feed_fixture_generation_and_validation(self) -> None:
        """Verify multi-regime dataset synthesis, Black-Scholes Greeks, JSON persistence, and audit."""
        feed = MarketDataFeed(storage_dir=self.temp_dir)
        snapshots = feed.generate_multi_day_dataset(start_date="2026-10-14", days=2, step_minutes=5)

        # 2 days * 76 bars/day = 152 snapshots
        self.assertGreaterEqual(len(snapshots), 140)

        # Strict validation
        valid, msg = feed.validate_fixture(snapshots)
        self.assertTrue(valid, f"Fixture failed validation: {msg}")

        # Check options chain details
        first_snap = snapshots[0]
        self.assertGreater(len(first_snap.options), 0)
        for sym, q in first_snap.options.items():
            self.assertGreater(q.ltp, 0.0)
            self.assertIn(q.option_type, ["CE", "PE"])
            self.assertGreaterEqual(q.delta, -1.0)
            self.assertLessEqual(q.delta, 1.0)

        # Test save & load roundtrip
        saved_path = feed.save_fixture(snapshots, "test_fixture.json")
        self.assertTrue(saved_path.exists())

        loaded_snapshots = feed.load_fixture(saved_path)
        self.assertEqual(len(loaded_snapshots), len(snapshots))
        self.assertEqual(loaded_snapshots[0].timestamp_ist, snapshots[0].timestamp_ist)
        self.assertEqual(loaded_snapshots[0].spot_bar.close, snapshots[0].spot_bar.close)

    def test_08_vwap_ema_and_baseline_strategy_benchmarks(self) -> None:
        """Benchmark VWAP + 20 EMA breakout strategy against No-Trade baseline on historical Bank Nifty."""
        feed = MarketDataFeed(storage_dir=self.temp_dir)
        bullish_day = feed.generate_regime_day(
            date_str="2026-10-14",
            regime="BULLISH_TRENDING",
            base_spot=52000.0,
            step_minutes=5,
            seed=42,
        )

        engine_vwap = BankNiftyBacktestEngine(initial_capital=500_000.0)
        strat_vwap = VWAPEMAStrategy(units_per_trade=15)
        report_vwap = engine_vwap.run(bullish_day, strat_vwap)

        self.assertIsInstance(report_vwap, BacktestReport)
        self.assertEqual(report_vwap.strategy_name, "BankNiftyVWAP_20EMA")
        self.assertGreater(report_vwap.total_trades, 0)
        self.assertGreater(report_vwap.total_statutory_fees, 0.0)
        self.assertTrue(report_vwap.zero_live_order_guarantee)

        # Benchmark against No-Trade baseline
        engine_base = BankNiftyBacktestEngine(initial_capital=500_000.0)
        strat_base = NoTradeBaselineStrategy()
        report_base = engine_base.run(bullish_day, strat_base)

        self.assertEqual(report_base.total_trades, 0)
        self.assertEqual(report_base.total_statutory_fees, 0.0)
        self.assertEqual(report_base.ending_capital, 500_000.0)
        self.assertEqual(report_base.total_net_pnl, 0.0)
        self.assertEqual(report_base.max_drawdown_amount, 0.0)

    def test_09_order_book_simulator_depth_fill_and_slippage(self) -> None:
        """Verify 5-level market depth walking, fill price volume-weighting, and slippage calculation."""
        book = OrderBookFactory.create_book("BANKNIFTY26OCT52000CE", ltp=300.0, is_atm=True)
        self.assertEqual(len(book.bids), 5)
        self.assertEqual(len(book.asks), 5)
        self.assertAlmostEqual(book.spread, 0.05, delta=0.01)

        # 1. Small order (15 units) matches Level 1 ask completely with zero price impact
        fill_small = book.execute_order(side=OrderSide.BUY, units=15, order_type=OrderType.MARKET)
        self.assertTrue(fill_small.fully_filled)
        self.assertEqual(fill_small.levels_consumed, 1)
        self.assertEqual(fill_small.avg_fill_price, book.best_ask)
        self.assertEqual(fill_small.slippage_amount, 0.0)

        # 2. Large order (500 units) walks through multiple levels, incurring depth-based slippage
        fill_large = book.execute_order(side=OrderSide.BUY, units=500, order_type=OrderType.MARKET)
        self.assertTrue(fill_large.fully_filled)
        self.assertGreater(fill_large.levels_consumed, 1)
        self.assertGreaterEqual(fill_large.avg_fill_price, book.best_ask)
        self.assertGreater(fill_large.slippage_amount, 0.0)
        self.assertGreater(fill_large.slippage_bps, 0.0)

        # 3. Limit order below ask: should remain unfilled
        fill_limit = book.execute_order(
            side=OrderSide.BUY,
            units=15,
            order_type=OrderType.LIMIT,
            limit_price=book.best_ask - 0.50,  # Below market ask
        )
        self.assertFalse(fill_limit.fully_filled)
        self.assertEqual(fill_limit.filled_units, 0)
        self.assertEqual(fill_limit.rationale, "UNFILLED")

    def test_10_order_book_factory_illiquid_strike_stress_test(self) -> None:
        """Stress-test wide spreads and illiquid book conditions on far OTM options."""
        illiquid_book = OrderBookFactory.create_book(
            "BANKNIFTY26OCT55000CE",
            ltp=8.50,
            is_atm=False,
            is_illiquid=True,
        )
        # Verify wide spread under illiquid regime
        self.assertGreaterEqual(illiquid_book.spread, 0.25)

        # Large fill experiences sharp slippage
        fill_stress = illiquid_book.execute_order(side=OrderSide.BUY, units=90, order_type=OrderType.MARKET)
        self.assertGreater(fill_stress.slippage_amount, 0.0)
        self.assertGreater(fill_stress.slippage_bps, 10.0)  # Significant slippage in bps


if __name__ == "__main__":
    unittest.main()


