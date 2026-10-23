"""Cycle 38: Hawkes graph centrality, L3 cancellation shocks and Variance Gamma pricing.

Offline research reference. Standard library only. No broker adapter or live order path.
"""
from __future__ import annotations

import cmath
import json
import math
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable, Mapping, Sequence

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
ASSETS = ("HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "RELIANCE", "NIFTY50", "BANKNIFTY")


def _finite(x: float, name: str) -> float:
    x = float(x)
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _vector(x: Sequence[float], name: str, n: int | None = None) -> list[float]:
    out = [_finite(v, name) for v in x]
    if n is not None and len(out) != n:
        raise ValueError(f"{name} must have length {n}")
    return out


def _matrix(x: Sequence[Sequence[float]], name: str, n: int | None = None) -> list[list[float]]:
    out = [_vector(row, name) for row in x]
    if not out or any(len(row) != len(out) for row in out):
        raise ValueError(f"{name} must be a non-empty square matrix")
    if n is not None and len(out) != n:
        raise ValueError(f"{name} must be {n}x{n}")
    return out


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    return sum(x * y for x, y in zip(a, b))


def _matvec(a: Sequence[Sequence[float]], x: Sequence[float]) -> list[float]:
    return [_dot(row, x) for row in a]


def _max_row_sum(a: Sequence[Sequence[float]]) -> float:
    return max((sum(abs(v) for v in row) for row in a), default=0.0)


def spectral_radius_nonnegative(a: Sequence[Sequence[float]], iterations: int = 300, tolerance: float = 1e-12) -> float:
    """Power estimate of Perron root for a nonnegative square matrix.

    For stability enforcement, callers additionally contract with the infinity-norm
    upper bound; thus this estimate is diagnostic while the row-sum bound is safe.
    """
    m = _matrix(a, "matrix")
    if any(v < 0 for row in m for v in row):
        raise ValueError("spectral_radius_nonnegative requires nonnegative entries")
    n = len(m)
    if max((max(row) for row in m), default=0.0) == 0.0:
        return 0.0
    # Tiny positive perturbation avoids periodicity/zero-coordinate pathologies.
    eps = max(1e-15, _max_row_sum(m) * 1e-14)
    x = [1.0 / n] * n
    eigen = 0.0
    for _ in range(max(1, iterations)):
        y = [sum(m[i][j] * x[j] for j in range(n)) + eps * sum(x) for i in range(n)]
        norm = max(abs(v) for v in y)
        if norm == 0.0:
            return 0.0
        nxt = [v / norm for v in y]
        if max(abs(nxt[i] - x[i]) for i in range(n)) < tolerance:
            x = nxt
            eigen = sum(sum(m[i][j] * x[j] for j in range(n)) for i in range(n)) / max(sum(x), 1e-300)
            break
        x = nxt
    # Rayleigh-like Perron estimate; conservative bound is available separately.
    y = [sum(m[i][j] * x[j] for j in range(n)) for i in range(n)]
    denom = sum(x)
    eigen = sum(y) / denom if denom else 0.0
    return max(0.0, eigen)


@dataclass
class HawkesDirectedGraph:
    """Directed multivariate Hawkes network with alpha[i][j] meaning j -> i."""
    nodes: tuple[str, ...] = ASSETS
    alpha: list[list[float]] = field(default_factory=list)
    beta_by_source: list[float] = field(default_factory=list)
    baseline: list[float] = field(default_factory=list)
    max_spectral_radius: float = 0.89

    def __post_init__(self) -> None:
        n = len(self.nodes)
        if n < 2 or len(set(self.nodes)) != n:
            raise ValueError("nodes must be unique and contain at least two members")
        if not 0 < self.max_spectral_radius < 1:
            raise ValueError("max_spectral_radius must be in (0, 1)")
        if not self.alpha:
            self.alpha = [[0.0 if i == j else 0.015 for j in range(n)] for i in range(n)]
        self.alpha = _matrix(self.alpha, "alpha", n)
        if any(v < 0 for row in self.alpha for v in row):
            raise ValueError("Hawkes alpha values must be nonnegative")
        if not self.beta_by_source:
            self.beta_by_source = [1.0] * n
        self.beta_by_source = _vector(self.beta_by_source, "beta_by_source", n)
        if any(v <= 0 for v in self.beta_by_source):
            raise ValueError("beta values must be positive")
        if not self.baseline:
            self.baseline = [0.1] * n
        self.baseline = _vector(self.baseline, "baseline", n)
        if any(v <= 0 for v in self.baseline):
            raise ValueError("baseline rates must be positive")
        self.contract_stability()

    @property
    def branching_matrix(self) -> list[list[float]]:
        return [[self.alpha[i][j] / self.beta_by_source[j] for j in range(len(self.nodes))] for i in range(len(self.nodes))]

    @property
    def spectral_radius(self) -> float:
        return spectral_radius_nonnegative(self.branching_matrix)

    @property
    def stability_upper_bound(self) -> float:
        return _max_row_sum(self.branching_matrix)

    def contract_stability(self) -> float:
        """Scale all couplings conservatively so the branching row-sum bound is < cap."""
        branch = self.branching_matrix
        bound = _max_row_sum(branch)
        rho = spectral_radius_nonnegative(branch)
        factor = 1.0
        if bound >= self.max_spectral_radius:
            factor = min(factor, (self.max_spectral_radius * (1.0 - 1e-10)) / max(bound, 1e-300))
        if rho >= self.max_spectral_radius:
            factor = min(factor, (self.max_spectral_radius * (1.0 - 1e-10)) / max(rho, 1e-300))
        if factor < 1.0:
            self.alpha = [[v * factor for v in row] for row in self.alpha]
        return factor

    def set_alpha(self, alpha: Sequence[Sequence[float]]) -> float:
        candidate = _matrix(alpha, "alpha", len(self.nodes))
        if any(v < 0 for row in candidate for v in row):
            raise ValueError("alpha values must be nonnegative")
        old = self.alpha
        self.alpha = candidate
        try:
            return self.contract_stability()
        except Exception:
            self.alpha = old
            raise

    def centrality(self) -> dict[str, dict[str, float]]:
        a = self.branching_matrix
        incoming = [sum(row) for row in a]      # absorption at node i
        outgoing = [sum(a[i][j] for i in range(len(a))) for j in range(len(a))]  # propagation from j
        return {node: {"in_degree_absorption": incoming[i], "out_degree_propagation": outgoing[i]}
                for i, node in enumerate(self.nodes)}

    def leadership(self) -> list[dict[str, float | str]]:
        c = self.centrality()
        total = sum(v["out_degree_propagation"] for v in c.values())
        return [{"node": name, "score": vals["out_degree_propagation"] / total if total else 0.0}
                for name, vals in sorted(c.items(), key=lambda item: item[1]["out_degree_propagation"], reverse=True)]

    def intensity(self, event_ages: Sequence[Sequence[float]] | None = None) -> list[float]:
        n = len(self.nodes)
        if event_ages is None:
            return list(self.baseline)
        if len(event_ages) != n:
            raise ValueError("event_ages must have one source list per node")
        rates = list(self.baseline)
        for i in range(n):
            for j in range(n):
                for age in event_ages[j]:
                    age = _finite(age, "event age")
                    if age < 0:
                        raise ValueError("event ages cannot be negative")
                    rates[i] += self.alpha[i][j] * math.exp(-self.beta_by_source[j] * age)
        return rates


@dataclass
class CancellationShockModel:
    baseline_intensity: float = 0.25
    excitation_alphas: tuple[float, ...] = (0.8, 0.4, 0.2)
    excitation_betas: tuple[float, ...] = (12.0, 3.0, 0.7)
    gamma_ofi: float = 0.25
    hazard_horizon_seconds: float = 0.05
    cascade_threshold: float = 0.70
    events: list[tuple[float, float, int]] = field(default_factory=list)  # time, mark, level

    def __post_init__(self) -> None:
        self.baseline_intensity = _finite(self.baseline_intensity, "baseline_intensity")
        self.gamma_ofi = _finite(self.gamma_ofi, "gamma_ofi")
        self.hazard_horizon_seconds = _finite(self.hazard_horizon_seconds, "hazard_horizon_seconds")
        if self.baseline_intensity < 0 or self.gamma_ofi < 0 or self.hazard_horizon_seconds <= 0:
            raise ValueError("invalid cancellation model rates/horizon")
        self.excitation_alphas = tuple(_vector(self.excitation_alphas, "excitation_alphas"))
        self.excitation_betas = tuple(_vector(self.excitation_betas, "excitation_betas"))
        if len(self.excitation_alphas) != len(self.excitation_betas) or not self.excitation_alphas:
            raise ValueError("alpha/beta excitation tuples must be same nonzero length")
        if any(v < 0 for v in self.excitation_alphas) or any(v <= 0 for v in self.excitation_betas):
            raise ValueError("alphas must be nonnegative and betas positive")
        if not 0 <= self.cascade_threshold <= 1:
            raise ValueError("cascade_threshold must be in [0, 1]")

    def add_cancel_event(self, timestamp: float, mark: float = 1.0, level: int = 1) -> None:
        timestamp, mark = _finite(timestamp, "timestamp"), _finite(mark, "mark")
        if timestamp < 0 or mark < 0 or not 1 <= int(level) <= 5:
            raise ValueError("event requires nonnegative time/mark and L1-L5 level")
        self.events.append((timestamp, mark, int(level)))
        self.events.sort(key=lambda x: x[0])

    def intensity(self, timestamp: float, ofi: float = 0.0) -> float:
        timestamp, ofi = _finite(timestamp, "timestamp"), _finite(ofi, "ofi")
        if timestamp < 0:
            raise ValueError("timestamp must be nonnegative")
        excitation = 0.0
        for t, mark, level in self.events:
            if t <= timestamp:
                idx = min(level - 1, len(self.excitation_alphas) - 1)
                excitation += self.excitation_alphas[idx] * mark * math.exp(-self.excitation_betas[idx] * (timestamp - t))
        return self.baseline_intensity + excitation + self.gamma_ofi * max(0.0, -ofi)

    def integrated_intensity(self, horizon: float, timestamp: float = 0.0, ofi: float = 0.0) -> float:
        horizon, timestamp, ofi = _finite(horizon, "horizon"), _finite(timestamp, "timestamp"), _finite(ofi, "ofi")
        if horizon < 0 or timestamp < 0:
            raise ValueError("horizon and timestamp must be nonnegative")
        total = (self.baseline_intensity + self.gamma_ofi * max(0.0, -ofi)) * horizon
        for t, mark, level in self.events:
            if t <= timestamp:
                idx = min(level - 1, len(self.excitation_alphas) - 1)
                beta = self.excitation_betas[idx]
                residual = self.excitation_alphas[idx] * mark * math.exp(-beta * (timestamp - t))
                total += residual * (-math.expm1(-beta * horizon)) / beta
        return max(0.0, total)

    def survival_probability(self, horizon: float, timestamp: float = 0.0, ofi: float = 0.0) -> float:
        return math.exp(-min(745.0, self.integrated_intensity(horizon, timestamp, ofi)))

    def cascade_hazard(self, timestamp: float, ofi: float = 0.0) -> float:
        return min(1.0, max(0.0, 1.0 - self.survival_probability(self.hazard_horizon_seconds, timestamp, ofi)))

    def should_pull_quotes(self, timestamp: float, ofi: float = 0.0) -> bool:
        return self.cascade_hazard(timestamp, ofi) >= self.cascade_threshold


@dataclass(frozen=True)
class VGParameters:
    sigma: float = 0.20
    nu: float = 0.20
    theta: float = -0.10

    def __post_init__(self) -> None:
        if not math.isfinite(self.sigma) or self.sigma <= 0:
            raise ValueError("sigma must be finite and positive")
        if not math.isfinite(self.nu) or self.nu <= 0:
            raise ValueError("nu must be finite and positive")
        if not math.isfinite(self.theta):
            raise ValueError("theta must be finite")
        if 1.0 - self.theta * self.nu - 0.5 * self.sigma * self.sigma * self.nu <= 0:
            raise ValueError("VG parameters violate martingale moment restriction")


@dataclass
class VarianceGammaSurface:
    params: VGParameters = field(default_factory=VGParameters)
    risk_free_rate: float = 0.05
    dividend_yield: float = 0.0
    damping: float = 1.5
    integration_upper: float = 120.0
    integration_steps: int = 800

    def __post_init__(self) -> None:
        self.risk_free_rate = _finite(self.risk_free_rate, "risk_free_rate")
        self.dividend_yield = _finite(self.dividend_yield, "dividend_yield")
        self.damping = _finite(self.damping, "damping")
        self.integration_upper = _finite(self.integration_upper, "integration_upper")
        if self.damping <= 0 or self.integration_upper <= 0 or self.integration_steps < 20:
            raise ValueError("damping/upper must be positive and integration_steps >= 20")
        if self.integration_steps % 2:
            self.integration_steps += 1

    def characteristic_function(self, u: complex | float, maturity: float = 1.0) -> complex:
        maturity = _finite(maturity, "maturity")
        if maturity < 0:
            raise ValueError("maturity cannot be negative")
        if maturity == 0:
            return 1.0 + 0.0j
        z = complex(u)
        p = self.params
        base = 1.0 - 1j * p.theta * p.nu * z + 0.5 * p.sigma * p.sigma * p.nu * z * z
        omega = math.log(1.0 - p.theta * p.nu - 0.5 * p.sigma * p.sigma * p.nu) / p.nu
        return cmath.exp(1j * z * (self.risk_free_rate - self.dividend_yield + omega) * maturity) * base ** (-maturity / p.nu)

    def call_price(self, spot: float, strike: float, maturity: float, *, steps: int | None = None) -> float:
        spot, strike, maturity = _finite(spot, "spot"), _finite(strike, "strike"), _finite(maturity, "maturity")
        if spot <= 0 or strike <= 0 or maturity < 0:
            raise ValueError("spot/strike must be positive and maturity nonnegative")
        if maturity == 0:
            return max(spot - strike, 0.0)
        n = int(steps or self.integration_steps)
        n = max(20, n + n % 2)
        h = self.integration_upper / n
        alpha = self.damping
        k = math.log(strike / spot)
        def integrand(u: float) -> float:
            z = complex(u, -(alpha + 1.0))
            phi = self.characteristic_function(z, maturity)
            den = complex(alpha * alpha + alpha - u * u, (2.0 * alpha + 1.0) * u)
            value = cmath.exp(-1j * u * k) * math.exp(-self.risk_free_rate * maturity) * phi / den
            return value.real
        # Composite Simpson integral.
        total = integrand(0.0) + integrand(self.integration_upper)
        for i in range(1, n):
            total += (4.0 if i % 2 else 2.0) * integrand(i * h)
        call = spot * math.exp(-alpha * k) * (h / 3.0) * total / math.pi
        # Numeric tails can create tiny negative prices; intrinsic is a safe lower floor.
        intrinsic = max(spot * math.exp(-self.dividend_yield * maturity) - strike * math.exp(-self.risk_free_rate * maturity), 0.0)
        return max(intrinsic, min(spot * math.exp(-self.dividend_yield * maturity), call))

    def put_price(self, spot: float, strike: float, maturity: float) -> float:
        call = self.call_price(spot, strike, maturity)
        return max(0.0, call - spot * math.exp(-self.dividend_yield * maturity) + strike * math.exp(-self.risk_free_rate * maturity))

    def price_strip(self, spot: float, strikes: Sequence[float], maturity: float) -> list[dict[str, float]]:
        ordered = _vector(strikes, "strikes")
        if any(k <= 0 for k in ordered) or ordered != sorted(ordered) or len(set(ordered)) != len(ordered):
            raise ValueError("strikes must be positive, sorted, and unique")
        return [{"strike": k, "call": self.call_price(spot, k, maturity), "put": self.put_price(spot, k, maturity)} for k in ordered]

    @staticmethod
    def butterfly_density(prices: Sequence[float], strike_spacing: float) -> list[float]:
        prices = _vector(prices, "prices")
        strike_spacing = _finite(strike_spacing, "strike_spacing")
        if strike_spacing <= 0 or len(prices) < 3:
            raise ValueError("positive spacing and at least 3 prices required")
        return [(prices[i - 1] - 2.0 * prices[i] + prices[i + 1]) / (strike_spacing * strike_spacing) for i in range(1, len(prices) - 1)]

    def relative_value_basis(self, strikes: Sequence[float], model_prices: Sequence[float], market_prices: Sequence[float]) -> list[dict[str, float]]:
        ks = _vector(strikes, "strikes")
        model = _vector(model_prices, "model_prices", len(ks))
        market = _vector(market_prices, "market_prices", len(ks))
        return [{"strike": k, "model_minus_market": m - p} for k, m, p in zip(ks, model, market)]


@dataclass(frozen=True)
class OptionLeg:
    side: str
    premium: float
    quantity: int
    contract: str = "INDEX_OPTION"

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if not math.isfinite(self.premium) or self.premium < 0 or self.quantity < 0:
            raise ValueError("premium and quantity must be nonnegative and finite")

    @property
    def turnover(self) -> float:
        return self.premium * self.quantity


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
    statutory_total: float
    slippage: float
    impact_hurdle: float
    total_hurdle: float


@dataclass(frozen=True)
class CostConfig:
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    exchange_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    brokerage_per_leg: float = 20.0

    def __post_init__(self) -> None:
        vals = (self.stt_sell_rate, self.stamp_buy_rate, self.exchange_per_crore, self.sebi_per_crore, self.gst_rate, self.brokerage_per_leg)
        if any(not math.isfinite(v) or v < 0 for v in vals):
            raise ValueError("cost rates must be finite and nonnegative")


@dataclass
class StatutoryCostCalculator:
    config: CostConfig = field(default_factory=CostConfig)

    def calculate(self, legs: Sequence[OptionLeg], *, slippage: float = 0.0, impact_hurdle: float = 0.0) -> FeeBreakdown:
        slippage, impact_hurdle = _finite(slippage, "slippage"), _finite(impact_hurdle, "impact_hurdle")
        if slippage < 0 or impact_hurdle < 0:
            raise ValueError("slippage and impact hurdle must be nonnegative")
        buy = sum(x.turnover for x in legs if x.side == "BUY")
        sell = sum(x.turnover for x in legs if x.side == "SELL")
        total = buy + sell
        stt = sell * self.config.stt_sell_rate
        stamp = buy * self.config.stamp_buy_rate
        exchange = total * self.config.exchange_per_crore / 1e7
        sebi = total * self.config.sebi_per_crore / 1e7
        brokerage = len(legs) * self.config.brokerage_per_leg
        gst = (exchange + sebi + brokerage) * self.config.gst_rate
        statutory = stt + stamp + exchange + sebi + brokerage + gst
        return FeeBreakdown(buy, sell, total, stt, stamp, exchange, sebi, brokerage, gst, statutory, slippage, impact_hurdle, statutory + slippage + impact_hurdle)

    def net_alpha(self, gross_alpha: float, costs: FeeBreakdown) -> float:
        return _finite(gross_alpha, "gross_alpha") - costs.total_hurdle

    def passes_gate(self, gross_alpha: float, costs: FeeBreakdown) -> bool:
        return self.net_alpha(gross_alpha, costs) > 0.0


@dataclass
class AntiOvertradingThrottler:
    max_daily_trades: int = 15
    base_cooldown_seconds: float = 900.0
    theta_h: float = 1.0
    lambda_baseline: float = 1.0
    loss_limit: int = 3
    revenge_ratio: float = 1.25
    rapid_fill_seconds: float = 30.0
    trade_count: int = 0
    consecutive_losses: int = 0
    cooldown_until: float = 0.0
    previous_size: float = 0.0
    previous_fill_time: float | None = None

    def __post_init__(self) -> None:
        if self.max_daily_trades < 0 or self.loss_limit < 1:
            raise ValueError("trade limit must be nonnegative and loss_limit positive")
        if self.base_cooldown_seconds < 0 or self.theta_h < 0 or self.lambda_baseline <= 0:
            raise ValueError("invalid cooldown parameters")
        if self.revenge_ratio <= 1 or self.rapid_fill_seconds < 0:
            raise ValueError("invalid behavioral thresholds")

    @staticmethod
    def optimal_daily_trade_cap(alpha: float, cost: float, risk: float) -> int:
        alpha, cost, risk = _finite(alpha, "alpha"), _finite(cost, "cost"), _finite(risk, "risk")
        if risk <= 0:
            raise ValueError("risk must be positive")
        return max(0, int(round((alpha - cost) / risk)))

    def dynamic_cooldown(self, hawkes_intensity: float) -> float:
        lam = _finite(hawkes_intensity, "hawkes_intensity")
        if lam < 0:
            raise ValueError("hawkes_intensity must be nonnegative")
        return self.base_cooldown_seconds * (1.0 + self.theta_h * (lam / self.lambda_baseline))

    def locked(self, now: float | None = None) -> bool:
        now = time.time() if now is None else _finite(now, "now")
        return self.trade_count >= self.max_daily_trades or now < self.cooldown_until

    def record_fill(self, *, timestamp: float, size: float, pnl: float, hawkes_intensity: float = 0.0) -> bool:
        timestamp, size, pnl = _finite(timestamp, "timestamp"), _finite(size, "size"), _finite(pnl, "pnl")
        if timestamp < 0 or size <= 0:
            raise ValueError("timestamp must be nonnegative and size positive")
        if self.previous_fill_time is not None and timestamp < self.previous_fill_time:
            raise ValueError("fill timestamps must be nondecreasing")
        reason = False
        if self.previous_fill_time is not None and timestamp - self.previous_fill_time < self.rapid_fill_seconds:
            reason = True
        if self.previous_size > 0 and size / self.previous_size > self.revenge_ratio:
            reason = True
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        if self.consecutive_losses >= self.loss_limit:
            reason = True
        self.trade_count += 1
        self.cooldown_until = max(self.cooldown_until, timestamp + self.dynamic_cooldown(hawkes_intensity)) if reason else self.cooldown_until
        self.previous_size = size
        self.previous_fill_time = timestamp
        return reason

    def reset_session(self) -> None:
        self.trade_count = 0
        self.consecutive_losses = 0
        self.cooldown_until = 0.0
        self.previous_size = 0.0
        self.previous_fill_time = None


class RiskState(str, Enum):
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    CANCELLATION_SHOCK = "CANCELLATION_SHOCK"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START = "START"
    SHOCK = "SHOCK"
    CLEAR_SHOCK = "CLEAR_SHOCK"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"
    RESET = "RESET"


@dataclass
class RiskStateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state is RiskState.EMERGENCY_UNWIND:
            self.emergency_latched = True

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown event; fail closed")
        if self.emergency_latched and event is not RiskEvent.RECOVERY_ACK:
            self.history.append((event.value, "blocked_latched"))
            return self.state
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event is RiskEvent.START and self.state is RiskState.IDLE:
            self.state = RiskState.MONITORING
        elif event is RiskEvent.SHOCK and self.state in {RiskState.IDLE, RiskState.MONITORING}:
            self.state = RiskState.CANCELLATION_SHOCK
        elif event is RiskEvent.CLEAR_SHOCK and self.state is RiskState.CANCELLATION_SHOCK:
            self.state = RiskState.MONITORING
        elif event is RiskEvent.RESET and not self.emergency_latched:
            self.state = RiskState.IDLE
        self.history.append((event.value, self.state.value))
        return self.state


@dataclass
class Cycle38ExecutionEngine:
    graph: HawkesDirectedGraph = field(default_factory=HawkesDirectedGraph)
    cancellation: CancellationShockModel = field(default_factory=CancellationShockModel)
    vg_surface: VarianceGammaSurface = field(default_factory=VarianceGammaSurface)
    costs: StatutoryCostCalculator = field(default_factory=StatutoryCostCalculator)
    throttler: AntiOvertradingThrottler = field(default_factory=AntiOvertradingThrottler)
    risk: RiskStateMachine = field(default_factory=RiskStateMachine)
    latest_gross_alpha: float = 0.0
    latest_net_alpha: float = 0.0
    latest_costs: FeeBreakdown | None = None
    last_snapshot: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        if LIVE_ORDER_DISPATCH_ENABLED is not False or REAL_BROKER_FILLS_LOCKED is not True:
            raise RuntimeError("paper-only safety invariant violated")

    def evaluate_candidate(self, gross_alpha: float, legs: Sequence[OptionLeg], *, slippage: float = 0.0, impact_hurdle: float = 0.0, now: float | None = None) -> dict[str, Any]:
        with self._lock:
            gross_alpha = _finite(gross_alpha, "gross_alpha")
            costs = self.costs.calculate(legs, slippage=slippage, impact_hurdle=impact_hurdle)
            net = self.costs.net_alpha(gross_alpha, costs)
            now = time.time() if now is None else _finite(now, "now")
            allowed_state = not self.risk.emergency_latched and self.risk.state not in {RiskState.CANCELLATION_SHOCK, RiskState.EMERGENCY_UNWIND}
            allowed = allowed_state and not self.throttler.locked(now) and self.costs.passes_gate(gross_alpha, costs)
            self.latest_gross_alpha = gross_alpha
            self.latest_net_alpha = net if allowed else 0.0
            self.latest_costs = costs
            return {"allowed": allowed, "gross_alpha": gross_alpha, "net_alpha": net if allowed else 0.0, "gross_minus_hurdle": net, "costs": asdict(costs), "risk_state": self.risk.state.value, "throttled": self.throttler.locked(now)}

    def process_cancel_event(self, timestamp: float, *, mark: float = 1.0, level: int = 1, ofi: float = 0.0) -> dict[str, float | bool | str]:
        with self._lock:
            self.cancellation.add_cancel_event(timestamp, mark, level)
            hazard = self.cancellation.cascade_hazard(timestamp, ofi)
            if hazard >= self.cancellation.cascade_threshold and not self.risk.emergency_latched:
                self.risk.transition(RiskEvent.SHOCK)
            return {"timestamp": timestamp, "intensity": self.cancellation.intensity(timestamp, ofi), "hazard": hazard, "quote_pullback": hazard >= self.cancellation.cascade_threshold, "risk_state": self.risk.state.value}

    def telemetry(self, *, now: float | None = None, ofi: float = 0.0) -> dict[str, Any]:
        now = time.time() if now is None else _finite(now, "now")
        with self._lock:
            cancel_intensity = self.cancellation.intensity(now, ofi)
            cancel_hazard = self.cancellation.cascade_hazard(now, ofi)
            payload = {
                "timestamp_ist": datetime.fromtimestamp(now, IST).isoformat(),
                "timestamp_epoch": now,
                "hawkes_graph": {"nodes": list(self.graph.nodes), "spectral_radius": self.graph.spectral_radius, "stability_upper_bound": self.graph.stability_upper_bound, "centrality": self.graph.centrality(), "leaders": self.graph.leadership(), "branching_matrix": self.graph.branching_matrix},
                "cancellation": {"intensity": cancel_intensity, "hazard": cancel_hazard, "quote_pullback": cancel_hazard >= self.cancellation.cascade_threshold},
                "vg_surface": {"sigma": self.vg_surface.params.sigma, "nu": self.vg_surface.params.nu, "theta": self.vg_surface.params.theta, "risk_free_rate": self.vg_surface.risk_free_rate},
                "net_expected_alpha": self.latest_net_alpha,
                "latest_costs": asdict(self.latest_costs) if self.latest_costs else None,
                "risk_state": self.risk.state.value,
                "throttle": {"trade_count": self.throttler.trade_count, "max_daily_trades": self.throttler.max_daily_trades, "cooldown_until": self.throttler.cooldown_until, "locked": self.throttler.locked(now)},
                "safety": {"LIVE_ORDER_DISPATCH_ENABLED": False, "REAL_BROKER_FILLS_LOCKED": True, "paper_ledger_epoch": PAPER_LEDGER_EPOCH},
            }
            self.last_snapshot = payload
            return payload

    def json_telemetry(self, **kwargs: Any) -> str:
        return json.dumps(self.telemetry(**kwargs), sort_keys=True, allow_nan=False, separators=(",", ":"))


class TelemetryHTTPServer:
    """Local JSON/SSE HTTP server. SSE sends a bounded event burst then closes cleanly."""
    def __init__(self, engine: Cycle38ExecutionEngine, host: str = "127.0.0.1", port: int = 8088, *, sse_events: int = 3, sse_interval: float = 0.05):
        if not (0 <= port <= 65535) or sse_events < 1 or sse_interval < 0:
            raise ValueError("invalid telemetry server parameters")
        self.engine, self.host, self.port = engine, host, port
        self.sse_events, self.sse_interval = sse_events, sse_interval
        engine_ref = engine
        event_count, interval = sse_events, sse_interval
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, fmt: str, *args: Any) -> None:
                return
            def _send(self, code: int, body: bytes, ctype: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path == "/health":
                    body = json.dumps({"ok": True, "risk_state": engine_ref.risk.state.value, "safety": {"LIVE_ORDER_DISPATCH_ENABLED": False, "REAL_BROKER_FILLS_LOCKED": True}}, allow_nan=False).encode()
                    self._send(200, body, "application/json; charset=utf-8")
                elif path == "/telemetry":
                    self._send(200, engine_ref.json_telemetry().encode(), "application/json; charset=utf-8")
                elif path == "/events":
                    body = bytearray()
                    for i in range(event_count):
                        data = engine_ref.json_telemetry()
                        body.extend(f"id: {i}\nevent: telemetry\ndata: {data}\n\n".encode())
                        if i + 1 < event_count and interval:
                            time.sleep(interval)
                    self._send(200, bytes(body), "text/event-stream; charset=utf-8")
                else:
                    self._send(404, b'{"error":"not found"}', "application/json; charset=utf-8")
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.httpd.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="cycle38-telemetry", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2.0)
