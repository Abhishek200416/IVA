"""Lee-Mykland (2008) High-Frequency Jump Detection & Intraday Co-Jump Engine.

Implements Suzanne Lee & Per Mykland's non-parametric jump test statistic,
realized bipower variation (Barndorff-Nielsen & Shephard, 2004) continuous volatility,
Gumbel extreme value distribution thresholding, cross-market co-jump detection,
and automated options market-making short gamma freeze circuit breakers.

References:
- Lee, S. S., & Mykland, P. A. (2008). Jumps in Financial Markets: A New Nonparametric
  Test and Jump Dynamics. The Review of Financial Studies, 21(6), 2535-2563.
- Barndorff-Nielsen, O. E., & Shephard, N. (2004). Power and bipower variation
  with stochastic volatility and jumps. Journal of Financial Econometrics, 2(1), 1-38.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class JumpRegime(Enum):
    """Classification of price motion regime."""
    NORMAL_DIFFUSION = "NORMAL_DIFFUSION"      # Continuous Brownian motion (no jump)
    MODERATE_JUMP = "MODERATE_JUMP"            # Test statistic exceeds critical threshold
    EXTREME_JUMP = "EXTREME_JUMP"              # Test statistic exceeds 1.5x critical threshold


class JumpDirection(Enum):
    """Direction of discrete price jump."""
    NONE = "NONE"
    POSITIVE_JUMP = "POSITIVE_JUMP"
    NEGATIVE_JUMP = "NEGATIVE_JUMP"


class JumpCircuitBreakerStatus(Enum):
    """Options risk circuit breaker state."""
    NORMAL = "NORMAL"                          # Normal continuous trading
    SHORT_GAMMA_FREEZE = "SHORT_GAMMA_FREEZE"  # Immediate halt on short options quoting
    COOLDOWN = "COOLDOWN"                      # Post-jump cooldown period


@dataclass(frozen=True)
class JumpDetectionResult:
    """Result of Lee-Mykland jump detection test for a single observation."""
    timestamp: str
    symbol: str
    price: float
    previous_price: float
    log_return: float
    bipower_volatility: float
    test_statistic_l: float
    critical_threshold: float
    jump_detected: bool
    jump_size: float
    jump_sign: int                             # +1 for upward jump, -1 for downward, 0 for none
    regime: JumpRegime
    confidence_level: float                    # 1 - alpha (e.g. 0.99)
    direction: JumpDirection = JumpDirection.NONE
    circuit_breaker_status: JumpCircuitBreakerStatus = JumpCircuitBreakerStatus.NORMAL

    @property
    def is_jump(self) -> bool:
        """Alias for jump_detected."""
        return self.jump_detected


@dataclass(frozen=True)
class CoJumpEvent:
    """Multi-asset cross-market co-jump detection event."""
    timestamp: str
    jumping_symbols: Tuple[str, ...]
    asset_results: Dict[str, JumpDetectionResult]
    is_co_jump: bool                           # True if >= min_cojump_assets detected
    concordance_ratio: float                   # Ratio of directional agreement
    freeze_short_gamma: bool                   # True if risk circuit breaker triggered
    recommended_lockout_seconds: int           # Cooldown window for short volatility quoting
    is_concordant: bool = True
    co_jump_severity: float = 0.0
    primary_result: Optional[JumpDetectionResult] = None
    secondary_result: Optional[JumpDetectionResult] = None


class LeeMyklandJumpDetector:
    """Suzanne Lee & Per Mykland (2008) Non-Parametric Intraday Jump Detector."""

    # E[|Z|] for standard normal Z = sqrt(2 / pi)
    C_CONSTANT: float = math.sqrt(2.0 / math.pi)

    def __init__(
        self,
        window_size_k: int = 16,
        bipower_window_k: Optional[int] = None,
        significance_alpha: float = 0.01,
        session_observations_n: int = 375,      # 375 1-min bars in standard NSE session
        cooldown_bars: int = 3,
        volatility_floor: float = 1e-6,
    ) -> None:
        """
        Args:
            window_size_k: Local window size for bipower variation (K >= 4, default 16).
            bipower_window_k: Alias for window_size_k.
            significance_alpha: Test significance level (default 0.01 for 99% confidence).
            session_observations_n: Total observations per session N used for Gumbel scaling.
            cooldown_bars: Number of subsequent ticks to maintain COOLDOWN state.
            volatility_floor: Minimum volatility denominator to prevent division by zero.
        """
        k = bipower_window_k if bipower_window_k is not None else window_size_k
        if k < 4:
            raise ValueError("window_size_k must be >= 4 for bipower variation estimation")
        if not (0.0 < significance_alpha < 1.0):
            raise ValueError("significance_alpha must be strictly between 0 and 1")
        if session_observations_n < 10:
            raise ValueError("session_observations_n must be >= 10")

        self.k = k
        self.alpha = significance_alpha
        self.n = session_observations_n
        self.cooldown_bars = cooldown_bars
        self.vol_floor = volatility_floor

        self.return_history: List[float] = []
        self.price_history: List[Tuple[float, float]] = []
        self._cooldown_remaining: int = 0

        # Precompute Gumbel extreme value threshold parameters
        self._c_n, self._s_n, self._beta_star, self._threshold = self._compute_threshold_constants(
            self.n, self.alpha
        )

    @classmethod
    def _compute_threshold_constants(
        cls, n: int, alpha: float
    ) -> Tuple[float, float, float, float]:
        """Compute asymptotic Gumbel threshold constants C_n, S_n, beta*, and critical value."""
        c = cls.C_CONSTANT
        log_n = math.log(max(10, n))
        sqrt_2log_n = math.sqrt(2.0 * log_n)

        # S_n = 1 / (c * sqrt(2 * ln(n)))
        s_n = 1.0 / (c * sqrt_2log_n)

        # C_n = sqrt(2 * ln(n)) / c - (ln(pi) + ln(ln(n))) / (2 * c * sqrt(2 * ln(n)))
        log_log_n = math.log(log_n)
        term1 = sqrt_2log_n / c
        term2 = (math.log(math.pi) + log_log_n) / (2.0 * c * sqrt_2log_n)
        c_n = term1 - term2

        # beta* = -ln(-ln(1 - alpha))
        beta_star = -math.log(-math.log(1.0 - alpha))

        # Critical threshold T_n = C_n + beta* * S_n
        critical_threshold = c_n + beta_star * s_n
        return c_n, s_n, beta_star, critical_threshold

    @property
    def critical_threshold(self) -> float:
        """Precomputed critical test statistic threshold."""
        return self._threshold

    def calculate_gumbel_threshold(self, n_sample_size: int = 375) -> float:
        """Compute Gumbel threshold for a given sample size n."""
        _, _, _, threshold = self._compute_threshold_constants(n_sample_size, self.alpha)
        return threshold

    def calculate_bipower_variation(self, log_returns_window: List[float]) -> float:
        """Compute Realized Bipower Variation (BV) continuous volatility estimator.
        
        Formula (Barndorff-Nielsen & Shephard, 2004; Lee & Mykland, 2008 eq 11):
            sigma^2(t_i) = 1/(K - 2) * (1 / c^2) * sum_{j=i-K+2}^{i-1} |r_j| * |r_{j-1}|
        where c = sqrt(2 / pi), so 1 / c^2 = pi / 2.
        """
        m = len(log_returns_window)
        if m < 2:
            return self.vol_floor

        product_sum = sum(
            abs(log_returns_window[j]) * abs(log_returns_window[j - 1])
            for j in range(1, m)
        )

        divisor = max(1, m - 1)
        inv_c_squared = math.pi / 2.0
        bv_variance = (inv_c_squared / divisor) * product_sum

        bv_vol = math.sqrt(max(0.0, bv_variance))
        return max(self.vol_floor, bv_vol)

    def calculate_bipower_volatility(self) -> float:
        """Calculate bipower volatility from internal return history."""
        if len(self.return_history) < 2:
            return self.vol_floor
        window = self.return_history[-self.k :]
        return self.calculate_bipower_variation(window)

    def test_single_observation(
        self,
        current_price: float,
        previous_price: float,
        prior_returns_window: List[float],
        timestamp: str = "",
        symbol: str = "BANKNIFTY",
    ) -> JumpDetectionResult:
        """Perform Lee-Mykland jump test for a single observation against its prior return window."""
        if current_price <= 0 or previous_price <= 0:
            raise ValueError("Prices must be strictly positive")

        log_return = math.log(current_price / previous_price)
        bv_vol = self.calculate_bipower_variation(prior_returns_window)

        # Test statistic L(t_i) = r_{t_i} / sigma_{t_i}
        test_stat = log_return / max(1e-9, bv_vol)
        abs_stat = abs(test_stat)

        jump_detected = abs_stat > self._threshold
        jump_size = log_return if jump_detected else 0.0
        jump_sign = (1 if log_return > 0 else -1) if jump_detected else 0

        if abs_stat > 1.5 * self._threshold:
            regime = JumpRegime.EXTREME_JUMP
        elif jump_detected:
            regime = JumpRegime.MODERATE_JUMP
        else:
            regime = JumpRegime.NORMAL_DIFFUSION

        direction = JumpDirection.NONE
        if jump_detected:
            direction = JumpDirection.POSITIVE_JUMP if log_return > 0 else JumpDirection.NEGATIVE_JUMP
            cb_status = JumpCircuitBreakerStatus.SHORT_GAMMA_FREEZE
            self._cooldown_remaining = self.cooldown_bars
        else:
            if self._cooldown_remaining > 0:
                cb_status = JumpCircuitBreakerStatus.COOLDOWN
                self._cooldown_remaining -= 1
            else:
                cb_status = JumpCircuitBreakerStatus.NORMAL

        return JumpDetectionResult(
            timestamp=timestamp,
            symbol=symbol,
            price=current_price,
            previous_price=previous_price,
            log_return=log_return,
            bipower_volatility=bv_vol,
            test_statistic_l=test_stat,
            critical_threshold=self._threshold,
            jump_detected=jump_detected,
            jump_size=jump_size,
            jump_sign=jump_sign,
            regime=regime,
            confidence_level=1.0 - self.alpha,
            direction=direction,
            circuit_breaker_status=cb_status,
        )

    def process_tick(self, timestamp: float, price: float) -> Optional[JumpDetectionResult]:
        """Process a streaming tick using internal price history."""
        if price <= 0:
            raise ValueError("Price must be strictly positive")

        if not self.price_history:
            self.price_history.append((timestamp, price))
            return None

        _, prev_price = self.price_history[-1]
        prior_window = self.return_history[-self.k :] if self.return_history else []

        res = self.test_single_observation(
            current_price=price,
            previous_price=prev_price,
            prior_returns_window=prior_window,
            timestamp=str(timestamp),
        )

        log_ret = math.log(price / prev_price)
        self.return_history.append(log_ret)
        self.price_history.append((timestamp, price))
        return res

    def detect_jumps_in_series(
        self,
        prices: List[float],
        timestamps: Optional[List[str]] = None,
        symbol: str = "BANKNIFTY",
    ) -> List[JumpDetectionResult]:
        """Detect jumps in a full price series using a rolling window of prior returns."""
        if len(prices) < 2:
            return []

        ts = timestamps if timestamps is not None and len(timestamps) == len(prices) else [
            f"T{i}" for i in range(len(prices))
        ]

        log_returns = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
        ]

        results: List[JumpDetectionResult] = []
        for i in range(1, len(prices)):
            window_start = max(0, (i - 1) - self.k)
            prior_window = log_returns[window_start : (i - 1)]

            result = self.test_single_observation(
                current_price=prices[i],
                previous_price=prices[i - 1],
                prior_returns_window=prior_window,
                timestamp=ts[i],
                symbol=symbol,
            )
            results.append(result)

        return results


class IntradayCoJumpEngine:
    """Synchronized Multi-Asset Co-Jump Detection Engine."""

    def __init__(
        self,
        primary_symbol: str = "BANKNIFTY-SPOT",
        secondary_symbol: str = "BANKNIFTY-FUT",
        bipower_window_k: int = 16,
        window_size_k: Optional[int] = None,
        significance_alpha: float = 0.01,
        cooldown_bars: int = 3,
        lockout_duration_seconds: int = 300,
        detector: Optional[LeeMyklandJumpDetector] = None,
        min_cojump_assets: int = 2,
    ) -> None:
        k = window_size_k if window_size_k is not None else bipower_window_k
        self.primary_symbol = primary_symbol
        self.secondary_symbol = secondary_symbol
        self.lockout_duration = lockout_duration_seconds
        self.min_cojump_assets = min_cojump_assets

        self.primary_detector = LeeMyklandJumpDetector(
            window_size_k=k,
            significance_alpha=significance_alpha,
            cooldown_bars=cooldown_bars,
        )
        self.secondary_detector = LeeMyklandJumpDetector(
            window_size_k=k,
            significance_alpha=significance_alpha,
            cooldown_bars=cooldown_bars,
        )
        self.detector = detector or self.primary_detector

    def process_synchronized_tick(
        self,
        timestamp: float,
        price_primary: float,
        price_secondary: float,
    ) -> Tuple[Optional[JumpDetectionResult], Optional[JumpDetectionResult], Optional[CoJumpEvent]]:
        """Process simultaneous ticks on primary and secondary assets."""
        res_prim = self.primary_detector.process_tick(timestamp, price_primary)
        res_sec = self.secondary_detector.process_tick(timestamp, price_secondary)

        co_event = None
        if res_prim and res_sec and res_prim.is_jump and res_sec.is_jump:
            is_concordant = (res_prim.direction == res_sec.direction)
            co_severity = (abs(res_prim.test_statistic_l) + abs(res_sec.test_statistic_l)) / 2.0
            jumping_symbols = (self.primary_symbol, self.secondary_symbol)
            asset_results = {
                self.primary_symbol: res_prim,
                self.secondary_symbol: res_sec,
            }
            co_event = CoJumpEvent(
                timestamp=str(timestamp),
                jumping_symbols=jumping_symbols,
                asset_results=asset_results,
                is_co_jump=True,
                concordance_ratio=1.0 if is_concordant else 0.5,
                freeze_short_gamma=True,
                recommended_lockout_seconds=self.lockout_duration,
                is_concordant=is_concordant,
                co_jump_severity=co_severity,
                primary_result=res_prim,
                secondary_result=res_sec,
            )

        return res_prim, res_sec, co_event

    def evaluate_multi_asset_tick(
        self,
        observations: Dict[str, Tuple[float, float, List[float]]],
        timestamp: str = "",
    ) -> CoJumpEvent:
        """Evaluate simultaneous multi-asset observations for co-jumps."""
        results: Dict[str, JumpDetectionResult] = {}
        jumping_symbols_list: List[str] = []

        for sym, (curr_p, prev_p, window) in observations.items():
            res = self.detector.test_single_observation(
                current_price=curr_p,
                previous_price=prev_p,
                prior_returns_window=window,
                timestamp=timestamp,
                symbol=sym,
            )
            results[sym] = res
            if res.jump_detected:
                jumping_symbols_list.append(sym)

        is_co_jump = len(jumping_symbols_list) >= self.min_cojump_assets

        concordance = 1.0
        if len(jumping_symbols_list) > 1:
            signs = [results[s].jump_sign for s in jumping_symbols_list]
            positive_count = sum(1 for s in signs if s > 0)
            negative_count = sum(1 for s in signs if s < 0)
            concordance = max(positive_count, negative_count) / len(signs)

        freeze_gamma = is_co_jump or any(
            r.regime == JumpRegime.EXTREME_JUMP for r in results.values()
        )

        severity = 0.0
        if jumping_symbols_list:
            severity = sum(abs(results[s].test_statistic_l) for s in jumping_symbols_list) / len(jumping_symbols_list)

        return CoJumpEvent(
            timestamp=timestamp,
            jumping_symbols=tuple(jumping_symbols_list),
            asset_results=results,
            is_co_jump=is_co_jump,
            concordance_ratio=round(concordance, 4),
            freeze_short_gamma=freeze_gamma,
            recommended_lockout_seconds=self.lockout_duration if freeze_gamma else 0,
            is_concordant=(concordance >= 0.8),
            co_jump_severity=severity,
        )


# Backward-compatible alias
CoJumpDetectionEngine = IntradayCoJumpEngine

