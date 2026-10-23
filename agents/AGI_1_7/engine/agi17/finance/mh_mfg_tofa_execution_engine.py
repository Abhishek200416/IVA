"""Cycle 56 MH-MFG-TOFA offline quantitative research engine.

This module is a deterministic, paper-only research implementation.  It contains
no broker adapter or live order path.  NumPy is the sole runtime dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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
            raise ValidationError("Cycle 56 actor-critic requires state_dim=16 and action_dim=3")
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
    raise PermissionError("Cycle 56 is paper-only: live order dispatch is permanently disabled")


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
        "cycle": 56, "engine": "MH-MFG-TOFA", "assets": list(ASSETS),
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

# ---------------------------------------------------------------------------
# Cycle 56: multi-horizon continuous-time mean-field game and toxicity model.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MFGConfig:
    """Configuration for the discretized market-maker mean-field game.

    The solver uses a finite inventory grid and a finite set of quote candidates.
    Its equilibrium is therefore a numerical approximation to the continuous-time
    HJB/FPK system, not a proof of a continuous-state Nash equilibrium.
    """
    horizon: float = 1.0
    n_steps: int = 32
    inventory_limit: int = 4
    risk_aversion: float = 0.25
    inventory_volatility: float = 0.20
    mean_field_coupling: float = 0.025
    noise_arrival_rate: float = 0.45
    spread_sensitivity: float = 7.0
    base_half_spread: float = 0.025
    spread_candidates: tuple[float, ...] = (0.0, 0.01, 0.025, 0.05, 0.08, 0.12)
    toxicity_penalty: float = 0.12
    toxic_spread_kappa: float = 0.015
    mlofi_toxicity_coefficient: float = 0.025
    statutory_fee_per_fill: float = 0.002
    terminal_inventory_penalty: float = 0.4
    initial_inventory_mean: float = 0.0
    initial_inventory_sd: float = 1.25
    fixed_point_iterations: int = 30
    fixed_point_tolerance: float = 2e-3
    relaxation: float = 0.45

    def __post_init__(self) -> None:
        numeric = (self.horizon, self.risk_aversion, self.inventory_volatility,
                   self.mean_field_coupling, self.noise_arrival_rate,
                   self.spread_sensitivity, self.base_half_spread,
                   self.toxicity_penalty, self.toxic_spread_kappa,
                   self.mlofi_toxicity_coefficient, self.statutory_fee_per_fill, self.terminal_inventory_penalty,
                   self.initial_inventory_mean, self.initial_inventory_sd,
                   self.fixed_point_tolerance, self.relaxation)
        if not all(math.isfinite(float(x)) for x in numeric):
            raise ValidationError("MFG configuration values must be finite")
        if self.horizon <= 0 or isinstance(self.n_steps, (bool, np.bool_)) or not isinstance(self.n_steps, (int, np.integer)) or self.n_steps < 1 or isinstance(self.inventory_limit, (bool, np.bool_)) or not isinstance(self.inventory_limit, (int, np.integer)) or self.inventory_limit < 1:
            raise ValidationError("horizon must be positive and n_steps/inventory_limit must be positive integers")
        if self.risk_aversion <= 0 or self.inventory_volatility < 0:
            raise ValidationError("risk_aversion must be > 0 and inventory_volatility >= 0")
        if self.mean_field_coupling < 0 or self.noise_arrival_rate < 0:
            raise ValidationError("mean-field coupling and noise arrival rate must be >= 0")
        if self.spread_sensitivity <= 0 or self.base_half_spread < 0:
            raise ValidationError("spread_sensitivity must be > 0 and base_half_spread >= 0")
        if min(self.toxicity_penalty, self.toxic_spread_kappa, self.mlofi_toxicity_coefficient,
               self.statutory_fee_per_fill, self.terminal_inventory_penalty) < 0:
            raise ValidationError("penalties and fee per fill must be >= 0")
        if self.initial_inventory_sd <= 0:
            raise ValidationError("initial_inventory_sd must be > 0")
        if isinstance(self.fixed_point_iterations, (bool, np.bool_)) or not isinstance(self.fixed_point_iterations, (int, np.integer)) or self.fixed_point_iterations < 1 or self.fixed_point_tolerance <= 0:
            raise ValidationError("fixed-point iterations must be a positive integer and tolerance positive")
        if not (0 < self.relaxation <= 1):
            raise ValidationError("relaxation must be in (0, 1]")
        c = np.asarray(self.spread_candidates, dtype=float)
        if c.ndim != 1 or c.size < 1 or not np.all(np.isfinite(c)) or np.any(c < 0):
            raise ValidationError("spread_candidates must be a nonempty finite nonnegative sequence")
        if np.any(np.diff(c) < 0):
            raise ValidationError("spread_candidates must be sorted in nondecreasing order")


@dataclass(frozen=True)
class MFGEquilibrium:
    """Numerical HJB/FPK fixed-point solution for competing market makers."""
    times: np.ndarray
    inventory_grid: np.ndarray
    value_function: np.ndarray
    density: np.ndarray
    optimal_bid_half_spread: np.ndarray
    optimal_ask_half_spread: np.ndarray
    bid_fill_intensity: np.ndarray
    ask_fill_intensity: np.ndarray
    aggregate_order_rate: np.ndarray
    fixed_point_iterations: int
    fixed_point_residual: float
    converged: bool

    @property
    def density_mass_error(self) -> float:
        return float(np.max(np.abs(np.sum(self.density, axis=1) - 1.0)))


@dataclass(frozen=True)
class ToxicFlowSplit:
    toxic_buy_rate: float
    toxic_sell_rate: float
    noise_buy_rate: float
    noise_sell_rate: float


def split_toxic_and_noise_flow(
    noise_arrival_rate: float,
    toxic_intensity: float,
    directional_toxicity: float,
) -> ToxicFlowSplit:
    """Split nonnegative noise flow and marked toxic flow by direction.

    ``directional_toxicity`` is clipped only by validation to [-1,1]; positive
    means informed buy pressure (ask-side market-maker exposure), negative means
    informed sell pressure (bid-side exposure).
    """
    vals = (noise_arrival_rate, toxic_intensity, directional_toxicity)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValidationError("flow split inputs must be finite")
    if noise_arrival_rate < 0 or toxic_intensity < 0:
        raise ValidationError("flow rates must be >= 0")
    if not -1.0 <= directional_toxicity <= 1.0:
        raise ValidationError("directional_toxicity must be in [-1,1]")
    pos = max(directional_toxicity, 0.0)
    neg = max(-directional_toxicity, 0.0)
    return ToxicFlowSplit(toxic_intensity * pos, toxic_intensity * neg,
                          float(noise_arrival_rate), float(noise_arrival_rate))


@dataclass
class ToxicFlowHawkes:
    """Scalar marked self-exciting toxic-flow intensity with MLOFI modulation."""
    baseline: float = 0.12
    excitation: float = 0.35
    decay: float = 2.2
    mlofi_coefficient: float = 0.025
    event_memory: float = 0.0

    def __post_init__(self) -> None:
        vals = (self.baseline, self.excitation, self.decay,
                self.mlofi_coefficient, self.event_memory)
        if not all(math.isfinite(float(x)) for x in vals):
            raise ValidationError("toxic Hawkes parameters must be finite")
        if self.baseline < 0 or self.excitation < 0 or self.mlofi_coefficient < 0:
            raise ValidationError("baseline, excitation and MLOFI coefficient must be >= 0")
        if self.decay <= 0 or self.event_memory < 0:
            raise ValidationError("decay must be > 0 and event_memory >= 0")

    def intensity(self, mlofi: float = 0.0) -> float:
        if not math.isfinite(mlofi):
            raise ValidationError("MLOFI must be finite")
        return float(self.baseline + self.excitation * self.event_memory
                     + self.mlofi_coefficient * abs(mlofi))

    def step(self, dt: float, event_count: float = 0.0, mlofi: float = 0.0) -> float:
        if not math.isfinite(dt) or dt < 0:
            raise ValidationError("dt must be finite and >= 0")
        if not math.isfinite(event_count) or event_count < 0:
            raise ValidationError("event_count must be finite and >= 0")
        # Update memory by decay, then append newly observed event marks.
        self.event_memory = self.event_memory * math.exp(-self.decay * dt) + event_count
        return self.intensity(mlofi)


def mlofi_cancellation_hazard(
    baseline: float,
    alpha: float,
    beta: float,
    elapsed_time: float,
    theta: float,
    mlofi: float,
) -> float:
    """Queue cancellation hazard λ₀ + α exp(-β Δt) + θ |MLOFI|."""
    vals = (baseline, alpha, beta, elapsed_time, theta, mlofi)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValidationError("cancellation hazard parameters must be finite")
    if baseline < 0 or alpha < 0 or beta <= 0 or elapsed_time < 0 or theta < 0:
        raise ValidationError("invalid cancellation hazard parameters")
    return float(baseline + alpha * math.exp(-beta * elapsed_time) + theta * abs(mlofi))


def toxic_spread_expansion(base_spread: float, toxic_intensity: float, kappa: float) -> float:
    """Return symmetric total spread widened linearly with toxic-flow intensity."""
    vals = (base_spread, toxic_intensity, kappa)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValidationError("spread expansion inputs must be finite")
    if base_spread < 0 or toxic_intensity < 0 or kappa < 0:
        raise ValidationError("spread expansion inputs must be >= 0")
    return float(base_spread + kappa * toxic_intensity)


def _normalize_density(density: np.ndarray) -> np.ndarray:
    density = np.maximum(np.asarray(density, dtype=float), 0.0)
    total = float(density.sum())
    if not math.isfinite(total) or total <= 0:
        raise RuntimeError("FPK density lost all probability mass")
    return density / total


def _solve_mfg_hjb(
    cfg: MFGConfig,
    q: np.ndarray,
    times: np.ndarray,
    density_guess: np.ndarray,
    toxicity_intensity: np.ndarray,
    directional_toxicity: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_steps = cfg.n_steps
    n_q = q.size
    dt = cfg.horizon / n_steps
    candidate = np.asarray(cfg.spread_candidates, dtype=float)
    v = np.zeros((n_steps + 1, n_q), dtype=float)
    v[-1] = -0.5 * cfg.terminal_inventory_penalty * q * q
    bid_spread = np.zeros((n_steps, n_q), dtype=float)
    ask_spread = np.zeros((n_steps, n_q), dtype=float)
    bid_rate = np.zeros((n_steps, n_q), dtype=float)
    ask_rate = np.zeros((n_steps, n_q), dtype=float)
    # Intensities stay bounded because spreads are nonnegative and rates decay in spread.
    for t_idx in range(n_steps - 1, -1, -1):
        next_v = v[t_idx + 1]
        aggregate = float(q @ density_guess[t_idx])
        toxic = float(toxicity_intensity[t_idx])
        direction = float(directional_toxicity[t_idx])
        share_buy = max(direction, 0.0)
        share_sell = max(-direction, 0.0)
        extra_spread = cfg.toxic_spread_kappa * toxic
        total_best_hamiltonian = np.zeros(n_q, dtype=float)
        for qi, inventory in enumerate(q):
            drift_reward = cfg.mean_field_coupling * aggregate * inventory
            holding_cost = 0.5 * cfg.risk_aversion * cfg.inventory_volatility**2 * inventory**2
            best_bid = 0.0
            best_ask = 0.0
            if qi < n_q - 1:  # cannot increase inventory beyond top boundary
                noise_plus_toxic = cfg.noise_arrival_rate + toxic * share_sell
                delta_value = next_v[qi + 1] - next_v[qi]
                best_bid = 0.0  # zero means do not quote if all candidate surpluses are negative
                for offset in candidate:
                    delta = cfg.base_half_spread + extra_spread + float(offset)
                    rate = noise_plus_toxic * math.exp(-cfg.spread_sensitivity * delta)
                    toxic_share = (toxic * share_sell / max(noise_plus_toxic, 1e-12)) if noise_plus_toxic > 0 else 0.0
                    fill_surplus = delta + delta_value - cfg.statutory_fee_per_fill - cfg.toxicity_penalty * toxic_share
                    objective = rate * fill_surplus
                    if objective > best_bid:
                        best_bid = objective
                        bid_spread[t_idx, qi] = delta
                        bid_rate[t_idx, qi] = rate
            if qi > 0:  # cannot decrease inventory beyond bottom boundary
                noise_plus_toxic = cfg.noise_arrival_rate + toxic * share_buy
                delta_value = next_v[qi - 1] - next_v[qi]
                best_ask = 0.0  # zero means do not quote if all candidate surpluses are negative
                for offset in candidate:
                    delta = cfg.base_half_spread + extra_spread + float(offset)
                    rate = noise_plus_toxic * math.exp(-cfg.spread_sensitivity * delta)
                    toxic_share = (toxic * share_buy / max(noise_plus_toxic, 1e-12)) if noise_plus_toxic > 0 else 0.0
                    fill_surplus = delta + delta_value - cfg.statutory_fee_per_fill - cfg.toxicity_penalty * toxic_share
                    objective = rate * fill_surplus
                    if objective > best_ask:
                        best_ask = objective
                        ask_spread[t_idx, qi] = delta
                        ask_rate[t_idx, qi] = rate
            if not math.isfinite(best_bid):
                best_bid = 0.0
            if not math.isfinite(best_ask):
                best_ask = 0.0
            total_best_hamiltonian[qi] = best_bid + best_ask + drift_reward - holding_cost
        v[t_idx] = next_v + dt * total_best_hamiltonian
    return v, bid_spread, ask_spread, bid_rate, ask_rate


def _solve_mfg_fpk(
    cfg: MFGConfig,
    q: np.ndarray,
    initial_density: np.ndarray,
    bid_rate: np.ndarray,
    ask_rate: np.ndarray,
) -> np.ndarray:
    """Forward Kolmogorov equation for the inventory birth-death chain."""
    n_steps = cfg.n_steps
    dt = cfg.horizon / n_steps
    n_q = q.size
    density = np.zeros((n_steps + 1, n_q), dtype=float)
    density[0] = _normalize_density(initial_density.copy())
    for t_idx in range(n_steps):
        lam_b = bid_rate[t_idx].copy()
        lam_a = ask_rate[t_idx].copy()
        lam_b[-1] = 0.0
        lam_a[0] = 0.0
        # Adaptive Euler substepping keeps the Markov transition probabilities nonnegative.
        max_out = float(np.max(lam_b + lam_a))
        n_sub = max(1, int(math.ceil(dt * max_out / 0.8)))
        ds = dt / n_sub
        mass = density[t_idx].copy()
        for _ in range(n_sub):
            out_b = lam_b * mass
            out_a = lam_a * mass
            nxt = mass - ds * (out_b + out_a)
            nxt[1:] += ds * out_b[:-1]
            nxt[:-1] += ds * out_a[1:]
            # Local negative roundoff can only be numerical; clipping plus normalization is conservative.
            nxt = _normalize_density(np.maximum(nxt, 0.0))
            mass = nxt
        density[t_idx + 1] = mass
    return density


def solve_mean_field_game(
    config: MFGConfig | None = None,
    toxicity_intensity_path: object | None = None,
    directional_toxicity_path: object | None = None,
    mlofi_path: object | None = None,
) -> MFGEquilibrium:
    """Solve a finite-grid mean-field market-making game by HJB/FPK iteration.

    Each market maker's HJB chooses bid/ask half-spreads from a candidate set.
    The FPK equation propagates the population distribution across integer
    inventory states.  Its mean inventory (the specified aggregate-flow proxy)
    shifts mid-price drift through the mean-field coupling.  Relaxed fixed-point
    iteration seeks consistency between the HJB policy and FPK density.
    """
    cfg = config or MFGConfig()
    n_steps = cfg.n_steps
    q = np.arange(-cfg.inventory_limit, cfg.inventory_limit + 1, dtype=float)
    times = np.linspace(0.0, cfg.horizon, n_steps + 1)
    def time_path(value: object | None, default: float, name: str) -> np.ndarray:
        if value is None:
            return np.full(n_steps, default, dtype=float)
        path = _as_float_array(value, name, (n_steps,)).copy()
        return path
    toxicity = time_path(toxicity_intensity_path, 0.12, "toxicity_intensity_path")
    direction = time_path(directional_toxicity_path, 0.0, "directional_toxicity_path")
    ofi = time_path(mlofi_path, 0.0, "mlofi_path")
    if np.any(toxicity < 0):
        raise ValidationError("toxicity intensities must be >= 0")
    if np.any(np.abs(direction) > 1.0):
        raise ValidationError("directional toxicity must be in [-1,1]")
    if not np.all(np.isfinite(ofi)):
        raise ValidationError("MLOFI path must be finite")
    toxicity = toxicity + cfg.mlofi_toxicity_coefficient * np.abs(ofi)  # MLOFI augments marked toxic-flow intensity
    initial = np.exp(-0.5 * ((q - cfg.initial_inventory_mean) / cfg.initial_inventory_sd)**2)
    initial = _normalize_density(initial)
    density_guess = np.repeat(initial[None, :], n_steps + 1, axis=0)
    residual = float("inf")
    converged = False
    values = bid_spread = ask_spread = bid_rate = ask_rate = None
    for iteration in range(1, cfg.fixed_point_iterations + 1):
        values, bid_spread, ask_spread, bid_rate, ask_rate = _solve_mfg_hjb(
            cfg, q, times, density_guess, toxicity, direction
        )
        density_new = _solve_mfg_fpk(cfg, q, initial, bid_rate, ask_rate)
        residual = float(np.max(np.abs(density_new - density_guess)))
        density_guess = (1.0 - cfg.relaxation) * density_guess + cfg.relaxation * density_new
        density_guess[0] = initial
        # Maintain exact normalization after fixed-point relaxation.
        for i in range(1, n_steps + 1):
            density_guess[i] = _normalize_density(density_guess[i])
        if residual <= cfg.fixed_point_tolerance:
            converged = True
            break
    # Recompute the value/policy against the final population density for consistent outputs.
    values, bid_spread, ask_spread, bid_rate, ask_rate = _solve_mfg_hjb(
        cfg, q, times, density_guess, toxicity, direction
    )
    density_final = _solve_mfg_fpk(cfg, q, initial, bid_rate, ask_rate)
    final_residual = float(np.max(np.abs(density_final - density_guess)))
    aggregate = density_final @ q
    return MFGEquilibrium(
        times=times, inventory_grid=q, value_function=values, density=density_final,
        optimal_bid_half_spread=bid_spread, optimal_ask_half_spread=ask_spread,
        bid_fill_intensity=bid_rate, ask_fill_intensity=ask_rate,
        aggregate_order_rate=aggregate, fixed_point_iterations=iteration,
        fixed_point_residual=final_residual, converged=bool(converged or final_residual <= cfg.fixed_point_tolerance),
    )


def solve_multi_horizon_mean_field_game(
    horizons: Sequence[float],
    config: MFGConfig | None = None,
    *,
    toxicity_intensity_path: object | None = None,
    directional_toxicity_path: object | None = None,
    mlofi_path: object | None = None,
) -> dict[float, MFGEquilibrium]:
    """Solve the HJB/FPK equilibrium independently at several horizons.

    Each horizon uses the same structural parameters and grid resolution; only
    the terminal time changes. This makes horizon effects auditable rather than
    silently extrapolating a single-horizon quote policy.
    """
    hs = [float(x) for x in horizons]
    if not hs or any((not math.isfinite(x) or x <= 0) for x in hs):
        raise ValidationError("horizons must be a nonempty sequence of finite positive values")
    if len(set(hs)) != len(hs):
        raise ValidationError("horizons must be unique")
    base = config or MFGConfig()
    results: dict[float, MFGEquilibrium] = {}
    for horizon in hs:
        cfg = replace(base, horizon=horizon)
        results[horizon] = solve_mean_field_game(
            cfg, toxicity_intensity_path=toxicity_intensity_path,
            directional_toxicity_path=directional_toxicity_path, mlofi_path=mlofi_path
        )
    return results


@dataclass(frozen=True)
class RoughVolterraLift:
    hurst: float
    weights: np.ndarray
    decay_rates: np.ndarray
    t_min: float
    t_max: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.hurst) or not (0 < self.hurst < 0.5):
            raise ValidationError("hurst must be in (0, 0.5)")
        w = _as_float_array(self.weights, "weights")
        g = _as_float_array(self.decay_rates, "decay_rates")
        if w.ndim != 1 or g.shape != w.shape or w.size < 1:
            raise ValidationError("lift weights and decay_rates must be equal-length vectors")
        if np.any(w < 0) or np.any(g <= 0):
            raise ValidationError("lift weights must be >= 0 and rates > 0")
        if not math.isfinite(self.t_min) or not math.isfinite(self.t_max) or self.t_min <= 0 or self.t_max <= self.t_min:
            raise ValidationError("require 0 < t_min < t_max")

    def kernel(self, t: float) -> float:
        if not math.isfinite(t) or t <= 0:
            raise ValidationError("t must be finite and > 0")
        return float(np.dot(self.weights, np.exp(-self.decay_rates * t)))

    @property
    def n_factors(self) -> int:
        return int(self.weights.size)


def build_rough_volterra_lift(
    n_factors: int = 12,
    hurst: float = 0.07,
    t_min: float = 1e-4,
    t_max: float = 10.0,
) -> RoughVolterraLift:
    """Construct positive log-quadrature weights for a 12-factor Volterra lift.

    The Laplace representation of t^(-p) is approximated on a logarithmic grid.
    This provides a positive exponential approximation, not a globally exact fit.
    """
    if not isinstance(n_factors, (int, np.integer)) or n_factors < 1:
        raise ValidationError("n_factors must be a positive integer")
    if not math.isfinite(hurst) or not (0 < hurst < 0.5):
        raise ValidationError("hurst must be in (0, 0.5)")
    if not math.isfinite(t_min) or not math.isfinite(t_max) or t_min <= 0 or t_max <= t_min:
        raise ValidationError("require 0 < t_min < t_max")
    p = 0.5 - hurst
    log_lo = math.log(0.01 / t_max)
    log_hi = math.log(100.0 / t_min)
    log_gamma = np.linspace(log_lo, log_hi, n_factors)
    gamma = np.exp(log_gamma)
    dlog = float(log_gamma[1] - log_gamma[0]) if n_factors > 1 else (log_hi - log_lo)
    weights = dlog * np.power(gamma, p) / (math.gamma(p) * math.gamma(hurst + 0.5))
    return RoughVolterraLift(float(hurst), weights.astype(float), gamma.astype(float), float(t_min), float(t_max))


@dataclass(frozen=True)
class RoughVolterraPaths:
    times: np.ndarray
    spot: np.ndarray
    variance: np.ndarray
    log_variance: np.ndarray
    jump_intensity: np.ndarray
    jump_count: np.ndarray
    leverage_correlation: float
    seed: int


def simulate_rough_volterra_jump_sde(
    *,
    initial_spot: float = 100.0,
    horizon: float = 1.0,
    n_steps: int = 128,
    forward_variance: float | Sequence[float] = 0.04,
    vol_of_vol: float = 0.35,
    hurst: float = 0.07,
    leverage_correlation: float = -0.65,
    drift: float = 0.02,
    dividend_yield: float = 0.0,
    jump_baseline: float = 0.4,
    jump_excitation: float = 0.25,
    jump_decay: float = 2.0,
    variance_jump_mu: float = -0.03,
    variance_jump_sigma: float = 0.10,
    price_jump_mu: float = -0.005,
    price_jump_sigma: float = 0.015,
    variance_bounds: tuple[float, float] = (1e-5, 4.0),
    seed: int = 5601,
    lift: RoughVolterraLift | None = None,
) -> RoughVolterraPaths:
    """Simulate rough-Volterra log variance and a common Hawkes jump stream.

    A positive 12-factor exponential lift drives the Volterra Gaussian convolution.
    The same event clock drives log-variance and log-spot jump marks; this is a
    transparent physical-measure research discretization, not a calibrated option model.
    """
    finite_vals = (initial_spot, horizon, vol_of_vol, hurst, leverage_correlation,
                   drift, dividend_yield, jump_baseline, jump_excitation, jump_decay,
                   variance_jump_mu, variance_jump_sigma, price_jump_mu, price_jump_sigma)
    if not all(math.isfinite(float(x)) for x in finite_vals):
        raise ValidationError("simulation inputs must be finite")
    if initial_spot <= 0 or horizon <= 0 or not isinstance(n_steps, (int, np.integer)) or n_steps < 1:
        raise ValidationError("spot/horizon must be > 0 and n_steps a positive integer")
    if vol_of_vol < 0 or not (0 < hurst < 0.5):
        raise ValidationError("vol_of_vol must be >= 0 and hurst in (0,0.5)")
    if not (-0.9 <= leverage_correlation <= -0.3):
        raise ValidationError("leverage_correlation must be in [-0.9,-0.3]")
    if jump_baseline < 0 or jump_excitation < 0 or jump_decay <= 0:
        raise ValidationError("jump intensity parameters are invalid")
    if variance_jump_sigma < 0 or price_jump_sigma < 0:
        raise ValidationError("jump standard deviations must be >= 0")
    v_min, v_max = map(float, variance_bounds)
    if not math.isfinite(v_min) or not math.isfinite(v_max) or v_min <= 0 or v_max <= v_min:
        raise ValidationError("variance_bounds must satisfy 0 < min < max")
    if lift is None:
        lift = build_rough_volterra_lift(12, hurst, max(1e-12, min(1e-4, horizon / (n_steps * 10.0))), horizon)
    elif abs(lift.hurst - hurst) > 1e-12:
        raise ValidationError("lift Hurst exponent must match hurst")
    if np.isscalar(forward_variance):
        xi = np.full(n_steps + 1, float(forward_variance), dtype=float)
    else:
        xi = _as_float_array(forward_variance, "forward_variance", (n_steps + 1,)).copy()
    if not np.all(np.isfinite(xi)) or np.any(xi <= 0):
        raise ValidationError("forward variance curve must be finite and > 0")
    rng = np.random.default_rng(seed)
    dt = horizon / n_steps
    times = np.linspace(0.0, horizon, n_steps + 1)
    spot = np.empty(n_steps + 1, dtype=float)
    variance = np.empty(n_steps + 1, dtype=float)
    log_variance = np.empty(n_steps + 1, dtype=float)
    intensity_path = np.empty(n_steps + 1, dtype=float)
    counts = np.zeros(n_steps + 1, dtype=int)
    spot[0] = initial_spot
    factor_state = np.zeros(lift.n_factors, dtype=float)
    cumulative_var_jump = 0.0
    memory = 0.0
    log_variance[0] = math.log(xi[0])
    variance[0] = float(np.clip(math.exp(log_variance[0]), v_min, v_max))
    intensity_path[0] = jump_baseline + jump_excitation * memory
    log_spot = math.log(initial_spot)
    for i in range(n_steps):
        z_s, z_perp = rng.normal(size=2)
        d_w_s = math.sqrt(dt) * z_s
        d_w_v = leverage_correlation * d_w_s + math.sqrt(1.0 - leverage_correlation**2) * math.sqrt(dt) * z_perp
        v_now = variance[i]
        decay = np.exp(-lift.decay_rates * dt)
        ou_std = np.sqrt(np.maximum((1.0 - np.exp(-2.0 * lift.decay_rates * dt)) / (2.0 * lift.decay_rates), 0.0))
        factor_state = decay * factor_state + vol_of_vol * ou_std * (d_w_v / math.sqrt(dt))
        intensity_now = max(0.0, jump_baseline + jump_excitation * memory)
        event = int(rng.random() < -math.expm1(-intensity_now * dt))
        memory = memory * math.exp(-jump_decay * dt) + event
        counts[i + 1] = event
        intensity_path[i + 1] = jump_baseline + jump_excitation * memory
        if event:
            cumulative_var_jump += float(rng.normal(variance_jump_mu, variance_jump_sigma))
            price_jump = float(rng.normal(price_jump_mu, price_jump_sigma))
        else:
            price_jump = 0.0
        log_variance[i + 1] = math.log(xi[i + 1]) + float(lift.weights @ factor_state) + cumulative_var_jump
        variance[i + 1] = float(np.clip(math.exp(np.clip(log_variance[i + 1], -700, 700)), v_min, v_max))
        log_spot += (drift - dividend_yield - 0.5 * v_now) * dt + math.sqrt(v_now) * d_w_s + price_jump
        spot[i + 1] = math.exp(float(np.clip(log_spot, -700, 700)))
    return RoughVolterraPaths(times, spot, variance, log_variance, intensity_path, counts,
                              float(leverage_correlation), int(seed))


def mean_field_advantage(
    gross_advantage: float,
    statutory_fee_drag: float,
    inventory: float,
    inventory_variance: float,
    risk_penalty: float,
    toxic_adverse_selection: float = 0.0,
) -> float:
    """HJB/actor-critic advantage after fees, inventory variance, and toxicity."""
    vals = (gross_advantage, statutory_fee_drag, inventory, inventory_variance,
            risk_penalty, toxic_adverse_selection)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValidationError("advantage inputs must be finite")
    if min(statutory_fee_drag, inventory_variance, risk_penalty, toxic_adverse_selection) < 0:
        raise ValidationError("friction, variance, risk and toxicity penalties must be >= 0")
    return float(gross_advantage - statutory_fee_drag
                 - risk_penalty * inventory**2 * inventory_variance
                 - toxic_adverse_selection)


# Keep the shared Cycle 55 components available and expose a Cycle 56 demo that
# adds an explicit HJB/FPK solve and rough-Volterra path in the JSON payload.
_cycle55_reference_demo = reference_demo

def reference_demo() -> dict[str, object]:
    base = _cycle55_reference_demo()
    cfg = MFGConfig(horizon=0.5, n_steps=12, inventory_limit=3, fixed_point_iterations=12)
    mfg = solve_mean_field_game(cfg, toxicity_intensity_path=np.linspace(0.08, 0.18, cfg.n_steps),
                                directional_toxicity_path=np.linspace(-0.5, 0.5, cfg.n_steps))
    path = simulate_rough_volterra_jump_sde(n_steps=24, horizon=0.5, seed=5601)
    base.update({
        "cycle": 56,
        "engine": "MH-MFG-TOFA",
        "mfg_equilibrium": {
            "inventory_grid": mfg.inventory_grid.tolist(),
            "initial_density_mass": float(mfg.density[0].sum()),
            "terminal_density_mass": float(mfg.density[-1].sum()),
            "density_mass_error": mfg.density_mass_error,
            "bid_spread_center": float(np.mean(mfg.optimal_bid_half_spread)),
            "ask_spread_center": float(np.mean(mfg.optimal_ask_half_spread)),
            "fixed_point_iterations": mfg.fixed_point_iterations,
            "fixed_point_residual": mfg.fixed_point_residual,
            "converged": mfg.converged,
        },
        "toxic_flow": {
            "intensity_at_mlofi": ToxicFlowHawkes().intensity(8.0),
            "spread_expansion": toxic_spread_expansion(0.05, 0.8, 0.02),
            "cancellation_hazard": mlofi_cancellation_hazard(0.1, 0.2, 1.5, 0.4, 0.03, 8.0),
        },
        "rough_volterra_path": {
            "hurst": 0.07,
            "n_factors": build_rough_volterra_lift().n_factors,
            "initial_spot": float(path.spot[0]),
            "terminal_spot": float(path.spot[-1]),
            "minimum_variance": float(np.min(path.variance)),
            "maximum_variance": float(np.max(path.variance)),
            "jump_count": int(np.sum(path.jump_count)),
            "seed": path.seed,
        },
        "mfg_advantage_example": mean_field_advantage(1.0, 0.1, 2.0, 0.4, 0.2, 0.05),
    })
    return base
