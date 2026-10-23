"""Cycle 34: state-conditioned SVI, queue depletion, BOCPD and offline telemetry.

Standard-library-only research reference. Live order dispatch is deliberately absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import exp, expm1, hypot, isfinite, lgamma, log, log1p, pi, sqrt
from threading import Thread, Event
from time import time, sleep
from typing import Any, Callable, Iterable, Optional, Sequence
import json

LIVE_ORDER_DISPATCH_ENABLED = False
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Fail-closed barrier preventing live execution during paper simulation."""
    if not LIVE_ORDER_DISPATCH_ENABLED:
        raise RuntimeError("live order dispatch is permanently disabled in paper simulation mode")


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _nonnegative(value: float, name: str) -> float:
    value = _finite(value, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _logsumexp(values: Sequence[float]) -> float:
    if not values:
        return float("-inf")
    m = max(values)
    if m == float("-inf"):
        return m
    return m + log(sum(exp(v - m) for v in values))


# ---------------------------------------------------------------------------
# State-conditioned SVI surface
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MicrostructureState:
    ofi_norm: float = 0.0
    hawkes_intensity_ratio: float = 1.0
    spread_ratio: float = 1.0
    queue_imbalance: float = 0.0

    def vector(self) -> tuple[float, float, float, float]:
        x = tuple(_finite(v, n) for v, n in zip(
            (self.ofi_norm, self.hawkes_intensity_ratio, self.spread_ratio, self.queue_imbalance),
            ("ofi_norm", "hawkes_intensity_ratio", "spread_ratio", "queue_imbalance"),
        ))
        if not -1.0 <= x[0] <= 1.0:
            raise ValueError("ofi_norm must be in [-1, 1]")
        if x[1] < 0:
            raise ValueError("hawkes_intensity_ratio must be nonnegative")
        if x[2] <= 0:
            raise ValueError("spread_ratio must be positive")
        if not -1.0 <= x[3] <= 1.0:
            raise ValueError("queue_imbalance must be in [-1, 1]")
        return x  # type: ignore[return-value]


@dataclass(frozen=True)
class SVIParams:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def __post_init__(self) -> None:
        for name in ("a", "b", "rho", "m", "sigma"):
            _finite(getattr(self, name), name)
        if self.b < 0:
            raise ValueError("SVI b must be nonnegative")
        if not abs(self.rho) < 1.0:
            raise ValueError("SVI rho must satisfy |rho| < 1")
        if self.sigma <= 0:
            raise ValueError("SVI sigma must be positive")
        if self.minimum_total_variance() < -1e-12:
            raise ValueError("SVI minimum total variance must be nonnegative")

    def minimum_total_variance(self) -> float:
        return self.a + self.b * self.sigma * sqrt(max(0.0, 1.0 - self.rho * self.rho))

    def total_variance(self, k: float) -> float:
        k = _finite(k, "k")
        x = k - self.m
        return self.a + self.b * (self.rho * x + hypot(x, self.sigma))

    def derivatives(self, k: float) -> tuple[float, float]:
        """Analytical w'(k), w''(k) for the SVI total-variance smile."""
        x = _finite(k, "k") - self.m
        d = hypot(x, self.sigma)
        first = self.b * (self.rho + x / d)
        second = self.b * self.sigma * self.sigma / (d ** 3)
        return first, second

    def butterfly_g(self, k: float) -> float:
        """Durrleman-Gatheral g(k), where nonnegative values are a sampled check."""
        w = self.total_variance(k)
        if w <= 1e-14:
            return float("-inf")
        wp, wpp = self.derivatives(k)
        return (1.0 - k * wp / (2.0 * w)) ** 2 - (wp * wp / 4.0) * (1.0 / w + 0.25) + 0.5 * wpp

    def validate_no_arbitrage(
        self, strikes: Optional[Sequence[float]] = None, *, tolerance: float = 1e-8
    ) -> float:
        """Validate basic SVI constraints and sampled butterfly g(k) >= -tolerance.

        This finite-grid diagnostic is not a proof of global continuous-strike
        arbitrage freedom. For production model approval, use a validated global test.
        """
        if self.b < 0 or not abs(self.rho) < 1 or self.sigma <= 0:
            raise ValueError("invalid SVI parameter bounds")
        if self.minimum_total_variance() < 0:
            raise ValueError("negative minimum total variance")
        grid = tuple(strikes) if strikes is not None else tuple(-5.0 + i * 0.05 for i in range(201))
        if not grid:
            raise ValueError("strike grid cannot be empty")
        values = [self.butterfly_g(k) for k in grid]
        if any(not isfinite(v) or v < -tolerance for v in values):
            raise ValueError("sampled butterfly-arbitrage diagnostic failed")
        return min(values)


@dataclass(frozen=True)
class SVIConditioningResult:
    params: SVIParams
    deltas: tuple[float, float, float, float, float]
    min_sampled_g: float


class MicrostructureSVIConditioner:
    """Linear state-to-parameter mapping with explicit fail-closed validation."""
    DEFAULT_WEIGHTS: tuple[tuple[float, ...], ...] = (
        (0.004, 0.003, 0.002, 0.002),   # a
        (0.020, 0.004, 0.010, -0.003),  # b; positive OFI expands right wing
        (-0.030, -0.006, 0.003, -0.012),# rho; aggressive buys rotate rho down
        (0.006, 0.001, 0.002, 0.001),   # m
        (0.002, 0.002, 0.004, 0.001),   # sigma
    )

    def __init__(self, weights: Optional[Sequence[Sequence[float]]] = None,
                 strike_grid: Optional[Sequence[float]] = None):
        raw = weights if weights is not None else self.DEFAULT_WEIGHTS
        matrix = tuple(tuple(_finite(v, "weight") for v in row) for row in raw)
        if len(matrix) != 5 or any(len(row) != 4 for row in matrix):
            raise ValueError("weights must be a 5x4 matrix")
        self.weights = matrix
        self.strike_grid = tuple(strike_grid) if strike_grid is not None else tuple(-5.0 + i * 0.05 for i in range(201))
        if not self.strike_grid:
            raise ValueError("strike_grid cannot be empty")

    def condition(self, base: SVIParams, state: MicrostructureState) -> SVIConditioningResult:
        x = state.vector()
        delta = tuple(sum(self.weights[i][j] * x[j] for j in range(4)) for i in range(5))
        params = SVIParams(
            a=base.a + delta[0], b=base.b + delta[1], rho=base.rho + delta[2],
            m=base.m + delta[3], sigma=base.sigma + delta[4],
        )
        # Fail closed rather than silently altering the requested linear shift.
        min_g = params.validate_no_arbitrage(self.strike_grid)
        return SVIConditioningResult(params=params, deltas=delta, min_sampled_g=min_g)


# ---------------------------------------------------------------------------
# L1-L5 queue depletion with clustered jump events
# ---------------------------------------------------------------------------

@dataclass
class QueueLevelState:
    level: int
    price: float
    q_ahead: float
    q_behind: float
    created_at: float
    last_update_at: float
    survival_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not 1 <= int(self.level) <= 5:
            raise ValueError("queue level must be between 1 and 5")
        _finite(self.price, "price")
        if self.price <= 0:
            raise ValueError("price must be positive")
        _nonnegative(self.q_ahead, "q_ahead")
        _nonnegative(self.q_behind, "q_behind")
        _finite(self.created_at, "created_at")
        _finite(self.last_update_at, "last_update_at")

    @property
    def total_at_level(self) -> float:
        return self.q_ahead + self.q_behind


@dataclass(frozen=True)
class DepletionJump:
    alpha: float
    beta: float
    timestamp: float

    def __post_init__(self) -> None:
        _nonnegative(self.alpha, "alpha")
        if _finite(self.beta, "beta") <= 0:
            raise ValueError("beta must be positive")
        _finite(self.timestamp, "timestamp")


class QueueDepletionMachine:
    def __init__(self, lambda0: float = 0.1, gamma_ofi: float = 0.5):
        self.lambda0 = _nonnegative(lambda0, "lambda0")
        self.gamma_ofi = _nonnegative(gamma_ofi, "gamma_ofi")
        self.levels: dict[int, QueueLevelState] = {}
        self.jumps: list[DepletionJump] = []
        self.last_intensity: float = self.lambda0
        self.last_update_at: Optional[float] = None

    def set_level(self, level: int, price: float, q_ahead: float, q_behind: float,
                  now: float) -> QueueLevelState:
        now = _finite(now, "now")
        old = self.levels.get(level)
        state = QueueLevelState(level, price, q_ahead, q_behind,
                                old.created_at if old else now, now,
                                max(0.0, now - (old.created_at if old else now)))
        self.levels[level] = state
        self.last_update_at = now
        return state

    def update_quantities(self, level: int, *, delta_ahead: float = 0.0,
                          delta_behind: float = 0.0, now: float) -> QueueLevelState:
        if level not in self.levels:
            raise KeyError(f"unknown queue level {level}")
        old = self.levels[level]
        da = _finite(delta_ahead, "delta_ahead")
        db = _finite(delta_behind, "delta_behind")
        now = _finite(now, "now")
        if now < old.last_update_at:
            raise ValueError("queue timestamps must be monotonic")
        state = QueueLevelState(level, old.price, max(0.0, old.q_ahead + da),
                                max(0.0, old.q_behind + db), old.created_at, now,
                                max(0.0, now - old.created_at))
        self.levels[level] = state
        self.last_update_at = now
        return state

    def add_jump(self, alpha: float, beta: float, now: float) -> None:
        now = _finite(now, "now")
        jump = DepletionJump(alpha, beta, now)
        self.jumps.append(jump)
        # Keep bounded memory: events with negligible current contribution are pruned on intensity updates.

    def intensity(self, *, now: float, ofi: float = 0.0) -> float:
        now = _finite(now, "now")
        ofi = _finite(ofi, "ofi")
        if self.last_update_at is not None and now < self.last_update_at:
            raise ValueError("intensity time must be monotonic")
        total = self.lambda0 + self.gamma_ofi * max(0.0, -ofi)
        retained: list[DepletionJump] = []
        for jump in self.jumps:
            age = now - jump.timestamp
            if age < 0:
                raise ValueError("jump timestamp is in the future")
            contribution = jump.alpha * exp(-jump.beta * age)
            total += contribution
            if contribution > 1e-10:
                retained.append(jump)
        self.jumps = retained
        if not isfinite(total):
            raise ValueError("depletion intensity overflowed")
        self.last_intensity = total
        self.last_update_at = now
        return total

    def depletion_velocity(self, *, now: float, ofi: float = 0.0) -> float:
        return self.intensity(now=now, ofi=ofi)

    def adverse_selection_probability(self, ofi: float, cross_spillover: float = 0.0,
                                      side: str = "BUY", sensitivity: float = 1.0) -> float:
        flow = _finite(ofi, "ofi") + _finite(cross_spillover, "cross_spillover")
        sensitivity = _nonnegative(sensitivity, "sensitivity")
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        adverse_direction = max(0.0, -flow) if side == "BUY" else max(0.0, flow)
        return _clamp(1.0 - exp(-sensitivity * adverse_direction), 0.0, 1.0)

    def fill_probability(self, q_ahead: float, horizon: float, *, now: float,
                         ofi: float = 0.0, cross_spillover: float = 0.0,
                         side: str = "BUY") -> float:
        q = _nonnegative(q_ahead, "q_ahead")
        horizon = _nonnegative(horizon, "horizon")
        lam = self.intensity(now=now, ofi=ofi)
        raw = -expm1(-lam * horizon / (1.0 + q))
        adv = self.adverse_selection_probability(ofi, cross_spillover, side)
        return _clamp(raw * (1.0 - adv), 0.0, 1.0)

    def expected_fill_latency(self, q_ahead: float, *, now: float, ofi: float = 0.0) -> float:
        q = _nonnegative(q_ahead, "q_ahead")
        lam = self.intensity(now=now, ofi=ofi)
        return float("inf") if lam <= 0 else (1.0 + q) / lam

    def should_reposition(self, q_ahead: float, horizon: float, *, now: float,
                          eta_reposition: float, cancel_replace_hazard: float,
                          ofi: float = 0.0, cross_spillover: float = 0.0,
                          side: str = "BUY") -> bool:
        eta = _finite(eta_reposition, "eta_reposition")
        hazard = _finite(cancel_replace_hazard, "cancel_replace_hazard")
        if not 0 <= eta <= 1 or not 0 <= hazard <= 1:
            raise ValueError("probability thresholds must be in [0, 1]")
        pfill = self.fill_probability(q_ahead, horizon, now=now, ofi=ofi,
                                     cross_spillover=cross_spillover, side=side)
        adverse = self.adverse_selection_probability(ofi, cross_spillover, side)
        return pfill < eta and (eta - pfill) > hazard + 0.25 * adverse

    def telemetry(self) -> dict[str, Any]:
        return {
            "depletion_intensity": self.last_intensity,
            "levels": [asdict(self.levels[k]) for k in sorted(self.levels)],
            "active_jump_count": len(self.jumps),
            "expected_fill_latency_l1": (lambda v: v if isfinite(v) else None)(self.expected_fill_latency(self.levels.get(1, QueueLevelState(1, 1.0, 0, 0, 0, 0)).q_ahead,
                                                                    now=max(self.last_update_at or 0.0, 0.0))),
        }


# ---------------------------------------------------------------------------
# Bayesian Online Changepoint Detection using Normal-Inverse-Gamma conjugacy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NIGStats:
    mu: float = 0.0
    kappa: float = 1.0
    alpha: float = 2.0
    beta: float = 1.0

    def __post_init__(self) -> None:
        _finite(self.mu, "mu")
        if _finite(self.kappa, "kappa") <= 0:
            raise ValueError("kappa must be positive")
        if _finite(self.alpha, "alpha") <= 0:
            raise ValueError("alpha must be positive")
        if _finite(self.beta, "beta") <= 0:
            raise ValueError("beta must be positive")


def nig_update(stats: NIGStats, x: float) -> NIGStats:
    x = _finite(x, "observation")
    kn = stats.kappa + 1.0
    mun = (stats.kappa * stats.mu + x) / kn
    an = stats.alpha + 0.5
    bn = stats.beta + stats.kappa * (x - stats.mu) ** 2 / (2.0 * kn)
    return NIGStats(mun, kn, an, bn)


def nig_predictive_logpdf(x: float, stats: NIGStats) -> float:
    """Student-t posterior predictive log density induced by a Normal-Inverse-Gamma prior."""
    x = _finite(x, "observation")
    df = 2.0 * stats.alpha
    scale2 = stats.beta * (stats.kappa + 1.0) / (stats.alpha * stats.kappa)
    scale = sqrt(scale2)
    diff = abs(x - stats.mu)
    if diff == 0.0:
        log_one_plus_ratio_sq = 0.0
    elif not isfinite(diff):
        raise ValueError("observation difference exceeds numeric range")
    else:
        log_ratio = log(diff) - log(scale) - 0.5 * log(df)
        # Stable log(1 + exp(2*log_ratio)) avoids squaring a huge z-score.
        log_one_plus_ratio_sq = (2.0 * log_ratio + log1p(exp(-2.0 * log_ratio))
                                 if log_ratio > 0 else log1p(exp(2.0 * log_ratio)))
    result = (lgamma((df + 1.0) / 2.0) - lgamma(df / 2.0)
              - 0.5 * log(df * pi) - log(scale)
              - ((df + 1.0) / 2.0) * log_one_plus_ratio_sq)
    if not isfinite(result):
        raise ValueError("predictive log density exceeds numeric range")
    return result


class MacroRegime(str, Enum):
    LOW_VOL_MEAN_REVERTING = "LOW_VOL_MEAN_REVERTING"
    HIGH_VOL_TRENDING = "HIGH_VOL_TRENDING"
    LIQUIDITY_CRISIS_JUMP = "LIQUIDITY_CRISIS_JUMP"


@dataclass(frozen=True)
class BOCPDResult:
    observation: float
    run_length_probabilities: tuple[float, ...]
    most_likely_run_length: int
    changepoint_probability: float
    z_score: float
    regime: MacroRegime


class BayesianOnlineChangepointDetector:
    def __init__(self, *, expected_run_length: float = 100.0,
                 prior: NIGStats = NIGStats(mu=0.0, kappa=0.05, alpha=2.5, beta=0.0004),
                 max_run_length: int = 200, crisis_z: float = 5.0,
                 high_vol_z: float = 2.5, changepoint_threshold: float = 0.25,
                 history_window: int = 50):
        er = _finite(expected_run_length, "expected_run_length")
        if er <= 1:
            raise ValueError("expected_run_length must exceed 1")
        if max_run_length < 1:
            raise ValueError("max_run_length must be >= 1")
        if history_window < 2:
            raise ValueError("history_window must be >= 2")
        self.hazard = 1.0 / er
        self.prior = prior
        self.max_run_length = int(max_run_length)
        self.crisis_z = _finite(crisis_z, "crisis_z")
        self.high_vol_z = _finite(high_vol_z, "high_vol_z")
        self.changepoint_threshold = _finite(changepoint_threshold, "changepoint_threshold")
        if not 0 < self.changepoint_threshold < 1:
            raise ValueError("changepoint_threshold must be in (0, 1)")
        self.history_window = int(history_window)
        self.run_probs: list[float] = [1.0]
        self.stats_by_run: list[NIGStats] = [prior]
        self.history: list[float] = []
        self.last_result: Optional[BOCPDResult] = None

    def update(self, observation: float) -> BOCPDResult:
        x = _finite(observation, "observation")
        preds = [nig_predictive_logpdf(x, s) for s in self.stats_by_run]
        prior_pred = nig_predictive_logpdf(x, self.prior)
        log_old = [log(max(p, 1e-300)) for p in self.run_probs]
        log_h = log(self.hazard)
        log_1mh = log1p_safe(-self.hazard)
        log_cp = _logsumexp([lp + log_h for lp in log_old]) + prior_pred
        growth_logs = [lp + log_1mh + pred for lp, pred in zip(log_old, preds)]
        all_logs = [log_cp] + growth_logs
        normalizer = _logsumexp(all_logs)
        new_probs = [exp(v - normalizer) for v in all_logs]
        new_stats = [nig_update(self.prior, x)] + [nig_update(s, x) for s in self.stats_by_run]
        self.run_probs = new_probs[: self.max_run_length + 1]
        self.stats_by_run = new_stats[: self.max_run_length + 1]
        total = sum(self.run_probs)
        self.run_probs = [max(0.0, p / total) for p in self.run_probs]
        # Re-normalize against floating-point accumulation.
        total = sum(self.run_probs)
        self.run_probs = [p / total for p in self.run_probs]
        history_for_z = self.history[-self.history_window:]
        if len(history_for_z) >= 2:
            mean = sum(history_for_z) / len(history_for_z)
            var = sum((v - mean) ** 2 for v in history_for_z) / max(1, len(history_for_z) - 1)
            scale = max(sqrt(var), sqrt(self.prior.beta / self.prior.alpha), 1e-6)
        else:
            mean = self.prior.mu
            scale = sqrt(self.prior.beta / self.prior.alpha)
        z = abs(x - mean) / max(scale, 1e-9)
        cp = self.run_probs[0]
        if z >= self.crisis_z:
            regime = MacroRegime.LIQUIDITY_CRISIS_JUMP
        elif z >= self.high_vol_z or cp >= self.changepoint_threshold:
            regime = MacroRegime.HIGH_VOL_TRENDING
        else:
            regime = MacroRegime.LOW_VOL_MEAN_REVERTING
        self.history.append(x)
        self.last_result = BOCPDResult(x, tuple(self.run_probs), max(range(len(self.run_probs)), key=self.run_probs.__getitem__), cp, z, regime)
        return self.last_result

    def telemetry(self) -> dict[str, Any]:
        if self.last_result is None:
            return {"observations": 0, "run_length_probabilities": [1.0],
                    "most_likely_run_length": 0, "changepoint_probability": 0.0,
                    "z_score": 0.0, "regime": MacroRegime.LOW_VOL_MEAN_REVERTING.value}
        r = self.last_result
        return {"observations": len(self.history),
                "run_length_probabilities": list(r.run_length_probabilities),
                "most_likely_run_length": r.most_likely_run_length,
                "changepoint_probability": r.changepoint_probability,
                "z_score": r.z_score, "regime": r.regime.value}


def log1p_safe(x: float) -> float:
    if x <= -1:
        raise ValueError("log1p argument must be greater than -1")
    return log1p(x)


# ---------------------------------------------------------------------------
# Indian statutory friction and strictly positive-alpha gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeeConfig:
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    exchange_rate: float = 3553.0 / 10_000_000.0
    sebi_rate: float = 10.0 / 10_000_000.0
    gst_rate: float = 0.18
    brokerage_per_leg: float = 0.0

    def __post_init__(self) -> None:
        for name in ("stt_sell_rate", "stamp_buy_rate", "exchange_rate", "sebi_rate", "gst_rate", "brokerage_per_leg"):
            if _nonnegative(getattr(self, name), name) > 1 and name != "brokerage_per_leg":
                raise ValueError(f"{name} appears to be an invalid rate")


@dataclass(frozen=True)
class TradeLeg:
    side: str
    premium: float
    lots: int
    lot_size: int
    half_spread_per_unit: float = 0.0
    impact_cost: float = 0.0
    brokerage: Optional[float] = None
    symbol: str = "OPTION"

    def __post_init__(self) -> None:
        if self.side.upper() not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if _nonnegative(self.premium, "premium") < 0:
            raise ValueError("premium must be nonnegative")
        if not isinstance(self.lots, int) or self.lots < 0:
            raise ValueError("lots must be a nonnegative integer")
        if not isinstance(self.lot_size, int) or self.lot_size < 1:
            raise ValueError("lot_size must be a positive integer")
        _nonnegative(self.half_spread_per_unit, "half_spread_per_unit")
        _nonnegative(self.impact_cost, "impact_cost")
        if self.brokerage is not None:
            _nonnegative(self.brokerage, "brokerage")

    @property
    def turnover(self) -> float:
        return self.premium * self.lots * self.lot_size

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size


@dataclass(frozen=True)
class FeeBreakdown:
    buy_turnover: float
    sell_turnover: float
    total_turnover: float
    stt: float
    stamp_duty: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    statutory_fees: float
    slippage: float
    impact: float
    total_hurdle: float


@dataclass(frozen=True)
class ProfitabilityResult:
    expected_gross_alpha: float
    expected_net_alpha: float
    hurdle: float
    qualifies: bool
    breakdown: FeeBreakdown


class StatutoryCostCalculator:
    def __init__(self, config: FeeConfig = FeeConfig()):
        self.config = config

    def calculate(self, legs: Sequence[TradeLeg]) -> FeeBreakdown:
        legs = tuple(legs)
        buy_turn = sum(l.turnover for l in legs if l.side.upper() == "BUY")
        sell_turn = sum(l.turnover for l in legs if l.side.upper() == "SELL")
        total = buy_turn + sell_turn
        stt = sell_turn * self.config.stt_sell_rate
        stamp = buy_turn * self.config.stamp_buy_rate
        exchange = total * self.config.exchange_rate
        sebi = total * self.config.sebi_rate
        brokerage = sum(l.brokerage if l.brokerage is not None else self.config.brokerage_per_leg for l in legs)
        gst = self.config.gst_rate * (exchange + sebi + brokerage)
        statutory = stt + stamp + exchange + sebi + gst + brokerage
        slippage = sum(l.half_spread_per_unit * l.quantity for l in legs)
        impact = sum(l.impact_cost for l in legs)
        values = (buy_turn, sell_turn, total, stt, stamp, exchange, sebi, brokerage, gst, statutory, slippage, impact, statutory + slippage + impact)
        if not all(isfinite(v) and v >= 0 for v in values):
            raise ValueError("invalid or overflowing fee calculation")
        return FeeBreakdown(buy_turn, sell_turn, total, stt, stamp, exchange, sebi, brokerage, gst, statutory, slippage, impact, statutory + slippage + impact)

    def profitability(self, expected_gross_alpha: float, legs: Sequence[TradeLeg], *, additional_impact_hurdle: float = 0.0) -> ProfitabilityResult:
        gross = _finite(expected_gross_alpha, "expected_gross_alpha")
        impact_hurdle = _nonnegative(additional_impact_hurdle, "additional_impact_hurdle")
        breakdown = self.calculate(legs)
        hurdle = breakdown.total_hurdle + impact_hurdle
        net = gross - hurdle
        return ProfitabilityResult(gross, net, hurdle, gross > hurdle, breakdown)


# ---------------------------------------------------------------------------
# Behavioral throttling and fail-closed engine
# ---------------------------------------------------------------------------

class RiskState(str, Enum):
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    ENTRY_BLOCKED = "ENTRY_BLOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class AntiOvertradingThrottler:
    def __init__(self, *, alpha: float = 1.0, cost: float = 0.1, risk_per_trade: float = 0.1,
                 loss_limit: int = 3, cooldown_seconds: float = 900.0,
                 max_daily_trades: Optional[int] = None):
        self.alpha = _finite(alpha, "alpha")
        self.cost = _finite(cost, "cost")
        self.risk_per_trade = _finite(risk_per_trade, "risk_per_trade")
        if self.risk_per_trade <= 0:
            raise ValueError("risk_per_trade must be positive")
        if loss_limit < 1:
            raise ValueError("loss_limit must be positive")
        self.loss_limit = int(loss_limit)
        self.cooldown_seconds = _nonnegative(cooldown_seconds, "cooldown_seconds")
        self.daily_cap = max(0, int(round((self.alpha - self.cost) / self.risk_per_trade)))
        if max_daily_trades is not None:
            if max_daily_trades < 0:
                raise ValueError("max_daily_trades must be nonnegative")
            self.daily_cap = min(self.daily_cap, int(max_daily_trades))
        self.trades_today = 0
        self.consecutive_losses = 0
        self.last_fill_time: Optional[float] = None
        self.last_fill_size: Optional[float] = None
        self.cooldown_until: float = 0.0
        self.lockout_reason: Optional[str] = None

    def _lock(self, now: float, reason: str) -> None:
        self.cooldown_until = max(self.cooldown_until, now + self.cooldown_seconds)
        self.lockout_reason = reason

    def record_fill(self, *, now: float, size: float, pnl: float) -> Optional[str]:
        now = _finite(now, "now")
        size = _nonnegative(size, "size")
        pnl = _finite(pnl, "pnl")
        if self.last_fill_time is not None and now < self.last_fill_time:
            raise ValueError("fill timestamps must be monotonic")
        reason = None
        if self.last_fill_time is not None and now - self.last_fill_time < 30.0:
            reason = "RAPID_FILL_PACING"
        if self.last_fill_size is not None and self.last_fill_size > 0 and size / self.last_fill_size > 1.25:
            reason = reason or "REVENGE_SIZING"
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        if self.consecutive_losses >= self.loss_limit:
            reason = reason or "LOSS_STREAK"
        self.trades_today += 1
        self.last_fill_time, self.last_fill_size = now, size
        if reason:
            self._lock(now, reason)
        return reason

    def can_enter(self, now: float) -> bool:
        now = _finite(now, "now")
        if now < self.cooldown_until:
            return False
        if self.trades_today >= self.daily_cap:
            return False
        self.lockout_reason = None
        return True

    def cooldown_remaining(self, now: float) -> float:
        return max(0.0, self.cooldown_until - _finite(now, "now"))

    def daily_reset(self) -> None:
        self.trades_today = 0
        self.consecutive_losses = 0
        self.last_fill_time = None
        self.last_fill_size = None
        self.cooldown_until = 0.0
        self.lockout_reason = None


class Cycle34ExecutionEngine:
    def __init__(self, *, base_svi: Optional[SVIParams] = None,
                 conditioner: Optional[MicrostructureSVIConditioner] = None,
                 queue_machine: Optional[QueueDepletionMachine] = None,
                 bocpd: Optional[BayesianOnlineChangepointDetector] = None,
                 cost_calculator: Optional[StatutoryCostCalculator] = None,
                 throttler: Optional[AntiOvertradingThrottler] = None):
        self.base_svi = base_svi or SVIParams(a=0.04, b=0.10, rho=-0.40, m=0.0, sigma=0.20)
        self.conditioner = conditioner or MicrostructureSVIConditioner()
        self.queue_machine = queue_machine or QueueDepletionMachine()
        self.bocpd = bocpd or BayesianOnlineChangepointDetector()
        self.cost_calculator = cost_calculator or StatutoryCostCalculator()
        self.throttler = throttler or AntiOvertradingThrottler()
        self.microstate = MicrostructureState()
        self.svi_result = self.conditioner.condition(self.base_svi, self.microstate)
        self.last_alpha: float = 0.0
        self.last_net_alpha: float = 0.0
        self.last_profitability: Optional[ProfitabilityResult] = None
        self.risk_state = RiskState.IDLE
        self.emergency_latched = False
        self.recovery_acknowledged = True
        self.last_regime = MacroRegime.LOW_VOL_MEAN_REVERTING
        self.last_update_epoch = time()
        self.heartbeat_count = 0

    @staticmethod
    def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
        dispatch_live_order(*args, **kwargs)

    def update_microstructure(self, state: MicrostructureState) -> SVIConditioningResult:
        result = self.conditioner.condition(self.base_svi, state)
        self.microstate = state
        self.svi_result = result
        self.risk_state = RiskState.MONITORING if self.risk_state == RiskState.IDLE else self.risk_state
        self.last_update_epoch = time()
        self.heartbeat_count += 1
        return result

    def update_observation(self, observation: float) -> BOCPDResult:
        result = self.bocpd.update(observation)
        self.last_regime = result.regime
        if result.regime == MacroRegime.LIQUIDITY_CRISIS_JUMP:
            self.enter_emergency("BOCPD_LIQUIDITY_CRISIS")
        elif result.regime == MacroRegime.HIGH_VOL_TRENDING and not self.emergency_latched:
            self.risk_state = RiskState.ENTRY_BLOCKED
        elif not self.emergency_latched:
            self.risk_state = RiskState.MONITORING
        self.last_update_epoch = time()
        self.heartbeat_count += 1
        return result

    def evaluate_candidate(self, expected_gross_alpha: float, legs: Sequence[TradeLeg], *, now: float,
                           additional_impact_hurdle: float = 0.0) -> ProfitabilityResult:
        now = _finite(now, "now")
        self.last_alpha = _finite(expected_gross_alpha, "expected_gross_alpha")
        if self.emergency_latched or not self.recovery_acknowledged:
            # Fail closed and do not report a positive net alpha for a blocked candidate.
            empty = self.cost_calculator.calculate(legs)
            result = ProfitabilityResult(self.last_alpha, min(0.0, self.last_alpha - empty.total_hurdle), empty.total_hurdle, False, empty)
        elif getattr(self, "last_regime", MacroRegime.LOW_VOL_MEAN_REVERTING) == MacroRegime.HIGH_VOL_TRENDING or not self.throttler.can_enter(now):
            empty = self.cost_calculator.calculate(legs)
            result = ProfitabilityResult(self.last_alpha, min(0.0, self.last_alpha - empty.total_hurdle), empty.total_hurdle, False, empty)
        else:
            self.risk_state = RiskState.MONITORING
            result = self.cost_calculator.profitability(self.last_alpha, legs, additional_impact_hurdle=additional_impact_hurdle)
        self.last_profitability = result
        self.last_net_alpha = result.expected_net_alpha if result.qualifies else min(0.0, result.expected_net_alpha)
        self.last_update_epoch = time()
        self.heartbeat_count += 1
        return result

    def record_fill(self, *, now: float, size: float, pnl: float) -> Optional[str]:
        reason = self.throttler.record_fill(now=now, size=size, pnl=pnl)
        if reason and not self.emergency_latched:
            self.risk_state = RiskState.ENTRY_BLOCKED
        self.last_update_epoch = time()
        self.heartbeat_count += 1
        return reason

    def enter_emergency(self, reason: str = "MANUAL_EMERGENCY") -> None:
        self.emergency_latched = True
        self.recovery_acknowledged = False
        self.risk_state = RiskState.EMERGENCY_UNWIND
        self.emergency_reason = str(reason)

    def recovery_ack(self, *, verified: bool) -> None:
        if not verified:
            raise PermissionError("recovery acknowledgement must be verified")
        self.emergency_latched = False
        self.recovery_acknowledged = True
        self.risk_state = RiskState.MONITORING
        self.emergency_reason = None

    def telemetry_payload(self, *, now_epoch: Optional[float] = None) -> dict[str, Any]:
        now = time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        utc_dt = datetime.fromtimestamp(now, tz=timezone.utc)
        ist_dt = utc_dt.astimezone(IST)
        queue = self.queue_machine.telemetry()
        try:
            bocpd_payload = self.bocpd.telemetry()
        except Exception:
            bocpd_payload = {"observations": 0, "run_length_probabilities": [1.0], "most_likely_run_length": 0,
                             "changepoint_probability": 0.0, "z_score": 0.0,
                             "regime": MacroRegime.LOW_VOL_MEAN_REVERTING.value}
        throttle = {
            "daily_cap": self.throttler.daily_cap,
            "trades_today": self.throttler.trades_today,
            "cooldown_remaining_seconds": self.throttler.cooldown_remaining(now),
            "lockout_reason": self.throttler.lockout_reason,
            "can_enter": self.throttler.can_enter(now) and not self.emergency_latched and self.risk_state != RiskState.ENTRY_BLOCKED,
        }
        params = asdict(self.svi_result.params)
        payload = {
            "timestamp_ist": ist_dt.isoformat(), "timestamp_epoch": now,
            "svi": {"params": params, "deltas": list(self.svi_result.deltas),
                    "min_sampled_butterfly_g": self.svi_result.min_sampled_g,
                    "state": asdict(self.microstate)},
            "queue": queue,
            "bocpd": bocpd_payload,
            "profitability": None if self.last_profitability is None else {
                "expected_gross_alpha": self.last_profitability.expected_gross_alpha,
                "expected_net_alpha": self.last_net_alpha,
                "hurdle": self.last_profitability.hurdle,
                "qualifies": self.last_profitability.qualifies,
                "fees": asdict(self.last_profitability.breakdown)},
            "throttle": throttle,
            "risk_state": self.risk_state.value,
            "emergency_latched": self.emergency_latched,
            "emergency_reason": getattr(self, "emergency_reason", None),
            "heartbeat_count": self.heartbeat_count,
            "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
        }
        # Round-trip here guarantees JSON-safe primitive types and catches accidental unserializable values.
        return json.loads(json.dumps(payload, allow_nan=False))


# ---------------------------------------------------------------------------
# Optional localhost JSON / SSE dashboard
# ---------------------------------------------------------------------------

class DashboardServer:
    def __init__(self, engine: Cycle34ExecutionEngine, host: str = "127.0.0.1", port: int = 8088,
                 *, sse_interval: float = 0.25, sse_max_events: int = 120):
        self.engine = engine
        self.host = host
        self.port = int(port)
        self.sse_interval = _nonnegative(sse_interval, "sse_interval")
        if self.sse_interval <= 0:
            raise ValueError("sse_interval must be positive")
        if sse_max_events < 1:
            raise ValueError("sse_max_events must be positive")
        self.sse_max_events = int(sse_max_events)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[Thread] = None

    def _handler(self):
        engine = self.engine
        interval = self.sse_interval
        max_events = self.sse_max_events

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def _headers(self, status: int, content_type: str, length: Optional[int] = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                if length is not None:
                    self.send_header("Content-Length", str(length))
                self.end_headers()

            def do_GET(self):
                if self.path == "/health":
                    body = json.dumps({"ok": True, "risk_state": engine.risk_state.value,
                                       "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                                       "heartbeat_count": engine.heartbeat_count}).encode()
                    self._headers(200, "application/json; charset=utf-8", len(body))
                    self.wfile.write(body)
                elif self.path == "/telemetry":
                    body = json.dumps(engine.telemetry_payload(), separators=(",", ":"), allow_nan=False).encode()
                    self._headers(200, "application/json; charset=utf-8", len(body))
                    self.wfile.write(body)
                elif self.path == "/events":
                    self._headers(200, "text/event-stream; charset=utf-8")
                    try:
                        for idx in range(max_events):
                            payload = json.dumps(engine.telemetry_payload(), separators=(",", ":"), allow_nan=False)
                            self.wfile.write(f"id: {idx}\nevent: telemetry\ndata: {payload}\n\n".encode())
                            self.wfile.flush()
                            sleep(interval)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                else:
                    body = b'{"error":"not_found"}'
                    self._headers(404, "application/json; charset=utf-8", len(body))
                    self.wfile.write(body)

            def log_message(self, format, *args):
                return

        return Handler

    def start(self) -> int:
        if self._httpd is not None:
            raise RuntimeError("dashboard server already started")
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._handler())
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = Thread(target=self._httpd.serve_forever, name="cycle34-dashboard", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()


def create_default_engine() -> Cycle34ExecutionEngine:
    return Cycle34ExecutionEngine()
