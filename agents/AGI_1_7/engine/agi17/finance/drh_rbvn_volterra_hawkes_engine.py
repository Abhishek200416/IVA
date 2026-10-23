"""Cycle 54 DRH-RBVN offline research and paper-simulation engine.

Implements a discretized rough-Bergomi-style Volterra jump SDE, a non-negative
12-factor exponential kernel lift, multi-asset Hawkes events, MLOFI, CVaR-based
hedging metrics, a small trainable continuous actor-critic, inventory no-trade
bands, statutory fee accounting and fail-closed governance. No broker adapters,
network calls, credentials, or live order path are provided.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, gamma as gamma_fn, log, sqrt
from typing import Any, Sequence, Mapping

import numpy as np

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0
ROUGH_HURST = 0.07
VOLTERRA_FACTORS = 12
STATE_DIMENSION = 16
MAX_KELLY_FRACTION = 0.10
INR_PER_CRORE = 10_000_000.0


def _arr(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    a = np.asarray(value, dtype=float)
    if ndim is not None and a.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must contain only finite values")
    return a


def _finite(value: float, name: str) -> float:
    x = float(value)
    if not np.isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _positive(value: float, name: str, allow_zero: bool = False) -> float:
    x = _finite(value, name)
    if x < 0 if allow_zero else x <= 0:
        q = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be {q}")
    return x


def _probability(value: float, name: str) -> float:
    x = _finite(value, name)
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"{name} must lie in [0, 1]")
    return x


def rough_volterra_kernel(t: float | Sequence[float], hurst: float = ROUGH_HURST) -> float | np.ndarray:
    """K_H(t)=t^(H-1/2)/Gamma(H+1/2), evaluated only for t>0."""
    H = _finite(hurst, "hurst")
    if not 0.0 < H < 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    scalar = np.ndim(t) == 0
    x = _arr(np.atleast_1d(t), "t", 1)
    if np.any(x <= 0):
        raise ValueError("rough Volterra kernel is singular for t <= 0")
    out = x ** (H - 0.5) / gamma_fn(H + 0.5)
    return float(out[0]) if scalar else out


@dataclass(frozen=True)
class ExponentialKernelLift:
    """Non-negative exponential approximation K(t) ~= sum w_k exp(-gamma_k t)."""
    hurst: float
    rates: np.ndarray
    weights: np.ndarray

    def __post_init__(self) -> None:
        H = _finite(self.hurst, "hurst")
        r = _arr(self.rates, "rates", 1)
        w = _arr(self.weights, "weights", 1)
        if not 0 < H < 0.5:
            raise ValueError("hurst must lie in (0, 0.5)")
        if r.size != 12 or w.size != 12:
            raise ValueError("Cycle 54 lift must contain exactly 12 factors")
        if np.any(r <= 0) or np.any(w < 0):
            raise ValueError("rates must be positive and weights non-negative")
        object.__setattr__(self, "rates", r.copy())
        object.__setattr__(self, "weights", w.copy())

    def evaluate(self, t: float | Sequence[float]) -> float | np.ndarray:
        scalar = np.ndim(t) == 0
        x = _arr(np.atleast_1d(t), "t", 1)
        if np.any(x < 0):
            raise ValueError("t must be non-negative")
        out = np.exp(-np.outer(x, self.rates)) @ self.weights
        return float(out[0]) if scalar else out


def build_volterra_lift(hurst: float = ROUGH_HURST, factors: int = VOLTERRA_FACTORS,
                        tau_min: float = 1e-3, tau_max: float = 100.0) -> ExponentialKernelLift:
    """Construct a deterministic positive least-squares 12-factor kernel lift.

    This is a numerical approximation, not an exact representation of the singular kernel.
    """
    H = _finite(hurst, "hurst")
    if not 0 < H < 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    if factors != 12:
        raise ValueError("Cycle 54 requires factors=12")
    lo, hi = _positive(tau_min, "tau_min"), _positive(tau_max, "tau_max")
    if lo >= hi:
        raise ValueError("tau_min must be less than tau_max")
    rates = np.geomspace(1.0 / hi, 1.0 / lo, factors)
    grid = np.geomspace(lo, hi, 480)
    design = np.exp(-np.outer(grid, rates))
    target = np.asarray(rough_volterra_kernel(grid, H))
    weights = np.maximum(np.linalg.lstsq(design, target, rcond=1e-10)[0], 0.0)
    gram = design.T @ design
    lipschitz = float(np.linalg.norm(gram, ord=2))
    if lipschitz > 0:
        step = 1.0 / lipschitz
        for _ in range(300):
            weights = np.maximum(weights - step * (design.T @ (design @ weights - target)), 0.0)
    return ExponentialKernelLift(H, rates, weights)


@dataclass(frozen=True)
class HawkesNetwork:
    """Four-asset exponential Hawkes network with a branching-ratio audit.

    `alpha[i,j]` is the event excitation into target i from source j;
    `beta[i,j]` is its exponential decay rate. Stability proxy is rho(alpha/beta).
    """
    baseline: np.ndarray
    alpha: np.ndarray
    beta: np.ndarray
    max_spectral_radius: float = 0.88

    def __post_init__(self) -> None:
        mu = _arr(self.baseline, "baseline", 1)
        a = _arr(self.alpha, "alpha", 2)
        b = _arr(self.beta, "beta", 2)
        if mu.shape != (4,) or a.shape != (4, 4) or b.shape != (4, 4):
            raise ValueError("baseline must be (4,), alpha and beta must be (4,4)")
        if np.any(mu < 0) or np.any(a < 0) or np.any(b <= 0):
            raise ValueError("baseline/alpha must be non-negative and beta strictly positive")
        lim = _positive(self.max_spectral_radius, "max_spectral_radius")
        radius = float(max(abs(np.linalg.eigvals(a / b))))
        if not radius < lim:
            raise ValueError(f"Hawkes branching spectral radius {radius:.6g} must be < {lim}")
        object.__setattr__(self, "baseline", mu.copy())
        object.__setattr__(self, "alpha", a.copy())
        object.__setattr__(self, "beta", b.copy())

    @property
    def spectral_radius(self) -> float:
        return float(max(abs(np.linalg.eigvals(self.alpha / self.beta))))

    def simulate(self, n_steps: int, dt: float, seed: int = 0) -> dict[str, np.ndarray]:
        if not isinstance(n_steps, int) or n_steps < 1:
            raise ValueError("n_steps must be a positive integer")
        dt = _positive(dt, "dt")
        rng = np.random.default_rng(seed)
        state = np.zeros((4, 4), dtype=float)
        intensities = np.zeros((n_steps, 4), dtype=float)
        counts = np.zeros((n_steps, 4), dtype=int)
        decay = np.exp(-self.beta * dt)
        for t in range(n_steps):
            lam = self.baseline + state.sum(axis=1)
            if np.any(~np.isfinite(lam)) or np.any(lam < 0):
                raise FloatingPointError("invalid Hawkes intensity")
            intensities[t] = lam
            events = rng.poisson(np.minimum(lam * dt, 1e7))
            counts[t] = events
            state = state * decay + self.alpha * events[np.newaxis, :]
        return {"intensity": intensities, "counts": counts, "spectral_radius": np.asarray(self.spectral_radius)}


def mlofi_top5(delta_bid_volume: Sequence[float], delta_ask_volume: Sequence[float],
               delta_bid_price: Sequence[float], delta_ask_price: Sequence[float],
               weights: Sequence[float] | None = None) -> float:
    """Top-five multi-level OFI using the exact directional indicators in the spec."""
    dbv = _arr(delta_bid_volume, "delta_bid_volume", 1)
    dav = _arr(delta_ask_volume, "delta_ask_volume", 1)
    dbp = _arr(delta_bid_price, "delta_bid_price", 1)
    dap = _arr(delta_ask_price, "delta_ask_price", 1)
    if any(a.shape != (5,) for a in (dbv, dav, dbp, dap)):
        raise ValueError("all MLOFI input vectors must have exactly five levels")
    w = np.asarray([1.0, 0.8, 0.6, 0.4, 0.2] if weights is None else _arr(weights, "weights", 1), dtype=float)
    if w.shape != (5,) or np.any(w < 0):
        raise ValueError("weights must be five finite non-negative values")
    bid_component = dbv * (dbp >= 0.0)
    ask_component = dav * (dap <= 0.0)
    return float(np.dot(w, bid_component - ask_component))


def cvar_alpha(losses: Sequence[float], alpha: float = 0.95) -> float:
    """Empirical right-tail CVaR: q_alpha + E[(L-q_alpha)+]/(1-alpha)."""
    x = _arr(losses, "losses", 1)
    if x.size == 0:
        raise ValueError("losses must not be empty")
    a = _finite(alpha, "alpha")
    if not 0.0 < a < 1.0:
        raise ValueError("alpha must lie strictly between 0 and 1")
    q = float(np.quantile(x, a, method="linear"))
    return float(q + np.maximum(x - q, 0.0).mean() / (1.0 - a))


def hedging_error_scenarios(terminal_pnl: float | Sequence[float], price_changes: Sequence[Sequence[float]],
                            delta_hedges: Sequence[float], transaction_costs: Sequence[float] | None = None) -> np.ndarray:
    """Compute pathwise terminal hedging error Pi_T - sum(delta_k * dS_k) + costs."""
    dS = _arr(price_changes, "price_changes", 2)
    delta = _arr(delta_hedges, "delta_hedges", 1)
    if dS.shape[1] != delta.size:
        raise ValueError("price_changes time dimension must equal delta_hedges length")
    pnl = _arr(np.atleast_1d(terminal_pnl), "terminal_pnl", 1)
    if pnl.size not in (1, dS.shape[0]):
        raise ValueError("terminal_pnl must be scalar or have one value per scenario")
    cost = np.zeros(delta.size) if transaction_costs is None else _arr(transaction_costs, "transaction_costs", 1)
    if cost.shape != delta.shape or np.any(cost < 0):
        raise ValueError("transaction_costs must be non-negative and match hedge steps")
    terminal = np.repeat(pnl, dS.shape[0]) if pnl.size == 1 else pnl
    return terminal - dS @ delta + float(cost.sum())


def calculate_statutory_fees(buy_turnover_inr: float, sell_turnover_inr: float, legs: int,
                             brokerage_per_leg: float = 20.0) -> dict[str, float]:
    buy = _positive(buy_turnover_inr, "buy_turnover_inr", allow_zero=True)
    sell = _positive(sell_turnover_inr, "sell_turnover_inr", allow_zero=True)
    if not isinstance(legs, int) or legs < 0:
        raise ValueError("legs must be a non-negative integer")
    brokerage_rate = _positive(brokerage_per_leg, "brokerage_per_leg", allow_zero=True)
    turnover = buy + sell
    stt = sell * 0.0015
    stamp = buy * 0.00003
    exchange = turnover * 3553.0 / INR_PER_CRORE
    sebi = turnover * 10.0 / INR_PER_CRORE
    brokerage = legs * brokerage_rate
    gst = 0.18 * (exchange + sebi + brokerage)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return {"buy_turnover_inr": buy, "sell_turnover_inr": sell, "total_turnover_inr": turnover,
            "stt_sell": stt, "stamp_buy": stamp, "exchange": exchange, "sebi": sebi,
            "brokerage": brokerage, "gst": gst, "total_fees": total}


def pretrade_net_alpha_gate(expected_gross_alpha: float, total_statutory_fees: float) -> dict[str, float | bool]:
    gross = _finite(expected_gross_alpha, "expected_gross_alpha")
    fees = _positive(total_statutory_fees, "total_statutory_fees", allow_zero=True)
    net = gross - fees
    return {"expected_gross_alpha": gross, "total_statutory_fees": fees,
            "expected_net_alpha": net, "approved": bool(net > 0.0)}


def beta_posterior_fractional_kelly(wins: int, losses: int, odds: float,
                                    prior_alpha: float = 1.0, prior_beta: float = 1.0,
                                    fractional_scale: float = 0.25,
                                    max_fraction: float = MAX_KELLY_FRACTION) -> dict[str, float]:
    if not isinstance(wins, int) or not isinstance(losses, int) or wins < 0 or losses < 0:
        raise ValueError("wins and losses must be non-negative integers")
    b = _positive(odds, "odds")
    a0, b0 = _positive(prior_alpha, "prior_alpha"), _positive(prior_beta, "prior_beta")
    scale = _positive(fractional_scale, "fractional_scale", allow_zero=True)
    cap = _finite(max_fraction, "max_fraction")
    if not 0 <= cap <= MAX_KELLY_FRACTION:
        raise ValueError("max_fraction must lie in [0, 0.10]")
    p = (a0 + wins) / (a0 + b0 + wins + losses)
    raw = ((p * (b + 1.0) - 1.0) / b) * scale
    fraction = float(np.clip(raw, 0.0, cap))
    return {"posterior_win_probability": p, "raw_fraction": float(raw), "fraction": fraction,
            "capital_inr": INITIAL_CAPITAL_INR * fraction}


@dataclass(frozen=True)
class NoTradeBand:
    target_inventory: float
    lower: float
    upper: float
    base_half_width: float


def friction_aware_no_trade_band(target_inventory: float, transaction_cost: float, volatility: float,
                                 risk_aversion: float, buy_spread_penalty: float = 0.0,
                                 sell_spread_penalty: float = 0.0, fee_drag: float = 0.0) -> NoTradeBand:
    q = _finite(target_inventory, "target_inventory")
    c = _positive(transaction_cost, "transaction_cost", allow_zero=True)
    sigma = _positive(volatility, "volatility", allow_zero=True)
    gamma_risk = _positive(risk_aversion, "risk_aversion")
    bp = _positive(buy_spread_penalty, "buy_spread_penalty", allow_zero=True)
    sp = _positive(sell_spread_penalty, "sell_spread_penalty", allow_zero=True)
    fd = _positive(fee_drag, "fee_drag", allow_zero=True)
    half = ((3.0 * c * sigma * sigma) / (4.0 * gamma_risk)) ** (1.0 / 3.0) if c * sigma * sigma > 0 else 0.0
    return NoTradeBand(q, q - (half + bp + fd), q + (half + sp + fd), half)


def inventory_action(inventory: float, band: NoTradeBand) -> str:
    q = _finite(inventory, "inventory")
    if q < band.lower:
        return "BUY_TOWARD_TARGET"
    if q > band.upper:
        return "SELL_TOWARD_TARGET"
    return "HOLD_NO_TRADE"


def friction_aware_advantage(reward: float, value: float, next_value: float,
                             statutory_fees: float, inventory_variance: float,
                             risk_aversion: float = 1.0, discount: float = 0.99) -> float:
    r, v, nv = _finite(reward, "reward"), _finite(value, "value"), _finite(next_value, "next_value")
    fees = _positive(statutory_fees, "statutory_fees", allow_zero=True)
    var = _positive(inventory_variance, "inventory_variance", allow_zero=True)
    risk = _positive(risk_aversion, "risk_aversion", allow_zero=True)
    g = _probability(discount, "discount")
    return float(r - fees - risk * var + g * nv - v)


class ContinuousActorCritic:
    """Trainable two-hidden-layer Gaussian actor and scalar value critic.

    State is 16D. The hedging action is tanh(z) in [-1,1]. Training methods use
    a score-function actor update and squared-error TD value update. This small
    NumPy baseline is intentionally transparent, not a production DRL framework.
    """
    def __init__(self, seed: int = 0, state_dim: int = STATE_DIMENSION,
                 hidden1: int = 32, hidden2: int = 16):
        if state_dim != STATE_DIMENSION or hidden1 < 2 or hidden2 < 2:
            raise ValueError("Cycle 54 requires state_dim=16 and hidden widths >= 2")
        rng = np.random.default_rng(seed)
        scale = 0.1
        def init(a: int, b: int) -> np.ndarray:
            return rng.normal(0, scale / sqrt(a), (a, b))
        self.W1, self.b1 = init(state_dim, hidden1), np.zeros(hidden1)
        self.W2, self.b2 = init(hidden1, hidden2), np.zeros(hidden2)
        self.Wmu, self.bmu = init(hidden2, 1), np.zeros(1)
        self.Wls, self.bls = init(hidden2, 1), np.full(1, -1.0)
        self.Wv1, self.bv1 = init(state_dim, hidden1), np.zeros(hidden1)
        self.Wv2, self.bv2 = init(hidden1, hidden2), np.zeros(hidden2)
        self.Wv, self.bv = init(hidden2, 1), np.zeros(1)

    @staticmethod
    def _state(state: Sequence[float]) -> np.ndarray:
        s = _arr(state, "state", 1)
        if s.shape != (STATE_DIMENSION,):
            raise ValueError("state must have exactly 16 dimensions")
        return s

    def _actor_forward(self, state: np.ndarray):
        h1 = np.tanh(state @ self.W1 + self.b1)
        h2 = np.tanh(h1 @ self.W2 + self.b2)
        mu = float((h2 @ self.Wmu + self.bmu)[0])
        log_std_raw = float((h2 @ self.Wls + self.bls)[0])
        log_std = float(np.clip(log_std_raw, -5.0, 1.0))
        return h1, h2, mu, log_std, log_std_raw

    def policy_parameters(self, state: Sequence[float]) -> tuple[float, float]:
        _, _, mu, log_std, _ = self._actor_forward(self._state(state))
        return mu, float(np.exp(log_std))

    def act(self, state: Sequence[float], seed: int = 0, deterministic: bool = False) -> float:
        s = self._state(state)
        _, _, mu, log_std, _ = self._actor_forward(s)
        z = mu if deterministic else mu + np.exp(log_std) * np.random.default_rng(seed).normal()
        return float(np.tanh(z))

    def value(self, state: Sequence[float]) -> float:
        s = self._state(state)
        h1 = np.tanh(s @ self.Wv1 + self.bv1)
        h2 = np.tanh(h1 @ self.Wv2 + self.bv2)
        return float((h2 @ self.Wv + self.bv)[0])

    def update(self, state: Sequence[float], action: float, advantage: float,
               target_value: float, learning_rate: float = 1e-3) -> dict[str, float]:
        s = self._state(state)
        a = _finite(action, "action")
        if not -1.0 < a < 1.0:
            raise ValueError("action must lie strictly inside (-1,1) for inverse tanh")
        adv, target = _finite(advantage, "advantage"), _finite(target_value, "target_value")
        lr = _positive(learning_rate, "learning_rate")
        h1, h2, mu, log_std, log_std_raw = self._actor_forward(s)
        std = np.exp(log_std); z = float(np.arctanh(a)); diff = z - mu
        grad_mu = adv * diff / (std * std)
        grad_ls = adv * ((diff * diff / (std * std)) - 1.0) if -5.0 < log_std_raw < 1.0 else 0.0
        old_W2 = self.W2.copy()
        old_Wmu = self.Wmu.copy(); old_Wls = self.Wls.copy()
        self.Wmu += lr * h2[:, None] * grad_mu; self.bmu += lr * grad_mu
        self.Wls += lr * h2[:, None] * grad_ls; self.bls += lr * grad_ls
        grad_h2 = old_Wmu[:, 0] * grad_mu + old_Wls[:, 0] * grad_ls
        grad_z2 = grad_h2 * (1.0 - h2 * h2)
        self.W2 += lr * np.outer(h1, grad_z2); self.b2 += lr * grad_z2
        grad_h1 = old_W2 @ grad_z2
        grad_z1 = grad_h1 * (1.0 - h1 * h1)
        self.W1 += lr * np.outer(s, grad_z1); self.b1 += lr * grad_z1
        # TD critic update, minimizing 0.5*(V-target)^2.
        vh1 = np.tanh(s @ self.Wv1 + self.bv1)
        vh2 = np.tanh(vh1 @ self.Wv2 + self.bv2)
        vpred = float((vh2 @ self.Wv + self.bv)[0])
        err = target - vpred
        old_Wv = self.Wv.copy()
        old_Wv2 = self.Wv2.copy()
        grad_vout = err
        self.Wv += lr * vh2[:, None] * grad_vout; self.bv += lr * grad_vout
        gh2 = old_Wv[:, 0] * grad_vout
        gz2 = gh2 * (1 - vh2 * vh2)
        self.Wv2 += lr * np.outer(vh1, gz2); self.bv2 += lr * gz2
        gh1 = old_Wv2 @ gz2
        gz1 = gh1 * (1 - vh1 * vh1)
        self.Wv1 += lr * np.outer(s, gz1); self.bv1 += lr * gz1
        return {"policy_mean_before_update": mu, "policy_std_before_update": float(std),
                "critic_value_before_update": vpred, "td_error": float(err)}


@dataclass(frozen=True)
class RoughBergomiSimulation:
    times: np.ndarray
    spot: np.ndarray
    variance: np.ndarray
    log_variance: np.ndarray
    returns: np.ndarray
    variance_brownian: np.ndarray
    price_brownian: np.ndarray
    jump_counts: np.ndarray
    jump_log_sizes: np.ndarray
    lift_rates: np.ndarray
    lift_weights: np.ndarray


def simulate_rough_bergomi_jump_sde(spot0: float, dt: float, n_steps: int,
                                    forward_variance: float | Sequence[float],
                                    vol_of_vol: float = 0.8, hurst: float = ROUGH_HURST,
                                    rho: float = -0.6, rate: float = 0.0, dividend: float = 0.0,
                                    jump_intensity: float = 0.1, mu_jump: float = -0.02,
                                    sigma_jump: float = 0.08, variance_jump_intensity: float = 0.0,
                                    variance_jump_mean: float = 0.0, variance_jump_std: float = 0.1,
                                    hawkes_intensity_path: Sequence[float] | None = None,
                                    seed: int = 0) -> RoughBergomiSimulation:
    """Discretized rough-Bergomi-style log-variance and compound-Poisson price SDE.

    Correlated drivers satisfy Corr(dW^S,dW^V)=rho. The 12-factor lift is
    returned for feature inspection; direct midpoint-lag convolution is used to
    reduce kernel approximation bias on short grids.
    """
    S0, dtime = _positive(spot0, "spot0"), _positive(dt, "dt")
    if not isinstance(n_steps, int) or n_steps < 1:
        raise ValueError("n_steps must be a positive integer")
    eta = _positive(vol_of_vol, "vol_of_vol", allow_zero=True)
    H = _finite(hurst, "hurst")
    if not 0 < H < 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    corr = _finite(rho, "rho")
    if not -0.9 <= corr <= -0.3:
        raise ValueError("rho leverage parameter must lie in [-0.9, -0.3]")
    r, q = _finite(rate, "rate"), _finite(dividend, "dividend")
    lam = _positive(jump_intensity, "jump_intensity", allow_zero=True)
    mj, sj = _finite(mu_jump, "mu_jump"), _positive(sigma_jump, "sigma_jump", allow_zero=True)
    vlam = _positive(variance_jump_intensity, "variance_jump_intensity", allow_zero=True)
    vm, vs = _finite(variance_jump_mean, "variance_jump_mean"), _positive(variance_jump_std, "variance_jump_std", allow_zero=True)
    xi_in = _arr(np.atleast_1d(forward_variance), "forward_variance", 1)
    if np.any(xi_in <= 0) or xi_in.size not in (1, n_steps, n_steps + 1):
        raise ValueError("forward_variance must be positive and scalar or have n_steps/(n_steps+1) values")
    xi = np.full(n_steps, xi_in[0]) if xi_in.size == 1 else (xi_in[1:] if xi_in.size == n_steps + 1 else xi_in.copy())
    if hawkes_intensity_path is None:
        intensity = np.full(n_steps, lam)
    else:
        intensity = _arr(hawkes_intensity_path, "hawkes_intensity_path", 1)
        if intensity.shape != (n_steps,) or np.any(intensity < 0):
            raise ValueError("hawkes_intensity_path must be non-negative and length n_steps")
    lift = build_volterra_lift(H, 12)
    rng = np.random.default_rng(seed)
    dWv = rng.normal(0.0, sqrt(dtime), n_steps)
    indep = rng.normal(0.0, sqrt(dtime), n_steps)
    dWs = corr * dWv + sqrt(1.0 - corr * corr) * indep
    jump_counts = rng.poisson(np.minimum(intensity * dtime, 1e6))
    jump_sizes = np.zeros(n_steps)
    variance_jumps = np.zeros(n_steps)
    for i, n in enumerate(jump_counts):
        if n:
            jump_sizes[i] = float(rng.normal(mj, sj, int(n)).sum())
    vcounts = rng.poisson(np.full(n_steps, min(vlam * dtime, 1e6), dtype=float))
    for i, n in enumerate(vcounts):
        if n:
            variance_jumps[i] = float(rng.normal(vm, vs, int(n)).sum())
    logv = np.empty(n_steps); var = np.empty(n_steps); spot = np.empty(n_steps + 1)
    rets = np.empty(n_steps); spot[0] = S0
    for i in range(n_steps):
        lags = (np.arange(i + 1, 0, -1, dtype=float) - 0.5) * dtime
        kernel = np.asarray(rough_volterra_kernel(lags, H))
        driver = float(np.dot(kernel, dWv[:i + 1]))
        t = (i + 1) * dtime
        baseline = log(max(float(xi[i]), 1e-12))
        logv[i] = baseline + eta * driver - 0.5 * eta * eta * (t ** (2.0 * H)) + variance_jumps[i]
        # Explicit bounds prevent overflow under extreme Gaussian shocks while preserving positivity.
        var[i] = float(np.exp(np.clip(logv[i], -25.0, 10.0)))
        rets[i] = (r - q - 0.5 * var[i]) * dtime + sqrt(var[i]) * dWs[i] + jump_sizes[i]
        spot[i + 1] = spot[i] * np.exp(np.clip(rets[i], -30.0, 30.0))
        if not np.isfinite(spot[i + 1]) or spot[i + 1] <= 0:
            raise FloatingPointError("simulated spot left positive finite range")
    return RoughBergomiSimulation(times=np.arange(n_steps + 1) * dtime, spot=spot, variance=var,
        log_variance=logv, returns=rets, variance_brownian=dWv, price_brownian=dWs,
        jump_counts=jump_counts, jump_log_sizes=jump_sizes,
        lift_rates=lift.rates.copy(), lift_weights=lift.weights.copy())


def quadratic_proportional_transaction_cost(delta_change: float, spot: float, quantity: float = 1.0,
                                            proportional_rate: float = 0.0005,
                                            quadratic_rate: float = 0.0001,
                                            statutory_fees: float = 0.0) -> float:
    dd = _finite(delta_change, "delta_change")
    S = _positive(spot, "spot")
    qty = _positive(quantity, "quantity", allow_zero=True)
    pr = _positive(proportional_rate, "proportional_rate", allow_zero=True)
    qr = _positive(quadratic_rate, "quadratic_rate", allow_zero=True)
    fees = _positive(statutory_fees, "statutory_fees", allow_zero=True)
    turnover = abs(dd) * S * qty
    return float(pr * turnover + qr * turnover * turnover + fees)


@dataclass(frozen=True)
class SquadDecision:
    approved: bool
    manager: str
    agents: tuple[str, ...]
    reasons: tuple[str, ...]
    paper_only: bool = True


def squad_consensus(manager_abhi_approves: bool, alex_queue_risk_ok: bool,
                    emily_volatility_ok: bool, max_net_alpha_ok: bool,
                    manager_veto: bool = False) -> SquadDecision:
    agents = ("Manager Abhi", "Alex", "Emily", "Max")
    checks = (manager_abhi_approves, alex_queue_risk_ok, emily_volatility_ok, max_net_alpha_ok)
    labels = ("Abhi capital approval absent", "Alex queue/microstructure risk veto", 
              "Emily rough-volatility/regime veto", "Max statutory net-alpha/Kelly veto")
    reasons = [label for ok, label in zip(checks, labels) if not ok]
    if manager_veto:
        reasons.insert(0, "Manager Abhi binding veto active")
    approved = bool(all(checks) and not manager_veto)
    return SquadDecision(approved, "Manager Abhi", agents, tuple(reasons), True)


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Unconditionally reject live execution; this package is paper-only."""
    raise PermissionError("Live order dispatch is disabled in Cycle 54 paper-research mode")


def safety_invariants() -> dict[str, bool | str | float]:
    return {"LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
            "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED,
            "PAPER_LEDGER_EPOCH": PAPER_LEDGER_EPOCH,
            "INITIAL_CAPITAL_INR": INITIAL_CAPITAL_INR,
            "live_dispatch_raises_permission_error": True}


def cycle54_summary(seed: int = 54) -> dict[str, Any]:
    """Stable demonstration summary used by the bundled reproducibility example."""
    lift = build_volterra_lift()
    hawkes = HawkesNetwork(np.array([0.8, 0.9, 0.6, 0.7]),
        np.full((4, 4), 0.015), np.full((4, 4), 1.0))
    sim = simulate_rough_bergomi_jump_sde(spot0=22000.0, dt=1/252/78, n_steps=24,
        forward_variance=0.04, seed=seed, jump_intensity=0.3, rho=-0.6)
    event_data = hawkes.simulate(24, 1/252/78, seed=seed)
    fees = calculate_statutory_fees(100000.0, 100000.0, 2)
    band = friction_aware_no_trade_band(0.0, 0.02, 0.2, 1.0, 0.01, 0.012, 0.005)
    return {"cycle": 54, "engine": "DRH-RBVN", "hurst": ROUGH_HURST,
        "lift_factors": int(lift.rates.size), "lift_nonnegative_weights": bool(np.all(lift.weights >= 0)),
        "hawkes_spectral_radius": float(hawkes.spectral_radius),
        "hawkes_event_count": int(event_data["counts"].sum()),
        "simulated_steps": int(sim.returns.size), "terminal_spot": float(sim.spot[-1]),
        "terminal_variance": float(sim.variance[-1]), "max_jump_count": int(sim.jump_counts.max()),
        "fee_breakdown": fees, "no_trade_band": {"lower": band.lower, "upper": band.upper},
        "safety": safety_invariants()}
