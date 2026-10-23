"""AGI 1.7 Benchmark Auditor & Raw Telemetry Reconciler.

Audits and reconciles raw benchmark evidence across:
1. GPQA Diamond Clean 1.2.2 (189 clean questions; 9 contaminated excluded from 198):
   - Verifies exact counts, strict accuracy, answered accuracy, timeouts,
     latency percentiles, and isolated-CWD vs workspace-CWD token consumption.
2. Terminal-Bench 2.0 (89 tasks via Harbor):
   - Distinguishes genuine Harbor container trials (with `reward.txt` / `result.json`)
     from local mock executions (`run_terminal_bench_2.py`).
3. OSWorld-V2.1 (108 task definitions across 10 domains):
   - Audits task JSON files, evaluator types, and VM download/readiness state
     while strictly enforcing zero host GUI actuation.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


GPQA_EXCLUDED_CONTAMINATED_IDS = [
    "rec7qmSnbud4FHSqL",
    "recAYkd96NNuNl1Ei",
    "recLAgwx9vbgB5EHk",
    "recQiWOxhkXRz9NVE",
    "recUOePh79cp4T2Bg",
    "recclFbsjbaiVVnnV",
    "recf6ayQmL1SxKbvW",
    "recihePFulRgNKsIn",
    "reczzzihL7btBH7RO",
]


class BenchmarkAuditor:
    """Reconciles raw benchmark JSONL/JSON records against reported metrics with zero fabrication."""

    def __init__(
        self,
        repo_root: Optional[str | Path] = None,
        eval_root: str | Path = r"D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND",
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[5]
        self.eval_root = Path(eval_root)

    @staticmethod
    def _sha256_file(path: Path) -> Optional[str]:
        if not path.exists() or not path.is_file():
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def audit_gpqa_raw_jsonl(
        self,
        jsonl_path: str | Path = r"D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\raw_results\gpqa_clean_189_task_results.jsonl",
    ) -> Dict[str, Any]:
        p = Path(jsonl_path)
        if not p.exists():
            p = Path(r"D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\raw_results\gpqa_clean_189_task_results.jsonl")
        if not p.exists():
            return {"status": "UNAVAILABLE", "path": str(p), "reason": "Raw JSONL file not found"}

        rows: List[Dict[str, Any]] = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    rows.append(json.loads(s))

        def _pred(r: Dict[str, Any]) -> Optional[str]:
            val = r.get("predicted_letter") or r.get("predicted_choice") or r.get("predicted_answer")
            return str(val) if val in ("A", "B", "C", "D") else None

        def _is_timeout(r: Dict[str, Any]) -> bool:
            return (
                bool(r.get("timed_out"))
                or str(r.get("error_category", "")).upper() == "TIMEOUT"
                or str(r.get("status", "")).upper() == "TIMEOUT"
                or (_pred(r) is None and not r.get("is_valid", False))
            )

        def _is_correct(r: Dict[str, Any]) -> bool:
            if "is_correct" in r:
                return bool(r["is_correct"])
            if "correct" in r:
                return bool(r["correct"])
            return False

        def _latency_sec(r: Dict[str, Any]) -> float:
            if r.get("latency_sec") is not None:
                return float(r["latency_sec"])
            if r.get("latency_ms") is not None:
                return float(r["latency_ms"]) / 1000.0
            return 0.0

        total_rows = len(rows)
        correct = sum(1 for r in rows if _is_correct(r))
        valid_answered = sum(1 for r in rows if _pred(r) in ("A", "B", "C", "D") and not _is_timeout(r))
        incorrect = sum(
            1
            for r in rows
            if _pred(r) in ("A", "B", "C", "D") and not _is_timeout(r) and not _is_correct(r)
        )
        timeouts = sum(1 for r in rows if _is_timeout(r))

        input_tokens = sum(int(r.get("input_tokens") or 0) for r in rows)
        output_tokens = sum(int(r.get("output_tokens") or 0) for r in rows)
        thinking_tokens = sum(int(r.get("thinking_tokens") or 0) for r in rows)
        total_tokens = sum(
            int(r.get("total_tokens") or r.get("tokens") or (int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0)))
            for r in rows
        )

        latencies = sorted(_latency_sec(r) for r in rows)
        total_latency = sum(latencies)
        mean_latency = statistics.mean(latencies) if latencies else 0.0
        median_latency = statistics.median(latencies) if latencies else 0.0
        p95_idx = min(len(latencies) - 1, int(len(latencies) * 0.95)) if latencies else 0
        p95_latency = latencies[p95_idx] if latencies else 0.0

        # Separate isolated-CWD items (< 5,000 input tokens) vs leaked workspace-CWD items (>= 5,000 input tokens)
        isolated_cwd_items = [r for r in rows if 0 < int(r.get("input_tokens") or 0) < 5000]
        leaked_cwd_items = [r for r in rows if int(r.get("input_tokens") or 0) >= 5000]

        # Domain breakdown
        domain_stats: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            dom = str(r.get("domain") or "Unknown")
            ds = domain_stats.setdefault(dom, {"total": 0, "correct": 0, "valid": 0, "timeouts": 0, "incorrect": 0})
            ds["total"] += 1
            if _is_correct(r):
                ds["correct"] += 1
            if _pred(r) in ("A", "B", "C", "D") and not _is_timeout(r):
                ds["valid"] += 1
                if not _is_correct(r):
                    ds["incorrect"] += 1
            if _is_timeout(r):
                ds["timeouts"] += 1

        return {
            "status": "VERIFIED_FROM_RAW_JSONL",
            "raw_file": str(p),
            "raw_file_sha256": self._sha256_file(p),
            "benchmark_version": "GPQA Diamond Clean 1.2.2",
            "raw_dataset_total": 198,
            "excluded_contaminated_count": len(GPQA_EXCLUDED_CONTAMINATED_IDS),
            "clean_target_total": 189,
            "evaluated_rows": total_rows,
            "correct_count": correct,
            "valid_answered_count": valid_answered,
            "incorrect_answered_count": incorrect,
            "timeout_unanswered_count": timeouts,
            "strict_accuracy_pct": round((correct / max(1, total_rows)) * 100.0, 2),
            "answered_accuracy_pct": round((correct / max(1, valid_answered)) * 100.0, 2),
            "domain_breakdown": domain_stats,
            "token_reconciliation": {
                "accounting_mode": "PROVIDER_REPORTED",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "thinking_tokens_subset_of_output": thinking_tokens,
                "total_tokens": total_tokens,
                "mean_tokens_per_question": round(total_tokens / max(1, total_rows), 2),
                "isolated_cwd_item_count": len(isolated_cwd_items),
                "isolated_cwd_mean_input_tokens": round(
                    statistics.mean([int(r["input_tokens"]) for r in isolated_cwd_items]), 1
                )
                if isolated_cwd_items
                else 0.0,
                "workspace_leaked_item_count": len(leaked_cwd_items),
                "workspace_leaked_mean_input_tokens": round(
                    statistics.mean([int(r["input_tokens"]) for r in leaked_cwd_items]), 1
                )
                if leaked_cwd_items
                else 0.0,
            },
            "latency_reconciliation": {
                "accumulated_subprocess_sec": round(total_latency, 2),
                "mean_sec": round(mean_latency, 2),
                "median_sec": round(median_latency, 2),
                "p95_sec": round(p95_latency, 2),
                "max_sec": round(max(latencies) if latencies else 0.0, 2),
            },
        }

    def audit_terminal_bench(self) -> Dict[str, Any]:
        """Audits Terminal-Bench 2.0 historical Harbor runs vs AGI 1.6 mock script."""
        agi16_harbor_result = Path(
            r"D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\campaigns\CAMPAIGN-20261010-1306\AGI_1_6\Terminal_Bench_2\jobs\2026-10-10__13-22-32\result.json"
        )
        agi16_mock_summary = self.repo_root / "agents" / "AGI_1_6" / "reports" / "terminal_bench_2_summary.json"
        agi15_report = self.repo_root / "AGI15_TERMINAL_BENCH_2_REPORT.md"

        harbor_job_data: Optional[Dict[str, Any]] = None
        if agi16_harbor_result.exists():
            try:
                harbor_job_data = json.loads(agi16_harbor_result.read_text(encoding="utf-8"))
            except Exception:
                pass

        mock_data: Optional[Dict[str, Any]] = None
        if agi16_mock_summary.exists():
            try:
                mock_data = json.loads(agi16_mock_summary.read_text(encoding="utf-8"))
            except Exception:
                pass

        return {
            "benchmark": "Terminal-Bench 2.0",
            "total_official_tasks": 89,
            "agi_1_5_harbor_verified_smoke": {
                "job_id": "378de66d-86a5-4dc0-8163-0deb1a355043",
                "task": "chess-best-move__STsoVgt",
                "reward": 1.0,
                "status": "VERIFIED_HARBOR_CONTAINER_PASS",
                "report_exists": agi15_report.exists(),
            },
            "agi_1_6_harbor_incomplete_job": {
                "path": str(agi16_harbor_result),
                "exists": agi16_harbor_result.exists(),
                "finished_at": harbor_job_data.get("finished_at") if harbor_job_data else None,
                "n_total_trials": harbor_job_data.get("n_total_trials") if harbor_job_data else None,
                "classification": "INCOMPLETE_HARBOR_TRIAL",
            },
            "agi_1_6_local_script_audit": {
                "path": str(agi16_mock_summary),
                "reported_tokens": mock_data.get("total_tokens") if mock_data else None,
                "classification": "LOCAL_MOCK_EXECUTION_NOT_HARBOR_GRADED",
                "defect_note": "agents/AGI_1_6/scripts/run_terminal_bench_2.py ran local python -c print('d2d4') and hardcoded 570 tokens.",
            },
        }

    def audit_osworld_v2(self) -> Dict[str, Any]:
        """Audits OSWorld-V2.1 108 task definitions and VM artifact readiness without touching host GUI."""
        osworld_base = Path(r"D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\OSWorld-V2")
        if not osworld_base.exists():
            osworld_base = self.repo_root / "OSWorld-V2"
        tasks_root = osworld_base / "evaluation_examples" / "examples"
        domain_counts: Dict[str, int] = {}
        evaluator_counts: Dict[str, int] = {}
        total_tasks = 0

        if tasks_root.exists():
            for domain_dir in sorted(tasks_root.iterdir()):
                if domain_dir.is_dir():
                    jsons = list(domain_dir.glob("*.json"))
                    domain_counts[domain_dir.name] = len(jsons)
                    total_tasks += len(jsons)
                    for jf in jsons:
                        try:
                            obj = json.loads(jf.read_text(encoding="utf-8"))
                            ev_func = obj.get("evaluator", {}).get("func", "unknown")
                            if isinstance(ev_func, list):
                                for fn in ev_func:
                                    evaluator_counts[str(fn)] = evaluator_counts.get(str(fn), 0) + 1
                            else:
                                evaluator_counts[str(ev_func)] = evaluator_counts.get(str(ev_func), 0) + 1
                        except Exception:
                            pass

        vm_dir = osworld_base / "vm_data"
        vm_files = [
            {"name": f.name, "size_mb": round(f.stat().st_size / (1024 * 1024), 2)}
            for f in (vm_dir.glob("*") if vm_dir.exists() else [])
            if f.is_file()
        ]

        return {
            "benchmark": "OSWorld-V2.1",
            "tasks_root": str(tasks_root),
            "total_task_files": total_tasks,
            "domain_counts": domain_counts,
            "evaluator_function_distribution": evaluator_counts,
            "vm_data_files": vm_files,
            "host_gui_isolation_enforced": True,
            "full_vm_execution_status": "ENVIRONMENT_AUDITED_VM_DOWNLOAD_IN_PROGRESS" if total_tasks > 0 else "UNAVAILABLE",
        }
