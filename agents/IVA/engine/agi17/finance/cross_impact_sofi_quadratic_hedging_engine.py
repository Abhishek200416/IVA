"""Cycle 36: SOFI, LOB resiliency, 2-D Hawkes, Bayesian regimes and delta-gamma hedging.

Standard-library-only, deterministic-by-seed research implementation. No live order path.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import exp, log, sqrt, isfinite, log1p
from random import Random
from threading import Thread
from typing import Any, Iterable, Sequence
import json
import time

LIVE_ORDER_DISPATCH_ENABLED = False
SAFETY_EPOCH = "epoch_10k"
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _finite(value: float, name: str) -> float:
    x = float(value)
    if not isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _vector(values: Sequence[float], name: str, *, allow_empty: bool = False) -> list[float]:
    result = [_finite(v, name) for v in values]
    if not allow_empty and not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _matrix(values: Sequence[Sequence[float]], name: str) -> list[list[float]]:
    mat = [_vector(row, name) for row in values]
    if not mat or any(len(r) != len(mat) for r in mat):
        raise ValueError(f"{name} must be a non-empty square matrix")
    return mat


def _mat_vec(a: Sequence[Sequence[float]], x: Sequence[float]) -> list[float]:
    return [sum(aij * xj for aij, xj in zip(row, x)) for row in a]


def _dot(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y):
        raise ValueError("vector length mismatch")
    return sum(a * b for a, b in zip(x, y))


def _clip(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


# ---------------------------------------------------------------------------
# SOFI jump diffusion
# ---------------------------------------------------------------------------
@dataclass
class SOFIJumpDiffusion:
    """Euler-Maruyama OU-like OFI process with compound Gaussian jumps."""
    kappa_ofi: float = 1.4
    mean_ofi: float = 0.0
    sigma_ofi: float = 0.25
    jump_mean: float = 0.0
    jump_std: float = 1.0
    jump_intensity: float = 0.2
    ofi: float = 0.0
    seed: int = 36
    rng: Random = field(init=False, repr=False)
    elapsed: float = 0.0

    def __post_init__(self) -> None:
        for n in ("kappa_ofi", "sigma_ofi", "jump_std", "jump_intensity"):
            v = _finite(getattr(self, n), n)
            if v < 0:
                raise ValueError(f"{n} must be nonnegative")
        for n in ("mean_ofi", "jump_mean", "ofi"):
            setattr(self, n, _finite(getattr(self, n), n))
        self.rng = Random(self.seed)

    def _poisson_count(self, lam: float) -> int:
        if lam <= 0:
            return 0
        if lam > 20:
            # Normal approximation avoids pathological loops for large event intensity.
            return max(0, int(round(self.rng.gauss(lam, sqrt(lam)))))
        limit = exp(-lam)
        product = 1.0
        count = 0
        while product > limit:
            count += 1
            product *= self.rng.random()
        return count - 1

    def step(self, dt: float, *, jump_intensity: float | None = None) -> float:
        dt = _finite(dt, "dt")
        if dt <= 0:
            raise ValueError("dt must be positive")
        intensity = self.jump_intensity if jump_intensity is None else _finite(jump_intensity, "jump_intensity")
        if intensity < 0:
            raise ValueError("jump_intensity must be nonnegative")
        drift = self.kappa_ofi * (self.mean_ofi - self.ofi) * dt
        diffusion = self.sigma_ofi * sqrt(dt) * self.rng.gauss(0.0, 1.0)
        n_jumps = self._poisson_count(intensity * dt)
        jumps = sum(self.rng.gauss(self.jump_mean, self.jump_std) for _ in range(n_jumps))
        self.ofi += drift + diffusion + jumps
        self.elapsed += dt
        return self.ofi

    def snapshot(self) -> dict[str, float]:
        return {"ofi": self.ofi, "kappa_ofi": self.kappa_ofi,
                "mean_ofi": self.mean_ofi, "sigma_ofi": self.sigma_ofi,
                "jump_intensity": self.jump_intensity, "elapsed": self.elapsed}


# ---------------------------------------------------------------------------
# Limit order book resiliency
# ---------------------------------------------------------------------------
@dataclass
class DepletionImpulse:
    time: float
    amplitude: float
    decay_rate: float


@dataclass
class LOBResiliencyKernel:
    """Exponential depth recovery kernel plus depletion-triggered impulses."""
    r0: float = 1.0
    beta_r: float = 0.8
    default_impulse_decay: float = 1.5
    impulses: list[DepletionImpulse] = field(default_factory=list)
    last_event_time: float = 0.0

    def __post_init__(self) -> None:
        self.r0 = _finite(self.r0, "r0")
        self.beta_r = _finite(self.beta_r, "beta_r")
        self.default_impulse_decay = _finite(self.default_impulse_decay, "default_impulse_decay")
        if self.r0 < 0 or self.beta_r <= 0 or self.default_impulse_decay <= 0:
            raise ValueError("r0 must be nonnegative and decay rates must be positive")

    @property
    def recovery_half_life(self) -> float:
        return log(2.0) / self.beta_r

    def record_depletion(self, timestamp: float, amplitude: float, decay_rate: float | None = None) -> None:
        t = _finite(timestamp, "timestamp")
        a = _finite(amplitude, "amplitude")
        rate = self.default_impulse_decay if decay_rate is None else _finite(decay_rate, "decay_rate")
        if t < self.last_event_time:
            raise ValueError("timestamps must be nondecreasing")
        if a < 0 or rate <= 0:
            raise ValueError("amplitude must be nonnegative and decay_rate positive")
        self.impulses.append(DepletionImpulse(t, a, rate))
        self.last_event_time = t

    def value(self, timestamp: float) -> float:
        t = _finite(timestamp, "timestamp")
        if t < 0:
            raise ValueError("timestamp must be nonnegative")
        baseline = self.r0 * exp(-self.beta_r * t)
        impulse_sum = 0.0
        for item in self.impulses:
            if t >= item.time:
                impulse_sum += item.amplitude * exp(-item.decay_rate * (t - item.time))
        return baseline + impulse_sum

    def replenishment_velocity(self, timestamp: float) -> float:
        """Nonnegative replenishment activity proxy; derivative magnitude of decays."""
        t = _finite(timestamp, "timestamp")
        if t < 0:
            raise ValueError("timestamp must be nonnegative")
        value = self.r0 * self.beta_r * exp(-self.beta_r * t)
        for item in self.impulses:
            if t >= item.time:
                value += item.amplitude * item.decay_rate * exp(-item.decay_rate * (t - item.time))
        return value

    def adverse_selection_hazard(self, *, ofi: float, spread_ratio: float,
                                 hawkes_intensity: float, depth_ratio: float = 1.0) -> float:
        vals = [_finite(ofi, "ofi"), _finite(spread_ratio, "spread_ratio"),
                _finite(hawkes_intensity, "hawkes_intensity"), _finite(depth_ratio, "depth_ratio")]
        if vals[1] < 0 or vals[2] < 0 or vals[3] < 0:
            raise ValueError("spread, Hawkes intensity and depth ratio must be nonnegative")
        # Logistic score: adverse directional flow, wide spread, excitation and shallow depth.
        z = 0.8 * abs(vals[0]) + 0.6 * max(0.0, vals[1] - 1.0) + 0.35 * vals[2] + 0.9 * max(0.0, 1.0 - vals[3]) - 1.4
        if z >= 0:
            return 1.0 / (1.0 + exp(-min(z, 700.0)))
        ez = exp(max(z, -700.0))
        return ez / (1.0 + ez)

    def snapshot(self, timestamp: float) -> dict[str, Any]:
        return {"recovery_half_life": self.recovery_half_life,
                "resiliency_value": self.value(timestamp),
                "replenishment_velocity": self.replenishment_velocity(timestamp),
                "impulse_count": len(self.impulses)}


# ---------------------------------------------------------------------------
# 2D mutually exciting Hawkes process with online projected SGD
# ---------------------------------------------------------------------------
def spectral_radius_2x2(matrix: Sequence[Sequence[float]]) -> float:
    m = _matrix(matrix, "matrix")
    if len(m) != 2:
        raise ValueError("matrix must be 2x2")
    a, b = m[0]
    c, d = m[1]
    disc = sqrt(max(0.0, (a - d) ** 2 + 4.0 * b * c))
    lam1 = (a + d + disc) / 2.0
    lam2 = (a + d - disc) / 2.0
    return max(abs(lam1), abs(lam2))


@dataclass
class HawkesMutualExcitation2D:
    mu_bid: float = 0.25
    mu_ask: float = 0.25
    alpha: list[list[float]] = field(default_factory=lambda: [[0.18, 0.06], [0.05, 0.16]])
    beta: float = 1.2
    learning_rate: float = 0.002
    stability_limit: float = 0.90
    epsilon: float = 1e-9
    history: list[tuple[float, int, int]] = field(default_factory=list)
    current_time: float = 0.0
    last_intensities: tuple[float, float] = (0.25, 0.25)

    def __post_init__(self) -> None:
        self.mu_bid = _finite(self.mu_bid, "mu_bid")
        self.mu_ask = _finite(self.mu_ask, "mu_ask")
        self.alpha = _matrix(self.alpha, "alpha")
        self.beta = _finite(self.beta, "beta")
        self.learning_rate = _finite(self.learning_rate, "learning_rate")
        self.stability_limit = _finite(self.stability_limit, "stability_limit")
        if self.mu_bid <= 0 or self.mu_ask <= 0 or self.beta <= 0 or self.learning_rate < 0:
            raise ValueError("baseline intensities and beta must be positive; learning_rate nonnegative")
        if not 0 < self.stability_limit < 1:
            raise ValueError("stability_limit must be in (0,1)")
        if any(x < 0 for row in self.alpha for x in row):
            raise ValueError("Hawkes alpha couplings must be nonnegative")
        self._project_stability()
        self.last_intensities = self.intensities(self.current_time)

    def branching_matrix(self) -> list[list[float]]:
        return [[v / self.beta for v in row] for row in self.alpha]

    def branching_spectral_radius(self) -> float:
        return spectral_radius_2x2(self.branching_matrix())

    def _project_stability(self) -> None:
        rho = self.branching_spectral_radius()
        if rho >= self.stability_limit:
            scale = (self.stability_limit * 0.999) / max(rho, self.epsilon)
            self.alpha = [[max(0.0, x * scale) for x in row] for row in self.alpha]

    def _traces(self, timestamp: float) -> tuple[list[float], list[float]]:
        trace = [0.0, 0.0]
        age_trace = [0.0, 0.0]
        for t, n_bid, n_ask in self.history:
            age = max(0.0, timestamp - t)
            decay = exp(-self.beta * age)
            trace[0] += n_bid * decay
            trace[1] += n_ask * decay
            age_trace[0] += n_bid * age * decay
            age_trace[1] += n_ask * age * decay
        return trace, age_trace

    def intensities(self, timestamp: float | None = None) -> tuple[float, float]:
        t = self.current_time if timestamp is None else _finite(timestamp, "timestamp")
        if t < 0:
            raise ValueError("timestamp must be nonnegative")
        tr, _ = self._traces(t)
        return (self.mu_bid + _dot(self.alpha[0], tr), self.mu_ask + _dot(self.alpha[1], tr))

    @property
    def cross_asymmetry(self) -> float:
        a12 = self.alpha[0][1]
        a21 = self.alpha[1][0]
        return (a12 - a21) / (a12 + a21 + self.epsilon)

    def observe(self, dt: float, n_bid: int = 0, n_ask: int = 0) -> tuple[float, float]:
        """Online binned point-process likelihood SGD; beta and alpha are projected positive/stable."""
        dt = _finite(dt, "dt")
        if dt <= 0:
            raise ValueError("dt must be positive")
        if isinstance(n_bid, bool) or isinstance(n_ask, bool) or int(n_bid) != n_bid or int(n_ask) != n_ask or n_bid < 0 or n_ask < 0:
            raise ValueError("event counts must be nonnegative integers")
        counts = [int(n_bid), int(n_ask)]
        old_time = self.current_time
        new_time = old_time + dt
        # Recompute traces under current beta at both interval endpoints.
        trace_start, _ = self._traces(old_time)
        trace_end, age_end = self._traces(new_time)
        mu = [self.mu_bid, self.mu_ask]
        alpha_old = [row[:] for row in self.alpha]
        f = -expm1_neg(self.beta * dt) / self.beta
        x = self.beta * dt
        # derivative of (1-exp(-beta*dt))/beta
        fprime = ((x * exp(-x)) - (1.0 - exp(-x))) / (self.beta * self.beta)
        lam = [max(self.epsilon, mu[i] + _dot(alpha_old[i], trace_end)) for i in range(2)]
        if self.learning_rate > 0:
            grad_mu = [counts[i] / lam[i] - dt for i in range(2)]
            grad_alpha = [[counts[i] * trace_end[j] / lam[i] - trace_start[j] * f for j in range(2)] for i in range(2)]
            grad_beta = 0.0
            for i in range(2):
                dlam_dbeta = -_dot(alpha_old[i], age_end)
                grad_beta += counts[i] * dlam_dbeta / lam[i]
                grad_beta -= sum(alpha_old[i][j] * trace_start[j] * fprime for j in range(2))
            lr = self.learning_rate
            self.mu_bid = max(1e-6, self.mu_bid + lr * _clip(grad_mu[0], -25.0, 25.0))
            self.mu_ask = max(1e-6, self.mu_ask + lr * _clip(grad_mu[1], -25.0, 25.0))
            self.alpha = [[max(0.0, alpha_old[i][j] + lr * _clip(grad_alpha[i][j], -25.0, 25.0)) for j in range(2)] for i in range(2)]
            self.beta = max(1e-5, self.beta + lr * _clip(grad_beta, -10.0, 10.0))
            self._project_stability()
        self.current_time = new_time
        if n_bid or n_ask:
            self.history.append((new_time, int(n_bid), int(n_ask)))
        self.last_intensities = self.intensities(new_time)
        return self.last_intensities

    def snapshot(self) -> dict[str, Any]:
        return {"mu": [self.mu_bid, self.mu_ask], "alpha": self.alpha,
                "beta": self.beta, "branching_matrix": self.branching_matrix(),
                "spectral_radius": self.branching_spectral_radius(),
                "cross_asymmetry": self.cross_asymmetry,
                "intensities": list(self.last_intensities), "events": len(self.history)}


def expm1_neg(x: float) -> float:
    """Stable 1-exp(-x), avoiding cancellation for small x."""
    if x < 1e-5:
        return x - x*x/2.0 + x*x*x/6.0 - x*x*x*x/24.0
    return 1.0 - exp(-x)


# ---------------------------------------------------------------------------
# Three-regime Bayesian sequential filter
# ---------------------------------------------------------------------------
class MicrostructureRegime(str, Enum):
    CALM_LIQUID = "CALM_LIQUID"
    HIGH_SPEED_TREND = "HIGH_SPEED_TREND"
    FLASH_ILLIQUIDITY = "FLASH_ILLIQUIDITY"


@dataclass
class BayesianMicrostructureFilter:
    """Diagonal-Gaussian HMM filter with adaptive Dirichlet transition smoothing."""
    transition: list[list[float]] = field(default_factory=lambda: [
        [0.94, 0.05, 0.01], [0.12, 0.80, 0.08], [0.08, 0.22, 0.70]])
    means: list[list[float]] = field(default_factory=lambda: [
        [0.0005, 1.0, 1.0, 0.05, 0.0],
        [0.0030, 1.8, 0.75, 0.8, 0.25],
        [0.0120, 4.0, 0.25, 2.5, 0.55]])
    stds: list[list[float]] = field(default_factory=lambda: [
        [0.0008, 0.35, 0.25, 0.2, 0.4],
        [0.0030, 0.7, 0.3, 0.8, 0.6],
        [0.0100, 1.8, 0.2, 2.0, 0.8]])
    posterior: list[float] = field(default_factory=lambda: [0.90, 0.08, 0.02])
    dirichlet_strength: float = 0.02
    z_threshold: float = 4.5
    last_z_regime: float = 0.0
    last_changepoint_probability: float = 0.02

    def __post_init__(self) -> None:
        self.transition = _matrix(self.transition, "transition")
        if len(self.transition) != 3:
            raise ValueError("transition matrix must be 3x3")
        for row in self.transition:
            if any(v < 0 for v in row) or sum(row) <= 0:
                raise ValueError("transition entries must be nonnegative with positive row sums")
            total = sum(row)
            row[:] = [v / total for v in row]
        self.means = [_vector(r, "means") for r in self.means]
        self.stds = [_vector(r, "stds") for r in self.stds]
        if len(self.means) != 3 or len(self.stds) != 3 or any(len(r) != 5 for r in self.means + self.stds):
            raise ValueError("means/stds must be 3x5")
        if any(v <= 0 for row in self.stds for v in row):
            raise ValueError("standard deviations must be positive")
        self.posterior = _vector(self.posterior, "posterior")
        if len(self.posterior) != 3 or any(v < 0 for v in self.posterior) or sum(self.posterior) <= 0:
            raise ValueError("posterior must contain three nonnegative probabilities")
        p_total = sum(self.posterior)
        self.posterior = [v / p_total for v in self.posterior]
        self.dirichlet_strength = _finite(self.dirichlet_strength, "dirichlet_strength")
        self.z_threshold = _finite(self.z_threshold, "z_threshold")
        if self.dirichlet_strength < 0 or self.z_threshold <= 0:
            raise ValueError("invalid smoothing strength or z threshold")

    def _log_likelihood(self, x: Sequence[float], state: int) -> float:
        total = 0.0
        for j in range(5):
            sd = self.stds[state][j]
            z = (x[j] - self.means[state][j]) / sd
            total += -0.5 * z*z - log(sd) - 0.5 * log(2.0 * 3.141592653589793)
        return total

    def update(self, observation: Sequence[float]) -> dict[str, Any]:
        x = _vector(observation, "observation")
        if len(x) != 5:
            raise ValueError("observation must have five features")
        if x[0] < 0 or x[1] < 0 or x[2] < 0 or x[3] < 0:
            raise ValueError("absolute return, spread ratio, depth ratio and sweep count must be nonnegative")
        predicted = [sum(self.posterior[i] * self.transition[i][j] for i in range(3)) for j in range(3)]
        logw = [log(max(1e-300, predicted[j])) + self._log_likelihood(x, j) for j in range(3)]
        maxlog = max(logw)
        unnormalized = [exp(v - maxlog) for v in logw]
        denom = sum(unnormalized)
        posterior = [v / denom for v in unnormalized]
        # Adaptive Dirichlet smoothing: tiny floor preserves recoverability of rare regimes.
        floor = self.dirichlet_strength / 3.0
        posterior = [(p + floor) / (1.0 + self.dirichlet_strength) for p in posterior]
        self.posterior = posterior
        calm_mean, calm_std = self.means[0], self.stds[0]
        z_components = [abs((x[j] - calm_mean[j]) / calm_std[j]) for j in range(5)]
        self.last_z_regime = sqrt(sum(v*v for v in z_components) / 5.0)
        self.last_changepoint_probability = _clip(1.0 - self.posterior[0], 0.0, 1.0)
        winner = max(range(3), key=lambda i: self.posterior[i])
        return {"regime": list(MicrostructureRegime)[winner].value,
                "posterior": self.posterior[:], "z_regime": self.last_z_regime,
                "changepoint_probability": self.last_changepoint_probability,
                "extreme_dislocation": self.last_z_regime > self.z_threshold}

    def snapshot(self) -> dict[str, Any]:
        idx = max(range(3), key=lambda i: self.posterior[i])
        return {"regime": list(MicrostructureRegime)[idx].value,
                "posterior": self.posterior[:], "z_regime": self.last_z_regime,
                "changepoint_probability": self.last_changepoint_probability,
                "extreme_dislocation": self.last_z_regime > self.z_threshold}


# ---------------------------------------------------------------------------
# Matrix / PSD utilities
# ---------------------------------------------------------------------------
def jacobi_eigenvalues(matrix: Sequence[Sequence[float]], *, tolerance: float = 1e-12,
                       max_sweeps: int = 100) -> list[float]:
    """Eigenvalues of real symmetric matrix via Jacobi rotations (small dimensions)."""
    a = _matrix(matrix, "matrix")
    n = len(a)
    if any(abs(a[i][j] - a[j][i]) > 1e-9 for i in range(n) for j in range(n)):
        raise ValueError("matrix must be symmetric")
    for i in range(n):
        for j in range(n):
            a[i][j] = 0.5 * (a[i][j] + a[j][i])
    for _ in range(max_sweeps):
        p, q = 0, 0
        max_val = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > max_val:
                    max_val = abs(a[i][j]); p, q = i, j
        if max_val <= tolerance:
            break
        tau = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
        t = (1.0 if tau >= 0 else -1.0) / (abs(tau) + sqrt(1.0 + tau*tau))
        c = 1.0 / sqrt(1.0 + t*t)
        s = t * c
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        a[p][p] = app - t * apq
        a[q][q] = aqq + t * apq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            if k not in (p, q):
                akp, akq = a[k][p], a[k][q]
                a[k][p] = a[p][k] = c * akp - s * akq
                a[k][q] = a[q][k] = s * akp + c * akq
    return [a[i][i] for i in range(n)]


def validate_psd(matrix: Sequence[Sequence[float]], name: str = "matrix", tol: float = 1e-8) -> list[list[float]]:
    m = _matrix(matrix, name)
    if any(abs(m[i][j] - m[j][i]) > 1e-9 for i in range(len(m)) for j in range(len(m))):
        raise ValueError(f"{name} must be symmetric")
    if min(jacobi_eigenvalues(m)) < -tol:
        raise ValueError(f"{name} must be positive semidefinite")
    return m


# ---------------------------------------------------------------------------
# Statutory fees and profitability hurdle
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OptionLeg:
    premium: float
    quantity: float
    side: str
    symbol: str = "OPTION"

    def __post_init__(self) -> None:
        premium = _finite(self.premium, "premium")
        quantity = _finite(self.quantity, "quantity")
        if premium < 0 or quantity < 0:
            raise ValueError("premium and quantity must be nonnegative")
        object.__setattr__(self, "premium", premium)
        object.__setattr__(self, "quantity", quantity)
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

    @property
    def turnover(self) -> float:
        return self.premium * self.quantity


@dataclass(frozen=True)
class FeeBreakdown:
    premium_turnover: float
    buy_turnover: float
    sell_turnover: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    half_spread_slippage: float
    cross_impact_hurdle: float
    total_statutory: float
    total_friction: float


@dataclass(frozen=True)
class StatutoryCostConfig:
    options_sell_stt: float = 0.0015
    exchange_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    stamp_buy_rate: float = 0.00003
    brokerage_per_leg: float = 0.0

    def __post_init__(self) -> None:
        for name in ("options_sell_stt", "exchange_per_crore", "sebi_per_crore", "gst_rate", "stamp_buy_rate", "brokerage_per_leg"):
            value = _finite(getattr(self, name), name)
            if value < 0:
                raise ValueError(f"{name} must be nonnegative")
            object.__setattr__(self, name, value)


@dataclass
class StatutoryCostCalculator:
    config: StatutoryCostConfig = field(default_factory=StatutoryCostConfig)

    def calculate(self, legs: Sequence[OptionLeg], *, half_spread_per_unit: float = 0.0,
                  cross_impact_hurdle: float = 0.0) -> FeeBreakdown:
        if not legs:
            raise ValueError("at least one leg is required")
        half_spread_per_unit = _finite(half_spread_per_unit, "half_spread_per_unit")
        cross_impact_hurdle = _finite(cross_impact_hurdle, "cross_impact_hurdle")
        if half_spread_per_unit < 0 or cross_impact_hurdle < 0:
            raise ValueError("slippage and impact must be nonnegative")
        buy_turnover = sum(l.turnover for l in legs if l.side == "BUY")
        sell_turnover = sum(l.turnover for l in legs if l.side == "SELL")
        total_turnover = buy_turnover + sell_turnover
        c = self.config
        stt = sell_turnover * c.options_sell_stt
        exchange = total_turnover * c.exchange_per_crore / 10_000_000.0
        sebi = total_turnover * c.sebi_per_crore / 10_000_000.0
        stamp = buy_turnover * c.stamp_buy_rate
        brokerage = len(legs) * c.brokerage_per_leg
        gst = (exchange + sebi + brokerage) * c.gst_rate
        spread = sum(l.quantity for l in legs) * half_spread_per_unit
        statutory = stt + exchange + sebi + gst + stamp + brokerage
        friction = statutory + spread + cross_impact_hurdle
        return FeeBreakdown(total_turnover, buy_turnover, sell_turnover, stt,
                            exchange, sebi, gst, stamp, brokerage, spread,
                            cross_impact_hurdle, statutory, friction)

    @staticmethod
    def profitable(gross_alpha: float, fees: FeeBreakdown) -> bool:
        return _finite(gross_alpha, "gross_alpha") > fees.total_friction


# ---------------------------------------------------------------------------
# Anti-overtrading
# ---------------------------------------------------------------------------
@dataclass
class AntiOvertradingThrottler:
    reward_alpha: float = 2.0
    cost_per_trade: float = 0.4
    risk_per_trade: float = 0.25
    max_daily_trades: int = 100
    loss_streak_limit: int = 3
    revenge_ratio_limit: float = 1.25
    min_fill_interval: float = 30.0
    cooldown_seconds: float = 900.0
    trades_today: int = 0
    consecutive_losses: int = 0
    lockout_until: float = 0.0
    last_fill_time: float | None = None
    last_fill_size: float | None = None
    lockout_reason: str | None = None

    def __post_init__(self) -> None:
        self.reward_alpha = _finite(self.reward_alpha, "reward_alpha")
        self.cost_per_trade = _finite(self.cost_per_trade, "cost_per_trade")
        self.risk_per_trade = _finite(self.risk_per_trade, "risk_per_trade")
        if self.reward_alpha < 0 or self.cost_per_trade < 0 or self.risk_per_trade < 0:
            raise ValueError("alpha/cost/risk must be nonnegative")
        if isinstance(self.max_daily_trades, bool) or int(self.max_daily_trades) != self.max_daily_trades or self.max_daily_trades < 0:
            raise ValueError("max_daily_trades must be nonnegative integer")
        if isinstance(self.loss_streak_limit, bool) or int(self.loss_streak_limit) != self.loss_streak_limit or self.loss_streak_limit < 1 or self.revenge_ratio_limit <= 0 or self.min_fill_interval < 0 or self.cooldown_seconds < 0:
            raise ValueError("invalid throttler limits")

    @property
    def optimal_daily_cap(self) -> int:
        if self.risk_per_trade == 0:
            return self.max_daily_trades if self.reward_alpha > self.cost_per_trade else 0
        raw = (self.reward_alpha - self.cost_per_trade) / self.risk_per_trade
        # Python round uses banker's rounding. Specify half-up to make count predictable.
        return max(0, int(raw + 0.5))

    def can_enter(self, now: float) -> bool:
        t = _finite(now, "now")
        return t >= self.lockout_until and self.trades_today < min(self.max_daily_trades, self.optimal_daily_cap)

    def register_fill(self, *, now: float, size: float, pnl: float) -> bool:
        t = _finite(now, "now")
        q = _finite(size, "size")
        p = _finite(pnl, "pnl")
        if q <= 0:
            raise ValueError("fill size must be positive")
        if self.last_fill_time is not None and t < self.last_fill_time:
            raise ValueError("fill timestamps must be nondecreasing")
        reason = None
        if self.last_fill_time is not None and t - self.last_fill_time < self.min_fill_interval:
            reason = "RAPID_PACING"
        if self.last_fill_size is not None and q / max(self.last_fill_size, 1e-12) > self.revenge_ratio_limit:
            reason = reason or "REVENGE_SIZING"
        self.consecutive_losses = self.consecutive_losses + 1 if p < 0 else 0
        if self.consecutive_losses >= self.loss_streak_limit:
            reason = reason or "LOSS_STREAK"
        self.trades_today += 1
        self.last_fill_time = t
        self.last_fill_size = q
        if reason:
            self.lockout_until = max(self.lockout_until, t + self.cooldown_seconds)
            self.lockout_reason = reason
            return True
        return False

    def reset_day(self) -> None:
        self.trades_today = 0
        self.consecutive_losses = 0
        self.last_fill_time = None
        self.last_fill_size = None
        self.lockout_until = 0.0
        self.lockout_reason = None

    def snapshot(self, now: float) -> dict[str, Any]:
        remaining = max(0.0, self.lockout_until - _finite(now, "now"))
        return {"optimal_daily_cap": self.optimal_daily_cap, "max_daily_trades": self.max_daily_trades,
                "trades_today": self.trades_today, "consecutive_losses": self.consecutive_losses,
                "lockout_reason": self.lockout_reason, "cooldown_remaining": remaining,
                "entry_allowed": self.can_enter(now)}


# ---------------------------------------------------------------------------
# Risk state and constrained nonlinear portfolio hedge
# ---------------------------------------------------------------------------
class RiskState(str, Enum):
    IDLE = "IDLE"
    EXECUTION_PLANNING = "EXECUTION_PLANNING"
    OPTIMAL_ROUTING = "OPTIMAL_ROUTING"
    OVERTRADING_LOCKED = "OVERTRADING_LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START = "START"
    ROUTE = "ROUTE"
    OVERTRADING = "OVERTRADING"
    EMERGENCY = "EMERGENCY"
    RESET = "RESET"
    RECOVERY_ACK = "RECOVERY_ACK"


@dataclass
class RiskStateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.state, RiskState):
            raise ValueError("invalid initial risk state")
        if self.state is RiskState.EMERGENCY_UNWIND:
            self.emergency_latched = True

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown risk event")
        if self.emergency_latched and event is not RiskEvent.RECOVERY_ACK:
            self.history.append((event.value, "BLOCKED_LATCHED"))
            return self.state
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event is RiskEvent.START and self.state is RiskState.IDLE:
            self.state = RiskState.EXECUTION_PLANNING
        elif event is RiskEvent.ROUTE and self.state in {RiskState.EXECUTION_PLANNING, RiskState.OPTIMAL_ROUTING}:
            self.state = RiskState.OPTIMAL_ROUTING
        elif event is RiskEvent.OVERTRADING:
            self.state = RiskState.OVERTRADING_LOCKED
        elif event is RiskEvent.RESET and not self.emergency_latched:
            self.state = RiskState.IDLE
        self.history.append((event.value, self.state.value))
        return self.state


@dataclass(frozen=True)
class HedgeOptimizationResult:
    weights: list[float]
    objective: float
    iterations: int
    delta_residual: float
    gamma_exposure: float
    converged: bool


@dataclass
class QuadraticSpreadHedgeOptimizer:
    """Projected-gradient optimizer with Dykstra projection onto box, delta plane and gamma slab."""
    eta_cross: float = 0.5
    lambda_cost: float = 1.0
    alpha_reward: float = 1.0
    tolerance: float = 1e-7
    max_iterations: int = 500

    def __post_init__(self) -> None:
        self.eta_cross = _finite(self.eta_cross, "eta_cross")
        self.lambda_cost = _finite(self.lambda_cost, "lambda_cost")
        self.alpha_reward = _finite(self.alpha_reward, "alpha_reward")
        if self.eta_cross < 0 or self.lambda_cost < 0 or self.alpha_reward < 0 or self.tolerance <= 0 or self.max_iterations < 1:
            raise ValueError("invalid optimizer parameters")

    @staticmethod
    def _project_box(x: list[float], lo: list[float], hi: list[float]) -> list[float]:
        return [_clip(v, l, h) for v, l, h in zip(x, lo, hi)]

    @staticmethod
    def _project_hyperplane(x: list[float], d: list[float]) -> list[float]:
        denom = _dot(d, d)
        if denom <= 1e-20:
            return x[:]
        scale = _dot(d, x) / denom
        return [v - scale * di for v, di in zip(x, d)]

    @staticmethod
    def _project_gamma_slab(x: list[float], g: list[float], bound: float) -> list[float]:
        val = _dot(g, x)
        denom = _dot(g, g)
        if denom <= 1e-20 or abs(val) <= bound:
            return x[:]
        target = bound if val > 0 else -bound
        scale = (val - target) / denom
        return [v - scale * gi for v, gi in zip(x, g)]

    def _project_feasible(self, v: list[float], d: list[float], g: list[float],
                          lo: list[float], hi: list[float], gamma_bound: float) -> list[float]:
        # Dykstra corrections for three convex sets: box, delta-neutral hyperplane, gamma slab.
        x = v[:]
        corrections = [[0.0] * len(v) for _ in range(3)]
        for _ in range(2500):
            old = x[:]
            y = [x[i] + corrections[0][i] for i in range(len(x))]
            z = self._project_box(y, lo, hi)
            corrections[0] = [y[i] - z[i] for i in range(len(x))]
            x = z
            y = [x[i] + corrections[1][i] for i in range(len(x))]
            z = self._project_hyperplane(y, d)
            corrections[1] = [y[i] - z[i] for i in range(len(x))]
            x = z
            y = [x[i] + corrections[2][i] for i in range(len(x))]
            z = self._project_gamma_slab(y, g, gamma_bound)
            corrections[2] = [y[i] - z[i] for i in range(len(x))]
            x = z
            if max(abs(x[i] - old[i]) for i in range(len(x))) < self.tolerance * 0.1:
                break
        # A final exact hyperplane projection can violate bounds, so verify all constraints.
        if any(x[i] < lo[i] - 1e-5 or x[i] > hi[i] + 1e-5 for i in range(len(x))):
            raise ValueError("portfolio constraints appear infeasible")
        if abs(_dot(d, x)) > 1e-4 or abs(_dot(g, x)) > gamma_bound + 1e-4:
            raise ValueError("portfolio constraints appear infeasible")
        return self._project_box(x, lo, hi)

    def optimize(self, covariance: Sequence[Sequence[float]], impact_matrix: Sequence[Sequence[float]],
                 deltas: Sequence[float], gammas: Sequence[float],
                 weight_min: Sequence[float], weight_max: Sequence[float],
                 cost_per_unit: Sequence[float], expected_alpha_per_unit: Sequence[float],
                 *, gamma_max: float, initial_weights: Sequence[float] | None = None) -> HedgeOptimizationResult:
        sigma = validate_psd(covariance, "covariance")
        omega = validate_psd(impact_matrix, "impact_matrix")
        n = len(sigma)
        if len(omega) != n:
            raise ValueError("matrix size mismatch")
        d, g = _vector(deltas, "deltas"), _vector(gammas, "gammas")
        lo, hi = _vector(weight_min, "weight_min"), _vector(weight_max, "weight_max")
        costs, alpha = _vector(cost_per_unit, "cost_per_unit"), _vector(expected_alpha_per_unit, "expected_alpha_per_unit")
        if any(len(x) != n for x in (d, g, lo, hi, costs, alpha)):
            raise ValueError("input vector length mismatch")
        if any(lo[i] > hi[i] for i in range(n)) or any(cost < 0 for cost in costs):
            raise ValueError("invalid weight bounds or negative cost")
        gamma_max = _finite(gamma_max, "gamma_max")
        if gamma_max < 0:
            raise ValueError("gamma_max must be nonnegative")
        H = [[sigma[i][j] + self.eta_cross * omega[i][j] for j in range(n)] for i in range(n)]
        # Conservative Lipschitz bound from max absolute row sum for a PSD Hessian.
        lipschitz = max(sum(abs(x) for x in row) for row in H)
        step = 0.8 / max(lipschitz, 1e-6)
        w0 = [0.0] * n if initial_weights is None else _vector(initial_weights, "initial_weights")
        if len(w0) != n:
            raise ValueError("initial weight length mismatch")
        w = self._project_feasible(w0, d, g, lo, hi, gamma_max)
        converged = False
        objective = 0.0
        for it in range(1, self.max_iterations + 1):
            Hw = _mat_vec(H, w)
            grad = [Hw[i] + self.lambda_cost * costs[i] - self.alpha_reward * alpha[i] for i in range(n)]
            raw = [w[i] - step * grad[i] for i in range(n)]
            new_w = self._project_feasible(raw, d, g, lo, hi, gamma_max)
            if max(abs(new_w[i] - w[i]) for i in range(n)) <= self.tolerance:
                w = new_w; converged = True
                break
            w = new_w
        Hw = _mat_vec(H, w)
        objective = 0.5 * _dot(w, Hw) + self.lambda_cost * _dot(costs, w) - self.alpha_reward * _dot(alpha, w)
        return HedgeOptimizationResult(w, objective, it, _dot(d, w), _dot(g, w), converged)


# ---------------------------------------------------------------------------
# Integrated engine + telemetry server
# ---------------------------------------------------------------------------
@dataclass
class Cycle36ExecutionEngine:
    sofi: SOFIJumpDiffusion = field(default_factory=SOFIJumpDiffusion)
    resiliency: LOBResiliencyKernel = field(default_factory=LOBResiliencyKernel)
    hawkes: HawkesMutualExcitation2D = field(default_factory=HawkesMutualExcitation2D)
    regime_filter: BayesianMicrostructureFilter = field(default_factory=BayesianMicrostructureFilter)
    fee_calculator: StatutoryCostCalculator = field(default_factory=StatutoryCostCalculator)
    optimizer: QuadraticSpreadHedgeOptimizer = field(default_factory=QuadraticSpreadHedgeOptimizer)
    throttler: AntiOvertradingThrottler = field(default_factory=AntiOvertradingThrottler)
    risk: RiskStateMachine = field(default_factory=RiskStateMachine)
    latest_regime: dict[str, Any] = field(default_factory=dict)
    latest_fee: FeeBreakdown | None = None
    latest_net_alpha: float = 0.0
    latest_optimization: HedgeOptimizationResult | None = None
    heartbeat: int = 0
    start_monotonic: float = field(default_factory=time.monotonic)

    def process_tick(self, *, dt: float, n_bid: int, n_ask: int,
                     observation: Sequence[float], ofi_jump_intensity: float | None = None) -> dict[str, Any]:
        # Validate the complete observation before mutating any model state.
        dt = _finite(dt, "dt")
        if dt <= 0:
            raise ValueError("dt must be positive")
        if isinstance(n_bid, bool) or isinstance(n_ask, bool) or int(n_bid) != n_bid or int(n_ask) != n_ask or n_bid < 0 or n_ask < 0:
            raise ValueError("event counts must be nonnegative integers")
        obs = list(observation)
        if len(obs) != 5:
            raise ValueError("observation must be [abs_return, spread_ratio, depth_ratio, sweeps, ofi]")
        for i in range(4):
            obs[i] = _finite(obs[i], f"observation[{i}]")
        if any(obs[i] < 0 for i in range(4)):
            raise ValueError("first four observation features must be nonnegative")
        if obs[4] is not None:
            obs[4] = _finite(obs[4], "observation OFI")
        self.sofi.step(dt, jump_intensity=ofi_jump_intensity)
        intensities = self.hawkes.observe(dt, n_bid, n_ask)
        ofi = self.sofi.ofi
        # Null OFI means use the currently sampled SOFI state; otherwise preserve supplied feature.
        obs[4] = ofi if obs[4] is None else obs[4]
        self.latest_regime = self.regime_filter.update(obs)
        if self.latest_regime["extreme_dislocation"]:
            self.risk.transition(RiskEvent.EMERGENCY)
        elif self.risk.state is RiskState.IDLE:
            self.risk.transition(RiskEvent.START)
        self.heartbeat += 1
        return {"ofi": ofi, "hawkes_intensities": intensities, "regime": self.latest_regime,
                "risk_state": self.risk.state.value}

    def optimize_portfolio(self, **kwargs: Any) -> HedgeOptimizationResult:
        """Run the constrained paper portfolio optimizer and publish its latest solution."""
        if self.risk.emergency_latched or self.risk.state is RiskState.EMERGENCY_UNWIND:
            raise RuntimeError("portfolio allocation is frozen during emergency unwind")
        result = self.optimizer.optimize(**kwargs)
        self.latest_optimization = result
        if self.risk.state is RiskState.IDLE:
            self.risk.transition(RiskEvent.START)
        self.risk.transition(RiskEvent.ROUTE)
        return result

    def evaluate_candidate(self, gross_alpha: float, legs: Sequence[OptionLeg], *,
                           half_spread_per_unit: float = 0.0, impact_hurdle: float = 0.0,
                           now: float | None = None) -> dict[str, Any]:
        fee = self.fee_calculator.calculate(legs, half_spread_per_unit=half_spread_per_unit,
                                            cross_impact_hurdle=impact_hurdle)
        gross_alpha = _finite(gross_alpha, "gross_alpha")
        net = gross_alpha - fee.total_friction
        clock = time.time() if now is None else _finite(now, "now")
        self.latest_fee = fee
        self.latest_net_alpha = net
        if self.risk.state is RiskState.OVERTRADING_LOCKED and clock >= self.throttler.lockout_until and not self.risk.emergency_latched:
            self.risk.transition(RiskEvent.RESET)
        risk_allows = self.risk.state in {RiskState.IDLE, RiskState.EXECUTION_PLANNING, RiskState.OPTIMAL_ROUTING}
        allowed = net > 0 and risk_allows and self.throttler.can_enter(clock) and not self.risk.emergency_latched
        if self.risk.state is RiskState.IDLE and risk_allows:
            self.risk.transition(RiskEvent.START)
        return {"gross_alpha": gross_alpha, "fees": asdict(fee), "net_expected_alpha": net,
                "profitable": net > 0, "entry_allowed": allowed,
                "block_reason": None if allowed else ("UNPROFITABLE" if net <= 0 else "RISK_OR_THROTTLE_BLOCK")}

    def register_fill(self, *, now: float, size: float, pnl: float) -> bool:
        locked = self.throttler.register_fill(now=now, size=size, pnl=pnl)
        if locked:
            self.risk.transition(RiskEvent.OVERTRADING)
        return locked

    def recover(self) -> None:
        self.risk.transition(RiskEvent.RECOVERY_ACK)

    def telemetry_payload(self) -> dict[str, Any]:
        now = datetime.now(IST)
        ts = time.time()
        hawkes = self.hawkes.snapshot()
        regime = self.regime_filter.snapshot()
        queue = self.resiliency.snapshot(self.resiliency.last_event_time)
        return {
            "timestamp_ist": now.isoformat(), "epoch_seconds": ts,
            "sofi": self.sofi.snapshot(), "lob_resiliency": queue,
            "hawkes": hawkes, "microstructure_regime": regime,
            "latest_fee_breakdown": asdict(self.latest_fee) if self.latest_fee else None,
            "latest_net_expected_alpha": self.latest_net_alpha,
            "optimization": asdict(self.latest_optimization) if self.latest_optimization else None,
            "throttler": self.throttler.snapshot(ts), "risk_state": self.risk.state.value,
            "emergency_latched": self.risk.emergency_latched,
            "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
            "safety_epoch": SAFETY_EPOCH, "heartbeat": self.heartbeat,
            "uptime_seconds": max(0.0, time.monotonic() - self.start_monotonic),
        }

    def health_payload(self) -> dict[str, Any]:
        return {"status": "ok", "heartbeat": self.heartbeat, "risk_state": self.risk.state.value,
                "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                "emergency_latched": self.risk.emergency_latched}


class _Cycle36HTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    def __init__(self, address: tuple[str, int], engine: Cycle36ExecutionEngine):
        self.engine = engine
        self.running = True
        super().__init__(address, _Cycle36RequestHandler)


class _Cycle36RequestHandler(BaseHTTPRequestHandler):
    server: _Cycle36HTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send_json(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(self.server.engine.health_payload())
        elif self.path == "/telemetry":
            self._send_json(self.server.engine.telemetry_payload())
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while self.server.running:
                    payload = json.dumps(self.server.engine.telemetry_payload(), separators=(",", ":"), allow_nan=False)
                    self.wfile.write((f"event: telemetry\ndata: {payload}\n\n").encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(1.0)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        else:
            raw = json.dumps({"error": "not_found"}).encode("utf-8")
            self.send_response(404); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)


def start_dashboard(engine: Cycle36ExecutionEngine, host: str = "127.0.0.1", port: int = 8088) -> tuple[_Cycle36HTTPServer, Thread]:
    """Start the local JSON/SSE telemetry server; caller owns shutdown."""
    server = _Cycle36HTTPServer((host, int(port)), engine)
    thread = Thread(target=server.serve_forever, name="cycle36-dashboard", daemon=True)
    thread.start()
    return server, thread


def stop_dashboard(server: _Cycle36HTTPServer) -> None:
    server.running = False
    server.shutdown()
    server.server_close()


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("live order dispatch is permanently disabled; paper simulation only")
