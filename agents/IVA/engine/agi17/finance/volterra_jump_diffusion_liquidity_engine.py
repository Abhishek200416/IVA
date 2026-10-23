"""Cycle 44: rough Volterra jump diffusion, liquidity contagion, dealer unwind,
Greek-constrained neural hedging, statutory friction and paper-only risk controls.

Research reference only. It intentionally contains no broker adapter or live order path.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo
from typing import Any, Iterable, Mapping, Sequence
import json
import math
import threading
import time

import numpy as np
from scipy.optimize import minimize

ASSETS = ("NIFTY 50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_PAPER_CAPITAL = 10_000.0
IST = ZoneInfo("Asia/Kolkata")


def _finite_array(values: Any, name: str, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain finite values")
    return arr


def _spectral_radius(matrix: np.ndarray) -> float:
    if matrix.size == 0:
        return 0.0
    vals = np.linalg.eigvals(matrix)
    return float(np.max(np.abs(vals))) if vals.size else 0.0


def _safe_exp(x: float, cap: float = 60.0) -> float:
    return math.exp(max(-cap, min(cap, float(x))))


def timestamp_payload(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(IST)
    return {"timestamp_ist": local.isoformat(), "timestamp_epoch": current.timestamp()}


class RiskState(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    QUARANTINE = "QUARANTINE"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class AgentName(str, Enum):
    MANAGER_ABHI = "Manager Abhi"
    ALEX = "Alex"
    EMILY = "Emily"
    MAX = "Max"


@dataclass(frozen=True)
class VolatilitySnapshot:
    asset: str
    variance: float
    volatility: float
    jump_intensity: float
    rough_state: float
    factor_count: int


class RoughVolterraJumpDiffusion:
    """Positive variance process using a finite exponential lift and compound jumps.

    The positive lift weights approximate K(t)=t^(H-1/2)/Gamma(H+1/2) on a
    finite calibrated horizon. State evolution is an approximation, not an exact rBergomi simulator.
    """
    def __init__(self, asset: str, hurst: float = 0.07, xi0: float = 0.04,
                 eta: float = 1.25, factors: int = 12,
                 gamma_min: float = 0.05, gamma_max: float = 250.0,
                 base_jump_intensity: float = 0.15, intensity_sensitivity: float = 0.35,
                 jump_log_mean: float = -0.02, jump_log_std: float = 0.08,
                 seed: int = 44) -> None:
        if not (0.05 < hurst < 0.5):
            raise ValueError("hurst must be in (0.05, 0.5)")
        if xi0 <= 0 or eta < 0 or factors < 8 or gamma_min <= 0 or gamma_max <= gamma_min:
            raise ValueError("invalid Volterra lift parameters")
        if base_jump_intensity < 0 or intensity_sensitivity < 0 or jump_log_std < 0:
            raise ValueError("invalid jump parameters")
        self.asset = str(asset)
        self.hurst = float(hurst)
        self.xi0 = float(xi0)
        self.eta = float(eta)
        self.factors = int(factors)
        self.gamma_rates, self.kernel_weights = self._make_lift(self.hurst, self.factors, gamma_min, gamma_max)
        self.normalized_weights = self.kernel_weights / max(float(np.sum(self.kernel_weights)), 1e-15)
        self.state = np.zeros(self.factors, dtype=float)
        self.variance = self.xi0
        self.base_jump_intensity = float(base_jump_intensity)
        self.intensity_sensitivity = float(intensity_sensitivity)
        self.jump_log_mean = float(jump_log_mean)
        self.jump_log_std = float(jump_log_std)
        self.rng = np.random.default_rng(seed)
        self.elapsed = 0.0
        self.last_jump_count = 0
        self.last_rough_state = 0.0

    @staticmethod
    def _make_lift(hurst: float, factors: int, gamma_min: float, gamma_max: float) -> tuple[np.ndarray, np.ndarray]:
        # Laplace representation of t^(a-1)/Gamma(a), a=H+1/2.
        a = hurst + 0.5
        log_nodes = np.linspace(math.log(gamma_min), math.log(gamma_max), factors)
        rates = np.exp(log_nodes)
        spacing = float(log_nodes[1] - log_nodes[0]) if factors > 1 else 1.0
        weights = (math.sin(math.pi * a) / math.pi) * rates ** (1.0 - a) * spacing
        return rates, weights

    def kernel(self, t: float) -> float:
        if not math.isfinite(t) or t <= 0:
            raise ValueError("kernel time must be finite and > 0")
        return float(t ** (self.hurst - 0.5) / math.gamma(self.hurst + 0.5))

    def lifted_kernel(self, t: float) -> float:
        if not math.isfinite(t) or t < 0:
            raise ValueError("lifted kernel time must be finite and >= 0")
        return float(np.dot(self.kernel_weights, np.exp(-self.gamma_rates * t)))

    def fit_error(self, times: Sequence[float]) -> float:
        ts = _finite_array(times, "times").reshape(-1)
        if ts.size == 0 or np.any(ts <= 0):
            raise ValueError("times must be a non-empty positive sequence")
        errors = [abs(self.lifted_kernel(float(t)) - self.kernel(float(t))) / max(self.kernel(float(t)), 1e-12) for t in ts]
        return float(max(errors))

    def instantaneous_jump_intensity(self) -> float:
        scale = abs(self.last_rough_state)
        return float(max(0.0, self.base_jump_intensity * (1.0 + self.intensity_sensitivity * scale)))

    def update(self, dt: float, gaussian_shock: float | None = None, jump_count: int | None = None,
               jump_sizes: Sequence[float] | None = None) -> VolatilitySnapshot:
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("dt must be finite and > 0")
        shock = float(self.rng.normal()) if gaussian_shock is None else float(gaussian_shock)
        if not math.isfinite(shock):
            raise ValueError("gaussian_shock must be finite")
        decay = np.exp(-self.gamma_rates * dt)
        innovation_scale = np.sqrt(np.maximum(1.0 - decay * decay, 0.0))
        self.state = decay * self.state + innovation_scale * shock
        self.last_rough_state = float(np.dot(self.normalized_weights, self.state))
        intensity = self.instantaneous_jump_intensity()
        if jump_count is None:
            count = int(self.rng.poisson(intensity * dt))
        else:
            if int(jump_count) != jump_count or jump_count < 0:
                raise ValueError("jump_count must be a non-negative integer")
            count = int(jump_count)
        if jump_sizes is None:
            jumps = self.rng.normal(self.jump_log_mean, self.jump_log_std, size=count) if count else np.empty(0)
        else:
            jumps = _finite_array(jump_sizes, "jump_sizes").reshape(-1)
            if jumps.size != count:
                raise ValueError("jump_sizes length must equal jump_count")
        jump_log_return = float(np.sum(jumps))
        exponent = self.eta * self.last_rough_state - 0.5 * self.eta * self.eta * dt ** (2 * self.hurst) + jump_log_return
        self.variance = float(max(1e-12, self.xi0 * _safe_exp(exponent, 45.0)))
        self.elapsed += dt
        self.last_jump_count = count
        return VolatilitySnapshot(self.asset, self.variance, math.sqrt(self.variance), intensity, self.last_rough_state, self.factors)

    def total_implied_variance(self, log_moneyness: float, maturity: float, *, skew: float = -0.25,
                               curvature: float = 0.15, wing_slope_cap: float = 2.0) -> float:
        if not math.isfinite(log_moneyness) or not math.isfinite(maturity) or maturity <= 0:
            raise ValueError("log_moneyness must be finite and maturity > 0")
        if curvature < 0 or wing_slope_cap <= 0:
            raise ValueError("curvature must be non-negative and wing_slope_cap positive")
        # Bounded SVI-like wings: linear asymptotic slopes are constrained below Lee's limit.
        rho = math.tanh(skew)
        b = min(curvature * max(maturity, 1e-6) ** (self.hurst - 0.5), wing_slope_cap * 0.499 / (1.0 + abs(rho)))
        sigma = 0.15
        atm = self.variance * maturity
        w = atm + b * (rho * log_moneyness + math.sqrt(log_moneyness**2 + sigma**2) - sigma)
        return float(max(1e-12, w))

    def lee_wing_slope(self, *, skew: float = -0.25, curvature: float = 0.15, maturity: float = 1.0) -> float:
        rho = math.tanh(skew)
        b = min(curvature * max(maturity, 1e-6) ** (self.hurst - 0.5), 2.0 * 0.499 / (1.0 + abs(rho)))
        return float(b * (1.0 + abs(rho)))


class MultiAssetVolterraEngine:
    def __init__(self, assets: Sequence[str] = ASSETS, hurst: float = 0.07, seed: int = 440,
                 correlation: np.ndarray | None = None, factors: int = 12) -> None:
        self.assets = tuple(assets)
        if len(self.assets) < 2 or len(set(self.assets)) != len(self.assets):
            raise ValueError("assets must be unique and contain at least two assets")
        n = len(self.assets)
        corr = np.eye(n) if correlation is None else _finite_array(correlation, "correlation", 2)
        if corr.shape != (n, n) or not np.allclose(corr, corr.T, atol=1e-10):
            raise ValueError("correlation must be symmetric with shape (n_assets,n_assets)")
        if not np.allclose(np.diag(corr), 1.0, atol=1e-8):
            raise ValueError("correlation diagonal must equal one")
        if np.linalg.eigvalsh(corr).min() < -1e-9:
            raise ValueError("correlation matrix must be positive semidefinite")
        self.correlation = corr
        # A tiny diagonal jitter supports semidefinite (rather than positive definite) matrices.
        self.cholesky = np.linalg.cholesky(corr + np.eye(n) * 1e-12)
        self.rng = np.random.default_rng(seed)
        self.models = {name: RoughVolterraJumpDiffusion(name, hurst=hurst, factors=factors, seed=seed + i + 1) for i, name in enumerate(self.assets)}
        self.last_snapshots: dict[str, VolatilitySnapshot] = {k: VolatilitySnapshot(k, m.variance, math.sqrt(m.variance), m.base_jump_intensity, 0.0, m.factors) for k, m in self.models.items()}

    def update(self, dt: float, brownian_shocks: Sequence[float] | None = None,
               jump_counts: Sequence[int] | None = None) -> dict[str, VolatilitySnapshot]:
        n = len(self.assets)
        z = self.rng.normal(size=n) if brownian_shocks is None else _finite_array(brownian_shocks, "brownian_shocks").reshape(-1)
        if z.size != n:
            raise ValueError("brownian_shocks length must equal asset count")
        correlated = self.cholesky @ z
        counts = [None] * n if jump_counts is None else list(jump_counts)
        if len(counts) != n:
            raise ValueError("jump_counts length must equal asset count")
        snapshots = {}
        for i, name in enumerate(self.assets):
            snapshots[name] = self.models[name].update(dt, float(correlated[i]), counts[i])
        self.last_snapshots = snapshots
        return dict(snapshots)

    def covariance_matrix(self) -> np.ndarray:
        vols = np.array([math.sqrt(self.models[a].variance) for a in self.assets])
        cov = np.outer(vols, vols) * self.correlation
        cov = (cov + cov.T) * 0.5
        # Numerical round-off can create tiny negative eigenvalues; preserve PSD explicitly.
        eig, vec = np.linalg.eigh(cov)
        return vec @ np.diag(np.maximum(eig, 0.0)) @ vec.T

    def telemetry(self) -> dict[str, Any]:
        return {"assets": list(self.assets), "hurst": {a: self.models[a].hurst for a in self.assets},
                "variance": {a: self.models[a].variance for a in self.assets},
                "volterra_factors": {a: self.models[a].factors for a in self.assets},
                "covariance": self.covariance_matrix().tolist()}


class LiquidityContagionGraph:
    """Four-node directed contagion graph with nonnegative subcritical adjacency."""
    def __init__(self, adjacency: Sequence[Sequence[float]] | None = None, rho_max: float = 0.88,
                 nodes: Sequence[str] = ASSETS) -> None:
        self.nodes = tuple(nodes)
        n = len(self.nodes)
        if n < 2 or len(set(self.nodes)) != n:
            raise ValueError("nodes must be unique and contain at least two entries")
        if not (0 < rho_max < 1):
            raise ValueError("rho_max must be in (0,1)")
        default = np.array([[0, .22, .10, .08], [.19, 0, .18, .12], [.12, .13, 0, .10], [.07, .12, .09, 0]], dtype=float)
        raw = default if adjacency is None and n == 4 else (np.ones((n,n)) - np.eye(n)) * .05 if adjacency is None else _finite_array(adjacency, "adjacency", 2)
        if raw.shape != (n, n) or np.any(raw < 0):
            raise ValueError("adjacency must be nonnegative with shape (n,n)")
        self.rho_max = float(rho_max)
        rho = _spectral_radius(raw)
        self.shrink_factor = min(1.0, self.rho_max * (1 - 1e-9) / max(rho, 1e-15))
        self.adjacency = raw * self.shrink_factor
        self.rng_intensity = np.ones(n, dtype=float) * 0.15
        self.beta = 2.0
        self.excitation = np.zeros((n, n), dtype=float)
        self.intensities = self.rng_intensity.copy()
        self.last_events = np.zeros(n, dtype=float)

    @property
    def spectral_radius(self) -> float:
        return _spectral_radius(self.adjacency)

    def centralities(self) -> dict[str, dict[str, float]]:
        # A[i,j]: source j contributes to target i. Row sums absorb; column sums spill.
        absorption = np.sum(self.adjacency, axis=1)
        spillover = np.sum(self.adjacency, axis=0)
        absorption = absorption / max(float(absorption.max()), 1e-12)
        spillover = spillover / max(float(spillover.max()), 1e-12)
        return {node: {"absorption": float(absorption[i]), "spillover": float(spillover[i])} for i, node in enumerate(self.nodes)}

    def update(self, dt: float, events: Sequence[int] | None = None) -> np.ndarray:
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and >= 0")
        n = len(self.nodes)
        ev = np.zeros(n, dtype=float) if events is None else _finite_array(events, "events").reshape(-1)
        if ev.size != n or np.any(ev < 0) or np.any(np.abs(ev - np.round(ev)) > 1e-9):
            raise ValueError("events must be non-negative integer counts per node")
        self.excitation *= math.exp(-self.beta * dt)
        self.excitation += self.beta * self.adjacency * ev[np.newaxis, :]
        self.intensities = self.rng_intensity + self.excitation.sum(axis=1)
        self.last_events = ev.copy()
        return self.intensities.copy()

    def transmit_shock(self, source: Sequence[float]) -> np.ndarray:
        x = _finite_array(source, "source").reshape(-1)
        if x.size != len(self.nodes):
            raise ValueError("source length must equal node count")
        return self.adjacency @ x


@dataclass(frozen=True)
class DealerUnwindSnapshot:
    intensity: float
    hazard_probability: float
    inventory_depth_ratio: float
    quote_pullback: bool
    reason: str


class DealerInventoryUnwind:
    def __init__(self, lambda0: float = 0.05, beta: float = 2.0, pullback_threshold: float = 0.65,
                 max_exponent: float = 30.0) -> None:
        if lambda0 < 0 or beta < 0 or not (0 <= pullback_threshold <= 1) or max_exponent <= 0:
            raise ValueError("invalid dealer unwind parameters")
        self.lambda0 = float(lambda0)
        self.beta = float(beta)
        self.pullback_threshold = float(pullback_threshold)
        self.max_exponent = float(max_exponent)
        self.inventory = 0.0
        self.depth = 1.0
        self.last_snapshot = DealerUnwindSnapshot(self.lambda0, 0.0, 0.0, False, "NORMAL")

    def update(self, inventory: float, market_depth: float, horizon: float = 1.0,
               toxic_flow: bool = False) -> DealerUnwindSnapshot:
        if not all(math.isfinite(v) for v in (inventory, market_depth, horizon)) or market_depth <= 0 or horizon < 0:
            raise ValueError("inventory finite, depth > 0, horizon >= 0 required")
        self.inventory, self.depth = float(inventory), float(market_depth)
        ratio = abs(inventory) / market_depth
        intensity = self.lambda0 * _safe_exp(self.beta * ratio, self.max_exponent)
        probability = 1.0 - math.exp(-intensity * horizon)
        pullback = bool(toxic_flow or probability >= self.pullback_threshold)
        reason = "TOXIC_FLOW" if toxic_flow else ("UNWIND_HAZARD" if pullback else "NORMAL")
        self.last_snapshot = DealerUnwindSnapshot(float(intensity), float(probability), float(ratio), pullback, reason)
        return self.last_snapshot


@dataclass
class QueueOrder:
    order_id: str
    asset: str
    side: str
    level: int
    quantity: int
    ahead: int
    behind: int = 0
    active: bool = True


class L3QueueDepletion:
    def __init__(self, lambda_market: float = 4.0, cancel_hazard: float = 0.3,
                 adverse_threshold: float = 0.0) -> None:
        if lambda_market < 0 or cancel_hazard < 0 or not math.isfinite(lambda_market + cancel_hazard + adverse_threshold):
            raise ValueError("invalid queue parameters")
        self.lambda_market = float(lambda_market)
        self.cancel_hazard = float(cancel_hazard)
        self.adverse_threshold = float(adverse_threshold)
        self.orders: dict[str, QueueOrder] = {}
        self.pullback_events: list[dict[str, Any]] = []

    def register(self, order_id: str, asset: str, side: str, level: int, quantity: int,
                 ahead: int, behind: int = 0) -> QueueOrder:
        if not order_id or order_id in self.orders:
            raise ValueError("order_id must be non-empty and unique")
        if side not in ("BUY", "SELL") or level not in range(1, 6):
            raise ValueError("side must be BUY/SELL and level in 1..5")
        if any(int(x) != x or x < 0 for x in (quantity, ahead, behind)) or quantity <= 0:
            raise ValueError("quantity must be positive integer; ahead/behind non-negative integers")
        order = QueueOrder(order_id, asset, side, int(level), int(quantity), int(ahead), int(behind))
        self.orders[order_id] = order
        return order

    def fill_probability(self, ahead: int, tau: float, lambda_market: float | None = None,
                         cancel_hazard: float | None = None) -> float:
        if int(ahead) != ahead or ahead < 0 or not math.isfinite(tau) or tau < 0:
            raise ValueError("ahead must be integer >= 0 and tau >= 0")
        lam = self.lambda_market if lambda_market is None else float(lambda_market)
        haz = self.cancel_hazard if cancel_hazard is None else float(cancel_hazard)
        if not math.isfinite(lam) or not math.isfinite(haz) or lam < 0 or haz < 0:
            raise ValueError("arrival rate and cancellation hazard must be finite and >= 0")
        x = (lam + haz) * tau
        if x == 0:
            return 1.0 if ahead < 0 else 0.0
        # P(N >= ahead+1), using survival recurrence to avoid cancellation for small tails.
        p = math.exp(-min(x, 745.0))
        cdf = p
        for k in range(1, int(ahead) + 1):
            p *= x / k
            cdf += p
        return float(min(1.0, max(0.0, 1.0 - cdf)))

    def survival_probability(self, tau: float, cancel_hazard: float | None = None) -> float:
        haz = self.cancel_hazard if cancel_hazard is None else float(cancel_hazard)
        if not math.isfinite(tau) or tau < 0 or not math.isfinite(haz) or haz < 0:
            raise ValueError("tau and cancellation hazard must be finite and non-negative")
        return float(math.exp(-haz * tau))

    def process_trade(self, asset: str, side: str, quantity: int) -> list[str]:
        if side not in ("BUY", "SELL") or int(quantity) != quantity or quantity < 0:
            raise ValueError("invalid trade event")
        remaining = int(quantity)
        filled: list[str] = []
        candidates = sorted((o for o in self.orders.values() if o.active and o.asset == asset and o.side == side), key=lambda o: o.level)
        for order in candidates:
            if remaining <= 0:
                break
            used_ahead = min(order.ahead, remaining)
            order.ahead -= used_ahead
            remaining -= used_ahead
            if remaining > 0:
                own_fill = min(order.quantity, remaining)
                order.quantity -= own_fill
                remaining -= own_fill
                if own_fill:
                    filled.append(order.order_id)
                if order.quantity == 0:
                    order.active = False
        return filled

    def evaluate_toxicity(self, order_id: str, tau: float, expected_adverse_slippage: float,
                          round_trip_friction: float) -> dict[str, Any]:
        if order_id not in self.orders:
            raise KeyError(order_id)
        if any(not math.isfinite(v) or v < 0 for v in (tau, expected_adverse_slippage, round_trip_friction)):
            raise ValueError("tau, adverse slippage and friction must be finite and non-negative")
        order = self.orders[order_id]
        pfill = self.fill_probability(order.ahead, tau)
        pullback = pfill > 0.85 and expected_adverse_slippage > round_trip_friction
        if pullback:
            order.active = False
            self.pullback_events.append({"order_id": order_id, "reason": "ADVERSE_SELECTION_EXCEEDS_FRICTION", "p_fill": pfill})
        return {"order_id": order_id, "p_fill": pfill, "quote_pullback_immediate": bool(pullback),
                "adverse_slippage": float(expected_adverse_slippage), "round_trip_friction": float(round_trip_friction)}


@dataclass(frozen=True)
class FeeBreakdown:
    buy_turnover: float
    sell_turnover: float
    total_turnover: float
    stt: float
    stamp_duty: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    half_spread_slippage: float
    impact_hurdle: float
    total_friction: float
    net_alpha: float


@dataclass(frozen=True)
class OptionLeg:
    premium: float
    quantity: float
    side: str
    asset: str = "NIFTY 50"
    leg_id: str = "leg"
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0


class StatutoryCostCalculator:
    STT_SELL = 0.0015
    STAMP_BUY = 0.00003
    EXCHANGE_RATE = 3553.0 / 1e7
    SEBI_RATE = 10.0 / 1e7
    GST_RATE = 0.18
    BROKERAGE_PER_LEG = 20.0

    def __init__(self, brokerage_per_leg: float = 20.0) -> None:
        if not math.isfinite(brokerage_per_leg) or brokerage_per_leg < 0:
            raise ValueError("brokerage_per_leg must be finite and non-negative")
        self.brokerage_per_leg = float(brokerage_per_leg)

    def calculate(self, legs: Sequence[OptionLeg], gross_alpha: float = 0.0,
                  half_spread_slippage: float = 0.0, impact_hurdle: float = 0.0) -> FeeBreakdown:
        if not math.isfinite(gross_alpha) or not math.isfinite(half_spread_slippage) or not math.isfinite(impact_hurdle):
            raise ValueError("alpha and friction inputs must be finite")
        if half_spread_slippage < 0 or impact_hurdle < 0:
            raise ValueError("slippage and impact must be non-negative")
        buy = sell = 0.0
        for leg in legs:
            if not isinstance(leg, OptionLeg):
                raise TypeError("legs must contain OptionLeg values")
            if not math.isfinite(leg.premium) or not math.isfinite(leg.quantity) or leg.premium < 0 or leg.quantity < 0:
                raise ValueError("premium and quantity must be finite and non-negative")
            if leg.side not in ("BUY", "SELL"):
                raise ValueError("leg side must be BUY or SELL")
            if not all(math.isfinite(x) for x in (leg.delta, leg.gamma, leg.vega)):
                raise ValueError("leg Greeks must be finite")
            turnover = leg.premium * leg.quantity
            if leg.side == "BUY":
                buy += turnover
            else:
                sell += turnover
        total = buy + sell
        stt = sell * self.STT_SELL
        stamp = buy * self.STAMP_BUY
        exchange = total * self.EXCHANGE_RATE
        sebi = total * self.SEBI_RATE
        brokerage = len(legs) * self.brokerage_per_leg
        gst = self.GST_RATE * (brokerage + exchange + sebi)
        friction = stt + stamp + exchange + sebi + brokerage + gst + half_spread_slippage + impact_hurdle
        return FeeBreakdown(buy, sell, total, stt, stamp, exchange, sebi, brokerage, gst,
                            half_spread_slippage, impact_hurdle, float(friction), float(gross_alpha - friction))

    @staticmethod
    def profitable(gross_alpha: float, fees: FeeBreakdown) -> bool:
        if not math.isfinite(gross_alpha):
            raise ValueError("gross_alpha must be finite")
        return bool(gross_alpha > fees.total_friction)


@dataclass(frozen=True)
class ThrottleStatus:
    locked: bool
    reason: str
    cooldown_remaining: float
    trades_today: int
    daily_cap: int


class AntiTiltThrottler:
    def __init__(self, daily_cap: int = 15, base_cooldown: float = 900.0,
                 theta_vol: float = 1.0, sigma_baseline: float = 0.2,
                 loss_limit: int = 3, revenge_ratio: float = 1.25, min_fill_interval: float = 30.0) -> None:
        if daily_cap < 0 or base_cooldown < 0 or theta_vol < 0 or sigma_baseline <= 0 or loss_limit < 1 or revenge_ratio <= 1 or min_fill_interval < 0:
            raise ValueError("invalid throttler parameters")
        self.daily_cap = int(daily_cap)
        self.base_cooldown = float(base_cooldown)
        self.theta_vol = float(theta_vol)
        self.sigma_baseline = float(sigma_baseline)
        self.loss_limit = int(loss_limit)
        self.revenge_ratio = float(revenge_ratio)
        self.min_fill_interval = float(min_fill_interval)
        self.trades_today = 0
        self.consecutive_losses = 0
        self.last_fill_time: float | None = None
        self.last_size: float | None = None
        self.lock_until = 0.0
        self.lock_reason = ""

    def cooldown_seconds(self, sigma_rough: float) -> float:
        if not math.isfinite(sigma_rough) or sigma_rough < 0:
            raise ValueError("sigma_rough must be finite and non-negative")
        return self.base_cooldown * (1.0 + self.theta_vol * sigma_rough / self.sigma_baseline)

    def _lock(self, now: float, reason: str, sigma_rough: float = 0.0) -> None:
        self.lock_until = max(self.lock_until, now + self.cooldown_seconds(sigma_rough))
        self.lock_reason = reason

    def record_fill(self, now: float, size: float, pnl: float, sigma_rough: float) -> ThrottleStatus:
        if any(not math.isfinite(x) for x in (now, size, pnl, sigma_rough)) or size <= 0:
            raise ValueError("fill inputs must be finite and size > 0")
        reason = ""
        if self.last_fill_time is not None:
            interval = now - self.last_fill_time
            if interval < 0:
                raise ValueError("fill timestamps must be non-decreasing")
            if interval < self.min_fill_interval:
                reason = "RAPID_PACING"
            if self.last_size and size / self.last_size > self.revenge_ratio:
                reason = "REVENGE_SIZING"
        self.trades_today += 1
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        if self.consecutive_losses >= self.loss_limit:
            reason = "LOSS_STREAK"
        if self.trades_today >= self.daily_cap and self.daily_cap > 0:
            # Trade cap blocks subsequent entries; it does not by itself reset the loss state.
            self.lock_reason = self.lock_reason or "DAILY_CAP"
        if reason:
            self._lock(now, reason, sigma_rough)
        self.last_fill_time, self.last_size = now, size
        return self.status(now)

    def status(self, now: float) -> ThrottleStatus:
        if not math.isfinite(now):
            raise ValueError("now must be finite")
        remaining = max(0.0, self.lock_until - now)
        daily_locked = self.daily_cap > 0 and self.trades_today >= self.daily_cap
        if remaining <= 0 and self.lock_reason not in ("DAILY_CAP",):
            reason = ""
            locked = daily_locked
        else:
            reason = self.lock_reason if remaining > 0 or self.lock_reason == "DAILY_CAP" else ""
            locked = remaining > 0 or daily_locked
        return ThrottleStatus(bool(locked), reason or ("DAILY_CAP" if daily_locked else "NORMAL"), remaining, self.trades_today, self.daily_cap)

    def can_enter(self, now: float) -> bool:
        return not self.status(now).locked


@dataclass(frozen=True)
class SquadDecision:
    approved: bool
    vetoes: tuple[str, ...]
    votes: Mapping[str, bool]
    reason: str


class TradingSquadConsensus:
    """Deterministic four-role review; Manager Abhi owns the binding veto."""
    def evaluate(self, *, live: bool, capital_required: float, available_capital: float,
                 net_alpha: float, toxicity: bool, volatility_stress: bool,
                 hedge_feasible: bool = True) -> SquadDecision:
        values = (capital_required, available_capital, net_alpha)
        if any(not math.isfinite(v) for v in values) or capital_required < 0 or available_capital < 0:
            raise ValueError("invalid capital/alpha values")
        votes = {
            "Manager Abhi": not live and capital_required <= available_capital,
            "Alex": not toxicity,
            "Emily": not volatility_stress,
            "Max": net_alpha > 0 and hedge_feasible,
        }
        vetoes = tuple(name for name, vote in votes.items() if not vote)
        approved = len(vetoes) == 0
        reason = "APPROVED_PAPER_ONLY" if approved else ("MANAGER_ABHI_VETO_LIVE" if live else "VETO:" + ",".join(vetoes))
        return SquadDecision(approved, vetoes, votes, reason)


class NeuralDeepHedger:
    """Small NumPy MLP that learns a hedge proposal from offline targets.

    This network is a research policy; a constrained optimizer must still validate Greeks.
    """
    def __init__(self, state_dim: int = 12, hidden_dim: int = 24, action_dim: int = 8,
                 seed: int = 440) -> None:
        if state_dim < 1 or hidden_dim < 1 or action_dim < 1:
            raise ValueError("network dimensions must be positive")
        self.state_dim, self.hidden_dim, self.action_dim = int(state_dim), int(hidden_dim), int(action_dim)
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0.0, math.sqrt(2.0 / state_dim), (state_dim, hidden_dim))
        self.b1 = np.zeros(hidden_dim)
        self.W2 = rng.normal(0.0, math.sqrt(1.0 / hidden_dim), (hidden_dim, action_dim))
        self.b2 = np.zeros(action_dim)
        self.loss_history: list[float] = []

    def predict(self, states: Sequence[float] | np.ndarray) -> np.ndarray:
        x = _finite_array(states, "states")
        single = x.ndim == 1
        if single:
            x = x.reshape(1, -1)
        if x.ndim != 2 or x.shape[1] != self.state_dim:
            raise ValueError("states have incorrect shape")
        hidden = np.tanh(x @ self.W1 + self.b1)
        out = hidden @ self.W2 + self.b2
        return out[0] if single else out

    def fit(self, states: np.ndarray, targets: np.ndarray, epochs: int = 20,
            learning_rate: float = 1e-2) -> list[float]:
        x = _finite_array(states, "states", 2)
        y = _finite_array(targets, "targets", 2)
        if x.shape[1] != self.state_dim or y.shape != (x.shape[0], self.action_dim) or x.shape[0] < 1:
            raise ValueError("training arrays have incompatible shapes")
        if epochs < 1 or not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("epochs and learning_rate must be positive")
        self.loss_history = []
        for _ in range(epochs):
            z1 = x @ self.W1 + self.b1
            h = np.tanh(z1)
            pred = h @ self.W2 + self.b2
            err = pred - y
            loss = float(np.mean(err * err))
            self.loss_history.append(loss)
            d_out = 2.0 * err / err.size
            gW2 = h.T @ d_out
            gb2 = np.sum(d_out, axis=0)
            d_h = d_out @ self.W2.T
            d_z1 = d_h * (1.0 - h * h)
            gW1 = x.T @ d_z1
            gb1 = np.sum(d_z1, axis=0)
            # Gradient clipping prevents pathological offline batches from exploding weights.
            norm = math.sqrt(sum(float(np.sum(g * g)) for g in (gW1, gb1, gW2, gb2)))
            scale = min(1.0, 5.0 / max(norm, 1e-12))
            self.W1 -= learning_rate * scale * gW1
            self.b1 -= learning_rate * scale * gb1
            self.W2 -= learning_rate * scale * gW2
            self.b2 -= learning_rate * scale * gb2
        return list(self.loss_history)


@dataclass(frozen=True)
class HedgeResult:
    weights: tuple[float, ...]
    delta_net: float
    gamma_net: float
    vega_net: float
    objective: float
    feasible: bool
    optimizer_success: bool
    message: str


class GreekNeutralHedgeOptimizer:
    """L1-cost and liquidity-vacuum regularized Greek-neutral hedge optimizer."""
    def __init__(self, delta_tolerance: float = 1e-4, gamma_tolerance: float = 1e-3,
                 vega_tolerance: float = 1.0, transaction_cost_weight: float = 0.02,
                 vacuum_weight: float = 0.1, max_iterations: int = 500) -> None:
        if min(delta_tolerance, gamma_tolerance, vega_tolerance) <= 0 or transaction_cost_weight < 0 or vacuum_weight < 0 or max_iterations < 1:
            raise ValueError("invalid hedge optimizer parameters")
        self.tols = np.array([delta_tolerance, gamma_tolerance, vega_tolerance], dtype=float)
        self.transaction_cost_weight = float(transaction_cost_weight)
        self.vacuum_weight = float(vacuum_weight)
        self.max_iterations = int(max_iterations)

    def optimize(self, greeks: Sequence[Sequence[float]], preferred_weights: Sequence[float],
                 depths: Sequence[float], spreads: Sequence[float],
                 bounds: Sequence[tuple[float, float]] | None = None) -> HedgeResult:
        G = _finite_array(greeks, "greeks", 2)
        target = _finite_array(preferred_weights, "preferred_weights").reshape(-1)
        depth = _finite_array(depths, "depths").reshape(-1)
        spread = _finite_array(spreads, "spreads").reshape(-1)
        if G.shape[0] != 3 or G.shape[1] != target.size or depth.size != target.size or spread.size != target.size or target.size < 1:
            raise ValueError("greeks must be 3 x n and all vectors must have length n")
        if np.any(depth < 0) or np.any(spread < 0):
            raise ValueError("depth and spread must be non-negative")
        bnds = [(-5.0, 5.0)] * target.size if bounds is None else list(bounds)
        if len(bnds) != target.size or any(not (math.isfinite(lo) and math.isfinite(hi) and lo <= hi) for lo, hi in bnds):
            raise ValueError("bounds must contain n finite (lower,upper) pairs")
        if any(not (lo <= 0 <= hi) for lo, hi in bnds):
            zero_feasible = False
        else:
            zero_feasible = True
        eps = 1e-9
        vacuum = 1.0 / (depth + eps)
        def objective(w: np.ndarray) -> float:
            tracking = 0.5 * float(np.sum((w - target) ** 2))
            l1 = self.transaction_cost_weight * float(np.dot(spread, np.sqrt(w*w + 1e-10)))
            vac = 0.5 * self.vacuum_weight * float(np.dot(vacuum, w*w))
            return tracking + l1 + vac
        def constraints(w: np.ndarray) -> np.ndarray:
            g = G @ w
            return self.tols - np.abs(g)
        initial = np.clip(np.zeros_like(target), [b[0] for b in bnds], [b[1] for b in bnds])
        if zero_feasible:
            initial = np.zeros_like(target)
        result = minimize(objective, initial, method="SLSQP", bounds=bnds,
                          constraints=[{"type": "ineq", "fun": constraints}],
                          options={"maxiter": self.max_iterations, "ftol": 1e-12, "disp": False})
        w = np.asarray(result.x if result.x is not None else initial, dtype=float)
        greek_net = G @ w
        feasible = bool(np.all(np.abs(greek_net) <= self.tols + 1e-7) and np.all(w >= np.array([b[0] for b in bnds]) - 1e-7) and np.all(w <= np.array([b[1] for b in bnds]) + 1e-7))
        if not feasible and zero_feasible:
            # Fail closed to a known neutral solution; do not report optimizer success as neutrality.
            w = np.zeros_like(target)
            greek_net = G @ w
            feasible = True
            message = "optimizer failed constraints; fallback to zero-trade neutral weights"
        else:
            message = str(result.message)
        return HedgeResult(tuple(float(v) for v in w), float(greek_net[0]), float(greek_net[1]), float(greek_net[2]),
                           float(objective(w)), feasible, bool(result.success), message)


@dataclass(frozen=True)
class CandidateEvaluation:
    accepted: bool
    gross_alpha: float
    net_alpha: float
    costs: FeeBreakdown
    squad: SquadDecision
    reason: str


class Cycle44ExecutionEngine:
    def __init__(self, seed: int = 440, capital: float = INITIAL_PAPER_CAPITAL) -> None:
        if not math.isfinite(capital) or capital <= 0:
            raise ValueError("capital must be finite and positive")
        self.capital = float(capital)
        self.cash = float(capital)
        self.ledger_epoch = PAPER_LEDGER_EPOCH
        self.volterra = MultiAssetVolterraEngine(seed=seed)
        self.dealer_unwind = DealerInventoryUnwind()
        self.queue = L3QueueDepletion()
        self.fees = StatutoryCostCalculator()
        self.throttler = AntiTiltThrottler()
        self.deep_hedger = NeuralDeepHedger(seed=seed)
        self.hedge_optimizer = GreekNeutralHedgeOptimizer()
        self.squad = TradingSquadConsensus()
        self.risk_state = RiskState.NORMAL
        self.last_candidate: CandidateEvaluation | None = None
        self.last_hedge: HedgeResult | None = None
        self.last_inventory: dict[str, float] = {asset: 0.0 for asset in ASSETS}
        self.live_order_dispatch_enabled = False
        self.real_broker_fills_locked = True
        self.audit_log: list[dict[str, Any]] = []

    def evaluate_candidate(self, gross_alpha: float, legs: Sequence[OptionLeg], *, slippage: float = 0.0,
                           impact: float = 0.0, capital_required: float = 0.0, live: bool = False,
                           toxicity: bool = False, volatility_stress: bool = False,
                           hedge_feasible: bool = True, now: float | None = None) -> CandidateEvaluation:
        current = time.time() if now is None else float(now)
        costs = self.fees.calculate(legs, gross_alpha, slippage, impact)
        throttle_ok = self.throttler.can_enter(current)
        net_positive = gross_alpha > costs.total_friction
        # `live=True` is a binding Manager Abhi veto, regardless of all other inputs.
        squad = self.squad.evaluate(live=live, capital_required=capital_required,
                                    available_capital=self.cash, net_alpha=costs.net_alpha,
                                    toxicity=toxicity, volatility_stress=volatility_stress,
                                    hedge_feasible=hedge_feasible)
        accepted = bool(net_positive and throttle_ok and squad.approved and self.risk_state != RiskState.EMERGENCY_UNWIND and not live)
        reason = "APPROVED_PAPER_ONLY" if accepted else ("LIVE_VETO" if live else ("NET_ALPHA_NOT_POSITIVE" if not net_positive else ("THROTTLED" if not throttle_ok else ("EMERGENCY_UNWIND" if self.risk_state == RiskState.EMERGENCY_UNWIND else squad.reason))))
        result = CandidateEvaluation(accepted, float(gross_alpha), float(costs.net_alpha), costs, squad, reason)
        self.last_candidate = result
        self.audit_log.append({"event": "candidate_evaluation", "accepted": accepted, "reason": reason, "net_alpha": result.net_alpha, "live_requested": bool(live)})
        return result

    def optimize_hedge(self, greeks: Sequence[Sequence[float]], preferred_weights: Sequence[float],
                       depths: Sequence[float], spreads: Sequence[float], bounds: Sequence[tuple[float, float]] | None = None) -> HedgeResult:
        result = self.hedge_optimizer.optimize(greeks, preferred_weights, depths, spreads, bounds)
        self.last_hedge = result
        self.audit_log.append({"event": "hedge_optimization", "feasible": result.feasible, "greeks": [result.delta_net, result.gamma_net, result.vega_net]})
        return result

    def paper_fill(self, now: float, size: float, pnl: float, sigma_rough: float) -> dict[str, Any]:
        if size <= 0 or not all(math.isfinite(v) for v in (now, size, pnl, sigma_rough)):
            raise ValueError("invalid paper fill")
        if size > self.cash + 1e-9:
            raise PermissionError("paper capital gate rejected fill")
        status = self.throttler.record_fill(now, size, pnl, sigma_rough)
        self.cash = max(0.0, self.cash + pnl)
        if status.locked:
            self.risk_state = RiskState.CAUTION
        self.audit_log.append({"event": "paper_fill", "size": size, "pnl": pnl, "cash": self.cash, "lock_reason": status.reason})
        return {"cash": self.cash, "throttle": asdict(status), "risk_state": self.risk_state.value}

    def dispatch_live_order(self, *args: Any, **kwargs: Any) -> None:
        raise PermissionError("live broker dispatch is permanently disabled in Cycle 44 paper mode")

    def telemetry(self, now: datetime | None = None) -> dict[str, Any]:
        current_epoch = time.time() if now is None else now.timestamp()
        throttle = self.throttler.status(current_epoch)
        return {**timestamp_payload(now), "cycle": 44, "risk_state": self.risk_state.value,
                "paper_ledger_epoch": self.ledger_epoch, "initial_capital": self.capital, "cash": self.cash,
                "live_order_dispatch_enabled": False, "real_broker_fills_locked": True,
                "volterra": self.volterra.telemetry(), "liquidity_contagion": self._contagion_telem,
                "dealer_unwind": asdict(self.dealer_unwind.last_snapshot),
                "queue_orders": {key: asdict(order) for key, order in self.queue.orders.items()},
                "last_hedge": None if self.last_hedge is None else asdict(self.last_hedge),
                "last_candidate": None if self.last_candidate is None else self._candidate_json(self.last_candidate),
                "throttle": asdict(throttle), "audit_events": len(self.audit_log)}

    @property
    def _contagion_telem(self) -> dict[str, Any]:
        # Lazy default graph kept separate from the Volterra covariance graph.
        if not hasattr(self, "contagion"):
            self.contagion = LiquidityContagionGraph()
        return {"nodes": list(self.contagion.nodes), "adjacency": self.contagion.adjacency.tolist(),
                "spectral_radius": self.contagion.spectral_radius, "centralities": self.contagion.centralities(),
                "intensities": self.contagion.intensities.tolist()}

    @staticmethod
    def _candidate_json(c: CandidateEvaluation) -> dict[str, Any]:
        return {"accepted": c.accepted, "gross_alpha": c.gross_alpha, "net_alpha": c.net_alpha,
                "costs": asdict(c.costs), "squad": {"approved": c.squad.approved, "vetoes": list(c.squad.vetoes),
                "votes": dict(c.squad.votes), "reason": c.squad.reason}, "reason": c.reason}

    def snapshot_after_tick(self, dt: float, shocks: Sequence[float] | None = None,
                            event_counts: Sequence[int] | None = None) -> dict[str, Any]:
        self.volterra.update(dt, shocks, event_counts)
        if not hasattr(self, "contagion"):
            self.contagion = LiquidityContagionGraph()
        self.contagion.update(dt, event_counts)
        return self.telemetry()


def make_dashboard_server(engine: Cycle44ExecutionEngine, host: str = "127.0.0.1", port: int = 8088) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, fmt: str, *args: Any) -> None:
            return
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self) -> None:
            if self.path == "/health":
                body = json.dumps({"ok": True, "cycle": 44, "live_order_dispatch_enabled": False,
                                   "real_broker_fills_locked": True, "risk_state": engine.risk_state.value}, allow_nan=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            elif self.path == "/telemetry":
                body = json.dumps(engine.telemetry(), allow_nan=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            elif self.path == "/events":
                payload = json.dumps(engine.telemetry(), allow_nan=False, separators=(",", ":"))
                body = ("retry: 1000\n" + "event: telemetry\n" + "data: " + payload + "\n\n").encode()
                self._send(200, body, "text/event-stream; charset=utf-8")
            else:
                self._send(404, b'{"error":"not found"}', "application/json; charset=utf-8")
    return ThreadingHTTPServer((host, port), Handler)
