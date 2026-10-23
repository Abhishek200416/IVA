"""Cycle 45 quantitative research engine.

Research/paper simulation only. No function in this module can dispatch a live order.
Core components: finite-horizon queue optimal stopping, stable multivariate Hawkes
intensities, a positive 12-factor rough-kernel lift, finite-grid option-surface checks,
dealer gamma-squeeze hazard, Greek-neutral convex hedging, statutory fee gates,
anti-tilt throttling, agent consensus, and a paper-only ledger.

Numerical conventions are documented in README_CYCLE45.md. In particular, the surface
calibrator is a lifted-kernel smile proxy calibrated to quotes; it is not represented
as a full characteristic-function rough-Heston pricer or a proof of global static
arbitrage freedom outside the checked quote grid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from math import erf, exp, expm1, isfinite, log, pi, sqrt
from typing import Iterable, Mapping, Sequence, Literal, Any

import numpy as np
from scipy.optimize import least_squares, minimize, nnls

ASSETS: tuple[str, ...] = ("NIFTY 50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
ASSET_INDEX: dict[str, int] = {name: i for i, name in enumerate(ASSETS)}
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
HAWKES_STABILITY_LIMIT = 0.88
DEFAULT_HURST_EXPONENT = 0.07
LIFT_FACTOR_COUNT = 12


def _finite(value: float, name: str) -> float:
    x = float(value)
    if not isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _positive(value: float, name: str, *, allow_zero: bool = False) -> float:
    x = _finite(value, name)
    if x < 0 if allow_zero else x <= 0:
        op = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be {op}")
    return x


def _matrix4(value: Sequence[Sequence[float]], name: str, *, nonnegative: bool = True) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (4, 4):
        raise ValueError(f"{name} must have shape (4, 4)")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain finite values")
    if nonnegative and np.any(arr < 0):
        raise ValueError(f"{name} must be non-negative")
    return arr


def _asset_index(asset: int | str) -> int:
    if isinstance(asset, str):
        if asset not in ASSET_INDEX:
            raise ValueError(f"unknown asset {asset!r}; expected one of {ASSETS}")
        return ASSET_INDEX[asset]
    if isinstance(asset, bool) or not isinstance(asset, (int, np.integer)) or not 0 <= int(asset) < 4:
        raise ValueError("asset index must be an integer in [0, 3]")
    return int(asset)


# ---------------------------------------------------------------------------
# 1. Queue microstructure and discrete-time Snell envelope / optimal stopping
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MicrostructureParameters:
    lambda_cancel: float = 2.0
    lambda_fill: float = 1.5
    holding_cost_per_unit: float = 0.002
    adverse_selection_per_unit: float = 0.01
    cancel_cost: float = 0.01
    peg_cost: float = 0.02
    peg_price_penalty_per_unit: float = 0.005
    rank_decay: float = 0.08
    peg_queue_ratio: float = 0.5

    def __post_init__(self) -> None:
        for name in ("lambda_cancel", "lambda_fill", "holding_cost_per_unit",
                     "adverse_selection_per_unit", "cancel_cost", "peg_cost",
                     "peg_price_penalty_per_unit", "rank_decay"):
            _positive(getattr(self, name), name, allow_zero=True)
        ratio = _finite(self.peg_queue_ratio, "peg_queue_ratio")
        if not 0.0 <= ratio <= 1.0:
            raise ValueError("peg_queue_ratio must lie in [0, 1]")
        if self.lambda_cancel + self.lambda_fill <= 0:
            raise ValueError("lambda_cancel + lambda_fill must be positive")

    @property
    def queue_depletion_hazard(self) -> float:
        """Competing queue-depletion hazard h = lambda_cancel + lambda_fill."""
        return self.lambda_cancel + self.lambda_fill


def queue_depletion_hazard(lambda_cancel: float, lambda_fill: float) -> float:
    lc = _positive(lambda_cancel, "lambda_cancel", allow_zero=True)
    lf = _positive(lambda_fill, "lambda_fill", allow_zero=True)
    if lc + lf <= 0:
        raise ValueError("at least one queue hazard must be positive")
    return lc + lf


@dataclass(frozen=True)
class OptimalStoppingResult:
    value: float
    action: str
    tau_star: float | None
    queue_revision_boundary: int | None
    policy_trace: tuple[tuple[float, int, str], ...]


def solve_queue_optimal_stopping(
    queue_ahead: int,
    edge_per_unit: float,
    order_qty: float = 1.0,
    *,
    horizon_steps: int = 20,
    dt: float = 0.1,
    params: MicrostructureParameters | None = None,
    boundary_scan_max: int | None = None,
) -> OptimalStoppingResult:
    """Solve a finite-horizon Snell envelope over WAIT, PEG, and CANCEL actions.

    A Poisson competing-risk step uses h=lambda_cancel+lambda_fill. Queue-cancel
    events improve priority by one; fill probability is attenuated by queue rank.
    PEG reprices, incurs a cost, and resets the rank to a configurable fraction.
    This is a discrete research approximation; no exchange queue is connected.
    """
    p = params or MicrostructureParameters()
    if isinstance(queue_ahead, bool) or int(queue_ahead) != queue_ahead or queue_ahead < 0:
        raise ValueError("queue_ahead must be a non-negative integer")
    edge = _finite(edge_per_unit, "edge_per_unit")
    qty = _positive(order_qty, "order_qty")
    if isinstance(horizon_steps, bool) or int(horizon_steps) != horizon_steps or horizon_steps < 1:
        raise ValueError("horizon_steps must be a positive integer")
    step_dt = _positive(dt, "dt")
    h = p.queue_depletion_hazard
    event_prob = -expm1(-h * step_dt)
    p_cancel_queue = p.lambda_cancel / h * event_prob
    decisions: dict[tuple[int, int, float], tuple[str, float]] = {}

    @lru_cache(maxsize=None)
    def bellman(step: int, ahead: int, edge_now: float) -> float:
        if step >= int(horizon_steps):
            return 0.0
        p_fill = p.lambda_fill / h * event_prob * exp(-p.rank_decay * ahead)
        p_cancel = p_cancel_queue
        # The model retains a non-negative survival probability when rank makes fill
        # less likely; queue cancellation is a competing exogenous event.
        p_survive = max(0.0, 1.0 - p_fill - p_cancel)
        fill_value = qty * (edge_now - p.adverse_selection_per_unit)
        wait_value = (p_fill * fill_value
                      + p_cancel * bellman(step + 1, max(0, ahead - 1), edge_now)
                      + p_survive * bellman(step + 1, ahead, edge_now)
                      - p.holding_cost_per_unit * qty * step_dt)
        new_ahead = min(ahead, int(round(ahead * p.peg_queue_ratio)))
        peg_edge = edge_now - p.peg_price_penalty_per_unit
        peg_value = -p.peg_cost + bellman(step + 1, new_ahead, peg_edge)
        cancel_value = -p.cancel_cost
        # WAIT wins exact ties to avoid unnecessary queue resets; CANCEL is selected
        # only if it strictly improves value over both continuing alternatives.
        candidates = (("WAIT", wait_value), ("PEG", peg_value), ("CANCEL", cancel_value))
        action, value = max(candidates, key=lambda item: item[1])
        decisions[(step, ahead, edge_now)] = (action, value)
        return value

    value = bellman(0, int(queue_ahead), edge)
    root_action = decisions[(0, int(queue_ahead), edge)][0]
    trace: list[tuple[float, int, str]] = []
    step, ahead, edge_now = 0, int(queue_ahead), edge
    tau_star: float | None = None
    for step in range(int(horizon_steps)):
        action, _ = decisions.get((step, ahead, edge_now), ("WAIT", 0.0))
        trace.append((step * step_dt, ahead, action))
        if action == "CANCEL":
            tau_star = step * step_dt
            break
        if action == "PEG":
            ahead = min(ahead, int(round(ahead * p.peg_queue_ratio)))
            edge_now -= p.peg_price_penalty_per_unit
        # WAIT advances time with the current modeled queue rank.
    scan_max = boundary_scan_max if boundary_scan_max is not None else max(20, int(queue_ahead) + 10)
    if scan_max < 0:
        raise ValueError("boundary_scan_max must be non-negative")
    cancel_queues = [q for q in range(int(scan_max) + 1)
                     if decisions.get((0, q, edge), ("", 0.0))[0] == "CANCEL"]
    # Populate scan states if memoization did not visit them on the initial path.
    for q in range(int(scan_max) + 1):
        if (0, q, edge) not in decisions:
            bellman(0, q, edge)
    cancel_queues = [q for q in range(int(scan_max) + 1)
                     if decisions.get((0, q, edge), ("", 0.0))[0] == "CANCEL"]
    return OptimalStoppingResult(float(value), root_action, tau_star,
                                 min(cancel_queues) if cancel_queues else None, tuple(trace))


# ---------------------------------------------------------------------------
# 2. Four-asset mutually-exciting Hawkes network and spillover centralities
# ---------------------------------------------------------------------------
@dataclass
class HawkesNetwork:
    mu: Sequence[float]
    alpha: Sequence[Sequence[float]]
    beta: Sequence[Sequence[float]]
    stability_limit: float = HAWKES_STABILITY_LIMIT
    gamma: np.ndarray = field(init=False, repr=False)
    spectral_radius: float = field(init=False)

    def __post_init__(self) -> None:
        self.mu = np.asarray(self.mu, dtype=float)
        if self.mu.shape != (4,) or not np.all(np.isfinite(self.mu)) or np.any(self.mu <= 0):
            raise ValueError("mu must contain four finite, strictly positive base intensities")
        self.alpha = _matrix4(self.alpha, "alpha")
        self.beta = _matrix4(self.beta, "beta")
        if np.any(self.beta <= 0):
            raise ValueError("all beta decay rates must be strictly positive")
        limit = _positive(self.stability_limit, "stability_limit")
        if limit >= 1:
            raise ValueError("stability_limit must be less than 1")
        self.gamma = self.alpha / self.beta
        self.spectral_radius = float(np.max(np.abs(np.linalg.eigvals(self.gamma))))
        if not self.spectral_radius < limit:
            raise ValueError(f"unstable Hawkes reproduction matrix: rho={self.spectral_radius:.8g} must be < {limit}")

    def intensity(self, event_history: Sequence[tuple[float, int | str]], t: float) -> np.ndarray:
        """Return lambda_i(t)=mu_i+sum_j sum_{s<t, event j} alpha_ij exp(-beta_ij(t-s))."""
        time = _finite(t, "t")
        result = self.mu.astype(float).copy()
        for event_time_raw, asset in event_history:
            event_time = _finite(event_time_raw, "event_time")
            j = _asset_index(asset)
            if event_time > time:
                raise ValueError("event history cannot contain events after requested time")
            lag = time - event_time
            result += self.alpha[:, j] * np.exp(-self.beta[:, j] * lag)
        if np.any(~np.isfinite(result)) or np.any(result <= 0):
            raise ArithmeticError("computed Hawkes intensity is not finite and positive")
        return result

    def impulse_response(self, max_order: int = 100) -> np.ndarray:
        """Fundamental response (I-Gamma)^-1; includes direct and recursive spillovers."""
        if max_order < 1:
            raise ValueError("max_order must be positive")
        identity = np.eye(4)
        return np.linalg.solve(identity - self.gamma, identity)

    def spillover_centralities(self) -> dict[str, dict[str, float]]:
        """Return source-wise total off-diagonal response and sink-wise exposure.

        Matrix convention: gamma[i,j] is excitation delivered to target i by source j.
        Hence column j describes propagation from source j; row i describes absorption
        arriving at target i.
        """
        response = self.impulse_response()
        offdiag = response - np.eye(4)
        source_spill = offdiag.sum(axis=0)
        target_absorption = response.sum(axis=1) - np.diag(response)
        return {
            "source_spillover": {ASSETS[i]: float(source_spill[i]) for i in range(4)},
            "target_absorption": {ASSETS[i]: float(target_absorption[i]) for i in range(4)},
            "source_normalized": {ASSETS[i]: float(source_spill[i] / (1.0 + source_spill[i])) for i in range(4)},
            "target_resilience": {ASSETS[i]: float(1.0 / (1.0 + target_absorption[i])) for i in range(4)},
        }


def hawkes_gamma(alpha: Sequence[Sequence[float]], beta: Sequence[Sequence[float]]) -> np.ndarray:
    a = _matrix4(alpha, "alpha")
    b = _matrix4(beta, "beta")
    if np.any(b <= 0):
        raise ValueError("beta must be strictly positive")
    return a / b


def hawkes_spectral_radius(gamma: Sequence[Sequence[float]]) -> float:
    g = _matrix4(gamma, "gamma")
    return float(np.max(np.abs(np.linalg.eigvals(g))))


# ---------------------------------------------------------------------------
# 3. Rough Heston Volterra kernel, 12-factor lift, and two-expiry surface fitting
# ---------------------------------------------------------------------------
def fractional_volterra_kernel(t: float | np.ndarray, hurst: float = DEFAULT_HURST_EXPONENT) -> float | np.ndarray:
    h = _finite(hurst, "hurst")
    if not 0.0 < h < 0.5:
        raise ValueError("rough Heston Hurst exponent must lie in (0, 0.5)")
    arr = np.asarray(t, dtype=float)
    if np.any(~np.isfinite(arr)) or np.any(arr <= 0):
        raise ValueError("kernel time t must be finite and strictly positive")
    from math import gamma as gamma_fn
    result = np.power(arr, h - 0.5) / gamma_fn(h + 0.5)
    return float(result) if result.ndim == 0 else result


@dataclass(frozen=True)
class ExponentialLift:
    hurst: float
    rates: tuple[float, ...]
    weights: tuple[float, ...]
    t_min: float
    t_max: float
    relative_rmse: float

    def __post_init__(self) -> None:
        if len(self.rates) != len(self.weights) or not self.rates:
            raise ValueError("lift rates and weights must have equal nonzero lengths")
        if any(not isfinite(x) or x <= 0 for x in self.rates):
            raise ValueError("lift rates must be finite and positive")
        if any(not isfinite(x) or x < 0 for x in self.weights):
            raise ValueError("lift weights must be finite and non-negative")
        if not 0 < self.hurst < 0.5:
            raise ValueError("hurst must lie in (0, 0.5)")

    @property
    def n_factors(self) -> int:
        return len(self.rates)

    def kernel(self, t: float | np.ndarray) -> float | np.ndarray:
        arr = np.asarray(t, dtype=float)
        if np.any(arr <= 0) or np.any(~np.isfinite(arr)):
            raise ValueError("lift evaluation times must be finite and positive")
        rates = np.asarray(self.rates)
        weights = np.asarray(self.weights)
        values = np.exp(-arr[..., None] * rates) @ weights
        return float(values) if values.ndim == 0 else values


def build_exponential_lift(
    hurst: float = DEFAULT_HURST_EXPONENT,
    n_factors: int = LIFT_FACTOR_COUNT,
    t_min: float = 1e-4,
    t_max: float = 2.0,
    fit_points: int = 500,
) -> ExponentialLift:
    h = _finite(hurst, "hurst")
    if not 0 < h < 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    if isinstance(n_factors, bool) or int(n_factors) != n_factors or n_factors < 1:
        raise ValueError("n_factors must be a positive integer")
    lo = _positive(t_min, "t_min")
    hi = _positive(t_max, "t_max")
    if hi <= lo:
        raise ValueError("t_max must exceed t_min")
    if fit_points < max(30, int(n_factors) * 3):
        raise ValueError("fit_points is too small for stable lift fitting")
    times = np.geomspace(lo, hi, int(fit_points))
    target = np.asarray(fractional_volterra_kernel(times, h))
    # Log-spaced decay rates span the reciprocal time window with margin. NNLS gives
    # positive weights, preserving a completely monotone exponential approximation.
    rates = np.geomspace(0.1 / hi, 10.0 / lo, int(n_factors))
    design = np.exp(-times[:, None] * rates[None, :])
    weights, _ = nnls(design, target, maxiter=int(n_factors) * 20)
    fitted = design @ weights
    rmse = float(np.sqrt(np.mean((fitted - target) ** 2)) / np.sqrt(np.mean(target ** 2)))
    return ExponentialLift(h, tuple(float(x) for x in rates), tuple(float(x) for x in weights), lo, hi, rmse)


def simulate_lifted_rough_heston(
    shocks: Sequence[float],
    *,
    v0: float = 0.04,
    theta: float = 0.04,
    kappa: float = 1.5,
    volvol: float = 0.35,
    dt: float = 1.0 / 252.0,
    lift: ExponentialLift | None = None,
) -> np.ndarray:
    """Euler simulation of a positive-clamped 12-factor Markovian Volterra lift.

    `shocks` are standard-normal innovations supplied by the caller, making runs
    deterministic and testable. This discretization is for research diagnostics, not
    an unbiased pricing engine; use smaller dt / convergence studies for research.
    """
    l = lift or build_exponential_lift()
    v0f = _positive(v0, "v0")
    thetaf = _positive(theta, "theta")
    kappaf = _positive(kappa, "kappa", allow_zero=True)
    volvolf = _positive(volvol, "volvol", allow_zero=True)
    step = _positive(dt, "dt")
    z = np.asarray(shocks, dtype=float)
    if z.ndim != 1 or not np.all(np.isfinite(z)):
        raise ValueError("shocks must be a one-dimensional finite sequence")
    if len(z) == 0:
        return np.array([v0f], dtype=float)
    rates = np.asarray(l.rates)
    weights = np.asarray(l.weights)
    factors = np.zeros(l.n_factors, dtype=float)
    variance = v0f
    path = [variance]
    for shock in z:
        rootv = sqrt(max(variance, 1e-12))
        common = kappaf * (thetaf - variance) * step + volvolf * rootv * sqrt(step) * float(shock)
        factors = np.exp(-rates * step) * factors + common
        variance = max(1e-10, v0f + float(np.dot(weights, factors)))
        path.append(variance)
    out = np.asarray(path)
    if np.any(~np.isfinite(out)) or np.any(out <= 0):
        raise ArithmeticError("lift simulation produced invalid variance")
    return out


@dataclass(frozen=True)
class SurfaceQuote:
    expiry: float
    log_moneyness: float
    implied_vol: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        _positive(self.expiry, "expiry")
        _finite(self.log_moneyness, "log_moneyness")
        _positive(self.implied_vol, "implied_vol")
        _positive(self.weight, "weight")


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def normalized_black_call(log_moneyness: float, total_variance: float) -> float:
    """Forward-normalized Black call with F=1 and K=exp(log_moneyness)."""
    k = _finite(log_moneyness, "log_moneyness")
    w = _positive(total_variance, "total_variance")
    sw = sqrt(w)
    d1 = (-k + 0.5 * w) / sw
    d2 = d1 - sw
    return max(0.0, _normal_cdf(d1) - exp(k) * _normal_cdf(d2))


def validate_surface(
    quotes: Sequence[SurfaceQuote],
    beta_call: float,
    beta_put: float,
    *,
    tolerance: float = 1e-8,
    raise_on_error: bool = True,
) -> dict[str, Any]:
    """Check Lee wing bounds and finite-grid monotonicity/convexity/calendar conditions.

    Wing constraints alone are not sufficient for a global arbitrage proof; this
    routine additionally checks call monotonicity/convexity on the supplied strike
    grid and total-variance calendar monotonicity at shared log-moneyness points.
    """
    reasons: list[str] = []
    bc = _finite(beta_call, "beta_call")
    bp = _finite(beta_put, "beta_put")
    if not 0 < bc <= 2:
        reasons.append("beta_call must lie in (0, 2]")
    if not 0 < bp <= 2:
        reasons.append("beta_put must lie in (0, 2]")
    tol = _positive(tolerance, "tolerance", allow_zero=True)
    if not quotes:
        reasons.append("at least one surface quote is required")
    by_expiry: dict[float, list[SurfaceQuote]] = {}
    for q in quotes:
        if not isinstance(q, SurfaceQuote):
            reasons.append("all entries must be SurfaceQuote instances")
            continue
        by_expiry.setdefault(float(q.expiry), []).append(q)
    for expiry, rows in by_expiry.items():
        rows.sort(key=lambda x: x.log_moneyness)
        if len({round(q.log_moneyness, 12) for q in rows}) != len(rows):
            reasons.append(f"duplicate strikes at expiry {expiry}")
        calls = np.array([normalized_black_call(q.log_moneyness, q.implied_vol**2 * q.expiry) for q in rows])
        strikes = np.exp([q.log_moneyness for q in rows])
        if len(rows) >= 2:
            if np.any(np.diff(calls) > tol):
                reasons.append(f"call prices are not non-increasing at expiry {expiry}")
            slopes = np.diff(calls) / np.diff(strikes)
            if len(slopes) >= 2 and np.any(np.diff(slopes) < -tol):
                reasons.append(f"call prices are not convex at expiry {expiry}")
    expiries = sorted(by_expiry)
    if len(expiries) >= 2:
        earliest = by_expiry[expiries[0]]
        for t0, t1 in zip(expiries[:-1], expiries[1:]):
            left = {round(q.log_moneyness, 12): q for q in by_expiry[t0]}
            right = {round(q.log_moneyness, 12): q for q in by_expiry[t1]}
            for key in sorted(set(left).intersection(right)):
                w0 = left[key].implied_vol**2 * t0
                w1 = right[key].implied_vol**2 * t1
                if w1 + tol < w0:
                    reasons.append(f"calendar total variance decreases at k={key} from {t0} to {t1}")
    report = {"valid": not reasons, "reasons": tuple(dict.fromkeys(reasons)),
              "expiries": tuple(expiries), "quote_count": len(quotes),
              "beta_call": bc, "beta_put": bp,
              "checks": ("Roger-Lee wing input bounds", "finite-grid call monotonicity",
                         "finite-grid butterfly convexity", "shared-strike calendar total variance")}
    if reasons and raise_on_error:
        raise ValueError("surface failed arbitrage checks: " + "; ".join(report["reasons"]))
    return report


@dataclass(frozen=True)
class RoughHestonFit:
    v0: float
    theta: float
    kappa: float
    volvol: float
    rho: float
    rms_iv_error: float
    success: bool
    evaluations: int
    hurst: float
    n_factors: int


class LiftedRoughHestonCalibrator:
    """Deterministic multi-expiry smile-proxy calibration using a positive Volterra lift.

    The model maps the fitted lift's average kernel response into a smooth log-variance
    smile, then solves a bounded nonlinear least-squares problem. This is a calibrated
    research proxy, not a full rough-Heston affine Riccati/characteristic-function
    implementation. Surface checks are run separately via validate_surface().
    """
    def __init__(self, lift: ExponentialLift | None = None):
        self.lift = lift or build_exponential_lift(DEFAULT_HURST_EXPONENT, LIFT_FACTOR_COUNT)

    def _average_kernel_response(self, expiry: float) -> float:
        rates, weights = np.asarray(self.lift.rates), np.asarray(self.lift.weights)
        response = np.sum(weights * (-np.expm1(-rates * expiry)) / rates) / expiry
        return float(max(1e-8, response))

    def predict_iv(self, quote: SurfaceQuote, params: Sequence[float]) -> float:
        v0, theta, kappa, volvol, rho = (float(x) for x in params)
        if v0 <= 0 or theta <= 0 or kappa < 0 or volvol < 0 or not -1 <= rho <= 1:
            raise ValueError("invalid rough-Heston proxy parameters")
        t, k = quote.expiry, quote.log_moneyness
        mean_variance = theta + (v0 - theta) * exp(-kappa * t)
        g = self._average_kernel_response(t)
        skew = 2.0 * rho * volvol * g / max(sqrt(mean_variance), 1e-6)
        curvature = min(8.0, (volvol * g / max(sqrt(mean_variance), 1e-6)) ** 2)
        log_variance = log(mean_variance) + skew * k + curvature * k * k
        return sqrt(exp(max(-20.0, min(4.0, log_variance))))

    def fit(self, quotes: Sequence[SurfaceQuote], *, initial: Sequence[float] = (0.04, 0.04, 1.5, 0.3, -0.5),
            max_nfev: int = 2000) -> RoughHestonFit:
        if len(quotes) < 5:
            raise ValueError("at least five quotes spanning expiries/strikes are required")
        if len({q.expiry for q in quotes}) < 2:
            raise ValueError("multi-expiry calibration requires at least two expiries")
        x0 = np.asarray(initial, dtype=float)
        if x0.shape != (5,) or not np.all(np.isfinite(x0)):
            raise ValueError("initial must be five finite parameters (v0, theta, kappa, volvol, rho)")
        target = np.array([q.implied_vol for q in quotes])
        weights = np.sqrt(np.array([q.weight for q in quotes]))
        def residual(x: np.ndarray) -> np.ndarray:
            pred = np.array([self.predict_iv(q, x) for q in quotes])
            return (pred - target) * weights
        result = least_squares(residual, x0,
                               bounds=([0.001, 0.001, 0.001, 0.0, -0.999],
                                       [2.0, 2.0, 20.0, 3.0, 0.999]),
                               max_nfev=int(max_nfev), xtol=1e-10, ftol=1e-10, gtol=1e-10)
        errs = np.array([self.predict_iv(q, result.x) - q.implied_vol for q in quotes])
        return RoughHestonFit(*(float(x) for x in result.x),
                              float(np.sqrt(np.mean(errs**2))), bool(result.success), int(result.nfev),
                              self.lift.hurst, self.lift.n_factors)


# ---------------------------------------------------------------------------
# 4. Dealer net GEX and squeeze/toxic-flow response
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GammaPosition:
    strike: float
    open_interest: float
    gamma: float
    dealer_sign: int = 1
    multiplier: float = 1.0

    def __post_init__(self) -> None:
        _positive(self.strike, "strike")
        _positive(self.open_interest, "open_interest", allow_zero=True)
        _positive(self.gamma, "gamma", allow_zero=True)
        _positive(self.multiplier, "multiplier")
        if self.dealer_sign not in (-1, 1):
            raise ValueError("dealer_sign must be -1 (short dealer gamma) or +1 (long dealer gamma)")


def map_dealer_gex(positions: Sequence[GammaPosition], spot: float) -> tuple[dict[float, float], float]:
    s = _positive(spot, "spot")
    by_strike: dict[float, float] = {}
    for position in positions:
        if not isinstance(position, GammaPosition):
            raise ValueError("positions must contain GammaPosition objects")
        exposure = position.dealer_sign * position.open_interest * position.gamma * s * position.multiplier
        by_strike[position.strike] = by_strike.get(position.strike, 0.0) + exposure
    return by_strike, float(sum(by_strike.values()))


@dataclass(frozen=True)
class GammaSqueezeDecision:
    gamma_dealer: float
    depth: float
    intensity: float
    normalized_exposure: float
    toxic_cascade: bool
    quote_retreat: bool
    quote_size_multiplier: float


@dataclass(frozen=True)
class GammaSqueezeMachine:
    lambda0: float = 0.05
    kappa: float = 2.0
    toxic_hazard_threshold: float = 0.5
    normalized_gex_threshold: float = 0.75

    def evaluate(self, gamma_dealer: float, depth: float) -> GammaSqueezeDecision:
        g = _finite(gamma_dealer, "gamma_dealer")
        d = _positive(depth, "depth")
        base = _positive(self.lambda0, "lambda0", allow_zero=True)
        kap = _positive(self.kappa, "kappa", allow_zero=True)
        threshold = _positive(self.toxic_hazard_threshold, "toxic_hazard_threshold", allow_zero=True)
        gex_threshold = _positive(self.normalized_gex_threshold, "normalized_gex_threshold", allow_zero=True)
        normalized = abs(g) / d
        exponent = kap * normalized
        if exponent > 700:
            raise OverflowError("gamma squeeze exponent exceeds safe floating-point range")
        hazard = base * exp(exponent)
        toxic = hazard >= threshold or normalized >= gex_threshold
        return GammaSqueezeDecision(g, d, hazard, normalized, toxic, toxic, 0.0 if toxic else 1.0)


# ---------------------------------------------------------------------------
# 5. Greek-neutral convex hedge via an epigraph formulation of the L1 objective
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GreekHedgeResult:
    weights: tuple[float, ...]
    delta_net: float
    gamma_net: float
    vega_net: float
    objective: float
    success: bool
    iterations: int
    message: str


def optimize_greek_neutral_hedge(
    covariance: Sequence[Sequence[float]],
    greek_matrix: Sequence[Sequence[float]],
    existing_greeks: Sequence[float],
    spreads: Sequence[float],
    *,
    lambda_cost: float = 0.01,
    lambda_spread: float = 0.01,
    neutrality_bounds: Sequence[float] = (1e-4, 1e-3, 1.0),
    max_iterations: int = 2000,
) -> GreekHedgeResult:
    """Minimize .5*w' Sigma w + lambda_cost*|w|_1 + lambda_spread*s'|w|.

    Absolute spread-weighted turnover is used (s'|w|), the convex interpretation of
    a transaction-spread penalty for signed hedge trades. Net Greek constraints are
    affine and bounded around zero. Raises ValueError if the constraints are infeasible.
    """
    sigma = np.asarray(covariance, dtype=float)
    gmat = np.asarray(greek_matrix, dtype=float)
    current = np.asarray(existing_greeks, dtype=float)
    spr = np.asarray(spreads, dtype=float)
    if sigma.ndim != 2 or sigma.shape[0] != sigma.shape[1] or sigma.shape[0] == 0:
        raise ValueError("covariance must be a nonempty square matrix")
    n = sigma.shape[0]
    if gmat.shape != (3, n) or current.shape != (3,) or spr.shape != (n,):
        raise ValueError("greek_matrix must be (3,n), existing_greeks (3,), spreads (n)")
    if not all(np.all(np.isfinite(x)) for x in (sigma, gmat, current, spr)):
        raise ValueError("hedge inputs must be finite")
    if np.any(spr < 0):
        raise ValueError("spreads must be non-negative")
    sigma = 0.5 * (sigma + sigma.T)
    eig_min = float(np.min(np.linalg.eigvalsh(sigma)))
    if eig_min < -1e-9:
        raise ValueError("covariance matrix must be positive semidefinite")
    lc = _positive(lambda_cost, "lambda_cost", allow_zero=True)
    ls = _positive(lambda_spread, "lambda_spread", allow_zero=True)
    bounds = np.asarray(neutrality_bounds, dtype=float)
    if bounds.shape != (3,) or np.any(~np.isfinite(bounds)) or np.any(bounds <= 0):
        raise ValueError("neutrality_bounds must contain three finite positive tolerances")
    # Decision vector x=(w,z), z >= |w|. Constraint rows are all linear.
    eye = np.eye(n)
    aub = np.vstack([
        np.hstack([eye, -eye]),       # w - z <= 0
        np.hstack([-eye, -eye]),      # -w - z <= 0
        np.hstack([gmat, np.zeros((3, n))]),
        np.hstack([-gmat, np.zeros((3, n))]),
    ])
    bub = np.concatenate([np.zeros(2 * n), bounds - current, bounds + current])
    c = np.concatenate([np.zeros(n), np.zeros(n)])
    feasible = __import__("scipy.optimize", fromlist=["linprog"]).linprog(
        c, A_ub=aub, b_ub=bub, bounds=[(None, None)] * n + [(0, None)] * n, method="highs")
    if not feasible.success:
        raise ValueError("Greek-neutral constraints are infeasible for supplied hedge instruments")

    def objective(x: np.ndarray) -> float:
        w, z = x[:n], x[n:]
        return float(0.5 * w @ sigma @ w + lc * np.sum(z) + ls * (spr @ z))

    def gradient(x: np.ndarray) -> np.ndarray:
        w = x[:n]
        return np.concatenate([sigma @ w, lc * np.ones(n) + ls * spr])

    constraints = ({"type": "ineq", "fun": lambda x: bub - aub @ x,
                    "jac": lambda x: -aub})
    x0 = feasible.x
    res = minimize(objective, x0, jac=gradient, constraints=constraints,
                   bounds=[(None, None)] * n + [(0, None)] * n,
                   method="SLSQP", options={"maxiter": int(max_iterations), "ftol": 1e-12, "disp": False})
    w = res.x[:n]
    net = current + gmat @ w
    if (not res.success) or np.any(np.abs(net) > bounds + 1e-7):
        raise ValueError(f"Greek-neutral optimizer failed to satisfy constraints: {res.message}; net={net}")
    return GreekHedgeResult(tuple(float(x) for x in w), float(net[0]), float(net[1]), float(net[2]),
                            float(objective(res.x)), True, int(res.nit), str(res.message))


# ---------------------------------------------------------------------------
# 6. User-specified Indian statutory schedule and strict net-alpha gate
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeeBreakdown:
    buy_turnover: float
    sell_turnover: float
    stt_sell: float
    stamp_duty_buy: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    total: float


@dataclass(frozen=True)
class IndianStatutoryFeeSchedule:
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    exchange_per_crore_inr: float = 3553.0
    sebi_per_crore_inr: float = 10.0
    gst_rate: float = 0.18
    brokerage_per_leg_inr: float = 20.0
    crore_inr: float = 10_000_000.0

    def calculate(self, buy_turnover: float, sell_turnover: float, legs: int) -> FeeBreakdown:
        buy = _positive(buy_turnover, "buy_turnover", allow_zero=True)
        sell = _positive(sell_turnover, "sell_turnover", allow_zero=True)
        if isinstance(legs, bool) or int(legs) != legs or legs < 0:
            raise ValueError("legs must be a non-negative integer")
        stt = sell * self.stt_sell_rate
        stamp = buy * self.stamp_buy_rate
        total_turnover = buy + sell
        exchange = total_turnover * self.exchange_per_crore_inr / self.crore_inr
        sebi = total_turnover * self.sebi_per_crore_inr / self.crore_inr
        brokerage = int(legs) * self.brokerage_per_leg_inr
        # GST base follows the conventional brokerage + exchange + SEBI service-fee
        # base; STT and stamp duty remain statutory levies, not GST-base components.
        gst = self.gst_rate * (brokerage + exchange + sebi)
        total = stt + stamp + exchange + sebi + brokerage + gst
        return FeeBreakdown(buy, sell, stt, stamp, exchange, sebi, brokerage, gst, total)


def calculate_indian_statutory_fees(buy_turnover: float, sell_turnover: float, legs: int,
                                    schedule: IndianStatutoryFeeSchedule | None = None) -> FeeBreakdown:
    return (schedule or IndianStatutoryFeeSchedule()).calculate(buy_turnover, sell_turnover, legs)


@dataclass(frozen=True)
class NetAlphaDecision:
    expected_gross_alpha: float
    total_fees: float
    expected_net_alpha: float
    approved: bool


def evaluate_net_alpha(expected_gross_alpha: float, buy_turnover: float, sell_turnover: float,
                       legs: int, schedule: IndianStatutoryFeeSchedule | None = None) -> NetAlphaDecision:
    gross = _finite(expected_gross_alpha, "expected_gross_alpha")
    fee = calculate_indian_statutory_fees(buy_turnover, sell_turnover, legs, schedule).total
    net = gross - fee
    return NetAlphaDecision(gross, fee, net, bool(net > 0.0))


def require_positive_net_alpha(expected_gross_alpha: float, buy_turnover: float, sell_turnover: float,
                               legs: int, schedule: IndianStatutoryFeeSchedule | None = None) -> NetAlphaDecision:
    decision = evaluate_net_alpha(expected_gross_alpha, buy_turnover, sell_turnover, legs, schedule)
    if not decision.approved:
        raise ValueError(f"net-alpha gate rejected: expected net alpha {decision.expected_net_alpha:.8f} must be > 0")
    return decision


# ---------------------------------------------------------------------------
# 7. Volatility-scaled adaptive cooldown and anti-tilt lockouts
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    reason: str
    cooldown_seconds: float
    spacing_seconds: float | None


@dataclass
class AdaptiveAntiTiltThrottle:
    consecutive_losses: int = 0
    last_trade_timestamp: float | None = None
    last_trade_size: float | None = None
    trades_today: int = 0
    session_day: str | None = None

    @staticmethod
    def cooldown(tau_base: float, theta_v: float, sigma_rough: float, sigma_base: float) -> float:
        base = _positive(tau_base, "tau_base")
        theta = _positive(theta_v, "theta_v", allow_zero=True)
        rough = _positive(sigma_rough, "sigma_rough", allow_zero=True)
        base_sigma = _positive(sigma_base, "sigma_base")
        return base * (1.0 + theta * rough / base_sigma)

    def can_trade(self, timestamp: float, size: float, sigma_rough: float, sigma_base: float, *,
                  tau_base: float = 30.0, theta_v: float = 0.5, daily_cap: int = 15,
                  session_day: str | None = None) -> ThrottleDecision:
        now = _finite(timestamp, "timestamp")
        quantity = _positive(size, "size")
        cooldown = self.cooldown(tau_base, theta_v, sigma_rough, sigma_base)
        effective_count = self.trades_today if session_day is None or session_day == self.session_day else 0
        spacing = None if self.last_trade_timestamp is None else now - self.last_trade_timestamp
        def reject(reason: str) -> ThrottleDecision:
            return ThrottleDecision(False, reason, cooldown, spacing)
        if self.consecutive_losses >= 3:
            return reject("three_consecutive_losses")
        if effective_count >= daily_cap:
            return reject("daily_trade_cap")
        if spacing is not None and spacing < 30.0:
            return reject("minimum_trade_spacing")
        if spacing is not None and spacing < cooldown:
            return reject("volatility_scaled_cooldown")
        if self.last_trade_size is not None and quantity > self.last_trade_size * 1.25:
            return reject("size_acceleration")
        return ThrottleDecision(True, "approved", cooldown, spacing)

    def record_trade(self, timestamp: float, size: float, pnl: float, *, session_day: str | None = None) -> None:
        now = _finite(timestamp, "timestamp")
        quantity = _positive(size, "size")
        profit = _finite(pnl, "pnl")
        if session_day is not None and session_day != self.session_day:
            self.trades_today = 0
            self.session_day = session_day
        self.trades_today += 1
        self.consecutive_losses = self.consecutive_losses + 1 if profit < 0 else 0
        self.last_trade_timestamp = now
        self.last_trade_size = quantity

    def manual_reset(self) -> None:
        self.consecutive_losses = 0
        self.last_trade_timestamp = None
        self.last_trade_size = None
        self.trades_today = 0
        self.session_day = None


# ---------------------------------------------------------------------------
# 8. Four-agent paper consensus, operator veto, and immutable execution boundary
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TradeIntent:
    mode: Literal["paper", "live"] = "paper"
    capital_requested: float = 0.0
    queue_risk_score: float = 0.0
    sigma_rough: float = 0.2
    expected_gross_alpha: float = 0.0
    buy_turnover: float = 0.0
    sell_turnover: float = 0.0
    legs: int = 0
    kelly_fraction: float = 0.0
    toxic_cascade: bool = False


@dataclass(frozen=True)
class AgentVote:
    agent: str
    approve: bool
    reason: str


@dataclass(frozen=True)
class SquadConsensus:
    approved_for_paper_simulation: bool
    live_veto_active: bool
    votes: tuple[AgentVote, ...]
    expected_net_alpha: float


class TradingSquad:
    """Abhi (manager/veto), Alex (L3 queue), Emily (rough vol), Max (net alpha/Kelly)."""
    MANAGER = "Manager Abhi"
    QUEUE_AGENT = "Alex"
    VOL_AGENT = "Emily"
    ALPHA_AGENT = "Max"

    def __init__(self, *, approved_capital: float = INITIAL_CAPITAL_INR,
                 max_queue_risk: float = 0.75, max_sigma_rough: float = 2.0,
                 max_kelly_fraction: float = 0.25,
                 fee_schedule: IndianStatutoryFeeSchedule | None = None):
        self.approved_capital = _positive(approved_capital, "approved_capital")
        self.max_queue_risk = _positive(max_queue_risk, "max_queue_risk")
        self.max_sigma_rough = _positive(max_sigma_rough, "max_sigma_rough")
        self.max_kelly_fraction = _positive(max_kelly_fraction, "max_kelly_fraction")
        self.fee_schedule = fee_schedule or IndianStatutoryFeeSchedule()

    @property
    def binding_live_veto(self) -> bool:
        """Read-only policy bit: operator veto cannot be disabled at runtime."""
        return True

    def evaluate(self, intent: TradeIntent) -> SquadConsensus:
        if not isinstance(intent, TradeIntent):
            raise ValueError("intent must be a TradeIntent")
        if intent.mode not in ("paper", "live"):
            raise ValueError("mode must be paper or live")
        net = evaluate_net_alpha(intent.expected_gross_alpha, intent.buy_turnover,
                                 intent.sell_turnover, intent.legs, self.fee_schedule)
        votes = (
            AgentVote(self.MANAGER, bool(intent.mode == "paper" and self.binding_live_veto
                                         and 0 <= intent.capital_requested <= self.approved_capital),
                      "paper capital within manager approval; live veto remains binding"
                      if intent.mode == "paper" else "live mode vetoed by Manager Abhi"),
            AgentVote(self.QUEUE_AGENT, bool(0 <= intent.queue_risk_score <= self.max_queue_risk),
                      "L3 queue risk acceptable" if 0 <= intent.queue_risk_score <= self.max_queue_risk else "L3 queue risk exceeds threshold"),
            AgentVote(self.VOL_AGENT, bool(0 <= intent.sigma_rough <= self.max_sigma_rough),
                      "rough volatility within configured band" if 0 <= intent.sigma_rough <= self.max_sigma_rough else "rough volatility exceeds threshold"),
            AgentVote(self.ALPHA_AGENT, bool(net.approved and 0 <= intent.kelly_fraction <= self.max_kelly_fraction),
                      "net alpha positive and Kelly fraction bounded" if net.approved and 0 <= intent.kelly_fraction <= self.max_kelly_fraction else "net alpha or Kelly sizing gate rejected"),
        )
        approved = intent.mode == "paper" and all(v.approve for v in votes) and not intent.toxic_cascade
        return SquadConsensus(approved, self.binding_live_veto, votes, net.expected_net_alpha)


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Unconditional live execution deny; deliberately raises before inspecting inputs."""
    raise PermissionError("Cycle 45 is paper-only: live order dispatch is permanently disabled")


# ---------------------------------------------------------------------------
# Paper ledger (epoch_10k only, no broker transport)
# ---------------------------------------------------------------------------
@dataclass
class PaperLedger:
    initial_capital: float = INITIAL_CAPITAL_INR
    epoch: str = PAPER_LEDGER_EPOCH
    cash: float = field(init=False)
    positions: dict[str, float] = field(default_factory=dict)
    entries: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.initial_capital = _positive(self.initial_capital, "initial_capital")
        if self.epoch != PAPER_LEDGER_EPOCH:
            raise ValueError(f"ledger epoch must be {PAPER_LEDGER_EPOCH!r}")
        self.cash = self.initial_capital

    def record_fill(self, asset: str, side: Literal["BUY", "SELL"], quantity: float, price: float,
                    fees: float = 0.0) -> dict[str, Any]:
        if asset not in ASSET_INDEX:
            raise ValueError(f"asset must be one of {ASSETS}")
        if side not in ("BUY", "SELL"):
            raise ValueError("paper side must be BUY or SELL")
        qty = _positive(quantity, "quantity")
        px = _positive(price, "price")
        fee = _positive(fees, "fees", allow_zero=True)
        notional = qty * px
        if side == "BUY":
            debit = notional + fee
            if debit > self.cash + 1e-9:
                raise ValueError("paper ledger cash limit exceeded")
            self.cash -= debit
            self.positions[asset] = self.positions.get(asset, 0.0) + qty
            cash_change = -debit
        else:
            position = self.positions.get(asset, 0.0)
            if qty > position + 1e-9:
                raise ValueError("paper ledger cannot sell more than the held position")
            self.positions[asset] = max(0.0, position - qty)
            credit = notional - fee
            self.cash += credit
            cash_change = credit
        entry = {"epoch": self.epoch, "asset": asset, "side": side, "quantity": qty,
                 "price": px, "fees": fee, "notional": notional, "cash_change": cash_change,
                 "cash_after": self.cash}
        self.entries.append(entry)
        return dict(entry)

    def snapshot(self) -> dict[str, Any]:
        return {"epoch": self.epoch, "initial_capital": self.initial_capital, "cash": self.cash,
                "positions": dict(self.positions), "entry_count": len(self.entries),
                "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED}


__all__ = [
    "ASSETS", "ASSET_INDEX", "LIVE_ORDER_DISPATCH_ENABLED", "REAL_BROKER_FILLS_LOCKED",
    "PAPER_LEDGER_EPOCH", "INITIAL_CAPITAL_INR", "HAWKES_STABILITY_LIMIT",
    "DEFAULT_HURST_EXPONENT", "LIFT_FACTOR_COUNT", "MicrostructureParameters",
    "queue_depletion_hazard", "OptimalStoppingResult", "solve_queue_optimal_stopping",
    "HawkesNetwork", "hawkes_gamma", "hawkes_spectral_radius", "fractional_volterra_kernel",
    "ExponentialLift", "build_exponential_lift", "simulate_lifted_rough_heston", "SurfaceQuote",
    "normalized_black_call", "validate_surface", "RoughHestonFit", "LiftedRoughHestonCalibrator",
    "GammaPosition", "map_dealer_gex", "GammaSqueezeDecision", "GammaSqueezeMachine",
    "GreekHedgeResult", "optimize_greek_neutral_hedge", "FeeBreakdown", "IndianStatutoryFeeSchedule",
    "calculate_indian_statutory_fees", "NetAlphaDecision", "evaluate_net_alpha",
    "require_positive_net_alpha", "ThrottleDecision", "AdaptiveAntiTiltThrottle", "TradeIntent",
    "AgentVote", "SquadConsensus", "TradingSquad", "dispatch_live_order", "PaperLedger",
]
