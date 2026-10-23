"""Cycle 55 HF-CEH-LOS offline quantitative research engine.

This module is a deterministic, paper-only research implementation.  It contains
no broker adapter or live order path.  NumPy is the sole runtime dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence
import math
import numpy as np

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
N_ASSETS = 4
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0

STT_SELL_RATE = 0.0015
STAMP_BUY_RATE = 0.00003
EXCHANGE_RATE = 3553.0 / 10_000_000.0
SEBI_RATE = 10.0 / 10_000_000.0
GST_RATE = 0.18
BROKERAGE_PER_LEG_INR = 20.0
DEFAULT_HAWKES_RADIUS_LIMIT = 0.88


class ValidationError(ValueError):
    """Raised when a model input violates a mathematical precondition."""


def _as_float_array(value: object, name: str, shape: tuple[int, ...] | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(arr)):
        raise ValidationError(f"{name} must contain only finite values")
    if shape is not None and arr.shape != shape:
        raise ValidationError(f"{name} must have shape {shape}, got {arr.shape}")
    return arr


def _spectral_radius(matrix: np.ndarray) -> float:
    vals = np.linalg.eigvals(matrix)
    return float(np.max(np.abs(vals))) if vals.size else 0.0


def regularize_impact_matrix(raw_impact: object, epsilon: float = 1e-8) -> np.ndarray:
    """Return a symmetric strictly positive-definite impact matrix.

    First symmetrize the raw matrix, then floor its eigenvalues at epsilon.
    Merely adding epsilon*I to an arbitrary symmetric matrix does not guarantee
    positive definiteness, so an eigenvalue projection is used as well.
    """
    g = _as_float_array(raw_impact, "raw_impact", (N_ASSETS, N_ASSETS))
    if epsilon <= 0 or not math.isfinite(epsilon):
        raise ValidationError("epsilon must be finite and > 0")
    sym = 0.5 * (g + g.T)
    eigvals, eigvecs = np.linalg.eigh(sym)
    floored = np.maximum(eigvals, epsilon)
    result = (eigvecs * floored) @ eigvecs.T
    result = 0.5 * (result + result.T)
    # Numerical guard: preserve the documented strict lower eigenvalue floor.
    min_eig = float(np.min(np.linalg.eigvalsh(result)))
    if min_eig <= 0:
        result += (epsilon - min_eig + epsilon) * np.eye(N_ASSETS)
    return result


@dataclass(frozen=True)
class CrossImpactModel:
    """Regularized cross-impact and exponential transient impact memory."""
    raw_impact: np.ndarray
    decay_rates: np.ndarray
    memory_kernel: np.ndarray
    exponent: float = 1.0
    epsilon: float = 1e-8

    def __post_init__(self) -> None:
        raw = _as_float_array(self.raw_impact, "raw_impact", (N_ASSETS, N_ASSETS))
        decay = _as_float_array(self.decay_rates, "decay_rates", (N_ASSETS, N_ASSETS))
        kernel = _as_float_array(self.memory_kernel, "memory_kernel", (N_ASSETS, N_ASSETS))
        if np.any(decay <= 0):
            raise ValidationError("all decay_rates must be > 0")
        if np.any(kernel < 0):
            raise ValidationError("memory_kernel entries must be >= 0")
        if not (0 < self.exponent <= 2):
            raise ValidationError("exponent must be in (0, 2]")
        # Validate that regularization succeeds; values are held by the frozen dataclass.
        regularize_impact_matrix(raw, self.epsilon)

    @property
    def impact_matrix(self) -> np.ndarray:
        return regularize_impact_matrix(self.raw_impact, self.epsilon)

    @property
    def minimum_eigenvalue(self) -> float:
        return float(np.min(np.linalg.eigvalsh(self.impact_matrix)))

    def decay_memory(self, memory_state: object, dt: float) -> np.ndarray:
        state = _as_float_array(memory_state, "memory_state", (N_ASSETS, N_ASSETS))
        if np.any(state < 0):
            raise ValidationError("memory_state must be >= 0")
        if dt < 0 or not math.isfinite(dt):
            raise ValidationError("dt must be finite and >= 0")
        return state * np.exp(-self.decay_rates * dt)

    def add_event(self, memory_state: object, source_asset: int, mark: float = 1.0) -> np.ndarray:
        state = _as_float_array(memory_state, "memory_state", (N_ASSETS, N_ASSETS)).copy()
        if not 0 <= int(source_asset) < N_ASSETS:
            raise ValidationError("source_asset must be in [0, 3]")
        if mark < 0 or not math.isfinite(mark):
            raise ValidationError("mark must be finite and >= 0")
        state[:, int(source_asset)] += mark
        return state

    def price_impact(self, signed_order_sizes: object, memory_state: object | None = None) -> np.ndarray:
        q = _as_float_array(signed_order_sizes, "signed_order_sizes", (N_ASSETS,))
        flow = np.sign(q) * np.power(np.abs(q), self.exponent)
        impact = self.impact_matrix @ flow
        if memory_state is not None:
            m = _as_float_array(memory_state, "memory_state", (N_ASSETS, N_ASSETS))
            if np.any(m < 0):
                raise ValidationError("memory_state must be >= 0")
            impact = impact + np.sum(self.memory_kernel * m, axis=1)
        return impact

    def quadratic_cost(self, trading_rates: object) -> float:
        v = _as_float_array(trading_rates, "trading_rates", (N_ASSETS,))
        value = float(v @ self.impact_matrix @ v)
        return max(value, 0.0)  # tolerate roundoff at zero


def cancellation_intensity(
    baseline: float,
    alpha: float,
    beta: float,
    past_event_ages: Iterable[float],
    ofi: float,
    gamma: float,
) -> float:
    """Marked-point-process cancellation intensity at the current time."""
    vals = (baseline, alpha, beta, ofi, gamma)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValidationError("cancellation parameters must be finite")
    if baseline < 0 or alpha < 0 or beta <= 0 or gamma < 0:
        raise ValidationError("require baseline, alpha, gamma >= 0 and beta > 0")
    ages = [float(x) for x in past_event_ages]
    if any((not math.isfinite(a) or a < 0) for a in ages):
        raise ValidationError("event ages must be finite and >= 0")
    return float(baseline + alpha * sum(math.exp(-beta * age) for age in ages) + gamma * abs(ofi))


def adverse_selection_probability(intensity: float, tau_fill: float) -> float:
    if not math.isfinite(intensity) or intensity < 0:
        raise ValidationError("intensity must be finite and >= 0")
    if not math.isfinite(tau_fill) or tau_fill < 0:
        raise ValidationError("tau_fill must be finite and >= 0")
    return float(-math.expm1(-intensity * tau_fill))


def mlofi_top5(
    bid_volume_delta: object,
    ask_volume_delta: object,
    bid_price_delta: object,
    ask_price_delta: object,
    weights: object = (5, 4, 3, 2, 1),
) -> float:
    """Top-five-level multi-level order-flow imbalance from volume/price changes."""
    vb = _as_float_array(bid_volume_delta, "bid_volume_delta", (5,))
    va = _as_float_array(ask_volume_delta, "ask_volume_delta", (5,))
    pb = _as_float_array(bid_price_delta, "bid_price_delta", (5,))
    pa = _as_float_array(ask_price_delta, "ask_price_delta", (5,))
    w = _as_float_array(weights, "weights", (5,))
    if np.any(w < 0):
        raise ValidationError("MLOFI weights must be >= 0")
    terms = vb * (pb >= 0) - va * (pa <= 0)
    return float(w @ terms)


def hawkes_stability_audit(
    excitation: object,
    decay: object,
    radius_limit: float = DEFAULT_HAWKES_RADIUS_LIMIT,
) -> dict[str, float | bool]:
    """Audit the branching matrix Gamma = A elementwise-divided by B.

    Stability is strict: rho(Gamma) must be < radius_limit.
    """
    a = _as_float_array(excitation, "excitation", (N_ASSETS, N_ASSETS))
    b = _as_float_array(decay, "decay", (N_ASSETS, N_ASSETS))
    if np.any(a < 0) or np.any(b <= 0):
        raise ValidationError("excitation must be >= 0 and decay must be > 0")
    if not math.isfinite(radius_limit) or radius_limit <= 0:
        raise ValidationError("radius_limit must be finite and > 0")
    radius = _spectral_radius(a / b)
    return {"spectral_radius": radius, "radius_limit": float(radius_limit), "stable": bool(radius < radius_limit)}


@dataclass
class HawkesCascade:
    """Four-dimensional exponential Hawkes state for paper simulation."""
    baseline: np.ndarray
    excitation: np.ndarray
    decay: np.ndarray
    radius_limit: float = DEFAULT_HAWKES_RADIUS_LIMIT
    memory: np.ndarray | None = None

    def __post_init__(self) -> None:
        self.baseline = _as_float_array(self.baseline, "baseline", (N_ASSETS,)).copy()
        self.excitation = _as_float_array(self.excitation, "excitation", (N_ASSETS, N_ASSETS)).copy()
        self.decay = _as_float_array(self.decay, "decay", (N_ASSETS, N_ASSETS)).copy()
        if np.any(self.baseline < 0):
            raise ValidationError("baseline intensities must be >= 0")
        audit = hawkes_stability_audit(self.excitation, self.decay, self.radius_limit)
        if not audit["stable"]:
            raise ValidationError(f"Hawkes branching ratio must be < {self.radius_limit}")
        if self.memory is None:
            self.memory = np.zeros((N_ASSETS, N_ASSETS), dtype=float)
        else:
            self.memory = _as_float_array(self.memory, "memory", (N_ASSETS, N_ASSETS)).copy()
            if np.any(self.memory < 0):
                raise ValidationError("memory must be >= 0")

    def intensities(self) -> np.ndarray:
        assert self.memory is not None
        return self.baseline + np.sum(self.excitation * self.memory, axis=1)

    def step(self, dt: float, event_counts: object | None = None) -> np.ndarray:
        if not math.isfinite(dt) or dt < 0:
            raise ValidationError("dt must be finite and >= 0")
        assert self.memory is not None
        self.memory *= np.exp(-self.decay * dt)
        if event_counts is not None:
            counts = _as_float_array(event_counts, "event_counts", (N_ASSETS,))
            if np.any(counts < 0):
                raise ValidationError("event_counts must be >= 0")
            self.memory += np.broadcast_to(counts, (N_ASSETS, N_ASSETS)).copy()
        result = self.intensities()
        if not np.all(np.isfinite(result)) or np.any(result < 0):
            raise RuntimeError("non-finite or negative Hawkes intensity")
        return result


@dataclass(frozen=True)
class ExecutionTrajectory:
    times: np.ndarray
    rates: np.ndarray  # shape (n_steps, 4), signed trading velocity
    remaining_inventory: np.ndarray  # shape (n_steps+1, 4)
    half_life: float
    expected_quadratic_cost: float


def almgren_chriss_trajectory(
    initial_inventory: object,
    horizon: float,
    n_steps: int,
    impact_matrix: object,
    covariance: object,
    risk_aversion: float,
    half_life: float | None = None,
) -> ExecutionTrajectory:
    """Deterministic half-life-shaped liquidation trajectory.

    The exponential rate is normalized on [0,T], so remaining inventory reaches
    exactly zero at the horizon rather than leaving an unliquidated exponential tail.
    This is a transparent discrete AC-style baseline, not a full stochastic-control solver.
    """
    q0 = _as_float_array(initial_inventory, "initial_inventory", (N_ASSETS,))
    impact = regularize_impact_matrix(impact_matrix)
    sigma = _as_float_array(covariance, "covariance", (N_ASSETS, N_ASSETS))
    sigma = 0.5 * (sigma + sigma.T)
    min_eig = float(np.min(np.linalg.eigvalsh(sigma)))
    if min_eig < -1e-9:
        raise ValidationError("covariance must be positive semidefinite")
    if horizon <= 0 or not math.isfinite(horizon):
        raise ValidationError("horizon must be finite and > 0")
    if not isinstance(n_steps, (int, np.integer)) or n_steps < 1:
        raise ValidationError("n_steps must be a positive integer")
    if risk_aversion < 0 or not math.isfinite(risk_aversion):
        raise ValidationError("risk_aversion must be finite and >= 0")
    effective = impact + risk_aversion * sigma
    scale = float(np.trace(effective) / N_ASSETS)
    if half_life is None:
        # Higher variance/risk raises urgency; strict positive lower bound prevents division by zero.
        vol_scale = float(np.trace(sigma) / N_ASSETS)
        urgency = math.sqrt(max(risk_aversion * vol_scale, 1e-12) / max(scale, 1e-12))
        half_life = min(max(0.25 * horizon / max(urgency, 1e-3), horizon / (100 * n_steps)), 100 * horizon)
    if not math.isfinite(half_life) or half_life <= 0:
        raise ValidationError("half_life must be finite and > 0")
    dt = horizon / n_steps
    times = np.linspace(0.0, horizon, n_steps + 1)
    k = math.log(2.0) / half_life
    # Average velocity in interval [t_i,t_{i+1}] integrates to each interval's target fraction.
    weights = np.exp(-k * times[:-1]) - np.exp(-k * times[1:])
    denom = 1.0 - math.exp(-k * horizon)
    if denom <= 0 or not math.isfinite(denom):
        weights = np.full(n_steps, 1.0 / n_steps)
    else:
        weights = weights / denom
    rates = -(weights[:, None] * q0[None, :] / dt)
    remaining = np.vstack([q0, q0[None, :] + np.cumsum(rates * dt, axis=0)])
    # Floating error at terminal time should not leave a residual.
    remaining[-1, :] = 0.0
    quad = 0.0
    for v in rates:
        quad += dt * float(v @ effective @ v)
    return ExecutionTrajectory(times, rates, remaining, float(half_life), float(max(quad, 0.0)))


@dataclass(frozen=True)
class NoTradeBand:
    target: float
    lower: float
    upper: float
    base_half_width: float
    buy_spread_penalty: float
    sell_spread_penalty: float
    fee_drag: float


def compute_no_trade_band(
    target_inventory: float,
    transaction_cost: float,
    volatility: float,
    risk_aversion: float,
    buy_spread_penalty: float = 0.0,
    sell_spread_penalty: float = 0.0,
    fee_drag: float = 0.0,
) -> NoTradeBand:
    vals = [target_inventory, transaction_cost, volatility, risk_aversion,
            buy_spread_penalty, sell_spread_penalty, fee_drag]
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValidationError("band parameters must be finite")
    if transaction_cost < 0 or volatility < 0 or risk_aversion <= 0:
        raise ValidationError("require cost, volatility >= 0 and risk_aversion > 0")
    if min(buy_spread_penalty, sell_spread_penalty, fee_drag) < 0:
        raise ValidationError("spread penalties and fee_drag must be >= 0")
    base = ((3.0 * transaction_cost * volatility**2) / (4.0 * risk_aversion)) ** (1.0 / 3.0)
    lower = target_inventory - (base + buy_spread_penalty + fee_drag)
    upper = target_inventory + (base + sell_spread_penalty + fee_drag)
    return NoTradeBand(float(target_inventory), float(lower), float(upper), float(base),
                       float(buy_spread_penalty), float(sell_spread_penalty), float(fee_drag))


def inventory_action(inventory: float, band: NoTradeBand, tolerance: float = 1e-12) -> str:
    if not math.isfinite(inventory) or tolerance < 0:
        raise ValidationError("inventory must be finite and tolerance >= 0")
    if band.lower - tolerance <= inventory <= band.upper + tolerance:
        return "NO_TRADE"
    return "BUY" if inventory < band.lower else "SELL"


@dataclass(frozen=True)
class FeeBreakdown:
    stt_sell: float
    stamp_buy: float
    exchange: float
    sebi: float
    brokerage: float
    gst: float
    total: float


def statutory_fees(buy_turnover: float, sell_turnover: float, executed_legs: int) -> FeeBreakdown:
    if not all(math.isfinite(float(v)) for v in (buy_turnover, sell_turnover)):
        raise ValidationError("turnover must be finite")
    if buy_turnover < 0 or sell_turnover < 0:
        raise ValidationError("turnover must be >= 0")
    if not isinstance(executed_legs, (int, np.integer)) or executed_legs < 0:
        raise ValidationError("executed_legs must be a non-negative integer")
    stt = float(sell_turnover * STT_SELL_RATE)
    stamp = float(buy_turnover * STAMP_BUY_RATE)
    total_turnover = float(buy_turnover + sell_turnover)
    exchange = total_turnover * EXCHANGE_RATE
    sebi = total_turnover * SEBI_RATE
    brokerage = float(executed_legs * BROKERAGE_PER_LEG_INR)
    gst = GST_RATE * (exchange + sebi + brokerage)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return FeeBreakdown(stt, stamp, exchange, sebi, brokerage, gst, float(total))


def net_alpha_gate(expected_gross_alpha: float, fees: float) -> dict[str, float | bool]:
    if not math.isfinite(expected_gross_alpha) or not math.isfinite(fees) or fees < 0:
        raise ValidationError("gross alpha must be finite and fees finite and >= 0")
    net = float(expected_gross_alpha - fees)
    return {"gross_alpha": float(expected_gross_alpha), "fees": float(fees), "net_alpha": net, "approved": bool(net > 0.0)}


def beta_posterior_fractional_kelly(
    alpha_wins: float,
    beta_losses: float,
    net_odds: float,
    scale: float = 0.25,
    max_fraction: float = 0.10,
) -> float:
    """Posterior-mean Kelly fraction; never exceeds the 10% ceiling."""
    vals = (alpha_wins, beta_losses, net_odds, scale, max_fraction)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValidationError("Kelly inputs must be finite")
    if alpha_wins <= 0 or beta_losses <= 0 or net_odds <= 0:
        raise ValidationError("Beta parameters and net_odds must be > 0")
    if scale < 0 or not (0 < max_fraction <= 0.10):
        raise ValidationError("scale must be >= 0 and max_fraction in (0, 0.10]")
    p = alpha_wins / (alpha_wins + beta_losses)
    full = (p * (net_odds + 1.0) - 1.0) / net_odds
    return float(min(max(full * scale, 0.0), max_fraction))


def friction_aware_advantage(
    gross_advantage: float,
    statutory_fees: float,
    inventory: float,
    inventory_variance: float,
    risk_penalty: float,
) -> float:
    vals = (gross_advantage, statutory_fees, inventory, inventory_variance, risk_penalty)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValidationError("advantage inputs must be finite")
    if statutory_fees < 0 or inventory_variance < 0 or risk_penalty < 0:
        raise ValidationError("fees, inventory_variance, risk_penalty must be >= 0")
    return float(gross_advantage - statutory_fees - risk_penalty * inventory**2 * inventory_variance)


def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(x, 0.0)


class ContinuousActorCritic:
    """Small deterministic NumPy actor-critic with a 16D state and 3 bounded actions.

    The policy uses a two-hidden-layer tanh network for its mean and a learned
    state-conditioned diagonal log standard deviation. The critic has two hidden
    layers and predicts scalar value. Update methods are transparent research
    baselines and do not imply successful strategy training.
    """
    def __init__(self, seed: int = 55, state_dim: int = 16, action_dim: int = 3,
                 hidden_1: int = 32, hidden_2: int = 16):
        if state_dim != 16 or action_dim != 3 or hidden_1 < 1 or hidden_2 < 1:
            raise ValidationError("Cycle 55 actor-critic requires state_dim=16 and action_dim=3")
        self.state_dim = state_dim
        self.action_dim = action_dim
        rng = np.random.default_rng(seed)
        def init(a: int, b: int) -> np.ndarray:
            return rng.normal(0.0, math.sqrt(2.0 / (a + b)), size=(a, b))
        self.actor = {
            "w1": init(state_dim, hidden_1), "b1": np.zeros(hidden_1),
            "w2": init(hidden_1, hidden_2), "b2": np.zeros(hidden_2),
            "wm": init(hidden_2, action_dim), "bm": np.zeros(action_dim),
            "ws": init(hidden_2, action_dim), "bs": np.full(action_dim, -0.5),
        }
        self.critic = {
            "w1": init(state_dim, hidden_1), "b1": np.zeros(hidden_1),
            "w2": init(hidden_1, hidden_2), "b2": np.zeros(hidden_2),
            "wv": init(hidden_2, 1), "bv": np.zeros(1),
        }

    def _actor_forward(self, state: object) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        s = _as_float_array(state, "state", (self.state_dim,))
        p = self.actor
        h1_pre = s @ p["w1"] + p["b1"]
        h1 = np.tanh(h1_pre)
        h2_pre = h1 @ p["w2"] + p["b2"]
        h2 = np.tanh(h2_pre)
        mean_pre = h2 @ p["wm"] + p["bm"]
        mean = np.tanh(mean_pre)
        log_std = np.clip(h2 @ p["ws"] + p["bs"], -5.0, 1.0)
        return mean, {"s": s, "h1": h1, "h2": h2, "mean_pre": mean_pre, "mean": mean, "log_std": log_std}

    def policy(self, state: object) -> dict[str, np.ndarray]:
        mean, cache = self._actor_forward(state)
        return {"mean": mean.copy(), "log_std": cache["log_std"].copy(),
                "std": np.exp(cache["log_std"]), "bounded_mean": np.clip(mean, -1.0, 1.0)}

    def sample_action(self, state: object, seed: int = 0, stochastic: bool = True) -> np.ndarray:
        pol = self.policy(state)
        if stochastic:
            z = np.random.default_rng(seed).normal(pol["mean"], pol["std"])
            action = np.tanh(z)
        else:
            action = pol["mean"]
        return np.clip(action, -1.0, 1.0)

    def value(self, state: object) -> float:
        s = _as_float_array(state, "state", (self.state_dim,))
        p = self.critic
        h1 = np.tanh(s @ p["w1"] + p["b1"])
        h2 = np.tanh(h1 @ p["w2"] + p["b2"])
        return float((h2 @ p["wv"] + p["bv"])[0])

    def update_critic(self, state: object, target_value: float, learning_rate: float = 1e-3) -> float:
        s = _as_float_array(state, "state", (self.state_dim,))
        if not math.isfinite(target_value) or learning_rate <= 0 or not math.isfinite(learning_rate):
            raise ValidationError("target_value must be finite and learning_rate > 0")
        p = self.critic
        h1_pre = s @ p["w1"] + p["b1"]; h1 = np.tanh(h1_pre)
        h2_pre = h1 @ p["w2"] + p["b2"]; h2 = np.tanh(h2_pre)
        value = float((h2 @ p["wv"] + p["bv"])[0])
        error = value - float(target_value)
        old_wv = p["wv"].copy()
        grad_wv = h2[:, None] * error
        grad_bv = np.array([error])
        grad_h2 = (old_wv[:, 0] * error) * (1.0 - h2**2)
        grad_w2 = np.outer(h1, grad_h2)
        grad_b2 = grad_h2.copy()
        grad_h1 = (p["w2"] @ grad_h2) * (1.0 - h1**2)
        grad_w1 = np.outer(s, grad_h1)
        grad_b1 = grad_h1.copy()
        for key, grad in (("wv", grad_wv), ("bv", grad_bv), ("w2", grad_w2),
                          ("b2", grad_b2), ("w1", grad_w1), ("b1", grad_b1)):
            p[key] -= learning_rate * grad
        return float(0.5 * error**2)

    def update_actor(self, state: object, action: object, advantage: float, learning_rate: float = 1e-3) -> float:
        s = _as_float_array(state, "state", (self.state_dim,))
        a = _as_float_array(action, "action", (self.action_dim,))
        if np.any(np.abs(a) > 1.0 + 1e-12):
            raise ValidationError("action components must be in [-1, 1]")
        if not math.isfinite(advantage) or not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValidationError("advantage finite and learning_rate > 0 required")
        _, c = self._actor_forward(s); p = self.actor
        # Deterministic policy-gradient style local update toward actions when advantage > 0.
        err = np.arctanh(np.clip(a, -0.999999, 0.999999)) - c["mean_pre"]
        grad_mean_pre = -float(advantage) * err * (1.0 - c["mean"]**2)
        grad_wm = np.outer(c["h2"], grad_mean_pre)
        grad_bm = grad_mean_pre
        grad_h2 = p["wm"] @ grad_mean_pre
        grad_h2 *= (1.0 - c["h2"]**2)
        grad_w2 = np.outer(c["h1"], grad_h2)
        grad_b2 = grad_h2
        grad_h1 = (p["w2"] @ grad_h2) * (1.0 - c["h1"]**2)
        grad_w1 = np.outer(s, grad_h1)
        grad_b1 = grad_h1
        for key, grad in (("wm", grad_wm), ("bm", grad_bm), ("w2", grad_w2),
                          ("b2", grad_b2), ("w1", grad_w1), ("b1", grad_b1)):
            p[key] -= learning_rate * grad
        return float(np.linalg.norm(grad_mean_pre))


def squad_consensus(
    *,
    manager_approved: bool,
    queue_risk_clear: bool,
    volatility_risk_clear: bool,
    net_alpha_positive: bool,
    paper_only: bool = True,
) -> dict[str, object]:
    """Fail-closed four-agent proposal review; never dispatches an order."""
    votes = {
        "Manager Abhi": bool(manager_approved),
        "Alex (L3 queue risk)": bool(queue_risk_clear),
        "Emily (rough volatility/regime)": bool(volatility_risk_clear),
        "Max (statutory net alpha/Kelly)": bool(net_alpha_positive),
    }
    approved = bool(paper_only and all(votes.values()))
    reasons = [name for name, vote in votes.items() if not vote]
    if not paper_only:
        reasons.append("live execution prohibited by fail-closed policy")
    return {"approved_for_paper_simulation": approved, "votes": votes,
            "rejection_reasons": reasons, "live_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED}


def dispatch_live_order(*args: object, **kwargs: object) -> None:
    """Live dispatch is deliberately unavailable in every configuration."""
    raise PermissionError("Cycle 55 is paper-only: live order dispatch is permanently disabled")


def rough_volterra_kernel(t: float, hurst: float = 0.07) -> float:
    """Singular rough kernel K(t)=t^(H-1/2)/Gamma(H+1/2), t>0."""
    if not math.isfinite(t) or t <= 0:
        raise ValidationError("t must be finite and > 0")
    if not math.isfinite(hurst) or not (0 < hurst < 0.5):
        raise ValidationError("hurst must be in (0, 0.5)")
    return float(t ** (hurst - 0.5) / math.gamma(hurst + 0.5))


def reference_demo() -> dict[str, object]:
    """Deterministic output used by the example and clean-archive checks."""
    raw_g = np.array([[0.7, 0.1, 0.04, 0.02], [0.1, 0.6, 0.03, 0.02],
                      [0.04, 0.03, 0.5, 0.05], [0.02, 0.02, 0.05, 0.4]])
    decay = np.full((4, 4), 1.0)
    kernel = np.full((4, 4), 0.02)
    cross = CrossImpactModel(raw_g, decay, kernel, exponent=1.0)
    memory = cross.add_event(np.zeros((4, 4)), 1, 2.0)
    impact = cross.price_impact(np.array([100.0, -50.0, 20.0, 0.0]), memory)
    cancel = cancellation_intensity(0.2, 0.4, 2.0, [0.0, 0.1, 0.4], ofi=1.2, gamma=0.05)
    adv = adverse_selection_probability(cancel, 0.25)
    hawkes = hawkes_stability_audit(np.eye(4) * 0.2, np.ones((4, 4)) * 1.0)
    trajectory = almgren_chriss_trajectory(np.array([10., -4., 2., 1.]), 10., 20,
                                           cross.impact_matrix, np.eye(4) * 0.01, 0.2, half_life=2.5)
    band = compute_no_trade_band(0.0, 0.01, 0.2, 1.0, 0.01, 0.015, 0.005)
    fees = statutory_fees(15000.0, 12000.0, 2)
    gate = net_alpha_gate(90.0, fees.total)
    kelly = beta_posterior_fractional_kelly(12.0, 8.0, 1.2)
    actor = ContinuousActorCritic(seed=55)
    state = np.linspace(-0.5, 0.5, 16)
    action = actor.sample_action(state, seed=123, stochastic=True)
    consensus = squad_consensus(manager_approved=True, queue_risk_clear=True,
                                volatility_risk_clear=True, net_alpha_positive=bool(gate["approved"]))
    return {
        "cycle": 55, "engine": "HF-CEH-LOS", "assets": list(ASSETS),
        "impact_matrix_min_eigenvalue": cross.minimum_eigenvalue,
        "cross_impact_delta_price": impact.tolist(),
        "cancellation_intensity": cancel, "adverse_selection_probability": adv,
        "hawkes_stability": hawkes,
        "trajectory_terminal_inventory": trajectory.remaining_inventory[-1].tolist(),
        "trajectory_quadratic_cost": trajectory.expected_quadratic_cost,
        "no_trade_band": {"lower": band.lower, "upper": band.upper,
                          "action_at_target": inventory_action(band.target, band)},
        "statutory_fees": fees.__dict__, "net_alpha_gate": gate,
        "fractional_kelly": kelly, "actor_policy_action": action.tolist(),
        "squad_consensus": consensus, "safety": {
            "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
            "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED,
            "PAPER_LEDGER_EPOCH": PAPER_LEDGER_EPOCH,
            "INITIAL_CAPITAL_INR": INITIAL_CAPITAL_INR,
        }
    }
