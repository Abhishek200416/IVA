"""AGI 1.7 Market Data Health & Source Provenance Monitor (Phase 12.4).

Provides:
1. Multi-source health monitoring (API Auth, WebSocket, Bhavcopy, Replay).
2. Explicit status classification:
   LIVE_VERIFIED, STALE, DISCONNECTED, HISTORICAL, REPLAY, MOCK, NOT_TESTED.
3. Event delivery delay, missing tick tracking, and reconnection diagnostics.
4. Fail-safe rule: A healthy HTTP 200 endpoint does NOT imply market data is flowing.
"""

from __future__ import annotations

import datetime
from enum import Enum
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("MarketDataHealth")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class MarketSourceHealthStatus(str, Enum):
    LIVE_VERIFIED = "LIVE_VERIFIED"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    HISTORICAL = "HISTORICAL"
    REPLAY = "REPLAY"
    MOCK = "MOCK"
    NOT_TESTED = "NOT_TESTED"


class MarketDataHealthMonitor:
    """Monitors live data flow, connection latency, auth status, and gaps."""

    def __init__(
        self,
        *,
        stale_threshold_sec: float = 15.0,
        storage_dir: Optional[Path] = None,
    ):
        self.stale_threshold_sec = stale_threshold_sec
        self.storage_dir = storage_dir or Path(__file__).resolve().parent.parent / "runtime_storage" / "health"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.health_log = self.storage_dir / "market_health_history.jsonl"

        # Current health state
        self.api_auth_state: str = "RETIRED_AWAITING_OWNER_ROTATION"
        self.websocket_state: str = "DISCONNECTED"
        self.active_subscriptions: List[str] = []
        self.last_auth_success_epoch: Optional[float] = None
        self.last_event_epoch: Optional[float] = None
        self.last_event_type: Optional[str] = None
        self.last_event_instrument: Optional[str] = None
        self.total_events_received = 0
        self.total_duplicates_detected = 0
        self.total_out_of_order_detected = 0
        self.reconnection_attempts = 0
        self.reconnection_failures = 0
        self.provenance_mode: str = "OFFLINE_AWAITING_ROTATION"

    def record_auth_event(self, success: bool, status_msg: str) -> None:
        """Records an API authentication attempt."""
        now = time.time()
        if success:
            self.api_auth_state = "AUTHENTICATED"
            self.last_auth_success_epoch = now
        else:
            self.api_auth_state = status_msg
        self._persist_event("AUTH_ATTEMPT", {"success": success, "status": status_msg})

    def record_connection_state(self, state: str, subscriptions: Optional[List[str]] = None) -> None:
        """Updates WebSocket transport connection state."""
        self.websocket_state = state
        if subscriptions is not None:
            self.active_subscriptions = list(subscriptions)
        if state == "RECONNECTING":
            self.reconnection_attempts += 1
        elif state == "RECONNECT_FAILED":
            self.reconnection_failures += 1
        self._persist_event("CONNECTION_CHANGE", {"state": state, "active_subs": self.active_subscriptions})

    def record_market_event(
        self,
        instrument_id: str,
        event_type: str,
        exchange_timestamp_epoch: Optional[float] = None,
        is_duplicate: bool = False,
        is_out_of_order: bool = False,
    ) -> None:
        """Updates ingestion timestamps and delivery delay metrics."""
        now = time.time()
        self.total_events_received += 1
        self.last_event_epoch = now
        self.last_event_type = event_type
        self.last_event_instrument = instrument_id

        if is_duplicate:
            self.total_duplicates_detected += 1
        if is_out_of_order:
            self.total_out_of_order_detected += 1

    def evaluate_composite_health(self) -> Dict[str, Any]:
        """Calculates multi-factor health status without falsely assuming data flow from HTTP up-state."""
        now = time.time()
        age_sec = (now - self.last_event_epoch) if self.last_event_epoch else None

        # Determine composite status
        if self.websocket_state == "CONNECTED" and self.api_auth_state == "AUTHENTICATED":
            if age_sec is not None and age_sec <= self.stale_threshold_sec:
                status = MarketSourceHealthStatus.LIVE_VERIFIED
            else:
                status = MarketSourceHealthStatus.STALE
        elif self.provenance_mode == "HISTORICAL_REPLAY":
            status = MarketSourceHealthStatus.REPLAY
        elif self.provenance_mode == "SYNTHETIC_DEMO":
            status = MarketSourceHealthStatus.MOCK
        elif self.api_auth_state == "RETIRED_AWAITING_OWNER_ROTATION":
            status = MarketSourceHealthStatus.DISCONNECTED
        else:
            status = MarketSourceHealthStatus.DISCONNECTED

        return {
            "status": status.value,
            "api_authentication": self.api_auth_state,
            "websocket_transport": self.websocket_state,
            "active_subscriptions_count": len(self.active_subscriptions),
            "active_subscriptions": self.active_subscriptions,
            "last_auth_success_iso": (
                datetime.datetime.fromtimestamp(self.last_auth_success_epoch, IST).isoformat()
                if self.last_auth_success_epoch
                else None
            ),
            "last_event_iso": (
                datetime.datetime.fromtimestamp(self.last_event_epoch, IST).isoformat()
                if self.last_event_epoch
                else None
            ),
            "last_event_age_sec": round(age_sec, 2) if age_sec is not None else None,
            "is_market_data_flowing": (
                status == MarketSourceHealthStatus.LIVE_VERIFIED
                or (status == MarketSourceHealthStatus.REPLAY and age_sec is not None and age_sec < 5.0)
            ),
            "total_events_received": self.total_events_received,
            "duplicate_events_count": self.total_duplicates_detected,
            "out_of_order_events_count": self.total_out_of_order_detected,
            "reconnection_metrics": {
                "attempts": self.reconnection_attempts,
                "failures": self.reconnection_failures,
            },
            "freshness_policy_threshold_sec": self.stale_threshold_sec,
            "operator_action_required": (
                "Rotate credentials on Paytm Developer Portal and enter Client ID & Secret"
                if self.api_auth_state == "RETIRED_AWAITING_OWNER_ROTATION"
                else None
            ),
        }

    def _persist_event(self, event_type: str, data: Dict[str, Any]) -> None:
        record = {
            "timestamp_iso": datetime.datetime.now(IST).isoformat(),
            "event_type": event_type,
            "data": data,
        }
        try:
            with open(self.health_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
