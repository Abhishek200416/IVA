"""AGI 1.7 Real-Time Market Depth Streaming Adapter & VPIN Microstructure Engine.

TASK-BN-24:
Implements institutional high-frequency streaming market depth observation and
Volume-Synchronized Probability of Toxicity (VPIN - Easley, Lopez de Prado, O'Hara, 2012).

Provides:
1. High-Frequency Market Depth Ingestion:
   Processes streaming 5-level order book depth snapshots and executed trades.
2. Micro-Price Calculation (Stoikov, 2018):
   P_micro = P_mid + 0.5 * (P_ask - P_bid) * (Q_bid - Q_ask) / (Q_bid + Q_ask)
3. Volume-Synchronized Probability of Toxicity (VPIN):
   VPIN = sum(|V_tau^B - V_tau^S|) / (N * V)
   where trade volume is discretized into equal-volume buckets and classified
   into buyer-initiated vs seller-initiated volume using the Lee-Ready (1991) tick rule.
4. Option Writing Toxicity Guardrail:
   Automatically flags HIGH_TOXIC_FLOW and halts short option writing / theta harvesting
   when VPIN breaches statistical risk thresholds (protecting against adverse selection).
5. Deterministic Playback & Event Stream Processing.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OrderSide
from .order_book_simulator import BookLevel, SimulatedOrderBook


class ToxicityRegime(enum.Enum):
    """Classification of institutional order flow toxicity."""

    LOW_TOXICITY = "LOW_TOXICITY"              # VPIN < 0.20 (Benign retail/balanced flow)
    MODERATE_TOXICITY = "MODERATE_TOXICITY"    # 0.20 <= VPIN < 0.35 (Normal market activity)
    HIGH_TOXIC_FLOW = "HIGH_TOXIC_FLOW"        # 0.35 <= VPIN < 0.45 (Informed institutional pressure)
    EXTREME_TOXICITY_HALT = "EXTREME_TOXICITY_HALT"  # VPIN >= 0.45 (Severe adverse selection risk)


@dataclasses.dataclass(frozen=True)
class TradeTick:
    """Single executed trade event."""

    timestamp_iso: str
    price: float
    units: int
    side: Optional[OrderSide] = None


@dataclasses.dataclass(frozen=True)
class MarketDepthTick:
    """Full 5-level market depth snapshot event."""

    timestamp_iso: str
    symbol: str
    bids: List[BookLevel]
    asks: List[BookLevel]
    last_trade: Optional[TradeTick] = None


@dataclasses.dataclass
class VolumeBucket:
    """Fixed-volume bucket for VPIN toxicity measurement."""

    bucket_id: int
    bucket_capacity_units: int
    accumulated_units: int = 0
    buy_units: float = 0.0
    sell_units: float = 0.0
    is_filled: bool = False


@dataclasses.dataclass(frozen=True)
class MicrostructureMetrics:
    """Instantaneous market microstructure health and toxicity indicators."""

    timestamp_iso: str
    symbol: str
    mid_price: float
    micro_price: float
    spread: float
    spread_bps: float
    total_depth_bids: int
    total_depth_asks: int
    liquidity_imbalance_ratio: float  # (Q_bid - Q_ask) / (Q_bid + Q_ask) in [-1.0, +1.0]
    current_vpin: float               # Volume-Synchronized Probability of Toxicity
    toxicity_regime: ToxicityRegime
    is_safe_for_writing: bool         # False when VPIN >= 0.35 to avoid adverse selection
    total_volume_processed: int
    diagnostics: str

    @property
    def vpin(self) -> float:
        return self.current_vpin


class StreamingMarketDepthAdapter:
    """Asynchronous and deterministic streaming market depth adapter for BANK NIFTY options."""

    DEFAULT_BUCKET_SIZE_UNITS: int = 750   # 50 lots (750 units) per volume bucket
    DEFAULT_NUM_BUCKETS: int = 20          # 20 consecutive buckets for rolling VPIN (15,000 units total)
    TOXICITY_WARNING_THRESHOLD: float = 0.35
    TOXICITY_HALT_THRESHOLD: float = 0.45

    def __init__(
        self,
        bucket_size_units: int = DEFAULT_BUCKET_SIZE_UNITS,
        num_buckets: int = DEFAULT_NUM_BUCKETS,
        toxicity_warning_threshold: float = TOXICITY_WARNING_THRESHOLD,
        toxicity_halt_threshold: float = TOXICITY_HALT_THRESHOLD,
    ) -> None:
        self.bucket_size_units = max(15, bucket_size_units)
        self.num_buckets = max(5, num_buckets)
        self.toxicity_warning_threshold = toxicity_warning_threshold
        self.toxicity_halt_threshold = toxicity_halt_threshold

        self.current_book: Optional[SimulatedOrderBook] = None
        self.last_trade_price: Optional[float] = None
        self.last_trade_side: OrderSide = OrderSide.BUY

        # VPIN State
        self.completed_buckets: List[VolumeBucket] = []
        self.current_bucket = VolumeBucket(bucket_id=0, bucket_capacity_units=self.bucket_size_units)
        self.total_volume_processed: int = 0
        self.latest_metrics: Optional[MicrostructureMetrics] = None

    def on_depth_tick(self, tick: MarketDepthTick) -> MicrostructureMetrics:
        """Processes an incoming market depth tick and updates rolling VPIN."""
        # 1. Update internal order book
        self.current_book = SimulatedOrderBook(
            symbol=tick.symbol,
            bids=tick.bids,
            asks=tick.asks,
        )

        best_bid = tick.bids[0].price if tick.bids else 0.0
        best_ask = tick.asks[0].price if tick.asks else 0.0
        mid_price = round((best_bid + best_ask) / 2.0, 2) if (best_bid and best_ask) else best_bid
        spread = round(max(0.05, best_ask - best_bid), 2) if (best_bid and best_ask) else 0.05
        spread_bps = round((spread / max(1.0, mid_price)) * 10000.0, 1)

        total_bid_qty = sum(b.units for b in tick.bids)
        total_ask_qty = sum(a.units for a in tick.asks)
        total_depth = total_bid_qty + total_ask_qty

        # 2. Compute Liquidity Imbalance Ratio (LIR)
        if total_depth > 0:
            lir = round((total_bid_qty - total_ask_qty) / total_depth, 4)
        else:
            lir = 0.0

        # 3. Compute Stoikov (2018) Micro-Price
        # P_micro = P_mid + 0.5 * spread * (Q_bid - Q_ask) / (Q_bid + Q_ask)
        micro_price = round(mid_price + 0.5 * spread * lir, 2)

        # 4. Ingest Trade for VPIN Bucket Accumulation
        if tick.last_trade is not None:
            trade = tick.last_trade
            self.total_volume_processed += trade.units

            # Determine trade direction using Lee-Ready (1991) tick rule if side not specified
            trade_side = trade.side
            if trade_side is None:
                if self.last_trade_price is not None:
                    if trade.price > self.last_trade_price:
                        trade_side = OrderSide.BUY
                    elif trade.price < self.last_trade_price:
                        trade_side = OrderSide.SELL
                    else:
                        trade_side = self.last_trade_side
                else:
                    trade_side = OrderSide.BUY if trade.price >= mid_price else OrderSide.SELL

            self.last_trade_price = trade.price
            self.last_trade_side = trade_side

            # Add volume into current volume bucket
            remaining_volume = trade.units
            while remaining_volume > 0:
                available_space = self.current_bucket.bucket_capacity_units - self.current_bucket.accumulated_units
                chunk = min(remaining_volume, available_space)

                if trade_side == OrderSide.BUY:
                    self.current_bucket.buy_units += chunk
                else:
                    self.current_bucket.sell_units += chunk

                self.current_bucket.accumulated_units += chunk
                remaining_volume -= chunk

                # If bucket is filled, archive it and start a new bucket
                if self.current_bucket.accumulated_units >= self.current_bucket.bucket_capacity_units:
                    self.current_bucket.is_filled = True
                    self.completed_buckets.append(self.current_bucket)
                    if len(self.completed_buckets) > self.num_buckets:
                        self.completed_buckets.pop(0)

                    next_id = self.current_bucket.bucket_id + 1
                    self.current_bucket = VolumeBucket(
                        bucket_id=next_id,
                        bucket_capacity_units=self.bucket_size_units,
                    )

        # 5. Compute Volume-Synchronized Probability of Toxicity (VPIN)
        current_vpin = self._calculate_vpin()

        # 6. Classify Toxicity Regime
        if current_vpin >= self.toxicity_halt_threshold:
            regime = ToxicityRegime.EXTREME_TOXICITY_HALT
            safe_to_write = False
        elif current_vpin >= self.toxicity_warning_threshold:
            regime = ToxicityRegime.HIGH_TOXIC_FLOW
            safe_to_write = False
        elif current_vpin >= 0.20:
            regime = ToxicityRegime.MODERATE_TOXICITY
            safe_to_write = True
        else:
            regime = ToxicityRegime.LOW_TOXICITY
            safe_to_write = True

        diagnostics = (
            f"Microstructure Tick for {tick.symbol}: Mid=₹{mid_price:.2f}, Micro=₹{micro_price:.2f}, "
            f"Spread={spread:.2f} ({spread_bps:.1f} bps), LIR={lir:+.2f}, VPIN={current_vpin:.3f} ({regime.value}). "
            f"Option Writing Safe: {safe_to_write}."
        )

        metrics = MicrostructureMetrics(
            timestamp_iso=tick.timestamp_iso,
            symbol=tick.symbol,
            mid_price=mid_price,
            micro_price=micro_price,
            spread=spread,
            spread_bps=spread_bps,
            total_depth_bids=total_bid_qty,
            total_depth_asks=total_ask_qty,
            liquidity_imbalance_ratio=lir,
            current_vpin=current_vpin,
            toxicity_regime=regime,
            is_safe_for_writing=safe_to_write,
            total_volume_processed=self.total_volume_processed,
            diagnostics=diagnostics,
        )

        self.latest_metrics = metrics
        return metrics

    def on_trade_tick(self, trade: TradeTick) -> Optional[MicrostructureMetrics]:
        """Processes an incoming executed trade tick directly."""
        if self.current_book is not None:
            tick = MarketDepthTick(
                timestamp_iso=trade.timestamp_iso,
                symbol=self.current_book.symbol,
                bids=self.current_book.bids,
                asks=self.current_book.asks,
                last_trade=trade,
            )
            return self.on_depth_tick(tick)
        return None

    def _calculate_vpin(self) -> float:
        """Calculates rolling VPIN across completed volume buckets."""
        if not self.completed_buckets:
            # If no completed bucket exists yet, use current partial bucket ratio
            if self.current_bucket.accumulated_units > 0:
                diff = abs(self.current_bucket.buy_units - self.current_bucket.sell_units)
                return round(diff / self.current_bucket.accumulated_units, 4)
            return 0.15  # Baseline default

        # VPIN = sum(|V_tau^B - V_tau^S|) / (N * V)
        total_abs_imbalance = sum(
            abs(b.buy_units - b.sell_units) for b in self.completed_buckets
        )
        total_bucket_volume = sum(b.accumulated_units for b in self.completed_buckets)

        if total_bucket_volume <= 0:
            return 0.15

        vpin = total_abs_imbalance / total_bucket_volume
        return round(max(0.0, min(1.0, vpin)), 4)

    def replay_synthetic_stream(
        self,
        ticks: Sequence[MarketDepthTick],
    ) -> List[MicrostructureMetrics]:
        """Processes a sequence of ticks deterministically."""
        results: List[MicrostructureMetrics] = []
        for tick in ticks:
            metrics = self.on_depth_tick(tick)
            results.append(metrics)
        return results
