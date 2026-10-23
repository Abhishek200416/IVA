"""Cycle 53 RBSVI-BOCPD research engine.

Offline numerical research and paper simulation only.  No broker adapters,
credentials, network calls, or live-order path are included.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, gamma as gamma_fn, log, pi as PI, sqrt
from typing import Sequence, Mapping, Any

import numpy as np

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0
ROUGH_HURST = 0.07
STATE_DIMENSION = 16
MAX_KELLY_FRACTION = 0.10
INR_PER_CRORE = 10_000_000.0


def _array(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be finite")
    return arr


def _positive(value: float, name: str, allow_zero: bool = False) -> float:
    x = float(value)
    if not np.isfinite(x) or (x < 0 if allow_zero else x <= 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return x


def _normalize_probabilities(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    if p.ndim != 1 or p.size == 0 or np.any(~np.isfinite(p)) or np.any(p < 0):
        raise ValueError("probabilities must be a non-empty finite non-negative vector")
    total = float(p.sum())
    if total <= 0:
        raise ValueError("probabilities must have positive sum")
    return p / total


# ---------------------------------------------------------------------------
# Forward variance curve and rough-Volterra proxy
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ForwardVarianceCurve:
    """Piecewise-linear positive forward variance xi_0(t), with times starting at 0."""
    times: np.ndarray
    values: np.ndarray

    def __post_init__(self):
        t = _array(self.times, "times", 1)
        v = _array(self.values, "values", 1)
        if t.size < 2 or t.shape != v.shape or not np.isclose(t[0], 0.0):
            raise ValueError("times and values must align, have >=2 points, and start at 0")
        if np.any(np.diff(t) <= 0) or np.any(v <= 0):
            raise ValueError("times must strictly increase and forward variances must be positive")
        object.__setattr__(self, "times", t.copy())
        object.__setattr__(self, "values", v.copy())

    def value(self, t: float | Sequence[float]) -> float | np.ndarray:
        x = _array(np.atleast_1d(t), "t", 1)
        if np.any(x < 0):
            raise ValueError("t must be non-negative")
        out = np.interp(x, self.times, self.values, left=self.values[0], right=self.values[-1])
        return float(out[0]) if np.ndim(t) == 0 else out

    def total_variance(self, expiry: float) -> float:
        T = _positive(expiry, "expiry", allow_zero=True)
        if T == 0:
            return 0.0
        interior = self.times[(self.times > 0) & (self.times < T)]
        knots = np.concatenate(([0.0], interior, [T]))
        vals = np.asarray(self.value(knots), dtype=float)
        # Exact integration of a piecewise-linear curve on each knot interval.
        return float(np.sum(np.diff(knots) * (vals[:-1] + vals[1:]) * 0.5))


def rough_volterra_kernel(t: float | Sequence[float], hurst: float = ROUGH_HURST) -> float | np.ndarray:
    """K_H(t)=t^(H-1/2)/Gamma(H+1/2); singular at t=0 for H<1/2."""
    H = float(hurst)
    if not 0 < H < 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    x = _array(np.atleast_1d(t), "t", 1)
    if np.any(x <= 0):
        raise ValueError("kernel is singular for t <= 0")
    out = x ** (H - 0.5) / gamma_fn(H + 0.5)
    return float(out[0]) if np.ndim(t) == 0 else out


@dataclass(frozen=True)
class ExponentialVolterraLift:
    hurst: float
    rates: np.ndarray
    weights: np.ndarray

    def __post_init__(self):
        if not 0 < float(self.hurst) < 0.5:
            raise ValueError("hurst must lie in (0, 0.5)")
        r = _array(self.rates, "rates", 1)
        w = _array(self.weights, "weights", 1)
        if r.size == 0 or r.shape != w.shape or np.any(r <= 0) or np.any(w < 0):
            raise ValueError("rates must be positive and weights aligned/non-negative")
        object.__setattr__(self, "rates", r.copy()); object.__setattr__(self, "weights", w.copy())

    def evaluate(self, t: float | Sequence[float]) -> float | np.ndarray:
        x = _array(np.atleast_1d(t), "t", 1)
        if np.any(x <= 0):
            raise ValueError("t must be positive")
        y = np.exp(-np.outer(x, self.rates)) @ self.weights
        return float(y[0]) if np.ndim(t) == 0 else y


def build_volterra_lift(hurst: float = ROUGH_HURST, factors: int = 12,
                        tau_min: float = 1e-3, tau_max: float = 100.0) -> ExponentialVolterraLift:
    H = float(hurst)
    if not 0 < H < 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    if not isinstance(factors, int) or factors < 1:
        raise ValueError("factors must be a positive integer")
    tau_min = _positive(tau_min, "tau_min"); tau_max = _positive(tau_max, "tau_max")
    if tau_min >= tau_max:
        raise ValueError("tau_min must be less than tau_max")
    rates = np.geomspace(1 / tau_max, 1 / tau_min, factors)
    grid = np.geomspace(tau_min, tau_max, max(200, factors * 12))
    design = np.exp(-np.outer(grid, rates))
    target = np.asarray(rough_volterra_kernel(grid, H))
    weights, *_ = np.linalg.lstsq(design, target, rcond=1e-10)
    weights = np.maximum(weights, 0.0)
    # Projected-gradient refinement, deterministic and non-negative.
    gram = design.T @ design
    L = float(np.linalg.norm(gram, ord=2))
    if L > 0:
        step = 1.0 / L
        for _ in range(500):
            weights = np.maximum(weights - step * (design.T @ (design @ weights - target)), 0.0)
    return ExponentialVolterraLift(H, rates, weights)


def simulate_rough_variance_proxy(forward_variance: float, brownian_increments: Sequence[float],
                                  dt: float, vol_of_vol: float = 0.8,
                                  hurst: float = ROUGH_HURST) -> np.ndarray:
    """Discrete rough-Bergomi-style variance proxy; not an exact rBergomi simulator."""
    xi = _positive(forward_variance, "forward_variance")
    dW = _array(brownian_increments, "brownian_increments", 1)
    if dW.size == 0:
        raise ValueError("brownian_increments must not be empty")
    dt = _positive(dt, "dt"); eta = _positive(vol_of_vol, "vol_of_vol", allow_zero=True)
    H = float(hurst)
    if not 0 < H < 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    out = np.empty(dW.size)
    for i in range(dW.size):
        # Midpoint-lag discretization avoids evaluating the singular kernel at zero.
        lags = (np.arange(i + 1, 0, -1, dtype=float) - 0.5) * dt
        kernel = np.asarray(rough_volterra_kernel(lags, H))
        driver = float(np.dot(kernel, dW[:i + 1]))
        t = (i + 1) * dt
        log_v = eta * driver - 0.5 * eta * eta * (t ** (2 * H))
        out[i] = np.clip(xi * np.exp(np.clip(log_v, -50.0, 50.0)), 1e-12, 1e6)
    return out


# ---------------------------------------------------------------------------
# SSVI surface: parametrization, constraints, diagnostics and grid calibration
# ---------------------------------------------------------------------------
def ssvi_phi(theta: float | np.ndarray, eta: float, gamma: float) -> float | np.ndarray:
    th = _array(np.atleast_1d(theta), "theta", 1)
    eta = _positive(eta, "eta")
    gamma = float(gamma)
    if not 0 <= gamma <= 1:
        raise ValueError("gamma must lie in [0, 1]")
    if np.any(th <= 0):
        raise ValueError("theta must be positive")
    ans = eta / (th ** gamma * (1.0 + th) ** (1.0 - gamma))
    return float(ans[0]) if np.ndim(theta) == 0 else ans


def ssvi_total_variance(k: float | Sequence[float], theta: float, rho: float,
                        eta: float, gamma: float) -> float | np.ndarray:
    x = _array(np.atleast_1d(k), "k", 1)
    th = _positive(theta, "theta")
    rho = float(rho)
    if not -1 < rho < 1:
        raise ValueError("rho must lie strictly between -1 and 1")
    phi = float(ssvi_phi(th, eta, gamma))
    u = phi * x + rho
    root = np.sqrt(u * u + 1.0 - rho * rho)
    w = 0.5 * th * (1.0 + rho * phi * x + root)
    if np.any(w <= 0) or np.any(~np.isfinite(w)):
        raise FloatingPointError("SSVI total variance was not positive/finite")
    return float(w[0]) if np.ndim(k) == 0 else w


def ssvi_derivatives(k: float | Sequence[float], theta: float, rho: float,
                     eta: float, gamma: float) -> tuple[float | np.ndarray, float | np.ndarray, float | np.ndarray]:
    x = _array(np.atleast_1d(k), "k", 1)
    th = _positive(theta, "theta")
    rho = float(rho)
    if not -1 < rho < 1:
        raise ValueError("rho must lie strictly between -1 and 1")
    phi = float(ssvi_phi(th, eta, gamma))
    u = phi * x + rho
    root = np.sqrt(u * u + 1.0 - rho * rho)
    w = 0.5 * th * (1 + rho * phi * x + root)
    wk = 0.5 * th * phi * (rho + u / root)
    wkk = 0.5 * th * phi * phi * (1 - rho * rho) / (root ** 3)
    if np.any(w <= 0):
        raise FloatingPointError("non-positive total variance")
    conv = lambda arr: float(arr[0]) if np.ndim(k) == 0 else arr
    return conv(w), conv(wk), conv(wkk)


def ssvi_butterfly_density(k: float | Sequence[float], theta: float, rho: float,
                           eta: float, gamma: float) -> float | np.ndarray:
    """Gatheral-Jacquier g(k) diagnostic for non-negative risk-neutral density."""
    x = _array(np.atleast_1d(k), "k", 1)
    w, wk, wkk = ssvi_derivatives(x, theta, rho, eta, gamma)
    w = np.asarray(w); wk = np.asarray(wk); wkk = np.asarray(wkk)
    g = (1.0 - x * wk / (2.0 * w)) ** 2 - (wk * wk / 4.0) * (1.0 / w + 0.25) + 0.5 * wkk
    return float(g[0]) if np.ndim(k) == 0 else g


def ssvi_wing_slopes(theta: float, rho: float, eta: float, gamma: float) -> tuple[float, float]:
    th = _positive(theta, "theta"); r = float(rho)
    if not -1 < r < 1:
        raise ValueError("rho must lie in (-1,1)")
    p = float(ssvi_phi(th, eta, gamma))
    return th * p * (1 - r) / 2.0, th * p * (1 + r) / 2.0  # put, call


def ssvi_parameter_constraints(theta: float, rho: float, eta: float, gamma: float,
                               tolerance: float = 1e-12) -> dict[str, bool | float]:
    """Sufficient SSVI parameter checks plus wing slopes; not a global proof on its own."""
    th = _positive(theta, "theta"); r = float(rho); e = _positive(eta, "eta"); g = float(gamma)
    if not -1 < r < 1 or not 0 <= g <= 1:
        raise ValueError("rho must lie in (-1,1) and gamma in [0,1]")
    p = float(ssvi_phi(th, e, g))
    condition1 = th * p * (1 + abs(r)) < 4.0 + tolerance
    condition2 = th * p * p * (1 + abs(r)) <= 4.0 + tolerance
    put_slope, call_slope = ssvi_wing_slopes(th, r, e, g)
    wing_ok = 0 <= put_slope <= 2.0 + tolerance and 0 <= call_slope <= 2.0 + tolerance
    return {"ssvi_condition_1": condition1, "ssvi_condition_2": condition2,
            "wing_bounds": wing_ok, "put_wing_slope": put_slope, "call_wing_slope": call_slope,
            "admissible": bool(condition1 and condition2 and wing_ok)}


def surface_diagnostics(expiries: Sequence[float], theta_values: Sequence[float], rho: float,
                        eta: float, gamma: float, k_grid: Sequence[float] | None = None,
                        tolerance: float = 1e-8) -> dict[str, Any]:
    T = _array(expiries, "expiries", 1); th = _array(theta_values, "theta_values", 1)
    if T.size == 0 or T.shape != th.shape or np.any(T <= 0) or np.any(np.diff(T) <= 0):
        raise ValueError("expiries must be positive and strictly increasing, matching theta values")
    if np.any(th <= 0):
        raise ValueError("theta values must be positive")
    kk = np.asarray(k_grid if k_grid is not None else np.linspace(-4, 4, 801), dtype=float)
    if kk.ndim != 1 or kk.size < 3 or not np.all(np.isfinite(kk)) or np.any(np.diff(kk) <= 0):
        raise ValueError("k_grid must be finite, increasing, and have at least 3 points")
    theta_order_ok = bool(np.all(np.diff(th) >= -tolerance))
    theta_phi = np.asarray(ssvi_phi(th, eta, gamma), dtype=float) * th
    theta_phi_ok = bool(np.all(np.diff(theta_phi) >= -tolerance))
    modeled = np.vstack([np.asarray(ssvi_total_variance(kk, float(ti), rho, eta, gamma)) for ti in th])
    pointwise_calendar_ok = bool(np.all(np.diff(modeled, axis=0) >= -tolerance))
    cal_ok = theta_order_ok and theta_phi_ok and pointwise_calendar_ok
    density = [np.asarray(ssvi_butterfly_density(kk, float(ti), rho, eta, gamma)) for ti in th]
    min_g = float(min(np.min(x) for x in density))
    wing = [ssvi_parameter_constraints(float(ti), rho, eta, gamma) for ti in th]
    return {"nonnegative_total_variance": bool(np.all(modeled > 0)), "calendar_monotonicity": cal_ok,
            "theta_monotonicity": theta_order_ok, "theta_phi_monotonicity": theta_phi_ok,
            "pointwise_surface_calendar_monotonicity": pointwise_calendar_ok,
            "minimum_butterfly_density": min_g, "butterfly_density_nonnegative": bool(min_g >= -tolerance),
            "wing_bounds": bool(all(x["wing_bounds"] for x in wing)),
            "ssvi_sufficient_conditions": bool(all(x["ssvi_condition_1"] and x["ssvi_condition_2"] for x in wing)),
            "admissible_on_grid": bool(cal_ok and min_g >= -tolerance and all(x["admissible"] for x in wing))}


@dataclass(frozen=True)
class SSVICalibration:
    rho: float
    eta: float
    gamma: float
    rmse: float
    accepted: bool
    constraints: Mapping[str, Any]


def calibrate_ssvi_grid(theta: float, k: Sequence[float], observed_total_variance: Sequence[float],
                        rho_candidates: Sequence[float] = (-0.7, -0.4, -0.1, 0.2),
                        eta_candidates: Sequence[float] = (0.1, 0.2, 0.35, 0.5),
                        gamma_candidates: Sequence[float] = (0.25, 0.5, 0.75),
                        density_grid: Sequence[float] | None = None) -> SSVICalibration:
    """Deterministic coarse-grid calibration with constraint filtering; no market-data claim."""
    th = _positive(theta, "theta")
    x = _array(k, "k", 1); y = _array(observed_total_variance, "observed_total_variance", 1)
    if x.size == 0 or x.shape != y.shape or np.any(y <= 0):
        raise ValueError("k and observed variances must be aligned, non-empty, and positive")
    dg = np.asarray(density_grid if density_grid is not None else np.linspace(-4, 4, 401), dtype=float)
    best: tuple[float, float, float, float, dict[str, Any]] | None = None
    for r in rho_candidates:
        for e in eta_candidates:
            for g in gamma_candidates:
                try:
                    c = ssvi_parameter_constraints(th, float(r), float(e), float(g))
                    if not c["admissible"]:
                        continue
                    dens = np.asarray(ssvi_butterfly_density(dg, th, float(r), float(e), float(g)))
                    if float(dens.min()) < -1e-8:
                        continue
                    pred = np.asarray(ssvi_total_variance(x, th, float(r), float(e), float(g)))
                    rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
                    if best is None or rmse < best[0]:
                        best = (rmse, float(r), float(e), float(g), c)
                except (ValueError, FloatingPointError):
                    continue
    if best is None:
        raise ValueError("no candidate satisfies SSVI constraints and sampled butterfly non-negativity")
    rmse, r, e, g, c = best
    return SSVICalibration(r, e, g, rmse, True, c)


# ---------------------------------------------------------------------------
# BOCPD: Gaussian predictive model + Hawkes intensity coupling
# ---------------------------------------------------------------------------
class BayesianOnlineChangepointDetector:
    """Run-length posterior with a Gaussian known-observation-variance model."""
    def __init__(self, hazard_lambda: float = 100.0, prior_mean: float = 0.0,
                 prior_variance: float = 1.0, observation_variance: float = 0.05,
                 max_run_length: int = 200):
        self.hazard_lambda = _positive(hazard_lambda, "hazard_lambda")
        self.prior_mean = float(prior_mean)
        self.prior_variance = _positive(prior_variance, "prior_variance")
        self.observation_variance = _positive(observation_variance, "observation_variance")
        if not np.isfinite(self.prior_mean):
            raise ValueError("prior_mean must be finite")
        if not isinstance(max_run_length, int) or max_run_length < 1:
            raise ValueError("max_run_length must be a positive integer")
        self.max_run_length = max_run_length
        self.run_probs = np.array([1.0])
        self.posterior_means = np.array([self.prior_mean])
        self.posterior_vars = np.array([self.prior_variance])
        self.n_observations = 0

    @property
    def hazard(self) -> float:
        return min(1.0, 1.0 / self.hazard_lambda)

    @property
    def changepoint_probability(self) -> float:
        return float(self.run_probs[0])

    def update(self, observation: float) -> dict[str, Any]:
        x = float(observation)
        if not np.isfinite(x):
            raise ValueError("observation must be finite")
        prior_pred_var = self.prior_variance + self.observation_variance
        cp_like = np.exp(-0.5 * (x - self.prior_mean) ** 2 / prior_pred_var) / np.sqrt(2 * PI * prior_pred_var)
        pred_var = self.posterior_vars + self.observation_variance
        like = np.exp(-0.5 * (x - self.posterior_means) ** 2 / pred_var) / np.sqrt(2 * PI * pred_var)
        H = self.hazard
        cp_mass = float(cp_like * np.sum(self.run_probs * H))
        growth = self.run_probs * like * (1.0 - H)
        raw = np.concatenate(([cp_mass], growth))
        if self.max_run_length + 1 < raw.size:
            raw = raw[:self.max_run_length + 1]
        z = float(raw.sum())
        if not np.isfinite(z) or z <= 0:
            raise FloatingPointError("BOCPD posterior normalization failed")
        self.run_probs = raw / z
        # Conjugate update including the current observation for both the reset
        # run and every growth run. Index zero now represents a run length of 0
        # completed observations since the changepoint *before* the current datum,
        # but its posterior predictive state has observed x_t.
        post_var = 1.0 / (1.0 / self.posterior_vars + 1.0 / self.observation_variance)
        post_mean = post_var * (self.posterior_means / self.posterior_vars + x / self.observation_variance)
        reset_var = 1.0 / (1.0 / self.prior_variance + 1.0 / self.observation_variance)
        reset_mean = reset_var * (self.prior_mean / self.prior_variance + x / self.observation_variance)
        self.posterior_means = np.concatenate(([reset_mean], post_mean))[:self.run_probs.size]
        self.posterior_vars = np.concatenate(([reset_var], post_var))[:self.run_probs.size]
        self.n_observations += 1
        return {"changepoint_probability": self.changepoint_probability,
                "run_length_probabilities": self.run_probs.copy(),
                "expected_run_length": float(np.dot(np.arange(self.run_probs.size), self.run_probs)),
                "posterior_mean_by_run": self.posterior_means.copy()}


@dataclass(frozen=True)
class HawkesBOCPDUpdate:
    intensities: np.ndarray
    changepoint_probabilities: np.ndarray
    system_changepoint_probability: float


class HawkesBOCPDFilter:
    """Multivariate exponential Hawkes traces augmented by per-asset BOCPD change mass."""
    def __init__(self, baseline: Sequence[float], alpha: Sequence[Sequence[float]],
                 beta: Sequence[Sequence[float]], bocpd_weight: float = 1.0,
                 hazard_lambda: float = 100.0, max_run_length: int = 200):
        self.mu = _array(baseline, "baseline", 1)
        self.alpha = _array(alpha, "alpha", 2); self.beta = _array(beta, "beta", 2)
        n = self.mu.size
        if n == 0 or self.alpha.shape != (n, n) or self.beta.shape != (n, n):
            raise ValueError("baseline, alpha and beta dimensions must align")
        if np.any(self.mu <= 0) or np.any(self.alpha < 0) or np.any(self.beta <= 0):
            raise ValueError("baseline/beta must be positive and alpha non-negative")
        self.bocpd_weight = _positive(bocpd_weight, "bocpd_weight", allow_zero=True)
        self.bocpd = [BayesianOnlineChangepointDetector(hazard_lambda, max_run_length=max_run_length) for _ in range(n)]
        self.kernel_state = np.zeros((n, n), dtype=float)
        self.intensities = self.mu.copy()
        self.last_change_probs = np.zeros(n)
        self.branching_matrix = self.alpha / self.beta
        self.spectral_radius = float(max(abs(np.linalg.eigvals(self.branching_matrix))))
        if self.spectral_radius >= 0.88:
            raise ValueError(f"Hawkes kernel must be strictly subcritical: rho={self.spectral_radius:.6f} >= 0.88")

    def update(self, event_counts: Sequence[float], observations: Sequence[float], dt: float) -> HawkesBOCPDUpdate:
        counts = _array(event_counts, "event_counts", 1); obs = _array(observations, "observations", 1)
        dt = _positive(dt, "dt")
        n = self.mu.size
        if counts.shape != (n,) or obs.shape != (n,) or np.any(counts < 0):
            raise ValueError("event_counts/observations must match asset count and counts be non-negative")
        cp = np.array([d.update(float(x))["changepoint_probability"] for d, x in zip(self.bocpd, obs)])
        self.kernel_state *= np.exp(-self.beta * dt)
        self.kernel_state += counts[np.newaxis, :]
        self.intensities = self.mu + np.sum(self.alpha * self.kernel_state, axis=1) + self.bocpd_weight * cp
        if np.any(~np.isfinite(self.intensities)) or np.any(self.intensities < 0):
            raise FloatingPointError("invalid Hawkes intensities")
        self.last_change_probs = cp
        return HawkesBOCPDUpdate(self.intensities.copy(), cp.copy(), float(np.max(cp)))


def validate_hawkes_stability(alpha: Sequence[Sequence[float]], beta: Sequence[Sequence[float]],
                              limit: float = 0.88) -> dict[str, Any]:
    a = _array(alpha, "alpha", 2); b = _array(beta, "beta", 2); lim = _positive(limit, "limit")
    if a.shape != b.shape or a.shape[0] != a.shape[1] or np.any(a < 0) or np.any(b <= 0):
        raise ValueError("alpha and beta must be aligned square matrices, alpha>=0, beta>0")
    B = a / b
    rho = float(max(abs(np.linalg.eigvals(B))))
    return {"branching_matrix": B, "spectral_radius": rho, "limit": lim, "stable": bool(rho < lim)}


# ---------------------------------------------------------------------------
# Friction-aware inventory indifference bands
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IndifferenceBand:
    lower: float
    upper: float
    base_half_width: float
    buy_half_width: float
    sell_half_width: float


def friction_aware_indifference_band(sigma: float, risk_aversion: float, friction_cost: float,
                                      buy_spread_penalty: float = 0.0, sell_spread_penalty: float = 0.0,
                                      statutory_fee_drag: float = 0.0,
                                      inventory_target: float = 0.0) -> IndifferenceBand:
    """Approximate cubic-root no-trade band with asymmetric spread and fee widening.

    Penalties are non-negative inventory-equivalent half-width adjustments. The returned
    boundaries are centered on ``inventory_target``. This is a stylized
    Davis-Norman/Shreve-inspired band, not an exact theorem for arbitrary markets.
    """
    sig = _positive(sigma, "sigma"); gamma_risk = _positive(risk_aversion, "risk_aversion")
    c = _positive(friction_cost, "friction_cost", allow_zero=True)
    bp = _positive(buy_spread_penalty, "buy_spread_penalty", allow_zero=True)
    sp = _positive(sell_spread_penalty, "sell_spread_penalty", allow_zero=True)
    fee = _positive(statutory_fee_drag, "statutory_fee_drag", allow_zero=True)
    target = float(inventory_target)
    if not np.isfinite(target):
        raise ValueError("inventory_target must be finite")
    base = ((3.0 * c * sig * sig) / (4.0 * gamma_risk)) ** (1.0 / 3.0) if c > 0 else 0.0
    buy = base + bp + fee
    sell = base + sp + fee
    return IndifferenceBand(target - buy, target + sell, base, buy, sell)


def friction_aware_advantage(reward: float, value: float, next_value: float, discount: float,
                             statutory_fees: float, inventory_variance: float,
                             inventory_penalty: float = 1.0) -> float:
    vals = np.asarray([reward, value, next_value, discount, statutory_fees, inventory_variance, inventory_penalty], float)
    if not np.all(np.isfinite(vals)) or not 0 <= discount <= 1 or statutory_fees < 0 or inventory_variance < 0 or inventory_penalty < 0:
        raise ValueError("invalid advantage inputs")
    return float(reward - statutory_fees - inventory_penalty * inventory_variance + discount * next_value - value)


# ---------------------------------------------------------------------------
# State-conditioned Gaussian actor-critic (NumPy, deterministic init)
# ---------------------------------------------------------------------------
class ContinuousActorCritic:
    def __init__(self, state_dim: int = STATE_DIMENSION, action_dim: int = 3,
                 hidden: tuple[int, int] = (32, 16), seed: int = 53):
        if state_dim != STATE_DIMENSION or action_dim != 3:
            raise ValueError("Cycle 53 contract requires state_dim=16 and action_dim=3")
        if len(hidden) != 2 or any(not isinstance(x, int) or x < 1 for x in hidden):
            raise ValueError("hidden must contain two positive widths")
        rng = np.random.default_rng(seed)
        self.state_dim = state_dim; self.action_dim = action_dim; self.hidden = hidden
        h1, h2 = hidden
        def w(a, b): return rng.normal(0, 1 / np.sqrt(a), size=(a, b))
        self.a_w1, self.a_b1 = w(state_dim, h1), np.zeros(h1)
        self.a_w2, self.a_b2 = w(h1, h2), np.zeros(h2)
        self.mu_w, self.mu_b = w(h2, action_dim), np.zeros(action_dim)
        self.logstd_w, self.logstd_b = w(h2, action_dim) * 0.15, np.full(action_dim, -0.5)
        self.c_w1, self.c_b1 = w(state_dim, h1), np.zeros(h1)
        self.c_w2, self.c_b2 = w(h1, h2), np.zeros(h2)
        self.v_w, self.v_b = w(h2, 1), np.zeros(1)
        self.rng = rng

    def _state(self, state: Sequence[float]) -> np.ndarray:
        s = _array(state, "state", 1)
        if s.shape != (self.state_dim,):
            raise ValueError(f"state must have shape ({self.state_dim},)")
        return s

    def policy_parameters(self, state: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
        s = self._state(state)
        h1 = np.tanh(s @ self.a_w1 + self.a_b1)
        h2 = np.tanh(h1 @ self.a_w2 + self.a_b2)
        mu = h2 @ self.mu_w + self.mu_b
        log_std = np.clip(h2 @ self.logstd_w + self.logstd_b, -5.0, 1.0)
        return mu, np.exp(log_std)

    def act(self, state: Sequence[float], deterministic: bool = True) -> np.ndarray:
        mu, std = self.policy_parameters(state)
        z = mu if deterministic else self.rng.normal(mu, std)
        return np.tanh(z)

    def value(self, state: Sequence[float]) -> float:
        s = self._state(state)
        h1 = np.tanh(s @ self.c_w1 + self.c_b1)
        h2 = np.tanh(h1 @ self.c_w2 + self.c_b2)
        return float((h2 @ self.v_w + self.v_b)[0])


def continuous_actor_critic_advantage(reward: float, value: float, next_value: float, discount: float,
                                      fees: float, inventory_variance: float, risk_weight: float = 1.0) -> float:
    return friction_aware_advantage(reward, value, next_value, discount, fees, inventory_variance, risk_weight)


# ---------------------------------------------------------------------------
# Indian statutory friction, strict net-alpha and fractional Kelly
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StatutoryFees:
    sell_stt: float
    buy_stamp_duty: float
    exchange_charges: float
    sebi_fee: float
    brokerage: float
    gst: float
    total: float


def calculate_statutory_fees(buy_turnover: float, sell_turnover: float, executed_legs: int,
                             brokerage_per_leg: float = 20.0) -> StatutoryFees:
    buy = _positive(buy_turnover, "buy_turnover", allow_zero=True)
    sell = _positive(sell_turnover, "sell_turnover", allow_zero=True)
    brokerage = _positive(brokerage_per_leg, "brokerage_per_leg", allow_zero=True)
    if not isinstance(executed_legs, int) or executed_legs < 0:
        raise ValueError("executed_legs must be a non-negative integer")
    total_turnover = buy + sell
    stt = sell * 0.0015
    stamp = buy * 0.00003
    exchange = total_turnover * 3553.0 / INR_PER_CRORE
    sebi = total_turnover * 10.0 / INR_PER_CRORE
    brok = executed_legs * brokerage
    gst = 0.18 * (exchange + sebi + brok)
    total = stt + stamp + exchange + sebi + brok + gst
    return StatutoryFees(stt, stamp, exchange, sebi, brok, gst, total)


def net_alpha_gate(expected_gross_alpha: float, fees: float | StatutoryFees) -> tuple[bool, float]:
    gross = float(expected_gross_alpha)
    fee = fees.total if isinstance(fees, StatutoryFees) else float(fees)
    if not np.isfinite(gross) or not np.isfinite(fee) or fee < 0:
        raise ValueError("gross alpha and fees must be finite; fees non-negative")
    net = gross - fee
    return bool(net > 0.0), float(net)


def beta_posterior_fractional_kelly(alpha_wins: float, beta_losses: float, payoff_odds: float,
                                    fractional_scale: float = 0.25,
                                    max_fraction: float = MAX_KELLY_FRACTION) -> float:
    a = _positive(alpha_wins, "alpha_wins"); bpost = _positive(beta_losses, "beta_losses")
    odds = _positive(payoff_odds, "payoff_odds")
    scale = float(fractional_scale); cap = float(max_fraction)
    if not np.isfinite(scale) or not 0 <= scale <= 1:
        raise ValueError("fractional_scale must be in [0,1]")
    if not np.isfinite(cap) or not 0 <= cap <= MAX_KELLY_FRACTION:
        raise ValueError("max_fraction must be in [0, 0.10]")
    p = a / (a + bpost)
    full_kelly = (p * (odds + 1.0) - 1.0) / odds
    return float(np.clip(full_kelly * scale, 0.0, cap))


# ---------------------------------------------------------------------------
# Squad consensus and immutable safety barrier
# ---------------------------------------------------------------------------
def four_agent_consensus(manager_approved: bool, queue_safe: bool, volatility_safe: bool,
                         net_alpha_positive: bool) -> dict[str, Any]:
    agents = {"Manager Abhi": bool(manager_approved), "Alex / L3 queue risk": bool(queue_safe),
              "Emily / rough volatility and BOCPD": bool(volatility_safe),
              "Max / statutory friction and Kelly": bool(net_alpha_positive)}
    failed = [name for name, ok in agents.items() if not ok]
    return {"approved": not failed, "agents": agents, "failed_vetoes": failed,
            "execution_mode": "PAPER_ONLY"}


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Unconditionally refuse live order dispatch; this barrier is intentionally immutable."""
    raise PermissionError("Live broker order dispatch is disabled; Cycle 53 is paper/research only")


def engine_manifest_summary() -> dict[str, Any]:
    return {"cycle": 53, "name": "RBSVI-BOCPD", "assets": list(ASSETS),
            "hurst": ROUGH_HURST, "state_dimension": STATE_DIMENSION,
            "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
            "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED,
            "paper_ledger_epoch": PAPER_LEDGER_EPOCH, "initial_capital_inr": INITIAL_CAPITAL_INR}
