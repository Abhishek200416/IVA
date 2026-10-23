"""Acceptance test suite for Mutually Exciting Bivariate Hawkes Process Engine."""

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.hawkes_process_engine import (
    BivariateHawkesEngine,
    HawkesClusterRegime,
    HawkesIntensitySnapshot,
    HawkesParameters,
)


class TestOmegaHawkesProcessEngine(unittest.TestCase):
    """Test suite for BivariateHawkesEngine."""

    def setUp(self) -> None:
        self.params = HawkesParameters(
            mu_buy=0.5,
            mu_sell=0.5,
            alpha_bb=0.3,
            alpha_bs=0.1,
            alpha_sb=0.1,
            alpha_ss=0.3,
            beta_decay=1.0,
        )
        self.engine = BivariateHawkesEngine(params=self.params)

    def test_spectral_radius_and_stability(self) -> None:
        """Verify spectral radius computation and stability condition."""
        # For symmetric matrix [[0.3, 0.1], [0.1, 0.3]], eigenvalues are 0.4 and 0.2
        rho, is_stable = BivariateHawkesEngine._compute_spectral_radius(self.params)
        self.assertAlmostEqual(rho, 0.4, places=4)
        self.assertTrue(is_stable)

        # Unstable / explosive branching ratio matrix (spectral radius >= 1.0)
        explosive_params = HawkesParameters(
            alpha_bb=0.8,
            alpha_bs=0.4,
            alpha_sb=0.4,
            alpha_ss=0.8,
            beta_decay=1.0,
        )
        rho_exp, is_stable_exp = BivariateHawkesEngine._compute_spectral_radius(explosive_params)
        self.assertAlmostEqual(rho_exp, 1.2, places=4)
        self.assertFalse(is_stable_exp)

    def test_recursive_state_decay_towards_baseline(self) -> None:
        """Verify intensity decay over time approaches baseline Poisson rate."""
        snap_initial = self.engine.get_intensity(current_time=0.0)
        self.assertEqual(snap_initial.lambda_buy, 0.5)
        self.assertEqual(snap_initial.lambda_sell, 0.5)

        # Record a buy event at t = 1.0
        snap_post_buy = self.engine.record_event(timestamp=1.0, event_type="BUY")
        # lambda_buy = mu_buy (0.5) + alpha_bb (0.3) = 0.8
        self.assertAlmostEqual(snap_post_buy.lambda_buy, 0.8, places=3)
        # lambda_sell = mu_sell (0.5) + alpha_sb (0.1) = 0.6
        self.assertAlmostEqual(snap_post_buy.lambda_sell, 0.6, places=3)

        # At t = 2.0 (dt = 1.0), excitement decays by exp(-1.0) ~ 0.367879
        snap_decayed = self.engine.get_intensity(current_time=2.0)
        expected_buy = 0.5 + 0.3 * math.exp(-1.0)  # ~0.6104
        self.assertAlmostEqual(snap_decayed.lambda_buy, expected_buy, delta=0.01)

        # As t -> infinity, intensities converge back to baseline 0.5
        snap_distant = self.engine.get_intensity(current_time=100.0)
        self.assertAlmostEqual(snap_distant.lambda_buy, 0.5, places=2)
        self.assertAlmostEqual(snap_distant.lambda_sell, 0.5, places=2)

    def test_self_and_cross_excitation_asymmetry(self) -> None:
        """Verify directional momentum creates intensity imbalance."""
        # Rapid series of 5 buy events
        for i in range(5):
            t = 10.0 + (i * 0.1)
            self.engine.record_event(timestamp=t, event_type="BUY")

        snap = self.engine.get_intensity(current_time=10.5)
        # Buy intensity should vastly exceed sell intensity
        self.assertGreater(snap.lambda_buy, snap.lambda_sell)
        self.assertGreater(snap.intensity_imbalance, 0.20)
        self.assertGreater(snap.endogeneity_ratio, 0.30)

    def test_clustering_regimes_and_spread_widening(self) -> None:
        """Verify regime classification and market-making quote spread widening."""
        # 1. Calm exogenous flow
        calm_snap = self.engine.get_intensity(0.0)
        self.assertEqual(calm_snap.regime, HawkesClusterRegime.EXOGENOUS_CALM)
        self.assertEqual(calm_snap.suggested_spread_widening_mult, 1.0)

        # 2. Dense directional clustering -> MOMENTUM_CLUSTERING
        engine_burst = BivariateHawkesEngine(params=self.params)
        for i in range(12):
            engine_burst.record_event(timestamp=1.0 + (i * 0.05), event_type="BUY")
        burst_snap = engine_burst.get_intensity(current_time=1.6)
        self.assertIn(
            burst_snap.regime,
            (HawkesClusterRegime.MOMENTUM_CLUSTERING, HawkesClusterRegime.EXPLOSIVE_CASCADE),
        )
        self.assertGreaterEqual(burst_snap.suggested_spread_widening_mult, 1.6)

        # 3. Unstable / near-critical cascade -> EXPLOSIVE_CASCADE
        unstable_params = HawkesParameters(
            alpha_bb=0.7,
            alpha_bs=0.3,
            alpha_sb=0.3,
            alpha_ss=0.7,
            beta_decay=1.0,
        )
        engine_unstable = BivariateHawkesEngine(params=unstable_params)
        for i in range(10):
            engine_unstable.record_event(timestamp=1.0 + (i * 0.02), event_type="BUY")
            engine_unstable.record_event(timestamp=1.01 + (i * 0.02), event_type="SELL")
        shock_snap = engine_unstable.get_intensity(current_time=1.3)
        self.assertEqual(shock_snap.regime, HawkesClusterRegime.EXPLOSIVE_CASCADE)
        self.assertEqual(shock_snap.suggested_spread_widening_mult, 2.5)

    def test_endogeneity_ratio_boundedness(self) -> None:
        """Verify endogeneity ratio stays bounded in [0.0, 1.0]."""
        snap = self.engine.get_intensity(current_time=0.0)
        self.assertGreaterEqual(snap.endogeneity_ratio, 0.0)
        self.assertLessEqual(snap.endogeneity_ratio, 1.0)

        # Flood of 20 mixed trades
        for i in range(20):
            event = "BUY" if i % 2 == 0 else "SELL"
            s = self.engine.record_event(timestamp=100.0 + (i * 0.05), event_type=event)
            self.assertGreaterEqual(s.endogeneity_ratio, 0.0)
            self.assertLessEqual(s.endogeneity_ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
