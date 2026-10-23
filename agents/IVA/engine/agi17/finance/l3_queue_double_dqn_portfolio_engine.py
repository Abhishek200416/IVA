"""Cycle 32 offline research engine: L3 queue dynamics, Double-DQN market making,
portfolio allocation under asymmetric Indian options transaction costs, and telemetry.

This module deliberately does not include a broker adapter or live order path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import random
import threading
import time
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlparse

LIVE_ORDER_DISPATCH_ENABLED = False
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
ACTION_OFFSETS: tuple[int, ...] = (-2, -1, 0, 1, 2)
STATE_DIM = 6
EPSILON = 1e-12


def _finite(value: float, name: str) -> float:
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _finite_vector(values: Sequence[float], name: str, expected: Optional[int] = None) -> list[float]:
    out = [_finite(x, name) for x in values]
    if expected is not None and len(out) != expected:
        raise ValueError(f"{name} must have length {expected}")
    return out


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("dot-product dimension mismatch")
    return sum(x * y for x, y in zip(a, b))


def _matvec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    if any(len(row) != len(vector) for row in matrix):
        raise ValueError("matrix/vector dimension mismatch")
    return [_dot(row, vector) for row in matrix]


def _matrix(values: Sequence[Sequence[float]], name: str) -> list[list[float]]:
    rows = [_finite_vector(row, name) for row in values]
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError(f"{name} must be a non-empty rectangular matrix")
    return rows


def _symmetric_psd_eigenvalues(matrix: Sequence[Sequence[float]], name: str, tol: float = 1e-9) -> list[float]:
    """Validate symmetry and estimate eigenvalues with Jacobi rotations (small matrices)."""
    a = _matrix(matrix, name)
    n = len(a)
    if any(len(row) != n for row in a):
        raise ValueError(f"{name} must be square")
    for i in range(n):
        for j in range(i + 1, n):
            if abs(a[i][j] - a[j][i]) > 1e-8:
                raise ValueError(f"{name} must be symmetric")
            v = 0.5 * (a[i][j] + a[j][i])
            a[i][j] = a[j][i] = v
    for _ in range(max(1, 50 * n * n)):
        p, q, largest = 0, 0, 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > largest:
                    p, q, largest = i, j, abs(a[i][j])
        if largest < tol:
            break
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        angle = 0.5 * math.atan2(2.0 * apq, aqq - app)
        c, s = math.cos(angle), math.sin(angle)
        for k in range(n):
            if k != p and k != q:
                akp, akq = a[k][p], a[k][q]
                a[k][p] = a[p][k] = c * akp - s * akq
                a[k][q] = a[q][k] = s * akp + c * akq
        a[p][p] = c*c*app - 2*s*c*apq + s*s*aqq
        a[q][q] = s*s*app + 2*s*c*apq + c*c*aqq
        a[p][q] = a[q][p] = 0.0
    eigenvalues = [a[i][i] for i in range(n)]
    if min(eigenvalues) < -1e-8:
        raise ValueError(f"{name} must be positive semidefinite")
    return eigenvalues


class QueueSide(str, Enum):
    BID = "BID"
    ASK = "ASK"


class QueueEventType(str, Enum):
    CANCEL_AHEAD = "CANCEL_AHEAD"
    TRADE_AHEAD = "TRADE_AHEAD"
    CANCEL_BEHIND = "CANCEL_BEHIND"
    TRADE_BEHIND = "TRADE_BEHIND"
    ADD_AHEAD = "ADD_AHEAD"
    ADD_BEHIND = "ADD_BEHIND"


@dataclass
class QueueState:
    instrument: str
    side: QueueSide
    price: float
    quantity_ahead: float
    quantity_behind: float
    created_at: float
    updated_at: float
    events: int = 0
    cumulative_ahead_depletion: float = 0.0
    priority_reached: bool = False

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("instrument cannot be empty")
        self.price = _finite(self.price, "price")
        self.quantity_ahead = _finite(self.quantity_ahead, "quantity_ahead")
        self.quantity_behind = _finite(self.quantity_behind, "quantity_behind")
        self.created_at = _finite(self.created_at, "created_at")
        self.updated_at = _finite(self.updated_at, "updated_at")
        if self.price <= 0 or self.quantity_ahead < 0 or self.quantity_behind < 0:
            raise ValueError("price must be positive and queue quantities nonnegative")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.quantity_ahead == 0:
            self.priority_reached = True

    @property
    def age_seconds(self) -> float:
        return max(0.0, self.updated_at - self.created_at)

    @property
    def queue_ahead_ratio(self) -> float:
        total = self.quantity_ahead + self.quantity_behind
        return self.quantity_ahead / total if total > 0 else 0.0


@dataclass(frozen=True)
class QueueEstimate:
    fill_probability: float
    adverse_selection_probability: float
    depletion_velocity: float
    expected_fill_latency_seconds: Optional[float]
    survival_probability: float
    reposition_recommended: bool
    reposition_hurdle: float


class L3QueueTracker:
    """Explicit ahead/behind MBO queue accounting plus simple probabilistic estimates.

    An event must identify whether displayed quantity is ahead of or behind this quote.
    Real exchange priority requires exact venue message sequencing and order identifiers;
    this state object is an offline estimator, not a certified exchange simulator.
    """
    def __init__(self, mu_cancel: float = 1.0, lambda_trade: float = 1.0,
                 hawkes_threshold: float = 1.0, epsilon: float = 1e-9,
                 adverse_sensitivity: float = 1.5) -> None:
        self.mu_cancel = _finite(mu_cancel, "mu_cancel")
        self.lambda_trade = _finite(lambda_trade, "lambda_trade")
        self.hawkes_threshold = _finite(hawkes_threshold, "hawkes_threshold")
        self.epsilon = _finite(epsilon, "epsilon")
        self.adverse_sensitivity = _finite(adverse_sensitivity, "adverse_sensitivity")
        if min(self.mu_cancel, self.lambda_trade, self.hawkes_threshold, self.epsilon, self.adverse_sensitivity) < 0 or self.epsilon == 0:
            raise ValueError("queue rate/sensitivity parameters must be nonnegative and epsilon positive")
        self.queues: dict[tuple[str, QueueSide, float], QueueState] = {}

    @staticmethod
    def _side(side: QueueSide | str) -> QueueSide:
        try:
            return side if isinstance(side, QueueSide) else QueueSide(str(side).upper())
        except ValueError as exc:
            raise ValueError("side must be BID or ASK") from exc

    def place_quote(self, instrument: str, side: QueueSide | str, price: float,
                    quantity_ahead: float, quantity_behind: float, now: float) -> QueueState:
        parsed_side = self._side(side)
        state = QueueState(instrument, parsed_side, price, quantity_ahead, quantity_behind, now, now)
        key = (state.instrument, state.side, state.price)
        self.queues[key] = state
        return state

    def get_queue(self, instrument: str, side: QueueSide | str, price: float) -> QueueState:
        key = (instrument, self._side(side), _finite(price, "price"))
        if key not in self.queues:
            raise KeyError(f"unknown queue: {key}")
        return self.queues[key]

    def apply_event(self, instrument: str, side: QueueSide | str, price: float,
                    event_type: QueueEventType | str, quantity: float, now: float) -> QueueState:
        state = self.get_queue(instrument, side, price)
        try:
            event = event_type if isinstance(event_type, QueueEventType) else QueueEventType(str(event_type).upper())
        except ValueError as exc:
            raise ValueError("unsupported queue event type") from exc
        qty = _finite(quantity, "quantity")
        ts = _finite(now, "now")
        if qty < 0 or ts < state.updated_at:
            raise ValueError("event quantity must be nonnegative and timestamps monotonic")
        if state.priority_reached and event is QueueEventType.ADD_AHEAD and qty > 0:
            raise ValueError("new FIFO orders at this price cannot jump ahead of an existing quote")
        if event in (QueueEventType.CANCEL_AHEAD, QueueEventType.TRADE_AHEAD):
            applied = min(qty, state.quantity_ahead)
            state.quantity_ahead -= applied
            state.cumulative_ahead_depletion += applied
        elif event in (QueueEventType.CANCEL_BEHIND, QueueEventType.TRADE_BEHIND):
            state.quantity_behind = max(0.0, state.quantity_behind - qty)
        elif event is QueueEventType.ADD_AHEAD:
            state.quantity_ahead += qty
        elif event is QueueEventType.ADD_BEHIND:
            state.quantity_behind += qty
        state.updated_at = ts
        state.events += 1
        if state.quantity_ahead <= self.epsilon:
            state.quantity_ahead = 0.0
            state.priority_reached = True
        return state

    def depletion_velocity(self, hawkes_intensity: float) -> float:
        intensity = _finite(hawkes_intensity, "hawkes_intensity")
        if intensity < 0:
            raise ValueError("hawkes_intensity cannot be negative")
        indicator = 1.0 if intensity > self.hawkes_threshold else 0.0
        return self.mu_cancel + self.lambda_trade * indicator

    def adverse_selection_probability(self, side: QueueSide | str, ofi: float,
                                      cross_asset_spillover: float = 0.0) -> float:
        parsed = self._side(side)
        flow = _finite(ofi, "ofi") + _finite(cross_asset_spillover, "cross_asset_spillover")
        side_sign = 1.0 if parsed is QueueSide.BID else -1.0
        z = max(-60.0, min(60.0, self.adverse_sensitivity * (-side_sign * flow)))
        return 1.0 / (1.0 + math.exp(-z))

    def estimate(self, instrument: str, side: QueueSide | str, price: float,
                 tau: float, hawkes_intensity: float, ofi: float,
                 cross_asset_spillover: float = 0.0, expected_edge: float = 0.0,
                 friction_hurdle: float = 0.0, reposition_cost: float = 0.0) -> QueueEstimate:
        state = self.get_queue(instrument, side, price)
        horizon = _finite(tau, "tau")
        if horizon <= 0:
            raise ValueError("tau must be positive")
        velocity = self.depletion_velocity(hawkes_intensity)
        adverse = self.adverse_selection_probability(side, ofi, cross_asset_spillover)
        denom = velocity * horizon + self.epsilon
        fill = math.exp(-state.quantity_ahead / denom) * (1.0 - adverse)
        fill = min(1.0, max(0.0, fill))
        latency = state.quantity_ahead / velocity if velocity > 0 else None
        survival = math.exp(-velocity * horizon / max(state.quantity_ahead, self.epsilon))
        hurdle = _finite(friction_hurdle, "friction_hurdle") + _finite(reposition_cost, "reposition_cost")
        net_value = fill * _finite(expected_edge, "expected_edge")
        reposition = net_value < hurdle
        return QueueEstimate(fill, adverse, velocity, latency, min(1.0, max(0.0, survival)), reposition, hurdle)

    def snapshot(self) -> list[dict[str, Any]]:
        return [{"instrument": q.instrument, "side": q.side.value, "price": q.price,
                 "quantity_ahead": q.quantity_ahead, "quantity_behind": q.quantity_behind,
                 "age_seconds": q.age_seconds, "events": q.events, "priority_reached": q.priority_reached,
                 "queue_ahead_ratio": q.queue_ahead_ratio}
                for q in sorted(self.queues.values(), key=lambda item: (item.instrument, item.side.value, item.price))]


@dataclass(frozen=True)
class Experience:
    state: tuple[float, ...]
    action_index: int
    reward: float
    next_state: tuple[float, ...]
    done: bool


class ReplayBuffer:
    def __init__(self, capacity: int = 10_000, seed: int = 7) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = int(capacity)
        self._data: list[Experience] = []
        self._position = 0
        self.rng = random.Random(seed)

    def __len__(self) -> int:
        return len(self._data)

    def add(self, experience: Experience) -> None:
        if len(self._data) < self.capacity:
            self._data.append(experience)
        else:
            self._data[self._position] = experience
        self._position = (self._position + 1) % self.capacity

    def sample(self, batch_size: int) -> list[Experience]:
        if batch_size < 1 or batch_size > len(self._data):
            raise ValueError("batch_size must be between one and replay size")
        return self.rng.sample(self._data, batch_size)

    def all(self) -> tuple[Experience, ...]:
        return tuple(self._data)


@dataclass(frozen=True)
class QuoteParameters:
    reservation_price: float
    theoretical_half_spread: float
    effective_half_spread: float
    bid_price: float
    ask_price: float

    def to_dict(self) -> dict[str, float]:
        return {"reservation_price": self.reservation_price,
                "theoretical_half_spread": self.theoretical_half_spread,
                "effective_half_spread": self.effective_half_spread,
                "bid_price": self.bid_price, "ask_price": self.ask_price}


class AvellanedaStoikovModel:
    """Transparent Avellaneda-Stoikov-Gueant baseline for inventory-aware quotes."""
    @staticmethod
    def calculate(spot: float, inventory: float, risk_aversion: float,
                  volatility: float, liquidity_kappa: float,
                  time_remaining: float, horizon: float = 1.0,
                  minimum_half_spread: float = 0.01) -> QuoteParameters:
        s = _finite(spot, "spot")
        q = _finite(inventory, "inventory")
        gamma = _finite(risk_aversion, "risk_aversion")
        sigma = _finite(volatility, "volatility")
        kappa = _finite(liquidity_kappa, "liquidity_kappa")
        rem = _finite(time_remaining, "time_remaining")
        total = _finite(horizon, "horizon")
        min_half = _finite(minimum_half_spread, "minimum_half_spread")
        if s <= 0 or gamma <= 0 or sigma < 0 or kappa <= 0 or total <= 0 or not 0 <= rem <= total or min_half < 0:
            raise ValueError("invalid Avellaneda-Stoikov quote parameters")
        tau = rem
        reservation = s - q * gamma * sigma * sigma * tau
        ratio = gamma / kappa
        log_base = math.log1p(ratio)
        exponent = (kappa / gamma + 1.0) * log_base
        if exponent > 700:
            raise ValueError("quote half-spread exponent exceeds finite numeric range")
        root_term = math.sqrt(max(0.0, (gamma * sigma * sigma / (2.0 * kappa)) * math.exp(exponent)))
        theoretical = (1.0 / gamma) * log_base + ((2.0 * q + 1.0) / 2.0) * root_term
        # Negative unconstrained spreads are not valid quotes; preserve the theoretical
        # diagnostic and clamp the executable-paper quote to the configured minimum.
        effective = max(min_half, theoretical)
        return QuoteParameters(reservation, theoretical, effective,
                               reservation - effective, reservation + effective)

    @staticmethod
    def apply_offset(quote: QuoteParameters, offset_ticks: int, tick_size: float) -> QuoteParameters:
        if offset_ticks not in ACTION_OFFSETS:
            raise ValueError("offset_ticks must be one of -2,-1,0,1,2")
        tick = _finite(tick_size, "tick_size")
        if tick <= 0:
            raise ValueError("tick_size must be positive")
        shift = offset_ticks * tick
        center = quote.reservation_price + shift
        return QuoteParameters(center, quote.theoretical_half_spread, quote.effective_half_spread,
                               center - quote.effective_half_spread, center + quote.effective_half_spread)


class DoubleDQNAgent:
    """Pure-Python two-layer Double-DQN baseline with deterministic replay/training.

    This is a small reference implementation, not a claim of a trained production policy.
    """
    def __init__(self, state_dim: int = STATE_DIM, hidden_dim: int = 16,
                 gamma: float = 0.99, learning_rate: float = 0.001,
                 replay_capacity: int = 10_000, target_sync_interval: int = 25,
                 seed: int = 7) -> None:
        if state_dim != STATE_DIM or hidden_dim < 1:
            raise ValueError(f"state_dim must be {STATE_DIM} and hidden_dim positive")
        self.state_dim, self.hidden_dim = state_dim, hidden_dim
        self.gamma = _finite(gamma, "gamma")
        self.learning_rate = _finite(learning_rate, "learning_rate")
        if not 0 <= self.gamma <= 1 or self.learning_rate <= 0:
            raise ValueError("gamma must be in [0,1] and learning_rate positive")
        if target_sync_interval < 1:
            raise ValueError("target_sync_interval must be positive")
        self.target_sync_interval = int(target_sync_interval)
        self.rng = random.Random(seed)
        self.replay = ReplayBuffer(replay_capacity, seed + 1)
        self.train_steps = 0
        scale1 = math.sqrt(2.0 / state_dim)
        scale2 = math.sqrt(2.0 / hidden_dim)
        self.w1 = [[self.rng.uniform(-scale1, scale1) for _ in range(state_dim)] for _ in range(hidden_dim)]
        self.b1 = [0.0 for _ in range(hidden_dim)]
        self.w2 = [[self.rng.uniform(-scale2, scale2) for _ in range(hidden_dim)] for _ in ACTION_OFFSETS]
        self.b2 = [0.0 for _ in ACTION_OFFSETS]
        self.sync_target()

    def _state(self, state: Sequence[float]) -> list[float]:
        return _finite_vector(state, "state", self.state_dim)

    def _forward(self, state: Sequence[float], target: bool = False) -> tuple[list[float], list[float]]:
        x = self._state(state)
        w1, b1, w2, b2 = ((self.target_w1, self.target_b1, self.target_w2, self.target_b2)
                           if target else (self.w1, self.b1, self.w2, self.b2))
        hidden = [math.tanh(_dot(row, x) + bias) for row, bias in zip(w1, b1)]
        q = [_dot(row, hidden) + bias for row, bias in zip(w2, b2)]
        return hidden, q

    def q_values(self, state: Sequence[float], target: bool = False) -> tuple[float, ...]:
        return tuple(self._forward(state, target)[1])

    def select_action_index(self, state: Sequence[float]) -> int:
        q = self.q_values(state)
        return max(range(len(q)), key=lambda i: (q[i], -i))

    def choose_action(self, state: Sequence[float], epsilon: float = 0.0) -> int:
        e = _finite(epsilon, "epsilon")
        if not 0 <= e <= 1:
            raise ValueError("epsilon must be in [0,1]")
        if self.rng.random() < e:
            return ACTION_OFFSETS[self.rng.randrange(len(ACTION_OFFSETS))]
        return ACTION_OFFSETS[self.select_action_index(state)]

    def remember(self, state: Sequence[float], action_offset: int, reward: float,
                 next_state: Sequence[float], done: bool = False) -> None:
        if action_offset not in ACTION_OFFSETS:
            raise ValueError("action_offset must be one of -2,-1,0,1,2")
        self.replay.add(Experience(tuple(self._state(state)), ACTION_OFFSETS.index(action_offset),
                                   _finite(reward, "reward"), tuple(self._state(next_state)), bool(done)))

    def bellman_targets(self, batch: Sequence[Experience]) -> tuple[float, ...]:
        targets: list[float] = []
        for item in batch:
            if item.done:
                targets.append(item.reward)
            else:
                online_next = self.q_values(item.next_state, target=False)
                best_action = max(range(len(online_next)), key=lambda i: (online_next[i], -i))
                target_next = self.q_values(item.next_state, target=True)[best_action]
                targets.append(item.reward + self.gamma * target_next)
        return tuple(targets)

    def sync_target(self) -> None:
        self.target_w1 = [row[:] for row in self.w1]
        self.target_b1 = self.b1[:]
        self.target_w2 = [row[:] for row in self.w2]
        self.target_b2 = self.b2[:]

    def train_step(self, batch_size: int = 32) -> dict[str, float]:
        if int(batch_size) < 1:
            raise ValueError("batch_size must be positive")
        if len(self.replay) == 0:
            return {"loss": 0.0, "batch_size": 0.0, "train_steps": float(self.train_steps)}
        n = min(int(batch_size), len(self.replay))
        batch = self.replay.sample(n)
        targets = self.bellman_targets(batch)
        loss_sum = 0.0
        for item, target in zip(batch, targets):
            x = list(item.state)
            hidden, q = self._forward(x)
            idx = item.action_index
            error = q[idx] - target
            abs_error = abs(error)
            loss_sum += 0.5 * error * error if abs_error <= 1.0 else abs_error - 0.5
            grad_q = max(-1.0, min(1.0, error))  # derivative of the Huber loss
            old_w2 = self.w2[idx][:]
            for j in range(self.hidden_dim):
                self.w2[idx][j] -= self.learning_rate * grad_q * hidden[j]
            self.b2[idx] -= self.learning_rate * grad_q
            for j in range(self.hidden_dim):
                grad_hidden = grad_q * old_w2[j] * (1.0 - hidden[j] * hidden[j])
                for k in range(self.state_dim):
                    self.w1[j][k] -= self.learning_rate * grad_hidden * x[k]
                self.b1[j] -= self.learning_rate * grad_hidden
        self.train_steps += 1
        if self.train_steps % self.target_sync_interval == 0:
            self.sync_target()
        return {"loss": loss_sum / n, "batch_size": float(n), "train_steps": float(self.train_steps)}


@dataclass(frozen=True)
class OptionLeg:
    instrument: str
    side: str
    premium: float
    quantity: float
    brokerage: float = 0.0
    half_spread_per_unit: float = 0.0
    impact_per_unit: float = 0.0

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("instrument cannot be empty")
        if self.side.upper() not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        for name in ("premium", "quantity", "brokerage", "half_spread_per_unit", "impact_per_unit"):
            value = _finite(getattr(self, name), name)
            if value < 0:
                raise ValueError(f"{name} must be nonnegative")

    @property
    def turnover(self) -> float:
        return self.premium * self.quantity


@dataclass(frozen=True)
class LegFeeBreakdown:
    instrument: str
    side: str
    turnover: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    stamp_duty: float
    brokerage: float
    half_spread_slippage: float
    impact_cost: float


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
    impact_cost: float
    total_statutory: float
    total_cost: float
    legs: tuple[LegFeeBreakdown, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"total_turnover": self.total_turnover, "buy_turnover": self.buy_turnover,
                "sell_turnover": self.sell_turnover, "stt": self.stt,
                "exchange_fee": self.exchange_fee, "sebi_fee": self.sebi_fee,
                "gst": self.gst, "stamp_duty": self.stamp_duty,
                "brokerage": self.brokerage, "half_spread_slippage": self.half_spread_slippage,
                "impact_cost": self.impact_cost, "total_statutory": self.total_statutory,
                "total_cost": self.total_cost,
                "legs": [leg.__dict__.copy() for leg in self.legs]}


class MultiLegFeeCalculator:
    """Premium-turnover fees; GST is modeled on brokerage + exchange + SEBI charges."""
    STT_SELL_RATE = 0.0015
    STAMP_BUY_RATE = 0.00003
    EXCHANGE_PER_CRORE = 3553.0
    SEBI_PER_CRORE = 10.0
    GST_RATE = 0.18
    RUPEES_PER_CRORE = 10_000_000.0

    def calculate(self, legs: Sequence[OptionLeg]) -> FeeBreakdown:
        if not legs:
            raise ValueError("at least one leg is required")
        all_rows: list[LegFeeBreakdown] = []
        buy_turnover = sell_turnover = brokerage = spread = impact = 0.0
        stt = stamp = 0.0
        for leg in legs:
            side = leg.side.upper()
            t = leg.turnover
            exchange = t * self.EXCHANGE_PER_CRORE / self.RUPEES_PER_CRORE
            sebi = t * self.SEBI_PER_CRORE / self.RUPEES_PER_CRORE
            leg_stt = t * self.STT_SELL_RATE if side == "SELL" else 0.0
            leg_stamp = t * self.STAMP_BUY_RATE if side == "BUY" else 0.0
            leg_spread = leg.half_spread_per_unit * leg.quantity
            leg_impact = leg.impact_per_unit * leg.quantity
            all_rows.append(LegFeeBreakdown(leg.instrument, side, t, leg_stt, exchange, sebi,
                                            leg_stamp, leg.brokerage, leg_spread, leg_impact))
            if side == "BUY":
                buy_turnover += t
            else:
                sell_turnover += t
            stt += leg_stt
            stamp += leg_stamp
            brokerage += leg.brokerage
            spread += leg_spread
            impact += leg_impact
        total_turnover = buy_turnover + sell_turnover
        exchange_total = sum(x.exchange_fee for x in all_rows)
        sebi_total = sum(x.sebi_fee for x in all_rows)
        gst = self.GST_RATE * (exchange_total + sebi_total + brokerage)
        statutory = stt + exchange_total + sebi_total + gst + stamp + brokerage
        total = statutory + spread + impact
        vals = [total_turnover, buy_turnover, sell_turnover, stt, exchange_total, sebi_total,
                gst, stamp, brokerage, spread, impact, statutory, total]
        if any(not math.isfinite(x) or x < -1e-9 for x in vals):
            raise ValueError("fee calculation produced invalid totals")
        return FeeBreakdown(*vals[:3], stt, exchange_total, sebi_total, gst, stamp, brokerage,
                            spread, impact, statutory, total, tuple(all_rows))


@dataclass(frozen=True)
class PortfolioOptimizationResult:
    weights: tuple[float, ...]
    expected_alpha: float
    statutory_and_execution_cost: float
    risk_penalty: float
    impact_penalty: float
    objective: float
    iterations: int


class PortfolioOptimizer:
    """Projected-gradient allocation on a capped simplex with PSD risk/impact matrices."""
    @staticmethod
    def _project_capped_simplex(values: Sequence[float], max_total: float, max_weight: float) -> list[float]:
        if max_total <= 0 or max_weight <= 0:
            return [0.0 for _ in values]
        clipped = [min(max_weight, max(0.0, x)) for x in values]
        if sum(clipped) <= max_total:
            return clipped
        lo = min(values) - max_weight - 1.0
        hi = max(values) + 1.0
        for _ in range(100):
            mid = 0.5 * (lo + hi)
            current = sum(min(max_weight, max(0.0, x - mid)) for x in values)
            if current > max_total:
                lo = mid
            else:
                hi = mid
        return [min(max_weight, max(0.0, x - hi)) for x in values]

    @staticmethod
    def _quadratic(w: Sequence[float], matrix: Sequence[Sequence[float]]) -> float:
        return _dot(w, _matvec(matrix, w))

    def objective(self, weights: Sequence[float], expected_returns: Sequence[float],
                  covariance: Sequence[Sequence[float]], cost_per_unit: Sequence[float],
                  impact_omega: Sequence[Sequence[float]], risk_aversion: float,
                  impact_eta: float) -> float:
        w = _finite_vector(weights, "weights")
        mu = _finite_vector(expected_returns, "expected_returns", len(w))
        costs = _finite_vector(cost_per_unit, "cost_per_unit", len(w))
        cov = _matrix(covariance, "covariance")
        omega = _matrix(impact_omega, "impact_omega")
        if len(cov) != len(w) or len(omega) != len(w) or any(len(r) != len(w) for r in cov + omega):
            raise ValueError("portfolio dimensions mismatch")
        risk = _finite(risk_aversion, "risk_aversion")
        eta = _finite(impact_eta, "impact_eta")
        if risk < 0 or eta < 0 or any(c < 0 for c in costs):
            raise ValueError("risk, impact, and costs must be nonnegative")
        _symmetric_psd_eigenvalues(cov, "covariance")
        _symmetric_psd_eigenvalues(omega, "impact_omega")
        return _dot(w, mu) - 0.5 * risk * self._quadratic(w, cov) - _dot(w, costs) - 0.5 * eta * self._quadratic(w, omega)

    def optimize(self, expected_returns: Sequence[float], covariance: Sequence[Sequence[float]],
                 cost_per_unit: Sequence[float], impact_omega: Sequence[Sequence[float]],
                 risk_aversion: float = 1.0, impact_eta: float = 1.0,
                 iterations: int = 500, step_size: float = 0.05,
                 max_total_weight: float = 1.0, max_weight: float = 1.0) -> PortfolioOptimizationResult:
        mu = _finite_vector(expected_returns, "expected_returns")
        n = len(mu)
        cov = _matrix(covariance, "covariance")
        omega = _matrix(impact_omega, "impact_omega")
        costs = _finite_vector(cost_per_unit, "cost_per_unit", n)
        if n < 1 or len(cov) != n or len(omega) != n or any(len(r) != n for r in cov + omega):
            raise ValueError("portfolio dimensions mismatch")
        if any(c < 0 for c in costs):
            raise ValueError("cost_per_unit must be nonnegative")
        risk = _finite(risk_aversion, "risk_aversion")
        eta = _finite(impact_eta, "impact_eta")
        lr = _finite(step_size, "step_size")
        total_cap = _finite(max_total_weight, "max_total_weight")
        individual_cap = _finite(max_weight, "max_weight")
        if risk < 0 or eta < 0 or lr <= 0 or iterations < 1 or total_cap < 0 or individual_cap < 0:
            raise ValueError("invalid optimization parameter")
        _symmetric_psd_eigenvalues(cov, "covariance")
        _symmetric_psd_eigenvalues(omega, "impact_omega")
        w = [0.0] * n
        used_iterations = 0
        for it in range(iterations):
            grad_risk = _matvec(cov, w)
            grad_impact = _matvec(omega, w)
            grad = [mu[i] - costs[i] - risk * grad_risk[i] - eta * grad_impact[i] for i in range(n)]
            w = self._project_capped_simplex([w[i] + lr * grad[i] for i in range(n)], total_cap, individual_cap)
            used_iterations = it + 1
        alpha = _dot(w, mu)
        statutory_cost = _dot(w, costs)
        risk_penalty = 0.5 * risk * self._quadratic(w, cov)
        impact_penalty = 0.5 * eta * self._quadratic(w, omega)
        obj = alpha - statutory_cost - risk_penalty - impact_penalty
        return PortfolioOptimizationResult(tuple(w), alpha, statutory_cost, risk_penalty,
                                           impact_penalty, obj, used_iterations)


class RiskState(str, Enum):
    IDLE = "IDLE"
    MARKET_MAKER_ACTIVE = "MARKET_MAKER_ACTIVE"
    OVERTRADING_LOCKED = "OVERTRADING_LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class AntiOvertradingThrottler:
    COOLDOWN_SECONDS = 15 * 60
    LOSS_STREAK_LIMIT = 3
    REVENGE_SIZE_RATIO = 1.25
    MIN_FILL_INTERVAL = 30.0

    def __init__(self, alpha: float = 1.0, cost: float = 0.2, risk: float = 0.1,
                 initial_trade_cap: Optional[int] = None) -> None:
        self.alpha = _finite(alpha, "alpha")
        self.cost = _finite(cost, "cost")
        self.risk = _finite(risk, "risk")
        self.trade_cap = self.optimal_trade_cap(self.alpha, self.cost, self.risk)
        if initial_trade_cap is not None:
            if initial_trade_cap < 0:
                raise ValueError("initial_trade_cap cannot be negative")
            self.trade_cap = int(initial_trade_cap)
        self.daily_trade_count = 0
        self._trade_date: Optional[str] = None
        self.loss_streak = 0
        self.last_fill_time: Optional[float] = None
        self.last_fill_size: Optional[float] = None
        self.cooldown_until = 0.0
        self.last_lockout_reason: Optional[str] = None

    @staticmethod
    def optimal_trade_cap(alpha: float, cost: float, risk: float) -> int:
        a, c, r = _finite(alpha, "alpha"), _finite(cost, "cost"), _finite(risk, "risk")
        if r <= 0:
            raise ValueError("risk must be positive")
        return max(0, int(round((a - c) / r)))

    def configure_cap(self, alpha: float, cost: float, risk: float) -> int:
        self.alpha, self.cost, self.risk = map(float, (alpha, cost, risk))
        self.trade_cap = self.optimal_trade_cap(alpha, cost, risk)
        return self.trade_cap

    @staticmethod
    def _date_key(now: float) -> str:
        return datetime.fromtimestamp(now, IST).date().isoformat()

    def _roll_day(self, now: float) -> None:
        day = self._date_key(now)
        if self._trade_date is None:
            self._trade_date = day
        elif day != self._trade_date:
            self._trade_date = day
            self.daily_trade_count = 0

    def lockout(self, now: float, reason: str) -> float:
        ts = _finite(now, "now")
        self.cooldown_until = max(self.cooldown_until, ts + self.COOLDOWN_SECONDS)
        self.last_lockout_reason = str(reason)
        return self.cooldown_until

    def record_fill(self, now: float, pnl: float, size: float) -> Optional[str]:
        ts, profit, quantity = _finite(now, "now"), _finite(pnl, "pnl"), _finite(size, "size")
        if quantity <= 0:
            raise ValueError("fill size must be positive")
        self._roll_day(ts)
        reason: Optional[str] = None
        if self.last_fill_time is not None:
            dt = ts - self.last_fill_time
            if dt < 0:
                raise ValueError("fill timestamps must be monotonic")
            if dt < self.MIN_FILL_INTERVAL:
                reason = "RAPID_FILL_PACING"
        if self.last_fill_size is not None and quantity / self.last_fill_size > self.REVENGE_SIZE_RATIO:
            reason = reason or "REVENGE_SIZING"
        if profit < 0:
            self.loss_streak += 1
        elif profit > 0:
            self.loss_streak = 0
        if self.loss_streak >= self.LOSS_STREAK_LIMIT:
            reason = reason or "LOSS_STREAK"
        self.daily_trade_count += 1
        self.last_fill_time = ts
        self.last_fill_size = quantity
        if reason:
            self.lockout(ts, reason)
        return reason

    def allow_entry(self, now: float, gross_alpha: float, total_cost: float,
                    cross_impact_hurdle: float = 0.0) -> tuple[bool, str, float]:
        ts = _finite(now, "now")
        gross = _finite(gross_alpha, "gross_alpha")
        costs = _finite(total_cost, "total_cost") + _finite(cross_impact_hurdle, "cross_impact_hurdle")
        if costs < 0:
            raise ValueError("total cost hurdle cannot be negative")
        self._roll_day(ts)
        if ts < self.cooldown_until:
            return False, "COOLDOWN", 0.0
        if self.daily_trade_count >= self.trade_cap:
            return False, "DAILY_TRADE_CAP", 0.0
        net = gross - costs
        if not gross > costs:
            return False, "FRICTION_HURDLE", net
        return True, "ALLOWED", net

    def snapshot(self, now: float) -> dict[str, Any]:
        ts = _finite(now, "now")
        return {"trade_cap": self.trade_cap, "daily_trade_count": self.daily_trade_count,
                "loss_streak": self.loss_streak, "cooldown_remaining_seconds": max(0.0, self.cooldown_until - ts),
                "lockout_reason": self.last_lockout_reason}


class Cycle32ExecutionEngine:
    """Offline orchestration facade; all order decisions are plans/telemetry only."""
    def __init__(self, queue_tracker: Optional[L3QueueTracker] = None,
                 dqn_agent: Optional[DoubleDQNAgent] = None,
                 portfolio_optimizer: Optional[PortfolioOptimizer] = None,
                 fee_calculator: Optional[MultiLegFeeCalculator] = None,
                 throttler: Optional[AntiOvertradingThrottler] = None) -> None:
        self.queue_tracker = queue_tracker if queue_tracker is not None else L3QueueTracker()
        self.dqn_agent = dqn_agent if dqn_agent is not None else DoubleDQNAgent()
        self.portfolio_optimizer = portfolio_optimizer if portfolio_optimizer is not None else PortfolioOptimizer()
        self.fee_calculator = fee_calculator if fee_calculator is not None else MultiLegFeeCalculator()
        self.throttler = throttler if throttler is not None else AntiOvertradingThrottler()
        self.avellaneda_stoikov = AvellanedaStoikovModel()
        self.last_quote_plan: Optional[QuoteParameters] = None
        self.state = RiskState.IDLE
        self._emergency_latched = False
        self.last_net_expected_alpha = 0.0
        self.last_action_offset = 0
        self.last_portfolio: Optional[PortfolioOptimizationResult] = None
        self.last_fees: Optional[FeeBreakdown] = None

    def start(self) -> RiskState:
        if self._emergency_latched:
            return self.state
        if self.state is RiskState.IDLE:
            self.state = RiskState.MARKET_MAKER_ACTIVE
        return self.state

    def infer_quote_action(self, state_vector: Sequence[float], epsilon: float = 0.0) -> int:
        if self._emergency_latched:
            raise RuntimeError("emergency latch blocks new quote actions")
        action = self.dqn_agent.choose_action(state_vector, epsilon)
        self.last_action_offset = action
        return action

    def quote_plan(self, state_vector: Sequence[float], *, spot: float, inventory: float,
                   risk_aversion: float, volatility: float, liquidity_kappa: float,
                   time_remaining: float, horizon: float = 1.0, tick_size: float = 0.05,
                   epsilon: float = 0.0) -> QuoteParameters:
        base = self.avellaneda_stoikov.calculate(spot, inventory, risk_aversion, volatility,
                                                 liquidity_kappa, time_remaining, horizon)
        offset = self.infer_quote_action(state_vector, epsilon)
        plan = self.avellaneda_stoikov.apply_offset(base, offset, tick_size)
        self.last_quote_plan = plan
        return plan

    def optimize_portfolio(self, *args: Any, **kwargs: Any) -> PortfolioOptimizationResult:
        if self._emergency_latched:
            raise RuntimeError("emergency latch blocks portfolio allocation")
        result = self.portfolio_optimizer.optimize(*args, **kwargs)
        self.last_portfolio = result
        return result

    def evaluate_entry(self, legs: Sequence[OptionLeg], gross_alpha: float, now: float,
                       cross_impact_hurdle: float = 0.0) -> dict[str, Any]:
        fees = self.fee_calculator.calculate(legs)
        self.last_fees = fees
        if self._emergency_latched:
            allowed, reason, net = False, "EMERGENCY_LATCHED", 0.0
        else:
            allowed, reason, net = self.throttler.allow_entry(now, gross_alpha, fees.total_cost, cross_impact_hurdle)
        self.last_net_expected_alpha = net if allowed else 0.0
        if self.throttler.cooldown_until > now and not self._emergency_latched:
            self.state = RiskState.OVERTRADING_LOCKED
        elif not self._emergency_latched and self.state in (RiskState.IDLE, RiskState.OVERTRADING_LOCKED):
            if self.state is RiskState.OVERTRADING_LOCKED and now < self.throttler.cooldown_until:
                pass
            elif allowed:
                self.state = RiskState.MARKET_MAKER_ACTIVE
        return {"allowed": allowed, "reason": reason, "expected_gross_alpha": _finite(gross_alpha, "gross_alpha"),
                "expected_net_alpha": net if allowed else 0.0, "fees": fees.to_dict(),
                "safety": {"live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                           "paper_only": True, "risk_state": self.state.value}}

    def record_fill(self, now: float, pnl: float, size: float) -> Optional[str]:
        if self._emergency_latched:
            raise RuntimeError("fills cannot be recorded into a latched emergency engine")
        reason = self.throttler.record_fill(now, pnl, size)
        if self.throttler.cooldown_until > now:
            self.state = RiskState.OVERTRADING_LOCKED
        return reason

    def emergency_unwind(self) -> RiskState:
        self._emergency_latched = True
        self.state = RiskState.EMERGENCY_UNWIND
        return self.state

    def recovery_ack(self, verified: bool = False) -> RiskState:
        if not self._emergency_latched:
            return self.state
        if verified is not True:
            raise PermissionError("recovery requires explicit verified=True acknowledgement")
        self._emergency_latched = False
        self.state = RiskState.IDLE
        return self.state

    def telemetry_payload(self, now: Optional[float] = None) -> dict[str, Any]:
        ts = time.time() if now is None else _finite(now, "now")
        stamp = datetime.fromtimestamp(ts, IST)
        payload = {"timestamp_ist": stamp.isoformat(), "epoch_seconds": ts,
                   "queues": self.queue_tracker.snapshot(),
                   "double_dqn": {"last_action_offset_ticks": self.last_action_offset,
                                  "action_space_ticks": list(ACTION_OFFSETS),
                                  "agent_train_steps": self.dqn_agent.train_steps,
                                  "replay_size": len(self.dqn_agent.replay)},
                   "portfolio": None if self.last_portfolio is None else {
                       "weights": list(self.last_portfolio.weights),
                       "expected_alpha": self.last_portfolio.expected_alpha,
                       "cost": self.last_portfolio.statutory_and_execution_cost,
                       "objective": self.last_portfolio.objective},
                   "last_fee_breakdown": None if self.last_fees is None else self.last_fees.to_dict(),
                   "quote_plan": None if self.last_quote_plan is None else self.last_quote_plan.to_dict(),
                   "net_expected_alpha": self.last_net_expected_alpha,
                   "throttler": self.throttler.snapshot(ts),
                   "risk_state": self.state.value,
                   "safety": {"live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                              "paper_only": True, "emergency_latched": self._emergency_latched}}
        # A strict round-trip ensures dashboard payloads remain JSON-safe.
        return json.loads(json.dumps(payload, allow_nan=False))

    @staticmethod
    def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("live order dispatch is permanently disabled; paper simulation only")


class TelemetryEmitter:
    """Thread-safe latest-state emitter used by JSON polling and SSE clients."""
    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._payload: dict[str, Any] = {"status": "starting", "safety": {"live_order_dispatch_enabled": False}}
        self._version = 0

    def publish(self, payload: Mapping[str, Any]) -> int:
        try:
            safe = json.loads(json.dumps(dict(payload), allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("telemetry payload must be JSON serializable and finite") from exc
        with self._lock:
            self._payload = safe
            self._version += 1
            self._lock.notify_all()
            return self._version

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._payload, allow_nan=False))

    def json_text(self) -> str:
        return json.dumps(self.snapshot(), separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    def wait_for_update(self, after_version: int, timeout: float = 1.0) -> tuple[int, dict[str, Any]]:
        with self._lock:
            if self._version <= after_version:
                self._lock.wait(timeout=max(0.0, timeout))
            return self._version, json.loads(json.dumps(self._payload, allow_nan=False))


class TelemetryHTTPServer:
    """Localhost-first threaded JSON/SSE server; no authentication or remote exposure."""
    def __init__(self, emitter: TelemetryEmitter, host: str = "127.0.0.1", port: int = 8088) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("dashboard defaults to loopback only; remote binding is intentionally disabled")
        self.emitter = emitter
        self.host, self.port = host, int(port)
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self._stop = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send_json(self, code: int, body: Mapping[str, Any]) -> None:
                raw = json.dumps(body, separators=(",", ":"), allow_nan=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/health":
                    payload = outer.emitter.snapshot()
                    self._send_json(200, {"ok": True, "risk_state": payload.get("risk_state", "UNKNOWN"),
                                          "live_order_dispatch_enabled": False, "paper_only": True})
                    return
                if path == "/telemetry":
                    self._send_json(200, outer.emitter.snapshot())
                    return
                if path == "/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    version = -1
                    try:
                        # Flush a current snapshot immediately, then stream updates/heartbeats.
                        while not outer._stop.is_set():
                            next_version, payload = outer.emitter.wait_for_update(version, 1.0)
                            if next_version != version:
                                frame = f"event: telemetry\ndata: {json.dumps(payload, separators=(',', ':'), allow_nan=False)}\n\n"
                                version = next_version
                            else:
                                frame = ": heartbeat\n\n"
                            self.wfile.write(frame.encode("utf-8"))
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                    return
                self._send_json(404, {"error": "not found"})

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        self._thread: Optional[threading.Thread] = None

    @property
    def address(self) -> tuple[str, int]:
        return self._httpd.server_address[0], self._httpd.server_address[1]

    def start(self) -> tuple[str, int]:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._httpd.serve_forever, name="cycle32-telemetry", daemon=True)
            self._thread.start()
        return self.address

    def close(self) -> None:
        self._stop.set()
        with self.emitter._lock:
            self.emitter._lock.notify_all()
        if self._thread is not None and self._thread.is_alive():
            self._httpd.shutdown()
            self._thread.join(timeout=2.0)
        self._httpd.server_close()

    def __enter__(self) -> "TelemetryHTTPServer":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
