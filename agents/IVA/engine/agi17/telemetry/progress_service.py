"""AGI 1.7 Live Progress Service & Ledger-Driven Dashboard Generator.

Computes all task counts, token metrics, resource snapshots, and benchmark
reconciliations strictly from the live SQLite TaskStore and JSONL ledgers.
Zero hardcoded metrics or fabricated benchmark results.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..capabilities.resource_snapshot import ResourceSnapshot
from ..task_control.task_store import TaskStore
from .token_economy import AdaptiveTokenController


class ProgressService:
    """Generates live telemetry snapshots and HTML dashboards directly from authoritative ledgers."""

    def __init__(
        self,
        task_store: TaskStore,
        token_controller: AdaptiveTokenController,
        output_dir: str | Path = r"D:\AGI_Storage\AGI_1_7\telemetry",
    ) -> None:
        self.task_store = task_store
        self.token_controller = token_controller
        self.output_dir = Path(output_dir)
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.output_dir = Path(__file__).resolve().parents[3] / "state_fallback" / "telemetry"
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_live_telemetry(self, extra_benchmarks: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        tasks = self.task_store.list_tasks()
        counts_by_state = self.task_store.count_by_state()
        token_summary = self.token_controller.get_summary()
        resource_snap = ResourceSnapshot.capture().to_dict()

        active_children = [
            {
                "task_id": t["task_id"],
                "parent_task_id": t["parent_task_id"],
                "title": t["title"],
                "state": t["state"],
                "specialist_role": t["specialist_role"],
                "worker_pid": t["worker_pid"],
                "updated_at": t["updated_at"],
            }
            for t in tasks
            if t["parent_task_id"] is not None
        ]

        payload = {
            "schema_version": "1.7.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "generated_at_epoch": time.time(),
            "source_of_truth": {
                "task_store_db": str(self.task_store.db_path),
                "task_events_jsonl": str(self.task_store.events_jsonl_path),
                "token_ledger_jsonl": str(self.token_controller.ledger_file),
            },
            "task_counts": {
                "total_tasks": len(tasks),
                "by_state": counts_by_state,
                "logical_child_tasks": len(active_children),
            },
            "active_and_recent_children": active_children[:50],
            "token_telemetry": token_summary,
            "resource_snapshot": resource_snap,
            "benchmarks": extra_benchmarks or {},
        }

        json_path = self.output_dir / "live_telemetry.json"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def render_html_dashboard(
        self,
        html_path: Optional[str | Path] = None,
        extra_benchmarks: Optional[Dict[str, Any]] = None,
    ) -> Path:
        data = self.build_live_telemetry(extra_benchmarks=extra_benchmarks)
        target = Path(html_path) if html_path else (self.output_dir / "omega_command_dashboard.html")
        target.parent.mkdir(parents=True, exist_ok=True)

        counts = data["task_counts"]["by_state"]
        tok = data["token_telemetry"]
        res = data["resource_snapshot"]

        state_rows = "".join(
            f"<tr><td><code>{state}</code></td><td>{cnt}</td></tr>"
            for state, cnt in sorted(counts.items())
        ) or "<tr><td colspan='2'>No tasks recorded yet</td></tr>"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>AGI 1.7 — OMEGA COMMAND Live Telemetry</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; margin: 2rem; }}
    h1, h2 {{ color: #38bdf8; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.25rem; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.25rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; }}
    th, td {{ text-align: left; padding: 0.45rem; border-bottom: 1px solid #334155; }}
    code {{ color: #f8fafc; background: #0f172a; padding: 0.15rem 0.35rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>AGI 1.7.0 — OMEGA COMMAND Live Ledger Dashboard</h1>
  <p>Generated at: <code>{data["generated_at_utc"]}</code> | Task DB: <code>{data["source_of_truth"]["task_store_db"]}</code></p>
  <div class="grid">
    <div class="card">
      <h2>Task Control Plane ({data["task_counts"]["total_tasks"]} total)</h2>
      <table>
        <thead><tr><th>State</th><th>Count</th></tr></thead>
        <tbody>{state_rows}</tbody>
      </table>
    </div>
    <div class="card">
      <h2>Enforced Token Ledger</h2>
      <table>
        <tbody>
          <tr><th>Total Tokens</th><td>{tok["total_tokens"]}</td></tr>
          <tr><th>Input Tokens</th><td>{tok["input_tokens"]}</td></tr>
          <tr><th>Output Tokens</th><td>{tok["output_tokens"]}</td></tr>
          <tr><th>Thinking Tokens</th><td>{tok["thinking_tokens"]}</td></tr>
          <tr><th>Provider Reported</th><td>{tok["tokens_by_accounting_mode"].get("PROVIDER_REPORTED", 0)}</td></tr>
          <tr><th>Local Estimate</th><td>{tok["tokens_by_accounting_mode"].get("LOCAL_ESTIMATE", 0)}</td></tr>
          <tr><th>Isolated CWD Calls</th><td>{tok["isolated_cwd_calls"]}</td></tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>Live Host Resource Snapshot</h2>
      <table>
        <tbody>
          <tr><th>CPU Load</th><td>{res["cpu_percent"]}%</td></tr>
          <tr><th>Available Physical RAM</th><td>{res["avail_phys_mb"]} MB / {res["total_phys_mb"]} MB</td></tr>
          <tr><th>Available Commit</th><td>{res["avail_pagefile_mb"]} MB / {res["total_pagefile_mb"]} MB</td></tr>
          <tr><th>Free Disk C:\\ / D:\\</th><td>{res["c_drive_free_gb"]} GB / {res["d_drive_free_gb"]} GB</td></tr>
          <tr><th>Active agy.exe Workers</th><td>{res["active_agy_processes"]}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""
        target.write_text(html, encoding="utf-8")
        return target
