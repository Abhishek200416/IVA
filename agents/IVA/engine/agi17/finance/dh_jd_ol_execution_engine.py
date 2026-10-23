"""Cycle 62 DH-JD-OL: offline research primitives for jump-risk liquidation.

Deterministic, paper-only implementation. This module deliberately exposes no
broker connector or live-order dispatch path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Sequence
import math
import numpy as np
from scipy.optimize import linprog

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0
GREEK_TOL = 1e-8
MAX_KELLY_FRACTION = 0.10


def _finite_array(x: Any, name: str, ndim: int | None = None) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if ndim is not None and a.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must contain only finite values")
    return a


def _nonnegative(x: float, name: str) -> float:
    x = float(x)
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return x


def multi_level_ofi(
    bid_volume_delta: Sequence[float], ask_volume_delta: Sequence[float],
    bid_price_delta: Sequence[float], ask_price_delta: Sequence[float],
    weights: Sequence[float] = (5, 4, 3, 2, 1),
) -> Dict[str, Any]:
    """Compute signed top-five MLOFI and return per-level contributions.

    Formula: w_l * (dVbid*1[dPbid>=0] - dVask*1[dPask<=0]). Volume changes
    may be signed; price/volume arrays must be finite and exactly length five.
    """
    arrays = [
        _finite_array(bid_volume_delta, "bid_volume_delta", 1),
        _finite_array(ask_volume_delta, "ask_volume_delta", 1),
        _finite_array(bid_price_delta, "bid_price_delta", 1),
        _finite_array(ask_price_delta, "ask_price_delta", 1),
        _finite_array(weights, "weights", 1),
    ]
    if any(a.shape != (5,) for a in arrays):
        raise ValueError("MLOFI expects exactly five values per input")
    bvol, avol, bpx, apx, w = arrays
    parts = w * (bvol * (bpx >= 0.0) - avol * (apx <= 0.0))
    return {"value": float(parts.sum()), "level_contributions": parts.tolist(), "weights": w.tolist()}


def queue_depletion_hazard(lambda0: float, level_coefficients: Sequence[float], mlofi_levels: Sequence[float], ofi_price: float = 0.0) -> float:
    """Nonnegative marked cancellation/depletion hazard from level signals."""
    lambda0 = _nonnegative(lambda0, "lambda0")
    c = _finite_array(level_coefficients, "level_coefficients", 1)
    f = _finite_array(mlofi_levels, "mlofi_levels", 1)
    if c.shape != (5,) or f.shape != (5,) or np.any(c < 0):
        raise ValueError("expected five nonnegative coefficients and five MLOFI values")
    ofi_price = float(ofi_price)
    if not math.isfinite(ofi_price):
        raise ValueError("ofi_price must be finite")
    # Absolute depletion is a hazard driver regardless of OFI sign.
    return float(lambda0 + np.dot(c, np.abs(f)) + abs(ofi_price))


class MarkedHawkes4:
    """Four-dimensional exponential marked Hawkes process with MLOFI coupling.

    For kernel alpha_ij exp(-beta_ij t), branching matrix is alpha/beta.
    State memory B_ij is exponentially decayed between observations, with
    event marks multiplying the corresponding source column at event times.
    """
    def __init__(self, mu: Sequence[float], alpha: Any, beta: Any, mlofi_gain: float = 0.0, max_rho: float = 0.88):
        self.mu = _finite_array(mu, "mu", 1)
        self.alpha = _finite_array(alpha, "alpha", 2)
        self.beta = _finite_array(beta, "beta", 2)
        if self.mu.shape != (4,) or self.alpha.shape != (4, 4) or self.beta.shape != (4, 4):
            raise ValueError("Hawkes arrays must have shapes (4,), (4,4), and (4,4)")
        if np.any(self.mu <= 0) or np.any(self.alpha < 0) or np.any(self.beta <= 0):
            raise ValueError("mu and beta must be positive; alpha must be nonnegative")
        self.mlofi_gain = float(mlofi_gain)
        self.max_rho = float(max_rho)
        if not math.isfinite(self.mlofi_gain) or self.mlofi_gain < 0:
            raise ValueError("mlofi_gain must be finite and nonnegative")
        if not (0 < self.max_rho <= 0.88):
            raise ValueError("max_rho must be in (0, 0.88]")
        self.branching = self.alpha / self.beta
        self.spectral_radius = float(np.max(np.abs(np.linalg.eigvals(self.branching))))
        if self.spectral_radius > self.max_rho + 1e-12:
            raise ValueError(f"Hawkes process not subcritical: rho={self.spectral_radius:.8g} > {self.max_rho}")
        self.memory = np.zeros((4, 4), dtype=float)
        self.intensity = self.mu.copy()
        self.time = 0.0

    def step(self, dt: float, mlofi: Sequence[float] | float = 0.0, marks: Sequence[float] | None = None) -> np.ndarray:
        dt = float(dt)
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        self.memory *= np.exp(-self.beta * dt)
        if marks is not None:
            mark = _finite_array(marks, "marks", 1)
            if mark.shape != (4,) or np.any(mark < 0):
                raise ValueError("marks must be four finite nonnegative values")
            self.memory += self.alpha * mark[np.newaxis, :]
        m = np.asarray(mlofi, dtype=float)
        if m.ndim == 0:
            m = np.full(4, float(m))
        if m.shape != (4,) or not np.all(np.isfinite(m)):
            raise ValueError("mlofi must be a scalar or four finite values")
        self.intensity = np.maximum(self.mu + self.memory.sum(axis=1) + self.mlofi_gain * m, 1e-12)
        self.time += dt
        return self.intensity.copy()

    def audit(self) -> Dict[str, float | bool]:
        return {"spectral_radius": self.spectral_radius, "limit": self.max_rho, "subcritical": self.spectral_radius <= self.max_rho}


def hazard_probability(intensity: float, horizon: float) -> float:
    intensity = _nonnegative(intensity, "intensity")
    horizon = _nonnegative(horizon, "horizon")
    return float(-math.expm1(-intensity * horizon))


def quote_action_for_toxicity(intensity: float, horizon: float, threshold: float = 0.60) -> Dict[str, float | str]:
    p = hazard_probability(intensity, horizon)
    threshold = float(threshold)
    if not (math.isfinite(threshold) and 0 <= threshold <= 1):
        raise ValueError("threshold must be in [0,1]")
    return {"adverse_probability": p, "quote_action": "RETREAT" if p > threshold else "QUOTE"}


def _tensor_concat(a: list[np.ndarray | float], b: list[np.ndarray | float], degree: int) -> list[np.ndarray | float]:
    out: list[np.ndarray | float] = []
    for n in range(degree + 1):
        acc = None
        for k in range(n + 1):
            left, right = a[k], b[n - k]
            term = np.tensordot(left, right, axes=0)
            acc = term if acc is None else acc + term
        out.append(float(acc) if np.ndim(acc) == 0 else np.asarray(acc, dtype=float))
    return out


def path_signature(path: Any, degree: int = 3) -> list[Any]:
    """Truncated tensor signature of a piecewise-linear path (levels 0..degree)."""
    x = _finite_array(path, "path", 2)
    if x.shape[0] < 1 or x.shape[1] < 1:
        raise ValueError("path must contain at least one point and one channel")
    if not isinstance(degree, (int, np.integer)) or not (1 <= degree <= 3):
        raise ValueError("degree must be an integer in [1,3]")
    d = x.shape[1]
    sig: list[Any] = [1.0] + [np.zeros((d,) * k, dtype=float) for k in range(1, degree + 1)]
    for dx in np.diff(x, axis=0):
        segment: list[Any] = [1.0]
        for k in range(1, degree + 1):
            t = dx
            for _ in range(k - 1):
                t = np.tensordot(t, dx, axes=0)
            segment.append(t / math.factorial(k))
        sig = _tensor_concat(sig, segment, degree)
    return sig


def levy_area(signature: Sequence[Any]) -> np.ndarray:
    if len(signature) < 3:
        raise ValueError("signature must contain level two")
    s2 = _finite_array(signature[2], "signature level 2", 2)
    if s2.shape[0] != s2.shape[1]:
        raise ValueError("signature level-2 tensor must be square")
    area = 0.5 * (s2 - s2.T)
    # Explicitly remove roundoff on the diagonal.
    np.fill_diagonal(area, 0.0)
    return area


def signature_random_features(paths: Sequence[Any], n_features: int = 128, seed: int = 6201, degree: int = 3) -> Dict[str, Any]:
    """Bounded randomized signature features and PSD kernel Gram matrix."""
    if not isinstance(n_features, (int, np.integer)) or n_features < 1:
        raise ValueError("n_features must be a positive integer")
    sigs = [path_signature(p, degree=degree) for p in paths]
    if not sigs:
        raise ValueError("paths cannot be empty")
    d0 = np.asarray(sigs[0][1]).size
    if any(np.asarray(s[1]).size != d0 for s in sigs):
        raise ValueError("all paths must have equal channel dimension")
    flat = np.stack([np.concatenate([np.asarray(v).reshape(-1) for v in s[1:]]) for s in sigs])
    rng = np.random.default_rng(seed)
    projection = rng.normal(0.0, 1.0 / math.sqrt(n_features), size=(flat.shape[1], n_features))
    features = flat @ projection
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    features = np.divide(features, np.maximum(norms, 1e-12))
    gram = 0.5 * (features @ features.T + 1.0)
    gram = 0.5 * (gram + gram.T)
    return {"features": features, "gram": gram, "min_eigenvalue": float(np.linalg.eigvalsh(gram).min()), "signatures": sigs}


def optimal_liquidation_schedule(
    q0: float, horizon: float, n_steps: int, impact: float, risk_aversion: float,
    volatility: float, jump_intensity: float = 0.0, jump_variance: float = 0.0,
) -> Dict[str, Any]:
    """Deterministic AC-style trajectory with terminal inventory exactly zero.

    The risk term adds a jump-variance proxy to diffusion variance. The solution
    is the continuous AC hyperbolic schedule sampled on a uniform grid.
    """
    vals = [q0, horizon, impact, risk_aversion, volatility, jump_intensity, jump_variance]
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("all scalar inputs must be finite")
    q0, horizon, impact, risk_aversion, volatility, jump_intensity, jump_variance = map(float, vals)
    if horizon <= 0 or impact <= 0 or risk_aversion < 0 or volatility < 0 or jump_intensity < 0 or jump_variance < 0:
        raise ValueError("horizon/impact must be positive; risk, volatility, jump terms nonnegative")
    if not isinstance(n_steps, (int, np.integer)) or n_steps < 2:
        raise ValueError("n_steps must be an integer >= 2")
    times = np.linspace(0.0, horizon, int(n_steps) + 1)
    total_var = volatility**2 + jump_intensity * jump_variance
    k = math.sqrt(risk_aversion * total_var / impact)
    if k * horizon < 1e-5:
        inventory = q0 * (1.0 - times / horizon)
    else:
        denom = -math.expm1(-2.0 * k * horizon)
        inventory = q0 * (np.exp(-k * times) - np.exp(-2.0 * k * horizon + k * times)) / denom
    inventory[0] = q0
    inventory[-1] = 0.0
    dt = horizon / int(n_steps)
    rates = -np.diff(inventory) / dt
    temporary_cost = impact * float(np.sum(rates**2) * dt)
    risk_cost = risk_aversion * total_var * float(np.sum(((inventory[:-1] + inventory[1:]) * 0.5) ** 2) * dt)
    return {"times": times, "inventory": inventory, "trading_rates": rates, "terminal_inventory": float(inventory[-1]), "half_life": (math.log(2.0) / k if k > 0 else math.inf), "temporary_cost_proxy": temporary_cost, "risk_cost_proxy": risk_cost}


def cross_index_surface_dislocations(nifty_total_variance: Any, banknifty_total_variance: Any, expiries: Sequence[float], strikes: Sequence[float], tolerance: float = 1e-10) -> Dict[str, Any]:
    n = _finite_array(nifty_total_variance, "nifty_total_variance", 2)
    b = _finite_array(banknifty_total_variance, "banknifty_total_variance", 2)
    t = _finite_array(expiries, "expiries", 1)
    k = _finite_array(strikes, "strikes", 1)
    if n.shape != b.shape or n.shape != (len(t), len(k)):
        raise ValueError("surface dimensions must match (number of expiries, number of strikes)")
    if np.any(np.diff(t) <= 0) or np.any(np.diff(k) <= 0) or np.any(n < 0) or np.any(b < 0):
        raise ValueError("expiries/strikes must increase and total variance must be nonnegative")
    if np.any(np.diff(n, axis=0) < -tolerance) or np.any(np.diff(b, axis=0) < -tolerance):
        raise ValueError("calendar total variance must be nondecreasing")
    spread = n - b
    return {"mean_cross_index_dislocation": float(np.mean(spread)), "max_abs_dislocation": float(np.max(np.abs(spread))), "calendar_monotone": True, "expiry_count": int(len(t)), "strike_count": int(len(k))}


def _martingale_lp(payoff: np.ndarray, x: np.ndarray, mu: np.ndarray, y: np.ndarray, nu: np.ndarray) -> Dict[str, Any]:
    n, m = payoff.shape
    nv = n * m
    Aeq, beq = [], []
    # Source marginals.
    for i in range(n):
        row = np.zeros((n, m)); row[i, :] = 1.0
        Aeq.append(row.ravel()); beq.append(mu[i])
    # Target marginals.
    for j in range(m):
        row = np.zeros((n, m)); row[:, j] = 1.0
        Aeq.append(row.ravel()); beq.append(nu[j])
    # Rowwise martingale constraint: sum_j (y_j-x_i) pi_ij = 0.
    for i in range(n):
        row = np.zeros((n, m)); row[i, :] = y - x[i]
        Aeq.append(row.ravel()); beq.append(0.0)
    Aeq_arr = np.asarray(Aeq); beq_arr = np.asarray(beq)
    lo = linprog(payoff.ravel(), A_eq=Aeq_arr, b_eq=beq_arr, bounds=(0.0, None), method="highs")
    hi = linprog(-payoff.ravel(), A_eq=Aeq_arr, b_eq=beq_arr, bounds=(0.0, None), method="highs")
    if not lo.success or not hi.success:
        raise ValueError(f"martingale transport infeasible: lower={lo.message}; upper={hi.message}")

    # Dual variables phi(x), psi(y), h(x): phi+psi+h*(y-x) <= payoff (lower)
    # or >= payoff (upper). Expectations of h*(Y-X) vanish under martingales.
    dual_obj = np.concatenate([mu, nu, np.zeros(n)])
    A_dual = []
    for i in range(n):
        for j in range(m):
            row = np.zeros(n + m + n)
            row[i] = 1.0; row[n + j] = 1.0; row[n + m + i] = y[j] - x[i]
            A_dual.append(row)
    A_dual = np.asarray(A_dual)
    lower_dual = linprog(-dual_obj, A_ub=A_dual, b_ub=payoff.ravel(), bounds=[(None, None)] * len(dual_obj), method="highs")
    upper_dual = linprog(dual_obj, A_ub=-A_dual, b_ub=-payoff.ravel(), bounds=[(None, None)] * len(dual_obj), method="highs")
    if not lower_dual.success or not upper_dual.success:
        raise RuntimeError("MOT dual LP did not converge")
    pi_lo = lo.x.reshape(n, m); pi_hi = hi.x.reshape(n, m)
    row_res = max(float(np.max(np.abs(pi.sum(axis=1) - mu))) for pi in (pi_lo, pi_hi))
    col_res = max(float(np.max(np.abs(pi.sum(axis=0) - nu))) for pi in (pi_lo, pi_hi))
    mart_res = max(float(np.max(np.abs(pi @ y - x * mu))) for pi in (pi_lo, pi_hi))
    lower_primal = float(lo.fun); upper_primal = float(-hi.fun)
    lower_d = float(-lower_dual.fun); upper_d = float(upper_dual.fun)
    gap_lo = abs(lower_primal - lower_d); gap_hi = abs(upper_d - upper_primal)
    return {"lower_bound": lower_primal, "upper_bound": upper_primal, "lower_dual_bound": lower_d, "upper_dual_bound": upper_d,
            "lower_coupling": pi_lo, "upper_coupling": pi_hi, "row_marginal_residual": row_res,
            "column_marginal_residual": col_res, "martingale_residual": mart_res,
            "lower_duality_gap": gap_lo, "upper_duality_gap": gap_hi,
            "max_duality_gap": max(gap_lo, gap_hi), "solver_success": True}


def martingale_transport_bounds(x_support: Sequence[float], mu: Sequence[float], y_support: Sequence[float], nu: Sequence[float], payoff: Any, tolerance: float = 1e-8) -> Dict[str, Any]:
    x = _finite_array(x_support, "x_support", 1); y = _finite_array(y_support, "y_support", 1)
    mu = _finite_array(mu, "mu", 1); nu = _finite_array(nu, "nu", 1); c = _finite_array(payoff, "payoff", 2)
    if len(x) == 0 or len(y) == 0 or mu.shape != x.shape or nu.shape != y.shape or c.shape != (len(x), len(y)):
        raise ValueError("supports, marginals and payoff have incompatible shapes")
    if np.any(mu < 0) or np.any(nu < 0) or abs(mu.sum() - 1) > tolerance or abs(nu.sum() - 1) > tolerance:
        raise ValueError("marginals must be nonnegative and sum to one")
    if abs(float(x @ mu) - float(y @ nu)) > tolerance:
        raise ValueError("source and target means must match for a martingale coupling")
    result = _martingale_lp(c, x, mu, y, nu)
    result["certificate_tolerance"] = float(tolerance)
    if result["martingale_residual"] > tolerance or result["max_duality_gap"] > tolerance:
        raise RuntimeError("MOT certificate residual exceeds requested tolerance")
    return result


def calculate_indian_fees(buy_turnover: float = 0.0, sell_turnover: float = 0.0, exercise_turnover: float = 0.0, executed_legs: int = 0) -> Dict[str, float]:
    buy = _nonnegative(buy_turnover, "buy_turnover")
    sell = _nonnegative(sell_turnover, "sell_turnover")
    exercise = _nonnegative(exercise_turnover, "exercise_turnover")
    if not isinstance(executed_legs, (int, np.integer)) or executed_legs < 0:
        raise ValueError("executed_legs must be a nonnegative integer")
    stt = 0.0015 * (sell + exercise)
    stamp = 0.00003 * buy
    exchange = 0.0003553 * (buy + sell)
    sebi = 0.000001 * (buy + sell)
    brokerage = 20.0 * int(executed_legs)
    gst = 0.18 * (exchange + brokerage)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return {"stt": stt, "stamp_duty": stamp, "exchange": exchange, "sebi": sebi, "brokerage": brokerage, "gst": gst, "total": total}


def net_alpha_gate(expected_gross_alpha: float, total_fees: float) -> Dict[str, float | bool]:
    gross = float(expected_gross_alpha); fees = _nonnegative(total_fees, "total_fees")
    if not math.isfinite(gross):
        raise ValueError("expected_gross_alpha must be finite")
    net = gross - fees
    return {"expected_gross_alpha": gross, "total_fees": fees, "expected_net_alpha": net, "approved": net > 0.0}


def beta_fractional_kelly(prior_alpha: float, prior_beta: float, wins: int = 0, losses: int = 0, odds: float = 1.0, scale: float = 0.25, ceiling: float = MAX_KELLY_FRACTION) -> Dict[str, float]:
    a = float(prior_alpha) + int(wins); b0 = float(prior_beta) + int(losses)
    odds, scale, ceiling = float(odds), float(scale), float(ceiling)
    if not all(math.isfinite(v) for v in (a, b0, odds, scale, ceiling)) or a <= 0 or b0 <= 0 or odds <= 0 or scale < 0 or not (0 <= ceiling <= 0.10):
        raise ValueError("invalid Beta/Kelly parameters")
    if not isinstance(wins, (int, np.integer)) or not isinstance(losses, (int, np.integer)) or wins < 0 or losses < 0:
        raise ValueError("wins and losses must be nonnegative integers")
    p = a / (a + b0)
    raw = ((p * (odds + 1.0) - 1.0) / odds) * scale
    f = min(ceiling, max(0.0, raw))
    return {"posterior_win_probability": p, "raw_fraction": raw, "capital_fraction": f, "capital_fraction_ceiling": ceiling}


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    raise PermissionError("Cycle 62 is paper-only: live order dispatch is permanently disabled")


class ActorCritic16:
    """Small deterministic NumPy actor-critic baseline with bounded 3D actions."""
    def __init__(self, seed: int = 6202, hidden: int = 24, learning_rate: float = 1e-3):
        if hidden < 2 or learning_rate <= 0 or not math.isfinite(learning_rate):
            raise ValueError("hidden must be >=2 and learning_rate positive")
        self.rng = np.random.default_rng(seed); self.lr = float(learning_rate)
        self.W1 = self.rng.normal(0, 1 / 4, (16, hidden)); self.b1 = np.zeros(hidden)
        self.W2 = self.rng.normal(0, 1 / math.sqrt(hidden), (hidden, hidden)); self.b2 = np.zeros(hidden)
        self.Wa = self.rng.normal(0, 1 / math.sqrt(hidden), (hidden, 3)); self.ba = np.zeros(3)
        self.Wv = self.rng.normal(0, 1 / math.sqrt(hidden), (hidden, 1)); self.bv = np.zeros(1)

    def _features(self, state: Sequence[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        s = _finite_array(state, "state", 1)
        if s.shape != (16,):
            raise ValueError("state must have exactly 16 dimensions")
        h1 = np.tanh(s @ self.W1 + self.b1); h2 = np.tanh(h1 @ self.W2 + self.b2)
        return s, h1, h2

    def policy(self, state: Sequence[float]) -> np.ndarray:
        _, _, h = self._features(state)
        return np.tanh(h @ self.Wa + self.ba)

    def value(self, state: Sequence[float]) -> float:
        _, _, h = self._features(state)
        return float((h @ self.Wv + self.bv)[0])

    def update(self, state: Sequence[float], reward: float, next_state: Sequence[float], gamma: float = 0.99, advantage: float | None = None) -> Dict[str, float]:
        reward = float(reward); gamma = float(gamma)
        if not math.isfinite(reward) or not (0 <= gamma <= 1):
            raise ValueError("invalid reward or gamma")
        s, h1, h2 = self._features(state); _, _, hn = self._features(next_state)
        v = float((h2 @ self.Wv + self.bv)[0]); vn = float((hn @ self.Wv + self.bv)[0])
        adv = reward + gamma * vn - v if advantage is None else float(advantage)
        if not math.isfinite(adv):
            raise ValueError("advantage must be finite")
        old_Wv = self.Wv.copy()
        grad_v = -adv
        self.Wv -= self.lr * grad_v * h2[:, None]; self.bv -= self.lr * np.array([grad_v])
        # Deterministic bounded policy update in the direction of advantage and current action.
        action = np.tanh(h2 @ self.Wa + self.ba)
        policy_signal = np.outer(h2, adv * (1.0 - action * action))
        self.Wa += self.lr * policy_signal; self.ba += self.lr * adv * (1.0 - action * action)
        return {"value_before": v, "target": reward + gamma * vn, "advantage": adv, "value_loss": 0.5 * adv * adv}


def toxicity_adjusted_spread(base_spread: float, gamma: float, volatility: float, inventory: float, toxicity_intensity: float, kappa: float = 1.0, alpha: float = 1.0) -> float:
    vals = [base_spread, gamma, volatility, inventory, toxicity_intensity, kappa, alpha]
    if not all(math.isfinite(float(v)) for v in vals) or base_spread < 0 or volatility < 0 or toxicity_intensity < 0 or kappa <= 0 or alpha <= 0:
        raise ValueError("invalid spread parameters")
    result = base_spread + gamma * volatility**2 * inventory + (2.0 / kappa) * math.log1p((kappa / alpha) * toxicity_intensity)
    return float(max(0.0, result))


def indifference_band(target_inventory: float, cost: float, volatility: float, risk_aversion: float, buy_penalty: float = 0.0, sell_penalty: float = 0.0, fee_drag: float = 0.0) -> Dict[str, float]:
    vals = [target_inventory, cost, volatility, risk_aversion, buy_penalty, sell_penalty, fee_drag]
    if not all(math.isfinite(float(v)) for v in vals) or cost < 0 or volatility < 0 or risk_aversion <= 0 or min(buy_penalty, sell_penalty, fee_drag) < 0:
        raise ValueError("invalid indifference band parameters")
    base = (3.0 * cost * volatility**2 / (4.0 * risk_aversion)) ** (1.0 / 3.0)
    return {"base_width": base, "lower": target_inventory - base - buy_penalty - fee_drag, "upper": target_inventory + base + sell_penalty + fee_drag}


def inventory_action(inventory: float, band: Dict[str, float]) -> str:
    q = float(inventory)
    if not math.isfinite(q) or not (math.isfinite(float(band["lower"])) and math.isfinite(float(band["upper"]))) or band["lower"] > band["upper"]:
        raise ValueError("invalid inventory or band")
    return "SELL/REDUCE" if q > band["upper"] else ("BUY/INCREASE" if q < band["lower"] else "NO_TRADE")


def agent_consensus(approvals: Dict[str, bool], manager_veto: bool = False) -> Dict[str, Any]:
    required = {"Manager Abhi", "Alex", "Emily", "Max"}
    missing = required.difference(approvals)
    if missing:
        return {"approved": False, "missing": sorted(missing), "reason": "incomplete squad"}
    approved = (not manager_veto) and all(bool(approvals[a]) for a in required)
    return {"approved": approved, "missing": [], "reason": "manager veto" if manager_veto else ("unanimous" if approved else "agent rejection")}


def offline_self_check() -> Dict[str, Any]:
    """Small fast smoke check used by example and offline runner."""
    mu = [0.1] * 4
    alpha = np.full((4, 4), 0.005); np.fill_diagonal(alpha, 0.01)
    beta = np.full((4, 4), 1.0)
    hawkes = MarkedHawkes4(mu, alpha, beta, mlofi_gain=0.001)
    intensity = hawkes.step(0.01, [0.2, -0.1, 0.3, 0.0], marks=[1, 0, 0.5, 0])
    path = np.array([[0., 0., 0.], [0.1, -0.05, 0.02], [0.2, 0.02, 0.03]])
    sig = path_signature(path, 3); area = levy_area(sig)
    liquid = optimal_liquidation_schedule(10.0, 1.0, 20, 0.2, 0.5, 0.2, 0.1, 0.03)
    fees = calculate_indian_fees(10000, 12000, executed_legs=2)
    risk = quote_action_for_toxicity(1.4, 0.8)
    return {"cycle": 62, "hawkes_intensity": intensity.tolist(), "hawkes_spectral_radius": hawkes.spectral_radius,
            "signature_level1": np.asarray(sig[1]).tolist(), "levy_area": area.tolist(),
            "liquidation_terminal_inventory": liquid["terminal_inventory"], "fee_total_inr": fees["total"],
            "adverse_probability": risk["adverse_probability"], "quote_action": risk["quote_action"],
            "paper_only": True}
