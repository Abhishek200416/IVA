"""Cycle 61 RB-FSK-DOFI research engine.

Offline research / paper simulation only. No broker connectivity or live-order path.
Python 3.11-compatible source; uses NumPy and SciPy for numerical routines.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import exp, factorial, gamma, log, sqrt
from typing import Iterable, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import linprog, nnls

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0
ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
MLOFI_WEIGHTS = np.asarray([5.0, 4.0, 3.0, 2.0, 1.0])
MAX_KELLY_FRACTION = 0.10
MAX_HAWKES_BRANCHING_RADIUS = 0.88


def dispatch_live_order(*args, **kwargs):
    """Permanently disabled order-dispatch boundary."""
    raise PermissionError("Cycle 61 is paper-only: live order dispatch is permanently disabled")


def _finite_array(value: ArrayLike, name: str, ndim: int | None = None) -> NDArray[np.float64]:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _positive_scalar(value: float, name: str, allow_zero: bool = False) -> float:
    value = float(value)
    if not np.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        comparison = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {comparison}")
    return value


@dataclass(frozen=True)
class VolterraLift:
    hurst: float
    rates: NDArray[np.float64]
    weights: NDArray[np.float64]
    t_min: float
    t_max: float
    relative_l2_error: float

    def kernel(self, times: ArrayLike) -> NDArray[np.float64]:
        t = _finite_array(times, "times")
        if np.any(t <= 0):
            raise ValueError("kernel evaluation times must be strictly positive")
        return np.exp(-np.outer(t.reshape(-1), self.rates)) @ self.weights if t.ndim else np.asarray(float(np.exp(-self.rates * float(t)) @ self.weights))

    def exact_kernel(self, times: ArrayLike) -> NDArray[np.float64]:
        t = _finite_array(times, "times")
        if np.any(t <= 0):
            raise ValueError("kernel evaluation times must be strictly positive")
        return np.power(t, self.hurst - 0.5) / gamma(self.hurst + 0.5)


@lru_cache(maxsize=48)
def _fit_lift_cached(hurst: float, n_factors: int, t_min: float, t_max: float, n_grid: int):
    rates = np.geomspace(1.0 / t_max, 1.0 / t_min, n_factors)
    fit_times = np.geomspace(t_min, t_max, n_grid)
    target = np.power(fit_times, hurst - 0.5) / gamma(hurst + 0.5)
    design = np.exp(-np.outer(fit_times, rates))
    weights, _ = nnls(design, target, maxiter=max(3 * n_factors, 100))
    approx = design @ weights
    denom = max(float(np.linalg.norm(target)), np.finfo(float).tiny)
    rel_error = float(np.linalg.norm(approx - target) / denom)
    return tuple(float(x) for x in rates), tuple(float(x) for x in weights), rel_error


def fit_volterra_lift(
    hurst: float = 0.07,
    n_factors: int = 12,
    t_min: float = 1e-4,
    t_max: float = 2.0,
    n_grid: int = 384,
) -> VolterraLift:
    """Fit a positive logarithmically-spaced exponential lift to K_H(t).

    Nonnegative least squares prevents negative exponential weights. The returned
    error is measured over the fitting grid; it is not a uniform-error proof.
    """
    hurst = float(hurst)
    if not 0.0 < hurst < 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    if int(n_factors) != n_factors or n_factors < 1:
        raise ValueError("n_factors must be a positive integer")
    if int(n_grid) != n_grid or n_grid < max(16, n_factors):
        raise ValueError("n_grid must be an integer >= max(16, n_factors)")
    t_min = _positive_scalar(t_min, "t_min")
    t_max = _positive_scalar(t_max, "t_max")
    if t_max <= t_min:
        raise ValueError("t_max must exceed t_min")
    r, w, err = _fit_lift_cached(hurst, int(n_factors), t_min, t_max, int(n_grid))
    return VolterraLift(hurst, np.asarray(r), np.asarray(w), t_min, t_max, err)


def forward_variance_curve(times: ArrayLike, xi0: ArrayLike, query_times: ArrayLike) -> NDArray[np.float64]:
    """Piecewise-linear positive forward variance interpolation."""
    t = _finite_array(times, "times", 1)
    x = _finite_array(xi0, "xi0", 1)
    q = _finite_array(query_times, "query_times")
    if len(t) != len(x) or len(t) < 2:
        raise ValueError("times and xi0 must have equal length >= 2")
    if np.any(np.diff(t) <= 0) or np.any(t < 0):
        raise ValueError("times must be strictly increasing and non-negative")
    if np.any(x <= 0):
        raise ValueError("forward variance values must be positive")
    if np.any(q < t[0]) or np.any(q > t[-1]):
        raise ValueError("query_times must lie inside the calibration horizon")
    return np.interp(q, t, x)


def cumulative_total_variance(times: ArrayLike, xi0: ArrayLike) -> NDArray[np.float64]:
    """Trapezoidal integral of a positive forward-variance curve."""
    t = _finite_array(times, "times", 1)
    x = _finite_array(xi0, "xi0", 1)
    if len(t) != len(x) or len(t) < 2 or np.any(np.diff(t) <= 0) or np.any(t < 0) or np.any(x <= 0):
        raise ValueError("times must increase and match positive xi0 values")
    out = np.zeros_like(t)
    out[1:] = np.cumsum(0.5 * (x[1:] + x[:-1]) * np.diff(t))
    return out


def validate_calendar_total_variance(total_variance: ArrayLike, tolerance: float = 1e-10) -> dict:
    """Check non-negative total variance and monotonicity in expiry rows."""
    w = _finite_array(total_variance, "total_variance", 2)
    tol = _positive_scalar(tolerance, "tolerance", allow_zero=True)
    if w.shape[0] < 1 or w.shape[1] < 1:
        raise ValueError("total_variance must be a non-empty expiry-by-strike matrix")
    calendar_diff = np.diff(w, axis=0)
    return {
        "non_negative": bool(np.all(w >= -tol)),
        "calendar_monotone": bool(np.all(calendar_diff >= -tol)),
        "min_total_variance": float(np.min(w)),
        "min_calendar_increment": float(np.min(calendar_diff)) if calendar_diff.size else float("inf"),
    }


def validate_butterfly_convexity(strikes: ArrayLike, call_prices: ArrayLike, tolerance: float = 1e-8) -> dict:
    """Finite-grid call-price convexity check using nonuniform strike slopes."""
    k = _finite_array(strikes, "strikes", 1)
    c = _finite_array(call_prices, "call_prices", 1)
    tol = _positive_scalar(tolerance, "tolerance", allow_zero=True)
    if len(k) != len(c) or len(k) < 3 or np.any(k <= 0) or np.any(np.diff(k) <= 0):
        raise ValueError("strikes must be positive, increasing, and have >=3 matching prices")
    slopes = np.diff(c) / np.diff(k)
    convex_diffs = np.diff(slopes)
    return {
        "convex": bool(np.all(convex_diffs >= -tol)),
        "min_slope_increment": float(np.min(convex_diffs)),
        "slopes": slopes.tolist(),
    }


def _signature_level_tensor(dx: NDArray[np.float64], level: int) -> NDArray[np.float64]:
    if level == 0:
        return np.asarray([1.0])
    return np.reshape(_tensor_power(dx, level) / factorial(level), (-1,))


def _tensor_power(x: NDArray[np.float64], degree: int) -> NDArray[np.float64]:
    out = np.asarray([1.0])
    for _ in range(degree):
        out = np.kron(out, x)
    return out


def path_signature(path: ArrayLike, degree: int = 3) -> dict[int, NDArray[np.float64]]:
    """Piecewise-linear truncated tensor signature through degree 3 by default."""
    p = _finite_array(path, "path", 2)
    if len(p) < 1 or p.shape[1] < 1:
        raise ValueError("path must have at least one row and one channel")
    if int(degree) != degree or degree < 1 or degree > 3:
        raise ValueError("degree must be an integer in [1, 3]")
    d = p.shape[1]
    sig = {0: np.asarray([1.0])}
    for level in range(1, int(degree) + 1):
        sig[level] = np.zeros(d ** level, dtype=float)
    for dx in np.diff(p, axis=0):
        segment = {0: np.asarray([1.0])}
        for level in range(1, int(degree) + 1):
            segment[level] = _tensor_power(dx, level) / factorial(level)
        combined = {}
        for level in range(1, int(degree) + 1):
            val = np.zeros(d ** level, dtype=float)
            for i in range(level + 1):
                old = sig[i] if i in sig else np.asarray([1.0])
                new = segment[level - i]
                val += np.kron(old, new)
            combined[level] = val
        sig.update(combined)
    return sig


def chen_concatenate(sig_a: Mapping[int, ArrayLike], sig_b: Mapping[int, ArrayLike], degree: int = 3) -> dict[int, NDArray[np.float64]]:
    """Truncated tensor product under Chen's identity."""
    if int(degree) != degree or degree < 1 or degree > 3:
        raise ValueError("degree must be an integer in [1, 3]")
    out: dict[int, NDArray[np.float64]] = {0: np.asarray([1.0])}
    for level in range(1, int(degree) + 1):
        if level not in sig_a or level not in sig_b:
            raise ValueError("both signatures must contain every requested level")
        a = {i: _finite_array(sig_a[i], f"sig_a[{i}]", 1) for i in range(level + 1)}
        b = {i: _finite_array(sig_b[i], f"sig_b[{i}]", 1) for i in range(level + 1)}
        acc = np.zeros(a[level].size + b[0].size - 1 + 0)  # replaced below with correct tensor dimension
        dim = int(round(a[1].size ** (1 / 1))) if level == 1 else None
        size = a[level].size
        acc = np.zeros(size, dtype=float)
        for i in range(level + 1):
            acc += np.kron(a[i], b[level - i])
        out[level] = acc
    # Level 0 is implicit; all levels must have compatible tensor dimensions.
    return out


def signature_feature_vector(path: ArrayLike, degree: int = 3) -> NDArray[np.float64]:
    sig = path_signature(path, degree)
    return np.concatenate([sig[k] for k in range(1, degree + 1)])


def randomized_signature_kernel(path_a: ArrayLike, path_b: ArrayLike, degree: int = 3, n_projections: int = 64, seed: int = 61, bandwidth: float = 1.0) -> float:
    """Seeded random-projection approximation to an RBF signature kernel."""
    fa = signature_feature_vector(path_a, degree)
    fb = signature_feature_vector(path_b, degree)
    if fa.shape != fb.shape:
        raise ValueError("paths must have the same channel dimension")
    if int(n_projections) != n_projections or n_projections < 1:
        raise ValueError("n_projections must be a positive integer")
    bandwidth = _positive_scalar(bandwidth, "bandwidth")
    rng = np.random.default_rng(seed)
    projection = rng.normal(size=(int(n_projections), fa.size)) / sqrt(int(n_projections))
    pa, pb = projection @ fa, projection @ fb
    return float(np.exp(-np.sum((pa - pb) ** 2) / (2.0 * bandwidth ** 2)))


def geometric_area_tensor(path: ArrayLike) -> NDArray[np.float64]:
    """Antisymmetric level-2 geometric area tensor A_ij=(Sij-Sji)/2."""
    sig = path_signature(path, 2)
    d = _finite_array(path, "path", 2).shape[1]
    second = sig[2].reshape(d, d)
    return 0.5 * (second - second.T)


def multi_level_ofi(
    delta_bid_volume: ArrayLike,
    delta_ask_volume: ArrayLike,
    delta_bid_price: ArrayLike,
    delta_ask_price: ArrayLike,
    weights: ArrayLike = MLOFI_WEIGHTS,
) -> tuple[float, NDArray[np.float64]]:
    """Top-five MLOFI; returns aggregate and signed level contributions."""
    vb = _finite_array(delta_bid_volume, "delta_bid_volume", 1)
    va = _finite_array(delta_ask_volume, "delta_ask_volume", 1)
    pb = _finite_array(delta_bid_price, "delta_bid_price", 1)
    pa = _finite_array(delta_ask_price, "delta_ask_price", 1)
    w = _finite_array(weights, "weights", 1)
    if any(len(x) != 5 for x in (vb, va, pb, pa, w)):
        raise ValueError("MLOFI requires exactly five L1-L5 values per input")
    contributions = w * (vb * (pb >= 0) - va * (pa <= 0))
    return float(np.sum(contributions)), contributions


def cancellation_intensity(
    base_rate: float,
    ofi_levels: ArrayLike,
    beta_price: float,
    delta_price: float,
    alpha_levels: ArrayLike | None = None,
) -> float:
    """Non-negative cancellation intensity from the specified L1-L5 model."""
    base = _positive_scalar(base_rate, "base_rate", allow_zero=True)
    ofi = _finite_array(ofi_levels, "ofi_levels", 1)
    if len(ofi) != 5:
        raise ValueError("ofi_levels must contain five values")
    alpha = np.ones(5) if alpha_levels is None else _finite_array(alpha_levels, "alpha_levels", 1)
    if len(alpha) != 5 or np.any(alpha < 0):
        raise ValueError("alpha_levels must contain five non-negative values")
    beta = _positive_scalar(beta_price, "beta_price", allow_zero=True)
    dp = float(delta_price)
    if not np.isfinite(dp):
        raise ValueError("delta_price must be finite")
    return float(max(0.0, base + np.dot(alpha, ofi) + beta * dp))


def queue_priority_degradation(queue_ahead: float, depth: float, age: float, cancellation_rate: float, ofi_toxicity: float) -> float:
    vals = [float(queue_ahead), float(depth), float(age), float(cancellation_rate), float(ofi_toxicity)]
    if not all(np.isfinite(vals)) or queue_ahead < 0 or depth <= 0 or age < 0 or cancellation_rate < 0:
        raise ValueError("queue/depth/age/hazard inputs are outside their valid domain")
    # Each term contributes monotonically; bounded sigmoid-like mapping.
    raw = 0.8 * queue_ahead / (queue_ahead + depth) + 0.1 * age / (1.0 + age) + 0.1 * cancellation_rate / (1.0 + cancellation_rate) + 0.1 * abs(ofi_toxicity) / (1.0 + abs(ofi_toxicity))
    return float(min(1.0, max(0.0, raw)))


def adverse_selection_probability(toxic_intensity: float, horizon: float) -> float:
    lam = _positive_scalar(toxic_intensity, "toxic_intensity", allow_zero=True)
    tau = _positive_scalar(horizon, "horizon", allow_zero=True)
    return float(-np.expm1(-lam * tau))


def quote_action(toxic_intensity: float, horizon: float, threshold: float = 0.60) -> str:
    threshold = float(threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    return "RETREAT" if adverse_selection_probability(toxic_intensity, horizon) > threshold else "QUOTE"


def rough_volterra_simulation(
    times: ArrayLike,
    xi0: ArrayLike,
    hurst: float = 0.07,
    n_factors: int = 12,
    nu: float = 0.6,
    seed: int = 61,
    t_min: float = 1e-4,
    t_max: float | None = None,
) -> dict[str, NDArray[np.float64]]:
    """Seeded positive variance path using a 12-factor Markovian kernel lift."""
    t = _finite_array(times, "times", 1)
    x0 = _finite_array(xi0, "xi0", 1)
    if len(t) != len(x0) or len(t) < 2 or np.any(np.diff(t) <= 0) or t[0] < 0 or np.any(x0 <= 0):
        raise ValueError("times must increase and match positive xi0 values")
    nu = _positive_scalar(nu, "nu", allow_zero=True)
    lift = fit_volterra_lift(hurst, n_factors, min(t_min, max(t[1] - t[0], 1e-8)), t_max or max(float(t[-1]), 0.01), 256)
    rng = np.random.default_rng(seed)
    states = np.zeros((len(t), n_factors), dtype=float)
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        decay = np.exp(-lift.rates * dt)
        # Exact OU-noise variance for each exponential-kernel factor. This is
        # substantially more stable than applying sqrt(dt) to very fast factors.
        noise_scale = lift.weights * np.sqrt(-np.expm1(-2.0 * lift.rates * dt) / (2.0 * lift.rates))
        dW = rng.standard_normal()
        states[i] = decay * states[i - 1] + noise_scale * dW
    log_v = np.log(x0) + nu * np.sum(states, axis=1)
    variance = np.exp(np.clip(log_v, -40.0, 10.0))
    return {"times": t.copy(), "variance": variance, "log_variance": np.log(variance), "factor_states": states, "lift_rates": lift.rates.copy(), "lift_weights": lift.weights.copy()}


@dataclass(frozen=True)
class HawkesAudit:
    branching_matrix: NDArray[np.float64]
    spectral_radius: float
    stable: bool
    threshold: float


def hawkes_stability_audit(alpha: ArrayLike, beta: ArrayLike, threshold: float = 0.88) -> HawkesAudit:
    a = _finite_array(alpha, "alpha", 2)
    b = _finite_array(beta, "beta", 2)
    threshold = _positive_scalar(threshold, "threshold")
    if a.shape != b.shape or a.shape[0] != a.shape[1] or np.any(a < 0) or np.any(b <= 0):
        raise ValueError("alpha/beta must be equally sized square matrices, alpha >= 0, beta > 0")
    branch = a / b
    radius = float(np.max(np.abs(np.linalg.eigvals(branch))))
    return HawkesAudit(branch, radius, bool(radius < threshold), threshold)


class MarkedHawkesEngine:
    """Four-asset Hawkes state with exponential memory and MLOFI excitation."""
    def __init__(self, base: ArrayLike, alpha: ArrayLike, beta: ArrayLike, gamma_mlofi: ArrayLike | float = 0.0, threshold: float = 0.88):
        self.base = _finite_array(base, "base", 1)
        self.alpha = _finite_array(alpha, "alpha", 2)
        self.beta = _finite_array(beta, "beta", 2)
        if self.alpha.shape != (len(self.base), len(self.base)) or self.beta.shape != self.alpha.shape:
            raise ValueError("base length and alpha/beta dimensions must agree")
        if np.any(self.base < 0):
            raise ValueError("base intensities must be non-negative")
        self.audit = hawkes_stability_audit(self.alpha, self.beta, threshold)
        if not self.audit.stable:
            raise ValueError(f"Hawkes system is not subcritical: spectral radius {self.audit.spectral_radius:.6g} >= {threshold}")
        gm = np.asarray(gamma_mlofi, dtype=float)
        if gm.ndim == 0:
            gm = np.full(len(self.base), float(gm))
        if gm.shape != self.base.shape or not np.all(np.isfinite(gm)) or np.any(gm < 0):
            raise ValueError("gamma_mlofi must be non-negative scalar or one value per asset")
        self.gamma_mlofi = gm
        self.memory = np.zeros_like(self.alpha)

    def intensity(self, mlofi: ArrayLike | None = None) -> NDArray[np.float64]:
        ofi = np.zeros(len(self.base)) if mlofi is None else _finite_array(mlofi, "mlofi", 1)
        if ofi.shape != self.base.shape:
            raise ValueError("mlofi has wrong asset dimension")
        lam = self.base + np.sum(self.alpha * self.memory, axis=1) + self.gamma_mlofi * ofi
        return np.maximum(lam, 0.0)

    def advance(self, dt: float, event_counts: ArrayLike, mlofi: ArrayLike | None = None) -> NDArray[np.float64]:
        dt = _positive_scalar(dt, "dt", allow_zero=True)
        counts = _finite_array(event_counts, "event_counts", 1)
        if counts.shape != self.base.shape or np.any(counts < 0):
            raise ValueError("event_counts must be non-negative and match assets")
        self.memory *= np.exp(-self.beta * dt)
        # Each event of source j adds one unit to all receiving/source memory cells.
        self.memory += np.broadcast_to(counts[None, :], self.memory.shape)
        return self.intensity(mlofi)


def jump_cascade_hazard(intensities: ArrayLike, mlofi: ArrayLike, weights: ArrayLike | None = None) -> float:
    lam = _finite_array(intensities, "intensities", 1)
    ofi = _finite_array(mlofi, "mlofi", 1)
    if lam.shape != ofi.shape or np.any(lam < 0):
        raise ValueError("intensities and MLOFI must be matching; intensities non-negative")
    w = np.ones_like(lam) if weights is None else _finite_array(weights, "weights", 1)
    if w.shape != lam.shape or np.any(w < 0):
        raise ValueError("weights must be non-negative and match intensities")
    return float(np.dot(w, lam) + np.dot(w, np.abs(ofi)))


@dataclass(frozen=True)
class MOTBounds:
    lower_bound: float
    upper_bound: float
    lower_coupling: NDArray[np.float64]
    upper_coupling: NDArray[np.float64]
    lower_dual: NDArray[np.float64]
    upper_dual: NDArray[np.float64]
    marginal_residual: float
    martingale_residual: float
    lower_dual_residual: float
    upper_dual_residual: float
    lower_duality_gap: float
    upper_duality_gap: float


def discrete_martingale_bounds(
    x_support: ArrayLike,
    mu: ArrayLike,
    y_support: ArrayLike,
    nu: ArrayLike,
    payoff: ArrayLike,
    tolerance: float = 1e-8,
) -> MOTBounds:
    """Discrete MOT primal bounds and LP dual certificates.

    Variables are pi[i,j]>=0 with source/target marginals and exact rowwise
    martingale constraints sum_j y[j] pi[i,j] = x[i] mu[i].
    """
    x = _finite_array(x_support, "x_support", 1)
    mx = _finite_array(mu, "mu", 1)
    y = _finite_array(y_support, "y_support", 1)
    my = _finite_array(nu, "nu", 1)
    p = _finite_array(payoff, "payoff", 2)
    tol = _positive_scalar(tolerance, "tolerance")
    n, m = len(x), len(y)
    if not n or not m or len(mx) != n or len(my) != m or p.shape != (n, m):
        raise ValueError("support, marginals, and payoff shapes are inconsistent")
    if np.any(mx < 0) or np.any(my < 0) or not np.isclose(mx.sum(), 1.0, atol=tol) or not np.isclose(my.sum(), 1.0, atol=tol):
        raise ValueError("marginals must be non-negative probabilities summing to one")
    if not np.isclose(np.dot(x, mx), np.dot(y, my), atol=tol):
        raise ValueError("source and target marginals must have equal means")
    rows, rhs = [], []
    for i in range(n):
        row = np.zeros((n, m)); row[i, :] = 1.0
        rows.append(row.ravel()); rhs.append(mx[i])
    for j in range(m):
        row = np.zeros((n, m)); row[:, j] = 1.0
        rows.append(row.ravel()); rhs.append(my[j])
    for i in range(n):
        row = np.zeros((n, m)); row[i, :] = y
        rows.append(row.ravel()); rhs.append(x[i] * mx[i])
    Aeq, beq = np.asarray(rows), np.asarray(rhs)
    lo = linprog(p.ravel(), A_eq=Aeq, b_eq=beq, bounds=(0, None), method="highs")
    hi = linprog(-p.ravel(), A_eq=Aeq, b_eq=beq, bounds=(0, None), method="highs")
    if not lo.success or not hi.success:
        raise ValueError(f"no feasible discrete martingale coupling: lower={lo.message}; upper={hi.message}")
    pi_lo = lo.x.reshape(n, m); pi_hi = hi.x.reshape(n, m)

    def residual(pi):
        r1 = float(np.max(np.abs(pi.sum(axis=1) - mx)))
        r2 = float(np.max(np.abs(pi.sum(axis=0) - my)))
        r3 = float(np.max(np.abs(pi @ y - x * mx)))
        return max(r1, r2), r3

    marginal_resid = max(residual(pi_lo)[0], residual(pi_hi)[0])
    mart_resid = max(residual(pi_lo)[1], residual(pi_hi)[1])
    if max(marginal_resid, mart_resid) > tol:
        raise ArithmeticError(f"MOT constraint residual exceeds tolerance: {max(marginal_resid, mart_resid)}")
    # HiGHS equality duals satisfy A^T y <= c for minimization. Negating
    # duals from min(-payoff) gives an upper-payoff dual certificate.
    lower_dual = np.asarray(lo.eqlin.marginals)
    upper_dual = -np.asarray(hi.eqlin.marginals)
    lower_dual_resid = float(max(0.0, np.max(Aeq.T @ lower_dual - p.ravel())))
    upper_dual_resid = float(max(0.0, np.max(p.ravel() - Aeq.T @ upper_dual)))
    lower_gap = float(abs(np.dot(beq, lower_dual) - float(lo.fun)))
    upper_gap = float(abs(np.dot(beq, upper_dual) - float(-hi.fun)))
    if max(lower_dual_resid, upper_dual_resid, lower_gap, upper_gap) > max(tol, 1e-7):
        raise ArithmeticError("MOT primal/dual certificate failed its feasibility or duality-gap audit")
    return MOTBounds(float(lo.fun), float(-hi.fun), pi_lo, pi_hi, lower_dual, upper_dual, marginal_resid, mart_resid, lower_dual_resid, upper_dual_resid, lower_gap, upper_gap)


def detect_cross_expiry_dislocation(
    weekly_total_variance: ArrayLike,
    monthly_total_variance: ArrayLike,
    strikes: ArrayLike | None = None,
    weekly_call_prices: ArrayLike | None = None,
    monthly_call_prices: ArrayLike | None = None,
    tolerance: float = 1e-8,
) -> dict:
    weekly = _finite_array(weekly_total_variance, "weekly_total_variance", 1)
    monthly = _finite_array(monthly_total_variance, "monthly_total_variance", 1)
    tol = _positive_scalar(tolerance, "tolerance", allow_zero=True)
    if weekly.shape != monthly.shape or np.any(weekly < 0) or np.any(monthly < 0):
        raise ValueError("weekly/monthly total variance must be matching non-negative vectors")
    calendar_ok = bool(np.all(monthly + tol >= weekly))
    result = {"calendar_ok": calendar_ok, "max_calendar_defect": float(np.max(weekly - monthly)), "butterfly_ok": True}
    if strikes is not None or weekly_call_prices is not None or monthly_call_prices is not None:
        if strikes is None or weekly_call_prices is None or monthly_call_prices is None:
            raise ValueError("strikes and both expiry call-price vectors are all required")
        w = validate_butterfly_convexity(strikes, weekly_call_prices, tol)
        m = validate_butterfly_convexity(strikes, monthly_call_prices, tol)
        result["butterfly_ok"] = bool(w["convex"] and m["convex"])
        result["weekly_butterfly"] = w
        result["monthly_butterfly"] = m
    result["arbitrage_flag"] = not (result["calendar_ok"] and result["butterfly_ok"])
    return result


@dataclass(frozen=True)
class FeeBreakdown:
    stt: float
    stamp_duty: float
    exchange: float
    sebi: float
    brokerage: float
    gst: float
    total: float


def statutory_fees(buy_turnover: float, sell_turnover: float, executed_legs: int, exercise_turnover: float = 0.0) -> FeeBreakdown:
    buy = _positive_scalar(buy_turnover, "buy_turnover", allow_zero=True)
    sell = _positive_scalar(sell_turnover, "sell_turnover", allow_zero=True)
    exercise = _positive_scalar(exercise_turnover, "exercise_turnover", allow_zero=True)
    if int(executed_legs) != executed_legs or executed_legs < 0:
        raise ValueError("executed_legs must be a non-negative integer")
    # Exercise turnover is included in the specified STT base; exchange/SEBI
    # turnover fees use the executed buy/sell turnover specified by the caller.
    total_turnover = buy + sell
    stt = 0.0015 * (sell + exercise)
    stamp = 0.00003 * buy
    exchange = 0.0003553 * total_turnover
    sebi = 0.000001 * total_turnover
    brokerage = 20.0 * int(executed_legs)
    gst = 0.18 * (exchange + brokerage)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return FeeBreakdown(*(float(z) for z in (stt, stamp, exchange, sebi, brokerage, gst, total)))


def net_alpha_gate(expected_gross_alpha: float, fees: float) -> dict:
    gross = float(expected_gross_alpha); fee = float(fees)
    if not np.isfinite(gross) or not np.isfinite(fee) or fee < 0:
        raise ValueError("alpha/fees must be finite and fees non-negative")
    net = gross - fee
    return {"gross_alpha": gross, "fees": fee, "expected_net_alpha": net, "approved": bool(net > 0.0)}


def beta_posterior_fractional_kelly(
    alpha_wins: float,
    beta_losses: float,
    odds: float = 1.0,
    fractional_scale: float = 0.25,
    max_fraction: float = MAX_KELLY_FRACTION,
    confidence_level: float = 0.10,
) -> float:
    """Conservative Kelly fraction using a lower Beta-posterior quantile."""
    aw = _positive_scalar(alpha_wins, "alpha_wins")
    bl = _positive_scalar(beta_losses, "beta_losses")
    odds = _positive_scalar(odds, "odds")
    scale = _positive_scalar(fractional_scale, "fractional_scale", allow_zero=True)
    cap = float(max_fraction)
    q = float(confidence_level)
    if not 0 <= cap <= MAX_KELLY_FRACTION or not 0 < q < 0.5:
        raise ValueError("max_fraction must be in [0, 0.10] and confidence_level in (0, 0.5)")
    from scipy.stats import beta as beta_distribution
    p = float(beta_distribution.ppf(q, aw, bl))
    raw = ((p * (odds + 1.0) - 1.0) / odds) * scale
    return float(np.clip(raw, 0.0, cap))


def indifference_band(q_target: float, cost: float, sigma: float, gamma_risk: float, buy_spread_penalty: float = 0.0, sell_spread_penalty: float = 0.0, fee_drag: float = 0.0) -> dict:
    c = _positive_scalar(cost, "cost", allow_zero=True)
    s = _positive_scalar(sigma, "sigma", allow_zero=True)
    g = _positive_scalar(gamma_risk, "gamma_risk")
    vals = [float(q_target), float(buy_spread_penalty), float(sell_spread_penalty), float(fee_drag)]
    if not all(np.isfinite(vals)) or any(z < 0 for z in vals[1:]):
        raise ValueError("target finite; spread penalties and fee drag non-negative")
    base = ((3.0 * c * s * s) / (4.0 * g)) ** (1.0 / 3.0) if c * s > 0 else 0.0
    lower = vals[0] - (base + vals[1] + vals[3])
    upper = vals[0] + (base + vals[2] + vals[3])
    return {"base_width": base, "lower": lower, "upper": upper}


def inventory_action(inventory: float, band: Mapping[str, float]) -> str:
    q = float(inventory)
    if not np.isfinite(q) or not band["lower"] <= band["upper"]:
        raise ValueError("invalid inventory or band")
    if q < band["lower"]:
        return "BUY_REBALANCE"
    if q > band["upper"]:
        return "SELL_REBALANCE"
    return "NO_TRADE"


def friction_aware_advantage(gross_advantage: float, statutory_cost: float, inventory: float, inventory_variance: float, risk_lambda: float) -> float:
    vals = [float(gross_advantage), float(statutory_cost), float(inventory), float(inventory_variance), float(risk_lambda)]
    if not all(np.isfinite(vals)) or statutory_cost < 0 or inventory_variance < 0 or risk_lambda < 0:
        raise ValueError("advantage inputs invalid")
    return float(gross_advantage - statutory_cost - risk_lambda * inventory ** 2 * inventory_variance)


class ContinuousActorCritic:
    """Small NumPy two-layer actor/critic baseline for paper-research workflows."""
    def __init__(self, state_dim: int = 16, hidden_dim: int = 32, action_dim: int = 3, seed: int = 61):
        if min(state_dim, hidden_dim, action_dim) < 1:
            raise ValueError("network dimensions must be positive")
        self.state_dim, self.hidden_dim, self.action_dim = int(state_dim), int(hidden_dim), int(action_dim)
        rng = np.random.default_rng(seed)
        scale = 1.0 / sqrt(self.state_dim)
        self.aw1 = rng.normal(0, scale, (self.state_dim, self.hidden_dim)); self.ab1 = np.zeros(self.hidden_dim)
        self.aw2 = rng.normal(0, 1 / sqrt(self.hidden_dim), (self.hidden_dim, self.hidden_dim)); self.ab2 = np.zeros(self.hidden_dim)
        self.aw3 = rng.normal(0, 1 / sqrt(self.hidden_dim), (self.hidden_dim, self.action_dim)); self.ab3 = np.zeros(self.action_dim)
        self.vw1 = rng.normal(0, scale, (self.state_dim, self.hidden_dim)); self.vb1 = np.zeros(self.hidden_dim)
        self.vw2 = rng.normal(0, 1 / sqrt(self.hidden_dim), (self.hidden_dim, self.hidden_dim)); self.vb2 = np.zeros(self.hidden_dim)
        self.vw3 = rng.normal(0, 1 / sqrt(self.hidden_dim), (self.hidden_dim, 1)); self.vb3 = np.zeros(1)

    def _state(self, state):
        s = _finite_array(state, "state", 1)
        if s.size != self.state_dim:
            raise ValueError(f"state must have {self.state_dim} values")
        return s

    def action(self, state: ArrayLike) -> NDArray[np.float64]:
        s = self._state(state)
        h1 = np.tanh(s @ self.aw1 + self.ab1)
        h2 = np.tanh(h1 @ self.aw2 + self.ab2)
        return np.tanh(h2 @ self.aw3 + self.ab3)

    def value(self, state: ArrayLike) -> float:
        s = self._state(state)
        h1 = np.tanh(s @ self.vw1 + self.vb1)
        h2 = np.tanh(h1 @ self.vw2 + self.vb2)
        return float((h2 @ self.vw3 + self.vb3)[0])

    def update_value(self, state: ArrayLike, target: float, learning_rate: float = 1e-3) -> float:
        s = self._state(state); target = float(target); lr = _positive_scalar(learning_rate, "learning_rate")
        if not np.isfinite(target):
            raise ValueError("target must be finite")
        h1 = np.tanh(s @ self.vw1 + self.vb1); h2 = np.tanh(h1 @ self.vw2 + self.vb2)
        pred = float((h2 @ self.vw3 + self.vb3)[0]); err = pred - target
        grad3 = err
        old_vw3 = self.vw3.copy()
        d2 = (old_vw3[:, 0] * grad3) * (1 - h2 ** 2)
        old_vw2 = self.vw2.copy()
        d1 = (d2 @ old_vw2.T) * (1 - h1 ** 2)
        self.vw3 -= lr * h2[:, None] * grad3; self.vb3 -= lr * np.asarray([grad3])
        self.vw2 -= lr * np.outer(h1, d2); self.vb2 -= lr * d2
        self.vw1 -= lr * np.outer(s, d1); self.vb1 -= lr * d1
        return float(err ** 2)

    def update_policy(self, state: ArrayLike, target_action: ArrayLike, advantage: float, learning_rate: float = 1e-3) -> float:
        s = self._state(state); target = _finite_array(target_action, "target_action", 1)
        if target.size != self.action_dim or np.any(np.abs(target) > 1.0):
            raise ValueError("target_action must match action dimension and lie in [-1,1]")
        adv = float(advantage); lr = _positive_scalar(learning_rate, "learning_rate")
        if not np.isfinite(adv):
            raise ValueError("advantage must be finite")
        h1 = np.tanh(s @ self.aw1 + self.ab1); h2 = np.tanh(h1 @ self.aw2 + self.ab2)
        pred = np.tanh(h2 @ self.aw3 + self.ab3)
        error = pred - target
        # Advantage-weighted supervised policy surrogate; transparent baseline.
        delta3 = 2.0 * error * (1.0 - pred ** 2) * max(0.0, 1.0 + adv)
        old_aw3 = self.aw3.copy(); old_aw2 = self.aw2.copy()
        d2 = (old_aw3 @ delta3) * (1.0 - h2 ** 2)
        d1 = (old_aw2 @ d2) * (1.0 - h1 ** 2)
        self.aw3 -= lr * np.outer(h2, delta3); self.ab3 -= lr * delta3
        self.aw2 -= lr * np.outer(h1, d2); self.ab2 -= lr * d2
        self.aw1 -= lr * np.outer(s, d1); self.ab1 -= lr * d1
        return float(np.mean(error ** 2))


def build_actor_critic_state(lead_lag: float, volterra_factors: ArrayLike, hawkes_intensity: float, mlofi_levels: ArrayLike, inventory: float) -> NDArray[np.float64]:
    vf = _finite_array(volterra_factors, "volterra_factors", 1)
    ofi = _finite_array(mlofi_levels, "mlofi_levels", 1)
    vals = [float(lead_lag), float(hawkes_intensity), float(inventory)]
    if vf.size != 12 or ofi.size != 5 or not all(np.isfinite(vals)) or vals[1] < 0:
        raise ValueError("requires 12 volatility factors, five MLOFI levels, and valid scalar state values")
    # Compress five-level OFI to aggregate plus scale-normalized imbalance so total state is 1+12+1+1+1=16.
    ofi_aggregate = float(np.dot(MLOFI_WEIGHTS, ofi))
    ofi_norm = ofi_aggregate / (1.0 + float(np.sum(np.abs(ofi))))
    state = np.concatenate(([vals[0]], vf, [vals[1], ofi_norm, vals[2]]))
    if state.size != 16:
        raise RuntimeError("internal state contract error")
    return state


AGENT_ROLES = {
    "Abhi": "operator_liaison_capital_approval_binding_live_veto",
    "Alex": "microstructure_mlofi_queue_risk",
    "Emily": "rough_volatility_macro_news_iv",
    "Max": "quantitative_rms_statutory_friction_kelly",
}


def squad_consensus(manager_approved: bool, alex_risk_ok: bool, emily_volatility_ok: bool, max_net_alpha_ok: bool) -> dict:
    votes = {"Abhi": bool(manager_approved), "Alex": bool(alex_risk_ok), "Emily": bool(emily_volatility_ok), "Max": bool(max_net_alpha_ok)}
    approved = all(votes.values()) and not LIVE_ORDER_DISPATCH_ENABLED and REAL_BROKER_FILLS_LOCKED
    return {"approved_for_paper_simulation": bool(approved), "votes": votes, "live_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED}


def system_health() -> dict:
    return {
        "cycle": 61,
        "name": "RB-FSK-DOFI",
        "assets": list(ASSETS),
        "paper_only": True,
        "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
        "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED,
        "paper_ledger_epoch": PAPER_LEDGER_EPOCH,
        "initial_capital_inr": INITIAL_CAPITAL_INR,
    }
