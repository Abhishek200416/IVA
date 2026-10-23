"""AGI 1.7 Stream Parser for Long-Running Processes.

Parses structured progress markers, JSON/JSONL events, error signatures,
and completion events from subprocess stdout/stderr streams in real time.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


PROGRESS_PERCENT_RE = re.compile(r"(?:progress|completed|downloading)?\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%", re.IGNORECASE)
PROGRESS_FRACTION_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
ERROR_SIGNATURE_RE = re.compile(
    r"(Traceback \(most recent call last\)|FATAL:|ERROR:|OutOfMemoryError|MemoryError|TimeoutExpired|ConnectionResetError|PermissionError)",
    re.IGNORECASE,
)


@dataclass
class ParsedStreamEvent:
    timestamp: float
    stream: str  # "stdout" | "stderr"
    raw_line: str
    event_type: str  # "text" | "json" | "progress" | "error" | "metric"
    progress_percent: Optional[float] = None
    completed_units: Optional[int] = None
    total_units: Optional[int] = None
    parsed_json: Optional[Dict[str, Any]] = None
    error_signature: Optional[str] = None
    usage_metadata: Optional[Dict[str, Any]] = None


class StreamParser:
    """Real-time line parser for subprocess stdout and stderr."""

    def __init__(self) -> None:
        self.events: List[ParsedStreamEvent] = []
        self.latest_progress_percent: Optional[float] = None
        self.detected_errors: List[str] = []
        self.extracted_usage: Dict[str, Any] = {}
        self.line_count: int = 0

    def parse_line(self, line: str, stream: str = "stdout") -> ParsedStreamEvent:
        now = time.time()
        self.line_count += 1
        stripped = line.strip()

        event_type = "text"
        progress_pct: Optional[float] = None
        comp_units: Optional[int] = None
        tot_units: Optional[int] = None
        parsed_obj: Optional[Dict[str, Any]] = None
        err_sig: Optional[str] = None
        usage_meta: Optional[Dict[str, Any]] = None

        # 1. Check JSON / stream-json line
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                candidate = json.loads(stripped)
                if isinstance(candidate, dict):
                    parsed_obj = candidate
                    event_type = "json"
                    if "usage" in candidate and isinstance(candidate["usage"], dict):
                        usage_meta = candidate["usage"]
                        self.extracted_usage.update(usage_meta)
                    elif "input_tokens" in candidate or "output_tokens" in candidate:
                        usage_meta = {
                            k: candidate[k]
                            for k in ("input_tokens", "output_tokens", "total_tokens", "thinking_tokens")
                            if k in candidate
                        }
                        self.extracted_usage.update(usage_meta)
                    if "progress" in candidate and isinstance(candidate["progress"], (int, float)):
                        progress_pct = max(0.0, min(100.0, float(candidate["progress"])))
                        self.latest_progress_percent = progress_pct
                        event_type = "progress"
            except Exception:
                pass

        # 2. Check percentage / fraction progress
        if progress_pct is None:
            m_pct = PROGRESS_PERCENT_RE.search(stripped)
            if m_pct:
                val = float(m_pct.group(1))
                if 0.0 <= val <= 100.0:
                    progress_pct = val
                    self.latest_progress_percent = val
                    if event_type == "text":
                        event_type = "progress"

            m_frac = PROGRESS_FRACTION_RE.search(stripped)
            if m_frac:
                c_val = int(m_frac.group(1))
                t_val = int(m_frac.group(2))
                if 0 < t_val <= 1_000_000 and 0 <= c_val <= t_val:
                    comp_units = c_val
                    tot_units = t_val
                    if progress_pct is None:
                        progress_pct = round((c_val / t_val) * 100.0, 2)
                        self.latest_progress_percent = progress_pct
                    if event_type == "text":
                        event_type = "progress"

        # 3. Check error signatures
        m_err = ERROR_SIGNATURE_RE.search(stripped)
        if m_err:
            err_sig = m_err.group(1)
            self.detected_errors.append(stripped[:300])
            if event_type == "text":
                event_type = "error"

        evt = ParsedStreamEvent(
            timestamp=now,
            stream=stream,
            raw_line=line.rstrip("\r\n"),
            event_type=event_type,
            progress_percent=progress_pct,
            completed_units=comp_units,
            total_units=tot_units,
            parsed_json=parsed_obj,
            error_signature=err_sig,
            usage_metadata=usage_meta,
        )
        # Keep bounded tail in memory (last 500 events)
        self.events.append(evt)
        if len(self.events) > 500:
            self.events.pop(0)
        return evt
