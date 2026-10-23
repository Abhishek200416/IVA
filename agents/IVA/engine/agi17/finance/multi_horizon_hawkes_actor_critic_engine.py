"""Cycle 46: multi-horizon Hawkes, actor-critic pegging and microstructure research engine.

This module is an offline research and paper-simulation reference. It deliberately
contains no broker client, credential handling, or live order path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, gamma, isfinite, log, sin, pi
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize

ASSETS: tuple[str, ...] = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
STATE_DIM = 16
ACTION_DIM = 3
HURST_DEFAULT = 0.07
LAMBDA_STABILITY_LIMIT = 0.88
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
RUPEES_PER_CRORE = 10_000_000.0


def _finite_scalar(value: float, name: str) -> float:
    x = float(value)
    if not isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _vector(value: Sequence[float], size: int, name: str, *, nonnegative: bool = False) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (size,) or not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be a finite vector of length {size}")
    if nonnegative and np.any(arr < 0):
        raise ValueError(f"{name} must be nonnegative")
    return arr


def _matrix(value: Sequence[Sequence[float]], shape: tuple[int, int], name: str, *, nonnegative: bool = False) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != shape or not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must have shape {shape} and finite values")
    if nonnegative and np.any(arr < 0):
        raise ValueError(f"{name} must be nonnegative")
    return arr


class MultiHorizonHawkes:
    """Four-dimensional Hawkes memory with fast and slow exponential lifts.

    Matrix convention: alpha[target, source]. The integrated joint excitation
    matrix is Gamma_ij = alpha_fast_ij*tau_fast + alpha_slow_ij*tau_slow.
    Stationarity is accepted only when spectral_radius(Gamma) < 0.88.
    """

    def __init__(self, mu: Sequence[float], alpha_fast: Sequence[Sequence[float]],
                 alpha_slow: Sequence[Sequence[float]], tau_fast: float = 0.010,
                 tau_slow: float = 1.0, stability_limit: float = LAMBDA_STABILITY_LIMIT):
        self.mu = _vector(mu, 4, "mu", nonnegative=True)
        self.alpha_fast = _matrix(alpha_fast, (4, 4), "alpha_fast", nonnegative=True)
        self.alpha_slow = _matrix(alpha_slow, (4, 4), "alpha_slow", nonnegative=True)
        self.tau_fast = _finite_scalar(tau_fast, "tau_fast")
        self.tau_slow = _finite_scalar(tau_slow, "tau_slow")
        self.stability_limit = _finite_scalar(stability_limit, "stability_limit")
        if self.tau_fast <= 0 or self.tau_slow <= 0:
            raise ValueError("decay time constants must be positive")
        if not 0 < self.stability_limit < 1:
            raise ValueError("stability_limit must lie in (0, 1)")
        self.gamma_matrix = self.alpha_fast * self.tau_fast + self.alpha_slow * self.tau_slow
        self.spectral_radius = float(np.max(np.abs(np.linalg.eigvals(self.gamma_matrix))))
        if not self.spectral_radius < self.stability_limit:
            raise ValueError(f"unstable Hawkes excitation: rho={self.spectral_radius:.8g} >= {self.stability_limit}")
        self._fast_state = np.zeros(4, dtype=float)
        self._slow_state = np.zeros(4, dtype=float)
        self.elapsed = 0.0

    @property
    def intensity(self) -> np.ndarray:
        """Current conditional intensity vector (events per time unit)."""
        return self.mu + self._fast_state + self._slow_state

    def advance(self, dt: float) -> np.ndarray:
        dt = _finite_scalar(dt, "dt")
        if dt < 0:
            raise ValueError("dt cannot be negative")
        self._fast_state *= exp(-dt / self.tau_fast)
        self._slow_state *= exp(-dt / self.tau_slow)
        self.elapsed += dt
        return self.intensity.copy()

    def register_event(self, asset: str | int) -> np.ndarray:
        idx = ASSETS.index(asset) if isinstance(asset, str) else int(asset)
        if not 0 <= idx < 4:
            raise ValueError("asset must be one of four configured assets")
        self._fast_state += self.alpha_fast[:, idx]
        self._slow_state += self.alpha_slow[:, idx]
        return self.intensity.copy()

    def leadership_index(self) -> np.ndarray:
        """Signed directed leadership matrix in [-1, 1]; row is target, col source."""
        out = np.zeros((4, 4), dtype=float)
        for i in range(4):
            for j in range(4):
                denom = self.gamma_matrix[i, j] + self.gamma_matrix[j, i]
                out[i, j] = 0.0 if denom <= 1e-15 else (self.gamma_matrix[i, j] - self.gamma_matrix[j, i]) / denom
        return np.clip(out, -1.0, 1.0)

    def spillover_centralities(self) -> dict[str, dict[str, float]]:
        # Column sums measure a source asset's excitation spillover; row sums
        # measure the target asset's received excitation / absorption load.
        outgoing = np.sum(self.gamma_matrix, axis=0)
        incoming = np.sum(self.gamma_matrix, axis=1)
        return {
            "outgoing_spillover": {a: float(outgoing[i]) for i, a in enumerate(ASSETS)},
            "incoming_absorption": {a: float(incoming[i]) for i, a in enumerate(ASSETS)},
        }

    def stress_summary(self) -> dict[str, Any]:
        return {"spectral_radius": self.spectral_radius, "stable": self.spectral_radius < self.stability_limit,
                "intensity": self.intensity.tolist(), "centralities": self.spillover_centralities()}


def encode_actor_state(ofi: Sequence[float], hawkes_intensity: Sequence[float],
                       rough_variance_lift: Sequence[float], queue_priority_position: float,
                       dealer_gex_stress: float, bid_ask_spread: float,
                       time_to_expiry_norm: float = 0.0) -> np.ndarray:
    """Encode four OFI, four Hawkes, four rough-lift, and four scalar fields."""
    out = np.concatenate([
        _vector(ofi, 4, "ofi"), _vector(hawkes_intensity, 4, "hawkes_intensity", nonnegative=True),
        _vector(rough_variance_lift, 4, "rough_variance_lift", nonnegative=True),
        np.asarray([queue_priority_position, dealer_gex_stress, bid_ask_spread, time_to_expiry_norm], dtype=float),
    ])
    if out.shape != (STATE_DIM,) or not np.all(np.isfinite(out)):
        raise ValueError("encoded actor state must contain 16 finite values")
    if out[12] < 0 or out[14] < 0 or out[15] < 0:
        raise ValueError("queue position, spread, and time-to-expiry must be nonnegative")
    return out


@dataclass
class ActorCriticUpdate:
    value_before: float
    value_after: float
    advantage: float
    actor_mean: list[float]


class ContinuousActorCritic:
    """Small linear Gaussian actor + linear critic for reproducible examples.

    This is a transparent research baseline, not a trained or production DRL agent.
    Actions are: [spread placement, cancel bias, size dampener], each in [-1, 1].
    """
    def __init__(self, seed: int = 46, actor_weights: Sequence[Sequence[float]] | None = None,
                 actor_bias: Sequence[float] | None = None, log_std: Sequence[float] | None = None,
                 critic_weights: Sequence[float] | None = None, critic_bias: float = 0.0):
        rng = np.random.default_rng(seed)
        self.actor_weights = (rng.normal(0.0, 0.03, (ACTION_DIM, STATE_DIM)) if actor_weights is None
                              else _matrix(actor_weights, (ACTION_DIM, STATE_DIM), "actor_weights"))
        self.actor_bias = np.zeros(ACTION_DIM) if actor_bias is None else _vector(actor_bias, ACTION_DIM, "actor_bias")
        ls = np.full(ACTION_DIM, -1.0) if log_std is None else _vector(log_std, ACTION_DIM, "log_std")
        self.sigma = np.exp(np.clip(ls, -5.0, 1.0))
        self.critic_weights = rng.normal(0.0, 0.03, STATE_DIM) if critic_weights is None else _vector(critic_weights, STATE_DIM, "critic_weights")
        self.critic_bias = _finite_scalar(critic_bias, "critic_bias")

    @staticmethod
    def _state(state: Sequence[float]) -> np.ndarray:
        return _vector(state, STATE_DIM, "state")

    def mean(self, state: Sequence[float]) -> np.ndarray:
        s = self._state(state)
        return np.tanh(self.actor_weights @ s + self.actor_bias)

    def policy(self, state: Sequence[float], *, stochastic: bool = False, seed: int | None = None) -> dict[str, np.ndarray]:
        mu = self.mean(state)
        if stochastic:
            rng = np.random.default_rng(seed)
            action = np.clip(rng.normal(mu, self.sigma), -1.0, 1.0)
        else:
            action = mu.copy()
        return {"mean": mu, "sigma": self.sigma.copy(), "action": action}

    def value(self, state: Sequence[float]) -> float:
        return float(self.critic_weights @ self._state(state) + self.critic_bias)

    @staticmethod
    def friction_aware_advantage(reward: float, next_value: float, current_value: float,
                                 fees: float, inventory_variance: float,
                                 inventory_penalty: float = 1.0, discount: float = 0.99) -> float:
        vals = [_finite_scalar(x, name) for x, name in [(reward, "reward"), (next_value, "next_value"),
                (current_value, "current_value"), (fees, "fees"), (inventory_variance, "inventory_variance"),
                (inventory_penalty, "inventory_penalty"), (discount, "discount")]]
        reward, next_value, current_value, fees, inventory_variance, inventory_penalty, discount = vals
        if fees < 0 or inventory_variance < 0 or inventory_penalty < 0 or not 0 <= discount <= 1:
            raise ValueError("fees/variance/penalty must be nonnegative and discount in [0,1]")
        net_reward = reward - fees - inventory_penalty * inventory_variance
        return float(net_reward + discount * next_value - current_value)

    def update(self, state: Sequence[float], action: Sequence[float], advantage: float,
               learning_rate: float = 1e-3) -> ActorCriticUpdate:
        s = self._state(state)
        a = _vector(action, ACTION_DIM, "action")
        if np.any(a < -1) or np.any(a > 1):
            raise ValueError("action must be in [-1, 1]")
        adv = _finite_scalar(advantage, "advantage")
        lr = _finite_scalar(learning_rate, "learning_rate")
        if lr <= 0:
            raise ValueError("learning_rate must be positive")
        before = self.value(s)
        mu = self.mean(s)
        grad_mu = (a - mu) / np.square(self.sigma) * (1.0 - np.square(mu))
        self.actor_weights += lr * adv * np.outer(grad_mu, s)
        self.actor_bias += lr * adv * grad_mu
        self.critic_weights += lr * adv * s
        self.critic_bias += lr * adv
        return ActorCriticUpdate(before, self.value(s), adv, mu.tolist())


def cancellation_hazard(depth: float, age: float, lambda0: float = 0.2,
                        kappa_depth: float = 1.0, kappa_age: float = 0.1) -> float:
    depth, age, lambda0, kappa_depth, kappa_age = [
        _finite_scalar(x, n) for x, n in [(depth, "depth"), (age, "age"), (lambda0, "lambda0"),
        (kappa_depth, "kappa_depth"), (kappa_age, "kappa_age")]]
    if depth < 0 or age < 0 or lambda0 < 0:
        raise ValueError("depth, age, and lambda0 must be nonnegative")
    exponent = kappa_depth / max(depth, 1.0) + kappa_age * age
    if exponent > 700:
        return float("inf")
    return float(lambda0 * exp(exponent))


def cancellation_survival(duration: float, depth: float, age: float = 0.0,
                          queue_ahead: float = 0.0, lambda0: float = 0.2,
                          kappa_depth: float = 1.0, kappa_age: float = 0.1) -> float:
    """Survival exp(-integrated hazard); order age increases during duration."""
    duration, age, queue_ahead = [_finite_scalar(x, n) for x, n in
                                  [(duration, "duration"), (age, "age"), (queue_ahead, "queue_ahead")]]
    if duration < 0 or age < 0 or queue_ahead < 0:
        raise ValueError("duration, age and queue_ahead must be nonnegative")
    eff_depth = max(_finite_scalar(depth, "depth") + queue_ahead, 1.0)
    lam0 = _finite_scalar(lambda0, "lambda0")
    kd = _finite_scalar(kappa_depth, "kappa_depth")
    ka = _finite_scalar(kappa_age, "kappa_age")
    if lam0 < 0:
        raise ValueError("lambda0 must be nonnegative")
    scale = lam0 * exp(min(700.0, kd / eff_depth + ka * age))
    if abs(ka) < 1e-12:
        cumulative = scale * duration
    else:
        exponent = min(700.0, ka * duration)
        cumulative = scale * (exp(exponent) - 1.0) / ka
    if cumulative < 0:
        # Negative kappa_age still defines a nonnegative integrated hazard.
        cumulative = max(0.0, cumulative)
    return float(exp(-min(cumulative, 745.0)))


def order_revision_decision(duration: float, depth: float, age: float, queue_ahead: float,
                            min_survival: float = 0.25, **hazard_kwargs: float) -> str:
    threshold = _finite_scalar(min_survival, "min_survival")
    if not 0 <= threshold <= 1:
        raise ValueError("min_survival must lie in [0,1]")
    surv = cancellation_survival(duration, depth, age, queue_ahead, **hazard_kwargs)
    return "HOLD" if surv >= threshold else "REVISE_OR_PULL"


def rough_volterra_kernel(t: float | Sequence[float] | np.ndarray, hurst: float = HURST_DEFAULT) -> float | np.ndarray:
    """K(t)=t**(H-1/2)/Gamma(H+1/2), only defined for t>0 and H in (0,1/2)."""
    h = _finite_scalar(hurst, "hurst")
    if not 0 < h < 0.5:
        raise ValueError("hurst must lie in (0, 0.5) for this rough kernel")
    arr = np.asarray(t, dtype=float)
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0):
        raise ValueError("kernel times must be finite and strictly positive")
    out = np.power(arr, h - 0.5) / gamma(h + 0.5)
    return float(out) if out.ndim == 0 else out


def exponential_rough_lift(hurst: float = HURST_DEFAULT, n_factors: int = 12,
                           horizon: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Positive log-spaced exponential quadrature approximation to the rough kernel."""
    h = _finite_scalar(hurst, "hurst")
    horizon = _finite_scalar(horizon, "horizon")
    if not 0 < h < 0.5 or int(n_factors) < 2 or horizon <= 0:
        raise ValueError("require H in (0,.5), at least 2 factors, and positive horizon")
    n = int(n_factors)
    betas = np.geomspace(0.05 / horizon, 500.0 / horizon, n)
    dlog = log(betas[-1] / betas[0]) / (n - 1)
    q = 0.5 - h
    weights = np.full(n, dlog * sin(pi * q) / pi) * np.power(betas, q)
    # Trapezoid endpoints in log-beta space.
    weights[[0, -1]] *= 0.5
    return betas, weights


def rough_lift_variance(times: Sequence[float], innovations: Sequence[float],
                        hurst: float = HURST_DEFAULT, n_factors: int = 12,
                        horizon: float = 2.0) -> np.ndarray:
    """Return n-factor decaying states driven by finite innovations (research proxy)."""
    ts = np.asarray(times, dtype=float)
    eps = np.asarray(innovations, dtype=float)
    if ts.ndim != 1 or eps.ndim != 1 or len(ts) != len(eps) or len(ts) == 0:
        raise ValueError("times and innovations must be nonempty one-dimensional arrays of equal length")
    if not np.all(np.isfinite(ts)) or not np.all(np.isfinite(eps)) or np.any(ts < 0) or np.any(np.diff(ts) < 0):
        raise ValueError("times must be finite, nonnegative and sorted; innovations finite")
    beta, weight = exponential_rough_lift(hurst, n_factors, horizon)
    states = np.zeros(len(beta))
    last_t = float(ts[0])
    for idx in range(len(ts)):
        if idx:
            states *= np.exp(-beta * (float(ts[idx]) - last_t))
        states += weight * eps[idx]
        last_t = float(ts[idx])
    return states


def _realized_variance(prices: Sequence[float]) -> tuple[float, int]:
    p = np.asarray(prices, dtype=float)
    if p.ndim != 1 or len(p) < 3 or not np.all(np.isfinite(p)) or np.any(p <= 0):
        raise ValueError("prices must be a finite positive 1-D array with at least 3 observations")
    r = np.diff(np.log(p))
    return float(r @ r), len(r)


def two_scale_realized_variance(fast_prices: Sequence[float], slow_prices: Sequence[float]) -> dict[str, float]:
    """Specified Cycle 46 estimator: RV_slow - (N_slow/N_fast)*RV_fast."""
    rv_fast, n_fast = _realized_variance(fast_prices)
    rv_slow, n_slow = _realized_variance(slow_prices)
    estimate = rv_slow - (n_slow / n_fast) * rv_fast
    return {"tsrv": float(estimate), "rv_fast": rv_fast, "rv_slow": rv_slow,
            "n_fast": float(n_fast), "n_slow": float(n_slow), "scale": float(n_slow / n_fast),
            "variance_nonnegative": bool(estimate >= 0.0)}


def debiased_midquote_returns(bids: Sequence[float], asks: Sequence[float]) -> np.ndarray:
    bid = np.asarray(bids, dtype=float)
    ask = np.asarray(asks, dtype=float)
    if bid.ndim != 1 or ask.ndim != 1 or bid.shape != ask.shape or len(bid) < 2:
        raise ValueError("bids and asks must be equal-length 1-D arrays with at least two observations")
    if not np.all(np.isfinite(bid)) or not np.all(np.isfinite(ask)) or np.any(bid <= 0) or np.any(ask < bid):
        raise ValueError("quotes must be finite, positive and non-crossed")
    mid = 0.5 * (bid + ask)
    return np.diff(np.log(mid))


def dealer_net_gamma(open_interest: Sequence[float], option_gamma: Sequence[float], spot: float) -> float:
    oi = np.asarray(open_interest, dtype=float)
    ga = np.asarray(option_gamma, dtype=float)
    spot = _finite_scalar(spot, "spot")
    if oi.ndim != 1 or ga.ndim != 1 or oi.shape != ga.shape or not np.all(np.isfinite(oi)) or not np.all(np.isfinite(ga)):
        raise ValueError("open_interest and option_gamma must be equal-length finite vectors")
    if np.any(oi < 0) or spot <= 0:
        raise ValueError("open interest must be nonnegative and spot positive")
    return float(np.sum(oi * ga * spot))


def gamma_squeeze_hazard(gamma_dealer: float, depth: float, lambda0: float = 0.1,
                         kappa: float = 1.0, toxic_threshold: float = 1.0) -> dict[str, Any]:
    g, d, l0, kap, thr = [_finite_scalar(x, n) for x, n in
                          [(gamma_dealer, "gamma_dealer"), (depth, "depth"), (lambda0, "lambda0"),
                           (kappa, "kappa"), (toxic_threshold, "toxic_threshold")]]
    if d < 0 or l0 < 0 or thr < 0:
        raise ValueError("depth, lambda0 and toxic_threshold must be nonnegative")
    exponent = kap * abs(g) / max(d, 1.0)
    hazard = float("inf") if exponent > 700 else l0 * exp(exponent)
    toxic = hazard >= thr
    return {"lambda_squeeze": hazard, "toxic_cascade": bool(toxic),
            "quote_retreat": bool(toxic)}


@dataclass
class HedgeResult:
    weights: np.ndarray
    objective: float
    net_delta: float
    net_gamma: float
    net_vega: float
    success: bool
    message: str
    iterations: int


def solve_greek_neutral_hedge(covariance: Sequence[Sequence[float]],
                              instrument_greeks: Sequence[Sequence[float]],
                              spreads: Sequence[float], current_greeks: Sequence[float],
                              lambda_cost: float = 0.01, lambda_spread: float = 1.0,
                              delta_tol: float = 1e-4, gamma_tol: float = 1e-3,
                              vega_tol: float = 1.0, max_abs_weight: float = 1e4) -> HedgeResult:
    """SLSQP convex-risk hedge with L1 turnover/spread penalties and hard Greek bands.

    instrument_greeks has shape (n_instruments, 3), ordered delta/gamma/vega.
    """
    greeks = np.asarray(instrument_greeks, dtype=float)
    if greeks.ndim != 2 or greeks.shape[1] != 3 or greeks.shape[0] < 1 or not np.all(np.isfinite(greeks)):
        raise ValueError("instrument_greeks must have shape (n,3) with finite values")
    n = greeks.shape[0]
    cov = _matrix(covariance, (n, n), "covariance")
    if not np.allclose(cov, cov.T, atol=1e-10):
        raise ValueError("covariance must be symmetric")
    if np.min(np.linalg.eigvalsh(cov)) < -1e-9:
        raise ValueError("covariance must be positive semidefinite")
    spr = _vector(spreads, n, "spreads", nonnegative=True)
    base = _vector(current_greeks, 3, "current_greeks")
    lc, ls, dt, gt, vt, bound = [_finite_scalar(x, name) for x, name in
        [(lambda_cost, "lambda_cost"), (lambda_spread, "lambda_spread"), (delta_tol, "delta_tol"),
         (gamma_tol, "gamma_tol"), (vega_tol, "vega_tol"), (max_abs_weight, "max_abs_weight")]]
    if min(lc, ls, dt, gt, vt) < 0 or bound <= 0:
        raise ValueError("penalties/tolerances must be nonnegative and weight bound positive")
    tolerances = np.array([dt, gt, vt])
    greeks_net = lambda w: base + greeks.T @ w
    objective = lambda w: 0.5 * float(w @ cov @ w) + lc * float(np.sum(np.abs(w))) + ls * float(np.sum(np.abs(w) * spr))
    # Least-squares neutral starting point improves feasibility when the matrix has rank.
    x0 = np.linalg.lstsq(greeks.T, -base, rcond=None)[0]
    x0 = np.clip(x0, -bound, bound)
    constraints = [{"type": "ineq", "fun": lambda w, i=i: tolerances[i] - abs(greeks_net(w)[i])} for i in range(3)]
    result = minimize(objective, x0, method="SLSQP", bounds=[(-bound, bound)] * n,
                      constraints=constraints, options={"maxiter": 1000, "ftol": 1e-12, "disp": False})
    net = greeks_net(result.x)
    feasible = bool(np.all(np.abs(net) <= tolerances + np.array([2e-6, 2e-5, 2e-4])))
    success = bool(result.success and feasible)
    return HedgeResult(np.asarray(result.x), float(objective(result.x)), float(net[0]), float(net[1]),
                       float(net[2]), success, str(result.message), int(getattr(result, "nit", 0)))


@dataclass(frozen=True)
class IndianFeeSchedule:
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    exchange_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    brokerage_per_leg: float = 20.0

    def calculate(self, buy_turnover: float, sell_turnover: float, legs: int) -> dict[str, float]:
        buy, sell = _finite_scalar(buy_turnover, "buy_turnover"), _finite_scalar(sell_turnover, "sell_turnover")
        if buy < 0 or sell < 0 or int(legs) < 0:
            raise ValueError("turnovers and legs must be nonnegative")
        brokerage = self.brokerage_per_leg * int(legs)
        exchange = (buy + sell) / RUPEES_PER_CRORE * self.exchange_per_crore
        sebi = (buy + sell) / RUPEES_PER_CRORE * self.sebi_per_crore
        stt = sell * self.stt_sell_rate
        stamp = buy * self.stamp_buy_rate
        gst = (brokerage + exchange + sebi) * self.gst_rate
        total = stt + stamp + brokerage + exchange + sebi + gst
        return {"stt": stt, "stamp_duty": stamp, "brokerage": brokerage,
                "exchange_fee": exchange, "sebi_fee": sebi, "gst": gst, "total_fees": total}


def net_alpha_gate(expected_gross_alpha: float, total_statutory_fees: float) -> dict[str, float | bool]:
    gross, fees = _finite_scalar(expected_gross_alpha, "expected_gross_alpha"), _finite_scalar(total_statutory_fees, "total_statutory_fees")
    if fees < 0:
        raise ValueError("fees must be nonnegative")
    net = gross - fees
    return {"expected_gross_alpha": gross, "total_statutory_fees": fees,
            "expected_net_alpha": net, "approved": bool(net > 0.0)}


@dataclass
class AntiTiltController:
    tau_base: float = 30.0
    theta_v: float = 1.0
    sigma_base: float = 0.2
    min_spacing_seconds: float = 30.0
    max_size_acceleration: float = 1.25
    max_consecutive_losses: int = 3
    consecutive_losses: int = 0
    last_trade_timestamp: float | None = None
    last_trade_size: float | None = None

    def cooldown(self, sigma_rough: float) -> float:
        tau, theta, base = [_finite_scalar(x, n) for x, n in
                            [(self.tau_base, "tau_base"), (self.theta_v, "theta_v"), (self.sigma_base, "sigma_base")]]
        sigma = _finite_scalar(sigma_rough, "sigma_rough")
        if tau < 0 or theta < 0 or base <= 0 or sigma < 0:
            raise ValueError("cooldown parameters must be nonnegative and sigma_base positive")
        return tau * (1.0 + theta * sigma / base)

    def record_trade(self, timestamp: float, size: float, pnl: float) -> None:
        t, s, p = [_finite_scalar(x, n) for x, n in [(timestamp, "timestamp"), (size, "size"), (pnl, "pnl")]]
        if t < 0 or s < 0:
            raise ValueError("timestamp and size must be nonnegative")
        if self.last_trade_timestamp is not None and t < self.last_trade_timestamp:
            raise ValueError("trade timestamps must be monotonic")
        self.consecutive_losses = self.consecutive_losses + 1 if p < 0 else 0
        self.last_trade_timestamp, self.last_trade_size = t, s

    def lockout_reasons(self, timestamp: float, proposed_size: float) -> list[str]:
        t, size = _finite_scalar(timestamp, "timestamp"), _finite_scalar(proposed_size, "proposed_size")
        if size < 0 or t < 0:
            raise ValueError("timestamp and proposed size must be nonnegative")
        reasons: list[str] = []
        if self.consecutive_losses >= self.max_consecutive_losses:
            reasons.append("CONSECUTIVE_LOSSES")
        if self.last_trade_timestamp is not None and t - self.last_trade_timestamp < self.min_spacing_seconds:
            reasons.append("TRADE_SPACING")
        if self.last_trade_size is not None and self.last_trade_size > 0 and size / self.last_trade_size > self.max_size_acceleration:
            reasons.append("SIZE_ACCELERATION")
        return reasons


@dataclass
class SquadDecision:
    approved: bool
    manager_veto: bool
    votes: dict[str, bool]
    reasons: list[str]


class TradingSquad:
    """Research consensus abstraction. Manager veto has absolute precedence."""
    roles = {"Manager Abhi": "operator liaison, capital approval, binding live veto",
             "Alex": "L3 queue and microstructure risk", "Emily": "rough volatility and macro",
             "Max": "statutory net alpha and Bayesian-Kelly sizing"}

    def review(self, *, manager_veto: bool = False, queue_risk_ok: bool = True,
               volatility_ok: bool = True, net_alpha_positive: bool = True,
               sizing_ok: bool = True, lockout_reasons: Sequence[str] = ()) -> SquadDecision:
        votes = {"Manager Abhi": not manager_veto, "Alex": bool(queue_risk_ok),
                 "Emily": bool(volatility_ok), "Max": bool(net_alpha_positive and sizing_ok)}
        reasons = list(lockout_reasons)
        if manager_veto:
            reasons.append("MANAGER_VETO")
        if not queue_risk_ok:
            reasons.append("QUEUE_RISK_REJECT")
        if not volatility_ok:
            reasons.append("VOLATILITY_REJECT")
        if not net_alpha_positive:
            reasons.append("NET_ALPHA_NONPOSITIVE")
        if not sizing_ok:
            reasons.append("SIZING_REJECT")
        if lockout_reasons:
            reasons.append("ANTI_TILT_LOCKOUT")
        approved = all(votes.values()) and not lockout_reasons
        return SquadDecision(bool(approved), bool(manager_veto), votes, reasons)


class PaperLedger:
    """Small local ledger; accepts paper P&L only and does not connect to a broker."""
    def __init__(self, initial_capital: float = INITIAL_CAPITAL_INR, epoch: str = PAPER_LEDGER_EPOCH):
        self.initial_capital = _finite_scalar(initial_capital, "initial_capital")
        if self.initial_capital <= 0 or epoch != PAPER_LEDGER_EPOCH:
            raise ValueError("positive initial capital and fixed epoch_10k are required")
        self.epoch = epoch
        self.capital = self.initial_capital
        self.events: list[dict[str, float]] = []

    def record_paper_pnl(self, gross_pnl: float, fees: float) -> float:
        gross, fee = _finite_scalar(gross_pnl, "gross_pnl"), _finite_scalar(fees, "fees")
        if fee < 0:
            raise ValueError("fees must be nonnegative")
        net = gross - fee
        self.capital += net
        self.events.append({"gross_pnl": gross, "fees": fee, "net_pnl": net, "capital": self.capital})
        return net


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Forbidden execution boundary: intentionally raises for every call."""
    raise PermissionError("Cycle 46 is paper-simulation only; live order dispatch is permanently disabled")


def research_preflight(*, expected_gross_alpha: float, buy_turnover: float, sell_turnover: float,
                       legs: int, manager_veto: bool = False, lockout_reasons: Sequence[str] = ()) -> dict[str, Any]:
    """Run statutory net-alpha gate and squad checks for a paper-only proposal."""
    fees = IndianFeeSchedule().calculate(buy_turnover, sell_turnover, legs)
    alpha = net_alpha_gate(expected_gross_alpha, fees["total_fees"])
    squad = TradingSquad().review(manager_veto=manager_veto,
                                  net_alpha_positive=bool(alpha["approved"]),
                                  lockout_reasons=lockout_reasons)
    return {"fees": fees, "alpha": alpha, "squad": squad, "paper_only": True,
            "live_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
            "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED}

__all__ = [
    "ASSETS", "STATE_DIM", "ACTION_DIM", "HURST_DEFAULT", "LAMBDA_STABILITY_LIMIT",
    "LIVE_ORDER_DISPATCH_ENABLED", "REAL_BROKER_FILLS_LOCKED", "PAPER_LEDGER_EPOCH", "INITIAL_CAPITAL_INR",
    "MultiHorizonHawkes", "encode_actor_state", "ContinuousActorCritic", "ActorCriticUpdate",
    "cancellation_hazard", "cancellation_survival", "order_revision_decision", "rough_volterra_kernel",
    "exponential_rough_lift", "rough_lift_variance", "two_scale_realized_variance", "debiased_midquote_returns",
    "dealer_net_gamma", "gamma_squeeze_hazard", "HedgeResult", "solve_greek_neutral_hedge", "IndianFeeSchedule",
    "net_alpha_gate", "AntiTiltController", "TradingSquad", "SquadDecision", "PaperLedger",
    "dispatch_live_order", "research_preflight"
]
