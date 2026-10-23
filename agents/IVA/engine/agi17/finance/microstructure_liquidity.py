"""Multi-Level Book Depth Liquidity Heatmap & Kyle's Lambda Price Impact Engine.

Implements Albert Kyle's (1985) continuous auction price impact coefficient (lambda),
Yakov Amihud's (2002) illiquidity ratio (ILLIQ), multi-level order book liquidity
density profiling, book slope/elasticity, and replenishment resilience metrics
for Bank Nifty options and futures trading.

References:
- Kyle, A. S. (1985). Continuous Auctions and Informed Trader.
  Econometrica, 53(6), 1315-1335.
- Amihud, Y. (2002). Illiquidity and stock returns: cross-section and time-series effects.
  Journal of Financial Markets, 5(1), 31-56.
- Biais, B., Hillion, P., & Spatt, C. (1995). An Empirical Analysis of the Limit Order
  Book and the Order Flow in the Paris Bourse. Journal of Finance, 50(5), 1655-1689.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class LiquidityRegime(Enum):
    """Classification of microstructure liquidity conditions."""
    HIGH_LIQUIDITY = "HIGH_LIQUIDITY"      # Tight spread, low lambda, high book depth
    NORMAL_LIQUIDITY = "NORMAL_LIQUIDITY"  # Standard intraday market conditions
    THIN_BOOK = "THIN_BOOK"                # Low depth, moderate lambda, wider spreads
    ADVERSE_SHOCK = "ADVERSE_SHOCK"        # Spiking lambda, high Amihud ratio, illiquid


class ExecutionSafetyStatus(Enum):
    """Institutional pre-trade order sizing decision."""
    SAFE = "SAFE"
    THROTTLE_CHILD_CLIPS = "THROTTLE_CHILD_CLIPS"
    REJECT_ILLIQUID = "REJECT_ILLIQUID"


@dataclass(frozen=True)
class BookLevel:
    """Individual price and quantity level in an order book."""
    price: float
    quantity: int


@dataclass
class BookDepthSnapshot:
    """Multi-level order book snapshot."""
    timestamp: float
    bids: List[BookLevel]  # Best bid at index 0
    asks: List[BookLevel]  # Best ask at index 0
    mid_price: float
    quoted_spread: float
    bid_total_qty: int
    ask_total_qty: int
    bid_slope: float
    ask_slope: float


@dataclass
class TradeTickRecord:
    """Trade tick for order flow and impact regression."""
    timestamp: float
    price: float
    volume: int
    signed_volume: float  # +volume for buyer-initiated, -volume for seller-initiated
    price_change: float


@dataclass
class MicrostructureLiquidityReport:
    """Consolidated microstructure liquidity metrics."""
    timestamp: float
    mid_price: float
    quoted_spread: float
    quoted_spread_bps: float
    kyles_lambda: float             # Price impact per unit signed volume (pts / unit volume)
    kyles_r_squared: float          # Goodness-of-fit for Kyle's linear impact model
    amihud_illiq: float             # |Delta P| / Volume
    bid_depth_5_levels: int
    ask_depth_5_levels: int
    book_imbalance_ratio: float     # (Bid_Vol - Ask_Vol) / (Bid_Vol + Ask_Vol)
    book_elasticity_slope: float    # Average volume depth per unit price distance
    replenishment_resilience: float # [0.0, 1.0] queue refill speed
    regime: LiquidityRegime
    is_safe_for_market_orders: bool


@dataclass
class ExecutionImpactEstimate:
    """Pre-trade estimation of market impact for a candidate order."""
    order_size: int
    side: str  # "BUY" or "SELL"
    expected_slippage_pts: float
    expected_slippage_bps: float
    kyle_impact_pts: float
    depth_consumed_levels: int
    status: ExecutionSafetyStatus
    recommended_max_clip_size: int
    rejection_reason: str = ""


class MicrostructureLiquidityEngine:
    """Multi-level order book liquidity density and price impact engine."""

    def __init__(
        self,
        rolling_window_trades: int = 50,
        rolling_window_books: int = 30,
        max_acceptable_lambda: float = 0.05,
        max_acceptable_spread_bps: float = 15.0,
        bank_nifty_lot_size: int = 15,
    ) -> None:
        self.rolling_window_trades = rolling_window_trades
        self.rolling_window_books = rolling_window_books
        self.max_acceptable_lambda = max_acceptable_lambda
        self.max_acceptable_spread_bps = max_acceptable_spread_bps
        self.lot_size = bank_nifty_lot_size

        self.trade_history: List[TradeTickRecord] = []
        self.book_history: List[BookDepthSnapshot] = []
        self._last_price: Optional[float] = None
        self._prior_depth_post_trade: Optional[int] = None

    def record_order_book(
        self,
        timestamp: float,
        bids: List[Tuple[float, int]],
        asks: List[Tuple[float, int]],
    ) -> BookDepthSnapshot:
        """Record multi-level order book snapshot.
        
        bids: list of (price, quantity) sorted descending
        asks: list of (price, quantity) sorted ascending
        """
        bid_levels = [BookLevel(p, q) for p, q in bids[:5]]
        ask_levels = [BookLevel(p, q) for p, q in asks[:5]]

        best_bid = bid_levels[0].price if bid_levels else 0.0
        best_ask = ask_levels[0].price if ask_levels else 0.0
        spread = max(0.0, best_ask - best_bid) if best_bid > 0 and best_ask > 0 else 0.0
        mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else (best_bid or best_ask)

        bid_tot = sum(b.quantity for b in bid_levels)
        ask_tot = sum(a.quantity for a in ask_levels)

        # Book slopes: Quantity per unit price distance from touch
        bid_price_dist = max(0.05, best_bid - bid_levels[-1].price) if len(bid_levels) > 1 else 1.0
        ask_price_dist = max(0.05, ask_levels[-1].price - best_ask) if len(ask_levels) > 1 else 1.0

        bid_slope = bid_tot / bid_price_dist
        ask_slope = ask_tot / ask_price_dist

        snapshot = BookDepthSnapshot(
            timestamp=timestamp,
            bids=bid_levels,
            asks=ask_levels,
            mid_price=mid,
            quoted_spread=spread,
            bid_total_qty=bid_tot,
            ask_total_qty=ask_tot,
            bid_slope=bid_slope,
            ask_slope=ask_slope,
        )

        self.book_history.append(snapshot)
        if len(self.book_history) > self.rolling_window_books:
            self.book_history.pop(0)

        return snapshot

    def record_trade(
        self,
        timestamp: float,
        price: float,
        volume: int,
        side: Optional[str] = None,
    ) -> TradeTickRecord:
        """Record trade tick and compute signed order flow."""
        if self._last_price is None:
            price_change = 0.0
        else:
            price_change = price - self._last_price

        # Lee-Ready classification if side is not explicitly provided
        if side is not None:
            sign = 1.0 if side.upper() in ("BUY", "B") else -1.0
        else:
            if price_change > 0:
                sign = 1.0
            elif price_change < 0:
                sign = -1.0
            else:
                # Use prior sign if price is unchanged
                sign = 1.0 if (self.trade_history and self.trade_history[-1].signed_volume >= 0) else -1.0

        signed_vol = sign * float(volume)
        record = TradeTickRecord(
            timestamp=timestamp,
            price=price,
            volume=volume,
            signed_volume=signed_vol,
            price_change=price_change,
        )

        self.trade_history.append(record)
        if len(self.trade_history) > self.rolling_window_trades:
            self.trade_history.pop(0)

        self._last_price = price
        return record

    def compute_kyles_lambda(self) -> Tuple[float, float]:
        """Compute Kyle's Lambda via OLS regression: Delta P = alpha + lambda * Q.
        
        Returns:
            (lambda, r_squared)
        """
        if len(self.trade_history) < 5:
            return 0.001, 0.0

        q_vals = [t.signed_volume for t in self.trade_history]
        dp_vals = [t.price_change for t in self.trade_history]
        n = len(q_vals)

        mean_q = sum(q_vals) / n
        mean_dp = sum(dp_vals) / n

        cov_q_dp = sum((q - mean_q) * (dp - mean_dp) for q, dp in zip(q_vals, dp_vals))
        var_q = sum((q - mean_q) ** 2 for q in q_vals)
        var_dp = sum((dp - mean_dp) ** 2 for dp in dp_vals)

        if var_q < 1e-6:
            return 0.001, 0.0

        lambda_coeff = max(0.0, cov_q_dp / var_q)
        
        # R-squared calculation
        if var_dp < 1e-6:
            r_squared = 0.0
        else:
            corr = cov_q_dp / math.sqrt(var_q * var_dp)
            r_squared = max(0.0, min(1.0, corr * corr))

        return lambda_coeff, r_squared

    def compute_amihud_illiq(self) -> float:
        """Compute rolling Amihud illiquidity ratio: average(|Delta P| / Volume)."""
        if not self.trade_history:
            return 0.0
        ratios = [
            abs(t.price_change) / max(1, t.volume)
            for t in self.trade_history
        ]
        return sum(ratios) / len(ratios)

    def compute_replenishment_resilience(self) -> float:
        """Measure queue replenishment speed across recent order books."""
        if len(self.book_history) < 3:
            return 1.0

        # Check rate of change in total top-level depth
        recent_depths = [b.bid_total_qty + b.ask_total_qty for b in self.book_history[-5:]]
        mean_depth = sum(recent_depths) / len(recent_depths)
        if mean_depth < 1:
            return 0.0

        last_depth = recent_depths[-1]
        resilience = min(1.0, last_depth / mean_depth)
        return max(0.0, resilience)

    def generate_liquidity_report(self) -> MicrostructureLiquidityReport:
        """Generate comprehensive microstructure liquidity assessment."""
        if not self.book_history:
            # Baseline dummy when no book exists
            return MicrostructureLiquidityReport(
                timestamp=0.0,
                mid_price=50000.0,
                quoted_spread=1.0,
                quoted_spread_bps=0.2,
                kyles_lambda=0.001,
                kyles_r_squared=0.0,
                amihud_illiq=0.0,
                bid_depth_5_levels=100,
                ask_depth_5_levels=100,
                book_imbalance_ratio=0.0,
                book_elasticity_slope=50.0,
                replenishment_resilience=1.0,
                regime=LiquidityRegime.NORMAL_LIQUIDITY,
                is_safe_for_market_orders=True,
            )

        latest_book = self.book_history[-1]
        k_lambda, k_r2 = self.compute_kyles_lambda()
        amihud = self.compute_amihud_illiq()
        resilience = self.compute_replenishment_resilience()

        mid = latest_book.mid_price
        spread = latest_book.quoted_spread
        spread_bps = (spread / mid) * 10000.0 if mid > 0 else 0.0

        tot_bid = latest_book.bid_total_qty
        tot_ask = latest_book.ask_total_qty
        tot_depth = tot_bid + tot_ask
        imbalance = (tot_bid - tot_ask) / max(1, tot_depth)
        avg_slope = (latest_book.bid_slope + latest_book.ask_slope) / 2.0

        # Classify regime
        if k_lambda > self.max_acceptable_lambda or spread_bps > self.max_acceptable_spread_bps:
            regime = LiquidityRegime.ADVERSE_SHOCK
            safe = False
        elif tot_depth < 4 * self.lot_size:
            regime = LiquidityRegime.THIN_BOOK
            safe = False
        elif spread_bps <= 3.0 and k_lambda < 0.005 and tot_depth >= 10 * self.lot_size:
            regime = LiquidityRegime.HIGH_LIQUIDITY
            safe = True
        else:
            regime = LiquidityRegime.NORMAL_LIQUIDITY
            safe = True

        return MicrostructureLiquidityReport(
            timestamp=latest_book.timestamp,
            mid_price=mid,
            quoted_spread=spread,
            quoted_spread_bps=spread_bps,
            kyles_lambda=k_lambda,
            kyles_r_squared=k_r2,
            amihud_illiq=amihud,
            bid_depth_5_levels=tot_bid,
            ask_depth_5_levels=tot_ask,
            book_imbalance_ratio=imbalance,
            book_elasticity_slope=avg_slope,
            replenishment_resilience=resilience,
            regime=regime,
            is_safe_for_market_orders=safe,
        )

    def evaluate_execution_impact(
        self,
        order_size: int,
        side: str = "BUY",
    ) -> ExecutionImpactEstimate:
        """Estimate slippage and depth impact for a proposed institutional order."""
        if not self.book_history:
            return ExecutionImpactEstimate(
                order_size=order_size,
                side=side,
                expected_slippage_pts=0.05,
                expected_slippage_bps=0.1,
                kyle_impact_pts=0.01,
                depth_consumed_levels=1,
                status=ExecutionSafetyStatus.SAFE,
                recommended_max_clip_size=order_size,
            )

        latest_book = self.book_history[-1]
        k_lambda, _ = self.compute_kyles_lambda()
        mid = latest_book.mid_price

        # Walk available book levels
        levels = latest_book.asks if side.upper() == "BUY" else latest_book.bids
        if not levels:
            return ExecutionImpactEstimate(
                order_size=order_size,
                side=side,
                expected_slippage_pts=999.0,
                expected_slippage_bps=999.0,
                kyle_impact_pts=0.0,
                depth_consumed_levels=0,
                status=ExecutionSafetyStatus.REJECT_ILLIQUID,
                recommended_max_clip_size=0,
                rejection_reason="No book liquidity available on requested side",
            )

        touch_price = levels[0].price
        remaining_qty = order_size
        total_cost = 0.0
        levels_consumed = 0

        for lvl in levels:
            levels_consumed += 1
            fill_from_lvl = min(remaining_qty, lvl.quantity)
            total_cost += fill_from_lvl * lvl.price
            remaining_qty -= fill_from_lvl
            if remaining_qty <= 0:
                break

        # If order size exceeds all 5 levels
        if remaining_qty > 0:
            return ExecutionImpactEstimate(
                order_size=order_size,
                side=side,
                expected_slippage_pts=999.0,
                expected_slippage_bps=999.0,
                kyle_impact_pts=0.0,
                depth_consumed_levels=5,
                status=ExecutionSafetyStatus.REJECT_ILLIQUID,
                recommended_max_clip_size=sum(lvl.quantity for lvl in levels),
                rejection_reason=f"Order size {order_size} exceeds total 5-level depth",
            )

        vwap_fill = total_cost / float(order_size)
        depth_slippage_pts = abs(vwap_fill - touch_price)
        kyle_impact_pts = k_lambda * float(order_size)
        total_slippage_pts = depth_slippage_pts + kyle_impact_pts
        total_slippage_bps = (total_slippage_pts / mid) * 10000.0 if mid > 0 else 0.0

        # Safety decision
        if levels_consumed > 3 or total_slippage_bps > self.max_acceptable_spread_bps:
            status = ExecutionSafetyStatus.THROTTLE_CHILD_CLIPS
            clip_size = max(self.lot_size, levels[0].quantity)
        else:
            status = ExecutionSafetyStatus.SAFE
            clip_size = order_size

        return ExecutionImpactEstimate(
            order_size=order_size,
            side=side,
            expected_slippage_pts=total_slippage_pts,
            expected_slippage_bps=total_slippage_bps,
            kyle_impact_pts=kyle_impact_pts,
            depth_consumed_levels=levels_consumed,
            status=status,
            recommended_max_clip_size=clip_size,
        )
