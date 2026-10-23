"""Cycle 28: friction-aware deep-hedging research engine (offline only).

This module intentionally has no broker connectivity or live order path.
The mathematical components are configurable research approximations and
must be calibrated/validated before any real-world financial use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence
import math

LIVE_ORDER_DISPATCH_ENABLED = False


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonnegative(value: float, name: str) -> float:
    result = _finite(value, name)
    if result < 0:
        raise ValueError(f"{name} must be nonnegative")
    return result


def _probability(value: float, name: str) -> float:
    result = _finite(value, name)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return result


@dataclass(frozen=True)
class FeeBreakdown:
    """Itemized fee estimate on option-premium turnover, in rupees."""
    turnover: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    spread_slippage: float
    permanent_impact: float
    total: float


@dataclass(frozen=True)
class StatutoryCostConfig:
    """Configurable defaults; reconcile rates and GST base to trade-date rules."""
    sell_stt_rate: float = 0.0015
    nse_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    buy_stamp_rate: float = 0.00003
    brokerage_per_order: float = 0.0
    gst_applies_to_exchange_and_sebi: bool = True

    def __post_init__(self) -> None:
        for name in ("sell_stt_rate", "nse_per_crore", "sebi_per_crore", "gst_rate",
                     "buy_stamp_rate", "brokerage_per_order"):
            _nonnegative(getattr(self, name), name)
        if self.gst_rate > 1.0:
            raise ValueError("gst_rate must be a rate in [0, 1]")


class StatutoryCostCalculator:
    """Estimate Indian equity-option costs and configurable execution frictions.

    Turnover = premium * lots * lot_size. The default GST base includes NSE,
    SEBI and brokerage charges, not the full option premium or STT/stamp duty.
    """
    def __init__(self, config: StatutoryCostConfig | None = None) -> None:
        self.config = config or StatutoryCostConfig()

    def calculate(
        self,
        *,
        premium: float,
        lots: int,
        lot_size: int,
        side: str,
        half_spread_per_unit: float = 0.0,
        permanent_impact_per_unit: float = 0.0,
        brokerage_per_order: float | None = None,
    ) -> FeeBreakdown:
        premium = _nonnegative(premium, "premium")
        spread = _nonnegative(half_spread_per_unit, "half_spread_per_unit")
        impact = _nonnegative(permanent_impact_per_unit, "permanent_impact_per_unit")
        if isinstance(lots, bool) or not isinstance(lots, int) or lots < 0:
            raise ValueError("lots must be a nonnegative integer")
        if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
            raise ValueError("lot_size must be a positive integer")
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        brokerage = self.config.brokerage_per_order if brokerage_per_order is None else _nonnegative(
            brokerage_per_order, "brokerage_per_order"
        )
        turnover = premium * lots * lot_size
        exchange = turnover * self.config.nse_per_crore / 10_000_000.0
        sebi = turnover * self.config.sebi_per_crore / 10_000_000.0
        stt = turnover * self.config.sell_stt_rate if side == "SELL" else 0.0
        stamp = turnover * self.config.buy_stamp_rate if side == "BUY" else 0.0
        gst_base = brokerage + (exchange + sebi if self.config.gst_applies_to_exchange_and_sebi else 0.0)
        gst = gst_base * self.config.gst_rate
        quantity = lots * lot_size
        spread_cost = spread * quantity
        impact_cost = impact * quantity
        components = (turnover, stt, exchange, sebi, gst, stamp, brokerage, spread_cost, impact_cost)
        if not all(math.isfinite(x) for x in components):
            raise ValueError("cost calculation overflowed")
        total = sum(components[1:])
        return FeeBreakdown(turnover, stt, exchange, sebi, gst, stamp, brokerage,
                            spread_cost, impact_cost, total)


@dataclass(frozen=True)
class IndifferenceBand:
    target_delta: float
    lower: float
    upper: float
    width: float

    def contains(self, hedge_error: float) -> bool:
        hedge_error = _finite(hedge_error, "hedge_error")
        return self.lower <= hedge_error <= self.upper

    def should_rebalance(self, hedge_error: float) -> bool:
        return not self.contains(hedge_error)


class IndifferenceBandEngine:
    """Rough-volatility-adjusted no-transaction band.

    The width is a Whalley-Wilmott-inspired cubic-root approximation:
      width = [3*C / (2*risk_aversion*|Gamma|*S^2*vol_scale)]^(1/3)
    where vol_scale is increased by realized volatility, roughness and regime
    multipliers. This is a configurable control approximation, not an exact
    solution of a fully nonlinear non-Markovian HJB equation.
    """
    def __init__(self, *, reference_volatility: float = 0.02,
                 roughness_sensitivity: float = 1.0,
                 min_width: float = 1e-4, max_width: float = 1.0,
                 gamma_epsilon: float = 1e-12) -> None:
        self.reference_volatility = _finite(reference_volatility, "reference_volatility")
        self.roughness_sensitivity = _nonnegative(roughness_sensitivity, "roughness_sensitivity")
        self.min_width = _nonnegative(min_width, "min_width")
        self.max_width = _nonnegative(max_width, "max_width")
        self.gamma_epsilon = _nonnegative(gamma_epsilon, "gamma_epsilon")
        if self.reference_volatility <= 0 or self.max_width < self.min_width:
            raise ValueError("invalid volatility or band bounds")

    def compute(self, *, target_delta: float, spot: float, option_gamma: float,
                transaction_cost: float, realized_volatility: float, hurst: float,
                risk_aversion: float, regime_multiplier: float = 1.0) -> IndifferenceBand:
        target = _finite(target_delta, "target_delta")
        spot = _finite(spot, "spot")
        gamma = _finite(option_gamma, "option_gamma")
        cost = _nonnegative(transaction_cost, "transaction_cost")
        vol = _nonnegative(realized_volatility, "realized_volatility")
        hurst = _finite(hurst, "hurst")
        aversion = _finite(risk_aversion, "risk_aversion")
        regime_multiplier = _finite(regime_multiplier, "regime_multiplier")
        if spot <= 0 or aversion <= 0 or not 0 < hurst < 0.5 or regime_multiplier <= 0:
            raise ValueError("spot/risk_aversion/regime_multiplier must be positive and H must be in (0, 0.5)")
        if cost == 0:
            width = self.min_width
        elif abs(gamma) <= self.gamma_epsilon:
            width = self.max_width
        else:
            vol_scale = max(vol / self.reference_volatility, 0.25)
            roughness_scale = 1.0 + self.roughness_sensitivity * (0.5 - hurst)
            risk_scale = vol_scale * roughness_scale * regime_multiplier
            raw = (3.0 * cost / (2.0 * aversion * abs(gamma) * spot * spot * risk_scale)) ** (1.0 / 3.0)
            width = min(self.max_width, max(self.min_width, raw))
        return IndifferenceBand(target, target - width, target + width, width)


class MarketRegime(str, Enum):
    CALM_DIFFUSION = "CALM_DIFFUSION"
    HIGH_VOLATILITY_CLUSTERING = "HIGH_VOLATILITY_CLUSTERING"
    POST_EVENT_JUMP_CRUSH = "POST_EVENT_JUMP_CRUSH"


@dataclass
class BayesianRegimeSwitchingModel:
    """Online three-state Gaussian-emission Bayesian filter.

    Observation vector: [realized_volatility, spread_multiple, jump_score].
    Emission parameters and transition probabilities are illustrative defaults
    and require calibration on training data only.
    """
    transition: tuple[tuple[float, float, float], ...] = (
        (0.94, 0.05, 0.01),
        (0.10, 0.82, 0.08),
        (0.18, 0.12, 0.70),
    )
    means: tuple[tuple[float, float, float], ...] = (
        (0.012, 1.0, 0.05),
        (0.035, 2.0, 0.35),
        (0.070, 5.0, 0.80),
    )
    stds: tuple[tuple[float, float, float], ...] = (
        (0.008, 0.45, 0.12),
        (0.020, 1.2, 0.25),
        (0.035, 2.5, 0.25),
    )
    posterior: list[float] = field(default_factory=lambda: [0.80, 0.17, 0.03])

    def __post_init__(self) -> None:
        self.transition = tuple(tuple(float(v) for v in row) for row in self.transition)
        self.means = tuple(tuple(float(v) for v in row) for row in self.means)
        self.stds = tuple(tuple(float(v) for v in row) for row in self.stds)
        if len(self.transition) != 3 or any(len(row) != 3 for row in self.transition):
            raise ValueError("transition must be 3x3")
        for row in self.transition:
            if any(not math.isfinite(v) or v < 0 for v in row) or not math.isclose(sum(row), 1.0, abs_tol=1e-9):
                raise ValueError("each transition row must be probabilities summing to one")
        for matrix_name, matrix in (("means", self.means), ("stds", self.stds)):
            if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
                raise ValueError(f"{matrix_name} must be 3x3")
            for row in matrix:
                if not all(math.isfinite(v) for v in row):
                    raise ValueError(f"{matrix_name} must be finite")
        if any(v <= 0 for row in self.stds for v in row):
            raise ValueError("all emission standard deviations must be positive")
        if len(self.posterior) != 3 or any(not math.isfinite(v) or v < 0 for v in self.posterior):
            raise ValueError("posterior must contain three nonnegative probabilities")
        total = sum(self.posterior)
        if total <= 0:
            raise ValueError("posterior must have positive mass")
        self.posterior = [v / total for v in self.posterior]

    @staticmethod
    def _log_gaussian(x: float, mean: float, std: float) -> float:
        z = (x - mean) / std
        return -0.5 * z * z - math.log(std) - 0.5 * math.log(2.0 * math.pi)

    def update(self, observation: Sequence[float]) -> tuple[float, float, float]:
        if len(observation) != 3:
            raise ValueError("observation must be [realized_volatility, spread_multiple, jump_score]")
        x = tuple(_finite(v, "observation") for v in observation)
        if x[0] < 0 or x[1] < 0 or not 0 <= x[2] <= 1:
            raise ValueError("volatility/spread must be nonnegative and jump_score in [0,1]")
        prior = [sum(self.posterior[i] * self.transition[i][j] for i in range(3)) for j in range(3)]
        log_weights = []
        for j in range(3):
            log_w = math.log(max(prior[j], 1e-300))
            for d in range(3):
                log_w += self._log_gaussian(x[d], self.means[j][d], self.stds[j][d])
            log_weights.append(log_w)
        peak = max(log_weights)
        weights = [math.exp(w - peak) for w in log_weights]
        normalizer = sum(weights)
        self.posterior = [w / normalizer for w in weights]
        return tuple(self.posterior)

    @property
    def most_likely_regime(self) -> MarketRegime:
        return (MarketRegime.CALM_DIFFUSION, MarketRegime.HIGH_VOLATILITY_CLUSTERING,
                MarketRegime.POST_EVENT_JUMP_CRUSH)[max(range(3), key=self.posterior.__getitem__)]


@dataclass(frozen=True)
class CVaRResult:
    alpha: float
    var_loss: float
    cvar_loss: float
    downside_shortfall: float
    observations: int


class CVaRObjectiveEvaluator:
    """Empirical CVaR/expected shortfall for losses L=-P&L."""
    def evaluate(self, pnl_samples: Sequence[float], *, alpha: float = 0.95,
                 target_pnl: float = 0.0) -> CVaRResult:
        if not pnl_samples:
            raise ValueError("pnl_samples must not be empty")
        alpha = _finite(alpha, "alpha")
        target = _finite(target_pnl, "target_pnl")
        if not 0 < alpha < 1:
            raise ValueError("alpha must be in (0,1)")
        pnl = [_finite(v, "pnl sample") for v in pnl_samples]
        losses = sorted(-v for v in pnl)
        var_index = min(len(losses) - 1, max(0, math.ceil(alpha * len(losses)) - 1))
        tail_count = max(1, math.ceil((1.0 - alpha) * len(losses)))
        cvar = sum(losses[-tail_count:]) / tail_count
        shortfall = sum(max(target - value, 0.0) for value in pnl) / len(pnl)
        return CVaRResult(alpha, losses[var_index], cvar, shortfall, len(pnl))

    def objective(self, pnl_samples: Sequence[float], *, alpha: float = 0.95,
                  cvar_weight: float = 1.0, target_pnl: float = 0.0) -> float:
        weight = _nonnegative(cvar_weight, "cvar_weight")
        result = self.evaluate(pnl_samples, alpha=alpha, target_pnl=target_pnl)
        return result.cvar_loss * weight + result.downside_shortfall


@dataclass(frozen=True)
class HedgePolicyScore:
    policy_name: str
    mean_pnl: float
    cvar_loss: float
    downside_shortfall: float
    objective: float


@dataclass(frozen=True)
class DeepHedgeChoice:
    selected_policy: str | None
    objective: float | None
    evaluations: tuple[HedgePolicyScore, ...]


class DeepHedgingPolicy:
    """CVaR-based offline selector for precomputed candidate hedge policies.

    This is not a neural network trainer. It compares policy rollouts generated
    by an external offline simulator and selects the eligible policy minimizing
    empirical CVaR plus a configurable downside-shortfall penalty. Keeping the
    policy selector separate prevents synthetic rewards from being mistaken for
    a trained or validated trading strategy.
    """
    def __init__(self, evaluator: CVaRObjectiveEvaluator | None = None,
                 downside_weight: float = 1.0) -> None:
        self.evaluator = evaluator or CVaRObjectiveEvaluator()
        self.downside_weight = _nonnegative(downside_weight, "downside_weight")

    def select(self, pnl_by_policy: Mapping[str, Sequence[float]], *, alpha: float = 0.95,
               min_mean_pnl: float = 0.0) -> DeepHedgeChoice:
        if not pnl_by_policy:
            raise ValueError("pnl_by_policy must not be empty")
        minimum = _finite(min_mean_pnl, "min_mean_pnl")
        scores: list[HedgePolicyScore] = []
        for name, sample in pnl_by_policy.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("policy names must be nonempty strings")
            if not sample:
                raise ValueError(f"policy {name!r} has no PnL observations")
            pnl = [_finite(v, f"{name} pnl") for v in sample]
            result = self.evaluator.evaluate(pnl, alpha=alpha)
            mean_pnl = sum(pnl) / len(pnl)
            objective = result.cvar_loss + self.downside_weight * result.downside_shortfall
            scores.append(HedgePolicyScore(name, mean_pnl, result.cvar_loss,
                                           result.downside_shortfall, objective))
        eligible = [item for item in scores if item.mean_pnl >= minimum]
        if not eligible:
            return DeepHedgeChoice(None, None, tuple(scores))
        best = min(eligible, key=lambda item: (item.objective, -item.mean_pnl, item.policy_name))
        return DeepHedgeChoice(best.policy_name, best.objective, tuple(scores))


@dataclass(frozen=True)
class TradeFrequencyResult:
    optimal_count: int
    net_log_growth: float
    candidate_growths: tuple[float, ...]


class AntiOvertradingThrottler:
    """Exact integer search for a stated quadratic log-growth approximation.

    g(n) = [n*(alpha-friction) - impact_coeff*n^2]/wealth
           - 0.5*n*variance_per_trade/wealth^2.
    This makes assumptions explicit; it is not a universal optimal-frequency
    theorem for market returns. Psychology rules can separately lock entries.
    """
    def __init__(self, *, max_daily_trades: int = 100,
                 loss_streak_limit: int = 3, revenge_ratio_limit: float = 1.25,
                 min_intertrade_seconds: float = 30.0, cooldown_seconds: float = 900.0) -> None:
        if isinstance(max_daily_trades, bool) or not isinstance(max_daily_trades, int) or max_daily_trades < 0:
            raise ValueError("max_daily_trades must be a nonnegative integer")
        if isinstance(loss_streak_limit, bool) or not isinstance(loss_streak_limit, int) or loss_streak_limit < 1:
            raise ValueError("loss_streak_limit must be a positive integer")
        self.hard_max_daily_trades = max_daily_trades
        self.max_daily_trades = max_daily_trades
        self.loss_streak_limit = loss_streak_limit
        self.revenge_ratio_limit = _finite(revenge_ratio_limit, "revenge_ratio_limit")
        self.min_intertrade_seconds = _nonnegative(min_intertrade_seconds, "min_intertrade_seconds")
        self.cooldown_seconds = _nonnegative(cooldown_seconds, "cooldown_seconds")
        if self.revenge_ratio_limit <= 1 or self.cooldown_seconds <= 0:
            raise ValueError("revenge ratio must exceed one and cooldown must be positive")
        self.trade_count = 0
        self.loss_streak = 0
        self.last_fill_time: float | None = None
        self.last_size: float | None = None
        self.lockout_until: float = -math.inf
        self.lockout_reason: str | None = None
        self.optimal_daily_trade_count = max_daily_trades

    def derive_optimal_trade_count(self, *, wealth: float, expected_gross_alpha_per_trade: float,
                                   friction_per_trade: float, impact_coefficient: float,
                                   variance_per_trade: float, max_candidates: int | None = None) -> TradeFrequencyResult:
        wealth = _finite(wealth, "wealth")
        alpha = _finite(expected_gross_alpha_per_trade, "expected_gross_alpha_per_trade")
        friction = _nonnegative(friction_per_trade, "friction_per_trade")
        impact = _nonnegative(impact_coefficient, "impact_coefficient")
        variance = _nonnegative(variance_per_trade, "variance_per_trade")
        if wealth <= 0:
            raise ValueError("wealth must be positive")
        if max_candidates is None:
            limit = self.hard_max_daily_trades
        else:
            if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates < 0:
                raise ValueError("max_candidates must be a nonnegative integer")
            limit = min(max_candidates, self.hard_max_daily_trades)
        growths = []
        for n in range(limit + 1):
            g = (n * (alpha - friction) - impact * n * n) / wealth - 0.5 * n * variance / (wealth * wealth)
            growths.append(g)
        best = max(range(len(growths)), key=growths.__getitem__)
        self.optimal_daily_trade_count = best
        self.max_daily_trades = best
        return TradeFrequencyResult(best, growths[best], tuple(growths))

    def is_locked(self, timestamp: float) -> bool:
        timestamp = _finite(timestamp, "timestamp")
        return timestamp < self.lockout_until

    def can_enter(self, timestamp: float) -> bool:
        timestamp = _finite(timestamp, "timestamp")
        return not self.is_locked(timestamp) and self.trade_count < self.max_daily_trades

    def _lock(self, timestamp: float, reason: str) -> None:
        self.lockout_until = max(self.lockout_until, timestamp + self.cooldown_seconds)
        self.lockout_reason = reason

    def record_fill(self, *, timestamp: float, pnl: float, size: float) -> tuple[bool, str | None]:
        timestamp = _finite(timestamp, "timestamp")
        pnl = _finite(pnl, "pnl")
        size = _finite(size, "size")
        if timestamp < 0 or size <= 0:
            raise ValueError("timestamp must be nonnegative and size positive")
        reason = None
        if self.last_fill_time is not None:
            interval = timestamp - self.last_fill_time
            if interval < 0:
                raise ValueError("fill timestamps must be nondecreasing")
            if interval < self.min_intertrade_seconds:
                reason = "rapid_pacing"
            if self.last_size is not None and size / self.last_size > self.revenge_ratio_limit:
                reason = "revenge_sizing"
        self.trade_count += 1
        self.loss_streak = self.loss_streak + 1 if pnl < 0 else 0
        if self.loss_streak >= self.loss_streak_limit:
            reason = "loss_streak"
        self.last_fill_time = timestamp
        self.last_size = size
        if reason:
            self._lock(timestamp, reason)
        return reason is not None, reason

    def reset_session(self) -> None:
        """Reset per-session counters without clearing an active cooldown latch."""
        self.trade_count = 0
        self.loss_streak = 0
        self.last_fill_time = None
        self.last_size = None


class RiskState(str, Enum):
    IDLE = "IDLE"
    MONITORING_ACTIVE = "MONITORING_ACTIVE"
    HEDGE_REBALANCING = "HEDGE_REBALANCING"
    OVERTRADING_LOCKED = "OVERTRADING_LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START_MONITORING = "START_MONITORING"
    HEDGE_OUTSIDE_BAND = "HEDGE_OUTSIDE_BAND"
    HEDGE_COMPLETE = "HEDGE_COMPLETE"
    OVERTRADING_TRIGGERED = "OVERTRADING_TRIGGERED"
    COOLDOWN_CLEARED = "COOLDOWN_CLEARED"
    EMERGENCY = "EMERGENCY"
    RESET = "RESET"
    RECOVERY_ACK = "RECOVERY_ACK"


@dataclass
class RiskStateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown event; fail closed")
        if self.emergency_latched and event is not RiskEvent.RECOVERY_ACK:
            self.history.append((event.value, "blocked_emergency_latch"))
            return self.state
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event is RiskEvent.START_MONITORING and self.state is RiskState.IDLE:
            self.state = RiskState.MONITORING_ACTIVE
        elif event is RiskEvent.HEDGE_OUTSIDE_BAND and self.state is RiskState.MONITORING_ACTIVE:
            self.state = RiskState.HEDGE_REBALANCING
        elif event is RiskEvent.HEDGE_COMPLETE and self.state is RiskState.HEDGE_REBALANCING:
            self.state = RiskState.MONITORING_ACTIVE
        elif event is RiskEvent.OVERTRADING_TRIGGERED and self.state is not RiskState.EMERGENCY_UNWIND:
            self.state = RiskState.OVERTRADING_LOCKED
        elif event is RiskEvent.COOLDOWN_CLEARED and self.state is RiskState.OVERTRADING_LOCKED:
            self.state = RiskState.MONITORING_ACTIVE
        elif event is RiskEvent.RESET and not self.emergency_latched:
            self.state = RiskState.IDLE
        self.history.append((event.value, self.state.value))
        return self.state


def dispatch_live_order(*args: object, **kwargs: object) -> None:
    """No live execution is available in Cycle 28."""
    raise RuntimeError("live order dispatch is permanently disabled; offline simulation only")


@dataclass(frozen=True)
class TradeAssessment:
    approved: bool
    expected_gross_alpha: float
    friction_hurdle: float
    estimated_costs: FeeBreakdown
    reason: str


@dataclass(frozen=True)
class HedgeAssessment:
    band: IndifferenceBand
    hedge_error: float
    rebalance_required: bool
    regime: MarketRegime
    regime_posterior: tuple[float, float, float]


@dataclass
class Cycle28ExecutionEngine:
    """Orchestrator for research signals, not an execution adapter."""
    cost_calculator: StatutoryCostCalculator = field(default_factory=StatutoryCostCalculator)
    band_engine: IndifferenceBandEngine = field(default_factory=IndifferenceBandEngine)
    regime_model: BayesianRegimeSwitchingModel = field(default_factory=BayesianRegimeSwitchingModel)
    cvar_evaluator: CVaRObjectiveEvaluator = field(default_factory=CVaRObjectiveEvaluator)
    deep_hedging_policy: DeepHedgingPolicy = field(default_factory=DeepHedgingPolicy)
    throttler: AntiOvertradingThrottler = field(default_factory=AntiOvertradingThrottler)
    risk_machine: RiskStateMachine = field(default_factory=RiskStateMachine)

    def start_monitoring(self) -> RiskState:
        return self.risk_machine.transition(RiskEvent.START_MONITORING)

    def assess_hedge(self, *, observation: Sequence[float], target_delta: float,
                     current_hedge_delta: float, spot: float, option_gamma: float,
                     transaction_cost: float, realized_volatility: float, hurst: float,
                     risk_aversion: float, regime_multipliers: Mapping[MarketRegime, float] | None = None) -> HedgeAssessment:
        posterior = self.regime_model.update(observation)
        regime = self.regime_model.most_likely_regime
        multiplier_map = regime_multipliers or {
            MarketRegime.CALM_DIFFUSION: 0.8,
            MarketRegime.HIGH_VOLATILITY_CLUSTERING: 1.2,
            MarketRegime.POST_EVENT_JUMP_CRUSH: 1.6,
        }
        band = self.band_engine.compute(
            target_delta=target_delta, spot=spot, option_gamma=option_gamma,
            transaction_cost=transaction_cost, realized_volatility=realized_volatility,
            hurst=hurst, risk_aversion=risk_aversion,
            regime_multiplier=multiplier_map[regime],
        )
        error = _finite(current_hedge_delta, "current_hedge_delta") - target_delta
        # The band is centered on target_delta; compare the current exposure to it.
        outside = band.should_rebalance(_finite(current_hedge_delta, "current_hedge_delta"))
        if self.risk_machine.state is RiskState.IDLE:
            self.start_monitoring()
        if outside:
            self.risk_machine.transition(RiskEvent.HEDGE_OUTSIDE_BAND)
        return HedgeAssessment(band, error, outside, regime, posterior)

    def assess_trade(self, *, expected_gross_alpha: float, premium: float,
                     lots: int, lot_size: int, side: str, timestamp: float,
                     half_spread_per_unit: float = 0.0,
                     permanent_impact_per_unit: float = 0.0,
                     extra_impact_hurdle: float = 0.0) -> TradeAssessment:
        alpha = _finite(expected_gross_alpha, "expected_gross_alpha")
        timestamp = _finite(timestamp, "timestamp")
        extra = _nonnegative(extra_impact_hurdle, "extra_impact_hurdle")
        # Automatically release only expired psychology cooldowns; a daily cap
        # remains locked until the caller explicitly resets the session counters.
        self.update_lockout_state(timestamp)
        costs = self.cost_calculator.calculate(
            premium=premium, lots=lots, lot_size=lot_size, side=side,
            half_spread_per_unit=half_spread_per_unit,
            permanent_impact_per_unit=permanent_impact_per_unit,
        )
        hurdle = costs.total + extra
        if self.risk_machine.emergency_latched:
            approved, reason = False, "emergency_latched"
        elif not self.throttler.can_enter(timestamp):
            if self.risk_machine.state is not RiskState.OVERTRADING_LOCKED:
                self.risk_machine.transition(RiskEvent.OVERTRADING_TRIGGERED)
            if self.throttler.is_locked(timestamp):
                reason = self.throttler.lockout_reason or "psychology_cooldown"
            else:
                reason = "daily_trade_cap"
            approved = False
        elif alpha <= hurdle:
            approved, reason = False, "gross_alpha_not_strictly_above_friction_hurdle"
        else:
            approved, reason = True, "paper_entry_gate_cleared"
        return TradeAssessment(approved, alpha, hurdle, costs, reason)

    def record_fill(self, *, timestamp: float, pnl: float, size: float) -> tuple[bool, str | None]:
        triggered, reason = self.throttler.record_fill(timestamp=timestamp, pnl=pnl, size=size)
        if triggered:
            self.risk_machine.transition(RiskEvent.OVERTRADING_TRIGGERED)
        return triggered, reason

    def update_lockout_state(self, timestamp: float) -> RiskState:
        if (self.risk_machine.state is RiskState.OVERTRADING_LOCKED
                and not self.throttler.is_locked(timestamp)
                and self.throttler.trade_count < self.throttler.max_daily_trades):
            self.risk_machine.transition(RiskEvent.COOLDOWN_CLEARED)
        return self.risk_machine.state

    def evaluate_cvar(self, pnl_samples: Sequence[float], *, alpha: float = 0.95,
                      target_pnl: float = 0.0) -> CVaRResult:
        return self.cvar_evaluator.evaluate(pnl_samples, alpha=alpha, target_pnl=target_pnl)

    def select_offline_hedge_policy(self, pnl_by_policy: Mapping[str, Sequence[float]], *,
                                    alpha: float = 0.95, min_mean_pnl: float = 0.0) -> DeepHedgeChoice:
        return self.deep_hedging_policy.select(pnl_by_policy, alpha=alpha, min_mean_pnl=min_mean_pnl)

    def trigger_emergency(self) -> RiskState:
        return self.risk_machine.transition(RiskEvent.EMERGENCY)

    def acknowledge_recovery(self) -> RiskState:
        return self.risk_machine.transition(RiskEvent.RECOVERY_ACK)
