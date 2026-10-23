"""Dynamic Multi-Leg Gamma Scalp & Elasticity-Aware Cross-Hedging Router.

Wave 30 Deliverable (TASK-BN-40):
Synthesized in consultation with MiniMax M2.7 and DeepSeek V4 Flash:
1. Cross-Asset Elasticity Allocation:
   Optimal cross-asset hedge weights between Bank Nifty (Asset 1) and Nifty 50 (Asset 2)
   based on order book queue elasticity (eps_1, eps_2) and marginal transaction cost (C_1, C_2):
     alpha = (C_2 * eps_1) / (C_2 * eps_1 + C_1 * eps_2) in [0.0, 1.0]
     allocation_2 = 1.0 - alpha
2. Toxicity-Adaptive Whalley-Wilmott Delta Bandwidth:
   Expands delta rebalancing tolerance under elevated adverse selection:
     delta_tolerance = delta_base * (1.0 + k_vpin * vpin_joint + k_toxic * rho_toxic)
   If vpin_joint >= 0.35 and rho_toxic >= 0.50:
     Activates SHORT_GAMMA_FREEZE (lock rebalancing, no new delta accumulation).
3. Integer Lot Quantization under SEBI regulations:
   Bank Nifty lot size = 15, Nifty 50 lot size = 25.
   Quantizes continuous hedge requirements to discrete contract multiples:
     N_1 = round(rupee_delta_1 / (S_1 * 15)) * 15
     N_2 = round(rupee_delta_2 / (S_2 * 25)) * 25
   Computes residual unhedged rupee delta and tracking error ratio.

Zero external dependencies outside standard library math and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, NamedTuple, Optional, Tuple


class ScalpRegime(str, Enum):
    """Scalping regime classifications based on market microstructure conditions."""
    NORMAL = "NORMAL"
    ADAPTIVE = "ADAPTIVE"
    SHORT_GAMMA_FREEZE = "SHORT_GAMMA_FREEZE"


class ElasticityParams(NamedTuple):
    """Order book elasticity parameters for both assets."""
    eps_1: float  # Bank Nifty elasticity
    eps_2: float  # Nifty 50 elasticity


class TransactionCostParams(NamedTuple):
    """Marginal transaction cost parameters in basis points or rupees."""
    c_1: float  # Bank Nifty marginal cost
    c_2: float  # Nifty 50 marginal cost


class ToxicityParams(NamedTuple):
    """Toxicity-adaptive parameters for Whalley-Wilmott expansion."""
    delta_base: float      # Base delta tolerance (e.g. 0.05)
    k_vpin: float          # VPIN sensitivity coefficient (e.g. 1.5)
    k_toxic: float         # Toxicity correlation coefficient (e.g. 1.0)
    vpin_threshold: float = 0.35
    rho_threshold: float = 0.50


@dataclass(frozen=True)
class ScalpOrderLeg:
    """Represents a single quantized order leg in the cross-hedge strategy."""
    asset_id: str
    symbol: str
    lot_size: int
    spot_price: float
    direction: str  # 'BUY' or 'SELL'
    continuous_delta: float
    quantized_contracts: int
    quantized_lots: int
    quantized_rupee_delta: float
    residual_rupee_delta: float


@dataclass(frozen=True)
class CrossHedgeScalpDecision:
    """Complete decision output for cross-hedge scalping strategy."""
    regime: ScalpRegime
    alpha_bank_nifty: float
    alpha_nifty_50: float
    delta_tolerance: float
    vpin_joint: float
    rho_toxic: float
    target_rupee_delta: float
    executed_rupee_delta: float
    residual_rupee_delta: float
    tracking_error_ratio: float
    is_freeze_active: bool
    should_rebalance: bool
    legs: Tuple[ScalpOrderLeg, ...]
    timestamp: float
    reason: str


class ElasticityCrossHedgeScalper:
    """Dynamic Multi-Leg Gamma Scalp & Elasticity-Aware Cross-Hedging Router."""

    BANK_NIFTY_LOT_SIZE: int = 15
    NIFTY_50_LOT_SIZE: int = 25
    BANK_NIFTY_SYMBOL: str = "BANK_NIFTY"
    NIFTY_50_SYMBOL: str = "NIFTY_50"

    def __init__(
        self,
        elasticity_params: ElasticityParams = ElasticityParams(eps_1=15.0, eps_2=25.0),
        cost_params: TransactionCostParams = TransactionCostParams(c_1=4.5, c_2=3.0),
        toxicity_params: ToxicityParams = ToxicityParams(delta_base=0.05, k_vpin=1.5, k_toxic=1.0),
    ) -> None:
        self._validate_params(elasticity_params, cost_params, toxicity_params)
        self.elasticity = elasticity_params
        self.costs = cost_params
        self.toxicity = toxicity_params

    @staticmethod
    def _validate_params(
        ep: ElasticityParams,
        cp: TransactionCostParams,
        tp: ToxicityParams,
    ) -> None:
        if ep.eps_1 <= 0.0 or ep.eps_2 <= 0.0:
            raise ValueError(f"Elasticity parameters must be positive, got eps_1={ep.eps_1}, eps_2={ep.eps_2}")
        if cp.c_1 <= 0.0 or cp.c_2 <= 0.0:
            raise ValueError(f"Transaction costs must be positive, got c_1={cp.c_1}, c_2={cp.c_2}")
        if tp.delta_base <= 0.0:
            raise ValueError(f"delta_base must be positive, got {tp.delta_base}")

    def compute_allocation_weights(self) -> Tuple[float, float]:
        """Calculates optimal cross-hedge weights alpha (Bank Nifty) and 1-alpha (Nifty 50).

        alpha = (c_2 * eps_1) / (c_2 * eps_1 + c_1 * eps_2)
        """
        c1, c2 = self.costs.c_1, self.costs.c_2
        eps1, eps2 = self.elasticity.eps_1, self.elasticity.eps_2

        numerator = c2 * eps1
        denominator = (c2 * eps1) + (c1 * eps2)
        if denominator <= 1e-9:
            return 0.50, 0.50

        alpha = numerator / denominator
        alpha = max(0.0, min(1.0, round(alpha, 4)))
        return alpha, round(1.0 - alpha, 4)

    def evaluate_toxicity_and_bandwidth(
        self,
        vpin_joint: float,
        rho_toxic: float,
    ) -> Tuple[float, ScalpRegime, bool]:
        """Evaluates Whalley-Wilmott delta tolerance bandwidth and freeze state."""
        tp = self.toxicity
        vpin = max(0.0, min(1.0, float(vpin_joint)))
        rho = max(-1.0, min(1.0, float(rho_toxic)))

        is_freeze = (vpin >= tp.vpin_threshold) and (rho >= tp.rho_threshold)

        if is_freeze:
            regime = ScalpRegime.SHORT_GAMMA_FREEZE
            tolerance = tp.delta_base * 2.5
        elif vpin >= (tp.vpin_threshold * 0.60):
            regime = ScalpRegime.ADAPTIVE
            tolerance = tp.delta_base * (1.0 + (tp.k_vpin * vpin) + (tp.k_toxic * max(0.0, rho)))
        else:
            regime = ScalpRegime.NORMAL
            tolerance = tp.delta_base * (1.0 + (tp.k_vpin * vpin) + (tp.k_toxic * max(0.0, rho)))

        tolerance = round(tolerance, 4)
        return tolerance, regime, is_freeze

    def route_hedge_rebalance(
        self,
        delta_exposure: float,
        spot_bank: float,
        spot_nifty: float,
        vpin_joint: float = 0.15,
        rho_toxic: float = 0.20,
        timestamp: float = 0.0,
    ) -> CrossHedgeScalpDecision:
        """Evaluates portfolio delta drift and generates integer-quantized cross-hedge orders."""
        if spot_bank <= 0.0 or spot_nifty <= 0.0:
            raise ValueError(f"Spot prices must be positive: spot_bank={spot_bank}, spot_nifty={spot_nifty}")

        tolerance, regime, is_freeze = self.evaluate_toxicity_and_bandwidth(vpin_joint, rho_toxic)
        alpha_bn, alpha_n50 = self.compute_allocation_weights()

        # To hedge +delta, we SELL underlying; to hedge -delta, we BUY underlying
        target_hedge_delta = -float(delta_exposure)
        target_rupee_delta = target_hedge_delta * spot_bank

        # Check if delta drift exceeds tolerance bandwidth
        drift_magnitude = abs(delta_exposure)
        should_rebalance = (drift_magnitude >= tolerance) and not is_freeze

        if not should_rebalance:
            if is_freeze:
                reason = f"SHORT_GAMMA_FREEZE active (VPIN={vpin_joint:.2f}, Rho={rho_toxic:.2f}). Rebalancing locked to prevent toxic adverse fills."
            else:
                reason = f"Delta drift {drift_magnitude:.4f} within tolerance {tolerance:.4f}. No rebalancing required."

            return CrossHedgeScalpDecision(
                regime=regime,
                alpha_bank_nifty=alpha_bn,
                alpha_nifty_50=alpha_n50,
                delta_tolerance=tolerance,
                vpin_joint=round(vpin_joint, 4),
                rho_toxic=round(rho_toxic, 4),
                target_rupee_delta=round(target_rupee_delta, 2),
                executed_rupee_delta=0.0,
                residual_rupee_delta=round(target_rupee_delta, 2),
                tracking_error_ratio=1.0 if abs(target_rupee_delta) > 1e-6 else 0.0,
                is_freeze_active=is_freeze,
                should_rebalance=False,
                legs=(),
                timestamp=float(timestamp),
                reason=reason,
            )

        # Allocate rupee delta between Bank Nifty and Nifty 50
        alloc_rupee_bn = target_rupee_delta * alpha_bn
        alloc_rupee_n50 = target_rupee_delta * alpha_n50

        # Continuous contract requirements
        cont_contracts_bn = alloc_rupee_bn / spot_bank
        cont_contracts_n50 = alloc_rupee_n50 / spot_nifty

        # SEBI Integer lot quantization (minimum 1 lot per active asset when rebalance is triggered)
        lots_bn_raw = round(cont_contracts_bn / self.BANK_NIFTY_LOT_SIZE)
        if lots_bn_raw == 0 and alpha_bn >= 0.20 and abs(cont_contracts_bn) > 1e-4:
            lots_bn = 1 if cont_contracts_bn > 0 else -1
        else:
            lots_bn = lots_bn_raw

        contracts_bn = lots_bn * self.BANK_NIFTY_LOT_SIZE
        exec_rupee_bn = contracts_bn * spot_bank
        res_rupee_bn = alloc_rupee_bn - exec_rupee_bn

        lots_n50_raw = round(cont_contracts_n50 / self.NIFTY_50_LOT_SIZE)
        if lots_n50_raw == 0 and alpha_n50 >= 0.20 and abs(cont_contracts_n50) > 1e-4:
            lots_n50 = 1 if cont_contracts_n50 > 0 else -1
        else:
            lots_n50 = lots_n50_raw

        contracts_n50 = lots_n50 * self.NIFTY_50_LOT_SIZE
        exec_rupee_n50 = contracts_n50 * spot_nifty
        res_rupee_n50 = alloc_rupee_n50 - exec_rupee_n50

        direction_bn = "BUY" if contracts_bn > 0 else ("SELL" if contracts_bn < 0 else "FLAT")
        direction_n50 = "BUY" if contracts_n50 > 0 else ("SELL" if contracts_n50 < 0 else "FLAT")

        leg_bn = ScalpOrderLeg(
            asset_id="1",
            symbol=self.BANK_NIFTY_SYMBOL,
            lot_size=self.BANK_NIFTY_LOT_SIZE,
            spot_price=spot_bank,
            direction=direction_bn,
            continuous_delta=round(cont_contracts_bn, 2),
            quantized_contracts=abs(contracts_bn),
            quantized_lots=abs(lots_bn),
            quantized_rupee_delta=round(exec_rupee_bn, 2),
            residual_rupee_delta=round(res_rupee_bn, 2),
        )

        leg_n50 = ScalpOrderLeg(
            asset_id="2",
            symbol=self.NIFTY_50_SYMBOL,
            lot_size=self.NIFTY_50_LOT_SIZE,
            spot_price=spot_nifty,
            direction=direction_n50,
            continuous_delta=round(cont_contracts_n50, 2),
            quantized_contracts=abs(contracts_n50),
            quantized_lots=abs(lots_n50),
            quantized_rupee_delta=round(exec_rupee_n50, 2),
            residual_rupee_delta=round(res_rupee_n50, 2),
        )

        total_exec_rupee = exec_rupee_bn + exec_rupee_n50
        total_res_rupee = target_rupee_delta - total_exec_rupee
        denom = abs(target_rupee_delta)
        tracking_error = abs(total_res_rupee) / denom if denom > 1e-6 else 0.0

        reason = (
            f"Cross-hedge rebalance executed ({regime.value}): target rupee delta {target_rupee_delta:.0f}, "
            f"BN={contracts_bn} contracts ({lots_bn} lots), N50={contracts_n50} contracts ({lots_n50} lots). "
            f"Residual {total_res_rupee:.0f} INR ({tracking_error * 100.0:.2f}% tracking error)."
        )

        return CrossHedgeScalpDecision(
            regime=regime,
            alpha_bank_nifty=alpha_bn,
            alpha_nifty_50=alpha_n50,
            delta_tolerance=tolerance,
            vpin_joint=round(vpin_joint, 4),
            rho_toxic=round(rho_toxic, 4),
            target_rupee_delta=round(target_rupee_delta, 2),
            executed_rupee_delta=round(total_exec_rupee, 2),
            residual_rupee_delta=round(total_res_rupee, 2),
            tracking_error_ratio=round(tracking_error, 4),
            is_freeze_active=is_freeze,
            should_rebalance=True,
            legs=(leg_bn, leg_n50),
            timestamp=float(timestamp),
            reason=reason,
        )


# Backward-compatibility aliases
CrossHedgeDecision = CrossHedgeScalpDecision
CrossHedgeRegime = ScalpRegime
ElasticityCrossHedgeScalperEngine = ElasticityCrossHedgeScalper
PortfolioDeltaState = ScalpOrderLeg

__all__ = [
    "ScalpRegime",
    "ElasticityParams",
    "TransactionCostParams",
    "ToxicityParams",
    "ScalpOrderLeg",
    "CrossHedgeScalpDecision",
    "ElasticityCrossHedgeScalper",
    "CrossHedgeDecision",
    "CrossHedgeRegime",
    "ElasticityCrossHedgeScalperEngine",
    "PortfolioDeltaState",
]

