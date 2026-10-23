"""AGI 1.7 Streaming Process Supervisor.

Replaces blocking subprocess.run() with non-blocking threaded stream readers,
real-time heartbeats, wall-clock and idle-output timeouts, tree termination,
automatic parent completion notification, and mandatory post-exit artifact
verification. Never requires manual polling to discover completion.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..task_control.task_manager import DurableTaskManager
from ..task_control.task_state_machine import TaskState
from .completion_notifier import (
    CompletionNotification,
    CompletionNotifier,
    ExpectedArtifactSpec,
)
from .recovery_manager import RecoveryDecision, RecoveryManager
from .stream_parser import ParsedStreamEvent, StreamParser


@dataclass
class SupervisedProcessHandle:
    task_id: str
    parent_task_id: Optional[str]
    command: List[str]
    cwd: str
    pid: int
    started_at: float
    stdout_log_path: str
    stderr_log_path: str
    wall_timeout_sec: float
    idle_timeout_sec: float


class ProcessSupervisor:
    """Supervises child processes with live streaming, heartbeats, and automatic completion push."""

    def __init__(
        self,
        task_manager: Optional[DurableTaskManager] = None,
        notifier: Optional[CompletionNotifier] = None,
        recovery_manager: Optional[RecoveryManager] = None,
        logs_dir: str | Path = r"D:\AGI_Storage\AGI_1_7\logs\processes",
        heartbeat_interval_sec: float = 1.0,
    ) -> None:
        self.task_manager = task_manager
        self.notifier = notifier or CompletionNotifier()
        self.recovery_manager = recovery_manager or RecoveryManager()
        self.logs_dir = Path(logs_dir)
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.logs_dir = Path(__file__).resolve().parents[3] / "state_fallback" / "logs" / "processes"
            self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self._active_processes: Dict[str, subprocess.Popen] = {}
        self._cancel_flags: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def cancel_process(self, task_id: str) -> bool:
        """Requests immediate cancellation of a running supervised process."""
        with self._lock:
            ev = self._cancel_flags.get(task_id)
            if ev:
                ev.set()
            proc = self._active_processes.get(task_id)
            if proc and proc.poll() is None:
                self._terminate_process_tree(proc)
                return True
        return False

    @staticmethod
    def _terminate_process_tree(proc: subprocess.Popen) -> None:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def run_supervised(
        self,
        *,
        task_id: str,
        command: Sequence[str],
        cwd: Optional[str | Path] = None,
        env: Optional[Dict[str, str]] = None,
        parent_task_id: Optional[str] = None,
        wall_timeout_sec: float = 180.0,
        idle_timeout_sec: float = 60.0,
        expected_artifacts: Optional[List[ExpectedArtifactSpec]] = None,
        on_progress: Optional[Callable[[ParsedStreamEvent], None]] = None,
        on_complete: Optional[Callable[[CompletionNotification], None]] = None,
        max_retries: int = 0,
    ) -> CompletionNotification:
        """Executes a process with real-time stream parsing, heartbeat updates, and automatic completion push."""
        attempt = 0
        last_notification: Optional[CompletionNotification] = None

        while attempt <= max_retries:
            attempt += 1
            last_notification = self._execute_single_attempt(
                task_id=task_id,
                attempt=attempt,
                command=list(command),
                cwd=str(cwd or os.getcwd()),
                env=env,
                parent_task_id=parent_task_id,
                wall_timeout_sec=wall_timeout_sec,
                idle_timeout_sec=idle_timeout_sec,
                expected_artifacts=expected_artifacts,
                on_progress=on_progress,
                on_complete=None,
            )

            decision: RecoveryDecision = self.recovery_manager.evaluate(
                last_notification,
                current_attempt=attempt,
                max_retries_override=max_retries,
            )
            if not decision.should_retry:
                if on_complete:
                    try:
                        on_complete(last_notification)
                    except Exception:
                        pass
                return last_notification

            if self.task_manager:
                try:
                    self.task_manager.store.record_event(
                        task_id,
                        "PROCESS_RETRY_SCHEDULED",
                        {
                            "attempt": attempt,
                            "reason": decision.reason,
                            "backoff_seconds": decision.backoff_seconds,
                        },
                    )
                except Exception:
                    pass
            time.sleep(decision.backoff_seconds)

        assert last_notification is not None
        return last_notification

    def _execute_single_attempt(
        self,
        *,
        task_id: str,
        attempt: int,
        command: List[str],
        cwd: str,
        env: Optional[Dict[str, str]],
        parent_task_id: Optional[str],
        wall_timeout_sec: float,
        idle_timeout_sec: float,
        expected_artifacts: Optional[List[ExpectedArtifactSpec]],
        on_progress: Optional[Callable[[ParsedStreamEvent], None]],
        on_complete: Optional[Callable[[CompletionNotification], None]],
    ) -> CompletionNotification:
        ts_ms = int(time.time() * 1000)
        stdout_log = self.logs_dir / f"{task_id}_att{attempt}_{ts_ms}_stdout.log"
        stderr_log = self.logs_dir / f"{task_id}_att{attempt}_{ts_ms}_stderr.log"

        parser = StreamParser()
        stdout_tail: List[str] = []
        stderr_tail: List[str] = []
        line_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        cancel_event = threading.Event()

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        started_at = time.time()
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                env=merged_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            err_msg = f"Command launch failed ({type(exc).__name__}): {exc}"
            stdout_log.write_text("", encoding="utf-8")
            stderr_log.write_text(err_msg + "\n", encoding="utf-8")
            finished_at = time.time()
            notification = self.notifier.notify_completion(
                task_id=task_id,
                parent_task_id=parent_task_id,
                pid=-1,
                exit_code=127,
                timed_out=False,
                idle_timed_out=False,
                canceled=False,
                started_at=started_at,
                finished_at=finished_at,
                stdout_log_path=str(stdout_log),
                stderr_log_path=str(stderr_log),
                stdout_tail=[],
                stderr_tail=[err_msg],
                latest_progress_percent=0.0,
                expected_artifacts=expected_artifacts,
                usage_metadata={},
            )
            if on_complete:
                try:
                    on_complete(notification)
                except Exception:
                    pass
            return notification

        with self._lock:
            self._active_processes[task_id] = proc
            self._cancel_flags[task_id] = cancel_event

        if self.task_manager:
            try:
                rec = self.task_manager.store.get_task(task_id)
                if rec and rec["state"] in (TaskState.READY.value, TaskState.QUEUED.value, TaskState.PLANNED.value, TaskState.CREATED.value):
                    if rec["state"] == TaskState.CREATED.value:
                        self.task_manager.transition(task_id, TaskState.PLANNED, reason="Process supervisor plan")
                        self.task_manager.transition(task_id, TaskState.QUEUED, reason="Process supervisor queue")
                        self.task_manager.transition(task_id, TaskState.READY, reason="Process supervisor ready")
                    elif rec["state"] == TaskState.PLANNED.value:
                        self.task_manager.transition(task_id, TaskState.QUEUED, reason="Process supervisor queue")
                        self.task_manager.transition(task_id, TaskState.READY, reason="Process supervisor ready")
                    elif rec["state"] == TaskState.QUEUED.value:
                        self.task_manager.transition(task_id, TaskState.READY, reason="Process supervisor ready")
                    self.task_manager.transition(task_id, TaskState.RUNNING, reason=f"Started PID {proc.pid}")
                self.task_manager.store.update_task_fields(
                    task_id,
                    worker_pid=proc.pid,
                    heartbeat_ts=started_at,
                )
            except Exception:
                pass

        def _reader(pipe: Any, stream_name: str, log_file: Path) -> None:
            try:
                with open(log_file, "w", encoding="utf-8", errors="replace") as lf:
                    for raw_line in iter(pipe.readline, ""):
                        if not raw_line:
                            break
                        lf.write(raw_line)
                        lf.flush()
                        line_queue.put((stream_name, raw_line))
            except Exception:
                pass
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        t_out = threading.Thread(target=_reader, args=(proc.stdout, "stdout", stdout_log), daemon=True)
        t_err = threading.Thread(target=_reader, args=(proc.stderr, "stderr", stderr_log), daemon=True)
        t_out.start()
        t_err.start()

        last_output_ts = started_at
        last_heartbeat_ts = started_at
        timed_out = False
        idle_timed_out = False
        canceled = False

        while True:
            now = time.time()
            # Drain available lines
            drained_any = False
            while True:
                try:
                    stream_name, raw_line = line_queue.get_nowait()
                    drained_any = True
                    last_output_ts = time.time()
                    evt = parser.parse_line(raw_line, stream=stream_name)
                    if stream_name == "stdout":
                        stdout_tail.append(evt.raw_line)
                        if len(stdout_tail) > 50:
                            stdout_tail.pop(0)
                    else:
                        stderr_tail.append(evt.raw_line)
                        if len(stderr_tail) > 50:
                            stderr_tail.pop(0)
                    if on_progress:
                        try:
                            on_progress(evt)
                        except Exception:
                            pass
                except queue.Empty:
                    break

            if cancel_event.is_set():
                canceled = True
                self._terminate_process_tree(proc)
                break

            if (now - started_at) > wall_timeout_sec:
                timed_out = True
                self._terminate_process_tree(proc)
                break

            if (now - last_output_ts) > idle_timeout_sec:
                idle_timed_out = True
                self._terminate_process_tree(proc)
                break

            if (now - last_heartbeat_ts) >= self.heartbeat_interval_sec:
                last_heartbeat_ts = now
                if self.task_manager:
                    try:
                        self.task_manager.heartbeat(
                            task_id,
                            worker_pid=proc.pid,
                            progress={
                                "latest_progress_percent": parser.latest_progress_percent,
                                "line_count": parser.line_count,
                                "elapsed_sec": round(now - started_at, 2),
                            },
                        )
                    except Exception:
                        pass

            if proc.poll() is not None and not drained_any:
                break

            time.sleep(0.05)

        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)

        # Drain any final lines after exit
        while not line_queue.empty():
            try:
                stream_name, raw_line = line_queue.get_nowait()
                evt = parser.parse_line(raw_line, stream=stream_name)
                if stream_name == "stdout":
                    stdout_tail.append(evt.raw_line)
                else:
                    stderr_tail.append(evt.raw_line)
                if on_progress:
                    try:
                        on_progress(evt)
                    except Exception:
                        pass
            except queue.Empty:
                break

        exit_code = proc.poll()
        finished_at = time.time()

        with self._lock:
            self._active_processes.pop(task_id, None)
            self._cancel_flags.pop(task_id, None)

        notification = self.notifier.notify_completion(
            task_id=task_id,
            parent_task_id=parent_task_id,
            pid=proc.pid,
            exit_code=exit_code,
            timed_out=timed_out,
            idle_timed_out=idle_timed_out,
            canceled=canceled,
            started_at=started_at,
            finished_at=finished_at,
            stdout_log_path=str(stdout_log),
            stderr_log_path=str(stderr_log),
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            latest_progress_percent=parser.latest_progress_percent,
            expected_artifacts=expected_artifacts,
            usage_metadata=parser.extracted_usage,
        )

        # Update task state in TaskStore if managed
        if self.task_manager:
            try:
                rec = self.task_manager.store.get_task(task_id)
                if rec and rec["state"] == TaskState.RUNNING.value:
                    if notification.final_status == "CANCELED":
                        self.task_manager.transition(task_id, TaskState.CANCELED, reason="Supervised process canceled")
                    elif notification.final_status == "TIMED_OUT":
                        self.task_manager.transition(
                            task_id,
                            TaskState.TIMED_OUT,
                            reason="Supervised process timed out",
                            error={"timed_out": timed_out, "idle_timed_out": idle_timed_out},
                        )
                    elif notification.final_status == "SUCCEEDED":
                        self.task_manager.transition(task_id, TaskState.VERIFYING, reason="Verifying process exit & artifacts")
                        self.task_manager.transition(
                            task_id,
                            TaskState.SUCCEEDED,
                            reason="Process exited 0 and artifacts verified",
                            result={
                                "notification_id": notification.notification_id,
                                "exit_code": exit_code,
                                "duration_sec": notification.duration_sec,
                                "stdout_tail": notification.stdout_tail[-5:],
                                "artifacts": notification.artifact_verifications,
                            },
                        )
                    else:
                        self.task_manager.transition(
                            task_id,
                            TaskState.FAILED,
                            reason=f"Process failed (exit_code={exit_code}, artifacts_ok={notification.all_artifacts_verified})",
                            error={
                                "exit_code": exit_code,
                                "stderr_tail": notification.stderr_tail[-10:],
                                "artifacts": notification.artifact_verifications,
                            },
                        )
            except Exception:
                pass

        if on_complete:
            try:
                on_complete(notification)
            except Exception:
                pass

        return notification
