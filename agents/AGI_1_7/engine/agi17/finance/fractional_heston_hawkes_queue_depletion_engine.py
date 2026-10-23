"""Cycle 39 research engine: fractional Heston/Hawkes, FIFO queue, Kalman-SSVI.

This module is a deterministic, offline/paper-trading reference implementation.
It deliberately contains no broker adapter and cannot submit live orders.
Dependencies: Python 3.11+, NumPy, SciPy.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import threading
import time
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
from scipy.special import gamma as gamma_fn
from scipy.stats import norm

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_PAPER_CAPITAL = 10_000.0
IST = ZoneInfo("Asia/Kolkata")


def _finite_float(value: float, name: str) -> float:
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _array(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    a = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must contain finite values")
    if ndim is not None and a.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    return a


def _spectral_radius(matrix: np.ndarray) -> float:
    if matrix.size == 0:
        return 0.0
    return float(np.max(np.abs(np.linalg.eigvals(matrix))))


def _clip_probability(p: float) -> float:
    return float(np.clip(p, 0.0, 1.0))


class Regime(str, Enum):
    CALM = "CALM"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"


class RiskState(str, Enum):
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    HEDGE_ONLY = "HEDGE_ONLY"
    QUARANTINED = "QUARANTINED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


@dataclass(frozen=True)
class SSVIParameters:
    theta: float
    rho: float
    phi: float
    mu: float = 0.0

    def validate(self) -> None:
        if not math.isfinite(self.theta) or self.theta <= 0:
            raise ValueError("theta must be finite and positive")
        if not math.isfinite(self.rho) or not abs(self.rho) < 1:
            raise ValueError("rho must be strictly between -1 and 1")
        if not math.isfinite(self.phi) or self.phi <= 0:
            raise ValueError("phi must be finite and positive")
        if not math.isfinite(self.mu):
            raise ValueError("mu must be finite")


class FractionalKernel12:
    """12-factor nonnegative exponential approximation to the fractional kernel.

    Positive weights are fitted by non-negative least squares over a log-spaced
    time grid. It is a finite approximation, not an exact Volterra solution.
    """
    def __init__(self, hurst: float = 0.075, factors: int = 12,
                 t_min: float = 1e-4, t_max: float = 2.0) -> None:
        if not (0.05 < hurst < 0.45):
            raise ValueError("hurst must be in (0.05, 0.45)")
        if factors != 12:
            raise ValueError("Cycle 39 uses exactly 12 Markovian factors")
        if not (0 < t_min < t_max and math.isfinite(t_max)):
            raise ValueError("require 0 < t_min < t_max")
        self.hurst = float(hurst)
        self.factors = factors
        self.t_min = float(t_min)
        self.t_max = float(t_max)
        self.decays = np.geomspace(1.0 / t_max, 1.0 / t_min, factors)
        times = np.geomspace(t_min, t_max, 320)
        target = times ** (hurst - 0.5) / float(gamma_fn(hurst + 0.5))
        design = np.exp(-np.outer(times, self.decays))
        # NNLS makes the exponential mixture physically interpretable.
        from scipy.optimize import nnls
        self.weights, _ = nnls(design, target, maxiter=20_000)
        self.fit_rmse = float(np.sqrt(np.mean((design @ self.weights - target) ** 2)))
        if not np.all(self.weights >= 0) or not np.all(np.isfinite(self.weights)):
            raise ArithmeticError("kernel fit produced invalid weights")

    def kernel(self, t: float | Sequence[float]) -> float | np.ndarray:
        x = _array(t, "t")
        if np.any(x <= 0):
            raise ValueError("fractional kernel is singular at t <= 0")
        result = np.exp(-np.outer(x.reshape(-1), self.decays)) @ self.weights
        result = result.reshape(x.shape)
        return float(result) if result.ndim == 0 else result

    def exact_kernel(self, t: float | Sequence[float]) -> float | np.ndarray:
        x = _array(t, "t")
        if np.any(x <= 0):
            raise ValueError("fractional kernel is singular at t <= 0")
        out = x ** (self.hurst - 0.5) / float(gamma_fn(self.hurst + 0.5))
        return float(out) if np.ndim(out) == 0 else out

    def memory_half_life(self) -> float:
        # Half-life of the slowest exponential mode, a conservative memory scale.
        return math.log(2.0) / float(np.min(self.decays))


class FractionalHestonHawkesModel:
    """Two-asset rough-factor variance model coupled to a stable bivariate Hawkes."""
    def __init__(self, kernel: FractionalKernel12 | None = None,
                 xi0: Sequence[float] = (0.04, 0.06), seed: int = 39) -> None:
        self.kernel = kernel or FractionalKernel12()
        self.xi0 = _array(xi0, "xi0", 1)
        if self.xi0.shape != (2,) or np.any(self.xi0 <= 0):
            raise ValueError("xi0 must contain two positive variances")
        self.factor_state = np.zeros((2, self.kernel.factors), dtype=float)
        self.rng = np.random.default_rng(seed)
        self.hawkes = BivariateHawkes()

    def variance(self) -> np.ndarray:
        v = self.xi0 + self.factor_state @ self.kernel.weights
        return np.maximum(v, 1e-10)

    def update(self, dt: float, shocks: Sequence[float] | None = None,
               jump_shocks: Sequence[float] | None = None) -> np.ndarray:
        dt = _finite_float(dt, "dt")
        if dt <= 0:
            raise ValueError("dt must be positive")
        z = self.rng.normal(size=2) if shocks is None else _array(shocks, "shocks", 1)
        j = np.zeros(2) if jump_shocks is None else _array(jump_shocks, "jump_shocks", 1)
        if z.shape != (2,) or j.shape != (2,):
            raise ValueError("shocks and jump_shocks must have length 2")
        current_v = self.variance()
        decay = np.exp(-self.kernel.decays * dt)
        weight_scale = max(float(np.sum(self.kernel.weights)), 1.0)
        for asset in range(2):
            # Normalize innovations across the 12-factor representation so a
            # single observed shock is not counted once per factor.
            innovation = math.sqrt(current_v[asset] * dt) * z[asset] / weight_scale
            jump = j[asset] / weight_scale
            self.factor_state[asset] = decay * self.factor_state[asset] + innovation + jump
        out = self.variance()
        self.hawkes.advance(dt)
        return out


class BivariateHawkes:
    """Bivariate exponential Hawkes process with subcritical branching matrix."""
    def __init__(self, mu: Sequence[float] = (0.4, 0.5),
                 alpha: Sequence[Sequence[float]] = ((0.25, 0.12), (0.10, 0.22)),
                 beta: Sequence[Sequence[float]] = ((1.8, 1.8), (1.8, 1.8)),
                 max_radius: float = 0.899, seed: int = 39) -> None:
        self.mu = _array(mu, "mu", 1).copy()
        self.alpha = _array(alpha, "alpha", 2).copy()
        self.beta = _array(beta, "beta", 2).copy()
        if self.mu.shape != (2,) or np.any(self.mu <= 0):
            raise ValueError("mu must be positive length-2 vector")
        if self.alpha.shape != (2, 2) or np.any(self.alpha < 0):
            raise ValueError("alpha must be a nonnegative 2x2 matrix")
        if self.beta.shape != (2, 2) or np.any(self.beta <= 0):
            raise ValueError("beta must be a positive 2x2 matrix")
        if not 0 < max_radius < 1:
            raise ValueError("max_radius must be in (0,1)")
        self.max_radius = max_radius
        self.rng = np.random.default_rng(seed)
        self.trace = np.zeros((2, 2), dtype=float)
        self._project_stability()

    @property
    def branching(self) -> np.ndarray:
        return self.alpha / self.beta

    @property
    def spectral_radius(self) -> float:
        return _spectral_radius(self.branching)

    @property
    def intensity(self) -> np.ndarray:
        return self.mu + np.sum(self.alpha * self.trace, axis=1)

    @property
    def cross_excitation_asymmetry(self) -> float:
        a12, a21 = float(self.alpha[0, 1]), float(self.alpha[1, 0])
        return float(np.clip((a12 - a21) / (a12 + a21 + 1e-12), -1, 1))

    def _project_stability(self) -> None:
        rho = self.spectral_radius
        if rho >= self.max_radius:
            self.alpha *= (self.max_radius * 0.999999) / rho

    def advance(self, dt: float) -> np.ndarray:
        dt = _finite_float(dt, "dt")
        if dt < 0:
            raise ValueError("dt must be nonnegative")
        self.trace *= np.exp(-self.beta * dt)
        return self.intensity.copy()

    def event(self, source: int, count: int = 1) -> np.ndarray:
        if source not in (0, 1):
            raise ValueError("source must be 0 (NIFTY) or 1 (BANKNIFTY)")
        if not isinstance(count, int) or count < 0:
            raise ValueError("count must be a nonnegative integer")
        self.trace[:, source] += count
        return self.intensity.copy()

    def sgd_update(self, counts: Sequence[int], dt: float, learning_rate: float = 1e-3) -> dict[str, float]:
        """Projected stochastic-gradient step for binned Poisson log likelihood."""
        y = _array(counts, "counts", 1)
        dt = _finite_float(dt, "dt")
        lr = _finite_float(learning_rate, "learning_rate")
        if y.shape != (2,) or np.any(y < 0) or np.any(y != np.floor(y)):
            raise ValueError("counts must be two nonnegative integers")
        if dt <= 0 or lr <= 0:
            raise ValueError("dt and learning_rate must be positive")
        lam = np.maximum(self.intensity.copy(), 1e-12)
        score = y / lam - dt
        self.mu = np.maximum(1e-8, self.mu + lr * score)
        self.alpha = np.maximum(0.0, self.alpha + lr * score[:, None] * self.trace)
        self._project_stability()
        ll = float(np.sum(y * np.log(lam) - lam * dt))
        return {"log_likelihood": ll, "spectral_radius": self.spectral_radius}


class SSVISurface:
    """Sampled SSVI surface with a calendar-monotone projected variance grid."""
    def __init__(self, maturities: Sequence[float], theta: Sequence[float],
                 rho: float = -0.35, phi: float = 0.8, mu: float = 0.0,
                 k_grid: Sequence[float] | None = None) -> None:
        self.maturities = _array(maturities, "maturities", 1)
        self.theta_curve = _array(theta, "theta", 1)
        if self.maturities.size < 2 or self.maturities.shape != self.theta_curve.shape:
            raise ValueError("maturities/theta must have matching length >= 2")
        if np.any(self.maturities <= 0) or np.any(np.diff(self.maturities) <= 0):
            raise ValueError("maturities must be positive and strictly increasing")
        if np.any(self.theta_curve <= 0):
            raise ValueError("theta values must be positive")
        if not abs(rho) < 1 or phi <= 0 or not all(map(math.isfinite, (rho, phi, mu))):
            raise ValueError("invalid SSVI parameters")
        self.rho, self.phi, self.mu = float(rho), float(phi), float(mu)
        self.k_grid = np.asarray(k_grid if k_grid is not None else np.linspace(-2.0, 2.0, 161), dtype=float)
        if self.k_grid.ndim != 1 or len(self.k_grid) < 3 or not np.all(np.isfinite(self.k_grid)) or np.any(np.diff(self.k_grid) <= 0):
            raise ValueError("k_grid must be finite, sorted, and contain >= 3 points")
        self._rebuild()

    def _rebuild(self) -> None:
        raw = np.vstack([self._raw_row(th) for th in self.theta_curve])
        # Calendar projection at each sampled log-moneyness. The final grid is
        # monotone in maturity by construction, but remains a sampled diagnostic.
        self.raw_grid = raw
        self.projected_grid = np.maximum.accumulate(raw, axis=0)
        self.calendar_adjustment = float(np.max(np.abs(self.projected_grid - self.raw_grid)))

    def recondition(self, *, rho: float | None = None, phi: float | None = None,
                    theta_curve: Sequence[float] | None = None) -> None:
        new_rho = self.rho if rho is None else _finite_float(rho, "rho")
        new_phi = self.phi if phi is None else _finite_float(phi, "phi")
        if not abs(new_rho) < 1 or new_phi <= 0:
            raise ValueError("rho must be in (-1,1) and phi must be positive")
        if theta_curve is not None:
            values = _array(theta_curve, "theta_curve", 1)
            if values.shape != self.theta_curve.shape or np.any(values <= 0):
                raise ValueError("theta_curve must match original shape and be positive")
            self.theta_curve = values.copy()
        self.rho, self.phi = new_rho, new_phi
        self._rebuild()

    def _raw_row(self, theta: float) -> np.ndarray:
        phi_theta = self.phi / (1.0 + 0.25 * theta)
        x = phi_theta * self.k_grid + self.mu
        return 0.5 * theta * (1.0 + self.rho * phi_theta * self.k_grid + np.sqrt(x*x + (1.0 - self.rho*self.rho)))

    def raw_total_variance(self, k: float, maturity: float) -> float:
        if maturity <= 0:
            raise ValueError("maturity must be positive")
        th = float(np.interp(maturity, self.maturities, self.theta_curve))
        pt = self.phi / (1.0 + 0.25 * th)
        x = pt * float(k) + self.mu
        value = 0.5 * th * (1 + self.rho * pt * float(k) + math.sqrt(x*x + 1 - self.rho*self.rho))
        return max(float(value), 1e-12)

    def total_variance(self, k: float, maturity: float) -> float:
        if maturity <= 0:
            raise ValueError("maturity must be positive")
        by_t = np.array([np.interp(k, self.k_grid, row) for row in self.projected_grid])
        return max(float(np.interp(maturity, self.maturities, by_t)), 1e-12)

    def implied_volatility(self, k: float, maturity: float) -> float:
        return math.sqrt(self.total_variance(k, maturity) / maturity)

    def calendar_check(self, tolerance: float = 1e-12) -> dict[str, float | bool]:
        differences = np.diff(self.projected_grid, axis=0)
        raw_differences = np.diff(self.raw_grid, axis=0)
        return {"monotone": bool(np.min(differences) >= -tolerance),
                "minimum_projected_increment": float(np.min(differences)),
                "minimum_raw_increment": float(np.min(raw_differences)),
                "maximum_projection_adjustment": self.calendar_adjustment}

    def call_price(self, k: float, maturity: float, forward: float = 1.0, discount: float = 1.0) -> float:
        if maturity <= 0 or forward <= 0 or discount <= 0:
            raise ValueError("maturity, forward, discount must be positive")
        strike = forward * math.exp(float(k))
        total_var = self.total_variance(k, maturity)
        vol_sqrt_t = math.sqrt(total_var)
        d1 = (math.log(forward / strike) + 0.5 * total_var) / vol_sqrt_t
        d2 = d1 - vol_sqrt_t
        return float(discount * (forward * norm.cdf(d1) - strike * norm.cdf(d2)))

    def butterfly_diagnostic(self) -> dict[str, float | bool]:
        prices = np.array([self.call_price(float(k), float(self.maturities[-1])) for k in self.k_grid])
        dks = np.diff(self.k_grid)
        # Convexity in strike K is checked using K=exp(k), nonuniform grid finite differences.
        strikes = np.exp(self.k_grid)
        slopes = np.diff(prices) / np.diff(strikes)
        convex_diffs = np.diff(slopes)
        return {"convex_nonnegative_sampled": bool(np.min(convex_diffs) >= -1e-8),
                "minimum_convexity_increment": float(np.min(convex_diffs))}


class SurfaceArbitrageBook:
    """Owns NIFTY/BANKNIFTY surfaces and reports cross-asset relative-value basis."""
    def __init__(self, nifty: SSVISurface, banknifty: SSVISurface, beta_vol: float = 1.0) -> None:
        self.nifty, self.banknifty = nifty, banknifty
        self.beta_vol = _finite_float(beta_vol, "beta_vol")
        if self.beta_vol <= 0:
            raise ValueError("beta_vol must be positive")

    def basis(self, k: float, maturity: float) -> float:
        return self.banknifty.implied_volatility(k, maturity) - self.beta_vol * self.nifty.implied_volatility(k, maturity)

    def relative_value_signal(self, k: float, maturity: float, threshold: float = 0.03) -> dict[str, Any]:
        threshold = _finite_float(threshold, "threshold")
        if threshold < 0:
            raise ValueError("threshold must be nonnegative")
        basis = self.basis(k, maturity)
        if basis > threshold:
            direction = "SELL_BANKNIFTY_VOL_BUY_NIFTY_VOL"
        elif basis < -threshold:
            direction = "BUY_BANKNIFTY_VOL_SELL_NIFTY_VOL"
        else:
            direction = "NO_TRADE"
        return {"basis": basis, "threshold": threshold, "direction": direction,
                "signal_strength": max(0.0, abs(basis)-threshold)}

    def diagnostics(self) -> dict[str, Any]:
        return {"nifty_calendar": self.nifty.calendar_check(),
                "banknifty_calendar": self.banknifty.calendar_check(),
                "nifty_butterfly": self.nifty.butterfly_diagnostic(),
                "banknifty_butterfly": self.banknifty.butterfly_diagnostic()}


@dataclass
class KalmanState:
    mean: np.ndarray
    covariance: np.ndarray
    probability: float


class TwoRegimeKalmanSSVI:
    """Two-regime Kalman filter for [skew slope, ATM curvature]."""
    def __init__(self, seed: int = 39) -> None:
        self.transition = np.array([[0.97, 0.03], [0.15, 0.85]], dtype=float)
        self.states = [KalmanState(np.array([-0.25, 0.15]), np.eye(2) * 0.1, 0.8),
                       KalmanState(np.array([-0.55, 0.45]), np.eye(2) * 0.2, 0.2)]
        self.process_noise = np.eye(2) * 2e-3
        self.observation_noise = np.eye(2) * 1e-2
        self.rng = np.random.default_rng(seed)
        self.expansion_probability = 0.2

    def update(self, observation: Sequence[float]) -> dict[str, Any]:
        y = _array(observation, "observation", 1)
        if y.shape != (2,):
            raise ValueError("observation must contain skew and curvature")
        prior_prob = np.array([1.0-self.expansion_probability, self.expansion_probability]) @ self.transition
        log_likelihoods = []
        predicted = []
        for i, st in enumerate(self.states):
            m = st.mean.copy()
            p = st.covariance + self.process_noise
            innovation = y - m
            s = p + self.observation_noise
            sign, logdet = np.linalg.slogdet(s)
            if sign <= 0:
                raise ArithmeticError("Kalman innovation covariance is not positive definite")
            loglik = -0.5 * (2 * math.log(2 * math.pi) + logdet + float(innovation @ np.linalg.solve(s, innovation)))
            gain = np.linalg.solve(s.T, p.T).T
            new_m = m + gain @ innovation
            new_p = (np.eye(2) - gain) @ p
            predicted.append((new_m, (new_p + new_p.T)/2))
            log_likelihoods.append(loglik + math.log(max(prior_prob[i], 1e-300)))
        mx = max(log_likelihoods)
        posterior = np.exp(np.array(log_likelihoods) - mx)
        posterior /= posterior.sum()
        for st, (m, p), prob in zip(self.states, predicted, posterior):
            st.mean, st.covariance, st.probability = m, p, float(prob)
        self.expansion_probability = float(posterior[1])
        mix_mean = (1-self.expansion_probability) * self.states[0].mean + self.expansion_probability * self.states[1].mean
        return {"regime": "VOLATILITY_EXPANSION" if self.expansion_probability >= 0.5 else "CALM",
                "expansion_probability": self.expansion_probability,
                "skew_slope": float(mix_mean[0]), "atm_curvature": float(mix_mean[1])}


@dataclass(frozen=True)
class HedgeResult:
    weights: tuple[float, ...]
    delta_net: float
    gamma_net: float
    gamma_residual: float
    objective: float
    iterations: int
    converged: bool
    feasible: bool


class DeltaGammaNeutralHedger:
    """Projected proximal-gradient hedge solver with an exact delta constraint.

    Minimize gamma tracking error plus spread and depth-vacuum penalties, subject
    to box bounds and delta0 + delta_sensitivities @ u == 0. Infeasible bounds
    are detected before optimization; the returned feasibility flag is explicit.
    """
    def __init__(self, max_iter: int = 2000, tolerance: float = 1e-8,
                 epsilon: float = 1e-8) -> None:
        if max_iter < 1 or tolerance <= 0 or epsilon <= 0:
            raise ValueError("max_iter, tolerance and epsilon must be positive")
        self.max_iter, self.tolerance, self.epsilon = int(max_iter), float(tolerance), float(epsilon)

    def _project(self, x: np.ndarray, delta: np.ndarray, target: float,
                 lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        if np.linalg.norm(delta) < 1e-15:
            if abs(target) > self.tolerance:
                raise ValueError("delta-neutral constraint is infeasible: all sensitivities are zero")
            return np.clip(x, lo, hi)
        def dot_at(lam: float) -> float:
            return float(delta @ np.clip(x - lam * delta, lo, hi))
        left, right = -1.0, 1.0
        for _ in range(100):
            if dot_at(left) >= target:
                break
            left *= 2.0
        for _ in range(100):
            if dot_at(right) <= target:
                break
            right *= 2.0
        if dot_at(left) < target - self.tolerance or dot_at(right) > target + self.tolerance:
            raise ValueError("delta-neutral constraint is infeasible under box bounds")
        for _ in range(100):
            mid = (left + right) / 2.0
            value = dot_at(mid)
            if value > target:
                left = mid
            else:
                right = mid
        return np.clip(x - ((left + right) / 2.0) * delta, lo, hi)

    def solve(self, *, delta0: float, gamma0: float, target_gamma: float,
              delta_sensitivities: Sequence[float], gamma_sensitivities: Sequence[float],
              spreads: Sequence[float], depths: Sequence[float],
              lower_bounds: Sequence[float], upper_bounds: Sequence[float],
              lambda_spread: float = 0.1, lambda_vacuum: float = 0.05) -> HedgeResult:
        d0, g0, gt = map(float, (delta0, gamma0, target_gamma))
        d = _array(delta_sensitivities, "delta_sensitivities", 1)
        g = _array(gamma_sensitivities, "gamma_sensitivities", 1)
        spread = _array(spreads, "spreads", 1)
        depth = _array(depths, "depths", 1)
        lo = _array(lower_bounds, "lower_bounds", 1)
        hi = _array(upper_bounds, "upper_bounds", 1)
        n = d.size
        if not all(math.isfinite(v) for v in (d0, g0, gt, lambda_spread, lambda_vacuum)):
            raise ValueError("hedge scalars must be finite")
        if n == 0 or any(x.shape != (n,) for x in (g, spread, depth, lo, hi)):
            raise ValueError("all hedge vectors must have identical non-zero length")
        if np.any(spread < 0) or np.any(depth < 0) or np.any(lo > hi) or lambda_spread < 0 or lambda_vacuum < 0:
            raise ValueError("invalid costs, depths, bounds, or regularization")
        target_delta = -d0
        min_dot = float(np.sum(d * np.where(d >= 0, lo, hi)))
        max_dot = float(np.sum(d * np.where(d >= 0, hi, lo)))
        if target_delta < min_dot - self.tolerance or target_delta > max_dot + self.tolerance:
            # Keep failure telemetry JSON-safe (rather than emitting Infinity).
            return HedgeResult(tuple(np.zeros(n)), d0, g0, gt-g0, 1e300, 0, False, False)
        denom = depth + self.epsilon
        lipschitz = float(g @ g + 2 * lambda_vacuum * np.max(1.0 / denom))
        step = 1.0 / max(lipschitz, 1e-9)
        u = self._project(np.clip(np.zeros(n), lo, hi), d, target_delta, lo, hi)
        converged = False
        for it in range(1, self.max_iter + 1):
            gamma_net = g0 + float(g @ u)
            grad = -(gt - gamma_net) * g + 2 * lambda_vacuum * u / denom
            candidate = u - step * grad
            # Proximal soft-threshold for the L1 spread penalty.
            threshold = step * lambda_spread * spread
            candidate = np.sign(candidate) * np.maximum(0.0, np.abs(candidate) - threshold)
            new_u = self._project(candidate, d, target_delta, lo, hi)
            if np.linalg.norm(new_u-u, ord=np.inf) <= self.tolerance:
                u = new_u
                converged = True
                break
            u = new_u
        delta_net = d0 + float(d @ u)
        gamma_net = g0 + float(g @ u)
        gamma_resid = gt - gamma_net
        objective = 0.5*gamma_resid**2 + lambda_spread*float(spread @ np.abs(u)) + lambda_vacuum*float(np.sum(u*u/denom))
        feasible = abs(delta_net) <= max(1e-6, 10*self.tolerance) and np.all(u >= lo-self.tolerance) and np.all(u <= hi+self.tolerance)
        return HedgeResult(tuple(float(x) for x in u), delta_net, gamma_net, gamma_resid,
                           objective, it, converged, bool(feasible))


@dataclass
class PaperLedger:
    capital: float = INITIAL_PAPER_CAPITAL
    epoch: str = PAPER_LEDGER_EPOCH
    pnl: float = 0.0
    fees: float = 0.0
    events: int = 0

    def __post_init__(self) -> None:
        if not math.isfinite(self.capital) or self.capital <= 0:
            raise ValueError("paper capital must be positive")

    @property
    def equity(self) -> float:
        return self.capital + self.pnl - self.fees

    def record(self, pnl: float, fees: float) -> float:
        p, f = _finite_float(pnl, "pnl"), _finite_float(fees, "fees")
        if f < 0:
            raise ValueError("fees must be nonnegative")
        self.pnl += p
        self.fees += f
        self.events += 1
        return self.equity


@dataclass(frozen=True)
class SquadVote:
    role: str
    approved: bool
    message: str


class SquadConsensus:
    """Deterministic role-based rules proxy; not four autonomous LLM agents."""
    ROLES = ("Manager Abhi / Safety Arbiter", "Alex / L3 Microstructure", "Emily / Macro Volatility", "Max / Statutory RMS & Sizing")

    def evaluate(self, *, safe: bool, queue_ok: bool, regime_ok: bool, net_alpha: float,
                 entry_allowed: bool) -> tuple[SquadVote, ...]:
        return (
            SquadVote(self.ROLES[0], bool(safe), "paper-only safety invariant" if safe else "safety state is not clear"),
            SquadVote(self.ROLES[1], bool(queue_ok), "queue/adverse-selection checks" if queue_ok else "queue risk rejected"),
            SquadVote(self.ROLES[2], bool(regime_ok), "surface/regime diagnostics" if regime_ok else "surface or regime quarantined"),
            SquadVote(self.ROLES[3], bool(net_alpha > 0 and entry_allowed), "net alpha and throttle pass" if net_alpha > 0 and entry_allowed else "net alpha nonpositive or throttled"),
        )

    @staticmethod
    def approved(votes: Sequence[SquadVote]) -> bool:
        return bool(votes) and all(v.approved for v in votes)


class Cycle39RiskMachine:
    def __init__(self) -> None:
        self.state = RiskState.IDLE
        self.emergency_latched = False
        self.history: list[tuple[str, str]] = []

    def transition(self, event: str) -> RiskState:
        if event not in {"START", "HEDGE", "QUARANTINE", "EMERGENCY", "RECOVERY_ACK", "RESET"}:
            raise ValueError("unknown risk event")
        if self.emergency_latched and event != "RECOVERY_ACK":
            self.history.append((event, "blocked_latched"))
            return self.state
        if event == "EMERGENCY":
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event == "RECOVERY_ACK" and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event == "START" and self.state == RiskState.IDLE:
            self.state = RiskState.MONITORING
        elif event == "HEDGE" and self.state in (RiskState.MONITORING, RiskState.HEDGE_ONLY):
            self.state = RiskState.HEDGE_ONLY
        elif event == "QUARANTINE":
            self.state = RiskState.QUARANTINED
        elif event == "RESET" and not self.emergency_latched:
            self.state = RiskState.IDLE
        self.history.append((event, self.state.value))
        return self.state


def poisson_queue_fill_probability(q_ahead: int, lambda_market: float, tau: float,
                                   cancellation_hazard: float = 0.0) -> float:
    """Probability that market events deplete q ahead, with hazard-accelerated rate.

    P(N >= q) for a Poisson count. q_ahead is a positive FIFO rank. Cancellation
    hazard augments arrival rate as a transparent approximation, not an exact
    competing-risks likelihood.
    """
    if not isinstance(q_ahead, int) or q_ahead < 1:
        raise ValueError("q_ahead must be a positive integer")
    lam, t, h = map(float, (lambda_market, tau, cancellation_hazard))
    if not all(map(math.isfinite, (lam, t, h))) or min(lam, t, h) < 0:
        raise ValueError("lambda, tau and cancellation hazard must be finite and nonnegative")
    mean = (lam + h) * t
    if mean == 0:
        return 0.0
    # Recurrence avoids factorial overflow: p_k = exp(-mean) mean^k / k!.
    p = math.exp(-mean)
    cumulative = p
    for k in range(1, q_ahead):
        p *= mean / k
        cumulative += p
        if p == 0.0:
            break
    return _clip_probability(1.0 - cumulative)


@dataclass
class QueueOrder:
    order_id: str
    symbol: str
    level: int
    side: str
    price: float
    quantity: float
    ahead: float
    behind: float = 0.0
    placed_at: float = 0.0
    cancelled: bool = False
    filled: bool = False

    def validate(self) -> None:
        if not self.order_id or not self.symbol:
            raise ValueError("order_id and symbol are required")
        if self.level not in range(1, 6):
            raise ValueError("level must be L1-L5 (1..5)")
        if self.side.upper() not in {"BID", "ASK"}:
            raise ValueError("side must be BID or ASK")
        if min(self.price, self.quantity, self.ahead, self.behind) < 0 or self.quantity <= 0:
            raise ValueError("price/queue quantities must be nonnegative; quantity positive")
        if not all(math.isfinite(x) for x in (self.price, self.quantity, self.ahead, self.behind, self.placed_at)):
            raise ValueError("queue fields must be finite")


@dataclass
class QueueExecutionAssessment:
    fill_probability: float
    expected_adverse_slippage: float
    round_trip_friction: float
    quote_pullback_immediate: bool
    reposition: bool


class L3QueueDepletionMachine:
    def __init__(self, cancellation_hazard: float = 0.0) -> None:
        self.orders: dict[str, QueueOrder] = {}
        self.cancellation_hazard = float(cancellation_hazard)
        if self.cancellation_hazard < 0 or not math.isfinite(self.cancellation_hazard):
            raise ValueError("cancellation hazard must be finite nonnegative")
        self.events: list[dict[str, Any]] = []

    def place(self, order: QueueOrder) -> None:
        order.validate()
        if order.order_id in self.orders:
            raise ValueError("duplicate order id")
        self.orders[order.order_id] = order
        self.events.append({"event": "PLACE", "order_id": order.order_id, "time": order.placed_at})

    def cancel_ahead(self, order_id: str, quantity: float, timestamp: float) -> float:
        order = self.orders[order_id]
        if quantity < 0 or not math.isfinite(quantity):
            raise ValueError("cancel quantity must be finite and nonnegative")
        removed = min(order.ahead, float(quantity))
        order.ahead -= removed
        self.cancellation_hazard += removed / max(1.0, order.ahead + removed)
        self.events.append({"event": "CANCEL_AHEAD", "order_id": order_id, "quantity": removed, "time": float(timestamp)})
        return removed

    def trade_ahead(self, order_id: str, quantity: float, timestamp: float) -> tuple[float, bool]:
        order = self.orders[order_id]
        if quantity < 0 or not math.isfinite(quantity):
            raise ValueError("trade quantity must be finite and nonnegative")
        used = min(order.ahead, float(quantity))
        order.ahead -= used
        leftover = float(quantity) - used
        filled = min(order.quantity, leftover)
        order.quantity -= filled
        if order.quantity <= 1e-12:
            order.quantity = 0.0
            order.filled = True
        self.events.append({"event": "TRADE_AHEAD", "order_id": order_id, "quantity": float(quantity), "filled": filled, "time": float(timestamp)})
        return filled, order.filled

    def cancel(self, order_id: str, timestamp: float) -> None:
        order = self.orders[order_id]
        if not math.isfinite(float(timestamp)):
            raise ValueError("timestamp must be finite")
        if order.filled:
            raise ValueError("a filled order cannot be cancelled")
        order.cancelled = True
        self.events.append({"event": "CANCEL", "order_id": order_id, "time": float(timestamp)})

    def assess(self, order_id: str, lambda_market: float, tau: float,
               expected_adverse_slippage: float, round_trip_friction: float,
               eta_reposition: float = 0.15) -> QueueExecutionAssessment:
        order = self.orders[order_id]
        if order.cancelled or order.filled:
            raise ValueError("cannot assess a terminal queue order")
        q_rank = max(1, int(math.ceil(order.ahead)))
        p = poisson_queue_fill_probability(q_rank, lambda_market, tau, self.cancellation_hazard)
        adv, friction = float(expected_adverse_slippage), float(round_trip_friction)
        if not all(math.isfinite(x) and x >= 0 for x in (adv, friction)) or not 0 <= eta_reposition <= 1:
            raise ValueError("invalid adverse/slippage/reposition parameters")
        pullback = p > 0.85 and adv > friction
        return QueueExecutionAssessment(p, adv, friction, pullback, p < eta_reposition)


@dataclass
class ExecutionPlan:
    times: list[float]
    remaining_inventory: list[float]
    trade_slices: list[float]
    effective_eta: float
    expected_cost: float
    lead_lag_seconds: float


class AlmgrenChrissHawkesPlanner:
    """Continuous Almgren-Chriss trajectory with Hawkes-scaled temporary impact."""
    def __init__(self, eta: float = 0.01, risk_aversion: float = 1e-6,
                 hawkes_impact_scale: float = 0.2, lead_lag_seconds: float = 0.1) -> None:
        self.eta = _finite_float(eta, "eta")
        self.risk_aversion = _finite_float(risk_aversion, "risk_aversion")
        self.hawkes_impact_scale = _finite_float(hawkes_impact_scale, "hawkes_impact_scale")
        self.lead_lag_seconds = _finite_float(lead_lag_seconds, "lead_lag_seconds")
        if self.eta <= 0 or self.risk_aversion < 0 or self.hawkes_impact_scale < 0:
            raise ValueError("invalid execution parameters")
        if not 0.05 <= self.lead_lag_seconds <= 0.5:
            raise ValueError("lead_lag_seconds must be in [0.05, 0.5]")

    def plan(self, quantity: float, horizon: float, steps: int, volatility: float,
             hawkes_intensity: Sequence[float] = (0.0, 0.0),
             lead_signal: float = 0.0) -> ExecutionPlan:
        q = _finite_float(quantity, "quantity")
        T = _finite_float(horizon, "horizon")
        sig = _finite_float(volatility, "volatility")
        signal = _finite_float(lead_signal, "lead_signal")
        lam = _array(hawkes_intensity, "hawkes_intensity", 1)
        if T <= 0 or steps < 1 or sig < 0 or q < 0 or np.any(lam < 0):
            raise ValueError("invalid execution plan inputs")
        effective_eta = self.eta * (1 + self.hawkes_impact_scale * float(np.sum(lam)))
        kappa = math.sqrt(self.risk_aversion * sig * sig / effective_eta)
        times = np.linspace(0, T, steps + 1)
        if kappa * T < 1e-8:
            remaining = q * (1 - times / T)
        else:
            remaining = q * np.sinh(kappa * (T - times)) / math.sinh(kappa * T)
        # A leading signal only shifts emphasis within the same fully executed schedule.
        urgency = float(np.clip(1 + signal * 0.1, 0.5, 1.5))
        remaining = q * np.maximum(0.0, remaining / q if q else remaining)
        remaining[1:-1] = np.clip(remaining[1:-1] + (q - remaining[1:-1]) * (urgency - 1) * (times[1:-1] / T) * (1-times[1:-1]/T), 0, q)
        remaining[0], remaining[-1] = q, 0.0
        remaining = np.minimum.accumulate(remaining)
        slices = np.diff(-remaining) * -1  # equivalent to positive inventory reductions
        slices = remaining[:-1] - remaining[1:]
        dt = T / steps
        velocities = slices / dt
        inventory = remaining[1:]
        cost = effective_eta * float(np.sum(velocities**2) * dt) + self.risk_aversion * sig**2 * float(np.sum(inventory**2) * dt)
        return ExecutionPlan(times.tolist(), remaining.tolist(), slices.tolist(), effective_eta, cost, self.lead_lag_seconds)


class MicrostructureParticleFilter:
    """Seeded SMC filter for volatility, jump intensity and liquidity resilience."""
    def __init__(self, particles: int = 256, seed: int = 39) -> None:
        if particles < 100:
            raise ValueError("at least 100 particles required")
        self.n = particles
        self.rng = np.random.default_rng(seed)
        self.volatility = self.rng.lognormal(mean=math.log(0.02), sigma=0.35, size=particles)
        self.jump_intensity = self.rng.lognormal(mean=math.log(0.3), sigma=0.5, size=particles)
        self.resilience_beta = self.rng.lognormal(mean=math.log(2.0), sigma=0.35, size=particles)
        self.weights = np.full(particles, 1 / particles)
        self.regime = "NORMAL_LIQUIDITY"
        self.resample_count = 0

    @property
    def effective_sample_size(self) -> float:
        return float(1.0 / np.sum(self.weights**2))

    def systematic_resample(self) -> np.ndarray:
        positions = (self.rng.random() + np.arange(self.n)) / self.n
        cumulative = np.cumsum(self.weights)
        cumulative[-1] = 1.0
        indices = np.searchsorted(cumulative, positions, side="left")
        self.volatility = self.volatility[indices].copy()
        self.jump_intensity = self.jump_intensity[indices].copy()
        self.resilience_beta = self.resilience_beta[indices].copy()
        self.weights.fill(1 / self.n)
        self.resample_count += 1
        return indices

    def update(self, abs_return: float, spread_ratio: float, depth_ratio: float,
               sweeps: float, ofi: float) -> dict[str, Any]:
        obs = np.array([abs_return, spread_ratio, depth_ratio, sweeps, ofi], dtype=float)
        if not np.all(np.isfinite(obs)) or abs_return < 0 or spread_ratio < 0 or depth_ratio < 0 or sweeps < 0:
            raise ValueError("invalid particle-filter observation")
        self.volatility = np.maximum(1e-6, self.volatility * np.exp(self.rng.normal(0, 0.025, self.n)))
        self.jump_intensity = np.maximum(1e-6, self.jump_intensity * np.exp(self.rng.normal(0, 0.04, self.n)))
        self.resilience_beta = np.maximum(1e-6, self.resilience_beta * np.exp(self.rng.normal(0, 0.025, self.n)))
        # Robust pseudo-likelihood around particle-generated feature expectations.
        pred_abs_ret = np.sqrt(self.volatility) * 0.8
        pred_spread = 1 / self.resilience_beta + 0.5 * self.jump_intensity
        pred_depth = 1 / (1 + self.jump_intensity)
        pred_sweeps = self.jump_intensity
        pred_ofi = np.tanh(self.jump_intensity - 0.5 * self.resilience_beta)
        errors = np.column_stack([obs[0]-pred_abs_ret, obs[1]-pred_spread,
                                  obs[2]-pred_depth, obs[3]-pred_sweeps, obs[4]-pred_ofi])
        scales = np.array([max(0.01, obs[0]+0.01), 0.5, 0.5, max(1.0, obs[3]+1.0), 1.0])
        log_lik = -0.5 * np.sum((errors / scales)**2, axis=1)
        log_lik -= np.max(log_lik)
        updated = self.weights * np.exp(np.clip(log_lik, -700, 0))
        total = float(updated.sum())
        self.weights = updated / total if total > 0 else np.full(self.n, 1/self.n)
        ess = self.effective_sample_size
        if ess < self.n / 2:
            self.systematic_resample()
        # Regime diagnosis from observed dislocation features, with deterministic thresholds.
        dislocation = max(obs[0] / 0.02, obs[1], 1 / max(obs[2], 0.05), obs[3] / 3.0)
        if obs[1] > 5 or obs[2] < 0.12 or obs[3] >= 5:
            self.regime = "LIQUIDITY_VACUUM"
        elif dislocation > 2.0 or obs[0] > 0.04:
            self.regime = "VOLATILITY_EXPANSION"
        else:
            self.regime = "NORMAL_LIQUIDITY"
        return {"regime": self.regime, "ess": self.effective_sample_size,
                "mean_volatility": float(self.weights @ self.volatility),
                "mean_jump_intensity": float(self.weights @ self.jump_intensity),
                "mean_resilience_beta": float(self.weights @ self.resilience_beta),
                "resample_count": self.resample_count}


# ---- Friction calculator, throttler and squad-level paper-only orchestration ----
@dataclass(frozen=True)
class Cycle39FeeRates:
    stt_sell: float = 0.0015
    stamp_buy: float = 0.00003
    exchange: float = 3553.0 / 10_000_000.0
    sebi: float = 10.0 / 10_000_000.0
    gst: float = 0.18
    brokerage_per_leg: float = 20.0


@dataclass(frozen=True)
class Cycle39Leg:
    side: str
    premium: float
    quantity: float
    half_spread_per_unit: float = 0.0
    impact_per_unit: float = 0.0

    def validate(self) -> None:
        if self.side.upper() not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if not all(math.isfinite(v) for v in (self.premium, self.quantity, self.half_spread_per_unit, self.impact_per_unit)):
            raise ValueError("leg inputs must be finite")
        if min(self.premium, self.quantity, self.half_spread_per_unit, self.impact_per_unit) < 0:
            raise ValueError("leg inputs must be nonnegative")


@dataclass(frozen=True)
class Cycle39CostBreakdown:
    turnover: float
    stt: float
    stamp_duty: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    slippage: float
    impact: float
    total: float


class Cycle39StatutoryCostCalculator:
    def __init__(self, rates: Cycle39FeeRates | None = None) -> None:
        self.rates = rates or Cycle39FeeRates()
        vals = (self.rates.stt_sell, self.rates.stamp_buy, self.rates.exchange,
                self.rates.sebi, self.rates.gst, self.rates.brokerage_per_leg)
        if not all(math.isfinite(v) and v >= 0 for v in vals):
            raise ValueError("fee rates must be finite and nonnegative")

    def breakdown(self, legs: Sequence[Cycle39Leg]) -> Cycle39CostBreakdown:
        if not legs:
            raise ValueError("at least one leg required")
        for leg in legs:
            leg.validate()
        turnover = sum(x.premium*x.quantity for x in legs)
        stt = sum(x.premium*x.quantity*self.rates.stt_sell for x in legs if x.side.upper() == "SELL")
        stamp = sum(x.premium*x.quantity*self.rates.stamp_buy for x in legs if x.side.upper() == "BUY")
        exchange = turnover*self.rates.exchange
        sebi = turnover*self.rates.sebi
        brokerage = len(legs)*self.rates.brokerage_per_leg
        gst = (exchange+sebi+brokerage)*self.rates.gst
        slippage = sum(x.half_spread_per_unit*x.quantity for x in legs)
        impact = sum(x.impact_per_unit*x.quantity for x in legs)
        total = stt+stamp+exchange+sebi+brokerage+gst+slippage+impact
        return Cycle39CostBreakdown(turnover, stt, stamp, exchange, sebi, brokerage, gst, slippage, impact, total)

    def net_alpha(self, gross_alpha: float, legs: Sequence[Cycle39Leg]) -> tuple[float, Cycle39CostBreakdown]:
        gross = _finite_float(gross_alpha, "gross_alpha")
        cost = self.breakdown(legs)
        return gross-cost.total, cost


@dataclass
class Cycle39Throttler:
    max_daily_trades: int = 15
    cooldown_base: float = 900.0
    theta_rough: float = 1.0
    sigma_baseline: float = 0.2
    max_loss_streak: int = 3
    min_fill_interval: float = 30.0
    max_size_ratio: float = 1.25
    trades_today: int = 0
    loss_streak: int = 0
    last_fill_time: float | None = None
    last_size: float | None = None
    cooldown_until: float = 0.0

    def __post_init__(self) -> None:
        if self.max_daily_trades < 0 or self.cooldown_base < 0 or self.theta_rough < 0:
            raise ValueError("trade cap, base cooldown, and roughness scale must be nonnegative")
        if self.sigma_baseline <= 0 or self.max_loss_streak < 1 or self.min_fill_interval < 0 or self.max_size_ratio <= 0:
            raise ValueError("invalid throttler baseline, streak, pacing, or size parameters")

    def cooldown_duration(self, sigma_rough: float) -> float:
        s = _finite_float(sigma_rough, "sigma_rough")
        if s < 0 or self.sigma_baseline <= 0:
            raise ValueError("volatility and baseline must be nonnegative/positive")
        return self.cooldown_base*(1+self.theta_rough*s/self.sigma_baseline)

    def record_fill(self, timestamp: float, size: float, pnl: float, sigma_rough: float = 0.0) -> bool:
        t, q, p = map(float, (timestamp, size, pnl))
        if not all(map(math.isfinite,(t,q,p))) or q <= 0:
            raise ValueError("invalid fill")
        violation = self.last_fill_time is not None and t-self.last_fill_time < self.min_fill_interval
        violation = violation or (self.last_size is not None and q/self.last_size > self.max_size_ratio)
        self.loss_streak = self.loss_streak+1 if p < 0 else 0
        self.trades_today += 1
        violation = violation or self.loss_streak >= self.max_loss_streak
        if violation:
            self.cooldown_until = max(self.cooldown_until, t+self.cooldown_duration(sigma_rough))
        self.last_fill_time, self.last_size = t, q
        return not violation and self.trades_today <= self.max_daily_trades

    def allowed(self, timestamp: float) -> bool:
        return self.trades_today < self.max_daily_trades and float(timestamp) >= self.cooldown_until


class Cycle39ExecutionEngine:
    """Unified model bundle, deterministic consensus rules and paper ledger."""
    def __init__(self, seed: int = 39, port: int = 8088, particles: int = 256) -> None:
        self.seed = seed
        self.rough = FractionalKernel12(hurst=0.075, factors=12)
        self.volatility = FractionalHestonHawkesModel(self.rough, seed=seed)
        self.hawkes = self.volatility.hawkes
        self.hedger = DeltaGammaNeutralHedger()
        self.nifty_surface = SSVISurface([0.08, 0.16, 0.32], [0.025, 0.043, 0.072], rho=-0.30, phi=0.8)
        self.bank_surface = SSVISurface([0.08, 0.16, 0.32], [0.032, 0.055, 0.087], rho=-0.40, phi=0.85)
        self._nifty_theta_base = self.nifty_surface.theta_curve.copy()
        self._bank_theta_base = self.bank_surface.theta_curve.copy()
        self.surface_book = SurfaceArbitrageBook(self.nifty_surface, self.bank_surface, 1.05)
        self.kalman = TwoRegimeKalmanSSVI(seed)
        self._last_regime: dict[str, Any] = {"regime": "CALM", "expansion_probability": 0.2,
                                             "skew_slope": -0.25, "atm_curvature": 0.15}
        self.queue = L3QueueDepletionMachine()
        self.execution_planner = AlmgrenChrissHawkesPlanner()
        self.particle_filter = MicrostructureParticleFilter(particles, seed)
        self.fees = Cycle39StatutoryCostCalculator()
        self.throttler = Cycle39Throttler()
        self.ledger = PaperLedger()
        self.risk = Cycle39RiskMachine()
        self.squad = SquadConsensus()
        self.port = int(port)
        self.last_queue_assessment: dict[str, Any] = {"fill_probability": 0.0, "quote_pullback_immediate": False}
        self.last_spread: dict[str, Any] = {"gross_alpha": 0.0, "net_alpha": 0.0, "costs": None, "approved": False}
        self._server: ThreadingHTTPServer | None = None
        self._lock = threading.Lock()

    def update_market(self, dt: float, shocks: Sequence[float] | None = None,
                      jump_shocks: Sequence[float] | None = None,
                      surface_observation: Sequence[float] = (-0.3, 0.2)) -> dict[str, Any]:
        variance = self.volatility.update(dt, shocks, jump_shocks)
        regime = self.kalman.update(surface_observation)
        self._last_regime = dict(regime)
        # Couple the filtered skew/curvature state into both SSVI surfaces.
        p_exp = float(regime["expansion_probability"])
        skew = float(regime["skew_slope"])
        curvature = float(regime["atm_curvature"])
        self.nifty_surface.recondition(
            rho=float(np.clip(skew, -0.95, 0.95)),
            phi=max(0.05, 0.8 + 0.25*(curvature-0.15)),
            theta_curve=self._nifty_theta_base*(1.0+0.10*p_exp))
        self.bank_surface.recondition(
            rho=float(np.clip(1.1*skew, -0.95, 0.95)),
            phi=max(0.05, 0.85 + 0.3375*(curvature-0.15)),
            theta_curve=self._bank_theta_base*(1.0+0.15*p_exp))
        if regime["expansion_probability"] > 0.8:
            self.risk.transition("QUARANTINE")
        elif self.risk.state == RiskState.QUARANTINED and not self.risk.emergency_latched:
            self.risk.transition("RESET")
            self.risk.transition("START")
        else:
            self.risk.transition("START")
        return {"variance": variance.tolist(), "hawkes_intensity": self.hawkes.intensity.tolist(), **regime}

    def record_hawkes_event(self, asset: int, count: int = 1) -> list[float]:
        return self.hawkes.event(asset, count).tolist()

    def update_microstructure(self, abs_return: float, spread_ratio: float, depth_ratio: float,
                              sweeps: float, ofi: float) -> dict[str, Any]:
        result = self.particle_filter.update(abs_return, spread_ratio, depth_ratio, sweeps, ofi)
        if result["regime"] in {"VOLATILITY_EXPANSION", "LIQUIDITY_VACUUM"}:
            self.risk.transition("QUARANTINE")
        elif self.risk.state == RiskState.QUARANTINED and not self.risk.emergency_latched:
            self.risk.transition("RESET")
        return result

    def record_fill(self, timestamp: float, size: float, pnl: float, fees: float = 0.0,
                    sigma_rough: float = 0.0) -> bool:
        allowed = self.throttler.record_fill(timestamp, size, pnl, sigma_rough)
        self.ledger.record(pnl, fees)
        if not allowed and self.throttler.cooldown_until > timestamp:
            self.risk.transition("QUARANTINE")
        return allowed

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "port": self.port, "paper_only": True,
                "risk_state": self.risk.state.value,
                "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
                "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED}

    def evaluate_candidate(self, gross_alpha: float, legs: Sequence[Cycle39Leg], *, queue_ok: bool = True,
                           surface_ok: bool = True, now: float | None = None) -> dict[str, Any]:
        ts = time.time() if now is None else _finite_float(now, "now")
        net, costs = self.fees.net_alpha(gross_alpha, legs)
        allowed = self.throttler.allowed(ts)
        if self.risk.emergency_latched or self.risk.state in (RiskState.QUARANTINED, RiskState.EMERGENCY_UNWIND):
            approved = False
        else:
            votes = self.squad.evaluate(safe=(not LIVE_ORDER_DISPATCH_ENABLED and REAL_BROKER_FILLS_LOCKED),
                                        queue_ok=queue_ok and not self.last_queue_assessment.get("quote_pullback_immediate", False),
                                        regime_ok=surface_ok, net_alpha=net, entry_allowed=allowed)
            approved = net > 0 and allowed and queue_ok and surface_ok and SquadConsensus.approved(votes)
        self.last_spread = {"gross_alpha": float(gross_alpha), "net_alpha": net if approved or net > 0 else 0.0,
                            "costs": asdict(costs), "approved": approved, "timestamp": ts}
        return dict(self.last_spread)

    def optimize_hedge(self, **kwargs: Any) -> HedgeResult:
        result = self.hedger.solve(**kwargs)
        # Store the result in a JSON-safe compact form for dashboard consumers.
        self.last_spread["hedge"] = asdict(result)
        return result

    def queue_check(self, q_ahead: int, lambda_market: float, horizon: float, adverse_slippage: float,
                    round_trip_friction: float, cancellation_hazard: float = 0.0) -> dict[str, Any]:
        fill = poisson_queue_fill_probability(q_ahead, lambda_market, horizon, cancellation_hazard)
        adverse_slippage = _finite_float(adverse_slippage, "adverse_slippage")
        round_trip_friction = _finite_float(round_trip_friction, "round_trip_friction")
        if adverse_slippage < 0 or round_trip_friction < 0:
            raise ValueError("adverse slippage and round-trip friction must be nonnegative")
        pullback = fill > 0.85 and adverse_slippage > round_trip_friction
        self.last_queue_assessment = {"q_ahead": q_ahead, "fill_probability": fill,
                                      "adverse_slippage": adverse_slippage, "round_trip_friction": round_trip_friction,
                                      "quote_pullback_immediate": pullback}
        if pullback:
            self.risk.transition("QUARANTINE")
        return dict(self.last_queue_assessment)

    def telemetry(self, now: datetime | None = None) -> dict[str, Any]:
        # Optional clock injection makes offline demonstrations reproducible.
        stamp = datetime.now(timezone.utc).astimezone(IST) if now is None else now.astimezone(IST)
        return {"timestamp_ist": stamp.isoformat(), "epoch_seconds": stamp.timestamp(),
                "paper_only": True, "rough": {"hurst": self.rough.hurst, "factors": self.rough.factors,
                    "fit_rmse": self.rough.fit_rmse, "memory_half_life": self.rough.memory_half_life()},
                "hawkes": {"intensity": self.hawkes.intensity.tolist(), "branching": self.hawkes.branching.tolist(),
                    "spectral_radius": self.hawkes.spectral_radius, "cross_asymmetry": self.hawkes.cross_excitation_asymmetry},
                "ssvi": {"nifty_calendar": self.nifty_surface.calendar_check(), "banknifty_calendar": self.bank_surface.calendar_check(),
                    "nifty_parameters": {"theta_curve": self.nifty_surface.theta_curve.tolist(), "rho": self.nifty_surface.rho, "phi": self.nifty_surface.phi},
                    "banknifty_parameters": {"theta_curve": self.bank_surface.theta_curve.tolist(), "rho": self.bank_surface.rho, "phi": self.bank_surface.phi},
                    "kalman_regime": dict(self._last_regime),
                    "atm_basis": self.surface_book.basis(0,0.16),
                    "relative_value_signal": self.surface_book.relative_value_signal(0.0, 0.16)},
                "queue": dict(self.last_queue_assessment), "spread": dict(self.last_spread),
                "particle_filter": {"regime": self.particle_filter.regime, "ess": self.particle_filter.effective_sample_size},
                "risk_state": self.risk.state.value, "cooldown_until": self.throttler.cooldown_until,
                "paper_ledger": {"epoch": self.ledger.epoch, "capital": self.ledger.capital, "equity": self.ledger.equity},
                "safety": {"LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
                           "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED}}

    def serve(self, host: str = "127.0.0.1", port: int | None = None) -> ThreadingHTTPServer:
        engine = self
        p = self.port if port is None else int(port)
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def _write(self, content_type: str, body: bytes) -> None:
                self.send_response(200); self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache"); self.send_header("Connection", "close")
                self.end_headers(); self.wfile.write(body)
            def do_GET(self) -> None:
                if self.path == "/health":
                    payload = {"status":"ok", "port":p, "paper_only":True,
                               "LIVE_ORDER_DISPATCH_ENABLED":LIVE_ORDER_DISPATCH_ENABLED,
                               "REAL_BROKER_FILLS_LOCKED":REAL_BROKER_FILLS_LOCKED}
                    self._write("application/json; charset=utf-8", json.dumps(payload,allow_nan=False).encode())
                elif self.path == "/telemetry":
                    self._write("application/json; charset=utf-8", json.dumps(engine.telemetry(),allow_nan=False).encode())
                elif self.path == "/events":
                    body = ("retry: 1000\nevent: telemetry\ndata: "+json.dumps(engine.telemetry(),allow_nan=False)+"\n\n").encode()
                    self._write("text/event-stream; charset=utf-8",body)
                else: self.send_error(404)
            def log_message(self,fmt: str,*args: Any) -> None: return
        server=ThreadingHTTPServer((host,p),Handler); server.daemon_threads=True; self._server=server; return server


# Static fail-closed API: no function ever dispatches a broker order.
def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("live broker dispatch is permanently disabled; paper simulation only")
