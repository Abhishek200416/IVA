"""Asynchronous Cross-Asset Lead-Lag Arbitrage Engine.

Wave 34 Deliverable (TASK-BN-44):
Synthesized in continuous consultation with external quantitative models:
1. Microstructure Foundation:
   - High-frequency prices between Bank Nifty and Nifty 50 arrive at non-synchronous,
     irregular intervals. Standard Pearson correlation suffers from the Epps effect
     (attenuation toward zero at ultra-short horizons).
   - Hayashi-Yoshida (2005) continuous-time covariance estimator evaluates cross-asset
     co-movements across overlapping tick intervals:
     Cov_HY(tau) = sum_{i, j} Delta P_1(i) * Delta P_2(j) * 1_{ [s_{i-1}, s_i] cap [t_{j-1}+tau, t_j+tau] neq emptyset }
2. Lead-Lag Asymmetry & Horizon Optimization:
   - Evaluates correlation across tau in [-T, +T] to find peak lag tau*:
     tau* = argmax_tau |rho_HY(tau)|
   - tau* > 0: Asset 1 leads Asset 2 by tau* seconds.
   - tau* < 0: Asset 2 leads Asset 1 by |tau*| seconds.
3. Cross-Asset Beta & Predictive Signal Spread:
   - High-frequency beta: beta_12 = Cov_HY(tau*) / Var(Delta P_lead)
   - Expected lagging asset catch-up move: Delta P_hat_lag = beta_12 * Delta P_lead
   - Arbitrage Signal Spread: S(t) = Delta P_hat_lag - Delta P_lag_current
4. Friction Barrier & Indian Statutory Lot Enforcement:
   - Gross Edge = |S(t)| * Lots * LotSize
   - Hurdle = Crossing friction (spread_bps) + Indian statutory charges (STT, GST, SEBI, Stamp).
   - Hard execution gate: Net Edge >= min_net_edge_inr.
   - Integer lot quantization: Bank Nifty = 15 contracts, Nifty 50 = 25 contracts.

Zero external dependencies outside standard library math, dataclasses, and typing.
Reuses HayashiYoshidaEstimator, MarketIndex, and AsynchronousTick from cross_impact_matrix.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .cross_impact_matrix import (
    AsynchronousTick,
    HayashiYoshidaEstimator,
    LeadLagPeak,
    MarketIndex,
)


class ArbitrageAction(str, Enum):
    """Actionable direction on the lagging asset."""
    BUY_LAGGING = "BUY_LAGGING"      # Lagging asset is underpriced relative to leader move
    SELL_LAGGING = "SELL_LAGGING"    # Lagging asset is overpriced relative to leader move
    HOLD_NEUTRAL = "HOLD_NEUTRAL"    # Discrepancy within noise or friction barrier


class ArbitrageExecutionStatus(str, Enum):
    """Execution status for lead-lag arbitrage."""
    SIGNAL_TRIGGERED = "SIGNAL_TRIGGERED"
    FRICTION_BARRIER_REJECTED = "FRICTION_BARRIER_REJECTED"
    CONFIDENCE_TOO_LOW = "CONFIDENCE_TOO_LOW"
    CAPITAL_INSUFFICIENT = "CAPITAL_INSUFFICIENT"


@dataclass(frozen=True)
class LeadLagArbitrageSignal:
    """Predictive statistical lead-lag discrepancy signal."""
    leading_asset: MarketIndex
    lagging_asset: MarketIndex
    optimal_lag_seconds: float
    peak_correlation: float
    high_freq_beta: float
    leader_recent_move: float
    lagging_recent_move: float
    forecasted_lagging_move: float
    signal_spread_pts: float
    action: ArbitrageAction
    is_statistically_significant: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "leading_asset": self.leading_asset.value,
            "lagging_asset": self.lagging_asset.value,
            "optimal_lag_seconds": round(self.optimal_lag_seconds, 3),
            "peak_correlation": round(self.peak_correlation, 4),
            "high_freq_beta": round(self.high_freq_beta, 4),
            "leader_recent_move": round(self.leader_recent_move, 2),
            "lagging_recent_move": round(self.lagging_recent_move, 2),
            "forecasted_lagging_move": round(self.forecasted_lagging_move, 2),
            "signal_spread_pts": round(self.signal_spread_pts, 2),
            "action": self.action.value,
            "is_significant": self.is_statistically_significant,
        }


@dataclass(frozen=True)
class ArbitrageOrderLeg:
    """Order specification for the lagging asset catch-up trade."""
    target_asset: MarketIndex
    action: str  # "BUY" or "SELL"
    lot_size: int
    lots: int
    contracts: int
    current_price: float
    expected_exit_price: float
    gross_edge_inr: float
    friction_cost_inr: float
    net_edge_inr: float
    time_to_live_seconds: float


@dataclass(frozen=True)
class LeadLagArbitrageExecution:
    """Execution decision report for the lead-lag trade."""
    timestamp: float
    signal: LeadLagArbitrageSignal
    status: ArbitrageExecutionStatus
    order_leg: Optional[ArbitrageOrderLeg]
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "signal": self.signal.to_dict(),
            "status": self.status.value,
            "order_leg": (
                {
                    "target_asset": self.order_leg.target_asset.value,
                    "action": self.order_leg.action,
                    "lots": self.order_leg.lots,
                    "contracts": self.order_leg.contracts,
                    "current_price": round(self.order_leg.current_price, 2),
                    "expected_exit": round(self.order_leg.expected_exit_price, 2),
                    "gross_edge_inr": round(self.order_leg.gross_edge_inr, 2),
                    "friction_cost_inr": round(self.order_leg.friction_cost_inr, 2),
                    "net_edge_inr": round(self.order_leg.net_edge_inr, 2),
                    "ttl_seconds": round(self.order_leg.time_to_live_seconds, 2),
                }
                if self.order_leg
                else None
            ),
            "notes": self.notes,
        }


class AsynchronousLeadLagArbitrageEngine:
    """Institutional Asynchronous Hayashi-Yoshida Lead-Lag Arbitrage Engine.

    Identifies lead-lag transmission between Bank Nifty and Nifty 50, models expected
    catch-up price jumps, and executes discrete lot-quantized arbitrage orders when
    expected edge exceeds total market friction.
    """

    def __init__(
        self,
        min_correlation_threshold: float = 0.40,
        min_net_edge_inr: float = 150.0,
        spread_bps_friction: float = 2.0,
        statutory_rate: float = 0.0006,
        max_lots: int = 10,
        half_life_multiplier: float = 1.5,
    ) -> None:
        if not (0.10 <= min_correlation_threshold <= 0.95):
            raise ValueError("min_correlation_threshold must be in [0.10, 0.95].")
        if min_net_edge_inr < 0.0:
            raise ValueError("min_net_edge_inr must be non-negative.")
        if max_lots < 1:
            raise ValueError("max_lots must be at least 1.")

        self.min_correlation_threshold = min_correlation_threshold
        self.min_net_edge_inr = min_net_edge_inr
        self.spread_bps_friction = spread_bps_friction
        self.statutory_rate = statutory_rate
        self.max_lots = max_lots
        self.half_life_multiplier = half_life_multiplier

    @staticmethod
    def get_lot_size(index: MarketIndex) -> int:
        """NSE discrete lot size."""
        if index == MarketIndex.BANK_NIFTY:
            return 15
        elif index == MarketIndex.NIFTY_50:
            return 25
        raise ValueError(f"Unknown index {index}")

    def evaluate_signal(
        self,
        nifty_ticks: Sequence[AsynchronousTick],
        bank_ticks: Sequence[AsynchronousTick],
        lag_grid_seconds: Optional[Sequence[float]] = None,
        lookback_ticks: int = 5,
    ) -> LeadLagArbitrageSignal:
        """Scan asynchronous ticks, estimate peak lead-lag correlation, and derive signal."""
        if not nifty_ticks or not bank_ticks:
            raise ValueError("Tick series must not be empty.")

        if lag_grid_seconds is None:
            # Default lag grid: -3.0s to +3.0s in 0.5s increments
            lag_grid_seconds = [round(x * 0.5, 1) for x in range(-6, 7)]

        peak = HayashiYoshidaEstimator.analyze_lead_lag_profile(
            list(nifty_ticks), list(bank_ticks), list(lag_grid_seconds)
        )

        leading_asset = peak.leading_asset
        lagging_asset = peak.lagging_asset
        optimal_lag = peak.optimal_lag_seconds
        peak_corr = peak.max_correlation

        # Determine leader and lagging series
        if leading_asset == MarketIndex.NIFTY_50:
            lead_series = nifty_ticks
            lag_series = bank_ticks
        else:
            lead_series = bank_ticks
            lag_series = nifty_ticks

        # High-frequency beta: beta = Cov_HY(tau*) / Var(lead)
        cov_opt = HayashiYoshidaEstimator.calculate_cross_covariance(
            list(nifty_ticks), list(bank_ticks), optimal_lag
        )
        lead_var = sum(t.price_change ** 2 for t in lead_series)
        if lead_var < 1e-12:
            beta = 1.0
        else:
            beta = cov_opt / lead_var

        # Recent price changes over last lookback_ticks
        k = max(1, min(lookback_ticks, len(lead_series), len(lag_series)))
        recent_lead_move = sum(lead_series[-i].price_change for i in range(1, k + 1))
        recent_lag_move = sum(lag_series[-i].price_change for i in range(1, k + 1))

        # Expected move on lagging asset
        forecasted_lag_move = beta * recent_lead_move
        spread_pts = forecasted_lag_move - recent_lag_move

        # Directional action
        # If correlation is below threshold or statistically insignificant -> NEUTRAL
        if (
            abs(peak_corr) < self.min_correlation_threshold
            or not peak.is_statistically_significant
            or abs(spread_pts) < 0.10
        ):
            action = ArbitrageAction.HOLD_NEUTRAL
        elif spread_pts > 0:
            action = ArbitrageAction.BUY_LAGGING
        else:
            action = ArbitrageAction.SELL_LAGGING

        return LeadLagArbitrageSignal(
            leading_asset=leading_asset,
            lagging_asset=lagging_asset,
            optimal_lag_seconds=optimal_lag,
            peak_correlation=peak_corr,
            high_freq_beta=beta,
            leader_recent_move=recent_lead_move,
            lagging_recent_move=recent_lag_move,
            forecasted_lagging_move=forecasted_lag_move,
            signal_spread_pts=spread_pts,
            action=action,
            is_statistically_significant=peak.is_statistically_significant,
        )

    def generate_arbitrage_orders(
        self,
        signal: LeadLagArbitrageSignal,
        current_lagging_price: float,
        available_capital_inr: float = 500000.0,
        timestamp: float = 0.0,
    ) -> LeadLagArbitrageExecution:
        """Evaluate economic friction and construct lot-aligned order."""
        if current_lagging_price <= 0.0:
            raise ValueError("Current lagging price must be strictly positive.")

        if signal.action == ArbitrageAction.HOLD_NEUTRAL:
            return LeadLagArbitrageExecution(
                timestamp=timestamp,
                signal=signal,
                status=ArbitrageExecutionStatus.CONFIDENCE_TOO_LOW,
                order_leg=None,
                notes="Signal is neutral or correlation below minimum significance threshold.",
            )

        lot_size = self.get_lot_size(signal.lagging_asset)
        notional_per_lot = current_lagging_price * lot_size

        # Capital check: at least 1 lot margin (~15% of notional)
        margin_per_lot = notional_per_lot * 0.15
        if available_capital_inr < margin_per_lot:
            return LeadLagArbitrageExecution(
                timestamp=timestamp,
                signal=signal,
                status=ArbitrageExecutionStatus.CAPITAL_INSUFFICIENT,
                order_leg=None,
                notes=f"Insufficient capital {available_capital_inr:.2f} for margin {margin_per_lot:.2f}",
            )

        # Lot calculation based on capital and max_lots
        affordable_lots = int(available_capital_inr // margin_per_lot)
        lots = max(1, min(self.max_lots, affordable_lots))
        contracts = lots * lot_size

        pts_edge = abs(signal.signal_spread_pts)
        gross_edge_inr = pts_edge * contracts

        # Economic friction: 2-way spread crossing + statutory charges
        # friction_rate = 2 * (spread_bps / 10000) + statutory_rate
        round_trip_friction_rate = (2.0 * (self.spread_bps_friction / 10000.0)) + self.statutory_rate
        friction_cost_inr = notional_per_lot * lots * round_trip_friction_rate
        net_edge_inr = gross_edge_inr - friction_cost_inr

        # Time to live: half_life_multiplier * |optimal_lag|
        ttl = max(1.0, abs(signal.optimal_lag_seconds) * self.half_life_multiplier)

        # Expected exit price
        if signal.action == ArbitrageAction.BUY_LAGGING:
            action_str = "BUY"
            expected_exit = current_lagging_price + pts_edge
        else:
            action_str = "SELL"
            expected_exit = current_lagging_price - pts_edge

        order_leg = ArbitrageOrderLeg(
            target_asset=signal.lagging_asset,
            action=action_str,
            lot_size=lot_size,
            lots=lots,
            contracts=contracts,
            current_price=current_lagging_price,
            expected_exit_price=expected_exit,
            gross_edge_inr=gross_edge_inr,
            friction_cost_inr=friction_cost_inr,
            net_edge_inr=net_edge_inr,
            time_to_live_seconds=ttl,
        )

        if net_edge_inr < self.min_net_edge_inr:
            return LeadLagArbitrageExecution(
                timestamp=timestamp,
                signal=signal,
                status=ArbitrageExecutionStatus.FRICTION_BARRIER_REJECTED,
                order_leg=order_leg,
                notes=f"Net edge {net_edge_inr:.2f} INR below hurdle {self.min_net_edge_inr:.2f} INR.",
            )

        return LeadLagArbitrageExecution(
            timestamp=timestamp,
            signal=signal,
            status=ArbitrageExecutionStatus.SIGNAL_TRIGGERED,
            order_leg=order_leg,
            notes=f"Lead-lag trade triggered: {action_str} {lots} lots ({contracts} contracts) of {signal.lagging_asset.value}.",
        )
