"""Cycle 20: High-Frequency Cross-Asset Microstructure Equilibrium & Dynamic Order Book Invariance Engine.

Mathematical Foundations:
1. Cross-Impact Tensor Regularization & Manipulation-Free Invariance:
   Given empirical cross-impact matrix G in R^{N x N}:
     Delta P = G * q
   Symmetric PSD regularization:
     G_sym = 0.5 * (G + G^T)
     G_reg = V * max(Lambda, eigen_floor) * V^T
   guarantees path-independent closed-loop manipulation work:
     oint Delta P(q) dq = 0.5 * q^T G_reg q >= 0.

2. Hawkes-Conditioned Queue Depletion & Passive Fill Probability:
   For passive limit orders at level l in {0, ..., 4}:
     rate_t = EWMA(depletion) * (1 + lambda_H * multiplier)
     P(Fill in [0, H]) = 1 - exp(-rate_t * H / (queue_ahead + own_size)).

3. Cross-Inventory Reservation Pricing & Adverse Selection Buffering:
   Reservation price:
     R_t = mid + expected_move - gamma * sigma * q_own - cross_penalty * sigma * beta * q_other
   Optimal bid/ask quotes:
     half_spread = max(tick/2, base_half_spread + gamma * sigma + coeff * sigma * hazard)
     bid = floor((R - half_spread) / tick) * tick
     ask = ceil((R + half_spread) / tick) * tick

4. Latched Fail-Closed 5-State Machine:
   States: IDLE -> BOOK_MONITORING -> QUOTE_SIMULATION | VOLATILITY_SPIKE_HALT | EMERGENCY_UNWIND.
   LIVE_ORDER_DISPATCH_ENABLED = False locked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

LIVE_ORDER_DISPATCH_ENABLED: bool = False


@dataclass(frozen=True)
class ImpactDiagnostics:
    raw_asymmetry_norm: float
    min_eigenvalue_before: float
    min_eigenvalue_after: float
    frobenius_adjustment: float
    symmetry_error_after: float
    psd_after: bool


def regularize_cross_impact_tensor(
    matrix: Sequence[Sequence[float]],
    *,
    eigen_floor: float = 1e-10,
) -> Tuple[np.ndarray, ImpactDiagnostics]:
    """Project real square impact matrix onto symmetric PSD cone to prevent round-trip arbitrage."""
    G = np.asarray(matrix, dtype=float)
    if G.ndim != 2 or G.shape[0] != G.shape[1] or G.shape[0] == 0:
        raise ValueError("impact tensor must be a non-empty square matrix")
    if not np.all(np.isfinite(G)):
        raise ValueError("impact tensor must be finite")
    if eigen_floor < 0 or not math.isfinite(eigen_floor):
        raise ValueError("eigen_floor must be finite and nonnegative")

    sym = 0.5 * (G + G.T)
    asym = float(np.linalg.norm(G - G.T, ord="fro"))
    eigvals, eigvecs = np.linalg.eigh(sym)
    before = float(eigvals.min())
    clipped = np.maximum(eigvals, eigen_floor)
    out = (eigvecs * clipped) @ eigvecs.T
    out = 0.5 * (out + out.T)

    diag = ImpactDiagnostics(
        raw_asymmetry_norm=asym,
        min_eigenvalue_before=before,
        min_eigenvalue_after=float(np.linalg.eigvalsh(out).min()),
        frobenius_adjustment=float(np.linalg.norm(out - G, ord="fro")),
        symmetry_error_after=float(np.linalg.norm(out - out.T, ord="fro")),
        psd_after=bool(np.linalg.eigvalsh(out).min() >= eigen_floor - 1e-8),
    )
    return out, diag


def quadratic_impact_cost(impact_tensor: np.ndarray, signed_flow: Sequence[float]) -> float:
    """Calculate 0.5 * q^T * G * q."""
    G = np.asarray(impact_tensor, dtype=float)
    q = np.asarray(signed_flow, dtype=float).reshape(-1)
    if G.shape != (q.size, q.size):
        raise ValueError("flow dimension must match impact tensor")
    return float(0.5 * q @ G @ q)


@dataclass(frozen=True)
class BookLevel:
    price: float
    displayed_size: float
    order_count: int = 1


@dataclass(frozen=True)
class QueueEstimate:
    level: int
    queue_ahead: float
    queue_behind: float
    depletion_rate: float
    hawkes_intensity: float
    fill_probability: float
    expected_wait_seconds: float


@dataclass
class QueuePriorityTracker:
    """Tracks queue priority and Hawkes-conditioned fill probability for passive limit orders."""
    level: int
    own_size: float
    queue_ahead: float
    queue_behind: float = 0.0
    max_levels: int = 5
    _last_ahead: Optional[float] = None
    _last_time: Optional[float] = None
    depletion_rate: float = 0.0
    ewma_decay: float = 0.8

    def __post_init__(self):
        if not (0 <= self.level < self.max_levels):
            raise ValueError("level must be within tracked top levels")
        if min(self.own_size, self.queue_ahead, self.queue_behind) < 0:
            raise ValueError("queue sizes must be nonnegative")
        if not (0.0 < self.ewma_decay < 1.0):
            raise ValueError("ewma_decay must be between 0 and 1")

    def observe(
        self,
        *,
        timestamp: float,
        queue_ahead: float,
        queue_behind: float,
        traded_volume_at_price: float = 0.0,
    ) -> None:
        vals = [timestamp, queue_ahead, queue_behind, traded_volume_at_price]
        if any(not math.isfinite(v) for v in vals) or min(queue_ahead, queue_behind, traded_volume_at_price) < 0:
            raise ValueError("observation values must be finite and nonnegative")

        if self._last_time is not None:
            dt = timestamp - self._last_time
            if dt <= 0:
                raise ValueError("timestamps must be strictly increasing")
            depletion = max(0.0, (self._last_ahead or 0.0) - queue_ahead) + traded_volume_at_price
            rate = depletion / dt
            self.depletion_rate = self.ewma_decay * self.depletion_rate + (1.0 - self.ewma_decay) * rate

        self._last_time = timestamp
        self._last_ahead = queue_ahead
        self.queue_ahead = queue_ahead
        self.queue_behind = queue_behind

    def estimate(
        self,
        *,
        horizon_seconds: float,
        hawkes_intensity: float,
        hawkes_depletion_multiplier: float = 1.0,
    ) -> QueueEstimate:
        if horizon_seconds < 0 or hawkes_intensity < 0 or hawkes_depletion_multiplier < 0:
            raise ValueError("horizon and intensities must be nonnegative")
        if not all(map(math.isfinite, [horizon_seconds, hawkes_intensity, hawkes_depletion_multiplier])):
            raise ValueError("estimation inputs must be finite")

        rate = self.depletion_rate * (1.0 + hawkes_intensity * hawkes_depletion_multiplier)
        required = self.queue_ahead + self.own_size

        if required <= 0:
            p = 1.0
            wait = 0.0
        elif rate <= 1e-12:
            p = 0.0
            wait = math.inf
        else:
            p = float(np.clip(1.0 - math.exp(-rate * horizon_seconds / required), 0.0, 1.0))
            wait = required / rate

        return QueueEstimate(
            level=self.level,
            queue_ahead=self.queue_ahead,
            queue_behind=self.queue_behind,
            depletion_rate=rate,
            hawkes_intensity=hawkes_intensity,
            fill_probability=p,
            expected_wait_seconds=wait,
        )


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    reservation_price: float
    half_spread: float
    inventory_skew: float
    cross_inventory_penalty: float
    adverse_selection_buffer: float


@dataclass
class InventoryQuoteModel:
    """Calculates non-crossing tick-aligned quotes with cross-asset inventory and hazard adjustments."""
    base_half_spread: float
    risk_aversion: float
    cross_penalty: float
    adverse_selection_coeff: float
    tick_size: float = 0.05

    def quote(
        self,
        *,
        mid: float,
        own_inventory: float,
        other_inventory: float,
        cross_beta: float,
        volatility: float,
        adverse_selection_hazard: float,
        expected_move: float = 0.0,
    ) -> Quote:
        values = [mid, own_inventory, other_inventory, cross_beta, volatility, adverse_selection_hazard, expected_move]
        if any(not math.isfinite(v) for v in values):
            raise ValueError("quote inputs must be finite")
        if mid <= 0 or volatility < 0 or adverse_selection_hazard < 0:
            raise ValueError("mid must be positive and risk inputs nonnegative")
        if min(self.base_half_spread, self.risk_aversion, self.cross_penalty, self.adverse_selection_coeff) < 0 or self.tick_size <= 0:
            raise ValueError("model parameters must be nonnegative; tick positive")

        inv_skew = self.risk_aversion * volatility * own_inventory
        cross = self.cross_penalty * volatility * cross_beta * other_inventory
        reservation = mid + expected_move - inv_skew - cross
        hazard_buffer = self.adverse_selection_coeff * volatility * adverse_selection_hazard
        half = max(self.tick_size / 2.0, self.base_half_spread + hazard_buffer + self.risk_aversion * volatility)

        bid = math.floor((reservation - half) / self.tick_size + 1e-12) * self.tick_size
        ask = math.ceil((reservation + half) / self.tick_size - 1e-12) * self.tick_size
        if bid >= ask:
            ask = bid + self.tick_size

        return Quote(bid, ask, reservation, half, inv_skew, cross, hazard_buffer)


class MicrostructureState(str, Enum):
    IDLE = "IDLE"
    BOOK_MONITORING = "BOOK_MONITORING"
    QUOTE_SIMULATION = "QUOTE_SIMULATION"
    VOLATILITY_SPIKE_HALT = "VOLATILITY_SPIKE_HALT"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class MicrostructureEvent(str, Enum):
    START = "START"
    QUOTE_READY = "QUOTE_READY"
    SPIKE = "SPIKE"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"
    RESET = "RESET"


@dataclass
class Cycle20StateMachine:
    state: MicrostructureState = MicrostructureState.IDLE
    emergency_latched: bool = False
    history: List[Tuple[MicrostructureEvent, MicrostructureState, str]] = field(default_factory=list)

    def transition(self, event: MicrostructureEvent) -> MicrostructureState:
        if self.emergency_latched and event != MicrostructureEvent.RECOVERY_ACK:
            self.history.append((event, self.state, "blocked_latched"))
            return self.state

        if event == MicrostructureEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = MicrostructureState.EMERGENCY_UNWIND
        elif event == MicrostructureEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = MicrostructureState.IDLE
        elif event == MicrostructureEvent.SPIKE:
            self.state = MicrostructureState.VOLATILITY_SPIKE_HALT
        elif event == MicrostructureEvent.START and self.state == MicrostructureState.IDLE:
            self.state = MicrostructureState.BOOK_MONITORING
        elif event == MicrostructureEvent.QUOTE_READY and self.state == MicrostructureState.BOOK_MONITORING:
            self.state = MicrostructureState.QUOTE_SIMULATION
        elif event == MicrostructureEvent.RESET and self.state != MicrostructureState.EMERGENCY_UNWIND:
            self.state = MicrostructureState.IDLE

        self.history.append((event, self.state, "accepted"))
        return self.state


def dispatch_live_order(*args, **kwargs):
    if not LIVE_ORDER_DISPATCH_ENABLED:
        raise RuntimeError("live order dispatch is disabled by invariant")
    raise RuntimeError("no live broker adapter exists in this reference package")
