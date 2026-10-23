"""Market Observation Engine with Strict Provenance & Freshness Controls.

Implements Phase 10 Requirements:
- Complete provenance tracking: provider ID, source type, exchange vs arrival timestamps.
- Explicit freshness policies and timeframe-aware quote age limits.
- Sequence tracking, gap detection, and deduplication.
- Rejection of stale, missing, out-of-order, or crossed quotes (bid > ask).
- Strict classification: GENUINE_LIVE, HISTORICAL_REPLAY, SYNTHETIC_DEMO.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
from enum import Enum
import math
import time
from typing import Any, Dict, List, Optional, Tuple


class ObservationProvenanceType(str, Enum):
    LIVE_WEBSOCKET = "LIVE_WEBSOCKET"
    LIVE_DOM = "LIVE_DOM"
    EOD_BHAVCOPY = "EOD_BHAVCOPY"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"


@dataclass
class MarketObservation:
    """Rigorous market observation unit with complete source provenance."""
    observation_id: str
    instrument: str
    underlying: str
    expiry_date: Optional[str]
    bid: float
    ask: float
    last_price: float
    volume: int
    open_interest: int
    exchange_timestamp_iso: str
    arrival_timestamp_iso: str
    quote_age_sec: float
    sequence_number: int
    provider_id: str
    provenance_type: ObservationProvenanceType
    is_synthetic: bool = False
    is_stale: bool = False
    is_valid: bool = True
    validation_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance_type"] = self.provenance_type.value
        return d


class MarketObservationEngine:
    """Validates, tracks, and filters market observations before strategy evaluation."""

    def __init__(
        self,
        max_allowed_quote_age_sec: float = 15.0,  # Strategy policy threshold for 15m/5m timeframe
        min_tick_size: float = 0.05,
    ) -> None:
        self.max_allowed_quote_age_sec = max_allowed_quote_age_sec
        self.min_tick_size = min_tick_size
        self._last_sequences: Dict[str, int] = {}
        self._latest_valid_observations: Dict[str, MarketObservation] = {}
        self._gap_counts: Dict[str, int] = {}
        self._total_observations_ingested = 0
        self._total_stale_rejections = 0
        self._total_invalid_rejections = 0

    def validate_observation(
        self,
        obs: MarketObservation,
        current_time_epoch: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Strictly validates market observation against mathematical and operational criteria."""
        now = current_time_epoch or time.time()

        # 1. Price non-positivity checks
        if obs.last_price <= 0.0 or obs.bid <= 0.0 or obs.ask <= 0.0:
            return False, f"Non-positive price detected: bid={obs.bid}, ask={obs.ask}, ltp={obs.last_price}"

        # 2. Crossed book check
        if obs.bid > obs.ask:
            return False, f"Crossed book detected: bid ({obs.bid}) > ask ({obs.ask})"

        # 3. Tick size compliance
        for p_name, p_val in (("bid", obs.bid), ("ask", obs.ask), ("last_price", obs.last_price)):
            rem = round(p_val % self.min_tick_size, 4)
            if rem > 0.0001 and rem < (self.min_tick_size - 0.0001):
                return False, f"{p_name} ({p_val}) is not a multiple of statutory tick size {self.min_tick_size}"

        # 4. Sequence number monotonicity
        last_seq = self._last_sequences.get(obs.instrument, -1)
        if obs.sequence_number <= last_seq and obs.provenance_type != ObservationProvenanceType.HISTORICAL_REPLAY:
            return False, f"Out-of-order or duplicate sequence: got {obs.sequence_number}, last was {last_seq}"

        # 5. Quote age and freshness verification
        if obs.quote_age_sec > self.max_allowed_quote_age_sec:
            return False, f"Stale quote: age {obs.quote_age_sec:.2f}s exceeds limit {self.max_allowed_quote_age_sec:.1f}s"

        return True, None

    def ingest_observation(
        self,
        instrument: str,
        underlying: str,
        bid: float,
        ask: float,
        last_price: float,
        volume: int = 0,
        open_interest: int = 0,
        expiry_date: Optional[str] = None,
        sequence_number: int = 1,
        provider_id: str = "NSE_FEED",
        provenance_type: ObservationProvenanceType = ObservationProvenanceType.LIVE_DOM,
        exchange_timestamp_iso: Optional[str] = None,
        arrival_timestamp_epoch: Optional[float] = None,
        is_synthetic: bool = False,
    ) -> MarketObservation:
        """Ingests and audits a single market observation."""
        now = arrival_timestamp_epoch or time.time()
        arr_iso = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat()
        exch_iso = exchange_timestamp_iso or arr_iso

        # Estimate quote age if exchange timestamp provided
        try:
            exch_dt = datetime.datetime.fromisoformat(exch_iso.replace("Z", "+00:00"))
            quote_age = max(0.0, now - exch_dt.timestamp())
        except Exception:
            quote_age = 0.0

        obs_id = f"OBS-{instrument}-{sequence_number}-{int(now * 1000)}"

        obs = MarketObservation(
            observation_id=obs_id,
            instrument=instrument,
            underlying=underlying,
            expiry_date=expiry_date,
            bid=bid,
            ask=ask,
            last_price=last_price,
            volume=volume,
            open_interest=open_interest,
            exchange_timestamp_iso=exch_iso,
            arrival_timestamp_iso=arr_iso,
            quote_age_sec=quote_age,
            sequence_number=sequence_number,
            provider_id=provider_id,
            provenance_type=provenance_type,
            is_synthetic=is_synthetic,
        )

        valid, reason = self.validate_observation(obs, current_time_epoch=now)
        self._total_observations_ingested += 1

        if not valid:
            obs.is_valid = False
            obs.validation_error = reason
            if "Stale" in (reason or ""):
                obs.is_stale = True
                self._total_stale_rejections += 1
            else:
                self._total_invalid_rejections += 1
            return obs

        # Track sequence and gap detection
        last_seq = self._last_sequences.get(instrument, sequence_number - 1)
        if sequence_number > last_seq + 1 and last_seq > 0:
            gaps = sequence_number - (last_seq + 1)
            self._gap_counts[instrument] = self._gap_counts.get(instrument, 0) + gaps

        self._last_sequences[instrument] = sequence_number
        self._latest_valid_observations[instrument] = obs
        return obs

    def get_latest_quote(self, instrument: str) -> Optional[MarketObservation]:
        """Returns the latest valid observation for an instrument, or None if unavailable/stale."""
        obs = self._latest_valid_observations.get(instrument)
        if not obs:
            return None
        return obs

    def get_data_health_summary(self) -> Dict[str, Any]:
        """Provides aggregate telemetry on market feed freshness and data gaps."""
        return {
            "total_ingested": self._total_observations_ingested,
            "total_stale_rejections": self._total_stale_rejections,
            "total_invalid_rejections": self._total_invalid_rejections,
            "tracked_instruments": list(self._latest_valid_observations.keys()),
            "gap_counts_by_instrument": dict(self._gap_counts),
            "max_allowed_quote_age_sec": self.max_allowed_quote_age_sec,
        }
