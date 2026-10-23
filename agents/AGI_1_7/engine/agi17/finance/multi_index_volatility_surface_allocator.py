"""Cycle 19: Multi-Asset Intraday Volatility Surface Co-Movement & Joint Orthogonal Skew Factorization Engine.

Mathematical Foundations:
1. Surface Parameterization & Skew Extraction:
   Total implied variance at maturity tau:
     w(k, tau) = a + psi * k + mu * k^2
   where k = ln(K / F) is log-moneyness.
   - sigma_0 = sqrt(max(a, 0) / tau): instantaneous ATM volatility level.
   - psi = dw / dk |_{k=0}: ATM skew slope.
   - mu: smile curvature coefficient.

2. Orthogonalized Cross-Asset Shock Propagator:
   Joint state vector:
     x_t = [sigma_0^N, psi^N, sigma_0^B, psi^B]^T in R^4.
   Raw shock: Delta x_t = x_t - x_{t-1}.
   Online EWMA Covariance with ridge regularization:
     Sigma_t = decay * Sigma_{t-1} + (1 - decay) * (Delta x_t)(Delta x_t)^T.
   Cholesky decomposition: Sigma_t = L_t L_t^T.
   Orthogonal innovation: z_t = L_t^{-1} Delta x_t.
   Cross-asset lead-lag regression:
     Delta x_t^{N} = M_{t-1} Delta x_{t-1}^{B} + epsilon_t.

3. Convex Risk-Liquidity Greek Allocation:
   min_w  0.5 w^T Q w - r^T w + turnover_penalty * ||w - w_0||^2
   subject to:
     delta^T w = 0                              (Joint Delta Neutrality)
     |vega^T w| <= Vega_max                     (Vega Budget)
     |gamma^T w| <= Gamma_max                   (Gamma Budget)
     -w_max <= w_i <= w_max                     (Exposure Limits)
   where Q = Cov + diag(2 * spread_cost + 2 * liquidity_penalty + 2 * turnover_penalty).

4. Lead-Lag Jump Detection & Regime Filter:
   Standardized return innovations z_t^B = |r_t^B| / scale^B, z_t^N = |r_t^N| / scale^N.
   Detects BANKNIFTY lead-shock propagating to NIFTY within delay_steps.
   Latches VOLATILITY_SPIKE_HALT upon sudden jump clustering until acknowledged.

5. Latched Fail-Closed State Machine:
   States: IDLE -> SURFACE_MONITORING -> ALLOCATION_ACTIVE | VOLATILITY_SPIKE_HALT | EMERGENCY_UNWIND.
   LIVE_ORDER_DISPATCH_ENABLED = False locked.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

LIVE_ORDER_DISPATCH_ENABLED: bool = False


class SurfaceFitError(ValueError):
    pass


@dataclass(frozen=True)
class SurfacePoint:
    log_moneyness: float
    tau_years: float
    implied_vol: float
    weight: float = 1.0


@dataclass(frozen=True)
class SurfaceParameters:
    total_variance_level: float
    sigma0: float
    skew_slope: float
    curvature: float
    tau_years: float
    rmse: float
    n_points: int


def fit_total_variance_surface(
    points: Sequence[SurfacePoint],
    *,
    min_points: int = 5,
    curvature_floor: float = 0.0,
) -> SurfaceParameters:
    """Fit quadratic total variance w(k, tau) = a + psi * k + mu * k^2 at a single expiry."""
    if len(points) < min_points:
        raise SurfaceFitError(f"need at least {min_points} points")

    taus = np.asarray([p.tau_years for p in points], dtype=float)
    if np.any(~np.isfinite(taus)) or np.any(taus <= 0):
        raise SurfaceFitError("tau_years must be finite and positive")

    tau = float(np.median(taus))
    if np.max(np.abs(taus - tau)) > max(1e-8, tau * 1e-4):
        raise SurfaceFitError("fit one expiry at a time; tau values differ")

    k = np.asarray([p.log_moneyness for p in points], dtype=float)
    iv = np.asarray([p.implied_vol for p in points], dtype=float)
    wt = np.asarray([p.weight for p in points], dtype=float)

    if np.any(~np.isfinite(k)) or np.any(~np.isfinite(iv)) or np.any(iv <= 0):
        raise SurfaceFitError("moneyness must be finite and IV finite/positive")
    if np.any(~np.isfinite(wt)) or np.any(wt <= 0):
        raise SurfaceFitError("weights must be finite and positive")

    w = iv * iv * taus
    X = np.column_stack((np.ones_like(k), k, k * k))
    sw = np.sqrt(wt)
    coef, *_ = np.linalg.lstsq(X * sw[:, None], w * sw, rcond=None)

    if not np.all(np.isfinite(coef)):
        raise SurfaceFitError("surface fit is non-finite")

    a, psi, mu = map(float, coef)
    fitted = X @ coef
    rmse = float(np.sqrt(np.average((w - fitted) ** 2, weights=wt)))
    mu = max(mu, curvature_floor)

    return SurfaceParameters(
        total_variance_level=a,
        sigma0=math.sqrt(max(a, 0.0) / tau),
        skew_slope=psi,
        curvature=mu,
        tau_years=tau,
        rmse=rmse,
        n_points=len(points),
    )


@dataclass
class OrthogonalShockPropagator:
    """EWMA covariance whitening and online cross-asset shock transmission."""
    decay: float = 0.94
    ridge: float = 1e-8
    covariance: np.ndarray = field(default_factory=lambda: np.eye(4) * 1e-6)
    previous: Optional[np.ndarray] = None
    fitted_cross_lag: np.ndarray = field(default_factory=lambda: np.zeros((2, 2)))
    _lag_x: List[np.ndarray] = field(default_factory=list, repr=False)
    _lag_y: List[np.ndarray] = field(default_factory=list, repr=False)

    def __post_init__(self):
        if not (0.0 < self.decay < 1.0):
            raise ValueError("decay must lie strictly between 0 and 1")
        self.covariance = np.asarray(self.covariance, dtype=float).reshape(4, 4)

    def update(self, state: Sequence[float]) -> Dict[str, Any]:
        x = np.asarray(state, dtype=float).reshape(4)
        if not np.all(np.isfinite(x)):
            raise ValueError("state must be finite")

        if self.previous is None:
            shock = np.zeros(4)
        else:
            shock = x - self.previous
            self.covariance = self.decay * self.covariance + (1.0 - self.decay) * np.outer(shock, shock)
            if np.linalg.norm(shock[2:]) > 0:
                self._lag_x.append(shock[2:].copy())
                self._lag_y.append(shock[:2].copy())
                if len(self._lag_x) >= 8:
                    X = np.asarray(self._lag_x)
                    Y = np.asarray(self._lag_y)
                    self.fitted_cross_lag = np.linalg.solve(X.T @ X + self.ridge * np.eye(2), X.T @ Y).T

        self.previous = x.copy()
        cov = (self.covariance + self.covariance.T) / 2.0 + self.ridge * np.eye(4)
        L = np.linalg.cholesky(cov)
        orthogonal = np.linalg.solve(L, shock)
        predicted_nifty = self.fitted_cross_lag @ shock[2:]

        return {
            "raw_shock": shock.copy(),
            "orthogonal_shock": orthogonal,
            "predicted_nifty_from_bank_lag": predicted_nifty,
            "cross_lag_matrix": self.fitted_cross_lag.copy(),
            "covariance": self.covariance.copy(),
        }


@dataclass(frozen=True)
class AssetGreeks:
    delta: float
    vega: float
    gamma: float
    expected_return: float = 0.0
    variance: float = 1.0
    spread_cost: float = 0.0
    liquidity_penalty: float = 0.0
    label: str = ""


@dataclass(frozen=True)
class AllocationResult:
    weights: np.ndarray
    objective: float
    joint_delta: float
    joint_vega: float
    joint_gamma: float
    success: bool
    message: str


def optimize_joint_allocation(
    assets: Sequence[AssetGreeks],
    covariance: np.ndarray,
    *,
    vega_max: float,
    gamma_max: float,
    delta_tolerance: float = 1e-6,
    max_weight: float = 1.0,
    turnover_penalty: float = 0.0,
    initial_weights: Optional[Sequence[float]] = None,
) -> AllocationResult:
    """Convex quadratic optimization with linear Greek neutrality bounds and liquidity friction."""
    n = len(assets)
    if n < 1:
        raise ValueError("at least one asset exposure is required")

    C = np.asarray(covariance, dtype=float)
    if C.shape != (n, n) or not np.all(np.isfinite(C)):
        raise ValueError("covariance shape/values invalid")

    C = (C + C.T) / 2.0
    eig_min = float(np.min(np.linalg.eigvalsh(C)))
    if eig_min < -1e-8:
        raise ValueError("covariance must be positive semidefinite")

    if vega_max < 0 or gamma_max < 0 or max_weight <= 0:
        raise ValueError("risk limits must be nonnegative and max_weight positive")

    delta = np.array([a.delta for a in assets], float)
    vega = np.array([a.vega for a in assets], float)
    gamma = np.array([a.gamma for a in assets], float)
    ret = np.array([a.expected_return for a in assets], float)
    liq = np.array([max(0.0, a.spread_cost) + max(0.0, a.liquidity_penalty) for a in assets])
    w0 = np.zeros(n) if initial_weights is None else np.asarray(initial_weights, float).reshape(n)
    Q = C + np.diag(2.0 * liq + 2.0 * turnover_penalty)

    def objective(w):
        d = w - w0
        return float(0.5 * w @ Q @ w - ret @ w + turnover_penalty * (d @ d))

    def grad(w):
        return Q @ w - ret

    constraints = [
        {"type": "eq", "fun": lambda w: float(delta @ w), "jac": lambda w: delta},
        {"type": "ineq", "fun": lambda w: float(vega_max - vega @ w), "jac": lambda w: -vega},
        {"type": "ineq", "fun": lambda w: float(vega_max + vega @ w), "jac": lambda w: vega},
        {"type": "ineq", "fun": lambda w: float(gamma_max - gamma @ w), "jac": lambda w: -gamma},
        {"type": "ineq", "fun": lambda w: float(gamma_max + gamma @ w), "jac": lambda w: gamma},
    ]

    try:
        from scipy.optimize import minimize
        res = minimize(
            objective,
            w0,
            jac=grad,
            method="SLSQP",
            bounds=[(-max_weight, max_weight)] * n,
            constraints=constraints,
            options={"maxiter": 500, "ftol": 1e-11},
        )
        w = np.asarray(res.x, float)
        success = bool(
            res.success
            and abs(delta @ w) <= max(delta_tolerance, 1e-5)
            and abs(vega @ w) <= vega_max + 1e-5
            and abs(gamma @ w) <= gamma_max + 1e-5
        )
        message = str(res.message)
    except ImportError:
        w = np.zeros(n)
        success = bool(np.all(np.abs(delta) < 1e-12) or n > 1 and np.linalg.matrix_rank(delta.reshape(1, -1)) < n)
        message = "SciPy unavailable; conservative zero-allocation fallback"

    return AllocationResult(
        weights=w,
        objective=objective(w),
        joint_delta=float(delta @ w),
        joint_vega=float(vega @ w),
        joint_gamma=float(gamma @ w),
        success=success,
        message=message,
    )


@dataclass(frozen=True)
class TransmissionEvent:
    bank_shock: float
    nifty_shock: float
    propagated: bool
    delay_steps: int
    regime: str


@dataclass
class LeadLagVolatilityFilter:
    """Finite-memory BANKNIFTY-to-NIFTY volatility jump propagation detector."""
    threshold: float = 3.0
    delay_steps: int = 2
    decay: float = 0.85
    bank_scale: float = 1e-4
    nifty_scale: float = 1e-4
    _queue: deque = field(default_factory=deque, repr=False)
    bank_ewma: float = 0.0
    nifty_ewma: float = 0.0
    halted: bool = False

    def __post_init__(self):
        if self.threshold <= 0 or self.delay_steps < 0 or not (0.0 < self.decay < 1.0):
            raise ValueError("invalid filter parameters")
        if self.bank_scale <= 0 or self.nifty_scale <= 0:
            raise ValueError("scales must be positive")

    def update(self, bank_return: float, nifty_return: float) -> TransmissionEvent:
        if not math.isfinite(bank_return) or not math.isfinite(nifty_return):
            raise ValueError("returns must be finite")

        bank_z = abs(bank_return) / self.bank_scale
        nifty_z = abs(nifty_return) / self.nifty_scale
        self.bank_ewma = self.decay * self.bank_ewma + (1.0 - self.decay) * bank_z
        self.nifty_ewma = self.decay * self.nifty_ewma + (1.0 - self.decay) * nifty_z

        bank_jump = bank_z >= self.threshold
        nifty_jump = nifty_z >= self.threshold
        self._queue.append((bank_jump, nifty_jump, bank_z, nifty_z))

        if len(self._queue) > self.delay_steps + 1:
            self._queue.popleft()

        propagated = False
        observed_delay = 0

        if nifty_jump and len(self._queue) >= 2:
            for idx in range(len(self._queue) - 2, -1, -1):
                prior = self._queue[idx]
                delay = len(self._queue) - 1 - idx
                if delay <= self.delay_steps and prior[0] and not prior[1]:
                    propagated = True
                    observed_delay = delay
                    break

        if bank_jump or nifty_jump:
            self.halted = True

        regime = "VOLATILITY_SPIKE" if self.halted else "NORMAL"
        return TransmissionEvent(bank_return, nifty_return, propagated, observed_delay, regime)

    def acknowledge_recovery(self):
        self.halted = False
        self._queue.clear()


class RiskState(str, Enum):
    IDLE = "IDLE"
    SURFACE_MONITORING = "SURFACE_MONITORING"
    ALLOCATION_ACTIVE = "ALLOCATION_ACTIVE"
    VOLATILITY_SPIKE_HALT = "VOLATILITY_SPIKE_HALT"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START_MONITORING = "START_MONITORING"
    ALLOCATION_APPROVED = "ALLOCATION_APPROVED"
    SPIKE = "SPIKE"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"
    RESET = "RESET"


@dataclass
class Cycle19StateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    history: List[Tuple[RiskEvent, RiskState, str]] = field(default_factory=list)

    def transition(self, event: RiskEvent) -> RiskState:
        if self.emergency_latched and event != RiskEvent.RECOVERY_ACK:
            self.history.append((event, self.state, "blocked_latched"))
            return self.state

        if event == RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event == RiskEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event == RiskEvent.SPIKE:
            self.state = RiskState.VOLATILITY_SPIKE_HALT
        elif event == RiskEvent.START_MONITORING and self.state == RiskState.IDLE:
            self.state = RiskState.SURFACE_MONITORING
        elif event == RiskEvent.ALLOCATION_APPROVED and self.state == RiskState.SURFACE_MONITORING:
            self.state = RiskState.ALLOCATION_ACTIVE
        elif event == RiskEvent.RESET and self.state != RiskState.EMERGENCY_UNWIND:
            self.state = RiskState.IDLE

        self.history.append((event, self.state, "accepted"))
        return self.state


def dispatch_live_order(*args, **kwargs):
    if not LIVE_ORDER_DISPATCH_ENABLED:
        raise RuntimeError("live order dispatch is disabled by invariant")
    raise RuntimeError("no live broker adapter exists in this reference package")
