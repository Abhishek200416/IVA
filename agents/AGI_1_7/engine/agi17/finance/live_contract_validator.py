"""Authoritative Live Contract Validation Layer for AGI 1.7 OMEGA COMMAND Phase 4.

Validates contract details visible in the Paytm Money broker UI before any order:
- Underlying index (NIFTY, BANKNIFTY)
- Instrument type, Strike, Expiry, Option Type (CE, PE)
- Order direction (BUY only for new entries; SELL strictly for validated exit of owned position)
- Strict prohibition of uncovered short options
- Lot size and minimum risk bounds vs configured max loss per trade
- Quote freshness and bid-ask spread tolerances
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class LiveContract:
    """Represents a validated derivative contract visible in Paytm Money."""
    underlying: str  # "NIFTY" or "BANKNIFTY"
    strike: float
    option_type: OptionType
    expiry_date: str  # Format: "YYYY-MM-DD"
    lot_size: int
    ltp: float
    bid: float
    ask: float
    timestamp: float
    exchange: str = "NSE"
    segment: str = "NFO"
    symbol: str = ""
    is_tradable: bool = True
    cycle_type: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.symbol:
            self.symbol = f"{self.underlying}{self.expiry_date.replace('-', '')}{int(self.strike)}{self.option_type.value}"


@dataclass
class ContractValidationResult:
    """Outcome of contract validation."""
    is_valid: bool
    reasons: List[str] = field(default_factory=list)
    contract: Optional[LiveContract] = None
    min_lot_risk_inr: float = 0.0
    is_exit_order: bool = False
    validation_timestamp: str = ""


class LiveContractValidator:
    """Authoritative contract validation engine for live brokerage execution."""

    STANDARD_LOT_SIZES = {
        "NIFTY": [25, 50, 65, 75],
        "BANKNIFTY": [15, 25, 30, 35],
        "FINNIFTY": [60, 65],
        "MIDCPNIFTY": [120, 140],
        "NIFTYNXT50": [25],
    }

    TICK_SIZE: float = 0.05

    def __init__(
        self,
        max_spread_pct: float = 0.08,
        max_quote_age_sec: float = 5.0,
        calendar: Optional[Any] = None,
    ) -> None:
        self.max_spread_pct = max_spread_pct
        self.max_quote_age_sec = max_quote_age_sec
        self.calendar = calendar

    @classmethod
    def get_standard_lot_size(
        cls,
        underlying: str,
        as_of_date: Optional[str | datetime.date] = None,
        expiry_date: Optional[str | datetime.date] = None,
        cycle_type: Optional[str] = None,
    ) -> int:
        """Resolves date-appropriate and expiry-aware standard lot size per NSE circulars.

        Authoritative Circulars & Annexures:
        1. NSE Circular NSE/FAOP/70616 (Dated: Oct 3, 2025 | Effective: Oct 28, 2025 EOD):
           - Prescribed Lot Revisions:
             * NIFTY 50: Revised from 75 to 65
             * BANK NIFTY: Revised from 35 to 30
             * FINNIFTY: Revised from 65 to 60
             * MIDCPNIFTY: Revised from 140 to 120
             * NIFTYNXT50: 25 (Unchanged)
           - Transition Cycle Rules:
             * Weekly & Monthly Contracts: Existing unexpired weekly and monthly contracts
               expiring on or before December 30, 2025 continue with existing lot sizes (75 / 35).
               Contracts expiring after December 30, 2025 adopt revised lots (65 / 30).
             * Quarterly & Half-Yearly Contracts: Existing quarterly and half-yearly contracts
               (e.g. March 2026, June 2026 expiries) maintained existing lot sizes (75 / 35)
               when observed on or before December 30, 2025 EOD. At EOD on December 30, 2025,
               their market lot was automatically revised to 65 / 30.
        2. SEBI Index Derivative Framework (Nov 20, 2024 to Oct 28, 2025):
           - NIFTY: 75 | BANKNIFTY: 35
        3. NSE Circular NSE/FAOP/61320 (April 26, 2024 to Nov 19, 2024):
           - NIFTY: 25 | BANKNIFTY: 15
        4. NSE Circular NSE/FAOP/57014 (July 1, 2023 to April 25, 2024):
           - NIFTY: 50 | BANKNIFTY: 15
        5. Historical Frameworks:
           - July 1, 2021 to June 30, 2023: NIFTY 50 | BANKNIFTY 25
           - Prior to July 1, 2021: NIFTY 75 | BANKNIFTY 25

        Fails closed on unknown underlyings, invalid date formats, or contradictory metadata.
        """
        if not underlying or not isinstance(underlying, str):
            raise ValueError(
                f"UNKNOWN_UNDERLYING: Underlying instrument must be a non-empty string, got '{underlying}'."
            )

        und = underlying.upper().strip().replace(" ", "").replace("-", "")
        if und in ("NIFTY", "NIFTY50"):
            canonical_und = "NIFTY"
        elif und in ("BANKNIFTY", "NIFTYBANK"):
            canonical_und = "BANKNIFTY"
        else:
            raise ValueError(
                f"UNKNOWN_UNDERLYING: Cannot determine standard lot size for unsupported underlying '{underlying}'. "
                "Only 'NIFTY' and 'BANKNIFTY' are permitted for autonomous execution."
            )

        # Parse and validate dates
        parsed_as_of: Optional[datetime.date] = None
        if as_of_date is not None:
            if isinstance(as_of_date, (datetime.datetime, datetime.date)):
                parsed_as_of = as_of_date.date() if isinstance(as_of_date, datetime.datetime) else as_of_date
            else:
                try:
                    parsed_as_of = datetime.date.fromisoformat(str(as_of_date).strip()[:10])
                except Exception as e:
                    raise ValueError(f"INVALID_DATE_METADATA: Failed to parse as_of_date '{as_of_date}': {e}")

        parsed_expiry: Optional[datetime.date] = None
        if expiry_date is not None:
            if isinstance(expiry_date, (datetime.datetime, datetime.date)):
                parsed_expiry = expiry_date.date() if isinstance(expiry_date, datetime.datetime) else expiry_date
            else:
                try:
                    parsed_expiry = datetime.date.fromisoformat(str(expiry_date).strip()[:10])
                except Exception as e:
                    raise ValueError(f"INVALID_DATE_METADATA: Failed to parse expiry_date '{expiry_date}': {e}")

        # Check for contradictory metadata
        if parsed_as_of and parsed_expiry:
            if parsed_expiry < parsed_as_of:
                raise ValueError(
                    f"CONTRADICTORY_METADATA: Contract expiry date ({parsed_expiry}) is strictly prior "
                    f"to observation as_of_date ({parsed_as_of}). Cannot trade expired contract."
                )

        # Default trade date if completely omitted
        trade_dt = parsed_as_of or datetime.date(2026, 10, 13)

        # Determine cycle type
        norm_cycle = cycle_type.upper().strip() if cycle_type else None
        is_quarterly_or_half = norm_cycle in ("QUARTERLY", "HALF_YEARLY", "ANNUAL")
        if not norm_cycle and parsed_as_of and parsed_expiry:
            days_to_expiry = (parsed_expiry - parsed_as_of).days
            if days_to_expiry > 85 and parsed_expiry.month in (3, 6, 9, 12):
                is_quarterly_or_half = True

        # Key regulatory cutoffs under NSE/FAOP/70616
        EOD_OCT_28_2025 = datetime.date(2025, 10, 28)
        EOD_DEC_30_2025 = datetime.date(2025, 12, 30)

        # NIFTYNEXT50 is unchanged at 25 across all regimes
        if canonical_und == "NIFTYNXT50":
            return 25

        # FINNIFTY
        if canonical_und == "FINNIFTY":
            ref = parsed_expiry or trade_dt
            if ref > EOD_DEC_30_2025:
                return 60
            return 65

        # MIDCPNIFTY
        if canonical_und == "MIDCPNIFTY":
            ref = parsed_expiry or trade_dt
            if ref > EOD_DEC_30_2025:
                return 120
            return 140

        # NIFTY 50
        if canonical_und == "NIFTY":
            if parsed_expiry is not None:
                if parsed_expiry > EOD_DEC_30_2025:
                    if is_quarterly_or_half and trade_dt <= EOD_DEC_30_2025:
                        return 75
                    return 65
                elif parsed_expiry > EOD_OCT_28_2025:
                    return 75
                elif parsed_expiry >= datetime.date(2024, 11, 20):
                    return 75
                elif parsed_expiry >= datetime.date(2024, 4, 26):
                    return 25
                elif parsed_expiry >= datetime.date(2021, 7, 1):
                    return 50
                else:
                    return 75
            else:
                if trade_dt > EOD_DEC_30_2025:
                    return 65
                elif trade_dt >= datetime.date(2024, 11, 20):
                    return 75
                elif trade_dt >= datetime.date(2024, 4, 26):
                    return 25
                elif trade_dt >= datetime.date(2021, 7, 1):
                    return 50
                else:
                    return 75

        # BANKNIFTY
        if canonical_und == "BANKNIFTY":
            if parsed_expiry is not None:
                if parsed_expiry > EOD_DEC_30_2025:
                    if is_quarterly_or_half and trade_dt <= EOD_DEC_30_2025:
                        return 35
                    return 30
                elif parsed_expiry > EOD_OCT_28_2025:
                    return 35
                elif parsed_expiry >= datetime.date(2024, 11, 20):
                    return 35
                elif parsed_expiry >= datetime.date(2023, 7, 1):
                    return 15
                else:
                    return 25
            else:
                if trade_dt > EOD_DEC_30_2025:
                    return 30
                elif trade_dt >= datetime.date(2024, 11, 20):
                    return 35
                elif trade_dt >= datetime.date(2023, 7, 1):
                    return 15
                else:
                    return 25

        raise ValueError(f"UNRESOLVED_LOT_METADATA: Cannot resolve lot size for {underlying} ({as_of_date}, {expiry_date}).")

    @classmethod
    def is_valid_lot_size(
        cls,
        underlying: str,
        quantity: int,
        as_of_date: Optional[str | datetime.date] = None,
        expiry_date: Optional[str | datetime.date] = None,
        cycle_type: Optional[str] = None,
    ) -> bool:
        """Validates that quantity is a positive, non-zero integer multiple of the statutory lot size."""
        if quantity <= 0:
            return False
        try:
            std_lot = cls.get_standard_lot_size(
                underlying,
                as_of_date=as_of_date,
                expiry_date=expiry_date,
                cycle_type=cycle_type,
            )
            return (quantity % std_lot) == 0
        except ValueError:
            return False

    def validate_contract(
        self,
        raw_contract: Dict[str, Any] | LiveContract,
        action: str | OrderAction,
        is_exit: bool = False,
        owned_position: Optional[Dict[str, Any]] = None,
        max_loss_per_trade_inr: float = 5000.0,
        stop_loss_pts: Optional[float] = None,
        now_dt: Optional[datetime.datetime] = None,
        check_calendar: bool = False,
    ) -> ContractValidationResult:
        """Validates visible contract against all Phase 4 live safety constraints."""
        reasons: List[str] = []
        now_dt = now_dt or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        now_ts = now_dt.timestamp()
        time_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        # 0. Calendar Session Validation (if enabled)
        if check_calendar and self.calendar is not None:
            phase = self.calendar.get_current_session_phase(now_dt)
            phase_val = getattr(phase, "value", str(phase))
            if phase_val == "WEEKEND_CLOSED":
                reasons.append(f"CALENDAR_REJECTION [WEEKEND_CLOSED]: Trading halted. Market is closed on weekend ({now_dt.strftime('%A %Y-%m-%d')}).")
            elif phase_val == "HOLIDAY_CLOSED":
                reasons.append(f"CALENDAR_REJECTION [HOLIDAY_CLOSED]: Trading halted. Market is closed for official exchange holiday on {now_dt.strftime('%Y-%m-%d')}.")
            elif phase_val == "OVERNIGHT_CLOSED":
                reasons.append(f"CALENDAR_REJECTION [OVERNIGHT_CLOSED]: Trading halted. Outside official market trading hours ({now_dt.strftime('%H:%M:%S IST')}).")

        # Normalize contract object
        if isinstance(raw_contract, dict):
            underlying = str(raw_contract.get("underlying", "")).upper()
            strike = float(raw_contract.get("strike", 0.0))
            raw_opt = str(raw_contract.get("option_type", raw_contract.get("call_put", ""))).upper()
            expiry_str = str(raw_contract.get("expiry_date", raw_contract.get("expiry", "")))
            lot_size = int(raw_contract.get("lot_size", 0))
            ltp = float(raw_contract.get("ltp", raw_contract.get("price", 0.0)))
            bid = float(raw_contract.get("bid", ltp * 0.995))
            ask = float(raw_contract.get("ask", ltp * 1.005))
            ts = float(raw_contract.get("timestamp", now_ts))
            symbol = str(raw_contract.get("symbol", ""))
            tradable = bool(raw_contract.get("is_tradable", True))
            exchange = str(raw_contract.get("exchange", "NSE")).upper()
            segment = str(raw_contract.get("segment", "NFO")).upper()
            cycle_type = raw_contract.get("cycle_type", None)

            try:
                opt_type = OptionType(raw_opt)
            except ValueError:
                return ContractValidationResult(
                    is_valid=False,
                    reasons=[f"Invalid option type '{raw_opt}'. Must be 'CE' or 'PE'."],
                    validation_timestamp=time_str,
                )

            contract = LiveContract(
                underlying=underlying,
                strike=strike,
                option_type=opt_type,
                expiry_date=expiry_str,
                lot_size=lot_size,
                ltp=ltp,
                bid=bid,
                ask=ask,
                timestamp=ts,
                exchange=exchange,
                segment=segment,
                symbol=symbol,
                is_tradable=tradable,
                cycle_type=cycle_type,
            )
        else:
            contract = raw_contract

        action_norm = OrderAction(action) if isinstance(action, str) else action

        # 1. Underlying validation
        if contract.underlying not in ("NIFTY", "BANKNIFTY"):
            rejections = f"Unauthorized underlying '{contract.underlying}'. Only 'NIFTY' and 'BANKNIFTY' are permitted."
            reasons.append(rejections)

        # 1b. Symbol Identity Validation
        if contract.symbol:
            sym_clean = contract.symbol.upper().replace(" ", "")
            if contract.underlying not in sym_clean:
                reasons.append(f"Contract symbol mismatch: Underlying '{contract.underlying}' not in symbol '{contract.symbol}'.")
            if contract.option_type.value not in sym_clean:
                reasons.append(f"Contract symbol mismatch: Option type '{contract.option_type.value}' not in symbol '{contract.symbol}'.")
            if str(int(contract.strike)) not in sym_clean:
                reasons.append(f"Contract symbol mismatch: Strike {contract.strike} not in symbol '{contract.symbol}'.")

        # 2. Exchange & Segment validation
        if contract.exchange != "NSE" or contract.segment != "NFO":
            reasons.append(f"Invalid exchange/segment '{contract.exchange}/{contract.segment}'. Must be NSE/NFO.")

        # 3. Tradable status
        if not contract.is_tradable:
            reasons.append("Contract is marked non-tradable or halted on broker interface.")

        # 4. Expiry validation
        try:
            exp_date = datetime.date.fromisoformat(contract.expiry_date)
            today_date = now_dt.date()
            if exp_date < today_date:
                reasons.append(f"Contract has already expired on {contract.expiry_date}.")
            elif exp_date == today_date and (now_dt.hour > 15 or (now_dt.hour == 15 and now_dt.minute >= 40)):
                reasons.append(f"Same-day contract expiry session has ended for {contract.expiry_date} (15:40 IST close).")
        except ValueError:
            reasons.append(f"Invalid expiry date format '{contract.expiry_date}'. Expected YYYY-MM-DD.")

        # 5. Strike validation
        if contract.strike <= 0:
            reasons.append(f"Invalid non-positive strike price: {contract.strike}.")

        # 6. Lot size validation
        if contract.lot_size <= 0:
            reasons.append(f"Invalid lot size: {contract.lot_size}.")
        else:
            try:
                expected_std_lot = self.get_standard_lot_size(
                    underlying=contract.underlying,
                    as_of_date=now_dt.date(),
                    expiry_date=contract.expiry_date,
                    cycle_type=contract.cycle_type,
                )
                if contract.lot_size != expected_std_lot:
                    reasons.append(
                        f"Lot size {contract.lot_size} does not match statutory standard lot size {expected_std_lot} "
                        f"for {contract.underlying} (expiry {contract.expiry_date})."
                    )
            except ValueError as ve:
                reasons.append(str(ve))

        # 7. Quote, tick size, and freshness validation
        if contract.ltp < self.TICK_SIZE:
            reasons.append(f"LTP ₹{contract.ltp:.2f} is below NSE tick size of ₹{self.TICK_SIZE:.2f}.")
        elif abs(contract.ltp - round(contract.ltp / self.TICK_SIZE) * self.TICK_SIZE) > 1e-4:
            reasons.append(f"LTP ₹{contract.ltp:.2f} is not a valid multiple of NSE tick size ₹{self.TICK_SIZE:.2f}.")

        quote_age = now_ts - contract.timestamp
        if quote_age > self.max_quote_age_sec:
            reasons.append(f"Quote data is stale ({quote_age:.2f}s > {self.max_quote_age_sec}s maximum).")

        # 8. Bid-Ask spread validation
        if contract.bid > contract.ask:
            reasons.append(f"Inverted bid-ask spread: Bid ₹{contract.bid:.2f} > Ask ₹{contract.ask:.2f}.")
        elif contract.ask > 0:
            spread_pct = (contract.ask - contract.bid) / contract.ask
            if spread_pct > self.max_spread_pct:
                reasons.append(f"Bid-ask spread ({spread_pct * 100:.2f}%) exceeds {self.max_spread_pct * 100:.1f}% tolerance.")

        # 9. DIRECTION & STRATEGY RULE: Initial live deployment strictly permits LONG CALL and LONG PUT entries.
        # SELL is permitted ONLY as an exit against an owned position.
        if action_norm == OrderAction.SELL:
            if not is_exit:
                reasons.append(
                    "UNCOVERED SHORT OPTION REJECTED: Initial Phase 4 live deployment strictly permits "
                    "LONG CALL and LONG PUT entries. Naked option writing is prohibited."
                )
            else:
                if not owned_position:
                    reasons.append("Sell exit rejected: No corresponding owned position provided.")
                else:
                    pos_symbol = owned_position.get("symbol", "")
                    pos_qty = owned_position.get("quantity", 0)
                    if pos_symbol and contract.symbol and pos_symbol != contract.symbol:
                        reasons.append(
                            f"Sell exit contract mismatch: Owned '{pos_symbol}' vs Selected '{contract.symbol}'."
                        )
                    if pos_qty <= 0:
                        reasons.append("Sell exit rejected: Owned position quantity is zero.")

        # 10. Per-trade risk limit check
        # For a long option, max loss if held to zero is lot_size * ltp.
        # If stop_loss_pts is provided, risk is lot_size * stop_loss_pts.
        effective_loss_pts = stop_loss_pts if stop_loss_pts and stop_loss_pts < contract.ltp else contract.ltp
        min_lot_risk = contract.lot_size * effective_loss_pts

        if not is_exit and action_norm == OrderAction.BUY:
            if min_lot_risk > max_loss_per_trade_inr:
                reasons.append(
                    f"Per-trade risk violation: Minimum lot risk ₹{min_lot_risk:.2f} "
                    f"exceeds authorized max loss per trade ₹{max_loss_per_trade_inr:.2f}."
                )

        return ContractValidationResult(
            is_valid=(len(reasons) == 0),
            reasons=reasons,
            contract=contract,
            min_lot_risk_inr=min_lot_risk,
            is_exit_order=is_exit,
            validation_timestamp=time_str,
        )


TICK_SIZE: float = 0.05
STANDARD_LOT_SIZES = LiveContractValidator.STANDARD_LOT_SIZES
get_standard_lot_size = LiveContractValidator.get_standard_lot_size


def is_valid_tick_size(price: float, tick: float = 0.05) -> bool:
    """Verifies that price is a strictly positive multiple of the exchange tick size (0.05)."""
    if price < tick:
        return False
    return abs(price - round(price / tick) * tick) < 1e-4

