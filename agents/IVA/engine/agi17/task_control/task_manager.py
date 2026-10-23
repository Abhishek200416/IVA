"""
engine/agi17/task_control/task_manager.py
AGI 1.7 OMEGA COMMAND — Durable Task Manager & Live Command Inbox
"""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .checkpoint_manager import CheckpointManager
from .dependency_manager import DependencyManager
from .task_state_machine import TERMINAL_STATES, TaskState, TaskStateMachine
from .task_store import TaskStore


class CommandIntent(str):
    NEW_INDEPENDENT_TASK = "NEW_INDEPENDENT_TASK"
    ADD_SUBTASK = "ADD_SUBTASK"
    ADD_CHILD_TASK = "ADD_CHILD_TASK"
    EXPAND_SCOPE = "EXPAND_SCOPE"
    CHANGE_PRIORITY = "CHANGE_PRIORITY"
    ADD_BENCHMARK = "ADD_BENCHMARK"
    PAUSE = "PAUSE"
    PAUSE_CURRENT_AND_SWITCH = "PAUSE_CURRENT_AND_SWITCH"
    RESUME = "RESUME"
    CANCEL = "CANCEL"
    CANCEL_AND_REPLACE = "CANCEL_AND_REPLACE"
    REQUEST_STATUS = "REQUEST_STATUS"
    REQUEST_RESOURCE_INFO = "REQUEST_RESOURCE_INFO"
    REVISE_PLAN = "REVISE_PLAN"
    CHANGE_BUDGET = "CHANGE_BUDGET"
    UPDATE_CONSTRAINTS = "UPDATE_CONSTRAINTS"
    APPEND_TO_QUEUE = "APPEND_TO_QUEUE"


class CommandInbox:
    """Durable SQLite-backed live instruction inbox."""

    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def submit(
        self,
        *,
        instruction_type: str,
        target_task_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        raw_instruction: Optional[str] = None,
    ) -> str:
        rec = self.store.record_command_event(
            raw_instruction=raw_instruction or instruction_type,
            intent_class=instruction_type,
            relationship_to_active="LIVE_CHECKPOINT_COMMAND",
            ack_status="ACKNOWLEDGED",
            handling_outcome="PENDING_CHECKPOINT",
            target_job_id=target_task_id,
            details=payload or {},
            processed_ts=None,
        )
        return str(rec["command_id"])


class DurableTaskManager:
    """Central durable control plane for tasks, child hierarchies, and live user instructions."""

    def __init__(
        self,
        db_path: str | Path = r"D:\AGI_Storage\AGI_1_7\state\tasks.db",
        events_jsonl_path: Optional[str | Path] = None,
        checkpoint_dir: str | Path = r"D:\AGI_Storage\AGI_1_7\checkpoints",
        checkpoints_dir: Optional[str | Path] = None,
        max_delegation_depth: int = 3,
        max_logical_children: int = 100,
    ):
        self.store = TaskStore(db_path=db_path, events_jsonl_path=events_jsonl_path)
        ckpt_target = checkpoints_dir if checkpoints_dir is not None else checkpoint_dir
        self.checkpoints = CheckpointManager(checkpoint_dir=ckpt_target, task_store=self.store)
        self.ckpt_mgr = self.checkpoints
        self.dependencies = DependencyManager(
            task_store=self.store,
            max_delegation_depth=max_delegation_depth,
            max_logical_children=max_logical_children,
        )
        self.dep_mgr = self.dependencies
        self.inbox = CommandInbox(self.store)
        self._idempotency_index: Dict[str, str] = {}

    def create_task(
        self,
        *,
        title: str,
        description: str = "",
        task_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
        priority: int = 50,
        specialist_role: Optional[str] = None,
        token_budget: int = 12000,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        meta = dict(metadata or {})
        if idempotency_key:
            meta["idempotency_key"] = idempotency_key
            existing_tid = self._idempotency_index.get(idempotency_key)
            if existing_tid:
                existing_rec = self.store.get_task(existing_tid)
                if existing_rec:
                    return existing_rec
            for t in self.store.list_tasks():
                if (t.get("metadata") or {}).get("idempotency_key") == idempotency_key:
                    self._idempotency_index[idempotency_key] = t["task_id"]
                    return t

        if task_id:
            existing_by_id = self.store.get_task(task_id)
            if existing_by_id and idempotency_key:
                self._idempotency_index[idempotency_key] = task_id
                return existing_by_id

        if parent_task_id:
            parent_rec = self.store.get_task(parent_task_id)
            job_id = parent_rec["job_id"] if parent_rec else parent_task_id
            self.dependencies.validate_child_creation(job_id, parent_task_id)
        else:
            job_id = task_id

        if depends_on and task_id:
            self.dependencies.validate_no_cycle(job_id, task_id, depends_on)

        created = self.store.create_task(
            title=title,
            description=description,
            job_id=job_id,
            task_id=task_id,
            parent_task_id=parent_task_id,
            specialist_role=specialist_role,
            priority=priority,
            depends_on=depends_on,
            token_budget=token_budget,
            metadata=meta,
        )
        if idempotency_key:
            self._idempotency_index[idempotency_key] = created["task_id"]
        return created

    def transition(
        self,
        task_id: str,
        next_state: str | TaskState,
        *,
        reason: str = "",
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Any] = None,
    ) -> Dict[str, Any]:
        err_str = str(error) if error is not None else None
        return self.store.transition_task(
            task_id=task_id,
            next_state=next_state,
            details={"reason": reason} if reason else {},
            error_detail=err_str,
            result_data=result,
        )

    def heartbeat(
        self,
        task_id: str,
        *,
        worker_pid: Optional[int] = None,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        kwargs: Dict[str, Any] = {}
        if worker_pid is not None:
            kwargs["pid"] = worker_pid
        self.store.update_task_fields(task_id, **kwargs)
        if progress:
            self.store.record_event(task_id, "HEARTBEAT", progress)

    def save_checkpoint(
        self,
        task_id: str,
        *,
        step_index: int,
        state_payload: Dict[str, Any],
        completed_side_effects: Optional[List[str]] = None,
        artifact_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self.checkpoints.save_checkpoint(
            task_id=task_id,
            step_index=step_index,
            completed_steps=completed_side_effects,
            state_payload=state_payload,
            artifact_paths=artifact_paths,
            completed_side_effects=completed_side_effects,
        )

    def process_inbox_checkpoint(self, active_task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Processes pending CommandInbox instructions at a safe wave/step checkpoint."""
        pending = self.store.get_pending_commands(target_task_id=active_task_id)
        applied: List[Dict[str, Any]] = []

        for cmd in pending:
            cid = cmd["command_id"]
            itype = cmd["instruction_type"]
            target_id = cmd.get("target_task_id") or active_task_id
            payload = cmd.get("payload") or {}
            action_summary: Dict[str, Any] = {"command_id": cid, "instruction_type": itype}

            if itype in ("ADD_CHILD_TASK", "ADD_SUBTASK", "ADD_BENCHMARK") and target_id:
                child_id = payload.get("child_task_id") or f"{target_id}-DYN-{uuid.uuid4().hex[:4]}"
                child = self.create_task(
                    task_id=child_id,
                    parent_task_id=target_id,
                    title=payload.get("title", "Dynamic Child Task"),
                    description=payload.get("description", ""),
                    depends_on=payload.get("depends_on", []),
                    priority=int(payload.get("priority", 60)),
                    specialist_role=payload.get("specialist_role", "swe_python_runtime_engineer"),
                )
                self.transition(child_id, TaskState.PLANNED, reason="Planned via CommandInbox")
                self.transition(child_id, TaskState.QUEUED, reason="Queued via CommandInbox")
                action_summary["created_child_id"] = child["task_id"]

            elif itype in ("PAUSE", "PAUSE_CURRENT_AND_SWITCH") and target_id:
                t_rec = self.store.get_task(target_id)
                if t_rec and t_rec["state"] in (TaskState.RUNNING.value, TaskState.READY.value, TaskState.QUEUED.value):
                    self.transition(target_id, TaskState.WAITING_FOR_INPUT, reason="Paused via CommandInbox")
                if itype == "PAUSE_CURRENT_AND_SWITCH":
                    new_id = payload.get("new_task_id") or f"URGENT-{int(time.time() * 1000)}"
                    self.create_task(
                        task_id=new_id,
                        title=payload.get("title", "Urgent Switch Task"),
                        description=payload.get("description", ""),
                        priority=int(payload.get("priority", 100)),
                    )
                    self.transition(new_id, TaskState.PLANNED, reason="Urgent switch planned")
                    self.transition(new_id, TaskState.QUEUED, reason="Urgent switch queued")
                    self.transition(new_id, TaskState.READY, reason="Urgent switch ready")
                    action_summary["switched_to_task_id"] = new_id

            elif itype in ("CANCEL", "CANCEL_AND_REPLACE") and target_id:
                t_rec = self.store.get_task(target_id)
                if t_rec and not TaskStateMachine.is_terminal(t_rec["state"]):
                    self.transition(target_id, TaskState.CANCELED, reason="Canceled via CommandInbox")
                if itype == "CANCEL_AND_REPLACE":
                    rep_id = payload.get("replacement_task_id") or f"REPL-{int(time.time() * 1000)}"
                    self.create_task(
                        task_id=rep_id,
                        title=payload.get("title", "Replacement Task"),
                        description=payload.get("description", ""),
                        priority=int(payload.get("priority", 80)),
                    )
                    self.transition(rep_id, TaskState.PLANNED, reason="Replacement planned")
                    self.transition(rep_id, TaskState.QUEUED, reason="Replacement queued")
                    self.transition(rep_id, TaskState.READY, reason="Replacement ready")
                    action_summary["replacement_task_id"] = rep_id

            elif itype in ("UPDATE_CONSTRAINTS", "CHANGE_BUDGET", "CHANGE_PRIORITY") and target_id:
                t_rec = self.store.get_task(target_id)
                if t_rec:
                    meta = dict(t_rec.get("metadata") or {})
                    meta.update(payload)
                    self.store.update_task_fields(
                        target_id,
                        metadata=meta,
                        priority=int(payload.get("priority", t_rec["priority"])),
                    )

            self.store.mark_command_processed(cid, outcome="APPLIED_AT_CHECKPOINT")
            applied.append(action_summary)

        return applied

    @staticmethod
    def _is_pid_alive(pid: Optional[int]) -> bool:
        if not pid or pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                res = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    shell=False,
                )
                return str(pid) in (res.stdout or "")
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def reconcile_after_restart(self) -> List[Dict[str, Any]]:
        """Reconciles persisted RUNNING tasks against actual OS processes and checkpoints upon restart."""
        running_tasks = self.store.list_tasks(state=TaskState.RUNNING)
        actions: List[Dict[str, Any]] = []

        for t in running_tasks:
            tid = t["task_id"]
            pid = t.get("pid")
            if pid and self._is_pid_alive(pid):
                actions.append({"task_id": tid, "action": "STILL_ALIVE", "pid": pid})
                continue

            self.store.transition_task(
                tid,
                TaskState.INTERRUPTED,
                {"reason": "process_not_running_on_reconciliation", "stale_pid": pid},
            )
            try:
                ckpt = self.checkpoints.load_checkpoint(tid)
            except (ValueError, OSError) as exc:
                actions.append(
                    {
                        "task_id": tid,
                        "action": "MARKED_INTERRUPTED_CORRUPTED_CHECKPOINT",
                        "error": str(exc),
                        "stale_pid": pid,
                    }
                )
                continue
            if ckpt and ckpt.get("side_effects_verified_intact", True):
                self.store.transition_task(
                    tid,
                    TaskState.READY,
                    {"reason": "requeued_from_verified_checkpoint", "checkpoint_step": ckpt.get("step_index")},
                )
                actions.append(
                    {
                        "task_id": tid,
                        "action": "REQUEUED_FROM_CHECKPOINT",
                        "checkpoint_step": ckpt.get("step_index"),
                        "stale_pid": pid,
                    }
                )
            else:
                actions.append(
                    {
                        "task_id": tid,
                        "action": "MARKED_INTERRUPTED",
                        "stale_pid": pid,
                    }
                )

        return actions
