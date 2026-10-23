"""
engine/agi17/task_control/task_store.py
AGI 1.7 OMEGA COMMAND — Transactional SQLite WAL Task Store & Append-Only Event Ledger
"""

import contextlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .task_state_machine import TaskState, TaskStateMachine


class TaskStore:
    """Thread-safe transactional SQLite WAL store + append-only JSONL event log."""

    def __init__(
        self,
        db_path: str | Path = r"D:\AGI_Storage\AGI_1_7\state\tasks.db",
        event_log_path: Optional[str | Path] = None,
        events_jsonl_path: Optional[str | Path] = None,
        fallback_dir: Optional[str | Path] = None,
    ):
        self.lock = threading.RLock()
        self.fallback_dir = str(
            fallback_dir
            or os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "local_fallback_storage", "state")
            )
        )
        self.db_path = self._resolve_writable_path(str(db_path))
        chosen_log = events_jsonl_path or event_log_path
        self.event_log_path = str(
            chosen_log
            if chosen_log is not None
            else os.path.join(os.path.dirname(self.db_path), "task_events.jsonl")
        )
        self.events_jsonl_path = self.event_log_path
        self._init_db()

    def _resolve_writable_path(self, preferred_path: str) -> str:
        try:
            parent = os.path.dirname(preferred_path)
            os.makedirs(parent, exist_ok=True)
            probe = os.path.join(parent, ".write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return preferred_path
        except Exception:
            os.makedirs(self.fallback_dir, exist_ok=True)
            return os.path.join(self.fallback_dir, os.path.basename(preferred_path))

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        parent_task_id TEXT,
                        campaign_id TEXT,
                        title TEXT NOT NULL,
                        description TEXT,
                        specialist_id TEXT,
                        agi_version TEXT DEFAULT '1.7.0',
                        state TEXT NOT NULL,
                        priority INTEGER DEFAULT 5,
                        idempotency_key TEXT UNIQUE,
                        dependencies_json TEXT DEFAULT '[]',
                        budget_json TEXT DEFAULT '{}',
                        checkpoint_json TEXT DEFAULT '{}',
                        artifact_path TEXT,
                        verification_status TEXT DEFAULT 'PROPOSED',
                        retry_count INTEGER DEFAULT 0,
                        max_retries INTEGER DEFAULT 2,
                        pid INTEGER,
                        exit_code INTEGER,
                        error_detail TEXT,
                        result_json TEXT DEFAULT '{}',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        started_at REAL,
                        ended_at REAL,
                        provenance TEXT DEFAULT 'SEEDED_FIXTURE',
                        last_heartbeat REAL,
                        verification_evidence_json TEXT DEFAULT '{}'
                    );

                    CREATE INDEX IF NOT EXISTS idx_tasks_job_id ON tasks(job_id);
                    CREATE INDEX IF NOT EXISTS idx_tasks_parent_id ON tasks(parent_task_id);
                    CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);

                    CREATE TABLE IF NOT EXISTS command_inbox (
                        event_id TEXT PRIMARY KEY,
                        arrival_ts REAL NOT NULL,
                        session_id TEXT,
                        target_job_id TEXT,
                        raw_instruction TEXT NOT NULL,
                        intent_class TEXT NOT NULL,
                        relationship_to_active TEXT NOT NULL,
                        ack_status TEXT NOT NULL,
                        handling_outcome TEXT NOT NULL,
                        created_task_id TEXT,
                        details_json TEXT DEFAULT '{}',
                        processed_ts REAL
                    );

                    CREATE TABLE IF NOT EXISTS task_events (
                        event_id TEXT PRIMARY KEY,
                        timestamp REAL NOT NULL,
                        task_id TEXT NOT NULL,
                        job_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        from_state TEXT,
                        to_state TEXT,
                        details_json TEXT DEFAULT '{}'
                    );
                    """
                )
                # Check for existing table schema migrations
                cursor = conn.execute("PRAGMA table_info(tasks)")
                existing_cols = {row["name"] for row in cursor.fetchall()}
                if "provenance" not in existing_cols:
                    conn.execute("ALTER TABLE tasks ADD COLUMN provenance TEXT DEFAULT 'SEEDED_FIXTURE'")
                if "last_heartbeat" not in existing_cols:
                    conn.execute("ALTER TABLE tasks ADD COLUMN last_heartbeat REAL")
                if "verification_evidence_json" not in existing_cols:
                    conn.execute("ALTER TABLE tasks ADD COLUMN verification_evidence_json TEXT DEFAULT '{}'")


    def _append_event(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        job_id: str,
        event_type: str,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ts = time.time()
        ev_id = f"TEV-{int(ts * 1000)}-{uuid.uuid4().hex[:8]}"
        details_dict = details or {}
        conn.execute(
            """
            INSERT INTO task_events (event_id, timestamp, task_id, job_id, event_type, from_state, to_state, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ev_id, ts, task_id, job_id, event_type, from_state, to_state, json.dumps(details_dict)),
        )
        record = {
            "event_id": ev_id,
            "timestamp": ts,
            "task_id": task_id,
            "job_id": job_id,
            "event_type": event_type,
            "from_state": from_state,
            "to_state": to_state,
            "details": details_dict,
        }
        try:
            os.makedirs(os.path.dirname(self.event_log_path), exist_ok=True)
            with open(self.event_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
        return record

    def record_event(self, task_id: str, event_type: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self.lock:
            with self._connect() as conn:
                row = conn.execute("SELECT job_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                j_id = row["job_id"] if row else task_id
                return self._append_event(conn, task_id, j_id, event_type, None, None, details)

    def create_task(
        self,
        title: str = "Task",
        description: str = "",
        job_id: Optional[str] = None,
        task_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        specialist_id: Optional[str] = None,
        specialist_role: Optional[str] = None,
        priority: int = 5,
        idempotency_key: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        depends_on: Optional[List[str]] = None,
        budget: Optional[Dict[str, Any]] = None,
        token_budget: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        input_data: Optional[Dict[str, Any]] = None,
        delegation_depth: Optional[int] = None,
        max_retries: int = 2,
        initial_state: TaskState = TaskState.CREATED,
        provenance: str = "REAL_DISPATCHED",
        verification_status: Optional[str] = None,
        verification_evidence: Optional[Dict[str, Any]] = None,
        worker_pid: Optional[int] = None,
        last_heartbeat: Optional[float] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            with self._connect() as conn:
                if idempotency_key:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE idempotency_key = ?", (idempotency_key,)
                    ).fetchone()
                    if row:
                        return self._row_to_dict(row)
                elif job_id:
                    active_match = conn.execute(
                        """
                        SELECT * FROM tasks 
                        WHERE job_id = ? AND COALESCE(parent_task_id, '') = ? AND LOWER(title) = ?
                          AND state NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')
                        """,
                        (job_id, parent_task_id or '', title.strip().lower()),
                    ).fetchone()
                    if active_match:
                        return self._row_to_dict(active_match)

                now = time.time()
                t_id = task_id or f"TSK-{int(now * 1000)}-{uuid.uuid4().hex[:6]}"
                j_id = job_id or (parent_task_id if parent_task_id else t_id)
                state_val = TaskStateMachine.normalize(initial_state).value
                spec_val = specialist_role or specialist_id or "plan_mission_decomposer"
                deps_list = list(depends_on if depends_on is not None else (dependencies or []))

                computed_depth = delegation_depth
                if computed_depth is None:
                    if parent_task_id:
                        p_row = conn.execute("SELECT budget_json FROM tasks WHERE task_id = ?", (parent_task_id,)).fetchone()
                        p_budget = json.loads(p_row["budget_json"] or "{}") if p_row else {}
                        computed_depth = int(p_budget.get("delegation_depth", 0)) + 1
                    else:
                        computed_depth = 0

                budget_dict = dict(budget or {})
                if token_budget is not None:
                    budget_dict["token_budget"] = token_budget
                if metadata is not None:
                    budget_dict["metadata"] = metadata
                elif input_data is not None:
                    budget_dict["metadata"] = input_data
                budget_dict["delegation_depth"] = computed_depth

                started_ts = now if state_val == "RUNNING" else None
                hb_ts = last_heartbeat if last_heartbeat is not None else (now if state_val == "RUNNING" else None)
                ver_status = verification_status or "PROPOSED"
                ver_evidence_str = json.dumps(verification_evidence or {})

                conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id, job_id, parent_task_id, campaign_id, title, description,
                        specialist_id, state, priority, idempotency_key, dependencies_json,
                        budget_json, max_retries, created_at, updated_at, started_at, pid,
                        provenance, last_heartbeat, verification_evidence_json, verification_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t_id,
                        j_id,
                        parent_task_id,
                        campaign_id,
                        title,
                        description,
                        spec_val,
                        state_val,
                        priority,
                        idempotency_key,
                        json.dumps(deps_list),
                        json.dumps(budget_dict),
                        max_retries,
                        now,
                        now,
                        started_ts,
                        worker_pid,
                        provenance,
                        hb_ts,
                        ver_evidence_str,
                        ver_status,
                    ),
                )
                self._append_event(
                    conn,
                    t_id,
                    j_id,
                    "TASK_CREATED",
                    None,
                    state_val,
                    {"title": title, "parent_task_id": parent_task_id, "specialist_id": spec_val, "provenance": provenance},
                )
                row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (t_id,)).fetchone()
                return self._row_to_dict(row)

    def transition_task(
        self,
        task_id: str,
        next_state: str | TaskState,
        details: Optional[Dict[str, Any]] = None,
        pid: Optional[int] = None,
        exit_code: Optional[int] = None,
        artifact_path: Optional[str] = None,
        verification_status: Optional[str] = None,
        verification_evidence: Optional[Dict[str, Any]] = None,
        error_detail: Optional[str] = None,
        result_data: Optional[Dict[str, Any]] = None,
        heartbeat: Optional[float] = None,
        provenance: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            with self._connect() as conn:
                tid = task_id.get("task_id") if isinstance(task_id, dict) else str(task_id)
                row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (tid,)).fetchone()
                if not row:
                    raise KeyError(f"Task not found: {task_id}")
                task_id = tid
                curr_state = row["state"]
                validated_next = TaskStateMachine.validate_transition(curr_state, next_state)
                now = time.time()

                started_at = row["started_at"]
                ended_at = row["ended_at"]
                if validated_next == TaskState.RUNNING and not started_at:
                    started_at = now
                if validated_next in {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.TIMED_OUT, TaskState.CANCELED}:
                    ended_at = now

                new_pid = pid if pid is not None else row["pid"]
                new_exit = exit_code if exit_code is not None else row["exit_code"]
                new_art = artifact_path if artifact_path is not None else row["artifact_path"]
                new_ver = verification_status if verification_status is not None else row["verification_status"]
                new_err = error_detail if error_detail is not None else row["error_detail"]
                new_res = json.dumps(result_data) if result_data is not None else row["result_json"]
                
                # Update heartbeat: if running, set to heartbeat param or current timestamp
                if validated_next == TaskState.RUNNING:
                    new_hb = heartbeat if heartbeat is not None else now
                else:
                    new_hb = heartbeat if heartbeat is not None else (row["last_heartbeat"] if "last_heartbeat" in row.keys() else None)

                # Verification Authenticity Gate:
                # A task must not be labeled VERIFIED_PASS without genuine validation evidence
                if new_ver == "VERIFIED_PASS":
                    has_evidence = False
                    if verification_evidence and isinstance(verification_evidence, dict) and len(verification_evidence) > 0:
                        if verification_evidence.get("passed") is True or verification_evidence.get("verified") is True:
                            has_evidence = True
                    if result_data and isinstance(result_data, dict):
                        if result_data.get("verified") is True or result_data.get("passed") is True or result_data.get("status") in ("PASSED", "VERIFIED"):
                            has_evidence = True
                        elif "checks_passed" in result_data and len(result_data["checks_passed"]) > 0:
                            has_evidence = True
                    if not has_evidence:
                        new_ver = "UNVERIFIED_RESULT"
                        if details is None:
                            details = {}
                        details["verification_override"] = "Downgraded from VERIFIED_PASS to UNVERIFIED_RESULT: lacks empirical verification evidence"

                ver_ev_json = json.dumps(verification_evidence) if verification_evidence is not None else (row["verification_evidence_json"] if "verification_evidence_json" in row.keys() else "{}")
                new_prov = provenance if provenance is not None else (row["provenance"] if "provenance" in row.keys() else "SEEDED_FIXTURE")

                conn.execute(
                    """
                    UPDATE tasks
                    SET state = ?, updated_at = ?, started_at = ?, ended_at = ?,
                        pid = ?, exit_code = ?, artifact_path = ?, verification_status = ?,
                        error_detail = ?, result_json = ?, last_heartbeat = ?,
                        verification_evidence_json = ?, provenance = ?
                    WHERE task_id = ?
                    """,
                    (
                        validated_next.value,
                        now,
                        started_at,
                        ended_at,
                        new_pid,
                        new_exit,
                        new_art,
                        new_ver,
                        new_err,
                        new_res,
                        new_hb,
                        ver_ev_json,
                        new_prov,
                        task_id,
                    ),
                )
                self._append_event(
                    conn,
                    task_id,
                    row["job_id"],
                    "STATE_TRANSITION",
                    curr_state,
                    validated_next.value,
                    details or {},
                )
                updated = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                return self._row_to_dict(updated)

    # Alias for compatibility with external callers
    transition_state = transition_task

    def record_heartbeat(
        self,
        task_id: str,
        timestamp: Optional[float] = None,
        pid: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Records a fresh heartbeat from an executing worker or daemon."""
        with self.lock:
            now = timestamp or time.time()
            tid = task_id.get("task_id") if isinstance(task_id, dict) else str(task_id)
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (tid,)).fetchone()
                if not row:
                    return False
                task_id = tid
                curr_pid = pid if pid is not None else row["pid"]
                conn.execute(
                    "UPDATE tasks SET last_heartbeat = ?, updated_at = ?, pid = ? WHERE task_id = ?",
                    (now, now, curr_pid, task_id),
                )
                self._append_event(
                    conn,
                    task_id,
                    row["job_id"],
                    "HEARTBEAT_RECORDED",
                    row["state"],
                    row["state"],
                    details or {"timestamp": now, "pid": curr_pid},
                )
                return True

    def audit_stale_tasks(
        self,
        staleness_threshold_sec: float = 120.0,
        auto_mark_orphaned: bool = False,
        stale_threshold_sec: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Audits tasks in RUNNING state to detect dead processes or missing heartbeats."""
        threshold = stale_threshold_sec if stale_threshold_sec is not None else staleness_threshold_sec
        with self.lock:
            stale_list = []
            now = time.time()
            with self._connect() as conn:
                running_rows = conn.execute("SELECT * FROM tasks WHERE state = 'RUNNING'").fetchall()
                for r in running_rows:
                    t = self._row_to_dict(r)
                    hb = t.get("last_heartbeat") or t.get("updated_at") or 0.0
                    age = now - hb
                    if age > threshold:
                        # Check PID liveness
                        is_pid_alive = False
                        pid = t.get("pid")
                        if pid:
                            try:
                                import psutil
                                is_pid_alive = psutil.pid_exists(pid)
                            except Exception:
                                try:
                                    os.kill(pid, 0)
                                    is_pid_alive = True
                                except Exception:
                                    is_pid_alive = False

                        health = "STALE_HEARTBEAT" if is_pid_alive else "ORPHANED_DEAD"
                        t["is_stale"] = True
                        t["execution_health"] = health
                        t["staleness_age_sec"] = round(age, 1)
                        stale_list.append(t)

                        if auto_mark_orphaned and not is_pid_alive:
                            conn.execute(
                                "UPDATE tasks SET state = 'FAILED', error_detail = ?, updated_at = ?, ended_at = ? WHERE task_id = ?",
                                (
                                    f"Orphaned task execution timed out after {age:.1f}s without heartbeat (PID dead or missing)",
                                    now,
                                    now,
                                    t["task_id"],
                                ),
                            )
                            self._append_event(
                                conn,
                                t["task_id"],
                                t["job_id"],
                                "TASK_ORPHANED_TIMEOUT",
                                "RUNNING",
                                "FAILED",
                                {"age_sec": age, "pid": pid},
                            )
            return stale_list

    def update_task_fields(self, task_id: str, **kwargs: Any) -> Dict[str, Any]:
        with self.lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                if not row:
                    raise KeyError(f"Task not found: {task_id}")

                if "worker_pid" in kwargs:
                    kwargs["pid"] = kwargs.pop("worker_pid")
                if "depends_on" in kwargs:
                    kwargs["dependencies_json"] = kwargs.pop("depends_on")
                if "checkpoint_path" in kwargs:
                    kwargs["artifact_path"] = kwargs.pop("checkpoint_path")
                if "specialist_role" in kwargs:
                    kwargs["specialist_id"] = kwargs.pop("specialist_role")
                if "metadata" in kwargs:
                    b_cur = json.loads(row["budget_json"] or "{}")
                    b_cur["metadata"] = kwargs.pop("metadata")
                    kwargs["budget_json"] = b_cur
                if "verification_evidence" in kwargs:
                    kwargs["verification_evidence_json"] = kwargs.pop("verification_evidence")

                allowed = {
                    "priority",
                    "dependencies_json",
                    "budget_json",
                    "checkpoint_json",
                    "artifact_path",
                    "verification_status",
                    "retry_count",
                    "pid",
                    "exit_code",
                    "error_detail",
                    "result_json",
                    "specialist_id",
                    "provenance",
                    "last_heartbeat",
                    "verification_evidence_json",
                }
                updates = []
                params = []
                for k, v in kwargs.items():
                    if k in allowed:
                        updates.append(f"{k} = ?")
                        params.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
                if updates:
                    updates.append("updated_at = ?")
                    params.append(time.time())
                    params.append(task_id)
                    conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?", tuple(params))
                updated = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                return self._row_to_dict(updated)

    def get_task(self, task_id: str | Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self.lock:
            tid = task_id.get("task_id") if isinstance(task_id, dict) else str(task_id)
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (tid,)).fetchone()
                return self._row_to_dict(row) if row else None

    def list_tasks(
        self,
        job_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        state: Optional[str | TaskState] = None,
    ) -> List[Dict[str, Any]]:
        with self.lock:
            with self._connect() as conn:
                clauses = []
                params = []
                if job_id:
                    clauses.append("job_id = ?")
                    params.append(job_id)
                if parent_task_id:
                    clauses.append("parent_task_id = ?")
                    params.append(parent_task_id)
                if state:
                    s_val = state.value if isinstance(state, TaskState) else str(state)
                    clauses.append("state = ?")
                    params.append(s_val)
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                rows = conn.execute(
                    f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at ASC",
                    tuple(params),
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]

    def count_by_state(self) -> Dict[str, int]:
        with self.lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT state, COUNT(*) as cnt FROM tasks GROUP BY state").fetchall()
                return {str(r["state"]): int(r["cnt"]) for r in rows}

    def record_command_event(
        self,
        raw_instruction: str,
        intent_class: str,
        relationship_to_active: str,
        ack_status: str = "ACKNOWLEDGED",
        handling_outcome: str = "QUEUED_FOR_CHECKPOINT",
        session_id: str = "local_session",
        target_job_id: Optional[str] = None,
        created_task_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        processed_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            now = time.time()
            ev_id = f"CMD-{int(now * 1000)}-{uuid.uuid4().hex[:6]}"
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO command_inbox (
                        event_id, arrival_ts, session_id, target_job_id, raw_instruction,
                        intent_class, relationship_to_active, ack_status, handling_outcome,
                        created_task_id, details_json, processed_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id,
                        now,
                        session_id,
                        target_job_id,
                        raw_instruction,
                        intent_class,
                        relationship_to_active,
                        ack_status,
                        handling_outcome,
                        created_task_id,
                        json.dumps(details or {}),
                        processed_ts,
                    ),
                )
            return {
                "event_id": ev_id,
                "command_id": ev_id,
                "arrival_ts": now,
                "session_id": session_id,
                "target_job_id": target_job_id,
                "target_task_id": target_job_id,
                "raw_instruction": raw_instruction,
                "intent_class": intent_class,
                "instruction_type": intent_class,
                "relationship_to_active": relationship_to_active,
                "ack_status": ack_status,
                "handling_outcome": handling_outcome,
                "created_task_id": created_task_id,
                "details": details or {},
                "payload": details or {},
            }

    def get_pending_commands(self, target_task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.lock:
            with self._connect() as conn:
                if target_task_id:
                    rows = conn.execute(
                        "SELECT * FROM command_inbox WHERE (target_job_id = ? OR target_job_id IS NULL) AND processed_ts IS NULL ORDER BY arrival_ts ASC",
                        (target_task_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM command_inbox WHERE processed_ts IS NULL ORDER BY arrival_ts ASC"
                    ).fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    details = json.loads(d.pop("details_json", "{}") or "{}")
                    d["command_id"] = d["event_id"]
                    d["instruction_type"] = d["intent_class"]
                    d["target_task_id"] = d["target_job_id"]
                    d["details"] = details
                    d["payload"] = details
                    out.append(d)
                return out

    def mark_command_processed(self, command_id: str, outcome: str = "APPLIED_AT_CHECKPOINT") -> None:
        with self.lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE command_inbox SET processed_ts = ?, handling_outcome = ? WHERE event_id = ?",
                    (time.time(), outcome, command_id),
                )

    def list_command_events(self, target_job_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.lock:
            with self._connect() as conn:
                if target_job_id:
                    rows = conn.execute(
                        "SELECT * FROM command_inbox WHERE target_job_id = ? ORDER BY arrival_ts ASC",
                        (target_job_id,),
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM command_inbox ORDER BY arrival_ts ASC").fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d["details"] = json.loads(d.pop("details_json", "{}") or "{}")
                    out.append(d)
                return out

    def list_task_events(self, task_id: Optional[str] = None, job_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.lock:
            with self._connect() as conn:
                if task_id:
                    rows = conn.execute(
                        "SELECT * FROM task_events WHERE task_id = ? ORDER BY timestamp ASC", (task_id,)
                    ).fetchall()
                elif job_id:
                    rows = conn.execute(
                        "SELECT * FROM task_events WHERE job_id = ? ORDER BY timestamp ASC", (job_id,)
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM task_events ORDER BY timestamp ASC").fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d["details"] = json.loads(d.pop("details_json", "{}") or "{}")
                    out.append(d)
                return out

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        deps = json.loads(d.pop("dependencies_json", "[]") or "[]")
        budget = json.loads(d.pop("budget_json", "{}") or "{}")
        checkpoint = json.loads(d.pop("checkpoint_json", "{}") or "{}")
        result = json.loads(d.pop("result_json", "{}") or "{}")

        d["dependencies"] = deps
        d["depends_on"] = deps
        d["budget"] = budget
        d["metadata"] = budget.get("metadata", {})
        d["delegation_depth"] = int(budget.get("delegation_depth", 1 if d.get("parent_task_id") else 0))
        d["checkpoint"] = checkpoint
        d["checkpoint_path"] = d.get("artifact_path") or checkpoint.get("checkpoint_path")
        d["result"] = result
        d["specialist_role"] = d.get("specialist_id")
        d["worker_pid"] = d.get("pid")

        # Provenance & Heartbeat telemetry
        d["provenance"] = d.get("provenance") or "SEEDED_FIXTURE"
        d["last_heartbeat"] = d.get("last_heartbeat")
        ver_ev = json.loads(d.pop("verification_evidence_json", "{}") or "{}") if "verification_evidence_json" in d else {}
        d["verification_evidence"] = ver_ev

        # Dynamic execution health calculation
        state = d.get("state")
        now = time.time()
        hb = d.get("last_heartbeat") or d.get("updated_at") or 0.0
        age = now - hb if hb > 0 else 999999.0

        if state == "RUNNING":
            if age > 120.0:
                d["is_stale"] = True
                d["execution_health"] = "STALE_HEARTBEAT" if d.get("pid") else "ORPHANED_DEAD"
            else:
                d["is_stale"] = False
                d["execution_health"] = "HEALTHY_RUNNING"
        elif state in ("SUCCEEDED", "COMPLETED"):
            d["is_stale"] = False
            if d.get("verification_status") == "VERIFIED_PASS":
                d["execution_health"] = "COMPLETED_VALIDATED"
            else:
                d["execution_health"] = "COMPLETED_UNVERIFIED"
        elif state == "FAILED":
            d["is_stale"] = False
            d["execution_health"] = "FAILED"
        else:
            d["is_stale"] = False
            d["execution_health"] = "QUEUED_STANDBY"

        return d

