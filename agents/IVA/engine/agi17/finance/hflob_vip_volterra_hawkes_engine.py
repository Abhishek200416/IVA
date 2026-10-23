"""Cycle 51 GUMMEE Grand Unified Microstructure-Macro Execution research engine.

Offline research / paper simulation only. No broker integration is implemented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence
import math
import time

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import minimize
from scipy.special import gamma

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
REGIMES = ("LOW_VOL_TREND", "HIGH_FREQ_CHOP", "JUMP_CASCADE")
STATE_DIM = 16
ACTION_DIM = 3
HURST = 0.07
TAU_FAST = 0.010
TAU_SLOW = 1.0
MAX_HAWKES_RADIUS = 0.88
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0


def _finite_array(value: ArrayLike, name: str) -> NDArray[np.float64]:
    arr = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _spectral_radius(matrix: ArrayLike) -> float:
    m = _finite_array(matrix, "matrix")
    if m.ndim != 2 or m.shape[0] != m.shape[1]:
        raise ValueError("spectral-radius matrix must be square")
    if m.size == 0:
        return 0.0
    return float(np.max(np.abs(np.linalg.eigvals(m))))


def normalize_probabilities(probabilities: ArrayLike) -> NDArray[np.float64]:
    p = _finite_array(probabilities, "probabilities")
    if p.ndim != 1 or np.any(p < 0):
        raise ValueError("probabilities must be a nonnegative vector")
    total = float(p.sum())
    if total <= 0:
        raise ValueError("probabilities must have positive total mass")
    return p / total


def validate_transition_matrix(matrix: ArrayLike, *, atol: float = 1e-10) -> NDArray[np.float64]:
    p = _finite_array(matrix, "transition matrix")
    if p.shape != (3, 3):
        raise ValueError("transition matrix must have shape (3, 3)")
    if np.any(p < 0):
        raise ValueError("transition probabilities cannot be negative")
    if not np.allclose(p.sum(axis=1), 1.0, atol=atol, rtol=0.0):
        raise ValueError("transition matrix rows must sum to one")
    return p


@dataclass
class HMMBeliefTracker:
    transition: NDArray[np.float64] = field(default_factory=lambda: np.array([
        [0.94, 0.05, 0.01], [0.06, 0.90, 0.04], [0.04, 0.12, 0.84]
    ], dtype=float))
    belief: NDArray[np.float64] = field(default_factory=lambda: np.array([0.70, 0.25, 0.05], dtype=float))

    def __post_init__(self) -> None:
        self.transition = validate_transition_matrix(self.transition)
        self.belief = normalize_probabilities(self.belief)
        if self.belief.shape != (3,):
            raise ValueError("belief must have three regime probabilities")

    def predict(self) -> NDArray[np.float64]:
        self.belief = normalize_probabilities(self.belief @ self.transition)
        return self.belief.copy()

    def update(self, likelihoods: ArrayLike) -> NDArray[np.float64]:
        likelihood = _finite_array(likelihoods, "likelihoods")
        if likelihood.shape != (3,) or np.any(likelihood < 0):
            raise ValueError("likelihoods must be three nonnegative values")
        predicted = self.belief @ self.transition
        posterior = predicted * likelihood
        if posterior.sum() <= 0:
            raise ValueError("likelihoods assign zero probability to every regime")
        self.belief = normalize_probabilities(posterior)
        return self.belief.copy()


@dataclass
class RegimeSwitchingHawkesNetwork:
    """Four-asset dual-timescale Hawkes memory bank with regime-specific amplitudes.

    The integrated branching matrix is Gamma_k = A_fast,k / beta_fast +
    A_slow,k / beta_slow. Amplitudes are scaled jointly per regime whenever
    needed so its spectral radius is strictly below 0.88.
    """
    alpha_fast: NDArray[np.float64] | None = None
    alpha_slow: NDArray[np.float64] | None = None
    mu: NDArray[np.float64] | None = None
    beta_fast: NDArray[np.float64] | None = None
    beta_slow: NDArray[np.float64] | None = None
    max_radius: float = MAX_HAWKES_RADIUS
    fast_state: NDArray[np.float64] = field(default_factory=lambda: np.zeros((4, 4), dtype=float))
    slow_state: NDArray[np.float64] = field(default_factory=lambda: np.zeros((4, 4), dtype=float))
    _scale_factors: NDArray[np.float64] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not (0.0 < self.max_radius < 0.88 + 1e-15):
            raise ValueError("max_radius must be positive and no greater than 0.88")
        default_fast = np.full((3, 4, 4), 0.000015, dtype=float)
        default_slow = np.full((3, 4, 4), 0.012, dtype=float)
        for k in range(3):
            np.fill_diagonal(default_fast[k], 0.000010)
            np.fill_diagonal(default_slow[k], 0.008)
        self.alpha_fast = _finite_array(default_fast if self.alpha_fast is None else self.alpha_fast, "alpha_fast")
        self.alpha_slow = _finite_array(default_slow if self.alpha_slow is None else self.alpha_slow, "alpha_slow")
        if self.alpha_fast.shape != (3, 4, 4) or self.alpha_slow.shape != (3, 4, 4):
            raise ValueError("alpha_fast and alpha_slow must have shape (3, 4, 4)")
        if np.any(self.alpha_fast < 0) or np.any(self.alpha_slow < 0):
            raise ValueError("Hawkes excitation amplitudes must be nonnegative")
        self.mu = _finite_array(np.tile(np.array([0.25, 0.8, 1.5])[:, None], (1, 4)) if self.mu is None else self.mu, "mu")
        if self.mu.shape != (3, 4) or np.any(self.mu < 0):
            raise ValueError("mu must be nonnegative with shape (3, 4)")
        self.beta_fast = _finite_array(np.full((4, 4), 1.0 / TAU_FAST) if self.beta_fast is None else self.beta_fast, "beta_fast")
        self.beta_slow = _finite_array(np.full((4, 4), 1.0 / TAU_SLOW) if self.beta_slow is None else self.beta_slow, "beta_slow")
        if self.beta_fast.shape != (4, 4) or self.beta_slow.shape != (4, 4):
            raise ValueError("beta matrices must have shape (4, 4)")
        if np.any(self.beta_fast <= 0) or np.any(self.beta_slow <= 0):
            raise ValueError("decay rates must be strictly positive")
        self.fast_state = _finite_array(self.fast_state, "fast_state")
        self.slow_state = _finite_array(self.slow_state, "slow_state")
        if self.fast_state.shape != (4, 4) or self.slow_state.shape != (4, 4):
            raise ValueError("state matrices must have shape (4, 4)")
        self._scale_factors = np.ones(3, dtype=float)
        self._enforce_regime_stability()

    def integrated_branching_matrix(self, regime: int) -> NDArray[np.float64]:
        self._check_regime(regime)
        return self.alpha_fast[regime] / self.beta_fast + self.alpha_slow[regime] / self.beta_slow

    def _check_regime(self, regime: int) -> None:
        if not isinstance(regime, (int, np.integer)) or regime not in (0, 1, 2):
            raise ValueError("regime must be 0, 1 or 2")

    def _enforce_regime_stability(self) -> None:
        strict_target = min(self.max_radius, MAX_HAWKES_RADIUS) - 1e-8
        if strict_target <= 0:
            raise ValueError("max_radius leaves no strictly stable region")
        for k in range(3):
            radius = _spectral_radius(self.integrated_branching_matrix(k))
            if radius >= strict_target:
                scale = strict_target / max(radius, np.finfo(float).eps)
                self.alpha_fast[k] *= scale
                self.alpha_slow[k] *= scale
                self._scale_factors[k] = scale
            if _spectral_radius(self.integrated_branching_matrix(k)) >= 0.88:
                raise RuntimeError("failed to enforce strict Hawkes stability")

    @property
    def regime_radii(self) -> NDArray[np.float64]:
        return np.asarray([_spectral_radius(self.integrated_branching_matrix(k)) for k in range(3)])

    def intensity_by_regime(self) -> NDArray[np.float64]:
        out = np.empty((3, 4), dtype=float)
        for k in range(3):
            out[k] = self.mu[k] + (self.alpha_fast[k] * self.fast_state).sum(axis=1) + (self.alpha_slow[k] * self.slow_state).sum(axis=1)
        return np.maximum(out, 0.0)

    def intensity(self, belief: ArrayLike) -> NDArray[np.float64]:
        p = normalize_probabilities(belief)
        if p.shape != (3,):
            raise ValueError("belief must have three values")
        return p @ self.intensity_by_regime()

    def advance(self, dt: float, event_counts: ArrayLike) -> NDArray[np.float64]:
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        events = _finite_array(event_counts, "event_counts")
        if events.shape != (4,) or np.any(events < 0):
            raise ValueError("event_counts must be a nonnegative 4-vector")
        fast_decay = np.exp(-self.beta_fast * dt)
        slow_decay = np.exp(-self.beta_slow * dt)
        # Each observed event adds one to the corresponding source column.
        self.fast_state = self.fast_state * fast_decay + np.broadcast_to(events, (4, 4))
        self.slow_state = self.slow_state * slow_decay + np.broadcast_to(events, (4, 4))
        return self.intensity_by_regime()

    def leadership_index(self) -> NDArray[np.float64]:
        # Integrated edge strength normalized directionally to [-1, 1].
        A = np.mean([self.integrated_branching_matrix(k) for k in range(3)], axis=0)
        out = np.zeros((4, 4), dtype=float)
        for i in range(4):
            for j in range(4):
                if i != j:
                    # A[target, source]: positive L[i,j] means asset i leads asset j.
                    out[i, j] = (A[j, i] - A[i, j]) / (A[i, j] + A[j, i] + 1e-15)
        return np.clip(out, -1.0, 1.0)

    def spillover_centrality(self) -> NDArray[np.float64]:
        return self.leadership_index().clip(min=0).sum(axis=1) / 3.0

    def absorption_centrality(self) -> NDArray[np.float64]:
        return self.leadership_index().clip(min=0).sum(axis=0) / 3.0


def build_state_vector(
    ofi: float,
    fast_intensities: ArrayLike,
    slow_intensities: ArrayLike,
    regime_belief: ArrayLike,
    rough_variance_lift: float,
    queue_priority: float,
    dealer_gex_stress: float,
    bid_ask_spread: float,
) -> NDArray[np.float64]:
    fast = _finite_array(fast_intensities, "fast_intensities")
    slow = _finite_array(slow_intensities, "slow_intensities")
    belief = normalize_probabilities(regime_belief)
    if fast.shape != (4,) or slow.shape != (4,) or belief.shape != (3,):
        raise ValueError("state requires 4 fast, 4 slow intensities and 3 regime probabilities")
    scalars = _finite_array([ofi, rough_variance_lift, queue_priority, dealer_gex_stress, bid_ask_spread], "state scalars")
    state = np.concatenate([[scalars[0]], fast, slow, belief, scalars[1:]])
    if state.shape != (STATE_DIM,):
        raise RuntimeError("internal state dimension error")
    return state


class _MLP:
    def __init__(self, input_dim: int, hidden1: int, hidden2: int, output_dim: int, seed: int):
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0, np.sqrt(2 / input_dim), (input_dim, hidden1))
        self.b1 = np.zeros(hidden1)
        self.W2 = rng.normal(0, np.sqrt(2 / hidden1), (hidden1, hidden2))
        self.b2 = np.zeros(hidden2)
        self.W3 = rng.normal(0, np.sqrt(1 / hidden2), (hidden2, output_dim))
        self.b3 = np.zeros(output_dim)

    def forward(self, X: NDArray[np.float64]) -> tuple[NDArray[np.float64], tuple[NDArray[np.float64], ...]]:
        z1 = X @ self.W1 + self.b1
        h1 = np.tanh(z1)
        z2 = h1 @ self.W2 + self.b2
        h2 = np.tanh(z2)
        y = h2 @ self.W3 + self.b3
        return y, (X, h1, h2)

    def backprop(self, cache: tuple[NDArray[np.float64], ...], grad_y: NDArray[np.float64], lr: float) -> None:
        X, h1, h2 = cache
        batch = max(1, X.shape[0])
        gW3 = h2.T @ grad_y / batch
        gb3 = grad_y.mean(axis=0)
        gh2 = grad_y @ self.W3.T
        gz2 = gh2 * (1.0 - h2 * h2)
        gW2 = h1.T @ gz2 / batch
        gb2 = gz2.mean(axis=0)
        gh1 = gz2 @ self.W2.T
        gz1 = gh1 * (1.0 - h1 * h1)
        gW1 = X.T @ gz1 / batch
        gb1 = gz1.mean(axis=0)
        for name, grad in (("W3", gW3), ("b3", gb3), ("W2", gW2), ("b2", gb2), ("W1", gW1), ("b1", gb1)):
            setattr(self, name, getattr(self, name) - lr * np.clip(grad, -10, 10))


@dataclass
class ContinuousActorCritic:
    state_dim: int = STATE_DIM
    action_dim: int = ACTION_DIM
    seed: int = 49
    learning_rate: float = 0.001
    log_std: NDArray[np.float64] = field(default_factory=lambda: np.full(ACTION_DIM, -0.5))
    _actor: _MLP = field(init=False, repr=False)
    _critic: _MLP = field(init=False, repr=False)
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.state_dim != 16 or self.action_dim != 3:
            raise ValueError("Cycle 51 contract is a 16-state, 3-action policy")
        # The actor emits both the latent Gaussian mean and a state-conditioned
        # log-standard-deviation vector. The latter head is initialized close
        # to zero so the supplied log_std is a stable prior at initialization.
        self._actor = _MLP(self.state_dim, 32, 16, self.action_dim * 2, self.seed)
        self._actor.W3[:, self.action_dim:] *= 0.05
        self._actor.b3[self.action_dim:] = 0.0
        self._critic = _MLP(self.state_dim, 32, 16, 1, self.seed + 1)
        self._rng = np.random.default_rng(self.seed + 2)
        self.log_std = np.clip(_finite_array(self.log_std, "log_std"), -5.0, 1.0)
        if self.log_std.shape != (self.action_dim,):
            raise ValueError("log_std must have length 3")

    def policy_parameters(self, states: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        X = _finite_array(states, "states")
        if X.ndim == 1:
            X = X[None, :]
        if X.ndim != 2 or X.shape[1] != self.state_dim:
            raise ValueError("states must have shape (batch, 16) or (16,)")
        raw, _ = self._actor.forward(X)
        mu = raw[:, :self.action_dim]
        state_log_std = np.clip(raw[:, self.action_dim:] + self.log_std[None, :], -5.0, 1.0)
        return np.tanh(mu), np.exp(state_log_std)

    def act(self, state: ArrayLike, *, deterministic: bool = False) -> NDArray[np.float64]:
        X = _finite_array(state, "state")
        if X.shape != (self.state_dim,):
            raise ValueError("state must have shape (16,)")
        raw, _ = self._actor.forward(X[None, :])
        mu = raw[0, :self.action_dim]
        state_log_std = np.clip(raw[0, self.action_dim:] + self.log_std, -5.0, 1.0)
        sigma = np.exp(state_log_std)
        latent = mu if deterministic else mu + self._rng.normal(0.0, sigma)
        return np.tanh(latent)

    def value(self, states: ArrayLike) -> NDArray[np.float64] | float:
        X = _finite_array(states, "states")
        scalar = X.ndim == 1
        if scalar:
            X = X[None, :]
        if X.ndim != 2 or X.shape[1] != self.state_dim:
            raise ValueError("states must have shape (batch, 16) or (16,)")
        values, _ = self._critic.forward(X)
        result = values[:, 0]
        return float(result[0]) if scalar else result

    def update_critic(self, states: ArrayLike, targets: ArrayLike) -> float:
        X = _finite_array(states, "states")
        y = _finite_array(targets, "targets").reshape(-1, 1)
        if X.ndim != 2 or X.shape[1] != self.state_dim or y.shape[0] != X.shape[0]:
            raise ValueError("critic update shape mismatch")
        pred, cache = self._critic.forward(X)
        error = pred - y
        loss = float(np.mean(error * error))
        self._critic.backprop(cache, 2.0 * error, self.learning_rate)
        return loss

    def update_actor(self, states: ArrayLike, actions: ArrayLike, advantages: ArrayLike) -> float:
        X = _finite_array(states, "states")
        A = _finite_array(actions, "actions")
        adv = _finite_array(advantages, "advantages").reshape(-1, 1)
        if X.ndim != 2 or X.shape[1] != self.state_dim or A.shape != (X.shape[0], self.action_dim) or adv.shape[0] != X.shape[0]:
            raise ValueError("actor update shape mismatch")
        A = np.clip(A, -0.999999, 0.999999)
        latent = np.arctanh(A)
        raw, cache = self._actor.forward(X)
        mu = raw[:, :self.action_dim]
        raw_log_std = raw[:, self.action_dim:] + self.log_std[None, :]
        log_std = np.clip(raw_log_std, -5.0, 1.0)
        sigma = np.exp(log_std)
        standardized = (latent - mu) / sigma
        # Score-function gradient of the diagonal Gaussian latent policy.
        # Clipping the log-scale prevents numerically degenerate variance.
        grad_mu = (mu - latent) / (sigma * sigma) * adv
        grad_log_std = adv * (1.0 - standardized * standardized)
        grad_log_std *= ((raw_log_std > -5.0) & (raw_log_std < 1.0))
        grad_output = np.concatenate([grad_mu, grad_log_std], axis=1)
        log_density = -0.5 * standardized * standardized - log_std
        loss = float(-np.mean(adv * log_density))
        self._actor.backprop(cache, grad_output, self.learning_rate)
        return loss


def friction_aware_advantage(
    reward: ArrayLike,
    value: ArrayLike,
    next_value: ArrayLike,
    *,
    statutory_fees: ArrayLike = 0.0,
    inventory_variance: ArrayLike = 0.0,
    variance_penalty: float = 0.0,
    discount: float = 0.99,
) -> dict[str, NDArray[np.float64] | float]:
    """One-step TD advantage net of fees and inventory-risk penalty.

    For samples, inputs follow NumPy broadcasting rules. This is a one-step
    research baseline; it is not a claim of an unbiased long-horizon estimator.
    """
    r = _finite_array(reward, "reward")
    v = _finite_array(value, "value")
    vn = _finite_array(next_value, "next_value")
    fees = _finite_array(statutory_fees, "statutory_fees")
    inv = _finite_array(inventory_variance, "inventory_variance")
    if np.any(fees < 0) or np.any(inv < 0) or variance_penalty < 0 or not (0 <= discount <= 1):
        raise ValueError("fees, inventory variance, and penalty must be nonnegative; discount in [0,1]")
    r, v, vn, fees, inv = np.broadcast_arrays(r, v, vn, fees, inv)
    td_target = r - fees - variance_penalty * inv + discount * vn
    advantage = td_target - v
    scalar = advantage.ndim == 0
    if scalar:
        return {"td_target": float(td_target), "advantage": float(advantage), "fee_drag": float(fees), "inventory_risk_penalty": float(variance_penalty * inv)}
    return {"td_target": td_target, "advantage": advantage, "fee_drag": fees, "inventory_risk_penalty": variance_penalty * inv}


def snell_envelope_step(immediate_value: float, expected_continuation: float, *, rate: float = 0.0, dt: float = 1.0, holding_cost_rate: float = 0.0) -> dict[str, Any]:
    vals = _finite_array([immediate_value, expected_continuation, rate, dt, holding_cost_rate], "Snell parameters")
    immediate, continuation, r, step, cost = map(float, vals)
    if step < 0 or cost < 0:
        raise ValueError("dt and holding cost rate must be nonnegative")
    continuation_value = math.exp(-r * step) * continuation - cost * step
    exercise = immediate >= continuation_value
    return {"value": max(immediate, continuation_value), "decision": "STOP" if exercise else "CONTINUE", "immediate_value": immediate, "continuation_value": continuation_value}


def snell_envelope_backward(immediate_values: ArrayLike, continuation_values: ArrayLike, *, discount: float = 1.0, holding_costs: ArrayLike | None = None) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    g = _finite_array(immediate_values, "immediate_values")
    c = _finite_array(continuation_values, "continuation_values")
    if g.ndim != 1 or c.shape != g.shape or not (0 <= discount <= 1):
        raise ValueError("Snell arrays must be equal one-dimensional arrays and discount in [0,1]")
    h = np.zeros_like(g) if holding_costs is None else _finite_array(holding_costs, "holding_costs")
    if h.shape != g.shape or np.any(h < 0):
        raise ValueError("holding costs must be nonnegative and match values")
    cont = discount * c - h
    stop = g >= cont
    return np.maximum(g, cont), stop


def cancellation_hazard(depth: float, age: float, *, lambda0: float = 0.15, kappa_depth: float = 0.8, kappa_age: float = 0.1) -> float:
    x = _finite_array([depth, age, lambda0, kappa_depth, kappa_age], "hazard parameters")
    d, a, l0, kd, ka = map(float, x)
    if a < 0 or l0 < 0 or d < 0:
        raise ValueError("depth, age, and lambda0 must be nonnegative")
    exponent = kd / max(d, 1.0) + ka * a
    return float(l0 * math.exp(min(exponent, 700.0)))


def order_survival_probability(tau: float, queue_ahead: float, *, depth: float, age: float, fill_rate: float, lambda0: float = 0.15, kappa_depth: float = 0.8, kappa_age: float = 0.1) -> float:
    x = _finite_array([tau, queue_ahead, fill_rate], "survival parameters")
    t, q, hf = map(float, x)
    if t < 0 or q < 0 or hf < 0:
        raise ValueError("tau, queue_ahead, and fill_rate must be nonnegative")
    hc = cancellation_hazard(depth, age, lambda0=lambda0, kappa_depth=kappa_depth, kappa_age=kappa_age)
    # Queue position increases effective exposure to fill/depletion events.
    total_hazard = hc + hf * (1.0 + q / max(depth, 1.0))
    return float(math.exp(-total_hazard * t))


def queue_revision_decision(survival: float, *, minimum_survival: float = 0.50) -> str:
    if not math.isfinite(survival) or not math.isfinite(minimum_survival):
        raise ValueError("survival threshold inputs must be finite")
    if not (0 <= survival <= 1) or not (0 <= minimum_survival <= 1):
        raise ValueError("probabilities must be in [0, 1]")
    return "HOLD" if survival >= minimum_survival else "REVISE_OR_PULL"


def midquote_log_returns(bids: ArrayLike, asks: ArrayLike) -> NDArray[np.float64]:
    bid = _finite_array(bids, "bids")
    ask = _finite_array(asks, "asks")
    if bid.ndim != 1 or ask.shape != bid.shape or len(bid) < 2:
        raise ValueError("bids and asks must be equal vectors of length >= 2")
    if np.any(bid <= 0) or np.any(ask <= 0) or np.any(ask < bid):
        raise ValueError("quotes must be positive and asks cannot be below bids")
    mid = (bid + ask) / 2.0
    return np.diff(np.log(mid))


def two_scale_realized_variance(fast_returns: ArrayLike, slow_returns: ArrayLike, *, n_fast: int | None = None, n_slow: int | None = None) -> float:
    rf = _finite_array(fast_returns, "fast_returns")
    rs = _finite_array(slow_returns, "slow_returns")
    if rf.ndim != 1 or rs.ndim != 1 or len(rf) == 0 or len(rs) == 0:
        raise ValueError("return arrays must be nonempty one-dimensional vectors")
    nf = len(rf) if n_fast is None else int(n_fast)
    ns = len(rs) if n_slow is None else int(n_slow)
    if nf <= 0 or ns <= 0 or ns > nf:
        raise ValueError("sample counts require 0 < n_slow <= n_fast")
    rv_fast = float(np.dot(rf, rf))
    rv_slow = float(np.dot(rs, rs))
    return rv_slow - (ns / nf) * rv_fast


def rough_volterra_lift(*, hurst: float = HURST, factors: int = 12, beta_min: float = 0.05, beta_max: float = 500.0) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    if not (0.0 < hurst < 0.5) or factors < 2 or beta_min <= 0 or beta_max <= beta_min:
        raise ValueError("invalid rough Volterra lift parameters")
    p = 0.5 - hurst
    edges = np.geomspace(beta_min, beta_max, factors + 1)
    betas = np.sqrt(edges[:-1] * edges[1:])
    weights = np.diff(edges ** p) / (gamma(p + 1.0) * gamma(1.0 - p))
    if np.any(weights <= 0) or not np.all(np.isfinite(weights)):
        raise RuntimeError("invalid Volterra quadrature weights")
    return betas.astype(float), weights.astype(float)


def volterra_kernel_approx(times: ArrayLike, *, hurst: float = HURST, factors: int = 12) -> NDArray[np.float64]:
    t = _finite_array(times, "times")
    if np.any(t <= 0):
        raise ValueError("kernel times must be positive")
    beta, weight = rough_volterra_lift(hurst=hurst, factors=factors)
    return np.exp(-np.outer(t.reshape(-1), beta)) @ weight


def simulate_volterra_jump_diffusion(*, steps: int = 128, dt: float = 1 / 100, spot: float = 100.0, v0: float = 0.04, mean_reversion: float = 2.0, vol_of_vol: float = 0.35, jump_intensity: float = 0.4, jump_mean: float = -0.01, jump_std: float = 0.02, seed: int = 49, hurst: float = HURST) -> dict[str, NDArray[np.float64]]:
    params = _finite_array([dt, spot, v0, mean_reversion, vol_of_vol, jump_intensity, jump_mean, jump_std, hurst], "simulation parameters")
    if steps < 2 or dt <= 0 or spot <= 0 or v0 <= 0 or mean_reversion < 0 or vol_of_vol < 0 or jump_intensity < 0 or jump_std < 0 or not (0 < hurst < 0.5):
        raise ValueError("invalid jump-diffusion parameters")
    rng = np.random.default_rng(seed)
    beta, weights = rough_volterra_lift(hurst=hurst)
    lift = np.zeros(len(beta), dtype=float)
    variance = np.empty(steps, dtype=float)
    log_price = np.empty(steps, dtype=float)
    variance[0] = v0
    log_price[0] = math.log(spot)
    for n in range(1, steps):
        dW = rng.normal(0.0, math.sqrt(dt))
        lift = np.exp(-beta * dt) * lift + rng.normal(0.0, math.sqrt(dt), size=len(beta))
        rough_shock = float(np.dot(weights, lift))
        variance[n] = np.clip(variance[n-1] + mean_reversion * (v0 - variance[n-1]) * dt + vol_of_vol * math.sqrt(max(variance[n-1], 1e-10)) * dW + 0.005 * rough_shock, 1e-8, 4.0)
        count = int(rng.poisson(jump_intensity * dt))
        jump = float(np.sum(rng.normal(jump_mean, jump_std, size=count))) if count else 0.0
        log_price[n] = log_price[n-1] - 0.5 * variance[n-1] * dt + math.sqrt(variance[n-1]) * dW + jump
    return {"time": np.arange(steps, dtype=float) * dt, "price": np.exp(log_price), "variance": variance, "log_price": log_price}


def synthetic_total_variance_surface(maturities: ArrayLike, log_moneyness: ArrayLike, *, base_variance: float = 0.04, skew: float = -0.08, curvature: float = 0.25) -> NDArray[np.float64]:
    T = _finite_array(maturities, "maturities")
    x = _finite_array(log_moneyness, "log_moneyness")
    if T.ndim != 1 or x.ndim != 1 or np.any(T <= 0) or np.any(base_variance < 0) or curvature < 0:
        raise ValueError("invalid surface inputs")
    # A total-variance proxy, monotone in maturity; nonnegative by construction.
    shape = np.maximum(0.05, 1.0 + skew * x + curvature * x * x)
    return np.outer(T * base_variance, shape)


def validate_vol_surface(total_variance: ArrayLike, maturities: ArrayLike, log_moneyness: ArrayLike, *, beta_call: float, beta_put: float, call_prices: ArrayLike | None = None, tolerance: float = 1e-10) -> dict[str, Any]:
    w = _finite_array(total_variance, "total_variance")
    T = _finite_array(maturities, "maturities")
    x = _finite_array(log_moneyness, "log_moneyness")
    if T.ndim != 1 or x.ndim != 1 or w.shape != (len(T), len(x)):
        raise ValueError("surface shape must be (len(maturities), len(log_moneyness))")
    if len(T) < 1 or np.any(T <= 0) or np.any(np.diff(T) <= 0):
        raise ValueError("maturities must be strictly increasing and positive")
    nonnegative = bool(np.all(w >= -tolerance))
    calendar = bool(np.all(np.diff(w, axis=0) >= -tolerance)) if len(T) > 1 else True
    wing = bool(0.0 < beta_call <= 2.0 and 0.0 < beta_put <= 2.0)
    butterfly = True
    if call_prices is not None:
        c = _finite_array(call_prices, "call_prices")
        if c.shape != (len(x),):
            raise ValueError("call_prices must match log_moneyness grid")
        if len(x) < 3 or np.any(np.diff(x) <= 0):
            raise ValueError("butterfly validation requires at least 3 increasing strikes")
        # Call prices must be convex in strike; on a nonuniform grid use slopes.
        strikes = np.exp(x)  # normalized spot is 1; K = exp(log-moneyness)
        slopes = np.diff(c) / np.diff(strikes)
        butterfly = bool(np.all(np.diff(slopes) >= -tolerance))
    return {"valid": bool(nonnegative and calendar and wing and butterfly), "nonnegative": nonnegative, "calendar_monotone": calendar, "roger_lee_wings": wing, "butterfly_convex": butterfly}


def dealer_net_gamma_exposure(open_interest: ArrayLike, option_gamma: ArrayLike, spot: float) -> float:
    oi = _finite_array(open_interest, "open_interest")
    gam = _finite_array(option_gamma, "option_gamma")
    if oi.shape != gam.shape or oi.ndim != 1 or np.any(oi < 0) or spot <= 0 or not math.isfinite(spot):
        raise ValueError("OI and gamma must be equal vectors; OI nonnegative and spot positive")
    return float(np.sum(oi * gam * spot))


def gamma_squeeze_hazard(gamma_dealer: float, depth: float, *, lambda0: float = 0.1, kappa: float = 0.5) -> float:
    vals = _finite_array([gamma_dealer, depth, lambda0, kappa], "gamma hazard parameters")
    g, d, l0, k = map(float, vals)
    if d < 0 or l0 < 0 or k < 0:
        raise ValueError("depth, lambda0 and kappa must be nonnegative")
    return float(l0 * math.exp(min(k * abs(g) / max(d, 1.0), 700.0)))


def quote_retreat_decision(*, toxic_cascade: bool, squeeze_hazard: float, hazard_threshold: float) -> str:
    if not math.isfinite(squeeze_hazard) or not math.isfinite(hazard_threshold) or squeeze_hazard < 0 or hazard_threshold < 0:
        raise ValueError("hazard inputs must be finite and nonnegative")
    return "RETREAT" if toxic_cascade or squeeze_hazard >= hazard_threshold else "QUOTE"


def greek_neutral_hedge(covariance: ArrayLike, greek_matrix: ArrayLike, target_greeks: ArrayLike, spreads: ArrayLike, *, lambda_cost: float = 0.01, lambda_spread: float = 0.01, neutrality_bounds: ArrayLike = (1.02e-4, 1.02e-3, 1.0002), maxiter: int = 1000) -> dict[str, Any]:
    """Convex split-variable solve with L1 transaction/spread penalties.

    greek_matrix has shape (3, n instruments); the returned `weights` are
    increments, and target_greeks are existing portfolio exposures to offset.
    """
    S = _finite_array(covariance, "covariance")
    G = _finite_array(greek_matrix, "greek_matrix")
    target = _finite_array(target_greeks, "target_greeks")
    spread = _finite_array(spreads, "spreads")
    bounds = _finite_array(neutrality_bounds, "neutrality_bounds")
    if S.ndim != 2 or S.shape[0] != S.shape[1]:
        raise ValueError("covariance must be square")
    n = S.shape[0]
    if G.shape != (3, n) or target.shape != (3,) or spread.shape != (n,) or bounds.shape != (3,):
        raise ValueError("hedge input shapes are inconsistent")
    if np.any(spread < 0) or np.any(bounds <= 0) or lambda_cost < 0 or lambda_spread < 0:
        raise ValueError("penalties, spreads and neutrality bounds must be nonnegative/positive")
    if not np.allclose(S, S.T, atol=1e-9):
        raise ValueError("covariance must be symmetric")
    if np.min(np.linalg.eigvalsh(S)) < -1e-8:
        raise ValueError("covariance must be positive semidefinite")
    # Split w = u - v; both u and v >= 0. L1(w) <= sum(u+v),
    # and spread penalties use absolute executed size, avoiding rebates on shorts.
    def unpack(z: NDArray[np.float64]) -> NDArray[np.float64]:
        return z[:n] - z[n:]
    def objective(z: NDArray[np.float64]) -> float:
        w = unpack(z)
        gross = 0.5 * float(w @ S @ w)
        penalties = lambda_cost * float(z.sum()) + lambda_spread * float(spread @ (z[:n] + z[n:]))
        return gross + penalties
    def gradient(z: NDArray[np.float64]) -> NDArray[np.float64]:
        w = unpack(z)
        base = S @ w
        return np.concatenate([base + lambda_cost + lambda_spread * spread, -base + lambda_cost + lambda_spread * spread])
    def constraints(z: NDArray[np.float64]) -> NDArray[np.float64]:
        net = target + G @ unpack(z)
        return np.concatenate([bounds - net, bounds + net])
    result = minimize(objective, np.zeros(2*n), jac=gradient, bounds=[(0.0, None)]*(2*n), constraints=[{"type": "ineq", "fun": constraints}], method="SLSQP", options={"maxiter": maxiter, "ftol": 1e-12, "disp": False})
    weights = unpack(result.x)
    net = target + G @ weights
    neutral = bool(np.all(np.abs(net) <= bounds + 2e-7))
    return {"weights": weights, "net_greeks": net, "objective": float(objective(result.x)), "success": bool(result.success and neutral), "neutral": neutral, "message": str(result.message), "iterations": int(getattr(result, "nit", 0))}


@dataclass(frozen=True)
class IndianStatutoryFees:
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    exchange_rate_per_crore: float = 3553.0
    sebi_rate_per_crore: float = 10.0
    gst_rate: float = 0.18
    brokerage_per_leg: float = 20.0

    def calculate(self, *, buy_turnover: float, sell_turnover: float, executed_legs: int) -> dict[str, float]:
        vals = _finite_array([buy_turnover, sell_turnover], "turnover")
        if np.any(vals < 0) or executed_legs < 0:
            raise ValueError("turnover and executed legs must be nonnegative")
        buy, sell = map(float, vals)
        total = buy + sell
        stt = self.stt_sell_rate * sell
        stamp = self.stamp_buy_rate * buy
        exchange = self.exchange_rate_per_crore * total / 10_000_000.0
        sebi = self.sebi_rate_per_crore * total / 10_000_000.0
        brokerage = self.brokerage_per_leg * int(executed_legs)
        gst = self.gst_rate * (exchange + sebi + brokerage)
        total_fees = stt + stamp + exchange + sebi + brokerage + gst
        return {"stt": stt, "stamp_duty": stamp, "exchange": exchange, "sebi": sebi, "brokerage": brokerage, "gst": gst, "total_fees": total_fees}


def bayesian_kelly_fraction(
    wins_prior: float,
    losses_prior: float,
    payoff_ratio: float,
    *,
    fraction_scale: float = 0.5,
    max_fraction: float = 0.10,
) -> dict[str, float]:
    """Conservative fractional Kelly from a Beta-posterior win probability.

    `wins_prior` and `losses_prior` act as positive Beta pseudo-counts. Kelly
    fraction is clipped at zero and at max_fraction; this is a sizing aid, not
    a guarantee of expected profit or a substitute for the net-fee gate.
    """
    values = _finite_array([wins_prior, losses_prior, payoff_ratio, fraction_scale, max_fraction], "Kelly inputs")
    a, b, payoff, scale, cap = map(float, values)
    if a <= 0 or b <= 0 or payoff <= 0 or not (0 <= scale <= 1) or not (0 <= cap <= 1):
        raise ValueError("Kelly priors/payoff must be positive; scale and cap must be in [0,1]")
    p = a / (a + b)
    full = p - (1.0 - p) / payoff
    fraction = min(cap, max(0.0, scale * full))
    return {"posterior_win_probability": p, "full_kelly_fraction": full, "fractional_kelly_fraction": fraction}


def expected_net_alpha_gate(expected_gross_alpha: float, total_statutory_fees: float) -> dict[str, Any]:
    gross, fees = map(float, _finite_array([expected_gross_alpha, total_statutory_fees], "alpha inputs"))
    if fees < 0:
        raise ValueError("fees must be nonnegative")
    net = gross - fees
    return {"gross_alpha": gross, "fees": fees, "expected_net_alpha": net, "approved": bool(net > 0.0)}


def volatility_scaled_cooldown(tau_base: float, theta_v: float, sigma_rough: float, sigma_base: float) -> float:
    vals = _finite_array([tau_base, theta_v, sigma_rough, sigma_base], "cooldown inputs")
    base, theta, rough, sbase = map(float, vals)
    if base < 0 or theta < 0 or rough < 0 or sbase <= 0:
        raise ValueError("cooldown inputs require nonnegative rates/volatility and positive sigma_base")
    return base * (1.0 + theta * rough / sbase)


@dataclass
class AntiTiltThrottle:
    consecutive_losses: int = 0
    last_trade_time: float | None = None
    last_size: float | None = None
    minimum_spacing_seconds: float = 30.0
    max_size_acceleration: float = 1.25

    def record_outcome(self, pnl: float) -> None:
        if not math.isfinite(pnl):
            raise ValueError("pnl must be finite")
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

    def evaluate(self, *, now: float, size: float) -> dict[str, Any]:
        if not math.isfinite(now) or not math.isfinite(size) or size < 0:
            raise ValueError("now must be finite and size nonnegative")
        reasons: list[str] = []
        if self.consecutive_losses >= 3:
            reasons.append("THREE_CONSECUTIVE_LOSSES")
        if self.last_trade_time is not None and now - self.last_trade_time < self.minimum_spacing_seconds:
            reasons.append("TRADE_SPACING_LT_30S")
        if self.last_size is not None and self.last_size > 0 and size / self.last_size > self.max_size_acceleration:
            reasons.append("SIZE_ACCELERATION_GT_1_25X")
        return {"allowed": not reasons, "reasons": reasons}

    def record_trade(self, *, now: float, size: float) -> None:
        if not math.isfinite(now) or not math.isfinite(size) or size < 0:
            raise ValueError("invalid trade record")
        self.last_trade_time = now
        self.last_size = size


AGENT_SQUAD = {
    "Abhi": "operator liaison, capital approval and binding live veto",
    "Alex": "L3 queue risk and microstructure",
    "Emily": "rough volatility and regime belief",
    "Max": "risk management, statutory friction and Bayesian-Kelly sizing",
}


def squad_consensus(*, manager_approved: bool, capital_approved: bool, queue_safe: bool, regime_safe: bool, alpha_approved: bool, risk_safe: bool, live_requested: bool = False) -> dict[str, Any]:
    # No consensus can enable live execution. A live request is denied regardless
    # of all agent approvals; this is a software invariant, not a preference.
    checks = {"Abhi_manager": bool(manager_approved), "Abhi_capital": bool(capital_approved), "Alex_queue": bool(queue_safe), "Emily_regime": bool(regime_safe), "Max_net_alpha": bool(alpha_approved), "Max_risk": bool(risk_safe)}
    denied = [name for name, passed in checks.items() if not passed]
    return {"approved": bool(not denied and not live_requested), "checks": checks, "denied_checks": denied, "mode": "PAPER_ONLY", "live_dispatch_permitted": False, "reason": "LIVE_REQUEST_DENIED" if live_requested else ("ALL_CHECKS_PASSED" if not denied else "FAIL_CLOSED")}


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Intentionally unavailable. Every call raises regardless of arguments."""
    raise PermissionError("Cycle 51 GUMMEE is paper-only: live broker order dispatch is disabled")




GUMMEE_NAME = "Grand Unified Microstructure-Macro Quantum-Jump Execution Engine"


@dataclass
class CrossAssetImpactModel:
    """Four-asset, directed linear cross-impact model for signed order flow.

    Rows denote the affected/target asset and columns the originating/source
    asset. This is an interpretable reduced-form research model, not a claim of
    causal identification from observational flow alone.
    """
    impact_matrix: NDArray[np.float64] = field(default_factory=lambda: np.array([
        [0.020, 0.004, 0.003, 0.002],
        [0.006, 0.018, 0.004, 0.003],
        [0.003, 0.005, 0.016, 0.004],
        [0.002, 0.003, 0.005, 0.015],
    ], dtype=float))
    liquidity_scale: NDArray[np.float64] = field(default_factory=lambda: np.ones(4, dtype=float))

    def __post_init__(self) -> None:
        self.impact_matrix = _finite_array(self.impact_matrix, "impact_matrix")
        self.liquidity_scale = _finite_array(self.liquidity_scale, "liquidity_scale")
        if self.impact_matrix.shape != (4, 4):
            raise ValueError("impact_matrix must have shape (4, 4), target rows by source columns")
        if self.liquidity_scale.shape != (4,) or np.any(self.liquidity_scale <= 0):
            raise ValueError("liquidity_scale must be a positive 4-vector")

    def predict_returns(self, signed_order_flow: ArrayLike) -> NDArray[np.float64]:
        flow = _finite_array(signed_order_flow, "signed_order_flow")
        if flow.shape != (4,):
            raise ValueError("signed_order_flow must be a 4-vector")
        # Liquidity normalization is source-specific; matrix columns encode
        # how source-asset order flow impacts each target asset.
        return self.impact_matrix @ (flow / self.liquidity_scale)

    def leadership_index(self) -> NDArray[np.float64]:
        out = np.zeros((4, 4), dtype=float)
        for i in range(4):
            for j in range(4):
                if i != j:
                    i_to_j = abs(self.impact_matrix[j, i])
                    j_to_i = abs(self.impact_matrix[i, j])
                    out[i, j] = (i_to_j - j_to_i) / (i_to_j + j_to_i + 1e-15)
        return np.clip(out, -1.0, 1.0)

    def source_spillover_centrality(self) -> NDArray[np.float64]:
        # Column strength: how much a source moves all other target assets.
        strength = np.abs(self.impact_matrix).sum(axis=0) - np.abs(np.diag(self.impact_matrix))
        total = float(strength.sum())
        return strength / total if total > 0 else np.zeros(4, dtype=float)

    def target_absorption_centrality(self) -> NDArray[np.float64]:
        # Row strength: how strongly a target absorbs other assets' flow.
        strength = np.abs(self.impact_matrix).sum(axis=1) - np.abs(np.diag(self.impact_matrix))
        total = float(strength.sum())
        return strength / total if total > 0 else np.zeros(4, dtype=float)

    def impact_cost(self, signed_order_flow: ArrayLike) -> float:
        flow = _finite_array(signed_order_flow, "signed_order_flow")
        if flow.shape != (4,):
            raise ValueError("signed_order_flow must be a 4-vector")
        returns = self.predict_returns(flow)
        return float(np.dot(np.abs(flow), np.abs(returns)))


def simulate_regime_marked_jumps(
    *,
    steps: int = 256,
    dt: float = 0.01,
    transition_matrix: ArrayLike | None = None,
    initial_belief: ArrayLike = (0.70, 0.25, 0.05),
    event_intensity: ArrayLike = (0.5, 1.5, 4.0),
    jump_mean: ArrayLike = (0.0002, -0.0001, -0.012),
    jump_std: ArrayLike = (0.001, 0.002, 0.025),
    seed: int = 50,
) -> dict[str, NDArray[np.float64]]:
    """Simulate regime-conditioned compound-Poisson jump marks reproducibly.

    The phrase ``quantum-jump`` in GUMMEE's research title is used as a product
    metaphor for discrete marked state transitions; this is a classical
    stochastic simulation and has no quantum-physics interpretation.
    """
    if not isinstance(steps, (int, np.integer)) or steps < 2:
        raise ValueError("steps must be an integer >= 2")
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError("dt must be finite and positive")
    transition = validate_transition_matrix(
        np.array([[0.94, 0.05, 0.01], [0.06, 0.90, 0.04], [0.04, 0.12, 0.84]])
        if transition_matrix is None else transition_matrix
    )
    belief = normalize_probabilities(initial_belief)
    intensity = _finite_array(event_intensity, "event_intensity")
    mean = _finite_array(jump_mean, "jump_mean")
    std = _finite_array(jump_std, "jump_std")
    if belief.shape != (3,) or intensity.shape != (3,) or mean.shape != (3,) or std.shape != (3,):
        raise ValueError("belief, event_intensity, jump_mean and jump_std must each have 3 entries")
    if np.any(intensity < 0) or np.any(std < 0):
        raise ValueError("event intensities and jump standard deviations must be nonnegative")
    rng = np.random.default_rng(seed)
    regimes = np.empty(steps, dtype=np.int64)
    counts = np.zeros(steps, dtype=np.int64)
    aggregate = np.zeros(steps, dtype=float)
    regimes[0] = int(rng.choice(3, p=belief))
    for t in range(steps):
        if t > 0:
            regimes[t] = int(rng.choice(3, p=transition[regimes[t - 1]]))
        k = int(regimes[t])
        counts[t] = int(rng.poisson(intensity[k] * dt))
        if counts[t] > 0:
            aggregate[t] = float(rng.normal(mean[k], std[k], size=counts[t]).sum())
    return {
        "time": np.arange(steps, dtype=float) * dt,
        "regime": regimes.astype(float),
        "event_count": counts.astype(float),
        "aggregate_jump_return": aggregate,
    }


def _run_cycle51_core_example() -> dict[str, Any]:
    tracker = HMMBeliefTracker()
    belief = tracker.update([0.2, 0.3, 0.8])
    hawkes = RegimeSwitchingHawkesNetwork()
    intensities = hawkes.advance(0.01, [1, 0, 1, 0])
    state = build_state_vector(0.1, intensities[0], intensities[1], belief, 0.04, 0.25, 0.1, 0.5)
    actor = ContinuousActorCritic(seed=50)
    action = actor.act(state, deterministic=True)
    survival = order_survival_probability(0.5, 2.0, depth=8.0, age=0.3, fill_rate=0.05)
    fees = IndianStatutoryFees().calculate(buy_turnover=100_000.0, sell_turnover=100_000.0, executed_legs=2)
    alpha = expected_net_alpha_gate(500.0, fees["total_fees"])
    quote = quote_retreat_decision(toxic_cascade=False, squeeze_hazard=0.2, hazard_threshold=1.0)
    return {
        "cycle": 51,
        "engine": GUMMEE_NAME,
        "assets": list(ASSETS),
        "regime_belief": belief.tolist(),
        "hawkes_spectral_radii": hawkes.regime_radii.tolist(),
        "hawkes_intensity_regime_0": intensities[0].tolist(),
        "actor_action": action.tolist(),
        "critic_value": actor.value(state),
        "state_dimension": int(state.size),
        "queue_survival": survival,
        "queue_decision": queue_revision_decision(survival),
        "quote_action": quote,
        "fees": fees,
        "net_alpha": alpha,
        "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
        "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED,
        "ledger_epoch": PAPER_LEDGER_EPOCH,
        "initial_capital_inr": INITIAL_CAPITAL_INR,
        "execution_mode": "PAPER_ONLY",
    }

# ---------------------------------------------------------------------------
# Cycle 51 HFLOB-VIP additions: VECM-L3, OFI toxicity, nonlinear Hawkes,
# and CARA utility-indifference pricing.
# ---------------------------------------------------------------------------

HFLOB_VIP_NAME = "High-Frequency Limit Order Book Cointegration and Volterra-Hawkes Utility Indifference Pricer"
VECM_ASSETS = ("NIFTY50", "BANKNIFTY")


def synthetic_forward_price(spot: float, risk_free_rate: float, dividend_yield: float, tau: float) -> float:
    """Continuous-carry fair forward ``F*=S exp((r-d) tau)`` in deterministic rates."""
    s, r, d, t = map(float, _finite_array([spot, risk_free_rate, dividend_yield, tau], "forward inputs"))
    if s <= 0 or t < 0:
        raise ValueError("spot must be positive and tau nonnegative")
    exponent = (r - d) * t
    if exponent > 700 or exponent < -700:
        raise ValueError("carry exponent outside numerically safe range")
    return float(s * math.exp(exponent))


def cointegration_spread(forward_price: float, spot_midquotes: ArrayLike, beta: ArrayLike, alpha0: float = 0.0) -> float:
    """Compute z=ln(F)-beta' ln(S)-alpha0 using positive observed prices."""
    f = float(forward_price)
    spots = _finite_array(spot_midquotes, "spot_midquotes")
    b = _finite_array(beta, "beta")
    intercept = float(alpha0)
    if not math.isfinite(f) or f <= 0 or spots.ndim != 1 or b.shape != spots.shape or np.any(spots <= 0) or not math.isfinite(intercept):
        raise ValueError("forward and spot prices must be positive; beta must match the spot vector")
    return float(math.log(f) - np.dot(b, np.log(spots)) - intercept)


@dataclass
class VECMSpreadModel:
    """Error-correction model for a log spot/forward cointegration residual.

    The scalar residual follows E[z(t+dt)|z(t)] = exp(-kappa*dt) z(t);
    the associated half-life is ln(2)/kappa. This is a reduced-form model,
    and stationarity must be validated on out-of-sample synchronized data.
    """
    beta: NDArray[np.float64] = field(default_factory=lambda: np.array([1.0, 0.0]))
    alpha0: float = 0.0
    kappa_vecm: float = 1.0

    def __post_init__(self) -> None:
        self.beta = _finite_array(self.beta, "beta")
        self.alpha0 = float(self.alpha0)
        self.kappa_vecm = float(self.kappa_vecm)
        if self.beta.ndim != 1 or self.beta.size < 1 or not math.isfinite(self.alpha0):
            raise ValueError("beta must be a finite vector and alpha0 finite")
        if not math.isfinite(self.kappa_vecm) or self.kappa_vecm <= 0:
            raise ValueError("kappa_vecm must be finite and strictly positive")

    @property
    def half_life(self) -> float:
        return math.log(2.0) / self.kappa_vecm

    def spread(self, forward_price: float, spot_midquotes: ArrayLike) -> float:
        return cointegration_spread(forward_price, spot_midquotes, self.beta, self.alpha0)

    def correction_drift(self, spread: float) -> float:
        z = float(spread)
        if not math.isfinite(z):
            raise ValueError("spread must be finite")
        return -self.kappa_vecm * z

    def expected_next_spread(self, spread: float, dt: float) -> float:
        z, step = map(float, _finite_array([spread, dt], "VECM step"))
        if step < 0:
            raise ValueError("dt must be nonnegative")
        return float(z * math.exp(-self.kappa_vecm * step))


def estimate_vecm_cointegration(
    forward_prices: ArrayLike,
    spot_prices: ArrayLike,
    *,
    dt: float = 1.0,
    minimum_observations: int = 20,
) -> dict[str, Any]:
    """OLS cointegrating vector plus AR(1) residual mean-reversion estimate.

    ``spot_prices`` has shape ``(n_observations, n_assets)`` and strictly
    positive prices. The residual AR(1) is fit through the origin after OLS
    with an intercept in the cointegration equation. It rejects non-mean-
    reverting samples instead of fabricating a positive half-life.
    """
    f = _finite_array(forward_prices, "forward_prices")
    spots = _finite_array(spot_prices, "spot_prices")
    step = float(dt)
    if f.ndim != 1 or spots.ndim != 2 or spots.shape[0] != f.size or spots.shape[1] < 1:
        raise ValueError("forward_prices must be (n,) and spot_prices must be (n, assets)")
    if f.size < max(int(minimum_observations), spots.shape[1] + 3) or np.any(f <= 0) or np.any(spots <= 0):
        raise ValueError("insufficient observations or nonpositive prices")
    if not math.isfinite(step) or step <= 0:
        raise ValueError("dt must be finite and positive")
    y = np.log(f)
    X = np.log(spots)
    design = np.column_stack([np.ones(f.size), X])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    intercept, beta = float(coefficients[0]), coefficients[1:]
    residual = y - design @ coefficients
    denominator = float(np.dot(residual[:-1], residual[:-1]))
    if denominator <= np.finfo(float).eps:
        raise ValueError("cointegration residual has negligible variation")
    phi = float(np.dot(residual[:-1], residual[1:]) / denominator)
    if not (0.0 < phi < 1.0):
        raise ValueError("residual AR(1) coefficient is not strictly mean reverting (0 < phi < 1)")
    kappa = -math.log(phi) / step
    ss_total = float(np.sum((y - y.mean()) ** 2))
    ss_residual = float(np.sum(residual ** 2))
    r2 = 1.0 - ss_residual / ss_total if ss_total > 0 else 1.0
    return {
        "beta": beta.astype(float), "alpha0": intercept, "spread": residual.astype(float),
        "phi": phi, "kappa_vecm": kappa, "half_life": math.log(2.0) / kappa,
        "r_squared": r2, "observations": int(f.size), "dt": step,
    }


def _five_levels(value: ArrayLike, name: str) -> NDArray[np.float64]:
    arr = _finite_array(value, name)
    if arr.shape != (5,) or np.any(arr < 0):
        raise ValueError(f"{name} must be a nonnegative five-level volume vector")
    return arr


def decompose_top5_ofi(
    bid_fill_delta: ArrayLike,
    bid_cancel_delta: ArrayLike,
    ask_fill_delta: ArrayLike,
    ask_cancel_delta: ArrayLike,
    *,
    informed_active_depletion: float | None = None,
) -> dict[str, Any]:
    """Split top-five L3 OFI into active execution and passive cancellation flow.

    Inputs are nonnegative *magnitudes* of fills/cancellations at levels 1..5.
    At each level: OFI=(bid fills - bid cancels) - (ask fills - ask cancels).
    The informed-depletion amount defaults to absolute net active execution,
    and is capped at total observed liquidity flow when forming the bounded
    toxicity ratio.
    """
    bf = _five_levels(bid_fill_delta, "bid_fill_delta")
    bc = _five_levels(bid_cancel_delta, "bid_cancel_delta")
    af = _five_levels(ask_fill_delta, "ask_fill_delta")
    ac = _five_levels(ask_cancel_delta, "ask_cancel_delta")
    active = bf - af
    passive = -bc + ac
    net = active + passive
    total_flow = float(bf.sum() + bc.sum() + af.sum() + ac.sum())
    if informed_active_depletion is None:
        informed = float(abs(bf.sum() - af.sum()))
    else:
        informed = float(informed_active_depletion)
        if not math.isfinite(informed) or informed < 0:
            raise ValueError("informed_active_depletion must be finite and nonnegative")
    if total_flow <= 0:
        toxicity = 0.0
    else:
        toxicity = min(1.0, max(0.0, informed / total_flow))
    return {
        "active_execution_flow_by_level": active,
        "passive_cancel_flow_by_level": passive,
        "ofi_by_level": net,
        "active_execution_flow": float(active.sum()),
        "passive_cancel_flow": float(passive.sum()),
        "net_ofi": float(net.sum()),
        "total_liquidity_flow": total_flow,
        "informed_active_depletion": informed,
        "toxicity_index": toxicity,
    }


def flow_toxicity_index(informed_active_depletion: float, total_liquidity_flow: float) -> float:
    informed, total = map(float, _finite_array([informed_active_depletion, total_liquidity_flow], "toxicity inputs"))
    if informed < 0 or total < 0:
        raise ValueError("flow amounts must be nonnegative")
    if total == 0:
        if informed == 0:
            return 0.0
        raise ValueError("positive informed depletion cannot be divided by zero liquidity flow")
    return min(1.0, informed / total)


def _spectral_radius_real(matrix: NDArray[np.float64]) -> float:
    eig = np.linalg.eigvals(matrix)
    return float(np.max(np.abs(eig))) if eig.size else 0.0


@dataclass
class NonlinearQuadraticHawkesNetwork:
    """Discrete-time marked approximation of nonlinear quadratic Hawkes excitation.

    For observed event counts dN_j, memory updates exponentially and each new
    event is marked by alpha_ij + gamma_ij * lambda_j(t-). The local branching
    audit uses Gamma_ij=(alpha_ij+gamma_ij*lambda_j)/beta_ij and rejects any
    state with spectral radius >= 0.88. This is a state-local stability audit,
    not a global theorem for an unbounded nonlinear point process.
    """
    mu: NDArray[np.float64] = field(default_factory=lambda: np.array([0.25, 0.35, 0.30, 0.20]))
    alpha: NDArray[np.float64] = field(default_factory=lambda: np.full((4, 4), 0.008))
    gamma: NDArray[np.float64] = field(default_factory=lambda: np.full((4, 4), 0.001))
    beta: NDArray[np.float64] = field(default_factory=lambda: np.full((4, 4), 1.0))
    max_radius: float = MAX_HAWKES_RADIUS
    intensity: NDArray[np.float64] | None = None
    memory: NDArray[np.float64] = field(default_factory=lambda: np.zeros((4, 4)))

    def __post_init__(self) -> None:
        self.mu = _finite_array(self.mu, "mu")
        self.alpha = _finite_array(self.alpha, "alpha")
        self.gamma = _finite_array(self.gamma, "gamma")
        self.beta = _finite_array(self.beta, "beta")
        self.memory = _finite_array(self.memory, "memory")
        if self.mu.shape != (4,) or np.any(self.mu < 0):
            raise ValueError("mu must be a nonnegative four-vector")
        for name, value in (("alpha", self.alpha), ("gamma", self.gamma), ("beta", self.beta), ("memory", self.memory)):
            if value.shape != (4, 4):
                raise ValueError(f"{name} must have shape (4,4)")
        if np.any(self.alpha < 0) or np.any(self.gamma < 0) or np.any(self.memory < 0) or np.any(self.beta <= 0):
            raise ValueError("alpha, gamma, and memory must be nonnegative; beta strictly positive")
        if not math.isfinite(self.max_radius) or not (0 < self.max_radius <= 0.88):
            raise ValueError("max_radius must be strictly between zero and 0.88")
        if self.intensity is None:
            self.intensity = self.mu.copy()
        else:
            self.intensity = _finite_array(self.intensity, "intensity")
        if self.intensity.shape != (4,) or np.any(self.intensity < 0):
            raise ValueError("intensity must be a nonnegative four-vector")
        # Constructor rejects unstable parameters rather than silently altering calibration.
        self.audit_stability(self.intensity)

    def effective_branching_matrix(self, source_intensity: ArrayLike | None = None) -> NDArray[np.float64]:
        lam = self.intensity if source_intensity is None else _finite_array(source_intensity, "source_intensity")
        if lam.shape != (4,) or np.any(lam < 0):
            raise ValueError("source_intensity must be a nonnegative four-vector")
        marked_amplitude = self.alpha + self.gamma * lam[None, :]
        return marked_amplitude / self.beta

    def audit_stability(self, source_intensity: ArrayLike | None = None) -> dict[str, Any]:
        matrix = self.effective_branching_matrix(source_intensity)
        radius = _spectral_radius_real(matrix)
        passed = bool(radius < self.max_radius and radius < 0.88)
        result = {"passed": passed, "spectral_radius": radius, "limit": min(self.max_radius, 0.88), "branching_matrix": matrix}
        if not passed:
            raise ValueError(f"quadratic Hawkes local spectral radius {radius:.8g} is not below 0.88")
        return result

    def step(self, dt: float, event_counts: ArrayLike) -> NDArray[np.float64]:
        step = float(dt)
        events = _finite_array(event_counts, "event_counts")
        if not math.isfinite(step) or step < 0 or events.shape != (4,) or np.any(events < 0):
            raise ValueError("dt must be nonnegative and event_counts a nonnegative four-vector")
        source_before = self.intensity.copy()
        candidate_memory = self.memory * np.exp(-self.beta * step) + events[None, :] * (self.alpha + self.gamma * source_before[None, :])
        candidate_intensity = self.mu + candidate_memory.sum(axis=1)
        # Check prospective state before committing, so a rejected update is atomic.
        self.audit_stability(candidate_intensity)
        self.memory = candidate_memory
        self.intensity = candidate_intensity
        return self.intensity.copy()


@dataclass
class UtilityIndifferencePricer:
    """CARA utility-indifference reservation pricer on scenario P&L.

    For terminal payoff X and inventory q, CE(q)=-gamma^{-1} log E[exp(-gamma q(X-m))]
    plus explicit quadratic inventory and jump-cascade penalties. Reservation
    bid = m + CE(q+1)-CE(q) - fee; ask = m + CE(q)-CE(q-1) + fee.
    The CE-difference formula is the exponential-utility indifference solution
    for a unit inventory change when the scenario distribution is held fixed.
    """
    gamma_risk: float = 0.05
    inventory_risk_penalty: float = 0.01
    jump_cascade_penalty: float = 0.05
    fee_per_unit: float = 0.0

    def __post_init__(self) -> None:
        self.gamma_risk = float(self.gamma_risk)
        self.inventory_risk_penalty = float(self.inventory_risk_penalty)
        self.jump_cascade_penalty = float(self.jump_cascade_penalty)
        self.fee_per_unit = float(self.fee_per_unit)
        vals = [self.gamma_risk, self.inventory_risk_penalty, self.jump_cascade_penalty, self.fee_per_unit]
        if not all(math.isfinite(v) for v in vals) or self.gamma_risk <= 0 or min(vals[1:]) < 0:
            raise ValueError("risk aversion must be positive; penalties and fee must be nonnegative")

    def utility(self, wealth: float) -> float:
        x = float(wealth)
        if not math.isfinite(x):
            raise ValueError("wealth must be finite")
        exponent = -self.gamma_risk * x
        if exponent > 700:
            return -math.inf
        return -math.exp(min(700.0, exponent)) / self.gamma_risk

    def certainty_equivalent(
        self,
        inventory: float,
        centered_payoff_scenarios: ArrayLike,
        *,
        cash: float = 0.0,
        cascade_score: float = 0.0,
    ) -> float:
        q, c, cascade = map(float, _finite_array([inventory, cash, cascade_score], "CE inputs"))
        x = _finite_array(centered_payoff_scenarios, "centered_payoff_scenarios")
        if x.ndim != 1 or x.size < 1 or cascade < 0:
            raise ValueError("scenarios must be a nonempty vector and cascade_score nonnegative")
        if cascade > 1:
            raise ValueError("cascade_score must be in [0,1]")
        y = -self.gamma_risk * q * x
        m = float(np.max(y))
        log_mean_exp = m + math.log(float(np.mean(np.exp(y - m))))
        ce = c - log_mean_exp / self.gamma_risk
        ce -= self.inventory_risk_penalty * (q ** 2) * float(np.var(x))
        ce -= self.jump_cascade_penalty * abs(q) * cascade
        return float(ce)

    def reservation_quotes(
        self,
        mid_price: float,
        inventory: float,
        payoff_scenarios: ArrayLike,
        *,
        cascade_score: float = 0.0,
    ) -> dict[str, float]:
        mark, q = map(float, _finite_array([mid_price, inventory], "quote inputs"))
        payoffs = _finite_array(payoff_scenarios, "payoff_scenarios")
        if mark < 0 or payoffs.ndim != 1 or payoffs.size < 1 or np.any(payoffs < 0):
            raise ValueError("mid_price and payoffs must be nonnegative and scenarios one-dimensional")
        centered = payoffs - mark
        ce_q = self.certainty_equivalent(q, centered, cascade_score=cascade_score)
        ce_buy = self.certainty_equivalent(q + 1.0, centered, cascade_score=cascade_score)
        ce_sell = self.certainty_equivalent(q - 1.0, centered, cascade_score=cascade_score)
        bid = mark + ce_buy - ce_q - self.fee_per_unit
        ask = mark + ce_q - ce_sell + self.fee_per_unit
        # Reservation quotes are kept economically ordered; any numeric breach is a fail-closed diagnostic.
        if ask + 1e-10 < bid:
            raise ArithmeticError("utility-indifference quote ordering violated")
        return {
            "reservation_bid": float(bid), "reservation_ask": float(ask),
            "mid_price": mark, "inventory": q, "risk_spread": float(ask - bid),
            "certainty_equivalent_inventory": float(ce_q), "cascade_score": float(cascade_score),
        }


def run_cycle51_example() -> dict[str, Any]:
    """Run reproducible Cycle 51 examples for VECM, L3 OFI, Hawkes, and CARA quotes."""
    out = _run_cycle51_core_example()
    out["cycle"] = 51
    out["engine"] = HFLOB_VIP_NAME
    out["synthetic_forward_nifty"] = synthetic_forward_price(24000.0, 0.065, 0.012, 30 / 365)
    vecm = VECMSpreadModel(beta=np.array([0.8, 0.2]), alpha0=0.01, kappa_vecm=0.25)
    fwd = synthetic_forward_price(24010.0, 0.065, 0.012, 30 / 365)
    out["vecm_spread"] = vecm.spread(fwd, [24000.0, 51000.0])
    out["vecm_half_life_seconds"] = vecm.half_life
    ofi = decompose_top5_ofi([5, 3, 2, 1, 1], [1, 0, 1, 0, 0], [3, 4, 1, 1, 0], [0, 1, 0, 0, 0])
    out["top5_ofi"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in ofi.items()}
    quadratic_hawkes = NonlinearQuadraticHawkesNetwork()
    out["quadratic_hawkes_radius"] = quadratic_hawkes.audit_stability()["spectral_radius"]
    out["quadratic_hawkes_intensity_after_events"] = quadratic_hawkes.step(0.01, [1, 0, 1, 0]).tolist()
    pricer = UtilityIndifferencePricer(gamma_risk=0.08, inventory_risk_penalty=0.02, jump_cascade_penalty=0.15, fee_per_unit=0.5)
    scenarios = np.array([17.0, 18.5, 19.0, 20.0, 21.5, 14.0, 22.0])
    out["utility_indifference_quotes"] = pricer.reservation_quotes(19.0, inventory=2.0, payoff_scenarios=scenarios, cascade_score=0.25)
    out["live_order_dispatch_enabled"] = False
    out["real_broker_fills_locked"] = True
    out["ledger_epoch"] = PAPER_LEDGER_EPOCH
    out["initial_capital_inr"] = INITIAL_CAPITAL_INR
    out["execution_mode"] = "PAPER_ONLY"
    return out
