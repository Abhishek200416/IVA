"""AGI 1.7 Acceptance Test Suite: Volatility Surface & Implied Volatility Skew Interpolation.

Verifies:
1. Downside Put Skew: OTM Puts trade at higher IV than ATM and OTM Calls (typical of Bank Nifty).
2. Boundary Protections: Arbitrage-free bounds (5% floor, 150% ceiling) under extreme moneyness.
3. Ordinary Least Squares Surface Calibration from observed option chain quotes.
4. Skew-aware Black-Scholes fair pricing and Greek sensitivity consistency.
"""

from __future__ import annotations

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OptionType
from agents.AGI_1_7.engine.agi17.finance.volatility_surface import (
    ObservedQuoteIV,
    SurfaceCalibrationResult,
    VolatilitySurfaceModel,
)


class TestOmegaVolatilitySurface(unittest.TestCase):
    """Test battery for Volatility Surface & Skew modeling."""

    def setUp(self) -> None:
        self.spot = 50000.0
        self.model = VolatilitySurfaceModel(
            base_atm_vol=0.16,
            skew_slope=-0.20,
            smile_curvature=0.40,
        )

    def test_01_log_moneyness_and_downside_put_skew(self) -> None:
        """Verifies that OTM Puts have higher IV than ATM, which in turn is higher than OTM Calls."""
        atm_strike = 50000.0
        otm_put_strike = 48500.0   # m = ln(48500 / 50000) < 0
        otm_call_strike = 51500.0  # m = ln(51500 / 50000) > 0

        atm_iv = self.model.get_implied_volatility(strike=atm_strike, spot=self.spot)
        otm_put_iv = self.model.get_implied_volatility(strike=otm_put_strike, spot=self.spot)
        otm_call_iv = self.model.get_implied_volatility(strike=otm_call_strike, spot=self.spot)

        # OTM Put should have higher IV due to negative slope (crash protection premium)
        self.assertGreater(otm_put_iv, atm_iv)
        # OTM Put IV must exceed OTM Call IV (negative skew)
        self.assertGreater(otm_put_iv, otm_call_iv)
        self.assertAlmostEqual(atm_iv, 0.16, places=2)

    def test_02_arbitrage_free_volatility_bounds(self) -> None:
        """Verifies bounded constraints under extreme deep-in-the-money or deep-out-of-the-money strikes."""
        deep_otm = 20000.0   # Extremely far OTM put / ITM call
        deep_itm = 90000.0   # Extremely far OTM call / ITM put

        deep_otm_iv = self.model.get_implied_volatility(strike=deep_otm, spot=self.spot)
        deep_itm_iv = self.model.get_implied_volatility(strike=deep_itm, spot=self.spot)

        self.assertGreaterEqual(deep_otm_iv, self.model.MIN_VOL)
        self.assertLessEqual(deep_otm_iv, self.model.MAX_VOL)

        self.assertGreaterEqual(deep_itm_iv, self.model.MIN_VOL)
        self.assertLessEqual(deep_itm_iv, self.model.MAX_VOL)

    def test_03_surface_calibration_from_observed_quotes(self) -> None:
        """Calibrates surface parameters from a synthetic option chain."""
        quotes = [
            ObservedQuoteIV(strike=48000.0, spot=self.spot, time_to_expiry_years=0.02, option_type=OptionType.PE, market_price=120.0, implied_vol=0.22),
            ObservedQuoteIV(strike=49000.0, spot=self.spot, time_to_expiry_years=0.02, option_type=OptionType.PE, market_price=220.0, implied_vol=0.18),
            ObservedQuoteIV(strike=50000.0, spot=self.spot, time_to_expiry_years=0.02, option_type=OptionType.CE, market_price=350.0, implied_vol=0.155),
            ObservedQuoteIV(strike=51000.0, spot=self.spot, time_to_expiry_years=0.02, option_type=OptionType.CE, market_price=160.0, implied_vol=0.145),
            ObservedQuoteIV(strike=52000.0, spot=self.spot, time_to_expiry_years=0.02, option_type=OptionType.CE, market_price=65.0, implied_vol=0.15),
        ]

        cal_res = self.model.calibrate_from_quotes(quotes, spot=self.spot)

        self.assertIsInstance(cal_res, SurfaceCalibrationResult)
        self.assertEqual(cal_res.observations_count, 5)
        self.assertLess(cal_res.mean_squared_error, 0.001)
        self.assertLess(cal_res.skew_slope, 0.0)  # Preserves negative skew

    def test_04_skew_aware_option_pricing(self) -> None:
        """Compares flat-IV vs skew-aware option pricing."""
        strike = 48500.0  # OTM Put
        t_years = 14.0 / 365.0

        # Flat pricing at 16%
        from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import BlackScholesCalculator
        flat_greeks = BlackScholesCalculator.calculate_greeks(
            spot=self.spot,
            strike=strike,
            time_to_expiry_years=t_years,
            rate=0.065,
            volatility=0.16,
            option_type=OptionType.PE,
        )

        # Skew-aware pricing (IV > 16%)
        skew_price, skew_greeks = self.model.price_option_with_skew(
            spot=self.spot,
            strike=strike,
            time_to_expiry_years=t_years,
            option_type=OptionType.PE,
        )

        # OTM Put with skew should price higher than flat ATM volatility
        self.assertGreater(skew_price, flat_greeks.price)
        self.assertGreater(skew_greeks.vega, 0.0)


if __name__ == "__main__":
    unittest.main()
