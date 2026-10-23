"""Cycle 18: Cross-Index Elasticity Cointegration & Joint Greek Hedging Engine.

Mathematical Foundations:
1. Dynamic Cross-Index Elasticity (Kalman Filter):
   log(S_t^B) = a_t + beta_t * log(S_t^N) + epsilon_t, where S^N is NIFTY and S^B is BANKNIFTY.
   State vector b_t = [a_t, beta_t]^T, Observation matrix H_t = [1, log(S_t^N)].
   Joseph-form covariance stabilization:
     P_t = (I - K_t H_t) P_{t|t-1} (I - K_t H_t)^T + K_t R K_t^T.

2. VECM Error-Correction & Hawkes Microstructure Conditioning:
   Speed and entry thresholds adaptively modulated by Hawkes cross-excitation asymmetry D_cross
   and order book depth:
     speed_t = base_speed * exp(gamma_exc * |D_cross|) / (1 + gamma_depth * Depth_norm).
     band_t = base_band * (1 + gamma_exc * |D_cross|) / sqrt(1 + gamma_depth * Depth_norm).

3. Joint Greek Neutrality & Dynamic Hedging:
   Delta_joint = Delta_NIFTY + beta_t * Delta_BANKNIFTY = 0.
   Hedge requirements:
     Delta_hedge^B = -Delta_joint / beta_t
     Delta_hedge^N = -Delta_joint

4. Full-Friction Gamma Rebalance Hurdle:
   Rebalance allowed iff Expected Gamma Gain > Statutory Friction + Execution Impact + Buffer.
   Statutory schedules conform to NSE October 2026 baseline:
     - Options Exchange + IPFT: ₹3,553 / crore of premium turnover.
     - Futures Exchange + IPFT: ₹183 / crore of notional turnover.
     - STT: 0.15% on options sale, 0.05% on futures sale.
     - Stamp Duty: 0.003% on options buy, 0.002% on futures buy.
     - SEBI: ₹10 / crore.
     - GST: 18% on Taxable Services (Brokerage + Exchange Fees + SEBI Fee).

5. Fail-Closed 5-State Machine & Risk Latches:
   States: IDLE, COINTEGRATION_HEDGE_ACTIVE, GAMMA_SCALP_REBALANCING, VOLATILITY_SPIKE_HALT, EMERGENCY_UNWIND.
   EMERGENCY latches fail-closed requiring explicit operator RECOVERY_ACK.
   LIVE_ORDER_DISPATCH_ENABLED = False locked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, Optional, Tuple

LIVE_ORDER_DISPATCH_ENABLED: bool = False


class State(str, Enum):
    IDLE = "IDLE"
    COINTEGRATION_HEDGE_ACTIVE = "COINTEGRATION_HEDGE_ACTIVE"
    GAMMA_SCALP_REBALANCING = "GAMMA_SCALP_REBALANCING"
    VOLATILITY_SPIKE_HALT = "VOLATILITY_SPIKE_HALT"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class Event(str, Enum):
    NORMAL = "NORMAL"
    COINTEGRATION_SIGNAL = "COINTEGRATION_SIGNAL"
    GAMMA_TRIGGER = "GAMMA_TRIGGER"
    VOL_SPIKE = "VOL_SPIKE"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"
    CLEAR = "CLEAR"


@dataclass(frozen=True)
class KalmanConfig:
    q_intercept: float = 1e-6
    q_beta: float = 1e-5
    r_obs: float = 1e-3
    beta_min: float = -5.0
    beta_max: float = 5.0
    covariance_floor: float = 1e-12


@dataclass
class KalmanElasticity:
    """Random-walk Kalman filter for dynamic log-price elasticity beta_t = d ln(S^B) / d ln(S^N)."""
    intercept: float = 0.0
    beta: float = 1.0
    p00: float = 1.0
    p01: float = 0.0
    p11: float = 1.0
    config: KalmanConfig = field(default_factory=KalmanConfig)

    def update(self, log_nifty: float, log_banknifty: float) -> Dict[str, float]:
        if not (math.isfinite(log_nifty) and math.isfinite(log_banknifty)):
            raise ValueError("log prices must be finite")
        c = self.config

        # 1. State prediction: random-walk with diagonal process covariance Q
        p00 = self.p00 + c.q_intercept
        p01 = self.p01
        p11 = self.p11 + c.q_beta

        # 2. Observation measurement: H = [1, log(S^N)]
        h0, h1 = 1.0, log_nifty
        pred = self.intercept + self.beta * log_nifty
        innovation = log_banknifty - pred

        # 3. Innovation covariance: S = H P H^T + R
        s = h0 * h0 * p00 + 2 * h0 * h1 * p01 + h1 * h1 * p11 + c.r_obs
        if not math.isfinite(s) or s <= 0:
            raise ValueError("invalid innovation covariance")

        # 4. Kalman gain: K = P H^T / S
        k0 = (p00 * h0 + p01 * h1) / s
        k1 = (p01 * h0 + p11 * h1) / s

        # 5. State update with parameter bounds
        self.intercept += k0 * innovation
        self.beta = min(c.beta_max, max(c.beta_min, self.beta + k1 * innovation))

        # 6. Joseph-stabilized covariance update: (I - KH) P (I - KH)^T + K R K^T
        a00, a01 = 1.0 - k0 * h0, -k0 * h1
        a10, a11 = -k1 * h0, 1.0 - k1 * h1

        n00 = a00 * a00 * p00 + 2 * a00 * a01 * p01 + a01 * a01 * p11 + k0 * k0 * c.r_obs
        n01 = a00 * a10 * p00 + (a00 * a11 + a01 * a10) * p01 + a01 * a11 * p11 + k0 * k1 * c.r_obs
        n11 = a10 * a10 * p00 + 2 * a10 * a11 * p01 + a11 * a11 * p11 + k1 * k1 * c.r_obs

        self.p00 = max(c.covariance_floor, n00)
        self.p01 = n01
        self.p11 = max(c.covariance_floor, n11)

        return {
            "beta": self.beta,
            "intercept": self.intercept,
            "innovation": innovation,
            "innovation_variance": s,
            "z_score": innovation / math.sqrt(s),
        }


@dataclass(frozen=True)
class VECMConfig:
    base_speed: float = 0.05
    min_speed: float = 0.001
    max_speed: float = 0.5
    base_band: float = 1.5
    min_band: float = 0.5
    max_band: float = 4.0
    excitation_gain: float = 0.25
    depth_gain: float = 0.5


def vecm_controls(
    d_cross: float,
    normalized_depth: float,
    cfg: VECMConfig = VECMConfig(),
) -> Dict[str, float]:
    """Calculate bounded mean-reversion speed and entry band z-scores conditioned on Hawkes D_cross & depth."""
    if not math.isfinite(d_cross) or not math.isfinite(normalized_depth) or normalized_depth < 0:
        raise ValueError("invalid cross-excitation/depth input")

    speed = cfg.base_speed * math.exp(cfg.excitation_gain * abs(d_cross)) / (1.0 + cfg.depth_gain * normalized_depth)
    speed = min(cfg.max_speed, max(cfg.min_speed, speed))

    band = cfg.base_band * (1.0 + cfg.excitation_gain * abs(d_cross)) / math.sqrt(1.0 + cfg.depth_gain * normalized_depth)
    band = min(cfg.max_band, max(cfg.min_band, band))

    return {"mean_reversion_speed": speed, "entry_band_z": band}


def spread_and_z(
    log_nifty: float,
    log_banknifty: float,
    intercept: float,
    beta: float,
    spread_mean: float,
    spread_sd: float,
) -> Tuple[float, float]:
    """Calculate cointegration spread residual e_t and its standardized z-score."""
    if spread_sd <= 0 or not all(map(math.isfinite, (log_nifty, log_banknifty, intercept, beta, spread_mean, spread_sd))):
        raise ValueError("invalid spread inputs")
    spread = log_banknifty - intercept - beta * log_nifty
    return spread, (spread - spread_mean) / spread_sd


@dataclass(frozen=True)
class GreekBook:
    delta_nifty: float
    delta_banknifty: float
    beta: float
    gamma_nifty: float = 0.0
    gamma_banknifty: float = 0.0

    @property
    def joint_delta(self) -> float:
        """Delta_joint = Delta_NIFTY + beta * Delta_BANKNIFTY."""
        return self.delta_nifty + self.beta * self.delta_banknifty


def hedge_delta_banknifty(book: GreekBook) -> float:
    """Signed delta change in BANKNIFTY required to restore joint delta neutrality."""
    if not math.isfinite(book.beta) or abs(book.beta) < 1e-10:
        raise ValueError("beta too close to zero for hedge conversion")
    return -book.joint_delta / book.beta


def hedge_delta_nifty(book: GreekBook) -> float:
    """Signed delta change in NIFTY required to restore joint delta neutrality."""
    return -book.joint_delta


@dataclass(frozen=True)
class FeeConfig:
    options_exchange_ipft_per_crore: float = 3553.0
    futures_exchange_ipft_per_crore: float = 183.0
    option_sell_stt: float = 0.0015
    futures_sell_stt: float = 0.0005
    option_buy_stamp: float = 0.00003
    futures_buy_stamp: float = 0.00002
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    brokerage: float = 0.0


def statutory_friction(
    *,
    product: str,
    side: str,
    turnover: float,
    cfg: FeeConfig = FeeConfig(),
) -> float:
    """Estimate statutory transaction cost under Indian tax regime (October 2026 NSE baseline).
    Turnover definition:
      - options: option premium turnover (premium * lots * lot_size)
      - futures: traded notional (futures price * lots * lot_size)
    """
    if product not in {"options", "futures"} or side not in {"buy", "sell"}:
        raise ValueError("product must be options/futures and side buy/sell")
    if not math.isfinite(turnover) or turnover < 0:
        raise ValueError("turnover must be finite and non-negative")

    ex_rate = cfg.options_exchange_ipft_per_crore if product == "options" else cfg.futures_exchange_ipft_per_crore
    exchange = turnover * ex_rate / 1e7
    sebi = turnover * cfg.sebi_per_crore / 1e7

    if product == "options":
        stt = turnover * cfg.option_sell_stt if side == "sell" else 0.0
        stamp = turnover * cfg.option_buy_stamp if side == "buy" else 0.0
    else:
        stt = turnover * cfg.futures_sell_stt if side == "sell" else 0.0
        stamp = turnover * cfg.futures_buy_stamp if side == "buy" else 0.0

    gst = cfg.gst_rate * (exchange + sebi + cfg.brokerage)
    return exchange + sebi + stt + stamp + cfg.brokerage + gst


def gamma_rebalance_hurdle(
    *,
    expected_gamma_gain: float,
    turnover: float,
    product: str,
    side: str,
    impact_cost: float,
    other_execution_cost: float = 0.0,
    safety_margin: float = 0.0,
    fee_cfg: FeeConfig = FeeConfig(),
) -> Dict[str, Any]:
    """Evaluate whether expected gamma-scalping gains strictly overcome all statutory and market frictions."""
    values = (expected_gamma_gain, turnover, impact_cost, other_execution_cost, safety_margin)
    if not all(math.isfinite(v) for v in values) or any(v < 0 for v in values):
        raise ValueError("costs and expected gain must be finite and non-negative")

    fees = statutory_friction(product=product, side=side, turnover=turnover, cfg=fee_cfg)
    total = fees + impact_cost + other_execution_cost + safety_margin
    net_edge = expected_gamma_gain - total

    return {
        "fees": fees,
        "total_friction": total,
        "net_edge": net_edge,
        "rebalance_allowed": expected_gamma_gain > total,
    }


@dataclass
class StateMachine:
    state: State = State.IDLE
    emergency_latched: bool = False

    def step(self, event: Event) -> State:
        if self.emergency_latched:
            if event == Event.RECOVERY_ACK:
                self.emergency_latched = False
                self.state = State.IDLE
            else:
                self.state = State.EMERGENCY_UNWIND
            return self.state

        if event == Event.EMERGENCY:
            self.emergency_latched = True
            self.state = State.EMERGENCY_UNWIND
        elif event == Event.VOL_SPIKE:
            self.state = State.VOLATILITY_SPIKE_HALT
        elif self.state == State.VOLATILITY_SPIKE_HALT:
            if event in (Event.RECOVERY_ACK, Event.CLEAR):
                self.state = State.IDLE
        elif event == Event.GAMMA_TRIGGER:
            self.state = State.GAMMA_SCALP_REBALANCING
        elif event == Event.COINTEGRATION_SIGNAL:
            self.state = State.COINTEGRATION_HEDGE_ACTIVE
        elif event == Event.CLEAR:
            self.state = State.IDLE

        return self.state


@dataclass(frozen=True)
class MockFill:
    requested: int
    filled: int
    price: float


class DeterministicMockBroker:
    def __init__(self, passive_fill_fraction: float = 0.5):
        if not (0.0 <= passive_fill_fraction <= 1.0):
            raise ValueError("passive_fill_fraction must be in [0, 1]")
        self.passive_fill_fraction = passive_fill_fraction

    def fill(self, quantity: int, price: float, *, passive: bool = True) -> MockFill:
        if quantity < 0 or not math.isfinite(price) or price <= 0:
            raise ValueError("invalid mock order")
        filled = int(quantity * self.passive_fill_fraction) if passive else quantity
        return MockFill(quantity, filled, price)


def dispatch_live_order(*args, **kwargs):
    if not LIVE_ORDER_DISPATCH_ENABLED:
        raise RuntimeError("Live order dispatch is disabled by Cycle 18 safety invariant")
    raise RuntimeError("No live broker order adapter is configured")
