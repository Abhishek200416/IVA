"""Unit and Integration Tests for Monte Carlo Portfolio Stress & Merton Jump-Diffusion Engine.

TASK-BN-23:
Verifies stochastic jump-diffusion modeling, multi-leg options mark-to-market,
extreme tail risk metrics (95%/99% VaR, CVaR), and trailing stop truncation for BANK NIFTY options.
"""

import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import (
    OptionType,
    OrderSide,
)
from agents.AGI_1_7.engine.agi17.finance.monte_carlo_portfolio_stress import (
    MonteCarloPortfolioStressEngine,
    OptionLeg,
    SimulationConfig,
)


class TestMonteCarloPortfolioStress(unittest.TestCase):
    """Test suite for Monte Carlo Jump-Diffusion Portfolio Stress Engine."""

    def test_spot_path_jump_diffusion(self) -> None:
        """Verifies geometric Brownian motion with discrete Poisson jump events."""
        cfg = SimulationConfig(
            num_paths=10,
            num_steps=75,
            spot_price=50000.0,
            annualized_vol=0.18,
            jump_intensity=0.20,  # 20% daily jump probability
            jump_mean=-0.02,
            jump_std=0.03,
            random_seed=123,
        )
        import random
        rng = random.Random(cfg.random_seed)
        prices, jumps = MonteCarloPortfolioStressEngine.simulate_spot_path(cfg, rng)

        self.assertEqual(len(prices), 76)  # Initial price + 75 steps
        self.assertEqual(prices[0], 50000.0)
        self.assertTrue(all(p > 0 for p in prices))

    def test_single_leg_revaluation_black_scholes(self) -> None:
        """Verifies call price rises and put price falls as spot rises."""
        call_leg = OptionLeg(
            strike=50000.0,
            option_type=OptionType.CE,
            side=OrderSide.BUY,
            units=15,
            entry_premium=350.0,
            dte_years=7.0 / 252.0,
            implied_vol=0.16,
        )
        put_leg = OptionLeg(
            strike=50000.0,
            option_type=OptionType.PE,
            side=OrderSide.BUY,
            units=15,
            entry_premium=350.0,
            dte_years=7.0 / 252.0,
            implied_vol=0.16,
        )

        call_low = MonteCarloPortfolioStressEngine.revalue_portfolio_leg(call_leg, 49500.0, 7.0 / 252.0)
        call_high = MonteCarloPortfolioStressEngine.revalue_portfolio_leg(call_leg, 50500.0, 7.0 / 252.0)
        self.assertGreater(call_high, call_low)

        put_low = MonteCarloPortfolioStressEngine.revalue_portfolio_leg(put_leg, 49500.0, 7.0 / 252.0)
        put_high = MonteCarloPortfolioStressEngine.revalue_portfolio_leg(put_leg, 50500.0, 7.0 / 252.0)
        self.assertGreater(put_low, put_high)

    def test_bull_call_spread_bounded_payoff(self) -> None:
        """Verifies Bull Call Spread risk remains bounded by net premium paid and strike spread."""
        portfolio = [
            OptionLeg(
                strike=50000.0,
                option_type=OptionType.CE,
                side=OrderSide.BUY,
                units=15,
                entry_premium=350.0,
                dte_years=7.0 / 252.0,
                implied_vol=0.16,
            ),
            OptionLeg(
                strike=50500.0,
                option_type=OptionType.CE,
                side=OrderSide.SELL,
                units=15,
                entry_premium=150.0,
                dte_years=7.0 / 252.0,
                implied_vol=0.16,
            ),
        ]
        cfg = SimulationConfig(
            num_paths=40,
            num_steps=30,
            spot_price=50000.0,
            annualized_vol=0.15,
            random_seed=42,
        )
        report = MonteCarloPortfolioStressEngine.run_stress_simulation(
            portfolio=portfolio,
            config=cfg,
            account_capital_inr=500000.0,
        )

        self.assertEqual(report.total_paths, 40)
        self.assertEqual(report.margin_breach_probability, 0.0)
        # Max loss is capped (net debit * 15 = ~200 * 15 = 3000)
        self.assertLess(report.max_loss_inr, 6000.0)

    def test_short_strangle_tail_risk_under_jump_shocks(self) -> None:
        """Verifies short strangle experiences fat-tailed losses during jump shocks (CVaR > VaR)."""
        portfolio = [
            OptionLeg(
                strike=50500.0,
                option_type=OptionType.CE,
                side=OrderSide.SELL,
                units=15,
                entry_premium=200.0,
                dte_years=7.0 / 252.0,
                implied_vol=0.16,
            ),
            OptionLeg(
                strike=49500.0,
                option_type=OptionType.PE,
                side=OrderSide.SELL,
                units=15,
                entry_premium=200.0,
                dte_years=7.0 / 252.0,
                implied_vol=0.16,
            ),
        ]
        cfg = SimulationConfig(
            num_paths=50,
            num_steps=30,
            spot_price=50000.0,
            annualized_vol=0.22,
            jump_intensity=0.35,  # Frequent shocks
            jump_mean=-0.03,      # Negative market jumps
            jump_std=0.035,
            random_seed=999,
        )
        report = MonteCarloPortfolioStressEngine.run_stress_simulation(
            portfolio=portfolio,
            config=cfg,
            account_capital_inr=500000.0,
        )

        self.assertGreater(report.total_jumps_observed, 0)
        # In a fat-tailed distribution, Expected Shortfall (CVaR) >= Value at Risk (VaR)
        self.assertGreaterEqual(report.cvar_95_inr, report.var_95_inr)
        self.assertGreaterEqual(report.cvar_99_inr, report.var_99_inr)

    def test_margin_breach_probability_under_insufficient_capital(self) -> None:
        """Verifies high breach rate when capital is too small to absorb short option adverse moves."""
        portfolio = [
            OptionLeg(
                strike=50500.0,
                option_type=OptionType.CE,
                side=OrderSide.SELL,
                units=15,
                entry_premium=200.0,
                dte_years=7.0 / 252.0,
                implied_vol=0.20,
            ),
        ]
        cfg = SimulationConfig(
            num_paths=30,
            num_steps=20,
            spot_price=50000.0,
            annualized_vol=0.30,  # High vol
            jump_intensity=0.40,
            jump_mean=0.04,       # Sharp upward rally crushing short calls
            random_seed=777,
        )
        # Account capital only ₹500 (breached easily on a 50 pt move)
        report_low_cap = MonteCarloPortfolioStressEngine.run_stress_simulation(
            portfolio=portfolio,
            config=cfg,
            account_capital_inr=500.0,
        )
        self.assertGreater(report_low_cap.margin_breach_probability, 0.0)

        # Well-capitalized account ₹500,000 (never breached)
        report_safe = MonteCarloPortfolioStressEngine.run_stress_simulation(
            portfolio=portfolio,
            config=cfg,
            account_capital_inr=500000.0,
        )
        self.assertEqual(report_safe.margin_breach_probability, 0.0)


if __name__ == "__main__":
    unittest.main()
