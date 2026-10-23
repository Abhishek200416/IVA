"""Unit test battery for Bayesian Posterior Learning & Fractional Kelly Position Sizer.

Wave 32 Test Suite (TASK-BN-42):
1. Test Bayesian Beta-Binomial win rate posterior updating.
2. Test Full and Fractional Kelly allocation fractions.
3. Test continuous exponential drawdown governor dampening.
4. Test SEBI integer lot quantization and margin utilization.
5. Test hard drawdown halt and capital exhaustion safety.
6. Test negative edge protection (zero capital allocation).
"""

import unittest
from agents.AGI_1_7.engine.agi17.finance.bayesian_kelly_position_sizer import (
    BayesianKellyPositionSizer,
    BayesianTradeHistory,
    DrawdownGovernorConfig,
    KellySizingResult,
    SizingRegime,
)


class TestBayesianKellyPositionSizer(unittest.TestCase):
    """Test suite for BayesianKellyPositionSizer."""

    def setUp(self) -> None:
        self.sizer = BayesianKellyPositionSizer(
            default_alpha_prior=12.0,
            default_beta_prior=8.0,  # Prior mean = 12 / 20 = 0.60 (60% win rate)
            drawdown_config=DrawdownGovernorConfig(
                soft_threshold=0.02,
                decay_rate=30.0,
                hard_stop=0.06,
            ),
            max_capital_allocation_fraction=0.40,
        )

    def test_bayesian_win_probability_update(self) -> None:
        """Verify conjugate Beta-Binomial posterior updating as trades occur."""
        # Baseline prior: 12 / (12 + 8) = 0.60
        self.assertAlmostEqual(self.sizer.compute_posterior_win_probability(), 0.60, places=3)

        # Record 10 wins and 0 losses: (12 + 10) / (20 + 10) = 22 / 30 = 0.7333
        for _ in range(10):
            self.sizer.record_trade_outcome(is_win=True)
        self.assertAlmostEqual(self.sizer.compute_posterior_win_probability(), 0.7333, places=3)

        # Record 10 losses: (22) / (30 + 10) = 22 / 40 = 0.55
        for _ in range(10):
            self.sizer.record_trade_outcome(is_win=False)
        self.assertAlmostEqual(self.sizer.compute_posterior_win_probability(), 0.55, places=3)

    def test_fractional_kelly_computation(self) -> None:
        """Verify Full Kelly and Fractional Kelly math with bounded risk ceiling."""
        # Prior p = 0.60, payoff b = 2.0
        # Edge = (0.60 * 2.0) - 0.40 = 1.20 - 0.40 = 0.80
        # Full Kelly = 0.80 / 2.0 = 0.40 (40%)
        # Quarter Kelly (kappa = 0.25): 0.40 * 0.25 = 0.10 (10%)
        full_f, frac_f = self.sizer.compute_fractional_kelly(payoff_ratio=2.0, kappa=0.25)
        self.assertAlmostEqual(full_f, 0.40, places=3)
        self.assertAlmostEqual(frac_f, 0.10, places=3)

        # Half Kelly (kappa = 0.50): 0.40 * 0.50 = 0.20 (20%)
        _, half_f = self.sizer.compute_fractional_kelly(payoff_ratio=2.0, kappa=0.50)
        self.assertAlmostEqual(half_f, 0.20, places=3)

    def test_continuous_drawdown_governor(self) -> None:
        """Verify exponential dampening above soft threshold and hard stop."""
        # 1. Drawdown below soft threshold (1% < 2%): factor = 1.0
        gov_low, is_stop_low = self.sizer.compute_drawdown_governor(current_drawdown=0.01)
        self.assertFalse(is_stop_low)
        self.assertAlmostEqual(gov_low, 1.0, places=3)

        # 2. Drawdown above soft threshold (4%):
        # excess = 0.04 - 0.02 = 0.02
        # factor = exp(-30 * 0.02) = exp(-0.6) = 0.5488
        gov_mid, is_stop_mid = self.sizer.compute_drawdown_governor(current_drawdown=0.04)
        self.assertFalse(is_stop_mid)
        self.assertAlmostEqual(gov_mid, 0.5488, places=3)

        # 3. Drawdown at or above hard stop (6%): factor = 0.0, is_hard_stop = True
        gov_stop, is_stop = self.sizer.compute_drawdown_governor(current_drawdown=0.065)
        self.assertTrue(is_stop)
        self.assertEqual(gov_stop, 0.0)

    def test_integer_lot_quantization_and_margin(self) -> None:
        """Verify capital allocation and Indian SEBI integer lot quantization."""
        # Equity = 1,000,000 INR
        # Margin per lot = 80,000 INR
        # Lot size = 15 contracts (Bank Nifty)
        # Sizing at Quarter Kelly (10% allocation):
        # Allocated capital = 100,000 INR
        # Lots = floor(100,000 / 80,000) = 1 lot = 15 contracts
        # Margin used = 80,000 INR, Cash buffer = 920,000 INR
        res = self.sizer.calculate_position_size(
            equity_inr=1000000.0,
            margin_per_lot_inr=80000.0,
            lot_size_contracts=15,
            payoff_ratio=2.0,
            current_drawdown=0.0,
            kappa=0.25,
        )
        self.assertEqual(res.regime, SizingRegime.OPTIMAL_KELLY)
        self.assertEqual(res.quantized_lots, 1)
        self.assertEqual(res.quantized_contracts, 15)
        self.assertEqual(res.margin_utilized_inr, 80000.0)
        self.assertEqual(res.cash_buffer_remaining_inr, 920000.0)
        self.assertGreaterEqual(res.cash_buffer_remaining_inr, 0.0)

    def test_hard_drawdown_halt_and_capital_exhaustion(self) -> None:
        """Verify safety halting under extreme drawdown or depleted equity."""
        # 1. Hard drawdown halt
        res_dd = self.sizer.calculate_position_size(
            equity_inr=1000000.0,
            margin_per_lot_inr=80000.0,
            current_drawdown=0.07,  # > 6%
        )
        self.assertEqual(res_dd.regime, SizingRegime.HARD_DRAWDOWN_HALT)
        self.assertEqual(res_dd.quantized_lots, 0)
        self.assertIn("HARD DRAWDOWN HALT", res_dd.rationale[0])

        # 2. Capital exhaustion
        res_cap = self.sizer.calculate_position_size(
            equity_inr=50000.0,  # Below 80,000 minimum lot margin
            margin_per_lot_inr=80000.0,
            current_drawdown=0.0,
        )
        self.assertEqual(res_cap.regime, SizingRegime.CAPITAL_EXHAUSTED)
        self.assertEqual(res_cap.quantized_lots, 0)
        self.assertIn("Insufficient equity", res_cap.rationale[0])

    def test_negative_edge_protection(self) -> None:
        """Verify zero capital allocation when expected mathematical edge is negative."""
        # Create a losing history: 2 wins, 18 losses
        # Posterior p = (12 + 2) / (20 + 20) = 14 / 40 = 0.35
        # With payoff b = 1.0: Edge = (0.35 * 1.0) - 0.65 = -0.30 < 0
        losing_sizer = BayesianKellyPositionSizer(
            default_alpha_prior=12.0,
            default_beta_prior=8.0,
        )
        for _ in range(2):
            losing_sizer.record_trade_outcome(is_win=True)
        for _ in range(18):
            losing_sizer.record_trade_outcome(is_win=False)

        res = losing_sizer.calculate_position_size(
            equity_inr=1000000.0,
            margin_per_lot_inr=80000.0,
            payoff_ratio=1.0,
        )
        self.assertEqual(res.regime, SizingRegime.NEGATIVE_EDGE_NO_ALLOCATION)
        self.assertEqual(res.quantized_lots, 0)
        self.assertEqual(res.allocated_capital_inr, 0.0)
        self.assertIn("Negative or zero statistical edge", res.rationale[0])


if __name__ == "__main__":
    unittest.main()
