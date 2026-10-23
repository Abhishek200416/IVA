"""Cycle 23: simulation-only Actor-Critic gamma-scalping meta-control."""
from __future__ import annotations


from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence
import math
import numpy as np


LIVE_ORDER_DISPATCH_ENABLED = False
ACTION_DIM = 3




def _finite_array(x, name: str) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must contain only finite values")
    return a




@dataclass(frozen=True)
class MarketState:
    """All features must be causally available at decision time."""
    ofi: float
    hawkes_intensity: float
    rough_lift: tuple[float, ...]
    inventory: float
    delta: float
    gamma: float
    vega: float
    theta: float
    realized_volatility: float
    spread_bps: float
    regime_probability_high: float


    def vector(self) -> np.ndarray:
        values = [
            self.ofi, self.hawkes_intensity, *self.rough_lift,
            self.inventory, self.delta, self.gamma, self.vega,
            self.theta, self.realized_volatility, self.spread_bps,
            self.regime_probability_high,
        ]
        x = _finite_array(values, "state")
        if self.hawkes_intensity < 0 or self.realized_volatility < 0:
            raise ValueError("intensity and volatility must be nonnegative")
        if self.spread_bps < 0:
            raise ValueError("spread_bps must be nonnegative")
        if not 0 <= self.regime_probability_high <= 1:
            raise ValueError("regime probability must be in [0, 1]")
        return x




@dataclass(frozen=True)
class Action:
    # All three normalized controls are constrained to [-1, 1].
    quoting_spread_offset: float
    inventory_skew: float
    gamma_rebalance_urgency: float


    def vector(self) -> np.ndarray:
        a = _finite_array([
            self.quoting_spread_offset,
            self.inventory_skew,
            self.gamma_rebalance_urgency,
        ], "action")
        if np.any(np.abs(a) > 1.0 + 1e-12):
            raise ValueError("normalized actions must be in [-1, 1]")
        return a




@dataclass(frozen=True)
class PolicySample:
    state: np.ndarray
    raw_action: np.ndarray
    action: Action
    old_log_probability: float
    value: float




@dataclass
class GaussianActorCritic:
    """Small linear Gaussian actor/value critic with PPO-style updates.


    This is a transparent research baseline, not a neural-network production
    policy. Train and validate offline; do not connect it to an execution API.
    """
    state_dim: int
    seed: int = 7
    learning_rate: float = 1e-3
    clip_ratio: float = 0.2
    entropy_coefficient: float = 0.005
    value_coefficient: float = 0.5
    max_gradient_norm: float = 1.0
    actor_w: np.ndarray = field(init=False)
    actor_b: np.ndarray = field(init=False)
    critic_w: np.ndarray = field(init=False)
    critic_b: float = 0.0
    log_std: np.ndarray = field(init=False)
    rng: np.random.Generator = field(init=False)


    def __post_init__(self) -> None:
        if self.state_dim < 1 or self.learning_rate <= 0:
            raise ValueError("invalid state_dim or learning_rate")
        if not 0 < self.clip_ratio < 1:
            raise ValueError("clip_ratio must be in (0, 1)")
        self.rng = np.random.default_rng(self.seed)
        self.actor_w = np.zeros((self.state_dim, ACTION_DIM))
        self.actor_b = np.zeros(ACTION_DIM)
        self.critic_w = np.zeros(self.state_dim)
        self.log_std = np.full(ACTION_DIM, -0.5)


    def _check_state(self, state: Sequence[float]) -> np.ndarray:
        x = _finite_array(state, "state").reshape(-1)
        if x.size != self.state_dim:
            raise ValueError(f"expected state dimension {self.state_dim}")
        return x


    @staticmethod
    def _log_prob(raw: np.ndarray, mean: np.ndarray,
                  log_std: np.ndarray) -> float:
        std = np.exp(log_std)
        return float(np.sum(
            -0.5 * ((raw - mean) / std) ** 2
            - log_std - 0.5 * math.log(2 * math.pi)
        ))


    def value(self, state: Sequence[float]) -> float:
        x = self._check_state(state)
        return float(x @ self.critic_w + self.critic_b)


    def act(self, state: Sequence[float], *,
            deterministic: bool = False) -> PolicySample:
        x = self._check_state(state)
        mean = x @ self.actor_w + self.actor_b
        std = np.exp(np.clip(self.log_std, -4.0, 1.0))
        raw = mean.copy() if deterministic else mean + std * self.rng.normal(size=ACTION_DIM)
        action_vec = np.tanh(raw)
        action = Action(*map(float, action_vec))
        return PolicySample(
            state=x.copy(),
            raw_action=raw.copy(),
            action=action,
            old_log_probability=self._log_prob(raw, mean, np.log(std)),
            value=self.value(x),
        )


    def update(self, samples: Sequence[PolicySample],
               advantages: Sequence[float],
               returns: Sequence[float],
               epochs: int = 4) -> dict[str, float]:
        """PPO-style clipped surrogate update on a supplied offline batch."""
        n = len(samples)
        adv = _finite_array(advantages, "advantages").reshape(-1)
        ret = _finite_array(returns, "returns").reshape(-1)
        if n == 0 or adv.size != n or ret.size != n or epochs < 1:
            raise ValueError("invalid training batch")
        X = np.stack([self._check_state(s.state) for s in samples])
        U = np.stack([_finite_array(s.raw_action, "raw_action") for s in samples])
        old_lp = np.asarray([s.old_log_probability for s in samples], dtype=float)
        if U.shape != (n, ACTION_DIM) or not np.all(np.isfinite(old_lp)):
            raise ValueError("invalid policy samples")
        if np.std(adv) > 1e-12:
            adv = (adv - adv.mean()) / (adv.std() + 1e-8)


        policy_loss = value_loss = entropy = 0.0
        for _ in range(epochs):
            means = X @ self.actor_w + self.actor_b
            log_std = np.clip(self.log_std, -4.0, 1.0)
            std = np.exp(log_std)
            diff = U - means
            new_lp = np.sum(
                -0.5 * (diff / std) ** 2 - log_std
                - 0.5 * math.log(2 * math.pi), axis=1
            )
            log_ratio = np.clip(new_lp - old_lp, -20, 20)
            ratio = np.exp(log_ratio)
            unclipped = ratio * adv
            clipped = np.clip(ratio, 1-self.clip_ratio, 1+self.clip_ratio) * adv
            active = ((adv >= 0) & (ratio <= 1+self.clip_ratio)) | (
                (adv < 0) & (ratio >= 1-self.clip_ratio)
            )
            grad_logp_mu = diff / (std ** 2)
            coeff = -(ratio * adv * active.astype(float)) / n
            grad_mu = coeff[:, None] * grad_logp_mu
            grad_w = X.T @ grad_mu
            grad_b = grad_mu.sum(axis=0)


            # Entropy of a diagonal Gaussian is sum(log_std) plus a constant.
            grad_log_std = np.sum(
                coeff[:, None] * ((diff / std) ** 2 - 1), axis=0
            ) - self.entropy_coefficient
            grads = [grad_w, grad_b, grad_log_std]
            norm = math.sqrt(sum(float(np.sum(g*g)) for g in grads))
            scale = min(1.0, self.max_gradient_norm / max(norm, 1e-12))
            self.actor_w -= self.learning_rate * grad_w * scale
            self.actor_b -= self.learning_rate * grad_b * scale
            self.log_std -= self.learning_rate * grad_log_std * scale
            self.log_std = np.clip(self.log_std, -4.0, 1.0)


            pred = X @ self.critic_w + self.critic_b
            err = pred - ret
            gw = self.value_coefficient * (X.T @ err) / n
            gb = self.value_coefficient * float(err.mean())
            self.critic_w -= self.learning_rate * gw
            self.critic_b -= self.learning_rate * gb


            policy_loss = float(-np.mean(np.minimum(unclipped, clipped)))
            value_loss = float(np.mean(err ** 2))
            entropy = float(np.sum(log_std + 0.5 * math.log(2*math.pi*math.e)))


        return {
            "policy_loss": policy_loss,
            "value_loss": value_loss,
            "entropy": entropy,
        }




@dataclass
class BayesianRegimeFilter:
    """Two-regime Gaussian emission filter over [OFI, realized volatility].


    The low/high regime means and standard deviations must be calibrated offline.
    """
    low_mean: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.01]))
    high_mean: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.03]))
    low_std: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.01]))
    high_std: np.ndarray = field(default_factory=lambda: np.array([2.0, 0.03]))
    p_low_to_high: float = 0.03
    p_high_to_low: float = 0.15
    p_high: float = 0.1


    def __post_init__(self) -> None:
        for name in ("low_mean", "high_mean", "low_std", "high_std"):
            a = _finite_array(getattr(self, name), name).reshape(-1)
            if a.size != 2:
                raise ValueError(f"{name} must have two features")
            setattr(self, name, a)
        if np.any(self.low_std <= 0) or np.any(self.high_std <= 0):
            raise ValueError("regime standard deviations must be positive")
        if not 0 <= self.p_low_to_high <= 1 or not 0 <= self.p_high_to_low <= 1:
            raise ValueError("transition probabilities must be in [0, 1]")
        if not 0 <= self.p_high <= 1:
            raise ValueError("p_high must be in [0, 1]")


    @staticmethod
    def _log_emission(x, mean, std) -> float:
        return float(np.sum(
            -0.5*((x-mean)/std)**2 - np.log(std)
            - 0.5*math.log(2*math.pi)
        ))


    def update(self, ofi: float, realized_volatility: float) -> float:
        x = _finite_array([ofi, realized_volatility], "regime observation")
        if realized_volatility < 0:
            raise ValueError("realized volatility must be nonnegative")
        prior = (
            self.p_high * (1-self.p_high_to_low)
            + (1-self.p_high) * self.p_low_to_high
        )
        log_high = math.log(max(prior, 1e-300)) + self._log_emission(
            x, self.high_mean, self.high_std
        )
        log_low = math.log(max(1-prior, 1e-300)) + self._log_emission(
            x, self.low_mean, self.low_std
        )
        m = max(log_high, log_low)
        ph = math.exp(log_high-m)
        pl = math.exp(log_low-m)
        self.p_high = ph/(ph+pl)
        return self.p_high




def gamma_rebalance_band(*, transaction_cost: float,
                         risk_aversion: float, option_gamma: float,
                         spot: float, hawkes_intensity: float = 0.0,
                         hawkes_sensitivity: float = 0.0,
                         min_band: float = 0.0,
                         max_band: float = 1.0) -> tuple[float, float]:
    """Return symmetric delta no-trade band; zero gamma disables this formula."""
    vals = [transaction_cost, risk_aversion, option_gamma, spot,
            hawkes_intensity, hawkes_sensitivity, min_band, max_band]
    if not np.all(np.isfinite(vals)):
        raise ValueError("band inputs must be finite")
    if transaction_cost < 0 or risk_aversion <= 0 or spot <= 0:
        raise ValueError("invalid cost, risk aversion, or spot")
    if hawkes_intensity < 0 or hawkes_sensitivity < 0:
        raise ValueError("Hawkes parameters must be nonnegative")
    if min_band < 0 or max_band < min_band:
        raise ValueError("invalid band bounds")
    if abs(option_gamma) < 1e-12 or transaction_cost == 0:
        width = max_band if abs(option_gamma) < 1e-12 else min_band
    else:
        width = (3*transaction_cost /
                 (2*risk_aversion*abs(option_gamma)*spot**2)) ** (1/3)
        # More arrivals => narrower band. This is a configurable heuristic.
        width /= (1 + hawkes_sensitivity*hawkes_intensity) ** (1/3)
        width = float(np.clip(width, min_band, max_band))
    return (-float(width), float(width))




@dataclass(frozen=True)
class FeeConfig:
    """Rates are configurable and must be verified for the transaction date."""
    options_sell_stt: float = 0.0015
    exchange_per_crore: float = 3553.0
    gst_rate: float = 0.18
    stamp_buy_rate: float = 0.00003
    sebi_per_crore: float = 10.0
    brokerage_per_order: float = 0.0
    gst_applies_to_exchange_and_sebi: bool = True




@dataclass(frozen=True)
class CostBreakdown:
    premium_turnover: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    half_spread_cost: float
    market_impact_cost: float
    total: float




def transaction_costs(*, premium: float, quantity: int, side: str,
                       half_spread_per_unit: float = 0.0,
                       market_impact_per_unit: float = 0.0,
                       config: FeeConfig = FeeConfig()) -> CostBreakdown:
    if not math.isfinite(premium) or premium < 0 or quantity < 0:
        raise ValueError("premium and quantity must be nonnegative and finite")
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if min(half_spread_per_unit, market_impact_per_unit) < 0:
        raise ValueError("spread and impact costs must be nonnegative")
    turnover = premium * quantity
    exchange = turnover * config.exchange_per_crore / 1e7
    sebi = turnover * config.sebi_per_crore / 1e7
    stt = turnover * config.options_sell_stt if side == "SELL" else 0.0
    stamp = turnover * config.stamp_buy_rate if side == "BUY" else 0.0
    brokerage = config.brokerage_per_order
    gst_base = brokerage + (exchange + sebi if config.gst_applies_to_exchange_and_sebi else 0.0)
    gst = gst_base * config.gst_rate
    spread = half_spread_per_unit * quantity
    impact = market_impact_per_unit * quantity
    components = [turnover, stt, exchange, sebi, gst, stamp, brokerage, spread, impact]
    if not np.all(np.isfinite(components)):
        raise ValueError("cost calculation overflowed")
    return CostBreakdown(
        turnover, stt, exchange, sebi, gst, stamp, brokerage, spread, impact,
        float(sum(components[1:])),
    )




def friction_aware_reward(*, pnl_change: float, inventory: Sequence[float],
                          covariance: np.ndarray, risk_aversion: float,
                          costs: CostBreakdown) -> float:
    q = _finite_array(inventory, "inventory").reshape(-1)
    cov = _finite_array(covariance, "covariance")
    if cov.shape != (q.size, q.size) or risk_aversion < 0:
        raise ValueError("invalid covariance shape or risk aversion")
    cov = (cov + cov.T) / 2
    if np.linalg.eigvalsh(cov).min() < -1e-8:
        raise ValueError("covariance must be positive semidefinite")
    if not math.isfinite(pnl_change):
        raise ValueError("pnl_change must be finite")
    risk_penalty = 0.5*risk_aversion*float(q @ cov @ q)
    return float(pnl_change - risk_penalty - costs.total)




class RiskState(str, Enum):
    IDLE = "IDLE"
    CONTROLLER_ACTIVE = "CONTROLLER_ACTIVE"
    SCALPING_REBALANCING = "SCALPING_REBALANCING"
    POLICY_DIVERGENCE_HALT = "POLICY_DIVERGENCE_HALT"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"




class RiskEvent(str, Enum):
    START = "START"
    REBALANCE = "REBALANCE"
    POLICY_DIVERGENCE = "POLICY_DIVERGENCE"
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
            self.history.append((event.value, "blocked_latched"))
            return self.state
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event is RiskEvent.POLICY_DIVERGENCE:
            self.state = RiskState.POLICY_DIVERGENCE_HALT
        elif event is RiskEvent.START and self.state is RiskState.IDLE:
            self.state = RiskState.CONTROLLER_ACTIVE
        elif event is RiskEvent.REBALANCE and self.state is RiskState.CONTROLLER_ACTIVE:
            self.state = RiskState.SCALPING_REBALANCING
        elif event is RiskEvent.RESET and self.state is not RiskState.EMERGENCY_UNWIND:
            self.state = RiskState.IDLE
        self.history.append((event.value, self.state.value))
        return self.state




def dispatch_live_order(*args, **kwargs):
    """Intentionally unavailable in this reference implementation."""
    raise RuntimeError("live order dispatch is disabled; simulation only")
