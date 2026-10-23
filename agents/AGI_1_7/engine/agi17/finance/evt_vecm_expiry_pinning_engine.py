"""Cycle 31: EVT tail risk, high-frequency VECM, pin-aware hedging and telemetry.

Offline research reference. Uses only the Python standard library. There is no
broker adapter or live order-submission implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta, time as datetime_time
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable, Optional, Sequence
import json
import math
import threading
import time

LIVE_ORDER_DISPATCH_ENABLED = False
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
CRORE = 10_000_000.0


def _finite(value: float, name: str) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    return v


def _finite_seq(values: Sequence[float], name: str, minimum: int = 1) -> list[float]:
    result = [_finite(v, name) for v in values]
    if len(result) < minimum:
        raise ValueError(f"{name} requires at least {minimum} values")
    return result


def _quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile, dependency-free (q in [0, 1])."""
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0, 1]")
    xs = sorted(values)
    if not xs:
        raise ValueError("quantile requires data")
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _solve_linear(a: list[list[float]], b: list[float], tol: float = 1e-12) -> list[float]:
    """Gaussian elimination with partial pivoting for small normal equations."""
    n = len(b)
    if len(a) != n or any(len(row) != n for row in a):
        raise ValueError("linear system must be square")
    m = [list(map(float, row)) + [float(bi)] for row, bi in zip(a, b)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < tol:
            raise ValueError("singular regression design")
        m[col], m[pivot] = m[pivot], m[col]
        scale = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= scale
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col]
            if factor:
                for j in range(col, n + 1):
                    m[r][j] -= factor * m[col][j]
    return [m[i][n] for i in range(n)]


def _ols(x: Sequence[Sequence[float]], y: Sequence[float]) -> list[float]:
    if not x or len(x) != len(y):
        raise ValueError("OLS requires matching non-empty X and y")
    p = len(x[0])
    if p == 0 or any(len(row) != p for row in x):
        raise ValueError("inconsistent OLS design dimensions")
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(p)] for i in range(p)]
    xty = [sum(row[i] * yi for row, yi in zip(x, y)) for i in range(p)]
    return _solve_linear(xtx, xty)


# ---------------------------------------------------------------------------
# EVT / peaks over threshold
# ---------------------------------------------------------------------------
@dataclass
class EVTGPDModel:
    """Peaks-over-threshold GPD model for positive loss magnitudes.

    ``fit`` uses a transparent method-of-moments estimator on threshold
    exceedances. This is a useful offline baseline, not a substitute for
    diagnostic-heavy maximum-likelihood estimation on production data.
    """
    threshold: float = 1.0
    shape_xi: float = 0.0
    scale_beta: float = 1.0
    sample_count: int = 100
    exceedance_count: int = 5
    fitted: bool = False

    def __post_init__(self) -> None:
        self.threshold = _finite(self.threshold, "threshold")
        self.shape_xi = _finite(self.shape_xi, "shape_xi")
        self.scale_beta = _finite(self.scale_beta, "scale_beta")
        if self.scale_beta <= 0:
            raise ValueError("scale_beta must be positive")
        if self.shape_xi >= 1.0:
            raise ValueError("shape_xi must be < 1 for finite expected shortfall")
        if self.sample_count < 1 or not 1 <= self.exceedance_count <= self.sample_count:
            raise ValueError("invalid sample/exceedance counts")

    def fit(self, losses: Sequence[float], threshold_quantile: float = 0.95,
            min_exceedances: int = 5) -> "EVTGPDModel":
        xs = _finite_seq(losses, "losses", minimum=10)
        if any(x < 0 for x in xs):
            raise ValueError("loss magnitudes must be nonnegative")
        if not 0.5 <= threshold_quantile < 1.0:
            raise ValueError("threshold_quantile must be in [0.5, 1)")
        if min_exceedances < 2:
            raise ValueError("min_exceedances must be >= 2")
        u = _quantile(xs, threshold_quantile)
        excess = [x - u for x in xs if x > u]
        if len(excess) < min_exceedances:
            raise ValueError("too few strict exceedances; lower the threshold quantile")
        mean_ex = sum(excess) / len(excess)
        var_ex = sum((x - mean_ex) ** 2 for x in excess) / (len(excess) - 1)
        if mean_ex <= 0 or not math.isfinite(mean_ex):
            raise ValueError("exceedance mean must be positive")
        if var_ex <= 1e-15:
            xi = -0.25
        else:
            xi = 0.5 * (1.0 - (mean_ex * mean_ex / var_ex))
        # Keep finite-moment, numerically stable MOM estimates; calibration
        # reports should retain the unclipped empirical estimate separately.
        xi = min(0.95, max(-0.25, xi))
        beta = mean_ex * (1.0 - xi)
        if beta <= 0 or not math.isfinite(beta):
            raise ValueError("GPD scale estimate is invalid")
        self.threshold = u
        self.shape_xi = xi
        self.scale_beta = beta
        self.sample_count = len(xs)
        self.exceedance_count = len(excess)
        self.fitted = True
        return self

    def _tail_probability(self, alpha: float) -> float:
        alpha = _finite(alpha, "alpha")
        if not 0 < alpha < 1:
            raise ValueError("alpha must be strictly between 0 and 1")
        p = (self.sample_count / self.exceedance_count) * (1.0 - alpha)
        if not 0 < p <= 1.0 + 1e-12:
            raise ValueError("alpha is outside the fitted POT tail range")
        return min(1.0, p)

    def var(self, alpha: float = 0.99) -> float:
        p = self._tail_probability(alpha)
        xi, beta, u = self.shape_xi, self.scale_beta, self.threshold
        if abs(xi) < 1e-8:
            return u + beta * math.log(1.0 / p)
        value = u + (beta / xi) * (p ** (-xi) - 1.0)
        if xi < 0:
            endpoint = u - beta / xi
            value = min(value, endpoint)
        if not math.isfinite(value):
            raise ArithmeticError("EVT VaR overflowed")
        return value

    def cvar(self, alpha: float = 0.99) -> float:
        q = self.var(alpha)
        xi, beta, u = self.shape_xi, self.scale_beta, self.threshold
        if xi >= 1.0:
            raise ValueError("finite CVaR requires shape_xi < 1")
        value = (q + beta - xi * u) / (1.0 - xi)
        if not math.isfinite(value):
            raise ArithmeticError("EVT CVaR overflowed")
        return value

    def tail_margin_multiplier(self, kappa: float = 1.0) -> float:
        kappa = _finite(kappa, "kappa")
        if kappa < 0:
            raise ValueError("kappa must be nonnegative")
        return 1.0 + kappa * max(0.0, self.shape_xi) / (1.0 - self.shape_xi)

    def diagnostics(self, alpha: float = 0.99) -> dict[str, Any]:
        return {
            "fitted": self.fitted,
            "threshold_u": self.threshold,
            "xi": self.shape_xi,
            "beta": self.scale_beta,
            "sample_count": self.sample_count,
            "exceedance_count": self.exceedance_count,
            "var": self.var(alpha),
            "cvar": self.cvar(alpha),
            "alpha": alpha,
            "tail_margin_multiplier": self.tail_margin_multiplier(),
        }


# ---------------------------------------------------------------------------
# Cointegration / VECM
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VECMParameters:
    beta_coint: float
    mu_coint: float
    alpha_1: float
    alpha_2: float
    gamma_11: float
    gamma_12: float
    gamma_21: float
    gamma_22: float
    raw_alpha_1: float
    raw_alpha_2: float
    stabilized: bool
    observations: int

    @property
    def stable(self) -> bool:
        return self.alpha_1 < 0 and self.alpha_2 > 0

    @property
    def correction_speed(self) -> float:
        return abs(self.alpha_1) + abs(self.alpha_2)

    @property
    def leader(self) -> str:
        # In a simple error-correction interpretation, the less-adjusting
        # series is the putative leader; this is not a causal proof.
        return "NIFTY 50" if abs(self.alpha_1) <= abs(self.alpha_2) else "BANKNIFTY"

    @property
    def leadership_asymmetry(self) -> float:
        denom = abs(self.alpha_1) + abs(self.alpha_2)
        if denom <= 1e-15:
            return 0.0
        return (abs(self.alpha_2) - abs(self.alpha_1)) / denom


class HighFrequencyVECM:
    """Two-index, one-cointegration-vector VECM with sign-stabilized alpha."""
    def __init__(self, z_threshold: float = 2.0, min_abs_speed: float = 1e-8) -> None:
        self.z_threshold = _finite(z_threshold, "z_threshold")
        self.min_abs_speed = _finite(min_abs_speed, "min_abs_speed")
        if self.z_threshold <= 0 or self.min_abs_speed <= 0:
            raise ValueError("threshold and min_abs_speed must be positive")
        self.parameters: Optional[VECMParameters] = None
        self.latest_z: Optional[float] = None
        self.latest_z_score: Optional[float] = None
        self.latest_dislocated = False

    def fit(self, log_nifty: Sequence[float], log_banknifty: Sequence[float],
            stabilize_mean_reversion: bool = True) -> VECMParameters:
        y1 = _finite_seq(log_nifty, "log_nifty", minimum=12)
        y2 = _finite_seq(log_banknifty, "log_banknifty", minimum=12)
        if len(y1) != len(y2):
            raise ValueError("index series lengths must match")
        mean1, mean2 = sum(y1) / len(y1), sum(y2) / len(y2)
        var2 = sum((v - mean2) ** 2 for v in y2)
        if var2 <= 1e-15:
            raise ValueError("BANKNIFTY log series has no level variation")
        beta = sum((x - mean2) * (y - mean1) for x, y in zip(y2, y1)) / var2
        mu = mean1 - beta * mean2
        z = [a - beta * b - mu for a, b in zip(y1, y2)]
        dy1 = [y1[i] - y1[i - 1] for i in range(1, len(y1))]
        dy2 = [y2[i] - y2[i - 1] for i in range(1, len(y2))]
        design: list[list[float]] = []
        out1: list[float] = []
        out2: list[float] = []
        # t=2..n-1, with lagged spread z[t-1] and lagged differences.
        for t in range(2, len(y1)):
            design.append([z[t - 1], dy1[t - 2], dy2[t - 2]])
            out1.append(dy1[t - 1])
            out2.append(dy2[t - 1])
        coef1 = _ols(design, out1)
        coef2 = _ols(design, out2)
        raw_a1, raw_a2 = coef1[0], coef2[0]
        if stabilize_mean_reversion:
            a1 = -max(abs(raw_a1), self.min_abs_speed)
            a2 = max(abs(raw_a2), self.min_abs_speed)
        else:
            a1, a2 = raw_a1, raw_a2
        self.parameters = VECMParameters(
            beta, mu, a1, a2, coef1[1], coef1[2], coef2[1], coef2[2],
            raw_a1, raw_a2, bool(stabilize_mean_reversion), len(y1),
        )
        self.latest_z = z[-1]
        self.latest_z_score = self.z_score(z)
        self.latest_dislocated = abs(self.latest_z_score) > self.z_threshold
        return self.parameters

    @staticmethod
    def z_score(spread_history: Sequence[float]) -> float:
        xs = _finite_seq(spread_history, "spread_history", minimum=2)
        mean = sum(xs) / len(xs)
        var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
        sd = math.sqrt(var)
        if sd <= 1e-12:
            return 0.0 if abs(xs[-1] - mean) <= 1e-12 else math.copysign(float("inf"), xs[-1] - mean)
        return (xs[-1] - mean) / sd

    def spread(self, log_nifty: float, log_banknifty: float) -> float:
        if self.parameters is None:
            raise RuntimeError("VECM must be fitted first")
        y1 = _finite(log_nifty, "log_nifty")
        y2 = _finite(log_banknifty, "log_banknifty")
        z = y1 - self.parameters.beta_coint * y2 - self.parameters.mu_coint
        self.latest_z = z
        return z

    def dislocation_signal(self, z: Optional[float] = None) -> bool:
        value = self.latest_z if z is None else _finite(z, "z")
        if value is None:
            raise RuntimeError("VECM spread is unavailable")
        return abs(value) > self.z_threshold

    def predict_differences(self, z_lag: float, dy1_lag: float, dy2_lag: float) -> tuple[float, float]:
        if self.parameters is None:
            raise RuntimeError("VECM must be fitted first")
        p = self.parameters
        z_lag, dy1_lag, dy2_lag = (_finite(z_lag, "z_lag"), _finite(dy1_lag, "dy1_lag"), _finite(dy2_lag, "dy2_lag"))
        return (p.alpha_1 * z_lag + p.gamma_11 * dy1_lag + p.gamma_12 * dy2_lag,
                p.alpha_2 * z_lag + p.gamma_21 * dy1_lag + p.gamma_22 * dy2_lag)


# ---------------------------------------------------------------------------
# Pinning and dynamic delta hedge
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StrikeExposure:
    strike: float
    open_interest: float
    gamma: float

    def __post_init__(self) -> None:
        if _finite(self.strike, "strike") <= 0:
            raise ValueError("strike must be positive")
        if _finite(self.open_interest, "open_interest") < 0:
            raise ValueError("open_interest must be nonnegative")
        _finite(self.gamma, "gamma")

    @property
    def pin_score(self) -> float:
        return self.open_interest * abs(self.gamma)


@dataclass(frozen=True)
class PinState:
    strike: float
    pin_score: float
    gamma_abs: float
    spot: float
    distance: float
    expiry_window: bool
    gravity_multiplier: float
    band_width: float


@dataclass(frozen=True)
class HedgePlan:
    action: str
    current_delta: float
    target_delta: float
    shortfall: float
    band_width: float
    adjustment: float
    pin_strike: Optional[float]
    reason: str


class ExpiryPinningModel:
    def __init__(self, width_base: float = 0.05, eta_pin: float = 1.0) -> None:
        self.width_base = _finite(width_base, "width_base")
        self.eta_pin = _finite(eta_pin, "eta_pin")
        if self.width_base <= 0 or self.eta_pin < 0:
            raise ValueError("width_base must be positive and eta_pin nonnegative")
        self.latest_pin: Optional[PinState] = None

    @staticmethod
    def is_expiry_window(now: datetime) -> bool:
        if not isinstance(now, datetime):
            raise TypeError("now must be a datetime")
        local = now.astimezone(IST) if now.tzinfo else now.replace(tzinfo=IST)
        clock = local.timetz().replace(tzinfo=None)
        return datetime_time(15, 0) <= clock <= datetime_time(15, 30)

    def identify_pin(self, spot: float, strikes: Sequence[StrikeExposure], now: datetime) -> PinState:
        spot = _finite(spot, "spot")
        if spot <= 0:
            raise ValueError("spot must be positive")
        if not strikes:
            raise ValueError("at least one strike exposure is required")
        if any(not isinstance(x, StrikeExposure) for x in strikes):
            raise TypeError("strikes must contain StrikeExposure records")
        pin = max(strikes, key=lambda x: x.pin_score)
        distance = abs(spot - pin.strike)
        expiry = self.is_expiry_window(now)
        gravity = 1.0 + self.eta_pin * abs(pin.gamma) / (1.0 + distance) if expiry else 1.0
        width = self.width_base * gravity
        self.latest_pin = PinState(pin.strike, pin.pin_score, abs(pin.gamma), spot, distance, expiry, gravity, width)
        return self.latest_pin

    def hedge_plan(self, current_delta: float, target_delta: float,
                   pin: Optional[PinState] = None, tail_multiplier: float = 1.0) -> HedgePlan:
        current_delta = _finite(current_delta, "current_delta")
        target_delta = _finite(target_delta, "target_delta")
        tail_multiplier = _finite(tail_multiplier, "tail_multiplier")
        if tail_multiplier < 1.0:
            raise ValueError("tail_multiplier must be >= 1")
        pin = pin or self.latest_pin
        width = (pin.band_width if pin is not None else self.width_base) / tail_multiplier
        shortfall = target_delta - current_delta
        if abs(shortfall) <= width:
            return HedgePlan("HOLD", current_delta, target_delta, shortfall, width, 0.0,
                             pin.strike if pin else None, "delta shortfall remains inside indifference band")
        adjustment = shortfall - math.copysign(width, shortfall)
        return HedgePlan("REBALANCE", current_delta, target_delta, shortfall, width, adjustment,
                         pin.strike if pin else None, "delta shortfall breached tail-adjusted indifference band")


# ---------------------------------------------------------------------------
# Indian statutory costs and spread hurdle
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeeSchedule:
    options_sell_stt_rate: float = 0.0015
    exchange_rate: float = 3553.0 / CRORE
    sebi_rate: float = 10.0 / CRORE
    gst_rate: float = 0.18
    options_buy_stamp_rate: float = 0.00003
    brokerage_per_order: float = 0.0

    def __post_init__(self) -> None:
        for name in ("options_sell_stt_rate", "exchange_rate", "sebi_rate", "gst_rate", "options_buy_stamp_rate", "brokerage_per_order"):
            if _finite(getattr(self, name), name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.gst_rate > 1.0:
            raise ValueError("gst_rate must be <= 1")


@dataclass(frozen=True)
class OptionLeg:
    name: str
    side: str
    premium: float
    quantity: float
    half_spread_per_unit: float = 0.0
    cross_impact_per_unit: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("leg name cannot be empty")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        for name in ("premium", "quantity", "half_spread_per_unit", "cross_impact_per_unit"):
            if _finite(getattr(self, name), name) < 0:
                raise ValueError(f"{name} must be nonnegative")

    @property
    def turnover(self) -> float:
        return self.premium * self.quantity


@dataclass(frozen=True)
class FeeBreakdown:
    name: str
    side: str
    premium_turnover: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    slippage: float
    cross_impact: float
    total: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpreadEvaluation:
    name: str
    expected_gross_alpha: float
    statutory_and_execution_cost: float
    separate_impact_hurdle: float
    expected_net_alpha: float
    qualifies: bool
    fee_breakdown: tuple[FeeBreakdown, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expected_gross_alpha": self.expected_gross_alpha,
            "statutory_and_execution_cost": self.statutory_and_execution_cost,
            "separate_impact_hurdle": self.separate_impact_hurdle,
            "expected_net_alpha": self.expected_net_alpha,
            "qualifies": self.qualifies,
            "fee_breakdown": [x.to_dict() for x in self.fee_breakdown],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SpreadCandidate:
    name: str
    legs: tuple[OptionLeg, ...]
    expected_gross_alpha: float
    separate_impact_hurdle: float = 0.0

    def __post_init__(self) -> None:
        if not self.name or not self.legs:
            raise ValueError("spread name and at least one leg are required")
        if not math.isfinite(self.expected_gross_alpha):
            raise ValueError("expected_gross_alpha must be finite")
        if _finite(self.separate_impact_hurdle, "separate_impact_hurdle") < 0:
            raise ValueError("separate impact hurdle must be nonnegative")


class StatutoryCostCalculator:
    def __init__(self, schedule: Optional[FeeSchedule] = None) -> None:
        self.schedule = schedule or FeeSchedule()

    def calculate_leg(self, leg: OptionLeg) -> FeeBreakdown:
        if not isinstance(leg, OptionLeg):
            raise TypeError("leg must be OptionLeg")
        turnover = leg.turnover
        stt = turnover * self.schedule.options_sell_stt_rate if leg.side == "SELL" else 0.0
        stamp = turnover * self.schedule.options_buy_stamp_rate if leg.side == "BUY" else 0.0
        exchange = turnover * self.schedule.exchange_rate
        sebi = turnover * self.schedule.sebi_rate
        brokerage = self.schedule.brokerage_per_order
        gst = (exchange + sebi + brokerage) * self.schedule.gst_rate
        slippage = leg.half_spread_per_unit * leg.quantity
        impact = leg.cross_impact_per_unit * leg.quantity
        total = sum((stt, exchange, sebi, gst, stamp, brokerage, slippage, impact))
        components = (turnover, stt, exchange, sebi, gst, stamp, brokerage, slippage, impact, total)
        if any(not math.isfinite(x) or x < 0 for x in components):
            raise ArithmeticError("fee calculation produced invalid value")
        return FeeBreakdown(leg.name, leg.side, turnover, stt, exchange, sebi, gst,
                            stamp, brokerage, slippage, impact, total)

    def calculate_multileg(self, legs: Sequence[OptionLeg]) -> tuple[FeeBreakdown, ...]:
        if not legs:
            raise ValueError("at least one leg is required")
        return tuple(self.calculate_leg(leg) for leg in legs)

    def evaluate_spread(self, candidate: SpreadCandidate) -> SpreadEvaluation:
        if not isinstance(candidate, SpreadCandidate):
            raise TypeError("candidate must be SpreadCandidate")
        breakdown = self.calculate_multileg(candidate.legs)
        total = sum(x.total for x in breakdown)
        hurdle = candidate.separate_impact_hurdle
        net = candidate.expected_gross_alpha - total - hurdle
        qualifies = candidate.expected_gross_alpha > total + hurdle
        reason = "strict net-alpha hurdle cleared" if qualifies else "gross alpha does not strictly exceed all costs and impact hurdle"
        return SpreadEvaluation(candidate.name, candidate.expected_gross_alpha, total, hurdle,
                                net, qualifies, breakdown, reason)


# ---------------------------------------------------------------------------
# Trade frequency and behavioral guard
# ---------------------------------------------------------------------------
class AntiOvertradingThrottler:
    def __init__(self, alpha: float, cost: float, risk: float,
                 cooldown_seconds: float = 900.0, max_loss_streak: int = 3,
                 max_size_ratio: float = 1.25, min_fill_interval: float = 30.0) -> None:
        self.alpha = _finite(alpha, "alpha")
        self.cost = _finite(cost, "cost")
        self.risk = _finite(risk, "risk")
        if self.risk <= 0 or self.cost < 0 or self.cooldown_seconds_invalid(cooldown_seconds):
            raise ValueError("invalid trade-frequency or cooldown parameters")
        self.cooldown_seconds = float(cooldown_seconds)
        self.max_loss_streak = int(max_loss_streak)
        self.max_size_ratio = _finite(max_size_ratio, "max_size_ratio")
        self.min_fill_interval = _finite(min_fill_interval, "min_fill_interval")
        if self.max_loss_streak < 1 or self.max_size_ratio <= 1 or self.min_fill_interval < 0:
            raise ValueError("invalid behavioral guard parameters")
        self.daily_cap = self.optimal_daily_cap(self.alpha, self.cost, self.risk)
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.previous_fill_size: Optional[float] = None
        self.previous_fill_timestamp: Optional[float] = None
        self.lockout_until_epoch: float = 0.0
        self.lockout_reasons: list[str] = []
        self.session_date: Optional[str] = None

    @staticmethod
    def cooldown_seconds_invalid(value: float) -> bool:
        return not math.isfinite(float(value)) or float(value) <= 0

    @staticmethod
    def optimal_daily_cap(alpha: float, cost: float, risk: float) -> int:
        alpha, cost, risk = _finite(alpha, "alpha"), _finite(cost, "cost"), _finite(risk, "risk")
        if risk <= 0 or cost < 0:
            raise ValueError("risk must be positive and cost nonnegative")
        raw = max(0.0, (alpha - cost) / risk)
        # Conventional half-up rounding avoids Python's ties-to-even surprise.
        return int(math.floor(raw + 0.5))

    def remaining_cooldown(self, now_epoch: Optional[float] = None) -> float:
        now = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        return max(0.0, self.lockout_until_epoch - now)

    def can_enter(self, now_epoch: Optional[float] = None) -> bool:
        return self.daily_trade_count < self.daily_cap and self.remaining_cooldown(now_epoch) <= 0.0

    def _trigger(self, reason: str, timestamp: float) -> None:
        self.lockout_until_epoch = max(self.lockout_until_epoch, timestamp + self.cooldown_seconds)
        self.lockout_reasons.append(reason)

    def record_fill(self, timestamp: float, size: float) -> tuple[str, ...]:
        ts, size = _finite(timestamp, "timestamp"), _finite(size, "size")
        if size <= 0:
            raise ValueError("fill size must be positive")
        if self.previous_fill_timestamp is not None and ts < self.previous_fill_timestamp:
            raise ValueError("fill timestamps must be nondecreasing")
        triggered: list[str] = []
        if self.previous_fill_timestamp is not None and ts - self.previous_fill_timestamp < self.min_fill_interval:
            self._trigger("RAPID_FILL_PACING", ts)
            triggered.append("RAPID_FILL_PACING")
        if self.previous_fill_size is not None and size / self.previous_fill_size > self.max_size_ratio:
            self._trigger("REVENGE_SIZING", ts)
            triggered.append("REVENGE_SIZING")
        self.daily_trade_count += 1
        self.previous_fill_timestamp = ts
        self.previous_fill_size = size
        self.session_date = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
        return tuple(triggered)

    def record_outcome(self, pnl: float, timestamp: float) -> bool:
        pnl, ts = _finite(pnl, "pnl"), _finite(timestamp, "timestamp")
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        if self.consecutive_losses >= self.max_loss_streak:
            self._trigger("LOSS_STREAK", ts)
            return True
        return False

    def reset_daily_count(self, session_date: str) -> None:
        if not session_date:
            raise ValueError("session_date cannot be empty")
        self.session_date = session_date
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.previous_fill_size = None
        self.previous_fill_timestamp = None
        # A new session does not bypass a still-active behavioral cooldown.

    def snapshot(self, now_epoch: Optional[float] = None) -> dict[str, Any]:
        return {
            "daily_trade_cap": self.daily_cap,
            "daily_trade_count": self.daily_trade_count,
            "can_enter": self.can_enter(now_epoch),
            "consecutive_losses": self.consecutive_losses,
            "cooldown_remaining_seconds": round(self.remaining_cooldown(now_epoch), 3),
            "lockout_reasons": list(self.lockout_reasons[-10:]),
        }


# ---------------------------------------------------------------------------
# Fail-closed orchestration and telemetry
# ---------------------------------------------------------------------------
class RiskState(str, Enum):
    IDLE = "IDLE"
    HEDGE_PLANNING = "HEDGE_PLANNING"
    HEDGE_REQUIRED = "HEDGE_REQUIRED"
    OVERTRADING_LOCKED = "OVERTRADING_LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START_PLANNING = "START_PLANNING"
    HEDGE_REQUIRED = "HEDGE_REQUIRED"
    THROTTLE = "THROTTLE"
    EMERGENCY = "EMERGENCY"
    RESET = "RESET"
    RECOVERY_ACK = "RECOVERY_ACK"


class RiskStateMachine:
    def __init__(self, state: RiskState = RiskState.IDLE) -> None:
        if not isinstance(state, RiskState):
            raise ValueError("state must be RiskState")
        self.state = state
        self.emergency_latched = state is RiskState.EMERGENCY_UNWIND
        self.history: list[tuple[str, str]] = []

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown risk event; fail closed")
        if self.emergency_latched and event is not RiskEvent.RECOVERY_ACK:
            self.history.append((event.value, "blocked_emergency_latched"))
            return self.state
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event is RiskEvent.THROTTLE:
            self.state = RiskState.OVERTRADING_LOCKED
        elif event is RiskEvent.START_PLANNING and self.state is RiskState.IDLE:
            self.state = RiskState.HEDGE_PLANNING
        elif event is RiskEvent.HEDGE_REQUIRED and self.state in (RiskState.HEDGE_PLANNING, RiskState.IDLE):
            self.state = RiskState.HEDGE_REQUIRED
        elif event is RiskEvent.RESET and self.state is not RiskState.EMERGENCY_UNWIND:
            self.state = RiskState.IDLE
        self.history.append((event.value, self.state.value))
        return self.state


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Intentionally unavailable. Cycle 31 is simulation-only."""
    raise RuntimeError("live order dispatch is permanently disabled; paper simulation only")


class Cycle31ExecutionEngine:
    def __init__(self, evt_model: Optional[EVTGPDModel] = None,
                 vecm_model: Optional[HighFrequencyVECM] = None,
                 pin_model: Optional[ExpiryPinningModel] = None,
                 cost_calculator: Optional[StatutoryCostCalculator] = None,
                 throttler: Optional[AntiOvertradingThrottler] = None,
                 risk_machine: Optional[RiskStateMachine] = None) -> None:
        self.evt = evt_model or EVTGPDModel()
        self.vecm = vecm_model or HighFrequencyVECM()
        self.pin_model = pin_model or ExpiryPinningModel()
        self.costs = cost_calculator or StatutoryCostCalculator()
        self.throttler = throttler or AntiOvertradingThrottler(alpha=1.0, cost=0.2, risk=1.0)
        self.risk = risk_machine or RiskStateMachine()
        self.latest_pin: Optional[PinState] = None
        self.latest_hedge: Optional[HedgePlan] = None
        self.latest_spreads: list[SpreadEvaluation] = []
        self.latest_log_nifty: Optional[float] = None
        self.latest_log_banknifty: Optional[float] = None
        self.latest_z: Optional[float] = None
        self.heartbeat_count = 0
        self.latest_updated_epoch = time.time()

    def fit_evt(self, losses: Sequence[float], threshold_quantile: float = 0.95) -> EVTGPDModel:
        self.evt.fit(losses, threshold_quantile=threshold_quantile)
        self._beat()
        return self.evt

    def fit_vecm(self, log_nifty: Sequence[float], log_banknifty: Sequence[float],
                 stabilize_mean_reversion: bool = True) -> VECMParameters:
        params = self.vecm.fit(log_nifty, log_banknifty, stabilize_mean_reversion)
        self.latest_log_nifty = float(log_nifty[-1])
        self.latest_log_banknifty = float(log_banknifty[-1])
        self.latest_z = self.vecm.latest_z
        self._beat()
        return params

    def update_vecm_observation(self, log_nifty: float, log_banknifty: float) -> float:
        self.latest_log_nifty = _finite(log_nifty, "log_nifty")
        self.latest_log_banknifty = _finite(log_banknifty, "log_banknifty")
        self.latest_z = self.vecm.spread(log_nifty, log_banknifty)
        self._beat()
        return self.latest_z

    def update_pin(self, spot: float, strikes: Sequence[StrikeExposure], now: datetime) -> PinState:
        self.latest_pin = self.pin_model.identify_pin(spot, strikes, now)
        self._beat()
        return self.latest_pin

    def plan_delta_hedge(self, current_delta: float, target_delta: float) -> HedgePlan:
        multiplier = self.evt.tail_margin_multiplier()
        self.latest_hedge = self.pin_model.hedge_plan(current_delta, target_delta, self.latest_pin, multiplier)
        if self.latest_hedge.action == "REBALANCE" and not self.risk.emergency_latched:
            self.risk.transition(RiskEvent.HEDGE_REQUIRED)
        self._beat()
        return self.latest_hedge

    def evaluate_spread(self, candidate: SpreadCandidate, now_epoch: Optional[float] = None) -> SpreadEvaluation:
        now = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        if self.risk.emergency_latched:
            evaluation = SpreadEvaluation(candidate.name, candidate.expected_gross_alpha, 0.0,
                                          candidate.separate_impact_hurdle, 0.0,
                                          False, tuple(), "blocked by latched emergency unwind")
        elif not self.throttler.can_enter(now):
            if self.risk.state is not RiskState.OVERTRADING_LOCKED:
                self.risk.transition(RiskEvent.THROTTLE)
            evaluation = SpreadEvaluation(candidate.name, candidate.expected_gross_alpha, 0.0,
                                          candidate.separate_impact_hurdle, 0.0,
                                          False, tuple(), "blocked by daily trade cap or behavioral cooldown")
        else:
            if self.risk.state is RiskState.OVERTRADING_LOCKED:
                self.risk.transition(RiskEvent.RESET)
            if self.risk.state is RiskState.IDLE:
                self.risk.transition(RiskEvent.START_PLANNING)
            evaluation = self.costs.evaluate_spread(candidate)
        self.latest_spreads.append(evaluation)
        self.latest_spreads = self.latest_spreads[-20:]
        self._beat()
        return evaluation

    def record_fill(self, timestamp: float, size: float, pnl: Optional[float] = None) -> tuple[str, ...]:
        triggers = list(self.throttler.record_fill(timestamp, size))
        if pnl is not None:
            if self.throttler.record_outcome(pnl, timestamp):
                triggers.append("LOSS_STREAK")
        if triggers or not self.throttler.can_enter(timestamp):
            if not self.risk.emergency_latched:
                self.risk.transition(RiskEvent.THROTTLE)
        self._beat()
        return tuple(triggers)

    def emergency_unwind(self) -> RiskState:
        result = self.risk.transition(RiskEvent.EMERGENCY)
        self._beat()
        return result

    def recovery_ack(self) -> RiskState:
        result = self.risk.transition(RiskEvent.RECOVERY_ACK)
        self._beat()
        return result

    def _beat(self) -> None:
        self.heartbeat_count += 1
        self.latest_updated_epoch = time.time()

    def telemetry_payload(self, now_epoch: Optional[float] = None) -> dict[str, Any]:
        epoch = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        timestamp = datetime.fromtimestamp(epoch, IST)
        try:
            evt = self.evt.diagnostics(0.99)
        except (ValueError, ArithmeticError):
            evt = {"fitted": self.evt.fitted, "threshold_u": self.evt.threshold,
                   "xi": self.evt.shape_xi, "beta": self.evt.scale_beta,
                   "sample_count": self.evt.sample_count, "exceedance_count": self.evt.exceedance_count,
                   "var": None, "cvar": None, "alpha": 0.99,
                   "tail_margin_multiplier": self.evt.tail_margin_multiplier()}
        params = self.vecm.parameters
        vecm_data: dict[str, Any] = {
            "fitted": params is not None,
            "spread_z": self.latest_z,
            "z_threshold": self.vecm.z_threshold,
            "dislocated": bool(self.latest_z is not None and abs(self.latest_z) > self.vecm.z_threshold),
            "beta_coint": params.beta_coint if params else None,
            "mu_coint": params.mu_coint if params else None,
            "alpha_1": params.alpha_1 if params else None,
            "alpha_2": params.alpha_2 if params else None,
            "correction_speed": params.correction_speed if params else None,
            "lead_lag_leader": params.leader if params else None,
            "leadership_asymmetry": params.leadership_asymmetry if params else None,
            "stable": params.stable if params else None,
        }
        pin = self.latest_pin
        pin_data: dict[str, Any] = {
            "strike": pin.strike if pin else None,
            "pin_score": pin.pin_score if pin else None,
            "gamma_abs": pin.gamma_abs if pin else None,
            "spot": pin.spot if pin else None,
            "distance": pin.distance if pin else None,
            "expiry_window": pin.expiry_window if pin else False,
            "gravity_multiplier": pin.gravity_multiplier if pin else 1.0,
            "band_width": pin.band_width if pin else self.pin_model.width_base,
        }
        return {
            "timestamp_ist": timestamp.isoformat(),
            "epoch_seconds": epoch,
            "evt": evt,
            "vecm": vecm_data,
            "pinning": pin_data,
            "hedge_plan": asdict(self.latest_hedge) if self.latest_hedge else None,
            "spread_recommendations": [x.to_dict() for x in self.latest_spreads[-10:]],
            "operations": {
                "heartbeat_count": self.heartbeat_count,
                "last_update_epoch": self.latest_updated_epoch,
                "risk_state": self.risk.state.value,
                "emergency_latched": self.risk.emergency_latched,
                "throttler": self.throttler.snapshot(epoch),
                "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                "mode": "PAPER_SIMULATION_ONLY",
            },
        }

    def telemetry_json(self, now_epoch: Optional[float] = None) -> str:
        return json.dumps(self.telemetry_payload(now_epoch), separators=(",", ":"), allow_nan=False)


class DashboardServer:
    """Local JSON/SSE dashboard on port 8088 by default; can bind port 0 for tests."""
    def __init__(self, engine: Cycle31ExecutionEngine, host: str = "127.0.0.1",
                 port: int = 8088, interval_seconds: float = 0.5) -> None:
        if not isinstance(engine, Cycle31ExecutionEngine):
            raise TypeError("engine must be Cycle31ExecutionEngine")
        self.engine = engine
        self.host = host
        self.port = int(port)
        self.interval_seconds = _finite(interval_seconds, "interval_seconds")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> tuple[str, int]:
        if self._httpd is not None:
            raise RuntimeError("dashboard server already started")
        engine = self.engine
        interval = self.interval_seconds

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _send_json(self, obj: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path == "/health":
                    self._send_json({"ok": True, "risk_state": engine.risk.state.value,
                                     "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                                     "mode": "PAPER_SIMULATION_ONLY"})
                elif path == "/telemetry":
                    self._send_json(engine.telemetry_payload())
                elif path == "/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    try:
                        self.wfile.write(b"retry: 1000\n\n")
                        self.wfile.flush()
                        while True:
                            payload = engine.telemetry_json()
                            event = ("event: telemetry\ndata: " + payload + "\n\n").encode("utf-8")
                            self.wfile.write(event)
                            self.wfile.flush()
                            time.sleep(interval)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                else:
                    self._send_json({"error": "not found"}, 404)

            def log_message(self, fmt: str, *args: Any) -> None:
                return

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        self._httpd.block_on_close = False
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="cycle31-dashboard", daemon=True)
        self._thread.start()
        address = self._httpd.server_address
        return str(address[0]), int(address[1])

    def stop(self) -> None:
        if self._httpd is None:
            return
        server = self._httpd
        self._httpd = None
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def __enter__(self) -> "DashboardServer":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()
