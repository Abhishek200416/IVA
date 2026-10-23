"""Acceptance tests for Slippage Calibration Engine and Volatility Skew Arbitrage Engine.

TASK-BN-18 & TASK-BN-19:
Covers:
1. Single-leg Square-Root Market Impact monotonicity, tick alignment, and BUY/SELL fills.
2. Market regime liquidity multiplier (India VIX escalation, opening range, expiry afternoon).
3. Multi-leg strategy execution evaluation (Bull Call Spread, Short Strangle) and bps budget gating.
4. Empirical constant Y calibration via OLS through origin from observed execution traces.
5. Volatility Smile metrics extraction (Risk Reversal, Butterfly curvature, Skew Z-score).
6. Overpriced Put Skew (Z >= +2.0) delta-hedged statistical arbitrage trade generation.
7. Underpriced Put Skew (Z <= -2.0) delta-hedged statistical arbitrage trade generation.
8. Fair-value equilibrium band gating (NO_TRADE when |Z| < 2.0).
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide
from agents.AGI_1_7.engine.agi17.finance.slippage_calibration import (
    MultiLegSlippageReport,
    SlippageCalibrationEngine,
    SlippageImpactReport,
    SquareRootImpactParams,
)
from agents.AGI_1_7.engine.agi17.finance.volatility_skew_arbitrage import (
    SkewArbitrageAction,
    SkewArbitrageTradeProposal,
    SkewMetricsSnapshot,
    SkewRegime,
    VolatilitySkewArbitrageEngine,
)


class TestOmegaSlippageAndSkewArbitrage(unittest.TestCase):
    """Test suite for market impact slippage calibration and volatility smile skew arbitrage."""

    def test_01_single_leg_square_root_impact_monotonicity_and_ticks(self) -> None:
        """Verifies market impact scales monotonically with order size and aligns with 0.05 ticks."""
        mid_price = 250.0  # Option premium 250 INR

        # Compare 1 lot (15 units) vs 10 lots (150 units) vs 50 lots (750 units)
        rep_1 = SlippageCalibrationEngine.calculate_single_leg_impact(
            symbol="BANKNIFTY-50000-CE",
            side=OrderSide.BUY,
            order_units=15,
            mid_price=mid_price,
            quoted_spread=0.10,
        )
        rep_10 = SlippageCalibrationEngine.calculate_single_leg_impact(
            symbol="BANKNIFTY-50000-CE",
            side=OrderSide.BUY,
            order_units=150,
            mid_price=mid_price,
            quoted_spread=0.10,
        )
        rep_50 = SlippageCalibrationEngine.calculate_single_leg_impact(
            symbol="BANKNIFTY-50000-CE",
            side=OrderSide.BUY,
            order_units=750,
            mid_price=mid_price,
            quoted_spread=0.10,
        )

        # Monotonicity checks
        self.assertLess(rep_1.permanent_impact_pts, rep_10.permanent_impact_pts)
        self.assertLess(rep_10.permanent_impact_pts, rep_50.permanent_impact_pts)
        self.assertLess(rep_1.total_cost_inr, rep_10.total_cost_inr)
        self.assertLess(rep_10.total_cost_inr, rep_50.total_cost_inr)

        # Tick alignment check (must be a valid multiple of 0.05)
        for r in [rep_1, rep_10, rep_50]:
            remainder = round(r.total_slippage_pts % 0.05, 4)
            self.assertTrue(remainder == 0.0 or remainder == 0.05)
            # Expected fill for BUY must be > mid_price
            self.assertGreater(r.expected_fill_price, mid_price)

        # For SELL side, expected fill must be < mid_price
        rep_sell = SlippageCalibrationEngine.calculate_single_leg_impact(
            symbol="BANKNIFTY-50000-PE",
            side=OrderSide.SELL,
            order_units=150,
            mid_price=mid_price,
            quoted_spread=0.10,
        )
        self.assertLess(rep_sell.expected_fill_price, mid_price)
        self.assertEqual(rep_sell.total_slippage_pts, rep_10.total_slippage_pts)

    def test_02_regime_multiplier_vix_and_session_events(self) -> None:
        """Verifies liquidity stress multipliers expand under elevated VIX, open, and expiry."""
        mult_calm = SlippageCalibrationEngine.calculate_regime_multiplier(vix_level=13.0)
        mult_elevated = SlippageCalibrationEngine.calculate_regime_multiplier(vix_level=23.0)
        mult_open = SlippageCalibrationEngine.calculate_regime_multiplier(vix_level=13.0, is_opening_range=True)
        mult_expiry = SlippageCalibrationEngine.calculate_regime_multiplier(vix_level=13.0, is_expiry_close=True)

        self.assertEqual(mult_calm, 1.0)
        self.assertGreater(mult_elevated, 1.0)  # VIX 23 -> 1.0 + (23-15)*0.05 = 1.40
        self.assertAlmostEqual(mult_elevated, 1.40, places=2)
        self.assertEqual(mult_open, 1.35)
        self.assertEqual(mult_expiry, 1.50)

    def test_03_multi_leg_strategy_slippage_and_budget_gating(self) -> None:
        """Verifies multi-leg strategy execution aggregation and pre-trade bps limits."""
        # Bull Call Spread: Buy ATM 50000 CE (200 INR), Sell OTM 50300 CE (90 INR)
        spread_legs = [
            {"symbol": "BANKNIFTY-50000-CE", "side": OrderSide.BUY, "order_units": 30, "mid_price": 200.0, "quoted_spread": 0.10},
            {"symbol": "BANKNIFTY-50300-CE", "side": OrderSide.SELL, "order_units": 30, "mid_price": 90.0, "quoted_spread": 0.15},
        ]

        report = SlippageCalibrationEngine.calculate_multi_leg_impact(
            strategy_name="BULL_CALL_SPREAD_2L",
            legs_specs=spread_legs,
            max_allowed_bps=50.0,
        )

        self.assertEqual(len(report.legs), 2)
        self.assertEqual(report.total_units, 60)
        self.assertEqual(report.total_lots, 4)  # 2 lots each
        self.assertGreater(report.total_slippage_cost_inr, 0.0)
        self.assertTrue(report.is_all_acceptable)
        self.assertIn("APPROVED", report.summary_verdict)

        # Test rejection under an unrealistically tight 1.0 bps budget
        strict_report = SlippageCalibrationEngine.calculate_multi_leg_impact(
            strategy_name="BULL_CALL_SPREAD_STRICT",
            legs_specs=spread_legs,
            max_allowed_bps=1.0,
        )
        self.assertFalse(strict_report.is_all_acceptable)
        self.assertIn("REJECTED_EXCESSIVE_SLIPPAGE", strict_report.summary_verdict)

    def test_04_empirical_y_constant_calibration(self) -> None:
        """Verifies calibration of dimensionless Y constant from observed execution traces."""
        # Synthetic observations with known theoretical Y = 0.65
        mid_prices = [100.0, 150.0, 200.0, 250.0, 300.0]
        order_units = [30, 60, 90, 150, 300]
        interval_vols = [25000, 25000, 30000, 35000, 40000]
        vols = [0.15, 0.16, 0.18, 0.15, 0.17]
        spreads = [0.10, 0.10, 0.15, 0.20, 0.25]

        # Synthesize observed slippages based on Y = 0.65
        obs_slippages = []
        for mid, q, v, vol, spr in zip(mid_prices, order_units, interval_vols, vols, spreads):
            half = spr / 2.0
            sigma_int = vol / ((252.0 * 75.0) ** 0.5)
            part = (q / v) ** 0.5
            perm = 0.65 * sigma_int * part * mid
            obs_slippages.append(half + perm)

        calibrated_y = SlippageCalibrationEngine.calibrate_empirical_constant(
            observed_slippages_pts=obs_slippages,
            mid_prices=mid_prices,
            order_units=order_units,
            interval_volumes=interval_vols,
            annualized_vols=vols,
            quoted_spreads=spreads,
        )

        self.assertAlmostEqual(calibrated_y, 0.65, places=2)

    def test_05_volatility_skew_metrics_extraction(self) -> None:
        """Verifies extraction of Risk Reversal, Butterfly curvature, and Skew Z-Score."""
        spot = 50000.0
        atm_strike = 50000.0
        atm_iv = 0.140  # 14.0%
        call_25d_strike = 50600.0
        call_25d_iv = 0.130  # 13.0%
        put_25d_strike = 49400.0
        put_25d_iv = 0.165  # 16.5% (Put IV > Call IV by 3.5%)

        metrics = VolatilitySkewArbitrageEngine.calculate_skew_metrics(
            spot_price=spot,
            atm_strike=atm_strike,
            atm_iv=atm_iv,
            call_25d_strike=call_25d_strike,
            call_25d_iv=call_25d_iv,
            put_25d_strike=put_25d_strike,
            put_25d_iv=put_25d_iv,
            historical_skew_mean=0.035,
            historical_skew_std=0.008,
        )

        self.assertAlmostEqual(metrics.risk_reversal_pts, -0.035, places=4)  # Call - Put = -3.5%
        self.assertAlmostEqual(metrics.put_skew_pts, 0.035, places=4)        # Put - Call = +3.5%
        self.assertAlmostEqual(metrics.butterfly_pts, 0.0075, places=4)      # (13+16.5)/2 - 14 = +0.75%
        self.assertEqual(metrics.skew_z_score, 0.0)                         # Exactly at historical mean
        self.assertEqual(metrics.regime, SkewRegime.FAIR_VALUE_EQUILIBRIUM)

    def test_06_overpriced_put_skew_arbitrage_generation(self) -> None:
        """Verifies trade generation when Put Skew is abnormally elevated (Z >= +2.0)."""
        # Put IV = 19.5%, Call IV = 13.0% -> Skew = 6.5% vs Mean 3.5% (Z = (0.065 - 0.035)/0.008 = +3.75)
        metrics = VolatilitySkewArbitrageEngine.calculate_skew_metrics(
            spot_price=50000.0,
            atm_strike=50000.0,
            atm_iv=0.150,
            call_25d_strike=50600.0,
            call_25d_iv=0.130,
            put_25d_strike=49400.0,
            put_25d_iv=0.195,
            historical_skew_mean=0.035,
            historical_skew_std=0.008,
        )

        self.assertEqual(metrics.regime, SkewRegime.OVERPRICED_PUT_SKEW)
        self.assertGreaterEqual(metrics.skew_z_score, 2.0)

        proposal = VolatilitySkewArbitrageEngine.evaluate_arbitrage_opportunity(
            metrics=metrics,
            dte=14.0,
            lots=2,
            statutory_friction_per_lot_inr=120.0,
        )

        self.assertEqual(proposal.action, SkewArbitrageAction.SELL_PUT_BUY_CALL_HEDGE)
        self.assertTrue(proposal.is_actionable)
        self.assertGreater(proposal.net_expected_edge_inr, 1000.0)
        self.assertEqual(proposal.net_delta, 0.0)  # Pure delta-neutral skew trade
        self.assertEqual(len(proposal.legs), 2)

        # Leg checks: Sell 25D PE, Buy 25D CE
        sell_pe_leg = next(leg for leg in proposal.legs if leg["side"] == OrderSide.SELL)
        buy_ce_leg = next(leg for leg in proposal.legs if leg["side"] == OrderSide.BUY)
        self.assertEqual(sell_pe_leg["strike"], 49400.0)
        self.assertEqual(buy_ce_leg["strike"], 50600.0)

        # Delta hedge: Short underlying future to neutralize +0.50 synthetic delta
        self.assertEqual(proposal.delta_hedge_leg["side"], OrderSide.SELL)
        self.assertEqual(proposal.delta_hedge_leg["delta"], -0.50)

    def test_07_underpriced_put_skew_arbitrage_generation(self) -> None:
        """Verifies trade generation when Put Skew is abnormally flat (Z <= -2.0)."""
        # Put IV = 14.5%, Call IV = 13.5% -> Skew = 1.0% vs Mean 3.5% (Z = (0.010 - 0.035)/0.008 = -3.125)
        metrics = VolatilitySkewArbitrageEngine.calculate_skew_metrics(
            spot_price=50000.0,
            atm_strike=50000.0,
            atm_iv=0.140,
            call_25d_strike=50600.0,
            call_25d_iv=0.135,
            put_25d_strike=49400.0,
            put_25d_iv=0.145,
            historical_skew_mean=0.035,
            historical_skew_std=0.008,
        )

        self.assertEqual(metrics.regime, SkewRegime.UNDERPRICED_PUT_SKEW)
        self.assertLessEqual(metrics.skew_z_score, -2.0)

        proposal = VolatilitySkewArbitrageEngine.evaluate_arbitrage_opportunity(
            metrics=metrics,
            dte=14.0,
            lots=2,
            statutory_friction_per_lot_inr=120.0,
        )

        self.assertEqual(proposal.action, SkewArbitrageAction.BUY_PUT_SELL_CALL_HEDGE)
        self.assertTrue(proposal.is_actionable)
        self.assertGreater(proposal.net_expected_edge_inr, 800.0)
        self.assertEqual(proposal.net_delta, 0.0)

        # Leg checks: Buy 25D PE, Sell 25D CE
        buy_pe_leg = next(leg for leg in proposal.legs if leg["side"] == OrderSide.BUY)
        sell_ce_leg = next(leg for leg in proposal.legs if leg["side"] == OrderSide.SELL)
        self.assertEqual(buy_pe_leg["strike"], 49400.0)
        self.assertEqual(sell_ce_leg["strike"], 50600.0)

        # Delta hedge: Long underlying future to neutralize -0.50 synthetic delta
        self.assertEqual(proposal.delta_hedge_leg["side"], OrderSide.BUY)
        self.assertEqual(proposal.delta_hedge_leg["delta"], 0.50)

    def test_08_fair_value_skew_gating_no_trade(self) -> None:
        """Verifies fair value skew produces NO_TRADE and preserves capital."""
        metrics = VolatilitySkewArbitrageEngine.calculate_skew_metrics(
            spot_price=50000.0,
            atm_strike=50000.0,
            atm_iv=0.140,
            call_25d_strike=50600.0,
            call_25d_iv=0.130,
            put_25d_strike=49400.0,
            put_25d_iv=0.165,
            historical_skew_mean=0.035,
            historical_skew_std=0.008,
        )

        proposal = VolatilitySkewArbitrageEngine.evaluate_arbitrage_opportunity(metrics=metrics)

        self.assertEqual(proposal.action, SkewArbitrageAction.NO_TRADE)
        self.assertFalse(proposal.is_actionable)
        self.assertEqual(proposal.net_expected_edge_inr, 0.0)
        self.assertEqual(len(proposal.legs), 0)
        self.assertIn("No statistical skew mispricing detected", proposal.rationale)


if __name__ == "__main__":
    unittest.main()
