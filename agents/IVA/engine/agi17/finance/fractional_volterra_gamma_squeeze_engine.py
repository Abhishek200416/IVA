"""Cycle 43: cross-asset rough Volterra, dealer gamma-squeeze and MLOFI engine.

Offline research and paper simulation only. This module intentionally provides no
broker adapter or live execution capability.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable, Mapping, Sequence
import json
import math
import threading
import time
import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
PAPER_INITIAL_CAPITAL = 10_000.0
ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
MLOFI_WEIGHTS = np.array([1.0, 0.8, 0.6, 0.4, 0.2], dtype=float)


def _finite_array(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _spectral_radius(matrix: np.ndarray) -> float:
    if matrix.size == 0:
        return 0.0
    return float(np.max(np.abs(np.linalg.eigvals(matrix))))


def _ist_timestamp(epoch: float | None = None) -> str:
    dt = datetime.fromtimestamp(time.time() if epoch is None else epoch, tz=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Mapping):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


@dataclass(frozen=True)
class VolterraKernel:
    """Positive sum-of-exponentials approximation of t^(H-1/2)/Gamma(H+1/2).

    A geometrically spaced quadrature is built from the Laplace-transform
    representation. It is fast O(M) to evaluate/update but is an approximation,
    not a claimed globally optimal fit.
    """
    hurst: float = 0.07
    n_factors: int = 12
    t_min: float = 1e-4
    t_max: float = 10.0
    rates: np.ndarray = field(init=False, repr=False)
    weights: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not (0.05 < self.hurst < 0.45):
            raise ValueError("hurst must be in (0.05, 0.45)")
        if self.n_factors < 8:
            raise ValueError("n_factors must be >= 8")
        if not (math.isfinite(self.t_min) and math.isfinite(self.t_max) and 0 < self.t_min < self.t_max):
            raise ValueError("require 0 < t_min < t_max")
        rates = np.geomspace(1.0 / self.t_max, 1.0 / self.t_min, self.n_factors)
        # For p=H+1/2, t^(p-1)/Gamma(p) = C integral x^(-p)e^(-tx) dx.
        p = self.hurst + 0.5
        edges = np.empty(self.n_factors + 1, dtype=float)
        edges[1:-1] = np.sqrt(rates[:-1] * rates[1:])
        edges[0] = rates[0] / math.sqrt(rates[1] / rates[0])
        edges[-1] = rates[-1] * math.sqrt(rates[-1] / rates[-2])
        constant = 1.0 / (math.gamma(p) * math.gamma(1.0 - p))
        weights = constant * (edges[1:] ** (1.0 - p) - edges[:-1] ** (1.0 - p)) / (1.0 - p)
        if np.any(weights <= 0) or not np.all(np.isfinite(weights)):
            raise ArithmeticError("kernel quadrature produced invalid weights")
        object.__setattr__(self, "rates", rates)
        object.__setattr__(self, "weights", weights)

    def exact(self, t: float) -> float:
        if not math.isfinite(t) or t <= 0:
            raise ValueError("t must be finite and positive")
        return t ** (self.hurst - 0.5) / math.gamma(self.hurst + 0.5)

    def evaluate(self, t: float) -> float:
        if not math.isfinite(t) or t < 0:
            raise ValueError("t must be finite and nonnegative")
        return float(self.weights @ np.exp(-self.rates * t))

    def relative_error(self, t: float) -> float:
        exact = self.exact(t)
        return abs(self.evaluate(t) - exact) / max(abs(exact), 1e-15)

    @property
    def memory_half_life(self) -> float:
        return math.log(2.0) / float(self.rates[0])


@dataclass
class RoughVolterraCovariance:
    """Four-asset positive-semidefinite covariance state driven by a Cholesky lift."""
    hurst: Sequence[float] = (0.07, 0.08, 0.09, 0.10)
    base_variance: Sequence[float] = (0.04, 0.06, 0.05, 0.055)
    eta: Sequence[float] = (1.2, 1.1, 1.0, 1.05)
    correlation: np.ndarray = field(default_factory=lambda: np.array([
        [1.0, .62, .50, .43], [.62, 1.0, .57, .45], [.50, .57, 1.0, .52], [.43, .45, .52, 1.0]
    ], dtype=float))
    n_factors: int = 12
    kernel_min: float = 1e-4
    kernel_max: float = 10.0
    log_variance_clip: float = 12.0
    kernels: list[VolterraKernel] = field(init=False)
    corr_cholesky: np.ndarray = field(init=False, repr=False)
    factor_state: np.ndarray = field(init=False, repr=False)
    instantaneous_variance: np.ndarray = field(init=False)
    elapsed: float = 0.0

    def __post_init__(self) -> None:
        hs = _finite_array(self.hurst, "hurst", 1)
        base = _finite_array(self.base_variance, "base_variance", 1)
        eta = _finite_array(self.eta, "eta", 1)
        if any(len(x) != 4 for x in (hs, base, eta)):
            raise ValueError("hurst, base_variance, eta must each have four values")
        if not math.isfinite(self.log_variance_clip) or self.log_variance_clip <= 0:
            raise ValueError("log_variance_clip must be finite and positive")
        if np.any((hs <= .05) | (hs >= .45)) or np.any(base <= 0) or np.any(eta < 0):
            raise ValueError("invalid rough covariance parameters")
        corr = _finite_array(self.correlation, "correlation", 2)
        if corr.shape != (4, 4) or not np.allclose(corr, corr.T, atol=1e-10):
            raise ValueError("correlation must be symmetric 4x4")
        if not np.allclose(np.diag(corr), 1.0, atol=1e-6):
            raise ValueError("correlation diagonal must equal one")
        eig = np.linalg.eigvalsh(corr)
        if eig.min() < -1e-9:
            raise ValueError("correlation must be positive semidefinite")
        # Small diagonal jitter permits numerically semidefinite user matrices.
        chol = np.linalg.cholesky(corr + np.eye(4) * max(1e-12, -float(eig.min()) + 1e-12))
        kernels = [VolterraKernel(float(h), self.n_factors, self.kernel_min, self.kernel_max) for h in hs]
        object.__setattr__(self, "hurst", hs)
        object.__setattr__(self, "base_variance", base)
        object.__setattr__(self, "eta", eta)
        object.__setattr__(self, "correlation", corr)
        object.__setattr__(self, "corr_cholesky", chol)
        object.__setattr__(self, "kernels", kernels)
        object.__setattr__(self, "factor_state", np.zeros((4, self.n_factors), dtype=float))
        object.__setattr__(self, "instantaneous_variance", base.copy())

    def update(self, dt: float, shocks: Sequence[float]) -> np.ndarray:
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("dt must be finite and positive")
        z = _finite_array(shocks, "shocks", 1)
        if z.shape != (4,):
            raise ValueError("shocks must contain four values")
        corr_shocks = self.corr_cholesky @ z
        state = self.factor_state.copy()
        for i, kernel in enumerate(self.kernels):
            decay = np.exp(-kernel.rates * dt)
            innovation_scale = np.sqrt(np.maximum(0.0, 1.0 - decay * decay))
            state[i] = state[i] * decay + corr_shocks[i] * innovation_scale
        # Normalize factor weights to avoid making variance scale depend on M.
        rough_driver = np.array([float(k.weights @ state[i]) / max(float(k.weights.sum()), 1e-12) for i, k in enumerate(self.kernels)])
        tpow = np.array([dt ** (2.0 * h) for h in self.hurst])
        log_mult = np.clip(self.eta * rough_driver - 0.5 * self.eta ** 2 * tpow, -self.log_variance_clip, self.log_variance_clip)
        var = self.base_variance * np.exp(log_mult)
        if not np.all(np.isfinite(var)) or np.any(var <= 0):
            raise ArithmeticError("variance update failed positivity/finite invariant")
        self.factor_state = state
        self.instantaneous_variance = var
        self.elapsed += dt
        cov = np.diag(np.sqrt(var)) @ self.correlation @ np.diag(np.sqrt(var))
        cov = (cov + cov.T) * .5
        if np.linalg.eigvalsh(cov).min() < -1e-9:
            raise ArithmeticError("covariance lost positive semidefiniteness")
        return cov

    def covariance(self) -> np.ndarray:
        std = np.sqrt(self.instantaneous_variance)
        out = np.diag(std) @ self.correlation @ np.diag(std)
        return (out + out.T) * .5

    def surface_total_variance(self, asset: int, k: float, tau: float, *, skew: float = 0.0,
                               curvature: float = 0.15, lee_beta: float = 2.0,
                               enforce_wing_bound: bool = True) -> float:
        if not 0 <= asset < 4 or not math.isfinite(k) or not math.isfinite(tau) or tau <= 0:
            raise ValueError("invalid asset/log-moneyness/tenor")
        if not math.isfinite(skew) or not math.isfinite(curvature) or curvature < 0 or lee_beta <= 0:
            raise ValueError("invalid smile parameters")
        atm = float(self.instantaneous_variance[asset]) * tau
        shape = 1.0 + skew * math.tanh(k) + curvature * k * k / (1.0 + k * k)
        w = max(atm * 1e-8, atm * shape)
        # Lee's bound is asymptotic; apply only to far wings, not at ATM.
        if enforce_wing_bound and abs(k) >= 2.0:
            w = min(w, lee_beta * abs(k))
        return float(w)

    def validate_lee_wing(self, asset: int, k: float, tau: float, **kwargs: Any) -> bool:
        w = self.surface_total_variance(asset, k, tau, **kwargs)
        beta = float(kwargs.get("lee_beta", 2.0))
        return True if abs(k) < 2.0 else w <= beta * abs(k) + 1e-12


@dataclass
class HawkesSpilloverGraph:
    """Four-node directed nonnegative Hawkes graph with rho(Gamma)<max_radius."""
    baseline: Sequence[float] = (0.5, 0.6, 0.35, 0.3)
    alpha: np.ndarray = field(default_factory=lambda: np.array([
        [0.08, .04, .03, .02], [.05, .08, .04, .02], [.03, .04, .07, .02], [.02, .03, .02, .06]
    ], dtype=float))
    beta: Sequence[float] = (1.5, 1.4, 1.7, 1.8)
    max_radius: float = 0.88
    intensity: np.ndarray = field(init=False)
    excitation_state: np.ndarray = field(init=False, repr=False)
    contraction_factor: float = field(init=False, default=1.0)

    def __post_init__(self) -> None:
        mu = _finite_array(self.baseline, "baseline", 1)
        alpha = _finite_array(self.alpha, "alpha", 2)
        beta = _finite_array(self.beta, "beta", 1)
        if mu.shape != (4,) or beta.shape != (4,) or alpha.shape != (4, 4):
            raise ValueError("Hawkes graph must be 4x4 with four baseline and beta values")
        if np.any(mu <= 0) or np.any(beta <= 0) or np.any(alpha < 0):
            raise ValueError("baseline/beta must be positive; alpha nonnegative")
        if not 0 < self.max_radius < 1:
            raise ValueError("max_radius must be in (0,1)")
        # Gamma_ij = alpha_ij / beta_j (source-specific decay).
        branching = alpha / beta[np.newaxis, :]
        radius = _spectral_radius(branching)
        target = self.max_radius * (1.0 - 1e-6)
        factor = min(1.0, target / radius) if radius > 0 else 1.0
        alpha = alpha * factor
        object.__setattr__(self, "baseline", mu)
        object.__setattr__(self, "beta", beta)
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "intensity", mu.copy())
        object.__setattr__(self, "excitation_state", np.zeros(4, dtype=float))
        object.__setattr__(self, "contraction_factor", factor)

    @property
    def branching_matrix(self) -> np.ndarray:
        return self.alpha / np.asarray(self.beta)[np.newaxis, :]

    @property
    def spectral_radius(self) -> float:
        return _spectral_radius(self.branching_matrix)

    def update(self, dt: float, events: Sequence[float] = (0, 0, 0, 0)) -> np.ndarray:
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        ev = _finite_array(events, "events", 1)
        if ev.shape != (4,) or np.any(ev < 0):
            raise ValueError("events must be four nonnegative counts")
        decayed = self.excitation_state * np.exp(-np.asarray(self.beta) * dt)
        # State is per source; events in source j excite target i via alpha[i,j].
        self.excitation_state = decayed + ev
        self.intensity = np.asarray(self.baseline) + self.alpha @ self.excitation_state
        if not np.all(np.isfinite(self.intensity)) or np.any(self.intensity <= 0):
            raise ArithmeticError("invalid Hawkes intensity")
        return self.intensity.copy()

    def add_events(self, events: Sequence[float]) -> np.ndarray:
        return self.update(0.0, events)

    def centralities(self) -> dict[str, list[float]]:
        g = self.branching_matrix
        incoming = g.sum(axis=1)
        outgoing = g.sum(axis=0)
        scale_in = incoming / max(float(incoming.max()), 1e-12)
        scale_out = outgoing / max(float(outgoing.max()), 1e-12)
        return {"in_degree_absorption": scale_in.tolist(), "out_degree_spillover": scale_out.tolist()}

    def leadership_matrix(self) -> np.ndarray:
        g = self.branching_matrix
        out = np.zeros_like(g)
        for i in range(4):
            for j in range(4):
                if i == j:
                    out[i, j] = 0.0
                else:
                    denom = abs(g[i, j]) + abs(g[j, i]) + 1e-12
                    out[i, j] = float(np.clip((g[i, j] - g[j, i]) / denom, -1, 1))
        return out


@dataclass
class MultiLevelOFI:
    assets: tuple[str, ...] = ASSETS
    weights: np.ndarray = field(default_factory=lambda: MLOFI_WEIGHTS.copy())
    values: np.ndarray = field(init=False)
    raw_levels: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.assets) != 4 or len(set(self.assets)) != 4:
            raise ValueError("exactly four unique assets required")
        self.weights = _finite_array(self.weights, "weights", 1)
        if self.weights.shape != (5,) or np.any(self.weights < 0):
            raise ValueError("weights must be five nonnegative numbers")
        self.values = np.zeros(4, dtype=float)

    def update(self, asset: str, bid_delta: Sequence[float], ask_delta: Sequence[float]) -> float:
        if asset not in self.assets:
            raise KeyError(asset)
        bid = _finite_array(bid_delta, "bid_delta", 1)
        ask = _finite_array(ask_delta, "ask_delta", 1)
        if bid.shape != (5,) or ask.shape != (5,):
            raise ValueError("bid/ask depth deltas must have five levels")
        val = float(self.weights @ (bid - ask))
        idx = self.assets.index(asset)
        self.values[idx] = val
        self.raw_levels[asset] = {"bid_delta": bid.tolist(), "ask_delta": ask.tolist()}
        return val

    def normalized(self, scale: float = 1.0) -> np.ndarray:
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("scale must be finite and positive")
        return np.tanh(self.values / scale)


@dataclass
class DealerGammaSqueezeTopology:
    lambda0: float = 0.2
    kappa: float = 0.8
    hazard_threshold: float = 2.0
    min_depth: float = 1.0
    clusters: dict[str, dict[float, float]] = field(default_factory=dict)
    last_hazards: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        params = (self.lambda0, self.kappa, self.hazard_threshold, self.min_depth)
        if not all(math.isfinite(x) for x in params) or self.lambda0 <= 0 or self.kappa < 0 or self.hazard_threshold <= 0 or self.min_depth <= 0:
            raise ValueError("invalid gamma squeeze parameters")

    def update(self, asset: str, strike_gex: Mapping[float, float], depth: float,
               *, toxic_cascade: bool = False) -> dict[str, Any]:
        if not asset or not math.isfinite(depth) or depth < 0:
            raise ValueError("asset and nonnegative finite depth required")
        entries = {float(k): float(v) for k, v in strike_gex.items()}
        if not entries or not all(math.isfinite(k) and math.isfinite(v) for k, v in entries.items()):
            raise ValueError("strike GEX map must be nonempty and finite")
        dominant = max(entries, key=lambda k: abs(entries[k]))
        net_gex = sum(entries.values())
        gross_gex = sum(abs(v) for v in entries.values())
        denom = max(depth, self.min_depth)
        # Gross strike-cluster exposure avoids false calm when opposing strikes net out.
        squeeze_exposure = max(abs(net_gex), gross_gex)
        exponent = min(40.0, self.kappa * squeeze_exposure / denom)
        hazard = self.lambda0 * math.exp(exponent)
        self.clusters[asset] = entries
        self.last_hazards[asset] = hazard
        retreat = bool(toxic_cascade or hazard >= self.hazard_threshold)
        return {"asset": asset, "dominant_strike": dominant, "net_gex": net_gex,
                "gross_gex": gross_gex, "squeeze_exposure": squeeze_exposure,
                "depth": depth, "squeeze_hazard": hazard,
                "quote_retreat_immediate": retreat,
                "reason": "toxic_cascade" if toxic_cascade else ("gamma_squeeze" if retreat else "normal")}


@dataclass
class OptionLeg:
    symbol: str
    premium: float
    quantity: float
    side: str
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    expiry: str = "near_week"
    expected_alpha: float = 0.0
    half_spread_per_unit: float = 0.0
    impact_per_unit: float = 0.0

    def validate(self) -> None:
        if not self.symbol or self.side not in {"BUY", "SELL"}:
            raise ValueError("symbol required and side must be BUY or SELL")
        nums = (self.premium, self.quantity, self.delta, self.gamma, self.vega, self.expected_alpha,
                self.half_spread_per_unit, self.impact_per_unit)
        if not all(math.isfinite(float(x)) for x in nums):
            raise ValueError("leg values must be finite")
        if self.premium < 0 or self.quantity < 0 or self.half_spread_per_unit < 0 or self.impact_per_unit < 0:
            raise ValueError("premium, quantity, slippage and impact must be nonnegative")


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
    slippage: float
    impact: float
    total_friction: float


@dataclass(frozen=True)
class CostConfig:
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    exchange_rate: float = 3553.0 / 10_000_000.0
    sebi_rate: float = 10.0 / 10_000_000.0
    gst_rate: float = 0.18
    brokerage_per_leg: float = 20.0

    def __post_init__(self) -> None:
        rates = (self.stt_sell_rate, self.stamp_buy_rate, self.exchange_rate, self.sebi_rate,
                 self.gst_rate, self.brokerage_per_leg)
        if not all(math.isfinite(x) and x >= 0 for x in rates) or self.gst_rate > 1:
            raise ValueError("invalid cost config")


class StatutoryCostCalculator:
    def __init__(self, config: CostConfig | None = None):
        self.config = config or CostConfig()

    def calculate(self, legs: Sequence[OptionLeg]) -> FeeBreakdown:
        if not legs:
            raise ValueError("at least one leg is required")
        for leg in legs:
            leg.validate()
        buy = sum(l.premium * l.quantity for l in legs if l.side == "BUY")
        sell = sum(l.premium * l.quantity for l in legs if l.side == "SELL")
        total = buy + sell
        c = self.config
        stt = sell * c.stt_sell_rate
        stamp = buy * c.stamp_buy_rate
        exchange = total * c.exchange_rate
        sebi = total * c.sebi_rate
        brokerage = c.brokerage_per_leg * len(legs)
        gst = (exchange + sebi + brokerage) * c.gst_rate
        slip = sum(l.half_spread_per_unit * l.quantity for l in legs)
        impact = sum(l.impact_per_unit * l.quantity for l in legs)
        friction = stt + stamp + exchange + sebi + brokerage + gst + slip + impact
        return FeeBreakdown(buy, sell, total, stt, stamp, exchange, sebi, brokerage, gst, slip, impact, friction)

    def profitability_gate(self, gross_alpha: float, legs: Sequence[OptionLeg], extra_impact_hurdle: float = 0.0) -> dict[str, Any]:
        if not math.isfinite(gross_alpha) or not math.isfinite(extra_impact_hurdle) or extra_impact_hurdle < 0:
            raise ValueError("alpha must be finite and extra hurdle nonnegative")
        costs = self.calculate(legs)
        net = gross_alpha - costs.total_friction - extra_impact_hurdle
        return {"approved": net > 0.0, "gross_alpha": gross_alpha, "friction": costs.total_friction,
                "extra_impact_hurdle": extra_impact_hurdle, "net_alpha": net, "costs": asdict(costs)}


@dataclass
class DynamicVolatilityThrottler:
    max_trades_per_day: int = 15
    base_cooldown_seconds: float = 900.0
    theta_vol: float = 1.0
    sigma_baseline: float = 0.20
    max_consecutive_losses: int = 3
    revenge_ratio_threshold: float = 1.25
    min_fill_interval: float = 30.0
    trades_today: int = 0
    consecutive_losses: int = 0
    last_fill_time: float | None = None
    last_fill_size: float | None = None
    locked_until: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        params = (self.base_cooldown_seconds, self.theta_vol, self.sigma_baseline, self.min_fill_interval, self.revenge_ratio_threshold)
        if not all(math.isfinite(float(x)) for x in params) or not isinstance(self.max_trades_per_day, int) or self.max_trades_per_day < 1 or self.base_cooldown_seconds <= 0 or self.theta_vol < 0 or self.sigma_baseline <= 0 or self.min_fill_interval < 0 or self.revenge_ratio_threshold <= 0 or self.max_consecutive_losses < 1:
            raise ValueError("invalid throttler settings")

    def cooldown_duration(self, sigma_rough: float) -> float:
        if not math.isfinite(sigma_rough) or sigma_rough < 0:
            raise ValueError("sigma_rough must be finite and nonnegative")
        return self.base_cooldown_seconds * (1.0 + self.theta_vol * sigma_rough / self.sigma_baseline)

    def _lock(self, now: float, reason: str, duration: float) -> None:
        self.locked_until = max(self.locked_until, now + duration)
        self.reasons.append(reason)

    def can_trade(self, now: float) -> bool:
        if not math.isfinite(now):
            return False
        return self.trades_today < self.max_trades_per_day and now >= self.locked_until

    def record_fill(self, now: float, size: float, pnl: float, sigma_rough: float) -> dict[str, Any]:
        if not all(math.isfinite(x) for x in (now, size, pnl, sigma_rough)) or size <= 0:
            raise ValueError("fill time/pnl/volatility must be finite and size positive")
        duration = self.cooldown_duration(sigma_rough)
        if self.last_fill_time is not None and now - self.last_fill_time < self.min_fill_interval:
            self._lock(now, "rapid_pacing", max(900.0, duration))
        if self.last_fill_size is not None and size / self.last_fill_size > self.revenge_ratio_threshold:
            self._lock(now, "revenge_sizing", max(900.0, duration))
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        if self.consecutive_losses >= self.max_consecutive_losses:
            self._lock(now, "loss_streak", max(900.0, duration))
        self.trades_today += 1
        self.last_fill_time, self.last_fill_size = now, size
        if self.trades_today >= self.max_trades_per_day:
            self._lock(now, "daily_cap", 24 * 3600)
        return {"can_trade": self.can_trade(now), "locked_until": self.locked_until,
                "cooldown_seconds": duration, "trades_today": self.trades_today,
                "reasons": self.reasons[-3:]}

    def reset_day(self) -> None:
        self.trades_today = 0
        self.consecutive_losses = 0
        self.last_fill_time = None
        self.last_fill_size = None
        self.locked_until = 0.0
        self.reasons.clear()


class AgentRole(str, Enum):
    MANAGER = "Manager Abhi"
    MICROSTRUCTURE = "Alex"
    VOLATILITY = "Emily"
    RISK = "Max"


@dataclass(frozen=True)
class AgentDecision:
    agent: str
    approved: bool
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class SquadConsensus:
    """Deterministic four-role review. Manager Abhi has unconditional live veto."""
    capital: float = PAPER_INITIAL_CAPITAL
    ledger_epoch: str = PAPER_LEDGER_EPOCH
    uncertainty_haircut: float = 0.5

    def __post_init__(self) -> None:
        if not math.isfinite(self.capital) or self.capital < 0 or not 0 <= self.uncertainty_haircut <= 1:
            raise ValueError("invalid capital or haircut")

    @staticmethod
    def bayesian_kelly(prob_win: float, reward_risk: float, uncertainty_haircut: float = 0.5) -> float:
        if not (math.isfinite(prob_win) and math.isfinite(reward_risk) and math.isfinite(uncertainty_haircut)):
            raise ValueError("Kelly inputs must be finite")
        if not 0 <= prob_win <= 1 or reward_risk <= 0 or not 0 <= uncertainty_haircut <= 1:
            raise ValueError("invalid Kelly inputs")
        raw = prob_win - (1.0 - prob_win) / reward_risk
        return max(0.0, min(1.0, raw * uncertainty_haircut))

    def evaluate(self, proposal: Mapping[str, Any], *, live: bool = False) -> dict[str, Any]:
        gross = float(proposal.get("gross_alpha", 0.0))
        friction = float(proposal.get("friction", 0.0))
        capital_required = float(proposal.get("capital_required", 0.0))
        queue_hazard = float(proposal.get("queue_hazard", 0.0))
        sigma_rough = float(proposal.get("sigma_rough", 0.0))
        if not all(math.isfinite(x) for x in (gross, friction, capital_required, queue_hazard, sigma_rough)):
            raise ValueError("proposal metrics must be finite")
        # Manager decision executes first and is a hard veto for live requests.
        manager_ok = (not live and not LIVE_ORDER_DISPATCH_ENABLED and REAL_BROKER_FILLS_LOCKED
                      and capital_required <= self.capital and capital_required >= 0)
        manager_reason = "paper_only_approved_for_review" if manager_ok else "manager_veto_live_or_capital"
        decisions = [AgentDecision(AgentRole.MANAGER.value, manager_ok, manager_reason,
                                   {"capital_required": capital_required, "available_capital": self.capital, "live_requested": live})]
        alex_ok = queue_hazard < 0.95
        decisions.append(AgentDecision(AgentRole.MICROSTRUCTURE.value, alex_ok,
                                       "queue_risk_acceptable" if alex_ok else "toxic_queue_hazard",
                                       {"queue_hazard": queue_hazard}))
        emily_ok = sigma_rough <= 3.0
        decisions.append(AgentDecision(AgentRole.VOLATILITY.value, emily_ok,
                                       "rough_volatility_acceptable" if emily_ok else "volatility_risk_limit",
                                       {"sigma_rough": sigma_rough}))
        max_ok = gross > friction
        decisions.append(AgentDecision(AgentRole.RISK.value, max_ok,
                                       "net_alpha_positive" if max_ok else "net_alpha_not_positive",
                                       {"net_alpha": gross - friction}))
        approved = all(d.approved for d in decisions)
        return {"approved": approved, "decisions": [_to_jsonable(d) for d in decisions],
                "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED,
                "paper_ledger_epoch": self.ledger_epoch}


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    raise PermissionError("Cycle 43 is paper-only: live broker order dispatch is permanently disabled")


@dataclass
class Cycle43ExecutionEngine:
    rough: RoughVolterraCovariance = field(default_factory=RoughVolterraCovariance)
    hawkes: HawkesSpilloverGraph = field(default_factory=HawkesSpilloverGraph)
    mlofi: MultiLevelOFI = field(default_factory=MultiLevelOFI)
    gamma_squeeze: DealerGammaSqueezeTopology = field(default_factory=DealerGammaSqueezeTopology)
    costs: StatutoryCostCalculator = field(default_factory=StatutoryCostCalculator)
    throttler: DynamicVolatilityThrottler = field(default_factory=DynamicVolatilityThrottler)
    squad: SquadConsensus = field(default_factory=SquadConsensus)
    last_hedge: dict[str, Any] = field(default_factory=dict)
    last_cost_gate: dict[str, Any] = field(default_factory=dict)
    last_squeeze: dict[str, Any] = field(default_factory=dict)
    ticks: int = 0

    def process_tick(self, dt: float, shocks: Sequence[float], event_counts: Sequence[float],
                     ofi_book: Mapping[str, tuple[Sequence[float], Sequence[float]]],
                     gamma_clusters: Mapping[str, Mapping[float, float]],
                     depth: Mapping[str, float], *, toxic_assets: Iterable[str] = ()) -> dict[str, Any]:
        cov = self.rough.update(dt, shocks)
        intensities = self.hawkes.update(dt, event_counts)
        ofi_values = {}
        for asset, (bid, ask) in ofi_book.items():
            ofi_values[asset] = self.mlofi.update(asset, bid, ask)
        toxic = set(toxic_assets)
        squeeze = {}
        for asset, gex in gamma_clusters.items():
            if asset not in depth:
                raise ValueError(f"missing depth for {asset}")
            squeeze[asset] = self.gamma_squeeze.update(asset, gex, depth[asset], toxic_cascade=asset in toxic)
        self.last_squeeze = squeeze
        self.ticks += 1
        return {"tick": self.ticks, "covariance": cov.tolist(), "hawkes_intensity": intensities.tolist(),
                "hawkes_radius": self.hawkes.spectral_radius, "mlofi": ofi_values,
                "squeeze": squeeze, "rough_variance": self.rough.instantaneous_variance.tolist()}

    def evaluate_spread(self, gross_alpha: float, legs: Sequence[OptionLeg], *, now: float,
                        capital_required: float = 0.0, extra_impact_hurdle: float = 0.0,
                        queue_hazard: float = 0.0, sigma_rough: float | None = None,
                        live: bool = False) -> dict[str, Any]:
        rough_sigma = float(np.mean(np.sqrt(self.rough.instantaneous_variance))) if sigma_rough is None else sigma_rough
        gate = self.costs.profitability_gate(gross_alpha, legs, extra_impact_hurdle)
        self.last_cost_gate = gate
        throttle_ok = self.throttler.can_trade(now)
        proposal = {"gross_alpha": gross_alpha, "friction": gate["friction"] + extra_impact_hurdle,
                    "capital_required": capital_required, "queue_hazard": queue_hazard,
                    "sigma_rough": rough_sigma}
        consensus = self.squad.evaluate(proposal, live=live)
        approved = bool(gate["approved"] and throttle_ok and consensus["approved"] and not live)
        return {"approved": approved, "net_alpha": gate["net_alpha"] if approved else min(0.0, gate["net_alpha"]),
                "gross_alpha": gross_alpha, "friction": gate["friction"], "extra_impact_hurdle": extra_impact_hurdle,
                "throttle_ok": throttle_ok, "consensus": consensus,
                "reason": "approved_for_paper_simulation" if approved else (
                    "live_veto" if live else "throttle_or_consensus_or_profitability_gate")}

    def record_fill(self, now: float, size: float, pnl: float) -> dict[str, Any]:
        sigma = float(np.mean(np.sqrt(self.rough.instantaneous_variance)))
        return self.throttler.record_fill(now, size, pnl, sigma)

    def optimize_greek_hedge(self, delta: Sequence[float], gamma: Sequence[float], vega: Sequence[float],
                             covariance: np.ndarray, spreads: Sequence[float], depths: Sequence[float],
                             *, current_delta: float = 0.0, current_gamma: float = 0.0,
                             current_vega: float = 0.0, delta_limit: float = 1e-4,
                             gamma_limit: float = 1e-3, vega_limit: float = 1.0,
                             max_abs_weight: float = 10.0, iterations: int = 1000,
                             learning_rate: float = 0.01, transaction_penalty: float = 0.01,
                             vacuum_penalty: float = 0.1, gamma_penalty: float = 100.0,
                             vega_penalty: float = 1.0) -> dict[str, Any]:
        d = _finite_array(delta, "delta", 1); g = _finite_array(gamma, "gamma", 1); v = _finite_array(vega, "vega", 1)
        sp = _finite_array(spreads, "spreads", 1); dep = _finite_array(depths, "depths", 1)
        cov = _finite_array(covariance, "covariance", 2)
        n = len(d)
        if n == 0 or any(x.shape != (n,) for x in (g, v, sp, dep)) or cov.shape != (n, n):
            raise ValueError("hedge vectors/covariance dimensions must match")
        if np.any(sp < 0) or np.any(dep < 0) or max_abs_weight <= 0 or iterations < 1 or learning_rate <= 0:
            raise ValueError("invalid hedge bounds, spreads, depth or solver controls")
        if not all(math.isfinite(x) for x in (current_delta, current_gamma, current_vega,
                                              delta_limit, gamma_limit, vega_limit,
                                              max_abs_weight, learning_rate, transaction_penalty,
                                              vacuum_penalty, gamma_penalty, vega_penalty)):
            raise ValueError("hedge exposures, limits, and penalties must be finite")
        if min(delta_limit, gamma_limit, vega_limit, transaction_penalty, vacuum_penalty, gamma_penalty, vega_penalty) < 0:
            raise ValueError("hedge limits and penalties must be nonnegative")
        if np.linalg.eigvalsh((cov + cov.T) / 2).min() < -1e-9:
            raise ValueError("option covariance must be positive semidefinite")
        # PSD cross-asset impact regularizer is a Gram matrix from spread/depth-scaled loadings.
        impact_diag = np.array([1.0 / max(float(x), 1e-6) for x in dep])
        omega = np.diag(impact_diag)
        hess = (cov + cov.T) / 2 + vacuum_penalty * omega + np.eye(n) * 1e-8
        linear = transaction_penalty * sp
        w = np.zeros(n, dtype=float)
        den_d = float(d @ d)
        # A conservative spectral step keeps the smooth quadratic part stable.
        lipschitz = float(np.linalg.norm(hess, 2) + gamma_penalty * (g @ g) + vega_penalty * (v @ v) + 1e-8)
        step = min(learning_rate, 0.9 / max(lipschitz, 1e-8))
        # Proximal projected-gradient. Repeated hyperplane/box projection handles signed bounded lots;
        # infeasibility is reported rather than silently claiming Greek neutrality.
        for _ in range(iterations):
            grad = hess @ w + gamma_penalty * g * (float(g @ w) + current_gamma) \
                   + vega_penalty * v * (float(v @ w) + current_vega)
            z = w - step * grad
            candidate = np.sign(z) * np.maximum(0.0, np.abs(z) - step * linear)
            candidate = np.clip(candidate, -max_abs_weight, max_abs_weight)
            if den_d > 1e-15:
                for _projection in range(4):
                    candidate -= d * ((float(d @ candidate) + current_delta) / den_d)
                    candidate = np.clip(candidate, -max_abs_weight, max_abs_weight)
            w = candidate
        net_delta = current_delta + float(d @ w)
        net_gamma = current_gamma + float(g @ w)
        net_vega = current_vega + float(v @ w)
        feasible = (abs(net_delta) <= delta_limit and abs(net_gamma) <= gamma_limit and abs(net_vega) <= vega_limit)
        self.last_hedge = {"weights": w.tolist(), "net_delta": net_delta, "net_gamma": net_gamma,
                           "net_vega": net_vega, "feasible": feasible, "impact_matrix": omega.tolist(),
                           "iterations": iterations, "step_size": step}
        return dict(self.last_hedge)

    def optimize_cross_expiry_hedge(self, legs: Sequence[OptionLeg], covariance: np.ndarray,
                                    depths: Sequence[float], *, current_delta: float = 0.0,
                                    current_gamma: float = 0.0, current_vega: float = 0.0,
                                    max_abs_weight: float = 10.0, iterations: int = 1000,
                                    learning_rate: float = 0.01, transaction_penalty: float = 0.01,
                                    vacuum_penalty: float = 0.1, gamma_penalty: float = 100.0,
                                    vega_penalty: float = 1.0) -> dict[str, Any]:
        """Convenience wrapper that reports hedge weights grouped by expiry.

        Signed weights denote net buy (+) or sell (-) quantities of each supplied
        option instrument. Feasibility is measured against the *total* portfolio
        Greeks, including the starting exposure; infeasible results are explicit.
        """
        if not legs:
            raise ValueError("cross-expiry hedge requires at least one leg")
        for leg in legs:
            leg.validate()
        result = self.optimize_greek_hedge(
            [leg.delta for leg in legs], [leg.gamma for leg in legs], [leg.vega for leg in legs],
            covariance, [leg.half_spread_per_unit for leg in legs], depths,
            current_delta=current_delta, current_gamma=current_gamma, current_vega=current_vega,
            max_abs_weight=max_abs_weight, iterations=iterations, learning_rate=learning_rate,
            transaction_penalty=transaction_penalty, vacuum_penalty=vacuum_penalty,
            gamma_penalty=gamma_penalty, vega_penalty=vega_penalty,
        )
        grouped: dict[str, float] = {}
        for leg, weight in zip(legs, result["weights"]):
            grouped[leg.expiry] = grouped.get(leg.expiry, 0.0) + float(weight)
        result["weights_by_expiry"] = grouped
        result["leg_symbols"] = [leg.symbol for leg in legs]
        return result

    def telemetry(self, *, now_clock: float | None = None, timestamp_epoch: float | None = None) -> dict[str, Any]:
        clock = time.monotonic() if now_clock is None else now_clock
        if not math.isfinite(clock):
            raise ValueError("now_clock must be finite")
        return _to_jsonable({
            "timestamp_ist": _ist_timestamp(timestamp_epoch), "tick_count": self.ticks,
            "assets": list(ASSETS), "hurst": list(self.rough.hurst),
            "rough_variance": self.rough.instantaneous_variance,
            "rough_covariance": self.rough.covariance(),
            "hawkes_intensity": self.hawkes.intensity,
            "hawkes_spectral_radius": self.hawkes.spectral_radius,
            "hawkes_centralities": self.hawkes.centralities(),
            "hawkes_leadership": self.hawkes.leadership_matrix(),
            "mlofi": self.mlofi.values,
            "gamma_squeeze": self.last_squeeze,
            "hedge": self.last_hedge, "last_cost_gate": self.last_cost_gate,
            "risk_throttle": {"trades_today": self.throttler.trades_today,
                               "locked_until": self.throttler.locked_until,
                               "reasons": self.throttler.reasons[-5:],
                               "can_trade_now": self.throttler.can_trade(clock)},
            "paper_ledger_epoch": PAPER_LEDGER_EPOCH, "initial_paper_capital": PAPER_INITIAL_CAPITAL,
            "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
            "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED,
        })

    @staticmethod
    def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
        dispatch_live_order(*args, **kwargs)


class _TelemetryHandler(BaseHTTPRequestHandler):
    engine: Cycle43ExecutionEngine | None = None
    def log_message(self, *args: Any) -> None:
        return
    def do_GET(self) -> None:
        engine = type(self).engine
        if engine is None:
            self.send_error(503, "engine unavailable"); return
        if self.path == "/health":
            payload = {"healthy": True, "paper_only": True, "live_dispatch": False,
                       "ledger_epoch": PAPER_LEDGER_EPOCH}
            self._json(payload); return
        if self.path == "/telemetry":
            self._json(engine.telemetry()); return
        if self.path == "/events":
            payload = json.dumps(engine.telemetry(), separators=(",", ":"), allow_nan=False)
            body = f"retry: 1000\nevent: telemetry\ndata: {payload}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); self.wfile.flush(); return
        self.send_error(404)
    def _json(self, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)


class TelemetryServer:
    def __init__(self, engine: Cycle43ExecutionEngine, host: str = "127.0.0.1", port: int = 8088):
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("dashboard is restricted to loopback by default")
        handler = type("Cycle43TelemetryHandler", (_TelemetryHandler,), {})
        handler.engine = engine
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server.daemon_threads = True
        self.thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown(); self.server.server_close()
        if self.thread: self.thread.join(timeout=1.0)
