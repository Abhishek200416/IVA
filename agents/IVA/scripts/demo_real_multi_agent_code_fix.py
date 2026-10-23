"""AGI 1.7 Live Multi-Agent Collaboration & Self-Healing Code-Test-Fix-Verify Demo.

Demonstrates end-to-end, verifiable model-driven work across 4 distinct specialists:
1. `plan_systems_architect` (Live `gemini-3.8-flash-high` via `ModelAdapter.invoke()`):
   Produces the edge-case specification for `interval_merger.py` with Ponytail & Sequential-Thinking railings.
2. `swe_python_runtime_engineer` (Live `gemini-3.8-flash-high` via `ModelAdapter.invoke()`):
   Receives upstream architect spec via `context["upstream_outputs"]` and generates `interval_merger.py` from scratch.
   (Deterministic fallback is retained only for CLI outages and explicitly reported via `fallback_used`).
3. `qa_unit_suite_runner` (Live `gemini-3.8-flash-high` via `ModelAdapter.invoke()` + `ProcessSupervisor.run_supervised()`):
   Generates `test_interval_merger.py` from scratch, injects a documented boundary defect (`<=` -> `<`) to trigger a real
   test failure (`exit_code = 1`), captures `stderr` traceback, and triggers SQLite state transition
   `RUNNING -> VERIFYING -> FAILED -> QUEUED -> READY -> RUNNING`.
4. `swe_patch_minimizer` (Live `gemini-3.8-flash-high` via `ModelAdapter.invoke()`):
   Receives the broken `interval_merger.py` + exact `unittest` traceback, synthesizes the root-cause patch,
   updates `interval_merger.py`, and re-runs `qa_unit_suite_runner` (`VERIFY-ATT2` -> `exit_code = 0`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.AGI_1_7.engine.agi17.adapters.agi_17_adapter import AGI17Adapter
from agents.AGI_1_7.engine.agi17.process_supervision.sandbox_runner import (
    DisposableSandboxRunner,
    HighImpactApprovalGate,
    SandboxPolicy,
)


FALLBACK_MODULE_CODE = '''"""Deterministic fallback implementation for interval_merger.py (used ONLY if CLI fails)."""
from typing import List, Tuple


def merge_overlapping_intervals(intervals: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not intervals:
        return []
    for start, end in intervals:
        if start > end:
            raise ValueError(f"Invalid inverted interval: ({start}, {end})")
    sorted_intervals = sorted(intervals, key=lambda x: (x[0], x[1]))
    merged: List[Tuple[int, int]] = [sorted_intervals[0]]
    for current_start, current_end in sorted_intervals[1:]:
        last_start, last_end = merged[-1]
        if current_start <= last_end:
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            merged.append((current_start, current_end))
    return merged
'''

FALLBACK_TEST_CODE = '''"""Deterministic fallback unittest suite for interval_merger.py (used ONLY if CLI fails)."""
import unittest
from interval_merger import merge_overlapping_intervals


class TestIntervalMerger(unittest.TestCase):
    def test_01_unsorted_overlapping_intervals(self) -> None:
        self.assertEqual(
            merge_overlapping_intervals([(8, 10), (1, 3), (2, 6), (15, 18)]),
            [(1, 6), (8, 10), (15, 18)],
        )

    def test_02_touching_boundary_intervals(self) -> None:
        self.assertEqual(
            merge_overlapping_intervals([(1, 3), (3, 5), (7, 9)]),
            [(1, 5), (7, 9)],
        )

    def test_03_negative_and_nested_intervals(self) -> None:
        self.assertEqual(
            merge_overlapping_intervals([(-10, -2), (-6, -3), (-2, 4)]),
            [(-10, 4)],
        )

    def test_04_inverted_interval_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            merge_overlapping_intervals([(1, 4), (6, 2)])


if __name__ == "__main__":
    unittest.main()
'''


def _get_agy_cli_version(agy_path: Path) -> str:
    try:
        res = subprocess.run([str(agy_path), "--version"], capture_output=True, text=True, timeout=10)
        return res.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main() -> int:
    demo_root = REPO_ROOT / "agents" / "AGI_1_7" / "demo_workspace"
    demo_code_dir = demo_root / "src"
    demo_storage = demo_root / "runtime_storage"
    demo_eval = demo_root / "eval_env"

    if demo_root.exists():
        shutil.rmtree(demo_root, ignore_errors=True)
    demo_code_dir.mkdir(parents=True, exist_ok=True)

    explicit_dev_sandbox = "--dev-sandbox" in sys.argv
    demo_policy = SandboxPolicy.development() if explicit_dev_sandbox else SandboxPolicy.production()
    demo_gate = HighImpactApprovalGate(approval_callback=lambda _desc, _cat: True, block_workspace_mutations=False)

    adapter = AGI17Adapter(
        storage_root=demo_storage,
        eval_root=demo_eval,
        sandbox_policy=demo_policy,
        approval_gate=demo_gate,
    )
    mission_id = "MISSION-LIVE-CODE-FIX-001"
    prompt = (
        "Implement `merge_overlapping_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]` "
        "in `interval_merger.py` that: (1) returns `[]` for empty input, (2) validates every `(start, end)` and "
        "raises `ValueError` if `start > end`, (3) sorts intervals by `(start, end)`, and (4) merges both overlapping "
        "and touching closed intervals (`current_start <= last_end`, e.g., `[(1, 3), (3, 5)] -> [(1, 5)]`)."
    )

    subtasks = adapter.build_code_and_test_subtasks(
        title="Multi-Agent Interval Merger Live Code, Test, Fault Injection & Self-Healing Repair",
        prompt=prompt,
        code_task_dir=demo_code_dir,
        module_filename="interval_merger.py",
        test_filename="test_interval_merger.py",
        inject_deliberate_test_failure=True,
        fallback_module_code=FALLBACK_MODULE_CODE,
        fallback_test_code=FALLBACK_TEST_CODE,
    )

    print(f"[DEMO] Launching 4-Call Live Model Multi-Agent Mission: {mission_id} (sandbox_mode={demo_policy.isolation_mode})")
    result = adapter.execute_mission(
        title="Multi-Agent Interval Merger Specification, Implementation, Test Failure Detection & Self-Healing Patch",
        prompt=prompt,
        task_id=mission_id,
        subtasks=subtasks,
        force_hierarchical=True,
        use_live_model=True,
    )

    events_file = demo_storage / "journals" / "task_events.jsonl"
    events = [
        json.loads(line)
        for line in events_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if events_file.exists() else []

    ledger_file = demo_storage / "token_ledger" / "token_usage_ledger.jsonl"
    token_records = [
        json.loads(line)
        for line in ledger_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if ledger_file.exists() else []

    total_in = sum(int(r.get("input_tokens", 0)) for r in token_records)
    total_out = sum(int(r.get("output_tokens", 0)) for r in token_records)
    total_think = sum(int(r.get("thinking_tokens", 0)) for r in token_records)
    total_tok = sum(int(r.get("total_tokens", 0)) for r in token_records)

    any_fallback = bool(result.get("fallback_summary", {}).get("any_fallback_used"))
    report_payload: Dict[str, Any] = {
        "mission_id": mission_id,
        "final_state": result["final_state"],
        "terminal_outcome": result.get("terminal_outcome"),
        "duration_sec": result["duration_sec"],
        "sandbox_isolation_mode": demo_policy.isolation_mode,
        "cli_and_model_metadata": {
            "cli_binary": str(adapter.model_adapter.agy_path),
            "cli_version": _get_agy_cli_version(adapter.model_adapter.agy_path),
            "model_identifier": adapter.model_adapter.SOLE_MODEL,
            "effort_level": "high",
        },
        "fallback_summary": result.get("fallback_summary", {}),
        "ecosystem_coordination_summary": result.get("ecosystem_coordination_summary", {}),
        "token_and_cost_summary": {
            "live_model_calls_count": 0 if any_fallback else len(token_records),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_thinking_tokens": total_think,
            "total_tokens": total_tok,
            "estimated_cost_usd_flash_pricing": round((total_in * 0.15 + total_out * 0.60) / 1_000_000, 6),
            "token_records": token_records,
        },
        "orchestration_result": result,
        "sqlite_event_journal": events,
    }

    if any_fallback or result.get("final_state") != "SUCCEEDED":
        report_path = demo_root / "DEMO_FALLBACK_EXECUTION_LOG.json"
    else:
        report_path = REPO_ROOT / "agents" / "AGI_1_7" / "reports" / "LIVE_MULTI_AGENT_EXECUTION_LOG.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, indent=2, default=str), encoding="utf-8")

    print(
        json.dumps(
            {
                "mission_id": mission_id,
                "final_state": result["final_state"],
                "terminal_outcome": result.get("terminal_outcome"),
                "sandbox_isolation_mode": demo_policy.isolation_mode,
                "duration_sec": result["duration_sec"],
                "live_model_calls_count": 0 if any_fallback else len(token_records),
                "total_tokens": total_tok,
                "any_fallback_used": any_fallback,
                "fallback_count": result.get("fallback_summary", {}).get("fallback_count"),
                "report_saved": str(report_path),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if result["final_state"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
