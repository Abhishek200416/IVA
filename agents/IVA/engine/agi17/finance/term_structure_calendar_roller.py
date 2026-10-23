"""
Cycle 16: Term-Structure & Calendar Roll Engine with Arbitrage Preservation.

Implements frontier mathematical methods researched from ChatGPT Cycle 16:
1. Arbitrage-Preserving Log-Forward Variance Evolution:
       z_i(t+dt) = zbar_i + exp(-eta_i*dt)*(z_i(t)-zbar_i)
                   + beta_i*(lambda_jump - lambda_bar)*C_i
   where C_i accounts for transient intensity decay omega (including the equal-decay-rate branch).
   Forward variance q_i = exp(z_i) > 0 guarantees ATM total variance
       theta(tau) = integral_0^tau q(u) du
   is strictly monotonic: d theta / d tau = q > 0, structurally eliminating calendar arbitrage.
2. Localized Forward VRP with Downside Tail-Hazard Penalization:
   Interval-aware jump integration over [tau_near, tau_next] without double-counting expected variance.
3. Dimensionless Expiry Pin-Risk Scoring:
   Normalized against cash gamma, settlement band width, and portfolio risk budget.
4. Corrected Carry-Risk Roll Score:
   Measures next-expiry carry/risk minus near-expiry carry/risk minus jump hazard.
5. 5-State Discrete State Machine with Latched Emergency & Fail-Closed Safety:
   HOLD -> PRE_ROLL_ALERT -> EXECUTE_ROLL / EMERGENCY_DELEVERAGE / ARBITRAGE_REPAIR.

Fail-Closed Safety Invariant:
    LIVE_ORDER_DISPATCH_ENABLED = False (broker order submission locked).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence, Tuple
import numpy as np

# Immutable Fail-Closed Safety Invariant
LIVE_ORDER_DISPATCH_ENABLED: bool = False


class EngineState(str, Enum):
    HOLD = "HOLD"
    PRE_ROLL_ALERT = "PRE_ROLL_ALERT"
    EXECUTE_ROLL = "EXECUTE_ROLL"
    EMERGENCY_DELEVERAGE = "EMERGENCY_DELEVERAGE"
    ARBITRAGE_REPAIR = "ARBITRAGE_REPAIR"


def _finite_array(name: str, value: Sequence[float], length: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1 or (length is not None and arr.size != length):
        suffix = f" of length {length}" if length is not None else ""
        raise ValueError(f"{name} must be a 1D array{suffix}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _validate_tau(tau_grid: Sequence[float], *, require_zero: bool = True) -> np.ndarray:
    tau = _finite_array("tau_grid", tau_grid)
    if tau.size < 2:
        raise ValueError("tau_grid must contain at least two points")
    if require_zero and abs(float(tau[0])) > 1e-12:
        raise ValueError("tau_grid must start at tau=0 so theta(0)=0 is explicit")
    if not require_zero and tau[0] < 0:
        raise ValueError("tau_grid maturities must be non-negative")
    if np.any(np.diff(tau) <= 0):
        raise ValueError("tau_grid must be strictly increasing")
    return tau


def _intensity_convolution(eta: np.ndarray, omega: float, dt: float) -> np.ndarray:
    """Integral exp(-eta*(dt-u))*exp(-omega*u) du from 0 to dt."""
    den = eta - omega
    out = np.empty_like(eta)
    close = np.abs(den) < 1e-8
    out[close] = dt * np.exp(-eta[close] * dt)
    out[~close] = (
        np.exp(-omega * dt) - np.exp(-eta[~close] * dt)
    ) / den[~close]
    return out


def propagate_log_forward_variance(
    tau_grid: Sequence[float],
    log_forward_variance: Sequence[float],
    log_forward_variance_baseline: Sequence[float],
    eta_tau: Sequence[float],
    beta_tau: Sequence[float],
    *,
    lambda_jump: float,
    lambda_bar: float,
    dt: float,
    intensity_mean_reversion: float = 0.0,
    max_abs_log_forward_variance: float = 30.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Propagate log forward variance and reconstruct arbitrage-safe ATM theta.

    State equation at each tenor-grid node i:
        z_i(t+dt) = zbar_i + exp(-eta_i*dt)*(z_i(t)-zbar_i)
                    + beta_i*(lambda_jump-lambda_bar)*C_i
    where C_i = integral_0^dt exp(-eta_i*(dt-u))*exp(-omega*u) du.
    omega=0 treats the current intensity deviation as constant during dt.
    For omega>0, the expected intensity deviation decays as exp(-omega*u).

    Forward variance q_i = exp(z_i) is positive. Total variance is theta(tau)
    = integral_0^tau q(u) du, approximated by trapezoidal integration on tau_grid.
    This guarantees theta(0)=0 and monotonically increasing theta at grid nodes.
    """
    tau = _validate_tau(tau_grid)
    n = tau.size
    z = _finite_array("log_forward_variance", log_forward_variance, n)
    zbar = _finite_array("log_forward_variance_baseline", log_forward_variance_baseline, n)
    eta = _finite_array("eta_tau", eta_tau, n)
    beta = _finite_array("beta_tau", beta_tau, n)

    scalars = [lambda_jump, lambda_bar, dt, intensity_mean_reversion, max_abs_log_forward_variance]
    if not all(math.isfinite(float(v)) for v in scalars):
        raise ValueError("scalar inputs must be finite")
    if lambda_jump < 0 or lambda_bar < 0:
        raise ValueError("Hawkes intensities must be non-negative")
    if dt <= 0 or intensity_mean_reversion < 0:
        raise ValueError("dt must be positive and intensity_mean_reversion non-negative")
    if max_abs_log_forward_variance <= 0:
        raise ValueError("max_abs_log_forward_variance must be positive")
    if np.any(eta <= 0):
        raise ValueError("eta_tau must be strictly positive")
    if np.any(beta < 0):
        raise ValueError("beta_tau must be non-negative for non-negative jump-hazard loading")

    decay = np.exp(-eta * dt)
    conv = _intensity_convolution(eta, float(intensity_mean_reversion), float(dt))
    z_next = zbar + decay * (z - zbar) + beta * (lambda_jump - lambda_bar) * conv

    if not np.all(np.isfinite(z_next)) or np.any(np.abs(z_next) > max_abs_log_forward_variance):
        raise ValueError("propagated log forward variance outside numerical safety bounds")

    q_next = np.exp(z_next)
    if not np.all(np.isfinite(q_next)) or np.any(q_next <= 0):
        raise ValueError("forward variance must be finite and strictly positive")

    theta = np.zeros_like(tau)
    increments = 0.5 * (q_next[:-1] + q_next[1:]) * np.diff(tau)
    theta[1:] = np.cumsum(increments)
    if np.any(np.diff(theta) <= 0):
        raise ArithmeticError("positive forward variance should imply strictly increasing theta")
    return z_next, q_next, theta


def calendar_monotonicity_violation(
    tau_grid: Sequence[float],
    theta: Sequence[float],
    *,
    tolerance: float = 1e-10,
) -> bool:
    """Check sampled ATM no-calendar-arbitrage condition dtheta/dtau >= 0."""
    tau = _validate_tau(tau_grid, require_zero=False)
    th = _finite_array("theta", theta, tau.size)
    if tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("tolerance must be finite and non-negative")
    return bool(np.any(np.diff(th) < -tolerance))


def expected_hazard_count(
    lambda_jump: float,
    lambda_bar: float,
    horizon: float,
    *,
    intensity_mean_reversion: float,
) -> float:
    """Expected jump count over H under E[lambda(t+u)]=bar+(lambda-bar)e^(-omega u)."""
    vals = [lambda_jump, lambda_bar, horizon, intensity_mean_reversion]
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("hazard inputs must be finite")
    if lambda_jump < 0 or lambda_bar < 0 or horizon < 0 or intensity_mean_reversion < 0:
        raise ValueError("intensities, horizon, and decay rate must be non-negative")
    if horizon == 0:
        return 0.0
    if intensity_mean_reversion == 0:
        return float(lambda_jump * horizon)
    omega = intensity_mean_reversion
    return float(lambda_bar * horizon + (lambda_jump - lambda_bar) * (-math.expm1(-omega * horizon)) / omega)


def expected_hazard_count_interval(
    lambda_jump: float,
    lambda_bar: float,
    start: float,
    end: float,
    *,
    intensity_mean_reversion: float,
) -> float:
    """Expected jump count on forward interval [start, end].

    Uses E_t[lambda(t+u)] = lambda_bar + (lambda_jump-lambda_bar)*exp(-omega*u).
    """
    vals = [lambda_jump, lambda_bar, start, end, intensity_mean_reversion]
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("hazard-interval inputs must be finite")
    if lambda_jump < 0 or lambda_bar < 0 or start < 0 or end < start or intensity_mean_reversion < 0:
        raise ValueError("invalid hazard interval or intensity inputs")
    if end == start:
        return 0.0
    omega = intensity_mean_reversion
    width = end - start
    if omega == 0:
        return float(lambda_jump * width)
    transient = (lambda_jump - lambda_bar) * (math.exp(-omega * start) - math.exp(-omega * end)) / omega
    return float(lambda_bar * width + transient)


def localized_forward_vrp_hazard_adjusted(
    *,
    tau_near: float,
    tau_next: float,
    theta_iv_near: float,
    theta_iv_next: float,
    expected_total_rv_near: float,
    expected_total_rv_next: float,
    lambda_jump: float,
    lambda_bar: float,
    downside_jump_return_sq_per_event: float,
    jump_risk_aversion: float = 1.0,
    intensity_mean_reversion: float = 0.0,
) -> Tuple[float, float, float]:
    """Forward-segment VRP for [tau_near, tau_next], with an added hazard penalty.

    Returns (raw_forward_vrp_rate, hazard_penalty_rate, risk_adjusted_forward_vrp_rate).
    """
    vals = [tau_near, tau_next, theta_iv_near, theta_iv_next,
            expected_total_rv_near, expected_total_rv_next,
            downside_jump_return_sq_per_event, jump_risk_aversion]
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("localized VRP inputs must be finite")
    if tau_near < 0 or tau_next <= tau_near:
        raise ValueError("require 0 <= tau_near < tau_next")
    if min(theta_iv_near, theta_iv_next, expected_total_rv_near, expected_total_rv_next) < 0:
        raise ValueError("total variance inputs must be non-negative")
    if downside_jump_return_sq_per_event < 0 or jump_risk_aversion < 0:
        raise ValueError("jump severity and risk aversion must be non-negative")

    width = tau_next - tau_near
    implied_forward_rate = (theta_iv_next - theta_iv_near) / width
    expected_realized_forward_rate = (expected_total_rv_next - expected_total_rv_near) / width
    raw = implied_forward_rate - expected_realized_forward_rate
    count = expected_hazard_count_interval(
        lambda_jump, lambda_bar, tau_near, tau_next,
        intensity_mean_reversion=intensity_mean_reversion,
    )
    penalty = jump_risk_aversion * count * downside_jump_return_sq_per_event / width
    return float(raw), float(penalty), float(raw - penalty)


def pin_risk_score(
    gamma_cash_per_point_sq: Sequence[float],
    pin_probability: Sequence[float],
    pin_band_points: Sequence[float],
    *,
    risk_budget_cash: float,
) -> float:
    """Dimensionless expiry pin-risk score from near-expiry position Greeks."""
    gamma = _finite_array("gamma_cash_per_point_sq", gamma_cash_per_point_sq)
    prob = _finite_array("pin_probability", pin_probability, gamma.size)
    band = _finite_array("pin_band_points", pin_band_points, gamma.size)
    if gamma.size == 0:
        raise ValueError("at least one near-expiry position is required")
    if not math.isfinite(float(risk_budget_cash)) or risk_budget_cash <= 0:
        raise ValueError("risk_budget_cash must be finite and positive")
    if np.any(prob < 0) or np.any(prob > 1):
        raise ValueError("pin probabilities must lie in [0, 1]")
    if np.any(band <= 0):
        raise ValueError("pin bands must be positive")
    expected_pin_gamma_loss = 0.5 * np.abs(gamma) * band**2 * prob
    return float(np.sum(expected_pin_gamma_loss) / risk_budget_cash)


def hazard_adjusted_vrp(
    implied_variance_rate: float,
    expected_total_realized_variance_rate: float,
    *,
    lambda_jump: float,
    lambda_bar: float,
    horizon: float,
    downside_jump_return_sq_per_event: float,
    jump_risk_aversion: float = 1.0,
    intensity_mean_reversion: float = 0.0,
) -> Tuple[float, float, float]:
    """Return (raw_vrp, hazard_penalty_rate, risk_adjusted_vrp)."""
    vals = [implied_variance_rate, expected_total_realized_variance_rate,
            downside_jump_return_sq_per_event, jump_risk_aversion]
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("VRP inputs must be finite")
    if implied_variance_rate < 0 or expected_total_realized_variance_rate < 0:
        raise ValueError("variance rates must be non-negative")
    if downside_jump_return_sq_per_event < 0 or jump_risk_aversion < 0:
        raise ValueError("jump severity and risk aversion must be non-negative")
    count = expected_hazard_count(
        lambda_jump, lambda_bar, horizon,
        intensity_mean_reversion=intensity_mean_reversion,
    )
    if horizon == 0:
        penalty = 0.0
    else:
        penalty = jump_risk_aversion * count * downside_jump_return_sq_per_event / horizon
    raw = implied_variance_rate - expected_total_realized_variance_rate
    return float(raw), float(penalty), float(raw - penalty)


def calendar_roll_score(
    *,
    carry_near_per_time: float,
    carry_next_per_time: float,
    gamma_near_abs: float,
    gamma_next_abs: float,
    stress_move: float,
    horizon: float,
    roll_cost: float,
    expected_jump_count: float,
    jump_damage_ratio: float,
    risk_floor: float = 1e-9,
) -> float:
    """Dimensionless roll advantage: next carry/risk minus near carry/risk.

    A positive score favors rolling, subject to separate hard risk/data gates.
    """
    vals = [carry_near_per_time, carry_next_per_time, gamma_near_abs,
            gamma_next_abs, stress_move, horizon, roll_cost, expected_jump_count,
            jump_damage_ratio, risk_floor]
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("roll-score inputs must be finite")
    if gamma_near_abs < 0 or gamma_next_abs < 0:
        raise ValueError("gamma magnitudes must be non-negative")
    if stress_move <= 0 or horizon < 0 or roll_cost < 0 or expected_jump_count < 0:
        raise ValueError("stress_move must be positive; horizon, cost, hazard non-negative")
    if jump_damage_ratio < 0 or risk_floor <= 0:
        raise ValueError("jump_damage_ratio must be non-negative and risk_floor positive")

    near_gamma_risk = max(0.5 * gamma_near_abs * stress_move**2, risk_floor)
    next_gamma_risk = max(0.5 * gamma_next_abs * stress_move**2, risk_floor)
    near_score = horizon * carry_near_per_time / near_gamma_risk
    next_score = (horizon * carry_next_per_time - roll_cost) / next_gamma_risk
    hazard_penalty = expected_jump_count * jump_damage_ratio
    return float(next_score - near_score - hazard_penalty)


@dataclass(frozen=True)
class RollPolicy:
    tau_alert: float
    pin_alert_threshold: float
    pin_emergency_threshold: float
    lambda_alert_threshold: float
    lambda_emergency_threshold: float
    roll_alert_threshold: float
    roll_execute_threshold: float

    def __post_init__(self) -> None:
        vals = [self.tau_alert, self.pin_alert_threshold,
                self.pin_emergency_threshold, self.lambda_alert_threshold,
                self.lambda_emergency_threshold, self.roll_alert_threshold,
                self.roll_execute_threshold]
        if not all(math.isfinite(float(v)) for v in vals):
            raise ValueError("policy thresholds must be finite")
        if self.tau_alert < 0:
            raise ValueError("tau_alert must be non-negative")
        if self.pin_alert_threshold < 0 or self.pin_emergency_threshold <= self.pin_alert_threshold:
            raise ValueError("pin emergency threshold must exceed non-negative alert threshold")
        if self.lambda_alert_threshold < 0 or self.lambda_emergency_threshold <= self.lambda_alert_threshold:
            raise ValueError("lambda emergency threshold must exceed non-negative alert threshold")
        if self.roll_execute_threshold < self.roll_alert_threshold:
            raise ValueError("roll_execute_threshold must be >= roll_alert_threshold")


@dataclass(frozen=True)
class RollSnapshot:
    tau_near: float
    pin_risk: float
    lambda_jump: float
    roll_score: float
    data_valid: bool = True
    calendar_violation: bool = False
    portfolio_risk_breach: bool = False
    execution_allowed: bool = True
    order_inflight: bool = False
    execution_reconciled: bool = True
    emergency_reset: bool = False

    def __post_init__(self) -> None:
        vals = [self.tau_near, self.pin_risk, self.lambda_jump, self.roll_score]
        if not all(math.isfinite(float(v)) for v in vals):
            raise ValueError("snapshot numeric inputs must be finite")
        if self.tau_near < 0 or self.pin_risk < 0 or self.lambda_jump < 0:
            raise ValueError("tau_near, pin_risk, and lambda_jump must be non-negative")


def next_roll_state(
    previous: EngineState,
    snapshot: RollSnapshot,
    policy: RollPolicy,
) -> EngineState:
    """Pure state transition. It emits states only; it does not place orders."""
    # Emergency state is latched until an explicit recovery acknowledgement.
    if previous == EngineState.EMERGENCY_DELEVERAGE and not snapshot.emergency_reset:
        return EngineState.EMERGENCY_DELEVERAGE

    # Hard risk triggers supersede ordinary roll logic.
    if (
        snapshot.portfolio_risk_breach
        or snapshot.pin_risk >= policy.pin_emergency_threshold
        or snapshot.lambda_jump >= policy.lambda_emergency_threshold
    ):
        return EngineState.EMERGENCY_DELEVERAGE

    # A broken surface or untrusted feed freezes new roll decisions.
    if not snapshot.data_valid or snapshot.calendar_violation:
        return EngineState.ARBITRAGE_REPAIR

    # Do not duplicate an order. Execution adapter must reconcile fills externally.
    if snapshot.order_inflight:
        return EngineState.EXECUTE_ROLL

    if previous == EngineState.EXECUTE_ROLL and not snapshot.execution_reconciled:
        return EngineState.ARBITRAGE_REPAIR

    pressure = (
        snapshot.tau_near <= policy.tau_alert
        or snapshot.pin_risk >= policy.pin_alert_threshold
        or snapshot.lambda_jump >= policy.lambda_alert_threshold
        or snapshot.roll_score >= policy.roll_alert_threshold
    )

    if previous == EngineState.PRE_ROLL_ALERT:
        if pressure and snapshot.execution_allowed and snapshot.roll_score >= policy.roll_execute_threshold:
            return EngineState.EXECUTE_ROLL
        if pressure:
            return EngineState.PRE_ROLL_ALERT
        return EngineState.HOLD

    if previous == EngineState.EXECUTE_ROLL:
        # After reconciliation, require a fresh alert cycle before another roll.
        return EngineState.PRE_ROLL_ALERT if pressure else EngineState.HOLD

    if pressure:
        return EngineState.PRE_ROLL_ALERT
    return EngineState.HOLD
