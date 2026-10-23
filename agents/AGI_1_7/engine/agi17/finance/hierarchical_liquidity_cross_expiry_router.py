"""Cycle 24: offline multi-agent liquidity routing and cross-expiry research engine.

This module creates simulation plans and paper-ledger accounting only. It has no
broker/exchange adapters, network access, authentication, or live-order path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import exp, floor, isfinite, log, sqrt
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False  # Non-negotiable invariant: never set True.


class IndexName(str, Enum):
    NIFTY = "NIFTY"
    BANKNIFTY = "BANKNIFTY"


class ExpiryName(str, Enum):
    TAU_1 = "tau_1"
    TAU_2 = "tau_2"
    TAU_3 = "tau_3"


class RiskState(str, Enum):
    IDLE = "IDLE"
    MONITORING_ACTIVE = "MONITORING_ACTIVE"
    ARBITRAGE_ENGAGED = "ARBITRAGE_ENGAGED"
    CIRCUIT_BREAKER_HALTED = "CIRCUIT_BREAKER_HALTED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    START_MONITORING = "START_MONITORING"
    ARBITRAGE_SIGNAL = "ARBITRAGE_SIGNAL"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    CALL_AUCTION_STABLE = "CALL_AUCTION_STABLE"
    RESUMPTION_CONFIRMED = "RESUMPTION_CONFIRMED"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"
    STOP = "STOP"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TimeInForce(str, Enum):
    IOC = "IOC"
    DAY = "DAY"
    GTC = "GTC"


class RouteVenue(str, Enum):
    VISIBLE_LIMIT = "VISIBLE_LIMIT"
    PASSIVE_PEGGED = "PASSIVE_PEGGED"
    SIMULATED_BLOCK = "SIMULATED_BLOCK"


def _finite_float(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _bounded(value: float, low: float, high: float, name: str) -> float:
    x = _finite_float(value, name)
    if x < low or x > high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return x


@dataclass(frozen=True)
class DislocationSnapshot:
    dislocation_index: float
    absolute_move: float
    depth_collapse: float
    spread_stress: float
    fill_stress: float
    circuit_breaker_level: Optional[int]


@dataclass
class DislocationTracker:
    """Normalize stress features into D_t in [0,1]. Moves are decimal returns.

    D = a_m min(|r|/0.20,1) + a_d clamp(1-depth/depth0)
        + a_s clamp((spread_multiple-1)/(spread_cap-1)) + a_f (1-fill_prob).
    The weights must sum to one. This is a control index, not a calibrated
    probability of a crash.
    """
    move_weight: float = 0.35
    depth_weight: float = 0.30
    spread_weight: float = 0.20
    fill_weight: float = 0.15
    spread_multiple_cap: float = 20.0
    last_snapshot: Optional[DislocationSnapshot] = field(default=None, init=False)

    def __post_init__(self) -> None:
        weights = [self.move_weight, self.depth_weight, self.spread_weight, self.fill_weight]
        if any(not isfinite(x) or x < 0 for x in weights):
            raise ValueError("dislocation weights must be finite and nonnegative")
        if abs(sum(weights) - 1.0) > 1e-9:
            raise ValueError("dislocation weights must sum to 1")
        if not isfinite(self.spread_multiple_cap) or self.spread_multiple_cap <= 1:
            raise ValueError("spread_multiple_cap must be greater than 1")

    def update(self, *, index_move: float, current_depth: float,
               baseline_depth: float, current_spread: float,
               baseline_spread: float, estimated_fill_probability: float) -> DislocationSnapshot:
        move = _finite_float(index_move, "index_move")
        depth = _finite_float(current_depth, "current_depth")
        depth0 = _finite_float(baseline_depth, "baseline_depth")
        spread = _finite_float(current_spread, "current_spread")
        spread0 = _finite_float(baseline_spread, "baseline_spread")
        fill = _bounded(estimated_fill_probability, 0.0, 1.0, "estimated_fill_probability")
        if depth < 0 or depth0 <= 0 or spread < 0 or spread0 <= 0:
            raise ValueError("depths must be nonnegative (baseline positive) and spreads baseline-positive")
        move_stress = min(abs(move) / 0.20, 1.0)
        depth_stress = min(max(1.0 - depth / depth0, 0.0), 1.0)
        spread_multiple = spread / spread0
        spread_stress = min(max((spread_multiple - 1.0) / (self.spread_multiple_cap - 1.0), 0.0), 1.0)
        fill_stress = 1.0 - fill
        d = (self.move_weight * move_stress + self.depth_weight * depth_stress
             + self.spread_weight * spread_stress + self.fill_weight * fill_stress)
        d = min(max(d, 0.0), 1.0)
        absolute_move = abs(move)
        # Conservative internal thresholds: the actual exchange response also
        # depends on time of day. This layer does not infer halt duration or
        # reopen automatically; downstream state needs an explicit session event.
        level = 20 if absolute_move >= 0.20 else 15 if absolute_move >= 0.15 else 10 if absolute_move >= 0.10 else None
        result = DislocationSnapshot(d, absolute_move, depth_stress, spread_stress, fill_stress, level)
        self.last_snapshot = result
        return result


@dataclass(frozen=True)
class PortfolioGreeks:
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0

    def vector(self) -> np.ndarray:
        x = np.asarray([self.delta, self.gamma, self.vega, self.theta], dtype=float)
        if not np.isfinite(x).all():
            raise ValueError("portfolio Greeks must be finite")
        return x


@dataclass(frozen=True)
class RiskBudgetAllocation:
    index: IndexName
    expiry: ExpiryName
    tau_years: float
    budget: float
    normalized_weight: float


@dataclass
class SystemicAllocator:
    """Allocate a shrinking risk budget across 2 indices x 3 expiries."""
    index_base_weights: Mapping[IndexName, float] = field(default_factory=lambda: {
        IndexName.NIFTY: 0.55, IndexName.BANKNIFTY: 0.45
    })
    expiry_base_weights: Tuple[float, float, float] = (0.50, 0.30, 0.20)
    greek_penalty_scale: float = 1.0
    dislocation_penalty: float = 2.0
    term_slope_sensitivity: float = 1.0

    def __post_init__(self) -> None:
        if set(self.index_base_weights) != set(IndexName):
            raise ValueError("base weights must specify NIFTY and BANKNIFTY")
        vals = list(self.index_base_weights.values()) + list(self.expiry_base_weights)
        if any(not isfinite(v) or v <= 0 for v in vals):
            raise ValueError("allocator base weights must be positive and finite")
        if abs(sum(self.index_base_weights.values()) - 1.0) > 1e-9:
            raise ValueError("index base weights must sum to 1")
        if abs(sum(self.expiry_base_weights) - 1.0) > 1e-9:
            raise ValueError("expiry base weights must sum to 1")
        if min(self.greek_penalty_scale, self.dislocation_penalty, self.term_slope_sensitivity) < 0:
            raise ValueError("penalty parameters must be nonnegative")

    def allocate(self, *, total_risk_budget: float, greeks: PortfolioGreeks,
                 dislocation_index: float, term_structure_slope: float,
                 taus: Sequence[float], halted: bool = False) -> List[RiskBudgetAllocation]:
        total = _finite_float(total_risk_budget, "total_risk_budget")
        d = _bounded(dislocation_index, 0.0, 1.0, "dislocation_index")
        slope = _finite_float(term_structure_slope, "term_structure_slope")
        gs = greeks.vector()
        tau_arr = np.asarray(taus, dtype=float)
        if total < 0:
            raise ValueError("total_risk_budget must be nonnegative")
        if tau_arr.shape != (3,) or not np.isfinite(tau_arr).all() or np.any(tau_arr <= 0):
            raise ValueError("taus must be three positive finite maturities in years")
        if halted:
            return [RiskBudgetAllocation(i, e, float(t), 0.0, 0.0)
                    for i in IndexName for e, t in zip(ExpiryName, tau_arr)]

        # Scaled absolute-Greek pressure: the caller should keep Greeks in a
        # consistent unit convention; these scales avoid a single raw unit
        # dominating simply because of its numerical magnitude.
        greek_pressure = float(np.sum(np.abs(gs) / np.array([100.0, 0.1, 100.0, 100.0])))
        usable_budget = total * (1.0 - d) ** 2 / (1.0 + self.greek_penalty_scale * greek_pressure)
        # Large magnitude slope is uncertainty: shrink risk globally and tilt
        # away from the nearest expiry during inversions.
        usable_budget /= (1.0 + self.term_slope_sensitivity * abs(slope))
        scores: List[Tuple[IndexName, ExpiryName, float, float]] = []
        for idx, idx_w in self.index_base_weights.items():
            for j, (expiry, tau) in enumerate(zip(ExpiryName, tau_arr)):
                near_penalty = 1.0 + self.dislocation_penalty * d / (j + 1)
                term_tilt = exp(-min(10.0, abs(slope) * (3 - j) * self.term_slope_sensitivity))
                score = idx_w * self.expiry_base_weights[j] * term_tilt / near_penalty
                scores.append((idx, expiry, float(tau), score))
        total_score = sum(row[3] for row in scores)
        if total_score <= 0 or not isfinite(total_score):
            raise RuntimeError("allocator score normalization failed")
        return [RiskBudgetAllocation(idx, expiry, tau, usable_budget * score / total_score, score / total_score)
                for idx, expiry, tau, score in scores]


@dataclass(frozen=True)
class VolSurfacePoint:
    index: IndexName
    tau_years: float
    log_moneyness: float
    implied_volatility: float


@dataclass(frozen=True)
class SurfaceValidation:
    valid: bool
    calendar_violations: Tuple[str, ...]
    butterfly_violations: Tuple[str, ...]
    point_count: int


@dataclass(frozen=True)
class CalendarSpreadSignal:
    index: IndexName
    log_moneyness: float
    front_tau: float
    back_tau: float
    front_iv: float
    back_iv: float
    annualized_variance_edge: float
    suggested_front_side: Side = Side.SELL
    suggested_back_side: Side = Side.BUY
    # Relative-value signal only: not risk-free arbitrage.


@dataclass
class CrossExpiryArbitrageur:
    calendar_tolerance: float = 1e-10
    butterfly_tolerance: float = 2e-4
    inversion_threshold: float = 0.005

    def __post_init__(self) -> None:
        params = [self.calendar_tolerance, self.butterfly_tolerance, self.inversion_threshold]
        if any(not isfinite(float(x)) or x < 0 for x in params):
            raise ValueError("validation tolerances must be finite and nonnegative")

    @staticmethod
    def _normal_cdf(x: float) -> float:
        # Python standard library only; stable enough for diagnostic grids.
        from math import erf
        return 0.5 * (1.0 + erf(x / sqrt(2.0)))

    @classmethod
    def _normalized_forward_call(cls, k: float, tau: float, iv: float) -> float:
        strike = exp(k)
        if tau <= 0 or iv < 0:
            raise ValueError("tau must be positive and IV nonnegative")
        if iv == 0:
            return max(1.0 - strike, 0.0)
        st = iv * sqrt(tau)
        d1 = (-k + 0.5 * st * st) / st
        d2 = d1 - st
        return cls._normal_cdf(d1) - strike * cls._normal_cdf(d2)

    def validate_surface(self, points: Sequence[VolSurfacePoint]) -> SurfaceValidation:
        if not points:
            raise ValueError("surface must contain at least one point")
        for p in points:
            vals = [p.tau_years, p.log_moneyness, p.implied_volatility]
            if not all(isfinite(float(v)) for v in vals):
                raise ValueError("surface inputs must be finite")
            if p.tau_years <= 0 or p.implied_volatility < 0:
                raise ValueError("maturities must be positive and IVs nonnegative")
        if any(not isinstance(p.index, IndexName) for p in points):
            raise ValueError("each surface point must use an IndexName")
        seen = set()
        for p in points:
            key = (p.index, p.tau_years, p.log_moneyness)
            if key in seen:
                raise ValueError("duplicate (index, maturity, log-moneyness) surface point")
            seen.add(key)
        calendar_violations: List[str] = []
        butterfly_violations: List[str] = []
        # Gatheral calendar condition: total variance w(k,tau)=sigma^2*tau
        # must be nondecreasing in tau at each fixed log-moneyness.
        groups: Dict[Tuple[IndexName, float], List[VolSurfacePoint]] = {}
        for p in points:
            groups.setdefault((p.index, p.log_moneyness), []).append(p)
        for (idx, k), arr in groups.items():
            arr.sort(key=lambda p: p.tau_years)
            for left, right in zip(arr, arr[1:]):
                w0 = left.implied_volatility ** 2 * left.tau_years
                w1 = right.implied_volatility ** 2 * right.tau_years
                if w1 + self.calendar_tolerance < w0:
                    calendar_violations.append(
                        f"{idx.value} k={k:g}: w({right.tau_years:g}) < w({left.tau_years:g})")
        # Sampled butterfly diagnostic: normalized call prices must decrease
        # and be convex in strike. This is a grid diagnostic, not a proof over
        # all strikes or a formal global-arbitrage guarantee.
        expiries = sorted({(p.index, p.tau_years) for p in points})
        for idx, tau in expiries:
            arr = sorted((p for p in points if p.index == idx and abs(p.tau_years-tau) < 1e-12),
                         key=lambda p: p.log_moneyness)
            if len(arr) < 3:
                continue
            strikes = np.asarray([exp(p.log_moneyness) for p in arr], dtype=float)
            calls = np.asarray([self._normalized_forward_call(p.log_moneyness, p.tau_years,
                                                              p.implied_volatility) for p in arr])
            if np.any(np.diff(calls) > self.butterfly_tolerance):
                butterfly_violations.append(f"{idx.value} tau={tau:g}: call price increases with strike")
            slopes = np.diff(calls) / np.diff(strikes)
            if np.any(np.diff(slopes) < -self.butterfly_tolerance):
                butterfly_violations.append(f"{idx.value} tau={tau:g}: sampled call curve is not convex")
            if np.any(calls < np.maximum(1.0-strikes, 0.0)-self.butterfly_tolerance) or np.any(calls > 1.0+self.butterfly_tolerance):
                butterfly_violations.append(f"{idx.value} tau={tau:g}: normalized call violates intrinsic/upper bound")
        return SurfaceValidation(not calendar_violations and not butterfly_violations,
                                 tuple(calendar_violations), tuple(butterfly_violations), len(points))

    def detect_spreads(self, points: Sequence[VolSurfacePoint], *, dislocation_index: float) -> List[CalendarSpreadSignal]:
        d = _bounded(dislocation_index, 0.0, 1.0, "dislocation_index")
        result = self.validate_surface(points)
        # Never create candidate signals from a surface that failed the sampled
        # no-arbitrage gate; invalid surfaces need quarantine/recalibration.
        if not result.valid:
            return []
        by_key: Dict[Tuple[IndexName, float], List[VolSurfacePoint]] = {}
        for p in points:
            by_key.setdefault((p.index, p.log_moneyness), []).append(p)
        signals: List[CalendarSpreadSignal] = []
        threshold = self.inversion_threshold * (1.0 - 0.5 * d)
        for (idx, k), arr in by_key.items():
            arr.sort(key=lambda p: p.tau_years)
            for front, back in zip(arr, arr[1:]):
                edge = front.implied_volatility ** 2 - back.implied_volatility ** 2
                # Annualized variance inversion can coexist with monotone total
                # variance; this is a relative-value setup, never a free lunch.
                if edge > threshold:
                    signals.append(CalendarSpreadSignal(idx, k, front.tau_years, back.tau_years,
                                                        front.implied_volatility, back.implied_volatility,
                                                        edge))
        return signals


@dataclass(frozen=True)
class FeeConfig:
    options_sell_stt_rate: float = 0.0015
    nse_exchange_rate: float = 0.0003553  # Rs 3,553 per Rs 1 crore
    gst_rate: float = 0.18
    stamp_buy_rate: float = 0.00003
    brokerage_per_order: float = 0.0
    gst_applies_to_exchange_and_brokerage: bool = True

    def __post_init__(self) -> None:
        rates = [self.options_sell_stt_rate, self.nse_exchange_rate, self.gst_rate,
                 self.stamp_buy_rate, self.brokerage_per_order]
        if any(not isfinite(x) or x < 0 for x in rates):
            raise ValueError("fee configuration values must be finite and nonnegative")


@dataclass(frozen=True)
class CostBreakdown:
    premium_turnover: float
    stt: float
    exchange_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    half_spread_slippage: float
    market_impact: float
    total: float


def statutory_friction(*, premium: float, lots: int, lot_size: int, side: Side,
                       base_spread_per_unit: float, dislocation_index: float,
                       kappa_dislocation: float = 5.0,
                       market_impact_per_unit: float = 0.0,
                       config: FeeConfig = FeeConfig()) -> CostBreakdown:
    """Calculate fees and slippage on turnover = premium * lots * lot_size.

    `base_spread_per_unit` is the full quoted spread in option premium points;
    slippage is half the effective spread times contract quantity.
    """
    prem = _finite_float(premium, "premium")
    base_spread = _finite_float(base_spread_per_unit, "base_spread_per_unit")
    impact_unit = _finite_float(market_impact_per_unit, "market_impact_per_unit")
    d = _bounded(dislocation_index, 0.0, 1.0, "dislocation_index")
    kappa = _finite_float(kappa_dislocation, "kappa_dislocation")
    if (not isinstance(lots, int) or isinstance(lots, bool)
            or not isinstance(lot_size, int) or isinstance(lot_size, bool)):
        raise ValueError("lots and lot_size must be integers")
    if prem < 0 or lots < 0 or lot_size <= 0 or base_spread < 0 or impact_unit < 0 or kappa < 0:
        raise ValueError("premium, lots, spreads, impact and kappa must be nonnegative; lot_size must be positive")
    if not isinstance(side, Side):
        raise ValueError("side must be a Side enum")
    contracts = int(lots) * int(lot_size)
    turnover = prem * contracts
    stt = turnover * config.options_sell_stt_rate if side is Side.SELL else 0.0
    exchange = turnover * config.nse_exchange_rate
    brokerage = config.brokerage_per_order
    gst_base = exchange + brokerage if config.gst_applies_to_exchange_and_brokerage else 0.0
    gst = gst_base * config.gst_rate
    stamp = turnover * config.stamp_buy_rate if side is Side.BUY else 0.0
    effective_full_spread = base_spread * (1.0 + kappa * d)
    half_spread_cost = 0.5 * effective_full_spread * contracts
    impact = impact_unit * contracts * (1.0 + d)  # conservative dislocation multiplier
    parts = [turnover, stt, exchange, gst, stamp, brokerage, half_spread_cost, impact]
    if not all(isfinite(x) for x in parts):
        raise ValueError("friction calculation overflowed")
    return CostBreakdown(turnover, stt, exchange, gst, stamp, brokerage,
                         half_spread_cost, impact, float(sum(parts[1:])))


def passes_alpha_hurdle(expected_gross_alpha: float, costs: CostBreakdown) -> bool:
    """Strict hurdle: alpha must be greater than, not equal to, total friction."""
    alpha = _finite_float(expected_gross_alpha, "expected_gross_alpha")
    return alpha > costs.total


@dataclass(frozen=True)
class BookSnapshot:
    index: IndexName
    best_bid: float
    best_ask: float
    visible_bid_depth_lots: int
    visible_ask_depth_lots: int
    passive_bid_depth_lots: int = 0
    passive_ask_depth_lots: int = 0
    simulated_block_depth_lots: int = 0
    baseline_spread: Optional[float] = None

    def __post_init__(self) -> None:
        values = [self.best_bid, self.best_ask]
        if not all(isfinite(x) for x in values) or self.best_bid < 0 or self.best_ask <= 0 or self.best_ask < self.best_bid:
            raise ValueError("invalid best bid/ask")
        depth_values = [self.visible_bid_depth_lots, self.visible_ask_depth_lots,
                        self.passive_bid_depth_lots, self.passive_ask_depth_lots,
                        self.simulated_block_depth_lots]
        if any(not isinstance(x, int) or x < 0 for x in depth_values):
            raise ValueError("book depths must be nonnegative integers")
        if self.baseline_spread is not None and (not isfinite(self.baseline_spread) or self.baseline_spread <= 0):
            raise ValueError("baseline_spread must be positive and finite")

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid


@dataclass(frozen=True)
class OrderIntent:
    index: IndexName
    expiry: ExpiryName
    side: Side
    premium: float
    lots: int
    lot_size: int
    expected_gross_alpha: float
    time_in_force: TimeInForce = TimeInForce.IOC
    urgency: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.side, Side) or not isinstance(self.time_in_force, TimeInForce):
            raise ValueError("side and time_in_force must be enums")
        if (not isfinite(self.premium) or self.premium < 0
                or not isinstance(self.lots, int) or isinstance(self.lots, bool) or self.lots < 0
                or not isinstance(self.lot_size, int) or isinstance(self.lot_size, bool) or self.lot_size <= 0):
            raise ValueError("invalid premium, lots, or lot_size; lots and lot_size must be integers")
        if not isfinite(self.expected_gross_alpha):
            raise ValueError("expected_gross_alpha must be finite")
        _bounded(self.urgency, 0.0, 1.0, "urgency")


@dataclass(frozen=True)
class ChildSlice:
    simulated_order_id: str
    venue: RouteVenue
    side: Side
    lots: int
    limit_price: float
    time_in_force: TimeInForce
    passive: bool


@dataclass(frozen=True)
class RouterDecision:
    accepted_for_simulation: bool
    reason: str
    costs: CostBreakdown
    expected_gross_alpha: float
    expected_net_alpha: float
    slices: Tuple[ChildSlice, ...]
    requested_lots: int
    planned_lots: int
    unallocated_lots: int


@dataclass
class SmartOrderRouter:
    """Build simulated child-slice plans; never transmits an order externally."""
    max_slice_lots: int = 10
    kappa_dislocation: float = 5.0
    market_impact_coefficient: float = 0.01
    fee_config: FeeConfig = field(default_factory=FeeConfig)
    _sequence: int = field(default=0, init=False)
    resting_passive_orders: Dict[str, ChildSlice] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.max_slice_lots, int) or isinstance(self.max_slice_lots, bool)
                or self.max_slice_lots < 1
                or not isfinite(float(self.kappa_dislocation)) or self.kappa_dislocation < 0
                or not isfinite(float(self.market_impact_coefficient)) or self.market_impact_coefficient < 0):
            raise ValueError("router parameters must be finite and nonnegative; max_slice_lots must be a positive integer")

    def cancel_all_passive_orders(self) -> int:
        count = len(self.resting_passive_orders)
        self.resting_passive_orders.clear()
        return count

    def plan_order(self, intent: OrderIntent, book: BookSnapshot, *, dislocation_index: float,
                   risk_state: RiskState) -> RouterDecision:
        d = _bounded(dislocation_index, 0.0, 1.0, "dislocation_index")
        if not isinstance(risk_state, RiskState):
            raise ValueError("risk_state must be RiskState")
        # Fail closed in all states other than explicit active risk states.
        if LIVE_ORDER_DISPATCH_ENABLED is not False:
            raise RuntimeError("live dispatch invariant violated")
        if risk_state not in {RiskState.MONITORING_ACTIVE, RiskState.ARBITRAGE_ENGAGED}:
            zero = statutory_friction(premium=intent.premium, lots=intent.lots, lot_size=intent.lot_size,
                                      side=intent.side, base_spread_per_unit=book.spread,
                                      dislocation_index=d, kappa_dislocation=self.kappa_dislocation,
                                      market_impact_per_unit=0.0, config=self.fee_config)
            return RouterDecision(False, "risk state blocks routing", zero, intent.expected_gross_alpha,
                                  intent.expected_gross_alpha-zero.total, (), intent.lots, 0, intent.lots)
        # Use spread in premium points and a convex participation-style impact proxy.
        effective_depth = (book.visible_ask_depth_lots + book.visible_bid_depth_lots
                           + book.passive_ask_depth_lots + book.passive_bid_depth_lots
                           + book.simulated_block_depth_lots)
        impact_unit = self.market_impact_coefficient * d * (max(intent.lots, 1) / max(effective_depth, 1)) ** 2
        costs = statutory_friction(premium=intent.premium, lots=intent.lots, lot_size=intent.lot_size,
                                   side=intent.side, base_spread_per_unit=book.spread,
                                   dislocation_index=d, kappa_dislocation=self.kappa_dislocation,
                                   market_impact_per_unit=impact_unit, config=self.fee_config)
        net_alpha = intent.expected_gross_alpha - costs.total
        if not passes_alpha_hurdle(intent.expected_gross_alpha, costs):
            return RouterDecision(False, "gross alpha does not strictly exceed friction hurdle", costs,
                                  intent.expected_gross_alpha, net_alpha, (), intent.lots, 0, intent.lots)
        if intent.lots == 0:
            return RouterDecision(False, "zero-size intent", costs, intent.expected_gross_alpha,
                                  net_alpha, (), 0, 0, 0)

        if intent.side is Side.BUY:
            capacities = [
                (RouteVenue.VISIBLE_LIMIT, book.visible_ask_depth_lots, False),
                (RouteVenue.SIMULATED_BLOCK, book.simulated_block_depth_lots, False),
                (RouteVenue.PASSIVE_PEGGED, book.passive_bid_depth_lots, True),
            ]
            limit_price = book.best_ask
        else:
            capacities = [
                (RouteVenue.VISIBLE_LIMIT, book.visible_bid_depth_lots, False),
                (RouteVenue.SIMULATED_BLOCK, book.simulated_block_depth_lots, False),
                (RouteVenue.PASSIVE_PEGGED, book.passive_ask_depth_lots, True),
            ]
            limit_price = book.best_bid
        if intent.time_in_force is TimeInForce.IOC:
            capacities = [x for x in capacities if not x[2]]
        # Smaller slices as dislocation rises; urgency can slightly increase slice size.
        base_slice = max(1, int(floor(self.max_slice_lots * (1.0 - 0.75*d) * (0.75 + 0.5*intent.urgency))))
        remaining = intent.lots
        children: List[ChildSlice] = []
        for venue, available, passive in capacities:
            venue_remaining = available
            while remaining > 0 and venue_remaining > 0:
                take = min(remaining, venue_remaining, base_slice)
                self._sequence += 1
                child_id = f"SIM-C24-{self._sequence:08d}"
                child = ChildSlice(child_id, venue, intent.side, take, float(limit_price),
                                   intent.time_in_force, passive)
                children.append(child)
                if passive:
                    self.resting_passive_orders[child_id] = child
                remaining -= take
                venue_remaining -= take
        planned = intent.lots - remaining
        reason = "planned in offline simulation" if remaining == 0 else "partial simulated liquidity; remainder not routed"
        return RouterDecision(planned > 0, reason, costs, intent.expected_gross_alpha, net_alpha,
                              tuple(children), intent.lots, planned, remaining)


@dataclass
class RiskStateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    circuit_breaker_latched: bool = False
    call_auction_stable: bool = False
    history: List[Tuple[str, str, str]] = field(default_factory=list)

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown risk event; fail closed")
        # Explicit acknowledgement is the sole operation that can clear the
        # emergency latch. Normal events cannot clear either latch by accident.
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.CIRCUIT_BREAKER:
            # Preserve the market halt latch even if an emergency is already
            # active; the emergency state has display/transition precedence.
            self.circuit_breaker_latched = True
            self.call_auction_stable = False
            if not self.emergency_latched:
                self.state = RiskState.CIRCUIT_BREAKER_HALTED
        elif event is RiskEvent.RECOVERY_ACK:
            if self.emergency_latched:
                self.emergency_latched = False
                self.state = (RiskState.CIRCUIT_BREAKER_HALTED if self.circuit_breaker_latched else RiskState.IDLE)
            # An acknowledgement does not itself resume a halted exchange.
        elif self.emergency_latched:
            pass
        elif event is RiskEvent.CALL_AUCTION_STABLE:
            if self.circuit_breaker_latched:
                self.call_auction_stable = True
                self.state = RiskState.CIRCUIT_BREAKER_HALTED
        elif event is RiskEvent.RESUMPTION_CONFIRMED:
            if self.circuit_breaker_latched and self.call_auction_stable:
                self.circuit_breaker_latched = False
                self.call_auction_stable = False
                self.state = RiskState.MONITORING_ACTIVE
        elif event is RiskEvent.START_MONITORING:
            if self.state is RiskState.IDLE and not self.circuit_breaker_latched:
                self.state = RiskState.MONITORING_ACTIVE
        elif event is RiskEvent.ARBITRAGE_SIGNAL:
            if self.state is RiskState.MONITORING_ACTIVE and not self.circuit_breaker_latched:
                self.state = RiskState.ARBITRAGE_ENGAGED
        elif event is RiskEvent.STOP:
            if not self.circuit_breaker_latched:
                self.state = RiskState.IDLE
        else:
            raise ValueError("unhandled risk event; fail closed")
        self.history.append((event.value, self.state.value, "emergency_latched" if self.emergency_latched else "ok"))
        return self.state

    def can_allocate_or_route(self) -> bool:
        return (not self.emergency_latched and not self.circuit_breaker_latched
                and self.state in {RiskState.MONITORING_ACTIVE, RiskState.ARBITRAGE_ENGAGED})


@dataclass
class MultiAgentRouter:
    """Top-level coordinator: dislocation observer, risk gate, allocator, agents."""
    dislocation_tracker: DislocationTracker = field(default_factory=DislocationTracker)
    allocator: SystemicAllocator = field(default_factory=SystemicAllocator)
    arbitrageur: CrossExpiryArbitrageur = field(default_factory=CrossExpiryArbitrageur)
    sor: SmartOrderRouter = field(default_factory=SmartOrderRouter)
    risk: RiskStateMachine = field(default_factory=RiskStateMachine)

    def observe_market(self, *, index_move: float, current_depth: float,
                       baseline_depth: float, current_spread: float,
                       baseline_spread: float, estimated_fill_probability: float) -> DislocationSnapshot:
        snapshot = self.dislocation_tracker.update(
            index_move=index_move, current_depth=current_depth, baseline_depth=baseline_depth,
            current_spread=current_spread, baseline_spread=baseline_spread,
            estimated_fill_probability=estimated_fill_probability)
        if snapshot.circuit_breaker_level is not None:
            self.risk.transition(RiskEvent.CIRCUIT_BREAKER)
            self.sor.cancel_all_passive_orders()
        return snapshot

    def allocate(self, *, total_risk_budget: float, greeks: PortfolioGreeks,
                 term_structure_slope: float, taus: Sequence[float]) -> List[RiskBudgetAllocation]:
        d = self.dislocation_tracker.last_snapshot.dislocation_index if self.dislocation_tracker.last_snapshot else 0.0
        allowed = self.risk.can_allocate_or_route()
        return self.allocator.allocate(total_risk_budget=total_risk_budget, greeks=greeks,
                                       dislocation_index=d, term_structure_slope=term_structure_slope,
                                       taus=taus, halted=not allowed)

    def plan_order(self, intent: OrderIntent, book: BookSnapshot) -> RouterDecision:
        d = self.dislocation_tracker.last_snapshot.dislocation_index if self.dislocation_tracker.last_snapshot else 0.0
        return self.sor.plan_order(intent, book, dislocation_index=d, risk_state=self.risk.state)


def dispatch_live_order(*args: object, **kwargs: object) -> None:
    """Deliberately nonfunctional live-dispatch sentinel."""
    raise RuntimeError("Cycle 24 is simulation-only; live order dispatch is disabled")
