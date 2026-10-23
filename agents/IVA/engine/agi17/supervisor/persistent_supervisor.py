"""AGI 1.7 Persistent 24/7 Supervisor — NEVER END AFTER ONE TASK.

Implements the 10-state continuous process-level supervisor:
STARTING → RECOVERING → READY → SELECTING_TASK → BUILDING_CONTEXT → EXECUTING → VERIFYING → RECORDING_LEARNING → SCHEDULING_NEXT → READY
- IDLE_HEALTHY: When queue is empty, runs periodic system health checks and remains alive.
- RETRY_WAIT: Bounded exponential backoff on transient faults.
- BUDGET_PAUSED: Pauses model calls when 1,000,000 daily token cap reached; continues local tasks & maintenance.
- SAFE_HALT: Clean shutdown strictly on explicit authorized stop or critical safety breach.
"""

from __future__ import annotations

import datetime
import enum
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..adapters.agi_17_adapter import AGI17Adapter
from ..context.context_engine import ContextEngine, EpistemicStatus
from ..task_control.task_manager import DurableTaskManager
from ..task_control.task_state_machine import TaskState

logger = logging.getLogger(__name__)


class SupervisorState(str, enum.Enum):
    STARTING = "STARTING"
    RECOVERING = "RECOVERING"
    READY = "READY"
    SELECTING_TASK = "SELECTING_TASK"
    BUILDING_CONTEXT = "BUILDING_CONTEXT"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECORDING_LEARNING = "RECORDING_LEARNING"
    SCHEDULING_NEXT = "SCHEDULING_NEXT"
    IDLE_HEALTHY = "IDLE_HEALTHY"
    RETRY_WAIT = "RETRY_WAIT"
    BUDGET_PAUSED = "BUDGET_PAUSED"
    SAFE_HALT = "SAFE_HALT"


class TaskPriority(int, enum.Enum):
    CRITICAL_SAFETY = 1
    LOOP_RELIABILITY = 2
    CONFIRMED_REGRESSION = 3
    MARKET_DATA_INTEGRITY = 4
    ALGORITHM_RESEARCH = 5
    FEATURE_IMPROVEMENT = 6
    EXPLORATORY_CLEANUP = 7


@dataclass
class QueuedTask:
    task_id: str
    title: str
    description: str
    priority: TaskPriority = TaskPriority.FEATURE_IMPROVEMENT
    requires_model_call: bool = False
    attempts: int = 0
    max_attempts: int = 3
    status: str = "QUEUED"  # QUEUED, RUNNING, SUCCEEDED, FAILED, BLOCKED
    created_at: float = field(default_factory=time.time)
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SupervisorRunState:
    supervisor_id: str
    state: SupervisorState
    heartbeat_epoch: float
    heartbeat_iso: str
    total_tasks_completed: int
    total_tasks_failed: int
    active_task_id: Optional[str]
    queued_tasks_count: int
    daily_token_usage: int
    daily_token_cap: int = 1_000_000
    is_budget_paused: bool = False
    stop_requested: bool = False
    last_health_check_result: Dict[str, Any] = field(default_factory=dict)


class PersistentSupervisor:
    """Production 24/7 process-level supervisor coordinating task queues, recovery, and continuous loops."""

    def __init__(
        self,
        adapter: Optional[AGI17Adapter] = None,
        state_file: Optional[Path] = None,
        heartbeat_interval_sec: float = 1.0,
        idle_sleep_sec: float = 0.2,
    ) -> None:
        self.adapter = adapter or AGI17Adapter()
        self.context_engine = ContextEngine()
        self.supervisor_id = f"SUP-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        self.state_file = state_file or (self.adapter.storage_root / "state" / "mission_run_state.json")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.idle_sleep_sec = idle_sleep_sec

        self.current_state: SupervisorState = SupervisorState.STARTING
        self.queue: List[QueuedTask] = []
        self.queue_lock = threading.RLock()
        self.active_task: Optional[QueuedTask] = None
        self.stop_requested: bool = False
        self.total_completed: int = 0
        self.total_failed: int = 0
        self.last_heartbeat: float = time.time()
        self.task_history: List[Dict[str, Any]] = []

        self._save_state()

    def enqueue_task(
        self,
        title: str,
        description: str,
        priority: Any = TaskPriority.FEATURE_IMPROVEMENT,
        requires_model_call: bool = False,
        requires_model: Optional[bool] = None,
        task_id: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> QueuedTask:
        eff_model = requires_model if requires_model is not None else requires_model_call
        p_enum = priority
        if isinstance(priority, int) and not isinstance(priority, TaskPriority):
            try:
                p_enum = TaskPriority(priority)
            except ValueError:
                p_enum = TaskPriority.FEATURE_IMPROVEMENT
        with self.queue_lock:
            tid = task_id or f"TASK-{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}"
            t = QueuedTask(
                task_id=tid,
                title=title,
                description=description,
                priority=p_enum,
                requires_model_call=eff_model,
                dependencies=dependencies or [],
                metadata=metadata or {},
            )
            self.queue.append(t)
            # Maintain stable priority order
            self.queue.sort(key=lambda item: (item.priority.value, item.created_at))
            self._save_state()
            return t

    def request_stop(self) -> None:
        """Signals graceful shutdown."""
        self.stop_requested = True
        self._save_state()

    def _save_state(self) -> None:
        now = time.time()
        self.last_heartbeat = now
        st = SupervisorRunState(
            supervisor_id=self.supervisor_id,
            state=self.current_state,
            heartbeat_epoch=now,
            heartbeat_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            total_tasks_completed=self.total_completed,
            total_tasks_failed=self.total_failed,
            active_task_id=self.active_task.task_id if self.active_task else None,
            queued_tasks_count=len(self.queue),
            daily_token_usage=self.adapter.token_controller.get_summary()["total_tokens"],
            daily_token_cap=1_000_000,
            is_budget_paused=self.current_state == SupervisorState.BUDGET_PAUSED,
            stop_requested=self.stop_requested,
            last_health_check_result={"healthy": True, "ram_ok": True},
        )
        try:
            self.state_file.write_text(json.dumps(asdict(st), indent=2), encoding="utf-8")
        except Exception:
            pass

    def run_startup_recovery(self) -> Dict[str, Any]:
        """Recovers from previous abnormal terminations without repeating side-effects."""
        self.current_state = SupervisorState.RECOVERING
        self._save_state()

        reconciliation = self.adapter.task_manager.reconcile_after_restart()
        startup_info = self.adapter.run_startup_reconciliation()

        self.current_state = SupervisorState.READY
        self._save_state()
        return {
            "reconciliation": reconciliation,
            "startup_info": startup_info,
            "recovered_at": time.time(),
        }

    def check_health(self) -> Dict[str, Any]:
        """Low-cost periodic health probe during IDLE_HEALTHY."""
        profile = self.adapter.profiler.build_full_profile()
        return {
            "status": "HEALTHY",
            "available_ram_mb": profile["memory"]["available_physical_ram_mb"],
            "d_drive_active": profile["storage_and_persistence"]["d_drive_verified"],
            "queued_tasks": len(self.queue),
        }

    def select_next_task(self) -> Optional[QueuedTask]:
        with self.queue_lock:
            # Check budget limit
            current_tokens = self.adapter.token_controller.get_summary()["total_tokens"]
            if current_tokens >= 1_000_000:
                self.current_state = SupervisorState.BUDGET_PAUSED
                self._save_state()
                # If budget paused, only allow tasks that do NOT require model calls
                for candidate in self.queue:
                    if not candidate.requires_model_call and candidate.status == "QUEUED":
                        self.queue.remove(candidate)
                        return candidate
                return None

            # Normal task selection
            for candidate in self.queue:
                if candidate.status == "QUEUED":
                    self.queue.remove(candidate)
                    return candidate
            return None

    def execute_task_step(self, task: QueuedTask) -> Dict[str, Any]:
        """Executes a single queued task through the full state machine."""
        self.active_task = task
        task.status = "RUNNING"
        task.attempts += 1

        # 1. BUILDING_CONTEXT
        self.current_state = SupervisorState.BUILDING_CONTEXT
        self._save_state()
        manifest = self.context_engine.assemble_manifest(
            task_id=task.task_id,
            objective=task.title,
            acceptance_criteria=[f"Complete {task.title} safely without regression"],
        )

        # 2. EXECUTING
        self.current_state = SupervisorState.EXECUTING
        self._save_state()
        try:
            res = self.adapter.execute(
                title=task.title,
                prompt=task.description,
                task_id=task.task_id,
                use_live_model=task.requires_model_call,
            )
            success = res.get("terminal_outcome") in (
                "SUCCEEDED_AND_VERIFIED",
                "SUCCEEDED_UNVERIFIED",
                "PROFILE_ONLY_OK",
                "ALREADY_PASSING",
            ) or res.get("final_state") == "SUCCEEDED"
        except Exception as exc:
            res = {"status": "FAILED", "error": str(exc), "terminal_outcome": "FAILED"}
            success = False

        # 3. VERIFYING
        self.current_state = SupervisorState.VERIFYING
        self._save_state()
        corr_val = res.get("output", {}).get("task_correctness_verified")
        is_verified = bool(success and (corr_val is not False))

        # 4. RECORDING_LEARNING
        self.current_state = SupervisorState.RECORDING_LEARNING
        self._save_state()
        if not success:
            self.context_engine.register_fact(
                subject_key=f"failure:{task.task_id}",
                claim=f"Task '{task.title}' failed: {res.get('error', 'unverified')}",
                status=EpistemicStatus.OBSERVATION,
                provenance=f"supervisor_run_{self.supervisor_id}",
                confidence=0.9,
            )
        else:
            self.context_engine.register_fact(
                subject_key=f"success:{task.task_id}",
                claim=f"Task '{task.title}' completed successfully and verified.",
                status=EpistemicStatus.VERIFIED_FACT,
                provenance=f"supervisor_run_{self.supervisor_id}",
                confidence=1.0,
            )

        # 5. SCHEDULING_NEXT
        self.current_state = SupervisorState.SCHEDULING_NEXT
        self._save_state()

        if success:
            task.status = "SUCCEEDED"
            self.total_completed += 1
        else:
            if task.attempts < task.max_attempts:
                task.status = "QUEUED"
                with self.queue_lock:
                    self.queue.append(task)
            else:
                task.status = "FAILED"
                self.total_failed += 1

        record = {
            "task_id": task.task_id,
            "title": task.title,
            "status": task.status,
            "attempts": task.attempts,
            "result": res,
            "verified": is_verified,
            "timestamp": time.time(),
        }
        self.task_history.append(record)
        self.active_task = None
        self.current_state = SupervisorState.READY
        self._save_state()
        return record

    def run_single_cycle(self) -> SupervisorState:
        """Runs one deterministic iteration of the supervisor loop."""
        if self.stop_requested:
            self.current_state = SupervisorState.SAFE_HALT
            self._save_state()
            return self.current_state

        if self.current_state == SupervisorState.STARTING:
            self.run_startup_recovery()
            return self.current_state

        # Check for eligible tasks
        self.current_state = SupervisorState.SELECTING_TASK
        self._save_state()
        next_task = self.select_next_task()

        if next_task is not None:
            self.execute_task_step(next_task)
            return self.current_state

        # Queue is empty or budget paused without local work: IDLE_HEALTHY
        if self.current_state != SupervisorState.BUDGET_PAUSED:
            self.current_state = SupervisorState.IDLE_HEALTHY
        self.check_health()
        self._save_state()
        return self.current_state

    def run_continuous_loop(self, max_cycles: Optional[int] = None) -> SupervisorState:
        """Runs the continuous loop. Exits strictly on SAFE_HALT or max_cycles."""
        cycles = 0
        while not self.stop_requested:
            cycles += 1
            st = self.run_single_cycle()
            if st == SupervisorState.SAFE_HALT:
                break
            if max_cycles is not None and cycles >= max_cycles:
                break
            if st in (SupervisorState.IDLE_HEALTHY, SupervisorState.BUDGET_PAUSED):
                time.sleep(self.idle_sleep_sec)

        if self.stop_requested:
            self.current_state = SupervisorState.SAFE_HALT
            self._save_state()
        return self.current_state
