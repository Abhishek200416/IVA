"""European Options Box Spread Arbitrage & Synthetic Lending Engine.

TASK-BN-15:
Analyzes European options 4-leg Box Spreads on NSE BANK NIFTY:
- Leg 1: Long Call K1
- Leg 2: Short Call K2 (K2 > K1)
- Leg 3: Long Put K2
- Leg 4: Short Put K1

Features:
1. Payoff invariance: Payoff at expiry is identically (K2 - K1).
2. Implied synthetic interest rate calculation:
   r_implied = (1 / T) * ln((K2 - K1) / Net_Debit)
3. Full Indian market statutory charge deduction:
   - STT: 0.10% on sell-side option premium (Legs 2 and 4).
   - Exchange Turnover Charge: 0.05% on total premium turnover.
   - GST: 18% on (Brokerage + Exchange Charges).
   - SEBI Turnover Fee: 0.0001% (Rs 10 per crore).
   - Stamp Duty: 0.003% on buy-side option premium (Legs 1 and 3).
   - Flat Brokerage: Rs 20 per order * 4 orders = Rs 80.
4. Frictional erosion gating: Distinguishes true net arbitrage from phantom spreads
   that get completely eroded by taxes, exchange fees, and bid-ask slippage.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Optional


@dataclasses.dataclass(frozen=True)
class BoxSpreadLegQuote:
    """Market quotes for an option leg in a box spread."""

    strike: float
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)


@dataclasses.dataclass(frozen=True)
class BoxSpreadArbitrageResult:
    """Quantitative report for a candidate 4-leg box spread arbitrage."""

    k1: float
    k2: float
    strike_width: float
    time_to_expiry_years: float
    net_debit_market: float  # Executed at Ask for buys, Bid for sells
    theoretical_pv: float    # (K2 - K1) * exp(-r * T)
    gross_arbitrage_profit: float  # (K2 - K1) - net_debit
    implied_synthetic_rate: float  # Annualized implied borrowing/lending rate
    total_statutory_charges: float # STT, GST, Exchange, SEBI, Stamp, Brokerage per lot
    net_arbitrage_profit_per_lot: float # Gross profit - total charges (for 1 lot = 15 or 30 qty)
    lot_size: int
    is_arbitrage_viable: bool
    status_message: str


class BoxSpreadArbitrageEngine:
    """Scans and evaluates European box spread mispricings with Indian tax frictions."""

    FLAT_BROKERAGE_PER_ORDER: float = 20.0  # Rs 20 per executed leg
    STT_SELL_PREMIUM_RATE: float = 0.0010  # 0.10% on sell premium
    EXCHANGE_TURNOVER_RATE: float = 0.0005  # 0.05% of premium turnover
    GST_RATE: float = 0.18                 # 18% on brokerage and exchange charges
    STAMP_DUTY_BUY_RATE: float = 0.00003   # 0.003% on buy premium
    SEBI_TURNOVER_RATE: float = 0.000001   # Rs 10 per crore (0.0001%)

    @classmethod
    def calculate_statutory_charges(
        cls,
        c1_ask: float,
        c2_bid: float,
        p2_ask: float,
        p1_bid: float,
        lot_size: int = 15,
    ) -> float:
        """Calculates total statutory friction for the 4 legs of a box spread per lot.

        Leg 1: BUY Call K1 (at Ask)
        Leg 2: SELL Call K2 (at Bid)
        Leg 3: BUY Put K2 (at Ask)
        Leg 4: SELL Put K1 (at Bid)
        """
        buy_premium_total = (c1_ask + p2_ask) * lot_size
        sell_premium_total = (c2_bid + p1_bid) * lot_size
        total_turnover = buy_premium_total + sell_premium_total

        # 1. Brokerage: Rs 20 * 4 legs = Rs 80
        brokerage = cls.FLAT_BROKERAGE_PER_ORDER * 4.0

        # 2. STT: 0.10% on sell premium
        stt = sell_premium_total * cls.STT_SELL_PREMIUM_RATE

        # 3. Exchange Turnover Charge
        exchange_charges = total_turnover * cls.EXCHANGE_TURNOVER_RATE

        # 4. GST: 18% on (Brokerage + Exchange)
        gst = (brokerage + exchange_charges) * cls.GST_RATE

        # 5. Stamp Duty: 0.003% on buy premium
        stamp_duty = buy_premium_total * cls.STAMP_DUTY_BUY_RATE

        # 6. SEBI Fee: 0.0001%
        sebi_fee = total_turnover * cls.SEBI_TURNOVER_RATE

        return brokerage + stt + exchange_charges + gst + stamp_duty + sebi_fee

    @classmethod
    def evaluate_box_spread(
        cls,
        call_k1: BoxSpreadLegQuote,
        call_k2: BoxSpreadLegQuote,
        put_k1: BoxSpreadLegQuote,
        put_k2: BoxSpreadLegQuote,
        time_to_expiry_years: float,
        risk_free_rate: float = 0.065,  # 6.5% RBI repo-linked risk-free benchmark
        lot_size: int = 15,
        min_net_profit_hurdle: float = 200.0,  # Minimum net profit hurdle in INR per lot
    ) -> BoxSpreadArbitrageResult:
        """Evaluates arbitrage viability and synthetic rate of a 4-leg box spread."""
        if call_k2.strike <= call_k1.strike:
            raise ValueError(f"K2 ({call_k2.strike}) must be strictly greater than K1 ({call_k1.strike})")
        if put_k2.strike != call_k2.strike or put_k1.strike != call_k1.strike:
            raise ValueError("Put strikes must match Call strikes (K1 and K2)")
        if time_to_expiry_years <= 0:
            raise ValueError("Time to expiry must be positive")

        strike_width = call_k2.strike - call_k1.strike
        theoretical_pv = strike_width * math.exp(-risk_free_rate * time_to_expiry_years)

        # Market execution debit (Buys at Ask, Sells at Bid)
        net_debit_market = (call_k1.ask - call_k2.bid) + (put_k2.ask - put_k1.bid)

        # Gross arbitrage profit per share
        gross_profit_per_share = strike_width - net_debit_market
        gross_profit_lot = gross_profit_per_share * lot_size

        # Implied synthetic interest rate
        if net_debit_market > 0 and strike_width > 0:
            implied_rate = (1.0 / time_to_expiry_years) * math.log(strike_width / net_debit_market)
        else:
            implied_rate = 0.0

        # Calculate exact Indian statutory charges
        total_charges = cls.calculate_statutory_charges(
            c1_ask=call_k1.ask,
            c2_bid=call_k2.bid,
            p2_ask=put_k2.ask,
            p1_bid=put_k1.bid,
            lot_size=lot_size,
        )

        net_profit_lot = gross_profit_lot - total_charges
        is_viable = net_profit_lot >= min_net_profit_hurdle

        if is_viable:
            status = f"ARBITRAGE_VIABLE: Net profit Rs {net_profit_lot:.2f} exceeds hurdle"
        elif gross_profit_lot > 0:
            status = f"EROSION_BY_FRICTION: Gross profit Rs {gross_profit_lot:.2f} eroded by Rs {total_charges:.2f} charges"
        else:
            status = f"NO_ARBITRAGE: Net debit Rs {net_debit_market:.2f} exceeds width Rs {strike_width:.2f}"

        return BoxSpreadArbitrageResult(
            k1=call_k1.strike,
            k2=call_k2.strike,
            strike_width=strike_width,
            time_to_expiry_years=time_to_expiry_years,
            net_debit_market=net_debit_market,
            theoretical_pv=theoretical_pv,
            gross_arbitrage_profit=gross_profit_lot,
            implied_synthetic_rate=implied_rate,
            total_statutory_charges=total_charges,
            net_arbitrage_profit_per_lot=net_profit_lot,
            lot_size=lot_size,
            is_arbitrage_viable=is_viable,
            status_message=status,
        )
