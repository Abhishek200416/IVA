"""Deflated Sharpe Ratio & Walk-Forward Strategy Parameter Optimizer.

Implements Marcos Lopez de Prado's Deflated Sharpe Ratio (DSR), Probabilistic
Sharpe Ratio (PSR), multiple-testing selection bias correction, and walk-forward
train/validation/test parameter grid search for Bank Nifty options strategies.

References:
- Bailey, D. H., & Lopez de Prado, M. (2014). The Deflated Sharpe Ratio:
  Correcting for Selection Bias, Backtest Overfitting and Non-Normality.
  Journal of Portfolio Management, 40(5), 94-107.
- Mertens, E. (2002). Comments on 'The Sharpe Ratio'.
  Journal of Risk, 4(2), 211-223.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function Phi(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    """Standard normal probability density function phi(x)."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def normal_ppf(p: float) -> float:
    """Standard normal quantile function (inverse CDF) using rational approximation & Newton-Raphson."""
    if p <= 1e-15:
        return -8.0
    if p >= 1.0 - 1e-15:
        return 8.0
    
    # Abramowitz & Stegun 26.2.23 initial rational approximation
    t = math.sqrt(-2.0 * math.log(min(p, 1.0 - p)))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    num = c0 + c1 * t + c2 * (t ** 2)
    den = 1.0 + d1 * t + d2 * (t ** 2) + d3 * (t ** 3)
    x0 = t - (num / den)
    if p < 0.5:
        x0 = -x0
    
    # Refine with 4 Newton-Raphson steps for float64 precision
    x = x0
    for _ in range(4):
        err = normal_cdf(x) - p
        pdf = max(normal_pdf(x), 1e-15)
        x -= err / pdf
    return x


def compute_sample_moments(returns: Sequence[float]) -> Tuple[float, float, float, float]:
    """Compute sample mean, standard deviation, skewness, and kurtosis.
    
    Returns:
        (mean, std, skewness, kurtosis) where kurtosis is Pearson (normal=3.0).
    """
    n = len(returns)
    if n < 3:
        return 0.0, 0.0, 0.0, 3.0

    mean = sum(returns) / n
    diffs = [r - mean for r in returns]
    var = sum(d * d for d in diffs) / (n - 1)
    std = math.sqrt(var) if var > 1e-12 else 1e-6

    # Skewness
    m3 = sum(d ** 3 for d in diffs) / n
    skew = m3 / (std ** 3) if std > 1e-6 else 0.0

    # Kurtosis (Pearson, normal is 3.0)
    m4 = sum(d ** 4 for d in diffs) / n
    kurt = m4 / (std ** 4) if std > 1e-6 else 3.0

    return mean, std, skew, kurt


def compute_sharpe_ratio(
    returns: Sequence[float],
    risk_free_rate: float = 0.0,
    annualization_factor: float = 1.0,
) -> float:
    """Compute annualized Sharpe ratio from return series."""
    if len(returns) < 2:
        return 0.0
    mean, std, _, _ = compute_sample_moments(returns)
    if std < 1e-8:
        return 0.0
    excess_mean = mean - risk_free_rate
    sr = (excess_mean / std) * math.sqrt(annualization_factor)
    return sr


def compute_sharpe_std_error(
    sr: float,
    sample_size: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Compute standard error of the Sharpe ratio (Mertens, 2002).
    
    sigma_SR = sqrt((1 + 0.5*SR^2 - skew*SR + ((kurt - 3)/4)*SR^2) / T)
    """
    if sample_size <= 1:
        return 1.0
    t = float(sample_size)
    variance_sr = (1.0 + 0.5 * (sr ** 2) - skewness * sr + ((kurtosis - 3.0) / 4.0) * (sr ** 2)) / t
    if variance_sr < 1e-8:
        variance_sr = 1.0 / t
    return math.sqrt(variance_sr)


def compute_probabilistic_sharpe_ratio(
    observed_sr: float,
    benchmark_sr: float = 0.0,
    sample_size: int = 100,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Probabilistic Sharpe Ratio (PSR) under non-normal returns.
    
    PSR = Phi((observed_sr - benchmark_sr) / sigma_SR)
    """
    se = compute_sharpe_std_error(observed_sr, sample_size, skewness, kurtosis)
    z = (observed_sr - benchmark_sr) / se
    return normal_cdf(z)


def compute_expected_max_sharpe(
    num_trials: int,
    trials_sr_variance: float = 1.0,
    euler_mascheroni: float = 0.57721566490153286,
) -> float:
    """Estimate expected maximum Sharpe ratio under null of zero skill across N independent trials.
    
    Formula (Bailey & Lopez de Prado 2014):
    E[max_N] ~= sqrt(V) * [ (1 - gamma)*Phi^-1(1 - 1/N) + gamma*Phi^-1(1 - 1/(N*e)) ]
    """
    if num_trials <= 1:
        return 0.0
    
    n = float(num_trials)
    std_v = math.sqrt(max(trials_sr_variance, 1e-6))
    
    p1 = 1.0 - 1.0 / n
    p2 = 1.0 - 1.0 / (n * math.e)
    
    z1 = normal_ppf(p1)
    z2 = normal_ppf(p2)
    
    expected_max = std_v * ((1.0 - euler_mascheroni) * z1 + euler_mascheroni * z2)
    return max(0.0, expected_max)


def compute_deflated_sharpe_ratio(
    observed_sr: float,
    num_trials: int,
    trials_sr_variance: float = 1.0,
    sample_size: int = 100,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Deflated Sharpe Ratio (DSR) correcting for multiple testing and selection bias.
    
    DSR = Phi((observed_sr - E[max_N]) / sigma_SR)
    """
    if num_trials <= 1:
        return compute_probabilistic_sharpe_ratio(
            observed_sr=observed_sr,
            benchmark_sr=0.0,
            sample_size=sample_size,
            skewness=skewness,
            kurtosis=kurtosis,
        )

    sr_star = compute_expected_max_sharpe(
        num_trials=num_trials,
        trials_sr_variance=trials_sr_variance,
    )
    se = compute_sharpe_std_error(observed_sr, sample_size, skewness, kurtosis)
    z = (observed_sr - sr_star) / se
    return normal_cdf(z)


class SplitMethod(Enum):
    """Walk-forward cross-validation splitting mode."""
    ANCHORED = "ANCHORED"  # Expanding training window
    ROLLING = "ROLLING"    # Fixed-length sliding training window


@dataclass(frozen=True)
class WalkForwardFold:
    """A train/test split with purge protection against serial correlation leak."""
    fold_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    purge_bars: int = 0


class WalkForwardSplitter:
    """Generates purged train/validation/test folds for time-series optimization."""

    def __init__(
        self,
        total_bars: int,
        n_splits: int = 4,
        train_ratio: float = 0.70,
        purge_bars: int = 5,
        method: SplitMethod = SplitMethod.ANCHORED,
    ) -> None:
        if total_bars < 20:
            raise ValueError(f"total_bars must be >= 20, got {total_bars}")
        if n_splits < 1:
            raise ValueError("n_splits must be >= 1")
        
        self.total_bars = total_bars
        self.n_splits = n_splits
        self.train_ratio = train_ratio
        self.purge_bars = purge_bars
        self.method = method

    def generate_folds(self) -> List[WalkForwardFold]:
        """Generate WalkForwardFold list."""
        folds: List[WalkForwardFold] = []
        test_chunk_size = (self.total_bars - self.purge_bars) // (self.n_splits + 1)
        if test_chunk_size < 5:
            test_chunk_size = 5

        for i in range(self.n_splits):
            if self.method == SplitMethod.ANCHORED:
                train_start = 0
                train_end = (i + 1) * test_chunk_size
                test_start = min(self.total_bars, train_end + self.purge_bars)
                test_end = min(self.total_bars, test_start + test_chunk_size)
            else:
                # Rolling fixed window
                window_size = int(self.train_ratio * self.total_bars // self.n_splits)
                train_start = i * test_chunk_size
                train_end = train_start + window_size
                test_start = min(self.total_bars, train_end + self.purge_bars)
                test_end = min(self.total_bars, test_start + test_chunk_size)

            if test_start >= self.total_bars or test_start >= test_end:
                break

            folds.append(
                WalkForwardFold(
                    fold_index=i,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    purge_bars=self.purge_bars,
                )
            )
        return folds


@dataclass
class StrategyTrial:
    """Results of a single parameter set evaluation."""
    trial_id: str
    params: Dict[str, Any]
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    in_sample_net_pnl: float
    out_of_sample_net_pnl: float
    max_drawdown_pct: float
    win_rate: float
    sample_size: int
    skewness: float
    kurtosis: float
    probabilistic_sharpe_ratio: float = 0.0
    deflated_sharpe_ratio: float = 0.0
    is_overfitted: bool = False
    notes: str = ""


@dataclass
class HyperparameterSpace:
    """Defines search parameters for strategy tuning."""
    discrete_params: Dict[str, List[Any]] = field(default_factory=dict)

    def generate_grid(self, max_combinations: Optional[int] = None) -> List[Dict[str, Any]]:
        """Generate Cartesian product of all parameters."""
        if not self.discrete_params:
            return [{}]
        keys = list(self.discrete_params.keys())
        values = list(self.discrete_params.values())
        product = [dict(zip(keys, combo)) for combo in itertools.product(*values)]
        if max_combinations is not None and len(product) > max_combinations:
            return product[:max_combinations]
        return product

    def sample_random(self, n_samples: int, seed: int = 42) -> List[Dict[str, Any]]:
        """Sample n random parameter combinations."""
        grid = self.generate_grid()
        if not grid:
            return [{}]
        rng = random.Random(seed)
        if len(grid) <= n_samples:
            rng.shuffle(grid)
            return grid
        return rng.sample(grid, n_samples)


class StrategyParameterOptimizer:
    """Grid & random walk-forward optimizer with Deflated Sharpe Ratio gating."""

    def __init__(
        self,
        strategy_evaluator: Callable[[Dict[str, Any], int, int], List[float]],
        space: HyperparameterSpace,
        benchmark_sr: float = 0.0,
        min_dsr_threshold: float = 0.90,
        max_degradation_tolerance: float = 0.50,
    ) -> None:
        """
        Args:
            strategy_evaluator: callable(params, start_bar, end_bar) -> returns list
            space: HyperparameterSpace definition
            benchmark_sr: Benchmark Sharpe ratio
            min_dsr_threshold: Minimum DSR required (e.g. 0.90 or 0.95)
            max_degradation_tolerance: Maximum allowable drop in OOS Sharpe vs IS Sharpe
        """
        self.evaluator = strategy_evaluator
        self.space = space
        self.benchmark_sr = benchmark_sr
        self.min_dsr_threshold = min_dsr_threshold
        self.max_degradation_tolerance = max_degradation_tolerance

    def optimize_walk_forward(
        self,
        total_bars: int,
        n_splits: int = 3,
        max_trials: int = 20,
        method: SplitMethod = SplitMethod.ANCHORED,
    ) -> Tuple[List[StrategyTrial], Optional[StrategyTrial]]:
        """Run walk-forward optimization across parameter candidates.
        
        Returns:
            (all_trials_sorted_by_dsr, best_robust_trial)
        """
        splitter = WalkForwardSplitter(
            total_bars=total_bars,
            n_splits=n_splits,
            method=method,
        )
        folds = splitter.generate_folds()
        if not folds:
            # Fallback single fold
            folds = [WalkForwardFold(0, 0, int(total_bars * 0.7), int(total_bars * 0.7), total_bars)]

        param_grid = self.space.generate_grid(max_combinations=max_trials)
        raw_trials: List[StrategyTrial] = []
        is_sharpes: List[float] = []

        # Step 1: Run In-Sample and Out-of-Sample evaluation for all candidates
        for idx, params in enumerate(param_grid):
            trial_id = f"TRIAL-{idx+1:03d}"
            fold_is_sharpes: List[float] = []
            fold_oos_sharpes: List[float] = []
            fold_is_returns: List[float] = []
            fold_oos_returns: List[float] = []

            for fold in folds:
                train_rets = self.evaluator(params, fold.train_start, fold.train_end)
                test_rets = self.evaluator(params, fold.test_start, fold.test_end)

                fold_is_returns.extend(train_rets)
                fold_oos_returns.extend(test_rets)

                fold_is_sharpes.append(compute_sharpe_ratio(train_rets))
                fold_oos_sharpes.append(compute_sharpe_ratio(test_rets))

            avg_is_sr = sum(fold_is_sharpes) / len(fold_is_sharpes) if fold_is_sharpes else 0.0
            avg_oos_sr = sum(fold_oos_sharpes) / len(fold_oos_sharpes) if fold_oos_sharpes else 0.0
            
            _, _, skew, kurt = compute_sample_moments(fold_is_returns)
            sample_len = len(fold_is_returns)

            # Simple PnL and metrics
            is_pnl = sum(fold_is_returns)
            oos_pnl = sum(fold_oos_returns)
            win_count = sum(1 for r in fold_is_returns if r > 0)
            win_rate = win_count / max(1, len(fold_is_returns))

            # Cumulative drawdown
            peak = 0.0
            cum = 0.0
            max_dd = 0.0
            for r in fold_is_returns:
                cum += r
                if cum > peak:
                    peak = cum
                dd = (peak - cum) / max(1.0, abs(peak))
                if dd > max_dd:
                    max_dd = dd

            trial = StrategyTrial(
                trial_id=trial_id,
                params=params,
                in_sample_sharpe=avg_is_sr,
                out_of_sample_sharpe=avg_oos_sr,
                in_sample_net_pnl=is_pnl,
                out_of_sample_net_pnl=oos_pnl,
                max_drawdown_pct=max_dd * 100.0,
                win_rate=win_rate,
                sample_size=sample_len,
                skewness=skew,
                kurtosis=kurt,
            )
            raw_trials.append(trial)
            is_sharpes.append(avg_is_sr)

        # Step 2: Compute Variance of IS Sharpe Ratios across all trials
        num_trials = len(raw_trials)
        if num_trials > 1:
            mean_sr = sum(is_sharpes) / num_trials
            sr_var = sum((s - mean_sr) ** 2 for s in is_sharpes) / (num_trials - 1)
        else:
            sr_var = 1.0

        # Step 3: Compute PSR, DSR, and Overfitting Flags
        for trial in raw_trials:
            trial.probabilistic_sharpe_ratio = compute_probabilistic_sharpe_ratio(
                observed_sr=trial.in_sample_sharpe,
                benchmark_sr=self.benchmark_sr,
                sample_size=trial.sample_size,
                skewness=trial.skewness,
                kurtosis=trial.kurtosis,
            )
            trial.deflated_sharpe_ratio = compute_deflated_sharpe_ratio(
                observed_sr=trial.in_sample_sharpe,
                num_trials=num_trials,
                trials_sr_variance=sr_var,
                sample_size=trial.sample_size,
                skewness=trial.skewness,
                kurtosis=trial.kurtosis,
            )

            # Check Overfitting:
            # 1. OOS Sharpe drops by more than max_degradation_tolerance of IS Sharpe
            # 2. Or OOS Sharpe turns negative while IS Sharpe is positive
            if trial.in_sample_sharpe > 0:
                degradation = (trial.in_sample_sharpe - trial.out_of_sample_sharpe) / trial.in_sample_sharpe
                if degradation > self.max_degradation_tolerance or trial.out_of_sample_sharpe < 0:
                    trial.is_overfitted = True
                    trial.notes = f"Degradation {degradation*100:.1f}% exceeds tolerance"
            else:
                trial.is_overfitted = True
                trial.notes = "In-sample Sharpe non-positive"

        # Sort trials by Deflated Sharpe Ratio descending, then Out-of-Sample Sharpe
        sorted_trials = sorted(
            raw_trials,
            key=lambda t: (t.deflated_sharpe_ratio, t.out_of_sample_sharpe),
            reverse=True,
        )

        # Select best robust trial (not overfitted and meeting DSR threshold)
        best_trial: Optional[StrategyTrial] = None
        for t in sorted_trials:
            if not t.is_overfitted and t.deflated_sharpe_ratio >= self.min_dsr_threshold:
                best_trial = t
                break
        
        # If none met strict DSR threshold, pick top non-overfitted trial with positive OOS
        if best_trial is None:
            for t in sorted_trials:
                if not t.is_overfitted and t.out_of_sample_sharpe > 0:
                    best_trial = t
                    break

        return sorted_trials, best_trial
