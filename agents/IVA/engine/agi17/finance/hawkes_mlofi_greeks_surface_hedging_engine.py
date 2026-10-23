"""Cycle 42: Hawkes/MLOFI/Greek-surface paper research engine.

This package is a deterministic research/simulation reference. It contains no
broker adapter and no live order route. NumPy is the only runtime dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo
import json
import math
import time
import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_PAPER_CAPITAL = 10_000.0
ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
DEPTH_WEIGHTS = np.array([1.0, 0.8, 0.6, 0.4, 0.2], dtype=float)
IST = ZoneInfo("Asia/Kolkata")


def _finite_array(values: Any, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _sym_psd(matrix: Any, name: str, tolerance: float = 1e-9) -> np.ndarray:
    arr = _finite_array(matrix, name)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"{name} must be a square matrix")
    arr = (arr + arr.T) / 2.0
    eig = np.linalg.eigvalsh(arr)
    if float(eig.min(initial=0.0)) < -tolerance:
        raise ValueError(f"{name} must be positive semidefinite")
    return arr


def _spectral_radius(matrix: np.ndarray) -> float:
    if matrix.size == 0:
        return 0.0
    return float(np.max(np.abs(np.linalg.eigvals(matrix))))


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, np.ndarray):
        return [_json_safe(x) for x in obj.tolist()]
    if isinstance(obj, np.generic):
        return obj.item()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _json_safe(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Mapping):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


@dataclass(frozen=True)
class FeeConfig:
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    exchange_rate: float = 3553.0 / 10_000_000.0  # ₹3,553/crore
    sebi_rate: float = 10.0 / 10_000_000.0       # ₹10/crore
    gst_rate: float = 0.18
    brokerage_per_leg: float = 20.0

    def __post_init__(self) -> None:
        rates = (self.stt_sell_rate, self.stamp_buy_rate, self.exchange_rate,
                 self.sebi_rate, self.gst_rate, self.brokerage_per_leg)
        if not all(math.isfinite(x) and x >= 0 for x in rates):
            raise ValueError("fee rates and brokerage must be finite and nonnegative")
        if self.gst_rate > 1:
            raise ValueError("gst_rate must be a fraction in [0, 1]")


@dataclass(frozen=True)
class OptionLeg:
    instrument: str
    side: str
    premium: float
    lots: float
    lot_size: int = 1
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    half_spread_per_unit: float = 0.0
    impact_per_unit: float = 0.0

    def __post_init__(self) -> None:
        if self.side.upper() not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        nums = (self.premium, self.lots, self.delta, self.gamma, self.vega,
                self.half_spread_per_unit, self.impact_per_unit)
        if not all(math.isfinite(float(x)) for x in nums):
            raise ValueError("leg values must be finite")
        if self.premium < 0 or self.lots < 0 or self.lot_size < 1:
            raise ValueError("premium/lots must be nonnegative and lot_size >= 1")
        if self.half_spread_per_unit < 0 or self.impact_per_unit < 0:
            raise ValueError("spread and impact must be nonnegative")

    @property
    def quantity(self) -> float:
        return float(self.lots * self.lot_size)

    @property
    def turnover(self) -> float:
        return float(self.premium * self.quantity)


@dataclass(frozen=True)
class LegFee:
    instrument: str
    side: str
    turnover: float
    stt: float
    stamp_duty: float
    exchange_fee: float
    sebi_fee: float
    gst: float
    brokerage: float
    half_spread_slippage: float
    impact_cost: float
    total: float


@dataclass(frozen=True)
class FeeReport:
    legs: tuple[LegFee, ...]
    total_turnover: float
    stt: float
    stamp_duty: float
    exchange_fee: float
    sebi_fee: float
    gst: float
    brokerage: float
    half_spread_slippage: float
    impact_cost: float
    total_friction: float
    gross_alpha: float
    net_alpha: float
    approved: bool


class StatutoryCostCalculator:
    """Itemized premium-turnover levy accounting; rates are explicit inputs."""
    def __init__(self, config: FeeConfig | None = None):
        self.config = config or FeeConfig()

    def calculate(self, legs: Sequence[OptionLeg], gross_alpha: float) -> FeeReport:
        if not math.isfinite(gross_alpha):
            raise ValueError("gross_alpha must be finite")
        leg_fees: list[LegFee] = []
        totals = {k: 0.0 for k in ("turnover", "stt", "stamp", "exchange", "sebi", "gst", "brokerage", "spread", "impact")}
        for leg in legs:
            side = leg.side.upper()
            turnover = leg.turnover
            stt = turnover * self.config.stt_sell_rate if side == "SELL" else 0.0
            stamp = turnover * self.config.stamp_buy_rate if side == "BUY" else 0.0
            exch = turnover * self.config.exchange_rate
            sebi = turnover * self.config.sebi_rate
            brokerage = self.config.brokerage_per_leg
            gst = (exch + sebi + brokerage) * self.config.gst_rate
            spread = leg.half_spread_per_unit * leg.quantity
            impact = leg.impact_per_unit * leg.quantity
            total = stt + stamp + exch + sebi + brokerage + gst + spread + impact
            vals = (turnover, stt, stamp, exch, sebi, brokerage, gst, spread, impact, total)
            if not all(math.isfinite(v) and v >= 0 for v in vals):
                raise ValueError("calculated fee component is invalid")
            leg_fees.append(LegFee(leg.instrument, side, turnover, stt, stamp, exch, sebi, gst,
                                   brokerage, spread, impact, total))
            for k, v in zip(totals, (turnover, stt, stamp, exch, sebi, gst, brokerage, spread, impact)):
                totals[k] += v
        friction = totals["stt"] + totals["stamp"] + totals["exchange"] + totals["sebi"] + totals["gst"] + totals["brokerage"] + totals["spread"] + totals["impact"]
        net = float(gross_alpha - friction)
        return FeeReport(tuple(leg_fees), totals["turnover"], totals["stt"], totals["stamp"],
                         totals["exchange"], totals["sebi"], totals["gst"], totals["brokerage"],
                         totals["spread"], totals["impact"], float(friction), float(gross_alpha), net, net > 0.0)


class MLOFITracker:
    """Weighted five-level OFI tracker for four index-derivative order books."""
    def __init__(self, assets: Sequence[str] = ASSETS, weights: Sequence[float] = DEPTH_WEIGHTS):
        self.assets = tuple(assets)
        self.weights = _finite_array(weights, "weights").reshape(-1)
        if len(self.assets) == 0 or len(set(self.assets)) != len(self.assets):
            raise ValueError("assets must be nonempty and unique")
        if self.weights.size != 5 or np.any(self.weights < 0):
            raise ValueError("exactly five nonnegative depth weights are required")
        self.last_ofi = np.zeros(len(self.assets))
        self.last_level_ofi = np.zeros((len(self.assets), 5))
        self.updates = 0

    def update(self, bid_volume_deltas: Any, ask_volume_deltas: Any) -> np.ndarray:
        bid = _finite_array(bid_volume_deltas, "bid_volume_deltas")
        ask = _finite_array(ask_volume_deltas, "ask_volume_deltas")
        expected = (len(self.assets), 5)
        if bid.shape != expected or ask.shape != expected:
            raise ValueError(f"bid/ask deltas must both have shape {expected}")
        level_ofi = bid - ask
        self.last_level_ofi = level_ofi
        self.last_ofi = level_ofi @ self.weights
        self.updates += 1
        return self.last_ofi.copy()

    def snapshot(self) -> dict[str, Any]:
        return {"assets": list(self.assets), "ofi": self.last_ofi.copy(),
                "level_ofi": self.last_level_ofi.copy(), "updates": self.updates}


class HawkesNetwork:
    """Four-node asymmetric Hawkes network with a strict subcritical bound."""
    def __init__(self, mu: Any = None, alpha: Any = None, beta: Any = None, spectral_limit: float = 0.88):
        n = len(ASSETS)
        self.mu = _finite_array(mu if mu is not None else np.full(n, 0.2), "mu").reshape(-1)
        self.alpha = _finite_array(alpha if alpha is not None else np.full((n, n), 0.03), "alpha")
        self.beta = _finite_array(beta if beta is not None else np.full(n, 1.2), "beta").reshape(-1)
        if self.mu.size != n or self.beta.size != n or self.alpha.shape != (n, n):
            raise ValueError("Hawkes dimensions must match four assets")
        if np.any(self.mu <= 0) or np.any(self.alpha < 0) or np.any(self.beta <= 0):
            raise ValueError("mu/beta must be positive and alpha nonnegative")
        if not (0 < spectral_limit < 1):
            raise ValueError("spectral_limit must be in (0,1)")
        self.spectral_limit = float(spectral_limit)
        self.event_memory = np.zeros(n)
        self.last_intensity = self.mu.copy()
        self.elapsed = 0.0
        self._contract()

    @property
    def branching_matrix(self) -> np.ndarray:
        return self.alpha / self.beta[np.newaxis, :]

    @property
    def spectral_radius(self) -> float:
        return _spectral_radius(self.branching_matrix)

    def _contract(self) -> None:
        radius = self.spectral_radius
        if radius >= self.spectral_limit:
            self.alpha *= (self.spectral_limit * 0.999) / max(radius, 1e-15)
        # ensure strict margin after floating-point eigenvalue evaluation
        if self.spectral_radius >= self.spectral_limit:
            self.alpha *= 0.999
        self.last_intensity = self.mu + self.alpha @ self.event_memory

    def advance(self, dt: float, events: Iterable[int] = ()) -> np.ndarray:
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        self.event_memory *= np.exp(-self.beta * dt)
        self.elapsed += dt
        for event in events:
            self.record_event(int(event), dt=0.0)
        self.last_intensity = self.mu + self.alpha @ self.event_memory
        return self.last_intensity.copy()

    def record_event(self, asset_index: int, dt: float = 0.0) -> np.ndarray:
        if not 0 <= int(asset_index) < len(ASSETS):
            raise ValueError("asset_index is out of range")
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        if dt:
            self.event_memory *= np.exp(-self.beta * dt)
            self.elapsed += dt
        self.event_memory[int(asset_index)] += 1.0
        self.last_intensity = self.mu + self.alpha @ self.event_memory
        return self.last_intensity.copy()

    def update_parameters(self, mu_gradient: Any, alpha_gradient: Any, learning_rate: float = 1e-3) -> None:
        mg = _finite_array(mu_gradient, "mu_gradient").reshape(-1)
        ag = _finite_array(alpha_gradient, "alpha_gradient")
        if mg.shape != self.mu.shape or ag.shape != self.alpha.shape:
            raise ValueError("gradient dimensions do not match model")
        if not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        self.mu = np.maximum(self.mu + learning_rate * mg, 1e-8)
        self.alpha = np.maximum(self.alpha + learning_rate * ag, 0.0)
        self._contract()

    def centrality(self) -> dict[str, Any]:
        a = self.alpha.copy()
        out = a.sum(axis=0)  # outgoing from source j = column sum
        inn = a.sum(axis=1)  # incoming into target i = row sum
        out = out / max(float(out.max(initial=0.0)), 1e-12)
        inn = inn / max(float(inn.max(initial=0.0)), 1e-12)
        leadership = (a - a.T) / (a + a.T + 1e-12)
        np.fill_diagonal(leadership, 0.0)
        return {"in_absorption": inn, "out_spillover": out, "leadership": np.clip(leadership, -1, 1),
                "spectral_radius": self.spectral_radius, "branching_matrix": self.branching_matrix}


class RoughVolterraCovariance:
    """Positive-semidefinite four-asset covariance via a Markovian rough-kernel lift."""
    def __init__(self, hurst: Any = None, factors: int = 12, xi0: Any = None,
                 eta: float = 1.0, correlation: Any = None, seed: int = 42):
        n = len(ASSETS)
        self.hurst = _finite_array(hurst if hurst is not None else np.full(n, 0.08), "hurst").reshape(-1)
        if self.hurst.size != n or np.any(self.hurst <= 0.05) or np.any(self.hurst >= 0.45):
            raise ValueError("four Hurst parameters in (0.05,0.45) are required")
        if factors < 8:
            raise ValueError("at least eight exponential factors are required")
        if not math.isfinite(eta) or eta < 0:
            raise ValueError("eta must be finite and nonnegative")
        self.factors = int(factors)
        self.xi0 = _finite_array(xi0 if xi0 is not None else np.full(n, 0.04), "xi0").reshape(-1)
        if self.xi0.size != n or np.any(self.xi0 <= 0):
            raise ValueError("xi0 must be positive for four assets")
        self.eta = float(eta)
        self.correlation = self._prepare_correlation(correlation)
        self.cholesky = self._stable_cholesky(self.correlation)
        self.gamma_nodes = np.geomspace(0.02, 80.0, self.factors)
        self.weights = np.vstack([self._fit_kernel(float(h)) for h in self.hurst])
        self.state = np.zeros((n, self.factors))
        self.rng = np.random.default_rng(seed)
        self.elapsed = 0.0
        self.last_variance = self.xi0.copy()

    @staticmethod
    def _prepare_correlation(correlation: Any) -> np.ndarray:
        n = len(ASSETS)
        c = _finite_array(correlation if correlation is not None else np.eye(n), "correlation")
        if c.shape != (n, n):
            raise ValueError("correlation must be 4x4")
        c = (c + c.T) / 2
        d = np.sqrt(np.maximum(np.diag(c), 1e-12))
        c = c / np.outer(d, d)
        vals, vecs = np.linalg.eigh(c)
        c = vecs @ np.diag(np.maximum(vals, 1e-10)) @ vecs.T
        d = np.sqrt(np.diag(c))
        c = c / np.outer(d, d)
        return (c + c.T) / 2

    @staticmethod
    def _stable_cholesky(c: np.ndarray) -> np.ndarray:
        vals, vecs = np.linalg.eigh((c + c.T) / 2)
        return vecs @ np.diag(np.sqrt(np.maximum(vals, 1e-12)))

    def kernel(self, t: Any, asset: int = 0) -> np.ndarray | float:
        ts = np.asarray(t, dtype=float)
        if np.any(~np.isfinite(ts)) or np.any(ts <= 0) or not 0 <= asset < len(ASSETS):
            raise ValueError("t must be positive finite and asset index valid")
        target = np.power(ts, self.hurst[asset] - 0.5) / math.gamma(self.hurst[asset] + 0.5)
        approx = np.sum(self.weights[asset][None, :] * np.exp(-ts.reshape(-1, 1) * self.gamma_nodes[None, :]), axis=1)
        if ts.ndim == 0:
            return float(approx[0])
        return approx.reshape(ts.shape)

    def _fit_kernel(self, h: float) -> np.ndarray:
        t = np.geomspace(1e-4, 20.0, 320)
        target = np.power(t, h - 0.5) / math.gamma(h + 0.5)
        basis = np.exp(-t[:, None] * self.gamma_nodes[None, :])
        # Unconstrained least squares followed by nonnegative projection; scale fit robustly.
        weight, *_ = np.linalg.lstsq(basis, target, rcond=1e-9)
        weight = np.maximum(weight, 0.0)
        if not np.any(weight > 0):
            weight[0] = max(float(np.mean(target)), 1e-8)
        return weight

    def update(self, dt: float, innovations: Any = None, jump_shocks: Any = None) -> np.ndarray:
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("dt must be positive and finite")
        z = self.rng.normal(size=len(ASSETS)) if innovations is None else _finite_array(innovations, "innovations").reshape(-1)
        if z.size != len(ASSETS):
            raise ValueError("innovations must have length four")
        corr_z = self.cholesky @ z
        jumps = np.zeros(len(ASSETS)) if jump_shocks is None else _finite_array(jump_shocks, "jump_shocks").reshape(-1)
        if jumps.size != len(ASSETS):
            raise ValueError("jump_shocks must have length four")
        decay = np.exp(-self.gamma_nodes * dt)
        self.state = self.state * decay[None, :] + corr_z[:, None] * np.sqrt(dt) * np.sqrt(2 * self.gamma_nodes)[None, :] * 0.02
        self.state += jumps[:, None] * 0.02
        self.elapsed += dt
        rough = np.sum(self.weights * self.state, axis=1)
        correction = 0.5 * self.eta**2 * np.power(max(self.elapsed, 1e-12), 2 * self.hurst)
        self.last_variance = self.xi0 * np.exp(np.clip(self.eta * rough - correction, -40, 40))
        return self.covariance_matrix()

    def covariance_matrix(self) -> np.ndarray:
        scale = np.sqrt(np.maximum(self.last_variance, 1e-14))
        cov = np.diag(scale) @ self.correlation @ np.diag(scale)
        return (cov + cov.T) / 2

    def half_lives(self) -> np.ndarray:
        return np.log(2.0) / self.gamma_nodes

    def diagnostics(self) -> dict[str, Any]:
        return {"hurst": self.hurst.copy(), "variance": self.last_variance.copy(),
                "covariance": self.covariance_matrix(), "gamma_nodes": self.gamma_nodes.copy(),
                "kernel_weights": self.weights.copy(), "memory_half_lives": self.half_lives()}


@dataclass
class QueueOrder:
    order_id: str
    asset: str
    level: int
    side: str
    price: float
    quantity: int
    ahead: int
    behind: int
    created_at: float
    active: bool = True


class L3QueueBook:
    """Simplified FIFO L1-L5 order tracker with Poisson fill and toxicity pullback."""
    def __init__(self):
        self.orders: dict[str, QueueOrder] = {}
        self.last_toxicity = 0.0
        self.pullbacks = 0

    def add_order(self, order_id: str, asset: str, level: int, side: str, price: float,
                  quantity: int, ahead: int, behind: int = 0, now: float | None = None) -> QueueOrder:
        if not order_id or order_id in self.orders:
            raise ValueError("order_id must be nonempty and unique")
        if asset not in ASSETS or level not in range(1, 6) or side.upper() not in {"BUY", "SELL"}:
            raise ValueError("invalid asset, book level, or side")
        if not all(isinstance(v, int) and v >= 0 for v in (quantity, ahead, behind)) or quantity == 0:
            raise ValueError("quantity must be positive integer; ahead/behind nonnegative integers")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive and finite")
        created = time.time() if now is None else float(now)
        if not math.isfinite(created):
            raise ValueError("now must be finite")
        order = QueueOrder(order_id, asset, level, side.upper(), float(price), quantity, ahead, behind, created)
        self.orders[order_id] = order
        return order

    def _get(self, order_id: str) -> QueueOrder:
        try:
            return self.orders[order_id]
        except KeyError:
            raise KeyError(f"unknown order_id: {order_id}") from None

    def cancel_ahead(self, order_id: str, quantity: int) -> int:
        order = self._get(order_id)
        if quantity < 0:
            raise ValueError("cancel quantity must be nonnegative")
        removed = min(order.ahead, int(quantity))
        order.ahead -= removed
        return order.ahead

    def trade_ahead(self, order_id: str, quantity: int) -> int:
        order = self._get(order_id)
        if quantity < 0:
            raise ValueError("trade quantity must be nonnegative")
        traded = min(order.ahead, int(quantity))
        order.ahead -= traded
        remainder = int(quantity) - traded
        if remainder > 0:
            filled = min(order.quantity, remainder)
            order.quantity -= filled
            if order.quantity == 0:
                order.active = False
        return order.ahead

    @staticmethod
    def poisson_fill_probability(ahead: int, intensity: float, horizon: float) -> float:
        if not isinstance(ahead, int) or ahead < 0:
            raise ValueError("ahead must be a nonnegative integer")
        if not math.isfinite(intensity) or intensity < 0 or not math.isfinite(horizon) or horizon < 0:
            raise ValueError("intensity and horizon must be finite and nonnegative")
        lam = intensity * horizon
        threshold = ahead + 1
        if lam == 0:
            return 0.0
        if threshold == 1:
            return float(-math.expm1(-lam))
        # Stable recurrence for P(N < threshold); sensible for the small L3 queue sizes.
        term = math.exp(-lam)
        cdf = term
        for k in range(1, threshold):
            term *= lam / k
            cdf += term
            if term == 0.0:
                break
        return float(min(1.0, max(0.0, 1.0 - cdf)))

    def evaluate_pullback(self, order_id: str, market_intensity: float, horizon: float,
                          cancellation_hazard: float, expected_adverse_slippage: float,
                          round_trip_friction: float, fill_threshold: float = 0.85) -> dict[str, Any]:
        order = self._get(order_id)
        if any(not math.isfinite(v) or v < 0 for v in (market_intensity, horizon, cancellation_hazard,
                                                       expected_adverse_slippage, round_trip_friction)):
            raise ValueError("pullback inputs must be finite and nonnegative")
        if not 0 <= fill_threshold <= 1:
            raise ValueError("fill_threshold must be in [0,1]")
        intensity = market_intensity + cancellation_hazard
        pfill = self.poisson_fill_probability(order.ahead, intensity, horizon)
        survival = math.exp(-cancellation_hazard * horizon)
        toxicity = float(np.clip(expected_adverse_slippage / max(round_trip_friction, 1e-12), 0.0, 10.0) / 10.0)
        pullback = pfill > fill_threshold and expected_adverse_slippage > round_trip_friction
        self.last_toxicity = toxicity
        if pullback and order.active:
            order.active = False
            self.pullbacks += 1
        return {"order_id": order_id, "fill_probability": pfill, "order_survival": survival,
                "expected_adverse_slippage": expected_adverse_slippage, "round_trip_friction": round_trip_friction,
                "toxicity_score": toxicity, "quote_pullback_immediate": bool(pullback), "active": order.active}

    def snapshot(self) -> dict[str, Any]:
        return {"orders": [_json_safe(o) for o in self.orders.values()], "toxicity_score": self.last_toxicity,
                "pullbacks": self.pullbacks}


@dataclass
class RegimeKalmanSurface:
    """Two-regime Kalman filter for skew slope and ATM curvature."""
    skew: float = -0.15
    curvature: float = 0.25
    process_var: float = 0.01
    observation_var: float = 0.05
    expansion_threshold: float = 0.25
    regime_prob: np.ndarray = field(default_factory=lambda: np.array([0.8, 0.2], dtype=float))
    covariance: np.ndarray = field(default_factory=lambda: np.eye(2) * 0.1)
    updates: int = 0

    def __post_init__(self) -> None:
        if self.process_var <= 0 or self.observation_var <= 0 or self.expansion_threshold < 0:
            raise ValueError("Kalman variances must be positive; threshold nonnegative")
        p = _finite_array(self.regime_prob, "regime_prob").reshape(-1)
        if p.size != 2 or np.any(p < 0) or p.sum() <= 0:
            raise ValueError("regime_prob must have two nonnegative entries")
        self.regime_prob = p / p.sum()
        c = _finite_array(self.covariance, "covariance")
        if c.shape != (2, 2):
            raise ValueError("covariance must be 2x2")
        self.covariance = _sym_psd(c, "covariance")

    def update(self, skew_observation: float, curvature_observation: float, volatility_innovation: float = 0.0) -> dict[str, Any]:
        obs = _finite_array([skew_observation, curvature_observation, volatility_innovation], "observations")
        x = np.array([self.skew, self.curvature], dtype=float)
        p = self.covariance + np.eye(2) * self.process_var
        y = obs[:2]
        r = np.eye(2) * self.observation_var
        innovation = y - x
        s = p + r
        k = p @ np.linalg.inv(s)
        x_new = x + k @ innovation
        p_new = (np.eye(2) - k) @ p
        p_new = (p_new + p_new.T) / 2
        # Bayes update of calm/expansion probabilities using a robust scalar score.
        score = abs(float(obs[2])) + 0.5 * float(np.linalg.norm(innovation))
        expansion_likelihood = math.exp(-0.5 * ((score - self.expansion_threshold * 1.5) / max(self.expansion_threshold, 0.05)) ** 2)
        calm_likelihood = math.exp(-0.5 * (score / max(self.expansion_threshold, 0.05)) ** 2)
        prior = np.array([0.97 * self.regime_prob[0] + 0.15 * self.regime_prob[1],
                          0.03 * self.regime_prob[0] + 0.85 * self.regime_prob[1]])
        post = prior * np.array([calm_likelihood, expansion_likelihood])
        self.regime_prob = post / max(float(post.sum()), 1e-300)
        self.skew, self.curvature = float(x_new[0]), max(0.0, float(x_new[1]))
        self.covariance = p_new
        self.updates += 1
        return {"skew": self.skew, "curvature": self.curvature,
                "regime_probabilities": self.regime_prob.copy(),
                "regime": "VOLATILITY_EXPANSION" if self.regime_prob[1] >= 0.5 else "CALM",
                "innovation": innovation.copy()}


@dataclass
class SSVISurface:
    theta: float = 0.04
    rho: float = -0.3
    phi: float = 1.0
    mu: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.theta) or self.theta < 0:
            raise ValueError("theta must be finite and nonnegative")
        if not math.isfinite(self.rho) or abs(self.rho) >= 1:
            raise ValueError("rho must satisfy |rho| < 1")
        if not math.isfinite(self.phi) or self.phi < 0 or not math.isfinite(self.mu):
            raise ValueError("phi must be nonnegative and mu finite")

    def total_variance(self, k: float) -> float:
        if not math.isfinite(k):
            raise ValueError("k must be finite")
        x = self.phi * k + self.mu
        w = 0.5 * self.theta * (1.0 + self.rho * self.phi * k + math.sqrt(x * x + 1.0 - self.rho * self.rho))
        return max(0.0, float(w))

    def calendar_project(self, theta_by_maturity: Sequence[float]) -> np.ndarray:
        vals = _finite_array(theta_by_maturity, "theta_by_maturity").reshape(-1)
        if np.any(vals < 0):
            raise ValueError("total variance must be nonnegative")
        return np.maximum.accumulate(vals)

    def update_from_filter(self, filter_state: RegimeKalmanSurface) -> None:
        self.rho = float(np.clip(filter_state.skew, -0.98, 0.98))
        self.phi = float(max(0.0, filter_state.curvature))


@dataclass(frozen=True)
class AgentDecision:
    agent: str
    approved: bool
    reason: str


@dataclass(frozen=True)
class SquadDecision:
    approved: bool
    live_veto: bool
    decisions: tuple[AgentDecision, ...]
    reason: str


class TradingSquadConsensus:
    """Deterministic four-role consensus; Manager Abhi owns veto and capital gate."""
    @staticmethod
    def bayesian_kelly_fraction(win_probability: float, payoff_ratio: float,
                                uncertainty: float = 0.0, max_fraction: float = 0.25) -> float:
        """Uncertainty-haircut Kelly fraction for paper sizing; never returns negative risk."""
        values = (win_probability, payoff_ratio, uncertainty, max_fraction)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Kelly inputs must be finite")
        if not 0.0 <= win_probability <= 1.0 or payoff_ratio <= 0.0:
            raise ValueError("win_probability must be in [0,1] and payoff_ratio positive")
        if not 0.0 <= uncertainty <= 1.0 or not 0.0 <= max_fraction <= 1.0:
            raise ValueError("uncertainty and max_fraction must be in [0,1]")
        raw = win_probability - (1.0 - win_probability) / payoff_ratio
        return float(np.clip(raw * (1.0 - uncertainty), 0.0, max_fraction))

    def evaluate(self, *, live: bool, equity: float, capital_required: float,
                 net_alpha: float, adverse_selection: float = 0.0,
                 risk_score: float = 0.0, operator_approved: bool = True) -> SquadDecision:
        if live:
            decisions = (AgentDecision("Manager Abhi", False, "live dispatch prohibited by permanent veto"),
                         AgentDecision("Alex", False, "not evaluated after manager live veto"),
                         AgentDecision("Emily", False, "not evaluated after manager live veto"),
                         AgentDecision("Max", False, "not evaluated after manager live veto"))
            return SquadDecision(False, True, decisions, "Manager Abhi veto: paper simulation only")
        if any(not math.isfinite(v) for v in (equity, capital_required, net_alpha, adverse_selection, risk_score)):
            raise ValueError("consensus inputs must be finite")
        mgr = operator_approved and equity >= capital_required and capital_required >= 0
        alex = adverse_selection <= max(net_alpha, 0.0)
        emily = risk_score < 1.0
        max_ok = net_alpha > 0.0
        decisions = (AgentDecision("Manager Abhi", mgr, "operator approval and capital gate" if mgr else "capital/operator veto"),
                     AgentDecision("Alex", alex, "queue/adverse-selection gate" if alex else "adverse selection exceeds net edge"),
                     AgentDecision("Emily", emily, "rough-volatility risk gate" if emily else "risk score too high"),
                     AgentDecision("Max", max_ok, "statutory net-alpha gate" if max_ok else "net alpha must be strictly positive"))
        approved = all(d.approved for d in decisions)
        return SquadDecision(approved, False, decisions, "consensus approved" if approved else "one or more agents rejected candidate")


class AntiOvertradingThrottler:
    def __init__(self, max_trades_per_day: int = 15, tau_base: float = 900.0,
                 theta_v: float = 1.0, sigma_baseline: float = 0.2):
        if max_trades_per_day < 1 or tau_base <= 0 or theta_v < 0 or sigma_baseline <= 0:
            raise ValueError("invalid throttler configuration")
        self.max_trades_per_day = int(max_trades_per_day)
        self.tau_base, self.theta_v, self.sigma_baseline = float(tau_base), float(theta_v), float(sigma_baseline)
        self.trade_count = 0
        self.day_key: int | None = None
        self.loss_streak = 0
        self.last_fill_time: float | None = None
        self.last_size: float | None = None
        self.cooldown_until = 0.0
        self.lock_reason = ""

    def dynamic_cooldown(self, sigma_rough: float) -> float:
        if not math.isfinite(sigma_rough) or sigma_rough < 0:
            raise ValueError("sigma_rough must be finite and nonnegative")
        return self.tau_base * (1.0 + self.theta_v * sigma_rough / self.sigma_baseline)

    def optimal_trade_cap(self, alpha: float, cost: float, risk: float) -> int:
        if any(not math.isfinite(v) for v in (alpha, cost, risk)) or risk <= 0:
            raise ValueError("alpha/cost finite and risk positive")
        return max(0, int(round((alpha - cost) / risk)))

    def _set_lock(self, now: float, reason: str, sigma_rough: float = 0.0) -> None:
        duration = max(900.0, self.dynamic_cooldown(sigma_rough))
        self.cooldown_until = max(self.cooldown_until, now + duration)
        self.lock_reason = reason

    def can_enter(self, now: float, sigma_rough: float = 0.0) -> tuple[bool, str]:
        if not math.isfinite(now):
            raise ValueError("now must be finite")
        day = int(now // 86400)
        if self.day_key is None or day != self.day_key:
            self.day_key, self.trade_count = day, 0
        if now < self.cooldown_until:
            return False, self.lock_reason or "cooldown"
        if self.trade_count >= self.max_trades_per_day:
            return False, "daily_trade_cap"
        return True, "allowed"

    def record_fill(self, now: float, size: float, pnl: float, sigma_rough: float = 0.0) -> None:
        if any(not math.isfinite(v) for v in (now, size, pnl, sigma_rough)) or size <= 0 or sigma_rough < 0:
            raise ValueError("fill values must be finite; size positive")
        allowed, reason = self.can_enter(now, sigma_rough)
        if not allowed and reason == "daily_trade_cap":
            raise RuntimeError("daily trade cap reached")
        if self.day_key != int(now // 86400):
            self.day_key, self.trade_count = int(now // 86400), 0
        if self.last_fill_time is not None and now - self.last_fill_time < 30.0:
            self._set_lock(now, "rapid_pacing", sigma_rough)
        if self.last_size is not None and size / self.last_size > 1.25:
            self._set_lock(now, "revenge_sizing", sigma_rough)
        self.trade_count += 1
        self.loss_streak = self.loss_streak + 1 if pnl < 0 else 0
        if self.loss_streak >= 3:
            self._set_lock(now, "consecutive_losses", sigma_rough)
        self.last_fill_time, self.last_size = now, size


@dataclass(frozen=True)
class HedgeResult:
    weights: np.ndarray
    net_greeks: np.ndarray
    feasible: bool
    converged: bool
    iterations: int
    objective: float
    residual: float


class GreekHedgeOptimizer:
    """Projected proximal-gradient hedge optimizer with delta/gamma/vega slabs.

    Solves a convex quadratic + L1-cost objective. Dykstra projections enforce
    box constraints and Greek-neutrality bands. If the bands and bounds do not
    intersect, ``feasible`` is false rather than silently claiming neutrality.
    """
    def __init__(self, greek_tolerances: Sequence[float] = (1e-4, 1e-3, 1.0),
                 max_projection_iter: int = 500, max_opt_iter: int = 400,
                 tolerance: float = 1e-8):
        self.greek_tolerances = _finite_array(greek_tolerances, "greek_tolerances").reshape(-1)
        if self.greek_tolerances.size != 3 or np.any(self.greek_tolerances <= 0):
            raise ValueError("three strictly positive Greek tolerances are required")
        if max_projection_iter < 1 or max_opt_iter < 1 or tolerance <= 0:
            raise ValueError("iteration limits and tolerance must be positive")
        self.max_projection_iter = int(max_projection_iter)
        self.max_opt_iter = int(max_opt_iter)
        self.tolerance = float(tolerance)

    def _project(self, x: np.ndarray, greek_matrix: np.ndarray, current: np.ndarray,
                 lower: np.ndarray, upper: np.ndarray) -> tuple[np.ndarray, bool]:
        # Dykstra projections onto box + 3 affine slabs; corrections preserve the
        # Euclidean projection onto the intersection when it is non-empty.
        n = x.size
        corrections = np.zeros((4, n), dtype=float)
        out = x.copy()
        vectors = [greek_matrix[:, j].copy() for j in range(3)]
        norms = [float(v @ v) for v in vectors]
        for _ in range(self.max_projection_iter):
            old = out.copy()
            y = out + corrections[0]
            projected = np.clip(y, lower, upper)
            corrections[0] = y - projected
            out = projected
            for j, a in enumerate(vectors, start=1):
                y = out + corrections[j]
                val = float(a @ y + current[j-1])
                tol = float(self.greek_tolerances[j-1])
                if val > tol:
                    target = tol
                elif val < -tol:
                    target = -tol
                else:
                    target = val
                if norms[j-1] <= 1e-24:
                    projected = y.copy() if abs(current[j-1]) <= tol else y.copy()
                else:
                    projected = y + ((target - val) / norms[j-1]) * a
                corrections[j] = y - projected
                out = projected
            if np.max(np.abs(out - old), initial=0.0) < self.tolerance:
                break
        net = current + greek_matrix.T @ out
        feasible = bool(np.all(np.abs(net) <= self.greek_tolerances + max(self.tolerance * 20, 1e-8))
                        and np.all(out >= lower - 1e-8) and np.all(out <= upper + 1e-8))
        return out, feasible

    def optimize(self, *, covariance: Any, cross_impact: Any, greeks: Any,
                 current_greeks: Any, transaction_cost_rates: Any,
                 lower_bounds: Any = None, upper_bounds: Any = None,
                 eta_cross: float = 1.0, lambda_cost: float = 1.0) -> HedgeResult:
        g = _finite_array(greeks, "greeks")
        if g.ndim != 2 or g.shape[1] != 3 or g.shape[0] < 3:
            raise ValueError("greeks must have shape (n_instruments, 3), n >= 3")
        n = g.shape[0]
        current = _finite_array(current_greeks, "current_greeks").reshape(-1)
        costs = _finite_array(transaction_cost_rates, "transaction_cost_rates").reshape(-1)
        if current.size != 3 or costs.size != n or np.any(costs < 0):
            raise ValueError("current_greeks must have size 3; costs size n and nonnegative")
        if not math.isfinite(eta_cross) or eta_cross < 0 or not math.isfinite(lambda_cost) or lambda_cost < 0:
            raise ValueError("regularization weights must be finite and nonnegative")
        cov = _sym_psd(covariance, "covariance")
        omega = _sym_psd(cross_impact, "cross_impact")
        if cov.shape != (n, n) or omega.shape != (n, n):
            raise ValueError("covariance and cross_impact must be n x n")
        lo = np.full(n, -10.0) if lower_bounds is None else _finite_array(lower_bounds, "lower_bounds").reshape(-1)
        hi = np.full(n, 10.0) if upper_bounds is None else _finite_array(upper_bounds, "upper_bounds").reshape(-1)
        if lo.size != n or hi.size != n or np.any(lo > hi):
            raise ValueError("bounds must have size n and lower <= upper")
        h = (cov + eta_cross * omega)
        h = (h + h.T) / 2 + np.eye(n) * 1e-10
        w, feasible = self._project(np.zeros(n), g, current, lo, hi)
        if not feasible:
            net = current + g.T @ w
            objective = 0.5 * float(w @ h @ w) + lambda_cost * float(costs @ np.abs(w))
            residual = float(np.max(np.abs(net) / self.greek_tolerances))
            return HedgeResult(w, net, False, False, 0, objective, residual)
        largest = max(float(np.linalg.eigvalsh(h).max()), 1e-8)
        step = 0.95 / largest
        converged = False
        iterations = 0
        for it in range(1, self.max_opt_iter + 1):
            grad = h @ w
            candidate = w - step * grad
            threshold = step * lambda_cost * costs
            candidate = np.sign(candidate) * np.maximum(np.abs(candidate) - threshold, 0.0)
            candidate, feasible_now = self._project(candidate, g, current, lo, hi)
            iterations = it
            if not feasible_now:
                # Retain latest feasible iterate; fail closed if feasibility was lost.
                break
            if float(np.max(np.abs(candidate - w), initial=0.0)) <= self.tolerance:
                w = candidate
                converged = True
                break
            w = candidate
        net = current + g.T @ w
        residual = float(np.max(np.abs(net) / self.greek_tolerances))
        feasible = bool(np.all(np.abs(net) <= self.greek_tolerances + 2e-6)
                        and np.all(w >= lo - 1e-8) and np.all(w <= hi + 1e-8))
        objective = 0.5 * float(w @ h @ w) + lambda_cost * float(costs @ np.abs(w))
        return HedgeResult(w, net, feasible, converged, iterations, objective, residual)


class RiskState(str, Enum):
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    HEDGE_REQUIRED = "HEDGE_REQUIRED"
    COOLDOWN = "COOLDOWN"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class Cycle42ExecutionEngine:
    """Unified simulation engine. Live flags are immutable safety invariants."""
    def __init__(self, seed: int = 42, initial_capital: float = INITIAL_PAPER_CAPITAL):
        if not math.isfinite(initial_capital) or initial_capital <= 0:
            raise ValueError("initial_capital must be positive and finite")
        self.initial_capital = float(initial_capital)
        self.equity = float(initial_capital)
        self.ledger_epoch = PAPER_LEDGER_EPOCH
        self.ofi = MLOFITracker()
        self.hawkes = HawkesNetwork()
        self.rough = RoughVolterraCovariance(seed=seed)
        self.queue = L3QueueBook()
        self.surface_filter = RegimeKalmanSurface()
        self.surface = SSVISurface()
        self.costs = StatutoryCostCalculator()
        self.throttler = AntiOvertradingThrottler()
        self.squad = TradingSquadConsensus()
        self.risk_state = RiskState.IDLE
        self.last_fee_report: FeeReport | None = None
        self.last_consensus: SquadDecision | None = None
        self.last_hedge: dict[str, Any] | None = None
        self.heartbeats = 0

    @property
    def safety_state(self) -> dict[str, Any]:
        return {"LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
                "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED,
                "paper_ledger_epoch": self.ledger_epoch,
                "initial_capital": self.initial_capital}

    def evaluate_candidate(self, legs: Sequence[OptionLeg], gross_alpha: float, now: float,
                           sigma_rough: float = 0.05, adverse_selection: float = 0.0,
                           risk_score: float = 0.0, capital_required: float = 0.0,
                           live: bool = False, operator_approved: bool = True) -> dict[str, Any]:
        if live:
            consensus = self.squad.evaluate(live=True, equity=self.equity, capital_required=capital_required,
                                             net_alpha=float(gross_alpha))
            self.last_consensus = consensus
            return {"approved": False, "reason": consensus.reason, "live_veto": True,
                    "net_alpha": None, "fee_report": None, "consensus": consensus}
        report = self.costs.calculate(legs, gross_alpha)
        allowed, reason = self.throttler.can_enter(now, sigma_rough)
        consensus = self.squad.evaluate(live=False, equity=self.equity, capital_required=capital_required,
                                        net_alpha=report.net_alpha, adverse_selection=adverse_selection,
                                        risk_score=risk_score, operator_approved=operator_approved)
        self.last_fee_report, self.last_consensus = report, consensus
        approved = report.approved and allowed and consensus.approved
        self.risk_state = RiskState.MONITORING if allowed else RiskState.COOLDOWN
        if approved:
            self.risk_state = RiskState.HEDGE_REQUIRED
        return {"approved": bool(approved), "reason": "approved" if approved else (reason if not allowed else consensus.reason if not consensus.approved else "net alpha did not clear friction"),
                "live_veto": False, "net_alpha": report.net_alpha, "fee_report": report,
                "consensus": consensus, "throttle_allowed": allowed}

    def optimize_hedge(self, **kwargs: Any) -> HedgeResult:
        optimizer = GreekHedgeOptimizer()
        result = optimizer.optimize(**kwargs)
        self.last_hedge = _json_safe(result)
        if not result.feasible:
            self.risk_state = RiskState.EMERGENCY_UNWIND
        else:
            self.risk_state = RiskState.HEDGE_REQUIRED
        return result

    def record_fill(self, now: float, size: float, pnl: float, sigma_rough: float = 0.05) -> None:
        self.throttler.record_fill(now, size, pnl, sigma_rough)
        self.equity += pnl
        if self.equity <= 0:
            self.risk_state = RiskState.EMERGENCY_UNWIND

    def dispatch_live_order(self, *args: Any, **kwargs: Any) -> None:
        raise PermissionError("live order dispatch is permanently disabled; paper simulation only")

    def update_microstructure(self, bid_deltas: Any, ask_deltas: Any, dt: float,
                              hawkes_events: Iterable[int] = ()) -> dict[str, Any]:
        ofi = self.ofi.update(bid_deltas, ask_deltas)
        intensity = self.hawkes.advance(dt, hawkes_events)
        cov = self.rough.update(dt)
        return {"ofi": ofi, "hawkes_intensity": intensity, "covariance": cov}

    def telemetry(self) -> dict[str, Any]:
        self.heartbeats += 1
        now = datetime.now(timezone.utc).astimezone(IST)
        report = self.last_fee_report
        return _json_safe({"timestamp_ist": now.isoformat(), "epoch_seconds": now.timestamp(),
                           "mlofi": self.ofi.snapshot(), "hawkes": self.hawkes.centrality(),
                           "rough_covariance": self.rough.diagnostics(),
                           "queue": self.queue.snapshot(),
                           "surface": {"theta": self.surface.theta, "rho": self.surface.rho,
                                       "phi": self.surface.phi, "mu": self.surface.mu,
                                       "kalman": {"skew": self.surface_filter.skew,
                                                  "curvature": self.surface_filter.curvature,
                                                  "regime_probabilities": self.surface_filter.regime_prob}},
                           "last_fee_report": report, "last_consensus": self.last_consensus, "last_hedge": self.last_hedge,
                           "risk_state": self.risk_state, "trade_count": self.throttler.trade_count,
                           "loss_streak": self.throttler.loss_streak,
                           "cooldown_until": self.throttler.cooldown_until,
                           "cooldown_remaining": max(0.0, self.throttler.cooldown_until - time.time()),
                           "heartbeat": self.heartbeats, "safety": self.safety_state})

    def start_dashboard(self, host: str = "127.0.0.1", port: int = 8088) -> ThreadingHTTPServer:
        engine = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    data = {"status": "ok", "risk_state": engine.risk_state.value, "safety": engine.safety_state}
                    raw = json.dumps(_json_safe(data), allow_nan=False).encode()
                    self.send_response(200); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
                elif self.path == "/telemetry":
                    raw = json.dumps(engine.telemetry(), allow_nan=False).encode()
                    self.send_response(200); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
                elif self.path == "/events":
                    raw = json.dumps(engine.telemetry(), allow_nan=False).encode()
                    body = b"retry: 1000\nevent: telemetry\ndata: " + raw + b"\n\n"
                    self.send_response(200); self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache"); self.send_header("Connection", "close")
                    self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                    self.close_connection = True
                else:
                    raw = b'{"error":"not_found"}'
                    self.send_response(404); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def log_message(self, format: str, *args: Any) -> None:
                return
        server = ThreadingHTTPServer((host, port), Handler)
        server.daemon_threads = True
        return server


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    raise PermissionError("live order dispatch is permanently disabled; paper simulation only")
