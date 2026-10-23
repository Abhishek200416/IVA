"""Cycle 27: rough Volterra volatility, expiry pinning, MLOFI jumps and safety controls.

Offline / paper-simulation research reference only. No exchange or broker connectivity.
LIVE_ORDER_DISPATCH_ENABLED is intentionally hard-coded False.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import exp, floor, isfinite, lgamma, log, sqrt
from typing import Iterable, Optional, Sequence

LIVE_ORDER_DISPATCH_ENABLED = False
SECONDS_PER_DAY = 86_400.0


def _finite(value: float, name: str) -> float:
    v = float(value)
    if not isfinite(v):
        raise ValueError(f"{name} must be finite")
    return v


def _nonnegative(value: float, name: str) -> float:
    v = _finite(value, name)
    if v < 0:
        raise ValueError(f"{name} must be nonnegative")
    return v


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def _hhmm_minutes(hhmm: str) -> int:
    if not isinstance(hhmm, str) or len(hhmm) != 5 or hhmm[2] != ":":
        raise ValueError("time must be HH:MM")
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:])
    except ValueError as exc:
        raise ValueError("time must be HH:MM") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("invalid time")
    return 60 * h + m


# ---------------------------------------------------------------------------
# Statutory friction on options premium turnover
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeeConfig:
    """Configurable schedule; confirm date/applicability against contract notes.

    NSE options charge is the published all-in outflow of Rs 3,553/crore from
    2026-03-01. GST is modeled on exchange + SEBI + brokerage charges only.
    """
    options_sell_stt_rate: float = 0.0015
    nse_options_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    equity_options_stamp_buy_rate: float = 0.00003
    brokerage_per_order: float = 0.0
    gst_on_exchange_sebi_brokerage: bool = True

    def __post_init__(self) -> None:
        for name in ("options_sell_stt_rate", "nse_options_per_crore",
                     "sebi_per_crore", "gst_rate", "equity_options_stamp_buy_rate",
                     "brokerage_per_order"):
            _nonnegative(getattr(self, name), name)
        if self.gst_rate > 1 or self.options_sell_stt_rate > 1:
            raise ValueError("tax rates must be decimal fractions in [0, 1]")
        if self.equity_options_stamp_buy_rate > 1:
            raise ValueError("stamp rate must be in [0, 1]")


@dataclass(frozen=True)
class FeeBreakdown:
    premium_turnover: float
    units: int
    stt: float
    nse_exchange_charge: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    half_spread_slippage: float
    permanent_cross_impact: float
    total_friction: float


class StatutoryCostCalculator:
    """Indian listed equity-options friction calculator on premium turnover."""
    def __init__(self, config: FeeConfig = FeeConfig()) -> None:
        self.config = config

    def calculate(self, *, premium: float, lots: int, lot_size: int, side: str,
                  half_spread_per_unit: float = 0.0,
                  spread_multiplier: float = 1.0,
                  permanent_impact_per_unit: float = 0.0,
                  brokerage_per_order: Optional[float] = None) -> FeeBreakdown:
        premium = _nonnegative(premium, "premium")
        if not isinstance(lots, int) or isinstance(lots, bool) or lots < 0:
            raise ValueError("lots must be a nonnegative integer")
        if not isinstance(lot_size, int) or isinstance(lot_size, bool) or lot_size <= 0:
            raise ValueError("lot_size must be a positive integer")
        side = str(side).upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        spread = _nonnegative(half_spread_per_unit, "half_spread_per_unit")
        spread_multiplier = _nonnegative(spread_multiplier, "spread_multiplier")
        impact_per_unit = _nonnegative(permanent_impact_per_unit, "permanent_impact_per_unit")
        brokerage = self.config.brokerage_per_order if brokerage_per_order is None else _nonnegative(brokerage_per_order, "brokerage_per_order")
        units = lots * lot_size
        turnover = premium * units
        # Rs per crore -> multiply turnover in Rs by rate / 10,000,000.
        exchange = turnover * self.config.nse_options_per_crore / 10_000_000.0
        sebi = turnover * self.config.sebi_per_crore / 10_000_000.0
        stt = turnover * self.config.options_sell_stt_rate if side == "SELL" else 0.0
        stamp = turnover * self.config.equity_options_stamp_buy_rate if side == "BUY" else 0.0
        gst_base = brokerage + (exchange + sebi if self.config.gst_on_exchange_sebi_brokerage else 0.0)
        gst = gst_base * self.config.gst_rate
        spread_cost = units * spread * spread_multiplier
        impact_cost = units * impact_per_unit
        charges = (stt, exchange, sebi, gst, stamp, brokerage, spread_cost, impact_cost)
        if not all(isfinite(x) for x in (turnover, *charges)):
            raise ValueError("cost calculation overflowed")
        return FeeBreakdown(
            premium_turnover=turnover, units=units, stt=stt,
            nse_exchange_charge=exchange, sebi_fee=sebi, gst=gst,
            stamp_duty=stamp, brokerage=brokerage,
            half_spread_slippage=spread_cost,
            permanent_cross_impact=impact_cost,
            total_friction=sum(charges),
        )

    @staticmethod
    def profitability_gate(expected_gross_alpha: float, fees: FeeBreakdown) -> bool:
        alpha = _finite(expected_gross_alpha, "expected_gross_alpha")
        # Strict inequality is intentional: equality does not clear the hurdle.
        return alpha > fees.total_friction


# ---------------------------------------------------------------------------
# Rough volatility: fractional Volterra kernel as a sum of exponentials
# ---------------------------------------------------------------------------

class RoughVolterraKernel:
    r"""Positive sum-of-exponentials approximation to K(t)=t^(H-1/2)/Gamma(H+1/2).

    Uses the Laplace representation of t^-alpha, alpha=1/2-H, and logarithmic
    quadrature rates. ``step(dW)`` advances OU-like state variables and returns
    their weighted sum, approximating a discrete Volterra convolution. Accuracy
    depends on rate bounds, number of terms, and the time-step range.
    """
    def __init__(self, hurst: float, n_terms: int = 24,
                 min_rate: float = 1e-3, max_rate: float = 1e3,
                 dt: float = 1.0) -> None:
        self.hurst = _finite(hurst, "hurst")
        if not 0.0 < self.hurst < 0.5:
            raise ValueError("hurst must be strictly between 0 and 0.5")
        if not isinstance(n_terms, int) or isinstance(n_terms, bool) or n_terms < 2:
            raise ValueError("n_terms must be an integer >= 2")
        self.min_rate = _finite(min_rate, "min_rate")
        self.max_rate = _finite(max_rate, "max_rate")
        self.dt = _finite(dt, "dt")
        if self.min_rate <= 0 or self.max_rate <= self.min_rate or self.dt <= 0:
            raise ValueError("rates and dt must be positive with max_rate > min_rate")
        self.n_terms = n_terms
        self.rates = self._logspace(self.min_rate, self.max_rate, n_terms)
        self.weights = self._make_weights()
        self.decays = tuple(exp(-r * self.dt) for r in self.rates)
        self.states = [0.0] * self.n_terms
        self.steps = 0

    @staticmethod
    def _logspace(lo: float, hi: float, n: int) -> tuple[float, ...]:
        a, b = log(lo), log(hi)
        return tuple(exp(a + (b-a)*i/(n-1)) for i in range(n))

    def _make_weights(self) -> tuple[float, ...]:
        alpha = 0.5 - self.hurst
        # Midpoint log-quadrature: dx = x d(log x).
        log_step = (log(self.max_rate) - log(self.min_rate)) / (self.n_terms - 1)
        norm = exp(-lgamma(alpha) - lgamma(self.hurst + 0.5))
        return tuple(norm * log_step * r**alpha for r in self.rates)

    def kernel_value(self, t: float) -> float:
        t = _finite(t, "t")
        if t <= 0:
            raise ValueError("kernel_value requires t > 0")
        return sum(w * exp(-r*t) for r, w in zip(self.rates, self.weights))

    def reset(self) -> None:
        self.states = [0.0] * self.n_terms
        self.steps = 0

    def step(self, increment: float) -> float:
        """Consume a finite innovation/increment; returns current lifted factor."""
        increment = _finite(increment, "increment")
        self.states = [d*s + increment for d, s in zip(self.decays, self.states)]
        self.steps += 1
        return sum(w*s for w, s in zip(self.weights, self.states))

    def fractional_integral(self, increments: Iterable[float]) -> tuple[float, ...]:
        return tuple(self.step(x) for x in increments)

    def state_vector(self) -> tuple[float, ...]:
        return tuple(self.states)


# ---------------------------------------------------------------------------
# Expiry strike pinning and liquidity black-hole stress model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrikeExposure:
    strike: float
    open_interest: float
    gamma: float

    def __post_init__(self) -> None:
        _finite(self.strike, "strike")
        _nonnegative(self.open_interest, "open_interest")
        _finite(self.gamma, "gamma")
        if self.strike <= 0:
            raise ValueError("strike must be positive")


@dataclass(frozen=True)
class ExpiryPinResult:
    pinned_strike: Optional[float]
    pin_strength: float
    pin_break_threshold_points: float
    distance_from_pin: float
    broke_pin: bool
    expiry_pressure: float
    black_hole_stress: float
    estimated_depth_fraction: float
    spread_multiplier: float


class ExpiryPinDynamicsModel:
    """Heuristic gamma/OI pin-pressure model; not a causal dealer-position model."""
    def __init__(self, base_break_threshold_points: float = 20.0,
                 min_depth_fraction: float = 0.10, max_spread_multiplier: float = 10.0,
                 stress_break_boost: float = 0.75) -> None:
        self.base_threshold = _nonnegative(base_break_threshold_points, "base_break_threshold_points")
        if self.base_threshold <= 0:
            raise ValueError("base break threshold must be positive")
        self.min_depth_fraction = _finite(min_depth_fraction, "min_depth_fraction")
        if not 0 < self.min_depth_fraction <= 1:
            raise ValueError("min_depth_fraction must be in (0, 1]")
        self.max_spread_multiplier = _finite(max_spread_multiplier, "max_spread_multiplier")
        if self.max_spread_multiplier < 1:
            raise ValueError("max_spread_multiplier must be >= 1")
        self.stress_break_boost = _nonnegative(stress_break_boost, "stress_break_boost")

    def evaluate(self, *, spot: float, hhmm_ist: str,
                 strikes: Sequence[StrikeExposure], market_depth_units: float = 1.0) -> ExpiryPinResult:
        spot = _finite(spot, "spot")
        if spot <= 0:
            raise ValueError("spot must be positive")
        depth = _nonnegative(market_depth_units, "market_depth_units")
        minute = _hhmm_minutes(hhmm_ist)
        # Pressure ramp is active only from 15:00 to 15:30 IST.
        if 15*60 <= minute <= 15*60+30:
            pressure = (minute - 15*60) / 30.0
        else:
            pressure = 0.0
        usable = [s for s in strikes if s.open_interest > 0 and abs(s.gamma) > 0]
        if not usable:
            threshold = self.base_threshold
            distance = float("inf")
            broke = False
            pin_strength = 0.0
            black_hole = 0.0
            depth_fraction = 1.0
            spread_mult = 1.0
            return ExpiryPinResult(None, pin_strength, threshold, distance, broke,
                                   pressure, black_hole, depth_fraction, spread_mult)
        exposures = [s.open_interest * abs(s.gamma) for s in usable]
        total = sum(exposures)
        idx = max(range(len(usable)), key=lambda i: exposures[i])
        pin = usable[idx].strike
        pin_strength = exposures[idx] / total if total > 0 else 0.0
        threshold = self.base_threshold * (1.0 + 0.5 * (1.0 - pin_strength))
        distance = abs(spot - pin)
        broke = distance > threshold
        # A break near expiry can amplify an already stressed market rapidly.
        black_hole = _clamp(pressure * pin_strength + (self.stress_break_boost if broke else 0.0), 0.0, 1.0)
        depth_fraction = max(self.min_depth_fraction, 1.0 - 0.9 * black_hole)
        spread_mult = 1.0 + (self.max_spread_multiplier - 1.0) * black_hole
        if depth == 0:
            depth_fraction = self.min_depth_fraction
            spread_mult = self.max_spread_multiplier
        return ExpiryPinResult(pin, pin_strength, threshold, distance, broke,
                               pressure, black_hole, depth_fraction, spread_mult)


# ---------------------------------------------------------------------------
# Five-level MLOFI and fractional-memory jump intensity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BookLevel:
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float

    def __post_init__(self) -> None:
        for name in ("bid_price", "bid_size", "ask_price", "ask_size"):
            _nonnegative(getattr(self, name), name)
        if self.bid_price <= 0 or self.ask_price <= 0 or self.bid_price > self.ask_price:
            raise ValueError("invalid bid/ask prices")


@dataclass(frozen=True)
class MLOFIObservation:
    mlofi: float
    normalized_imbalance: float
    intensity: float
    jump_probability: float
    signed_jump_score: float


class MLOFIJumpDetector:
    """Five-level depth OFI with exponential Hawkes excitation and fractional tail."""
    def __init__(self, levels: int = 5, baseline_intensity: float = 0.02,
                 excitation: float = 0.35, decay: float = 0.8,
                 fractional_exponent: float = 0.35,
                 level_decay: float = 0.65, history_limit: int = 512) -> None:
        if levels != 5:
            raise ValueError("Cycle 27 detector requires exactly five levels")
        self.levels = levels
        self.baseline = _nonnegative(baseline_intensity, "baseline_intensity")
        self.excitation = _nonnegative(excitation, "excitation")
        self.decay = _nonnegative(decay, "decay")
        self.fractional_exponent = _finite(fractional_exponent, "fractional_exponent")
        if not 0 < self.fractional_exponent < 1:
            raise ValueError("fractional_exponent must be in (0, 1)")
        self.level_decay = _finite(level_decay, "level_decay")
        if not 0 < self.level_decay <= 1:
            raise ValueError("level_decay must be in (0, 1]")
        if not isinstance(history_limit, int) or history_limit < 1:
            raise ValueError("history_limit must be a positive integer")
        self.history_limit = history_limit
        raw_weights = [self.level_decay**i for i in range(levels)]
        z = sum(raw_weights)
        self.level_weights = tuple(w/z for w in raw_weights)
        self.previous: Optional[tuple[BookLevel, ...]] = None
        self.exponential_excitation = 0.0
        self.event_history: list[tuple[float, float]] = []  # (age seconds, mark)
        self.elapsed_seconds = 0.0

    @staticmethod
    def _level_ofi(now: BookLevel, prev: BookLevel) -> float:
        if now.bid_price > prev.bid_price:
            bid = now.bid_size
        elif now.bid_price < prev.bid_price:
            bid = -prev.bid_size
        else:
            bid = now.bid_size - prev.bid_size
        if now.ask_price < prev.ask_price:
            ask = -now.ask_size
        elif now.ask_price > prev.ask_price:
            ask = prev.ask_size
        else:
            ask = prev.ask_size - now.ask_size
        return bid + ask

    def update(self, book: Sequence[BookLevel], dt_seconds: float) -> MLOFIObservation:
        dt = _finite(dt_seconds, "dt_seconds")
        if dt <= 0:
            raise ValueError("dt_seconds must be positive")
        if len(book) != self.levels:
            raise ValueError("book must have exactly five levels")
        now = tuple(book)
        if not all(isinstance(x, BookLevel) for x in now):
            raise TypeError("book entries must be BookLevel")
        total_depth = sum(x.bid_size + x.ask_size for x in now)
        imb = (sum(w*(x.bid_size-x.ask_size) for w, x in zip(self.level_weights, now)) /
               max(sum(w*(x.bid_size+x.ask_size) for w, x in zip(self.level_weights, now)), 1e-12))
        if self.previous is None:
            raw_ofi = 0.0
        else:
            raw_ofi = sum(w*self._level_ofi(n, p) for w, n, p in zip(self.level_weights, now, self.previous))
        scale = max(total_depth / self.levels, 1.0)
        mlofi = raw_ofi / scale
        self.elapsed_seconds += dt
        self.exponential_excitation *= exp(-self.decay*dt)
        self.event_history = [(age+dt, mark) for age, mark in self.event_history]
        mark = abs(mlofi)
        if mark > 0:
            self.exponential_excitation += self.excitation * mark
            self.event_history.append((0.0, mark))
            if len(self.event_history) > self.history_limit:
                self.event_history = self.event_history[-self.history_limit:]
        fractional = self.excitation * sum(mark_i / ((age+dt)**self.fractional_exponent)
                                           for age, mark_i in self.event_history)
        intensity = max(0.0, self.baseline + self.exponential_excitation + fractional)
        probability = _clamp(1.0-exp(-intensity*dt), 0.0, 1.0)
        signed = mlofi * (1.0 if imb >= 0 else -1.0)
        self.previous = now
        return MLOFIObservation(mlofi, _clamp(imb, -1.0, 1.0), intensity, probability, signed)

    def reset(self) -> None:
        self.previous = None
        self.exponential_excitation = 0.0
        self.event_history.clear()
        self.elapsed_seconds = 0.0


# ---------------------------------------------------------------------------
# Trade-frequency optimization and behavioural tilt protection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrequencyOptimum:
    optimal_trades: int
    expected_net_growth: float
    objective_by_count: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class ThrottleStatus:
    allowed: bool
    reason: str
    trades_today: int
    optimal_trades: int
    cooldown_until_seconds: float
    loss_streak: int
    tilt_locked: bool


class AntiOvertradingThrottler:
    """Discrete net-growth optimizer plus hard entry lockouts.

    Objective for count n:
      G(n)=n*a - d*n*(n-1)/2 - n*c - 0.5*r*n^2
    where a is gross edge per trade, d is edge decay with crowding/frequency,
    c is expected per-trade friction, and r is a quadratic risk/turnover penalty.
    The chosen n is the exact integer argmax over [0, max_trades].
    """
    def __init__(self, *, expected_gross_edge_per_trade: float,
                 edge_decay_per_extra_trade: float, friction_per_trade: float,
                 risk_penalty: float = 0.0, max_trades: int = 100,
                 loss_streak_limit: int = 3, revenge_ratio_limit: float = 1.25,
                 min_pacing_seconds: float = 30.0, cooldown_seconds: float = 900.0) -> None:
        self.edge = _finite(expected_gross_edge_per_trade, "expected_gross_edge_per_trade")
        self.edge_decay = _nonnegative(edge_decay_per_extra_trade, "edge_decay_per_extra_trade")
        self.friction = _nonnegative(friction_per_trade, "friction_per_trade")
        self.risk_penalty = _nonnegative(risk_penalty, "risk_penalty")
        if not isinstance(max_trades, int) or max_trades < 0:
            raise ValueError("max_trades must be a nonnegative integer")
        if not isinstance(loss_streak_limit, int) or loss_streak_limit < 1:
            raise ValueError("loss_streak_limit must be positive")
        self.max_trades = max_trades
        self.loss_streak_limit = loss_streak_limit
        self.revenge_ratio_limit = _finite(revenge_ratio_limit, "revenge_ratio_limit")
        if self.revenge_ratio_limit <= 1:
            raise ValueError("revenge_ratio_limit must be > 1")
        self.min_pacing_seconds = _nonnegative(min_pacing_seconds, "min_pacing_seconds")
        self.cooldown_seconds = _nonnegative(cooldown_seconds, "cooldown_seconds")
        self.trades_today = 0
        self.loss_streak = 0
        self.previous_size: Optional[float] = None
        self.previous_fill_time: Optional[float] = None
        self.cooldown_until_seconds = 0.0
        self.lock_reasons: set[str] = set()
        self.frequency_optimum = self.optimize_frequency()

    def objective(self, n: int) -> float:
        if not isinstance(n, int) or n < 0:
            raise ValueError("n must be a nonnegative integer")
        return (n*self.edge - self.edge_decay*n*(n-1)/2.0
                - n*self.friction - 0.5*self.risk_penalty*n*n)

    def optimize_frequency(self) -> FrequencyOptimum:
        values = tuple((n, self.objective(n)) for n in range(self.max_trades+1))
        # Deterministic tie break favors fewer trades.
        best_n, best_value = max(values, key=lambda pair: (pair[1], -pair[0]))
        return FrequencyOptimum(best_n, best_value, values)

    @property
    def optimal_trades(self) -> int:
        return self.frequency_optimum.optimal_trades

    def _engage_cooldown(self, now: float, reason: str) -> None:
        self.cooldown_until_seconds = max(self.cooldown_until_seconds, now + self.cooldown_seconds)
        self.lock_reasons.add(reason)

    def record_fill(self, *, timestamp_seconds: float, pnl: float, size: float) -> ThrottleStatus:
        now = _finite(timestamp_seconds, "timestamp_seconds")
        pnl = _finite(pnl, "pnl")
        size = _nonnegative(size, "size")
        if not 0 <= now <= SECONDS_PER_DAY:
            raise ValueError("timestamp_seconds must be within the session day")
        if self.previous_fill_time is not None and now < self.previous_fill_time:
            raise ValueError("fill timestamps must be nondecreasing")
        if self.previous_fill_time is not None and now-self.previous_fill_time < self.min_pacing_seconds:
            self._engage_cooldown(now, "PACING_VIOLATION")
        if self.previous_size is not None and self.previous_size > 0 and size/self.previous_size > self.revenge_ratio_limit:
            self._engage_cooldown(now, "REVENGE_SIZING")
        self.loss_streak = self.loss_streak + 1 if pnl < 0 else 0
        if self.loss_streak >= self.loss_streak_limit:
            self._engage_cooldown(now, "LOSS_STREAK")
        self.previous_fill_time = now
        self.previous_size = size
        self.trades_today += 1
        return self.status(now)

    def status(self, now_seconds: float) -> ThrottleStatus:
        now = _finite(now_seconds, "now_seconds")
        if self.trades_today >= self.optimal_trades:
            return ThrottleStatus(False, "OPTIMAL_FREQUENCY_CAP", self.trades_today,
                                  self.optimal_trades, self.cooldown_until_seconds,
                                  self.loss_streak, now < self.cooldown_until_seconds)
        if now < self.cooldown_until_seconds:
            reasons = ",".join(sorted(self.lock_reasons)) or "PSYCHOLOGY_TILT"
            return ThrottleStatus(False, f"PSYCHOLOGY_TILT_LOCKOUT:{reasons}",
                                  self.trades_today, self.optimal_trades,
                                  self.cooldown_until_seconds, self.loss_streak, True)
        return ThrottleStatus(True, "CLEAR", self.trades_today, self.optimal_trades,
                              self.cooldown_until_seconds, self.loss_streak, False)

    def entry_allowed(self, *, now_seconds: float, expected_gross_alpha: float,
                      fees: FeeBreakdown, additional_impact_hurdle: float = 0.0) -> ThrottleStatus:
        status = self.status(now_seconds)
        if not status.allowed:
            return status
        impact = _nonnegative(additional_impact_hurdle, "additional_impact_hurdle")
        if _finite(expected_gross_alpha, "expected_gross_alpha") <= fees.total_friction + impact:
            return ThrottleStatus(False, "FRICTION_HURDLE_NOT_CLEARED", status.trades_today,
                                  status.optimal_trades, status.cooldown_until_seconds,
                                  status.loss_streak, status.tilt_locked)
        return status

    def reset_session(self) -> None:
        self.trades_today = 0
        self.loss_streak = 0
        self.previous_size = None
        self.previous_fill_time = None
        self.cooldown_until_seconds = 0.0
        self.lock_reasons.clear()


# ---------------------------------------------------------------------------
# Fail-closed risk machine and orchestration
# ---------------------------------------------------------------------------

class RiskState(str, Enum):
    IDLE = "IDLE"
    EXECUTION_PLANNING = "EXECUTION_PLANNING"
    OPTIMAL_ROUTING = "OPTIMAL_ROUTING"
    OVERTRADING_LOCKED = "OVERTRADING_LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START_PLANNING = "START_PLANNING"
    ROUTE_APPROVED = "ROUTE_APPROVED"
    OVERTRADING = "OVERTRADING"
    COOLDOWN_COMPLETE = "COOLDOWN_COMPLETE"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"
    RESET = "RESET"


@dataclass
class RiskStateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown risk event; failing closed")
        if self.emergency_latched and event is not RiskEvent.RECOVERY_ACK:
            self.history.append((event.value, "BLOCKED_EMERGENCY_LATCH"))
            return self.state
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK:
            if self.emergency_latched:
                self.emergency_latched = False
                self.state = RiskState.IDLE
        elif event is RiskEvent.START_PLANNING and self.state is RiskState.IDLE:
            self.state = RiskState.EXECUTION_PLANNING
        elif event is RiskEvent.ROUTE_APPROVED and self.state is RiskState.EXECUTION_PLANNING:
            self.state = RiskState.OPTIMAL_ROUTING
        elif event is RiskEvent.OVERTRADING and self.state is not RiskState.IDLE:
            self.state = RiskState.OVERTRADING_LOCKED
        elif event is RiskEvent.COOLDOWN_COMPLETE and self.state is RiskState.OVERTRADING_LOCKED:
            self.state = RiskState.EXECUTION_PLANNING
        elif event is RiskEvent.RESET and not self.emergency_latched:
            self.state = RiskState.IDLE
        self.history.append((event.value, self.state.value))
        return self.state


def dispatch_live_order(*args: object, **kwargs: object) -> None:
    """Intentional safety tripwire: order dispatch is unavailable."""
    raise RuntimeError("LIVE_ORDER_DISPATCH_ENABLED is False; paper simulation only")


@dataclass(frozen=True)
class Cycle27Snapshot:
    timestamp_ist: str
    rough_vol_factor: float
    pin: ExpiryPinResult
    mlofi: MLOFIObservation
    spread_multiplier: float
    risk_state: RiskState
    live_dispatch_enabled: bool = False


@dataclass(frozen=True)
class EntryDecision:
    allowed: bool
    reason: str
    fees: FeeBreakdown
    throttle: ThrottleStatus
    risk_state: RiskState


class Cycle27ExecutionEngine:
    """Orchestrates Cycle 27 diagnostics and paper-only profitability gates."""
    def __init__(self, *, hurst: float = 0.1, fee_config: FeeConfig = FeeConfig(),
                 pin_model: Optional[ExpiryPinDynamicsModel] = None,
                 jump_detector: Optional[MLOFIJumpDetector] = None,
                 throttler: Optional[AntiOvertradingThrottler] = None) -> None:
        self.volterra = RoughVolterraKernel(hurst=hurst)
        self.costs = StatutoryCostCalculator(fee_config)
        self.pin_model = pin_model or ExpiryPinDynamicsModel()
        self.jump_detector = jump_detector or MLOFIJumpDetector()
        self.throttler = throttler or AntiOvertradingThrottler(
            expected_gross_edge_per_trade=100.0, edge_decay_per_extra_trade=10.0,
            friction_per_trade=20.0, risk_penalty=1.0, max_trades=20)
        self.risk = RiskStateMachine()
        self.last_snapshot: Optional[Cycle27Snapshot] = None
        self.entries_blocked_reason: Optional[str] = None

    def observe(self, *, timestamp_ist: str, spot: float,
                strikes: Sequence[StrikeExposure], book: Sequence[BookLevel],
                dt_seconds: float, volatility_innovation: float,
                market_depth_units: float = 1.0) -> Cycle27Snapshot:
        minute = _hhmm_minutes(timestamp_ist)
        del minute  # validated; pin model performs the exact session-window check
        if self.risk.state is RiskState.IDLE:
            self.risk.transition(RiskEvent.START_PLANNING)
        rough = self.volterra.step(volatility_innovation)
        pin = self.pin_model.evaluate(spot=spot, hhmm_ist=timestamp_ist,
                                      strikes=strikes, market_depth_units=market_depth_units)
        mlofi = self.jump_detector.update(book, dt_seconds)
        # Combine pin and jump stress but keep the effective multiplier inside the
        # configured black-hole ceiling (10x by default); do not multiply two
        # independently capped stress factors into an unrealistic 100x spread.
        spread_multiplier = min(
            self.pin_model.max_spread_multiplier,
            pin.spread_multiplier * (1.0 + min(9.0, mlofi.jump_probability * 9.0)),
        )
        if pin.black_hole_stress >= 0.95 or mlofi.jump_probability >= 0.995:
            self.entries_blocked_reason = "EXTREME_LIQUIDITY_STRESS"
            self.risk.transition(RiskEvent.EMERGENCY)
        elif self.risk.state is RiskState.EXECUTION_PLANNING:
            self.risk.transition(RiskEvent.ROUTE_APPROVED)
        snap = Cycle27Snapshot(timestamp_ist, rough, pin, mlofi,
                               spread_multiplier, self.risk.state, False)
        self.last_snapshot = snap
        return snap

    def evaluate_entry(self, *, now_seconds: float, premium: float, lots: int,
                       lot_size: int, side: str, expected_gross_alpha: float,
                       base_half_spread_per_unit: float,
                       permanent_impact_per_unit: float = 0.0,
                       additional_impact_hurdle: float = 0.0) -> EntryDecision:
        stress_mult = self.last_snapshot.spread_multiplier if self.last_snapshot else 1.0
        fees = self.costs.calculate(
            premium=premium, lots=lots, lot_size=lot_size, side=side,
            half_spread_per_unit=base_half_spread_per_unit,
            spread_multiplier=stress_mult,
            permanent_impact_per_unit=permanent_impact_per_unit,
        )
        if self.risk.emergency_latched or self.risk.state is RiskState.EMERGENCY_UNWIND:
            throttle = self.throttler.status(now_seconds)
            return EntryDecision(False, "EMERGENCY_UNWIND_LATCHED", fees, throttle, self.risk.state)
        if self.risk.state is RiskState.OVERTRADING_LOCKED:
            throttle = self.throttler.status(now_seconds)
            return EntryDecision(False, "RISK_STATE_OVERTRADING_LOCKED", fees, throttle, self.risk.state)
        throttle = self.throttler.entry_allowed(now_seconds=now_seconds,
            expected_gross_alpha=expected_gross_alpha, fees=fees,
            additional_impact_hurdle=additional_impact_hurdle)
        if not throttle.allowed:
            if "LOCKOUT" in throttle.reason or throttle.reason == "OPTIMAL_FREQUENCY_CAP":
                self.risk.transition(RiskEvent.OVERTRADING)
            return EntryDecision(False, throttle.reason, fees, throttle, self.risk.state)
        if not self.costs.profitability_gate(expected_gross_alpha, fees):
            return EntryDecision(False, "FRICTION_HURDLE_NOT_CLEARED", fees, throttle, self.risk.state)
        return EntryDecision(True, "PAPER_ENTRY_APPROVED", fees, throttle, self.risk.state)

    def record_fill(self, *, timestamp_seconds: float, pnl: float, size: float) -> ThrottleStatus:
        status = self.throttler.record_fill(timestamp_seconds=timestamp_seconds, pnl=pnl, size=size)
        if not status.allowed:
            # Preserve the explicit hierarchy even if fills are replayed before the
            # first planning tick: IDLE -> EXECUTION_PLANNING -> OVERTRADING_LOCKED.
            if self.risk.state is RiskState.IDLE:
                self.risk.transition(RiskEvent.START_PLANNING)
            self.risk.transition(RiskEvent.OVERTRADING)
        return status

    def recovery_ack(self) -> RiskState:
        return self.risk.transition(RiskEvent.RECOVERY_ACK)

    @staticmethod
    def live_dispatch_enabled() -> bool:
        return LIVE_ORDER_DISPATCH_ENABLED
