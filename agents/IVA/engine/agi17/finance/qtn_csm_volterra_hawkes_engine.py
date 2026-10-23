"""Cycle 57 QTN-CSM offline quantitative research engine.

Tensor-train/MPS compression, multi-scale fractional Hawkes memory, liquidity
resilience, rough-Volterra kernel lift, continuous actor-critic, fee gates, and
fail-closed paper-execution controls. This is a deterministic research baseline,
not a broker integration or a production pricing/hedging system.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, gamma, log, sqrt
from typing import Iterable, Sequence

import numpy as np

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
STATE_DIM = 16
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0
MAX_KELLY_FRACTION = 0.10


class ValidationError(ValueError):
    """Raised when a research input violates an explicit model contract."""


class TensorRankLimitError(ValueError):
    """Raised when an MPS bond cap cannot meet the requested error tolerance."""


def _finite_array(value: object, *, ndim: int | None = None, name: str = "array") -> np.ndarray:
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} cannot be converted to a rectangular numeric array") from exc
    if ndim is not None and arr.ndim != ndim:
        raise ValidationError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValidationError(f"{name} must be finite")
    return arr


def _positive(value: float, name: str, *, allow_zero: bool = False) -> float:
    value = float(value)
    if not np.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        relation = "non-negative" if allow_zero else "positive"
        raise ValidationError(f"{name} must be finite and {relation}")
    return value


@dataclass(frozen=True)
class TensorTrain:
    """Matrix product state / tensor-train factors A[i] with shape (rL,n,rR)."""

    factors: tuple[np.ndarray, ...]
    shape: tuple[int, ...]
    relative_error: float
    requested_tolerance: float

    @property
    def max_bond_dimension(self) -> int:
        if len(self.factors) <= 1:
            return 1
        return max(max(a.shape[0], a.shape[2]) for a in self.factors)

    def reconstruct(self) -> np.ndarray:
        if not self.factors:
            return np.asarray(1.0)
        cur = self.factors[0]
        # Remove the left boundary rank, leaving (n0, r1).
        cur = cur[0, :, :]
        for factor in self.factors[1:]:
            cur = np.tensordot(cur, factor, axes=([-1], [0]))
        # The final boundary bond rank is one.
        return np.asarray(cur[..., 0]).reshape(self.shape)

    def contract(self, vectors: Sequence[Sequence[float]]) -> float:
        """Contract the MPS with one vector per tensor mode."""
        if len(vectors) != len(self.factors):
            raise ValidationError("one contraction vector is required for each tensor mode")
        state = np.ones(1, dtype=float)
        for i, (factor, vector) in enumerate(zip(self.factors, vectors)):
            vec = _finite_array(vector, ndim=1, name=f"contraction vector {i}")
            if len(vec) != factor.shape[1]:
                raise ValidationError(f"contraction vector {i} has the wrong length")
            state = np.einsum("a,aib,i->b", state, factor, vec, optimize=True)
        if state.size != 1:
            raise ValidationError("invalid tensor-train boundary rank")
        return float(state[0])

    def evaluate(self, indices: Sequence[int]) -> float:
        if len(indices) != len(self.shape):
            raise ValidationError("one index is required for each tensor mode")
        vectors = []
        for axis, index in enumerate(indices):
            if not isinstance(index, (int, np.integer)) or not 0 <= int(index) < self.shape[axis]:
                raise ValidationError(f"index {axis} is out of bounds")
            basis = np.zeros(self.shape[axis], dtype=float)
            basis[int(index)] = 1.0
            vectors.append(basis)
        return self.contract(vectors)


def tensor_train_svd(
    tensor: Sequence[float] | np.ndarray,
    *,
    max_bond_dim: int = 16,
    tolerance: float = 1e-4,
    require_tolerance: bool = True,
) -> TensorTrain:
    """Decompose a finite tensor using sequential truncated SVD.

    Local discarded Frobenius norms are budgeted at tolerance/sqrt(d-1), giving
    the usual TT-SVD error bound when the bond cap does not bind. If the cap
    prevents the requested accuracy, this is reported in relative_error and
    (by default) raises TensorRankLimitError rather than claiming success.
    """
    arr = _finite_array(tensor, name="tensor")
    if arr.ndim < 2 or any(n <= 0 for n in arr.shape):
        raise ValidationError("tensor must have at least two non-empty modes")
    if not isinstance(max_bond_dim, (int, np.integer)) or max_bond_dim < 1 or max_bond_dim > 16:
        raise ValidationError("max_bond_dim must be an integer in [1,16]")
    tolerance = _positive(tolerance, "tolerance", allow_zero=True)
    d = arr.ndim
    norm = float(np.linalg.norm(arr.ravel()))
    if norm == 0.0:
        factors = tuple(np.zeros((1, n, 1), dtype=float) for n in arr.shape)
        return TensorTrain(factors, tuple(arr.shape), 0.0, tolerance)
    if d == 2:
        u, s, vh = np.linalg.svd(arr, full_matrices=False)
        local_target = tolerance * norm
        # Choose the smallest rank whose discarded singular-value tail meets tolerance.
        rank = min(max_bond_dim, len(s))
        if tolerance > 0:
            for r in range(1, min(max_bond_dim, len(s)) + 1):
                if np.linalg.norm(s[r:]) <= local_target:
                    rank = r
                    break
        factors = (u[:, :rank].reshape(1, arr.shape[0], rank), (s[:rank, None] * vh[:rank, :]).reshape(rank, arr.shape[1], 1))
    else:
        core = arr.copy()
        r_prev = 1
        factors_list: list[np.ndarray] = []
        local_target = tolerance * norm / sqrt(d - 1) if tolerance > 0 else 0.0
        for mode in range(d - 1):
            n = arr.shape[mode]
            matrix = core.reshape(r_prev * n, -1)
            u, s, vh = np.linalg.svd(matrix, full_matrices=False)
            allowed = min(int(max_bond_dim), len(s))
            rank = allowed
            if tolerance > 0:
                for r in range(1, allowed + 1):
                    if np.linalg.norm(s[r:]) <= local_target:
                        rank = r
                        break
            factors_list.append(u[:, :rank].reshape(r_prev, n, rank))
            core = s[:rank, None] * vh[:rank, :]
            r_prev = rank
        factors_list.append(core.reshape(r_prev, arr.shape[-1], 1))
        factors = tuple(factors_list)
    provisional = TensorTrain(tuple(np.asarray(f, dtype=float) for f in factors), tuple(arr.shape), float("inf"), tolerance)
    approx = provisional.reconstruct()
    err = float(np.linalg.norm((arr - approx).ravel()) / norm)
    result = TensorTrain(provisional.factors, provisional.shape, err, tolerance)
    if require_tolerance and err > tolerance + 1e-12:
        raise TensorRankLimitError(
            f"bond cap {max_bond_dim} cannot meet relative tolerance {tolerance:g}; achieved {err:g}"
        )
    return result


def gamma_vacuum_detect(gamma_surface: Sequence[float] | np.ndarray, threshold: float) -> bool:
    """Return True if any measured dealer-gamma cell is below -threshold."""
    values = _finite_array(gamma_surface, name="gamma_surface")
    threshold = _positive(threshold, "threshold", allow_zero=True)
    return bool(np.any(values < -threshold))


def mps_convex_interpolate(mps: TensorTrain, weights: Sequence[Sequence[float]], *, tolerance: float = 1e-10) -> float:
    """Contract normalized non-negative interpolation weights through an MPS.

    Convex interpolation of a non-negative sampled tensor preserves
    non-negativity. This helper checks convex weights and result sign; it does
    not itself certify calendar or butterfly arbitrage for an option surface.
    """
    tol = _positive(tolerance, "tolerance", allow_zero=True)
    if len(weights) != len(mps.shape):
        raise ValidationError("one interpolation vector is required per tensor mode")
    vectors = []
    for mode, raw in enumerate(weights):
        vec = _finite_array(raw, ndim=1, name=f"interpolation weights {mode}")
        if vec.shape != (mps.shape[mode],):
            raise ValidationError(f"interpolation vector {mode} has the wrong length")
        if np.any(vec < -tol) or not np.isclose(float(np.sum(vec)), 1.0, atol=tol, rtol=0):
            raise ValidationError("interpolation weights must be non-negative and sum to one")
        vectors.append(np.maximum(vec, 0.0))
    value = mps.contract(vectors)
    if value < -tol:
        raise ValidationError("convex interpolation produced a negative surface value")
    return float(max(value, 0.0))


def assert_calendar_monotone_surface(total_variance: Sequence[float] | np.ndarray, *, expiry_axis: int = 1, tolerance: float = 1e-10) -> bool:
    """Check sampled total variance is non-negative and non-decreasing by expiry."""
    surface = _finite_array(total_variance, name="total_variance")
    tol = _positive(tolerance, "tolerance", allow_zero=True)
    if surface.ndim < 2:
        raise ValidationError("total variance surface must have at least two dimensions")
    if not isinstance(expiry_axis, (int, np.integer)) or not -surface.ndim <= expiry_axis < surface.ndim:
        raise ValidationError("expiry_axis is out of bounds")
    if np.any(surface < -tol):
        raise ValidationError("total variance must be non-negative")
    if np.any(np.diff(surface, axis=expiry_axis) < -tol):
        raise ValidationError("total variance decreases across sampled expiries")
    return True


@dataclass(frozen=True)
class HawkesStabilityReport:
    branching_matrix: np.ndarray
    spectral_radius: float
    stable: bool
    limit: float


class MultiScaleFractionalHawkes:
    """Four-dimensional exponential + integrable power-law Hawkes intensity.

    For beta > 1, the branching matrix is A_exp/kappa + A_power/(beta-1).
    Intensities are clipped at zero after the signed MLOFI covariate is added.
    """

    def __init__(
        self,
        baseline: Sequence[float],
        alpha_exp: Sequence[Sequence[float]],
        alpha_power: Sequence[Sequence[float]],
        kappa: float,
        beta: float,
        *,
        mlofi_gamma: float = 0.0,
        stability_limit: float = 0.88,
        events: Iterable[tuple[float, int]] = (),
    ) -> None:
        self.baseline = _finite_array(baseline, ndim=1, name="baseline")
        self.alpha_exp = _finite_array(alpha_exp, ndim=2, name="alpha_exp")
        self.alpha_power = _finite_array(alpha_power, ndim=2, name="alpha_power")
        n = len(self.baseline)
        if n != 4 or self.alpha_exp.shape != (n, n) or self.alpha_power.shape != (n, n):
            raise ValidationError("baseline and excitation matrices must describe four assets")
        if np.any(self.baseline < 0) or np.any(self.alpha_exp < 0) or np.any(self.alpha_power < 0):
            raise ValidationError("Hawkes baseline and excitations must be non-negative")
        self.kappa = _positive(kappa, "kappa")
        self.beta = _positive(beta, "beta")
        if self.beta <= 1.0:
            raise ValidationError("power-law exponent beta must exceed 1 for finite branching mass")
        self.mlofi_gamma = float(mlofi_gamma)
        if not np.isfinite(self.mlofi_gamma):
            raise ValidationError("mlofi_gamma must be finite")
        self.stability_limit = _positive(stability_limit, "stability_limit")
        self.events: list[tuple[float, int]] = []
        for time, asset in events:
            self.record_event(time, asset)

    def stability_report(self) -> HawkesStabilityReport:
        branching = self.alpha_exp / self.kappa + self.alpha_power / (self.beta - 1.0)
        radius = float(np.max(np.abs(np.linalg.eigvals(branching))))
        return HawkesStabilityReport(branching, radius, radius <= self.stability_limit + 1e-12, self.stability_limit)

    def assert_stable(self) -> None:
        report = self.stability_report()
        if not report.stable:
            raise ValidationError(f"Hawkes branching spectral radius {report.spectral_radius:.6g} exceeds {report.limit:.6g}")

    def record_event(self, time: float, asset: int) -> None:
        time = float(time)
        if not np.isfinite(time) or time < 0:
            raise ValidationError("event time must be finite and non-negative")
        if not isinstance(asset, (int, np.integer)) or not 0 <= int(asset) < 4:
            raise ValidationError("asset index must be an integer in [0,3]")
        if self.events and time < self.events[-1][0]:
            raise ValidationError("Hawkes events must be recorded in nondecreasing time order")
        self.events.append((time, int(asset)))

    def intensity(self, time: float, mlofi: Sequence[float] | None = None) -> np.ndarray:
        time = float(time)
        if not np.isfinite(time) or time < 0:
            raise ValidationError("intensity time must be finite and non-negative")
        if self.events and time < self.events[-1][0]:
            raise ValidationError("query time cannot precede the latest recorded event")
        result = self.baseline.copy()
        for event_time, source in self.events:
            age = time - event_time
            result += self.alpha_exp[:, source] * np.exp(-self.kappa * age)
            result += self.alpha_power[:, source] * (1.0 + age) ** (-self.beta)
        if mlofi is not None:
            flow = _finite_array(mlofi, ndim=1, name="mlofi")
            if flow.shape != (4,):
                raise ValidationError("mlofi must contain four asset-level values")
            result += self.mlofi_gamma * flow
        return np.maximum(result, 0.0)


def sample_hawkes_arrivals(
    process: MultiScaleFractionalHawkes, time: float, dt: float,
    mlofi: Sequence[float], rng: np.random.Generator,
) -> np.ndarray:
    """Sample a piecewise-constant Hawkes increment over [time,time+dt].

    This tau-leap approximation draws independent Poisson counts from the
    pre-step intensities and records all events at the end of the interval. It
    is deterministic for a fixed Generator seed and makes the discretization
    assumption explicit; it is not exact Ogata thinning.
    """
    time = float(time)
    dt = _positive(dt, "dt")
    if not np.isfinite(time) or time < 0:
        raise ValidationError("time must be finite and non-negative")
    if not isinstance(rng, np.random.Generator):
        raise ValidationError("rng must be a numpy Generator")
    intensities = process.intensity(time, mlofi)
    counts = rng.poisson(intensities * dt).astype(int)
    for asset, count in enumerate(counts):
        for _ in range(int(count)):
            process.record_event(time + dt, asset)
    return counts


def rough_vol_price_step(
    spot: float, drift: float, variance: float, dt: float, dW: float,
    jump_amplitudes: Sequence[float] = (),
) -> float:
    """Positive exponential step for rough-volatility price and relative jumps.

    Jump amplitudes are simple relative price jumps J_k and must exceed -1.
    The diffusion uses the standard log-Euler correction -0.5*V*dt.
    """
    spot = _positive(spot, "spot")
    variance = _positive(variance, "variance", allow_zero=True)
    dt = _positive(dt, "dt")
    drift = float(drift)
    dW = float(dW)
    if not np.isfinite(drift) or not np.isfinite(dW):
        raise ValidationError("drift and dW must be finite")
    jumps = _finite_array(jump_amplitudes, ndim=1, name="jump_amplitudes")
    if np.any(jumps <= -1.0):
        raise ValidationError("relative jump amplitudes must exceed -1")
    log_jump = float(np.sum(np.log1p(jumps))) if jumps.size else 0.0
    log_return = (drift - 0.5 * variance) * dt + sqrt(variance) * dW + log_jump
    return float(spot * np.exp(np.clip(log_return, -100.0, 100.0)))


@dataclass
class LiquidityResilience:
    """Exact constant-forcing step for dR/dt=-theta(R-R0)+eta*fill-zeta*toxic."""

    equilibrium: float = 1.0
    theta: float = 1.0
    eta: float = 0.1
    zeta: float = 0.2
    value: float | None = None

    def __post_init__(self) -> None:
        self.equilibrium = _positive(self.equilibrium, "equilibrium", allow_zero=True)
        self.theta = _positive(self.theta, "theta")
        self.eta = _positive(self.eta, "eta", allow_zero=True)
        self.zeta = _positive(self.zeta, "zeta", allow_zero=True)
        if self.value is None:
            self.value = self.equilibrium
        self.value = _positive(float(self.value), "value", allow_zero=True)

    @property
    def half_life(self) -> float:
        return log(2.0) / self.theta

    def step(self, dt: float, *, passive_fill: float = 0.0, toxic_intensity: float = 0.0) -> float:
        dt = _positive(dt, "dt")
        fill = _positive(passive_fill, "passive_fill", allow_zero=True)
        toxic = _positive(toxic_intensity, "toxic_intensity", allow_zero=True)
        decay = exp(-self.theta * dt)
        forcing = self.eta * fill - self.zeta * toxic
        assert self.value is not None
        updated = self.equilibrium + (self.value - self.equilibrium) * decay + forcing * (1.0 - decay) / self.theta
        self.value = max(0.0, float(updated))
        return self.value


class RoughVolterraLift:
    """Twelve-factor positive exponential approximation to a rough Volterra kernel."""

    def __init__(self, hurst: float = 0.07, factors: int = 12):
        self.hurst = float(hurst)
        if not 0.0 < self.hurst < 0.5:
            raise ValidationError("hurst must be in (0, 0.5)")
        if not isinstance(factors, (int, np.integer)) or factors != 12:
            raise ValidationError("Cycle 57 uses exactly 12 Markovian lift factors")
        self.factor_count = int(factors)
        # Log-quadrature of the Laplace representation for t^(-a), a=1/2-H.
        a = 0.5 - self.hurst
        log_gamma = np.linspace(log(1e-3), log(1e3), factors)
        self.decay_rates = np.exp(log_gamma)
        spacing = (log_gamma[-1] - log_gamma[0]) / (factors - 1)
        self.weights = spacing * self.decay_rates**a / (gamma(a) * gamma(self.hurst + 0.5))
        self.state = np.zeros(factors, dtype=float)

    def kernel(self, t: float) -> float:
        t = _positive(t, "t")
        return float(np.dot(self.weights, np.exp(-self.decay_rates * t)))

    def singular_kernel(self, t: float) -> float:
        t = _positive(t, "t")
        return float(t ** (self.hurst - 0.5) / gamma(self.hurst + 0.5))

    def step(self, dt: float, dW: float, *, nu: float = 0.3, jump: float = 0.0, forward_variance: float = 0.04) -> tuple[float, float]:
        dt = _positive(dt, "dt")
        dW = float(dW)
        nu = _positive(nu, "nu", allow_zero=True)
        jump = float(jump)
        forward_variance = _positive(forward_variance, "forward_variance")
        if not np.isfinite(dW) or not np.isfinite(jump):
            raise ValidationError("Brownian increment and jump must be finite")
        self.state = self.state * np.exp(-self.decay_rates * dt) + self.weights * nu * dW
        log_var = log(forward_variance) + float(np.sum(self.state)) + jump
        log_var = float(np.clip(log_var, -30.0, 20.0))
        variance = float(np.exp(log_var))
        return log_var, variance


@dataclass(frozen=True)
class FeeBreakdown:
    stt: float
    stamp_duty: float
    exchange: float
    sebi: float
    brokerage: float
    gst: float
    total: float


def indian_statutory_fees(*, buy_turnover: float = 0.0, sell_turnover: float = 0.0, legs: int = 0) -> FeeBreakdown:
    buy = _positive(buy_turnover, "buy_turnover", allow_zero=True)
    sell = _positive(sell_turnover, "sell_turnover", allow_zero=True)
    if not isinstance(legs, (int, np.integer)) or legs < 0:
        raise ValidationError("legs must be a non-negative integer")
    total_turnover = buy + sell
    stt = 0.0015 * sell
    stamp = 0.00003 * buy
    exchange = total_turnover * 3553.0 / 100_000_000.0
    sebi = total_turnover * 10.0 / 100_000_000.0
    brokerage = 20.0 * int(legs)
    gst = 0.18 * (exchange + sebi + brokerage)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return FeeBreakdown(*(float(x) for x in (stt, stamp, exchange, sebi, brokerage, gst, total)))


def net_alpha_gate(expected_gross_alpha: float, fees: float) -> tuple[bool, float]:
    gross = float(expected_gross_alpha)
    fee = _positive(fees, "fees", allow_zero=True)
    if not np.isfinite(gross):
        raise ValidationError("expected_gross_alpha must be finite")
    net = gross - fee
    return net > 0.0, net


def beta_fractional_kelly(wins: float, losses: float, odds: float, *, scale: float = 0.25, cap: float = MAX_KELLY_FRACTION) -> float:
    wins = _positive(wins, "wins", allow_zero=True)
    losses = _positive(losses, "losses", allow_zero=True)
    odds = _positive(odds, "odds")
    scale = _positive(scale, "scale", allow_zero=True)
    cap = _positive(cap, "cap", allow_zero=True)
    if cap > MAX_KELLY_FRACTION + 1e-12:
        raise ValidationError("Kelly cap cannot exceed 10%")
    posterior_p = (1.0 + wins) / (2.0 + wins + losses)
    full_kelly = (posterior_p * (odds + 1.0) - 1.0) / odds
    return float(np.clip(full_kelly * scale, 0.0, min(cap, MAX_KELLY_FRACTION)))


@dataclass(frozen=True)
class InventoryBand:
    target: float
    lower: float
    upper: float
    base_width: float


def inventory_indifference_band(
    *, target_inventory: float, cost: float, sigma: float, gamma_risk: float,
    buy_spread_penalty: float = 0.0, sell_spread_penalty: float = 0.0, fee_drag: float = 0.0,
) -> InventoryBand:
    target = float(target_inventory)
    if not np.isfinite(target):
        raise ValidationError("target_inventory must be finite")
    c = _positive(cost, "cost", allow_zero=True)
    vol = _positive(sigma, "sigma", allow_zero=True)
    risk = _positive(gamma_risk, "gamma_risk")
    buy_pen = _positive(buy_spread_penalty, "buy_spread_penalty", allow_zero=True)
    sell_pen = _positive(sell_spread_penalty, "sell_spread_penalty", allow_zero=True)
    drag = _positive(fee_drag, "fee_drag", allow_zero=True)
    width = ((3.0 * c * vol * vol) / (4.0 * risk)) ** (1.0 / 3.0)
    return InventoryBand(target, target - (width + buy_pen + drag), target + (width + sell_pen + drag), width)


def inventory_action(inventory: float, band: InventoryBand) -> str:
    inv = float(inventory)
    if not np.isfinite(inv):
        raise ValidationError("inventory must be finite")
    if inv < band.lower:
        return "BUY_TO_REBALANCE"
    if inv > band.upper:
        return "SELL_TO_REBALANCE"
    return "NO_TRADE"


class _MLP:
    def __init__(self, dims: Sequence[int], seed: int, *, bounded_output: bool):
        self.dims = tuple(int(x) for x in dims)
        if len(self.dims) < 2 or any(x <= 0 for x in self.dims):
            raise ValidationError("network dimensions must be positive")
        self.bounded_output = bounded_output
        rng = np.random.default_rng(seed)
        self.weights = [rng.normal(0.0, sqrt(2.0 / (a + b)), (a, b)) for a, b in zip(self.dims[:-1], self.dims[1:])]
        self.biases = [np.zeros(b) for b in self.dims[1:]]

    def forward(self, x: np.ndarray, *, cache: bool = False):
        activations = [x]
        current = x
        for layer, (weight, bias) in enumerate(zip(self.weights, self.biases)):
            z = current @ weight + bias
            if layer < len(self.weights) - 1 or self.bounded_output:
                current = np.tanh(z)
            else:
                current = z
            activations.append(current)
        return (current, activations) if cache else current

    def backward_update(self, activations: list[np.ndarray], grad_prediction: np.ndarray, learning_rate: float) -> None:
        grad = np.asarray(grad_prediction, dtype=float).reshape(-1)
        lr = _positive(learning_rate, "learning_rate")
        for layer in range(len(self.weights) - 1, -1, -1):
            output = activations[layer + 1]
            if layer < len(self.weights) - 1 or self.bounded_output:
                grad_z = grad * (1.0 - output * output)
            else:
                grad_z = grad
            grad_w = np.outer(activations[layer], grad_z)
            grad = self.weights[layer] @ grad_z
            self.weights[layer] -= lr * grad_w
            self.biases[layer] -= lr * grad_z


class ContinuousActorCritic:
    """Two-hidden-layer state-conditioned policy and critic, for paper research."""

    def __init__(self, seed: int = 57, state_dim: int = STATE_DIM, hidden: tuple[int, int] = (32, 16)):
        if state_dim != STATE_DIM:
            raise ValidationError("Cycle 57 actor-critic requires a 16-dimensional state")
        if len(hidden) != 2 or any(int(h) <= 0 for h in hidden):
            raise ValidationError("exactly two positive hidden-layer sizes are required")
        self.actor = _MLP((state_dim, *hidden, 3), seed, bounded_output=True)
        self.critic = _MLP((state_dim, *hidden, 1), seed + 1, bounded_output=False)
        self.rng = np.random.default_rng(seed + 2)

    @staticmethod
    def _state(state: Sequence[float]) -> np.ndarray:
        arr = _finite_array(state, ndim=1, name="state")
        if arr.shape != (STATE_DIM,):
            raise ValidationError("state must have exactly 16 dimensions")
        return arr

    def act(self, state: Sequence[float], *, noise_scale: float = 0.0) -> np.ndarray:
        arr = self._state(state)
        noise = _positive(noise_scale, "noise_scale", allow_zero=True)
        mean = np.asarray(self.actor.forward(arr), dtype=float)
        if noise > 0:
            mean = mean + self.rng.normal(0.0, noise, size=3)
        return np.clip(mean, -1.0, 1.0)

    def value(self, state: Sequence[float]) -> float:
        arr = self._state(state)
        return float(self.critic.forward(arr)[0])

    def update_critic(self, state: Sequence[float], target: float, learning_rate: float = 1e-3) -> float:
        arr = self._state(state)
        target = float(target)
        if not np.isfinite(target):
            raise ValidationError("target must be finite")
        prediction, cache = self.critic.forward(arr, cache=True)
        error = float(prediction[0] - target)
        self.critic.backward_update(cache, np.asarray([2.0 * error]), learning_rate)
        return error * error

    def update_actor(self, state: Sequence[float], action_gradient: Sequence[float], learning_rate: float = 1e-3) -> np.ndarray:
        arr = self._state(state)
        grad = _finite_array(action_gradient, ndim=1, name="action_gradient")
        if grad.shape != (3,):
            raise ValidationError("action_gradient must have three dimensions")
        prediction, cache = self.actor.forward(arr, cache=True)
        # Gradient descent on -Q approximates a deterministic policy-gradient step.
        self.actor.backward_update(cache, -grad, learning_rate)
        return np.asarray(prediction)


def friction_aware_advantage(gross_advantage: float, statutory_fees: float, inventory: float, sigma_inventory: float, risk_lambda: float) -> float:
    gross = float(gross_advantage)
    if not np.isfinite(gross):
        raise ValidationError("gross_advantage must be finite")
    fees = _positive(statutory_fees, "statutory_fees", allow_zero=True)
    q = float(inventory)
    if not np.isfinite(q):
        raise ValidationError("inventory must be finite")
    sigma = _positive(sigma_inventory, "sigma_inventory", allow_zero=True)
    lam = _positive(risk_lambda, "risk_lambda", allow_zero=True)
    return gross - fees - lam * q * q * sigma * sigma


def mlofi(
    bid_volume_delta: Sequence[float], ask_volume_delta: Sequence[float],
    bid_price_delta: Sequence[float], ask_price_delta: Sequence[float],
    weights: Sequence[float] = (5, 4, 3, 2, 1),
) -> float:
    vb = _finite_array(bid_volume_delta, ndim=1, name="bid_volume_delta")
    va = _finite_array(ask_volume_delta, ndim=1, name="ask_volume_delta")
    pb = _finite_array(bid_price_delta, ndim=1, name="bid_price_delta")
    pa = _finite_array(ask_price_delta, ndim=1, name="ask_price_delta")
    w = _finite_array(weights, ndim=1, name="weights")
    if any(x.shape != (5,) for x in (vb, va, pb, pa, w)):
        raise ValidationError("MLOFI requires exactly five levels for all inputs")
    return float(np.sum(w * (vb * (pb >= 0.0) - va * (pa <= 0.0))))


@dataclass(frozen=True)
class AgentVote:
    agent: str
    approve: bool
    reason: str


AGENT_ROLES = {
    "Manager Abhi": "operator liaison, capital approval, binding live veto",
    "Alex": "MPS tensor and liquidity/queue risk",
    "Emily": "rough volatility and regime risk",
    "Max": "statutory net alpha and Bayesian-Kelly sizing",
}


def squad_consensus(votes: Sequence[AgentVote], *, manager_veto: bool = False, net_alpha_positive: bool = False) -> bool:
    if manager_veto or not net_alpha_positive:
        return False
    by_name = {v.agent: v for v in votes}
    if set(by_name) != set(AGENT_ROLES):
        return False
    if len(votes) != len(AGENT_ROLES):
        return False
    return all(v.approve for v in votes) and by_name["Manager Abhi"].approve


def dispatch_live_order(*args, **kwargs):
    """Live dispatch is deliberately impossible in this research package."""
    raise PermissionError("Cycle 57 is paper-only; live order dispatch is disabled")


def safety_invariants() -> dict[str, object]:
    return {
        "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
        "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED,
        "PAPER_LEDGER_EPOCH": PAPER_LEDGER_EPOCH,
        "INITIAL_CAPITAL_INR": INITIAL_CAPITAL_INR,
    }


__all__ = [
    "ASSETS", "STATE_DIM", "LIVE_ORDER_DISPATCH_ENABLED", "REAL_BROKER_FILLS_LOCKED",
    "PAPER_LEDGER_EPOCH", "INITIAL_CAPITAL_INR", "MAX_KELLY_FRACTION", "ValidationError",
    "TensorRankLimitError", "TensorTrain", "tensor_train_svd", "gamma_vacuum_detect",
    "mps_convex_interpolate", "assert_calendar_monotone_surface",
    "HawkesStabilityReport", "MultiScaleFractionalHawkes", "sample_hawkes_arrivals",
    "rough_vol_price_step", "LiquidityResilience",
    "RoughVolterraLift", "FeeBreakdown", "indian_statutory_fees", "net_alpha_gate",
    "beta_fractional_kelly", "InventoryBand", "inventory_indifference_band", "inventory_action",
    "ContinuousActorCritic", "friction_aware_advantage", "mlofi", "AgentVote", "AGENT_ROLES",
    "squad_consensus", "dispatch_live_order", "safety_invariants",
]
