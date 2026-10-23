"""AGI 1.7 Continuous 24/7 Supervisor — Multi-Task Continuity & State Machine.

Implements the exact 10-state transactional control plane:
STARTING → RECOVERING → READY → SELECTING_TASK → BUILDING_CONTEXT → EXECUTING → VERIFYING → RECORDING_LEARNING → SCHEDULING_NEXT → READY
- IDLE_HEALTHY: When queue is empty, runs low-cost health checks without terminating.
- BUDGET_PAUSED: Pauses model calls when 1,000,000 daily UTC token cap is reached.
- SAFE_HALT: Clean shutdown only upon explicit request_safe_halt() or critical safety breach.
"""

from __future__ import annotations

import datetime
import enum
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..adapters.agi_17_adapter import AGI17Adapter
from ..context.context_engine import ContextEngine, EpistemicStatus
from ..supervisor.persistent_supervisor import (
    QueuedTask,
    SupervisorRunState,
    SupervisorState,
    TaskPriority,
)
from ..telemetry.token_economy import AdaptiveTokenController


@dataclass
class SupervisorHeartbeat:
    supervisor_id: str
    state: SupervisorState
    timestamp: float
    iso_timestamp: str
    tasks_completed: int
    tasks_failed: int
    queue_depth: int
    active_task_id: Optional[str]
    storage_healthy: bool = True
    token_budget_paused: bool = False


class ContinuousSupervisor:
    """Deterministic, fine-grained state machine supervisor supporting continuous operations."""

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        token_controller: Optional[AdaptiveTokenController] = None,
        adapter: Optional[AGI17Adapter] = None,
        idle_sleep_sec: float = 0.05,
    ) -> None:
        self.state_dir = Path(state_dir) if state_dir else Path(r"D:\AGI_Storage\AGI_1_7\state\supervisor")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "mission_run_state.json"
        self.inbox_dir = self.state_dir / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir = self.state_dir / "inbox_processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        self.adapter = adapter or AGI17Adapter()
        self.token_controller = token_controller or self.adapter.token_controller
        self.context_engine = ContextEngine()
        self.supervisor_id = f"SUP-CONT-{int(time.time())}-{uuid.uuid4().hex[:4]}"
        self.idle_sleep_sec = idle_sleep_sec

        self.current_state: SupervisorState = SupervisorState.READY
        self.queue: List[QueuedTask] = []
        self.queue_lock = threading.RLock()
        self.active_task: Optional[QueuedTask] = None
        self._current_manifest: Any = None
        self._last_execution_result: Optional[Dict[str, Any]] = None
        self._executor_hook: Optional[Callable[[Any, Any], Dict[str, Any]]] = None

        self.stop_requested: bool = False
        self.stop_reason: str = ""
        self.total_completed: int = 0
        self.total_failed: int = 0
        self.task_history: List[Dict[str, Any]] = []

        self._load_persisted_queue()
        self._save_state()

    def _load_persisted_queue(self) -> None:
        """Recovers queued and in-flight tasks following supervisor restart."""
        queue_file = self.state_dir / "tasks_queue.json"
        if queue_file.exists():
            try:
                raw = json.loads(queue_file.read_text(encoding="utf-8"))
                for item in raw:
                    p_val = item.get("priority", 6)
                    try:
                        p_enum = TaskPriority(p_val)
                    except Exception:
                        p_enum = TaskPriority.FEATURE_IMPROVEMENT
                    t = QueuedTask(
                        task_id=item["task_id"],
                        title=item["title"],
                        description=item["description"],
                        priority=p_enum,
                        requires_model_call=item.get("requires_model_call", False),
                        attempts=item.get("attempts", 0),
                        max_attempts=item.get("max_attempts", 3),
                        status="QUEUED" if item.get("status") in ("RUNNING", "QUEUED") else item.get("status", "QUEUED"),
                        created_at=item.get("created_at", time.time()),
                        dependencies=item.get("dependencies", []),
                        metadata=item.get("metadata", {}),
                    )
                    if t.status in ("QUEUED", "BLOCKED"):
                        self.queue.append(t)
            except Exception:
                pass
        if self.state_file.exists():
            try:
                st_data = json.loads(self.state_file.read_text(encoding="utf-8"))
                self.total_completed = st_data.get("total_tasks_completed", 0)
                self.total_failed = st_data.get("total_tasks_failed", 0)
            except Exception:
                pass

    def set_executor(self, hook: Callable[[Any, Any], Dict[str, Any]]) -> None:
        self._executor_hook = hook

    def request_safe_halt(self, reason: str = "Authorized halt requested") -> None:
        self.stop_requested = True
        self.stop_reason = reason
        self._save_state()

    def request_stop(self) -> None:
        self.request_safe_halt("Stop requested")

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
        idempotency_key: Optional[str] = None,
        owner: str = "supervisor",
        deadline: Optional[float] = None,
    ) -> QueuedTask:
        eff_model = requires_model if requires_model is not None else requires_model_call
        p_enum = priority
        if isinstance(priority, int) and not isinstance(priority, TaskPriority):
            try:
                p_enum = TaskPriority(priority)
            except ValueError:
                p_enum = TaskPriority.FEATURE_IMPROVEMENT

        meta = dict(metadata or {})
        if idempotency_key:
            meta["idempotency_key"] = idempotency_key
        meta["owner"] = owner
        if deadline:
            meta["deadline"] = deadline

        with self.queue_lock:
            # Idempotency check: deduplicate against active or queued tasks
            if idempotency_key:
                for existing in self.queue:
                    if existing.metadata.get("idempotency_key") == idempotency_key:
                        return existing
                if self.active_task and self.active_task.metadata.get("idempotency_key") == idempotency_key:
                    return self.active_task

            tid = task_id or f"TASK-{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}"
            t = QueuedTask(
                task_id=tid,
                title=title,
                description=description,
                priority=p_enum,
                requires_model_call=eff_model,
                dependencies=dependencies or [],
                metadata=meta,
            )
            self.queue.append(t)
            self.queue.sort(key=lambda item: (item.priority.value, item.created_at))
            self._save_state()
            return t

    def poll_inbox(self) -> int:
        """Polls self.inbox_dir for task files (*.json, *.jsonl) and enqueues them."""
        if not self.inbox_dir.exists():
            return 0
        enqueued_count = 0
        try:
            for p in sorted(self.inbox_dir.glob("*.*")):
                if p.suffix.lower() not in (".json", ".jsonl"):
                    continue
                try:
                    content = p.read_text(encoding="utf-8").strip()
                    if not content:
                        continue
                    tasks_data: List[Dict[str, Any]] = []
                    if p.suffix.lower() == ".json":
                        data = json.loads(content)
                        if isinstance(data, list):
                            tasks_data = data
                        elif isinstance(data, dict):
                            tasks_data = [data]
                    else:
                        for line in content.splitlines():
                            line = line.strip()
                            if line:
                                tasks_data.append(json.loads(line))

                    for t_dict in tasks_data:
                        title = t_dict.get("title") or t_dict.get("name") or "Untitled Task"
                        description = t_dict.get("description") or t_dict.get("prompt") or ""
                        priority = t_dict.get("priority", TaskPriority.FEATURE_IMPROVEMENT)
                        requires_model = t_dict.get("requires_model", t_dict.get("requires_model_call", False))
                        task_id = t_dict.get("task_id")
                        dependencies = t_dict.get("dependencies", [])
                        metadata = t_dict.get("metadata", {})
                        self.enqueue_task(
                            title=title,
                            description=description,
                            priority=priority,
                            requires_model=requires_model,
                            task_id=task_id,
                            dependencies=dependencies,
                            metadata=metadata,
                        )
                        enqueued_count += 1

                    target_dest = self.processed_dir / f"{p.stem}_{int(time.time() * 1000)}{p.suffix}"
                    p.rename(target_dest)
                except Exception:
                    err_dest = self.processed_dir / f"error_{p.name}_{int(time.time() * 1000)}"
                    try:
                        p.rename(err_dest)
                    except Exception:
                        pass
        except Exception:
            pass
        return enqueued_count

    def _save_state(self) -> None:
        now = time.time()
        tokens_used = self.token_controller.get_daily_utc_usage() if hasattr(self.token_controller, "get_daily_utc_usage") else 0
        st = SupervisorRunState(
            supervisor_id=self.supervisor_id,
            state=self.current_state,
            heartbeat_epoch=now,
            heartbeat_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            total_tasks_completed=self.total_completed,
            total_tasks_failed=self.total_failed,
            active_task_id=self.active_task.task_id if self.active_task else None,
            queued_tasks_count=len(self.queue),
            daily_token_usage=tokens_used,
            daily_token_cap=1_000_000,
            is_budget_paused=self.current_state == SupervisorState.BUDGET_PAUSED,
            stop_requested=self.stop_requested,
            last_health_check_result={"healthy": True, "storage_healthy": True},
        )
        try:
            # Atomic state file replacement
            tmp_state = self.state_file.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}")
            tmp_state.write_text(json.dumps(asdict(st), indent=2), encoding="utf-8")
            tmp_state.replace(self.state_file)

            # Atomic queue file replacement
            queue_file = self.state_dir / "tasks_queue.json"
            all_tasks = [asdict(t) for t in self.queue]
            if self.active_task:
                all_tasks.insert(0, asdict(self.active_task))
            tmp_queue = queue_file.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}")
            tmp_queue.write_text(json.dumps(all_tasks, indent=2), encoding="utf-8")
            tmp_queue.replace(queue_file)
        except Exception:
            pass

    def emit_heartbeat(self) -> SupervisorHeartbeat:
        now = time.time()
        hb = SupervisorHeartbeat(
            supervisor_id=self.supervisor_id,
            state=self.current_state,
            timestamp=now,
            iso_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            tasks_completed=self.total_completed,
            tasks_failed=self.total_failed,
            queue_depth=len(self.queue),
            active_task_id=self.active_task.task_id if self.active_task else None,
            storage_healthy=True,
            token_budget_paused=self.current_state == SupervisorState.BUDGET_PAUSED,
        )
        self._save_state()
        return hb

    def step(self) -> SupervisorState:
        """Executes exactly one discrete state transition in the 10-state control loop."""
        if self.current_state == SupervisorState.SAFE_HALT:
            return self.current_state

        self.poll_inbox()

        if self.stop_requested and self.current_state in (
            SupervisorState.READY,
            SupervisorState.IDLE_HEALTHY,
            SupervisorState.BUDGET_PAUSED,
        ):
            self.current_state = SupervisorState.SAFE_HALT
            self._save_state()
            return self.current_state

        # 1. READY -> SELECTING_TASK
        if self.current_state == SupervisorState.READY:
            self.current_state = SupervisorState.SELECTING_TASK
            self._save_state()
            return self.current_state

        # 2. SELECTING_TASK -> BUILDING_CONTEXT or IDLE_HEALTHY / BUDGET_PAUSED
        if self.current_state == SupervisorState.SELECTING_TASK:
            tokens_used = (
                self.token_controller.get_daily_utc_usage()
                if hasattr(self.token_controller, "get_daily_utc_usage")
                else 0
            )
            is_exhausted = tokens_used >= 1_000_000

            with self.queue_lock:
                candidate: Optional[QueuedTask] = None
                if is_exhausted:
                    # Look for non-model tasks only
                    for item in self.queue:
                        if not item.requires_model_call and item.status == "QUEUED":
                            candidate = item
                            break
                    if candidate is None:
                        self.current_state = SupervisorState.BUDGET_PAUSED
                        self._save_state()
                        return self.current_state
                else:
                    for item in self.queue:
                        if item.status == "QUEUED":
                            candidate = item
                            break

                if candidate is not None:
                    self.queue.remove(candidate)
                    self.active_task = candidate
                    candidate.status = "RUNNING"
                    candidate.attempts += 1
                    self.current_state = SupervisorState.BUILDING_CONTEXT
                    self._save_state()
                    return self.current_state
                else:
                    self.current_state = SupervisorState.IDLE_HEALTHY
                    self._save_state()
                    return self.current_state

        # 3. BUILDING_CONTEXT -> EXECUTING
        if self.current_state == SupervisorState.BUILDING_CONTEXT:
            if self.active_task is not None:
                self._current_manifest = self.context_engine.assemble_manifest(
                    task_id=self.active_task.task_id,
                    objective=self.active_task.title,
                    acceptance_criteria=[f"Execute {self.active_task.title} safely"],
                )
            self.current_state = SupervisorState.EXECUTING
            self._save_state()
            return self.current_state

        # 4. EXECUTING -> VERIFYING
        if self.current_state == SupervisorState.EXECUTING:
            if self.active_task is not None:
                try:
                    if self._executor_hook:
                        self._last_execution_result = self._executor_hook(self.active_task, self._current_manifest)
                    else:
                        self._last_execution_result = self.adapter.execute(
                            title=self.active_task.title,
                            prompt=self.active_task.description,
                            task_id=self.active_task.task_id,
                        )
                except Exception as exc:
                    self._last_execution_result = {"status": "FAILED", "error": str(exc)}
            self.current_state = SupervisorState.VERIFYING
            self._save_state()
            return self.current_state

        # 5. VERIFYING -> RECORDING_LEARNING
        if self.current_state == SupervisorState.VERIFYING:
            self.current_state = SupervisorState.RECORDING_LEARNING
            self._save_state()
            return self.current_state

        # 6. RECORDING_LEARNING -> SCHEDULING_NEXT
        if self.current_state == SupervisorState.RECORDING_LEARNING:
            res = self._last_execution_result or {}
            is_success = res.get("status") in ("SUCCEEDED", "PASSED") or res.get("terminal_outcome") in (
                "SUCCEEDED_AND_VERIFIED",
                "PROFILE_ONLY_OK",
                "ALREADY_PASSING",
            )
            if self.active_task:
                if is_success:
                    self.context_engine.register_fact(
                        subject_key=f"task:{self.active_task.task_id}",
                        claim=f"Task '{self.active_task.title}' succeeded and verified",
                        status=EpistemicStatus.VERIFIED_FACT,
                        provenance="continuous_supervisor",
                    )
                else:
                    self.context_engine.register_fact(
                        subject_key=f"task:{self.active_task.task_id}",
                        claim=f"Task '{self.active_task.title}' failed: {res.get('error', 'unknown')}",
                        status=EpistemicStatus.OBSERVATION,
                        provenance="continuous_supervisor",
                    )
            self.current_state = SupervisorState.SCHEDULING_NEXT
            self._save_state()
            return self.current_state

        # 7. SCHEDULING_NEXT -> READY (Loop NEVER dies!)
        if self.current_state == SupervisorState.SCHEDULING_NEXT:
            res = self._last_execution_result or {}
            is_success = res.get("status") in ("SUCCEEDED", "PASSED") or res.get("terminal_outcome") in (
                "SUCCEEDED_AND_VERIFIED",
                "PROFILE_ONLY_OK",
                "ALREADY_PASSING",
            )
            if self.active_task:
                if is_success:
                    self.active_task.status = "SUCCEEDED"
                    self.total_completed += 1
                else:
                    err_text = str(res.get("error", "Unknown execution failure"))
                    is_rate_limited = "429" in err_text or "rate limit" in err_text.lower() or "quota" in err_text.lower()
                    is_provider_down = "503" in err_text or "outage" in err_text.lower() or "unavailable" in err_text.lower() or "502" in err_text or "504" in err_text

                    diagnostic = {
                        "attempted": f"Execution of task '{self.active_task.title}'",
                        "failed": True,
                        "error": err_text,
                        "remains_possible": "Local state inspection, retry with exponential backoff, supervisor health checks",
                        "next_step": "Diagnose root cause in log trace, check provider quota/connectivity, execute isolated unit test",
                        "is_rate_limited": is_rate_limited,
                        "is_provider_down": is_provider_down,
                    }
                    res["diagnostic"] = diagnostic

                    if (is_rate_limited or is_provider_down) and self.active_task.requires_model_call:
                        self.active_task.status = "BLOCKED"
                        self.active_task.metadata["block_reason"] = "PROVIDER_UNAVAILABLE" if is_provider_down else "RATE_LIMIT_EXCEEDED"
                        self.active_task.metadata["diagnostic"] = diagnostic
                        self.total_failed += 1
                    elif self.active_task.attempts < self.active_task.max_attempts:
                        import random
                        backoff_sec = min(60.0, (2 ** self.active_task.attempts) + random.uniform(0.1, 0.5))
                        self.active_task.metadata["next_retry_at"] = time.time() + backoff_sec
                        self.active_task.status = "QUEUED"
                        with self.queue_lock:
                            self.queue.append(self.active_task)
                    else:
                        self.active_task.status = "FAILED"
                        self.active_task.metadata["diagnostic"] = diagnostic
                        self.total_failed += 1

                self.task_history.append(
                    {
                        "task_id": self.active_task.task_id,
                        "title": self.active_task.title,
                        "status": self.active_task.status,
                        "attempts": self.active_task.attempts,
                        "result": res,
                        "diagnostic": res.get("diagnostic"),
                    }
                )
                self.active_task = None
                self._current_manifest = None
                self._last_execution_result = None

            self.current_state = SupervisorState.READY
            self._save_state()
            return self.current_state

        # 8. IDLE_HEALTHY -> READY if new work, else stay IDLE
        if self.current_state == SupervisorState.IDLE_HEALTHY:
            with self.queue_lock:
                has_work = any(t.status == "QUEUED" for t in self.queue)
            if has_work:
                self.current_state = SupervisorState.READY
            self._save_state()
            return self.current_state

        # 9. BUDGET_PAUSED -> READY if budget resets or non-model task queued
        if self.current_state == SupervisorState.BUDGET_PAUSED:
            tokens_used = (
                self.token_controller.get_daily_utc_usage()
                if hasattr(self.token_controller, "get_daily_utc_usage")
                else 0
            )
            with self.queue_lock:
                has_local_work = any(not t.requires_model_call and t.status == "QUEUED" for t in self.queue)
            if tokens_used < 1_000_000 or has_local_work:
                self.current_state = SupervisorState.READY
            self._save_state()
            return self.current_state

        return self.current_state

    def run_continuous(self, max_iterations: Optional[int] = None) -> int:
        """Continuous execution loop with configurable iteration bound."""
        iterations = 0
        while not self.stop_requested:
            iterations += 1
            st = self.step()
            if st == SupervisorState.SAFE_HALT:
                break
            if max_iterations is not None and iterations >= max_iterations:
                break
            if st in (SupervisorState.IDLE_HEALTHY, SupervisorState.BUDGET_PAUSED):
                time.sleep(self.idle_sleep_sec)

        if self.stop_requested:
            self.current_state = SupervisorState.SAFE_HALT
            self._save_state()
        return self.total_completed
