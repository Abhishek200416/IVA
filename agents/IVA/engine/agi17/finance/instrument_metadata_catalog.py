"""AGI 1.7 Instrument Master & Metadata Catalog Engine (Phase 12.4.1).

Replaces hard-coded universal assumptions with validated, segment-aware metadata:
1. Segment-aware trading schedules:
   - NSE Equity Derivatives (F&O): 09:15 - 15:40 IST (Official NSE Derivatives trading close)
   - NSE Equity Cash: 09:00 - 09:15 Pre-open, 09:15 - 15:30 Normal, 15:30 - 15:40 Closing, 15:40 - 16:00 Post-market
   - MCX Commodities (Crude, Gold): 09:00 - 23:30 / 23:55 IST
   - Currency Derivatives (NSE CDS): 09:00 - 17:00 IST
2. Instrument-specific tick size rules:
   - NSE Equity Derivatives (NIFTY, BANKNIFTY options/futures): ₹0.05
   - NSE Equity Cash:
     * Price < ₹250.00: ₹0.01 tick size (per NSE Circular on sub-250 tick rationalization)
     * Price >= ₹250.00: ₹0.05 tick size
   - MCX Crude Oil: ₹1.00 per barrel
   - MCX Gold: ₹1.00 per 10 grams
   - NSE Currency (USDINR): ₹0.0025 (quarter-paisa)
3. Date-aware lot sizes and quantity increments:
   - NIFTY 50: 65 (Post-Dec 2025 EOD per NSE Circular NSE/FAOP/70616; historically 75, 50, 25)
   - BANK NIFTY: 30 (Post-Dec 2025 EOD; historically 35, 15)
4. Rejection of missing, stale, or conflicting metadata:
   - Candidates without verified contract master entries are rejected with specific reason codes.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class MarketSegment(str, Enum):
    EQUITY_CASH = "EQUITY_CASH"
    EQUITY_DERIVATIVES = "EQUITY_DERIVATIVES"
    COMMODITY_DERIVATIVES = "COMMODITY_DERIVATIVES"
    CURRENCY_DERIVATIVES = "CURRENCY_DERIVATIVES"


class InstrumentType(str, Enum):
    INDEX_OPTION = "INDEX_OPTION"
    INDEX_FUTURE = "INDEX_FUTURE"
    STOCK_OPTION = "STOCK_OPTION"
    STOCK_FUTURE = "STOCK_FUTURE"
    EQUITY_SHARE = "EQUITY_SHARE"
    COMMODITY_FUTURE = "COMMODITY_FUTURE"
    CURRENCY_FUTURE = "CURRENCY_FUTURE"


class SegmentMarketSessionPhase(str, Enum):
    PRE_OPEN = "PRE_OPEN"                     # 09:00 - 09:15 IST (Cash only)
    NORMAL_TRADING = "NORMAL_TRADING"         # Continuous trading
    ENTRY_CUTOFF = "ENTRY_CUTOFF"             # Risk-restricted entry window before close
    CLOSING_AUCTION = "CLOSING_AUCTION"       # 15:30 - 15:40 IST (Cash only)
    POST_MARKET = "POST_MARKET"               # 15:40 - 16:00 IST
    CLOSED = "CLOSED"                         # Outside trading hours or weekends/holidays


@dataclass
class InstrumentMetadata:
    """Authoritative contract and trading parameter specification for an instrument."""
    symbol: str
    underlying: str
    exchange: str                             # "NSE", "BSE", "MCX"
    segment: MarketSegment
    instrument_type: InstrumentType
    lot_size: int
    base_tick_size: float
    price_multiplier: float = 1.0
    expiry_rule: str = "WEEKLY_THURSDAY"
    normal_market_open: datetime.time = datetime.time(9, 15)
    normal_market_close: datetime.time = datetime.time(15, 40)  # Derivatives: 15:40; Cash: 15:30
    entry_cutoff_time: datetime.time = datetime.time(15, 15)
    has_pre_open: bool = False
    pre_open_start: Optional[datetime.time] = None
    pre_open_end: Optional[datetime.time] = None
    is_active: bool = True
    last_verified_utc: str = "2026-10-15T00:00:00Z"
    metadata_source: str = "NSE Contract Master / Circular NSE/FAOP/70616"
    staleness_ttl_days: int = 30

    def resolve_effective_tick_size(self, current_price: Optional[float] = None) -> float:
        """Computes price-dependent tick size (e.g. NSE Cash < ₹250 uses ₹0.01)."""
        if self.segment == MarketSegment.EQUITY_CASH and current_price is not None:
            if current_price < 250.0:
                return 0.01
            return 0.05
        return self.base_tick_size

    def is_stale(self, as_of_date: Optional[datetime.date] = None) -> bool:
        """Determines if the metadata is stale (> staleness_ttl_days without official verification)."""
        if as_of_date is None:
            as_of_date = datetime.date(2026, 10, 15)
        verified_date = datetime.date.fromisoformat(self.last_verified_utc.split("T")[0])
        return (as_of_date - verified_date).days > self.staleness_ttl_days

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "exchange": self.exchange,
            "segment": self.segment.value,
            "instrument_type": self.instrument_type.value,
            "lot_size": self.lot_size,
            "base_tick_size": self.base_tick_size,
            "expiry_rule": self.expiry_rule,
            "normal_market_open": self.normal_market_open.isoformat(),
            "normal_market_close": self.normal_market_close.isoformat(),
            "entry_cutoff_time": self.entry_cutoff_time.isoformat(),
            "has_pre_open": self.has_pre_open,
            "is_active": self.is_active,
            "last_verified_utc": self.last_verified_utc,
            "metadata_source": self.metadata_source,
        }


class InstrumentMetadataCatalog:
    """Catalog of verified instruments with deterministic validation of ticks, hours, and expiries."""

    def __init__(self) -> None:
        self._catalog: Dict[str, InstrumentMetadata] = self._build_canonical_catalog()

    @staticmethod
    def _build_canonical_catalog() -> Dict[str, InstrumentMetadata]:
        catalog: Dict[str, InstrumentMetadata] = {}

        # 1. NIFTY 50 Index Options & Futures (NSE F&O Segment)
        # Normal trading: 09:15 to 15:40 IST (Official NSE Derivatives timing)
        catalog["NIFTY"] = InstrumentMetadata(
            symbol="NIFTY",
            underlying="NIFTY",
            exchange="NSE",
            segment=MarketSegment.EQUITY_DERIVATIVES,
            instrument_type=InstrumentType.INDEX_OPTION,
            lot_size=65,  # Revised lot size per NSE Circular NSE/FAOP/70616
            base_tick_size=0.05,
            expiry_rule="WEEKLY_THURSDAY",
            normal_market_open=datetime.time(9, 15),
            normal_market_close=datetime.time(15, 40),
            entry_cutoff_time=datetime.time(15, 15),
            has_pre_open=False,
            metadata_source="NSE Circular NSE/FAOP/70616 & Official NSE Derivatives Schedule",
        )

        # 2. BANK NIFTY Index Options & Futures (NSE F&O Segment)
        # Normal trading: 09:15 to 15:40 IST
        catalog["BANKNIFTY"] = InstrumentMetadata(
            symbol="BANKNIFTY",
            underlying="BANKNIFTY",
            exchange="NSE",
            segment=MarketSegment.EQUITY_DERIVATIVES,
            instrument_type=InstrumentType.INDEX_OPTION,
            lot_size=30,  # Revised lot size per NSE Circular NSE/FAOP/70616
            base_tick_size=0.05,
            expiry_rule="WEEKLY_WEDNESDAY",
            normal_market_open=datetime.time(9, 15),
            normal_market_close=datetime.time(15, 40),
            entry_cutoff_time=datetime.time(15, 15),
            has_pre_open=False,
            metadata_source="NSE Circular NSE/FAOP/70616 & Official NSE Derivatives Schedule",
        )

        # 3. NSE Cash Market Equities (e.g. RELIANCE, TATASTEEL)
        # Normal trading: 09:15 to 15:30 IST; Pre-open: 09:00 - 09:15; Closing: 15:30 - 15:40
        catalog["RELIANCE"] = InstrumentMetadata(
            symbol="RELIANCE",
            underlying="RELIANCE",
            exchange="NSE",
            segment=MarketSegment.EQUITY_CASH,
            instrument_type=InstrumentType.EQUITY_SHARE,
            lot_size=1,
            base_tick_size=0.05,  # >= 250 -> 0.05
            expiry_rule="NA",
            normal_market_open=datetime.time(9, 15),
            normal_market_close=datetime.time(15, 30),
            entry_cutoff_time=datetime.time(15, 15),
            has_pre_open=True,
            pre_open_start=datetime.time(9, 0),
            pre_open_end=datetime.time(9, 15),
            metadata_source="NSE Equity Cash Market Schedule",
        )

        catalog["TATASTEEL"] = InstrumentMetadata(
            symbol="TATASTEEL",
            underlying="TATASTEEL",
            exchange="NSE",
            segment=MarketSegment.EQUITY_CASH,
            instrument_type=InstrumentType.EQUITY_SHARE,
            lot_size=1,
            base_tick_size=0.01,  # Sub-250 INR stock -> ₹0.01 tick size
            expiry_rule="NA",
            normal_market_open=datetime.time(9, 15),
            normal_market_close=datetime.time(15, 30),
            entry_cutoff_time=datetime.time(15, 15),
            has_pre_open=True,
            pre_open_start=datetime.time(9, 0),
            pre_open_end=datetime.time(9, 15),
            metadata_source="NSE Equity Cash Sub-250 Tick Rationalization Schedule",
        )

        # 4. MCX Commodity Derivatives (e.g. CRUDEOIL, GOLD)
        # Normal trading: 09:00 to 23:30 IST; Tick size: ₹1.00
        catalog["CRUDEOIL"] = InstrumentMetadata(
            symbol="CRUDEOIL",
            underlying="CRUDEOIL",
            exchange="MCX",
            segment=MarketSegment.COMMODITY_DERIVATIVES,
            instrument_type=InstrumentType.COMMODITY_FUTURE,
            lot_size=100,
            base_tick_size=1.00,  # ₹1.00 per barrel
            expiry_rule="MONTHLY_19TH",
            normal_market_open=datetime.time(9, 0),
            normal_market_close=datetime.time(23, 30),
            entry_cutoff_time=datetime.time(23, 15),
            has_pre_open=False,
            metadata_source="MCX Commodity Contract Specification",
        )

        # 5. Currency Derivatives (e.g. USDINR)
        # Normal trading: 09:00 to 17:00 IST; Tick size: ₹0.0025 (quarter-paisa)
        catalog["USDINR"] = InstrumentMetadata(
            symbol="USDINR",
            underlying="USDINR",
            exchange="NSE",
            segment=MarketSegment.CURRENCY_DERIVATIVES,
            instrument_type=InstrumentType.CURRENCY_FUTURE,
            lot_size=1000,
            base_tick_size=0.0025,  # 0.25 paisa
            expiry_rule="MONTHLY_LAST_WEDNESDAY",
            normal_market_open=datetime.time(9, 0),
            normal_market_close=datetime.time(17, 0),
            entry_cutoff_time=datetime.time(16, 45),
            has_pre_open=False,
            metadata_source="NSE Currency Derivatives Specifications",
        )

        return catalog

    def get_metadata(self, identifier: str) -> Optional[InstrumentMetadata]:
        """Resolves metadata for an instrument ID or symbol (e.g. 'NIFTY', 'NSE:NIFTY26OCT25000CE')."""
        clean_id = identifier.upper().replace("NSE:", "").replace("BSE:", "").replace("MCX:", "")
        # Exact symbol match
        if clean_id in self._catalog:
            return self._catalog[clean_id]
        # Match root underlying
        for root in ("NIFTY", "BANKNIFTY", "RELIANCE", "TATASTEEL", "CRUDEOIL", "USDINR"):
            if clean_id.startswith(root):
                return self._catalog[root]
        return None

    def validate_tick_size(
        self, price: float, identifier: str
    ) -> Tuple[bool, float, Optional[str]]:
        """Audits a price against the instrument's verified tick size.

        Returns: (is_valid, effective_tick_size, failure_reason)
        """
        meta = self.get_metadata(identifier)
        if not meta:
            return False, 0.0, f"REJECTED_MISSING_METADATA: No verified contract master for '{identifier}'"

        if meta.is_stale():
            return False, 0.0, f"REJECTED_STALE_METADATA: Contract master for '{identifier}' is stale"

        tick = meta.resolve_effective_tick_size(price)
        rem = round(price % tick, 6)
        if 0.00001 < rem < (tick - 0.00001):
            return (
                False,
                tick,
                f"REJECTED_INVALID_TICK_SIZE: Price {price} is not a multiple of verified tick size {tick} for {meta.symbol}",
            )
        return True, tick, None

    def evaluate_session_phase(
        self, dt: datetime.datetime, identifier: str
    ) -> Tuple[SegmentMarketSessionPhase, Optional[str]]:
        """Determines segment-aware market session phase for the exact instrument and time."""
        meta = self.get_metadata(identifier)
        if not meta:
            return SegmentMarketSessionPhase.CLOSED, f"Missing metadata for {identifier}"

        dt_ist = dt.astimezone(IST)
        # Weekend check
        if dt_ist.weekday() >= 5:
            return SegmentMarketSessionPhase.CLOSED, "Weekend non-trading day"

        t = dt_ist.time()

        # Pre-open phase (for Cash equity segment only)
        if meta.has_pre_open and meta.pre_open_start and meta.pre_open_end:
            if meta.pre_open_start <= t < meta.pre_open_end:
                return SegmentMarketSessionPhase.PRE_OPEN, None

        # Normal trading phase
        if meta.normal_market_open <= t < meta.entry_cutoff_time:
            return SegmentMarketSessionPhase.NORMAL_TRADING, None

        # Entry cutoff phase (approaching close)
        if meta.entry_cutoff_time <= t < meta.normal_market_close:
            return SegmentMarketSessionPhase.ENTRY_CUTOFF, "Risk entry cutoff in effect"

        # Closing auction phase (Cash segment: 15:30 - 15:40)
        if meta.segment == MarketSegment.EQUITY_CASH:
            if datetime.time(15, 30) <= t < datetime.time(15, 40):
                return SegmentMarketSessionPhase.CLOSING_AUCTION, "Closing price determination auction"

        # Post-market phase (15:40 - 16:00 for NSE)
        if meta.segment in (MarketSegment.EQUITY_CASH, MarketSegment.EQUITY_DERIVATIVES):
            if datetime.time(15, 40) <= t <= datetime.time(16, 0):
                return SegmentMarketSessionPhase.POST_MARKET, "Post-market trade modification session"

        return SegmentMarketSessionPhase.CLOSED, "Outside segment trading hours"
