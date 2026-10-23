"""AGI 1.7 OMEGA COMMAND — End-to-End Structured Observability & Distributed Tracing.

Implements Phase 12.3 Correlation & Observability Architecture:
- Trace ID and Request ID propagation across supervisor, agents, models, tools, and paper execution.
- OpenTelemetry-aligned structured event taxonomy.
- Automatic secret and credential redaction prior to serialization.
- Local high-performance append-only JSONL event ledger (`events.jsonl`).
- Timeline reconstruction and query interface for operator inspection.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters.model_adapter import redact_sensitive_text

logger = logging.getLogger("OmegaTracer")


@dataclass
class TraceContext:
    """Immutable trace propagation context carrying request correlation anchors."""
    trace_id: str
    request_id: str
    span_id: str
    parent_span_id: Optional[str] = None

    def child_span(self) -> TraceContext:
        """Derives a downstream child span context linked to this span."""
        return TraceContext(
            trace_id=self.trace_id,
            request_id=self.request_id,
            span_id=uuid.uuid4().hex[:12],
            parent_span_id=self.span_id,
        )


@dataclass
class OmegaStructuredEvent:
    """Rigorous structured telemetry event matching OpenTelemetry semantic conventions."""
    event_id: str
    trace_id: str
    request_id: str
    span_id: str
    parent_span_id: Optional[str]
    timestamp: float
    timestamp_iso: str
    event_type: str
    actor: str
    model_id: Optional[str] = None
    latency_ms: Optional[float] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    error_type: Optional[str] = None


class OmegaTracer:
    """Singleton-capable structured tracer producing correlated, redacted event ledgers."""

    _instance: Optional[OmegaTracer] = None
    _lock = threading.Lock()

    def __init__(self, trace_dir: Optional[Path] = None) -> None:
        if trace_dir:
            self.trace_dir = Path(trace_dir)
        else:
            self.trace_dir = (
                Path(__file__).resolve().parents[3]
                / "runtime_storage"
                / "traces"
            )
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.trace_dir / "events.jsonl"
        self._write_lock = threading.Lock()

    @classmethod
    def get_instance(cls, trace_dir: Optional[Path] = None) -> OmegaTracer:
        with cls._lock:
            if cls._instance is None:
                cls._instance = OmegaTracer(trace_dir=trace_dir)
            return cls._instance

    def start_trace(self, request_id: Optional[str] = None) -> TraceContext:
        """Initializes a root trace context for an incoming request or mission."""
        req_id = request_id or f"REQ-{uuid.uuid4().hex[:8]}"
        trace_id = f"TRC-{uuid.uuid4().hex[:12]}"
        span_id = uuid.uuid4().hex[:12]
        return TraceContext(
            trace_id=trace_id,
            request_id=req_id,
            span_id=span_id,
            parent_span_id=None,
        )

    def record_event(
        self,
        ctx: TraceContext,
        event_type: str,
        actor: str,
        *,
        model_id: Optional[str] = None,
        latency_ms: Optional[float] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        cost_usd: Optional[float] = None,
        payload: Optional[Dict[str, Any]] = None,
        error_type: Optional[str] = None,
    ) -> OmegaStructuredEvent:
        """Records and persists an OpenTelemetry-aligned structured event with secret redaction."""
        now = time.time()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        event_id = f"EVT-{uuid.uuid4().hex[:10]}"

        # Deep sanitization of payload
        clean_payload: Dict[str, Any] = {}
        if payload:
            for k, v in payload.items():
                if isinstance(v, str):
                    clean_payload[k] = redact_sensitive_text(v)
                elif isinstance(v, (int, float, bool, list, dict)):
                    clean_payload[k] = v
                else:
                    clean_payload[k] = redact_sensitive_text(str(v))

        event = OmegaStructuredEvent(
            event_id=event_id,
            trace_id=ctx.trace_id,
            request_id=ctx.request_id,
            span_id=ctx.span_id,
            parent_span_id=ctx.parent_span_id,
            timestamp=now,
            timestamp_iso=now_iso,
            event_type=event_type,
            actor=actor,
            model_id=model_id,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            payload=clean_payload,
            error_type=error_type,
        )

        # Thread-safe append to JSONL ledger
        line = json.dumps(asdict(event), ensure_ascii=False) + "\n"
        with self._write_lock:
            try:
                with open(self.events_file, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                logger.error(f"Failed to append to trace event ledger: {e}")

        return event

    def get_trace_timeline(self, trace_id: str) -> List[Dict[str, Any]]:
        """Retrieves chronologically sorted events for a specific trace ID."""
        if not self.events_file.exists():
            return []

        events: List[Dict[str, Any]] = []
        with self._write_lock:
            try:
                with open(self.events_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            if d.get("trace_id") == trace_id:
                                events.append(d)
                        except Exception:
                            continue
            except Exception as e:
                logger.error(f"Failed to read trace timeline for {trace_id}: {e}")

        events.sort(key=lambda x: x.get("timestamp", 0.0))
        return events

    def list_recent_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Summarizes recent traces with event counts, duration, and error status."""
        if not self.events_file.exists():
            return []

        traces: Dict[str, Dict[str, Any]] = {}
        with self._write_lock:
            try:
                with open(self.events_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            tid = d.get("trace_id")
                            if not tid:
                                continue
                            if tid not in traces:
                                traces[tid] = {
                                    "trace_id": tid,
                                    "request_id": d.get("request_id"),
                                    "first_seen": d.get("timestamp"),
                                    "first_seen_iso": d.get("timestamp_iso"),
                                    "last_seen": d.get("timestamp"),
                                    "last_seen_iso": d.get("timestamp_iso"),
                                    "event_count": 0,
                                    "error_count": 0,
                                    "actors": set(),
                                    "event_types": set(),
                                    "has_error": False,
                                }
                            t_info = traces[tid]
                            t_info["event_count"] += 1
                            t_info["last_seen"] = d.get("timestamp")
                            t_info["last_seen_iso"] = d.get("timestamp_iso")
                            t_info["actors"].add(d.get("actor", "unknown"))
                            t_info["event_types"].add(d.get("event_type", "unknown"))
                            if d.get("error_type"):
                                t_info["error_count"] += 1
                                t_info["has_error"] = True
                        except Exception:
                            continue
            except Exception as e:
                logger.error(f"Failed to list recent traces: {e}")

        result: List[Dict[str, Any]] = []
        for tid, t_info in sorted(traces.items(), key=lambda item: item[1]["last_seen"], reverse=True)[:limit]:
            result.append({
                "trace_id": t_info["trace_id"],
                "request_id": t_info["request_id"],
                "first_seen_iso": t_info["first_seen_iso"],
                "last_seen_iso": t_info["last_seen_iso"],
                "duration_ms": round((t_info["last_seen"] - t_info["first_seen"]) * 1000, 2),
                "event_count": t_info["event_count"],
                "error_count": t_info["error_count"],
                "has_error": t_info["has_error"],
                "actors": list(t_info["actors"]),
                "event_types": list(t_info["event_types"]),
            })
        return result
