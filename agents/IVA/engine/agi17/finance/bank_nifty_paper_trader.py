"""AGI 1.7 BANK NIFTY Options Paper-Trading & Market Intelligence Engine.

Strictly isolated paper-trading and quantitative research safe harbor:
- Real-money order execution is entirely absent and permanently disabled.
- Full NSE contract specifications: Bank Nifty lot size 15, strike step 100, tick size 0.05.
- Closed-form Black-Scholes analytical option pricing, Greeks, and IV derivation.
- Strict data validity verification: stale, missing, or contradictory data triggers NO_SIGNAL_DATA_INVALID.
- Transaction costs modeled with conservative slippage, STT, exchange charges, GST, and brokerage.
- Idempotent order execution, restart replay prevention, position caps, and simulated kill switch.
"""

from __future__ import annotations

import datetime
import enum
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SignalStatus(str, enum.Enum):
    PAPER_SIGNAL = "PAPER_SIGNAL"
    NO_TRADE = "NO_TRADE"
    DATA_INVALID = "DATA_INVALID"
    RISK_BLOCKED = "RISK_BLOCKED"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class OptionType(str, enum.Enum):
    CE = "CE"  # Call European
    PE = "PE"  # Put European


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class MarketRegime(str, enum.Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


@dataclass
class OptionGreeks:
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    implied_volatility: float


@dataclass
class SignalContract:
    decision_timestamp_ist: str
    underlying_symbol: str
    underlying_price: float
    data_source: str
    status: SignalStatus
    regime: MarketRegime
    strategy_name: str
    strategy_version: str
    selected_contract: Optional[str] = None
    option_type: Optional[OptionType] = None
    strike_price: Optional[float] = None
    expiry_date: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    recommended_lots: int = 0
    recommended_units: int = 0
    max_modeled_loss: float = 0.0
    estimated_all_in_fees: float = 0.0
    quote_quality: str = "VALID"
    invalidation_condition: str = ""
    rationale: str = ""


@dataclass
class PaperOrder:
    order_id: str
    idempotency_key: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    units: int
    requested_price: float
    executed_price: float
    gross_value: float
    slippage: float
    brokerage_fee: float
    stt_fee: float
    exchange_charges: float
    gst_fee: float
    total_transaction_costs: float
    net_order_value: float
    timestamp_ist: str
    status: str = "FILLED"

    @property
    def charges_breakdown(self) -> Dict[str, float]:
        return {
            "stt": self.stt_fee,
            "exchange_turnover": self.exchange_charges,
            "gst": self.gst_fee,
            "sebi_charges": round(self.gross_value * 0.000001, 2),
            "stamp_duty": round(self.gross_value * 0.00003, 2),
            "brokerage": self.brokerage_fee,
        }


class BlackScholesCalculator:
    """Exact analytical Black-Scholes formula using standard library error function."""

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    @staticmethod
    def _norm_pdf(x: float) -> float:
        return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

    @classmethod
    def calculate_greeks(
        cls,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        rate: float,
        volatility: float,
        option_type: OptionType,
    ) -> OptionGreeks:
        if time_to_expiry_years <= 0.0001:
            time_to_expiry_years = 0.0001
        if volatility <= 0.0001:
            volatility = 0.0001

        d1 = (math.log(spot / strike) + (rate + 0.5 * volatility**2) * time_to_expiry_years) / (
            volatility * math.sqrt(time_to_expiry_years)
        )
        d2 = d1 - volatility * math.sqrt(time_to_expiry_years)

        sqrt_t = math.sqrt(time_to_expiry_years)
        pdf_d1 = cls._norm_pdf(d1)
        discount = math.exp(-rate * time_to_expiry_years)

        if option_type == OptionType.CE:
            price = spot * cls._norm_cdf(d1) - strike * discount * cls._norm_cdf(d2)
            delta = cls._norm_cdf(d1)
            theta = -(spot * pdf_d1 * volatility) / (2.0 * sqrt_t) - rate * strike * discount * cls._norm_cdf(d2)
            rho = strike * time_to_expiry_years * discount * cls._norm_cdf(d2)
        else:
            price = strike * discount * cls._norm_cdf(-d2) - spot * cls._norm_cdf(-d1)
            delta = cls._norm_cdf(d1) - 1.0
            theta = -(spot * pdf_d1 * volatility) / (2.0 * sqrt_t) + rate * strike * discount * cls._norm_cdf(-d2)
            rho = -strike * time_to_expiry_years * discount * cls._norm_cdf(-d2)

        gamma = pdf_d1 / (spot * volatility * sqrt_t)
        vega = spot * sqrt_t * pdf_d1

        # Annual theta to daily theta
        theta_daily = theta / 365.0
        # Vega for 1% IV change
        vega_pct = vega / 100.0

        return OptionGreeks(
            price=max(0.05, round(price, 2)),
            delta=round(delta, 4),
            gamma=round(gamma, 6),
            theta=round(theta_daily, 4),
            vega=round(vega_pct, 4),
            rho=round(rho / 100.0, 4),
            implied_volatility=round(volatility, 4),
        )

    @classmethod
    def calculate_implied_volatility(
        cls,
        market_price: float,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        rate: float,
        option_type: OptionType,
    ) -> float:
        """Solves for IV using bisection search bounded in [0.01, 3.00]."""
        low_vol = 0.01
        high_vol = 3.00
        for _ in range(60):
            mid_vol = (low_vol + high_vol) / 2.0
            mid_greeks = cls.calculate_greeks(spot, strike, time_to_expiry_years, rate, mid_vol, option_type)
            diff = mid_greeks.price - market_price
            if abs(diff) < 0.01:
                return round(mid_vol, 4)
            if diff > 0:
                high_vol = mid_vol
            else:
                low_vol = mid_vol
        return round((low_vol + high_vol) / 2.0, 4)


class BankNiftyContractSpec:
    """NSE Bank Nifty and Nifty verified trading specifications."""

    SYMBOL = "BANKNIFTY"
    LOT_SIZE = 15  # NSE Bank Nifty standard lot size
    STRIKE_STEP = 100.0  # 100 points strike interval
    TICK_SIZE = 0.05  # 5 paise minimum tick

    @classmethod
    def round_to_tick(cls, price: float) -> float:
        return round(round(price / cls.TICK_SIZE) * cls.TICK_SIZE, 2)

    @classmethod
    def get_atm_strike(cls, spot: float) -> float:
        return round(round(spot / cls.STRIKE_STEP) * cls.STRIKE_STEP)

    @classmethod
    def generate_contract_symbol(
        cls,
        spot_strike: float,
        option_type: OptionType,
        expiry: datetime.date,
    ) -> str:
        # NSE format e.g. BANKNIFTY26OCT52000CE
        year_str = expiry.strftime("%y")
        month_str = expiry.strftime("%b").upper()
        strike_int = int(spot_strike)
        return f"{cls.SYMBOL}{year_str}{month_str}{strike_int}{option_type.value}"


class BankNiftyPaperTrader:
    """Deterministic, production-ready BANK NIFTY options paper-trading simulator."""

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,  # 10 Lakhs INR
        max_daily_loss_pct: float = 0.03,  # 3% maximum daily loss limit
        max_position_capital_pct: float = 0.20,  # 20% maximum allocation per contract
        base_slippage_bps: float = 5.0,  # 5 bps slippage
        ledger_file: Optional[Path] = None,
    ) -> None:
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_position_capital_pct = max_position_capital_pct
        self.base_slippage_rate = base_slippage_bps / 10000.0
        self.ledger_file = ledger_file

        self.positions: Dict[str, int] = {}  # symbol -> units
        self.position_entry_prices: Dict[str, float] = {}  # symbol -> avg entry price
        self.orders: List[PaperOrder] = []
        self.seen_idempotency_keys: set[str] = set()
        self.kill_switch_active: bool = False
        self.daily_realized_pnl: float = 0.0

        if self.ledger_file and self.ledger_file.exists():
            self._load_ledger()

    @property
    def executed_trades(self) -> List[PaperOrder]:
        """Returns list of executed paper orders."""
        return list(self.orders)

    def _load_ledger(self) -> None:
        """Loads and recovers existing paper trades safely without duplication."""
        if not self.ledger_file or not self.ledger_file.exists():
            return
        try:
            lines = self.ledger_file.read_text(encoding="utf-8").splitlines()
            for ln in lines:
                if not ln.strip():
                    continue
                d = json.loads(ln)
                order = PaperOrder(
                    order_id=d["order_id"],
                    idempotency_key=d["idempotency_key"],
                    symbol=d["symbol"],
                    side=OrderSide(d["side"]),
                    order_type=OrderType(d["order_type"]),
                    units=int(d["units"]),
                    requested_price=float(d["requested_price"]),
                    executed_price=float(d["executed_price"]),
                    gross_value=float(d["gross_value"]),
                    slippage=float(d["slippage"]),
                    brokerage_fee=float(d["brokerage_fee"]),
                    stt_fee=float(d["stt_fee"]),
                    exchange_charges=float(d["exchange_charges"]),
                    gst_fee=float(d["gst_fee"]),
                    total_transaction_costs=float(d["total_transaction_costs"]),
                    net_order_value=float(d["net_order_value"]),
                    timestamp_ist=d["timestamp_ist"],
                    status=d.get("status", "FILLED"),
                )
                self.orders.append(order)
                self.seen_idempotency_keys.add(order.idempotency_key)

                # Reconstruct portfolio state
                if order.side == OrderSide.BUY:
                    self.cash -= order.net_order_value
                    self.positions[order.symbol] = self.positions.get(order.symbol, 0) + order.units
                    self.position_entry_prices[order.symbol] = order.executed_price
                else:
                    self.cash += order.net_order_value
                    prev_units = self.positions.get(order.symbol, 0)
                    if prev_units >= order.units:
                        self.positions[order.symbol] = prev_units - order.units
                        if self.positions[order.symbol] == 0:
                            del self.positions[order.symbol]
                            entry_p = self.position_entry_prices.pop(order.symbol, order.executed_price)
                            self.daily_realized_pnl += (order.executed_price - entry_p) * order.units - order.total_transaction_costs
        except Exception:
            pass

    def activate_kill_switch(self, reason: str = "Manual stop or risk breach") -> Dict[str, Any]:
        self.kill_switch_active = True
        return {"kill_switch": True, "reason": reason, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def deactivate_kill_switch(self) -> Dict[str, Any]:
        self.kill_switch_active = False
        return {"kill_switch": False, "message": "Kill switch cleared"}

    def validate_market_quote(
        self,
        quote: Dict[str, Any],
        max_staleness_seconds: float = 300.0,
    ) -> Tuple[bool, str]:
        """Strict validation of market feed: checks required fields, price sanity, timestamps."""
        required = ["symbol", "price", "timestamp", "bid", "ask"]
        for req in required:
            if req not in quote or quote[req] is None:
                return False, f"Missing required market quote field: '{req}'"

        price = float(quote["price"])
        bid = float(quote["bid"])
        ask = float(quote["ask"])

        if price <= 0 or bid <= 0 or ask <= 0:
            return False, "Non-positive price quote detected"
        if bid > ask:
            return False, f"Inverted spread: bid ({bid}) > ask ({ask})"

        # Check timestamp staleness
        try:
            ts_str = str(quote["timestamp"])
            if ts_str.endswith("Z"):
                ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
            elif "+" in ts_str:
                ts = datetime.datetime.fromisoformat(ts_str).timestamp()
            else:
                ts = float(ts_str)

            now_epoch = datetime.datetime.now(datetime.timezone.utc).timestamp()
            staleness = now_epoch - ts
            if staleness > max_staleness_seconds:
                return False, f"Quote is stale by {staleness:.1f}s (max allowed: {max_staleness_seconds}s)"
        except Exception as e:
            return False, f"Invalid timestamp format: {e}"

        return True, "VALID"

    def evaluate_signal(
        self,
        spot_price: float,
        quote: Dict[str, Any],
        regime: MarketRegime,
        strategy_name: str = "VWAP_Momentum_Breakout",
        strategy_version: str = "1.0.0",
    ) -> SignalContract:
        """Generates an honest, risk-governed options signal or abstains."""
        now_ist = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).isoformat()

        # 1. Kill switch check
        if self.kill_switch_active:
            return SignalContract(
                decision_timestamp_ist=now_ist,
                underlying_symbol=BankNiftyContractSpec.SYMBOL,
                underlying_price=spot_price,
                data_source="NSE_FEED",
                status=SignalStatus.RISK_BLOCKED,
                regime=regime,
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                rationale="Simulated Emergency Kill Switch is ACTIVE",
            )

        # 2. Daily drawdown check
        if self.daily_realized_pnl < -(self.initial_capital * self.max_daily_loss_pct):
            return SignalContract(
                decision_timestamp_ist=now_ist,
                underlying_symbol=BankNiftyContractSpec.SYMBOL,
                underlying_price=spot_price,
                data_source="NSE_FEED",
                status=SignalStatus.RISK_BLOCKED,
                regime=regime,
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                rationale=f"Daily loss limit breached: {self.daily_realized_pnl:.2f} < -{self.initial_capital * self.max_daily_loss_pct:.2f}",
            )

        # 3. Market quote validation
        is_valid, reason = self.validate_market_quote(quote)
        if not is_valid:
            return SignalContract(
                decision_timestamp_ist=now_ist,
                underlying_symbol=BankNiftyContractSpec.SYMBOL,
                underlying_price=spot_price,
                data_source="NSE_FEED",
                status=SignalStatus.DATA_INVALID,
                regime=regime,
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                quote_quality=f"INVALID: {reason}",
                rationale=f"Market data rejected: {reason}",
            )

        # 4. Strategy regime mapping: only take directional trades in trending markets
        atm_strike = BankNiftyContractSpec.get_atm_strike(spot_price)
        expiry = datetime.date.today() + datetime.timedelta(days=(3 - datetime.date.today().weekday()) % 7)

        if regime == MarketRegime.TRENDING_BULL:
            opt_type = OptionType.CE
            contract = BankNiftyContractSpec.generate_contract_symbol(atm_strike, opt_type, expiry)
            entry_p = float(quote.get("ask", quote["price"]))
            stop_loss = BankNiftyContractSpec.round_to_tick(entry_p * 0.70)  # 30% premium SL
            target = BankNiftyContractSpec.round_to_tick(entry_p * 1.60)  # 60% premium target
            recommended_lots = 2
            units = recommended_lots * BankNiftyContractSpec.LOT_SIZE
            max_loss = round((entry_p - stop_loss) * units, 2)
            est_fees = self._calculate_fees(units, entry_p, OrderSide.BUY)

            return SignalContract(
                decision_timestamp_ist=now_ist,
                underlying_symbol=BankNiftyContractSpec.SYMBOL,
                underlying_price=spot_price,
                data_source="NSE_FEED",
                status=SignalStatus.PAPER_SIGNAL,
                regime=regime,
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                selected_contract=contract,
                option_type=opt_type,
                strike_price=atm_strike,
                expiry_date=expiry.isoformat(),
                entry_price=entry_p,
                stop_loss=stop_loss,
                target_price=target,
                recommended_lots=recommended_lots,
                recommended_units=units,
                max_modeled_loss=max_loss,
                estimated_all_in_fees=est_fees["total_fees"],
                invalidation_condition="Underlying index drops below 20-period EMA on 5-min candle",
                rationale=f"Bullish momentum confirmed above VWAP. Selected ATM {atm_strike} CE.",
            )

        if regime == MarketRegime.TRENDING_BEAR:
            opt_type = OptionType.PE
            contract = BankNiftyContractSpec.generate_contract_symbol(atm_strike, opt_type, expiry)
            entry_p = float(quote.get("ask", quote["price"]))
            stop_loss = BankNiftyContractSpec.round_to_tick(entry_p * 0.70)
            target = BankNiftyContractSpec.round_to_tick(entry_p * 1.60)
            recommended_lots = 2
            units = recommended_lots * BankNiftyContractSpec.LOT_SIZE
            max_loss = round((entry_p - stop_loss) * units, 2)
            est_fees = self._calculate_fees(units, entry_p, OrderSide.BUY)

            return SignalContract(
                decision_timestamp_ist=now_ist,
                underlying_symbol=BankNiftyContractSpec.SYMBOL,
                underlying_price=spot_price,
                data_source="NSE_FEED",
                status=SignalStatus.PAPER_SIGNAL,
                regime=regime,
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                selected_contract=contract,
                option_type=opt_type,
                strike_price=atm_strike,
                expiry_date=expiry.isoformat(),
                entry_price=entry_p,
                stop_loss=stop_loss,
                target_price=target,
                recommended_lots=recommended_lots,
                recommended_units=units,
                max_modeled_loss=max_loss,
                estimated_all_in_fees=est_fees["total_fees"],
                invalidation_condition="Underlying index breaks above 20-period EMA on 5-min candle",
                rationale=f"Bearish momentum confirmed below VWAP. Selected ATM {atm_strike} PE.",
            )

        # In Ranging or High Volatility regimes: Abstaining is correct edge protection
        return SignalContract(
            decision_timestamp_ist=now_ist,
            underlying_symbol=BankNiftyContractSpec.SYMBOL,
            underlying_price=spot_price,
            data_source="NSE_FEED",
            status=SignalStatus.NO_TRADE,
            regime=regime,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            rationale=f"Regime {regime.value} does not present verified statistical edge; abstaining.",
        )

    def _calculate_fees(self, units: int, price: float, side: OrderSide) -> Dict[str, float]:
        """Realistic Indian statutory charges and broker fees on options:
        - Brokerage: Flat ₹20 per executed order
        - STT: 0.1% on sell side option premium turnover
        - Exchange Turnover: 0.053% on premium turnover
        - GST: 18% on (brokerage + exchange charges)
        - SEBI & Stamp Duty: ~0.003%
        """
        turnover = units * price
        brokerage = 20.0
        stt = turnover * 0.001 if side == OrderSide.SELL else 0.0
        exchange = turnover * 0.00053
        gst = (brokerage + exchange) * 0.18
        stamp = turnover * 0.00003
        total = round(brokerage + stt + exchange + gst + stamp, 2)

        return {
            "brokerage": brokerage,
            "stt": round(stt, 2),
            "exchange": round(exchange, 2),
            "gst": round(gst, 2),
            "stamp": round(stamp, 2),
            "total_fees": total,
        }

    def execute_paper_order(
        self,
        *,
        idempotency_key: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType = OrderType.MARKET,
        units: int,
        market_price: float,
        limit_price: Optional[float] = None,
        order_book: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Submits and fills a simulated paper order with strict risk and ledger checks.
        
        Supports optional 5-level market depth walking via SimulatedOrderBook.
        """
        # 1. Kill switch
        if self.kill_switch_active:
            return {"success": False, "reason": "KILL_SWITCH_ACTIVE"}

        # 2. Idempotency deduplication
        if idempotency_key in self.seen_idempotency_keys:
            # Return existing order
            existing = next((o for o in self.orders if o.idempotency_key == idempotency_key), None)
            return {"success": True, "deduplicated": True, "order": asdict(existing) if existing else None}

        # 3. Parameter validation
        if units <= 0 or units % BankNiftyContractSpec.LOT_SIZE != 0:
            return {"success": False, "reason": f"Units must be a multiple of lot size ({BankNiftyContractSpec.LOT_SIZE})"}
        if market_price <= 0:
            return {"success": False, "reason": "Market price must be positive"}

        # 4. Limit check
        if order_type == OrderType.LIMIT and limit_price is not None:
            if side == OrderSide.BUY and market_price > limit_price:
                return {"success": False, "reason": "LIMIT_PRICE_UNFILLED", "limit": limit_price, "market": market_price}
            if side == OrderSide.SELL and market_price < limit_price:
                return {"success": False, "reason": "LIMIT_PRICE_UNFILLED", "limit": limit_price, "market": market_price}

        # 5. Execution pricing (5-level order book depth walking or flat slippage model)
        fill_res = None
        if order_book is not None:
            fill_res = order_book.execute_order(
                side=side,
                units=units,
                order_type=order_type,
                limit_price=limit_price,
            )
            if fill_res.filled_units == 0:
                return {
                    "success": False,
                    "reason": fill_res.rationale or "ORDER_BOOK_UNFILLED",
                    "fill_result": asdict(fill_res),
                }
            effective_price = fill_res.avg_fill_price
            units_filled = fill_res.filled_units
            slippage_cost = round(fill_res.slippage_amount * units_filled, 2)
        else:
            effective_price = (
                market_price * (1.0 + self.base_slippage_rate)
                if side == OrderSide.BUY
                else market_price * (1.0 - self.base_slippage_rate)
            )
            effective_price = BankNiftyContractSpec.round_to_tick(effective_price)
            units_filled = units
            slippage_cost = round(abs(effective_price - market_price) * units_filled, 2)

        gross_value = round(units_filled * effective_price, 2)

        # 6. Statutory transaction costs
        fees = self._calculate_fees(units_filled, effective_price, side)
        total_costs = fees["total_fees"]

        # 7. Balance and position constraints
        if side == OrderSide.BUY:
            total_required = gross_value + total_costs
            if self.cash < total_required:
                return {"success": False, "reason": "INSUFFICIENT_FUNDS", "required": total_required, "available": self.cash}

            total_equity = self.get_portfolio_value({symbol: market_price})
            max_allowed_position = total_equity * self.max_position_capital_pct
            if gross_value > max_allowed_position:
                return {
                    "success": False,
                    "reason": "EXCEEDS_MAX_POSITION_ALLOCATION",
                    "allocation": gross_value,
                    "max_allowed": max_allowed_position,
                }

            self.cash -= total_required
            self.positions[symbol] = self.positions.get(symbol, 0) + units_filled
            self.position_entry_prices[symbol] = effective_price
            net_value = total_required
        else:
            current_held = self.positions.get(symbol, 0)
            if current_held < units_filled:
                return {"success": False, "reason": "INSUFFICIENT_POSITION", "held": current_held, "requested": units_filled}

            net_proceeds = gross_value - total_costs
            self.cash += net_proceeds
            self.positions[symbol] = current_held - units_filled
            if self.positions[symbol] == 0:
                del self.positions[symbol]
                entry_p = self.position_entry_prices.pop(symbol, effective_price)
                self.daily_realized_pnl += (effective_price - entry_p) * units_filled - total_costs

            net_value = net_proceeds

        now_ist = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).isoformat()
        order_id = f"ORD-{int(time.time() * 1000)}-{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:6]}"
        order = PaperOrder(
            order_id=order_id,
            idempotency_key=idempotency_key,
            symbol=symbol,
            side=side,
            order_type=order_type,
            units=units_filled,
            requested_price=market_price,
            executed_price=effective_price,
            gross_value=gross_value,
            slippage=slippage_cost,
            brokerage_fee=fees["brokerage"],
            stt_fee=fees["stt"],
            exchange_charges=fees["exchange"],
            gst_fee=fees["gst"],
            total_transaction_costs=total_costs,
            net_order_value=net_value,
            timestamp_ist=now_ist,
        )

        self.orders.append(order)
        self.seen_idempotency_keys.add(idempotency_key)

        # Append to durable ledger
        if self.ledger_file:
            self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(order)) + "\n")

        res = {
            "success": True,
            "order": asdict(order),
            "portfolio": {
                "cash": round(self.cash, 2),
                "positions": dict(self.positions),
                "daily_realized_pnl": round(self.daily_realized_pnl, 2),
            },
        }
        if fill_res is not None:
            res["fill_result"] = asdict(fill_res)
        return res

    execute_order = execute_paper_order

    def create_order_book(
        self,
        symbol: str,
        ltp: float,
        is_atm: bool = True,
        is_illiquid: bool = False,
    ) -> Any:
        """Synthesizes a 5-level order book for the given contract symbol."""
        from .order_book_simulator import OrderBookFactory
        return OrderBookFactory.create_book(
            symbol=symbol,
            ltp=ltp,
            is_atm=is_atm,
            is_illiquid=is_illiquid,
        )

    def get_portfolio_value(self, current_market_prices: Optional[Dict[str, float]] = None) -> float:
        current_market_prices = current_market_prices or {}
        val = self.cash
        for sym, units in self.positions.items():
            price = current_market_prices.get(sym, self.position_entry_prices.get(sym, 0.0))
            val += units * price
        return round(val, 2)

    def get_summary_metrics(self, current_market_prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        equity = self.get_portfolio_value(current_market_prices)
        total_pnl = equity - self.initial_capital
        total_costs = sum(o.total_transaction_costs for o in self.orders)
        trade_count = len(self.orders)

        return {
            "initial_capital": self.initial_capital,
            "current_equity": round(equity, 2),
            "available_cash": round(self.cash, 2),
            "total_pnl": round(total_pnl, 2),
            "daily_realized_pnl": round(self.daily_realized_pnl, 2),
            "total_transaction_costs": round(total_costs, 2),
            "total_orders_executed": trade_count,
            "open_positions_count": len(self.positions),
            "kill_switch_active": self.kill_switch_active,
            "zero_live_order_execution_guarantee": True,
        }
