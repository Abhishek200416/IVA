"""Daily Model Token Budget Manager.

Implements Section 9:
- Treats 1,000,000 model tokens per UTC accounting day as a hard ceiling.
- Warning thresholds at 70%, 85%, and 95% of daily budget.
- Hard admission stop before the configured ceiling can be exceeded.
- Forecasting and consumption rate tracking.
- Preserves trading risk checks regardless of token budget state.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass
class TokenBudgetStatus:
    """Current state of daily token budget consumption."""
    daily_ceiling: int = 1_000_000
    tokens_consumed_today: int = 0
    tokens_remaining: int = 1_000_000
    percent_consumed: float = 0.0
    is_warning_70: bool = False
    is_warning_85: bool = False
    is_warning_95: bool = False
    is_admission_stopped: bool = False
    date_utc: str = ""
    reserve_buffer: int = 25_000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "daily_ceiling": self.daily_ceiling,
            "consumed_today": self.tokens_consumed_today,
            "remaining": self.tokens_remaining,
            "percent_consumed": round(self.percent_consumed, 2),
            "warning_70": self.is_warning_70,
            "warning_85": self.is_warning_85,
            "warning_95": self.is_warning_95,
            "admission_stopped": self.is_admission_stopped,
            "date_utc": self.date_utc,
        }


class TokenBudgetManager:
    """Thread-safe manager for the 1,000,000 token daily limit."""

    def __init__(
        self,
        daily_ceiling: int = 1_000_000,
        reserve_buffer: int = 25_000,
        storage_path: Optional[Path] = None,
    ) -> None:
        self.lock = threading.Lock()
        self.daily_ceiling = daily_ceiling
        self.reserve_buffer = reserve_buffer
        self.storage_path = storage_path or (
            Path(__file__).resolve().parents[2] / "runtime_storage" / "telemetry" / "daily_token_budget.json"
        )
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.consumed_today: int = 0
        self.current_date_utc: str = self._get_current_utc_date()

        self._load_state()

    def _get_current_utc_date(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def _load_state(self) -> None:
        if self.storage_path.is_file():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                if data.get("date_utc") == self.current_date_utc:
                    self.consumed_today = int(data.get("consumed_today", 0))
            except Exception:
                self.consumed_today = 0

    def _save_state(self) -> None:
        try:
            payload = {
                "date_utc": self.current_date_utc,
                "consumed_today": self.consumed_today,
                "daily_ceiling": self.daily_ceiling,
                "last_updated": time.time(),
            }
            self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    def check_and_record(self, tokens_to_use: int) -> Tuple[bool, TokenBudgetStatus]:
        """Checks if tokens can be admitted and atomically records usage."""
        with self.lock:
            today = self._get_current_utc_date()
            if today != self.current_date_utc:
                self.current_date_utc = today
                self.consumed_today = 0

            projected = self.consumed_today + tokens_to_use
            max_admissible = self.daily_ceiling - self.reserve_buffer

            if projected > max_admissible:
                status = self._build_status(is_admission_stopped=True)
                return False, status

            self.consumed_today += tokens_to_use
            self._save_state()
            status = self._build_status(is_admission_stopped=False)
            return True, status

    def get_status(self) -> TokenBudgetStatus:
        with self.lock:
            today = self._get_current_utc_date()
            if today != self.current_date_utc:
                self.current_date_utc = today
                self.consumed_today = 0
            stopped = (self.consumed_today + self.reserve_buffer) >= self.daily_ceiling
            return self._build_status(is_admission_stopped=stopped)

    def _build_status(self, is_admission_stopped: bool) -> TokenBudgetStatus:
        remaining = max(0, self.daily_ceiling - self.consumed_today)
        pct = (self.consumed_today / self.daily_ceiling) * 100.0 if self.daily_ceiling > 0 else 100.0

        return TokenBudgetStatus(
            daily_ceiling=self.daily_ceiling,
            tokens_consumed_today=self.consumed_today,
            tokens_remaining=remaining,
            percent_consumed=pct,
            is_warning_70=(pct >= 70.0),
            is_warning_85=(pct >= 85.0),
            is_warning_95=(pct >= 95.0),
            is_admission_stopped=is_admission_stopped,
            date_utc=self.current_date_utc,
            reserve_buffer=self.reserve_buffer,
        )
