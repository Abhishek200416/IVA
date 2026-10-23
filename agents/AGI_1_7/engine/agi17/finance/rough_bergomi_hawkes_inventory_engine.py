"""Cycle 40 offline research engine: rough Bergomi, Hawkes market making, VG strips.

This module intentionally does not contain a broker connector or live order path.
The numerical models are research approximations; calibrate and validate before use.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
from scipy.integrate import quad
from scipy.optimize import nnls

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
PAPER_INITIAL_CAPITAL = 10_000.0
IST = ZoneInfo("Asia/Kolkata")
EPS = 1e-12


def _finite_float(value: float, name: str) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _finite_array(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be finite")
    return arr


def _json_safe(value: Any) -> Any:
    """Convert numpy and dataclass objects to strict JSON-compatible values."""
    if hasattr(value, "__dataclass_fields__"):
        return _json_safe(asdict(value))
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def strict_json_dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), allow_nan=False, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Rough Bergomi / Markovian lift
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RoughKernelDiagnostics:
    hurst: float
    factors: int
    max_abs_kernel_error: float
    max_relative_kernel_error: float
    half_life_seconds: float


class RoughBergomiLift:
    """Positive sum-of-exponentials approximation to a rough Volterra kernel.

    A common Brownian innovation drives all exponential factors. This is a
    compact Markovian-lift research approximation, not an exact rBergomi solver.
    """
    def __init__(self, hurst: float = 0.07, eta: float = 1.5,
                 xi0: float | Callable[[float], float] = 0.04,
                 n_factors: int = 12, horizon: float = 1.0,
                 t_min: float = 1e-4, fit_points: int = 360, seed: int = 7):
        if not (0.0 < hurst < 0.5):
            raise ValueError("hurst must be in (0, 0.5)")
        if eta < 0 or not math.isfinite(eta):
            raise ValueError("eta must be finite and nonnegative")
        if n_factors < 8:
            raise ValueError("n_factors must be >= 8")
        if horizon <= 0 or t_min <= 0 or t_min >= horizon:
            raise ValueError("require 0 < t_min < horizon")
        if fit_points < 32:
            raise ValueError("fit_points must be >= 32")
        self.hurst = float(hurst)
        self.eta = float(eta)
        self.xi0 = xi0
        self.n_factors = int(n_factors)
        self.horizon = float(horizon)
        self.t_min = float(t_min)
        self.rng = np.random.default_rng(seed)
        # Geometric decay rates resolve both rapid short-lag and slow long-lag memory.
        self.gamma = np.geomspace(1.0 / self.horizon, 1.0 / self.t_min, self.n_factors)
        t_fit = np.geomspace(self.t_min, self.horizon, int(fit_points))
        target = self.kernel(t_fit)
        design = np.exp(-np.outer(t_fit, self.gamma))
        self.omega, _ = nnls(design, target)
        # A positive floor keeps every factor represented if NNLS drives a tiny term to 0.
        self.omega = np.maximum(self.omega, 1e-14)
        fitted = design @ self.omega
        abs_err = np.abs(fitted - target)
        rel_err = abs_err / np.maximum(np.abs(target), 1e-15)
        self.diagnostics = RoughKernelDiagnostics(
            hurst=self.hurst, factors=self.n_factors,
            max_abs_kernel_error=float(np.max(abs_err)),
            max_relative_kernel_error=float(np.max(rel_err)),
            half_life_seconds=float(math.log(2.0) / np.min(self.gamma)),
        )
        self.states = np.zeros(self.n_factors, dtype=float)
        self.time = 0.0
        self.last_driver = 0.0
        self.last_variance = self._xi0_at(0.0)

    def kernel(self, t: float | Sequence[float] | np.ndarray) -> float | np.ndarray:
        arr = np.asarray(t, dtype=float)
        if not np.all(np.isfinite(arr)) or np.any(arr < 0):
            raise ValueError("kernel time must be finite and nonnegative")
        # The mathematical kernel is singular at zero for H < 1/2; expose inf there.
        out = np.empty_like(arr, dtype=float)
        positive = arr > 0
        out[positive] = np.power(arr[positive], self.hurst - 0.5) / math.gamma(self.hurst + 0.5)
        out[~positive] = math.inf
        return float(out) if out.ndim == 0 else out

    def approximate_kernel(self, t: float | Sequence[float] | np.ndarray) -> float | np.ndarray:
        arr = np.asarray(t, dtype=float)
        if not np.all(np.isfinite(arr)) or np.any(arr < 0):
            raise ValueError("kernel time must be finite and nonnegative")
        out = np.exp(-np.outer(arr.reshape(-1), self.gamma)) @ self.omega
        out = out.reshape(arr.shape)
        return float(out) if out.ndim == 0 else out

    def _xi0_at(self, t: float) -> float:
        val = self.xi0(t) if callable(self.xi0) else self.xi0
        val = _finite_float(val, "xi0")
        if val <= 0:
            raise ValueError("xi0(t) must be positive")
        return val

    @property
    def memory_half_life(self) -> float:
        return math.log(2.0) / float(np.min(self.gamma))

    @property
    def rough_variance(self) -> float:
        return float(self.last_variance)

    def advance(self, dt: float, brownian_z: float | None = None,
                xi0: float | None = None) -> dict[str, float]:
        dt = _finite_float(dt, "dt")
        if dt <= 0:
            raise ValueError("dt must be positive")
        z = float(self.rng.normal()) if brownian_z is None else _finite_float(brownian_z, "brownian_z")
        decay = np.exp(-self.gamma * dt)
        # Exact OU marginal innovation factors, sharing a Brownian shock as a lift approximation.
        innovation_sd = np.sqrt(np.maximum((1.0 - np.exp(-2.0 * self.gamma * dt)) / (2.0 * self.gamma), 0.0))
        self.states = decay * self.states + innovation_sd * z
        self.time += dt
        self.last_driver = float(math.sqrt(2.0 * self.hurst) * np.dot(self.omega, self.states))
        base = self._xi0_at(self.time) if xi0 is None else _finite_float(xi0, "xi0")
        if base <= 0:
            raise ValueError("xi0 must be positive")
        exponent = self.eta * self.last_driver - 0.5 * self.eta**2 * self.time**(2.0 * self.hurst)
        self.last_variance = float(base * math.exp(max(-60.0, min(60.0, exponent))))
        return {"time": self.time, "driver": self.last_driver, "variance": self.last_variance}

    def variance_at(self, t: float, driver: float | None = None, xi0: float | None = None) -> float:
        t = _finite_float(t, "t")
        if t < 0:
            raise ValueError("t must be nonnegative")
        d = self.last_driver if driver is None else _finite_float(driver, "driver")
        base = self._xi0_at(t) if xi0 is None else _finite_float(xi0, "xi0")
        if base <= 0:
            raise ValueError("xi0 must be positive")
        e = self.eta * d - 0.5 * self.eta**2 * t**(2.0 * self.hurst)
        return base * math.exp(max(-60.0, min(60.0, e)))

    def atm_skew_scaling(self, tau: float, scale: float = 1.0) -> float:
        tau = _finite_float(tau, "tau")
        scale = _finite_float(scale, "scale")
        if tau <= 0:
            raise ValueError("tau must be positive")
        return scale * tau**(self.hurst - 0.5)

    @staticmethod
    def roger_lee_wing_variance(log_moneyness: float, atm_variance: float,
                                wing_slope: float) -> float:
        k = _finite_float(log_moneyness, "log_moneyness")
        atm = _finite_float(atm_variance, "atm_variance")
        slope = _finite_float(wing_slope, "wing_slope")
        if atm < 0 or slope < 0 or slope > 2.0:
            raise ValueError("require atm_variance >= 0 and wing_slope in [0, 2]")
        return atm + slope * abs(k)


# ---------------------------------------------------------------------------
# Four-node Hawkes graph and market-maker spread optimization
# ---------------------------------------------------------------------------
DEFAULT_ASSETS = ("NIFTY50", "BANKNIFTY", "HDFCBANK", "RELIANCE")


class HawkesGraph4:
    """Four-node Hawkes process with nonnegative subcritical branching matrix."""
    def __init__(self, mu: Sequence[float] = (0.20, 0.22, 0.25, 0.18),
                 alpha: Sequence[Sequence[float]] | None = None,
                 beta: Sequence[Sequence[float]] | Sequence[float] = (2.0, 2.2, 2.4, 2.1),
                 assets: Sequence[str] = DEFAULT_ASSETS, stability_limit: float = 0.88):
        self.assets = tuple(assets)
        self.n = len(self.assets)
        if self.n != 4:
            raise ValueError("Cycle 40 Hawkes graph expects exactly four assets")
        self.mu = _finite_array(mu, "mu", 1)
        if self.mu.shape != (4,) or np.any(self.mu <= 0):
            raise ValueError("mu must be a positive vector of length four")
        if not (0 < stability_limit < 1):
            raise ValueError("stability_limit must be in (0, 1)")
        self.stability_limit = float(stability_limit)
        if alpha is None:
            alpha_arr = np.array([[0.0, .08, .05, .03], [.06, 0.0, .07, .04], [.04, .07, 0.0, .03], [.03, .04, .04, 0.0]], dtype=float)
        else:
            alpha_arr = _finite_array(alpha, "alpha", 2)
        if alpha_arr.shape != (4, 4) or np.any(alpha_arr < 0):
            raise ValueError("alpha must be a nonnegative 4x4 matrix")
        beta_arr = np.asarray(beta, dtype=float)
        if beta_arr.ndim == 1:
            if beta_arr.shape != (4,):
                raise ValueError("beta vector must have length four")
            beta_arr = np.tile(beta_arr.reshape(1, 4), (4, 1))
        beta_arr = _finite_array(beta_arr, "beta", 2)
        if beta_arr.shape != (4, 4) or np.any(beta_arr <= 0):
            raise ValueError("beta must be positive 4-vector or 4x4 matrix")
        self.beta = beta_arr.copy()
        self.alpha = self._contract(alpha_arr.copy())
        self.excitation = np.zeros((4, 4), dtype=float)
        self.intensities = self.mu.copy()
        self.elapsed = 0.0

    def branching_matrix(self) -> np.ndarray:
        return self.alpha / self.beta

    @staticmethod
    def _rho(matrix: np.ndarray) -> float:
        vals = np.linalg.eigvals(matrix)
        return float(np.max(np.abs(vals)))

    @property
    def spectral_radius(self) -> float:
        return self._rho(self.branching_matrix())

    def _contract(self, alpha: np.ndarray) -> np.ndarray:
        rho = self._rho(alpha / self.beta)
        target = self.stability_limit - 1e-6
        if rho >= target and rho > 0:
            alpha *= target / rho
        return alpha

    def set_alpha(self, alpha: Sequence[Sequence[float]]) -> float:
        arr = _finite_array(alpha, "alpha", 2)
        if arr.shape != (4, 4) or np.any(arr < 0):
            raise ValueError("alpha must be a nonnegative 4x4 matrix")
        self.alpha = self._contract(arr.copy())
        return self.spectral_radius

    def update(self, dt: float, events: Sequence[int | float]) -> np.ndarray:
        dt = _finite_float(dt, "dt")
        e = _finite_array(events, "events", 1)
        if dt <= 0 or e.shape != (4,) or np.any(e < 0):
            raise ValueError("dt positive; events must be nonnegative length four")
        self.excitation *= np.exp(-self.beta * dt)
        # Rows are recipient i, columns are source j.
        self.excitation += self.alpha * e.reshape(1, 4)
        self.elapsed += dt
        self.intensities = self.mu + np.sum(self.excitation, axis=1)
        return self.intensities.copy()

    def online_sgd(self, dt: float, events: Sequence[int | float], learning_rate: float = 1e-3) -> float:
        """Small projected pseudo-likelihood step; illustrative online calibration."""
        dt = _finite_float(dt, "dt")
        e = _finite_array(events, "events", 1)
        lr = _finite_float(learning_rate, "learning_rate")
        if dt <= 0 or e.shape != (4,) or np.any(e < 0) or lr <= 0:
            raise ValueError("invalid online SGD inputs")
        lam = np.maximum(self.intensities, 1e-9)
        residual = e - lam * dt
        self.mu = np.maximum(1e-6, self.mu + lr * residual)
        score = residual.reshape(4, 1) * (self.excitation / np.maximum(lam.reshape(4, 1), 1e-9))
        self.alpha = np.maximum(0.0, self.alpha + lr * score)
        self.alpha = self._contract(self.alpha)
        return self.spectral_radius

    def centrality(self) -> dict[str, dict[str, float]]:
        # Incoming entries absorb information; columns propagate to recipients.
        a = self.alpha
        incoming = np.sum(a, axis=1)
        outgoing = np.sum(a, axis=0)
        in_norm = incoming / max(float(np.max(incoming)), EPS)
        out_norm = outgoing / max(float(np.max(outgoing)), EPS)
        return {name: {"in_degree_absorption": float(in_norm[i]),
                       "out_degree_spillover": float(out_norm[i])}
                for i, name in enumerate(self.assets)}


@dataclass(frozen=True)
class QuotePlan:
    reservation_price: float
    half_spread: float
    bid: float
    ask: float
    hawkes_widening: float


class HawkesMarketMaker:
    def __init__(self, risk_aversion: float = 0.1, order_book_kappa: float = 1.2,
                 hawkes_spread_scale: float = 0.08, min_half_spread: float = 0.05):
        self.gamma = _finite_float(risk_aversion, "risk_aversion")
        self.kappa = _finite_float(order_book_kappa, "order_book_kappa")
        self.hawkes_scale = _finite_float(hawkes_spread_scale, "hawkes_spread_scale")
        self.min_half_spread = _finite_float(min_half_spread, "min_half_spread")
        if self.gamma <= 0 or self.kappa <= 0 or self.hawkes_scale < 0 or self.min_half_spread < 0:
            raise ValueError("invalid market maker parameters")

    def quote(self, mid: float, inventory: float, volatility: float, horizon: float,
              hawkes_intensity: float, tick: float = 0.05) -> QuotePlan:
        mid = _finite_float(mid, "mid")
        q = _finite_float(inventory, "inventory")
        sig = _finite_float(volatility, "volatility")
        T = _finite_float(horizon, "horizon")
        lam = _finite_float(hawkes_intensity, "hawkes_intensity")
        tick = _finite_float(tick, "tick")
        if mid <= 0 or sig < 0 or T < 0 or lam < 0 or tick <= 0:
            raise ValueError("invalid quote inputs")
        reservation = mid - q * self.gamma * sig**2 * T
        base = math.log(1.0 + self.gamma / self.kappa) / self.gamma + 0.5 * self.gamma * sig**2 * T
        widening = 1.0 + self.hawkes_scale * lam
        half = max(self.min_half_spread, base * widening)
        half = math.ceil(half / tick - 1e-12) * tick
        bid = max(0.0, reservation-half)
        ask = max(bid + tick, reservation+half)
        return QuotePlan(reservation, half, bid, ask, widening)


# ---------------------------------------------------------------------------
# Level 3 queue depletion and adverse selection
# ---------------------------------------------------------------------------
@dataclass
class QueueOrder:
    order_id: str
    level: int
    side: str
    quantity: float
    ahead: float
    behind: float = 0.0
    filled: float = 0.0
    state: str = "RESTING"

    @property
    def remaining(self) -> float:
        return max(0.0, self.quantity - self.filled)


class L3QueueMachine:
    def __init__(self, levels: int = 5):
        if levels != 5:
            raise ValueError("Cycle 40 queue model expects L1-L5")
        self.levels = 5
        self.orders: dict[str, QueueOrder] = {}
        self.last_pullback = False
        self.last_fill_probability = 0.0

    def add_order(self, order_id: str, level: int, side: str, quantity: float,
                  ahead: float, behind: float = 0.0) -> QueueOrder:
        if not order_id or order_id in self.orders:
            raise ValueError("order_id must be nonempty and unique")
        if level not in range(1, 6) or side.upper() not in {"BUY", "SELL"}:
            raise ValueError("level must be 1..5 and side BUY/SELL")
        q, a, b = map(float, (quantity, ahead, behind))
        if not all(math.isfinite(x) for x in (q, a, b)) or q <= 0 or a < 0 or b < 0:
            raise ValueError("queue quantities must be finite; quantity positive")
        order = QueueOrder(order_id, level, side.upper(), q, a, b)
        self.orders[order_id] = order
        return order

    def cancel_ahead(self, order_id: str, quantity: float) -> float:
        order = self._get_resting(order_id)
        amount = _finite_float(quantity, "quantity")
        if amount < 0:
            raise ValueError("quantity cannot be negative")
        removed = min(order.ahead, amount)
        order.ahead -= removed
        return removed

    def trade_through(self, order_id: str, quantity: float) -> float:
        order = self._get_resting(order_id)
        amount = _finite_float(quantity, "quantity")
        if amount < 0:
            raise ValueError("quantity cannot be negative")
        consume = amount
        if order.ahead > 0:
            dec = min(order.ahead, consume)
            order.ahead -= dec
            consume -= dec
        fill = min(order.remaining, consume)
        order.filled += fill
        if order.remaining <= EPS:
            order.state = "FILLED"
        return fill

    def cancel_order(self, order_id: str) -> None:
        if order_id not in self.orders:
            raise KeyError(order_id)
        order = self.orders[order_id]
        if order.state == "RESTING":
            order.state = "CANCELLED"

    def _get_resting(self, order_id: str) -> QueueOrder:
        if order_id not in self.orders:
            raise KeyError(order_id)
        order = self.orders[order_id]
        if order.state != "RESTING":
            raise ValueError("order is not resting")
        return order

    @staticmethod
    def cancellation_intensity(base: float, events: Sequence[tuple[float, float, float]],
                               t: float, gamma_ofi: float = 0.0, ofi: float = 0.0) -> float:
        base, t, gamma_ofi, ofi = map(float, (base, t, gamma_ofi, ofi))
        if base < 0 or t < 0 or gamma_ofi < 0 or not all(math.isfinite(x) for x in (base, t, gamma_ofi, ofi)):
            raise ValueError("invalid cancellation intensity parameters")
        intensity = base + gamma_ofi * max(0.0, -ofi)
        for event_time, alpha, beta in events:
            event_time, alpha, beta = map(float, (event_time, alpha, beta))
            if not all(math.isfinite(x) for x in (event_time, alpha, beta)) or event_time > t or alpha < 0 or beta <= 0:
                raise ValueError("invalid cancellation event")
            intensity += alpha * math.exp(-beta * (t-event_time))
        return max(0.0, intensity)

    @staticmethod
    def survival_probability(tau: float, base: float,
                             events: Sequence[tuple[float, float, float]] = (),
                             gamma_ofi: float = 0.0, ofi: float = 0.0) -> float:
        """Exact integral for base + decaying exponential excitation on [0,tau]."""
        tau, base, gamma_ofi, ofi = map(float, (tau, base, gamma_ofi, ofi))
        if tau < 0 or base < 0 or gamma_ofi < 0 or not all(math.isfinite(x) for x in (tau, base, gamma_ofi, ofi)):
            raise ValueError("invalid survival inputs")
        integrated = (base + gamma_ofi * max(0.0, -ofi)) * tau
        for event_time, alpha, beta in events:
            event_time, alpha, beta = map(float, (event_time, alpha, beta))
            if event_time < 0 or alpha < 0 or beta <= 0 or event_time > tau:
                raise ValueError("invalid event for survival integral")
            integrated += alpha / beta * (1.0 - math.exp(-beta * (tau-event_time)))
        return min(1.0, max(0.0, math.exp(-min(integrated, 745.0))))

    @staticmethod
    def poisson_fill_probability(queue_ahead: int, horizon: float, market_arrival_rate: float,
                                 cancellation_hazard: float = 0.0) -> float:
        if int(queue_ahead) != queue_ahead or queue_ahead < 0:
            raise ValueError("queue_ahead must be a nonnegative integer")
        horizon, rate, hazard = map(float, (horizon, market_arrival_rate, cancellation_hazard))
        if min(horizon, rate, hazard) < 0 or not all(math.isfinite(x) for x in (horizon, rate, hazard)):
            raise ValueError("horizon, rate, and hazard must be nonnegative finite")
        lam = (rate + hazard) * horizon
        if lam == 0:
            return 0.0
        # P(N >= q+1), so all queue_ahead orders are consumed before a fill.
        cdf = sum(math.exp(-lam + k*math.log(lam) - math.lgamma(k+1)) for k in range(queue_ahead+1)) if lam < 700 else 0.0
        return min(1.0, max(0.0, 1.0-cdf))

    def evaluate_pullback(self, order_id: str, horizon: float, market_arrival_rate: float,
                          cancellation_hazard: float, expected_adverse_slippage: float,
                          round_trip_statutory_friction: float, fill_threshold: float = 0.85) -> dict[str, Any]:
        order = self._get_resting(order_id)
        # Use conservative integer count when queue volume has fractional representation.
        q_ahead = max(0, int(math.ceil(order.ahead)))
        p_fill = self.poisson_fill_probability(q_ahead, horizon, market_arrival_rate, cancellation_hazard)
        adverse = _finite_float(expected_adverse_slippage, "expected_adverse_slippage")
        friction = _finite_float(round_trip_statutory_friction, "round_trip_statutory_friction")
        if adverse < 0 or friction < 0 or not 0 <= fill_threshold <= 1:
            raise ValueError("invalid pullback inputs")
        pull = p_fill > fill_threshold and adverse > friction
        self.last_fill_probability = p_fill
        self.last_pullback = pull
        if pull:
            order.state = "PULLBACK"
        return {"order_id": order_id, "fill_probability": p_fill,
                "expected_adverse_slippage": adverse, "round_trip_friction": friction,
                "quote_pullback_immediate": pull, "queue_state": order.state}


# ---------------------------------------------------------------------------
# Indian statutory fees
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OptionLeg:
    side: str
    premium: float
    quantity: float
    brokerage_orders: int = 1


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
    total: float


@dataclass(frozen=True)
class FeeConfig:
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    exchange_rate: float = 3553.0 / 10_000_000.0
    sebi_rate: float = 10.0 / 10_000_000.0
    gst_rate: float = 0.18
    brokerage_per_order: float = 20.0

    def validate(self) -> None:
        rates = (self.stt_sell_rate, self.stamp_buy_rate, self.exchange_rate, self.sebi_rate, self.gst_rate, self.brokerage_per_order)
        if any(not math.isfinite(float(x)) or x < 0 for x in rates):
            raise ValueError("all fee rates and brokerage must be finite and nonnegative")
        if self.gst_rate > 1:
            raise ValueError("GST rate should be represented as a fraction")


class StatutoryCostCalculator:
    def __init__(self, config: FeeConfig = FeeConfig()):
        config.validate()
        self.config = config

    def calculate(self, legs: Sequence[OptionLeg], half_spread_slippage: float = 0.0,
                  impact_hurdle: float = 0.0) -> FeeBreakdown:
        slip = _finite_float(half_spread_slippage, "half_spread_slippage")
        impact = _finite_float(impact_hurdle, "impact_hurdle")
        if slip < 0 or impact < 0:
            raise ValueError("slippage and impact hurdle must be nonnegative")
        buy = sell = brokerage = 0.0
        for leg in legs:
            side = leg.side.upper()
            premium = _finite_float(leg.premium, "premium")
            quantity = _finite_float(leg.quantity, "quantity")
            if side not in {"BUY", "SELL"} or premium < 0 or quantity < 0:
                raise ValueError("invalid option leg")
            if not isinstance(leg.brokerage_orders, int) or leg.brokerage_orders < 0:
                raise ValueError("brokerage_orders must be nonnegative integer")
            turnover = premium * quantity
            if side == "BUY":
                buy += turnover
            else:
                sell += turnover
            brokerage += self.config.brokerage_per_order * leg.brokerage_orders
        total_turnover = buy + sell
        stt = sell * self.config.stt_sell_rate
        stamp = buy * self.config.stamp_buy_rate
        exchange = total_turnover * self.config.exchange_rate
        sebi = total_turnover * self.config.sebi_rate
        gst = (brokerage + exchange + sebi) * self.config.gst_rate
        total = stt + stamp + exchange + sebi + brokerage + gst + slip + impact
        return FeeBreakdown(buy, sell, total_turnover, stt, stamp, exchange, sebi,
                            brokerage, gst, slip, impact, total)


# ---------------------------------------------------------------------------
# Inventory controller and risk checks
# ---------------------------------------------------------------------------
class InventoryRiskController:
    def __init__(self, initial_capital: float = PAPER_INITIAL_CAPITAL,
                 max_abs_inventory: float = 5.0, max_loss: float = 1_000.0):
        self.initial_capital = _finite_float(initial_capital, "initial_capital")
        self.max_abs_inventory = _finite_float(max_abs_inventory, "max_abs_inventory")
        self.max_loss = _finite_float(max_loss, "max_loss")
        if self.initial_capital <= 0 or self.max_abs_inventory <= 0 or self.max_loss <= 0:
            raise ValueError("capital, inventory cap, and max_loss must be positive")
        self.cash = self.initial_capital
        self.inventory = 0.0
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.last_mark_price = 0.0
        self.emergency_latched = False

    @property
    def equity(self) -> float:
        return self.cash + self.inventory * self.last_mark_price

    def approve_inventory_change(self, delta_quantity: float) -> bool:
        dq = _finite_float(delta_quantity, "delta_quantity")
        return not self.emergency_latched and abs(self.inventory + dq) <= self.max_abs_inventory + 1e-12 and self.realized_pnl + self.unrealized_pnl > -self.max_loss

    def apply_paper_fill(self, side: str, quantity: float, price: float, fees: float = 0.0) -> dict[str, float | bool]:
        side = side.upper()
        q, p, fee = map(float, (quantity, price, fees))
        if side not in {"BUY", "SELL"} or not all(math.isfinite(x) for x in (q,p,fee)) or q <= 0 or p <= 0 or fee < 0:
            raise ValueError("invalid paper fill")
        dq = q if side == "BUY" else -q
        if not self.approve_inventory_change(dq):
            return {"accepted": False, "inventory": self.inventory, "cash": self.cash}
        cash_delta = -(q*p) if side == "BUY" else (q*p)
        self.cash += cash_delta - fee
        self.inventory += dq
        self.last_mark_price = p
        self.realized_pnl -= fee
        if self.realized_pnl + self.unrealized_pnl <= -self.max_loss:
            self.emergency_latched = True
        return {"accepted": True, "inventory": self.inventory, "cash": self.cash}

    def mark_to_market(self, spot: float, average_cost: float = 0.0) -> float:
        spot = _finite_float(spot, "spot")
        cost = _finite_float(average_cost, "average_cost")
        if spot < 0:
            raise ValueError("spot must be nonnegative")
        self.last_mark_price = spot
        self.unrealized_pnl = self.inventory * (spot - cost)
        if self.realized_pnl + self.unrealized_pnl <= -self.max_loss:
            self.emergency_latched = True
        return self.unrealized_pnl

    def recovery_ack(self) -> None:
        # Recovery only clears if exposure and losses are back within limits.
        if abs(self.inventory) <= self.max_abs_inventory and self.realized_pnl + self.unrealized_pnl > -self.max_loss:
            self.emergency_latched = False
        else:
            raise RuntimeError("cannot recover while exposure/loss limits remain breached")


class TiltThrottler:
    def __init__(self, max_trades_per_session: int = 15, cooldown_seconds: float = 900.0,
                 max_sizing_ratio: float = 1.25, min_fill_interval: float = 30.0):
        if max_trades_per_session < 1 or cooldown_seconds <= 0 or max_sizing_ratio <= 1 or min_fill_interval <= 0:
            raise ValueError("invalid throttler config")
        self.max_trades = int(max_trades_per_session)
        self.cooldown_seconds = float(cooldown_seconds)
        self.max_sizing_ratio = float(max_sizing_ratio)
        self.min_fill_interval = float(min_fill_interval)
        self.trade_count = 0
        self.consecutive_losses = 0
        self.last_fill_time: float | None = None
        self.last_size: float | None = None
        self.lockout_until = 0.0

    def can_enter(self, now: float) -> bool:
        now = _finite_float(now, "now")
        return self.trade_count < self.max_trades and now >= self.lockout_until

    def record_fill(self, now: float, size: float, pnl: float) -> bool:
        now, size, pnl = map(float, (now, size, pnl))
        if not all(math.isfinite(x) for x in (now, size, pnl)) or size <= 0:
            raise ValueError("invalid fill inputs")
        tilted = False
        if self.last_fill_time is not None and now - self.last_fill_time < self.min_fill_interval:
            tilted = True
        if self.last_size is not None and size / max(self.last_size, EPS) > self.max_sizing_ratio:
            tilted = True
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        if self.consecutive_losses >= 3:
            tilted = True
        self.trade_count += 1
        self.last_fill_time, self.last_size = now, size
        if tilted:
            self.lockout_until = max(self.lockout_until, now + self.cooldown_seconds)
        return tilted

    def reset_session(self) -> None:
        self.trade_count = 0
        self.consecutive_losses = 0
        self.last_fill_time = None
        self.last_size = None
        self.lockout_until = 0.0


# ---------------------------------------------------------------------------
# Execution engine, squad review, telemetry
# ---------------------------------------------------------------------------
class RiskState(str, Enum):
    NORMAL = "NORMAL"
    QUOTE_PULLBACK = "QUOTE_PULLBACK"
    COOLDOWN = "COOLDOWN"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


@dataclass(frozen=True)
class SpreadEvaluation:
    gross_alpha: float
    fees: float
    net_alpha: float
    approved: bool
    reason: str


class FourAgentSquad:
    """Deterministic role-separated review; not autonomous external agents."""
    roles = {
        "Manager Abhi": "operator approval and safety veto",
        "Alex": "L3 queue and microstructure review",
        "Emily": "macro and rough-volatility review",
        "Max": "risk and statutory-cost review",
    }

    @classmethod
    def evaluate(cls, operator_approved: bool, alpha_positive: bool,
                 queue_safe: bool, volatility_safe: bool, statutory_valid: bool,
                 emergency: bool = False) -> dict[str, Any]:
        votes = {
            "Manager Abhi": bool(operator_approved and not emergency),
            "Alex": bool(queue_safe and not emergency),
            "Emily": bool(volatility_safe and not emergency),
            "Max": bool(alpha_positive and statutory_valid and not emergency),
        }
        return {"votes": votes, "roles": dict(cls.roles),
                "manager_veto": not votes["Manager Abhi"],
                "approved": all(votes.values()),
                "reason": "approved" if all(votes.values()) else "one_or_more_agent_checks_failed"}


class Cycle40ExecutionEngine:
    def __init__(self, seed: int = 40, now_fn: Callable[[], datetime] | None = None):
        self.rough = RoughBergomiLift(seed=seed)
        self.hawkes = HawkesGraph4()
        self.market_maker = HawkesMarketMaker()
        self.queue = L3QueueMachine()
        self.vg = VarianceGammaModel()
        self.vg_replicator = DiscreteVarianceGammaReplicator(self.vg)
        self.fees = StatutoryCostCalculator()
        self.inventory = InventoryRiskController()
        self.throttler = TiltThrottler()
        self.state = RiskState.NORMAL
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.last_fee_breakdown: FeeBreakdown | None = None
        self.last_spread_evaluation: SpreadEvaluation | None = None
        self.last_quote: QuotePlan | None = None
        self.operator_approved = False
        self.paper_ledger_epoch = PAPER_LEDGER_EPOCH

    def evaluate_spread(self, gross_alpha: float, legs: Sequence[OptionLeg],
                        slippage: float = 0.0, impact: float = 0.0,
                        now: float | None = None, operator_approved: bool = False,
                        queue_safe: bool = True, volatility_safe: bool = True) -> SpreadEvaluation:
        gross = _finite_float(gross_alpha, "gross_alpha")
        now_mono = time.monotonic() if now is None else _finite_float(now, "now")
        breakdown = self.fees.calculate(legs, slippage, impact)
        net = gross - breakdown.total
        self.last_fee_breakdown = breakdown
        votes = FourAgentSquad.evaluate(operator_approved, gross > breakdown.total,
                                        queue_safe, volatility_safe, True,
                                        self.state == RiskState.EMERGENCY_UNWIND or self.inventory.emergency_latched)
        approved = bool(net > 0 and votes["approved"] and self.state == RiskState.NORMAL
                        and not self.inventory.emergency_latched
                        and self.throttler.can_enter(now_mono))
        reason = "approved" if approved else (
            "nonpositive_net_alpha" if net <= 0 else
            "manager_or_squad_veto" if not votes["approved"] else
            "risk_state_block" if self.state != RiskState.NORMAL else
            "inventory_emergency_latched" if self.inventory.emergency_latched else "throttler_block")
        result = SpreadEvaluation(gross, breakdown.total, net if approved else 0.0, approved, reason)
        self.last_spread_evaluation = result
        return result

    def make_quote(self, mid: float, inventory: float, volatility: float, horizon: float,
                   hawkes_events: Sequence[int | float]) -> QuotePlan:
        rates = self.hawkes.intensities
        if len(hawkes_events) == 4:
            rates = self.hawkes.update(0.01, hawkes_events)
        self.last_quote = self.market_maker.quote(mid, inventory, volatility, horizon,
                                                  float(np.sum(rates)))
        return self.last_quote

    def approve_paper_fill(self, side: str, quantity: float, price: float,
                           gross_alpha: float, legs: Sequence[OptionLeg],
                           now: float, slippage: float = 0.0, impact: float = 0.0,
                           operator_approved: bool = False) -> dict[str, Any]:
        evaluation = self.evaluate_spread(gross_alpha, legs, slippage, impact, now, operator_approved)
        if not evaluation.approved:
            return {"accepted": False, "reason": evaluation.reason, "net_alpha": 0.0}
        fill = self.inventory.apply_paper_fill(side, quantity, price, self.last_fee_breakdown.total if self.last_fee_breakdown else 0.0)
        if fill["accepted"]:
            self.throttler.record_fill(now, quantity, evaluation.net_alpha)
        return {"accepted": bool(fill["accepted"]), "fill": fill,
                "net_alpha": evaluation.net_alpha, "reason": "accepted" if fill["accepted"] else "inventory_limit"}

    def register_queue_pullback(self, order_id: str, **kwargs: Any) -> dict[str, Any]:
        verdict = self.queue.evaluate_pullback(order_id, **kwargs)
        if verdict["quote_pullback_immediate"]:
            self.state = RiskState.QUOTE_PULLBACK
        return verdict

    def recovery_ack(self) -> None:
        if self.inventory.emergency_latched:
            self.inventory.recovery_ack()
        self.state = RiskState.NORMAL

    def telemetry(self) -> dict[str, Any]:
        dt = self.now_fn()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now_ist = dt.astimezone(IST)
        hawkes_centrality = self.hawkes.centrality()
        return _json_safe({
            "timestamp_ist": now_ist.isoformat(), "epoch_seconds": now_ist.timestamp(),
            "rough": {"hurst": self.rough.hurst, "eta": self.rough.eta,
                      "variance": self.rough.rough_variance, "kernel_half_life": self.rough.memory_half_life,
                      "kernel_fit": asdict(self.rough.diagnostics)},
            "hawkes": {"assets": list(self.hawkes.assets), "intensities": self.hawkes.intensities,
                       "branching_spectral_radius": self.hawkes.spectral_radius,
                       "centrality": hawkes_centrality},
            "queue": {"tracked_orders": len(self.queue.orders),
                      "last_fill_probability": self.queue.last_fill_probability,
                      "last_pullback": self.queue.last_pullback},
            "quote": self.last_quote,
            "fees": self.last_fee_breakdown,
            "spread_evaluation": self.last_spread_evaluation,
            "inventory": {"cash": self.inventory.cash, "quantity": self.inventory.inventory,
                          "realized_pnl": self.inventory.realized_pnl,
                          "unrealized_pnl": self.inventory.unrealized_pnl,
                          "emergency_latched": self.inventory.emergency_latched},
            "risk_state": self.state.value,
            "throttler": {"trade_count": self.throttler.trade_count,
                           "max_trades": self.throttler.max_trades,
                           "consecutive_losses": self.throttler.consecutive_losses,
                           "lockout_until": self.throttler.lockout_until},
            "paper_ledger": {"epoch": self.paper_ledger_epoch, "initial_capital": PAPER_INITIAL_CAPITAL},
            "safety": {"LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
                       "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED},
        })

    @staticmethod
    def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("live order dispatch is permanently disabled; paper simulation only")


# ---------------------------------------------------------------------------
# Variance Gamma option pricing and discrete variance replication
# ---------------------------------------------------------------------------
class VarianceGammaModel:
    """Risk-neutral Variance Gamma call pricer using Carr-Madan Fourier inversion."""
    def __init__(self, sigma: float = 0.20, nu: float = 0.20, theta: float = -0.10,
                 rate: float = 0.06, dividend_yield: float = 0.0,
                 damping: float = 1.5, integration_limit: float = 180.0):
        vals = [sigma, nu, theta, rate, dividend_yield, damping, integration_limit]
        if not all(math.isfinite(float(x)) for x in vals):
            raise ValueError("VG parameters must be finite")
        if sigma <= 0 or nu <= 0 or damping <= 0 or integration_limit <= 10:
            raise ValueError("sigma, nu, damping and integration limit must be positive")
        self.sigma, self.nu, self.theta = float(sigma), float(nu), float(theta)
        self.rate, self.dividend_yield = float(rate), float(dividend_yield)
        self.damping, self.integration_limit = float(damping), float(integration_limit)
        martingale = 1.0 - self.theta * self.nu - 0.5 * self.sigma**2 * self.nu
        if martingale <= 0:
            raise ValueError("VG parameters violate the risk-neutral martingale condition")
        self.omega = math.log(martingale) / self.nu
        # Damping moment requires E[S^(alpha+1)] to exist.
        y = self.damping + 1.0
        if 1.0 - self.theta*self.nu*y - 0.5*self.sigma**2*self.nu*y*y <= 0:
            raise ValueError("damping outside available VG moment strip; reduce damping")

    def characteristic_function(self, u: complex | float, maturity: float) -> complex:
        T = _finite_float(maturity, "maturity")
        if T < 0:
            raise ValueError("maturity must be nonnegative")
        u = complex(u)
        base = 1.0 - 1j*self.theta*self.nu*u + 0.5*self.sigma**2*self.nu*u*u
        return complex(np.exp(1j*u*(self.rate-self.dividend_yield+self.omega)*T) * np.power(base, -T/self.nu))

    def log_spot_characteristic(self, u: complex | float, spot: float, maturity: float) -> complex:
        spot = _finite_float(spot, "spot")
        if spot <= 0:
            raise ValueError("spot must be positive")
        return complex(np.exp(1j*complex(u)*math.log(spot)) * self.characteristic_function(u, maturity))

    def call_price(self, spot: float, strike: float, maturity: float,
                   integration_limit: float | None = None) -> float:
        S, K, T = map(float, (spot, strike, maturity))
        if not all(math.isfinite(x) for x in (S, K, T)) or S <= 0 or K <= 0 or T < 0:
            raise ValueError("spot/strike positive and maturity nonnegative required")
        if T == 0:
            return max(S-K, 0.0)
        a = self.damping
        limit = self.integration_limit if integration_limit is None else _finite_float(integration_limit, "integration_limit")
        if limit <= 10:
            raise ValueError("integration_limit must exceed 10")
        logk = math.log(K)
        def integrand(u: float) -> float:
            z = complex(u, -(a+1.0))
            phi = self.log_spot_characteristic(z, S, T)
            denom = a*a + a - u*u + 1j*(2*a+1.0)*u
            psi = math.exp(-self.rate*T) * phi / denom
            return float((np.exp(-1j*u*logk)*psi).real)
        integral, _err = quad(integrand, 0.0, limit, epsabs=2e-7, epsrel=2e-7, limit=350)
        price = math.exp(-a*logk) * integral / math.pi
        lower = max(S*math.exp(-self.dividend_yield*T)-K*math.exp(-self.rate*T), 0.0)
        upper = S*math.exp(-self.dividend_yield*T)
        return float(min(upper, max(lower, price)))

    def put_price(self, spot: float, strike: float, maturity: float) -> float:
        call = self.call_price(spot, strike, maturity)
        S, K, T = float(spot), float(strike), float(maturity)
        return float(max(0.0, call - S*math.exp(-self.dividend_yield*T) + K*math.exp(-self.rate*T)))


class DiscreteVarianceGammaReplicator:
    def __init__(self, model: VarianceGammaModel):
        self.model = model

    def strip(self, spot: float, strikes: Sequence[float], maturity: float) -> dict[str, Any]:
        ks = _finite_array(strikes, "strikes", 1)
        if ks.size < 3 or np.any(ks <= 0) or np.any(np.diff(ks) <= 0):
            raise ValueError("strikes must contain at least 3 positive increasing values")
        S = _finite_float(spot, "spot")
        T = _finite_float(maturity, "maturity")
        if S <= 0 or T <= 0:
            raise ValueError("spot and maturity must be positive")
        calls = np.array([self.model.call_price(S, float(K), T) for K in ks])
        puts = np.array([self.model.put_price(S, float(K), T) for K in ks])
        butterflies = (calls[:-2] - 2*calls[1:-1] + calls[2:]) / np.diff(ks[:-1])**2
        # Grid is not uniform in general; use average local gap squared.
        for i in range(1, len(ks)-1):
            h0, h1 = ks[i]-ks[i-1], ks[i+1]-ks[i]
            butterflies[i-1] = 2.0 * ((calls[i+1]-calls[i])/h1 - (calls[i]-calls[i-1])/h0) / (h0+h1)
        var_sum = 0.0
        for i in range(len(ks)-1):
            k_mid = 0.5*(ks[i]+ks[i+1])
            dK = ks[i+1]-ks[i]
            if k_mid <= S:
                price = 0.5*(puts[i]+puts[i+1])
            else:
                price = 0.5*(calls[i]+calls[i+1])
            var_sum += dK/(k_mid*k_mid) * price
        variance_swap = 2.0*var_sum/T
        return {"strikes": ks.tolist(), "calls": calls.tolist(), "puts": puts.tolist(),
                "butterfly_density_discrete": butterflies.tolist(),
                "butterfly_nonnegative_sampled": bool(np.all(butterflies >= -1e-7)),
                "variance_swap_rate": float(max(0.0, variance_swap)),
                "max_strike_gap": float(np.max(np.diff(ks)))}


class TelemetryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], engine: Cycle40ExecutionEngine):
        self.engine = engine
        super().__init__(server_address, TelemetryRequestHandler)


class TelemetryRequestHandler(BaseHTTPRequestHandler):
    server: TelemetryHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Avoid noisy default console output; host can attach its own access logging.
        return

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = self.path.split("?", 1)[0]
        engine = self.server.engine
        if path == "/health":
            payload = {"ok": True, "risk_state": engine.state.value,
                       "live_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                       "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED}
            self._send(200, "application/json; charset=utf-8", strict_json_dumps(payload).encode())
        elif path == "/telemetry":
            self._send(200, "application/json; charset=utf-8", strict_json_dumps(engine.telemetry()).encode())
        elif path == "/events":
            body = ("retry: 1000\n" + "event: telemetry\n" +
                    "data: " + strict_json_dumps(engine.telemetry()) + "\n\n").encode()
            self._send(200, "text/event-stream; charset=utf-8", body)
        else:
            self._send(404, "application/json; charset=utf-8", b'{"error":"not_found"}')


def create_dashboard_server(engine: Cycle40ExecutionEngine,
                            host: str = "127.0.0.1", port: int = 8088) -> TelemetryHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("dashboard defaults to loopback only; remote binding is intentionally blocked")
    if not (0 <= int(port) <= 65535):
        raise ValueError("invalid port")
    return TelemetryHTTPServer((host, int(port)), engine)


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Permanent fail-closed boundary. No live broker path is implemented."""
    raise RuntimeError("LIVE_ORDER_DISPATCH_ENABLED=False and REAL_BROKER_FILLS_LOCKED=True")


__all__ = [
    "LIVE_ORDER_DISPATCH_ENABLED", "REAL_BROKER_FILLS_LOCKED", "PAPER_LEDGER_EPOCH",
    "PAPER_INITIAL_CAPITAL", "RoughBergomiLift", "RoughKernelDiagnostics",
    "HawkesGraph4", "HawkesMarketMaker", "QuotePlan", "L3QueueMachine", "QueueOrder",
    "OptionLeg", "FeeBreakdown", "FeeConfig", "StatutoryCostCalculator",
    "InventoryRiskController", "TiltThrottler", "RiskState", "SpreadEvaluation",
    "FourAgentSquad", "Cycle40ExecutionEngine", "VarianceGammaModel",
    "DiscreteVarianceGammaReplicator", "TelemetryHTTPServer", "create_dashboard_server",
    "dispatch_live_order", "strict_json_dumps",
]
