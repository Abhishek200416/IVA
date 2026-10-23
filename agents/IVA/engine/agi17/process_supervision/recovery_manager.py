"""AGI 1.7 Process Recovery Manager.

Provides bounded retry logic, exponential backoff with jitter, and failure
classification (transient timeout, OOM/memory pressure, permanent command error)
for supervised child processes.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import List, Optional

from .completion_notifier import CompletionNotification


@dataclass
class RecoveryDecision:
    should_retry: bool
    reason: str
    backoff_seconds: float
    reduce_concurrency_recommended: bool = False
    switch_to_fallback_mode: bool = False


class RecoveryManager:
    """Determines recovery actions for failed or timed-out subprocesses."""

    NON_RETRYABLE_EXIT_CODES = {2, 126, 127}  # Syntax error, permission denied / not executable, command not found

    def __init__(
        self,
        max_retries: int = 2,
        base_backoff_sec: float = 1.0,
        max_backoff_sec: float = 15.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec
        self.max_backoff_sec = max_backoff_sec

    def evaluate(
        self,
        notification: CompletionNotification,
        current_attempt: int,
        max_retries_override: Optional[int] = None,
    ) -> RecoveryDecision:
        limit = self.max_retries if max_retries_override is None else max_retries_override

        if notification.final_status == "SUCCEEDED":
            return RecoveryDecision(
                should_retry=False,
                reason="Process succeeded and artifacts verified",
                backoff_seconds=0.0,
            )

        if notification.canceled:
            return RecoveryDecision(
                should_retry=False,
                reason="Process was explicitly canceled",
                backoff_seconds=0.0,
            )

        if current_attempt > limit:
            return RecoveryDecision(
                should_retry=False,
                reason=f"Retry budget exhausted (attempt {current_attempt} > max_retries {limit})",
                backoff_seconds=0.0,
                switch_to_fallback_mode=True,
            )

        if notification.exit_code in self.NON_RETRYABLE_EXIT_CODES:
            return RecoveryDecision(
                should_retry=False,
                reason=f"Non-retryable exit code {notification.exit_code}",
                backoff_seconds=0.0,
            )

        combined_stderr = "\n".join(notification.stderr_tail).lower()
        memory_pressure = any(
            sig in combined_stderr
            for sig in ("memoryerror", "outofmemory", "paging file is too small", "oserror: [winerror 1455]")
        )

        raw_backoff = min(self.max_backoff_sec, self.base_backoff_sec * (2 ** max(0, current_attempt - 1)))
        jitter = random.uniform(0.0, 0.25 * raw_backoff)
        backoff = round(raw_backoff + jitter, 3)

        if notification.timed_out or notification.idle_timed_out:
            return RecoveryDecision(
                should_retry=True,
                reason="Process timed out; retrying with backoff and reduced concurrency recommendation",
                backoff_seconds=backoff,
                reduce_concurrency_recommended=True,
            )

        if memory_pressure:
            return RecoveryDecision(
                should_retry=True,
                reason="Memory pressure detected; retrying after backoff with reduced concurrency",
                backoff_seconds=backoff,
                reduce_concurrency_recommended=True,
            )

        return RecoveryDecision(
            should_retry=True,
            reason=f"Process failed (exit_code={notification.exit_code}); retrying attempt {current_attempt + 1}",
            backoff_seconds=backoff,
            reduce_concurrency_recommended=False,
        )
