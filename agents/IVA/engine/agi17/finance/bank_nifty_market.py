"""AGI 1.7 BANK NIFTY Market Specifications & IST Session Calendar.

Provides authoritative exchange metadata, trading session timers,
holiday calendars, and candle/quote validation for NSE BANK NIFTY.
Strictly read-only and simulation-facing. ZERO live execution keys permitted.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


@dataclass(frozen=True)
class BankNiftyContractSpec:
    LOT_SIZE: int = 15
    TICK_SIZE: float = 0.05
    STRIKE_INTERVAL: int = 100
    STRIKE_STEP: float = 100.0

    symbol: str = "BANKNIFTY"
    exchange: str = "NSE"
    segment: str = "NFO"
    lot_size: int = 15  # Current standard lot size
    tick_size: float = 0.05
    strike_interval: int = 100
    expiry_weekday: int = 2  # Wednesday (0=Mon, 2=Wed)
    market_open_time: datetime.time = datetime.time(9, 15)
    market_close_time: datetime.time = datetime.time(15, 30)
    intraday_squareoff_time: datetime.time = datetime.time(15, 15)

    @staticmethod
    def get_atm_strike(spot: float) -> float:
        return round(round(spot / 100.0) * 100.0)

    @staticmethod
    def round_to_tick(price: float) -> float:
        return round(round(price / 0.05) * 0.05, 2)

    @classmethod
    def get_lot_size(
        cls,
        as_of_date: Optional[datetime.date] = None,
        expiry_date: Optional[datetime.date] = None,
    ) -> int:
        from .live_contract_validator import get_standard_lot_size
        return get_standard_lot_size("BANKNIFTY", as_of_date, expiry_date)

    @classmethod
    def generate_contract_symbol(
        cls,
        spot_strike: float,
        option_type: Any,
        expiry: datetime.date,
    ) -> str:
        year_str = expiry.strftime("%y")
        month_str = expiry.strftime("%b").upper()
        strike_int = int(spot_strike)
        opt_str = getattr(option_type, "value", str(option_type))
        return f"BANKNIFTY{year_str}{month_str}{strike_int}{opt_str}"


# Standard NSE calendar holidays (representative reference list)
NSE_HOLIDAYS_2026: set[datetime.date] = {
    datetime.date(2026, 1, 26),   # Republic Day
    datetime.date(2026, 3, 17),   # Id-ul-Fitr / Mahashivratri approx
    datetime.date(2026, 4, 3),    # Good Friday
    datetime.date(2026, 4, 14),   # Dr. B.R. Ambedkar Jayanti
    datetime.date(2026, 5, 1),    # Maharashtra Day
    datetime.date(2026, 8, 15),   # Independence Day
    datetime.date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    datetime.date(2026, 10, 20),  # Dussehra approx
    datetime.date(2026, 11, 8),   # Diwali Laxmi Pujan
    datetime.date(2026, 12, 25),  # Christmas
}


class BankNiftyMarketCalendar:
    """Manages Indian Standard Time (IST) exchange sessions and contract validations."""

    def __init__(self, spec: Optional[BankNiftyContractSpec] = None) -> None:
        self.spec = spec or BankNiftyContractSpec()

    @staticmethod
    def now_ist() -> datetime.datetime:
        return datetime.datetime.now(IST)

    def is_trading_day(self, date_ist: datetime.date) -> bool:
        if date_ist.weekday() >= 5:  # Saturday or Sunday
            return False
        if date_ist in NSE_HOLIDAYS_2026:
            return False
        return True

    def is_market_open(self, dt_ist: Optional[datetime.datetime] = None) -> bool:
        dt = dt_ist or self.now_ist()
        if not self.is_trading_day(dt.date()):
            return False
        t = dt.time()
        return self.spec.market_open_time <= t <= self.spec.market_close_time

    def is_entry_allowed(self, dt_ist: Optional[datetime.datetime] = None) -> bool:
        """New intraday paper entries halted after 15:15 IST."""
        dt = dt_ist or self.now_ist()
        if not self.is_trading_day(dt.date()):
            return False
        t = dt.time()
        return self.spec.market_open_time <= t <= self.spec.intraday_squareoff_time

    def get_nearest_expiry(self, ref_date: Optional[datetime.date] = None) -> datetime.date:
        ref = ref_date or self.now_ist().date()
        days_ahead = (self.spec.expiry_weekday - ref.weekday()) % 7
        if days_ahead == 0 and not self.is_market_open():
            days_ahead = 7
        expiry = ref + datetime.timedelta(days=days_ahead)
        while not self.is_trading_day(expiry):
            expiry -= datetime.timedelta(days=1)
        return expiry

    def get_expiry_chain(self, ref_date: Optional[datetime.date] = None, count: int = 4) -> List[datetime.date]:
        """Returns the next `count` consecutive valid weekly expiry dates."""
        expiries: List[datetime.date] = []
        cur = self.get_nearest_expiry(ref_date)
        while len(expiries) < count:
            if cur not in expiries:
                expiries.append(cur)
            next_base = cur + datetime.timedelta(days=(7 - (cur.weekday() - self.spec.expiry_weekday) % 7))
            if next_base <= cur:
                next_base += datetime.timedelta(days=7)
            while not self.is_trading_day(next_base):
                next_base -= datetime.timedelta(days=1)
            cur = next_base
        return expiries

    def calculate_dte(self, expiry_date: datetime.date, current_date: Optional[datetime.date] = None) -> float:
        """Returns Days To Expiry (DTE) in days."""
        ref = current_date or self.now_ist().date()
        delta_days = (expiry_date - ref).days
        return max(0.0, float(delta_days))

    def should_roll_contract(
        self,
        current_expiry: datetime.date,
        current_date: Optional[datetime.date] = None,
        min_dte: float = 0.5,
    ) -> bool:
        """Determines if an options contract should be rolled forward to the next expiry."""
        dte = self.calculate_dte(current_expiry, current_date)
        return dte <= min_dte

    def get_monthly_expiry(self, year: int, month: int) -> datetime.date:
        """Calculates the exact NSE Bank Nifty monthly expiry date.

        Per SEBI & NSE circulars:
        - Post-September 1, 2025: Last Tuesday of the month.
        - March 1, 2024 - August 31, 2025: Last Wednesday of the month.
        - Prior to March 1, 2024: Last Thursday of the month.
        Shifts to prior trading day if falling on exchange holiday.
        """
        if month == 12:
            last_day = datetime.date(year, 12, 31)
        else:
            last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

        if last_day >= datetime.date(2025, 9, 1):
            target_weekday = 1  # Tuesday
        elif last_day >= datetime.date(2024, 3, 1):
            target_weekday = 2  # Wednesday
        else:
            target_weekday = 3  # Thursday

        offset = (last_day.weekday() - target_weekday) % 7
        expiry = last_day - datetime.timedelta(days=offset)

        while not self.is_trading_day(expiry):
            expiry -= datetime.timedelta(days=1)
        return expiry

    def get_monthly_expiry_chain(
        self,
        ref_date: Optional[datetime.date] = None,
        count: int = 3,
    ) -> List[datetime.date]:
        """Returns the next `count` consecutive monthly expiry dates."""
        ref = ref_date or self.now_ist().date()
        year = ref.year
        month = ref.month
        chain: List[datetime.date] = []

        while len(chain) < count:
            exp = self.get_monthly_expiry(year, month)
            if exp >= ref:
                chain.append(exp)
            # Advance to next calendar month
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
        return chain

    def validate_quote(self, quote: Dict[str, Any]) -> Tuple[bool, str]:
        required = ["symbol", "bid", "ask", "last_price", "timestamp"]
        for field in required:
            if field not in quote:
                return False, f"Missing required quote field: '{field}'"
        bid = float(quote["bid"])
        ask = float(quote["ask"])
        last_price = float(quote["last_price"])
        if bid < 0 or ask < 0 or last_price < 0:
            return False, "Negative prices detected in quote"
        if bid > ask and ask > 0:
            return False, f"Impossible spread: bid ({bid}) > ask ({ask})"
        return True, "VALID_QUOTE"

    def validate_candle(self, candle: Dict[str, Any]) -> Tuple[bool, str]:
        required = ["timestamp", "open", "high", "low", "close", "volume"]
        for field in required:
            if field not in candle:
                return False, f"Missing required candle field: '{field}'"
        o, h, l, c = float(candle["open"]), float(candle["high"]), float(candle["low"]), float(candle["close"])
        if any(v <= 0 for v in (o, h, l, c)):
            return False, "Candle price components must be positive"
        if not (l <= o <= h and l <= c <= h):
            return False, f"Inconsistent OHLC: open={o}, high={h}, low={l}, close={c}"
        if float(candle["volume"]) < 0:
            return False, "Negative volume detected"
        return True, "VALID_CANDLE"
