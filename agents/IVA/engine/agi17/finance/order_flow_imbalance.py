"""AGI 1.7 Order Flow Imbalance (OFI) & Microstructure Pressure Engine for BANK NIFTY Options.

TASK-BN-21:
Implements the foundational market microstructure framework of Cont, Kukanov, and Stoikov (2014):
"The Price Impact of Order Book Events", Journal of Financial Econometrics.

Provides:
1. Level-1 Order Flow Imbalance (OFI):
   OFI_t = I_{P_b,t >= P_b,t-1} * q_b,t - I_{P_b,t <= P_b,t-1} * q_b,t-1
         - I_{P_a,t <= P_a,t-1} * q_a,t + I_{P_a,t >= P_a,t-1} * q_a,t-1
2. Multi-Level OFI (MLOFI):
   Weighted aggregation across top-5 order book depth levels with harmonic weights w_k = 1/k.
3. Normalized OFI Ratio in [-1.0, +1.0]:
   OFI_Ratio = MLOFI / Total_Depth_Volume
4. Microstructure Price Impact Predictor:
   Delta P_pred = beta_OFI * OFI_t, where beta_OFI = 1.0 / Market_Depth
5. Pre-Trade Breakout Confirmation Filter:
   Detects false breakouts (absorption traps) when price direction contradicts institutional OFI.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from typing import Any, Dict, List, Optional

from .order_book_simulator import BookLevel, SimulatedOrderBook


class OFISignalRegime(enum.Enum):
    """Classification of order flow pressure regime."""

    STRONG_BUY_PRESSURE = "STRONG_BUY_PRESSURE"      # Ratio >= +0.40
    MODERATE_BUY_PRESSURE = "MODERATE_BUY_PRESSURE"  # +0.15 <= Ratio < +0.40
    NEUTRAL_BALANCED = "NEUTRAL_BALANCED"            # -0.15 < Ratio < +0.15
    MODERATE_SELL_PRESSURE = "MODERATE_SELL_PRESSURE"# -0.40 < Ratio <= -0.15
    STRONG_SELL_PRESSURE = "STRONG_SELL_PRESSURE"    # Ratio <= -0.40


@dataclasses.dataclass(frozen=True)
class LevelOFISnapshot:
    """OFI calculation at a specific depth level k."""

    level: int
    weight: float
    bid_flow: float
    ask_flow: float
    level_ofi: float


@dataclasses.dataclass(frozen=True)
class OFIMicrostructureReport:
    """Comprehensive Order Flow Imbalance and microstructure impact report."""

    symbol: str
    level_1_ofi: float
    multi_level_ofi: float
    total_depth_volume: int
    normalized_ofi_ratio: float
    regime: OFISignalRegime
    predicted_price_impact_pts: float
    estimated_beta: float
    is_breakout_confirmed: bool
    breakout_warning: Optional[str]
    level_breakdowns: list[LevelOFISnapshot]
    diagnostics: str


class OrderFlowImbalanceEngine:
    """Calculates Cont-Kukanov-Stoikov OFI and multi-level microstructure pressure."""

    STRONG_RATIO_THRESHOLD: float = 0.40
    MODERATE_RATIO_THRESHOLD: float = 0.15

    @classmethod
    def calculate_level_1_ofi(
        cls,
        prev_bid_price: float,
        prev_bid_units: int,
        curr_bid_price: float,
        curr_bid_units: int,
        prev_ask_price: float,
        prev_ask_units: int,
        curr_ask_price: float,
        curr_ask_units: int,
    ) -> float:
        """Computes canonical Level-1 OFI per Cont, Kukanov & Stoikov (2014) equation (1)."""
        # Bid contribution:
        # If P_b,t > P_b,t-1: +curr_bid_units (higher bid placed)
        # If P_b,t == P_b,t-1: +(curr_bid_units - prev_bid_units)
        # If P_b,t < P_b,t-1: -prev_bid_units (bid dropped)
        if curr_bid_price > prev_bid_price:
            bid_flow = float(curr_bid_units)
        elif curr_bid_price == prev_bid_price:
            bid_flow = float(curr_bid_units - prev_bid_units)
        else:
            bid_flow = -float(prev_bid_units)

        # Ask contribution:
        # If P_a,t < P_a,t-1: -curr_ask_units (aggressive seller placed lower ask)
        # If P_a,t == P_a,t-1: -(curr_ask_units - prev_ask_units) (ask size increase = negative flow)
        # If P_a,t > P_a,t-1: +prev_ask_units (ask lifted by buyer)
        if curr_ask_price < prev_ask_price:
            ask_flow = -float(curr_ask_units)
        elif curr_ask_price == prev_ask_price:
            ask_flow = -float(curr_ask_units - prev_ask_units)
        else:
            ask_flow = float(prev_ask_units)

        # Total Level-1 OFI = Bid Flow + Ask Flow
        return round(bid_flow + ask_flow, 4)

    @classmethod
    def evaluate_order_book_transition(
        cls,
        prev_book: SimulatedOrderBook,
        curr_book: SimulatedOrderBook,
        max_levels: int = 5,
        target_breakout_direction: Optional[str] = None,  # "BULLISH" or "BEARISH"
    ) -> OFIMicrostructureReport:
        """Evaluates OFI across full 5-level market depth transitions."""
        symbol = curr_book.symbol
        level_snaps: list[LevelOFISnapshot] = []

        total_weights = 0.0
        mlofi_sum = 0.0
        total_depth_units = 0

        # Compute level-by-level OFI
        k_levels = min(max_levels, len(curr_book.bids), len(curr_book.asks))
        k_levels = max(1, k_levels)

        # Compute harmonic weights w_k = 1/k
        weights = [1.0 / (k + 1) for k in range(k_levels)]
        weight_sum = sum(weights)
        norm_weights = [w / weight_sum for w in weights]

        for k in range(k_levels):
            w = norm_weights[k]

            prev_b = prev_book.bids[k] if k < len(prev_book.bids) else BookLevel(0.0, 0)
            curr_b = curr_book.bids[k] if k < len(curr_book.bids) else BookLevel(0.0, 0)
            prev_a = prev_book.asks[k] if k < len(prev_book.asks) else BookLevel(0.0, 0)
            curr_a = curr_book.asks[k] if k < len(curr_book.asks) else BookLevel(0.0, 0)

            total_depth_units += curr_b.units + curr_a.units

            # Level-k OFI
            if curr_b.price > prev_b.price:
                b_flow = float(curr_b.units)
            elif curr_b.price == prev_b.price:
                b_flow = float(curr_b.units - prev_b.units)
            else:
                b_flow = -float(prev_b.units)

            if curr_a.price < prev_a.price:
                a_flow = -float(curr_a.units)
            elif curr_a.price == prev_a.price:
                a_flow = -float(curr_a.units - prev_a.units)
            else:
                a_flow = float(prev_a.units)

            lvl_ofi = b_flow + a_flow
            mlofi_sum += w * lvl_ofi

            level_snaps.append(
                LevelOFISnapshot(
                    level=k + 1,
                    weight=round(w, 4),
                    bid_flow=round(b_flow, 2),
                    ask_flow=round(a_flow, 2),
                    level_ofi=round(lvl_ofi, 2),
                )
            )

        level_1_ofi = level_snaps[0].level_ofi if level_snaps else 0.0
        multi_level_ofi = round(mlofi_sum, 2)

        # Normalized OFI Ratio: MLOFI / Total Depth Units (bounded [-1.0, +1.0])
        safe_depth = max(1, total_depth_units)
        raw_ratio = multi_level_ofi / safe_depth
        norm_ratio = round(max(-1.0, min(1.0, raw_ratio)), 4)

        # Regime classification
        if norm_ratio >= cls.STRONG_RATIO_THRESHOLD:
            regime = OFISignalRegime.STRONG_BUY_PRESSURE
        elif norm_ratio >= cls.MODERATE_RATIO_THRESHOLD:
            regime = OFISignalRegime.MODERATE_BUY_PRESSURE
        elif norm_ratio <= -cls.STRONG_RATIO_THRESHOLD:
            regime = OFISignalRegime.STRONG_SELL_PRESSURE
        elif norm_ratio <= -cls.MODERATE_RATIO_THRESHOLD:
            regime = OFISignalRegime.MODERATE_SELL_PRESSURE
        else:
            regime = OFISignalRegime.NEUTRAL_BALANCED

        # Microstructure Price Impact Predictor:
        # Cont et al.: beta = 1 / Depth. Delta P = beta * OFI
        beta = round(1.0 / max(10.0, float(total_depth_units) / max(1, k_levels)), 6)
        pred_impact_pts = round(beta * multi_level_ofi, 4)

        # Breakout validation check
        is_breakout_confirmed = True
        warning = None

        if target_breakout_direction == "BULLISH":
            if norm_ratio < 0.0:
                is_breakout_confirmed = False
                warning = (
                    f"FALSE BREAKOUT WARNING: Price pushed higher but OFI is negative ({norm_ratio:+.2f}). "
                    "Indicates thin-book absorption or institutional distribution."
                )
        elif target_breakout_direction == "BEARISH":
            if norm_ratio > 0.0:
                is_breakout_confirmed = False
                warning = (
                    f"FALSE BREAKDOWN WARNING: Price pushed lower but OFI is positive ({norm_ratio:+.2f}). "
                    "Indicates aggressive dip-buying absorption."
                )

        diagnostics = (
            f"OFI Report for {symbol}: L1 OFI={level_1_ofi:+.1f}, MLOFI={multi_level_ofi:+.1f}, "
            f"Depth={total_depth_units} units, Ratio={norm_ratio:+.2f} ({regime.value}). "
            f"Pred Impact={pred_impact_pts:+.2f} pts."
        )

        return OFIMicrostructureReport(
            symbol=symbol,
            level_1_ofi=level_1_ofi,
            multi_level_ofi=multi_level_ofi,
            total_depth_volume=total_depth_units,
            normalized_ofi_ratio=norm_ratio,
            regime=regime,
            predicted_price_impact_pts=pred_impact_pts,
            estimated_beta=beta,
            is_breakout_confirmed=is_breakout_confirmed,
            breakout_warning=warning,
            level_breakdowns=level_snaps,
            diagnostics=diagnostics,
        )
