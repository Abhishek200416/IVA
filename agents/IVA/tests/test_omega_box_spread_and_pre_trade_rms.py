"""Acceptance tests for Box Spread Arbitrage, Pre-Trade RMS & SEBI Monthly Calendar.

Covers:
1. TASK-BN-15: BoxSpreadArbitrageEngine:
   - 4-leg box spread payoff invariance (K2 - K1).
   - Implied synthetic interest rate calculation.
   - Indian market statutory charge modeling (STT, GST, Exchange, SEBI, Stamp Duty, Brokerage).
   - Frictional erosion detection distinguishing viable arbitrage from fee-eroded phantom spreads.
2. TASK-BN-16: BankNiftyPreTradeRms:
   - SEBI/NSE tick size (0.05) and lot size bounds.
   - Notional value and strike concentration gating.
   - Peak-to-trough intraday drawdown kill-switch and trade lockout.
3. BankNiftyMarketCalendar:
   - Monthly expiry schedule verification across regulatory eras (Thursdays pre-2024, Wednesdays 2024-2025, Tuesdays post-Sept 2025).
"""

from __future__ import annotations

import datetime
import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyMarketCalendar
from agents.AGI_1_7.engine.agi17.finance.box_spread_arbitrage import (
    BoxSpreadArbitrageEngine,
    BoxSpreadArbitrageResult,
    BoxSpreadLegQuote,
)
from agents.AGI_1_7.engine.agi17.finance.pre_trade_rms import (
    BankNiftyPreTradeRms,
    PreTradeOrderIntent,
    RmsCheckResult,
)


class TestOmegaBoxSpreadAndPreTradeRms(unittest.TestCase):
    """Test suite for Box Spread Arbitrage and Pre-Trade RMS."""

    def test_01_box_spread_payoff_and_implied_rate(self) -> None:
        """Verifies 4-leg box spread payoff width and implied synthetic lending rate."""
        k1 = 50000.0
        k2 = 50500.0
        strike_width = 500.0
        t = 30.0 / 365.0  # 30 days to expiry

        # Synthetic net debit = 485 INR (less than 500 INR width)
        call_k1 = BoxSpreadLegQuote(strike=k1, bid=590.0, ask=600.0)
        call_k2 = BoxSpreadLegQuote(strike=k2, bid=280.0, ask=290.0)  # Call spread cost: 600 - 280 = 320
        put_k1 = BoxSpreadLegQuote(strike=k1, bid=150.0, ask=160.0)
        put_k2 = BoxSpreadLegQuote(strike=k2, bid=310.0, ask=325.0)   # Put spread cost: 325 - 150 = 175
        # Total net debit = 320 + 175 = 495

        res = BoxSpreadArbitrageEngine.evaluate_box_spread(
            call_k1=call_k1,
            call_k2=call_k2,
            put_k1=put_k1,
            put_k2=put_k2,
            time_to_expiry_years=t,
            risk_free_rate=0.065,
            lot_size=15,
        )

        self.assertIsInstance(res, BoxSpreadArbitrageResult)
        self.assertEqual(res.strike_width, 500.0)
        self.assertEqual(res.net_debit_market, 495.0)
        # Gross profit per share = 5.0 -> for 15 lots = 75.0 INR
        self.assertEqual(res.gross_arbitrage_profit, 75.0)
        # Implied synthetic rate should be positive because width > net debit
        self.assertGreater(res.implied_synthetic_rate, 0.0)

    def test_02_box_spread_statutory_charge_and_frictional_erosion(self) -> None:
        """Verifies statutory charges erode small theoretical mispricings."""
        k1 = 50000.0
        k2 = 50500.0
        t = 15.0 / 365.0

        # Scenario A: Thin spread (gross profit = 75 INR per lot) -> Eroded by fees
        call_k1 = BoxSpreadLegQuote(strike=k1, bid=590.0, ask=600.0)
        call_k2 = BoxSpreadLegQuote(strike=k2, bid=280.0, ask=290.0)
        put_k1 = BoxSpreadLegQuote(strike=k1, bid=150.0, ask=160.0)
        put_k2 = BoxSpreadLegQuote(strike=k2, bid=310.0, ask=325.0)

        res_thin = BoxSpreadArbitrageEngine.evaluate_box_spread(
            call_k1=call_k1,
            call_k2=call_k2,
            put_k1=put_k1,
            put_k2=put_k2,
            time_to_expiry_years=t,
            lot_size=15,
        )
        self.assertFalse(res_thin.is_arbitrage_viable)
        self.assertIn("EROSION_BY_FRICTION", res_thin.status_message)
        self.assertGreater(res_thin.total_statutory_charges, 80.0)  # > Rs 80 brokerage alone

        # Scenario B: Wide mispricing (net debit = 420 INR, gross profit = 80 * 15 = 1200 INR) -> Viable
        call_k1_wide = BoxSpreadLegQuote(strike=k1, bid=550.0, ask=560.0)
        call_k2_wide = BoxSpreadLegQuote(strike=k2, bid=300.0, ask=310.0) # 560 - 300 = 260
        put_k1_wide = BoxSpreadLegQuote(strike=k1, bid=140.0, ask=150.0)
        put_k2_wide = BoxSpreadLegQuote(strike=k2, bid=290.0, ask=300.0)  # 300 - 140 = 160
        # Net debit = 260 + 160 = 420. Gross profit = (500 - 420) * 15 = 1200 INR

        res_wide = BoxSpreadArbitrageEngine.evaluate_box_spread(
            call_k1=call_k1_wide,
            call_k2=call_k2_wide,
            put_k1=put_k1_wide,
            put_k2=put_k2_wide,
            time_to_expiry_years=t,
            lot_size=15,
        )
        self.assertTrue(res_wide.is_arbitrage_viable)
        self.assertIn("ARBITRAGE_VIABLE", res_wide.status_message)
        self.assertGreater(res_wide.net_arbitrage_profit_per_lot, 200.0)

    def test_03_pre_trade_rms_order_approval_and_tick_validation(self) -> None:
        """Verifies pre-trade RMS approval, 0.05 tick checks, and lot limits."""
        rms = BankNiftyPreTradeRms(starting_equity=1_000_000.0)

        # 1. Valid order
        valid_order = PreTradeOrderIntent(
            order_id="ORD-001",
            symbol="BANKNIFTY26OCT50000CE",
            strike=50000.0,
            option_type="CE",
            lots=5,
            lot_size=15,
            price=250.05,  # Valid multiple of 0.05
            is_buy=True,
        )
        res1 = rms.validate_order(valid_order)
        self.assertTrue(res1.is_approved)
        self.assertEqual(res1.verdict_code, "APPROVED")

        # 2. Invalid tick price (250.07 is not a multiple of 0.05)
        bad_tick_order = PreTradeOrderIntent(
            order_id="ORD-002",
            symbol="BANKNIFTY26OCT50000CE",
            strike=50000.0,
            option_type="CE",
            lots=5,
            lot_size=15,
            price=250.07,
            is_buy=True,
        )
        res2 = rms.validate_order(bad_tick_order)
        self.assertFalse(res2.is_approved)
        self.assertEqual(res2.verdict_code, "REJECTED_INVALID_TICK_SIZE")

        # 3. Exceeded max single order lots (50 > 40 limit)
        too_many_lots = PreTradeOrderIntent(
            order_id="ORD-003",
            symbol="BANKNIFTY26OCT50000CE",
            strike=50000.0,
            option_type="CE",
            lots=50,
            lot_size=15,
            price=250.00,
            is_buy=True,
        )
        res3 = rms.validate_order(too_many_lots)
        self.assertFalse(res3.is_approved)
        self.assertEqual(res3.verdict_code, "REJECTED_ORDER_LOTS_EXCEEDED")

    def test_04_pre_trade_rms_drawdown_kill_switch(self) -> None:
        """Verifies peak-to-trough intraday drawdown kill-switch circuit breaker."""
        rms = BankNiftyPreTradeRms(starting_equity=1_000_000.0, max_drawdown_pct=0.03)  # 3.0% limit

        # Account rallies to 1,050,000 HWM
        rms.update_equity(1_050_000.0)
        self.assertEqual(rms.high_water_mark, 1_050_000.0)
        self.assertFalse(rms.kill_switch_active)

        # Equity drops to 1,010,000 (drawdown = 40,000 / 1,050,000 = 3.81% > 3.0%)
        rms.update_equity(1_010_000.0)
        self.assertTrue(rms.kill_switch_active)
        self.assertIsNotNone(rms.kill_switch_triggered_at)

        # New order must be rejected by kill-switch
        order = PreTradeOrderIntent(
            order_id="ORD-KILL",
            symbol="BANKNIFTY26OCT50000CE",
            strike=50000.0,
            option_type="CE",
            lots=2,
            lot_size=15,
            price=100.00,
            is_buy=True,
        )
        res = rms.validate_order(order)
        self.assertFalse(res.is_approved)
        self.assertEqual(res.verdict_code, "REJECTED_DRAWDOWN_KILL_SWITCH")

    def test_05_monthly_expiry_schedule_historical_and_current(self) -> None:
        """Verifies BankNiftyMarketCalendar monthly expiry logic across regulatory eras."""
        calendar = BankNiftyMarketCalendar()

        # 1. Pre-March 2024 era (e.g. Jan 2024): Last Thursday
        exp_jan_2024 = calendar.get_monthly_expiry(2024, 1)
        self.assertEqual(exp_jan_2024.weekday(), 3)  # Thursday
        self.assertEqual(exp_jan_2024, datetime.date(2024, 1, 25))

        # 2. March 2024 - Aug 2025 era (e.g. October 2024): Last Wednesday
        exp_oct_2024 = calendar.get_monthly_expiry(2024, 10)
        self.assertEqual(exp_oct_2024.weekday(), 2)  # Wednesday
        self.assertEqual(exp_oct_2024, datetime.date(2024, 10, 30))

        # 3. Post-Sept 2025 era (e.g. October 2026): Last Tuesday
        exp_oct_2026 = calendar.get_monthly_expiry(2026, 10)
        self.assertEqual(exp_oct_2026.weekday(), 1)  # Tuesday
        self.assertEqual(exp_oct_2026, datetime.date(2026, 10, 27))

        # 4. Chain generation
        chain = calendar.get_monthly_expiry_chain(ref_date=datetime.date(2026, 10, 1), count=3)
        self.assertEqual(len(chain), 3)
        self.assertTrue(chain[0] < chain[1] < chain[2])


if __name__ == "__main__":
    unittest.main()
