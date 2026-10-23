"""Cycle 33 research engine: OFI information graph, multivariate Hawkes,
rough Volterra variance-swap replication, Indian transaction costs and telemetry.

Offline/paper simulation only. No exchange or broker connectivity is implemented.
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

LIVE_ORDER_DISPATCH_ENABLED = False
EPSILON = 1e-12
INR_PER_CRORE = 10_000_000.0
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
DEFAULT_NODES = (
    "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
    "RELIANCE", "NIFTY50", "BANKNIFTY",
)


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Fail-closed barrier preventing live execution during paper simulation."""
    if not LIVE_ORDER_DISPATCH_ENABLED:
        raise RuntimeError("live order dispatch is permanently disabled in paper simulation mode")


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _matrix(matrix: Sequence[Sequence[float]], name: str, *, nonnegative: bool = False) -> list[list[float]]:
    rows = [[_finite(v, name) for v in row] for row in matrix]
    if not rows or any(len(row) != len(rows) for row in rows):
        raise ValueError(f"{name} must be a non-empty square matrix")
    if nonnegative and any(v < 0 for row in rows for v in row):
        raise ValueError(f"{name} must be nonnegative")
    return rows


def spectral_radius(matrix: Sequence[Sequence[float]], iterations: int = 1000, tolerance: float = 1e-12) -> float:
    """Power-method spectral-radius estimate for a nonnegative square matrix."""
    a = _matrix(matrix, "matrix", nonnegative=True)
    n = len(a)
    if iterations < 1 or tolerance <= 0:
        raise ValueError("iterations must be positive and tolerance must be > 0")
    if max(sum(row) for row in a) <= EPSILON:
        return 0.0
    x = [1.0 / n] * n
    prev = 0.0
    estimate = 0.0
    for _ in range(iterations):
        y = [sum(a[i][j] * x[j] for j in range(n)) for i in range(n)]
        norm = max(abs(v) for v in y)
        if norm <= EPSILON:
            return 0.0
        x = [v / norm for v in y]
        # Collatz-Wielandt quotient: stable for irreducible nonnegative matrices.
        ax = [sum(a[i][j] * x[j] for j in range(n)) for i in range(n)]
        ratios = [ax[i] / x[i] for i in range(n) if x[i] > EPSILON]
        estimate = sum(ratios) / len(ratios) if ratios else norm
        if abs(estimate - prev) <= tolerance * max(1.0, abs(estimate)):
            break
        prev = estimate
    # A zero-diagonal nilpotent/periodic matrix can make the Rayleigh estimate
    # oscillate; the power norm is a useful additional estimate.
    return max(0.0, min(estimate, max(sum(row) for row in a)))


def shrink_nonnegative_matrix(matrix: Sequence[Sequence[float]], bound: float) -> tuple[list[list[float]], float, float]:
    """Uniformly shrink matrix to ensure rho <= bound (row-sum conservative).

    Returns (matrix, pre-shrink rho estimate, scale). The maximum row sum is
    used as an upper bound on rho, guarding power-method under-estimation.
    """
    a = _matrix(matrix, "matrix", nonnegative=True)
    bound = _finite(bound, "bound")
    if bound <= 0:
        raise ValueError("bound must be > 0")
    rho = spectral_radius(a)
    max_row = max(sum(row) for row in a)
    denominator = max(rho, max_row)
    scale = min(1.0, bound / denominator) if denominator > EPSILON else 1.0
    out = [[v * scale for v in row] for row in a]
    return out, rho, scale


@dataclass(frozen=True)
class BookLevelDelta:
    bid_qty_delta: float
    ask_qty_delta: float
    bid_price_delta: float
    ask_price_delta: float

    def __post_init__(self) -> None:
        for name in ("bid_qty_delta", "ask_qty_delta", "bid_price_delta", "ask_price_delta"):
            _finite(getattr(self, name), name)


@dataclass(frozen=True)
class OFIResult:
    node: str
    ofi: float
    level_contributions: tuple[float, ...]


class MultiLevelOFITracker:
    """Compute weighted multi-level OFI from Level-3 deltas."""
    def __init__(self, level_weights: Sequence[float] = (1.0, 0.7, 0.5, 0.3, 0.2)) -> None:
        weights = tuple(_finite(w, "level weight") for w in level_weights)
        if not weights or any(w < 0 for w in weights):
            raise ValueError("level weights must be non-empty and nonnegative")
        if sum(weights) <= 0:
            raise ValueError("at least one level weight must be positive")
        self.level_weights = weights
        self.last: dict[str, OFIResult] = {}
        self.history: dict[str, list[float]] = {}

    def compute(self, node: str, levels: Sequence[BookLevelDelta]) -> OFIResult:
        if not node.strip():
            raise ValueError("node must be non-empty")
        if not levels or len(levels) > len(self.level_weights):
            raise ValueError("levels must be non-empty and no greater than configured weight count")
        contributions = []
        for w, level in zip(self.level_weights, levels):
            bid = level.bid_qty_delta if level.bid_price_delta >= 0 else 0.0
            ask = level.ask_qty_delta if level.ask_price_delta <= 0 else 0.0
            contributions.append(w * (bid - ask))
        result = OFIResult(node, sum(contributions), tuple(contributions))
        self.last[node] = result
        self.history.setdefault(node, []).append(result.ofi)
        return result


class DirectedInformationGraph:
    """Nonnegative directed adjacency; A[target][source] means source -> target."""
    def __init__(self, nodes: Sequence[str] = DEFAULT_NODES, spectral_bound: float = 0.95) -> None:
        self.nodes = tuple(nodes)
        if not self.nodes or len(set(self.nodes)) != len(self.nodes) or any(not n for n in self.nodes):
            raise ValueError("nodes must be unique, non-empty names")
        self.index = {n: i for i, n in enumerate(self.nodes)}
        self.spectral_bound = _finite(spectral_bound, "spectral_bound")
        if not 0 < self.spectral_bound < 1:
            raise ValueError("spectral_bound must be in (0, 1)")
        self.adjacency = [[0.0 for _ in self.nodes] for _ in self.nodes]
        self.pre_shrink_radius = 0.0
        self.shrink_scale = 1.0

    def set_edge(self, source: str, target: str, information_strength: float) -> None:
        if source not in self.index or target not in self.index:
            raise KeyError("source and target must be configured nodes")
        strength = _finite(information_strength, "information_strength")
        if strength < 0:
            raise ValueError("information_strength must be nonnegative")
        self.adjacency[self.index[target]][self.index[source]] = strength
        self._enforce_bound()

    def set_matrix(self, adjacency: Sequence[Sequence[float]]) -> None:
        a = _matrix(adjacency, "adjacency", nonnegative=True)
        if len(a) != len(self.nodes):
            raise ValueError("adjacency shape must match nodes")
        self.adjacency = a
        self._enforce_bound()

    def _enforce_bound(self) -> None:
        self.adjacency, self.pre_shrink_radius, self.shrink_scale = shrink_nonnegative_matrix(
            self.adjacency, self.spectral_bound
        )

    @property
    def radius(self) -> float:
        # Since the matrix was scaled by a row-sum bound this value is guaranteed <= bound.
        return spectral_radius(self.adjacency)

    def centrality(self) -> dict[str, dict[str, float]]:
        incoming = {n: sum(self.adjacency[self.index[n]]) for n in self.nodes}
        outgoing = {n: sum(self.adjacency[i][self.index[n]] for i in range(len(self.nodes))) for n in self.nodes}
        return {n: {"in_degree_absorption": incoming[n], "out_degree_propagation": outgoing[n]} for n in self.nodes}

    def leaders(self, top_n: int = 5) -> list[dict[str, float | str]]:
        if top_n < 1:
            raise ValueError("top_n must be positive")
        return sorted(
            ({"node": n, **metrics} for n, metrics in self.centrality().items()),
            key=lambda item: float(item["out_degree_propagation"]), reverse=True
        )[:top_n]


class MultivariateHawkesNetwork:
    """Discrete-bin multivariate exponential Hawkes approximation.

    alpha[target][source] is the source event's excitation of the target rate.
    This is a practical online estimator, not a full continuous-time MLE.
    """
    def __init__(self, nodes: Sequence[str] = DEFAULT_NODES,
                 baseline_rates: Sequence[float] | None = None,
                 alpha: Sequence[Sequence[float]] | None = None,
                 beta: Sequence[Sequence[float]] | None = None,
                 branching_bound: float = 0.90, learning_rate: float = 0.005) -> None:
        self.nodes = tuple(nodes)
        n = len(self.nodes)
        if n < 1 or len(set(self.nodes)) != n:
            raise ValueError("nodes must be non-empty and unique")
        self.index = {name: i for i, name in enumerate(self.nodes)}
        self.baseline = list(baseline_rates if baseline_rates is not None else [0.1] * n)
        if len(self.baseline) != n or any(not math.isfinite(v) or v <= 0 for v in self.baseline):
            raise ValueError("baseline_rates must be positive finite values matching nodes")
        self.alpha = _matrix(alpha if alpha is not None else [[0.0] * n for _ in range(n)], "alpha", nonnegative=True)
        self.beta = _matrix(beta if beta is not None else [[1.0] * n for _ in range(n)], "beta", nonnegative=True)
        if len(self.alpha) != n or len(self.beta) != n or any(v <= 0 for row in self.beta for v in row):
            raise ValueError("alpha/beta matrix shapes must match nodes; beta must be > 0")
        self.branching_bound = _finite(branching_bound, "branching_bound")
        self.learning_rate = _finite(learning_rate, "learning_rate")
        if not 0 < self.branching_bound < 1 or self.learning_rate < 0:
            raise ValueError("invalid branching bound or learning rate")
        self.trace = [[0.0] * n for _ in range(n)]
        self.last_intensities = self.intensities()
        self.last_log_likelihood = 0.0
        self._project_stability()

    def branching_matrix(self) -> list[list[float]]:
        return [[self.alpha[i][j] / self.beta[i][j] for j in range(len(self.nodes))] for i in range(len(self.nodes))]

    def branching_radius(self) -> float:
        return spectral_radius(self.branching_matrix())

    def _project_stability(self) -> None:
        gamma, _, _ = shrink_nonnegative_matrix(self.branching_matrix(), self.branching_bound)
        self.alpha = [[gamma[i][j] * self.beta[i][j] for j in range(len(self.nodes))] for i in range(len(self.nodes))]

    def intensities(self) -> dict[str, float]:
        result = {}
        for i, name in enumerate(self.nodes):
            result[name] = max(EPSILON, self.baseline[i] + sum(self.alpha[i][j] * self.trace[i][j] for j in range(len(self.nodes))))
        return result

    def update(self, dt: float, event_counts: Sequence[float]) -> dict[str, float]:
        dt = _finite(dt, "dt")
        if dt <= 0:
            raise ValueError("dt must be > 0")
        counts = [_finite(c, "event count") for c in event_counts]
        n = len(self.nodes)
        if len(counts) != n or any(c < 0 for c in counts):
            raise ValueError("event_counts must match nodes and be nonnegative")
        for i in range(n):
            for j in range(n):
                self.trace[i][j] *= math.exp(-self.beta[i][j] * dt)
        lam = [max(EPSILON, self.baseline[i] + sum(self.alpha[i][j] * self.trace[i][j] for j in range(n))) for i in range(n)]
        log_likelihood = 0.0
        if self.learning_rate > 0:
            for i in range(n):
                count = counts[i]
                log_likelihood += count * math.log(lam[i]) - lam[i] * dt
                score = count / lam[i] - dt
                self.baseline[i] = max(1e-6, self.baseline[i] + self.learning_rate * score)
                for j in range(n):
                    grad = self.trace[i][j] * score
                    self.alpha[i][j] = max(0.0, self.alpha[i][j] + self.learning_rate * grad)
            self._project_stability()
        else:
            log_likelihood = sum(counts[i] * math.log(lam[i]) - lam[i] * dt for i in range(n))
        for i in range(n):
            for j in range(n):
                self.trace[i][j] += counts[j]
        self.last_log_likelihood = log_likelihood
        self.last_intensities = self.intensities()
        return dict(self.last_intensities)

    def leadership(self, target: str | None = None) -> list[dict[str, float | str]]:
        if target is not None and target not in self.index:
            raise KeyError(target)
        rows = []
        targets = [target] if target else list(self.nodes)
        for target_name in targets:
            i = self.index[target_name]
            denom = sum(self.alpha[i]) + EPSILON
            for j, source_name in enumerate(self.nodes):
                if source_name == target_name:
                    continue
                rows.append({"source": source_name, "target": target_name, "alpha": self.alpha[i][j],
                             "leadership": self.alpha[i][j] / denom})
        return sorted(rows, key=lambda x: float(x["leadership"]), reverse=True)


@dataclass(frozen=True)
class VolterraApproximation:
    hurst: float
    coefficients: tuple[float, ...]
    decay_rates: tuple[float, ...]
    log_gamma_min: float
    log_gamma_max: float


@dataclass(frozen=True)
class VarianceSwapResult:
    fair_variance: float
    max_strike_gap: float
    discretization_error_bound: float
    truncation_error_bound: float
    total_error_bound: float


@dataclass(frozen=True)
class VarianceSwapQuote:
    strike: float
    option_type: str
    price: float


class RoughVolterraKernel:
    """Fast log-grid sum-of-exponentials approximation to the rough kernel."""
    def __init__(self, hurst: float = 0.10, factors: int = 32,
                 log_gamma_min: float = -8.0, log_gamma_max: float = 8.0) -> None:
        h = _finite(hurst, "hurst")
        if not 0 < h < 0.5:
            raise ValueError("hurst must lie in (0, 0.5)")
        if factors < 2:
            raise ValueError("factors must be >= 2")
        lo, hi = _finite(log_gamma_min, "log_gamma_min"), _finite(log_gamma_max, "log_gamma_max")
        if not lo < hi:
            raise ValueError("log_gamma_min must be below log_gamma_max")
        self.hurst, self.factors = h, int(factors)
        self.log_gamma_min, self.log_gamma_max = lo, hi
        self.approximation = self._make_approximation()
        self.states = [0.0] * self.factors

    def _make_approximation(self) -> VolterraApproximation:
        # K(t) = t^{-p}/Gamma(1-p), p=1/2-H; Laplace/log-grid quadrature.
        p = 0.5 - self.hurst
        du = (self.log_gamma_max - self.log_gamma_min) / self.factors
        prefactor = math.sin(math.pi * p) / math.pi
        coeff, rates = [], []
        for m in range(self.factors):
            u = self.log_gamma_min + (m + 0.5) * du
            rate = math.exp(u)
            rates.append(rate)
            coeff.append(prefactor * math.exp(p * u) * du)
        return VolterraApproximation(self.hurst, tuple(coeff), tuple(rates), self.log_gamma_min, self.log_gamma_max)

    def exact_kernel(self, t: float) -> float:
        t = _finite(t, "t")
        if t <= 0:
            raise ValueError("t must be > 0")
        return t ** (self.hurst - 0.5) / math.gamma(self.hurst + 0.5)

    def approximate_kernel(self, t: float) -> float:
        t = _finite(t, "t")
        if t <= 0:
            raise ValueError("t must be > 0")
        return sum(c * math.exp(-g * t) for c, g in zip(self.approximation.coefficients, self.approximation.decay_rates))

    def update(self, input_value: float, dt: float) -> float:
        x, dt = _finite(input_value, "input_value"), _finite(dt, "dt")
        if dt <= 0:
            raise ValueError("dt must be > 0")
        for i, rate in enumerate(self.approximation.decay_rates):
            self.states[i] = self.states[i] * math.exp(-rate * dt) + x * dt
        return sum(c * s for c, s in zip(self.approximation.coefficients, self.states))

    def reset(self) -> None:
        self.states = [0.0] * self.factors

    @staticmethod
    def replicate_variance_swap(spot: float, maturity: float, quotes: Sequence[VarianceSwapQuote],
                                integrand_second_derivative_bound: float = 0.0,
                                tail_truncation_bound: float = 0.0) -> VarianceSwapResult:
        spot, maturity = _finite(spot, "spot"), _finite(maturity, "maturity")
        curvature = _finite(integrand_second_derivative_bound, "integrand_second_derivative_bound")
        truncation = _finite(tail_truncation_bound, "tail_truncation_bound")
        if spot <= 0 or maturity <= 0 or curvature < 0 or truncation < 0:
            raise ValueError("spot/maturity must be positive and error bounds nonnegative")
        if len(quotes) < 2:
            raise ValueError("at least two strike quotes are required")
        sorted_quotes = sorted(quotes, key=lambda q: q.strike)
        strikes = [q.strike for q in sorted_quotes]
        if any(not math.isfinite(k) or k <= 0 for k in strikes) or len(set(strikes)) != len(strikes):
            raise ValueError("strike grid must contain distinct positive strikes")
        if any(not math.isfinite(q.price) or q.price < 0 for q in sorted_quotes):
            raise ValueError("option prices must be finite and nonnegative")
        if any(q.option_type.upper() not in {"PUT", "CALL"} for q in sorted_quotes):
            raise ValueError("option_type must be PUT or CALL")
        gaps = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1)]
        widths = []
        for i in range(len(strikes)):
            if i == 0:
                widths.append(gaps[0] / 2)
            elif i == len(strikes) - 1:
                widths.append(gaps[-1] / 2)
            else:
                widths.append((gaps[i - 1] + gaps[i]) / 2)
        accumulator = 0.0
        for q, width in zip(sorted_quotes, widths):
            kind = q.option_type.upper()
            if q.strike <= spot and kind == "PUT":
                accumulator += width * q.price / (q.strike * q.strike)
            elif q.strike > spot and kind == "CALL":
                accumulator += width * q.price / (q.strike * q.strike)
        fair = 2.0 * accumulator / maturity
        # Composite trapezoidal quadrature bound: M2/12 * sum(h_i^3), then 2/T.
        discretization = (2.0 / maturity) * curvature * sum(g ** 3 for g in gaps) / 12.0
        return VarianceSwapResult(fair, max(gaps), discretization, truncation,
                                  discretization + truncation)


@dataclass(frozen=True)
class OptionLeg:
    premium: float
    quantity: float
    side: str
    label: str = ""


@dataclass(frozen=True)
class FeeBreakdown:
    buy_turnover: float
    sell_turnover: float
    total_turnover: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    stamp_duty: float
    slippage: float
    impact_hurdle: float
    total_statutory: float
    total_friction: float
    expected_gross_alpha: float
    expected_net_alpha: float
    passes_profitability_gate: bool


class StatutoryCostCalculator:
    def __init__(self, stt_sell_rate: float = 0.0015, stamp_buy_rate: float = 0.00003,
                 exchange_per_crore: float = 3553.0, sebi_per_crore: float = 10.0,
                 gst_rate: float = 0.18, brokerage_per_leg: float = 0.0) -> None:
        self.stt_sell_rate = _finite(stt_sell_rate, "stt_sell_rate")
        self.stamp_buy_rate = _finite(stamp_buy_rate, "stamp_buy_rate")
        self.exchange_per_crore = _finite(exchange_per_crore, "exchange_per_crore")
        self.sebi_per_crore = _finite(sebi_per_crore, "sebi_per_crore")
        self.gst_rate = _finite(gst_rate, "gst_rate")
        self.brokerage_per_leg = _finite(brokerage_per_leg, "brokerage_per_leg")
        if any(v < 0 for v in (self.stt_sell_rate, self.stamp_buy_rate, self.exchange_per_crore,
                               self.sebi_per_crore, self.gst_rate, self.brokerage_per_leg)):
            raise ValueError("fee rates must be nonnegative")

    def calculate(self, legs: Sequence[OptionLeg], expected_gross_alpha: float,
                  slippage: float = 0.0, impact_hurdle: float = 0.0) -> FeeBreakdown:
        gross, slippage, impact = _finite(expected_gross_alpha, "expected_gross_alpha"), _finite(slippage, "slippage"), _finite(impact_hurdle, "impact_hurdle")
        if slippage < 0 or impact < 0:
            raise ValueError("slippage and impact_hurdle must be nonnegative")
        if not legs:
            raise ValueError("at least one option leg is required")
        buy = sell = 0.0
        for leg in legs:
            premium, quantity = _finite(leg.premium, "premium"), _finite(leg.quantity, "quantity")
            if premium < 0 or quantity < 0 or leg.side.upper() not in {"BUY", "SELL"}:
                raise ValueError("legs require nonnegative premium/quantity and BUY/SELL side")
            if leg.side.upper() == "BUY":
                buy += premium * quantity
            else:
                sell += premium * quantity
        total = buy + sell
        stt = sell * self.stt_sell_rate
        stamp = buy * self.stamp_buy_rate
        exchange = total * self.exchange_per_crore / INR_PER_CRORE
        sebi = total * self.sebi_per_crore / INR_PER_CRORE
        brokerage = self.brokerage_per_leg * len(legs)
        gst = self.gst_rate * (exchange + sebi + brokerage)
        statutory = stt + stamp + exchange + sebi + brokerage + gst
        friction = statutory + slippage + impact
        net = gross - friction
        components = (buy, sell, total, stt, stamp, exchange, sebi, brokerage, gst, statutory, friction, net)
        if not all(math.isfinite(v) for v in components):
            raise ValueError("cost calculation overflow")
        return FeeBreakdown(buy, sell, total, stt, exchange, sebi, brokerage, gst,
                            stamp, slippage, impact, statutory, friction, gross, net, net > 0.0)


@dataclass(frozen=True)
class TradeCapResult:
    trade_cap: int
    alpha: float
    cost: float
    risk: float


def optimal_daily_trade_cap(alpha: float, cost: float, risk: float) -> TradeCapResult:
    alpha, cost, risk = _finite(alpha, "alpha"), _finite(cost, "cost"), _finite(risk, "risk")
    if risk <= 0:
        raise ValueError("risk must be > 0")
    return TradeCapResult(max(0, round((alpha - cost) / risk)), alpha, cost, risk)


class AntiOvertradingThrottler:
    def __init__(self, cap: int, cooldown_seconds: float = 900.0,
                 loss_streak_limit: int = 3, revenge_ratio: float = 1.25,
                 min_fill_interval: float = 30.0) -> None:
        if cap < 0 or loss_streak_limit < 1:
            raise ValueError("cap must be >=0 and loss_streak_limit >=1")
        self.cap, self.cooldown_seconds = int(cap), _finite(cooldown_seconds, "cooldown_seconds")
        self.loss_streak_limit = int(loss_streak_limit)
        self.revenge_ratio, self.min_fill_interval = _finite(revenge_ratio, "revenge_ratio"), _finite(min_fill_interval, "min_fill_interval")
        if self.cooldown_seconds < 0 or self.revenge_ratio <= 1 or self.min_fill_interval < 0:
            raise ValueError("invalid throttle configuration")
        self.trade_count = 0
        self.loss_streak = 0
        self.previous_size: float | None = None
        self.last_fill_timestamp: float | None = None
        self.cooldown_until = 0.0
        self.lockout_reason: str | None = None

    def can_trade(self, now: float) -> bool:
        now = _finite(now, "now")
        return self.trade_count < self.cap and now >= self.cooldown_until

    def record_fill(self, timestamp: float, size: float, pnl: float) -> str | None:
        timestamp, size, pnl = _finite(timestamp, "timestamp"), _finite(size, "size"), _finite(pnl, "pnl")
        if size <= 0:
            raise ValueError("size must be > 0")
        reason = None
        if self.last_fill_timestamp is not None and timestamp < self.last_fill_timestamp:
            raise ValueError("fill timestamps must be monotonic")
        if self.previous_size is not None and size / self.previous_size > self.revenge_ratio:
            reason = "REVENGE_SIZING"
        if self.last_fill_timestamp is not None and timestamp - self.last_fill_timestamp < self.min_fill_interval:
            reason = reason or "RAPID_PACING"
        self.loss_streak = self.loss_streak + 1 if pnl < 0 else 0
        if self.loss_streak >= self.loss_streak_limit:
            reason = reason or "LOSS_STREAK"
        self.trade_count += 1
        self.last_fill_timestamp, self.previous_size = timestamp, size
        if reason:
            self.lockout_reason = reason
            self.cooldown_until = max(self.cooldown_until, timestamp + self.cooldown_seconds)
        return reason

    def reset_session(self) -> None:
        self.trade_count = self.loss_streak = 0
        self.previous_size = self.last_fill_timestamp = None
        self.cooldown_until = 0.0
        self.lockout_reason = None

    def remaining_cooldown(self, now: float) -> float:
        return max(0.0, self.cooldown_until - _finite(now, "now"))


class RiskState(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class Cycle33Engine:
    def __init__(self, nodes: Sequence[str] = DEFAULT_NODES, level_weights: Sequence[float] = (1.0, 0.7, 0.5, 0.3, 0.2),
                 hurst: float = 0.10, hawkes_learning_rate: float = 0.005,
                 daily_trade_cap: int = 20) -> None:
        self.nodes = tuple(nodes)
        self.ofi_tracker = MultiLevelOFITracker(level_weights)
        self.info_graph = DirectedInformationGraph(nodes=self.nodes)
        self.hawkes = MultivariateHawkesNetwork(nodes=self.nodes, learning_rate=hawkes_learning_rate)
        self.rough_kernel = RoughVolterraKernel(hurst=hurst)
        self.costs = StatutoryCostCalculator()
        self.throttler = AntiOvertradingThrottler(daily_trade_cap)
        self.risk_state = RiskState.IDLE
        self.emergency_latched = False
        self.last_variance_swap: VarianceSwapResult | None = None
        self.last_fee_breakdown: FeeBreakdown | None = None
        self.last_ofi: dict[str, float] = {}
        self.heartbeat = 0

    @staticmethod
    def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
        dispatch_live_order(*args, **kwargs)

    def update_ofi(self, node: str, levels: Sequence[BookLevelDelta]) -> OFIResult:
        if node not in self.nodes:
            raise KeyError(node)
        result = self.ofi_tracker.compute(node, levels)
        self.last_ofi[node] = result.ofi
        return result

    def process_hawkes(self, dt: float, event_counts: Sequence[float]) -> dict[str, float]:
        return self.hawkes.update(dt, event_counts)

    def set_information_edge(self, source: str, target: str, strength: float) -> None:
        self.info_graph.set_edge(source, target, strength)

    def price_variance_swap(self, spot: float, maturity: float, quotes: Sequence[VarianceSwapQuote],
                            integrand_second_derivative_bound: float = 0.0, tail_truncation_bound: float = 0.0) -> VarianceSwapResult:
        result = self.rough_kernel.replicate_variance_swap(spot, maturity, quotes,
                                                          integrand_second_derivative_bound, tail_truncation_bound)
        self.last_variance_swap = result
        return result

    def evaluate_spread(self, legs: Sequence[OptionLeg], expected_gross_alpha: float,
                        slippage: float = 0.0, impact_hurdle: float = 0.0,
                        now: float | None = None) -> FeeBreakdown:
        now = time.time() if now is None else now
        if self.emergency_latched or not self.throttler.can_trade(now):
            # Return rejected candidate with no positive net-alpha illusion.
            result = self.costs.calculate(legs, expected_gross_alpha=0.0, slippage=slippage, impact_hurdle=impact_hurdle)
            self.last_fee_breakdown = result
            return FeeBreakdown(**{**asdict(result), "expected_gross_alpha": expected_gross_alpha,
                                   "expected_net_alpha": 0.0, "passes_profitability_gate": False})
        result = self.costs.calculate(legs, expected_gross_alpha, slippage, impact_hurdle)
        self.last_fee_breakdown = result
        if result.passes_profitability_gate:
            self.risk_state = RiskState.ACTIVE
        return result

    def record_fill(self, timestamp: float, size: float, pnl: float) -> str | None:
        reason = self.throttler.record_fill(timestamp, size, pnl)
        return reason

    def trigger_emergency(self) -> None:
        self.emergency_latched = True
        self.risk_state = RiskState.EMERGENCY_UNWIND

    def recovery_ack(self) -> bool:
        if not self.emergency_latched:
            return False
        self.emergency_latched = False
        self.risk_state = RiskState.IDLE
        return True

    def telemetry_payload(self, now_epoch: float | None = None) -> dict[str, Any]:
        now_epoch = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        dt = datetime.fromtimestamp(now_epoch, tz=timezone.utc).astimezone(IST)
        self.heartbeat += 1
        return {
            "timestamp_ist": dt.isoformat(), "epoch_seconds": now_epoch,
            "ofi": dict(self.last_ofi), "ofi_graph": {"spectral_radius": self.info_graph.radius,
                "spectral_bound": self.info_graph.spectral_bound, "centrality": self.info_graph.centrality(),
                "leaders": self.info_graph.leaders()},
            "hawkes": {"intensities": self.hawkes.intensities(), "branching_radius": self.hawkes.branching_radius(),
                       "branching_bound": self.hawkes.branching_bound, "leaders": self.hawkes.leadership()[:10]},
            "rough_volterra": {"hurst": self.rough_kernel.hurst, "factors": self.rough_kernel.factors,
                               "kernel_at_1": self.rough_kernel.approximate_kernel(1.0)},
            "variance_swap": asdict(self.last_variance_swap) if self.last_variance_swap else None,
            "last_fee_breakdown": asdict(self.last_fee_breakdown) if self.last_fee_breakdown else None,
            "trade_throttle": {"trade_count": self.throttler.trade_count, "daily_cap": self.throttler.cap,
                                "loss_streak": self.throttler.loss_streak, "lockout_reason": self.throttler.lockout_reason,
                                "cooldown_remaining_seconds": self.throttler.remaining_cooldown(now_epoch)},
            "risk_state": self.risk_state.value, "emergency_latched": self.emergency_latched,
            "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
            "paper_simulation_only": True, "heartbeat": self.heartbeat,
        }


class _DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], engine: Cycle33Engine):
        self.engine = engine
        self.sse_running = True
        super().__init__(address, _DashboardHandler)

    def shutdown(self) -> None:
        self.sse_running = False
        super().shutdown()


class _DashboardHandler(BaseHTTPRequestHandler):
    server: _DashboardServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler interface
        if self.path == "/health":
            self._write_json(200, {"status": "ok", "paper_simulation_only": True,
                                   "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
                                   "risk_state": self.server.engine.risk_state.value})
        elif self.path == "/telemetry":
            self._write_json(200, self.server.engine.telemetry_payload())
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                while self.server.sse_running:
                    payload = json.dumps(self.server.engine.telemetry_payload(), separators=(",", ":"), allow_nan=False)
                    self.wfile.write(("event: telemetry\ndata: " + payload + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
        else:
            self._write_json(404, {"error": "not_found"})


class TelemetryServer:
    """Threaded local HTTP/SSE server. Default bind is loopback for safety."""
    def __init__(self, engine: Cycle33Engine, host: str = "127.0.0.1", port: int = 8088):
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("dashboard server may bind only to loopback by default")
        if not 0 <= port <= 65535:
            raise ValueError("port must be in [0, 65535]")
        self.server = _DashboardServer((host, port), engine)
        self.thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        return self.server.server_address[0], self.server.server_address[1]

    def start(self) -> tuple[str, int]:
        if self.thread and self.thread.is_alive():
            return self.address
        self.thread = threading.Thread(target=self.server.serve_forever, name="cycle33-telemetry", daemon=True)
        self.thread.start()
        return self.address

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2.0)
