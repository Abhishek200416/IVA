"""Unit test battery for SABR & SVI Arbitrage-Free Implied Volatility Surface Calibrator.

Wave 35 Verification Suite (TASK-BN-45):
Validates:
1. Hagan et al. (2002) SABR analytical volatility evaluation and negative spot-vol skew.
2. Parameter boundary validation (alpha > 0, 0 <= beta <= 1, |rho| < 1).
3. Gatheral (2004) Raw SVI total variance and implied volatility inversion.
4. Butterfly arbitrage verification via Durrleman risk-neutral density g(k) >= 0.
5. Calendar spread monotonicity audit across multi-week expiry slices.
6. SABR ATM alpha calibration inversion.
"""

from __future__ import annotations

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.sabr_svi_calibrator import (
    ArbitrageAuditResult,
    FrictionAwareKellyResult,
    LIVE_ORDER_DISPATCH_ENABLED,
    ModelUncertaintySkewResult,
    SABRParameters,
    SSVIParameters,
    SVIParameters,
    SabrSviCalibrator,
    VolatilityModelType,
)


class TestOmegaSabrSviCalibrator(unittest.TestCase):
    """Test suite for Wave 35 SABR & SVI Volatility Calibrator."""

    def setUp(self) -> None:
        self.calibrator = SabrSviCalibrator()
        # Typical Bank Nifty parameters: Forward = 51,000, ATM Vol = ~16%
        self.forward = 51000.0
        self.t_near = 7.0 / 365.0   # 1 week to expiry
        self.t_far = 30.0 / 365.0   # ~1 month to expiry

    def test_sabr_atm_and_otm_volatility_skew(self) -> None:
        """Verify SABR ATM vol and canonical negative equity index skew (OTM Puts > OTM Calls)."""
        params = SABRParameters(
            alpha=0.16,
            beta=1.0,         # Lognormal SABR
            rho=-0.35,        # Negative spot-vol correlation -> downward skew
            nu=0.45,          # Vol-of-vol
        )

        vol_atm = self.calibrator.calculate_sabr_volatility(
            forward=self.forward, strike=self.forward, expiry_years=self.t_near, params=params
        )
        self.assertAlmostEqual(vol_atm, 0.16, delta=0.015)

        # 95% Moneyness (OTM Put) vs 105% Moneyness (OTM Call)
        vol_put_otm = self.calibrator.calculate_sabr_volatility(
            forward=self.forward, strike=self.forward * 0.95, expiry_years=self.t_near, params=params
        )
        vol_call_otm = self.calibrator.calculate_sabr_volatility(
            forward=self.forward, strike=self.forward * 1.05, expiry_years=self.t_near, params=params
        )

        # With negative rho, OTM Put volatility should be higher than OTM Call volatility
        self.assertGreater(vol_put_otm, vol_atm)
        self.assertGreater(vol_atm, vol_call_otm)

    def test_sabr_parameter_validation(self) -> None:
        """Verify strict error handling for out-of-bound SABR parameters."""
        with self.assertRaises(ValueError):
            # Alpha non-positive
            SABRParameters(alpha=-0.1, beta=1.0, rho=0.0, nu=0.2).validate()

        with self.assertRaises(ValueError):
            # Beta > 1.0
            SABRParameters(alpha=0.2, beta=1.5, rho=0.0, nu=0.2).validate()

        with self.assertRaises(ValueError):
            # |Rho| >= 1.0
            SABRParameters(alpha=0.2, beta=0.8, rho=1.0, nu=0.2).validate()

    def test_svi_total_variance_and_implied_vol(self) -> None:
        """Verify Gatheral Raw SVI total variance and Black volatility derivation."""
        svi_params = SVIParameters(
            a=0.01,
            b=0.08,
            rho=-0.40,
            m=0.0,
            sigma=0.05,
        )

        # At k = 0 (ATM)
        w_atm = self.calibrator.calculate_svi_total_variance(0.0, svi_params)
        expected_w = 0.01 + 0.08 * (0.0 + 0.05)  # 0.01 + 0.004 = 0.014
        self.assertAlmostEqual(w_atm, expected_w, places=5)

        # Implied vol = sqrt(w / T)
        iv_atm = self.calibrator.calculate_svi_implied_volatility(
            forward=self.forward, strike=self.forward, expiry_years=self.t_near, params=svi_params
        )
        expected_iv = math.sqrt(expected_w / self.t_near)
        self.assertAlmostEqual(iv_atm, expected_iv, places=4)

    def test_butterfly_arbitrage_durrleman_condition(self) -> None:
        """Verify Durrleman risk-neutral density g(k) >= 0 prevents butterfly arbitrage."""
        # Clean, well-behaved SVI slice
        clean_svi = SVIParameters(
            a=0.02,
            b=0.05,
            rho=-0.25,
            m=0.01,
            sigma=0.06,
        )
        k_grid = [round(x * 0.02, 3) for x in range(-10, 11)]  # [-0.20 to +0.20]

        has_arb, min_dens, violations = self.calibrator.check_svi_butterfly_arbitrage(
            clean_svi, k_grid
        )
        self.assertFalse(has_arb)
        self.assertGreater(min_dens, 0.0)
        self.assertEqual(len(violations), 0)

    def test_calendar_spread_monotonicity_audit(self) -> None:
        """Verify surface audit across near and far maturities."""
        k_grid = [round(x * 0.03, 3) for x in range(-6, 7)]

        # Near slice (lower total variance)
        svi_near = SVIParameters(a=0.005, b=0.04, rho=-0.3, m=0.0, sigma=0.04)
        # Far slice (higher total variance across all strikes)
        svi_far = SVIParameters(a=0.025, b=0.05, rho=-0.3, m=0.0, sigma=0.05)

        report = self.calibrator.audit_surface_arbitrage(
            svi_near=svi_near,
            svi_far=svi_far,
            t_near=self.t_near,
            t_far=self.t_far,
            k_grid=k_grid,
        )

        self.assertFalse(report.has_calendar_arbitrage)
        self.assertFalse(report.has_butterfly_arbitrage)
        self.assertTrue(report.is_arbitrage_free)
        self.assertLess(report.max_wing_slope, 2.0)

        # Invert slices to simulate calendar arbitrage violation
        inverted_report = self.calibrator.audit_surface_arbitrage(
            svi_near=svi_far,  # near has higher variance
            svi_far=svi_near,  # far has lower variance
            t_near=self.t_near,
            t_far=self.t_far,
            k_grid=k_grid,
        )
        self.assertTrue(inverted_report.has_calendar_arbitrage)
        self.assertFalse(inverted_report.is_arbitrage_free)

    def test_sabr_atm_calibration_inversion(self) -> None:
        """Verify that fit_sabr_atm accurately matches target market ATM volatility."""
        target_atm_vol = 0.175
        calibrated_params = self.calibrator.fit_sabr_atm(
            forward=self.forward,
            atm_vol=target_atm_vol,
            expiry_years=self.t_near,
            beta=1.0,
            rho=-0.30,
            nu=0.40,
        )

        reproduced_vol = self.calibrator.calculate_sabr_volatility(
            forward=self.forward,
            strike=self.forward,
            expiry_years=self.t_near,
            params=calibrated_params,
        )

        self.assertAlmostEqual(reproduced_vol, target_atm_vol, places=4)

    def test_svi_parameter_constraints_strict_validation(self) -> None:
        """Verify strict enforcement of SVI parameter constraints: b >= 0, |rho| < 1, sigma > 0, min_var >= 0."""
        # 1. Valid SVI parameters
        valid_svi = SVIParameters(a=0.04, b=0.10, rho=-0.35, m=0.0, sigma=0.08)
        valid_svi.validate()
        self.assertGreaterEqual(valid_svi.b, 0.0)
        self.assertLess(abs(valid_svi.rho), 1.0)
        self.assertGreater(valid_svi.sigma, 0.0)
        self.assertGreaterEqual(valid_svi.min_variance, 0.0)

        # 2. b < 0 violation (negative wing slope)
        with self.assertRaises(ValueError) as ctx:
            SVIParameters(a=0.04, b=-0.05, rho=-0.35, m=0.0, sigma=0.08).validate()
        self.assertIn("SVI b must be non-negative", str(ctx.exception))

        # 3. |rho| >= 1.0 violation (correlation boundary)
        with self.assertRaises(ValueError) as ctx:
            SVIParameters(a=0.04, b=0.10, rho=1.0, m=0.0, sigma=0.08).validate()
        self.assertIn("SVI rho must be strictly in (-1.0, 1.0)", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            SVIParameters(a=0.04, b=0.10, rho=-1.02, m=0.0, sigma=0.08).validate()
        self.assertIn("SVI rho must be strictly in (-1.0, 1.0)", str(ctx.exception))

        # 4. sigma <= 0.0 violation (vertex smoothness non-positive)
        with self.assertRaises(ValueError) as ctx:
            SVIParameters(a=0.04, b=0.10, rho=-0.35, m=0.0, sigma=0.0).validate()
        self.assertIn("SVI sigma must be strictly positive", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            SVIParameters(a=0.04, b=0.10, rho=-0.35, m=0.0, sigma=-0.05).validate()
        self.assertIn("SVI sigma must be strictly positive", str(ctx.exception))

        # 5. a + b * sigma * sqrt(1 - rho^2) < 0 violation (negative total variance)
        # min_var = -0.05 + 0.05 * 0.05 * sqrt(1 - 0) = -0.05 + 0.0025 = -0.0475 < 0
        with self.assertRaises(ValueError) as ctx:
            SVIParameters(a=-0.05, b=0.05, rho=0.0, m=0.0, sigma=0.05).validate()
        self.assertIn("positive variance condition", str(ctx.exception))

    def test_ssvi_to_raw_svi_mapping_and_arbitrage_guarantees(self) -> None:
        """Verify SSVI to Raw-SVI closed-form mapping identically satisfies positive variance and butterfly bounds."""
        ssvi = SSVIParameters(theta=0.045, rho=-0.30, eta=0.40, gamma=0.5)
        ssvi.validate()

        raw_svi = self.calibrator.ssvi_to_raw_svi(ssvi, enforce_butterfly_free=True)
        raw_svi.validate()

        # Closed-form identity checks:
        # a = (theta / 2) * (1 - rho^2)
        expected_a = (0.045 / 2.0) * (1.0 - (-0.30) ** 2)
        self.assertAlmostEqual(raw_svi.a, expected_a, places=5)

        # Minimum variance proof: min_var = theta * (1 - rho^2)
        expected_min_var = 0.045 * (1.0 - (-0.30) ** 2)
        self.assertAlmostEqual(raw_svi.min_variance, expected_min_var, places=5)
        self.assertGreater(raw_svi.min_variance, 0.0)

        # Butterfly density g(k) >= 0 across strike grid
        k_grid = [round(x * 0.02, 3) for x in range(-15, 16)]
        has_arb, min_dens, violations = self.calibrator.check_svi_butterfly_arbitrage(raw_svi, k_grid)
        self.assertFalse(has_arb)
        self.assertGreater(min_dens, 0.0)
        self.assertEqual(len(violations), 0)

    def test_model_uncertainty_aware_skew_z_score_formulation(self) -> None:
        """Verify z_t = (IV_market - IV_model) / sqrt(s_quote^2 + s_model^2 + s_parameter^2)."""
        # Case 1: Statistically significant overpriced Put (Z >= +2.0)
        # IV_mkt = 22%, IV_model = 16%, diff = +6%
        # s_quote = 1.0%, s_model = 1.5%, s_param = 1.0% -> s_total = sqrt(1e-4 + 2.25e-4 + 1e-4) = sqrt(4.25e-4) = 0.0206155
        res_over = self.calibrator.calculate_model_uncertainty_skew_z_score(
            iv_market=0.22,
            iv_model=0.16,
            s_quote=0.010,
            s_model=0.015,
            s_parameter=0.010,
            significance_threshold=2.0,
        )
        expected_z_over = (0.22 - 0.16) / math.sqrt(0.010 ** 2 + 0.015 ** 2 + 0.010 ** 2)
        self.assertAlmostEqual(res_over.z_score, expected_z_over, places=3)
        self.assertTrue(res_over.is_statistically_significant)
        self.assertEqual(res_over.regime, "OVERPRICED")
        self.assertGreaterEqual(res_over.z_score, 2.0)

        # Case 2: Statistically significant underpriced Put (Z <= -2.0)
        res_under = self.calibrator.calculate_model_uncertainty_skew_z_score(
            iv_market=0.10,
            iv_model=0.16,
            s_quote=0.010,
            s_model=0.015,
            s_parameter=0.010,
            significance_threshold=2.0,
        )
        self.assertTrue(res_under.is_statistically_significant)
        self.assertEqual(res_under.regime, "UNDERPRICED")
        self.assertLessEqual(res_under.z_score, -2.0)

        # Case 3: Fair Value Equilibrium (diff within composite uncertainty envelope)
        res_fair = self.calibrator.calculate_model_uncertainty_skew_z_score(
            iv_market=0.165,
            iv_model=0.160,
            s_quote=0.010,
            s_model=0.015,
            s_parameter=0.010,
            significance_threshold=2.0,
        )
        self.assertFalse(res_fair.is_statistically_significant)
        self.assertEqual(res_fair.regime, "FAIR_VALUE")
        self.assertLess(abs(res_fair.z_score), 2.0)

        # Case 4: High quote uncertainty / wide bid-ask spread suppresses false alarm
        res_wide_spread = self.calibrator.calculate_model_uncertainty_skew_z_score(
            iv_market=0.19,
            iv_model=0.16,
            s_quote=0.035,   # Wide 3.5% bid-ask spread noise
            s_model=0.015,
            s_parameter=0.010,
            significance_threshold=2.0,
        )
        # s_total = sqrt(0.035^2 + 0.015^2 + 0.01^2) = sqrt(0.001225 + 0.000225 + 0.0001) = 0.03937
        # z = 0.03 / 0.03937 = 0.76 < 2.0
        self.assertFalse(res_wide_spread.is_statistically_significant)
        self.assertEqual(res_wide_spread.regime, "FAIR_VALUE")

        # Case 5: Error handling
        with self.assertRaises(ValueError):
            self.calibrator.calculate_model_uncertainty_skew_z_score(0.18, 0.16, -0.01, 0.01, 0.01)
        with self.assertRaises(ValueError):
            self.calibrator.calculate_model_uncertainty_skew_z_score(0.18, 0.16, 0.0, 0.0, 0.0)

    def test_friction_aware_bayesian_kelly_allocation_with_statutory_deductions(self) -> None:
        """Verify Bayesian-Kelly allocation f* under downside semi-variance with exact Indian statutory deductions."""
        equity = 1_000_000.0        # INR 10 Lakhs capital
        margin_lot = 60_000.0       # Margin per lot
        lot_size = 15               # Bank Nifty lot size
        entry_prem = 250.0          # BUY entry premium
        expected_exit = 310.0       # SELL expected exit premium (+60 pts edge = INR 900 gross per lot)

        # Downside return series: historical losses
        downside_returns = [-0.04, -0.06, 0.08, -0.05, 0.12, -0.03, -0.07]

        alloc = self.calibrator.calculate_friction_aware_kelly_allocation(
            equity_inr=equity,
            margin_per_lot_inr=margin_lot,
            lot_size_contracts=lot_size,
            entry_premium=entry_prem,
            expected_exit_premium=expected_exit,
            downside_returns=downside_returns,
            kappa=0.25,                    # Quarter Kelly
            max_allocation_fraction=0.40,  # 40% cap
            live_order_dispatch_enabled=False,
        )

        self.assertTrue(alloc.is_actionable)
        self.assertEqual(alloc.gross_edge_pts, 60.0)
        self.assertGreater(alloc.statutory_friction_inr, 0.0)
        self.assertGreater(alloc.net_return_pct, 0.0)
        self.assertGreater(alloc.downside_semi_variance, 0.0)
        self.assertGreater(alloc.fractional_kelly_fraction, 0.0)
        self.assertLessEqual(alloc.effective_allocation_fraction, 0.40)
        self.assertGreater(alloc.quantized_lots, 0)
        self.assertEqual(alloc.quantized_contracts, alloc.quantized_lots * lot_size)
        self.assertAlmostEqual(alloc.margin_utilized_inr + alloc.cash_buffer_remaining_inr, equity, delta=1.0)
        self.assertFalse(alloc.live_order_dispatch_enabled)
        self.assertIsNone(alloc.fail_closed_reason)

    def test_friction_exceeds_edge_gating_fail_closed(self) -> None:
        """Verify trade is gated (0 allocation, fail-closed) when gross edge is eaten by statutory friction."""
        alloc = self.calibrator.calculate_friction_aware_kelly_allocation(
            equity_inr=500_000.0,
            margin_per_lot_inr=50_000.0,
            lot_size_contracts=15,
            entry_premium=100.0,
            expected_exit_premium=100.50,  # 0.50 pt gross edge = INR 7.50 gross, friction is ~INR 50
            downside_semi_variance=0.0025,
            live_order_dispatch_enabled=False,
        )

        self.assertFalse(alloc.is_actionable)
        self.assertEqual(alloc.quantized_lots, 0)
        self.assertEqual(alloc.quantized_contracts, 0)
        self.assertEqual(alloc.effective_allocation_fraction, 0.0)
        self.assertEqual(alloc.allocated_capital_inr, 0.0)
        self.assertIsNotNone(alloc.fail_closed_reason)
        self.assertIn("Negative or zero net edge", alloc.fail_closed_reason)

    def test_fail_closed_live_order_dispatch_safety_invariant(self) -> None:
        """Verify strict adherence to fail-closed safety invariant: LIVE_ORDER_DISPATCH_ENABLED = False."""
        from agents.AGI_1_7.engine.agi17.finance.sabr_svi_calibrator import LIVE_ORDER_DISPATCH_ENABLED

        # System module safety lock must be permanently False
        self.assertFalse(LIVE_ORDER_DISPATCH_ENABLED)

        # Attempting to request live dispatch in position sizing fails closed immediately
        alloc = self.calibrator.calculate_friction_aware_kelly_allocation(
            equity_inr=1_000_000.0,
            margin_per_lot_inr=60_000.0,
            lot_size_contracts=15,
            entry_premium=250.0,
            expected_exit_premium=350.0,
            downside_semi_variance=0.0025,
            live_order_dispatch_enabled=True,  # Prohibited live dispatch flag
        )

        self.assertFalse(alloc.is_actionable)
        self.assertEqual(alloc.quantized_lots, 0)
        self.assertEqual(alloc.quantized_contracts, 0)
        self.assertIn("LIVE_ORDER_DISPATCH_ENABLED safety invariant violated", alloc.fail_closed_reason)


if __name__ == "__main__":
    unittest.main()
