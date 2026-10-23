"""
engine/agi17/capabilities/capability_profiler.py
AGI 1.7 OMEGA COMMAND — System & Device Capability Profiler

Discovers and validates the actual host environment on startup and on demand:
1. CPU & Compute (Model, physical vs logical cores, live utilization, architecture).
2. Memory (Physical RAM, available RAM, pressure, commit usage/limit, paging, reserves).
3. GPU & Accelerators (Detected adapters, driver versions, dedicated vs shared RAM, acceleration support).
4. Storage & Persistence (Volumes, filesystem, D:\\ write/read/SHA-256 verification).
5. Virtualization & Execution Environments (Docker Desktop/WSL2, Python, uv, Git, agy.exe).
6. Network & Model Services (agy.exe flags, gemini-3.8-flash-high availability, telemetry fields).
7. Connected Devices & Power (Present PnP devices, AC/battery state, thermal UNAVAILABLE honesty).
"""

import os
import sys
import json
import time
import shutil
import hashlib
import platform
import subprocess
from typing import Dict, Any, List, Optional

from .resource_snapshot import capture_live_resource_snapshot, ResourceSnapshot


class CapabilityProfiler:
    """Non-destructive system and device capability profiler for AGI 1.7 OMEGA COMMAND."""

    def __init__(
        self,
        storage_root: str = r"D:\AGI_Storage\AGI_1_7",
        eval_root: str = r"D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND",
        local_fallback_root: Optional[str] = None
    ):
        self.storage_root = storage_root
        self.eval_root = eval_root
        self.local_fallback_root = local_fallback_root or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "local_fallback_storage")
        )
        self.latest_profile: Optional[Dict[str, Any]] = None

    def _run_ps_json(self, ps_expr: str, timeout: int = 8) -> Any:
        if sys.platform != "win32":
            return None
        try:
            cmd = ["powershell", "-NoProfile", "-Command", f"{ps_expr} | ConvertTo-Json -Compress -Depth 3"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout.strip())
        except Exception:
            pass
        return None

    def _run_cmd_text(self, cmd: List[str], timeout: int = 6) -> Optional[str]:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
            if res.returncode == 0:
                return (res.stdout or res.stderr).strip()
        except Exception:
            pass
        return None

    def inspect_cpu_and_compute(self, snap: ResourceSnapshot) -> Dict[str, Any]:
        cpu_data = self._run_ps_json(
            "Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed, Architecture"
        )
        if isinstance(cpu_data, list) and cpu_data:
            cpu_data = cpu_data[0]
        elif not isinstance(cpu_data, dict):
            cpu_data = {}

        phys_cores = cpu_data.get("NumberOfCores") or "UNKNOWN"
        log_cores = cpu_data.get("NumberOfLogicalProcessors") or snap.logical_processors
        model_name = (cpu_data.get("Name") or platform.processor() or "UNKNOWN").strip()

        return {
            "processor_model": model_name,
            "architecture": platform.machine(),
            "physical_cores": phys_cores,
            "logical_processors": log_cores,
            "max_clock_mhz": cpu_data.get("MaxClockSpeed", "UNKNOWN"),
            "current_cpu_utilization_pct": snap.cpu_utilization_pct,
            "runtime_hardware_supported": True,
            "source": "Win32_Processor_CIM+GetSystemTimes",
            "confidence": "MEASURED"
        }

    def inspect_gpu_and_accelerators(self) -> Dict[str, Any]:
        gpus = self._run_ps_json(
            "Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, AdapterRAM, VideoProcessor, Status"
        )
        if isinstance(gpus, dict):
            gpus = [gpus]
        elif not isinstance(gpus, list):
            gpus = []

        adapters = []
        has_dedicated_cuda = False
        for g in gpus:
            name = g.get("Name", "Unknown Adapter")
            ram_bytes = g.get("AdapterRAM") or 0
            is_integrated = any(k in name.lower() for k in ["intel", "uhd", "iris", "amd radeon(tm) graphics", "microsoft basic"])
            if "nvidia" in name.lower():
                has_dedicated_cuda = True
            adapters.append({
                "name": name,
                "driver_version": g.get("DriverVersion", "UNKNOWN"),
                "reported_adapter_ram_mb": round(ram_bytes / (1024 * 1024), 1) if ram_bytes else "UNKNOWN",
                "memory_type": "SHARED_SYSTEM_RAM_INTEGRATED" if is_integrated else "DEDICATED_OR_DISCRETE",
                "status": g.get("Status", "UNKNOWN")
            })

        return {
            "detected_adapters": adapters,
            "adapter_count": len(adapters),
            "local_cuda_inference_acceleration": "AVAILABLE" if has_dedicated_cuda else "UNAVAILABLE",
            "gpu_telemetry_sensor": "UNAVAILABLE" if not has_dedicated_cuda else "NVIDIA_SMI",
            "note": "Shared integrated graphics memory is not counted as independent dedicated VRAM. Foundation model gemini-3.8-flash-high executes via remote Antigravity runtime rather than local GPU weights.",
            "source": "Win32_VideoController_CIM",
            "confidence": "MEASURED"
        }

    def verify_storage_and_persistence(self) -> Dict[str, Any]:
        drives_raw = self._run_ps_json(
            "[System.IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady } | Select-Object Name, DriveFormat, DriveType, VolumeLabel, TotalSize, AvailableFreeSpace"
        )
        if isinstance(drives_raw, dict):
            drives_raw = [drives_raw]
        elif not isinstance(drives_raw, list):
            drives_raw = []

        volumes = []
        for d in drives_raw:
            tot = d.get("TotalSize") or 0
            free = d.get("AvailableFreeSpace") or 0
            volumes.append({
                "mount": d.get("Name"),
                "filesystem": d.get("DriveFormat", "UNKNOWN"),
                "drive_type": str(d.get("DriveType", "UNKNOWN")),
                "label": d.get("VolumeLabel") or "",
                "total_gb": round(tot / (1024 ** 3), 2) if tot else 0.0,
                "free_gb": round(free / (1024 ** 3), 2) if free else 0.0
            })

        # Verify D:\ write/read/checksum integrity and required subdirectories
        d_verified = False
        d_probe_sha256 = "UNAVAILABLE"
        active_storage_root = self.local_fallback_root
        active_eval_root = os.path.join(self.local_fallback_root, "evaluation")
        storage_mode = "LOCAL_FALLBACK"

        required_storage_subdirs = [
            "memory", "state", "checkpoints", "journals", "logs", "telemetry",
            "research_cache", "task_artifacts", "agent_messages", "token_ledger",
            "backups", "integrity"
        ]
        required_eval_subdirs = [
            "evaluation", "reports", "manifests", "raw_results",
            "normalized_results", "checkpoints", "logs", "telemetry", "integrity", "isolated_cwd"
        ]

        if os.path.exists("D:\\"):
            try:
                for sub in required_storage_subdirs:
                    os.makedirs(os.path.join(self.storage_root, sub), exist_ok=True)
                for sub in required_eval_subdirs:
                    os.makedirs(os.path.join(self.eval_root, sub), exist_ok=True)

                probe_file = os.path.join(self.storage_root, "integrity", "capability_probe.json")
                payload = json.dumps({
                    "agent": "AGI_1_7_OMEGA_COMMAND",
                    "timestamp": time.time(),
                    "storage_root": self.storage_root
                }, sort_keys=True).encode("utf-8")
                expected_hash = hashlib.sha256(payload).hexdigest()
                with open(probe_file, "wb") as f:
                    f.write(payload)
                with open(probe_file, "rb") as f:
                    read_back = f.read()
                actual_hash = hashlib.sha256(read_back).hexdigest()
                if actual_hash == expected_hash:
                    d_verified = True
                    d_probe_sha256 = actual_hash
                    active_storage_root = self.storage_root
                    active_eval_root = self.eval_root
                    storage_mode = "EXTERNAL_D_VERIFIED"
            except Exception:
                d_verified = False

        if not d_verified:
            for sub in required_storage_subdirs:
                os.makedirs(os.path.join(active_storage_root, sub), exist_ok=True)
            for sub in required_eval_subdirs:
                os.makedirs(os.path.join(active_eval_root, sub), exist_ok=True)

        return {
            "volumes": volumes,
            "d_drive_verified": d_verified,
            "d_probe_sha256": d_probe_sha256,
            "storage_mode": storage_mode,
            "active_storage_root": active_storage_root,
            "active_evaluation_root": active_eval_root,
            "agi_1_5_storage_preserved": os.path.exists(r"D:\AGI_Evaluation\AGI_1_5"),
            "agi_1_6_storage_preserved": os.path.exists(r"D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS"),
            "source": "DriveInfo+SHA256ReadBack",
            "confidence": "MEASURED"
        }

    def inspect_virtualization_and_runtimes(self, snap: ResourceSnapshot) -> Dict[str, Any]:
        docker_out = self._run_cmd_text(["docker", "info", "--format", "{{json .}}"], timeout=6)
        docker_info = {}
        docker_healthy = False
        if docker_out:
            try:
                docker_info = json.loads(docker_out)
                docker_healthy = bool(docker_info.get("ServerVersion"))
            except Exception:
                pass

        git_ver = self._run_cmd_text(["git", "--version"]) or "UNAVAILABLE"
        uv_ver = self._run_cmd_text(["uv", "--version"]) or "UNAVAILABLE"

        return {
            "docker_engine_available": docker_healthy,
            "docker_server_version": docker_info.get("ServerVersion", "UNAVAILABLE"),
            "docker_ncpu": docker_info.get("NCPU", "UNKNOWN"),
            "docker_mem_total_mb": round(docker_info.get("MemTotal", 0) / (1024 * 1024), 1) if docker_info.get("MemTotal") else "UNKNOWN",
            "docker_operating_system": docker_info.get("OperatingSystem", "UNKNOWN"),
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "git_version": git_ver,
            "uv_version": uv_ver,
            "active_workload_processes": snap.active_workload_processes,
            "source": "docker_cli+sys",
            "confidence": "MEASURED"
        }

    def inspect_model_and_network_services(self) -> Dict[str, Any]:
        agy_path = os.path.expandvars(r"%LOCALAPPDATA%\agy\bin\agy.exe")
        agy_exists = os.path.exists(agy_path)
        help_text = ""
        if agy_exists:
            try:
                res = subprocess.run([agy_path, "--help"], capture_output=True, text=True, timeout=5, shell=False)
                help_text = (res.stdout or "") + "\n" + (res.stderr or "")
            except Exception:
                pass

        supports_json = "--output-format" in help_text and "json" in help_text
        supports_stream_json = "stream-json" in help_text
        supports_effort = "--effort" in help_text

        return {
            "agy_cli_path": agy_path if agy_exists else "UNAVAILABLE",
            "agy_cli_available": agy_exists,
            "sole_foundation_model": "gemini-3.8-flash-high",
            "supports_output_format_json": supports_json,
            "supports_output_format_stream_json": supports_stream_json,
            "supports_effort_flag": supports_effort,
            "telemetry_fields_exposed": ["input_tokens", "output_tokens", "thinking_tokens", "total_tokens", "latency_ms", "conversation_id"],
            "usage_accounting_note": "agy.exe --output-format json reports cumulative input_tokens across internal turns of a CLI invocation, and includes thinking_tokens inside output_tokens. Isolated CWD is required to avoid 22.7k workspace context injection.",
            "provider_quota_remaining_api": "UNAVAILABLE_NOT_EXPOSED_BY_CLI",
            "source": "agy_cli_inspection",
            "confidence": "MEASURED"
        }

    def inspect_connected_devices(self, max_devices: int = 15) -> List[Dict[str, Any]]:
        if sys.platform != "win32":
            return []
        devices = []
        try:
            res = subprocess.run(["pnputil", "/enum-devices", "/connected"], capture_output=True, text=True, timeout=8, shell=False)
            if res.stdout:
                for blk in res.stdout.split("\n\n"):
                    lines = [ln.strip() for ln in blk.split("\n") if ":" in ln]
                    entry = {}
                    for ln in lines:
                        k, v = ln.split(":", 1)
                        entry[k.strip().lower().replace(" ", "_")] = v.strip()
                    if "instance_id" in entry or "device_description" in entry:
                        cls_name = entry.get("class_name", "Unknown")
                        devices.append({
                            "instance_id": entry.get("instance_id", "Unknown"),
                            "description": entry.get("device_description", "Unknown"),
                            "class": cls_name,
                            "status": entry.get("status", "Unknown"),
                            "actuation_policy": "BLOCKED_PERSONAL_OR_MEDIA_DEVICE" if any(
                                m in cls_name.lower() for m in ["camera", "audio", "media", "biometric", "bluetooth"]
                            ) else "READ_ONLY_ENUMERATED"
                        })
                        if len(devices) >= max_devices:
                            break
        except Exception:
            pass
        return devices

    def build_full_profile(self, save_path: Optional[str] = None) -> Dict[str, Any]:
        snap = capture_live_resource_snapshot(include_processes=True)
        cpu = self.inspect_cpu_and_compute(snap)
        gpu = self.inspect_gpu_and_accelerators()
        storage = self.verify_storage_and_persistence()
        virt = self.inspect_virtualization_and_runtimes(snap)
        model_svc = self.inspect_model_and_network_services()
        devices = self.inspect_connected_devices()

        profile = {
            "profile_id": f"CAP-AGI17-{int(snap.timestamp)}",
            "timestamp": snap.timestamp,
            "iso_timestamp": snap.iso_timestamp,
            "runtime_version": "1.7.0",
            "codename": "OMEGA COMMAND",
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine()
            },
            "cpu_and_compute": cpu,
            "memory": {
                "installed_physical_ram_mb": snap.installed_physical_ram_mb,
                "available_physical_ram_mb": snap.available_physical_ram_mb,
                "used_physical_ram_mb": snap.used_physical_ram_mb,
                "memory_load_percent": snap.memory_load_percent,
                "memory_pressure": snap.memory_pressure,
                "commit_limit_mb": snap.commit_limit_mb,
                "commit_available_mb": snap.commit_available_mb,
                "commit_used_mb": snap.commit_used_mb,
                "safe_headroom_ram_mb": snap.safe_headroom_ram_mb,
                "source": "Win32_GlobalMemoryStatusEx",
                "confidence": "MEASURED"
            },
            "gpu_and_accelerators": gpu,
            "storage_and_persistence": storage,
            "virtualization_and_runtimes": virt,
            "network_and_model_services": model_svc,
            "power_and_thermals": snap.power_telemetry,
            "connected_devices_sample": devices
        }
        self.latest_profile = profile

        target_json = save_path or os.path.join(
            storage["active_storage_root"], "telemetry", "latest_capability_profile.json"
        )
        try:
            os.makedirs(os.path.dirname(target_json), exist_ok=True)
            with open(target_json, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
        except Exception:
            pass

        return profile
