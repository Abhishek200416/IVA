"""Cross-Asset Order Book Level Imbalance & Bid-Ask Elasticity Coupling Engine.

Wave 29 Deliverable (TASK-BN-39):
Synthesized in consultation with MiniMax M2.7 and DeepSeek V4 Flash:
1. Multi-Level Depth Imbalance:
   - Evaluates 5-level queue depth imbalance:
     I_k(t) = (Q_k^{bid}(t) - Q_k^{ask}(t)) / (Q_k^{bid}(t) + Q_k^{ask}(t)) in [-1.0, 1.0]
   - Exponential decay weights: w_k = exp(-alpha * (k - 1)), alpha in [0.2, 0.5]
   - Integrated order book pressure:
     W_I(t) = sum_{k=1}^K (w_k * I_k(t)) / sum_{k=1}^K w_k in [-1.0, 1.0]
2. Cross-Asset Elasticity Coupling Matrix E:
   - Models queue replenishment following cross-asset price shocks:
     Delta Q_1^{rep} = E_11 * Delta P_1 + E_12 * Delta P_2
     Delta Q_2^{rep} = E_21 * Delta P_1 + E_22 * Delta P_2
   - Normalized cross-elasticity coefficient:
     epsilon_12 = E_12 / sqrt(E_11 * E_22)
   - Queue resilience time scale tau_replenish:
     Delta Q^{obs}(t + Delta t) = Delta Q^{rep} * exp(-Delta t / tau_replenish)
3. Phantom Liquidity & Queue Evaporation Detector:
   - Measures replenishment asymmetry A(t) = |Delta Q_1^{obs} - Delta Q_2^{obs}|
   - Detects queue breakdown when |Delta Q^{obs} - Delta Q^{pred}| > theta
   - Outputs dynamic quote spread widening multiplier M in [1.0, 3.0] to protect
     market makers against adverse selection and spoofing.

Zero external dependencies outside standard library math and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ElasticityRegime(str, Enum):
    COUPLED_RESILIENT = "COUPLED_RESILIENT"
    NORMAL_EQUILIBRIUM = "NORMAL_EQUILIBRIUM"
    ASYMMETRIC_PRESSURE = "ASYMMETRIC_PRESSURE"
    PHANTOM_LIQUIDITY_EVAPORATION = "PHANTOM_LIQUIDITY_EVAPORATION"


@dataclass(frozen=True)
class OrderBookLevel:
    """A single price-level in the order book."""
    level: int  # 1 (best) through 5
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float

    @property
    def level_imbalance(self) -> float:
        """I_k = (Q_bid - Q_ask) / (Q_bid + Q_ask) in [-1.0, 1.0]."""
        total = self.bid_qty + self.ask_qty
        if total <= 1e-9:
            return 0.0
        return (self.bid_qty - self.ask_qty) / total


@dataclass(frozen=True)
class OrderBookDepthSnapshot:
    """5-level depth snapshot for an asset."""
    symbol: str
    timestamp: float
    mid_price: float
    levels: List[OrderBookLevel]

    def compute_integrated_pressure(self, alpha: float = 0.30) -> Tuple[List[float], float]:
        """Calculates multi-level imbalance vector and integrated pressure W_I."""
        if not self.levels:
            return [], 0.0

        imbalances: List[float] = []
        weighted_sum = 0.0
        weight_sum = 0.0

        for idx, lvl in enumerate(self.levels):
            imb = lvl.level_imbalance
            imbalances.append(imb)
            w = math.exp(-alpha * idx)
            weighted_sum += w * imb
            weight_sum += w

        w_i = weighted_sum / weight_sum if weight_sum > 0.0 else 0.0
        w_i = max(-1.0, min(1.0, w_i))
        return imbalances, round(w_i, 4)


@dataclass(frozen=True)
class ElasticityCouplingMatrix:
    """2x2 Cross-Asset Queue Elasticity Matrix."""
    e_11: float  # Nifty own-elasticity
    e_22: float  # Bank Nifty own-elasticity
    e_12: float  # Cross-elasticity (Nifty price -> Bank Nifty queue)
    e_21: float  # Cross-elasticity (Bank Nifty price -> Nifty queue)
    tau_replenish_sec: float = 2.5  # Queue resilience half-life

    @property
    def normalized_cross_elasticity(self) -> float:
        """epsilon_12 = E_12 / sqrt(E_11 * E_22)."""
        denom = math.sqrt(abs(self.e_11 * self.e_22))
        if denom <= 1e-9:
            return 0.0
        return max(-1.0, min(1.0, self.e_12 / denom))

    def predict_replenishment(
        self,
        delta_p_nifty: float,
        delta_p_bank: float,
    ) -> Tuple[float, float]:
        """Predicts expected queue replenishment: Delta Q = E * Delta P."""
        q1_pred = (self.e_11 * delta_p_nifty) + (self.e_12 * delta_p_bank)
        q2_pred = (self.e_21 * delta_p_nifty) + (self.e_22 * delta_p_bank)
        return q1_pred, q2_pred

    def decay_replenishment(self, delta_q: float, elapsed_seconds: float) -> float:
        """Applies exponential decay over elapsed time."""
        if self.tau_replenish_sec <= 0.0:
            return delta_q
        decay_factor = math.exp(-elapsed_seconds / self.tau_replenish_sec)
        return delta_q * decay_factor


@dataclass(frozen=True)
class CrossElasticityMetrics:
    """Current cross-asset elasticity coupling and queue pressure metrics."""
    symbol_nifty: str
    symbol_bank: str
    pressure_nifty: float
    pressure_bank: float
    pressure_imbalance_ratio: float
    normalized_cross_elasticity: float
    predicted_replenish_nifty: float
    predicted_replenish_bank: float
    observed_replenish_nifty: float
    observed_replenish_bank: float
    replenishment_asymmetry: float
    prediction_error_nifty: float
    prediction_error_bank: float
    regime: ElasticityRegime
    phantom_liquidity_alert: bool
    spread_multiplier: float


class CrossAssetElasticityEngine:
    """Multi-Asset Order Book Level Imbalance & Bid-Ask Elasticity Coupling Engine."""

    def __init__(
        self,
        symbol_nifty: str = "NIFTY_50",
        symbol_bank: str = "BANK_NIFTY",
        coupling_matrix: Optional[ElasticityCouplingMatrix] = None,
        alpha_depth_decay: float = 0.30,
        breakdown_threshold: float = 40.0,
        spread_sensitivity_lambda: float = 0.03,
    ) -> None:
        self.symbol_nifty = str(symbol_nifty)
        self.symbol_bank = str(symbol_bank)
        self.matrix = coupling_matrix or ElasticityCouplingMatrix(
            e_11=25.0,  # 25 contracts replenishment per point move
            e_22=15.0,  # 15 contracts replenishment per point move
            e_12=8.0,   # cross-elasticity
            e_21=8.0,
            tau_replenish_sec=2.5,
        )
        self.alpha = float(alpha_depth_decay)
        self.breakdown_threshold = float(breakdown_threshold)
        self.sensitivity_lambda = float(spread_sensitivity_lambda)

        # Previous snapshots for Delta P and Delta Q tracking
        self.prev_nifty_snapshot: Optional[OrderBookDepthSnapshot] = None
        self.prev_bank_snapshot: Optional[OrderBookDepthSnapshot] = None

    def evaluate_coupling(
        self,
        nifty_snap: OrderBookDepthSnapshot,
        bank_snap: OrderBookDepthSnapshot,
        observed_delta_q_nifty: Optional[float] = None,
        observed_delta_q_bank: Optional[float] = None,
    ) -> CrossElasticityMetrics:
        """Evaluates 5-level depth pressure, queue replenishment, and phantom liquidity alerts."""
        _, pressure_nifty = nifty_snap.compute_integrated_pressure(self.alpha)
        _, pressure_bank = bank_snap.compute_integrated_pressure(self.alpha)

        # Compute price changes if previous snapshots exist
        if self.prev_nifty_snapshot:
            dp_nifty = nifty_snap.mid_price - self.prev_nifty_snapshot.mid_price
        else:
            dp_nifty = 0.0

        if self.prev_bank_snapshot:
            dp_bank = bank_snap.mid_price - self.prev_bank_snapshot.mid_price
        else:
            dp_bank = 0.0

        # Predict replenishment from coupling matrix
        pred_q1, pred_q2 = self.matrix.predict_replenishment(dp_nifty, dp_bank)

        # Observed replenishment defaults to predicted if not supplied
        obs_q1 = observed_delta_q_nifty if observed_delta_q_nifty is not None else pred_q1
        obs_q2 = observed_delta_q_bank if observed_delta_q_bank is not None else pred_q2

        # Errors
        err1 = abs(obs_q1 - pred_q1)
        err2 = abs(obs_q2 - pred_q2)
        asymmetry = abs(obs_q1 - obs_q2)

        # Pressure ratio
        diff_pressure = abs(pressure_nifty - pressure_bank)

        # Phantom Liquidity / Breakdown Trigger
        is_breakdown = (err1 > self.breakdown_threshold) or (err2 > self.breakdown_threshold)

        if is_breakdown:
            regime = ElasticityRegime.PHANTOM_LIQUIDITY_EVAPORATION
            phantom_alert = True
            # Spread multiplier scales with excess prediction error
            max_err = max(err1, err2)
            spread_mult = 1.0 + (self.sensitivity_lambda * max_err)
            spread_mult = min(3.0, max(1.5, spread_mult))
        elif diff_pressure >= 0.60:
            regime = ElasticityRegime.ASYMMETRIC_PRESSURE
            phantom_alert = False
            spread_mult = 1.25
        elif abs(self.matrix.normalized_cross_elasticity) >= 0.40:
            regime = ElasticityRegime.COUPLED_RESILIENT
            phantom_alert = False
            spread_mult = 1.0
        else:
            regime = ElasticityRegime.NORMAL_EQUILIBRIUM
            phantom_alert = False
            spread_mult = 1.0

        # Update cache
        self.prev_nifty_snapshot = nifty_snap
        self.prev_bank_snapshot = bank_snap

        return CrossElasticityMetrics(
            symbol_nifty=self.symbol_nifty,
            symbol_bank=self.symbol_bank,
            pressure_nifty=pressure_nifty,
            pressure_bank=pressure_bank,
            pressure_imbalance_ratio=round(diff_pressure, 4),
            normalized_cross_elasticity=round(self.matrix.normalized_cross_elasticity, 4),
            predicted_replenish_nifty=round(pred_q1, 2),
            predicted_replenish_bank=round(pred_q2, 2),
            observed_replenish_nifty=round(obs_q1, 2),
            observed_replenish_bank=round(obs_q2, 2),
            replenishment_asymmetry=round(asymmetry, 2),
            prediction_error_nifty=round(err1, 2),
            prediction_error_bank=round(err2, 2),
            regime=regime,
            phantom_liquidity_alert=phantom_alert,
            spread_multiplier=round(spread_mult, 2),
        )

    def compute_pacing_decision(
        self,
        metrics: CrossElasticityMetrics,
        base_delay_ms: float = 50.0,
    ) -> ExecutionPacingDecision:
        """Translates cross-elasticity metrics and regime into execution pacing and routing constraints."""
        regime = metrics.regime
        pacing_multiplier = 1.0

        if regime == ElasticityRegime.PHANTOM_LIQUIDITY_EVAPORATION:
            pacing_multiplier = min(5.0, max(2.5, metrics.spread_multiplier * 1.5))
            is_passive_only = True
            reason = f"Phantom liquidity evaporation detected (spread_mult={metrics.spread_multiplier:.2f}), forcing passive-only quote posting."
        elif regime == ElasticityRegime.ASYMMETRIC_PRESSURE:
            if metrics.pressure_imbalance_ratio > 0.70:
                pacing_multiplier = 3.5
                is_passive_only = True
                reason = f"Severe asymmetric queue pressure (imbalance={metrics.pressure_imbalance_ratio:.2f} > 0.70), forcing passive-only routing."
            else:
                pacing_multiplier = 2.0
                is_passive_only = False
                reason = f"Moderate asymmetric queue pressure (imbalance={metrics.pressure_imbalance_ratio:.2f}), pacing throttled."
        elif regime == ElasticityRegime.COUPLED_RESILIENT:
            pacing_multiplier = 1.0
            is_passive_only = False
            reason = f"Coupled resilient queues (epsilon_12={metrics.normalized_cross_elasticity:.2f}), normal high-frequency pacing."
        else:
            pacing_multiplier = 1.0
            is_passive_only = False
            reason = "Normal equilibrium cross-asset elasticity, standard pacing."

        pacing_multiplier = max(1.0, min(5.0, round(pacing_multiplier, 2)))
        recommended_delay_ms = round(base_delay_ms * pacing_multiplier, 1)

        return ExecutionPacingDecision(
            symbol=metrics.symbol_bank,
            pacing_multiplier=pacing_multiplier,
            recommended_delay_ms=recommended_delay_ms,
            is_passive_only=is_passive_only,
            reason=reason,
        )


@dataclass(frozen=True)
class ExecutionPacingDecision:
    """Dynamic execution pacing and routing decision based on cross-elasticity."""
    symbol: str
    pacing_multiplier: float
    recommended_delay_ms: float
    is_passive_only: bool
    reason: str


# Backward-compatibility aliases
CrossElasticityMatrix = ElasticityCouplingMatrix
ElasticityDepthSnapshot = OrderBookDepthSnapshot

