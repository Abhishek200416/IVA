"""AGI 1.7 Acceptance Tests for Portfolio Greeks Aggregation, Delta Hedging, and Macro Stress Testing.

Covers:
1. PortfolioGreeksRiskEngine:
   - Multi-leg Option Greeks aggregation (Delta, Gamma, Vega, Theta).
   - Delta neutrality evaluation and lot-aligned hedge recommendation.
2. BankNiftyStressTester:
   - Parametric Delta-Gamma 1-day 95% & 99% Value-at-Risk (VaR) and CVaR.
   - Historical Macro Scenario Stress Testing (COVID-19 Crash, Budget Day Shock, Election Rally Vol Crush).
   - Capital preservation and resilience rating determination.
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OptionType
from agents.AGI_1_7.engine.agi17.finance.portfolio_risk import (
    BankNiftyStressTester,
    PortfolioGreeksRiskEngine,
    PortfolioGreeksSummary,
    PositionRiskItem,
    StressTestReport,
)


class TestOmegaPortfolioRiskAndStress(unittest.TestCase):
    """Test suite for portfolio Greeks aggregation, delta hedging, and stress testing."""

    def test_01_portfolio_greeks_aggregation_strangle(self) -> None:
        """Verifies Greeks aggregation for a Short Strangle (Net Delta near 0, Negative Vega & Gamma)."""
        spot = 50000.0
        time_to_expiry = 7.0 / 365.0  # 1 week to expiry
        vol = 0.16

        # Short 30 units 50500 CE, Short 30 units 49500 PE
        short_ce = PositionRiskItem(
            symbol="BANKNIFTY26OCT50500CE",
            units=-30,
            option_type=OptionType.CE,
            strike=50500.0,
            spot=spot,
            time_to_expiry_years=time_to_expiry,
            volatility=vol,
        )
        short_pe = PositionRiskItem(
            symbol="BANKNIFTY26OCT49500PE",
            units=-30,
            option_type=OptionType.PE,
            strike=49500.0,
            spot=spot,
            time_to_expiry_years=time_to_expiry,
            volatility=vol,
        )

        summary = PortfolioGreeksRiskEngine.evaluate_portfolio([short_ce, short_pe], spot_price=spot)

        self.assertIsInstance(summary, PortfolioGreeksSummary)
        self.assertEqual(summary.total_positions, 2)
        self.assertEqual(summary.net_units, -60)
        # Symmetrical Strangle has near zero delta
        self.assertLess(abs(summary.net_delta), 10.0)
        self.assertTrue(summary.is_delta_neutral)
        self.assertEqual(summary.recommended_hedge_action, "NO_HEDGE_REQUIRED")

        # Short options have negative gamma and vega, but positive theta (decay harvest)
        self.assertLess(summary.net_gamma, 0.0)
        self.assertLess(summary.net_vega, 0.0)
        self.assertGreater(summary.net_theta, 0.0)

    def test_02_delta_imbalance_triggers_lot_aligned_hedge(self) -> None:
        """Verifies directional imbalance recommends correct lot-aligned hedge order."""
        spot = 50000.0
        time_to_expiry = 14.0 / 365.0
        vol = 0.18

        # Large Long 45 units ATM Call -> Delta ~ 45 * 0.50 = +22.5
        long_ce = PositionRiskItem(
            symbol="BANKNIFTY26OCT50000CE",
            units=45,
            option_type=OptionType.CE,
            strike=50000.0,
            spot=spot,
            time_to_expiry_years=time_to_expiry,
            volatility=vol,
        )

        summary = PortfolioGreeksRiskEngine.evaluate_portfolio([long_ce], spot_price=spot)

        self.assertFalse(summary.is_delta_neutral)
        self.assertGreater(summary.net_delta, 15.0)
        # To offset positive delta, must SELL Call units
        self.assertIn("SELL_", summary.recommended_hedge_action)
        self.assertIn("_ATM_CE", summary.recommended_hedge_action)
        # Hedge units must be lot-aligned (multiple of 15)
        self.assertEqual(summary.recommended_hedge_units % BankNiftyContractSpec.LOT_SIZE, 0)
        self.assertLess(summary.recommended_hedge_units, 0)

    def test_03_parametric_var_and_cvar(self) -> None:
        """Verifies 1-day 95% and 99% Parametric Value-at-Risk calculations."""
        spot = 50000.0
        time_to_expiry = 10.0 / 365.0
        vol = 0.18

        # Long 30 units ATM Call
        pos = PositionRiskItem(
            symbol="BANKNIFTY26OCT50000CE",
            units=30,
            option_type=OptionType.CE,
            strike=50000.0,
            spot=spot,
            time_to_expiry_years=time_to_expiry,
            volatility=vol,
        )

        report = BankNiftyStressTester.run_stress_test([pos], current_spot=spot, initial_capital=1_000_000.0)

        self.assertIsInstance(report, StressTestReport)
        self.assertGreater(report.var_95_1day_inr, 0.0)
        self.assertGreater(report.var_99_1day_inr, report.var_95_1day_inr)
        self.assertGreater(report.cvar_99_1day_inr, report.var_99_1day_inr)

    def test_04_macro_scenario_stress_testing_resilience(self) -> None:
        """Verifies tail-risk stress testing across historical shocks."""
        spot = 50000.0
        time_to_expiry = 21.0 / 365.0
        vol = 0.17

        # Hedged Bull Call Spread: Long 30 units 50000 CE, Short 30 units 50500 CE
        long_ce = PositionRiskItem(
            symbol="BANKNIFTY26OCT50000CE",
            units=30,
            option_type=OptionType.CE,
            strike=50000.0,
            spot=spot,
            time_to_expiry_years=time_to_expiry,
            volatility=vol,
        )
        short_ce = PositionRiskItem(
            symbol="BANKNIFTY26OCT50500CE",
            units=-30,
            option_type=OptionType.CE,
            strike=50500.0,
            spot=spot,
            time_to_expiry_years=time_to_expiry,
            volatility=vol,
        )

        report = BankNiftyStressTester.run_stress_test([long_ce, short_ce], current_spot=spot, initial_capital=500_000.0)

        self.assertEqual(len(report.scenario_results), 4)
        scenario_names = [sc.scenario_name for sc in report.scenario_results]
        self.assertIn("COVID_CIRCUIT_BREAKER_2020", scenario_names)
        self.assertIn("UNION_BUDGET_GAMMA_SHOCK", scenario_names)
        self.assertIn("ELECTION_RALLY_VOL_CRUSH", scenario_names)
        self.assertIn("RBI_INTEREST_RATE_HIKE", scenario_names)

        # Hedged spread has strictly bounded loss
        self.assertGreater(report.worst_case_loss_inr, -50_000.0)
        self.assertIn(report.portfolio_resilience_rating, ("ROBUST", "MODERATE"))
        for sc in report.scenario_results:
            self.assertFalse(sc.margin_call_triggered)


if __name__ == "__main__":
    unittest.main()
