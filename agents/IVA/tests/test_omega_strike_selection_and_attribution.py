"""AGI 1.7 Acceptance Tests for Options Strike Selection & Greeks P&L Attribution.

Covers:
1. BankNiftyStrikeSelector:
   - Target Delta matching (0.50 ATM, 0.30 OTM Wings).
   - Liquidity filtering (Open Interest floor & max bid-ask spread constraint).
2. OptionsPnlAttributionEngine:
   - 1st and 2nd order Taylor-series decomposition (Delta, Gamma, Theta, Vega).
   - Realized P&L explained ratio variance (>= 90% explained under normal diffusion).
"""

from __future__ import annotations

import datetime
import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OptionType
from agents.AGI_1_7.engine.agi17.finance.options_attribution_and_selection import (
    BankNiftyStrikeSelector,
    GreeksPnlAttributionReport,
    OptionsPnlAttributionEngine,
    SelectedStrikeCandidate,
)
from agents.AGI_1_7.engine.agi17.finance.options_math import OptionsMath


class TestOmegaStrikeSelectionAndAttribution(unittest.TestCase):
    """Test suite for strike selection and P&L Greeks attribution."""

    def test_01_atm_strike_selection(self) -> None:
        """Verifies selecting ATM strike with target delta 0.50."""
        spot = 50030.0
        expiry = datetime.date(2026, 10, 28)
        t = 7.0 / 365.0

        candidate = BankNiftyStrikeSelector.select_strike_by_delta(
            spot_price=spot,
            target_delta=0.50,
            option_type=OptionType.CE,
            expiry_date=expiry,
            time_to_expiry_years=t,
            volatility=0.16,
        )

        self.assertIsInstance(candidate, SelectedStrikeCandidate)
        self.assertIn(candidate.strike, (50000.0, 50100.0))  # Adjacent ATM strikes
        self.assertAlmostEqual(candidate.delta, 0.50, delta=0.05)
        self.assertTrue(candidate.is_liquid)
        self.assertIn("BANKNIFTY", candidate.contract_symbol)

    def test_02_otm_delta_wing_selection(self) -> None:
        """Verifies selecting OTM strike with target delta ~ 0.30 for Strangle."""
        spot = 50000.0
        expiry = datetime.date(2026, 10, 28)
        t = 14.0 / 365.0

        # OTM Call with delta 0.30
        call_cand = BankNiftyStrikeSelector.select_strike_by_delta(
            spot_price=spot,
            target_delta=0.30,
            option_type=OptionType.CE,
            expiry_date=expiry,
            time_to_expiry_years=t,
            volatility=0.16,
        )
        self.assertGreater(call_cand.strike, spot)  # OTM Call has strike > spot
        self.assertAlmostEqual(call_cand.delta, 0.30, delta=0.05)

        # OTM Put with delta -0.30
        put_cand = BankNiftyStrikeSelector.select_strike_by_delta(
            spot_price=spot,
            target_delta=0.30,
            option_type=OptionType.PE,
            expiry_date=expiry,
            time_to_expiry_years=t,
            volatility=0.16,
        )
        self.assertLess(put_cand.strike, spot)  # OTM Put has strike < spot
        self.assertAlmostEqual(abs(put_cand.delta), 0.30, delta=0.05)

    def test_03_liquidity_gating_and_score(self) -> None:
        """Verifies candidate scoring penalizes illiquid strikes with wide spreads."""
        spot = 50000.0
        expiry = datetime.date(2026, 10, 28)
        t = 7.0 / 365.0

        quotes = {
            50000.0: {"open_interest": 1000, "bid_ask_spread": 2.50},  # Severely illiquid
            50100.0: {"open_interest": 250_000, "bid_ask_spread": 0.05},  # Highly liquid
        }

        candidate = BankNiftyStrikeSelector.select_strike_by_delta(
            spot_price=spot,
            target_delta=0.50,
            option_type=OptionType.CE,
            expiry_date=expiry,
            time_to_expiry_years=t,
            available_market_quotes=quotes,
        )
        # Even though 50000 is closer to ATM, 50100 is chosen because of the liquidity penalty
        self.assertTrue(candidate.is_liquid)
        self.assertEqual(candidate.strike, 50100.0)

    def test_04_greeks_pnl_attribution_decomposition(self) -> None:
        """Verifies Greeks P&L decomposition accurately accounts for price, theta, and vega changes."""
        spot_init = 50000.0
        strike = 50000.0
        t_init = 10.0 / 365.0
        vol_init = 0.16
        rate = 0.065

        greeks_init = OptionsMath.calculate_greeks(
            spot=spot_init,
            strike=strike,
            time_to_expiry_years=t_init,
            risk_free_rate=rate,
            volatility=vol_init,
            is_call=True,
        )
        px_init = greeks_init["price"]

        # Next day: spot rises +150 pts, vol drops -1.0%, 1 day elapsed
        spot_final = 50150.0
        vol_final = 0.15
        t_final = 9.0 / 365.0

        greeks_final = OptionsMath.calculate_greeks(
            spot=spot_final,
            strike=strike,
            time_to_expiry_years=t_final,
            risk_free_rate=rate,
            volatility=vol_final,
            is_call=True,
        )
        px_final = greeks_final["price"]

        # Long 30 units (2 lots)
        units = 30
        report = OptionsPnlAttributionEngine.attribute_pnl(
            symbol="BANKNIFTY26OCT50000CE",
            units=units,
            initial_spot=spot_init,
            final_spot=spot_final,
            initial_iv=vol_init,
            final_iv=vol_final,
            initial_greeks=greeks_init,
            initial_price=px_init,
            final_price=px_final,
            days_elapsed=1.0,
        )

        self.assertIsInstance(report, GreeksPnlAttributionReport)
        self.assertGreater(report.delta_pnl, 0.0)  # Spot rose -> delta PnL positive
        self.assertLess(report.theta_pnl, 0.0)    # Long option suffered theta decay
        self.assertLess(report.vega_pnl, 0.0)     # Vol dropped -> vega loss
        # The sum of explained P&L must account for >= 90% of total P&L
        self.assertGreaterEqual(report.explained_ratio_pct, 90.0)


if __name__ == "__main__":
    unittest.main()
