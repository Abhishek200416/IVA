"""Cycle 47 offline quantitative research and paper-simulation engine.

This module is a deterministic, auditable research baseline, not a broker adapter
or production-certified trading system. Live execution is deliberately disabled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import math
import time

import numpy as np

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
STATE_DIM = 16
ACTION_DIM = 3
HURST_EXPONENT = 0.07
HAWKES_MAX_SPECTRAL_RADIUS = 0.88
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0


class Cycle47Error(ValueError):
    """Base exception for invalid model inputs and constraints."""


class StabilityError(Cycle47Error):
    """Raised when a Hawkes excitation matrix is not strictly stable."""


class SurfaceArbitrageError(Cycle47Error):
    """Raised when tested volatility-surface constraints fail."""


class RiskLimitError(Cycle47Error):
    """Raised when a risk or Greek-neutrality condition is violated."""


def _finite_array(value: Any, *, shape: tuple[int, ...] | None = None, name: str = "array") -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if shape is not None and arr.shape != shape:
        raise Cycle47Error(f"{name} must have shape {shape}, got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise Cycle47Error(f"{name} must contain only finite values")
    return arr


def _nonnegative(value: float, name: str) -> float:
    v = float(value)
    if not math.isfinite(v) or v < 0:
        raise Cycle47Error(f"{name} must be finite and nonnegative")
    return v


@dataclass(frozen=True)
class HawkesDiagnostics:
    spectral_radius: float
    stable: bool
    leadership: np.ndarray
    spillover_out: np.ndarray
    absorption_in: np.ndarray


class MultiHorizonHawkes:
    """Four-variate Hawkes process with fast and slow exponential kernels.

    ``Gamma = alpha_fast / beta_fast + alpha_slow / beta_slow`` is the
    integrated offspring matrix. Stability is enforced using rho(Gamma) < 0.88.
    Matrix entries are nonnegative and are interpreted as source-column to
    target-row excitation coefficients.
    """
    def __init__(self, mu: Sequence[float], alpha_fast: Any, beta_fast: Any,
                 alpha_slow: Any, beta_slow: Any,
                 max_spectral_radius: float = HAWKES_MAX_SPECTRAL_RADIUS):
        self.mu = _finite_array(mu, shape=(4,), name="mu")
        if np.any(self.mu <= 0):
            raise Cycle47Error("all Hawkes baselines mu must be positive")
        self.alpha_fast = _finite_array(alpha_fast, shape=(4, 4), name="alpha_fast")
        self.beta_fast = _finite_array(beta_fast, shape=(4, 4), name="beta_fast")
        self.alpha_slow = _finite_array(alpha_slow, shape=(4, 4), name="alpha_slow")
        self.beta_slow = _finite_array(beta_slow, shape=(4, 4), name="beta_slow")
        if np.any(self.alpha_fast < 0) or np.any(self.alpha_slow < 0):
            raise Cycle47Error("Hawkes excitation coefficients must be nonnegative")
        if np.any(self.beta_fast <= 0) or np.any(self.beta_slow <= 0):
            raise Cycle47Error("Hawkes decay rates must be positive")
        self.max_spectral_radius = float(max_spectral_radius)
        if not (0 < self.max_spectral_radius < 1):
            raise Cycle47Error("max_spectral_radius must lie in (0, 1)")
        self.gamma = self.alpha_fast / self.beta_fast + self.alpha_slow / self.beta_slow
        eig = np.linalg.eigvals(self.gamma)
        self.spectral_radius = float(np.max(np.abs(eig)))
        if not self.spectral_radius < self.max_spectral_radius:
            raise StabilityError(
                f"Hawkes rho(Gamma)={self.spectral_radius:.8g} must be strictly less than "
                f"{self.max_spectral_radius:.8g}"
            )
        # Retain source-target components because every (i,j) may have its own beta.
        self.fast_components = np.zeros((4, 4), dtype=float)
        self.slow_components = np.zeros((4, 4), dtype=float)
        self.elapsed = 0.0

    @classmethod
    def from_memory_times(cls, mu: Sequence[float], alpha_fast: Any, alpha_slow: Any,
                          tau_fast: float = 0.010, tau_slow: float = 1.0,
                          max_spectral_radius: float = HAWKES_MAX_SPECTRAL_RADIUS) -> "MultiHorizonHawkes":
        if tau_fast <= 0 or tau_slow <= 0:
            raise Cycle47Error("memory times must be positive")
        bf = np.full((4, 4), 1.0 / tau_fast)
        bs = np.full((4, 4), 1.0 / tau_slow)
        return cls(mu, alpha_fast, bf, alpha_slow, bs, max_spectral_radius)

    def intensity(self) -> np.ndarray:
        return self.mu + self.fast_components.sum(axis=1) + self.slow_components.sum(axis=1)

    def advance(self, dt: float, event_counts: Sequence[int] | None = None) -> np.ndarray:
        dt = float(dt)
        if not math.isfinite(dt) or dt < 0:
            raise Cycle47Error("dt must be finite and nonnegative")
        counts = np.zeros(4, dtype=float) if event_counts is None else _finite_array(event_counts, shape=(4,), name="event_counts")
        if np.any(counts < 0) or np.any(counts != np.floor(counts)):
            raise Cycle47Error("event_counts must be nonnegative integers")
        self.fast_components *= np.exp(-self.beta_fast * dt)
        self.slow_components *= np.exp(-self.beta_slow * dt)
        self.fast_components += self.alpha_fast * counts[np.newaxis, :]
        self.slow_components += self.alpha_slow * counts[np.newaxis, :]
        self.elapsed += dt
        return self.intensity().copy()

    def diagnostics(self, directional_scores: Any | None = None) -> HawkesDiagnostics:
        # Directed influence weights normalized by row/column totals.
        influence = self.gamma.copy()
        np.fill_diagonal(influence, 0.0)
        out = influence.sum(axis=0)
        into = influence.sum(axis=1)
        denom = max(float(np.max(out)), float(np.max(into)), 1e-12)
        spill = out / denom
        absorption = into / denom
        if directional_scores is None:
            # Asymmetric excitation is a model-implied lead-lag proxy, not causal proof.
            raw = self.gamma - self.gamma.T
        else:
            raw = _finite_array(directional_scores, shape=(4, 4), name="directional_scores")
        scale = max(float(np.max(np.abs(raw))), 1e-12)
        leadership = np.clip(raw / scale, -1.0, 1.0)
        np.fill_diagonal(leadership, 0.0)
        return HawkesDiagnostics(self.spectral_radius, True, leadership, spill, absorption)


def information_leadership_index(scores: Any) -> np.ndarray:
    """Scale a finite 4x4 directional score matrix into [-1, 1], zero diagonal."""
    s = _finite_array(scores, shape=(4, 4), name="scores")
    scale = max(float(np.max(np.abs(s))), 1e-12)
    out = np.clip(s / scale, -1.0, 1.0)
    np.fill_diagonal(out, 0.0)
    return out


def directed_centralities(adjacency: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return normalized source spillover (column sums) and target absorption (row sums)."""
    a = _finite_array(adjacency, shape=(4, 4), name="adjacency")
    if np.any(a < 0):
        raise Cycle47Error("adjacency weights must be nonnegative")
    out, into = a.sum(axis=0), a.sum(axis=1)
    scale = max(float(out.max(initial=0.0)), float(into.max(initial=0.0)), 1e-12)
    return out / scale, into / scale


@dataclass(frozen=True)
class SnellDecision:
    value: float
    immediate_value: float
    continuation_value: float
    action: str
    stopping: bool


def snell_envelope(immediate_value: float, expected_continuation: float,
                   holding_cost_rate: float, dt: float, discount_rate: float = 0.0) -> SnellDecision:
    """One-step Snell envelope: V=max(g, exp(-r dt) E[V_next] - c_h dt)."""
    vals = [float(immediate_value), float(expected_continuation), float(holding_cost_rate), float(dt), float(discount_rate)]
    if not all(math.isfinite(x) for x in vals) or holding_cost_rate < 0 or dt < 0 or discount_rate < 0:
        raise Cycle47Error("Snell inputs must be finite; rates, costs and dt must be nonnegative")
    continuation = math.exp(-discount_rate * dt) * expected_continuation - holding_cost_rate * dt
    stop = immediate_value >= continuation
    return SnellDecision(max(immediate_value, continuation), immediate_value, continuation,
                         "STOP" if stop else "CONTINUE", stop)


def stopping_boundary(immediate_values: Sequence[float], continuation_values: Sequence[float],
                      holding_cost_rate: float = 0.0, dt: float = 1.0) -> np.ndarray:
    g = _finite_array(immediate_values, name="immediate_values")
    c = _finite_array(continuation_values, shape=g.shape, name="continuation_values")
    if g.ndim != 1:
        raise Cycle47Error("values must be one-dimensional")
    return g >= (c - _nonnegative(holding_cost_rate, "holding_cost_rate") * _nonnegative(dt, "dt"))


def validate_state(state: Sequence[float]) -> np.ndarray:
    """Validate the 16-dimensional continuous actor-critic state."""
    s = _finite_array(state, shape=(STATE_DIM,), name="state")
    return s


class GaussianActorCritic:
    """Seeded two-hidden-layer Gaussian actor / value critic in pure NumPy.

    The actor parameterizes a latent diagonal Gaussian and applies tanh to keep
    actions in [-1,1]. The critic is an MLP state-value baseline. Update methods
    implement simple one-step policy-gradient and squared-error critic steps; this
    is a transparent research scaffold, not a pretrained or validated strategy.
    """
    def __init__(self, seed: int = 47, state_dim: int = STATE_DIM, action_dim: int = ACTION_DIM):
        if state_dim != STATE_DIM or action_dim != ACTION_DIM:
            raise Cycle47Error("Cycle 47 uses exactly 16 state and 3 action dimensions")
        rng = np.random.default_rng(seed)
        # Actor: 16 -> 32 -> 16 -> 3.
        self.actor_w1 = rng.normal(0.0, 0.05, (32, STATE_DIM)); self.actor_b1 = np.zeros(32)
        self.actor_w2 = rng.normal(0.0, 0.05, (16, 32)); self.actor_b2 = np.zeros(16)
        self.actor_w3 = rng.normal(0.0, 0.05, (ACTION_DIM, 16)); self.actor_b3 = np.zeros(ACTION_DIM)
        self.log_sigma = np.full(ACTION_DIM, -1.0)
        # Critic: 16 -> 32 -> 16 -> 1.
        self.critic_w1 = rng.normal(0.0, 0.05, (32, STATE_DIM)); self.critic_b1 = np.zeros(32)
        self.critic_w2 = rng.normal(0.0, 0.05, (16, 32)); self.critic_b2 = np.zeros(16)
        self.critic_w3 = rng.normal(0.0, 0.05, 16); self.critic_b3 = 0.0

    def _actor_forward(self, state: Sequence[float]) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray]]:
        s = validate_state(state)
        h1 = np.tanh(self.actor_w1 @ s + self.actor_b1)
        h2 = np.tanh(self.actor_w2 @ h1 + self.actor_b2)
        latent_mean = self.actor_w3 @ h2 + self.actor_b3
        return latent_mean, (s, h1, h2)

    def _critic_forward(self, state: Sequence[float]) -> tuple[float, tuple[np.ndarray, np.ndarray, np.ndarray]]:
        s = validate_state(state)
        h1 = np.tanh(self.critic_w1 @ s + self.critic_b1)
        h2 = np.tanh(self.critic_w2 @ h1 + self.critic_b2)
        value = float(self.critic_w3 @ h2 + self.critic_b3)
        return value, (s, h1, h2)

    def value(self, state: Sequence[float]) -> float:
        return self._critic_forward(state)[0]

    def policy_parameters(self, state: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
        """Return latent Gaussian location and positive diagonal standard deviation."""
        mean, _ = self._actor_forward(state)
        sigma = np.exp(np.clip(self.log_sigma, -5.0, 1.0))
        return mean, sigma

    def act(self, state: Sequence[float], *, deterministic: bool = True, seed: int | None = None) -> np.ndarray:
        mean, sigma = self.policy_parameters(state)
        latent = mean if deterministic else np.random.default_rng(seed).normal(mean, sigma)
        return np.tanh(latent)

    def friction_aware_advantage(self, state: Sequence[float], reward: float,
                                 next_state: Sequence[float], done: bool,
                                 gamma: float = 0.99, statutory_fees: float = 0.0,
                                 inventory_variance: float = 0.0,
                                 variance_penalty: float = 0.0) -> float:
        vals = [reward, gamma, statutory_fees, inventory_variance, variance_penalty]
        if not all(math.isfinite(float(v)) for v in vals) or not 0 <= gamma <= 1 or min(statutory_fees, inventory_variance, variance_penalty) < 0:
            raise Cycle47Error("invalid advantage inputs")
        target = float(reward) - float(statutory_fees) - float(variance_penalty) * float(inventory_variance)
        if not done:
            target += float(gamma) * self.value(next_state)
        return target - self.value(state)

    def train_critic(self, state: Sequence[float], target: float, learning_rate: float = 1e-3) -> float:
        target, learning_rate = float(target), float(learning_rate)
        if not math.isfinite(target) or not math.isfinite(learning_rate) or learning_rate <= 0:
            raise Cycle47Error("target must be finite and learning_rate positive")
        prediction, cache = self._critic_forward(state)
        s, h1, h2 = cache
        delta3 = target - prediction
        old_w3 = self.critic_w3.copy()
        delta2 = (old_w3 * delta3) * (1.0 - h2 * h2)
        old_w2 = self.critic_w2.copy()
        delta1 = (old_w2.T @ delta2) * (1.0 - h1 * h1)
        self.critic_w3 += learning_rate * delta3 * h2
        self.critic_b3 += learning_rate * delta3
        self.critic_w2 += learning_rate * np.outer(delta2, h1)
        self.critic_b2 += learning_rate * delta2
        self.critic_w1 += learning_rate * np.outer(delta1, s)
        self.critic_b1 += learning_rate * delta1
        return float(delta3)

    def train_linear_critic(self, state: Sequence[float], target: float, learning_rate: float = 1e-3) -> float:
        """Compatibility alias; critic is now a multilayer perceptron."""
        return self.train_critic(state, target, learning_rate)

    def train_actor(self, state: Sequence[float], action: Sequence[float], advantage: float,
                    learning_rate: float = 1e-4) -> float:
        """One REINFORCE-style Gaussian score step for a bounded tanh-Gaussian action."""
        a = _finite_array(action, shape=(ACTION_DIM,), name="action")
        adv, lr = float(advantage), float(learning_rate)
        if np.any(a < -1) or np.any(a > 1) or not math.isfinite(adv) or not math.isfinite(lr) or lr <= 0:
            raise Cycle47Error("invalid actor update inputs")
        mean, cache = self._actor_forward(state)
        s, h1, h2 = cache
        sigma = np.exp(np.clip(self.log_sigma, -5.0, 1.0))
        latent_action = np.arctanh(np.clip(a, -1.0 + 1e-6, 1.0 - 1e-6))
        # Score of diagonal Gaussian in latent space; tanh Jacobian is action-dependent only.
        grad_mean = adv * (latent_action - mean) / (sigma * sigma)
        grad_log_sigma = adv * (((latent_action - mean) ** 2) / (sigma * sigma) - 1.0)
        delta2 = (self.actor_w3.T @ grad_mean) * (1.0 - h2 * h2)
        old_w2 = self.actor_w2.copy()
        delta1 = (old_w2.T @ delta2) * (1.0 - h1 * h1)
        self.actor_w3 += lr * np.outer(grad_mean, h2)
        self.actor_b3 += lr * grad_mean
        self.actor_w2 += lr * np.outer(delta2, h1)
        self.actor_b2 += lr * delta2
        self.actor_w1 += lr * np.outer(delta1, s)
        self.actor_b1 += lr * delta1
        self.log_sigma = np.clip(self.log_sigma + lr * grad_log_sigma, -5.0, 1.0)
        return float(np.linalg.norm(grad_mean))

def actor_action_interpretation(action: Sequence[float]) -> dict[str, float]:
    a = _finite_array(action, shape=(ACTION_DIM,), name="action")
    if np.any(a < -1.0) or np.any(a > 1.0):
        raise Cycle47Error("actor actions must lie in [-1, 1]")
    return {"spread_placement": float(a[0]), "cancellation_bias": float(a[1]), "size_dampener": float((a[2] + 1.0) / 2.0)}


@dataclass(frozen=True)
class CancellationHazard:
    hazard_rate: float
    survival_probability: float
    revision: str
    expected_fill_hazard: float


def cancellation_hazard(depth: float, age: float, lambda0: float = 0.02,
                         kappa_depth: float = 0.5, kappa_age: float = 0.1) -> float:
    depth = max(float(depth), 1.0)
    age, lambda0, kappa_depth, kappa_age = map(float, (age, lambda0, kappa_depth, kappa_age))
    if not all(math.isfinite(x) for x in (depth, age, lambda0, kappa_depth, kappa_age)):
        raise Cycle47Error("hazard inputs must be finite")
    if age < 0 or lambda0 < 0 or kappa_depth < 0 or kappa_age < 0:
        raise Cycle47Error("age, baseline hazard and coefficients must be nonnegative")
    exponent = min(kappa_depth / depth + kappa_age * age, 700.0)
    return lambda0 * math.exp(exponent)


def order_survival_and_revision(tau: float, queue_ahead: float, depth: float, age: float,
                                lambda0: float = 0.02, kappa_depth: float = 0.5,
                                kappa_age: float = 0.1, fill_rate: float = 0.1,
                                min_survival: float = 0.25) -> CancellationHazard:
    tau, queue_ahead, fill_rate, min_survival = map(float, (tau, queue_ahead, fill_rate, min_survival))
    if not all(math.isfinite(x) for x in (tau, queue_ahead, fill_rate, min_survival)) or tau < 0 or queue_ahead < 0 or fill_rate < 0 or not 0 <= min_survival <= 1:
        raise Cycle47Error("invalid order survival inputs")
    h_cancel = cancellation_hazard(depth, age, lambda0, kappa_depth, kappa_age)
    h_fill = fill_rate / (1.0 + queue_ahead)
    survival = math.exp(-(h_cancel + h_fill) * tau)
    revision = "HOLD" if survival >= min_survival else "REVISE_OR_PULL"
    return CancellationHazard(h_cancel + h_fill, survival, revision, h_fill)


def debias_tick_returns(returns: Sequence[float], *, pairwise: bool = True) -> np.ndarray:
    """Simple reproducible bid-ask-bounce filter by pair averaging.

    This reduces alternating-sign microstructure noise; it is not a universal
    noise estimator and should be validated for the sampling design in use.
    """
    r = _finite_array(returns, name="returns")
    if r.ndim != 1:
        raise Cycle47Error("returns must be one-dimensional")
    if not pairwise:
        return r.copy()
    n = len(r) // 2
    if n == 0:
        return r.copy()
    out = (r[:2*n:2] + r[1:2*n:2]) / 2.0
    if len(r) % 2:
        out = np.concatenate([out, r[-1:]])
    return out


@dataclass(frozen=True)
class TSRVEstimate:
    rv_slow: float
    rv_fast: float
    correction: float
    tsrv: float
    n_slow: int
    n_fast: int


def tsrv_estimate(fast_returns: Sequence[float], slow_returns: Sequence[float],
                  n_fast: int | None = None, n_slow: int | None = None) -> TSRVEstimate:
    fast = _finite_array(fast_returns, name="fast_returns")
    slow = _finite_array(slow_returns, name="slow_returns")
    if fast.ndim != 1 or slow.ndim != 1 or len(fast) == 0 or len(slow) == 0:
        raise Cycle47Error("fast and slow returns must be nonempty vectors")
    nf, ns = len(fast) if n_fast is None else int(n_fast), len(slow) if n_slow is None else int(n_slow)
    if nf <= 0 or ns <= 0 or ns > nf:
        raise Cycle47Error("counts must satisfy n_fast >= n_slow > 0")
    rvf, rvs = float(fast @ fast), float(slow @ slow)
    corr = (ns / nf) * rvf
    return TSRVEstimate(rvs, rvf, corr, rvs - corr, ns, nf)


def two_scale_realized_variance(fast_returns: Sequence[float], slow_returns: Sequence[float],
                                n_fast: int | None = None, n_slow: int | None = None) -> float:
    return tsrv_estimate(fast_returns, slow_returns, n_fast, n_slow).tsrv


def rough_volterra_kernel(t: Any, hurst: float = HURST_EXPONENT) -> np.ndarray | float:
    h = float(hurst)
    if not 0 < h < 0.5:
        raise Cycle47Error("rough Hurst exponent must lie in (0, 0.5)")
    times = np.asarray(t, dtype=float)
    if np.any(~np.isfinite(times)) or np.any(times <= 0):
        raise Cycle47Error("kernel times must be finite and positive")
    # Gamma function at H+1/2 is available through math.gamma.
    result = np.power(times, h - 0.5) / math.gamma(h + 0.5)
    return float(result) if result.ndim == 0 else result


def markovian_exponential_lift(hurst: float = HURST_EXPONENT, n_factors: int = 12,
                               t_min: float = 1e-3, t_max: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Approximate the rough kernel with a nonnegative 12-factor exponential lift.

    Returns positive decay rates and nonnegative least-squares-clipped weights.
    It is a practical discretized lift, not a certified uniform approximation.
    """
    if int(n_factors) < 1 or not 0 < t_min < t_max or not math.isfinite(t_max):
        raise Cycle47Error("invalid exponential-lift settings")
    rates = np.geomspace(1.0 / t_max, 1.0 / t_min, int(n_factors))
    grid = np.geomspace(t_min, t_max, max(300, 30 * int(n_factors)))
    design = np.exp(-np.outer(grid, rates))
    target = np.asarray(rough_volterra_kernel(grid, hurst), dtype=float)
    weights, *_ = np.linalg.lstsq(design, target, rcond=None)
    weights = np.maximum(weights, 0.0)
    if not np.any(weights > 0):
        weights[np.argmin(np.abs(rates - 1.0 / math.sqrt(t_min * t_max)))] = 1e-12
    return rates, weights


def validate_total_variance_surface(expiries: Sequence[float], log_moneyness: Sequence[float],
                                    total_variance: Any, beta_call: float, beta_put: float,
                                    tolerance: float = 1e-10,
                                    normalized_call_prices: Any | None = None) -> dict[str, Any]:
    """Check discrete calendar monotonicity/nonnegativity and Roger-Lee wing bounds.

    This finite-grid check does not prove continuous-strike butterfly arbitrage freedom.
    """
    t = _finite_array(expiries, name="expiries")
    k = _finite_array(log_moneyness, name="log_moneyness")
    w = _finite_array(total_variance, name="total_variance")
    if t.ndim != 1 or k.ndim != 1 or len(t) < 1 or len(k) < 1 or w.shape != (len(t), len(k)):
        raise Cycle47Error("surface dimensions must be (number of expiries, number of strikes)")
    if np.any(t <= 0) or np.any(np.diff(t) <= 0):
        raise Cycle47Error("expiries must be positive and strictly increasing")
    if np.any(np.diff(k) <= 0) or np.any(w < -tolerance):
        raise SurfaceArbitrageError("strikes must increase and total variance must be nonnegative")
    if not (0 < float(beta_call) <= 2.0 and 0 < float(beta_put) <= 2.0):
        raise SurfaceArbitrageError("Roger-Lee wing slopes must lie in (0, 2]")
    calendar_ok = bool(np.all(np.diff(w, axis=0) >= -tolerance))
    if not calendar_ok:
        raise SurfaceArbitrageError("calendar arbitrage: total variance decreases with expiry")
    butterfly_checked = False
    if normalized_call_prices is not None:
        calls = _finite_array(normalized_call_prices, name="normalized_call_prices")
        if calls.shape != w.shape:
            raise Cycle47Error("normalized_call_prices must match total_variance shape")
        for row in calls:
            validate_call_price_butterfly(np.exp(k), row, tolerance=tolerance)
        butterfly_checked = True
    return {"calendar_monotone": True, "nonnegative_total_variance": True,
            "roger_lee_call_beta": float(beta_call), "roger_lee_put_beta": float(beta_put),
            "finite_grid_only": True, "butterfly_checked": butterfly_checked}


def validate_call_price_butterfly(normalized_strikes: Sequence[float],
                                  normalized_call_prices: Sequence[float],
                                  tolerance: float = 1e-8) -> dict[str, bool]:
    """Check discrete normalized call no-arbitrage bounds, monotonicity and convexity.

    Strikes are K/F and prices are C/F. This finite-grid check is necessary but not
    sufficient to prove a continuous arbitrage-free surface between grid points.
    """
    x = _finite_array(normalized_strikes, name="normalized_strikes")
    c = _finite_array(normalized_call_prices, name="normalized_call_prices")
    tol = float(tolerance)
    if x.ndim != 1 or c.ndim != 1 or len(x) != len(c) or len(x) < 3:
        raise Cycle47Error("strikes and call prices must be equal-length vectors with at least 3 points")
    if not math.isfinite(tol) or tol < 0 or np.any(x <= 0) or np.any(np.diff(x) <= 0):
        raise Cycle47Error("strikes must be positive, strictly increasing and tolerance nonnegative")
    lower = np.maximum(1.0 - x, 0.0)
    if np.any(c < lower - tol) or np.any(c > 1.0 + tol):
        raise SurfaceArbitrageError("normalized calls violate intrinsic/upper price bounds")
    slopes = np.diff(c) / np.diff(x)
    if np.any(slopes > tol) or np.any(slopes < -1.0 - tol):
        raise SurfaceArbitrageError("call prices violate decreasingness or slope bounds [-1,0]")
    if np.any(np.diff(slopes) < -tol):
        raise SurfaceArbitrageError("call prices are not discretely convex in strike (butterfly arbitrage)")
    return {"price_bounds": True, "decreasing_calls": True, "slope_bounds": True, "convex_calls": True}


def dealer_net_gamma_exposure(open_interest: Sequence[float], option_gamma: Sequence[float], spot: float) -> float:
    oi = _finite_array(open_interest, name="open_interest")
    ga = _finite_array(option_gamma, shape=oi.shape, name="option_gamma")
    spot = float(spot)
    if oi.ndim != 1 or np.any(oi < 0) or not math.isfinite(spot) or spot <= 0:
        raise Cycle47Error("open interest must be a nonnegative vector and spot positive")
    return float(np.sum(oi * ga * spot))


def gamma_squeeze_hazard(gamma_dealer: float, depth: float, lambda0: float = 0.01,
                         kappa: float = 0.5) -> float:
    gamma_dealer, depth, lambda0, kappa = map(float, (gamma_dealer, depth, lambda0, kappa))
    if not all(math.isfinite(x) for x in (gamma_dealer, depth, lambda0, kappa)) or depth <= 0 or lambda0 < 0 or kappa < 0:
        raise Cycle47Error("invalid GEX hazard parameters")
    return lambda0 * math.exp(min(kappa * abs(gamma_dealer) / depth, 700.0))


def quote_retreat_decision(gamma_dealer: float, depth: float, hazard_threshold: float,
                           toxic_cascade: bool = False, lambda0: float = 0.01,
                           kappa: float = 0.5) -> dict[str, Any]:
    hazard = gamma_squeeze_hazard(gamma_dealer, depth, lambda0, kappa)
    if not math.isfinite(hazard_threshold) or hazard_threshold < 0:
        raise Cycle47Error("hazard_threshold must be finite and nonnegative")
    retreat = bool(toxic_cascade or hazard >= hazard_threshold)
    return {"lambda_squeeze": hazard, "toxic_cascade": bool(toxic_cascade),
            "quote_action": "RETREAT" if retreat else "MAINTAIN"}


@dataclass(frozen=True)
class HedgeResult:
    weights: np.ndarray
    objective: float
    delta_net: float
    gamma_net: float
    vega_net: float
    success: bool
    message: str


def greek_neutral_hedge(covariance: Any, greek_exposures: Any, current_greeks: Sequence[float],
                        spreads: Sequence[float], lambda_cost: float = 0.01,
                        lambda_spread: float = 0.01, bounds: float | Sequence[tuple[float, float]] = 10.0,
                        delta_tolerance: float = 1.02e-4, gamma_tolerance: float = 1.02e-3,
                        vega_tolerance: float = 1.0002) -> HedgeResult:
    """Convex quadratic hedge with L1 and spread costs and absolute Greek constraints.

    Uses SLSQP with an epigraph for L1 costs. Rejects an infeasible solve instead
    of silently returning a non-neutral portfolio.
    """
    cov = _finite_array(covariance, name="covariance")
    greeks = _finite_array(greek_exposures, name="greek_exposures")
    curr = _finite_array(current_greeks, shape=(3,), name="current_greeks")
    spread = _finite_array(spreads, name="spreads")
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1] or greeks.shape != (3, cov.shape[0]) or spread.shape != (cov.shape[0],):
        raise Cycle47Error("covariance, Greek exposures, and spreads have inconsistent dimensions")
    if not np.allclose(cov, cov.T, atol=1e-10) or np.min(np.linalg.eigvalsh(cov)) < -1e-8:
        raise Cycle47Error("covariance must be symmetric positive semidefinite")
    if np.any(spread < 0) or lambda_cost < 0 or lambda_spread < 0:
        raise Cycle47Error("spreads and cost penalties must be nonnegative")
    if isinstance(bounds, (int, float)):
        b = float(bounds)
        if not math.isfinite(b) or b <= 0:
            raise Cycle47Error("scalar bounds must be positive and finite")
        bnds = [(-b, b)] * cov.shape[0]
    else:
        bnds = list(bounds)
        if len(bnds) != cov.shape[0] or any(lo > hi for lo, hi in bnds):
            raise Cycle47Error("invalid per-instrument bounds")
    tol = np.asarray([delta_tolerance, gamma_tolerance, vega_tolerance], dtype=float)
    if np.any(~np.isfinite(tol)) or np.any(tol <= 0):
        raise Cycle47Error("Greek tolerances must be positive")
    try:
        from scipy.optimize import minimize
        n = cov.shape[0]
        # x=[w, u], u>=|w|. Objective is smooth in this epigraph form.
        def obj(x: np.ndarray) -> float:
            w, u = x[:n], x[n:]
            return float(0.5 * w @ cov @ w + lambda_cost * np.sum(u) + lambda_spread * (w @ spread))
        def cons_greeks(x: np.ndarray) -> np.ndarray:
            net = curr + greeks @ x[:n]
            return np.concatenate([tol - net, tol + net])
        def cons_abs_pos(x: np.ndarray) -> np.ndarray:
            w, u = x[:n], x[n:]
            return np.concatenate([u - w, u + w])
        x0 = np.zeros(2*n)
        x0[n:] = 1e-8
        opt_bounds = bnds + [(0.0, None)] * n
        res = minimize(obj, x0, method="SLSQP", bounds=opt_bounds,
                       constraints=[{"type": "ineq", "fun": cons_greeks}, {"type": "ineq", "fun": cons_abs_pos}],
                       options={"ftol": 1e-12, "maxiter": 1500, "disp": False})
        weights = res.x[:n]
        net = curr + greeks @ weights
        okay = bool(res.success and np.all(np.abs(net) <= tol + 1e-7))
        return HedgeResult(weights.copy(), obj(res.x), float(net[0]), float(net[1]), float(net[2]), okay, str(res.message))
    except ImportError as exc:
        raise RuntimeError("scipy is required for constrained Greek-neutral optimization") from exc


@dataclass(frozen=True)
class FeeBreakdown:
    stt: float
    stamp_duty: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    total: float


def indian_statutory_fees(buy_turnover: float, sell_turnover: float, legs: int = 1) -> FeeBreakdown:
    """Specified options schedule. GST applies to exchange + SEBI + brokerage.

    STT and stamp duty are excluded from the GST base in this stated schedule.
    Currency inputs are INR turnover; ``legs`` is the count of charged order legs.
    """
    buy, sell = float(buy_turnover), float(sell_turnover)
    if not all(math.isfinite(x) and x >= 0 for x in (buy, sell)) or int(legs) != legs or legs < 0:
        raise Cycle47Error("turnover must be nonnegative and legs a nonnegative integer")
    stt = 0.0015 * sell
    stamp = 0.00003 * buy
    exch = (3553.0 / 10_000_000.0) * (buy + sell)
    sebi = (10.0 / 10_000_000.0) * (buy + sell)
    brokerage = 20.0 * int(legs)
    gst = 0.18 * (exch + sebi + brokerage)
    return FeeBreakdown(stt, stamp, exch, sebi, brokerage, gst, stt + stamp + exch + sebi + brokerage + gst)


def net_alpha_gate(expected_gross_alpha: float, fees: FeeBreakdown) -> dict[str, float | bool]:
    gross = float(expected_gross_alpha)
    if not math.isfinite(gross):
        raise Cycle47Error("expected gross alpha must be finite")
    net = gross - float(fees.total)
    return {"expected_gross_alpha": gross, "total_statutory_fees": fees.total,
            "expected_net_alpha": net, "approved": bool(net > 0.0)}


@dataclass
class AntiTiltController:
    tau_base: float = 1.0
    theta_v: float = 1.0
    sigma_base: float = 1.0
    minimum_spacing_seconds: float = 30.0
    max_size_acceleration: float = 1.25
    loss_limit: int = 3
    consecutive_losses: int = 0
    last_trade_time: float | None = None
    last_size: float = 0.0

    def cooldown(self, sigma_rough: float) -> float:
        sig = float(sigma_rough)
        if not math.isfinite(sig) or sig < 0 or self.tau_base < 0 or self.theta_v < 0 or self.sigma_base <= 0:
            raise Cycle47Error("invalid cooldown inputs")
        return self.tau_base * (1.0 + self.theta_v * sig / self.sigma_base)

    def record_result(self, pnl: float) -> None:
        pnl = float(pnl)
        if not math.isfinite(pnl):
            raise Cycle47Error("pnl must be finite")
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

    def approve_trade(self, now: float, size: float, sigma_rough: float) -> tuple[bool, str, float]:
        now, size = float(now), float(size)
        if not math.isfinite(now) or not math.isfinite(size) or size <= 0:
            return False, "INVALID_TIME_OR_SIZE", self.cooldown(sigma_rough)
        wait = self.cooldown(sigma_rough)
        if self.consecutive_losses >= self.loss_limit:
            return False, "THREE_CONSECUTIVE_LOSSES", wait
        if self.last_trade_time is not None and now - self.last_trade_time < self.minimum_spacing_seconds:
            return False, "TRADE_SPACING_LT_30S", wait
        if self.last_size > 0 and size / self.last_size > self.max_size_acceleration:
            return False, "SIZE_ACCELERATION_GT_1.25X", wait
        return True, "APPROVED_FOR_PAPER_SIMULATION", wait

    def commit_paper_trade(self, now: float, size: float) -> None:
        self.last_trade_time, self.last_size = float(now), float(size)


@dataclass(frozen=True)
class AgentVerdict:
    name: str
    approve: bool
    reason: str


@dataclass(frozen=True)
class SquadDecision:
    approve: bool
    verdicts: tuple[AgentVerdict, ...]
    manager_veto: bool
    reason: str


def squad_consensus(*, manager_approved: bool, alex_approved: bool,
                    emily_approved: bool, max_approved: bool) -> SquadDecision:
    verdicts = (
        AgentVerdict("Abhi", bool(manager_approved), "capital approval and binding live veto"),
        AgentVerdict("Alex", bool(alex_approved), "L3 queue and microstructure risk"),
        AgentVerdict("Emily", bool(emily_approved), "rough volatility and macro risk"),
        AgentVerdict("Max", bool(max_approved), "statutory net alpha and Bayesian-Kelly sizing"),
    )
    if not manager_approved:
        return SquadDecision(False, verdicts, True, "MANAGER_ABHI_VETO")
    passed = all(v.approve for v in verdicts)
    return SquadDecision(passed, verdicts, False, "ALL_APPROVED" if passed else "AGENT_RISK_VETO")


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Unconditionally deny live order dispatch; it never inspects arguments."""
    raise PermissionError("Cycle 47 is paper-simulation only; live order dispatch is permanently disabled")


@dataclass
class PaperLedger:
    epoch: str = PAPER_LEDGER_EPOCH
    initial_capital: float = INITIAL_CAPITAL_INR
    cash: float = INITIAL_CAPITAL_INR
    realized_pnl: float = 0.0
    trade_count: int = 0
    entries: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.epoch != PAPER_LEDGER_EPOCH or self.initial_capital != INITIAL_CAPITAL_INR:
            raise Cycle47Error("Cycle 47 paper ledger epoch/capital are fixed")
        if not math.isfinite(self.cash) or self.cash < 0:
            raise Cycle47Error("paper ledger cash must be finite and nonnegative")

    def record(self, *, pnl: float, fees: float = 0.0, label: str = "paper_fill") -> dict[str, Any]:
        pnl, fees = float(pnl), float(fees)
        if not all(math.isfinite(x) for x in (pnl, fees)) or fees < 0:
            raise Cycle47Error("pnl must be finite and fees nonnegative")
        net = pnl - fees
        self.cash += net
        self.realized_pnl += net
        self.trade_count += 1
        row = {"epoch": self.epoch, "trade": self.trade_count, "label": str(label),
               "gross_pnl": pnl, "fees": fees, "net_pnl": net, "cash": self.cash}
        self.entries.append(row)
        return row


def default_hawkes_model() -> MultiHorizonHawkes:
    """Stable small-excitation example across the four specified index families."""
    af = np.full((4, 4), 0.0005)
    ass = np.full((4, 4), 0.04)
    np.fill_diagonal(af, 0.002)
    np.fill_diagonal(ass, 0.06)
    # rho integrated excitation is comfortably below 0.88 with these memory scales.
    return MultiHorizonHawkes.from_memory_times([0.2, 0.18, 0.12, 0.1], af, ass, 0.010, 1.0)


def run_cycle47_example() -> dict[str, Any]:
    hawkes = default_hawkes_model()
    before = hawkes.intensity()
    after = hawkes.advance(0.01, [1, 0, 0, 0])
    actor = GaussianActorCritic(seed=47)
    state = np.linspace(-0.5, 0.5, STATE_DIM)
    action = actor.act(state)
    fee = indian_statutory_fees(5000.0, 5000.0, legs=2)
    gate = net_alpha_gate(5.0, fee)
    hazard = order_survival_and_revision(0.5, 4, 10, 0.2)
    ledger = PaperLedger()
    ledger.record(pnl=3.0, fees=fee.total, label="cycle47_example")
    return {
        "cycle": 47,
        "assets": list(ASSETS),
        "hawkes_spectral_radius": hawkes.spectral_radius,
        "hawkes_stable": hawkes.spectral_radius < HAWKES_MAX_SPECTRAL_RADIUS,
        "intensity_before": before.tolist(),
        "intensity_after": after.tolist(),
        "actor_action": action.tolist(),
        "order_survival": hazard.survival_probability,
        "order_revision": hazard.revision,
        "fee_total_inr": fee.total,
        "net_alpha_approved": gate["approved"],
        "paper_ledger_cash": ledger.cash,
        "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
        "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED,
    }


__all__ = [
    "ASSETS", "STATE_DIM", "ACTION_DIM", "HURST_EXPONENT", "HAWKES_MAX_SPECTRAL_RADIUS",
    "LIVE_ORDER_DISPATCH_ENABLED", "REAL_BROKER_FILLS_LOCKED", "PAPER_LEDGER_EPOCH", "INITIAL_CAPITAL_INR",
    "Cycle47Error", "StabilityError", "SurfaceArbitrageError", "RiskLimitError", "HawkesDiagnostics",
    "MultiHorizonHawkes", "information_leadership_index", "directed_centralities", "SnellDecision",
    "snell_envelope", "stopping_boundary", "validate_state", "GaussianActorCritic", "actor_action_interpretation",
    "CancellationHazard", "cancellation_hazard", "order_survival_and_revision", "debias_tick_returns",
    "TSRVEstimate", "tsrv_estimate", "two_scale_realized_variance", "rough_volterra_kernel",
    "markovian_exponential_lift", "validate_total_variance_surface", "validate_call_price_butterfly", "dealer_net_gamma_exposure",
    "gamma_squeeze_hazard", "quote_retreat_decision", "HedgeResult", "greek_neutral_hedge", "FeeBreakdown",
    "indian_statutory_fees", "net_alpha_gate", "AntiTiltController", "AgentVerdict", "SquadDecision",
    "squad_consensus", "dispatch_live_order", "PaperLedger", "default_hawkes_model", "run_cycle47_example",
]
