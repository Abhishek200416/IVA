"""Avellaneda-Stoikov (2008) Optimal Market Making & Inventory Risk Engine.

Implements Marco Avellaneda and Sasha Stoikov's optimal limit order quoting model,
reservation (indifference) price calculations, inventory risk aversion adjustments,
asymmetric quote skewing, and Indian market statutory cost spread bounds.

References:
- Avellaneda, M., & Stoikov, S. (2008). High-frequency trading in a limit order book.
  Quantitative Finance, 8(3), 217-224.
- Guéant, O., Tapia, C. A., & Manziadi, A. (2012). Dealing with the inventory risk:
  a solution to the market making problem. Mathematics and Financial Economics, 6(4), 259-277.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class InventoryRiskRegime(Enum):
    """Inventory risk exposure state."""
    BALANCED = "BALANCED"              # Inventory near 0, symmetric quoting
    LONG_SKEW = "LONG_SKEW"            # Long inventory, lower quotes to attract buyers
    SHORT_SKEW = "SHORT_SKEW"          # Short inventory, raise quotes to attract sellers
    INVENTORY_LIMIT_HIT = "INVENTORY_LIMIT_HIT"  # One-sided quote only (liquidation mode)


@dataclass(frozen=True)
class OptimalQuotes:
    """Optimal two-sided limit order quotes produced by Avellaneda-Stoikov model."""
    mid_price: float
    reservation_price: float
    optimal_bid: float
    optimal_ask: float
    half_spread_bid: float
    half_spread_ask: float
    total_spread: float
    inventory: int
    effective_inventory_delta: float
    time_remaining_tau: float
    regime: InventoryRiskRegime
    post_bid: bool
    post_ask: bool


class AvellanedaStoikovEngine:
    """Avellaneda-Stoikov (2008) Market Making and Inventory Control Engine."""

    def __init__(
        self,
        risk_aversion_gamma: float = 0.1,
        order_intensity_kappa: float = 1.5,
        default_volatility_sigma: float = 0.20,
        max_inventory_units: int = 150,  # 10 lots of Bank Nifty (15 * 10)
        tick_size: float = 0.05,
        min_statutory_spread_bps: float = 2.0,
        bank_nifty_lot_size: int = 15,
    ) -> None:
        """
        Args:
            risk_aversion_gamma: Risk aversion parameter gamma > 0
            order_intensity_kappa: Order arrival intensity decay kappa > 0
            default_volatility_sigma: Annualized or normalized asset volatility
            max_inventory_units: Hard inventory ceiling (contracts)
            tick_size: NSE tick size (0.05)
            min_statutory_spread_bps: Minimum spread hurdle in bps to cover taxes/fees
            bank_nifty_lot_size: Lot size (15)
        """
        if risk_aversion_gamma <= 0:
            raise ValueError("risk_aversion_gamma must be > 0")
        if order_intensity_kappa <= 0:
            raise ValueError("order_intensity_kappa must be > 0")

        self.gamma = risk_aversion_gamma
        self.kappa = order_intensity_kappa
        self.sigma = default_volatility_sigma
        self.max_inventory = max_inventory_units
        self.tick_size = tick_size
        self.min_statutory_spread_bps = min_statutory_spread_bps
        self.lot_size = bank_nifty_lot_size

    def align_to_tick(self, price: float, round_up: bool = False) -> float:
        """Align price to standard NSE tick size (0.05)."""
        if round_up:
            ticks = math.ceil(price / self.tick_size - 1e-9)
        else:
            ticks = math.floor(price / self.tick_size + 1e-9)
        return round(ticks * self.tick_size, 2)

    def calculate_reservation_price(
        self,
        mid_price: float,
        inventory: int,
        tau: float,
        volatility: Optional[float] = None,
        delta: float = 1.0,
    ) -> float:
        """Compute reservation (indifference) price r(s, q, tau).
        
        Formula: r(s, q, tau) = s - q * gamma * sigma^2 * tau
        """
        vol = volatility if volatility is not None else self.sigma
        eff_q = float(inventory) * delta
        reservation = mid_price - (eff_q * self.gamma * (vol ** 2) * tau)
        return reservation

    def calculate_optimal_spread(
        self,
        tau: float,
        volatility: Optional[float] = None,
        mid_price: float = 50000.0,
    ) -> float:
        """Compute optimal reservation spread s*(tau).
        
        Formula: s* = gamma * sigma^2 * tau + (2 / gamma) * ln(1 + gamma / kappa)
        Enforces statutory fee spread floor and minimum tick size.
        """
        vol = volatility if volatility is not None else self.sigma
        term1 = self.gamma * (vol ** 2) * tau
        term2 = (2.0 / self.gamma) * math.log(1.0 + (self.gamma / self.kappa))
        raw_spread = term1 + term2

        # Floor by statutory friction in points
        statutory_floor = (self.min_statutory_spread_bps / 10000.0) * mid_price
        min_spread = max(self.tick_size * 2.0, statutory_floor)
        
        return max(min_spread, raw_spread)

    def compute_quotes(
        self,
        mid_price: float,
        inventory: int,
        tau: float = 1.0,
        volatility: Optional[float] = None,
        delta: float = 1.0,
    ) -> OptimalQuotes:
        """Compute optimal bid and ask quotes around reservation price.
        
        Args:
            mid_price: Current market mid-price
            inventory: Current net inventory (contracts)
            tau: Normalized time remaining to horizon [0.0, 1.0]
            volatility: Asset/option volatility
            delta: Option delta (default 1.0 for linear futures/underlying)
        """
        vol = volatility if volatility is not None else self.sigma
        tau = max(1e-4, min(1.0, tau))
        eff_q = float(inventory) * delta

        res_price = self.calculate_reservation_price(
            mid_price=mid_price,
            inventory=inventory,
            tau=tau,
            volatility=vol,
            delta=delta,
        )

        total_spread = self.calculate_optimal_spread(
            tau=tau,
            volatility=vol,
            mid_price=mid_price,
        )
        half_spread = total_spread / 2.0

        # Asymmetric half spreads around reservation price
        raw_bid = res_price - half_spread
        raw_ask = res_price + half_spread

        # Ensure ask > bid and quotes aligned to tick
        bid_price = self.align_to_tick(raw_bid, round_up=False)
        ask_price = self.align_to_tick(raw_ask, round_up=True)

        if ask_price <= bid_price:
            ask_price = self.align_to_tick(bid_price + self.tick_size, round_up=True)

        # Classify inventory regime and apply limit controls
        post_bid = True
        post_ask = True

        if abs(inventory) >= self.max_inventory:
            regime = InventoryRiskRegime.INVENTORY_LIMIT_HIT
            if inventory >= self.max_inventory:
                # Max long: halt bids, only post asks to shed inventory
                post_bid = False
            else:
                # Max short: halt asks, only post bids to cover
                post_ask = False
        elif inventory > 2 * self.lot_size:
            regime = InventoryRiskRegime.LONG_SKEW
        elif inventory < -2 * self.lot_size:
            regime = InventoryRiskRegime.SHORT_SKEW
        else:
            regime = InventoryRiskRegime.BALANCED

        return OptimalQuotes(
            mid_price=mid_price,
            reservation_price=res_price,
            optimal_bid=bid_price,
            optimal_ask=ask_price,
            half_spread_bid=max(0.0, mid_price - bid_price),
            half_spread_ask=max(0.0, ask_price - mid_price),
            total_spread=ask_price - bid_price,
            inventory=inventory,
            effective_inventory_delta=eff_q,
            time_remaining_tau=tau,
            regime=regime,
            post_bid=post_bid,
            post_ask=post_ask,
        )
