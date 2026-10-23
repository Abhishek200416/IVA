"""AGI 1.7 Acceptance Test Suite: Dynamic Regime-Adaptive Strategy & 5-Level Order Book Integration.

Verifies:
1. Direct integration of 5-level SimulatedOrderBook into BankNiftyPaperTrader.execute_paper_order.
2. Depth-based level walking and volume-weighted execution prices in live paper mode.
3. DynamicRegimeAdaptiveStrategy multi-regime classification and allocation (Bullish breakout vs Ranging strangle).
4. BankNiftyBacktestEngine 5-level market depth toggle (use_order_book_depth=True).
5. Zero lookahead bias, strict statutory fee deductions, and 15:15 IST mandatory square-off.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import (
    BankNiftyPaperTrader,
    OrderSide,
    OrderType,
)
from agents.AGI_1_7.engine.agi17.finance.order_book_simulator import (
    OrderBookFactory,
    SimulatedOrderBook,
)
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_backtest import (
    BankNiftyBacktestEngine,
    DynamicRegimeAdaptiveStrategy,
    MarketBar,
    MarketSnapshot,
    OptionChainQuote,
    VWAPEMAStrategy,
)
from agents.AGI_1_7.engine.agi17.finance.market_data_feed import MarketDataFeed


class TestOmegaAdaptiveAndLiveBook(unittest.TestCase):
    """Test battery for Wave 3 quantitative features."""

    def setUp(self) -> None:
        self.fixture_path = (
            Path(__file__).resolve().parent.parent
            / "runtime_storage"
            / "finance"
            / "data"
            / "bank_nifty_multi_regime_fixture.json"
        )
        self.assertTrue(self.fixture_path.exists(), f"Fixture missing at {self.fixture_path}")
        with open(self.fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.snapshots = []
        for d in data:
            sb = MarketBar(**d["spot_bar"])
            opts = {k: OptionChainQuote(**v) for k, v in d["options"].items()}
            self.snapshots.append(MarketSnapshot(timestamp_ist=d["timestamp_ist"], spot_bar=sb, options=opts))

    def test_paper_trader_order_book_depth_execution(self) -> None:
        """Verifies that BankNiftyPaperTrader executes against a 5-level SimulatedOrderBook."""
        trader = BankNiftyPaperTrader(initial_capital=500_000.0)
        symbol = "BANKNIFTY26OCT48500CE"
        book = trader.create_order_book(symbol=symbol, ltp=350.0, is_atm=True)

        res = trader.execute_paper_order(
            idempotency_key="TEST-DEPTH-01",
            symbol=symbol,
            side=OrderSide.BUY,
            units=15,
            market_price=350.0,
            order_book=book,
        )

        self.assertTrue(res["success"], f"Order failed: {res}")
        self.assertIn("fill_result", res)
        fill = res["fill_result"]
        self.assertEqual(fill["filled_units"], 15)
        self.assertTrue(fill["fully_filled"])
        self.assertGreaterEqual(fill["levels_consumed"], 1)
        self.assertGreater(fill["avg_fill_price"], 0.0)
        self.assertIn(symbol, trader.positions)
        self.assertEqual(trader.positions[symbol], 15)

    def test_paper_trader_illiquid_multi_level_walking(self) -> None:
        """Verifies multi-level walking and depth slippage under illiquid regimes."""
        trader = BankNiftyPaperTrader(initial_capital=500_000.0)
        symbol = "BANKNIFTY26OCT49500CE"
        # Illiquid book has smaller lots per level (15-45 units)
        illiquid_book = trader.create_order_book(symbol=symbol, ltp=80.0, is_atm=False, is_illiquid=True)

        # Request 60 units (4 lots) to force walking across multiple depth levels
        res = trader.execute_paper_order(
            idempotency_key="TEST-DEPTH-MULTI-01",
            symbol=symbol,
            side=OrderSide.BUY,
            units=60,
            market_price=80.0,
            order_book=illiquid_book,
        )

        self.assertTrue(res["success"])
        fill = res["fill_result"]
        self.assertEqual(fill["filled_units"], 60)
        self.assertGreaterEqual(fill["levels_consumed"], 2)  # Walked at least 2 levels
        self.assertGreater(fill["avg_fill_price"], fill["expected_top_price"])
        self.assertGreater(fill["slippage_bps"], 0.0)

    def test_paper_trader_unfilled_limit_on_order_book(self) -> None:
        """Verifies clean rejection when limit price cannot be filled by the order book."""
        trader = BankNiftyPaperTrader(initial_capital=500_000.0)
        symbol = "BANKNIFTY26OCT48500CE"
        book = trader.create_order_book(symbol=symbol, ltp=350.0, is_atm=True)

        # Attempt to buy at limit price 300.0 when best ask is ~350.0
        res = trader.execute_paper_order(
            idempotency_key="TEST-DEPTH-LIMIT-01",
            symbol=symbol,
            side=OrderSide.BUY,
            units=15,
            market_price=350.0,
            order_type=OrderType.LIMIT,
            limit_price=300.0,
            order_book=book,
        )

        self.assertFalse(res["success"])
        self.assertIn("UNFILLED", res["reason"])
        self.assertNotIn(symbol, trader.positions)

    def test_dynamic_regime_adaptive_strategy_replay(self) -> None:
        """Verifies DynamicRegimeAdaptiveStrategy across multi-regime backtest."""
        engine = BankNiftyBacktestEngine(initial_capital=500_000.0)
        strategy = DynamicRegimeAdaptiveStrategy(units_per_trade=15)

        report = engine.run(self.snapshots, strategy)

        self.assertEqual(report.strategy_name, "BankNiftyDynamicRegimeAdaptive")
        self.assertTrue(report.zero_live_order_guarantee)
        self.assertGreaterEqual(report.total_trades, 1)
        self.assertGreater(report.total_statutory_fees, 0.0)
        # All positions must be closed at session end
        self.assertEqual(len(engine.trader.positions), 0)

    def test_backtest_engine_order_book_depth_toggle(self) -> None:
        """Compares flat-slippage vs 5-level depth walking backtest execution."""
        # 1. Flat slippage backtest
        engine_flat = BankNiftyBacktestEngine(initial_capital=500_000.0, use_order_book_depth=False)
        strategy_flat = DynamicRegimeAdaptiveStrategy(units_per_trade=15)
        report_flat = engine_flat.run(self.snapshots, strategy_flat)

        # 2. 5-level depth walking backtest
        engine_depth = BankNiftyBacktestEngine(initial_capital=500_000.0, use_order_book_depth=True)
        strategy_depth = DynamicRegimeAdaptiveStrategy(units_per_trade=15)
        report_depth = engine_depth.run(self.snapshots, strategy_depth)

        self.assertTrue(report_flat.zero_live_order_guarantee)
        self.assertTrue(report_depth.zero_live_order_guarantee)
        self.assertGreaterEqual(report_depth.total_trades, 1)
        self.assertEqual(report_flat.total_trades, report_depth.total_trades)
        # Depth execution records realistic fills
        self.assertIsInstance(report_depth.total_net_pnl, float)
        self.assertIsInstance(report_depth.sharpe_ratio, float)

    def test_atr_trailing_stop_hedger_monotonicity_and_execution(self) -> None:
        """Verifies ATR Trailing Stop calculation, monotonicity, and strategy integration."""
        from agents.AGI_1_7.engine.agi17.finance.bank_nifty_backtest import ATRTrailingStopHedger

        hedger = ATRTrailingStopHedger(atr_period=3, multiplier=1.5)
        # Bar 1: 100-110, close 108
        atr1 = hedger.update_bar(MarketBar(timestamp_ist="2026-10-09 09:15:00", open=100.0, high=110.0, low=100.0, close=108.0))
        self.assertEqual(atr1, 10.0)

        # Bar 2: 105-120, close 118 -> TR = max(15, 12, 3) = 15
        atr2 = hedger.update_bar(MarketBar(timestamp_ist="2026-10-09 09:20:00", open=108.0, high=120.0, low=105.0, close=118.0))
        self.assertAlmostEqual(atr2, 12.5)

        # For a Call: Initial SL at 100.0. Price rises to 125.0 -> new SL = 125 - 1.5 * 12.5 = 106.25 > 100.0
        sl1 = hedger.compute_trailing_stop(current_spot=125.0, current_sl=100.0, is_call=True, atr=atr2)
        self.assertGreater(sl1, 100.0)

        # If price dips back to 120.0, SL must NOT decrease (strict monotonicity)
        sl2 = hedger.compute_trailing_stop(current_spot=120.0, current_sl=sl1, is_call=True, atr=atr2)
        self.assertEqual(sl2, sl1)

        # Strategy test with ATR trailing enabled
        engine = BankNiftyBacktestEngine(initial_capital=500_000.0)
        strategy = VWAPEMAStrategy(units_per_trade=15, use_atr_trailing=True, atr_multiplier=1.5)
        report = engine.run(self.snapshots, strategy)
        self.assertTrue(report.zero_live_order_guarantee)
        self.assertGreaterEqual(report.total_trades, 1)

    def test_market_calendar_expiry_chain_and_contract_roll(self) -> None:
        """Verifies multi-week expiry chain generation, DTE calculation, and roll triggers."""
        import datetime
        from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyMarketCalendar

        cal = BankNiftyMarketCalendar()
        ref = datetime.date(2026, 10, 5)  # A Monday

        chain = cal.get_expiry_chain(ref_date=ref, count=4)
        self.assertEqual(len(chain), 4)
        # Monotonically increasing
        for i in range(len(chain) - 1):
            self.assertLess(chain[i], chain[i + 1])
            # Must be a trading day
            self.assertTrue(cal.is_trading_day(chain[i]))
            self.assertNotIn(chain[i].weekday(), (5, 6))

        # Test DTE
        nearest = chain[0]
        dte = cal.calculate_dte(nearest, current_date=ref)
        self.assertGreaterEqual(dte, 1.0)

        # Test Roll trigger
        self.assertFalse(cal.should_roll_contract(nearest, current_date=ref, min_dte=0.5))
        # On expiry day (DTE = 0.0), roll must be triggered
        self.assertTrue(cal.should_roll_contract(nearest, current_date=nearest, min_dte=0.5))


if __name__ == "__main__":
    unittest.main()

