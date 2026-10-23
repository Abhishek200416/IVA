"""AGI 1.7 Canonical Market Data Model & Validation Pipeline (Phase 12.4).

Provides:
1. CanonicalMarketObservation: Single unified schema for all market events (Quotes, Trades, OHLC, Depth, Option Chain).
2. Timezone-aware timestamping (Asia/Kolkata / IST) with explicit Indian exchange session phase tracking.
3. Strict validation rules:
   - Price non-positivity, tick size compliance (0.05 multiple).
   - Crossed book detection (bid > ask).
   - Sequence number monotonicity & duplicate event suppression.
   - Source-aware staleness thresholds.
   - Option strike and expiry consistency.
4. Quarantine and rejection logging with preserved original payloads and diagnostic reasons.
5. Consistent snapshot cache for UI and strategy engines.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("CanonicalMarketData")

from .instrument_metadata_catalog import (
    InstrumentMetadataCatalog,
    InstrumentMetadata,
    MarketSegment as CatalogMarketSegment,
)

# Indian Standard Time (IST) timezone
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"  # NSE Futures & Options
    BFO = "BFO"  # BSE Futures & Options
    MCX = "MCX"


class OptionType(str, Enum):
    CE = "CE"  # Call European
    PE = "PE"  # Put European
    FUT = "FUT"
    EQUITY = "EQUITY"


class ObservationType(str, Enum):
    QUOTE = "QUOTE"
    TRADE = "TRADE"
    OHLC_CANDLE = "OHLC_CANDLE"
    OPTION_CHAIN = "OPTION_CHAIN"
    MARKET_DEPTH = "MARKET_DEPTH"


class DataProvenance(str, Enum):
    LIVE_VERIFIED = "LIVE_VERIFIED"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    TEST_MOCK = "TEST_MOCK"


class ConnectionState(str, Enum):
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    DISCONNECTED = "DISCONNECTED"
    OFFLINE = "OFFLINE"


class MarketSessionPhase(str, Enum):
    PRE_OPEN = "PRE_OPEN"          # 09:00 - 09:08 IST
    NORMAL_TRADING = "NORMAL_TRADING"  # 09:15 - 15:30 (Cash) / 15:40 (Derivatives)
    ENTRY_CUTOFF = "ENTRY_CUTOFF"  # 15:15 IST (No new entries)
    CLOSING = "CLOSING"            # 15:30 - 15:40 IST (Closing auction)
    POST_CLOSE = "POST_CLOSE"      # 15:40 - 16:00 IST
    CLOSED = "CLOSED"              # All other times and exchange holidays


class ValidationOutcome(str, Enum):
    VALID = "VALID"
    QUARANTINED = "QUARANTINED"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_CROSSED = "REJECTED_CROSSED"
    REJECTED_OUT_OF_ORDER = "REJECTED_OUT_OF_ORDER"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_MALFORMED = "REJECTED_MALFORMED"
    REJECTED_WRONG_INSTRUMENT = "REJECTED_WRONG_INSTRUMENT"
    REJECTED_MISSING_METADATA = "REJECTED_MISSING_METADATA"
    REJECTED_SESSION_CLOSED = "REJECTED_SESSION_CLOSED"


class CanonicalMarketObservation:
    """Rigorous canonical market observation unit with complete source provenance."""

    def __init__(
        self,
        *,
        instrument_id: str,
        exchange: Exchange,
        underlying: str,
        observation_type: ObservationType,
        source_id: str,
        price: float,
        quantity: int = 1,
        price_unit: str = "INR",
        qty_unit: str = "SHARES",
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        bid_qty: Optional[int] = None,
        ask_qty: Optional[int] = None,
        strike: Optional[float] = None,
        option_type: OptionType = OptionType.EQUITY,
        expiry_date: Optional[str] = None,
        lot_size: int = 1,
        sequence_number: Optional[int] = None,
        exchange_timestamp: Optional[datetime.datetime] = None,
        receipt_timestamp: Optional[datetime.datetime] = None,
        provenance: DataProvenance = DataProvenance.LIVE_VERIFIED,
        connection_state: ConnectionState = ConnectionState.CONNECTED,
        validation_outcome: ValidationOutcome = ValidationOutcome.VALID,
        rejection_reason: Optional[str] = None,
        diagnostic_metadata: Optional[Dict[str, Any]] = None,
    ):
        now_ist = datetime.datetime.now(IST)
        self.instrument_id = instrument_id
        self.exchange = exchange
        self.underlying = underlying
        self.observation_type = observation_type
        self.source_id = source_id
        self.price = float(price)
        self.quantity = int(quantity)
        self.price_unit = price_unit
        self.qty_unit = qty_unit
        self.bid = float(bid) if bid is not None else None
        self.ask = float(ask) if ask is not None else None
        self.bid_qty = int(bid_qty) if bid_qty is not None else None
        self.ask_qty = int(ask_qty) if ask_qty is not None else None
        self.strike = float(strike) if strike is not None else None
        self.option_type = option_type
        self.expiry_date = expiry_date
        self.lot_size = lot_size
        self.sequence_number = sequence_number
        self.exchange_timestamp = exchange_timestamp or now_ist
        self.receipt_timestamp = receipt_timestamp or now_ist
        self.provenance = provenance
        self.connection_state = connection_state
        self.validation_outcome = validation_outcome
        self.rejection_reason = rejection_reason
        self.diagnostic_metadata = diagnostic_metadata or {}

        # Quote age calculation
        if self.exchange_timestamp and self.receipt_timestamp:
            delta = (self.receipt_timestamp - self.exchange_timestamp).total_seconds()
            self.quote_age_sec = max(0.0, delta)
        else:
            self.quote_age_sec = 0.0

        # Unique observation fingerprint
        raw_key = f"{self.instrument_id}:{self.sequence_number}:{self.exchange_timestamp.isoformat()}:{self.price}"
        self.observation_id = f"OBS-{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:16]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "instrument_id": self.instrument_id,
            "exchange": self.exchange.value,
            "underlying": self.underlying,
            "observation_type": self.observation_type.value,
            "source_id": self.source_id,
            "price": self.price,
            "quantity": self.quantity,
            "price_unit": self.price_unit,
            "qty_unit": self.qty_unit,
            "bid": self.bid,
            "ask": self.ask,
            "bid_qty": self.bid_qty,
            "ask_qty": self.ask_qty,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "expiry_date": self.expiry_date,
            "lot_size": self.lot_size,
            "sequence_number": self.sequence_number,
            "exchange_timestamp_iso": self.exchange_timestamp.isoformat(),
            "receipt_timestamp_iso": self.receipt_timestamp.isoformat(),
            "quote_age_sec": round(self.quote_age_sec, 3),
            "provenance": self.provenance.value,
            "connection_state": self.connection_state.value,
            "validation_outcome": self.validation_outcome.value,
            "rejection_reason": self.rejection_reason,
            "diagnostic_metadata": self.diagnostic_metadata,
        }


class CanonicalMarketDataPipeline:
    """Audits, normalizes, deduplicates, and caches market observations."""

    def __init__(
        self,
        *,
        max_quote_age_sec: float = 15.0,
        max_candle_age_sec: float = 300.0,
        min_tick_size: float = 0.05,
        storage_dir: Optional[Path] = None,
        metadata_catalog: Optional[InstrumentMetadataCatalog] = None,
    ):
        self.max_quote_age_sec = max_quote_age_sec
        self.max_candle_age_sec = max_candle_age_sec
        self.min_tick_size = min_tick_size
        self.metadata_catalog = metadata_catalog or InstrumentMetadataCatalog()
        self.storage_dir = storage_dir or Path(__file__).resolve().parent.parent / "runtime_storage" / "market_data"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_file = self.storage_dir / "quarantined_observations.jsonl"

        # Tracking state
        self._last_sequences: Dict[str, int] = {}
        self._seen_event_hashes: set[str] = set()
        self._latest_valid_snapshots: Dict[str, CanonicalMarketObservation] = {}
        self._quarantined_records: List[Dict[str, Any]] = []

        # Metrics
        self.total_ingested = 0
        self.total_valid = 0
        self.total_rejected = 0

    @classmethod
    def get_market_session_phase(
        cls, dt: datetime.datetime, segment: str = "DERIVATIVES"
    ) -> MarketSessionPhase:
        """Determines the active Indian exchange market session phase for a given timestamp and segment."""
        dt_ist = dt.astimezone(IST)
        # Check weekend
        if dt_ist.weekday() >= 5:
            return MarketSessionPhase.CLOSED

        t = dt_ist.time()
        if segment.upper() in ("EQUITY", "CASH", "EQUITY_CASH"):
            # Cash market: 09:00 - 09:15 pre-open, 09:15 - 15:30 normal trading, 15:30 - 15:40 closing auction
            if datetime.time(9, 0) <= t < datetime.time(9, 8):
                return MarketSessionPhase.PRE_OPEN
            elif datetime.time(9, 15) <= t < datetime.time(15, 15):
                return MarketSessionPhase.NORMAL_TRADING
            elif datetime.time(15, 15) <= t <= datetime.time(15, 30):
                return MarketSessionPhase.ENTRY_CUTOFF
            elif datetime.time(15, 30) < t <= datetime.time(15, 40):
                return MarketSessionPhase.CLOSING
            elif datetime.time(15, 40) < t <= datetime.time(16, 0):
                return MarketSessionPhase.POST_CLOSE
            else:
                return MarketSessionPhase.CLOSED
        else:
            # Equity Derivatives (F&O): 09:15 to 15:40 normal trading (Official NSE Derivatives schedule)
            if datetime.time(9, 15) <= t < datetime.time(15, 15):
                return MarketSessionPhase.NORMAL_TRADING
            elif datetime.time(15, 15) <= t <= datetime.time(15, 40):
                return MarketSessionPhase.ENTRY_CUTOFF
            elif datetime.time(15, 40) < t <= datetime.time(16, 0):
                return MarketSessionPhase.POST_CLOSE
            else:
                return MarketSessionPhase.CLOSED

    def validate_observation(
        self, obs: CanonicalMarketObservation
    ) -> Tuple[ValidationOutcome, Optional[str]]:
        """Strictly audits a market observation against mathematical and operational criteria."""
        # 1. Non-positive price
        if obs.price <= 0.0:
            return ValidationOutcome.REJECTED_MALFORMED, f"Non-positive price: {obs.price}"

        # 2. Crossed book
        if obs.bid is not None and obs.ask is not None:
            if obs.bid <= 0.0 or obs.ask <= 0.0:
                return ValidationOutcome.REJECTED_MALFORMED, f"Non-positive quote: bid={obs.bid}, ask={obs.ask}"
            if obs.bid > obs.ask:
                return ValidationOutcome.REJECTED_CROSSED, f"Crossed book: bid ({obs.bid}) > ask ({obs.ask})"

        # 3. Instrument Metadata & Tick size compliance
        meta = self.metadata_catalog.get_metadata(obs.instrument_id)
        expected_tick = meta.resolve_effective_tick_size(obs.price) if meta else self.min_tick_size
        for p_name, p_val in (("price", obs.price), ("bid", obs.bid), ("ask", obs.ask)):
            if p_val is not None:
                rem = round(p_val % expected_tick, 4)
                if 0.0001 < rem < (expected_tick - 0.0001):
                    return (
                        ValidationOutcome.REJECTED_MALFORMED,
                        f"{p_name} ({p_val}) not a multiple of verified tick size {expected_tick}",
                    )

        # 4. Derivative contract metadata consistency
        if obs.option_type in (OptionType.CE, OptionType.PE):
            if obs.strike is None or obs.strike <= 0.0:
                return ValidationOutcome.REJECTED_WRONG_INSTRUMENT, f"Missing or invalid strike for option: {obs.strike}"
            if not obs.expiry_date:
                return ValidationOutcome.REJECTED_WRONG_INSTRUMENT, "Missing expiry date for option derivative"

        # 5. Duplicate event detection
        event_hash = f"{obs.instrument_id}:{obs.sequence_number}:{obs.exchange_timestamp.isoformat()}"
        if event_hash in self._seen_event_hashes and obs.provenance != DataProvenance.HISTORICAL_REPLAY:
            return ValidationOutcome.REJECTED_DUPLICATE, f"Duplicate event hash detected: {event_hash}"

        # 6. Sequence number monotonicity
        if obs.sequence_number is not None and obs.provenance != DataProvenance.HISTORICAL_REPLAY:
            last_seq = self._last_sequences.get(obs.instrument_id, -1)
            if obs.sequence_number <= last_seq:
                return (
                    ValidationOutcome.REJECTED_OUT_OF_ORDER,
                    f"Out of order sequence: got {obs.sequence_number}, last was {last_seq}",
                )

        # 7. Staleness check
        staleness_limit = (
            self.max_candle_age_sec
            if obs.observation_type == ObservationType.OHLC_CANDLE
            else self.max_quote_age_sec
        )
        if obs.quote_age_sec > staleness_limit and obs.provenance == DataProvenance.LIVE_VERIFIED:
            return (
                ValidationOutcome.REJECTED_STALE,
                f"Stale observation: age {obs.quote_age_sec:.2f}s exceeds limit {staleness_limit:.1f}s",
            )

        return ValidationOutcome.VALID, None

    def ingest(self, obs: CanonicalMarketObservation) -> CanonicalMarketObservation:
        """Ingests and routes an observation through validation, caching, and quarantine."""
        self.total_ingested += 1
        outcome, reason = self.validate_observation(obs)
        obs.validation_outcome = outcome
        obs.rejection_reason = reason

        if outcome == ValidationOutcome.VALID:
            self.total_valid += 1
            if obs.sequence_number is not None:
                self._last_sequences[obs.instrument_id] = obs.sequence_number
            event_hash = f"{obs.instrument_id}:{obs.sequence_number}:{obs.exchange_timestamp.isoformat()}"
            self._seen_event_hashes.add(event_hash)
            self._latest_valid_snapshots[obs.instrument_id] = obs
        else:
            self.total_rejected += 1
            self._quarantine(obs)

        return obs

    def _quarantine(self, obs: CanonicalMarketObservation) -> None:
        """Persists rejected/quarantined observations with full diagnostics."""
        record = obs.to_dict()
        record["quarantined_at_iso"] = datetime.datetime.now(IST).isoformat()
        self._quarantined_records.append(record)
        try:
            with open(self.quarantine_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.warning(f"Failed to append to quarantine file: {exc}")

    def get_latest_snapshot(self, instrument_id: str) -> Optional[CanonicalMarketObservation]:
        """Returns the single validated canonical snapshot for a given instrument."""
        return self._latest_valid_snapshots.get(instrument_id)

    def get_all_snapshots(self) -> Dict[str, Dict[str, Any]]:
        return {k: v.to_dict() for k, v in self._latest_valid_snapshots.items()}

    def get_quarantine_stats(self) -> Dict[str, Any]:
        return {
            "total_ingested": self.total_ingested,
            "total_valid": self.total_valid,
            "total_rejected": self.total_rejected,
            "rejection_rate_pct": (
                round((self.total_rejected / max(1, self.total_ingested)) * 100.0, 2)
            ),
            "recent_quarantined_count": len(self._quarantined_records),
        }
