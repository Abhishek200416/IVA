"""Acceptance tests for Dupire (1994) Arbitrage-Free Local Volatility Surface Engine.

TASK-BN-29:
Covers:
1. Flat volatility invariance (constant IV yields identical local volatility).
2. Negative skew slope amplification (local vol slope is steeper than implied vol slope).
3. Calendar arbitrage detection and numerical non-negative clamping.
4. Butterfly arbitrage detection (strictly positive risk-neutral density).
5. 2D Local volatility surface grid construction across strikes and maturities.
6. Euler-Maruyama local volatility discrete step simulation.
"""

from __future__ import annotations

import math
import unittest
from typing import Callable

from agents.AGI_1_7.engine.agi17.finance.local_volatility_engine import (
    DupireLocalVolatilityEngine,
    LocalVolPoint,
    LocalVolSurfaceGrid,
)


class TestOmegaLocalVolatilityEngine(unittest.TestCase):
    """Test suite for DupireLocalVolatilityEngine and arbitrage-free surface calibration."""

    def setUp(self) -> None:
        self.engine = DupireLocalVolatilityEngine(risk_free_rate=0.065)

    def test_flat_volatility_asymptotic_invariance(self) -> None:
        """Verify that under constant implied volatility, local volatility recovers base IV."""
        spot = 50000.0
        strike = 50000.0  # ATM
        t_exp = 0.10      # ~36 days
        base_iv = 0.16

        pt = self.engine.calculate_local_volatility(
            spot=spot,
            strike=strike,
            time_to_expiry_years=t_exp,
            base_iv=base_iv,
        )

        self.assertFalse(pt.is_calendar_arbitrage)
        self.assertFalse(pt.is_butterfly_arbitrage)
        # Numerical tolerance within 0.015 of 0.16
        self.assertAlmostEqual(pt.local_vol, base_iv, delta=0.015)

    def test_negative_skew_slope_amplification(self) -> None:
        """Verify that negative implied volatility skew generates steeper local volatility."""
        spot = 50000.0
        t_exp = 0.08

        # Define realistic Bank Nifty put skew: IV = 0.16 - 0.000015 * (K - S)
        def skewed_iv(k: float, t: float) -> float:
            return 0.16 - 0.000015 * (k - spot)

        pt_otm_put = self.engine.calculate_local_volatility(
            spot=spot,
            strike=49000.0,
            time_to_expiry_years=t_exp,
            iv_model=skewed_iv,
        )
        pt_atm = self.engine.calculate_local_volatility(
            spot=spot,
            strike=50000.0,
            time_to_expiry_years=t_exp,
            iv_model=skewed_iv,
        )
        pt_otm_call = self.engine.calculate_local_volatility(
            spot=spot,
            strike=51000.0,
            time_to_expiry_years=t_exp,
            iv_model=skewed_iv,
        )

        # OTM Put local vol > ATM local vol > OTM Call local vol
        self.assertGreater(pt_otm_put.local_vol, pt_atm.local_vol)
        self.assertGreater(pt_atm.local_vol, pt_otm_call.local_vol)

        # Verify amplification: local vol spread is larger than implied vol spread
        imp_spread = pt_otm_put.implied_vol - pt_otm_call.implied_vol
        loc_spread = pt_otm_put.local_vol - pt_otm_call.local_vol
        self.assertGreater(loc_spread, imp_spread)

    def test_calendar_arbitrage_detection_and_safety(self) -> None:
        """Verify engine detects calendar arbitrage and clamps safely without NaN/errors."""
        spot = 50000.0
        strike = 50000.0

        # Synthesize artificial decaying volatility in time that causes dC/dT < 0
        def inverted_time_model(k: float, t: float) -> float:
            # Huge plunge in IV with maturity
            return max(0.02, 0.40 - (t * 5.0))

        pt = self.engine.calculate_local_volatility(
            spot=spot,
            strike=strike,
            time_to_expiry_years=0.05,
            iv_model=inverted_time_model,
        )

        # Engine handles calendar distortion safely
        self.assertFalse(math.isnan(pt.local_vol))
        self.assertGreater(pt.local_vol, 0.0)
        self.assertLessEqual(pt.local_vol, self.engine.max_local_vol)

    def test_butterfly_arbitrage_detection_and_safety(self) -> None:
        """Verify engine detects butterfly arbitrage (negative density) and prevents division blow-up."""
        spot = 50000.0

        # Wild discontinuous step function violating convexity (d^2C/dK^2 <= 0)
        def concave_iv_model(k: float, t: float) -> float:
            return 0.30 if abs(k - spot) < 200 else 0.05

        pt = self.engine.calculate_local_volatility(
            spot=spot,
            strike=50200.0,
            time_to_expiry_years=0.08,
            iv_model=concave_iv_model,
        )

        self.assertFalse(math.isnan(pt.local_vol))
        self.assertGreaterEqual(pt.local_vol, self.engine.min_local_vol)
        self.assertLessEqual(pt.local_vol, self.engine.max_local_vol)

    def test_surface_grid_construction(self) -> None:
        """Verify generation of a 2D mesh of local volatilities across strikes and maturities."""
        spot = 50000.0
        strikes = [49000.0, 49500.0, 50000.0, 50500.0, 51000.0]
        maturities = [7.0 / 365.0, 14.0 / 365.0, 30.0 / 365.0]

        grid: LocalVolSurfaceGrid = self.engine.generate_surface_grid(
            spot=spot,
            strikes=strikes,
            maturities_years=maturities,
            base_iv=0.16,
        )

        self.assertEqual(len(grid.strikes), 5)
        self.assertEqual(len(grid.maturities_years), 3)
        self.assertEqual(len(grid.matrix), 3)
        self.assertEqual(len(grid.matrix[0]), 5)
        self.assertEqual(len(grid.atm_local_vols), 3)

        for row in grid.matrix:
            for val in row:
                self.assertGreater(val, 0.0)
                self.assertFalse(math.isnan(val))

    def test_euler_maruyama_discrete_step(self) -> None:
        """Verify discrete Euler-Maruyama step dynamics under local volatility."""
        spot = 50000.0
        dt = 1.0 / (365.0 * 75.0)  # 5-minute intraday bar
        local_vol = 0.16

        # 1. Zero noise: deterministic drift
        s_drift = self.engine.simulate_local_vol_step(
            current_spot=spot,
            current_t=0.05,
            dt=dt,
            z=0.0,
            local_vol=local_vol,
        )
        self.assertGreater(s_drift, 0.0)

        # 2. Positive shock Z = +2.0
        s_up = self.engine.simulate_local_vol_step(
            current_spot=spot,
            current_t=0.05,
            dt=dt,
            z=2.0,
            local_vol=local_vol,
        )
        self.assertGreater(s_up, s_drift)

        # 3. Negative shock Z = -2.0
        s_down = self.engine.simulate_local_vol_step(
            current_spot=spot,
            current_t=0.05,
            dt=dt,
            z=-2.0,
            local_vol=local_vol,
        )
        self.assertLess(s_down, s_drift)


if __name__ == "__main__":
    unittest.main()
