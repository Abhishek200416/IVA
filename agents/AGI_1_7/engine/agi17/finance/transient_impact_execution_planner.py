"""
Phase 28 / Cycle 17: Transient vs Permanent Price Impact Execution Planner.

Implements frontier mathematical methods researched from ChatGPT Cycle 17:
1. Multi-Exponential Transient Impact Kernel & Propagator:
       G(u) = sum_{k=1}^K gamma_k exp(-rho_k u)
   with exact constant-rate interval recurrence:
       z_{k, n+1} = exp(-rho_k Delta t) z_{k,n} + (gamma_k u_n / rho_k) (1 - exp(-rho_k Delta t))
   and exact integrated interval impact cost.
2. Almgren-Chriss Continuous-Time Inventory Schedule Baseline:
       x(t) = Q * sinh(kappa * (T - t)) / sinh(kappa * T), where kappa = sqrt(lambda * sigma^2 / eta)
3. Discrete Lot-Grid Dynamic Programming Optimizer:
   Optimizes integer child-order lot sizes over finite horizons with hard terminal
   boundary x(T) = 0, capacity bounds, and statutory fee mapping.
4. Hawkes Intensity & Multi-Level OFI Conditioned Adaptive Slicing:
   Dynamically scales participation rate nu_t and crossing aggression based on aligned OFI
   and Hawkes jump hazard ratio lambda_J(t) / lambda_bar.
5. Effective-Dated Indian Derivatives Statutory Fee Engine (NSE October 2026):
   - Options exchange + IPFT: Rs 3,553 / crore of premium turnover.
   - Futures exchange + IPFT: Rs 183 / crore of notional turnover.
   - STT: 0.15% on options sale; 0.05% on futures sale.
   - Stamp Duty: 0.003% on options buy; 0.002% on futures buy.
   - SEBI Fee: Rs 10 / crore.
   - GST: 18% on Taxable Services (Brokerage + Exchange + SEBI), strictly excluding STT and Stamp Duty.
6. 5-State Discrete Execution State Machine & Deterministic Mock Fills:
   IDLE -> PASSIVE_POSTING -> CROSS_SPREAD_FILL | ADVERSE_SELECTION_HALT | EMERGENCY_UNWIND (latched).

Fail-Closed Safety Invariant:
    LIVE_ORDER_DISPATCH_ENABLED = False (strictly advisory and execution planning; real broker fills locked).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum
from functools import lru_cache
from typing import Mapping, Sequence, Tuple
import numpy as np

# Immutable Fail-Closed Safety Invariant
LIVE_ORDER_DISPATCH_ENABLED: bool = False
RUPEES_PER_CRORE: float = 10_000_000.0


class Product(str, Enum):
    OPTION = "option"
    FUTURE = "future"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderIntent(str, Enum):
    PASSIVE = "passive"
    AGGRESSIVE = "aggressive"


class ExecutionState(str, Enum):
    IDLE = "IDLE"
    PASSIVE_POSTING = "PASSIVE_POSTING"
    CROSS_SPREAD_FILL = "CROSS_SPREAD_FILL"
    ADVERSE_SELECTION_HALT = "ADVERSE_SELECTION_HALT"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


@dataclass(frozen=True)
class FeeBreakdown:
    exchange_and_ipft: float
    sebi: float
    stt: float
    stamp_duty: float
    brokerage: float
    gst: float

    @property
    def total(self) -> float:
        return sum((self.exchange_and_ipft, self.sebi, self.stt,
                    self.stamp_duty, self.brokerage, self.gst))


@dataclass(frozen=True)
class NSEFeeModel:
    """Effective-dated fee schedule reference for the 2026-10-17 baseline.

    Turnover is premium turnover for options and futures notional for futures.
    GST base intentionally excludes STT and stamp duty.
    """
    exchange_fee_effective_date: str = "2026-03-01"
    stt_effective_date: str = "2026-04-01"
    options_exchange_ipft_per_crore: float = 3553.0
    futures_exchange_ipft_per_crore: float = 183.0
    sebi_per_crore: float = 10.0
    option_sell_stt_rate: float = 0.0015
    future_sell_stt_rate: float = 0.0005
    option_buy_stamp_rate: float = 0.00003
    future_buy_stamp_rate: float = 0.00002
    gst_rate: float = 0.18

    def calculate(
        self,
        product: Product | str,
        side: Side | str,
        price: float,
        quantity_contracts: int,
        lot_size: int = 1,
        brokerage: float = 0.0,
    ) -> FeeBreakdown:
        product, side = Product(product), Side(side)
        if not math.isfinite(price) or price < 0:
            raise ValueError("price must be finite and non-negative")
        if quantity_contracts < 0 or lot_size <= 0:
            raise ValueError("quantity must be non-negative and lot_size positive")
        if not math.isfinite(brokerage) or brokerage < 0:
            raise ValueError("brokerage must be finite and non-negative")

        turnover = price * quantity_contracts * lot_size
        exchange_rate = (
            self.options_exchange_ipft_per_crore
            if product is Product.OPTION
            else self.futures_exchange_ipft_per_crore
        ) / RUPEES_PER_CRORE
        exchange = turnover * exchange_rate
        sebi = turnover * (self.sebi_per_crore / RUPEES_PER_CRORE)

        stt_rate = (
            self.option_sell_stt_rate
            if product is Product.OPTION
            else self.future_sell_stt_rate
        )
        stt = turnover * stt_rate if side is Side.SELL else 0.0

        stamp_rate = (
            self.option_buy_stamp_rate
            if product is Product.OPTION
            else self.future_buy_stamp_rate
        )
        stamp = turnover * stamp_rate if side is Side.BUY else 0.0

        gst = self.gst_rate * (exchange + sebi + brokerage)
        return FeeBreakdown(exchange, sebi, stt, stamp, brokerage, gst)


def quantize_limit_price(
    price: float,
    tick_size: float,
    side: Side | str,
    intent: OrderIntent | str,
) -> float:
    """Round to tick grid: passive avoids crossing; aggressive rounds marketable."""
    side, intent = Side(side), OrderIntent(intent)
    if not math.isfinite(price) or price < 0:
        raise ValueError("price must be finite and non-negative")
    if not math.isfinite(tick_size) or tick_size <= 0:
        raise ValueError("tick_size must be finite and positive")
    p, tick = Decimal(str(price)), Decimal(str(tick_size))
    units = p / tick
    if (side is Side.BUY and intent is OrderIntent.PASSIVE) or (
        side is Side.SELL and intent is OrderIntent.AGGRESSIVE
    ):
        rounded = units.to_integral_value(rounding=ROUND_FLOOR)
    else:
        rounded = units.to_integral_value(rounding=ROUND_CEILING)
    return float(rounded * tick)


@dataclass(frozen=True)
class TransientImpactKernel:
    """Multi-exponential propagator G(u) = sum gamma_k exp(-rho_k u)."""
    gammas: Tuple[float, ...]
    rhos: Tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.gammas or len(self.gammas) != len(self.rhos):
            raise ValueError("gammas and rhos must be non-empty and same length")
        if any(not math.isfinite(g) or g < 0 for g in self.gammas):
            raise ValueError("gammas must be finite and non-negative")
        if any(not math.isfinite(r) or r <= 0 for r in self.rhos):
            raise ValueError("rhos must be finite and positive")

    def _check_state(self, state: Sequence[float]) -> Tuple[float, ...]:
        z = tuple(float(v) for v in state)
        if len(z) != len(self.gammas):
            raise ValueError("impact state length must match kernel")
        if any(not math.isfinite(v) or v < 0 for v in z):
            raise ValueError("impact state must be finite and non-negative")
        return z

    def decay(self, state: Sequence[float], dt: float) -> Tuple[float, ...]:
        z = self._check_state(state)
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and non-negative")
        return tuple(v * math.exp(-r * dt) for v, r in zip(z, self.rhos))

    def advance(self, state: Sequence[float], rate: float, dt: float) -> Tuple[float, ...]:
        """Exact state update for constant non-negative rate over [t, t+dt]."""
        z = self._check_state(state)
        if not math.isfinite(rate) or rate < 0:
            raise ValueError("rate must be finite and non-negative")
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and non-negative")
        out = []
        for old, gamma, rho in zip(z, self.gammas, self.rhos):
            decay = math.exp(-rho * dt)
            added = gamma * rate * (-math.expm1(-rho * dt)) / rho
            out.append(old * decay + added)
        return tuple(out)

    def integrated_cost(self, rate: float, state: Sequence[float], dt: float) -> float:
        """Integral rate*z(t) dt with constant rate and exact exponential decay."""
        z = self._check_state(state)
        if not math.isfinite(rate) or rate < 0:
            raise ValueError("rate must be finite and non-negative")
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and non-negative")
        total = 0.0
        for old, gamma, rho in zip(z, self.gammas, self.rhos):
            area = -math.expm1(-rho * dt) / rho
            prior_impact_cost = rate * old * area
            self_impact_cost = (gamma * rate * rate / rho) * (dt - area)
            total += prior_impact_cost + self_impact_cost
        return total


def square_root_impact_per_unit(Y: float, sigma_price: float, participation: float) -> float:
    """Impact concession Y*sigma*sqrt(u/V)."""
    if not math.isfinite(Y) or Y < 0:
        raise ValueError("Y must be finite and non-negative")
    if not math.isfinite(sigma_price) or sigma_price < 0:
        raise ValueError("sigma_price must be finite and non-negative")
    if not math.isfinite(participation) or participation < 0:
        raise ValueError("participation must be finite and non-negative")
    return Y * sigma_price * math.sqrt(participation)


def almgren_chriss_inventory_schedule(
    quantity: float,
    horizon: float,
    intervals: int,
    temporary_impact_eta: float,
    risk_aversion: float,
    volatility: float,
) -> Tuple[float, ...]:
    """Continuous-time AC baseline inventory x(t), sampled at interval edges."""
    vals = (quantity, horizon, temporary_impact_eta, risk_aversion, volatility)
    if any(not math.isfinite(v) for v in vals):
        raise ValueError("all numeric inputs must be finite")
    if quantity < 0 or horizon <= 0 or intervals <= 0 or temporary_impact_eta <= 0:
        raise ValueError("invalid quantity/horizon/intervals/impact eta")
    if risk_aversion < 0 or volatility < 0:
        raise ValueError("risk_aversion and volatility must be non-negative")
    kappa = math.sqrt(risk_aversion * volatility * volatility / temporary_impact_eta)
    times = [horizon * i / intervals for i in range(intervals + 1)]
    if kappa * horizon < 1e-7:
        return tuple(quantity * (1.0 - t / horizon) for t in times[:-1]) + (0.0,)
    denom = math.sinh(kappa * horizon)
    inv = [quantity * math.sinh(kappa * (horizon - t)) / denom for t in times]
    inv[0], inv[-1] = quantity, 0.0
    return tuple(max(0.0, float(x)) for x in inv)


@dataclass(frozen=True)
class SliceDecision:
    target_participation: float
    target_rate: float
    aggression: float  # [0, 1]
    posture: str       # PASSIVE, CROSS_CANDIDATE, or HALT
    hazard_ratio: float
    aligned_ofi: float


def conditioned_slice_policy(
    *,
    base_participation: float,
    max_participation: float,
    market_volume_rate: float,
    hawkes_intensity: float,
    hawkes_baseline: float,
    normalized_ofi: float,
    parent_side: int,
    urgency: float = 1.0,
    base_aggression: float = 0.25,
    pace_ofi_gain: float = 0.6,
    pace_hazard_gain: float = 0.8,
    aggression_ofi_gain: float = 0.6,
    aggression_hazard_gain: float = 0.9,
    halt_hazard_ratio: float = 4.0,
    halt_aligned_ofi: float = 0.95,
    cross_candidate_threshold: float = 0.6,
) -> SliceDecision:
    """Hawkes/NOFI-conditioned schedule and aggression recommendation."""
    scalars = [base_participation, max_participation, market_volume_rate,
               hawkes_intensity, hawkes_baseline, normalized_ofi, urgency,
               base_aggression, pace_ofi_gain, pace_hazard_gain,
               aggression_ofi_gain, aggression_hazard_gain, halt_hazard_ratio,
               halt_aligned_ofi, cross_candidate_threshold]
    if any(not math.isfinite(v) for v in scalars):
        raise ValueError("all numeric inputs must be finite")
    if parent_side not in (-1, 1):
        raise ValueError("parent_side must be +1 (buy) or -1 (sell)")
    if base_participation < 0 or max_participation <= 0 or base_participation > max_participation:
        raise ValueError("invalid participation bounds")
    if market_volume_rate <= 0 or hawkes_intensity < 0 or hawkes_baseline <= 0:
        raise ValueError("volume rate must be positive; intensities must be valid")
    if urgency < 0 or not 0 <= base_aggression <= 1:
        raise ValueError("urgency must be non-negative and aggression in [0,1]")
    if min(pace_ofi_gain, pace_hazard_gain, aggression_ofi_gain, aggression_hazard_gain) < 0:
        raise ValueError("policy gains must be non-negative")
    if halt_hazard_ratio <= 1 or not -1 <= normalized_ofi <= 1:
        raise ValueError("invalid hazard threshold or normalized OFI")

    aligned = max(-1.0, min(1.0, parent_side * normalized_ofi))
    hazard_ratio = hawkes_intensity / hawkes_baseline
    hazard_excess = max(0.0, hazard_ratio - 1.0)
    urgency = min(3.0, urgency)

    pace_multiplier = (
        urgency * math.exp(pace_ofi_gain * aligned)
        / (1.0 + pace_hazard_gain * hazard_excess)
    )
    target_participation = min(max_participation, base_participation * pace_multiplier)
    target_rate = target_participation * market_volume_rate

    aggression = base_aggression
    aggression *= math.exp(-aggression_hazard_gain * hazard_excess)
    aggression *= max(0.0, 1.0 - aggression_ofi_gain * max(0.0, aligned))
    aggression = max(0.0, min(1.0, aggression))

    if hazard_ratio >= halt_hazard_ratio or aligned >= halt_aligned_ofi:
        posture, aggression = "HALT", 0.0
    elif aggression >= cross_candidate_threshold:
        posture = "CROSS_CANDIDATE"
    else:
        posture = "PASSIVE"
    return SliceDecision(target_participation, target_rate, aggression, posture,
                          hazard_ratio, aligned)


@dataclass(frozen=True)
class StateContext:
    remaining_lots: int
    market_data_valid: bool = True
    jump_hazard_ratio: float = 1.0
    aligned_ofi: float = 0.0
    cross_cost_justified: bool = False
    hard_risk_breach: bool = False
    cooldown_clear: bool = False
    manual_recovery_ack: bool = False
    order_in_flight: bool = False


class ExecutionStateMachine:
    """Pure state machine; never places/cancels/replaces live orders."""
    def __init__(self, *, hazard_halt_ratio: float = 4.0,
                 aligned_ofi_halt: float = 0.95,
                 cross_hazard_max: float = 2.0) -> None:
        if hazard_halt_ratio <= 1 or cross_hazard_max <= 0 or aligned_ofi_halt <= 0:
            raise ValueError("invalid state-machine thresholds")
        self.state = ExecutionState.IDLE
        self.hazard_halt_ratio = hazard_halt_ratio
        self.aligned_ofi_halt = aligned_ofi_halt
        self.cross_hazard_max = cross_hazard_max

    def update(self, c: StateContext) -> ExecutionState:
        if c.remaining_lots < 0:
            raise ValueError("remaining_lots must be non-negative")
        if not math.isfinite(c.jump_hazard_ratio) or c.jump_hazard_ratio < 0:
            raise ValueError("jump_hazard_ratio must be finite and non-negative")
        if not math.isfinite(c.aligned_ofi) or not -1 <= c.aligned_ofi <= 1:
            raise ValueError("aligned_ofi must be in [-1,1]")

        if c.hard_risk_breach:
            self.state = ExecutionState.EMERGENCY_UNWIND
            return self.state
        if self.state is ExecutionState.EMERGENCY_UNWIND:
            if c.manual_recovery_ack and c.market_data_valid:
                self.state = ExecutionState.IDLE
            return self.state

        if not c.market_data_valid:
            self.state = ExecutionState.ADVERSE_SELECTION_HALT
            return self.state
        if self.state is ExecutionState.ADVERSE_SELECTION_HALT:
            if (c.cooldown_clear
                and c.jump_hazard_ratio < self.hazard_halt_ratio
                and abs(c.aligned_ofi) < self.aligned_ofi_halt):
                self.state = (ExecutionState.PASSIVE_POSTING if c.remaining_lots > 0
                              else ExecutionState.IDLE)
            return self.state

        if c.remaining_lots == 0:
            self.state = ExecutionState.IDLE
            return self.state

        if c.jump_hazard_ratio >= self.hazard_halt_ratio or abs(c.aligned_ofi) >= self.aligned_ofi_halt:
            self.state = ExecutionState.ADVERSE_SELECTION_HALT
            return self.state

        if c.order_in_flight:
            if self.state is ExecutionState.IDLE:
                self.state = ExecutionState.PASSIVE_POSTING
            return self.state

        if self.state in (ExecutionState.IDLE, ExecutionState.CROSS_SPREAD_FILL):
            self.state = ExecutionState.PASSIVE_POSTING
        elif self.state is ExecutionState.PASSIVE_POSTING:
            if (c.cross_cost_justified
                and c.jump_hazard_ratio < self.cross_hazard_max):
                self.state = ExecutionState.CROSS_SPREAD_FILL
        return self.state


@dataclass(frozen=True)
class MockFill:
    requested_lots: int
    filled_lots: int
    remaining_lots: int
    mode: str


class DeterministicMockFillSimulator:
    """Deterministic fill simulator; no network or broker code."""
    def __init__(self, passive_fill_fraction: float = 0.5) -> None:
        if not math.isfinite(passive_fill_fraction) or not 0 <= passive_fill_fraction <= 1:
            raise ValueError("passive_fill_fraction must be in [0,1]")
        self.passive_fill_fraction = passive_fill_fraction

    def fill(self, requested_lots: int, available_lots: int, mode: str) -> MockFill:
        if requested_lots < 0 or available_lots < 0:
            raise ValueError("lot quantities must be non-negative")
        if mode not in ("PASSIVE_POSTING", "CROSS_SPREAD_FILL"):
            raise ValueError("mode must be PASSIVE_POSTING or CROSS_SPREAD_FILL")
        if mode == "PASSIVE_POSTING":
            target = int(math.floor(requested_lots * self.passive_fill_fraction))
        else:
            target = requested_lots
        filled = min(requested_lots, available_lots, target)
        return MockFill(requested_lots, filled, requested_lots - filled, mode)


def dispatch_live_order(*_args, **_kwargs):
    """Intentionally unavailable: fail closed even if a caller attempts dispatch."""
    if not LIVE_ORDER_DISPATCH_ENABLED:
        raise RuntimeError("Live order dispatch is disabled in Cycle 17 reference package")
    raise RuntimeError("No broker adapter is implemented in this package")


@dataclass(frozen=True)
class ScheduleResult:
    cost: float
    lots_per_step: Tuple[int, ...]
    terminal_inventory_lots: int


def optimize_discrete_schedule(
    *,
    total_lots: int,
    steps: int,
    max_lots_per_step: int,
    lot_size: int,
    dt: float,
    market_volume_rate: float,
    half_spread_ticks: float,
    tick_size: float,
    kernel: TransientImpactKernel,
    initial_impact_state: Sequence[float] | None = None,
    Y: float = 0.0,
    sigma_price: float = 0.0,
    inventory_risk_aversion: float = 0.0,
    return_volatility: float = 0.0,
    fee_cost_by_lots: Mapping[int, float] | None = None,
    impact_state_quantum: float = 0.01,
) -> ScheduleResult:
    """Small finite-horizon DP over whole lots and quantized impact-state."""
    if total_lots < 0 or steps <= 0 or max_lots_per_step <= 0 or lot_size <= 0:
        raise ValueError("invalid lot/step bounds")
    nums = [dt, market_volume_rate, half_spread_ticks, tick_size, Y, sigma_price,
            inventory_risk_aversion, return_volatility, impact_state_quantum]
    if any(not math.isfinite(v) for v in nums):
        raise ValueError("all numeric parameters must be finite")
    if dt <= 0 or market_volume_rate <= 0 or half_spread_ticks < 0 or tick_size <= 0:
        raise ValueError("invalid time/volume/spread/tick inputs")
    if Y < 0 or sigma_price < 0 or inventory_risk_aversion < 0 or return_volatility < 0:
        raise ValueError("impact and risk parameters must be non-negative")
    if impact_state_quantum <= 0:
        raise ValueError("impact_state_quantum must be positive")
    fees = dict(fee_cost_by_lots or {0: 0.0})
    fees.setdefault(0, 0.0)
    if any(q < 0 or not math.isfinite(v) or v < 0 for q, v in fees.items()):
        raise ValueError("fee mapping must contain finite non-negative costs")
    state0 = tuple(initial_impact_state or (0.0,) * len(kernel.gammas))
    state0 = kernel._check_state(state0)

    def to_grid(values: Sequence[float]) -> Tuple[int, ...]:
        return tuple(int(round(v / impact_state_quantum)) for v in values)

    def from_grid(keys: Tuple[int, ...]) -> Tuple[float, ...]:
        return tuple(k * impact_state_quantum for k in keys)

    @lru_cache(maxsize=None)
    def bellman(step: int, remaining: int, impact_key: Tuple[int, ...]):
        if step == steps:
            return (0.0, ()) if remaining == 0 else (math.inf, ())
        remaining_steps = steps - step
        if remaining > remaining_steps * max_lots_per_step:
            return math.inf, ()
        impact_state = from_grid(impact_key)
        best_cost, best_actions = math.inf, ()
        min_trade = max(0, remaining - (remaining_steps - 1) * max_lots_per_step)
        max_trade = min(max_lots_per_step, remaining)
        for q_lots in range(min_trade, max_trade + 1):
            if q_lots not in fees:
                continue
            shares = q_lots * lot_size
            rate = shares / dt
            transient = kernel.integrated_cost(rate, impact_state, dt)
            next_state_raw = kernel.advance(impact_state, rate, dt)
            next_key = to_grid(next_state_raw)
            participation = rate / market_volume_rate
            perm_per_unit = square_root_impact_per_unit(Y, sigma_price, participation)
            spread_cost = shares * half_spread_ticks * tick_size
            impact_cost = transient + shares * perm_per_unit
            remaining_after = remaining - q_lots
            inventory_cost = (inventory_risk_aversion * return_volatility**2
                              * (remaining_after * lot_size)**2 * dt)
            immediate = spread_cost + impact_cost + fees[q_lots] + inventory_cost
            future_cost, future_actions = bellman(step + 1, remaining_after, next_key)
            total = immediate + future_cost
            if total < best_cost:
                best_cost = total
                best_actions = (q_lots,) + future_actions
        return best_cost, best_actions

    start_key = to_grid(state0)
    cost, actions = bellman(0, total_lots, start_key)
    if not math.isfinite(cost) or len(actions) != steps or sum(actions) != total_lots:
        raise ValueError("No feasible schedule satisfies capacity and terminal inventory=0")
    return ScheduleResult(float(cost), tuple(actions), total_lots - sum(actions))
