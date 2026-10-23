"""Cycle 52 FPS-EPGV research primitives: path signatures, pinning, contagion and safe paper controls.

Offline research/paper simulation only. No broker clients, credentials, or live order path are included.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from math import exp, gamma as gamma_fn, log, tanh
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np

ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
REGIME_NAMES = ("TREND_PERSISTENCE", "CHOP_MEAN_REVERSION", "JUMP_TOXIC_DEPLETION")
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0
ROUGH_HURST = 0.07
SIGNATURE_DEGREE = 3
SIGNATURE_PATH_DIMENSION = 4  # time + three price/return channels
MAX_KELLY_FRACTION = 0.10


def _finite_array(value, name: str, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain finite values")
    return arr


def _nonnegative(value, name: str) -> float:
    value = float(value)
    if not np.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


@dataclass(frozen=True)
class PathSignature:
    """Tensor signature levels S^1, S^2, S^3 of a piecewise-linear path."""
    level1: np.ndarray
    level2: np.ndarray
    level3: np.ndarray

    def __post_init__(self):
        l1 = _finite_array(self.level1, "level1", 1)
        d = l1.size
        l2 = _finite_array(self.level2, "level2", 2)
        l3 = _finite_array(self.level3, "level3", 3)
        if l2.shape != (d, d) or l3.shape != (d, d, d):
            raise ValueError("signature tensor levels have inconsistent dimensions")
        object.__setattr__(self, "level1", l1.copy())
        object.__setattr__(self, "level2", l2.copy())
        object.__setattr__(self, "level3", l3.copy())

    @property
    def dimension(self) -> int:
        return int(self.level1.size)

    @classmethod
    def identity(cls, dimension: int = SIGNATURE_PATH_DIMENSION) -> "PathSignature":
        if not isinstance(dimension, int) or dimension < 1:
            raise ValueError("dimension must be a positive integer")
        return cls(np.zeros(dimension), np.zeros((dimension, dimension)), np.zeros((dimension, dimension, dimension)))

    @classmethod
    def of_increment(cls, dx: Sequence[float]) -> "PathSignature":
        x = _finite_array(dx, "increment", 1)
        return cls(x, np.einsum("i,j->ij", x, x) / 2.0,
                   np.einsum("i,j,k->ijk", x, x, x) / 6.0)

    def concatenate(self, other: "PathSignature") -> "PathSignature":
        """Chen product S(X concatenated with Y), truncated at degree three."""
        if self.dimension != other.dimension:
            raise ValueError("cannot concatenate signatures of different dimensions")
        l1 = self.level1 + other.level1
        l2 = self.level2 + other.level2 + np.einsum("i,j->ij", self.level1, other.level1)
        l3 = (self.level3 + other.level3
              + np.einsum("i,jk->ijk", self.level1, other.level2)
              + np.einsum("ij,k->ijk", self.level2, other.level1))
        return PathSignature(l1, l2, l3)

    def flatten(self) -> np.ndarray:
        return np.concatenate((self.level1.ravel(), self.level2.ravel(), self.level3.ravel()))


def path_signature(points: Sequence[Sequence[float]], degree: int = SIGNATURE_DEGREE) -> PathSignature:
    """Compute the truncated signature of a path whose rows are ordered observations."""
    pts = _finite_array(points, "points", 2)
    if pts.shape[0] < 1 or pts.shape[1] < 1:
        raise ValueError("points must contain at least one point and one coordinate")
    if degree != 3:
        raise ValueError("this engine currently supports truncation at degree 3 only")
    sig = PathSignature.identity(pts.shape[1])
    for dx in np.diff(pts, axis=0):
        sig = sig.concatenate(PathSignature.of_increment(dx))
    return sig


def signature_features(signature: PathSignature, size: int = 16) -> np.ndarray:
    """Return a fixed-width, deterministic vector derived from signature levels."""
    if not isinstance(signature, PathSignature):
        raise TypeError("signature must be a PathSignature")
    if not isinstance(size, int) or size < 1:
        raise ValueError("size must be positive")
    flat = signature.flatten()
    if flat.size >= size:
        # Evenly spaced features preserve contributions from levels one through three.
        idx = np.linspace(0, flat.size - 1, num=size, dtype=int)
        out = flat[idx]
    else:
        out = np.pad(flat, (0, size - flat.size))
    return out.astype(float, copy=True)


def signature_predictability_features(signature: PathSignature) -> dict[str, float]:
    """Simple interpretable research features; these are not a trained predictor."""
    antisym = 0.5 * (signature.level2 - signature.level2.T)
    return {
        "net_path_norm": float(np.linalg.norm(signature.level1)),
        "geometric_area_norm": float(np.linalg.norm(antisym)),
        "degree3_norm": float(np.linalg.norm(signature.level3)),
        "volatility_burst_proxy": float(np.linalg.norm(signature.level2) + np.linalg.norm(signature.level3)),
    }


@dataclass(frozen=True)
class ExponentialVolterraLift:
    hurst: float
    rates: np.ndarray
    weights: np.ndarray

    def __post_init__(self):
        if not (0.0 < float(self.hurst) < 0.5):
            raise ValueError("hurst must lie in (0, 0.5)")
        rates = _finite_array(self.rates, "rates", 1)
        weights = _finite_array(self.weights, "weights", 1)
        if rates.size == 0 or rates.shape != weights.shape or np.any(rates <= 0) or np.any(weights < 0):
            raise ValueError("rates must be positive and aligned with non-negative weights")
        object.__setattr__(self, "rates", rates.copy())
        object.__setattr__(self, "weights", weights.copy())

    def evaluate(self, t: float | Sequence[float]) -> np.ndarray | float:
        ts = _finite_array(np.atleast_1d(t), "t", 1)
        if np.any(ts <= 0):
            raise ValueError("Volterra kernel is singular at t <= 0")
        ans = np.exp(-np.outer(ts, self.rates)) @ self.weights
        return float(ans[0]) if np.ndim(t) == 0 else ans


def rough_volterra_kernel(t: float | Sequence[float], hurst: float = ROUGH_HURST) -> np.ndarray | float:
    """K(t)=t^(H-1/2)/Gamma(H+1/2); t=0 is singular for H<1/2."""
    h = float(hurst)
    if not (0.0 < h < 0.5):
        raise ValueError("hurst must lie in (0, 0.5)")
    ts = _finite_array(np.atleast_1d(t), "t", 1)
    if np.any(ts <= 0):
        raise ValueError("t must be strictly positive because the kernel is singular at zero")
    vals = np.power(ts, h - 0.5) / gamma_fn(h + 0.5)
    return float(vals[0]) if np.ndim(t) == 0 else vals


def build_exponential_volterra_lift(hurst: float = ROUGH_HURST, factors: int = 12,
                                    tau_min: float = 1e-3, tau_max: float = 100.0) -> ExponentialVolterraLift:
    """Build a non-negative least-squares-like exponential proxy via projected gradient.

    The fit is a deterministic approximation, not a calibrated exact fractional kernel.
    """
    h = float(hurst)
    if not (0.0 < h < 0.5):
        raise ValueError("hurst must lie in (0, 0.5)")
    if not isinstance(factors, int) or factors < 1:
        raise ValueError("factors must be positive integer")
    tau_min = float(tau_min); tau_max = float(tau_max)
    if not (np.isfinite(tau_min) and np.isfinite(tau_max) and 0 < tau_min < tau_max):
        raise ValueError("require 0 < tau_min < tau_max")
    rates = np.geomspace(1.0 / tau_max, 1.0 / tau_min, factors)
    grid = np.geomspace(tau_min, tau_max, max(100, 8 * factors))
    design = np.exp(-np.outer(grid, rates))
    target = np.asarray(rough_volterra_kernel(grid, h))
    gram = design.T @ design
    lipschitz = float(np.linalg.norm(gram, ord=2))
    weights = np.full(factors, max(float(np.mean(target)) / factors, 1e-9))
    if lipschitz > 0:
        step = 1.0 / lipschitz
        for _ in range(800):
            grad = design.T @ (design @ weights - target)
            weights = np.maximum(weights - step * grad, 0.0)
    return ExponentialVolterraLift(h, rates, weights)


def _largest_open_interest_strike(open_interest: Mapping[float, float]) -> tuple[float, float, float]:
    if not isinstance(open_interest, Mapping) or not open_interest:
        raise ValueError("open_interest must be a non-empty strike-to-OI mapping")
    parsed: list[tuple[float, float]] = []
    for strike, oi in open_interest.items():
        strike = float(strike); oi = float(oi)
        if not np.isfinite(strike) or not np.isfinite(oi) or oi < 0:
            raise ValueError("strikes must be finite and OI finite/non-negative")
        parsed.append((strike, oi))
    total = sum(oi for _, oi in parsed)
    if total <= 0:
        raise ValueError("total open interest must be positive")
    # Deterministic tie-break: lowest strike among equal OI values.
    k_star, oi_star = sorted(parsed, key=lambda row: (-row[1], row[0]))[0]
    return k_star, oi_star, total


def expiry_pinning_force(spot: float, open_interest: Mapping[float, float], time_to_expiry: float,
                         kappa_pin: float, alpha: float = 0.5, epsilon: float = 1e-6) -> float:
    """Expiry pinning force toward max-OI strike; time_to_expiry units are caller-defined."""
    spot = float(spot); tau = float(time_to_expiry); kappa = float(kappa_pin)
    alpha = float(alpha); eps = float(epsilon)
    if not np.isfinite(spot) or spot <= 0:
        raise ValueError("spot must be positive and finite")
    if not np.isfinite(tau) or tau < 0:
        raise ValueError("time_to_expiry must be finite and non-negative")
    if not np.isfinite(kappa) or kappa < 0 or not np.isfinite(alpha) or alpha < 0:
        raise ValueError("kappa_pin and alpha must be finite and non-negative")
    if not np.isfinite(eps) or eps <= 0:
        raise ValueError("epsilon must be positive and finite")
    k_star, oi_star, total = _largest_open_interest_strike(open_interest)
    return -kappa * (spot - k_star) / (tau ** alpha + eps) * (oi_star / total)


def in_expiry_pin_window(timestamp: datetime, start: time = time(15, 0), end: time = time(15, 30),
                         expiry_weekday: int = 3) -> bool:
    """Check a Thursday final-30-minute window in Asia/Kolkata local time.

    Schedule is explicit/configurable and should be adjusted if exchange expiry rules change.
    """
    if not isinstance(timestamp, datetime):
        raise TypeError("timestamp must be a datetime")
    tz = ZoneInfo("Asia/Kolkata")
    local = timestamp.replace(tzinfo=tz) if timestamp.tzinfo is None else timestamp.astimezone(tz)
    return local.weekday() == int(expiry_weekday) and start <= local.timetz().replace(tzinfo=None) <= end


def gamma_vacuum_quote_action(dealer_gamma: float, gamma_threshold: float, hazard: float = 0.0,
                             hazard_threshold: float = float("inf"), toxic_cascade: bool = False) -> str:
    """Fail-safe quote response to negative dealer gamma vacuum or toxic/high-hazard conditions."""
    g = float(dealer_gamma); gt = float(gamma_threshold); h = float(hazard); ht = float(hazard_threshold)
    if not all(np.isfinite(x) or x == float("inf") for x in (g, gt, h, ht)):
        raise ValueError("gamma and hazard inputs must be finite (hazard threshold may be infinity)")
    if gt < 0 or h < 0 or ht < 0:
        raise ValueError("thresholds and hazard must be non-negative")
    return "RETREAT" if toxic_cascade or g < -gt or h >= ht else "QUOTE"


def cross_asset_liquidity_depletion(coupling: Sequence[Sequence[float]], decay: Sequence[Sequence[float]],
                                    shock_sizes: Sequence[float], ages: float | Sequence[float]) -> np.ndarray:
    """Return non-positive liquidity changes for asymmetric cross-impact shocks."""
    c = _finite_array(coupling, "coupling", 2)
    theta = _finite_array(decay, "decay", 2)
    q = _finite_array(shock_sizes, "shock_sizes", 1)
    if c.shape[0] != c.shape[1] or theta.shape != c.shape or q.size != c.shape[0]:
        raise ValueError("coupling/decay must be square and aligned with shock_sizes")
    if np.any(c < 0) or np.any(theta < 0):
        raise ValueError("coupling and decay rates must be non-negative")
    age = np.asarray(ages, dtype=float)
    if age.ndim == 0:
        age = np.full(q.size, float(age))
    if age.shape != q.shape or not np.all(np.isfinite(age)) or np.any(age < 0):
        raise ValueError("ages must be scalar or a non-negative vector aligned with shocks")
    if not np.all(np.isfinite(q)):
        raise ValueError("shock_sizes must be finite")
    return -np.sum(c * np.abs(q)[None, :] * np.exp(-theta * age[None, :]), axis=1)


def resilience_half_life(decay_matrix: Sequence[Sequence[float]], asset_index: int) -> float:
    theta = _finite_array(decay_matrix, "decay_matrix", 2)
    if theta.shape[0] != theta.shape[1] or np.any(theta < 0):
        raise ValueError("decay_matrix must be square and non-negative")
    if not isinstance(asset_index, int) or not 0 <= asset_index < theta.shape[0]:
        raise ValueError("asset_index out of range")
    rate = float(theta[asset_index, asset_index])
    return float("inf") if rate == 0 else log(2.0) / rate


class PathSignatureActorCritic:
    """Small deterministic two-hidden-layer actor and critic research baseline."""
    def __init__(self, state_dim: int = 16, hidden1: int = 32, hidden2: int = 16, seed: int = 52):
        if min(state_dim, hidden1, hidden2) < 1:
            raise ValueError("network dimensions must be positive")
        self.state_dim = int(state_dim)
        rng = np.random.default_rng(seed)
        self.aw1 = rng.normal(0, np.sqrt(2 / state_dim), (state_dim, hidden1))
        self.ab1 = np.zeros(hidden1)
        self.aw2 = rng.normal(0, np.sqrt(2 / hidden1), (hidden1, hidden2))
        self.ab2 = np.zeros(hidden2)
        self.aw3 = rng.normal(0, np.sqrt(1 / hidden2), (hidden2, 3))
        self.ab3 = np.zeros(3)
        self.cw1 = rng.normal(0, np.sqrt(2 / state_dim), (state_dim, hidden1))
        self.cb1 = np.zeros(hidden1)
        self.cw2 = rng.normal(0, np.sqrt(2 / hidden1), (hidden1, hidden2))
        self.cb2 = np.zeros(hidden2)
        self.cw3 = rng.normal(0, np.sqrt(1 / hidden2), (hidden2, 1))
        self.cb3 = np.zeros(1)

    def _state(self, state: Sequence[float]) -> np.ndarray:
        s = _finite_array(state, "state", 1)
        if s.size != self.state_dim:
            raise ValueError(f"state must contain exactly {self.state_dim} values")
        return s

    def act(self, state: Sequence[float]) -> np.ndarray:
        s = self._state(state)
        h1 = np.tanh(s @ self.aw1 + self.ab1)
        h2 = np.tanh(h1 @ self.aw2 + self.ab2)
        return np.tanh(h2 @ self.aw3 + self.ab3)

    def value(self, state: Sequence[float]) -> float:
        s = self._state(state)
        h1 = np.tanh(s @ self.cw1 + self.cb1)
        h2 = np.tanh(h1 @ self.cw2 + self.cb2)
        return float((h2 @ self.cw3 + self.cb3)[0])

    def train_critic(self, state: Sequence[float], target: float, learning_rate: float = 1e-3) -> float:
        s = self._state(state); target = float(target); lr = float(learning_rate)
        if not np.isfinite(target) or not np.isfinite(lr) or lr <= 0:
            raise ValueError("target must be finite and learning_rate positive")
        z1 = s @ self.cw1 + self.cb1; h1 = np.tanh(z1)
        z2 = h1 @ self.cw2 + self.cb2; h2 = np.tanh(z2)
        pred = float((h2 @ self.cw3 + self.cb3)[0])
        err = pred - target
        grad3 = np.array([err])
        dh2 = self.cw3 @ grad3
        dz2 = dh2 * (1 - h2 * h2)
        dh1 = self.cw2 @ dz2
        dz1 = dh1 * (1 - h1 * h1)
        self.cw3 -= lr * np.outer(h2, grad3)
        self.cb3 -= lr * grad3
        self.cw2 -= lr * np.outer(h1, dz2)
        self.cb2 -= lr * dz2
        self.cw1 -= lr * np.outer(s, dz1)
        self.cb1 -= lr * dz1
        return 0.5 * err * err

    def policy_gradient_step(self, state: Sequence[float], action_gradient: Sequence[float],
                             learning_rate: float = 1e-4) -> float:
        """Deterministic policy-gradient update given d(objective)/d(action)."""
        s = self._state(state); grad_a = _finite_array(action_gradient, "action_gradient", 1)
        lr = float(learning_rate)
        if grad_a.size != 3 or not np.isfinite(lr) or lr <= 0:
            raise ValueError("action_gradient must have 3 values and learning_rate be positive")
        z1 = s @ self.aw1 + self.ab1; h1 = np.tanh(z1)
        z2 = h1 @ self.aw2 + self.ab2; h2 = np.tanh(z2)
        z3 = h2 @ self.aw3 + self.ab3; act = np.tanh(z3)
        dz3 = grad_a * (1.0 - act * act)
        dh2 = self.aw3 @ dz3
        dz2 = dh2 * (1.0 - h2 * h2)
        dh1 = self.aw2 @ dz2
        dz1 = dh1 * (1.0 - h1 * h1)
        # Gradient ascent on the supplied objective.
        self.aw3 += lr * np.outer(h2, dz3); self.ab3 += lr * dz3
        self.aw2 += lr * np.outer(h1, dz2); self.ab2 += lr * dz2
        self.aw1 += lr * np.outer(s, dz1); self.ab1 += lr * dz1
        return float(np.linalg.norm(grad_a))


def friction_aware_advantage(reward: float, baseline_value: float, statutory_fees: float,
                             inventory: float, volatility: float, risk_aversion: float = 1.0) -> float:
    vals = np.asarray([reward, baseline_value, statutory_fees, inventory, volatility, risk_aversion], dtype=float)
    if not np.all(np.isfinite(vals)) or statutory_fees < 0 or volatility < 0 or risk_aversion < 0:
        raise ValueError("invalid advantage inputs")
    return float(reward - statutory_fees - risk_aversion * (inventory * volatility) ** 2 - baseline_value)


@dataclass(frozen=True)
class StatutoryFees:
    stt: float
    stamp_duty: float
    exchange: float
    sebi: float
    brokerage: float
    gst: float
    total: float


def calculate_statutory_fees(buy_turnover: float, sell_turnover: float, executed_legs: int,
                             brokerage_per_leg: float = 20.0) -> StatutoryFees:
    """Calculate the specified INR fee model.

    GST is modeled on exchange charges + SEBI fees + brokerage, not on turnover itself.
    """
    buy = _nonnegative(buy_turnover, "buy_turnover")
    sell = _nonnegative(sell_turnover, "sell_turnover")
    bp = _nonnegative(brokerage_per_leg, "brokerage_per_leg")
    if not isinstance(executed_legs, int) or executed_legs < 0:
        raise ValueError("executed_legs must be a non-negative integer")
    total_turnover = buy + sell
    stt = 0.0015 * sell
    stamp = 0.00003 * buy
    exchange = total_turnover * 3553.0 / 10_000_000.0
    sebi = total_turnover * 10.0 / 10_000_000.0
    brokerage = bp * executed_legs
    gst = 0.18 * (exchange + sebi + brokerage)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return StatutoryFees(stt, stamp, exchange, sebi, brokerage, gst, total)


def net_alpha_gate(expected_gross_alpha: float, fees: StatutoryFees | float) -> tuple[bool, float]:
    gross = float(expected_gross_alpha)
    fee_total = float(fees.total if isinstance(fees, StatutoryFees) else fees)
    if not np.isfinite(gross) or not np.isfinite(fee_total) or fee_total < 0:
        raise ValueError("gross alpha must be finite and fees finite/non-negative")
    net = gross - fee_total
    return net > 0.0, net


def beta_posterior_fractional_kelly(alpha_wins: float, beta_losses: float, payoff_odds: float,
                                   kelly_scale: float = 0.25, max_fraction: float = MAX_KELLY_FRACTION) -> float:
    """Conservative fractional Kelly using the Beta posterior mean win probability."""
    a = float(alpha_wins); bta = float(beta_losses); odds = float(payoff_odds)
    scale = float(kelly_scale); cap = float(max_fraction)
    if not all(np.isfinite(x) for x in (a, bta, odds, scale, cap)) or a <= 0 or bta <= 0 or odds <= 0:
        raise ValueError("alpha, beta, and odds must be finite and positive")
    if not (0 <= scale <= 1) or not (0 <= cap <= MAX_KELLY_FRACTION):
        raise ValueError("scale must lie in [0,1] and cap in [0,0.10]")
    p = a / (a + bta)
    full_kelly = max(0.0, (p * (odds + 1.0) - 1.0) / odds)
    return float(min(cap, scale * full_kelly))


def four_agent_consensus(manager_abhi: bool, alex_queue_safe: bool, emily_volatility_safe: bool,
                         max_net_alpha_safe: bool, manager_veto: bool = False) -> dict[str, object]:
    """Four-agent research consensus; approval only approves paper analysis, never live dispatch."""
    votes = {"Manager Abhi": bool(manager_abhi), "Alex": bool(alex_queue_safe),
             "Emily": bool(emily_volatility_safe), "Max": bool(max_net_alpha_safe)}
    if manager_veto or not votes["Manager Abhi"]:
        status = "VETO"
    elif all(votes.values()):
        status = "PAPER_APPROVE"
    else:
        status = "REJECT"
    return {"status": status, "votes": votes, "live_dispatch": False,
            "paper_ledger_epoch": PAPER_LEDGER_EPOCH, "initial_capital_inr": INITIAL_CAPITAL_INR}


def dispatch_live_order(*args, **kwargs):
    """Live routing is intentionally unavailable, independent of arguments or environment."""
    raise PermissionError("Live order dispatch is disabled in this research package")


def engine_manifest_summary() -> dict[str, object]:
    return {"cycle": 52, "engine": "FPS-EPGV", "assets": list(ASSETS), "degree": SIGNATURE_DEGREE,
            "path_dimension": SIGNATURE_PATH_DIMENSION, "rough_hurst": ROUGH_HURST,
            "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
            "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED,
            "paper_ledger_epoch": PAPER_LEDGER_EPOCH, "initial_capital_inr": INITIAL_CAPITAL_INR}
