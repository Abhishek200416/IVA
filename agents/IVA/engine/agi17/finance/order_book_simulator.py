"""AGI 1.7 BANK NIFTY 5-Level Order Book Simulator & Depth-Based Slippage Engine.

Provides:
1. 5-level market depth modeling (Bids and Asks with quantity and order counts).
2. Realistic order book walking for market and limit paper orders.
3. Precise volume-weighted execution price (fill price) and depth-based slippage calculation in basis points.
4. Liquidity regime modeling:
   - High liquidity (ATM, 1-tick spread, deep book)
   - Medium liquidity (near OTM/ITM, 2-3 ticks spread)
   - Illiquid / stressed regime (far OTM, wide 5-15 ticks spread, shallow depth, heavy slippage)
5. Zero real-money paths: Strictly simulated paper execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OrderSide, OrderType


@dataclass
class BookLevel:
    price: float
    units: int
    orders_count: int = 1


@dataclass
class OrderFillResult:
    symbol: str
    side: OrderSide
    order_type: OrderType
    requested_units: int
    filled_units: int
    avg_fill_price: float
    expected_top_price: float
    slippage_amount: float
    slippage_bps: float
    fully_filled: bool
    levels_consumed: int
    unfilled_units: int = 0
    rationale: str = ""


class SimulatedOrderBook:
    """Represents a 5-level order book for an option or index contract."""

    def __init__(
        self,
        symbol: str,
        bids: Optional[List[BookLevel]] = None,
        asks: Optional[List[BookLevel]] = None,
    ) -> None:
        self.symbol = symbol
        # Bids sorted descending by price
        self.bids: List[BookLevel] = sorted(bids or [], key=lambda l: l.price, reverse=True)
        # Asks sorted ascending by price
        self.asks: List[BookLevel] = sorted(asks or [], key=lambda l: l.price)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> float:
        if self.best_bid is not None and self.best_ask is not None:
            return round(self.best_ask - self.best_bid, 2)
        return 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid is not None and self.best_ask is not None:
            return round((self.best_bid + self.best_ask) / 2.0, 2)
        return self.best_bid or self.best_ask or 0.0

    def execute_order(
        self,
        *,
        side: OrderSide,
        units: int,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
    ) -> OrderFillResult:
        """Fills an order by walking through the relevant side of the book."""
        if units <= 0:
            raise ValueError(f"Units must be positive: {units}")

        book_side = self.asks if side == OrderSide.BUY else self.bids
        if not book_side:
            return OrderFillResult(
                symbol=self.symbol,
                side=side,
                order_type=order_type,
                requested_units=units,
                filled_units=0,
                avg_fill_price=0.0,
                expected_top_price=0.0,
                slippage_amount=0.0,
                slippage_bps=0.0,
                fully_filled=False,
                levels_consumed=0,
                unfilled_units=units,
                rationale="ORDER_BOOK_EMPTY",
            )

        top_price = book_side[0].price
        remaining = units
        total_cost = 0.0
        levels_walked = 0

        for level in book_side:
            if remaining <= 0:
                break

            # Limit price check
            if order_type == OrderType.LIMIT and limit_price is not None:
                if side == OrderSide.BUY and level.price > limit_price:
                    break
                if side == OrderSide.SELL and level.price < limit_price:
                    break

            fill_qty = min(remaining, level.units)
            total_cost += fill_qty * level.price
            remaining -= fill_qty
            levels_walked += 1

        filled_units = units - remaining
        if filled_units > 0:
            avg_price = BankNiftyContractSpec.round_to_tick(total_cost / filled_units)
            if side == OrderSide.BUY:
                slippage = round(avg_price - top_price, 2)
            else:
                slippage = round(top_price - avg_price, 2)

            slippage_bps = round((abs(slippage) / top_price) * 10_000.0, 2) if top_price > 0 else 0.0
        else:
            avg_price = 0.0
            slippage = 0.0
            slippage_bps = 0.0

        return OrderFillResult(
            symbol=self.symbol,
            side=side,
            order_type=order_type,
            requested_units=units,
            filled_units=filled_units,
            avg_fill_price=avg_price,
            expected_top_price=top_price,
            slippage_amount=slippage,
            slippage_bps=slippage_bps,
            fully_filled=(remaining == 0),
            levels_consumed=levels_walked,
            unfilled_units=remaining,
            rationale="FILLED" if remaining == 0 else ("PARTIAL_FILL" if filled_units > 0 else "UNFILLED"),
        )


class OrderBookFactory:
    """Synthesizes realistic 5-level market depth for Bank Nifty options."""

    @staticmethod
    def create_book(
        symbol: str,
        ltp: float,
        is_atm: bool = True,
        is_illiquid: bool = False,
        base_lot_size: int = BankNiftyContractSpec.LOT_SIZE,
    ) -> SimulatedOrderBook:
        """Constructs a realistic 5-level depth book calibrated to Indian index options."""
        ltp_clean = BankNiftyContractSpec.round_to_tick(max(0.50, ltp))

        if is_illiquid:
            # Wide spread (5 to 10 ticks), shallow depth
            tick_spread = 6
            half_spread = tick_spread * 0.05 / 2.0
            qty_multiplier = 1  # 1-2 lots per level
        elif is_atm:
            # Tight spread (1 tick = 0.05), deep depth
            half_spread = 0.05 / 2.0
            qty_multiplier = 10  # 10-25 lots per level
        else:
            # Near OTM / ITM (2 ticks spread)
            half_spread = 0.10 / 2.0
            qty_multiplier = 4  # 4-8 lots per level

        best_bid = BankNiftyContractSpec.round_to_tick(max(0.05, ltp_clean - half_spread))
        best_ask = BankNiftyContractSpec.round_to_tick(best_bid + (half_spread * 2.0))

        bids: List[BookLevel] = []
        asks: List[BookLevel] = []

        for i in range(5):
            bid_p = BankNiftyContractSpec.round_to_tick(max(0.05, best_bid - (i * 0.05)))
            ask_p = BankNiftyContractSpec.round_to_tick(best_ask + (i * 0.05))

            # Quantity increases slightly deeper into the book
            units_at_level = int((qty_multiplier + i * 2) * base_lot_size)
            bids.append(BookLevel(price=bid_p, units=units_at_level, orders_count=max(1, i + 1)))
            asks.append(BookLevel(price=ask_p, units=units_at_level, orders_count=max(1, i + 1)))

        return SimulatedOrderBook(symbol=symbol, bids=bids, asks=asks)
