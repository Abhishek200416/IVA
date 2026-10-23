"""Kyle-Obizhaeva (2016) Market Microstructure Invariance & Volume Micro-Clustering Engine.

Implements Albert Kyle & Anna Obizhaeva (2016) 'Market Microstructure Invariance'
principles and dimensional scaling relations for high-frequency algorithmic execution:
1. Invariance Scaling Relations:
   - Dollar volatility: W = P * V * sigma (where P = price, V = volume in shares/contracts, sigma = returns volatility).
   - Business time transaction rate: N ~ (P * V * sigma)^(2/3) / gamma_0
   - Average bet size (metaorder size): Q_bar ~ V / N = V^(1/3) * (P * sigma)^(-2/3) * gamma_0
   - Price impact / transaction cost per dollar: Cost_$ ~ sigma * V^(-1/3) * (P * sigma)^(-1/3) = (sigma / P^(1/3)) * V^(-1/3)
2. Metaorder Segmentation & Child Order Slicing:
   - Parent order quantity X mapped into dimensionless bet units: x_tilde = X / Q_bar
   - Child order clips dynamically sized proportional to Q_bar and volatility regime.
   - Bank Nifty options constraints: contract lot size = 15, tick size = 0.05.
3. Volume Micro-Clustering Detection:
   - High-frequency volume intensity tracking relative to baseline.
   - Burst identification when empirical arrival rates deviate from Poisson baseline.
   - Adaptive routing switch: Passive post-only slicing under clustering surges to avoid adverse selection.

Zero external dependencies outside standard math and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class InvarianceRegime(str, Enum):
    NORMAL = "NORMAL"
    MICRO_CLUSTERED = "MICRO_CLUSTERED"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    ILLIQUID = "ILLIQUID"


@dataclass(frozen=True)
class InvarianceMetrics:
    """Calculated Kyle-Obizhaeva (2016) invariance dimensions."""
    price: float
    volume: float
    volatility: float  # annualized or per-period return standard deviation
    dollar_volatility: float  # W = P * V * sigma
    transaction_rate_N: float  # expected trade event frequency
    average_bet_size_Q: float  # Q_bar = V / N
    normalized_bet_size: float  # X / Q_bar for a given metaorder
    expected_cost_bps: float  # Basis points transaction cost
    business_time_ratio: float  # business clock dt* vs calendar clock dt
    regime: InvarianceRegime


@dataclass
class ChildClipOrder:
    """A sliced child execution clip generated from metaorder."""
    clip_index: int
    quantity_contracts: int
    lots: int
    projected_delay_seconds: float
    urgency_weight: float
    order_type: str  # "LIMIT_PASSIVE" or "LIMIT_CROSSING"
    limit_price: float
    expected_impact_bps: float


@dataclass
class MicroClusterState:
    """Rolling volume micro-clustering state."""
    rolling_volume: float = 0.0
    rolling_time_window: float = 60.0
    baseline_intensity: float = 1.0
    current_intensity: float = 1.0
    clustering_ratio: float = 1.0
    cluster_detected: bool = False
    last_update_timestamp: float = 0.0


class KyleObizhaevaInvarianceEngine:
    """Albert Kyle & Anna Obizhaeva (2016) Microstructure Invariance Engine.
    
    Provides mathematically invariant scaling of order sizes, trading velocity,
    transaction costs, and metaorder child-clipping for Bank Nifty options and futures.
    """

    def __init__(
        self,
        base_gamma_0: float = 1.0,
        lot_size: int = 15,
        tick_size: float = 0.05,
        cluster_threshold: float = 2.25,
        min_clip_lots: int = 1,
        max_clip_lots: int = 20,
    ) -> None:
        """Initialize Kyle-Obizhaeva engine.
        
        Args:
            base_gamma_0: Empirical invariant constant (typically calibrated to asset class).
            lot_size: Bank Nifty options lot size (15 contracts).
            tick_size: Minimum tick increment on NSE (0.05 INR).
            cluster_threshold: Ratio of instantaneous intensity to baseline for clustering.
            min_clip_lots: Minimum lots per child order (1 lot = 15 contracts).
            max_clip_lots: Maximum lots per child order to avoid market impact.
        """
        self.base_gamma_0 = max(1e-4, float(base_gamma_0))
        self.lot_size = max(1, int(lot_size))
        self.tick_size = max(0.01, float(tick_size))
        self.cluster_threshold = max(1.1, float(cluster_threshold))
        self.min_clip_lots = max(1, int(min_clip_lots))
        self.max_clip_lots = max(self.min_clip_lots, int(max_clip_lots))

        # Internal clustering monitor
        self.cluster_state = MicroClusterState()

    def compute_invariance_metrics(
        self,
        price: float,
        daily_volume: float,
        volatility: float,
        metaorder_size: float = 15.0,
    ) -> InvarianceMetrics:
        """Compute Kyle-Obizhaeva invariance fundamental scaling dimensions.
        
        Args:
            price: Asset or option price (INR).
            daily_volume: Daily traded volume in units/contracts.
            volatility: Annualized or daily return volatility (sigma).
            metaorder_size: Size of parent order in contracts.
            
        Returns:
            InvarianceMetrics dataclass with all invariant parameters.
        """
        p = max(0.05, float(price))
        v = max(1.0, float(daily_volume))
        sig = max(1e-5, float(volatility))
        order_sz = max(1.0, float(metaorder_size))

        # 1. Dollar Volatility: W = P * V * sigma
        w = p * v * sig

        # 2. Transaction Rate N ~ (W)^(2/3) * gamma_0
        # Dimensionless trading velocity in business time
        n_rate = (w ** (2.0 / 3.0)) * self.base_gamma_0
        n_rate = max(1.0, n_rate)

        # 3. Average Bet Size Q_bar = V / N ~ V^(1/3) * (P * sigma)^(-2/3)
        q_bar = v / n_rate
        q_bar = max(1.0, q_bar)

        # 4. Normalized Bet Size: x_tilde = X / Q_bar
        norm_bet = order_sz / q_bar

        # 5. Invariance Expected Cost (bps):
        # Transaction cost scales as Cost_$ ~ sigma * V^(-1/3)
        # Normalized as bps of trade value
        raw_cost = sig * (v ** (-1.0 / 3.0))
        # Scaled to basis points (1 bp = 0.0001)
        cost_bps = raw_cost * 10000.0

        # 6. Business Time Rate: dt* / dt = (V * sigma)^(2/3) normalized
        # Baseline reference volume of 100,000 contracts and 0.15 vol
        ref_w = 49000.0 * 100000.0 * 0.15
        business_ratio = max(0.1, min(10.0, (w / ref_w) ** (2.0 / 3.0)))

        # Determine regime
        if self.cluster_state.cluster_detected:
            regime = InvarianceRegime.MICRO_CLUSTERED
        elif sig > 0.35:
            regime = InvarianceRegime.HIGH_VOLATILITY
        elif v < 1000.0:
            regime = InvarianceRegime.ILLIQUID
        else:
            regime = InvarianceRegime.NORMAL

        return InvarianceMetrics(
            price=p,
            volume=v,
            volatility=sig,
            dollar_volatility=w,
            transaction_rate_N=n_rate,
            average_bet_size_Q=q_bar,
            normalized_bet_size=norm_bet,
            expected_cost_bps=cost_bps,
            business_time_ratio=business_ratio,
            regime=regime,
        )

    def update_volume_clustering(
        self,
        interval_volume: float,
        interval_seconds: float,
    ) -> MicroClusterState:
        """Update volume micro-clustering tracker with recent tick/candle flow.
        
        Args:
            interval_volume: Volume traded in the interval.
            interval_seconds: Duration of the interval in seconds.
            
        Returns:
            Updated MicroClusterState.
        """
        dt = max(0.1, float(interval_seconds))
        vol = max(0.0, float(interval_volume))

        # Instantaneous volume intensity (contracts per second)
        inst_intensity = vol / dt

        # Update exponential rolling baseline (half-life ~ 60s)
        alpha = 1.0 - math.exp(-dt / 60.0)
        self.cluster_state.baseline_intensity = (
            (1.0 - alpha) * self.cluster_state.baseline_intensity
            + alpha * inst_intensity
        )
        self.cluster_state.baseline_intensity = max(0.01, self.cluster_state.baseline_intensity)

        self.cluster_state.current_intensity = inst_intensity
        ratio = inst_intensity / self.cluster_state.baseline_intensity
        self.cluster_state.clustering_ratio = ratio
        self.cluster_state.cluster_detected = ratio >= self.cluster_threshold

        return self.cluster_state

    def segment_metaorder(
        self,
        parent_lots: int,
        mid_price: float,
        daily_volume: float,
        volatility: float,
        side: str = "BUY",
        max_duration_seconds: float = 300.0,
    ) -> List[ChildClipOrder]:
        """Segment a parent metaorder into invariant child order clips.
        
        Uses Kyle-Obizhaeva invariance to determine the optimal number and sizes
        of child clips based on average bet size Q_bar and current clustering regime.
        
        Args:
            parent_lots: Number of Bank Nifty option lots (each lot = 15 contracts).
            mid_price: Current mid price of the option or future.
            daily_volume: Total daily volume of the instrument.
            volatility: Instrument returns volatility.
            side: "BUY" or "SELL".
            max_duration_seconds: Target total execution window.
            
        Returns:
            List of ChildClipOrder objects.
        """
        lots = max(1, int(parent_lots))
        total_contracts = lots * self.lot_size
        p = max(0.05, float(mid_price))

        metrics = self.compute_invariance_metrics(
            price=p,
            daily_volume=daily_volume,
            volatility=volatility,
            metaorder_size=float(total_contracts),
        )

        # Base optimal clip size in contracts ~ min(Q_bar, max_clip_lots * lot_size)
        base_clip_contracts = max(
            self.min_clip_lots * self.lot_size,
            min(metrics.average_bet_size_Q, self.max_clip_lots * self.lot_size),
        )
        # Convert to whole lots
        base_clip_lots = max(self.min_clip_lots, int(round(base_clip_contracts / self.lot_size)))
        base_clip_lots = min(self.max_clip_lots, base_clip_lots)

        # Micro-clustering adjustment: Under clustering, reduce clip size and use passive orders
        is_clustered = self.cluster_state.cluster_detected or metrics.regime == InvarianceRegime.MICRO_CLUSTERED
        if is_clustered:
            # Throttle clip size by 50% to prevent adverse selection
            clip_lots_target = max(self.min_clip_lots, base_clip_lots // 2)
            default_order_type = "LIMIT_PASSIVE"
        else:
            clip_lots_target = base_clip_lots
            default_order_type = "LIMIT_PASSIVE" if metrics.normalized_bet_size > 1.5 else "LIMIT_CROSSING"

        # Partition parent lots into child clips
        remaining_lots = lots
        clips: List[ChildClipOrder] = []
        clip_idx = 0
        cumulative_delay = 0.0

        # Time pacing inversely proportional to business time clock ratio
        base_interval = max_duration_seconds / max(1.0, (lots / clip_lots_target))
        adjusted_interval = base_interval / metrics.business_time_ratio

        while remaining_lots > 0:
            current_clip_lots = min(remaining_lots, clip_lots_target)
            current_contracts = current_clip_lots * self.lot_size

            # Invariant price impact for this clip
            # Impact bps ~ Cost_bps * (clip_contracts / Q_bar)^0.5
            clip_impact = metrics.expected_cost_bps * math.sqrt(
                current_contracts / max(1.0, metrics.average_bet_size_Q)
            )

            # Limit price calculation aligned to tick size (0.05)
            if side.upper() == "BUY":
                if default_order_type == "LIMIT_PASSIVE":
                    # Bid slightly inside/at current mid
                    limit_raw = p - (self.tick_size if not is_clustered else 2 * self.tick_size)
                else:
                    limit_raw = p + self.tick_size
            else:
                if default_order_type == "LIMIT_PASSIVE":
                    limit_raw = p + (self.tick_size if not is_clustered else 2 * self.tick_size)
                else:
                    limit_raw = p - self.tick_size

            limit_aligned = self._align_to_tick(limit_raw)

            urgency = 1.0 - (remaining_lots / lots) * 0.3

            clips.append(
                ChildClipOrder(
                    clip_index=clip_idx,
                    quantity_contracts=current_contracts,
                    lots=current_clip_lots,
                    projected_delay_seconds=round(cumulative_delay, 2),
                    urgency_weight=round(urgency, 3),
                    order_type=default_order_type,
                    limit_price=limit_aligned,
                    expected_impact_bps=round(clip_impact, 2),
                )
            )

            remaining_lots -= current_clip_lots
            clip_idx += 1
            cumulative_delay += adjusted_interval

        return clips

    def _align_to_tick(self, price: float) -> float:
        """Align price strictly to exchange tick size (0.05 paise divisibility)."""
        paise = round(price * 100.0)
        tick_paise = round(self.tick_size * 100.0)
        remainder = paise % tick_paise
        if remainder != 0:
            if remainder >= tick_paise / 2.0:
                paise += tick_paise - remainder
            else:
                paise -= remainder
        return round(paise / 100.0, 2)


__all__ = [
    "InvarianceRegime",
    "InvarianceMetrics",
    "ChildClipOrder",
    "MicroClusterState",
    "KyleObizhaevaInvarianceEngine",
]
