"""Acceptance test suite for Deflated Sharpe Ratio & Strategy Parameter Optimizer."""

import unittest
from typing import Any, Dict, List

from agents.AGI_1_7.engine.agi17.finance.strategy_optimizer import (
    HyperparameterSpace,
    SplitMethod,
    StrategyParameterOptimizer,
    StrategyTrial,
    WalkForwardFold,
    WalkForwardSplitter,
    compute_deflated_sharpe_ratio,
    compute_expected_max_sharpe,
    compute_probabilistic_sharpe_ratio,
    compute_sample_moments,
    compute_sharpe_ratio,
    compute_sharpe_std_error,
)


class TestOmegaStrategyOptimizer(unittest.TestCase):
    """Test suite for Deflated Sharpe Ratio and walk-forward parameter optimizer."""

    def test_sample_moments_and_sharpe_ratio(self) -> None:
        """Verify statistical moment calculation and Mertens Sharpe standard error."""
        # Symmetric zero-mean returns
        returns = [0.01, -0.01, 0.02, -0.02, 0.015, -0.015]
        mean, std, skew, kurt = compute_sample_moments(returns)
        self.assertAlmostEqual(mean, 0.0, places=4)
        self.assertGreater(std, 0.0)
        self.assertAlmostEqual(skew, 0.0, places=2)

        # Standard error under normal vs fat tails
        sr = 1.5
        se_normal = compute_sharpe_std_error(sr=sr, sample_size=100, skewness=0.0, kurtosis=3.0)
        se_fat_tails = compute_sharpe_std_error(sr=sr, sample_size=100, skewness=-1.0, kurtosis=6.0)
        # Fat tails and negative skew increase standard error
        self.assertGreater(se_fat_tails, se_normal)

    def test_probabilistic_sharpe_ratio(self) -> None:
        """Verify PSR behavior across benchmark and non-normal parameters."""
        # If observed SR equals benchmark SR, PSR must be exactly 0.50
        psr_neutral = compute_probabilistic_sharpe_ratio(
            observed_sr=1.0,
            benchmark_sr=1.0,
            sample_size=100,
        )
        self.assertAlmostEqual(psr_neutral, 0.50, places=2)

        # If observed SR is significantly higher than benchmark SR, PSR approaches 1.0
        psr_high = compute_probabilistic_sharpe_ratio(
            observed_sr=2.5,
            benchmark_sr=0.0,
            sample_size=100,
        )
        self.assertGreater(psr_high, 0.99)

        # Negative skewness decreases confidence in a positive Sharpe ratio
        psr_skewed = compute_probabilistic_sharpe_ratio(
            observed_sr=1.5,
            benchmark_sr=0.0,
            sample_size=50,
            skewness=-2.0,
            kurtosis=6.0,
        )
        psr_unskewed = compute_probabilistic_sharpe_ratio(
            observed_sr=1.5,
            benchmark_sr=0.0,
            sample_size=50,
            skewness=0.0,
            kurtosis=3.0,
        )
        self.assertLess(psr_skewed, psr_unskewed)

    def test_expected_max_sharpe_multiple_testing(self) -> None:
        """Verify expected maximum Sharpe under null increases with trial count."""
        e_max_10 = compute_expected_max_sharpe(num_trials=10, trials_sr_variance=1.0)
        e_max_100 = compute_expected_max_sharpe(num_trials=100, trials_sr_variance=1.0)
        e_max_1000 = compute_expected_max_sharpe(num_trials=1000, trials_sr_variance=1.0)

        self.assertGreater(e_max_10, 0.0)
        self.assertGreater(e_max_100, e_max_10)
        self.assertGreater(e_max_1000, e_max_100)

        # Variance scaling
        e_max_high_var = compute_expected_max_sharpe(num_trials=100, trials_sr_variance=4.0)
        self.assertAlmostEqual(e_max_high_var, 2.0 * e_max_100, places=2)

    def test_deflated_sharpe_ratio(self) -> None:
        """Verify DSR penalizes multiple testing selection bias."""
        observed_sr = 1.8
        sample_size = 80

        # With 1 trial, DSR == PSR
        psr = compute_probabilistic_sharpe_ratio(observed_sr=observed_sr, sample_size=sample_size)
        dsr_1 = compute_deflated_sharpe_ratio(
            observed_sr=observed_sr,
            num_trials=1,
            sample_size=sample_size,
        )
        self.assertAlmostEqual(psr, dsr_1, places=4)

        # With 100 trials tested, DSR must be strictly lower than PSR due to multiple testing
        dsr_100 = compute_deflated_sharpe_ratio(
            observed_sr=observed_sr,
            num_trials=100,
            trials_sr_variance=0.8,
            sample_size=sample_size,
        )
        self.assertLess(dsr_100, psr)
        self.assertGreater(dsr_100, 0.0)
        self.assertLessEqual(dsr_100, 1.0)

    def test_walk_forward_splitter(self) -> None:
        """Verify purged walk-forward folds generation in anchored and rolling modes."""
        total_bars = 120
        splitter = WalkForwardSplitter(
            total_bars=total_bars,
            n_splits=3,
            purge_bars=4,
            method=SplitMethod.ANCHORED,
        )
        folds = splitter.generate_folds()
        self.assertGreaterEqual(len(folds), 2)

        for fold in folds:
            # Train must end before test starts by at least purge_bars
            self.assertGreaterEqual(fold.test_start, fold.train_end + fold.purge_bars)
            self.assertLessEqual(fold.test_end, total_bars)
            self.assertGreater(fold.test_end, fold.test_start)

        # Rolling mode
        rolling_splitter = WalkForwardSplitter(
            total_bars=total_bars,
            n_splits=3,
            purge_bars=2,
            method=SplitMethod.ROLLING,
        )
        r_folds = rolling_splitter.generate_folds()
        self.assertGreaterEqual(len(r_folds), 2)

    def test_strategy_parameter_optimizer_walk_forward(self) -> None:
        """Run end-to-end walk-forward optimizer with overfitting detection."""
        # Define synthetic strategy evaluator
        # Parameter 'regime_threshold':
        # threshold 10 is genuine (positive in both train and test)
        # threshold 50 is overfitted (high in train, negative in test)
        def mock_evaluator(params: Dict[str, Any], start: int, end: int) -> List[float]:
            thresh = params.get("regime_threshold", 10)
            n_bars = end - start
            if thresh == 10:
                # Consistent modest positive returns
                return [0.002 * ((i % 3) - 0.5) + 0.001 for i in range(n_bars)]
            elif thresh == 50:
                # In-sample (early) high positive, out-of-sample (late) negative
                if start < 50:
                    return [0.005 for _ in range(n_bars)]
                else:
                    return [-0.004 for _ in range(n_bars)]
            else:
                return [0.0 for _ in range(n_bars)]

        space = HyperparameterSpace(
            discrete_params={
                "regime_threshold": [10, 50],
                "trailing_mult": [1.5, 2.0],
            }
        )

        optimizer = StrategyParameterOptimizer(
            strategy_evaluator=mock_evaluator,
            space=space,
            benchmark_sr=0.0,
            min_dsr_threshold=0.50,
            max_degradation_tolerance=0.40,
        )

        trials, best_trial = optimizer.optimize_walk_forward(
            total_bars=100,
            n_splits=2,
            max_trials=10,
        )

        self.assertEqual(len(trials), 4)
        self.assertIsNotNone(best_trial)

        # Check that overfitted parameter threshold 50 was flagged
        overfitted_trials = [t for t in trials if t.params["regime_threshold"] == 50]
        for ot in overfitted_trials:
            self.assertTrue(ot.is_overfitted)

        # Check best trial is from the robust threshold 10
        self.assertEqual(best_trial.params["regime_threshold"], 10)
        self.assertFalse(best_trial.is_overfitted)
        self.assertGreater(best_trial.out_of_sample_sharpe, 0.0)


if __name__ == "__main__":
    unittest.main()
