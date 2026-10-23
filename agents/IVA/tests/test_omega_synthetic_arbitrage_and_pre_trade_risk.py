"""Acceptance tests for Synthetic Option Arbitrage & Pre-Trade Risk Engine.

TASK-BN-15:
1. Box Spread Arbitrage Detector:
   - Fair value alignment (No arbitrage when net debit ~= PV(Box)).
   - Long Box mispricing detection (Debit < PV(Box) - friction).
   - Short Box mispricing detection (Credit > PV(Box) + friction).
   - Put-Call Parity synthetic future conversion/reversal arbitrage.
TASK-BN-16:
2. Pre-Trade Risk Engine & Portfolio Kill-Switch:
   - Max single order lots limit check.
   - Max single order notional limit check.
   - Max gross portfolio exposure limit check.
   - Fat-finger price deviation check (+/- 20% from fair value).
   - Margin lockout gate (rejecting new orders when in MARGIN_CALL or FORCE_LIQUIDATION).
   - Portfolio High Water Mark tracking and peak-to-trough drawdown kill switch.
   - Emergency order cancellation plan generation and administrative reset.
"""

from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OptionType, OrderSide, OrderType
from agents.AGI_1_7.engine.agi17.finance.margin_liquidation import (
    MarginAccountSnapshot,
    MarginCallLiquidationEngine,
    MarginStatus,
)
from agents.AGI_1_7.engine.agi17.finance.pre_trade_risk_killswitch import (
    EmergencyCancellationPlan,
    PortfolioKillSwitch,
    PreTradeOrderRequest,
    PreTradeRiskEngine,
)
from agents.AGI_1_7.engine.agi17.finance.synthetic_arbitrage import (
    ArbitrageType,
    BoxSpreadArbitrageOpportunity,
    OptionMarketQuote,
    PutCallParityArbitrageOpportunity,
    SyntheticArbitrageEngine,
)


class TestOmegaSyntheticArbitrageAndPreTradeRisk(unittest.TestCase):
    """Test suite for Synthetic Option Arbitrage and Pre-Trade Risk Engine."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.journal_file = Path(self.temp_dir.name) / "risk_journal.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_01_box_spread_fair_value_no_arbitrage(self) -> None:
        """Verifies no arbitrage is reported when box quotes reflect discounted fair value."""
        # 14 days to expiry, 6.5% interest rate
        # K1 = 49000, K2 = 50000 (width = 1000)
        # PV = 1000 * exp(-0.065 * 14/365) = 997.51
        c1 = OptionMarketQuote(strike=49000.0, option_type=OptionType.CE, bid=1250.0, ask=1252.0)
        c2 = OptionMarketQuote(strike=50000.0, option_type=OptionType.CE, bid=500.0, ask=502.0)
        p2 = OptionMarketQuote(strike=50000.0, option_type=OptionType.PE, bid=280.0, ask=282.0)
        p1 = OptionMarketQuote(strike=49000.0, option_type=OptionType.PE, bid=35.0, ask=36.0)

        # Debit to buy box = Ask_C1 (1252) - Bid_C2 (500) + Ask_P2 (282) - Bid_P1 (35) = 999.0
        # Since Debit (999.0) > PV (997.51), buying yields negative excess return
        res = SyntheticArbitrageEngine.evaluate_box_spread(
            c1_quote=c1,
            c2_quote=c2,
            p2_quote=p2,
            p1_quote=p1,
            days_to_expiry=14.0,
            risk_free_rate=0.065,
        )

        self.assertIsInstance(res, BoxSpreadArbitrageOpportunity)
        self.assertEqual(res.arbitrage_type, ArbitrageType.NO_ARBITRAGE)
        self.assertFalse(res.is_actionable)
        self.assertEqual(res.max_executable_lots, 0)
        self.assertAlmostEqual(res.theoretical_pv, 997.51, places=1)

    def test_02_long_box_spread_arbitrage_detection(self) -> None:
        """Verifies detection of underpriced Box Spread with abnormal riskless yield."""
        # Box width = 1000 pts (strikes 49000 and 50000). PV ~= 997.51
        # Mispriced quotes where net buy debit is only 920.0
        c1 = OptionMarketQuote(strike=49000.0, option_type=OptionType.CE, bid=1200.0, ask=1205.0, ask_size=300)
        c2 = OptionMarketQuote(strike=50000.0, option_type=OptionType.CE, bid=520.0, ask=525.0, bid_size=450)
        p2 = OptionMarketQuote(strike=50000.0, option_type=OptionType.PE, bid=260.0, ask=265.0, ask_size=300)
        p1 = OptionMarketQuote(strike=49000.0, option_type=OptionType.PE, bid=30.0, ask=35.0, bid_size=300)

        # Buy Debit = Ask_C1 (1205) - Bid_C2 (520) + Ask_P2 (265) - Bid_P1 (30) = 920.0
        # Payoff at T is 1000. Gross edge = 1000 - 920 = 80 pts.
        res = SyntheticArbitrageEngine.evaluate_box_spread(
            c1_quote=c1,
            c2_quote=c2,
            p2_quote=p2,
            p1_quote=p1,
            days_to_expiry=14.0,
            risk_free_rate=0.065,
            min_net_spread_pts=5.0,
        )

        self.assertEqual(res.arbitrage_type, ArbitrageType.LONG_BOX_ARBITRAGE)
        self.assertTrue(res.is_actionable)
        self.assertEqual(res.max_executable_lots, 20)  # min size 300 // 15 = 20 lots
        self.assertGreater(res.implied_annualized_rate, 1.0)  # > 100% annualized return
        self.assertGreater(res.net_arbitrage_spread_per_unit, 70.0)
        self.assertGreater(res.projected_net_pnl_inr, 20_000.0)

    def test_03_short_box_spread_arbitrage_detection(self) -> None:
        """Verifies detection of overpriced Box Spread (synthetic negative-rate loan)."""
        # Box width = 1000. PV ~= 997.51.
        # Credit to sell box = Bid_C1 (1300) - Ask_C2 (480) + Bid_P2 (320) - Ask_P1 (40)
        # Wait, formula for Sell Credit in engine:
        # c1_quote.bid - c2_quote.ask + p2_quote.bid - p2_quote.ask... wait let's verify formula!
        # Sell Credit: Short C1 (Bid_C1), Long C2 (Ask_C2), Short P2 (Bid_P2), Long P1 (Ask_P1)
        # Sell Credit = Bid_C1 - Ask_C2 + Bid_P2 - Ask_P1 = 1300 - 480 + 320 - 40 = 1100.0 > 997.51
        c1 = OptionMarketQuote(strike=49000.0, option_type=OptionType.CE, bid=1300.0, ask=1305.0, bid_size=150)
        c2 = OptionMarketQuote(strike=50000.0, option_type=OptionType.CE, bid=475.0, ask=480.0, ask_size=150)
        p2 = OptionMarketQuote(strike=50000.0, option_type=OptionType.PE, bid=320.0, ask=325.0, bid_size=150)
        p1 = OptionMarketQuote(strike=49000.0, option_type=OptionType.PE, bid=35.0, ask=40.0, ask_size=150)

        res = SyntheticArbitrageEngine.evaluate_box_spread(
            c1_quote=c1,
            c2_quote=c2,
            p2_quote=p2,
            p1_quote=p1,
            days_to_expiry=14.0,
            risk_free_rate=0.065,
            min_net_spread_pts=5.0,
        )

        self.assertEqual(res.arbitrage_type, ArbitrageType.SHORT_BOX_ARBITRAGE)
        self.assertTrue(res.is_actionable)
        self.assertEqual(res.max_executable_lots, 10)  # 150 // 15 = 10 lots
        self.assertGreater(res.net_arbitrage_spread_per_unit, 50.0)
        self.assertGreater(res.projected_net_pnl_inr, 7_500.0)
        self.assertEqual(res.strike_low, 49000.0)
        self.assertEqual(res.strike_high, 50000.0)

    def test_04_put_call_parity_conversion_reversal(self) -> None:
        """Verifies Put-Call Parity conversion and reversal mispricing detection."""
        spot = 50000.0
        strike = 50000.0
        days = 10.0
        rate = 0.065
        pv_k = strike * math.exp(-rate * days / 365.0)

        # Case A: Conversion opportunity (Spot is cheap, Synthetic Future is expensive)
        # Buy Spot @ 50,000, Buy Put @ 200, Sell Call @ 500.
        # Cost = 50,000 + 200 - 500 = 49,700. Payoff at expiry = 50,000.
        # PV profit = 49,911 - 49,700 = ~211 pts.
        call_q = OptionMarketQuote(strike=strike, option_type=OptionType.CE, bid=500.0, ask=502.0)
        put_q = OptionMarketQuote(strike=strike, option_type=OptionType.PE, bid=198.0, ask=200.0)

        res = SyntheticArbitrageEngine.evaluate_put_call_parity(
            spot_price=spot,
            strike=strike,
            call_quote=call_q,
            put_quote=put_q,
            days_to_expiry=days,
            risk_free_rate=rate,
            min_profit_threshold=5.0,
        )

        self.assertEqual(res.arbitrage_type, ArbitrageType.CONVERSION_ARBITRAGE)
        self.assertTrue(res.is_actionable)
        self.assertGreater(res.net_profit_per_unit, 50.0)

    def test_05_pre_trade_risk_checks(self) -> None:
        """Verifies pre-trade risk engine filters orders violating institutional limits."""
        engine = PreTradeRiskEngine(
            max_single_order_lots=50,
            max_single_order_notional=2_500_000.0,
            max_gross_exposure=10_000_000.0,
            max_price_deviation_pct=0.20,
            journal_path=self.journal_file,
        )

        # 1. Valid order passes
        req_ok = PreTradeOrderRequest(
            order_id="ORD-001",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=150,  # 10 lots
            requested_price=500.0,
            theoretical_fair_price=505.0,
        )
        dec_ok = engine.validate_order(req_ok, current_portfolio_gross_exposure=1_000_000.0)
        self.assertTrue(dec_ok.approved)
        self.assertIsNone(dec_ok.rejection_rule)

        # 2. Lot limit breach (60 lots = 900 units > 50 lots)
        req_lots = PreTradeOrderRequest(
            order_id="ORD-002",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=900,
            requested_price=500.0,
        )
        dec_lots = engine.validate_order(req_lots, current_portfolio_gross_exposure=1_000_000.0)
        self.assertFalse(dec_lots.approved)
        self.assertEqual(dec_lots.rejection_rule, "MAX_ORDER_LOTS_BREACH")

        # 3. Notional limit breach (750 units * ₹4,000 = ₹30 Lakhs > ₹25 Lakhs)
        req_notional = PreTradeOrderRequest(
            order_id="ORD-003",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=750,
            requested_price=4_000.0,
        )
        dec_notional = engine.validate_order(req_notional, current_portfolio_gross_exposure=1_000_000.0)
        self.assertFalse(dec_notional.approved)
        self.assertEqual(dec_notional.rejection_rule, "MAX_ORDER_NOTIONAL_BREACH")

        # 4. Gross exposure breach (Existing 95 Lakhs + order 10 Lakhs > 1 Crore cap)
        req_gross = PreTradeOrderRequest(
            order_id="ORD-004",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=300,
            requested_price=3_500.0,
        )
        dec_gross = engine.validate_order(req_gross, current_portfolio_gross_exposure=9_500_000.0)
        self.assertFalse(dec_gross.approved)
        self.assertEqual(dec_gross.rejection_rule, "MAX_GROSS_EXPOSURE_BREACH")

        # 5. Fat finger deviation check (Price 700 vs fair 500 = +40% deviation > 20% limit)
        req_fat = PreTradeOrderRequest(
            order_id="ORD-005",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=150,
            requested_price=700.0,
            theoretical_fair_price=500.0,
        )
        dec_fat = engine.validate_order(req_fat, current_portfolio_gross_exposure=1_000_000.0)
        self.assertFalse(dec_fat.approved)
        self.assertEqual(dec_fat.rejection_rule, "FAT_FINGER_PRICE_DEVIATION")

        # 6. Margin lockout check
        margin_distress = MarginAccountSnapshot(
            total_equity=1_000_000.0,
            available_cash=-20_000.0,
            initial_margin_required=1_100_000.0,
            maintenance_margin_required=825_000.0,
            margin_utilization=1.10,
            status=MarginStatus.MARGIN_CALL,
            margin_deficit=100_000.0,
        )
        dec_margin = engine.validate_order(
            req_ok,
            current_portfolio_gross_exposure=1_000_000.0,
            margin_account=margin_distress,
        )
        self.assertFalse(dec_margin.approved)
        self.assertEqual(dec_margin.rejection_rule, "MARGIN_LOCKOUT")

        # Verify journal logging
        self.assertTrue(self.journal_file.exists())
        lines = self.journal_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 6)

    def test_06_portfolio_kill_switch_hwm_and_trips(self) -> None:
        """Verifies High Water Mark ratcheting, drawdown circuit-breaker trips, and resets."""
        ks = PortfolioKillSwitch(
            initial_capital=1_000_000.0,
            max_drawdown_pct=0.03,  # 3% drawdown trip
            max_daily_loss_inr=50_000.0,
        )
        self.assertFalse(ks.is_engaged)

        # 1. Equity grows -> HWM ratchets higher
        res1 = ks.update_equity(1_200_000.0)
        self.assertIsNone(res1)
        self.assertEqual(ks.peak_equity, 1_200_000.0)
        self.assertFalse(ks.is_engaged)

        # 2. Equity drops from 1,200,000 to 1,150,000 (DD = 4.17% > 3.0% threshold)
        plan = ks.update_equity(
            1_150_000.0,
            open_working_order_ids=["ORD-OPEN-1", "ORD-OPEN-2"],
        )
        self.assertIsNotNone(plan)
        self.assertIsInstance(plan, EmergencyCancellationPlan)
        self.assertTrue(ks.is_engaged)
        self.assertTrue(plan.kill_switch_engaged)
        self.assertIn("Peak-to-Trough drawdown limit breached", plan.trigger_reason)
        self.assertEqual(plan.orders_to_cancel, ["ORD-OPEN-1", "ORD-OPEN-2"])

        # 3. Orders submitted during kill switch are blocked by PreTradeRiskEngine
        engine = PreTradeRiskEngine()
        req = PreTradeOrderRequest(
            order_id="ORD-010",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=150,
            requested_price=500.0,
        )
        dec = engine.validate_order(
            req,
            current_portfolio_gross_exposure=500_000.0,
            kill_switch=ks,
        )
        self.assertFalse(dec.approved)
        self.assertEqual(dec.rejection_rule, "KILL_SWITCH_ACTIVE")

        # 4. Administrative reset requires valid token
        with self.assertRaises(ValueError):
            ks.reset("short")  # Invalid token

        ks.reset("AUTHORIZED_ADMIN_OVERRIDE_2026")
        self.assertFalse(ks.is_engaged)


if __name__ == "__main__":
    unittest.main()
