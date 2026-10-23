"""Cycle 25: news-IV modelling, frequency throttling, anti-tilt, and paper costs.

Simulation-only reference engine. No broker/network adapter or live dispatch exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Iterable, Optional, Sequence, Union

import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
MIN_COOLING_OFF_SECONDS = 15 * 60

Numeric = Union[float, int, np.ndarray, Sequence[float]]


def _finite_float(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonnegative(value: float, name: str) -> float:
    result = _finite_float(value, name)
    if result < 0:
        raise ValueError(f"{name} must be nonnegative")
    return result


@dataclass(frozen=True)
class NewsIVModel:
    """Piecewise event IV curve; time is in minutes relative to event.

    Before the event: baseline + event bump * Gaussian approach-to-event.
    At/after the event: baseline + event bump * exponential decay.
    The curve is continuous at t=0, but its slope generally is not.
    """
    sigma_baseline: float
    delta_sigma_event: float
    sigma_pre_minutes: float
    tau_decay_minutes: float

    def __post_init__(self) -> None:
        _nonnegative(self.sigma_baseline, "sigma_baseline")
        _nonnegative(self.delta_sigma_event, "delta_sigma_event")
        if _finite_float(self.sigma_pre_minutes, "sigma_pre_minutes") <= 0:
            raise ValueError("sigma_pre_minutes must be positive")
        tau = _finite_float(self.tau_decay_minutes, "tau_decay_minutes")
        if not 10.0 <= tau <= 60.0:
            raise ValueError("tau_decay_minutes must be in [10, 60]")

    def implied_volatility(self, minutes_from_event: Numeric) -> Union[float, np.ndarray]:
        """Return IV for scalar or vector times, with no overflow on long pre-event horizons."""
        x = np.asarray(minutes_from_event, dtype=float)
        if not np.all(np.isfinite(x)):
            raise ValueError("minutes_from_event must be finite")
        pre_scaled = np.clip(x / self.sigma_pre_minutes, -1e150, 1e150)
        pre_bump = self.delta_sigma_event * np.exp(-0.5 * pre_scaled * pre_scaled)
        post_time = np.maximum(x, 0.0)
        post_bump = self.delta_sigma_event * np.exp(-np.minimum(post_time / self.tau_decay_minutes, 745.0))
        result = self.sigma_baseline + np.where(x < 0.0, pre_bump, post_bump)
        if x.ndim == 0:
            return float(result)
        return result

    @property
    def event_peak_iv(self) -> float:
        return self.sigma_baseline + self.delta_sigma_event

    def post_event_crush_fraction(self, minutes_from_event: float) -> float:
        t = _finite_float(minutes_from_event, "minutes_from_event")
        if t < 0:
            raise ValueError("crush fraction is only defined at/after the event")
        if self.delta_sigma_event == 0:
            return 0.0
        current = float(self.implied_volatility(t))
        return float(np.clip((self.event_peak_iv - current) / self.delta_sigma_event, 0.0, 1.0))


class StrategyRegime(str, Enum):
    LONG_VEGA_GAMMA = "LONG_VEGA_GAMMA"
    WAIT_FOR_STABILIZATION = "WAIT_FOR_STABILIZATION"
    SHORT_VEGA_DELTA_NEUTRAL = "SHORT_VEGA_DELTA_NEUTRAL"
    HALT = "HALT"


@dataclass(frozen=True)
class NewsRegimeController:
    """Produces research labels, never orders, for event-driven regimes."""
    minimum_crush_fraction: float = 0.25
    max_stress_for_short_vega: float = 0.45

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_crush_fraction <= 1:
            raise ValueError("minimum_crush_fraction must be in [0, 1]")
        if not 0 <= self.max_stress_for_short_vega <= 1:
            raise ValueError("max_stress_for_short_vega must be in [0, 1]")

    def recommend(
        self,
        model: NewsIVModel,
        minutes_from_event: float,
        observed_iv: float,
        news_stress: float,
        *,
        market_halted: bool = False,
    ) -> StrategyRegime:
        t = _finite_float(minutes_from_event, "minutes_from_event")
        iv = _nonnegative(observed_iv, "observed_iv")
        stress = _finite_float(news_stress, "news_stress")
        if not 0 <= stress <= 1:
            raise ValueError("news_stress must be in [0, 1]")
        if market_halted:
            return StrategyRegime.HALT
        if t < 0:
            return StrategyRegime.LONG_VEGA_GAMMA
        crush = 0.0 if model.delta_sigma_event <= 0 else float(
            np.clip((model.event_peak_iv - iv) / model.delta_sigma_event, 0, 1)
        )
        if crush >= self.minimum_crush_fraction and stress <= self.max_stress_for_short_vega:
            return StrategyRegime.SHORT_VEGA_DELTA_NEUTRAL
        return StrategyRegime.WAIT_FOR_STABILIZATION


def effective_spread(base_spread_per_unit: float, kappa_news: float, news_stress: float) -> float:
    """Full bid-ask spread per option unit after event-stress scaling."""
    base = _nonnegative(base_spread_per_unit, "base_spread_per_unit")
    kappa = _nonnegative(kappa_news, "kappa_news")
    stress = _finite_float(news_stress, "news_stress")
    if not 0 <= stress <= 1:
        raise ValueError("news_stress must be in [0, 1]")
    return base * (1.0 + kappa * stress)


@dataclass(frozen=True)
class FeeConfig:
    """Configurable default assumptions; verify rate/tax base by transaction date.

    Rates are fractions of option-premium turnover, not percentages as whole numbers.
    GST applies to configured service charges (NSE charge + brokerage), not turnover.
    """
    options_sell_stt_rate: float = 0.0015
    nse_options_rate: float = 0.0003553  # INR 3,553 per INR 1 crore
    sebi_turnover_rate: float = 0.000001  # INR 10 per INR 1 crore
    gst_rate: float = 0.18
    stamp_buy_rate: float = 0.00003
    brokerage_per_order: float = 0.0

    def __post_init__(self) -> None:
        for name in ("options_sell_stt_rate", "nse_options_rate", "sebi_turnover_rate", "gst_rate", "stamp_buy_rate", "brokerage_per_order"):
            _nonnegative(getattr(self, name), name)


@dataclass(frozen=True)
class CostBreakdown:
    premium_turnover: float
    quantity: int
    side: str
    stt: float
    nse_exchange_charge: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    effective_spread_per_unit: float
    half_spread_slippage: float
    market_impact: float
    statutory_fees: float
    slippage: float
    total_friction: float


@dataclass(frozen=True)
class StatutoryCostModel:
    config: FeeConfig = field(default_factory=FeeConfig)
    kappa_news: float = 3.0

    def __post_init__(self) -> None:
        _nonnegative(self.kappa_news, "kappa_news")

    def calculate(
        self,
        *,
        premium: float,
        lots: int,
        lot_size: int,
        side: str,
        base_spread_per_unit: float,
        news_stress: float,
        market_impact_per_unit: float = 0.0,
    ) -> CostBreakdown:
        premium_value = _nonnegative(premium, "premium")
        if isinstance(lots, bool) or int(lots) != lots or lots < 0:
            raise ValueError("lots must be a nonnegative integer")
        if isinstance(lot_size, bool) or int(lot_size) != lot_size or lot_size <= 0:
            raise ValueError("lot_size must be a positive integer")
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        impact_per_unit = _nonnegative(market_impact_per_unit, "market_impact_per_unit")
        quantity = int(lots) * int(lot_size)
        turnover = premium_value * quantity
        spread = effective_spread(base_spread_per_unit, self.kappa_news, news_stress)
        stt = turnover * self.config.options_sell_stt_rate if side == "SELL" else 0.0
        exchange = turnover * self.config.nse_options_rate
        sebi_fee = turnover * self.config.sebi_turnover_rate
        brokerage = self.config.brokerage_per_order if quantity > 0 else 0.0
        gst = (exchange + sebi_fee + brokerage) * self.config.gst_rate
        stamp = turnover * self.config.stamp_buy_rate if side == "BUY" else 0.0
        half_spread = 0.5 * spread * quantity
        impact = impact_per_unit * quantity
        statutory = stt + exchange + sebi_fee + gst + stamp + brokerage
        slippage = half_spread + impact
        total = statutory + slippage
        components = (turnover, stt, exchange, sebi_fee, gst, stamp, brokerage, spread, half_spread, impact, total)
        if not all(math.isfinite(x) for x in components):
            raise ValueError("cost calculation overflowed")
        return CostBreakdown(
            premium_turnover=turnover,
            quantity=quantity,
            side=side,
            stt=stt,
            nse_exchange_charge=exchange,
            sebi_fee=sebi_fee,
            gst=gst,
            stamp_duty=stamp,
            brokerage=brokerage,
            effective_spread_per_unit=spread,
            half_spread_slippage=half_spread,
            market_impact=impact,
            statutory_fees=statutory,
            slippage=slippage,
            total_friction=total,
        )


def profitability_gate(expected_gross_alpha: float, total_friction_hurdle: float) -> bool:
    """Strict gate: alpha must be greater than, not equal to, all modeled friction."""
    alpha = _finite_float(expected_gross_alpha, "expected_gross_alpha")
    hurdle = _nonnegative(total_friction_hurdle, "total_friction_hurdle")
    return alpha > hurdle


@dataclass(frozen=True)
class TradeFrequencyOptimizer:
    """Analytical frequency model in daily log-wealth-growth units.

    For integer trade count n:
      mu_gross(n) = alpha_per_trade*n - edge_decay*n^2
      g(n) = mu_gross(n) - 0.5*sigma_eff^2*n^2
             - n*round_trip_friction/wealth

    With edge_decay >= 0, this objective is concave when the quadratic
    coefficient is positive. The continuous maximizer is clipped to [0, Nmax];
    the exact integer solution is the best of its floor, ceil, and boundaries.
    Calibration parameters must come from offline walk-forward data.
    """
    alpha_per_trade: float
    edge_decay: float
    sigma_eff: float
    round_trip_friction: float
    max_trades_per_day: int = 100

    def __post_init__(self) -> None:
        _finite_float(self.alpha_per_trade, "alpha_per_trade")
        _nonnegative(self.edge_decay, "edge_decay")
        _nonnegative(self.sigma_eff, "sigma_eff")
        _nonnegative(self.round_trip_friction, "round_trip_friction")
        if isinstance(self.max_trades_per_day, bool) or int(self.max_trades_per_day) != self.max_trades_per_day or self.max_trades_per_day < 0:
            raise ValueError("max_trades_per_day must be a nonnegative integer")

    @property
    def quadratic_coefficient(self) -> float:
        return self.edge_decay + 0.5 * self.sigma_eff * self.sigma_eff

    def gross_mu(self, trade_count: int) -> float:
        n = self._validate_count(trade_count)
        return self.alpha_per_trade * n - self.edge_decay * n * n

    def net_log_growth(self, trade_count: int, wealth: float) -> float:
        n = self._validate_count(trade_count)
        w = _finite_float(wealth, "wealth")
        if w <= 0:
            raise ValueError("wealth must be positive")
        return (
            self.gross_mu(n)
            - 0.5 * self.sigma_eff * self.sigma_eff * n * n
            - (n * self.round_trip_friction) / w
        )

    def continuous_optimum(self, wealth: float) -> float:
        w = _finite_float(wealth, "wealth")
        if w <= 0:
            raise ValueError("wealth must be positive")
        denom = 2.0 * self.edge_decay + self.sigma_eff * self.sigma_eff
        marginal_after_cost = self.alpha_per_trade - self.round_trip_friction / w
        if denom <= 0:
            return float(self.max_trades_per_day if marginal_after_cost > 0 else 0)
        return float(np.clip(marginal_after_cost / denom, 0.0, float(self.max_trades_per_day)))

    def optimal_daily_trade_count(self, wealth: float) -> int:
        target = self.continuous_optimum(wealth)
        candidates = {0, self.max_trades_per_day, int(math.floor(target)), int(math.ceil(target))}
        feasible = [min(self.max_trades_per_day, max(0, n)) for n in candidates]
        # Prefer the smaller count on ties: conservative against overtrading.
        return max(sorted(set(feasible)), key=lambda n: (self.net_log_growth(n, wealth), -n))

    def _validate_count(self, trade_count: int) -> int:
        if isinstance(trade_count, bool) or int(trade_count) != trade_count or trade_count < 0:
            raise ValueError("trade_count must be a nonnegative integer")
        return int(trade_count)


@dataclass
class DailyTradeThrottle:
    """Daily hard entry cap; accepted entry opportunities consume a slot."""
    optimizer: TradeFrequencyOptimizer
    session_id: Optional[str] = None
    daily_limit: int = 0
    accepted_entries: int = 0

    def begin_session(self, session_id: str, wealth: float) -> int:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        limit = self.optimizer.optimal_daily_trade_count(wealth)
        self.session_id = session_id
        self.daily_limit = limit
        self.accepted_entries = 0
        return limit

    @property
    def throttle_active(self) -> bool:
        return self.accepted_entries >= self.daily_limit

    def can_enter(self) -> bool:
        return self.session_id is not None and self.accepted_entries < self.daily_limit

    def record_accepted_entry(self) -> bool:
        if not self.can_enter():
            return False
        self.accepted_entries += 1
        return True


@dataclass(frozen=True)
class TiltAssessment:
    triggered: bool
    reasons: tuple[str, ...]
    consecutive_losses: int
    lockout_until: float


@dataclass
class AntiTiltGuard:
    """Behavioral lockout using monotonic timestamps (seconds), not wall-clock time."""
    loss_streak_limit: int = 3
    revenge_size_ratio: float = 1.25
    min_intertrade_seconds: float = 30.0
    cooling_off_seconds: float = float(MIN_COOLING_OFF_SECONDS)
    consecutive_losses: int = 0
    lockout_until: float = 0.0
    last_trade_time: Optional[float] = None
    last_position_size: Optional[float] = None

    def __post_init__(self) -> None:
        if self.loss_streak_limit < 1:
            raise ValueError("loss_streak_limit must be >= 1")
        if _finite_float(self.revenge_size_ratio, "revenge_size_ratio") <= 1:
            raise ValueError("revenge_size_ratio must be > 1")
        if _finite_float(self.min_intertrade_seconds, "min_intertrade_seconds") < 0:
            raise ValueError("min_intertrade_seconds must be nonnegative")
        if _finite_float(self.cooling_off_seconds, "cooling_off_seconds") < MIN_COOLING_OFF_SECONDS:
            raise ValueError("cooling_off_seconds must be at least 15 minutes")

    def record_trade(self, *, timestamp: float, realized_pnl: float, position_size: float) -> TiltAssessment:
        now = _finite_float(timestamp, "timestamp")
        pnl = _finite_float(realized_pnl, "realized_pnl")
        size = _finite_float(position_size, "position_size")
        if size <= 0:
            raise ValueError("position_size must be positive")
        if self.last_trade_time is not None and now < self.last_trade_time:
            raise ValueError("timestamps must be nondecreasing monotonic values")

        reasons: list[str] = []
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        if self.consecutive_losses >= self.loss_streak_limit:
            reasons.append("LOSS_STREAK")

        if self.last_position_size is not None and self.last_position_size > 0:
            if size / self.last_position_size > self.revenge_size_ratio:
                reasons.append("REVENGE_SIZING_ESCALATION")
        if self.last_trade_time is not None:
            interval = now - self.last_trade_time
            if interval < self.min_intertrade_seconds:
                reasons.append("RAPID_INTERTRADE_PACING")

        if reasons:
            self.lockout_until = max(self.lockout_until, now + self.cooling_off_seconds)
        self.last_trade_time = now
        self.last_position_size = size
        return TiltAssessment(
            triggered=bool(reasons),
            reasons=tuple(reasons),
            consecutive_losses=self.consecutive_losses,
            lockout_until=self.lockout_until,
        )

    def is_locked(self, now: float) -> bool:
        timestamp = _finite_float(now, "now")
        return timestamp < self.lockout_until

    def remaining_seconds(self, now: float) -> float:
        timestamp = _finite_float(now, "now")
        return max(0.0, self.lockout_until - timestamp)


class RiskState(str, Enum):
    IDLE = "IDLE"
    EVENT_MONITORING = "EVENT_MONITORING"
    ASYMMETRIC_HARVEST = "ASYMMETRIC_HARVEST"
    OVERTRADING_LOCKED = "OVERTRADING_LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START_MONITORING = "START_MONITORING"
    HARVEST_SIGNAL = "HARVEST_SIGNAL"
    EVENT_WINDOW_CLOSED = "EVENT_WINDOW_CLOSED"
    OVERTRADING_THROTTLE_ACTIVE = "OVERTRADING_THROTTLE_ACTIVE"
    PSYCHOLOGY_TILT_LOCKOUT = "PSYCHOLOGY_TILT_LOCKOUT"
    COOLDOWN_COMPLETE = "COOLDOWN_COMPLETE"
    DAILY_SESSION_RESET = "DAILY_SESSION_RESET"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"


@dataclass
class RiskStateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    history: list[tuple[str, str, str]] = field(default_factory=list)

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown risk event; fail closed")
        prior = self.state
        if self.emergency_latched and event is not RiskEvent.RECOVERY_ACK:
            self.history.append((event.value, prior.value, "blocked_emergency_latch"))
            return self.state

        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK:
            if self.emergency_latched:
                self.emergency_latched = False
                self.state = RiskState.IDLE
        elif event is RiskEvent.START_MONITORING and self.state is RiskState.IDLE:
            self.state = RiskState.EVENT_MONITORING
        elif event is RiskEvent.HARVEST_SIGNAL and self.state is RiskState.EVENT_MONITORING:
            self.state = RiskState.ASYMMETRIC_HARVEST
        elif event is RiskEvent.EVENT_WINDOW_CLOSED and self.state is RiskState.ASYMMETRIC_HARVEST:
            self.state = RiskState.EVENT_MONITORING
        elif event in (RiskEvent.OVERTRADING_THROTTLE_ACTIVE, RiskEvent.PSYCHOLOGY_TILT_LOCKOUT) and self.state in (
            RiskState.EVENT_MONITORING, RiskState.ASYMMETRIC_HARVEST
        ):
            self.state = RiskState.OVERTRADING_LOCKED
        elif event in (RiskEvent.COOLDOWN_COMPLETE, RiskEvent.DAILY_SESSION_RESET) and self.state is RiskState.OVERTRADING_LOCKED:
            self.state = RiskState.EVENT_MONITORING
        self.history.append((event.value, prior.value, self.state.value))
        return self.state


def dispatch_live_order(*args: object, **kwargs: object) -> None:
    """Intentionally unavailable; Cycle 25 only produces simulation decisions."""
    raise RuntimeError("live order dispatch is permanently disabled in this reference engine")


@dataclass
class Cycle25Engine:
    """Small coordination layer for research signals and hard entry gates."""
    news_model: NewsIVModel
    cost_model: StatutoryCostModel
    frequency_optimizer: TradeFrequencyOptimizer
    regime_controller: NewsRegimeController = field(default_factory=NewsRegimeController)
    anti_tilt: AntiTiltGuard = field(default_factory=AntiTiltGuard)
    risk: RiskStateMachine = field(default_factory=RiskStateMachine)
    throttle: DailyTradeThrottle = field(init=False)

    def __post_init__(self) -> None:
        self.throttle = DailyTradeThrottle(self.frequency_optimizer)

    def begin_session(self, session_id: str, wealth: float, *, now: Optional[float] = None) -> int:
        limit = self.throttle.begin_session(session_id, wealth)
        if (
            now is not None
            and self.risk.state is RiskState.OVERTRADING_LOCKED
            and not self.anti_tilt.is_locked(now)
        ):
            # Explicit new session plus an expired tilt lock can clear the old cap.
            # Entry authorization still requires a fresh harvest signal.
            self.risk.transition(RiskEvent.DAILY_SESSION_RESET)
        return limit

    def record_trade(self, *, timestamp: float, realized_pnl: float, position_size: float) -> TiltAssessment:
        assessment = self.anti_tilt.record_trade(
            timestamp=timestamp, realized_pnl=realized_pnl, position_size=position_size
        )
        if assessment.triggered:
            self.risk.transition(RiskEvent.PSYCHOLOGY_TILT_LOCKOUT)
        return assessment

    def resume_after_cooldown(self, now: float) -> RiskState:
        """Resume monitoring only after the timer expires and daily cap is not active."""
        if (
            self.risk.state is RiskState.OVERTRADING_LOCKED
            and not self.anti_tilt.is_locked(now)
            and not self.throttle.throttle_active
        ):
            return self.risk.transition(RiskEvent.COOLDOWN_COMPLETE)
        return self.risk.state

    def start_monitoring(self) -> RiskState:
        return self.risk.transition(RiskEvent.START_MONITORING)

    def engage_harvest(self) -> RiskState:
        return self.risk.transition(RiskEvent.HARVEST_SIGNAL)

    @property
    def overtrading_throttle_active(self) -> bool:
        return self.throttle.throttle_active

    def evaluate_entry(
        self,
        *,
        expected_gross_alpha: float,
        friction_hurdle: float,
        now: float,
    ) -> tuple[bool, str]:
        """Authorize a *paper entry intent* only; consumes one cap slot on pass."""
        if LIVE_ORDER_DISPATCH_ENABLED:
            return False, "LIVE_DISPATCH_INVARIANT_VIOLATION"
        if self.risk.emergency_latched or self.risk.state is RiskState.EMERGENCY_UNWIND:
            return False, "EMERGENCY_LATCHED"
        if self.anti_tilt.is_locked(now):
            self.risk.transition(RiskEvent.PSYCHOLOGY_TILT_LOCKOUT)
            return False, "PSYCHOLOGY_TILT_LOCKOUT"
        if self.throttle.session_id is None:
            return False, "SESSION_NOT_INITIALIZED"
        if self.throttle.throttle_active or not self.throttle.can_enter():
            self.risk.transition(RiskEvent.OVERTRADING_THROTTLE_ACTIVE)
            return False, "OVERTRADING_THROTTLE_ACTIVE"
        if self.risk.state is not RiskState.ASYMMETRIC_HARVEST:
            return False, "HARVEST_STATE_REQUIRED"
        if not profitability_gate(expected_gross_alpha, friction_hurdle):
            return False, "FRICTION_HURDLE_NOT_CLEARED"
        if not self.throttle.record_accepted_entry():
            self.risk.transition(RiskEvent.OVERTRADING_THROTTLE_ACTIVE)
            return False, "OVERTRADING_THROTTLE_ACTIVE"
        if self.throttle.throttle_active:
            self.risk.transition(RiskEvent.OVERTRADING_THROTTLE_ACTIVE)
        return True, "PAPER_ENTRY_APPROVED"
