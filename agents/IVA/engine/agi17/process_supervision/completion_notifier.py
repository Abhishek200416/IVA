"""AGI 1.7 Completion Notifier & Artifact Validator.

Automatically notifies parent tasks and writes durable completion records
when a supervised process finishes, crashes, or times out. Performs
mandatory post-exit artifact verification before marking any download
or build task SUCCEEDED.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ExpectedArtifactSpec:
    path: str
    min_size_bytes: int = 1
    expected_sha256: Optional[str] = None
    must_be_valid_json: bool = False


@dataclass
class ArtifactVerificationResult:
    path: str
    exists: bool
    size_bytes: int
    sha256: Optional[str]
    size_ok: bool
    hash_ok: bool
    format_ok: bool
    passed: bool
    error: Optional[str] = None


@dataclass
class CompletionNotification:
    notification_id: str
    task_id: str
    parent_task_id: Optional[str]
    pid: int
    exit_code: Optional[int]
    timed_out: bool
    idle_timed_out: bool
    canceled: bool
    started_at: float
    finished_at: float
    duration_sec: float
    stdout_log_path: str
    stderr_log_path: str
    stdout_tail: List[str]
    stderr_tail: List[str]
    latest_progress_percent: Optional[float]
    artifact_verifications: List[Dict[str, Any]]
    all_artifacts_verified: bool
    final_status: str  # "SUCCEEDED" | "FAILED" | "TIMED_OUT" | "CANCELED"
    usage_metadata: Dict[str, Any] = field(default_factory=dict)


class CompletionNotifier:
    """Verifies expected output artifacts and publishes immediate completion events to parent."""

    def __init__(
        self,
        notifications_dir: str | Path = r"D:\AGI_Storage\AGI_1_7\agent_messages",
    ) -> None:
        self.notifications_dir = Path(notifications_dir)
        try:
            self.notifications_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.notifications_dir = Path(__file__).resolve().parents[3] / "state_fallback" / "agent_messages"
            self.notifications_dir.mkdir(parents=True, exist_ok=True)
        self._callbacks: List[Callable[[CompletionNotification], None]] = []

    def register_callback(self, callback: Callable[[CompletionNotification], None]) -> None:
        self._callbacks.append(callback)

    @staticmethod
    def verify_artifact(spec: ExpectedArtifactSpec) -> ArtifactVerificationResult:
        p = Path(spec.path)
        if not p.exists() or not p.is_file():
            return ArtifactVerificationResult(
                path=spec.path,
                exists=False,
                size_bytes=0,
                sha256=None,
                size_ok=False,
                hash_ok=False,
                format_ok=False,
                passed=False,
                error="File does not exist",
            )
        size_bytes = p.stat().st_size
        size_ok = size_bytes >= spec.min_size_bytes

        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        digest = h.hexdigest()

        hash_ok = True
        if spec.expected_sha256:
            hash_ok = digest.lower() == spec.expected_sha256.lower()

        format_ok = True
        err_msg: Optional[str] = None
        if spec.must_be_valid_json:
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                format_ok = False
                err_msg = f"Invalid JSON: {exc}"

        passed = size_ok and hash_ok and format_ok
        if not passed and not err_msg:
            if not size_ok:
                err_msg = f"Size {size_bytes} < min_size_bytes {spec.min_size_bytes}"
            elif not hash_ok:
                err_msg = f"SHA-256 mismatch: expected {spec.expected_sha256}, got {digest}"

        return ArtifactVerificationResult(
            path=spec.path,
            exists=True,
            size_bytes=size_bytes,
            sha256=digest,
            size_ok=size_ok,
            hash_ok=hash_ok,
            format_ok=format_ok,
            passed=passed,
            error=err_msg,
        )

    def notify_completion(
        self,
        *,
        task_id: str,
        parent_task_id: Optional[str],
        pid: int,
        exit_code: Optional[int],
        timed_out: bool,
        idle_timed_out: bool,
        canceled: bool,
        started_at: float,
        finished_at: float,
        stdout_log_path: str,
        stderr_log_path: str,
        stdout_tail: List[str],
        stderr_tail: List[str],
        latest_progress_percent: Optional[float],
        expected_artifacts: Optional[List[ExpectedArtifactSpec]] = None,
        usage_metadata: Optional[Dict[str, Any]] = None,
    ) -> CompletionNotification:
        verifications: List[ArtifactVerificationResult] = []
        all_verified = True
        for spec in expected_artifacts or []:
            res = self.verify_artifact(spec)
            verifications.append(res)
            if not res.passed:
                all_verified = False

        if canceled:
            final_status = "CANCELED"
        elif timed_out or idle_timed_out:
            final_status = "TIMED_OUT"
        elif exit_code == 0 and all_verified:
            final_status = "SUCCEEDED"
        else:
            final_status = "FAILED"

        notification = CompletionNotification(
            notification_id=f"NOTIF-{task_id}-{int(finished_at * 1000)}",
            task_id=task_id,
            parent_task_id=parent_task_id,
            pid=pid,
            exit_code=exit_code,
            timed_out=timed_out,
            idle_timed_out=idle_timed_out,
            canceled=canceled,
            started_at=started_at,
            finished_at=finished_at,
            duration_sec=round(max(0.0, finished_at - started_at), 4),
            stdout_log_path=stdout_log_path,
            stderr_log_path=stderr_log_path,
            stdout_tail=stdout_tail[-25:],
            stderr_tail=stderr_tail[-25:],
            latest_progress_percent=latest_progress_percent,
            artifact_verifications=[asdict(v) for v in verifications],
            all_artifacts_verified=all_verified,
            final_status=final_status,
            usage_metadata=usage_metadata or {},
        )

        # Persist durable completion record immediately
        out_path = self.notifications_dir / f"{notification.notification_id}.json"
        out_path.write_text(json.dumps(asdict(notification), indent=2), encoding="utf-8")

        # Also append to parent's notification stream
        ledger_path = self.notifications_dir / "completion_notifications.jsonl"
        with open(ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(notification), ensure_ascii=False) + "\n")

        for cb in list(self._callbacks):
            try:
                cb(notification)
            except Exception:
                pass

        return notification
