"""Unit test battery for High-Frequency Dynamic Hedge Ratio & Kalman Filter Cointegration Engine.

Wave 36 Verification Suite (TASK-BN-46):
Validates:
1. Kalman recursive parameter convergence toward true synthetic alpha and beta.
2. Dynamic tracking of time-varying hedge ratio shifts (regime changes).
3. Ornstein-Uhlenbeck (OU) mean-reversion speed kappa and half-life t_{1/2} estimation.
4. Standardized Z-Score thresholding and SEBI discrete lot quantization (Bank Nifty = 15, Nifty = 25).
5. Exit band and Stop-Loss safety circuit breakers.
6. Input parameter boundary validation.
"""

from __future__ import annotations

import math
import random
import unittest

from agents.AGI_1_7.engine.agi17.finance.kalman_spread_filter import (
    HalfLifeEstimation,
    KalmanSpreadAction,
    KalmanSpreadFilter,
    KalmanStateSnapshot,
    KalmanTradingSignal,
)


class TestOmegaKalmanSpreadFilter(unittest.TestCase):
    """Test suite for Wave 36 Dynamic Kalman Filter Cointegration Engine."""

    def setUp(self) -> None:
        self.filter = KalmanSpreadFilter(
            delta_process_noise=1e-4,
            measurement_noise=1.0,
            initial_beta=1.0,
            initial_alpha=0.0,
            initial_state_cov=10.0,
            entry_z=2.0,
            exit_z=0.5,
            stop_z=3.5,
            min_half_life_sec=2.0,
            max_half_life_sec=3600.0,
        )

    def test_kalman_filter_parameter_convergence(self) -> None:
        """Verify that Kalman filter converges to true relationship y = 50.0 + 2.0 * x."""
        rng = random.Random(42)
        true_alpha = 50.0
        true_beta = 2.0

        snapshot = None
        for i in range(120):
            t = float(i)
            x = 24000.0 + rng.gauss(0.0, 50.0)
            noise = rng.gauss(0.0, 1.0)
            y = true_alpha + true_beta * x + noise

            snapshot = self.filter.update(y=y, x=x, timestamp=t)

        self.assertIsNotNone(snapshot)
        # Beta should converge very close to 2.0
        self.assertAlmostEqual(snapshot.hedge_ratio_beta, true_beta, delta=0.05)
        # Normalized error should remain small
        self.assertLess(abs(snapshot.spread_error), 5.0)

    def test_dynamic_hedge_ratio_tracking(self) -> None:
        """Verify tracking of a regime shift where beta moves from 1.5 to 2.2."""
        rng = random.Random(101)
        # First phase: beta = 1.5
        for i in range(80):
            x = 24000.0 + rng.gauss(0.0, 30.0)
            y = 1.5 * x + rng.gauss(0.0, 1.0)
            self.filter.update(y=y, x=x, timestamp=float(i))

        snap1 = self.filter.update(y=1.5 * 24000.0, x=24000.0, timestamp=80.0)
        self.assertAlmostEqual(snap1.hedge_ratio_beta, 1.5, delta=0.08)

        # Second phase: beta shifts to 2.2
        for i in range(81, 180):
            x = 24000.0 + rng.gauss(0.0, 30.0)
            y = 2.2 * x + rng.gauss(0.0, 1.0)
            snap2 = self.filter.update(y=y, x=x, timestamp=float(i))

        self.assertGreater(snap2.hedge_ratio_beta, 2.0)

    def test_ornstein_uhlenbeck_half_life_estimation(self) -> None:
        """Verify OU half-life estimation on a mean-reverting spread process."""
        rng = random.Random(999)
        # Synthetic OU spread with kappa = 0.05 (half-life ~ 13.86 seconds)
        e = 0.0
        dt = 1.0
        kappa_true = 0.05

        for i in range(150):
            t = float(i)
            # de = -kappa * e * dt + noise
            de = -kappa_true * e * dt + rng.gauss(0.0, 1.0)
            e += de
            x = 24000.0
            y = x + e
            self.filter.update(y=y, x=x, timestamp=t)

        half_life = self.filter.estimate_half_life(min_samples=20)
        self.assertTrue(half_life.is_mean_reverting)
        self.assertGreater(half_life.kappa, 0.0)
        # True half-life is ln(2)/0.05 ~ 13.86 seconds
        self.assertAlmostEqual(half_life.half_life_seconds, 13.86, delta=8.0)

    def test_trading_signal_generation_and_lot_quantization(self) -> None:
        """Verify Long/Short signal generation and SEBI lot quantization (BN=15, NIFTY=25)."""
        rng = random.Random(777)
        # Feed 30 steady points to establish mean-reverting history
        for i in range(30):
            x = 24000.0
            y = 2.0 * x + (1.0 if i % 2 == 0 else -1.0)
            self.filter.update(y=y, x=x, timestamp=float(i))

        # Push large negative innovation to trigger LONG_SPREAD (z <= -2.0)
        snap_long = self.filter.update(y=2.0 * 24000.0 - 15.0, x=24000.0, timestamp=31.0)
        self.assertLessEqual(snap_long.normalized_z_score, -self.filter.entry_z)

        signal_long = self.filter.generate_signal(
            snapshot=snap_long, base_lots_asset_1=1, lot_size_1=15, lot_size_2=25
        )
        self.assertEqual(signal_long.action, KalmanSpreadAction.LONG_SPREAD)
        self.assertEqual(signal_long.asset_1_lots, 1)
        # For beta ~ 2.0, target qty 2 = 2.0 * 1 * 15 = 30 contracts -> round(30 / 25) = 1 lot of Nifty
        self.assertEqual(signal_long.asset_2_lots, 1)

        # Push large positive innovation to trigger SHORT_SPREAD (z >= +2.0)
        snap_short = self.filter.update(y=2.0 * 24000.0 + 15.0, x=24000.0, timestamp=32.0)
        self.assertGreaterEqual(snap_short.normalized_z_score, self.filter.entry_z)
        signal_short = self.filter.generate_signal(snapshot=snap_short)
        self.assertEqual(signal_short.action, KalmanSpreadAction.SHORT_SPREAD)

    def test_stop_loss_and_exit_transitions(self) -> None:
        """Verify exit condition (|z| <= 0.5) and stop-loss condition (|z| >= 3.5)."""
        for i in range(25):
            self.filter.update(y=24000.0, x=24000.0, timestamp=float(i))

        # Extreme expansion -> STOP_LOSS
        snap_stop = self.filter.update(y=24000.0 + 50.0, x=24000.0, timestamp=26.0)
        sig_stop = self.filter.generate_signal(snap_stop)
        self.assertEqual(sig_stop.action, KalmanSpreadAction.STOP_LOSS)

        # Tight convergence -> EXIT_POSITION
        snap_exit = self.filter.update(y=24000.0 + 0.05, x=24000.0, timestamp=27.0)
        sig_exit = self.filter.generate_signal(snap_exit)
        self.assertEqual(sig_exit.action, KalmanSpreadAction.EXIT_POSITION)

    def test_parameter_boundary_validation(self) -> None:
        """Verify parameter bounds enforcement on initialization."""
        with self.assertRaises(ValueError):
            KalmanSpreadFilter(delta_process_noise=-0.01)

        with self.assertRaises(ValueError):
            # Inverted z-score thresholds (entry < exit)
            KalmanSpreadFilter(entry_z=0.4, exit_z=0.5, stop_z=3.0)


if __name__ == "__main__":
    unittest.main()
