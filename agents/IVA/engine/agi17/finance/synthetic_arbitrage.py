"""AGI 1.7 Multi-Leg Synthetic Option Arbitrage & Box Spread Mispricing Engine.

TASK-BN-15:
Enables real-time detection of risk-free multi-leg option arbitrage opportunities
in European index options (BANK NIFTY):
1. Box Spread Arbitrage Detector:
   - Long Box (Bull Call Spread + Bear Put Spread):
     * Long K1 Call, Short K2 Call, Long K2 Put, Short K1 Put (K2 > K1).
     * Guaranteed expiry payoff = K2 - K1.
     * Discounted Present Value = (K2 - K1) * exp(-r * T).
     * Compares Net Debit (Ask_C1 - Bid_C2 + Ask_P2 - Bid_P1) vs PV(Box).
     * Computes annualized implied financing rate:
       r_implied = (365 / days) * ln((K2 - K1) / Net Debit).
   - Short Box (Bear Call Spread + Bull Put Spread):
     * Synthetic borrowing when Net Credit > PV(Box) + friction.
   - Rigorous Indian market transaction costs (STT, exchange turnover, GST, stamp duty, brokerage).
   - Lot-level depth executability based on minimum order book liquidity.
2. Put-Call Parity Synthetic Arbitrage:
   - Evaluates Synthetic Future vs Actual Future / Spot price.
   - Detects Conversions (Long Underlying + Long Put + Short Call) and
     Reversals (Short Underlying + Long Call + Short Put).
"""

from __future__ import annotations

import dataclasses
import enum
import math
from typing import Dict, List, Optional, Sequence, Tuple

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OptionType
from .options_math import OptionsMath


class ArbitrageType(enum.Enum):
    """Classification of detected options arbitrage."""

    NO_ARBITRAGE = "NO_ARBITRAGE"
    LONG_BOX_ARBITRAGE = "LONG_BOX_ARBITRAGE"    # Buy box: borrow at high implied yield / earn riskless spread
    SHORT_BOX_ARBITRAGE = "SHORT_BOX_ARBITRAGE"  # Sell box: raise synthetic cash at ultra-low interest
    CONVERSION_ARBITRAGE = "CONVERSION_ARBITRAGE"
    REVERSAL_ARBITRAGE = "REVERSAL_ARBITRAGE"


@dataclasses.dataclass(frozen=True)
class OptionMarketQuote:
    """Market depth and price snapshot for an individual strike option."""

    strike: float
    option_type: OptionType
    bid: float
    ask: float
    bid_size: int = 150  # Available units at bid
    ask_size: int = 150  # Available units at ask


@dataclasses.dataclass(frozen=True)
class BoxSpreadArbitrageOpportunity:
    """Quantitative evaluation of a 4-leg Box Spread arbitrage candidate."""

    strike_low: float
    strike_high: float
    days_to_expiry: float
    box_width: float                    # K2 - K1
    theoretical_pv: float               # (K2 - K1) * exp(-r * T)
    buy_box_debit: float                # Ask_C1 - Bid_C2 + Ask_P2 - Bid_P1
    sell_box_credit: float              # Bid_C1 - Ask_C2 + Bid_P2 - Ask_P1
    total_statutory_friction: float     # 4-leg round-trip transaction costs per unit
    net_arbitrage_spread_per_unit: float
    implied_annualized_rate: float
    arbitrage_type: ArbitrageType
    max_executable_units: int
    max_executable_lots: int
    projected_net_pnl_inr: float
    is_actionable: bool
    rationale: str


@dataclasses.dataclass(frozen=True)
class PutCallParityArbitrageOpportunity:
    """Put-Call Parity conversion/reversal arbitrage evaluation."""

    strike: float
    spot_price: float
    days_to_expiry: float
    call_bid: float
    call_ask: float
    put_bid: float
    put_ask: float
    synthetic_future_buy: float   # Ask_C - Bid_P + K * exp(-r*T)
    synthetic_future_sell: float  # Bid_C - Ask_P + K * exp(-r*T)
    discrepancy_vs_spot: float
    total_friction: float
    arbitrage_type: ArbitrageType
    net_profit_per_unit: float
    is_actionable: bool
    rationale: str


class SyntheticArbitrageEngine:
    """Real-time multi-leg synthetic arbitrage and box spread mispricing detector."""

    LOT_SIZE: int = BankNiftyContractSpec.LOT_SIZE

    @classmethod
    def calculate_statutory_friction(
        cls,
        c1_price: float,
        c2_price: float,
        p2_price: float,
        p1_price: float,
        units: int,
    ) -> float:
        """Calculates total Indian statutory friction and brokerage across 4 legs.

        Each executed leg incurs:
        - Brokerage: ₹20 per order
        - Exchange turnover charges: 0.053% of premium turnover
        - GST: 18% on (brokerage + exchange charges)
        - Stamp duty: 0.003% of premium turnover
        - STT: 0.1% on sell orders
        """
        leg_prices = [c1_price, c2_price, p2_price, p1_price]
        # In a long box, legs 2 (C2) and 4 (P1) are SELL orders
        total_fees = 0.0

        for i, price in enumerate(leg_prices):
            turnover = units * price
            brokerage = 20.0
            is_sell = (i in (1, 3))
            stt = turnover * 0.001 if is_sell else 0.0
            exchange = turnover * 0.00053
            gst = (brokerage + exchange) * 0.18
            stamp = turnover * 0.00003
            leg_total = brokerage + stt + exchange + gst + stamp
            total_fees += leg_total

        return round(total_fees, 2)

    @classmethod
    def evaluate_box_spread(
        cls,
        *,
        c1_quote: OptionMarketQuote,
        c2_quote: OptionMarketQuote,
        p2_quote: OptionMarketQuote,
        p1_quote: OptionMarketQuote,
        days_to_expiry: float,
        risk_free_rate: float = 0.065,
        min_net_spread_pts: float = 1.0,
    ) -> BoxSpreadArbitrageOpportunity:
        """Evaluates a 4-leg Box Spread (K1, K2 where K2 > K1) for mispricing.

        K1 = c1_quote.strike == p1_quote.strike
        K2 = c2_quote.strike == p2_quote.strike
        """
        k1 = c1_quote.strike
        k2 = c2_quote.strike

        if k2 <= k1:
            raise ValueError(f"High strike K2 ({k2}) must be strictly greater than Low strike K1 ({k1})")
        if c1_quote.strike != p1_quote.strike or c2_quote.strike != p2_quote.strike:
            raise ValueError("Option strikes do not match box geometry (K1 call/put and K2 call/put)")
        if days_to_expiry <= 0:
            raise ValueError("Days to expiry must be strictly positive")

        t_years = days_to_expiry / 365.0
        box_width = k2 - k1
        discount_factor = math.exp(-risk_free_rate * t_years)
        theoretical_pv = box_width * discount_factor

        # 1. Cost to BUY the Box (Long Box: Long C1, Short C2, Long P2, Short P1)
        # Pay Ask for C1, Receive Bid for C2, Pay Ask for P2, Receive Bid for P1
        buy_box_debit = c1_quote.ask - c2_quote.bid + p2_quote.ask - p1_quote.bid

        # 2. Proceeds to SELL the Box (Short Box: Short C1, Long C2, Short P2, Long P1)
        # Receive Bid for C1, Pay Ask for C2, Receive Bid for P2, Pay Ask for P1
        sell_box_credit = c1_quote.bid - c2_quote.ask + p2_quote.bid - p1_quote.ask

        # Executable liquidity for Buying the box
        buy_executable_units = min(
            c1_quote.ask_size,
            c2_quote.bid_size,
            p2_quote.ask_size,
            p1_quote.bid_size,
        )
        buy_executable_lots = buy_executable_units // cls.LOT_SIZE

        # Executable liquidity for Selling the box
        sell_executable_units = min(
            c1_quote.bid_size,
            c2_quote.ask_size,
            p2_quote.bid_size,
            p1_quote.ask_size,
        )
        sell_executable_lots = sell_executable_units // cls.LOT_SIZE

        aligned_units = max(1, max(buy_executable_lots, sell_executable_lots)) * cls.LOT_SIZE

        # Transaction friction per unit for a standard lot
        friction_total = cls.calculate_statutory_friction(
            c1_price=c1_quote.ask,
            c2_price=c2_quote.bid,
            p2_price=p2_quote.ask,
            p1_price=p1_quote.bid,
            units=aligned_units,
        )
        friction_per_unit = friction_total / aligned_units

        # Implied annualized return from buying the box
        if buy_box_debit > 0 and box_width > buy_box_debit:
            implied_annualized_rate = (365.0 / days_to_expiry) * math.log(box_width / buy_box_debit)
        else:
            implied_annualized_rate = 0.0

        # Arbitrage Decision Logic:
        # Long Box is profitable if PV(Box) - buy_box_debit > friction_per_unit + min_spread
        long_box_spread = theoretical_pv - buy_box_debit - friction_per_unit

        # Short Box is profitable if sell_box_credit - PV(Box) > friction_per_unit + min_spread
        short_box_spread = sell_box_credit - theoretical_pv - friction_per_unit

        if long_box_spread >= min_net_spread_pts:
            arb_type = ArbitrageType.LONG_BOX_ARBITRAGE
            net_spread = long_box_spread
            is_actionable = buy_executable_lots > 0
            executable_lots = buy_executable_lots
            pnl_inr = net_spread * (buy_executable_lots * cls.LOT_SIZE)
            rationale = (
                f"Long Box Mispriced: Debit ₹{buy_box_debit:.2f} < PV ₹{theoretical_pv:.2f}. "
                f"Net yield {implied_annualized_rate*100:.2f}% p.a. vs risk-free {risk_free_rate*100:.2f}%. "
                f"Net spread +₹{net_spread:.2f}/unit after ₹{friction_per_unit:.2f} friction."
            )
        elif short_box_spread >= min_net_spread_pts:
            arb_type = ArbitrageType.SHORT_BOX_ARBITRAGE
            net_spread = short_box_spread
            is_actionable = sell_executable_lots > 0
            executable_lots = sell_executable_lots
            pnl_inr = net_spread * (sell_executable_lots * cls.LOT_SIZE)
            rationale = (
                f"Short Box Mispriced: Credit ₹{sell_box_credit:.2f} > PV ₹{theoretical_pv:.2f}. "
                f"Net spread +₹{net_spread:.2f}/unit after ₹{friction_per_unit:.2f} friction."
            )
        else:
            arb_type = ArbitrageType.NO_ARBITRAGE
            net_spread = max(long_box_spread, short_box_spread)
            is_actionable = False
            executable_lots = 0
            pnl_inr = 0.0
            rationale = (
                f"No Box Arbitrage: Buy Debit ₹{buy_box_debit:.2f}, PV ₹{theoretical_pv:.2f}, "
                f"Friction ₹{friction_per_unit:.2f}/unit. Net spread {net_spread:.2f} below threshold."
            )

        return BoxSpreadArbitrageOpportunity(
            strike_low=k1,
            strike_high=k2,
            days_to_expiry=days_to_expiry,
            box_width=box_width,
            theoretical_pv=theoretical_pv,
            buy_box_debit=buy_box_debit,
            sell_box_credit=sell_box_credit,
            total_statutory_friction=friction_total,
            net_arbitrage_spread_per_unit=round(net_spread, 2),
            implied_annualized_rate=round(implied_annualized_rate, 4),
            arbitrage_type=arb_type,
            max_executable_units=(executable_lots * cls.LOT_SIZE) if is_actionable else 0,
            max_executable_lots=executable_lots if is_actionable else 0,
            projected_net_pnl_inr=round(pnl_inr, 2),
            is_actionable=is_actionable,
            rationale=rationale,
        )

    @classmethod
    def evaluate_put_call_parity(
        cls,
        *,
        spot_price: float,
        strike: float,
        call_quote: OptionMarketQuote,
        put_quote: OptionMarketQuote,
        days_to_expiry: float,
        risk_free_rate: float = 0.065,
        min_profit_threshold: float = 1.0,
    ) -> PutCallParityArbitrageOpportunity:
        """Evaluates European Put-Call Parity for Conversion or Reversal mispricing.

        Put-Call Parity:
            C - P = S - K * exp(-r * T)
            Synthetic Future (Buy) = Ask_C - Bid_P + K * exp(-r * T)
            Synthetic Future (Sell) = Bid_C - Ask_P + K * exp(-r * T)
        """
        if spot_price <= 0 or strike <= 0:
            raise ValueError("Spot price and strike must be strictly positive")
        if days_to_expiry <= 0:
            raise ValueError("Days to expiry must be positive")

        t_years = days_to_expiry / 365.0
        pv_strike = strike * math.exp(-risk_free_rate * t_years)

        # Synthetic Future Long: Buy Call, Sell Put -> Fair equivalent spot = Ask_C - Bid_P + PV(K)
        synth_long = call_quote.ask - put_quote.bid + pv_strike

        # Synthetic Future Short: Sell Call, Buy Put -> Fair equivalent spot = Bid_C - Ask_P + PV(K)
        synth_short = call_quote.bid - put_quote.ask + pv_strike

        # Round-trip friction estimate (2 options legs + underlying cash leg)
        # Brokerage (2 * 20 = 40) + taxes approx 0.05% of spot
        friction_per_unit = 0.50 + (spot_price * 0.0002)

        # Conversion: Underlying is cheap, Synthetic Future is expensive
        # Buy Spot S, Buy Put P, Sell Call C -> Payoff at T is K.
        # Cost = S + Ask_P - Bid_C. Net PV profit = PV(K) - Cost.
        conversion_profit = pv_strike - (spot_price + put_quote.ask - call_quote.bid) - friction_per_unit

        # Reversal: Underlying is expensive, Synthetic Future is cheap
        # Short Spot S, Sell Put P, Buy Call C -> Cost = Ask_C - Bid_P - S.
        # Profit = -Cost - PV(K) = Spot - Ask_C + Bid_P - PV(K).
        reversal_profit = (spot_price - call_quote.ask + put_quote.bid - pv_strike) - friction_per_unit

        discrepancy = synth_long - spot_price

        if conversion_profit >= min_profit_threshold:
            arb_type = ArbitrageType.CONVERSION_ARBITRAGE
            net_profit = conversion_profit
            actionable = True
            rationale = (
                f"Conversion Arbitrage Detected: Buy Spot @ {spot_price:.2f}, Buy Put @ {put_quote.ask:.2f}, "
                f"Sell Call @ {call_quote.bid:.2f}. Net profit +₹{net_profit:.2f}/unit."
            )
        elif reversal_profit >= min_profit_threshold:
            arb_type = ArbitrageType.REVERSAL_ARBITRAGE
            net_profit = reversal_profit
            actionable = True
            rationale = (
                f"Reversal Arbitrage Detected: Short Spot @ {spot_price:.2f}, Buy Call @ {call_quote.ask:.2f}, "
                f"Sell Put @ {put_quote.bid:.2f}. Net profit +₹{net_profit:.2f}/unit."
            )
        else:
            arb_type = ArbitrageType.NO_ARBITRAGE
            net_profit = max(conversion_profit, reversal_profit)
            actionable = False
            rationale = f"Put-Call Parity aligned within friction band (net discrepancy {discrepancy:.2f} pts)."

        return PutCallParityArbitrageOpportunity(
            strike=strike,
            spot_price=spot_price,
            days_to_expiry=days_to_expiry,
            call_bid=call_quote.bid,
            call_ask=call_quote.ask,
            put_bid=put_quote.bid,
            put_ask=put_quote.ask,
            synthetic_future_buy=round(synth_long, 2),
            synthetic_future_sell=round(synth_short, 2),
            discrepancy_vs_spot=round(discrepancy, 2),
            total_friction=round(friction_per_unit, 2),
            arbitrage_type=arb_type,
            net_profit_per_unit=round(net_profit, 2),
            is_actionable=actionable,
            rationale=rationale,
        )
