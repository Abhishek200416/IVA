"""Cycle 41: cross-asset rough Volterra covariance, Hawkes spillover and paper hedging.

This is an offline quantitative research reference. Live broker execution is deliberately
unavailable. NumPy is used for small matrix operations; SciPy is not required.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
import json
import math
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")

# Published NSE defaults: STT options-sale rate from 1-Apr-2026; transaction-charge
# outflow for equity options from 1-Mar-2026. Rates remain configurable for reconciliation.
@dataclass(frozen=True)
class StatutoryConfig:
    sell_stt_rate: float = 0.0015
    buy_stamp_rate: float = 0.00003
    exchange_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    brokerage_per_leg: float = 20.0
    def __post_init__(self) -> None:
        rates = (self.sell_stt_rate, self.buy_stamp_rate, self.gst_rate)
        fees = (self.exchange_per_crore, self.sebi_per_crore, self.brokerage_per_leg)
        if any((not math.isfinite(x) or x < 0) for x in rates + fees):
            raise ValueError("rates and fees must be finite and nonnegative")
        if self.gst_rate > 1:
            raise ValueError("gst_rate must be expressed as a fraction")

@dataclass(frozen=True)
class TradeLeg:
    side: str
    premium: float
    lots: int
    lot_size: int = 1
    label: str = "option-leg"
    def __post_init__(self) -> None:
        if self.side.upper() not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if not math.isfinite(self.premium) or self.premium < 0:
            raise ValueError("premium must be finite and nonnegative")
        if self.lots < 0 or self.lot_size < 1:
            raise ValueError("lots must be nonnegative and lot_size positive")

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
    total: float
    @property
    def statutory_total(self) -> float:
        return self.stt + self.stamp_duty + self.exchange_fee + self.sebi_fee + self.gst + self.brokerage

class StatutoryCostCalculator:
    def __init__(self, config: StatutoryConfig = StatutoryConfig()) -> None:
        self.config = config
    def calculate(self, legs: Sequence[TradeLeg]) -> FeeBreakdown:
        if not legs:
            return FeeBreakdown(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        buy = sum(x.premium * x.lots * x.lot_size for x in legs if x.side.upper() == "BUY")
        sell = sum(x.premium * x.lots * x.lot_size for x in legs if x.side.upper() == "SELL")
        total_turnover = buy + sell
        stt = sell * self.config.sell_stt_rate
        stamp = buy * self.config.buy_stamp_rate
        exchange = total_turnover * self.config.exchange_per_crore / 10_000_000.0
        sebi = total_turnover * self.config.sebi_per_crore / 10_000_000.0
        brokerage = sum(self.config.brokerage_per_leg for _ in legs)
        gst = self.config.gst_rate * (exchange + sebi + brokerage)
        total = stt + stamp + exchange + sebi + brokerage + gst
        values = (buy, sell, total_turnover, stt, stamp, exchange, sebi, brokerage, gst, total)
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError("invalid or overflowing fee calculation")
        return FeeBreakdown(*values)
    def net_alpha(self, gross_alpha: float, legs: Sequence[TradeLeg],
                  slippage: float = 0.0, impact_hurdle: float = 0.0) -> float:
        if not math.isfinite(gross_alpha) or not math.isfinite(slippage) or not math.isfinite(impact_hurdle):
            raise ValueError("alpha and hurdles must be finite")
        if slippage < 0 or impact_hurdle < 0:
            raise ValueError("slippage and impact must be nonnegative")
        return gross_alpha - self.calculate(legs).total - slippage - impact_hurdle
    def qualifies(self, gross_alpha: float, legs: Sequence[TradeLeg],
                  slippage: float = 0.0, impact_hurdle: float = 0.0) -> bool:
        # Strict inequality: exactly break-even is rejected.
        return self.net_alpha(gross_alpha, legs, slippage, impact_hurdle) > 0.0

# ----------------------- linear algebra / validation helpers -----------------------
def _arr(value: Any, shape: Optional[tuple[int, ...]] = None, name: str = "array") -> np.ndarray:
    a = np.asarray(value, dtype=float)
    if shape is not None and a.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {a.shape}")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must be finite")
    return a

def _psd_project(matrix: np.ndarray, floor: float = 0.0) -> np.ndarray:
    sym = 0.5 * (matrix + matrix.T)
    vals, vecs = np.linalg.eigh(sym)
    vals = np.maximum(vals, floor)
    out = (vecs * vals) @ vecs.T
    return 0.5 * (out + out.T)

def _cov_corr(correlation: Sequence[Sequence[float]], n: int) -> tuple[np.ndarray, np.ndarray]:
    c = _arr(correlation, (n, n), "correlation")
    if not np.allclose(c, c.T, atol=1e-10):
        raise ValueError("correlation matrix must be symmetric")
    if not np.allclose(np.diag(c), 1.0, atol=1e-8):
        raise ValueError("correlation diagonal must be one")
    vals, vecs = np.linalg.eigh(c)
    if float(vals.min()) < -1e-9:
        raise ValueError("correlation matrix must be positive semidefinite")
    root = vecs @ np.diag(np.sqrt(np.maximum(vals, 0.0))) @ vecs.T
    return c, root

# ----------------------- multi-asset rough Volterra covariance ---------------------
@dataclass(frozen=True)
class VolterraSnapshot:
    timestamp_seconds: float
    variances: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    rough_states: tuple[tuple[float, ...], ...]
    min_covariance_eigenvalue: float
    kernel_relative_errors: tuple[float, ...]

class MultiAssetRoughVolterraCovariance:
    """Positive-semidefinite four-asset covariance via a Cholesky/eigen lift.

    The exponential sum uses positive log-grid quadrature weights for the Laplace
    representation of the fractional kernel. This is an approximation, not an exact
    representation of a fractional stochastic integral.
    """
    def __init__(self, hurst: Sequence[float] = (0.075, 0.10, 0.14, 0.20),
                 n_factors: int = 12, base_variances: Sequence[float] = (0.04, 0.06, 0.07, 0.08),
                 eta: Sequence[float] = (1.0, 1.0, 0.9, 0.9),
                 correlation: Optional[Sequence[Sequence[float]]] = None,
                 horizon: float = 1.0, seed: int = 41) -> None:
        self.hurst = _arr(hurst, (4,), "hurst")
        if np.any(self.hurst <= 0.05) or np.any(self.hurst >= 0.45):
            raise ValueError("each Hurst parameter must be in (0.05, 0.45)")
        if n_factors < 8:
            raise ValueError("n_factors must be at least 8")
        if not math.isfinite(horizon) or horizon <= 0:
            raise ValueError("horizon must be positive")
        self.n_factors = int(n_factors)
        self.base_variances = _arr(base_variances, (4,), "base_variances")
        self.eta = _arr(eta, (4,), "eta")
        if np.any(self.base_variances <= 0) or np.any(self.eta < 0):
            raise ValueError("base variances must be positive and eta nonnegative")
        if correlation is None:
            correlation = [[1, .55, .42, .35], [.55, 1, .30, .25], [.42, .30, 1, .40], [.35, .25, .40, 1]]
        self.correlation, self.correlation_root = _cov_corr(correlation, 4)
        self.horizon = float(horizon)
        self.rng = np.random.default_rng(seed)
        # Rates span timescales faster than the minimum time step through the horizon.
        self.gamma_nodes = np.geomspace(1.0 / (self.horizon * 100.0), 1.0 / (self.horizon / 100.0), self.n_factors)
        self.omega = np.vstack([self._weights_for_h(float(h)) for h in self.hurst])
        self.states = np.zeros((4, self.n_factors), dtype=float)
        self.elapsed = 0.0
        self.last_snapshot = self.snapshot()
    def _weights_for_h(self, h: float) -> np.ndarray:
        p = 0.5 - h
        x = np.log(self.gamma_nodes)
        dx = float(np.mean(np.diff(x))) if len(x) > 1 else 1.0
        log_coeff = p * x - math.lgamma(p) - math.lgamma(1.0 - p) + math.log(dx)
        return np.exp(np.clip(log_coeff, -700, 700))
    def kernel_exact(self, h_index: int, t: float) -> float:
        if not 0 <= h_index < 4: raise IndexError("asset index out of range")
        if not math.isfinite(t) or t <= 0: raise ValueError("kernel time must be positive")
        h = float(self.hurst[h_index])
        return t ** (h - 0.5) / math.gamma(h + 0.5)
    def kernel_approx(self, h_index: int, t: float) -> float:
        if not math.isfinite(t) or t <= 0: raise ValueError("kernel time must be positive")
        return float(np.dot(self.omega[h_index], np.exp(-self.gamma_nodes * t)))
    def kernel_relative_error(self, h_index: int, t: float) -> float:
        exact = self.kernel_exact(h_index, t)
        return abs(self.kernel_approx(h_index, t) / exact - 1.0)
    def snapshot(self) -> VolterraSnapshot:
        rough = self.states @ self.omega.T if False else np.sum(self.states * self.omega, axis=1)
        log_scale = np.clip(self.eta * rough - 0.5 * self.eta**2 * max(self.elapsed, 1e-12) ** (2 * self.hurst), -50, 50)
        variances = self.base_variances * np.exp(log_scale)
        scales = np.sqrt(variances)
        cov = np.diag(scales) @ self.correlation @ np.diag(scales)
        eigmin = float(np.linalg.eigvalsh(0.5 * (cov + cov.T)).min())
        errs = tuple(self.kernel_relative_error(i, min(max(self.elapsed, self.horizon / 1000), self.horizon)) for i in range(4))
        return VolterraSnapshot(self.elapsed, tuple(map(float, variances)), tuple(tuple(map(float, row)) for row in cov),
                                tuple(tuple(map(float, row)) for row in self.states), eigmin, errs)
    def step(self, dt: float, innovations: Optional[Sequence[float]] = None) -> VolterraSnapshot:
        if not math.isfinite(dt) or dt <= 0: raise ValueError("dt must be finite and positive")
        eps = self.rng.normal(size=4) if innovations is None else _arr(innovations, (4,), "innovations")
        correlated = self.correlation_root @ eps
        decay = np.exp(-self.gamma_nodes * dt)
        innovation_scale = np.sqrt(np.maximum((1.0 - decay**2) / (2.0 * self.gamma_nodes), 0.0))
        self.states = self.states * decay[None, :] + correlated[:, None] * innovation_scale[None, :]
        self.elapsed += dt
        self.last_snapshot = self.snapshot()
        if self.last_snapshot.min_covariance_eigenvalue < -1e-8:
            raise ArithmeticError("covariance PSD invariant violated")
        return self.last_snapshot

# ----------------------- 4-asset Hawkes spillover network --------------------------
class HawkesLeadLagGraph:
    NODES = ASSETS
    def __init__(self, baseline: Sequence[float] = (0.4, 0.5, 0.2, 0.25),
                 alpha: Optional[Sequence[Sequence[float]]] = None,
                 beta: Optional[Sequence[Sequence[float]] | Sequence[float]] = None,
                 stability_limit: float = 0.88) -> None:
        self.mu = _arr(baseline, (4,), "baseline")
        if np.any(self.mu <= 0): raise ValueError("baseline intensities must be positive")
        if not 0 < stability_limit < 1: raise ValueError("stability limit must be in (0,1)")
        self.stability_limit = float(stability_limit)
        if alpha is None:
            alpha = [[0.10, .08, .05, .04], [.09, .12, .07, .05], [.04, .06, .09, .03], [.03, .04, .03, .08]]
        self.alpha = _arr(alpha, (4, 4), "alpha")
        if np.any(self.alpha < 0): raise ValueError("alpha couplings must be nonnegative")
        if beta is None: beta = [[2.0, 2.2, 2.4, 2.5] for _ in range(4)]
        b = np.asarray(beta, dtype=float)
        if b.shape == (4,): b = np.tile(b[None, :], (4, 1))
        self.beta = _arr(b, (4, 4), "beta")
        if np.any(self.beta <= 0): raise ValueError("beta must be positive")
        self.excitation = np.zeros((4, 4), dtype=float)
        self.elapsed = 0.0
        self.project_stability()
    @property
    def branching(self) -> np.ndarray: return self.alpha / self.beta
    def spectral_radius(self, matrix: Optional[np.ndarray] = None) -> float:
        mat = self.branching if matrix is None else _arr(matrix, (4, 4), "matrix")
        return float(np.max(np.abs(np.linalg.eigvals(mat))))
    def project_stability(self) -> float:
        radius = self.spectral_radius()
        if radius >= self.stability_limit:
            # Perron-Frobenius scaling preserves non-negativity and direction, and strictly
            # contracts the spectral radius below the requested boundary.
            self.alpha *= (self.stability_limit * (1.0 - 1e-8)) / max(radius, 1e-12)
        if self.spectral_radius() >= self.stability_limit:
            raise ArithmeticError("failed Hawkes stability projection")
        return self.spectral_radius()
    def intensity(self) -> np.ndarray: return self.mu + self.excitation.sum(axis=1)
    def step(self, dt: float, event_counts: Sequence[int | float] = (0, 0, 0, 0)) -> np.ndarray:
        if not math.isfinite(dt) or dt <= 0: raise ValueError("dt must be positive")
        counts = _arr(event_counts, (4,), "event_counts")
        if np.any(counts < 0): raise ValueError("event counts must be nonnegative")
        before = self.intensity().copy()
        self.excitation *= np.exp(-self.beta * dt)
        self.excitation += self.alpha * counts[None, :]
        self.elapsed += dt
        return self.intensity()
    def online_sgd(self, dt: float, event_counts: Sequence[int | float], learning_rate: float = 1e-3) -> float:
        if dt <= 0 or not math.isfinite(dt): raise ValueError("dt must be positive")
        if learning_rate <= 0 or not math.isfinite(learning_rate): raise ValueError("learning_rate must be positive")
        counts = _arr(event_counts, (4,), "event_counts")
        if np.any(counts < 0): raise ValueError("event counts must be nonnegative")
        lam = np.maximum(self.intensity(), 1e-9)
        score = counts / lam - dt
        self.mu = np.maximum(self.mu + learning_rate * score, 1e-6)
        # Residual score nudges excitation magnitudes in proportion to current feature state.
        feature = self.excitation + self.alpha * np.maximum(counts, 0.0)[None, :]
        denom = np.sum(feature * feature, axis=1, keepdims=True) + 1e-9
        self.alpha = np.maximum(self.alpha + learning_rate * score[:, None] * feature / denom, 0.0)
        self.project_stability()
        return float(np.sum(counts * np.log(lam) - lam * dt))
    def leadership_matrix(self) -> np.ndarray:
        g = self.branching
        return (g - g.T) / (g + g.T + 1e-12)
    def centralities(self) -> dict[str, dict[str, float]]:
        g = self.branching
        return {name: {"absorption_in_degree": float(g[i, :].sum()),
                       "spillover_out_degree": float(g[:, i].sum())}
                for i, name in enumerate(self.NODES)}
    def leading_constituents(self, n: int = 4) -> list[tuple[str, float]]:
        if n < 0: raise ValueError("n must be nonnegative")
        c = self.centralities()
        return sorted(((k, v["spillover_out_degree"]) for k, v in c.items()), key=lambda x: (-x[1], x[0]))[:n]

# ----------------------- Level-3 queue and adverse selection -----------------------
@dataclass
class QueueOrder:
    order_id: str
    instrument: str
    side: str
    level: int
    quantity: float
    ahead: float
    behind: float = 0.0
    created_at: float = 0.0
    active: bool = True
    def __post_init__(self) -> None:
        self.side = self.side.upper()
        if self.side not in {"BUY", "SELL"}: raise ValueError("side must be BUY or SELL")
        if not 1 <= self.level <= 5: raise ValueError("level must be between 1 and 5")
        if self.quantity <= 0 or self.ahead < 0 or self.behind < 0: raise ValueError("invalid queue quantities")
        if not all(math.isfinite(x) for x in (self.quantity, self.ahead, self.behind, self.created_at)):
            raise ValueError("queue quantities and time must be finite")

class L3QueueDepletionMachine:
    def __init__(self, lambda_market: float = 1.0, lambda_cancel0: float = 0.2,
                 alpha_cancel: Sequence[float] = (0.4, 0.2), beta_cancel: Sequence[float] = (2.0, 0.3),
                 gamma_ofi: float = 0.1) -> None:
        if lambda_market < 0 or lambda_cancel0 < 0 or gamma_ofi < 0: raise ValueError("intensities must be nonnegative")
        self.lambda_market = float(lambda_market); self.lambda_cancel0 = float(lambda_cancel0); self.gamma_ofi = float(gamma_ofi)
        self.alpha_cancel = _arr(alpha_cancel, name="alpha_cancel"); self.beta_cancel = _arr(beta_cancel, name="beta_cancel")
        if self.alpha_cancel.shape != self.beta_cancel.shape or np.any(self.alpha_cancel < 0) or np.any(self.beta_cancel <= 0):
            raise ValueError("cancel alpha/beta arrays must align and be nonnegative/positive")
        self.shock_ages: list[float] = []; self.orders: dict[str, QueueOrder] = {}; self.current_time = 0.0; self.last_ofi = 0.0
    def add_order(self, order: QueueOrder) -> None:
        if order.order_id in self.orders and self.orders[order.order_id].active: raise ValueError("duplicate active order_id")
        self.orders[order.order_id] = order
    def add_cancel_shock(self) -> None: self.shock_ages.append(0.0)
    def advance(self, dt: float, ofi: float = 0.0) -> None:
        if not math.isfinite(dt) or dt < 0 or not math.isfinite(ofi): raise ValueError("invalid advance input")
        self.current_time += dt; self.shock_ages = [age + dt for age in self.shock_ages]; self.last_ofi = float(ofi)
    def cancel_intensity(self, ofi: Optional[float] = None) -> float:
        value_ofi = self.last_ofi if ofi is None else ofi
        if not math.isfinite(value_ofi): raise ValueError("ofi must be finite")
        value = self.lambda_cancel0 + self.gamma_ofi * max(0.0, -value_ofi)
        value += sum(float(self.alpha_cancel[i % len(self.alpha_cancel)] * math.exp(-self.beta_cancel[i % len(self.beta_cancel)] * age))
                     for i, age in enumerate(self.shock_ages))
        return float(max(0.0, value))
    def survival_probability(self, tau: float, ofi: Optional[float] = None) -> float:
        if not math.isfinite(tau) or tau < 0: raise ValueError("tau must be finite and nonnegative")
        value_ofi = self.last_ofi if ofi is None else ofi
        hazard_integral = (self.lambda_cancel0 + self.gamma_ofi * max(0.0, -value_ofi)) * tau
        hazard_integral += sum(float(self.alpha_cancel[i % len(self.alpha_cancel)] / self.beta_cancel[i % len(self.beta_cancel)]
                                         * math.exp(-self.beta_cancel[i % len(self.beta_cancel)] * age)
                                         * (1.0 - math.exp(-self.beta_cancel[i % len(self.beta_cancel)] * tau)))
                               for i, age in enumerate(self.shock_ages))
        return float(math.exp(-max(0.0, hazard_integral)))
    def fill_probability(self, order_id: str, tau: float, cancellation_weight: float = 1.0) -> float:
        if order_id not in self.orders: raise KeyError(order_id)
        if not math.isfinite(tau) or tau < 0 or cancellation_weight < 0: raise ValueError("invalid fill horizon or cancellation weight")
        order = self.orders[order_id]
        # Approximate depletion as Poisson queue-advance events. Queue ahead is represented
        # in event-equivalent units; fractional ahead rounds up conservatively.
        need = max(1, int(math.ceil(order.ahead - 1e-12)))
        rate = self.lambda_market + cancellation_weight * self.cancel_intensity()
        x = rate * tau
        if x == 0: return 0.0
        # P(Poisson(x) >= need), computed through the finite lower-tail sum.
        term = math.exp(-x); cdf = term
        for k in range(1, need):
            term *= x / k; cdf += term
            if term == 0: break
        return float(min(1.0, max(0.0, 1.0 - cdf)))
    def deplete(self, order_id: str, quantity: float, ahead_first: bool = True) -> float:
        if order_id not in self.orders: raise KeyError(order_id)
        if not math.isfinite(quantity) or quantity < 0: raise ValueError("quantity must be finite and nonnegative")
        o = self.orders[order_id]
        if not o.active: return 0.0
        used = min(quantity, o.ahead) if ahead_first else 0.0
        o.ahead -= used
        rest = quantity - used
        filled = min(o.quantity, rest) if o.ahead <= 1e-12 else 0.0
        o.quantity -= filled
        if o.quantity <= 1e-12: o.active = False
        return float(filled)
    def pullback_required(self, fill_probability: float, expected_adverse_slippage: float,
                          round_trip_friction: float, threshold: float = 0.85) -> bool:
        vals = (fill_probability, expected_adverse_slippage, round_trip_friction, threshold)
        if not all(math.isfinite(x) for x in vals): raise ValueError("pullback inputs must be finite")
        if not 0 <= fill_probability <= 1 or not 0 <= threshold <= 1 or expected_adverse_slippage < 0 or round_trip_friction < 0:
            raise ValueError("invalid pullback inputs")
        return fill_probability > threshold and expected_adverse_slippage > round_trip_friction

# ----------------------- Convex multi-horizon gamma/delta hedging ------------------
@dataclass(frozen=True)
class OptionInstrument:
    name: str
    delta: float
    gamma: float
    half_spread: float
    depth: float
    max_adjustment: float
    expiry_days: float = 7.0
    price: float = 0.0
    def __post_init__(self) -> None:
        nums = (self.delta, self.gamma, self.half_spread, self.depth, self.max_adjustment, self.expiry_days, self.price)
        if not all(math.isfinite(x) for x in nums): raise ValueError("instrument parameters must be finite")
        if self.half_spread < 0 or self.depth < 0 or self.max_adjustment < 0 or self.expiry_days < 0 or self.price < 0:
            raise ValueError("spreads, depth, limits, expiry, and price must be nonnegative")

@dataclass(frozen=True)
class HedgeResult:
    adjustments: tuple[float, ...]
    objective: float
    net_delta: float
    net_gamma: float
    gamma_target: float
    converged: bool
    iterations: int
    delta_neutral: bool
    def as_dict(self) -> dict[str, Any]: return asdict(self)

class MultiHorizonGammaHedger:
    """Convex proximal-gradient optimizer for delta/gamma tracking with L1 cost and vacuum penalty."""
    def __init__(self, instruments: Sequence[OptionInstrument], lambda_cost: float = 1.0,
                 lambda_vacuum: float = 0.1, delta_weight: float = 5.0, gamma_weight: float = 1.0,
                 epsilon: float = 1e-6, max_iter: int = 3000, tol: float = 1e-8) -> None:
        if not instruments: raise ValueError("at least one instrument is required")
        if any(not isinstance(x, OptionInstrument) for x in instruments): raise TypeError("instruments must be OptionInstrument")
        params = (lambda_cost, lambda_vacuum, delta_weight, gamma_weight, epsilon, tol)
        if not all(math.isfinite(x) and x >= 0 for x in params) or epsilon <= 0 or tol <= 0: raise ValueError("invalid optimizer parameters")
        if max_iter < 1: raise ValueError("max_iter must be positive")
        self.instruments = tuple(instruments); self.lambda_cost = lambda_cost; self.lambda_vacuum = lambda_vacuum
        self.delta_weight = delta_weight; self.gamma_weight = gamma_weight; self.epsilon = epsilon; self.max_iter = int(max_iter); self.tol = tol
        self.delta = np.array([x.delta for x in instruments]); self.gamma = np.array([x.gamma for x in instruments])
        self.cost = np.array([x.half_spread for x in instruments]); self.depth = np.array([x.depth for x in instruments])
        self.bounds = np.array([x.max_adjustment for x in instruments])
    def objective(self, u: Sequence[float], initial_delta: float, initial_gamma: float, gamma_target: float) -> float:
        x = _arr(u, (len(self.instruments),), "adjustments")
        nd = initial_delta + float(self.delta @ x); ng = initial_gamma + float(self.gamma @ x)
        return float(0.5 * self.delta_weight * nd**2 + 0.5 * self.gamma_weight * (ng - gamma_target)**2
                     + self.lambda_cost * np.sum(self.cost * np.abs(x))
                     + self.lambda_vacuum * np.sum(x*x / (self.depth + self.epsilon)))
    def optimize(self, initial_delta: float, initial_gamma: float, gamma_target: float) -> HedgeResult:
        if not all(math.isfinite(x) for x in (initial_delta, initial_gamma, gamma_target)):
            raise ValueError("Greek inputs must be finite")
        n = len(self.instruments); u = np.zeros(n, dtype=float)
        H = self.delta_weight * np.outer(self.delta, self.delta) + self.gamma_weight * np.outer(self.gamma, self.gamma)
        H += np.diag(2.0 * self.lambda_vacuum / (self.depth + self.epsilon))
        L = max(float(np.linalg.eigvalsh(H).max()), 1e-8)
        step = 1.0 / L
        linear = self.lambda_cost * self.cost
        converged = False
        # FISTA acceleration for the smooth quadratic + separable L1/box prox.
        y = u.copy(); t_acc = 1.0
        for it in range(1, self.max_iter + 1):
            nd_y = initial_delta + float(self.delta @ y)
            ng_y = initial_gamma + float(self.gamma @ y)
            grad = self.delta_weight * nd_y * self.delta + self.gamma_weight * (ng_y - gamma_target) * self.gamma
            grad += 2.0 * self.lambda_vacuum * y / (self.depth + self.epsilon)
            z = y - step * grad
            # Proximal operator of weighted L1 followed by box projection.
            u_new = np.sign(z) * np.maximum(np.abs(z) - step * linear, 0.0)
            u_new = np.clip(u_new, -self.bounds, self.bounds)
            if float(np.max(np.abs(u_new - u))) <= self.tol * max(1.0, float(np.max(np.abs(u_new)))):
                u = u_new; converged = True; break
            t_new = 0.5 * (1.0 + math.sqrt(1.0 + 4.0 * t_acc * t_acc))
            y = u_new + ((t_acc - 1.0) / t_new) * (u_new - u)
            u = u_new; t_acc = t_new
        nd = initial_delta + float(self.delta @ u); ng = initial_gamma + float(self.gamma @ u)
        return HedgeResult(tuple(map(float, u)), self.objective(u, initial_delta, initial_gamma, gamma_target),
                           nd, ng, float(gamma_target), converged, it, abs(nd) <= 1e-4)

# ----------------------- Throttler, paper ledger and agent squad --------------------
class AntiOvertiltThrottler:
    def __init__(self, max_daily_trades: int = 15, loss_limit: int = 3, cooldown_seconds: float = 900.0,
                 base_cooldown: float = 900.0, theta_rough: float = 0.0, sigma_baseline: float = 1.0) -> None:
        if max_daily_trades < 0 or loss_limit < 1 or cooldown_seconds < 0 or base_cooldown < 0 or theta_rough < 0 or sigma_baseline <= 0:
            raise ValueError("invalid throttler settings")
        self.max_daily_trades = max_daily_trades; self.loss_limit = loss_limit; self.cooldown_seconds = cooldown_seconds
        self.base_cooldown = base_cooldown; self.theta_rough = theta_rough; self.sigma_baseline = sigma_baseline
        self.trade_count = 0; self.loss_streak = 0; self.last_fill_time: Optional[float] = None; self.last_size: Optional[float] = None
        self.locked_until = 0.0; self.lock_reason = ""; self.day_key: Optional[str] = None
    def dynamic_cooldown(self, sigma_rough: float) -> float:
        if not math.isfinite(sigma_rough) or sigma_rough < 0: raise ValueError("rough sigma must be nonnegative")
        return self.base_cooldown * (1.0 + self.theta_rough * sigma_rough / self.sigma_baseline)
    def _lock(self, now: float, reason: str, duration: Optional[float] = None) -> None:
        if not math.isfinite(now): raise ValueError("time must be finite")
        span = self.cooldown_seconds if duration is None else duration
        self.locked_until = max(self.locked_until, now + span); self.lock_reason = reason
    def can_enter(self, now: float, sigma_rough: float = 0.0) -> tuple[bool, str]:
        if not math.isfinite(now): return False, "invalid_time"
        if now < self.locked_until: return False, self.lock_reason or "cooldown"
        if self.trade_count >= self.max_daily_trades: return False, "daily_trade_cap"
        return True, "ok"
    def record_fill(self, now: float, size: float, pnl: float, sigma_rough: float = 0.0) -> bool:
        if not all(math.isfinite(x) for x in (now, size, pnl)) or size <= 0: raise ValueError("invalid fill data")
        if self.last_fill_time is not None and now < self.last_fill_time: raise ValueError("fill timestamps must be nondecreasing")
        reason = ""
        if self.last_size is not None and size / self.last_size > 1.25: reason = "revenge_sizing"
        if self.last_fill_time is not None and now - self.last_fill_time < 30.0: reason = reason or "rapid_pacing"
        self.trade_count += 1
        self.loss_streak = self.loss_streak + 1 if pnl < 0 else 0
        if self.loss_streak >= self.loss_limit: reason = reason or "loss_streak"
        self.last_fill_time = now; self.last_size = size
        if reason:
            self._lock(now, reason, max(self.cooldown_seconds, self.dynamic_cooldown(sigma_rough)))
            return True
        return False
    def reset_day(self, day_key: str) -> None:
        if not day_key: raise ValueError("day_key cannot be empty")
        if day_key != self.day_key:
            self.day_key = day_key; self.trade_count = 0; self.loss_streak = 0; self.last_fill_time = None; self.last_size = None
            self.locked_until = 0.0; self.lock_reason = ""

@dataclass(frozen=True)
class TradeCandidate:
    name: str
    gross_alpha: float
    legs: tuple[TradeLeg, ...]
    slippage: float = 0.0
    impact_hurdle: float = 0.0
    risk_reserve: float = 0.0
    notional: float = 0.0
    expected_adverse_slippage: float = 0.0
    fill_probability: float = 0.0
    def __post_init__(self) -> None:
        for x in (self.gross_alpha, self.slippage, self.impact_hurdle, self.risk_reserve, self.notional,
                  self.expected_adverse_slippage, self.fill_probability):
            if not math.isfinite(x): raise ValueError("candidate numeric fields must be finite")
        if min(self.slippage, self.impact_hurdle, self.risk_reserve, self.notional, self.expected_adverse_slippage) < 0:
            raise ValueError("candidate costs/size must be nonnegative")
        if not 0 <= self.fill_probability <= 1: raise ValueError("fill_probability must be in [0,1]")

@dataclass(frozen=True)
class SquadDecision:
    approved: bool
    net_alpha: float
    costs: FeeBreakdown
    votes: Mapping[str, bool]
    reasons: tuple[str, ...]
    def as_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "net_alpha": self.net_alpha, "costs": asdict(self.costs),
                "votes": dict(self.votes), "reasons": list(self.reasons)}

class ManagerAbhi:
    name = "Manager Abhi"
    def receive_operator_intent(self, candidate: TradeCandidate) -> TradeCandidate:
        """Single public intent ingress; the other role checks only score that intent."""
        if not isinstance(candidate, TradeCandidate):
            raise TypeError("operator intent must be a TradeCandidate")
        return candidate
    def approve(self, candidate: TradeCandidate, capital: float, live: bool = False) -> tuple[bool, str]:
        if live or LIVE_ORDER_DISPATCH_ENABLED: return False, "manager_veto_live_dispatch_locked"
        if not math.isfinite(capital) or capital < 0: return False, "manager_veto_invalid_capital"
        if candidate.notional > capital: return False, "manager_veto_capital_limit"
        return True, "manager_paper_capital_ok"
class AlexMicrostructure:
    name = "Alex"
    def approve(self, candidate: TradeCandidate, friction: float) -> tuple[bool, str]:
        if candidate.fill_probability > 0.85 and candidate.expected_adverse_slippage > friction:
            return False, "alex_veto_toxic_queue"
        return True, "alex_queue_risk_acceptable"
class EmilyRoughVolatility:
    name = "Emily"
    def approve(self, candidate: TradeCandidate, surface_valid: bool = True, covariance_valid: bool = True) -> tuple[bool, str]:
        if not surface_valid: return False, "emily_veto_surface_invalid"
        if not covariance_valid: return False, "emily_veto_covariance_invalid"
        return True, "emily_model_checks_pass"
class MaxRiskStatutory:
    name = "Max"
    @staticmethod
    def bayesian_kelly_fraction(posterior_mean: float, posterior_variance: float,
                                uncertainty_penalty: float = 1.0, max_fraction: float = 0.10) -> float:
        """Conservative posterior-Kelly approximation: (mu - c*sd)/variance, clipped.

        This is a sizing heuristic, not an estimate of a validated trading edge.
        """
        vals = (posterior_mean, posterior_variance, uncertainty_penalty, max_fraction)
        if not all(math.isfinite(x) for x in vals): raise ValueError("Kelly inputs must be finite")
        if posterior_variance <= 0 or uncertainty_penalty < 0 or not 0 <= max_fraction <= 1:
            raise ValueError("invalid Kelly variance/penalty/cap")
        adjusted = posterior_mean - uncertainty_penalty * math.sqrt(posterior_variance)
        return float(min(max_fraction, max(0.0, adjusted / posterior_variance)))
    def approve(self, candidate: TradeCandidate, fee_calculator: StatutoryCostCalculator) -> tuple[bool, str, FeeBreakdown, float]:
        costs = fee_calculator.calculate(candidate.legs)
        net = candidate.gross_alpha - costs.total - candidate.slippage - candidate.impact_hurdle - candidate.risk_reserve
        return net > 0, ("max_net_alpha_positive" if net > 0 else "max_veto_nonpositive_net_alpha"), costs, net

class FourAgentSquad:
    """Deterministic role-based consensus rules; these are not separate autonomous LLMs."""
    def __init__(self, fees: Optional[StatutoryCostCalculator] = None) -> None:
        self.fees = fees or StatutoryCostCalculator()
        self.manager = ManagerAbhi(); self.alex = AlexMicrostructure(); self.emily = EmilyRoughVolatility(); self.max = MaxRiskStatutory()
    def evaluate(self, candidate: TradeCandidate, capital: float, *, live: bool = False,
                 surface_valid: bool = True, covariance_valid: bool = True) -> SquadDecision:
        max_ok, max_reason, costs, net = self.max.approve(candidate, self.fees)
        alex_ok, alex_reason = self.alex.approve(candidate, costs.total + candidate.slippage + candidate.impact_hurdle)
        emily_ok, emily_reason = self.emily.approve(candidate, surface_valid, covariance_valid)
        manager_ok, manager_reason = self.manager.approve(candidate, capital, live)
        votes = {self.manager.name: manager_ok, self.alex.name: alex_ok, self.emily.name: emily_ok, self.max.name: max_ok}
        reasons = (manager_reason, alex_reason, emily_reason, max_reason)
        return SquadDecision(all(votes.values()), float(net), costs, votes, reasons)

class PaperLedger:
    def __init__(self, initial_capital: float = INITIAL_CAPITAL_INR, epoch: str = PAPER_LEDGER_EPOCH) -> None:
        if not math.isfinite(initial_capital) or initial_capital < 0 or epoch != PAPER_LEDGER_EPOCH:
            raise ValueError("invalid paper ledger setup")
        self.initial_capital = float(initial_capital); self.cash = float(initial_capital); self.epoch = epoch
        self.realized_pnl = 0.0; self.events: list[dict[str, Any]] = []
    @property
    def equity(self) -> float: return self.cash + self.realized_pnl
    def record_paper_outcome(self, candidate: TradeCandidate, net_alpha: float, now: float) -> None:
        if not math.isfinite(net_alpha) or not math.isfinite(now): raise ValueError("invalid paper outcome")
        # The expected alpha is a scenario PnL only when a synthetic outcome is explicitly supplied.
        self.realized_pnl += net_alpha
        self.events.append({"time": now, "candidate": candidate.name, "simulated_net_pnl": net_alpha, "ledger_epoch": self.epoch})

def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    raise PermissionError("live order dispatch permanently disabled; paper simulation only")

# ----------------------- unified engine + telemetry server --------------------------
class Cycle41ExecutionEngine:
    def __init__(self, *, rough_model: Optional[MultiAssetRoughVolterraCovariance] = None,
                 hawkes: Optional[HawkesLeadLagGraph] = None, queue: Optional[L3QueueDepletionMachine] = None,
                 hedger: Optional[MultiHorizonGammaHedger] = None, throttler: Optional[AntiOvertiltThrottler] = None,
                 squad: Optional[FourAgentSquad] = None, ledger: Optional[PaperLedger] = None) -> None:
        self.rough = rough_model or MultiAssetRoughVolterraCovariance()
        self.hawkes = hawkes or HawkesLeadLagGraph()
        self.queue = queue or L3QueueDepletionMachine()
        self.hedger = hedger or MultiHorizonGammaHedger([
            OptionInstrument("NIFTY_WEEKLY_CALL", .45, .02, 2.0, 1000, 10, 7),
            OptionInstrument("NIFTY_WEEKLY_PUT", -.45, .02, 2.2, 850, 10, 7),
            OptionInstrument("BANKNIFTY_NEXT_WEEK_CALL", .55, .03, 3.4, 300, 6, 14),
            OptionInstrument("BANKNIFTY_NEXT_WEEK_PUT", -.55, .03, 3.6, 250, 6, 14),
        ])
        self.throttler = throttler or AntiOvertiltThrottler()
        self.squad = squad or FourAgentSquad()
        self.ledger = ledger or PaperLedger()
        self._last_candidate: Optional[dict[str, Any]] = None
        self._last_hedge: Optional[HedgeResult] = None
        self._risk_state = "IDLE"
        self._emergency_latched = False
        self._recovery_ready = False
        self._lock = threading.RLock()
    def submit_operator_intent(self, candidate: TradeCandidate, now: float, *, surface_valid: bool = True,
                               covariance_valid: bool = True) -> SquadDecision:
        # Operator-facing intent enters through Manager Abhi only.
        candidate = self.squad.manager.receive_operator_intent(candidate)
        return self.evaluate_candidate(candidate, now, surface_valid=surface_valid, covariance_valid=covariance_valid)
    def evaluate_candidate(self, candidate: TradeCandidate, now: float, *, surface_valid: bool = True,
                           covariance_valid: bool = True) -> SquadDecision:
        with self._lock:
            allowed, reason = self.throttler.can_enter(now)
            if self._emergency_latched:
                costs = self.squad.fees.calculate(candidate.legs)
                d = SquadDecision(False, 0.0, costs, {"Manager Abhi": False, "Alex": False, "Emily": False, "Max": False},
                                  ("emergency_latched",))
            elif not allowed:
                costs = self.squad.fees.calculate(candidate.legs)
                net = candidate.gross_alpha - costs.total - candidate.slippage - candidate.impact_hurdle - candidate.risk_reserve
                d = SquadDecision(False, float(net), costs, {"Manager Abhi": True, "Alex": True, "Emily": True, "Max": False}, (reason,))
            else:
                d = self.squad.evaluate(candidate, self.ledger.equity, surface_valid=surface_valid, covariance_valid=covariance_valid)
            self._last_candidate = {"name": candidate.name, "approved": d.approved, "net_alpha": d.net_alpha,
                                    "costs": asdict(d.costs), "votes": dict(d.votes), "reasons": list(d.reasons)}
            return d
    def optimize_hedge(self, initial_delta: float, initial_gamma: float, gamma_target: float) -> HedgeResult:
        result = self.hedger.optimize(initial_delta, initial_gamma, gamma_target)
        with self._lock: self._last_hedge = result
        return result
    def record_paper_outcome(self, candidate: TradeCandidate, decision: SquadDecision, now: float,
                             realized_net_pnl: float, size: float = 1.0, rough_sigma: float = 0.0) -> bool:
        if not decision.approved: raise PermissionError("cannot record outcome for rejected paper candidate")
        # Do not turn a forecast into a PnL automatically; caller supplies synthetic/observed outcome explicitly.
        self.ledger.record_paper_outcome(candidate, realized_net_pnl, now)
        triggered = self.throttler.record_fill(now, size, realized_net_pnl, rough_sigma)
        if triggered: self._risk_state = "OVERTRADING_LOCKED"
        return triggered
    def emergency(self, reason: str = "emergency") -> None:
        with self._lock: self._emergency_latched = True; self._recovery_ready = False; self._risk_state = "EMERGENCY_UNWIND"; self._emergency_reason = str(reason)
    def verify_recovery(self, verified: bool) -> None:
        with self._lock: self._recovery_ready = bool(verified)
    def recovery_ack(self) -> None:
        with self._lock:
            if not self._emergency_latched: raise RuntimeError("no emergency latch is active")
            if not self._recovery_ready: raise PermissionError("independent recovery verification required")
            self._emergency_latched = False; self._risk_state = "IDLE"
    def dispatch_live_order(self, *args: Any, **kwargs: Any) -> None:
        dispatch_live_order(*args, **kwargs)
    def telemetry(self) -> dict[str, Any]:
        with self._lock:
            snap = self.rough.last_snapshot
            now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
            return {
                "timestamp_ist": now.isoformat(), "epoch_seconds": time.time(),
                "assets": list(ASSETS), "rough_volterra": {"hurst": list(map(float, self.rough.hurst)),
                    "factor_count": self.rough.n_factors, "variances": list(snap.variances),
                    "covariance": [list(x) for x in snap.covariance], "min_covariance_eigenvalue": snap.min_covariance_eigenvalue,
                    "kernel_relative_errors": list(snap.kernel_relative_errors)},
                "hawkes": {"baseline": list(map(float, self.hawkes.mu)), "intensity": list(map(float, self.hawkes.intensity())),
                    "branching": self.hawkes.branching.tolist(), "spectral_radius": self.hawkes.spectral_radius(),
                    "centralities": self.hawkes.centralities(), "leadership_matrix": self.hawkes.leadership_matrix().tolist()},
                "queue": {"active_orders": sum(1 for o in self.queue.orders.values() if o.active),
                    "cancel_intensity": self.queue.cancel_intensity(), "shock_ages": list(self.queue.shock_ages),
                    "order_states": {k: asdict(v) for k, v in self.queue.orders.items()}},
                "hedge": None if self._last_hedge is None else self._last_hedge.as_dict(),
                "candidate": self._last_candidate, "risk_state": self._risk_state,
                "throttler": {"trade_count": self.throttler.trade_count, "loss_streak": self.throttler.loss_streak,
                    "locked_until": self.throttler.locked_until, "lock_reason": self.throttler.lock_reason,
                    "max_daily_trades": self.throttler.max_daily_trades},
                "paper_ledger": {"epoch": self.ledger.epoch, "initial_capital": self.ledger.initial_capital,
                    "cash": self.ledger.cash, "realized_pnl": self.ledger.realized_pnl, "equity": self.ledger.equity},
                "safety": {"LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
                    "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED, "paper_only": True,
                    "emergency_latched": self._emergency_latched},
            }

class TelemetryHTTPServer:
    def __init__(self, engine: Cycle41ExecutionEngine, host: str = "127.0.0.1", port: int = 8088) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}: raise ValueError("dashboard must bind to loopback")
        self.engine = engine; self.host = host; self.port = int(port); self._httpd: Optional[ThreadingHTTPServer] = None; self._thread: Optional[threading.Thread] = None
    def _handler(self):
        engine = self.engine
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, format: str, *args: Any) -> None: return
            def do_GET(self):
                if self.path not in {"/health", "/telemetry", "/events"}:
                    body = b'{"error":"not_found"}'
                    self.send_response(404); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
                if self.path == "/health": payload = {"status": "ok", "paper_only": True, "live_order_dispatch_enabled": False}
                else: payload = engine.telemetry()
                try:
                    if self.path == "/events":
                        body = ("retry: 1000\nevent: telemetry\ndata: " + json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n\n").encode()
                        self.send_response(200); self.send_header("Content-Type", "text/event-stream; charset=utf-8"); self.send_header("Cache-Control", "no-cache"); self.send_header("Connection", "close"); self.end_headers(); self.wfile.write(body); self.wfile.flush(); self.close_connection = True
                    else:
                        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
                        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError): pass
        return Handler
    def start(self) -> None:
        if self._httpd is not None: return
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._handler()); self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="cycle41-telemetry", daemon=True); self._thread.start()
    def close(self) -> None:
        if self._httpd is not None: self._httpd.shutdown(); self._httpd.server_close(); self._httpd = None
        if self._thread is not None: self._thread.join(timeout=2); self._thread = None

__all__ = ["LIVE_ORDER_DISPATCH_ENABLED", "REAL_BROKER_FILLS_LOCKED", "PAPER_LEDGER_EPOCH", "INITIAL_CAPITAL_INR", "ASSETS",
"StatutoryConfig", "TradeLeg", "FeeBreakdown", "StatutoryCostCalculator", "VolterraSnapshot", "MultiAssetRoughVolterraCovariance",
"HawkesLeadLagGraph", "QueueOrder", "L3QueueDepletionMachine", "OptionInstrument", "HedgeResult", "MultiHorizonGammaHedger",
"AntiOvertiltThrottler", "TradeCandidate", "SquadDecision", "ManagerAbhi", "AlexMicrostructure", "EmilyRoughVolatility", "MaxRiskStatutory",
"FourAgentSquad", "PaperLedger", "dispatch_live_order", "Cycle41ExecutionEngine", "TelemetryHTTPServer"]
