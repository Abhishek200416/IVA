"""AGI 1.7 OMEGA COMMAND — Authoritative Unified Runtime Supervisor (Phase 17.19).

Coordinates the three primary managed services:
1. chrome_cdp_service (Chrome on port 9229)
2. dashboard_service (Standalone Dashboard on port 8088)
3. overlay_service (Persistent Overlay Guardian Daemon)

Enforces strict lifecycle state machines (STOPPED, STARTING, RUNNING, DEGRADED, FAILED, STOPPING),
dependency-ordered startup, process adoption without duplicates, and audit-grade telemetry.
"""

import enum
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("RuntimeSupervisor")


class ServiceState(str, enum.Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPING = "STOPPING"


class RuntimeReadiness(str, enum.Enum):
    STOPPED = "STOPPED"
    STARTED = "STARTED"
    HEALTHY = "HEALTHY"
    LIVE_DATA_QUALIFIED = "LIVE_DATA_QUALIFIED"
    AFTER_HOURS_MONITORING = "AFTER_HOURS_MONITORING"


@dataclass
class ServiceStatus:
    name: str
    state: ServiceState = ServiceState.STOPPED
    pid: Optional[int] = None
    port: Optional[int] = None
    start_time: Optional[str] = None
    last_heartbeat: Optional[str] = None
    last_health_check: Optional[str] = None
    last_error: Optional[str] = None
    restart_count: int = 0
    is_adopted: bool = False
    unhealthy_reason: Optional[str] = None
    launch_command: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass
class RuntimeEvent:
    event_id: str
    timestamp: str
    component: str
    event_type: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RuntimeSupervisor:
    """Authoritative singleton supervisor for AGI 1.7 runtime."""

    _instance: Optional["RuntimeSupervisor"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "RuntimeSupervisor":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, workspace_dir: Optional[Path] = None):
        self.workspace_dir = workspace_dir or Path(Path(__file__).resolve().parents[3])
        self.python_exe = str(self.workspace_dir / ".venv" / "Scripts" / "python.exe")
        if not os.path.exists(self.python_exe):
            self.python_exe = sys.executable

        self._services: Dict[str, ServiceStatus] = {
            "chrome_cdp_service": ServiceStatus(
                name="chrome_cdp_service",
                port=9229,
                launch_command=f"{self.python_exe} -m agents.AGI_1_7.engine.agi17.browser.launch_persistent_browser --login-url \"https://www.paytmmoney.com/stocks/fno/dashboard\"",
                dependencies=[]
            ),
            "dashboard_service": ServiceStatus(
                name="dashboard_service",
                port=8088,
                launch_command=f"{self.python_exe} -m agents.AGI_1_7.ui.standalone_dashboard_server 8088",
                dependencies=[]
            ),
            "overlay_service": ServiceStatus(
                name="overlay_service",
                launch_command=f"{self.python_exe} persistent_overlay_guardian_daemon.py",
                dependencies=["chrome_cdp_service", "dashboard_service"]
            ),
        }

        self._managed_procs: Dict[str, subprocess.Popen] = {}
        self._events: List[RuntimeEvent] = []
        self._event_counter: int = 0
        self._monitoring_active: bool = False
        self._monitor_thread: Optional[threading.Thread] = None

        self._emit_event("SUPERVISOR", "INITIALIZATION", "Runtime supervisor initialized with service registry.")
        # Perform non-invasive initial reconciliation
        self.reconcile()

    def _emit_event(self, component: str, event_type: str, message: str, details: Optional[Dict[str, Any]] = None):
        self._event_counter += 1
        now_str = datetime.now(timezone.utc).isoformat()
        evt = RuntimeEvent(
            event_id=f"EVT-{int(time.time())}-{self._event_counter:04d}",
            timestamp=now_str,
            component=component,
            event_type=event_type,
            message=message,
            details=details or {}
        )
        self._events.append(evt)
        # Cap event history to latest 500 events
        if len(self._events) > 500:
            self._events = self._events[-500:]

    def get_service_status(self, name: str) -> Optional[ServiceStatus]:
        return self._services.get(name)

    def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        return {k: v.to_dict() for k, v in self._services.items()}

    def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._events[-limit:]]

    def _probe_port_http(self, port: int, path: str = "/") -> Tuple[bool, Optional[str]]:
        """Probe local port with lightweight HTTP request."""
        url = f"http://127.0.0.1:{port}{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AGI-1.7-Supervisor-Probe"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if 200 <= resp.status < 400:
                    return True, None
                return False, f"HTTP status {resp.status}"
        except urllib.error.URLError as e:
            return False, str(e.reason)
        except Exception as e:
            return False, str(e)

    def probe_chrome_cdp(self) -> Tuple[bool, Optional[str]]:
        svc = self._services["chrome_cdp_service"]
        svc.last_health_check = datetime.now(timezone.utc).isoformat()
        ok, reason = self._probe_port_http(9229, "/json/version")
        if ok:
            svc.state = ServiceState.RUNNING
            svc.last_heartbeat = datetime.now(timezone.utc).isoformat()
            svc.unhealthy_reason = None
            return True, None
        else:
            if svc.state == ServiceState.RUNNING:
                svc.state = ServiceState.DEGRADED
                svc.unhealthy_reason = f"CDP port 9229 probe failed: {reason}"
            return False, reason

    def probe_dashboard(self) -> Tuple[bool, Optional[str]]:
        svc = self._services["dashboard_service"]
        svc.last_health_check = datetime.now(timezone.utc).isoformat()
        ok, reason = self._probe_port_http(8088, "/health")
        if not ok:
            # Try /api/health
            ok, reason = self._probe_port_http(8088, "/api/health")

        if ok:
            svc.state = ServiceState.RUNNING
            svc.last_heartbeat = datetime.now(timezone.utc).isoformat()
            svc.unhealthy_reason = None
            return True, None
        else:
            if svc.state == ServiceState.RUNNING:
                svc.state = ServiceState.DEGRADED
                svc.unhealthy_reason = f"Dashboard port 8088 probe failed: {reason}"
            return False, reason

    def probe_overlay(self) -> Tuple[bool, Optional[str]]:
        svc = self._services["overlay_service"]
        svc.last_health_check = datetime.now(timezone.utc).isoformat()

        # Check if proc is alive in managed list
        proc = self._managed_procs.get("overlay_service")
        if proc and proc.poll() is None:
            svc.state = ServiceState.RUNNING
            svc.pid = proc.pid
            svc.last_heartbeat = datetime.now(timezone.utc).isoformat()
            svc.unhealthy_reason = None
            return True, None

        # Check if the portfolio sync file has been modified recently (< 60s)
        portfolio_file = self.workspace_dir / "live_triumvirate_portfolio.json"
        if portfolio_file.exists():
            age_s = time.time() - portfolio_file.stat().st_mtime
            if age_s < 120.0:
                svc.state = ServiceState.RUNNING
                svc.is_adopted = True
                svc.last_heartbeat = datetime.now(timezone.utc).isoformat()
                svc.unhealthy_reason = None
                return True, None

        if svc.state == ServiceState.RUNNING:
            svc.state = ServiceState.DEGRADED
            svc.unhealthy_reason = "Overlay daemon process not found and sync file is stale"
        return False, svc.unhealthy_reason

    def reconcile(self) -> Dict[str, Any]:
        """Audit real environment status and adopt already-running healthy services."""
        self._emit_event("SUPERVISOR", "RECONCILE_START", "Reconciling service states with local host...")

        # 1. Chrome CDP
        cdp_ok, cdp_err = self.probe_chrome_cdp()
        cdp_svc = self._services["chrome_cdp_service"]
        if cdp_ok and cdp_svc.pid is None:
            cdp_svc.is_adopted = True
            cdp_svc.start_time = cdp_svc.start_time or datetime.now(timezone.utc).isoformat()
            self._emit_event("chrome_cdp_service", "ADOPTED", "Adopted existing healthy Chrome CDP on port 9229.")

        # 2. Dashboard
        dash_ok, dash_err = self.probe_dashboard()
        dash_svc = self._services["dashboard_service"]
        if dash_ok and dash_svc.pid is None:
            dash_svc.is_adopted = True
            dash_svc.start_time = dash_svc.start_time or datetime.now(timezone.utc).isoformat()
            self._emit_event("dashboard_service", "ADOPTED", "Adopted existing healthy Standalone Dashboard on port 8088.")

        # 3. Overlay
        over_ok, over_err = self.probe_overlay()
        over_svc = self._services["overlay_service"]
        if over_ok and over_svc.is_adopted:
            self._emit_event("overlay_service", "ADOPTED", "Adopted active overlay sync daemon from heartbeat.")

        readiness = self.calculate_readiness()
        self._emit_event("SUPERVISOR", "RECONCILE_COMPLETE", f"Reconciliation complete. Readiness: {readiness.value}")
        return self.get_runtime_telemetry()

    def calculate_readiness(self) -> RuntimeReadiness:
        # Determine market session: after 15:30 IST is AFTER_HOURS
        now_utc = datetime.now(timezone.utc)
        ist_offset = timezone(datetime.now().astimezone().tzinfo.utcoffset(None) or datetime.timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_offset)
        min_of_day = now_ist.hour * 60 + now_ist.minute
        is_after_hours = (min_of_day > 15 * 60 + 35) or (now_ist.weekday() >= 5)

        all_running = all(s.state == ServiceState.RUNNING for s in self._services.values())
        any_running = any(s.state == ServiceState.RUNNING for s in self._services.values())

        if not any_running:
            return RuntimeReadiness.STOPPED

        if all_running:
            if is_after_hours:
                return RuntimeReadiness.AFTER_HOURS_MONITORING
            return RuntimeReadiness.HEALTHY

        return RuntimeReadiness.STARTED

    def start_all_services(self) -> Dict[str, Any]:
        """Starts missing or failed services in exact dependency order. Never duplicates healthy ones."""
        self._emit_event("SUPERVISOR", "START_REQUESTED", "Starting trading runtime in dependency order...")

        # 1. Dashboard first
        dash_ok, _ = self.probe_dashboard()
        if not dash_ok:
            self._launch_service("dashboard_service")
            # Wait up to 5s for dashboard health
            for _ in range(10):
                time.sleep(0.5)
                if self.probe_dashboard()[0]:
                    break
        else:
            self._emit_event("dashboard_service", "REUSED", "Dashboard service already healthy on port 8088; reusing.")

        # 2. Chrome CDP second
        cdp_ok, _ = self.probe_chrome_cdp()
        if not cdp_ok:
            self._launch_service("chrome_cdp_service")
            for _ in range(15):
                time.sleep(0.5)
                if self.probe_chrome_cdp()[0]:
                    break
        else:
            self._emit_event("chrome_cdp_service", "REUSED", "Chrome CDP service already healthy on port 9229; reusing.")

        # 3. Overlay Guardian third
        over_ok, _ = self.probe_overlay()
        if not over_ok:
            self._launch_service("overlay_service")
            time.sleep(1.0)
            self.probe_overlay()
        else:
            self._emit_event("overlay_service", "REUSED", "Overlay guardian service already active; reusing.")

        return self.get_runtime_telemetry()

    def _launch_service(self, name: str) -> bool:
        svc = self._services[name]
        if not svc.launch_command:
            svc.state = ServiceState.FAILED
            svc.unhealthy_reason = "No launch command configured"
            return False

        svc.state = ServiceState.STARTING
        svc.start_time = datetime.now(timezone.utc).isoformat()
        self._emit_event(name, "STARTING", f"Launching command: {svc.launch_command}")

        try:
            # Prohibit shell injection, parse command
            cmd_parts = svc.launch_command.split(" ")
            # If the command has quoted args, handle cleanly
            import shlex
            cmd_parts = shlex.split(svc.launch_command)

            proc = subprocess.Popen(
                cmd_parts,
                cwd=str(self.workspace_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            )
            self._managed_procs[name] = proc
            svc.pid = proc.pid
            svc.state = ServiceState.RUNNING
            svc.is_adopted = False
            self._emit_event(name, "STARTED", f"Launched process with PID {proc.pid}")
            return True
        except Exception as e:
            svc.state = ServiceState.FAILED
            svc.last_error = str(e)
            svc.unhealthy_reason = f"Launch exception: {e}"
            self._emit_event(name, "LAUNCH_FAILED", f"Failed to launch: {e}")
            return False

    def stop_service(self, name: str) -> bool:
        svc = self._services.get(name)
        if not svc:
            return False

        svc.state = ServiceState.STOPPING
        self._emit_event(name, "STOPPING", f"Stopping service {name}...")

        proc = self._managed_procs.get(name)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._managed_procs.pop(name, None)

        svc.state = ServiceState.STOPPED
        svc.pid = None
        self._emit_event(name, "STOPPED", f"Service {name} stopped successfully.")
        return True

    def stop_all_services(self) -> Dict[str, Any]:
        """Gracefully halts all managed services in reverse dependency order."""
        self._emit_event("SUPERVISOR", "STOP_ALL", "Halt requested for all runtime services.")
        self.stop_service("overlay_service")
        self.stop_service("dashboard_service")
        self.stop_service("chrome_cdp_service")
        return self.get_runtime_telemetry()

    def get_runtime_telemetry(self) -> Dict[str, Any]:
        readiness = self.calculate_readiness()
        return {
            "status": "ok",
            "readiness": readiness.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": self.get_all_statuses(),
            "live_order_dispatch": "DISABLED_QUARANTINED",
            "session": {
                "active_epoch": "epoch_10k",
                "mode": "PAPER",
                "market_state": "AFTER_HOURS" if readiness == RuntimeReadiness.AFTER_HOURS_MONITORING else "ACTIVE"
            },
            "recent_events": self.get_events(10)
        }
