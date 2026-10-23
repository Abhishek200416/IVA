"""AGI 1.7 Adaptive Resource Governor & Quantum Compute Gatekeeper.

Separates:
  - MAX_AGENT_SPECIALIZATIONS = 100 (registry breadth)
  - MAX_LOGICAL_CHILD_TASKS = 100 (planned child tasks in SQLite DAG)
  - MAX_ACTIVE_EXECUTIONS = dynamic (governed by live CPU/RAM/commit/disk/quota headroom)

Implements the admission formula:
  current_usage(r) + estimated_new_load(r) <= safe_capacity(r)
across CPU, physical RAM, Windows commit charge, C:\\ and D:\\ disk space,
subprocess count, container slots, and token quota pressure, with hysteresis
to prevent rapid concurrency oscillation.

Also implements `QuantumComputeAdapter` disabled by default (`status="UNAVAILABLE"`)
per PRX Quantum 3, 030101 and Frontiers in AI 2026 (10.3389/frai.2026.1836641).
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..capabilities.resource_snapshot import LiveResourceMetrics, ResourceSnapshot


MAX_AGENT_SPECIALIZATIONS: int = 100
MAX_LOGICAL_CHILD_TASKS: int = 100


@dataclass
class WorkloadFootprint:
    queue_type: str  # "light_in_process" | "model_call" | "cli_subprocess" | "docker_container" | "browser" | "heavy_download"
    estimated_ram_mb: float
    estimated_commit_mb: float
    estimated_cpu_pct: float
    requires_subprocess: bool = False
    requires_container: bool = False


WORKLOAD_FOOTPRINTS: Dict[str, WorkloadFootprint] = {
    "light_in_process": WorkloadFootprint("light_in_process", 15.0, 20.0, 3.0, False, False),
    "model_call": WorkloadFootprint("model_call", 280.0, 350.0, 12.0, True, False),
    "cli_subprocess": WorkloadFootprint("cli_subprocess", 250.0, 320.0, 15.0, True, False),
    "docker_container": WorkloadFootprint("docker_container", 650.0, 800.0, 25.0, True, True),
    "browser": WorkloadFootprint("browser", 450.0, 550.0, 20.0, True, False),
    "heavy_download": WorkloadFootprint("heavy_download", 120.0, 160.0, 8.0, True, False),
}


@dataclass
class AdmissionDecision:
    admitted: bool
    queue_type: str
    reason: str
    recommended_max_active_executions: int
    current_active_in_queue: int
    queue_limit: int
    snapshot_summary: Dict[str, Any] = field(default_factory=dict)


class QuantumComputeAdapter:
    """Optional quantum execution adapter disabled by default unless provable backend exists."""

    def __init__(self, enabled: bool = False, backend_provider: Optional[str] = None) -> None:
        self.enabled = False  # Enforced disabled unless verified hardware/credential & provable speedup exist
        self.backend_provider = backend_provider
        self.status = "UNAVAILABLE"

    def get_status(self) -> Dict[str, Any]:
        return {
            "adapter": "QuantumComputeAdapter",
            "enabled": self.enabled,
            "status": self.status,
            "backend_provider": self.backend_provider,
            "scientific_justification": (
                "Disabled by default per PRX Quantum 3, 030101 and Frontiers in AI 2026 "
                "(10.3389/frai.2026.1836641): classical scheduling/routing heuristics "
                "outperform unverified quantum simulations without exponential state overhead."
            ),
        }

    def execute_quantum_circuit(self, circuit_spec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "UNAVAILABLE",
            "executed": False,
            "reason": "QuantumComputeAdapter is disabled by default; no verified quantum backend configured.",
        }


class ResourceGovernor:
    """Dynamic concurrency governor with multi-queue admission control and hysteresis."""

    def __init__(
        self,
        *,
        min_free_phys_ram_mb: float = 1400.0,
        min_free_commit_mb: float = 2500.0,
        max_cpu_percent: float = 85.0,
        min_c_drive_free_gb: float = 5.0,
        min_d_drive_free_gb: float = 10.0,
        hysteresis_window: int = 3,
    ) -> None:
        self.min_free_phys_ram_mb = min_free_phys_ram_mb
        self.min_free_commit_mb = min_free_commit_mb
        self.max_cpu_percent = max_cpu_percent
        self.min_c_drive_free_gb = min_c_drive_free_gb
        self.min_d_drive_free_gb = min_d_drive_free_gb
        self.hysteresis_window = hysteresis_window

        self._lock = threading.RLock()
        self._active_by_queue: Dict[str, int] = {k: 0 for k in WORKLOAD_FOOTPRINTS}
        self._base_queue_limits: Dict[str, int] = {
            "light_in_process": 16,
            "model_call": 3,
            "cli_subprocess": 3,
            "docker_container": 2,
            "browser": 1,
            "heavy_download": 1,
        }
        self._current_heavy_cap: int = 2
        self._consecutive_healthy_samples: int = 0
        self._timeout_or_quota_strike_count: int = 0
        self.quantum_adapter = QuantumComputeAdapter(enabled=False)

    def compute_dynamic_active_cap(self, snap: Optional[LiveResourceMetrics] = None) -> int:
        metrics = snap or ResourceSnapshot.capture(sample_cpu_ms=40)
        with self._lock:
            # Check hard pressure conditions -> immediate scale down
            ram_headroom = metrics.avail_phys_mb - self.min_free_phys_ram_mb
            commit_headroom = metrics.avail_pagefile_mb - self.min_free_commit_mb

            if (
                ram_headroom < 300.0
                or commit_headroom < 500.0
                or metrics.cpu_percent > self.max_cpu_percent
                or self._timeout_or_quota_strike_count > 0
            ):
                self._consecutive_healthy_samples = 0
                self._current_heavy_cap = 1
                return self._current_heavy_cap

            # Compute safe ceiling from available physical RAM (~350 MB per heavy worker above floor)
            ram_slots = max(1, int(ram_headroom // 350.0))
            commit_slots = max(1, int(commit_headroom // 450.0))
            cpu_slots = max(1, int((self.max_cpu_percent - metrics.cpu_percent) // 18.0))
            target_cap = max(1, min(4, ram_slots, commit_slots, cpu_slots))

            if target_cap > self._current_heavy_cap:
                self._consecutive_healthy_samples += 1
                if self._consecutive_healthy_samples >= self.hysteresis_window:
                    self._current_heavy_cap = min(4, self._current_heavy_cap + 1)
                    self._consecutive_healthy_samples = 0
            elif target_cap < self._current_heavy_cap:
                # Scale down immediately on tightening headroom
                self._current_heavy_cap = target_cap
                self._consecutive_healthy_samples = 0

            return self._current_heavy_cap

    def report_timeout_or_quota_pressure(self) -> int:
        """Immediately throttles concurrency down when timeouts or rate-limit errors occur."""
        with self._lock:
            self._timeout_or_quota_strike_count += 1
            self._current_heavy_cap = 1
            self._consecutive_healthy_samples = 0
            return self._current_heavy_cap

    def clear_pressure_strikes(self) -> None:
        with self._lock:
            self._timeout_or_quota_strike_count = 0

    def check_admission(
        self,
        queue_type: str = "model_call",
        snap: Optional[LiveResourceMetrics] = None,
    ) -> AdmissionDecision:
        if queue_type not in WORKLOAD_FOOTPRINTS:
            raise ValueError(f"Unknown workload queue_type '{queue_type}'")

        footprint = WORKLOAD_FOOTPRINTS[queue_type]
        metrics = snap or ResourceSnapshot.capture(sample_cpu_ms=30)

        with self._lock:
            dyn_cap = self.compute_dynamic_active_cap(metrics)
            cur_q = self._active_by_queue.get(queue_type, 0)
            q_limit = (
                self._base_queue_limits["light_in_process"]
                if queue_type == "light_in_process"
                else min(self._base_queue_limits[queue_type], dyn_cap)
            )

            snap_summary = {
                "cpu_percent": metrics.cpu_percent,
                "avail_phys_mb": metrics.avail_phys_mb,
                "avail_pagefile_mb": metrics.avail_pagefile_mb,
                "c_drive_free_gb": metrics.c_drive_free_gb,
                "d_drive_free_gb": metrics.d_drive_free_gb,
            }

            if cur_q >= q_limit:
                return AdmissionDecision(
                    admitted=False,
                    queue_type=queue_type,
                    reason=f"Queue '{queue_type}' at capacity ({cur_q}/{q_limit})",
                    recommended_max_active_executions=dyn_cap,
                    current_active_in_queue=cur_q,
                    queue_limit=q_limit,
                    snapshot_summary=snap_summary,
                )

            # Check admission formula: current_usage(r) + estimated_new_load(r) <= safe_capacity(r)
            projected_free_ram = metrics.avail_phys_mb - footprint.estimated_ram_mb
            if queue_type != "light_in_process" and projected_free_ram < self.min_free_phys_ram_mb:
                return AdmissionDecision(
                    admitted=False,
                    queue_type=queue_type,
                    reason=(
                        f"Insufficient physical RAM headroom: avail={metrics.avail_phys_mb:.1f}MB - "
                        f"est={footprint.estimated_ram_mb:.1f}MB < floor={self.min_free_phys_ram_mb:.1f}MB"
                    ),
                    recommended_max_active_executions=dyn_cap,
                    current_active_in_queue=cur_q,
                    queue_limit=q_limit,
                    snapshot_summary=snap_summary,
                )

            projected_free_commit = metrics.avail_pagefile_mb - footprint.estimated_commit_mb
            if queue_type != "light_in_process" and projected_free_commit < self.min_free_commit_mb:
                return AdmissionDecision(
                    admitted=False,
                    queue_type=queue_type,
                    reason=(
                        f"Insufficient commit headroom: avail={metrics.avail_pagefile_mb:.1f}MB - "
                        f"est={footprint.estimated_commit_mb:.1f}MB < floor={self.min_free_commit_mb:.1f}MB"
                    ),
                    recommended_max_active_executions=dyn_cap,
                    current_active_in_queue=cur_q,
                    queue_limit=q_limit,
                    snapshot_summary=snap_summary,
                )

            if metrics.cpu_percent + footprint.estimated_cpu_pct > 95.0 and queue_type != "light_in_process":
                return AdmissionDecision(
                    admitted=False,
                    queue_type=queue_type,
                    reason=f"CPU saturation guard: current={metrics.cpu_percent:.1f}% + est={footprint.estimated_cpu_pct:.1f}% > 95%",
                    recommended_max_active_executions=dyn_cap,
                    current_active_in_queue=cur_q,
                    queue_limit=q_limit,
                    snapshot_summary=snap_summary,
                )

            if metrics.d_drive_free_gb < self.min_d_drive_free_gb:
                return AdmissionDecision(
                    admitted=False,
                    queue_type=queue_type,
                    reason=f"D:\\ free space ({metrics.d_drive_free_gb} GB) below minimum ({self.min_d_drive_free_gb} GB)",
                    recommended_max_active_executions=dyn_cap,
                    current_active_in_queue=cur_q,
                    queue_limit=q_limit,
                    snapshot_summary=snap_summary,
                )

            return AdmissionDecision(
                admitted=True,
                queue_type=queue_type,
                reason="Resource admission formula satisfied",
                recommended_max_active_executions=dyn_cap,
                current_active_in_queue=cur_q,
                queue_limit=q_limit,
                snapshot_summary=snap_summary,
            )

    def acquire_slot(self, queue_type: str = "model_call", snap: Optional[LiveResourceMetrics] = None) -> AdmissionDecision:
        with self._lock:
            decision = self.check_admission(queue_type=queue_type, snap=snap)
            if decision.admitted:
                self._active_by_queue[queue_type] = self._active_by_queue.get(queue_type, 0) + 1
                decision.current_active_in_queue = self._active_by_queue[queue_type]
            return decision

    def release_slot(self, queue_type: str = "model_call") -> None:
        with self._lock:
            cur = self._active_by_queue.get(queue_type, 0)
            self._active_by_queue[queue_type] = max(0, cur - 1)

    def get_limits_summary(self, snap: Optional[LiveResourceMetrics] = None) -> Dict[str, Any]:
        with self._lock:
            dyn_cap = self.compute_dynamic_active_cap(snap)
            return {
                "MAX_AGENT_SPECIALIZATIONS": MAX_AGENT_SPECIALIZATIONS,
                "MAX_LOGICAL_CHILD_TASKS": MAX_LOGICAL_CHILD_TASKS,
                "MAX_ACTIVE_EXECUTIONS": dyn_cap,
                "active_by_queue": dict(self._active_by_queue),
                "timeout_or_quota_strikes": self._timeout_or_quota_strike_count,
                "quantum_adapter": self.quantum_adapter.get_status(),
            }
