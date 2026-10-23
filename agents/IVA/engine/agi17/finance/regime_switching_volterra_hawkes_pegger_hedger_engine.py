"""Cycle 49 regime-switching Volterra-Hawkes execution research engine.

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
            raise ValueError("Cycle 49 contract is a 16-state, 3-action policy")
        self._actor = _MLP(self.state_dim, 32, 16, self.action_dim, self.seed)
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
        mu, _ = self._actor.forward(X)
        return np.tanh(mu), np.broadcast_to(np.exp(self.log_std), mu.shape).copy()

    def act(self, state: ArrayLike, *, deterministic: bool = False) -> NDArray[np.float64]:
        X = _finite_array(state, "state")
        if X.shape != (self.state_dim,):
            raise ValueError("state must have shape (16,)")
        raw, _ = self._actor.forward(X[None, :])
        latent = raw[0] if deterministic else raw[0] + self._rng.normal(0.0, np.exp(self.log_std))
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
        mu, cache = self._actor.forward(X)
        sigma = np.exp(self.log_std)
        # Gaussian score gradient in latent action space; tanh Jacobian is part
        # of the transformed density but omitted from the mean-parameter score.
        grad_mu = (mu - latent) / (sigma * sigma) * adv
        loss = float(-np.mean(adv * (-0.5 * ((latent - mu) / sigma) ** 2 - self.log_std)))
        self._actor.backprop(cache, grad_mu, self.learning_rate)
        grad_log_std = np.mean(1.0 - ((latent - mu) / sigma) ** 2, axis=0) * (-np.mean(adv))
        self.log_std = np.clip(self.log_std - self.learning_rate * np.clip(grad_log_std, -1.0, 1.0), -5.0, 1.0)
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
    raise PermissionError("Cycle 49 is paper-only: live broker order dispatch is disabled")


def run_cycle49_example() -> dict[str, Any]:
    tracker = HMMBeliefTracker()
    belief = tracker.update([0.2, 0.3, 0.8])
    hawkes = RegimeSwitchingHawkesNetwork()
    intensities = hawkes.advance(0.01, [1, 0, 1, 0])
    state = build_state_vector(0.1, intensities[0], intensities[1], belief, 0.04, 0.25, 0.1, 0.5)
    actor = ContinuousActorCritic(seed=49)
    action = actor.act(state, deterministic=True)
    survival = order_survival_probability(0.5, 2.0, depth=8.0, age=0.3, fill_rate=0.05)
    fees = IndianStatutoryFees().calculate(buy_turnover=100_000.0, sell_turnover=100_000.0, executed_legs=2)
    alpha = expected_net_alpha_gate(500.0, fees["total_fees"])
    quote = quote_retreat_decision(toxic_cascade=False, squeeze_hazard=0.2, hazard_threshold=1.0)
    return {
        "cycle": 49,
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
