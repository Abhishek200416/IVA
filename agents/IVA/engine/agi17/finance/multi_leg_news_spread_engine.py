"""Cycle 29 — News-conditioned jump filtering and multi-leg option spread economics.

Offline/paper-research reference only. No broker API or live order path is present.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import math
from typing import Iterable, Mapping, Sequence

LIVE_ORDER_DISPATCH_ENABLED = False  # fixed safety invariant; do not change at runtime


def _finite(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _nonnegative(name: str, value: float) -> float:
    value = _finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _probability(name: str, value: float) -> float:
    value = _finite(name, value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return value


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SpreadType(str, Enum):
    VERTICAL = "VERTICAL"
    IRON_CONDOR = "IRON_CONDOR"
    CALENDAR = "CALENDAR"
    RATIO = "RATIO"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class OptionLeg:
    """One option trade leg. ``lots`` is a nonnegative integer.

    The model assumes premium turnover = premium * lots * lot_size, with premium
    and impact/spread expressed in rupees per option unit. Quantity must be scaled
    to actual contract lot size before any real accounting reconciliation.
    """
    symbol: str
    side: Side
    premium: float
    lots: int
    lot_size: int
    half_spread_per_unit: float = 0.0
    impact_per_unit: float = 0.0
    brokerage_per_order: float = 0.0

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        if not isinstance(self.side, Side):
            try:
                object.__setattr__(self, "side", Side(str(self.side).upper()))
            except ValueError as exc:
                raise ValueError("side must be BUY or SELL") from exc
        _nonnegative("premium", self.premium)
        if isinstance(self.lots, bool) or not isinstance(self.lots, int) or self.lots < 0:
            raise ValueError("lots must be a nonnegative integer")
        if isinstance(self.lot_size, bool) or not isinstance(self.lot_size, int) or self.lot_size <= 0:
            raise ValueError("lot_size must be a positive integer")
        _nonnegative("half_spread_per_unit", self.half_spread_per_unit)
        _nonnegative("impact_per_unit", self.impact_per_unit)
        _nonnegative("brokerage_per_order", self.brokerage_per_order)

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    @property
    def turnover(self) -> float:
        return self.premium * self.quantity


@dataclass(frozen=True)
class StatutorySchedule:
    """Configurable India equity-options levy assumptions.

    NSE options charge is modeled using Rs 3,553 per crore of premium turnover
    (0.03553% expressed as an all-in amount). Check the applicable exchange tariff,
    broker invoice, rounding, GST base, and trade-date rules before real use.
    """
    options_sell_stt_rate: float = 0.0015
    nse_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    options_buy_stamp_rate: float = 0.00003
    gst_on_exchange: bool = True
    gst_on_sebi: bool = True
    gst_on_brokerage: bool = True

    def __post_init__(self) -> None:
        for name in ("options_sell_stt_rate", "nse_per_crore", "sebi_per_crore",
                     "gst_rate", "options_buy_stamp_rate"):
            _nonnegative(name, getattr(self, name))
        if self.options_sell_stt_rate > 1 or self.gst_rate > 1 or self.options_buy_stamp_rate > 1:
            raise ValueError("percentage rates must be decimal fractions in [0, 1]")


@dataclass(frozen=True)
class FeeBreakdown:
    total_turnover: float
    buy_turnover: float
    sell_turnover: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    half_spread_slippage: float
    cross_impact: float
    statutory_total: float
    execution_cost_total: float
    total_cost: float


class MultiLegFeeCalculator:
    """Itemized costs computed independently for every leg, then aggregated."""
    CRORE_RUPEES = 10_000_000.0

    def __init__(self, schedule: StatutorySchedule | None = None) -> None:
        self.schedule = schedule or StatutorySchedule()

    def calculate(self, legs: Sequence[OptionLeg], *, extra_cross_impact: float = 0.0) -> FeeBreakdown:
        if not legs:
            raise ValueError("at least one leg is required")
        _nonnegative("extra_cross_impact", extra_cross_impact)
        total_turnover = buy_turnover = sell_turnover = 0.0
        stt = exchange_fee = sebi_fee = stamp = brokerage = slippage = impact = 0.0
        for leg in legs:
            if not isinstance(leg, OptionLeg):
                raise TypeError("legs must contain OptionLeg values")
            turnover = leg.turnover
            total_turnover += turnover
            if leg.side is Side.BUY:
                buy_turnover += turnover
                stamp += turnover * self.schedule.options_buy_stamp_rate
            else:
                sell_turnover += turnover
                stt += turnover * self.schedule.options_sell_stt_rate
            exchange_fee += turnover * self.schedule.nse_per_crore / self.CRORE_RUPEES
            sebi_fee += turnover * self.schedule.sebi_per_crore / self.CRORE_RUPEES
            if leg.quantity > 0:
                brokerage += leg.brokerage_per_order
            slippage += leg.half_spread_per_unit * leg.quantity
            impact += leg.impact_per_unit * leg.quantity
        impact += extra_cross_impact
        gst_base = 0.0
        if self.schedule.gst_on_exchange:
            gst_base += exchange_fee
        if self.schedule.gst_on_sebi:
            gst_base += sebi_fee
        if self.schedule.gst_on_brokerage:
            gst_base += brokerage
        gst = gst_base * self.schedule.gst_rate
        statutory = stt + exchange_fee + sebi_fee + gst + stamp + brokerage
        execution = slippage + impact
        values = (total_turnover, buy_turnover, sell_turnover, stt, exchange_fee,
                  sebi_fee, gst, stamp, brokerage, slippage, impact, statutory,
                  execution, statutory + execution)
        if not all(math.isfinite(x) and x >= 0 for x in values):
            raise ValueError("cost computation produced invalid value")
        return FeeBreakdown(total_turnover, buy_turnover, sell_turnover, stt,
                            exchange_fee, sebi_fee, gst, stamp, brokerage,
                            slippage, impact, statutory, execution, statutory + execution)


@dataclass(frozen=True)
class NewsConditioning:
    sentiment: float
    urgency: float
    seconds_from_event: float
    jump_intensity: float
    call_iv_shift: float
    put_iv_shift: float
    stress_score: float


class NewsSentimentVolatilityConditioner:
    """Map news sentiment/urgency to decaying event intensity and skew shifts.

    For timestamps before an event, a Gaussian anticipation envelope is used;
    after the event, an exponential kernel is used. This is a configurable signal
    mapping, not an NLP model or an estimate of causal news impact.
    """
    def __init__(self, *, baseline_intensity: float = 0.05,
                 gamma_news: float = 2.0, beta_news: float = 1.0 / 900.0,
                 pre_event_scale_seconds: float = 900.0,
                 skew_gain: float = 0.03) -> None:
        self.baseline_intensity = _nonnegative("baseline_intensity", baseline_intensity)
        self.gamma_news = _nonnegative("gamma_news", gamma_news)
        self.beta_news = _nonnegative("beta_news", beta_news)
        self.pre_event_scale_seconds = _nonnegative("pre_event_scale_seconds", pre_event_scale_seconds)
        if self.pre_event_scale_seconds == 0:
            raise ValueError("pre_event_scale_seconds must be positive")
        self.skew_gain = _nonnegative("skew_gain", skew_gain)

    def condition(self, *, sentiment: float, urgency: float,
                  seconds_from_event: float) -> NewsConditioning:
        sentiment = _finite("sentiment", sentiment)
        if not -1.0 <= sentiment <= 1.0:
            raise ValueError("sentiment must be in [-1, 1]")
        urgency = _probability("urgency", urgency)
        seconds_from_event = _finite("seconds_from_event", seconds_from_event)
        if seconds_from_event >= 0:
            kernel = math.exp(-self.beta_news * seconds_from_event)
        else:
            z = seconds_from_event / self.pre_event_scale_seconds
            kernel = math.exp(-0.5 * z * z)
        event_component = self.gamma_news * urgency * kernel
        intensity = self.baseline_intensity + event_component
        # Positive sentiment tilts modeled demand toward calls; negative toward puts.
        signed_skew = self.skew_gain * sentiment * urgency * kernel
        stress = min(1.0, max(0.0, urgency * kernel * (0.5 + 0.5 * abs(sentiment))))
        return NewsConditioning(sentiment, urgency, seconds_from_event,
                                intensity, signed_skew, -signed_skew, stress)


@dataclass(frozen=True)
class JumpFilterEstimate:
    log_return: float
    drift_estimate: float
    diffusion_variance: float
    jump_detected: bool
    jump_intensity: float
    jump_residual: float
    observation_count: int


class SequentialJumpDiffusionFilter:
    """Online EWMA drift/variance filter with residual-threshold jump detection."""
    def __init__(self, *, drift_alpha: float = 0.05, variance_alpha: float = 0.05,
                 jump_z_threshold: float = 4.0, initial_variance: float = 1e-6,
                 intensity_decay: float = 0.98, jump_increment: float = 0.2) -> None:
        for name, value in (("drift_alpha", drift_alpha), ("variance_alpha", variance_alpha),
                            ("intensity_decay", intensity_decay)):
            _probability(name, value)
        if drift_alpha == 0 or variance_alpha == 0:
            raise ValueError("EWMA learning rates must be positive")
        self.jump_z_threshold = _nonnegative("jump_z_threshold", jump_z_threshold)
        self.variance = _nonnegative("initial_variance", initial_variance)
        if self.variance <= 0:
            raise ValueError("initial_variance must be positive")
        self.drift = 0.0
        self.intensity = 0.0
        self.drift_alpha = drift_alpha
        self.variance_alpha = variance_alpha
        self.intensity_decay = intensity_decay
        self.jump_increment = _nonnegative("jump_increment", jump_increment)
        self.observation_count = 0

    def update(self, log_return: float, *, dt_seconds: float = 1.0,
               news_intensity: float = 0.0) -> JumpFilterEstimate:
        r = _finite("log_return", log_return)
        dt_seconds = _finite("dt_seconds", dt_seconds)
        if dt_seconds <= 0:
            raise ValueError("dt_seconds must be positive")
        news_intensity = _nonnegative("news_intensity", news_intensity)
        residual = r - self.drift * dt_seconds
        scale = math.sqrt(max(self.variance * dt_seconds, 1e-16))
        jump = abs(residual) > self.jump_z_threshold * scale
        # News increases the prior jump intensity; event detection adds a bounded increment.
        self.intensity = self.intensity_decay * self.intensity + news_intensity * (1.0 - self.intensity_decay)
        if jump:
            self.intensity += self.jump_increment
        self.intensity = max(0.0, self.intensity)
        drift_observation = r / dt_seconds
        variance_observation = residual * residual / dt_seconds
        if not jump:
            # Keep isolated jumps out of the continuous drift and diffusion estimates.
            self.drift += self.drift_alpha * (drift_observation - self.drift)
            self.variance += self.variance_alpha * (variance_observation - self.variance)
        self.variance = max(self.variance, 1e-16)
        self.observation_count += 1
        return JumpFilterEstimate(r, self.drift, self.variance, jump,
                                  self.intensity, residual, self.observation_count)


@dataclass(frozen=True)
class SpreadEvaluation:
    name: str
    spread_type: SpreadType
    gross_expected_alpha: float
    fee_breakdown: FeeBreakdown
    cross_impact_hurdle: float
    total_hurdle: float
    expected_net_alpha: float
    net_yield_on_turnover: float
    accepted: bool
    rejection_reason: str
    leg_ratio: tuple[int, ...]


class MultiLegSpreadOptimizer:
    """Evaluate supplied vertical, iron-condor, calendar, or ratio-spread structures.

    It does not discover market opportunities or prove an option structure's
    payoff/risk profile. The caller supplies expected gross alpha and risk budget.
    """
    def __init__(self, fee_calculator: MultiLegFeeCalculator | None = None) -> None:
        self.fee_calculator = fee_calculator or MultiLegFeeCalculator()

    def evaluate(self, *, name: str, spread_type: SpreadType,
                 legs: Sequence[OptionLeg], gross_expected_alpha: float,
                 cross_impact_hurdle: float = 0.0) -> SpreadEvaluation:
        if not isinstance(spread_type, SpreadType):
            spread_type = SpreadType(str(spread_type).upper())
        if not name.strip():
            raise ValueError("name must not be blank")
        alpha = _finite("gross_expected_alpha", gross_expected_alpha)
        impact_hurdle = _nonnegative("cross_impact_hurdle", cross_impact_hurdle)
        if not legs:
            raise ValueError("at least one leg is required")
        if sum(leg.quantity for leg in legs) <= 0:
            raise ValueError("at least one spread leg must have positive quantity")
        fees = self.fee_calculator.calculate(legs, extra_cross_impact=impact_hurdle)
        if fees.total_turnover <= 0:
            raise ValueError("spread must have positive premium turnover")
        # Cross-impact appears in FeeBreakdown execution total; explicit risk hurdle is also gated.
        total_hurdle = fees.total_cost
        expected_net = alpha - total_hurdle
        turnover = fees.total_turnover
        net_yield = expected_net / turnover if turnover > 0 else (math.inf if expected_net > 0 else 0.0)
        reason = ""
        accepted = True
        if alpha <= total_hurdle:
            accepted = False
            reason = "gross alpha does not strictly exceed modeled total friction and impact hurdle"
        ratios = tuple(leg.lots for leg in legs)
        return SpreadEvaluation(name, spread_type, alpha, fees, impact_hurdle,
                                total_hurdle, expected_net, net_yield, accepted,
                                reason, ratios)

    def optimize_ratios(self, *, name: str, spread_type: SpreadType,
                        template_legs: Sequence[OptionLeg],
                        ratio_candidates: Sequence[Sequence[int]],
                        gross_alpha_by_ratio: Sequence[float],
                        cross_impact_hurdle: float = 0.0) -> SpreadEvaluation | None:
        if len(ratio_candidates) != len(gross_alpha_by_ratio):
            raise ValueError("each ratio candidate requires one gross alpha estimate")
        best: SpreadEvaluation | None = None
        for ratio, alpha in zip(ratio_candidates, gross_alpha_by_ratio):
            if len(ratio) != len(template_legs):
                raise ValueError("each ratio must match number of template legs")
            if not any((isinstance(q, int) and not isinstance(q, bool) and q > 0) for q in ratio):
                continue
            scaled: list[OptionLeg] = []
            for leg, lots in zip(template_legs, ratio):
                if isinstance(lots, bool) or not isinstance(lots, int) or lots < 0:
                    raise ValueError("ratio lots must be nonnegative integers")
                scaled.append(replace(leg, lots=lots))
            result = self.evaluate(name=name, spread_type=spread_type, legs=scaled,
                                   gross_expected_alpha=alpha,
                                   cross_impact_hurdle=cross_impact_hurdle)
            if result.accepted and (best is None or result.expected_net_alpha > best.expected_net_alpha):
                best = result
        return best


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    optimal_daily_trade_count: int
    executed_trades: int
    lockout_until: float
    reason: str


class AntiOvertradingThrottler:
    """Integer trade cap and behavioral cooling-off monitor.

    Maximizes g(n) = n*(gross_edge - friction) - 0.5*risk_coeff*n^2 for
    integer n in [0, max_trades]. This is exact for the specified quadratic model,
    not a universal market-optimal trade count.
    """
    def __init__(self, *, gross_edge_per_trade: float, friction_per_trade: float,
                 risk_coeff: float, max_trades: int = 100,
                 loss_streak_limit: int = 3, revenge_ratio_limit: float = 1.25,
                 min_pacing_seconds: float = 30.0, cooldown_seconds: float = 900.0) -> None:
        self.gross_edge = _finite("gross_edge_per_trade", gross_edge_per_trade)
        self.friction = _nonnegative("friction_per_trade", friction_per_trade)
        self.risk_coeff = _nonnegative("risk_coeff", risk_coeff)
        if self.risk_coeff <= 0:
            raise ValueError("risk_coeff must be positive")
        if isinstance(max_trades, bool) or not isinstance(max_trades, int) or max_trades < 0:
            raise ValueError("max_trades must be a nonnegative integer")
        if isinstance(loss_streak_limit, bool) or not isinstance(loss_streak_limit, int) or loss_streak_limit < 1:
            raise ValueError("loss_streak_limit must be positive")
        self.max_trades = max_trades
        self.loss_streak_limit = loss_streak_limit
        self.revenge_ratio_limit = _finite("revenge_ratio_limit", revenge_ratio_limit)
        if self.revenge_ratio_limit <= 1:
            raise ValueError("revenge_ratio_limit must exceed 1")
        self.min_pacing_seconds = _nonnegative("min_pacing_seconds", min_pacing_seconds)
        self.cooldown_seconds = _nonnegative("cooldown_seconds", cooldown_seconds)
        self.executed_trades = 0
        self.consecutive_losses = 0
        self.last_fill_time: float | None = None
        self.last_size: float | None = None
        self.lockout_until = 0.0
        self.lockout_reason = ""
        self.optimal_count = self._solve_optimal_count()

    def _solve_optimal_count(self) -> int:
        net_edge = self.gross_edge - self.friction
        continuous = net_edge / self.risk_coeff
        candidates = {0, self.max_trades, max(0, min(self.max_trades, math.floor(continuous))),
                      max(0, min(self.max_trades, math.ceil(continuous)))}
        def growth(n: int) -> float:
            return n * net_edge - 0.5 * self.risk_coeff * n * n
        return min(candidates, key=lambda n: (-growth(n), n))

    def _lock(self, now: float, reason: str) -> None:
        self.lockout_until = max(self.lockout_until, now + self.cooldown_seconds)
        self.lockout_reason = reason

    def check_entry(self, *, now: float) -> ThrottleDecision:
        now = _finite("now", now)
        if now < self.lockout_until:
            return ThrottleDecision(False, self.optimal_count, self.executed_trades,
                                    self.lockout_until, self.lockout_reason or "cooldown active")
        if self.executed_trades >= self.optimal_count:
            return ThrottleDecision(False, self.optimal_count, self.executed_trades,
                                    self.lockout_until, "optimal daily trade cap reached")
        return ThrottleDecision(True, self.optimal_count, self.executed_trades,
                                self.lockout_until, "entry permitted")

    def record_fill(self, *, now: float, size: float, pnl: float) -> ThrottleDecision:
        now = _finite("now", now)
        size = _nonnegative("size", size)
        pnl = _finite("pnl", pnl)
        if self.last_fill_time is not None:
            interval = now - self.last_fill_time
            if interval < 0:
                raise ValueError("fill timestamps must be nondecreasing")
            if interval < self.min_pacing_seconds:
                self._lock(now, "rapid fill pacing")
        if self.last_size is not None and self.last_size > 0 and size / self.last_size > self.revenge_ratio_limit:
            self._lock(now, "revenge sizing escalation")
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        if self.consecutive_losses >= self.loss_streak_limit:
            self._lock(now, "consecutive loss streak")
        self.last_fill_time = now
        self.last_size = size
        self.executed_trades += 1
        return self.check_entry(now=now)

    def reset_session(self) -> None:
        """Reset daily count/loss tracking; cooldown is intentionally preserved."""
        self.executed_trades = 0
        self.consecutive_losses = 0
        self.last_fill_time = None
        self.last_size = None


class RiskState(str, Enum):
    IDLE = "IDLE"
    EVENT_MONITORING = "EVENT_MONITORING"
    SPREAD_EVALUATED = "SPREAD_EVALUATED"
    OVERTRADING_LOCKED = "OVERTRADING_LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START_MONITORING = "START_MONITORING"
    SPREAD_ACCEPTED = "SPREAD_ACCEPTED"
    SPREAD_REJECTED = "SPREAD_REJECTED"
    THROTTLE = "THROTTLE"
    EMERGENCY = "EMERGENCY"
    RESET = "RESET"
    RECOVERY_ACK = "RECOVERY_ACK"


@dataclass
class RiskStateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.state, RiskState):
            self.state = RiskState(self.state)
        # Inconsistent construction fails closed: an emergency state is always latched.
        if self.emergency_latched or self.state is RiskState.EMERGENCY_UNWIND:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown risk event; fail closed")
        if self.emergency_latched and event is not RiskEvent.RECOVERY_ACK:
            self.history.append((event.value, "blocked_emergency_latch"))
            return self.state
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event is RiskEvent.START_MONITORING:
            if self.state is RiskState.IDLE:
                self.state = RiskState.EVENT_MONITORING
        elif event is RiskEvent.SPREAD_ACCEPTED:
            if self.state in (RiskState.EVENT_MONITORING, RiskState.SPREAD_EVALUATED):
                self.state = RiskState.SPREAD_EVALUATED
        elif event is RiskEvent.SPREAD_REJECTED:
            if self.state is RiskState.IDLE:
                self.state = RiskState.EVENT_MONITORING
        elif event is RiskEvent.THROTTLE:
            if self.state is not RiskState.EMERGENCY_UNWIND:
                self.state = RiskState.OVERTRADING_LOCKED
        elif event is RiskEvent.RESET:
            if self.state is not RiskState.EMERGENCY_UNWIND:
                self.state = RiskState.IDLE
        self.history.append((event.value, self.state.value))
        return self.state


@dataclass(frozen=True)
class ExecutionResult:
    conditioning: NewsConditioning
    jump_filter: JumpFilterEstimate
    spread_evaluation: SpreadEvaluation | None
    throttle: ThrottleDecision
    risk_state: RiskState
    live_dispatch_enabled: bool = False


class Cycle29ExecutionEngine:
    """Orchestrates news conditioning, jump filtering, spread costs and controls."""
    def __init__(self, *, conditioner: NewsSentimentVolatilityConditioner | None = None,
                 jump_filter: SequentialJumpDiffusionFilter | None = None,
                 spread_optimizer: MultiLegSpreadOptimizer | None = None,
                 throttler: AntiOvertradingThrottler | None = None,
                 risk_machine: RiskStateMachine | None = None) -> None:
        self.conditioner = conditioner or NewsSentimentVolatilityConditioner()
        self.jump_filter = jump_filter or SequentialJumpDiffusionFilter()
        self.spread_optimizer = spread_optimizer or MultiLegSpreadOptimizer()
        self.throttler = throttler or AntiOvertradingThrottler(
            gross_edge_per_trade=100.0, friction_per_trade=20.0, risk_coeff=10.0,
            max_trades=20)
        self.risk = risk_machine or RiskStateMachine()

    def evaluate(self, *, sentiment: float, urgency: float,
                 seconds_from_event: float, log_return: float, dt_seconds: float,
                 legs: Sequence[OptionLeg], spread_type: SpreadType,
                 expected_gross_alpha: float, cross_impact_hurdle: float = 0.0,
                 now: float = 0.0, name: str = "news-conditioned spread") -> ExecutionResult:
        if not isinstance(LIVE_ORDER_DISPATCH_ENABLED, bool) or LIVE_ORDER_DISPATCH_ENABLED is not False:
            raise RuntimeError("safety invariant violated")
        if self.risk.state is RiskState.IDLE:
            self.risk.transition(RiskEvent.START_MONITORING)
        conditioning = self.conditioner.condition(
            sentiment=sentiment, urgency=urgency, seconds_from_event=seconds_from_event)
        jump_estimate = self.jump_filter.update(
            log_return, dt_seconds=dt_seconds, news_intensity=conditioning.jump_intensity)
        throttle = self.throttler.check_entry(now=now)
        if self.risk.emergency_latched:
            throttle = ThrottleDecision(False, self.throttler.optimal_count,
                self.throttler.executed_trades, self.throttler.lockout_until,
                "emergency unwind latch active")
        if throttle.allowed and self.risk.state is RiskState.OVERTRADING_LOCKED:
            self.risk.transition(RiskEvent.RESET)
            self.risk.transition(RiskEvent.START_MONITORING)
        evaluation: SpreadEvaluation | None = None
        if not throttle.allowed:
            self.risk.transition(RiskEvent.THROTTLE)
        else:
            evaluation = self.spread_optimizer.evaluate(
                name=name, spread_type=spread_type, legs=legs,
                gross_expected_alpha=expected_gross_alpha,
                cross_impact_hurdle=cross_impact_hurdle)
            if evaluation.accepted:
                self.risk.transition(RiskEvent.SPREAD_ACCEPTED)
            else:
                self.risk.transition(RiskEvent.SPREAD_REJECTED)
        return ExecutionResult(conditioning, jump_estimate, evaluation, throttle,
                               self.risk.state, LIVE_ORDER_DISPATCH_ENABLED)

    def record_fill(self, *, now: float, size: float, pnl: float) -> ThrottleDecision:
        result = self.throttler.record_fill(now=now, size=size, pnl=pnl)
        if not result.allowed:
            self.risk.transition(RiskEvent.THROTTLE)
        return result

    def emergency_unwind(self) -> RiskState:
        return self.risk.transition(RiskEvent.EMERGENCY)

    def recovery_ack(self) -> RiskState:
        return self.risk.transition(RiskEvent.RECOVERY_ACK)

    def dispatch_live_order(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("live order dispatch is permanently disabled; simulation only")
