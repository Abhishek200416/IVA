"""Multi-Asset Cross-Asset VPIN & Adverse Selection Co-Toxicity Engine.

Synthesized in consultation with MiniMax M2.7 and DeepSeek V4 Flash:
1. Volume Bucket Synchronization:
   - Synchronized volume buckets across NIFTY 50 and BANK NIFTY options and futures.
   - Lee-Ready (1991) trade sign classification for high-frequency tick aggregation.
2. Cross-Asset VPIN & Toxicity Covariance:
   - Single-asset VPIN: VPIN_a = sum_{tau} |V_{tau}^B - V_{tau}^S| / (N * V_bar_a)
   - Bivariate order flow imbalance covariance: Gamma_12 = Cov(|O_1(tau)|, |O_2(tau)|)
   - Joint Toxicity Correlation: rho_toxic = Gamma_12 / sqrt(Var(|O_1|) * Var(|O_2|))
   - Contagion Spillover Index = max(0, rho_toxic) * sqrt(VPIN_1 * VPIN_2)
3. Joint Adverse Selection Circuit Breaker:
   - Macro Systemic Shock: When VPIN_1 >= 0.30, VPIN_2 >= 0.30, and rho_toxic >= 0.50:
     Triggers SHORT_GAMMA_FREEZE across both option chains, locking out short gamma writing.
   - Idiosyncratic Toxicity: When one asset's VPIN is elevated but correlation is low,
     freezes only the toxic leg while allowing writing on the calm asset.

Zero external dependencies outside standard library math and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ToxicityRegime(str, Enum):
    BENIGN_FLOW = "BENIGN_FLOW"
    IDIOSYNCRATIC_TOXICITY = "IDIOSYNCRATIC_TOXICITY"
    CONTAGION_RISK = "CONTAGION_RISK"
    MACRO_SYSTEMIC_SHOCK = "MACRO_SYSTEMIC_SHOCK"


@dataclass
class VolumeBucket:
    """A volume-synchronized bucket tracking buy and sell flow."""
    asset_name: str
    target_volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    start_timestamp: float = 0.0
    end_timestamp: float = 0.0

    @property
    def total_volume(self) -> float:
        return self.buy_volume + self.sell_volume

    @property
    def imbalance(self) -> float:
        """Signed order flow imbalance: V_buy - V_sell."""
        return self.buy_volume - self.sell_volume

    @property
    def absolute_imbalance(self) -> float:
        """Absolute imbalance |V_buy - V_sell|."""
        return abs(self.buy_volume - self.sell_volume)

    @property
    def is_full(self) -> bool:
        return self.total_volume >= (self.target_volume - 1e-9)


@dataclass(frozen=True)
class CoToxicityMetrics:
    """Result of cross-asset VPIN and toxicity co-movement estimation."""
    asset1_name: str
    asset2_name: str
    vpin_asset1: float
    vpin_asset2: float
    rho_toxic_correlation: float
    toxicity_covariance_gamma: float
    contagion_spillover_index: float
    regime: ToxicityRegime
    short_gamma_freeze_active: bool
    asset1_safe_for_writing: bool
    asset2_safe_for_writing: bool
    bucket_count_asset1: int
    bucket_count_asset2: int


class CrossAssetToxicityEngine:
    """Multi-Asset Cross-Asset VPIN & Adverse Selection Co-Toxicity Engine."""

    def __init__(
        self,
        asset1_name: str = "NIFTY50",
        asset2_name: str = "BANKNIFTY",
        bucket_size_asset1: float = 200.0,
        bucket_size_asset2: float = 100.0,
        window_bucket_count: int = 10,
        vpin_alert_threshold: float = 0.35,
        cotoxicity_alert_threshold: float = 0.50,
    ) -> None:
        self.asset1_name = str(asset1_name)
        self.asset2_name = str(asset2_name)
        self.bucket_size1 = float(bucket_size_asset1)
        self.bucket_size2 = float(bucket_size_asset2)
        self.window_count = int(window_bucket_count)
        self.vpin_alert_threshold = float(vpin_alert_threshold)
        self.cotoxicity_alert_threshold = float(cotoxicity_alert_threshold)

        # Active buckets
        self.active_bucket1 = VolumeBucket(self.asset1_name, self.bucket_size1)
        self.active_bucket2 = VolumeBucket(self.asset2_name, self.bucket_size2)

        # History of completed buckets
        self.buckets1: List[VolumeBucket] = []
        self.buckets2: List[VolumeBucket] = []

        # Last trade directions for tick rule
        self._last_direction1: Optional[str] = None
        self._last_direction2: Optional[str] = None

    def record_tick(
        self,
        asset: str,
        volume: float,
        price: float,
        prev_price: float,
        timestamp: float = 0.0,
    ) -> Optional[CoToxicityMetrics]:
        """Ingests a high-frequency trade tick and updates volume buckets.

        Returns updated CoToxicityMetrics whenever a volume bucket completes.
        """
        vol = float(volume)
        p = float(price)
        prev_p = float(prev_price)
        ts = float(timestamp)

        if asset == self.asset1_name:
            # Lee-Ready tick rule for asset 1
            if p > prev_p:
                direction = "BUY"
                self._last_direction1 = "BUY"
            elif p < prev_p:
                direction = "SELL"
                self._last_direction1 = "SELL"
            else:
                direction = self._last_direction1 if self._last_direction1 is not None else "NEUTRAL"

            completed = self._accumulate_volume(
                self.active_bucket1,
                self.buckets1,
                vol,
                direction,
                ts,
                self.bucket_size1,
            )
        elif asset == self.asset2_name:
            # Lee-Ready tick rule for asset 2
            if p > prev_p:
                direction = "BUY"
                self._last_direction2 = "BUY"
            elif p < prev_p:
                direction = "SELL"
                self._last_direction2 = "SELL"
            else:
                direction = self._last_direction2 if self._last_direction2 is not None else "NEUTRAL"

            completed = self._accumulate_volume(
                self.active_bucket2,
                self.buckets2,
                vol,
                direction,
                ts,
                self.bucket_size2,
            )
        else:
            raise ValueError(f"Unknown asset: {asset}")

        if completed and len(self.buckets1) > 0 and len(self.buckets2) > 0:
            return self.compute_cotoxicity_metrics()

        return None

    def _accumulate_volume(
        self,
        active: VolumeBucket,
        completed_list: List[VolumeBucket],
        volume: float,
        direction: str,
        timestamp: float,
        target_size: float,
    ) -> bool:
        """Accumulates trade volume into active bucket, rolling over if capacity reached."""
        rem_volume = volume
        completed_any = False

        while rem_volume > 0.0:
            space_left = active.target_volume - active.total_volume
            if space_left <= 0.0:
                active.end_timestamp = timestamp
                completed_list.append(active)
                completed_any = True
                # Reset active
                new_b = VolumeBucket(active.asset_name, target_size, start_timestamp=timestamp)
                if active is self.active_bucket1:
                    self.active_bucket1 = new_b
                    active = self.active_bucket1
                else:
                    self.active_bucket2 = new_b
                    active = self.active_bucket2
                space_left = target_size

            fill = min(rem_volume, space_left)
            if direction == "BUY":
                active.buy_volume += fill
            elif direction == "SELL":
                active.sell_volume += fill
            else:
                active.buy_volume += fill / 2.0
                active.sell_volume += fill / 2.0
            rem_volume -= fill

            if active.is_full:
                active.end_timestamp = timestamp
                completed_list.append(active)
                completed_any = True
                new_b = VolumeBucket(active.asset_name, target_size, start_timestamp=timestamp)
                if active is self.active_bucket1:
                    self.active_bucket1 = new_b
                    active = self.active_bucket1
                else:
                    self.active_bucket2 = new_b
                    active = self.active_bucket2

        return completed_any

    def compute_cotoxicity_metrics(self) -> CoToxicityMetrics:
        """Calculates VPINs, toxicity covariance Gamma, rho_toxic, and circuit breaker status."""
        w = self.window_count

        # Select window of completed buckets
        b1_win = self.buckets1[-w:] if self.buckets1 else [self.active_bucket1]
        b2_win = self.buckets2[-w:] if self.buckets2 else [self.active_bucket2]

        n1 = len(b1_win)
        n2 = len(b2_win)

        # Single-asset VPIN
        sum_abs_imb1 = sum(b.absolute_imbalance for b in b1_win)
        vpin1 = sum_abs_imb1 / (n1 * self.bucket_size1) if n1 > 0 else 0.0
        vpin1 = min(1.0, max(0.0, vpin1))

        sum_abs_imb2 = sum(b.absolute_imbalance for b in b2_win)
        vpin2 = sum_abs_imb2 / (n2 * self.bucket_size2) if n2 > 0 else 0.0
        vpin2 = min(1.0, max(0.0, vpin2))

        # Synchronize pairwise completed bucket imbalances for co-toxicity
        pair_len = min(n1, n2)
        if pair_len >= 3:
            s1 = b1_win[-pair_len:]
            s2 = b2_win[-pair_len:]
            imbs1 = [b.absolute_imbalance for b in s1]
            imbs2 = [b.absolute_imbalance for b in s2]

            mean1 = sum(imbs1) / pair_len
            mean2 = sum(imbs2) / pair_len

            cov = sum((x - mean1) * (y - mean2) for x, y in zip(imbs1, imbs2)) / pair_len
            var1 = sum((x - mean1) ** 2 for x in imbs1) / pair_len
            var2 = sum((y - mean2) ** 2 for y in imbs2) / pair_len

            non_zero_1 = sum(1 for x in imbs1 if abs(x) > 1e-6)
            non_zero_2 = sum(1 for y in imbs2 if abs(y) > 1e-6)

            if non_zero_1 >= 2 and non_zero_2 >= 2 and var1 > 1e-12 and var2 > 1e-12:
                rho = cov / math.sqrt(var1 * var2)
                rho = max(-1.0, min(1.0, rho))
            else:
                rho = 0.0
                cov = 0.0
        else:
            rho = 0.0
            cov = 0.0

        spillover = max(0.0, rho) * math.sqrt(vpin1 * vpin2)

        # Circuit Breaker & Regime Classification
        is_systemic = (
            vpin1 >= 0.30
            and vpin2 >= 0.30
            and rho >= self.cotoxicity_alert_threshold
        )

        if is_systemic:
            regime = ToxicityRegime.MACRO_SYSTEMIC_SHOCK
            freeze = True
            safe1 = False
            safe2 = False
        elif vpin1 >= self.vpin_alert_threshold or vpin2 >= self.vpin_alert_threshold:
            freeze = True
            safe1 = (vpin1 < self.vpin_alert_threshold)
            safe2 = (vpin2 < self.vpin_alert_threshold)
            regime = ToxicityRegime.CONTAGION_RISK if rho >= 0.30 else ToxicityRegime.IDIOSYNCRATIC_TOXICITY
        else:
            regime = ToxicityRegime.BENIGN_FLOW
            freeze = False
            safe1 = True
            safe2 = True

        return CoToxicityMetrics(
            asset1_name=self.asset1_name,
            asset2_name=self.asset2_name,
            vpin_asset1=round(vpin1, 4),
            vpin_asset2=round(vpin2, 4),
            rho_toxic_correlation=round(rho, 4),
            toxicity_covariance_gamma=round(cov, 4),
            contagion_spillover_index=round(spillover, 4),
            regime=regime,
            short_gamma_freeze_active=freeze,
            asset1_safe_for_writing=safe1,
            asset2_safe_for_writing=safe2,
            bucket_count_asset1=len(self.buckets1),
            bucket_count_asset2=len(self.buckets2),
        )
