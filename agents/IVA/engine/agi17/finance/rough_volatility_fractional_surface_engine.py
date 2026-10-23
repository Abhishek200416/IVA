"""Cycle 21: Rough Volatility (H < 0.5) Fractional Surface Calibration & Multi-Factor Markovian Lift Engine.

Mathematical Foundations:
1. Riemann-Liouville Fractional Volterra Kernel:
   For Hurst parameter H in (0, 0.5) (typically H approx 0.10 - 0.15 on NSE):
     K(t) = t^{H - 1/2} / Gamma(H + 1/2),  t > 0.

2. Fast Multi-Factor Markovian Exponential Lift (Abi Jaber - El Euch):
   Approximate non-Markovian kernel by M-factor decaying exponentials:
     K(t) approx sum_{i=1}^M c_i * exp(-x_i * t)
   where x_i are log-spaced rates and c_i >= 0 are non-negative weights.
   State recursion in O(M) time:
     z_i(t + Delta t) = exp(-x_i Delta t) * z_i(t) + c_i * (1 - exp(-x_i Delta t)) / x_i * Delta W.

3. Empirical Hurst Estimation from Return Increments:
   Log-log linear regression of RMS increments:
     ln(RMS(Delta_l X)) = H * ln(l) + intercept.

4. Rough Skew Extrapolation for Ultrashort Expiries:
   Power-law ATM implied volatility skew scaling:
     psi(tau) = psi_ref * (tau / tau_ref)^{H - 1/2},  tau in [1/365, 30/365].

5. No-Arbitrage SVI Butterfly Diagnostic & Calendar Check:
   Gatheral g(k) = (1 - k w' / (2w))^2 - (w'^2 / 4)(1/w + 1/4) + w'' / 2 >= 0.
   Calendar monotonicity: Delta w_tau >= 0.

6. Latched Fail-Closed 5-State Machine:
   States: IDLE -> CALIBRATION_ACTIVE -> SURFACE_VALIDATION | VOLATILITY_SPIKE_HALT | EMERGENCY_UNWIND.
   LIVE_ORDER_DISPATCH_ENABLED = False locked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

LIVE_ORDER_DISPATCH_ENABLED: bool = False


def fractional_rl_kernel(t: Sequence[float] | float, H: float) -> np.ndarray:
    """Riemann-Liouville fractional kernel t^(H - 1/2) / Gamma(H + 1/2) for H in (0, 0.5)."""
    if not (0.0 < H < 0.5):
        raise ValueError("rough-volatility H must lie in (0, 0.5)")
    tt = np.asarray(t, dtype=float)
    if np.any(~np.isfinite(tt)) or np.any(tt <= 0):
        raise ValueError("kernel times must be finite and positive")
    gamma = math.gamma(H + 0.5)
    return np.power(tt, H - 0.5) / gamma


@dataclass(frozen=True)
class ExponentialLift:
    H: float
    weights: np.ndarray
    rates: np.ndarray
    grid: np.ndarray
    target: np.ndarray
    approximation: np.ndarray
    relative_rmse: float
    max_relative_error: float

    @property
    def factors(self) -> int:
        return int(len(self.weights))

    def update_states(self, states: Sequence[float], new_innovation: float, dt: float) -> np.ndarray:
        """O(M) exact state update: z_i(t+dt) = exp(-x_i dt) z_i(t) + c_i (1 - exp(-x_i dt))/x_i * innovation."""
        z = np.asarray(states, dtype=float).reshape(-1)
        if z.size != self.factors or np.any(~np.isfinite(z)):
            raise ValueError("state vector must be finite and match factor count")
        if not math.isfinite(new_innovation) or not math.isfinite(dt) or dt <= 0:
            raise ValueError("innovation must be finite and dt positive")
        decay = np.exp(-self.rates * dt)
        drive = self.weights * (-np.expm1(-self.rates * dt)) / self.rates
        return decay * z + drive * new_innovation


def fit_markovian_lift(
    H: float,
    *,
    factors: int = 5,
    t_min: float = 1e-4,
    t_max: float = 1.0,
    grid_size: int = 500,
    weight_power: float = 0.5,
    rate_span: float = 10.0,
) -> ExponentialLift:
    """Fit non-negative multi-exponential sum to fractional kernel over a log-time grid."""
    if not (0.0 < H < 0.5):
        raise ValueError("H must lie in (0, 0.5)")
    if factors < 1 or grid_size < max(10, factors) or t_min <= 0 or t_max <= t_min:
        raise ValueError("invalid fit dimensions or time bounds")
    if weight_power < 0 or rate_span <= 1:
        raise ValueError("weight_power must be nonnegative and rate_span > 1")

    grid = np.geomspace(t_min, t_max, grid_size)
    target = fractional_rl_kernel(grid, H)
    rates = np.geomspace(1.0 / t_max, rate_span / t_min, factors)
    A = np.exp(-np.outer(grid, rates))
    row_weight = np.power(grid, weight_power)
    Aw, yw = A * row_weight[:, None], target * row_weight

    try:
        from scipy.optimize import nnls
        weights, _ = nnls(Aw, yw, maxiter=max(3 * factors, 100))
    except ImportError:
        weights, *_ = np.linalg.lstsq(Aw, yw, rcond=None)
        weights = np.maximum(weights, 0.0)

    approximation = A @ weights
    rel = (approximation - target) / np.maximum(np.abs(target), 1e-14)

    return ExponentialLift(
        H=H,
        weights=weights,
        rates=rates,
        grid=grid,
        target=target,
        approximation=approximation,
        relative_rmse=float(np.sqrt(np.mean(rel ** 2))),
        max_relative_error=float(np.max(np.abs(rel))),
    )


def estimate_hurst_from_increments(
    series: Sequence[float],
    *,
    min_lag: int = 1,
    max_lag: Optional[int] = None,
    min_points: int = 64,
) -> Dict[str, Any]:
    """Estimate Hurst roughness H from log-log root-mean-square increments."""
    x = np.asarray(series, dtype=float).reshape(-1)
    if x.size < min_points or np.any(~np.isfinite(x)):
        raise ValueError(f"series must have >= {min_points} finite samples")

    max_lag = max_lag or max(min_lag + 2, min(x.size // 8, 64))
    if min_lag < 1 or max_lag <= min_lag or max_lag >= x.size // 2:
        raise ValueError("invalid lag range")

    lags = np.arange(min_lag, max_lag + 1)
    rms = np.array([np.sqrt(np.mean((x[lag:] - x[:-lag]) ** 2)) for lag in lags])
    good = np.isfinite(rms) & (rms > 0)
    if good.sum() < 3:
        raise ValueError("insufficient nonzero increment scales")

    slope, intercept = np.polyfit(np.log(lags[good]), np.log(rms[good]), 1)
    predicted = intercept + slope * np.log(lags[good])
    residuals = np.log(rms[good]) - predicted
    ss_tot = np.sum((np.log(rms[good]) - np.mean(np.log(rms[good]))) ** 2)
    r_squared = float(1.0 - np.sum(residuals ** 2) / max(ss_tot, 1e-15))

    return {
        "H": float(slope),
        "intercept": float(intercept),
        "lags": lags[good],
        "rms_increments": rms[good],
        "r_squared": r_squared,
    }


def rough_skew_extrapolate(
    tau: Sequence[float] | float,
    *,
    psi_ref: float,
    tau_ref: float,
    H: float,
    sigma_ref: float,
    sigma_floor: float = 1e-4,
    sigma_cap: float = 5.0,
) -> np.ndarray:
    """Power-law ATM skew extrapolation psi(tau) = psi_ref * (tau / tau_ref)^(H - 1/2)."""
    if not (0.0 < H < 0.5) or tau_ref <= 0 or sigma_ref <= 0:
        raise ValueError("H must be in (0, 0.5), tau_ref and sigma_ref positive")

    tt = np.asarray(tau, dtype=float)
    if np.any(~np.isfinite(tt)) or np.any(tt < 1 / 365) or np.any(tt > 30 / 365):
        raise ValueError("tau must be within [1/365, 30/365] years")

    if not all(map(math.isfinite, [psi_ref, sigma_ref, sigma_floor, sigma_cap])) or sigma_floor <= 0 or sigma_cap < sigma_floor:
        raise ValueError("invalid finite calibration bounds")

    psi = psi_ref * np.power(tt / tau_ref, H - 0.5)
    return np.clip(psi, -sigma_cap, sigma_cap)


def svi_g(
    k: Sequence[float] | float,
    *,
    a: float,
    b: float,
    rho: float,
    m: float,
    sigma: float,
) -> np.ndarray:
    """Gatheral butterfly density diagnostic g(k) for raw SVI total variance w(k)."""
    if b < 0 or not (-1.0 < rho < 1.0) or sigma <= 0 or not all(map(math.isfinite, [a, b, rho, m, sigma])):
        raise ValueError("invalid raw-SVI parameters")

    kk = np.asarray(k, dtype=float)
    if np.any(~np.isfinite(kk)):
        raise ValueError("k must be finite")

    z = kk - m
    root = np.sqrt(z * z + sigma * sigma)
    w = a + b * (rho * z + root)
    wp = b * (rho + z / root)
    wpp = b * sigma * sigma / (root ** 3)

    safe_w = np.maximum(w, 1e-14)
    g = (1.0 - kk * wp / (2.0 * safe_w)) ** 2 - (wp * wp / 4.0) * (1.0 / safe_w + 0.25) + wpp / 2.0
    return g


def check_surface_arbitrage(
    k_grid: Sequence[float],
    tau_grid: Sequence[float],
    total_variance: Sequence[Sequence[float]],
    *,
    tolerance: float = 1e-8,
) -> Dict[str, Any]:
    """Check no-calendar monotonicity and non-negative total variance on a discrete grid."""
    k = np.asarray(k_grid, dtype=float)
    tau = np.asarray(tau_grid, dtype=float)
    w = np.asarray(total_variance, dtype=float)

    if k.ndim != 1 or tau.ndim != 1 or w.shape != (tau.size, k.size):
        raise ValueError("grid/variance shapes are inconsistent")
    if np.any(~np.isfinite(w)) or np.any(~np.isfinite(k)) or np.any(~np.isfinite(tau)):
        raise ValueError("surface grid must be finite")
    if np.any(tau <= 0) or np.any(np.diff(tau) <= 0):
        raise ValueError("maturities must be positive and strictly increasing")

    calendar_diff = np.diff(w, axis=0)

    return {
        "nonnegative_total_variance": bool(np.all(w >= -tolerance)),
        "calendar_monotone": bool(np.all(calendar_diff >= -tolerance)),
        "min_calendar_increment": float(np.min(calendar_diff)) if calendar_diff.size else math.inf,
        "min_total_variance": float(np.min(w)),
        "tolerance": tolerance,
    }


class RoughVolState(str, Enum):
    IDLE = "IDLE"
    CALIBRATION_ACTIVE = "CALIBRATION_ACTIVE"
    SURFACE_VALIDATION = "SURFACE_VALIDATION"
    VOLATILITY_SPIKE_HALT = "VOLATILITY_SPIKE_HALT"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RoughVolEvent(str, Enum):
    START_CALIBRATION = "START_CALIBRATION"
    CALIBRATION_DONE = "CALIBRATION_DONE"
    SURFACE_ACCEPTED = "SURFACE_ACCEPTED"
    SPIKE = "SPIKE"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"
    RESET = "RESET"


@dataclass
class Cycle21StateMachine:
    state: RoughVolState = RoughVolState.IDLE
    emergency_latched: bool = False
    history: List[Tuple[RoughVolEvent, RoughVolState, str]] = field(default_factory=list)

    def transition(self, event: RoughVolEvent) -> RoughVolState:
        if self.emergency_latched and event != RoughVolEvent.RECOVERY_ACK:
            self.history.append((event, self.state, "blocked_latched"))
            return self.state

        if event == RoughVolEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RoughVolState.EMERGENCY_UNWIND
        elif event == RoughVolEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RoughVolState.IDLE
        elif event == RoughVolEvent.SPIKE:
            self.state = RoughVolState.VOLATILITY_SPIKE_HALT
        elif event == RoughVolEvent.START_CALIBRATION and self.state == RoughVolState.IDLE:
            self.state = RoughVolState.CALIBRATION_ACTIVE
        elif event == RoughVolEvent.CALIBRATION_DONE and self.state == RoughVolState.CALIBRATION_ACTIVE:
            self.state = RoughVolState.SURFACE_VALIDATION
        elif event == RoughVolEvent.SURFACE_ACCEPTED and self.state == RoughVolState.SURFACE_VALIDATION:
            self.state = RoughVolState.IDLE
        elif event == RoughVolEvent.RESET and self.state != RoughVolState.EMERGENCY_UNWIND:
            self.state = RoughVolState.IDLE

        self.history.append((event, self.state, "accepted"))
        return self.state


def dispatch_live_order(*args, **kwargs):
    if not LIVE_ORDER_DISPATCH_ENABLED:
        raise RuntimeError("live order dispatch is disabled by invariant")
    raise RuntimeError("no live broker adapter exists in this reference package")
