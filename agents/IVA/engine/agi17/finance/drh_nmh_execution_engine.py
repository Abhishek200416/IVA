"""Cycle 58 DRH-NMH research engine.

Deep rough-Heston lifted characteristic function/calibration, volatility-excited
Hawkes clusters, path-signature/Wasserstein diagnostics, slippage/optimal
scheduling, actor-critic quote control, Indian fee accounting, and paper-only
safety barriers. This is an offline research baseline, not a broker adapter or
production pricing system.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import exp, gamma as gamma_fn, log, pi, sqrt
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares, linprog

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
ROUGH_HURST = 0.07
VOLTERRA_FACTORS = 12
STATE_DIMENSION = 16
ACTION_DIMENSION = 3
MAX_KELLY_FRACTION = 0.10
INR_PER_CRORE = 10_000_000.0
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0


class ValidationError(ValueError):
    """An input violates the explicit mathematical/model contract."""


class HawkesStabilityError(ValidationError):
    """The requested Hawkes kernel fails the subcriticality audit."""


def _array(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    try:
        out = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a rectangular numeric array") from exc
    if ndim is not None and out.ndim != ndim:
        raise ValidationError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(out)):
        raise ValidationError(f"{name} must contain only finite values")
    return out


def _positive(value: float, name: str, *, allow_zero: bool = False) -> float:
    value = float(value)
    if not np.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        text = "non-negative" if allow_zero else "positive"
        raise ValidationError(f"{name} must be finite and {text}")
    return value


def _integer(value: int, name: str, minimum: int = 1) -> int:
    if not isinstance(value, (int, np.integer)) or isinstance(value, bool) or value < minimum:
        raise ValidationError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _spectral_radius(matrix: np.ndarray) -> float:
    if matrix.size == 0:
        return 0.0
    return float(np.max(np.abs(np.linalg.eigvals(matrix))))


# ---------------------------------------------------------------------------
# Forward variance and logarithmically spaced 12-factor Volterra lift
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ForwardVarianceCurve:
    times: np.ndarray
    values: np.ndarray

    def __post_init__(self) -> None:
        t = _array(self.times, "times", 1)
        v = _array(self.values, "values", 1)
        if t.size < 2 or t.shape != v.shape or abs(float(t[0])) > 1e-14:
            raise ValidationError("forward curve requires aligned vectors of length >=2 starting at zero")
        if np.any(np.diff(t) <= 0) or np.any(v <= 0):
            raise ValidationError("forward-variance times must increase and variance values be positive")
        object.__setattr__(self, "times", t.copy())
        object.__setattr__(self, "values", v.copy())

    def value(self, t: float | Sequence[float]) -> float | np.ndarray:
        raw = np.asarray(t, dtype=float)
        if not np.all(np.isfinite(raw)) or np.any(raw < 0):
            raise ValidationError("curve evaluation time must be finite and non-negative")
        answer = np.interp(raw, self.times, self.values, left=self.values[0], right=self.values[-1])
        return float(answer) if raw.ndim == 0 else answer

    def total_variance(self, expiry: float) -> float:
        T = _positive(expiry, "expiry", allow_zero=True)
        if T == 0:
            return 0.0
        interior = self.times[(self.times > 0) & (self.times < T)]
        knots = np.concatenate(([0.0], interior, [T]))
        vals = np.asarray(self.value(knots), dtype=float)
        return float(np.sum(np.diff(knots) * (vals[:-1] + vals[1:]) * 0.5))


def rough_volterra_kernel(t: float | Sequence[float], hurst: float = ROUGH_HURST) -> float | np.ndarray:
    H = float(hurst)
    if not np.isfinite(H) or not 0 < H < 0.5:
        raise ValidationError("Hurst exponent must lie in (0, 0.5)")
    x = np.asarray(t, dtype=float)
    if not np.all(np.isfinite(x)) or np.any(x <= 0):
        raise ValidationError("Volterra kernel is singular/non-finite for t <= 0")
    out = x ** (H - 0.5) / gamma_fn(H + 0.5)
    return float(out) if x.ndim == 0 else out


@dataclass(frozen=True)
class ExponentialVolterraLift:
    hurst: float
    rates: np.ndarray
    weights: np.ndarray
    relative_kernel_error: float

    def __post_init__(self) -> None:
        H = float(self.hurst)
        rates = _array(self.rates, "rates", 1)
        weights = _array(self.weights, "weights", 1)
        err = float(self.relative_kernel_error)
        if not 0 < H < 0.5 or rates.shape != weights.shape or rates.size != VOLTERRA_FACTORS:
            raise ValidationError("lift requires H in (0,.5) and exactly 12 aligned factors")
        if np.any(rates <= 0) or np.any(weights < 0) or not np.isfinite(err) or err < 0:
            raise ValidationError("lift rates must be positive, weights non-negative, error finite")
        object.__setattr__(self, "rates", rates.copy())
        object.__setattr__(self, "weights", weights.copy())

    def evaluate(self, t: float | Sequence[float]) -> float | np.ndarray:
        x = np.asarray(t, dtype=float)
        if not np.all(np.isfinite(x)) or np.any(x <= 0):
            raise ValidationError("lift evaluation times must be positive")
        out = np.exp(-np.atleast_1d(x).reshape(-1, 1) * self.rates) @ self.weights
        if x.ndim == 0:
            return float(out[0])
        return out.reshape(x.shape)


def build_volterra_lift(hurst: float = ROUGH_HURST, tau_min: float = 1e-4,
                        tau_max: float = 10.0, grid_size: int = 512) -> ExponentialVolterraLift:
    """Fit K_H(t) with a non-negative 12-term log-spaced exponential lift."""
    H = float(hurst)
    if not np.isfinite(H) or not 0 < H < 0.5:
        raise ValidationError("Hurst exponent must lie in (0, 0.5)")
    lo, hi = _positive(tau_min, "tau_min"), _positive(tau_max, "tau_max")
    if lo >= hi:
        raise ValidationError("tau_min must be less than tau_max")
    n = _integer(grid_size, "grid_size", 64)
    rates = np.geomspace(1.0 / hi, 1.0 / lo, VOLTERRA_FACTORS)
    grid = np.geomspace(lo, hi, n)
    design = np.exp(-np.outer(grid, rates))
    target = np.asarray(rough_volterra_kernel(grid, H), dtype=float)
    # Projected-gradient non-negative least squares avoids an optional optimizer dependency.
    weights = np.maximum(np.linalg.lstsq(design, target, rcond=1e-12)[0], 0.0)
    gram = design.T @ design
    lipschitz = float(np.linalg.norm(gram, ord=2))
    if lipschitz > 0:
        step = 0.95 / lipschitz
        for _ in range(1200):
            residual = design @ weights - target
            candidate = np.maximum(weights - step * (design.T @ residual), 0.0)
            if np.linalg.norm(candidate - weights) <= 1e-12 * (1.0 + np.linalg.norm(weights)):
                weights = candidate
                break
            weights = candidate
    norm = float(np.linalg.norm(target))
    rel = float(np.linalg.norm(design @ weights - target) / max(norm, 1e-300))
    return ExponentialVolterraLift(H, rates, weights, rel)


# ---------------------------------------------------------------------------
# Rough-Heston lifted Riccati ODE, option pricing and surface calibration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RoughHestonParams:
    kappa: float = 1.5
    theta: float = 0.04
    vol_of_vol: float = 0.65
    rho: float = -0.70
    initial_variance: float = 0.04
    risk_free: float = 0.06
    dividend_yield: float = 0.0

    def __post_init__(self) -> None:
        for key in ("kappa", "theta", "vol_of_vol", "initial_variance"):
            _positive(getattr(self, key), key)
        for key in ("risk_free", "dividend_yield"):
            if not np.isfinite(float(getattr(self, key))):
                raise ValidationError(f"{key} must be finite")
        if not -0.999 < float(self.rho) < 0.999:
            raise ValidationError("rho must lie in (-0.999, 0.999)")


@dataclass(frozen=True)
class OptionQuote:
    asset: str
    spot: float
    strike: float
    expiry: float
    market_price: float
    option_type: str = "call"
    rate: float = 0.06
    dividend_yield: float = 0.0
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.asset not in ASSETS:
            raise ValidationError(f"asset must be one of {ASSETS}")
        for key in ("spot", "strike", "expiry", "market_price", "weight"):
            _positive(getattr(self, key), key, allow_zero=(key == "market_price"))
        if self.option_type.lower() not in ("call", "put"):
            raise ValidationError("option_type must be call or put")
        if not np.isfinite(self.rate) or not np.isfinite(self.dividend_yield):
            raise ValidationError("rate and dividend yield must be finite")
        object.__setattr__(self, "option_type", self.option_type.lower())


@dataclass(frozen=True)
class SurfaceCalibrationResult:
    asset: str
    params: RoughHestonParams
    weighted_rmse: float
    quote_count: int
    success: bool
    message: str
    evaluations: int


class RoughHestonLiftedPricer:
    """Lifted rough-Heston affine characteristic-function approximation.

    The 12 auxiliary ODE states approximate the fractional Riccati convolution:
    y'_k=-gamma_k*y_k+F(u,D), D=sum_k w_k y_k. The initial variance comes from
    the forward curve at zero if provided; the curve also modulates the mean-
    reversion level in the affine cumulant. This is a finite-factor approximation.
    """
    def __init__(self, lift: ExponentialVolterraLift, params: RoughHestonParams | None = None,
                 forward_variance: ForwardVarianceCurve | None = None):
        self.lift = lift
        self.params = params or RoughHestonParams()
        self.forward_variance = forward_variance

    def _characteristic_grid(self, u: np.ndarray, expiry: float, spot: float,
                             integration_steps: int = 100, rate_override: float | None = None,
                             dividend_override: float | None = None) -> np.ndarray:
        T = _positive(expiry, "expiry", allow_zero=True)
        S0 = _positive(spot, "spot")
        n_steps = _integer(integration_steps, "integration_steps", 4)
        uu = np.asarray(u, dtype=complex).reshape(-1)
        if not np.all(np.isfinite(uu.real)) or not np.all(np.isfinite(uu.imag)):
            raise ValidationError("characteristic arguments must be finite")
        p = self.params
        r = p.risk_free if rate_override is None else float(rate_override)
        q = p.dividend_yield if dividend_override is None else float(dividend_override)
        if not np.isfinite(r) or not np.isfinite(q):
            raise ValidationError("rate/dividend overrides must be finite")
        if T == 0:
            return np.exp(1j * uu * log(S0))
        times = np.linspace(0.0, T, n_steps + 1)
        weights, rates = self.lift.weights, self.lift.rates
        n_u = uu.size

        def ode(t: float, packed: np.ndarray) -> np.ndarray:
            y = packed.reshape(n_u, VOLTERRA_FACTORS)
            D = y @ weights
            F = -0.5 * (uu * uu + 1j * uu) + (p.rho * p.vol_of_vol * 1j * uu - p.kappa) * D + 0.5 * p.vol_of_vol**2 * D * D
            dy = -y * rates[None, :] + F[:, None]
            return dy.reshape(-1)

        y0 = np.zeros(n_u * VOLTERRA_FACTORS, dtype=complex)
        sol = solve_ivp(ode, (0.0, T), y0, method="DOP853", t_eval=times,
                        rtol=2e-6, atol=1e-8, max_step=T / max(8, n_steps // 4))
        if not sol.success or np.any(~np.isfinite(sol.y)):
            raise FloatingPointError(f"lifted Riccati ODE failed: {sol.message}")
        ys = sol.y.T.reshape(n_steps + 1, n_u, VOLTERRA_FACTORS)
        Dpath = ys @ weights
        DT = Dpath[-1]
        if self.forward_variance is None:
            mean_level = np.full(times.shape, p.theta, dtype=float)
            v0 = p.initial_variance
        else:
            mean_level = np.asarray(self.forward_variance.value(times), dtype=float)
            v0 = float(self.forward_variance.value(0.0))
        cumulant = p.kappa * np.trapezoid(Dpath * mean_level[:, None], times, axis=0)
        exponent = 1j * uu * (log(S0) + (r - q) * T) + v0 * DT + cumulant
        # Avoid silent overflow. Characteristic functions must be finite; small numerical excursions are clipped.
        exponent_real = np.clip(exponent.real, -700.0, 100.0)
        exponent = exponent_real + 1j * exponent.imag
        return np.exp(exponent)

    def characteristic_function(self, u: complex | Sequence[complex] | np.ndarray, expiry: float,
                                spot: float, integration_steps: int = 100) -> complex | np.ndarray:
        raw = np.asarray(u, dtype=complex)
        result = self._characteristic_grid(raw.reshape(-1), expiry, spot, integration_steps)
        if raw.ndim == 0:
            return complex(result[0])
        return result.reshape(raw.shape)

    def call_price(self, spot: float, strike: float, expiry: float, *, rate: float | None = None,
                   dividend_yield: float | None = None, alpha: float = 1.5,
                   frequency_count: int = 192, u_max: float = 120.0,
                   integration_steps: int = 100) -> float:
        """Carr-Madan damped Fourier call price; includes a finite frequency grid."""
        S, K, T = _positive(spot, "spot"), _positive(strike, "strike"), _positive(expiry, "expiry")
        a = _positive(alpha, "alpha")
        n = _integer(frequency_count, "frequency_count", 32)
        umax = _positive(u_max, "u_max")
        r = self.params.risk_free if rate is None else float(rate)
        q = self.params.dividend_yield if dividend_yield is None else float(dividend_yield)
        if not np.isfinite(r) or not np.isfinite(q):
            raise ValidationError("rates must be finite")
        u = np.linspace(1e-8, umax, n)
        shifted = u - 1j * (a + 1.0)
        phi = self._characteristic_grid(shifted.astype(complex), T, S, integration_steps, r, q)
        denom = (a * a + a - u * u) + 1j * (2.0 * a + 1.0) * u
        kernel = np.exp(-1j * u * log(K)) * np.exp(-r * T) * phi / denom
        value = float(np.exp(-a * log(K)) * np.trapezoid(kernel.real, u) / pi)
        # Numerical Fourier truncation can create small violations; reject material violations.
        lower = max(S * exp(-q * T) - K * exp(-r * T), 0.0)
        upper = S * exp(-q * T)
        if not np.isfinite(value):
            raise FloatingPointError("Fourier price is not finite")
        if value < lower - 0.02 * max(S, 1.0) or value > upper + 0.02 * max(S, 1.0):
            raise FloatingPointError(f"Fourier call price outside no-arbitrage bounds: {value:g}")
        return float(np.clip(value, lower, upper))

    def option_price(self, spot: float, strike: float, expiry: float, option_type: str = "call", **kwargs: Any) -> float:
        r = self.params.risk_free if kwargs.get("rate") is None else float(kwargs["rate"])
        q = self.params.dividend_yield if kwargs.get("dividend_yield") is None else float(kwargs["dividend_yield"])
        call = self.call_price(spot, strike, expiry, **kwargs)
        if option_type.lower() == "call":
            return call
        if option_type.lower() != "put":
            raise ValidationError("option_type must be call or put")
        return float(call - spot * exp(-q * expiry) + strike * exp(-r * expiry))


def calibrate_rough_heston_surface(asset: str, quotes: Sequence[OptionQuote], lift: ExponentialVolterraLift,
                                   initial_params: RoughHestonParams | None = None,
                                   max_nfev: int = 12, frequency_count: int = 96,
                                   integration_steps: int = 64, u_max: float = 60.0) -> SurfaceCalibrationResult:
    """Least-squares calibration to a supplied cross-strike/expiry option surface.

    Quotes must all belong to one of the four supported underlyings. The routine
    fits kappa, theta, vol-of-vol, and rho with bounded nonlinear least squares.
    Calibration is deterministic; quote quality and model misspecification remain
    the caller's responsibility.
    """
    if asset not in ASSETS:
        raise ValidationError(f"asset must be one of {ASSETS}")
    qts = tuple(quotes)
    if len(qts) < 4 or any(q.asset != asset for q in qts):
        raise ValidationError("calibration needs >=4 quotes, all for the selected asset")
    nfev = _integer(max_nfev, "max_nfev", 1)
    _integer(frequency_count, "frequency_count", 32)
    _integer(integration_steps, "integration_steps", 4)
    _positive(u_max, "u_max")
    base = initial_params or RoughHestonParams()
    x0 = np.array([base.kappa, base.theta, base.vol_of_vol, base.rho], dtype=float)
    lower = np.array([0.05, 1e-4, 0.03, -0.98])
    upper = np.array([12.0, 2.0, 3.0, 0.98])

    def residual(x: np.ndarray) -> np.ndarray:
        params = replace(base, kappa=float(x[0]), theta=float(x[1]), vol_of_vol=float(x[2]), rho=float(x[3]))
        errors = []
        for quote in qts:
            pricer = RoughHestonLiftedPricer(lift, params)
            model = pricer.option_price(quote.spot, quote.strike, quote.expiry, quote.option_type,
                                        rate=quote.rate, dividend_yield=quote.dividend_yield,
                                        frequency_count=frequency_count, integration_steps=integration_steps,
                                        u_max=u_max)
            errors.append((model - quote.market_price) * sqrt(quote.weight))
        return np.asarray(errors, dtype=float)

    fit = least_squares(residual, x0=np.clip(x0, lower + 1e-10, upper - 1e-10), bounds=(lower, upper),
                        max_nfev=nfev, method="trf", x_scale="jac")
    fitted = replace(base, kappa=float(fit.x[0]), theta=float(fit.x[1]),
                     vol_of_vol=float(fit.x[2]), rho=float(fit.x[3]))
    residuals = residual(fit.x)
    rms = float(np.sqrt(np.mean(residuals**2)))
    return SurfaceCalibrationResult(asset, fitted, rms, len(qts), bool(fit.success), str(fit.message), int(fit.nfev))


def calibrate_four_asset_surfaces(quotes_by_asset: Mapping[str, Sequence[OptionQuote]], lift: ExponentialVolterraLift,
                                  initial_params: RoughHestonParams | None = None, **kwargs: Any) -> dict[str, SurfaceCalibrationResult]:
    missing = [asset for asset in ASSETS if asset not in quotes_by_asset]
    if missing:
        raise ValidationError(f"surface quote mapping missing assets: {missing}")
    return {asset: calibrate_rough_heston_surface(asset, quotes_by_asset[asset], lift, initial_params, **kwargs)
            for asset in ASSETS}


def validate_surface_arbitrage(strikes: Sequence[float], expiries: Sequence[float],
                               total_variance: Sequence[Sequence[float]],
                               call_prices: Sequence[Sequence[float]] | None = None,
                               tolerance: float = 1e-8) -> dict[str, Any]:
    """Finite-grid calendar monotonicity and strike-coordinate call convexity.

    total_variance is shaped (n_expiries, n_strikes); call_prices, when given,
    must have the same shape. This is a grid diagnostic, not a continuous proof.
    """
    k = _array(strikes, "strikes", 1)
    T = _array(expiries, "expiries", 1)
    w = _array(total_variance, "total_variance", 2)
    tol = _positive(tolerance, "tolerance", allow_zero=True)
    if k.size < 3 or T.size < 1 or w.shape != (T.size, k.size):
        raise ValidationError("surface dimensions must be (n_expiries, n_strikes) with >=3 strikes")
    if np.any(k <= 0) or np.any(np.diff(k) <= 0) or np.any(T <= 0) or np.any(np.diff(T) <= 0):
        raise ValidationError("strikes/expiries must be positive and strictly increasing")
    if np.any(w < -tol):
        raise ValidationError("total variance must be non-negative")
    calendar = bool(np.all(np.diff(w, axis=0) >= -tol))
    convex = True
    min_second = float("inf")
    if call_prices is not None:
        c = _array(call_prices, "call_prices", 2)
        if c.shape != w.shape:
            raise ValidationError("call_prices must match total_variance shape")
        # Non-uniform-grid convexity via slopes of adjacent secants.
        slopes = np.diff(c, axis=1) / np.diff(k)[None, :]
        seconds = np.diff(slopes, axis=1)
        min_second = float(np.min(seconds)) if seconds.size else 0.0
        convex = bool(np.all(seconds >= -tol))
    return {"calendar_monotone": calendar, "butterfly_convex": convex,
            "min_discrete_slope_increment": min_second,
            "nonnegative_total_variance": bool(np.all(w >= -tol)),
            "admissible_on_grid": bool(calendar and convex and np.all(w >= -tol))}


# ---------------------------------------------------------------------------
# Marked multidimensional Hawkes with L^2 volatility feedback
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HawkesStabilityReport:
    branching_matrix: np.ndarray
    spectral_radius: float
    limit: float
    stable: bool


class NonMarkovianHawkesL2:
    """Four-asset marked Hawkes approximation with volatility-sensitive marks.

    For reference variance sigma2, branching entries are
    (alpha_ij + gamma_ij*sigma2_j)/beta_ij. This is a local/subcriticality audit
    for the selected variance level; it is not a global proof for unbounded marks.
    """
    def __init__(self, baseline: Sequence[float], alpha: Sequence[Sequence[float]],
                 gamma: Sequence[Sequence[float]], beta: Sequence[Sequence[float]],
                 gamma_mlofi: float = 0.1, stability_limit: float = 0.88,
                 reference_variance: float = 0.04):
        self.mu = _array(baseline, "baseline", 1)
        self.alpha = _array(alpha, "alpha", 2)
        self.gamma = _array(gamma, "gamma", 2)
        self.beta = _array(beta, "beta", 2)
        n = self.mu.size
        if n != len(ASSETS) or any(x.shape != (n, n) for x in (self.alpha, self.gamma, self.beta)):
            raise ValidationError("Hawkes arrays must be aligned 4-vectors/4x4 matrices")
        if np.any(self.mu <= 0) or np.any(self.alpha < 0) or np.any(self.gamma < 0) or np.any(self.beta <= 0):
            raise ValidationError("baseline/beta positive; alpha/gamma non-negative")
        self.gamma_mlofi = float(gamma_mlofi)
        if not np.isfinite(self.gamma_mlofi) or self.gamma_mlofi < 0:
            raise ValidationError("gamma_mlofi must be finite and non-negative")
        self.limit = _positive(stability_limit, "stability_limit")
        if self.limit > 0.88:
            raise ValidationError("stability_limit may not exceed the required 0.88")
        self.reference_variance = _positive(reference_variance, "reference_variance", allow_zero=True)
        self.memory = np.zeros((n, n), dtype=float)
        report = self.stability_report(np.full(n, self.reference_variance))
        if not report.stable:
            raise HawkesStabilityError(f"reference Hawkes branching radius {report.spectral_radius:.6g} >= {self.limit}")

    def branching_matrix(self, sigma2: Sequence[float] | None = None) -> np.ndarray:
        v = np.full(self.mu.size, self.reference_variance) if sigma2 is None else _array(sigma2, "sigma2", 1)
        if v.shape != self.mu.shape or np.any(v < 0):
            raise ValidationError("sigma2 must be a non-negative 4-vector")
        return (self.alpha + self.gamma * v[None, :]) / self.beta

    def stability_report(self, sigma2: Sequence[float] | None = None) -> HawkesStabilityReport:
        matrix = self.branching_matrix(sigma2)
        rho = _spectral_radius(matrix)
        return HawkesStabilityReport(matrix, rho, self.limit, bool(rho < self.limit))

    def assert_stable(self, sigma2: Sequence[float] | None = None) -> HawkesStabilityReport:
        report = self.stability_report(sigma2)
        if not report.stable:
            raise HawkesStabilityError(f"Hawkes branching radius {report.spectral_radius:.6g} >= {report.limit}")
        return report

    def advance(self, dt: float) -> None:
        h = _positive(dt, "dt", allow_zero=True)
        self.memory *= np.exp(-self.beta * h)

    def record_event(self, asset_index: int, mark: float = 1.0, sigma2: Sequence[float] | None = None) -> None:
        if not isinstance(asset_index, (int, np.integer)) or isinstance(asset_index, bool) or not 0 <= asset_index < len(ASSETS):
            raise ValidationError("asset_index must be an integer in [0,3]")
        mk = _positive(mark, "mark", allow_zero=True)
        v = np.full(4, self.reference_variance) if sigma2 is None else _array(sigma2, "sigma2", 1)
        if v.shape != (4,) or np.any(v < 0):
            raise ValidationError("sigma2 must be a non-negative 4-vector")
        j = int(asset_index)
        self.memory[:, j] += (self.alpha[:, j] + self.gamma[:, j] * v[j]) * mk

    def intensity(self, mlofi: Sequence[float] | None = None) -> np.ndarray:
        flow = np.zeros(4) if mlofi is None else _array(mlofi, "mlofi", 1)
        if flow.shape != (4,):
            raise ValidationError("mlofi must be a 4-vector")
        out = self.mu + np.sum(self.memory, axis=1) + self.gamma_mlofi * flow
        return np.maximum(out, 0.0)

    def simulate_step(self, dt: float, mlofi: Sequence[float] | None = None,
                      sigma2: Sequence[float] | None = None, seed: int | None = None) -> np.ndarray:
        h = _positive(dt, "dt")
        rng = np.random.default_rng(seed)
        self.advance(h)
        intensity = self.intensity(mlofi)
        counts = rng.poisson(intensity * h)
        variance = np.full(4, self.reference_variance) if sigma2 is None else _array(sigma2, "sigma2", 1)
        for j, count in enumerate(counts):
            for _ in range(int(count)):
                self.record_event(j, 1.0, variance)
        return counts


# ---------------------------------------------------------------------------
# Truncated signatures (degree <=3), geometric area and discrete W2 distance
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PathSignature:
    level1: np.ndarray
    level2: np.ndarray
    level3: np.ndarray
    dimension: int

    def flatten(self) -> np.ndarray:
        return np.concatenate(([1.0], self.level1.ravel(), self.level2.ravel(), self.level3.ravel()))

    def area_tensor(self) -> np.ndarray:
        return 0.5 * (self.level2 - self.level2.T)


def _identity_signature(dimension: int) -> PathSignature:
    d = dimension
    return PathSignature(np.zeros(d), np.zeros((d, d)), np.zeros((d, d, d)), d)


def chen_concatenate(a: PathSignature, b: PathSignature) -> PathSignature:
    if a.dimension != b.dimension:
        raise ValidationError("Chen concatenation signatures must share a dimension")
    l1 = a.level1 + b.level1
    l2 = a.level2 + np.einsum("i,j->ij", a.level1, b.level1) + b.level2
    l3 = (a.level3 + np.einsum("ij,k->ijk", a.level2, b.level1)
          + np.einsum("i,jk->ijk", a.level1, b.level2) + b.level3)
    return PathSignature(l1, l2, l3, a.dimension)


def _straight_segment_signature(increment: np.ndarray) -> PathSignature:
    dx = increment
    return PathSignature(dx.copy(), np.einsum("i,j->ij", dx, dx) / 2.0,
                         np.einsum("i,j,k->ijk", dx, dx, dx) / 6.0, dx.size)


def path_signature(path: Sequence[Sequence[float]], degree: int = 3) -> PathSignature:
    points = _array(path, "path", 2)
    if points.shape[0] < 1 or points.shape[1] < 1:
        raise ValidationError("path must have >=1 point and >=1 channel")
    if degree != 3:
        raise ValidationError("Cycle 58 signature contract currently supports degree=3")
    signature = _identity_signature(points.shape[1])
    for increment in np.diff(points, axis=0):
        signature = chen_concatenate(signature, _straight_segment_signature(increment))
    return signature


def signature_features(path: Sequence[Sequence[float]]) -> np.ndarray:
    sig = path_signature(path)
    return sig.flatten()


def wasserstein2_distance(samples_a: Sequence[Sequence[float]], samples_b: Sequence[Sequence[float]],
                          weights_a: Sequence[float] | None = None,
                          weights_b: Sequence[float] | None = None) -> float:
    """Exact discrete empirical W2 (square root of optimal squared-Euclidean cost)."""
    A, B = _array(samples_a, "samples_a", 2), _array(samples_b, "samples_b", 2)
    if A.shape[0] == 0 or B.shape[0] == 0 or A.shape[1] != B.shape[1]:
        raise ValidationError("sample matrices must be non-empty and have equal feature dimension")
    def normalize(w: Sequence[float] | None, n: int, name: str) -> np.ndarray:
        z = np.full(n, 1.0 / n) if w is None else _array(w, name, 1)
        if z.shape != (n,) or np.any(z < 0) or z.sum() <= 0:
            raise ValidationError(f"{name} must be non-negative with positive sum")
        return z / z.sum()
    wa, wb = normalize(weights_a, len(A), "weights_a"), normalize(weights_b, len(B), "weights_b")
    cost = np.sum((A[:, None, :] - B[None, :, :]) ** 2, axis=2)
    n, m = cost.shape
    # Drop one redundant marginal equality to avoid rank deficiency in the LP.
    Aeq = np.zeros((n + m - 1, n * m), dtype=float)
    beq = np.concatenate((wa, wb[:-1]))
    for i in range(n):
        Aeq[i, i * m:(i + 1) * m] = 1.0
    for j in range(m - 1):
        Aeq[n + j, j::m] = 1.0
    result = linprog(cost.ravel(), A_eq=Aeq, b_eq=beq, bounds=(0, None), method="highs")
    if not result.success or result.fun < -1e-10:
        raise FloatingPointError(f"Wasserstein transport optimization failed: {result.message}")
    return float(sqrt(max(float(result.fun), 0.0)))


def signature_wasserstein2(paths_a: Sequence[Sequence[Sequence[float]]],
                            paths_b: Sequence[Sequence[Sequence[float]]]) -> float:
    if not paths_a or not paths_b:
        raise ValidationError("path ensembles must be non-empty")
    A = np.stack([signature_features(p) for p in paths_a])
    B = np.stack([signature_features(p) for p in paths_b])
    return wasserstein2_distance(A, B)


# ---------------------------------------------------------------------------
# Indian options nonlinear slippage, transient impact and optimal scheduling
# ---------------------------------------------------------------------------
def transient_market_impact(trading_rate: float, elapsed: float, eta: float,
                            alpha: float = 1.0, kappa: float = 1.0) -> float:
    v = float(trading_rate); t = _positive(elapsed, "elapsed", allow_zero=True)
    eta = _positive(eta, "eta", allow_zero=True); a = _positive(alpha, "alpha"); k = _positive(kappa, "kappa", allow_zero=True)
    if not np.isfinite(v):
        raise ValidationError("trading_rate must be finite")
    return float(eta * np.sign(v) * abs(v) ** a * exp(-k * t))


def liquidity_replenishment_half_life(kappa: float) -> float:
    k = _positive(kappa, "kappa")
    return float(log(2.0) / k)


@dataclass(frozen=True)
class ExecutionSchedule:
    times: np.ndarray
    inventory: np.ndarray
    rates: np.ndarray
    expected_cost: float
    variance_cost: float


def optimal_trade_schedule(quantity: float, horizon: float, steps: int, impact_eta: float,
                           risk_aversion: float, return_variance: float,
                           fee_per_unit: float = 0.0) -> ExecutionSchedule:
    """Almgren-Chriss-style finite-horizon schedule with hyperbolic decay.

    Rates are signed for buy/sell direction; inventory hits zero at the horizon.
    A flat per-unit fee is added to the cost report (it does not alter trajectory
    when the same proportional fee applies at every time).
    """
    Q = float(quantity)
    if not np.isfinite(Q):
        raise ValidationError("quantity must be finite")
    T = _positive(horizon, "horizon")
    n = _integer(steps, "steps", 2)
    eta = _positive(impact_eta, "impact_eta")
    lam = _positive(risk_aversion, "risk_aversion", allow_zero=True)
    sig2 = _positive(return_variance, "return_variance", allow_zero=True)
    fee = _positive(fee_per_unit, "fee_per_unit", allow_zero=True)
    times = np.linspace(0.0, T, n + 1)
    dt = T / n
    if lam * sig2 <= 1e-18:
        inventory = Q * (1.0 - times / T)
    else:
        k = sqrt(lam * sig2 / eta)
        denominator = np.sinh(min(k * T, 300.0))
        if abs(denominator) < 1e-14:
            inventory = Q * (1.0 - times / T)
        else:
            inventory = Q * np.sinh(np.minimum(k * (T - times), 300.0)) / denominator
    inventory[0], inventory[-1] = Q, 0.0
    rates = -(np.diff(inventory) / dt)
    impact_cost = float(eta * np.sum(rates * rates) * dt)
    risk_cost = float(lam * sig2 * np.sum(inventory[:-1] ** 2) * dt)
    fee_cost = float(abs(Q) * fee)
    return ExecutionSchedule(times, inventory, rates, impact_cost + risk_cost + fee_cost, risk_cost)


# ---------------------------------------------------------------------------
# Multi-level microstructure OFI, statutory fee gate, Kelly and indifference band
# ---------------------------------------------------------------------------
def multi_level_ofi(delta_bid_volume: Sequence[float], delta_ask_volume: Sequence[float],
                    delta_bid_price: Sequence[float], delta_ask_price: Sequence[float],
                    level_weights: Sequence[float] = (5, 4, 3, 2, 1)) -> float:
    arrays = [_array(x, name, 1) for x, name in ((delta_bid_volume, "delta_bid_volume"),
             (delta_ask_volume, "delta_ask_volume"), (delta_bid_price, "delta_bid_price"),
             (delta_ask_price, "delta_ask_price"), (level_weights, "level_weights"))]
    if any(x.shape != (5,) for x in arrays):
        raise ValidationError("MLOFI inputs and weights must each have five levels")
    db, da, dpb, dpa, w = arrays
    if np.any(w < 0):
        raise ValidationError("level weights must be non-negative")
    return float(np.sum(w * (db * (dpb >= 0) - da * (dpa <= 0))))


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
    broker = _positive(brokerage_per_leg, "brokerage_per_leg", allow_zero=True)
    if not isinstance(executed_legs, (int, np.integer)) or isinstance(executed_legs, bool) or executed_legs < 0:
        raise ValidationError("executed_legs must be a non-negative integer")
    turnover = buy + sell
    stt, stamp = sell * 0.0015, buy * 0.00003
    exchange = turnover * 3553.0 / INR_PER_CRORE
    sebi = turnover * 10.0 / INR_PER_CRORE
    brokerage = int(executed_legs) * broker
    gst = 0.18 * (exchange + sebi + brokerage)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return StatutoryFees(stt, stamp, exchange, sebi, brokerage, gst, total)


def net_alpha_gate(expected_gross_alpha: float, fees: float | StatutoryFees) -> tuple[bool, float]:
    gross = float(expected_gross_alpha)
    cost = fees.total if isinstance(fees, StatutoryFees) else float(fees)
    if not np.isfinite(gross) or not np.isfinite(cost) or cost < 0:
        raise ValidationError("alpha must be finite and fee cost non-negative")
    net = gross - cost
    return bool(net > 0.0), float(net)


def beta_posterior_fractional_kelly(alpha_wins: float, beta_losses: float, payoff_odds: float,
                                    fractional_scale: float = 0.25,
                                    max_fraction: float = MAX_KELLY_FRACTION) -> float:
    a = _positive(alpha_wins, "alpha_wins"); b = _positive(beta_losses, "beta_losses")
    odds = _positive(payoff_odds, "payoff_odds")
    scale, cap = float(fractional_scale), float(max_fraction)
    if not np.isfinite(scale) or not 0 <= scale <= 1:
        raise ValidationError("fractional_scale must lie in [0,1]")
    if not np.isfinite(cap) or not 0 <= cap <= MAX_KELLY_FRACTION:
        raise ValidationError("max_fraction must lie in [0,0.10]")
    p = a / (a + b)
    full = (p * (odds + 1.0) - 1.0) / odds
    return float(np.clip(full * scale, 0.0, cap))


@dataclass(frozen=True)
class IndifferenceBand:
    lower: float
    upper: float
    base_width: float
    buy_width: float
    sell_width: float


def inventory_indifference_band(sigma: float, risk_aversion: float, friction_cost: float,
                                buy_spread_penalty: float = 0.0, sell_spread_penalty: float = 0.0,
                                fee_drag: float = 0.0, target_inventory: float = 0.0) -> IndifferenceBand:
    sig = _positive(sigma, "sigma"); gam = _positive(risk_aversion, "risk_aversion")
    c = _positive(friction_cost, "friction_cost", allow_zero=True)
    bp = _positive(buy_spread_penalty, "buy_spread_penalty", allow_zero=True)
    sp = _positive(sell_spread_penalty, "sell_spread_penalty", allow_zero=True)
    fee = _positive(fee_drag, "fee_drag", allow_zero=True)
    target = float(target_inventory)
    if not np.isfinite(target):
        raise ValidationError("target_inventory must be finite")
    base = ((3.0 * c * sig * sig) / (4.0 * gam)) ** (1.0 / 3.0) if c else 0.0
    buy, sell = base + bp + fee, base + sp + fee
    return IndifferenceBand(target - buy, target + sell, base, buy, sell)


def inventory_trade_decision(inventory: float, band: IndifferenceBand, target_inventory: float = 0.0) -> str:
    q, target = float(inventory), float(target_inventory)
    if not np.isfinite(q) or not np.isfinite(target):
        raise ValidationError("inventory and target must be finite")
    if band.lower > band.upper:
        raise ValidationError("band lower must not exceed upper")
    if band.lower <= q <= band.upper:
        return "NO_TRADE"
    return "SELL_TO_REBALANCE" if q > band.upper else "BUY_TO_REBALANCE"


def cancellation_and_toxic_sweep_hazard(hawkes_intensity: float | Sequence[float], mlofi: float,
                                       cancellation_baseline: float = 0.05,
                                       intensity_scale: float = 0.2,
                                       mlofi_scale: float = 0.01) -> dict[str, float]:
    """Combine cross-asset Hawkes activity and absolute OFI into hazard proxies.

    The separate components are proxies for cancellation risk and toxic-sweep
    risk; they are not empirically calibrated probabilities.
    """
    lam = np.asarray(hawkes_intensity, dtype=float)
    if lam.ndim > 1 or lam.size == 0 or not np.all(np.isfinite(lam)) or np.any(lam < 0):
        raise ValidationError("hawkes_intensity must be a non-empty non-negative scalar/vector")
    flow = float(mlofi)
    base = _positive(cancellation_baseline, "cancellation_baseline", allow_zero=True)
    scale_i = _positive(intensity_scale, "intensity_scale", allow_zero=True)
    scale_f = _positive(mlofi_scale, "mlofi_scale", allow_zero=True)
    if not np.isfinite(flow):
        raise ValidationError("mlofi must be finite")
    mean_intensity = float(np.mean(lam))
    cancellation = base + scale_i * mean_intensity + scale_f * abs(flow)
    toxic_sweep = scale_i * mean_intensity + scale_f * abs(flow)
    return {"mean_hawkes_intensity": mean_intensity, "cancellation_hazard": cancellation,
            "toxic_sweep_hazard": toxic_sweep, "combined_hazard": cancellation + toxic_sweep}


def build_16_state_vector(last_return: float, volterra_factors: Sequence[float],
                          hawkes_intensity: float | Sequence[float],
                          mlofi_levels: float | Sequence[float], inventory: float,
                          level_weights: Sequence[float] = (5, 4, 3, 2, 1)) -> np.ndarray:
    """Assemble the fixed 16-state contract. Top-5 MLOFI is aggregated to one scalar.

    The raw prompt's listed channels (return + 12 factors + 4 Hawkes intensities
    + 5 MLOFI levels + inventory) exceed 16 dimensions. This helper explicitly
    compresses the four Hawkes intensities to their mean and top-five MLOFI to a
    normalized weighted aggregate, retaining the stated 16-dimensional policy API.
    """
    ret, inv = float(last_return), float(inventory)
    if not np.isfinite(ret) or not np.isfinite(inv):
        raise ValidationError("return and inventory must be finite")
    factors = _array(volterra_factors, "volterra_factors", 1)
    if factors.shape != (VOLTERRA_FACTORS,):
        raise ValidationError("volterra_factors must contain exactly 12 values")
    intensity = np.asarray(hawkes_intensity, dtype=float)
    if intensity.ndim > 1 or intensity.size not in (1, 4) or not np.all(np.isfinite(intensity)) or np.any(intensity < 0):
        raise ValidationError("hawkes_intensity must be a non-negative scalar or 4-vector")
    intensity_scalar = float(np.mean(intensity))
    flow = np.asarray(mlofi_levels, dtype=float)
    if flow.ndim == 0:
        flow_scalar = float(flow)
    else:
        weights = _array(level_weights, "level_weights", 1)
        if flow.shape != (5,) or weights.shape != (5,) or np.any(weights < 0) or weights.sum() <= 0:
            raise ValidationError("MLOFI levels and weights must be five-vectors; weights non-negative and nonzero")
        if not np.all(np.isfinite(flow)):
            raise ValidationError("MLOFI levels must be finite")
        flow_scalar = float(np.dot(weights, flow) / weights.sum())
    if not np.isfinite(flow_scalar):
        raise ValidationError("MLOFI aggregate must be finite")
    state = np.concatenate(([ret], factors, [intensity_scalar, flow_scalar, inv]))
    if state.shape != (STATE_DIMENSION,):
        raise AssertionError("internal fixed-state construction error")
    return state


# ---------------------------------------------------------------------------
# 16-state continuous actor-critic and friction-aware advantage
# ---------------------------------------------------------------------------
class ContinuousActorCritic:
    """Two-hidden-layer NumPy actor/critic baseline with policy/value updates."""
    def __init__(self, state_dim: int = STATE_DIMENSION, action_dim: int = ACTION_DIMENSION,
                 hidden: tuple[int, int] = (32, 16), seed: int = 58):
        if state_dim != STATE_DIMENSION or action_dim != ACTION_DIMENSION:
            raise ValidationError("Cycle 58 requires state_dim=16 and action_dim=3")
        if len(hidden) != 2 or any(not isinstance(i, int) or i < 1 for i in hidden):
            raise ValidationError("hidden must contain two positive integer widths")
        rng = np.random.default_rng(seed)
        h1, h2 = hidden
        def init(n_in: int, n_out: int) -> np.ndarray:
            return rng.normal(0, 1.0 / sqrt(n_in), size=(n_in, n_out))
        self.aw1, self.ab1 = init(state_dim, h1), np.zeros(h1)
        self.aw2, self.ab2 = init(h1, h2), np.zeros(h2)
        self.amuw, self.amub = init(h2, action_dim), np.zeros(action_dim)
        self.asw, self.asb = init(h2, action_dim) * 0.1, np.full(action_dim, -0.7)
        self.cw1, self.cb1 = init(state_dim, h1), np.zeros(h1)
        self.cw2, self.cb2 = init(h1, h2), np.zeros(h2)
        self.cvw, self.cvb = init(h2, 1), np.zeros(1)
        self.rng = rng

    @staticmethod
    def _state(state: Sequence[float]) -> np.ndarray:
        s = _array(state, "state", 1)
        if s.shape != (STATE_DIMENSION,):
            raise ValidationError("state must be a finite 16-vector")
        return s

    def policy_parameters(self, state: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
        s = self._state(state)
        h1 = np.tanh(s @ self.aw1 + self.ab1)
        h2 = np.tanh(h1 @ self.aw2 + self.ab2)
        mu = h2 @ self.amuw + self.amub
        log_std = np.clip(h2 @ self.asw + self.asb, -5.0, 1.0)
        return mu, np.exp(log_std)

    def act(self, state: Sequence[float], deterministic: bool = True) -> np.ndarray:
        mu, std = self.policy_parameters(state)
        z = mu if deterministic else self.rng.normal(mu, std)
        return np.tanh(z)

    def value(self, state: Sequence[float]) -> float:
        s = self._state(state)
        h1 = np.tanh(s @ self.cw1 + self.cb1)
        h2 = np.tanh(h1 @ self.cw2 + self.cb2)
        return float((h2 @ self.cvw + self.cvb)[0])

    def update(self, state: Sequence[float], action: Sequence[float], target_value: float,
               advantage: float, learning_rate: float = 1e-3) -> dict[str, float]:
        s = self._state(state); a = _array(action, "action", 1)
        if a.shape != (ACTION_DIMENSION,) or np.any(np.abs(a) >= 1.0):
            raise ValidationError("update action must be a 3-vector strictly inside (-1,1)")
        target, adv, lr = float(target_value), float(advantage), _positive(learning_rate, "learning_rate")
        if not np.isfinite(target) or not np.isfinite(adv):
            raise ValidationError("target_value and advantage must be finite")
        # Actor: Gaussian score in pre-tanh action coordinates, ascent on advantage*log pi.
        h1 = np.tanh(s @ self.aw1 + self.ab1); h2 = np.tanh(h1 @ self.aw2 + self.ab2)
        mu = h2 @ self.amuw + self.amub
        logstd_raw = h2 @ self.asw + self.asb
        logstd = np.clip(logstd_raw, -5.0, 1.0); std = np.exp(logstd)
        z = np.arctanh(np.clip(a, -0.999999, 0.999999))
        score_mu = (z - mu) / (std * std)
        score_logstd = ((z - mu) ** 2 / (std * std) - 1.0) * (logstd_raw >= -5.0) * (logstd_raw <= 1.0)
        grad_mu = np.clip(adv * score_mu, -20.0, 20.0)
        grad_ls = np.clip(adv * score_logstd, -20.0, 20.0)
        grad_h2 = grad_mu @ self.amuw.T + grad_ls @ self.asw.T
        # Apply actor ascent with backprop through both tanh layers.
        self.amuw += lr * np.outer(h2, grad_mu); self.amub += lr * grad_mu
        self.asw += lr * np.outer(h2, grad_ls); self.asb += lr * grad_ls
        grad_h2 *= (1.0 - h2 * h2)
        grad_h1 = grad_h2 @ self.aw2.T
        self.aw2 += lr * np.outer(h1, grad_h2); self.ab2 += lr * grad_h2
        grad_h1 *= (1.0 - h1 * h1)
        self.aw1 += lr * np.outer(s, grad_h1); self.ab1 += lr * grad_h1
        # Critic: one-sample squared-error descent.
        v1 = np.tanh(s @ self.cw1 + self.cb1); v2 = np.tanh(v1 @ self.cw2 + self.cb2)
        value = float((v2 @ self.cvw + self.cvb)[0]); err = value - target
        dv = np.array([2.0 * err])
        gv2 = self.cvw @ dv
        old_cvw = self.cvw.copy()
        self.cvw -= lr * np.outer(v2, dv); self.cvb -= lr * dv
        gv2 = (gv2 * (1.0 - v2 * v2))
        gv1 = gv2 @ self.cw2.T
        self.cw2 -= lr * np.outer(v1, gv2); self.cb2 -= lr * gv2
        gv1 = gv1 * (1.0 - v1 * v1)
        self.cw1 -= lr * np.outer(s, gv1); self.cb1 -= lr * gv1
        return {"value_before": value, "critic_loss": float(err * err),
                "policy_score_norm": float(np.linalg.norm(grad_mu) + np.linalg.norm(grad_ls))}


def friction_aware_advantage(gross_advantage: float, statutory_fees: float,
                             inventory: float, inventory_variance: float,
                             risk_weight: float) -> float:
    g, fees, q, var, risk = map(float, (gross_advantage, statutory_fees, inventory, inventory_variance, risk_weight))
    if not np.all(np.isfinite([g, fees, q, var, risk])) or fees < 0 or var < 0 or risk < 0:
        raise ValidationError("invalid friction-aware advantage inputs")
    return float(g - fees - risk * q * q * var)


# ---------------------------------------------------------------------------
# Seeded rough-Volterra stochastic volatility with coupled Hawkes/Poisson jumps
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RoughHestonPath:
    times: np.ndarray
    spot: np.ndarray
    variance: np.ndarray
    log_variance: np.ndarray
    returns: np.ndarray
    jump_counts: np.ndarray
    hawkes_intensity: np.ndarray
    volterra_factors: np.ndarray


def simulate_rough_heston_path(spot0: float, dt: float, steps: int, forward_variance: ForwardVarianceCurve,
                               lift: ExponentialVolterraLift, *, mu: float = 0.0,
                               vol_of_vol: float = 0.8, rho: float = -0.6,
                               jump_intensity: float = 0.2, jump_mu: float = -0.01,
                               jump_sigma: float = 0.04, seed: int = 58,
                               hawkes: NonMarkovianHawkesL2 | None = None) -> RoughHestonPath:
    s0, h = _positive(spot0, "spot0"), _positive(dt, "dt")
    n = _integer(steps, "steps", 1); eta = _positive(vol_of_vol, "vol_of_vol", allow_zero=True)
    ji, js = _positive(jump_intensity, "jump_intensity", allow_zero=True), _positive(jump_sigma, "jump_sigma", allow_zero=True)
    if not -0.999 < rho < 0.999 or not np.isfinite(mu) or not np.isfinite(jump_mu):
        raise ValidationError("rho or drift/jump parameters invalid")
    rng = np.random.default_rng(seed)
    times = np.arange(n + 1, dtype=float) * h
    spot = np.empty(n + 1); variance = np.empty(n + 1); logv = np.empty(n + 1)
    returns = np.zeros(n + 1); counts = np.zeros((n, 4), dtype=int); intensities = np.zeros((n, 4))
    states = np.zeros((n + 1, VOLTERRA_FACTORS), dtype=float)
    spot[0] = s0; variance[0] = float(forward_variance.value(0.0)); logv[0] = log(variance[0])
    kernel_decay = np.exp(-lift.rates * h)
    for t in range(n):
        z_s, z_perp = rng.normal(size=2)
        dWs = sqrt(h) * z_s
        dWv = sqrt(h) * (rho * z_s + sqrt(1.0 - rho * rho) * z_perp)
        states[t + 1] = kernel_decay * states[t] + dWv
        rough_term = eta * float(np.dot(lift.weights, states[t + 1]))
        base_xi = float(forward_variance.value(times[t + 1]))
        # The centering term stabilizes variance scale in this Euler-style proxy.
        lv = log(base_xi) + rough_term - 0.5 * eta * eta * max(times[t + 1], h) ** (2.0 * lift.hurst)
        if hawkes is not None:
            hawkes.advance(h)
            local_intensity = hawkes.intensity(np.zeros(4))
            local_counts = rng.poisson(local_intensity * h)
            intensities[t] = local_intensity
            counts[t] = local_counts
            for j, c in enumerate(local_counts):
                for _ in range(int(c)):
                    hawkes.record_event(j, sigma2=np.full(4, variance[t]))
            jumps_this_step = int(local_counts[0])
        else:
            jumps_this_step = int(rng.poisson(ji * h))
            intensities[t] = ji
            counts[t, 0] = jumps_this_step
        jump_marks_v = rng.normal(-0.5 * jump_sigma * jump_sigma, jump_sigma, size=jumps_this_step).sum() if jumps_this_step else 0.0
        lv += jump_marks_v
        logv[t + 1] = float(np.clip(lv, -25.0, 12.0))
        variance[t + 1] = float(np.clip(np.exp(logv[t + 1]), 1e-10, 1e5))
        jump_marks_s = rng.normal(jump_mu, js, size=jumps_this_step).sum() if jumps_this_step else 0.0
        ret = (mu - 0.5 * variance[t]) * h + sqrt(variance[t]) * dWs + jump_marks_s
        spot[t + 1] = max(1e-10, spot[t] * exp(float(np.clip(ret, -30.0, 30.0))))
        returns[t + 1] = log(spot[t + 1] / spot[t])
    return RoughHestonPath(times, spot, variance, logv, returns, counts, intensities, states)


# ---------------------------------------------------------------------------
# Squad consensus and permanent live-order refusal
# ---------------------------------------------------------------------------
def four_agent_consensus(manager_approved: bool, queue_safe: bool, volatility_safe: bool,
                         net_alpha_positive: bool) -> dict[str, Any]:
    decisions = {"Manager Abhi": bool(manager_approved), "Alex / microstructure and queue risk": bool(queue_safe),
                 "Emily / macro intelligence and rough volatility": bool(volatility_safe),
                 "Max / RMS and statutory friction": bool(net_alpha_positive)}
    failed = [name for name, accepted in decisions.items() if not accepted]
    return {"approved": len(failed) == 0, "agents": decisions, "failed_vetoes": failed, "mode": "PAPER_ONLY"}


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    raise PermissionError("Cycle 58 is paper-only: live order dispatch is permanently disabled")


def engine_manifest_summary() -> dict[str, Any]:
    return {"cycle": 58, "engine": "DRH-NMH", "assets": list(ASSETS), "hurst": ROUGH_HURST,
            "volterra_factors": VOLTERRA_FACTORS, "state_dimension": STATE_DIMENSION,
            "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
            "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED,
            "paper_ledger_epoch": PAPER_LEDGER_EPOCH, "initial_capital_inr": INITIAL_CAPITAL_INR}
