"""AGI 1.7 Win32 Continuous Resource Watchdog Daemon.

Monitors:
1. Physical RAM headroom against the 1,400 MB minimum floor.
2. Commit charge / pagefile headroom against the 2,500 MB floor.
3. CPU utilization against the 85.0% maximum ceiling.
4. Host disk volume headroom (C: >= 5.0 GB, D: >= 10.0 GB).
5. Dynamic notification to ResourceGovernor when pressure thresholds are breached.
6. Zero external dependencies: Uses native Win32 ctypes via ResourceSnapshot.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..capabilities.resource_snapshot import LiveResourceMetrics, ResourceSnapshot
from ..orchestration.resource_governor import ResourceGovernor


@dataclass
class WatchdogReport:
    timestamp_utc: str
    status: str  # "HEALTHY" | "PRESSURE_WARNING" | "PRESSURE_THROTTLED"
    free_phys_ram_mb: float
    free_commit_mb: float
    cpu_percent: float
    free_c_gb: float
    free_d_gb: float
    on_ac_power: bool
    battery_pct: int
    warnings: List[str] = field(default_factory=list)
    throttle_applied: bool = False


class ResourceWatchdogDaemon:
    """Continuous background resource watchdog and telemetry logger."""

    def __init__(
        self,
        *,
        governor: Optional[ResourceGovernor] = None,
        state_dir: Optional[Path | str] = None,
        min_free_ram_mb: float = 1400.0,
        min_free_commit_mb: float = 2500.0,
        max_cpu_percent: float = 85.0,
        min_c_free_gb: float = 5.0,
        min_d_free_gb: float = 10.0,
        alert_callback: Optional[Callable[[WatchdogReport], None]] = None,
    ) -> None:
        self.governor = governor or ResourceGovernor()
        self.min_free_ram_mb = min_free_ram_mb
        self.min_free_commit_mb = min_free_commit_mb
        self.max_cpu_percent = max_cpu_percent
        self.min_c_free_gb = min_c_free_gb
        self.min_d_free_gb = min_d_free_gb
        self.alert_callback = alert_callback

        if state_dir:
            self.state_dir = Path(state_dir)
        else:
            self.state_dir = Path("agents/AGI_1_7/runtime_storage/state")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "resource_watchdog_state.json"

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self.last_report: Optional[WatchdogReport] = None

    def probe_once(self, snap: Optional[LiveResourceMetrics] = None) -> WatchdogReport:
        """Captures hardware state and applies governance throttling if pressure detected."""
        metrics = snap or ResourceSnapshot.capture(sample_cpu_ms=40)
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(metrics.timestamp))

        warnings: List[str] = []
        throttle_needed = False

        # Physical RAM check
        if metrics.avail_phys_mb < self.min_free_ram_mb:
            warnings.append(f"RAM below floor: {metrics.avail_phys_mb:.1f} MB < {self.min_free_ram_mb} MB")
            throttle_needed = True
        elif metrics.avail_phys_mb < self.min_free_ram_mb + 400.0:
            warnings.append(f"RAM near floor: {metrics.avail_phys_mb:.1f} MB")

        # Commit headroom check
        if metrics.avail_pagefile_mb < self.min_free_commit_mb:
            warnings.append(f"Commit headroom low: {metrics.avail_pagefile_mb:.1f} MB < {self.min_free_commit_mb} MB")
            throttle_needed = True

        # CPU check
        if metrics.cpu_percent > self.max_cpu_percent:
            warnings.append(f"CPU high: {metrics.cpu_percent:.1f}% > {self.max_cpu_percent}%")
            throttle_needed = True
        elif metrics.cpu_percent > 75.0:
            warnings.append(f"CPU elevated: {metrics.cpu_percent:.1f}%")

        # Disk checks
        if metrics.c_drive_free_gb < self.min_c_free_gb:
            warnings.append(f"C: drive low: {metrics.c_drive_free_gb:.1f} GB < {self.min_c_free_gb} GB")
        if metrics.d_drive_free_gb < self.min_d_free_gb:
            warnings.append(f"D: drive low: {metrics.d_drive_free_gb:.1f} GB < {self.min_d_free_gb} GB")

        # Status determination
        if throttle_needed:
            status = "PRESSURE_THROTTLED"
            self.governor.report_timeout_or_quota_pressure()
        elif warnings:
            status = "PRESSURE_WARNING"
        else:
            status = "HEALTHY"
            self.governor.clear_pressure_strikes()

        report = WatchdogReport(
            timestamp_utc=now_str,
            status=status,
            free_phys_ram_mb=round(metrics.avail_phys_mb, 1),
            free_commit_mb=round(metrics.avail_pagefile_mb, 1),
            cpu_percent=round(metrics.cpu_percent, 1),
            free_c_gb=round(metrics.c_drive_free_gb, 1),
            free_d_gb=round(metrics.d_drive_free_gb, 1),
            on_ac_power=metrics.on_ac_power,
            battery_pct=metrics.battery_life_pct,
            warnings=warnings,
            throttle_applied=throttle_needed,
        )

        with self._lock:
            self.last_report = report
            try:
                self.state_file.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
            except Exception:
                pass

        if self.alert_callback and (status != "HEALTHY"):
            try:
                self.alert_callback(report)
            except Exception:
                pass

        return report

    def start_background(self, poll_interval_sec: float = 2.0) -> None:
        """Launches continuous monitoring thread."""
        with self._lock:
            if self._running:
                return
            self._running = True

            def _loop() -> None:
                while self._running:
                    try:
                        self.probe_once()
                    except Exception:
                        pass
                    time.sleep(poll_interval_sec)

            self._thread = threading.Thread(target=_loop, daemon=True, name="AGI17-ResourceWatchdog")
            self._thread.start()

    def stop_background(self) -> None:
        """Halts the background monitoring thread."""
        with self._lock:
            self._running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
                self._thread = None
