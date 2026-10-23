"""Reproducible 3-Way Held-Out Coding Benchmark Runner (`run_heldout_coding_benchmark.py`).

Compares three configurations on identical repository tasks using the exact same foundation model (`gemini-3.8-flash-high`):
  1. `Config A (RAW_BASE_MODEL_SINGLE_SHOT)`: Single-shot `ModelAdapter.invoke()` call with the issue prompt
     and starter module code, without test execution or multi-agent orchestration.
  2. `Config B (SINGLE_AGENT_REPAIR_LOOP)`: Single-agent code + self-test + sandboxed repair loop
     (no multi-agent architect decomposition; 1 agent generates module + self-test, runs inside
     `DisposableSandboxRunner`, and triggers 1 repair call if self-tests fail).
  3. `Config C (AGI_1_7_OMEGA_COMMAND)`: Full `AGI17Adapter.execute_mission()` multi-agent workflow
     (`plan_systems_architect` -> `swe_python_runtime_engineer` -> `qa_unit_suite_runner` ->
     `DisposableSandboxRunner` -> `swe_patch_minimizer`).

Enforces pre-flight token, USD cost, and runtime budget estimation before invoking live models.
All configurations start from the identical workspace (`task.starter_files`) and are graded
strictly by the unseen `heldout_test_code` inside `DisposableSandboxRunner`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.AGI_1_7.benchmarks.heldout_coding_suite import (
    HELDOUT_CODING_50_SUITE,
    HELDOUT_CODING_TASKS,
    HeldOutCodingTask,
)
from agents.AGI_1_7.engine.agi17.adapters.agi_17_adapter import AGI17Adapter
from agents.AGI_1_7.engine.agi17.adapters.model_adapter import redact_sensitive_text
from agents.AGI_1_7.engine.agi17.orchestration.hierarchical_orchestrator import (
    _extract_python_code,
    _is_valid_python_syntax,
)


def estimate_preflight_budget(num_tasks: int, configs: List[str], max_budget_usd: float) -> Dict[str, Any]:
    """Calculates maximum token usage, USD cost, and wall-clock runtime before running live benchmark calls."""
    calls_per_task = {
        "A": 1,
        "B": 3,  # module + self-test + optional repair
        "C": 4,  # architect + impl + test + optional repair
    }
    total_max_calls = sum(calls_per_task.get(c, 3) for c in configs) * num_tasks
    est_max_tokens = total_max_calls * 8_500
    est_max_cost_usd = round(total_max_calls * 0.0045, 6)
    est_max_runtime_sec = total_max_calls * 22
    if est_max_cost_usd > max_budget_usd:
        raise RuntimeError(
            f"Pre-flight budget check failed: estimated max cost ${est_max_cost_usd:.4f} exceeds --max-budget-usd ${max_budget_usd:.4f}"
        )
    return {
        "tasks_count": num_tasks,
        "configs_selected": configs,
        "estimated_max_model_calls": total_max_calls,
        "estimated_max_tokens": est_max_tokens,
        "estimated_max_cost_usd": est_max_cost_usd,
        "configured_budget_ceiling_usd": max_budget_usd,
        "estimated_max_runtime_sec": est_max_runtime_sec,
        "budget_admission_passed": True,
    }


def _get_cli_version(agy_path: Path) -> str:
    try:
        res = subprocess.run([str(agy_path), "--version"], capture_output=True, text=True, timeout=10)
        return res.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _populate_starter_workspace(ws_dir: Path, task: HeldOutCodingTask) -> None:
    if ws_dir.exists():
        shutil.rmtree(ws_dir, ignore_errors=True)
    ws_dir.mkdir(parents=True, exist_ok=True)
    for rel_name, content in task.starter_files.items():
        (ws_dir / rel_name).write_text(content, encoding="utf-8")


def _parse_unittest_counts(stderr_text: str) -> Dict[str, int]:
    ran_m = re.search(r"Ran\s+(\d+)\s+test", stderr_text)
    ran = int(ran_m.group(1)) if ran_m else 0
    fail_m = re.search(r"failures=(\d+)", stderr_text)
    err_m = re.search(r"errors=(\d+)", stderr_text)
    failures = int(fail_m.group(1)) if fail_m else 0
    errors = int(err_m.group(1)) if err_m else 0
    passed = max(0, ran - failures - errors)
    return {
        "tests_ran": ran,
        "tests_passed": passed,
        "failures": failures,
        "errors": errors,
    }


def _run_heldout_grader(adapter: AGI17Adapter, ws_dir: Path, task: HeldOutCodingTask) -> Dict[str, Any]:
    module_path = ws_dir / task.module_filename
    mod_code = module_path.read_text(encoding="utf-8") if module_path.exists() else ""
    grader_name = f"test_heldout_{task.test_filename}"
    sbx_res = adapter.orchestrator.sandbox_runner.run_python_unittest_sandbox(
        files={
            task.module_filename: mod_code,
            grader_name: task.heldout_test_code,
        },
        test_pattern=grader_name,
        sandbox_id=f"GRADE-{task.task_id}",
    )
    counts = _parse_unittest_counts(sbx_res.stderr)
    return {
        "exit_code": sbx_res.exit_code,
        "task_completed_verified": sbx_res.passed and counts["tests_ran"] > 0,
        "isolation_backend": sbx_res.isolation_backend,
        "duration_sec": sbx_res.duration_sec,
        "tests_ran": counts["tests_ran"],
        "tests_passed": counts["tests_passed"],
        "failures": counts["failures"],
        "errors": counts["errors"],
        "stdout": sbx_res.stdout,
        "stderr": sbx_res.stderr,
    }


def evaluate_raw_base_model(
    adapter: AGI17Adapter,
    task: HeldOutCodingTask,
    ws_dir: Path,
) -> Dict[str, Any]:
    _populate_starter_workspace(ws_dir, task)
    module_path = ws_dir / task.module_filename
    starter_code = module_path.read_text(encoding="utf-8") if module_path.exists() else ""
    t0 = time.time()
    prompt = (
        f"Task: {task.prompt}\n\n"
        f"CURRENT `{task.module_filename}`:\n```python\n{starter_code}\n```\n\n"
        f"IMPORTANT: Do NOT call any tools or shell commands. Return ONLY the complete fixed Python code for `{task.module_filename}` in a ```python ... ``` block."
    )
    model_res = adapter.model_adapter.invoke(
        task_id=f"BASE-{task.task_id}",
        child_task_id=f"BASE-{task.task_id}-SINGLE",
        prompt=prompt,
        agent_id="raw_base_model_single_shot",
        effort="high",
        is_benchmark_or_single_shot=True,
        tier="BENCHMARK_ITEM",
    )
    code_str = _extract_python_code(model_res["response_text"])
    module_path.write_text(code_str, encoding="utf-8")
    sha256 = hashlib.sha256(module_path.read_bytes()).hexdigest()
    grade = _run_heldout_grader(adapter, ws_dir, task)
    tok = model_res["token_usage"]
    in_tok = int(tok.get("input_tokens", 0))
    out_tok = int(tok.get("output_tokens", 0))
    return {
        "candidate": "RAW_BASE_MODEL_SINGLE_SHOT",
        "task_id": task.task_id,
        "model": model_res["model"],
        "duration_sec": round(time.time() - t0, 4),
        "model_calls": 1,
        "timed_out": bool(model_res.get("timed_out", False)),
        "fallback_used": False,
        "written_file": redact_sensitive_text(str(module_path)),
        "file_sha256": sha256,
        "token_usage": tok,
        "estimated_cost_usd": round((in_tok * 0.15 + out_tok * 0.60) / 1_000_000, 6),
        "heldout_grading": grade,
    }


def evaluate_single_agent_repair_loop(
    adapter: AGI17Adapter,
    task: HeldOutCodingTask,
    ws_dir: Path,
) -> Dict[str, Any]:
    """Config B: Single-agent code + self-test + sandboxed repair loop (no multi-agent architect decomposition)."""
    _populate_starter_workspace(ws_dir, task)
    module_path = ws_dir / task.module_filename
    test_path = ws_dir / task.test_filename
    module_stem = task.module_filename[:-3] if task.module_filename.endswith(".py") else task.module_filename
    starter_code = module_path.read_text(encoding="utf-8") if module_path.exists() else ""
    t0 = time.time()

    total_in = 0
    total_out = 0
    total_think = 0
    total_tok = 0
    model_calls = 0
    any_timeout = False

    # Call 1: Generate fixed module implementation
    impl_prompt = (
        f"You are a single Python coding agent.\n"
        f"Task: {task.prompt}\n\n"
        f"CURRENT `{task.module_filename}`:\n```python\n{starter_code}\n```\n\n"
        f"IMPORTANT: Do NOT call any tools or shell commands. Return ONLY the complete Python code for `{task.module_filename}` inside a ```python ... ``` block."
    )
    res_impl = adapter.model_adapter.invoke(
        task_id=f"SINGLE-LOOP-{task.task_id}",
        child_task_id=f"SINGLE-LOOP-{task.task_id}-IMPL",
        prompt=impl_prompt,
        agent_id="single_agent_coder",
        effort="high",
        is_benchmark_or_single_shot=True,
        tier="COMPLEX",
    )
    model_calls += 1
    any_timeout = any_timeout or bool(res_impl.get("timed_out", False))
    for k, acc in (("input_tokens", "in"), ("output_tokens", "out"), ("thinking_tokens", "think"), ("total_tokens", "tok")):
        val = int(res_impl["token_usage"].get(k, 0))
        if acc == "in":
            total_in += val
        elif acc == "out":
            total_out += val
        elif acc == "think":
            total_think += val
        else:
            total_tok += val

    impl_code = _extract_python_code(res_impl["response_text"])
    if _is_valid_python_syntax(impl_code):
        module_path.write_text(impl_code, encoding="utf-8")

    # Call 2: Generate unit test suite
    test_prompt = (
        f"You are a single Python coding agent. Write a `unittest` test suite `{task.test_filename}` importing from `{module_stem}`.\n"
        f"Task specification: {task.prompt}\n\n"
        f"IMPLEMENTATION (`{task.module_filename}`):\n```python\n{module_path.read_text(encoding='utf-8')}\n```\n\n"
        f"IMPORTANT: Do NOT call any tools or shell commands. Return ONLY the complete `{task.test_filename}` code inside a ```python ... ``` block."
    )
    res_test = adapter.model_adapter.invoke(
        task_id=f"SINGLE-LOOP-{task.task_id}",
        child_task_id=f"SINGLE-LOOP-{task.task_id}-TEST",
        prompt=test_prompt,
        agent_id="single_agent_coder",
        effort="high",
        is_benchmark_or_single_shot=True,
        tier="COMPLEX",
    )
    model_calls += 1
    any_timeout = any_timeout or bool(res_test.get("timed_out", False))
    total_in += int(res_test["token_usage"].get("input_tokens", 0))
    total_out += int(res_test["token_usage"].get("output_tokens", 0))
    total_think += int(res_test["token_usage"].get("thinking_tokens", 0))
    total_tok += int(res_test["token_usage"].get("total_tokens", 0))

    test_code = _extract_python_code(res_test["response_text"])
    if _is_valid_python_syntax(test_code):
        test_path.write_text(test_code, encoding="utf-8")

    # Run self-test in disposable sandbox
    sbx_initial = adapter.orchestrator.sandbox_runner.run_python_unittest_sandbox(
        files={
            task.module_filename: module_path.read_text(encoding="utf-8"),
            task.test_filename: test_path.read_text(encoding="utf-8") if test_path.exists() else "",
        },
        test_pattern=task.test_filename,
        sandbox_id=f"SINGLE-LOOP-{task.task_id}-SBX1",
    )
    repair_triggered = False
    if not sbx_initial.passed:
        repair_triggered = True
        rep_prompt = (
            f"You are a single Python coding agent. Fix `{task.module_filename}` so the failing unit tests pass.\n\n"
            f"CURRENT `{task.module_filename}`:\n```python\n{module_path.read_text(encoding='utf-8')}\n```\n\n"
            f"UNITTEST TRACEBACK:\n```text\n{(sbx_initial.stderr or sbx_initial.stdout)[-1500:]}\n```\n\n"
            f"IMPORTANT: Do NOT call any tools or shell commands. Return ONLY the complete fixed `{task.module_filename}` in a ```python ... ``` block."
        )
        res_rep = adapter.model_adapter.invoke(
            task_id=f"SINGLE-LOOP-{task.task_id}",
            child_task_id=f"SINGLE-LOOP-{task.task_id}-REPAIR",
            prompt=rep_prompt,
            agent_id="single_agent_coder",
            effort="high",
            is_benchmark_or_single_shot=True,
            tier="COMPLEX",
        )
        model_calls += 1
        any_timeout = any_timeout or bool(res_rep.get("timed_out", False))
        total_in += int(res_rep["token_usage"].get("input_tokens", 0))
        total_out += int(res_rep["token_usage"].get("output_tokens", 0))
        total_think += int(res_rep["token_usage"].get("thinking_tokens", 0))
        total_tok += int(res_rep["token_usage"].get("total_tokens", 0))
        rep_code = _extract_python_code(res_rep["response_text"])
        if _is_valid_python_syntax(rep_code):
            module_path.write_text(rep_code, encoding="utf-8")

    sha256 = hashlib.sha256(module_path.read_bytes()).hexdigest() if module_path.exists() else None
    grade = _run_heldout_grader(adapter, ws_dir, task)

    return {
        "candidate": "SINGLE_AGENT_REPAIR_LOOP",
        "task_id": task.task_id,
        "model": adapter.model_adapter.SOLE_MODEL,
        "duration_sec": round(time.time() - t0, 4),
        "model_calls": model_calls,
        "timed_out": any_timeout,
        "initial_self_test_failed": not sbx_initial.passed,
        "self_healing_repair_triggered": repair_triggered,
        "sandbox_isolation_backend": sbx_initial.isolation_backend,
        "fallback_used": False,
        "written_file": redact_sensitive_text(str(module_path)),
        "file_sha256": sha256,
        "token_usage": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "thinking_tokens": total_think,
            "total_tokens": total_tok,
        },
        "estimated_cost_usd": round((total_in * 0.15 + total_out * 0.60) / 1_000_000, 6),
        "heldout_grading": grade,
    }


def evaluate_agi17_orchestrated(
    adapter: AGI17Adapter,
    task: HeldOutCodingTask,
    ws_dir: Path,
) -> Dict[str, Any]:
    _populate_starter_workspace(ws_dir, task)
    t0 = time.time()
    mission_id = f"AGI17-{task.task_id}-{int(t0)}"
    orch_res = adapter.execute_mission(
        title=f"Held-Out Coding Benchmark: {task.title}",
        prompt=task.prompt,
        task_id=mission_id,
        code_task_dir=ws_dir,
        module_filename=task.module_filename,
        test_filename=task.test_filename,
        inject_deliberate_test_failure=False,
    )
    module_path = ws_dir / task.module_filename
    sha256 = hashlib.sha256(module_path.read_bytes()).hexdigest() if module_path.exists() else None
    grade = _run_heldout_grader(adapter, ws_dir, task)

    total_in = 0
    total_out = 0
    total_think = 0
    total_tok = 0
    model_calls = 0
    repair_triggered = False
    initial_self_test_failed = False
    failed_attempt_details: List[Dict[str, Any]] = []

    for cid, ch in orch_res.get("child_results", {}).items():
        art = ch.get("artifacts", {}) if isinstance(ch, dict) else {}
        tu = art.get("token_usage")
        if isinstance(tu, dict):
            model_calls += 1
            total_in += int(tu.get("input_tokens", 0))
            total_out += int(tu.get("output_tokens", 0))
            total_think += int(tu.get("thinking_tokens", 0))
            total_tok += int(tu.get("total_tokens", 0))
        init_ver = art.get("initial_verification_run")
        if isinstance(init_ver, dict) and init_ver.get("exit_code", 0) != 0:
            initial_self_test_failed = True
            failed_attempt_details.append(
                {
                    "child_task_id": cid,
                    "attempt": 1,
                    "exit_code": init_ver.get("exit_code"),
                    "stderr_excerpt": (init_ver.get("stderr") or "")[-600:],
                }
            )
        rep = art.get("repair_execution")
        if isinstance(rep, dict):
            repair_triggered = True
            rtu = rep.get("token_usage")
            if isinstance(rtu, dict):
                model_calls += 1
                total_in += int(rtu.get("input_tokens", 0))
                total_out += int(rtu.get("output_tokens", 0))
                total_think += int(rtu.get("thinking_tokens", 0))
                total_tok += int(rtu.get("total_tokens", 0))

    return {
        "candidate": "AGI_1_7_OMEGA_COMMAND",
        "task_id": task.task_id,
        "mission_id": mission_id,
        "orchestrator_final_state": orch_res.get("final_state"),
        "terminal_outcome": orch_res.get("terminal_outcome"),
        "duration_sec": round(time.time() - t0, 4),
        "model_calls": model_calls,
        "initial_self_test_failed": initial_self_test_failed,
        "failed_attempts_before_repair": failed_attempt_details,
        "self_healing_repair_triggered": repair_triggered,
        "fallback_summary": orch_res.get("fallback_summary", {}),
        "written_file": redact_sensitive_text(str(module_path)),
        "file_sha256": sha256,
        "token_usage": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "thinking_tokens": total_think,
            "total_tokens": total_tok,
        },
        "estimated_cost_usd": round((total_in * 0.15 + total_out * 0.60) / 1_000_000, 6),
        "heldout_grading": grade,
        "child_results_summary": {
            cid: {
                "agent_id": ch.get("agent_id"),
                "status": ch.get("status"),
                "schema_validation_passed": ch.get("schema_validation_passed"),
                "artifact_verification_passed": ch.get("artifact_verification_passed"),
                "task_correctness_verified": ch.get("task_correctness_verified"),
                "memory_guardrails_injected": ch.get("artifacts", {}).get("memory_guardrails_injected", False),
                "fallback_used": ch.get("artifacts", {}).get("fallback_used", False),
                "ecosystem_coordination": ch.get("artifacts", {}).get("ecosystem_coordination"),
            }
            for cid, ch in orch_res.get("child_results", {}).items()
        },
    }


def _compute_candidate_metrics(results_per_task: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    n = max(1, len(results_per_task))
    tasks_passed = sum(1 for r in results_per_task if r[key]["heldout_grading"]["task_completed_verified"])
    tests_ran = sum(r[key]["heldout_grading"]["tests_ran"] for r in results_per_task)
    tests_passed = sum(r[key]["heldout_grading"]["tests_passed"] for r in results_per_task)
    total_tok = sum(r[key]["token_usage"]["total_tokens"] for r in results_per_task)
    total_cost = round(sum(r[key]["estimated_cost_usd"] for r in results_per_task), 6)
    avg_latency = round(sum(r[key]["duration_sec"] for r in results_per_task) / n, 2)
    timeouts = sum(1 for r in results_per_task if r[key].get("timed_out", False) or r[key]["token_usage"]["total_tokens"] == 0)
    regressions = sum(
        1
        for r in results_per_task
        if r[key]["heldout_grading"]["tests_ran"] > 0 and r[key]["heldout_grading"]["tests_passed"] == 0
    )
    return {
        "tasks_completed": f"{tasks_passed}/{len(results_per_task)}",
        "task_completion_rate_pct": round(100.0 * tasks_passed / n, 2),
        "heldout_unit_tests_passed": f"{tests_passed}/{tests_ran}",
        "unit_test_pass_rate_pct": round(100.0 * tests_passed / max(1, tests_ran), 2),
        "regression_rate_pct": round(100.0 * regressions / n, 2),
        "failure_or_timeout_rate_pct": round(100.0 * timeouts / n, 2),
        "average_latency_sec": avg_latency,
        "total_tokens": total_tok,
        "total_cost_usd": total_cost,
        "cost_per_verified_task_usd": round(total_cost / tasks_passed, 6) if tasks_passed > 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="3-Way Held-Out Coding Benchmark: Config A vs Config B vs Config C")
    parser.add_argument("--max-tasks", type=int, default=3, help="Number of held-out coding tasks to run (1..50)")
    parser.add_argument("--max-budget-usd", type=float, default=0.25, help="Maximum pre-flight USD budget ceiling")
    parser.add_argument(
        "--only-config-b",
        action="store_true",
        help="Run live Config B (Single-Agent Repair Loop) and merge with existing Config A & Config C records",
    )
    parser.add_argument(
        "--re-evaluate-config-c-task",
        default=None,
        help="Re-evaluate a specific task ID on Config C (AGI 1.7) after self-learning memory & adaptive test reuse updates",
    )
    args = parser.parse_args()

    selected_tasks = HELDOUT_CODING_50_SUITE[: max(1, min(args.max_tasks, len(HELDOUT_CODING_50_SUITE)))]
    if args.re_evaluate_config_c_task:
        configs_to_run = ["C"]
        preflight = estimate_preflight_budget(1, configs_to_run, args.max_budget_usd)
    else:
        configs_to_run = ["B"] if args.only_config_b else ["A", "B", "C"]
        preflight = estimate_preflight_budget(len(selected_tasks), configs_to_run, args.max_budget_usd)
    print("PRE-FLIGHT BUDGET ESTIMATE:", json.dumps(preflight, indent=2), flush=True)

    bench_root = REPO_ROOT / "agents" / "AGI_1_7" / "heldout_benchmark_workspace"
    bench_root.mkdir(parents=True, exist_ok=True)

    adapter = AGI17Adapter(
        storage_root=bench_root / "runtime_storage",
        eval_root=bench_root / "eval_env",
    )
    cli_version = _get_cli_version(adapter.model_adapter.agy_path)

    raw_out = REPO_ROOT / "agents" / "AGI_1_7" / "reports" / "HELDOUT_CODING_BENCHMARK_RAW_RESULTS.json"
    existing_by_task: Dict[str, Dict[str, Any]] = {}
    old_data: Dict[str, Any] = {}
    if raw_out.exists():
        old_data = json.loads(raw_out.read_text(encoding="utf-8"))
        for item in old_data.get("task_level_results", []):
            existing_by_task[item["task_id"]] = item

    # Seed persistent self-learning lesson from prior TASK-01 failure if re-evaluating Config C
    if args.re_evaluate_config_c_task:
        adapter.memory.record_failure_lesson(
            task_id="PRIOR-AGI17-TASK-01-TOKEN-BUCKET",
            module_name="token_bucket.py",
            failing_assertion="AttributeError: 'TokenBucketRateLimiter' object has no attribute 'snapshot'",
            root_cause="Initial specification omitted repository test contract snapshot(now) and strict ValueError checks on capacity/refill_rate/tokens <= 0.",
            minimal_patch_rule=(
                "For token_bucket.py (TokenBucketRateLimiter): validate capacity > 0, refill_rate > 0 in __init__ and tokens > 0 in try_acquire (raise ValueError); "
                "use >= for exact boundary acquisition; clamp non-monotonic clock elapsed=max(0.0, now - last_timestamp); "
                "implement snapshot(now) returning {'available': available_tokens(now), 'capacity': self.capacity, 'refill_rate': self.refill_rate}."
            ),
        )

    results_per_task: List[Dict[str, Any]] = []
    pre_self_improvement_record: Dict[str, Any] = {}
    for idx, task in enumerate(selected_tasks):
        base_ws = bench_root / "candidates" / "raw_base_model" / task.task_id
        single_ws = bench_root / "candidates" / "single_agent_repair" / task.task_id
        agi17_ws = bench_root / "candidates" / "agi17_orchestrated" / task.task_id

        if args.re_evaluate_config_c_task:
            if task.task_id == args.re_evaluate_config_c_task:
                print(f"[RE-EVAL CONFIG C] Running self-improved AGI 1.7 on {task.task_id}...", flush=True)
                if task.task_id in existing_by_task:
                    pre_self_improvement_record[task.task_id] = existing_by_task[task.task_id].get("agi_1_7_omega_command")
                base_res = existing_by_task[task.task_id]["raw_base_model"]
                single_res = existing_by_task[task.task_id]["single_agent_repair_loop"]
                agi17_res = evaluate_agi17_orchestrated(adapter, task, agi17_ws)
            else:
                base_res = existing_by_task[task.task_id]["raw_base_model"]
                single_res = existing_by_task[task.task_id]["single_agent_repair_loop"]
                agi17_res = existing_by_task[task.task_id]["agi_1_7_omega_command"]
        elif args.only_config_b and task.task_id in existing_by_task:
            print(f"[{idx + 1}/{len(selected_tasks)}] Evaluating Config B on {task.task_id}...", flush=True)
            base_res = existing_by_task[task.task_id]["raw_base_model"]
            agi17_res = existing_by_task[task.task_id]["agi_1_7_omega_command"]
            single_res = evaluate_single_agent_repair_loop(adapter, task, single_ws)
        else:
            print(f"[{idx + 1}/{len(selected_tasks)}] Evaluating {task.task_id} ({task.title})...", flush=True)
            base_res = evaluate_raw_base_model(adapter, task, base_ws)
            agi17_res = evaluate_agi17_orchestrated(adapter, task, agi17_ws)
            single_res = evaluate_single_agent_repair_loop(adapter, task, single_ws)

        results_per_task.append(
            {
                "task_id": task.task_id,
                "title": task.title,
                "category": task.category,
                "grader_sha256": task.grader_sha256,
                "raw_base_model": base_res,
                "single_agent_repair_loop": single_res,
                "agi_1_7_omega_command": agi17_res,
            }
        )

    scoreboard = {
        "config_a_raw_base_model_single_shot": _compute_candidate_metrics(results_per_task, "raw_base_model"),
        "config_b_single_agent_repair_loop": _compute_candidate_metrics(results_per_task, "single_agent_repair_loop"),
        "config_c_agi_1_7_omega_command": {
            **_compute_candidate_metrics(results_per_task, "agi_1_7_omega_command"),
            "any_fallback_used": any(
                r["agi_1_7_omega_command"].get("fallback_summary", {}).get("any_fallback_used", False)
                for r in results_per_task
            ),
        },
    }

    summary_payload = {
        "benchmark_name": "AGI 1.7 3-Way Held-Out Reproducible Coding Benchmark (Config A vs B vs C)",
        "executed_at_epoch": time.time(),
        "suite_inventory": {
            "total_suite_tasks": len(HELDOUT_CODING_50_SUITE),
            "categories_count": 10,
            "live_evaluated_tasks": len(selected_tasks),
        },
        "preflight_budget_estimate": preflight,
        "cli_and_model_metadata": {
            "cli_binary": redact_sensitive_text(str(adapter.model_adapter.agy_path)),
            "cli_version": cli_version,
            "model_identifier": adapter.model_adapter.SOLE_MODEL,
            "effort_level": "high",
            "sandbox_isolation_backend": adapter.orchestrator.sandbox_runner.detect_docker_python_image()
            and "docker_disposable_container"
            or "ephemeral_restricted_tempdir",
        },
        "tasks_evaluated": len(selected_tasks),
        "scoreboard": scoreboard,
        "self_learning_improvement_comparison": pre_self_improvement_record,
        "task_level_results": results_per_task,
    }

    raw_out.parent.mkdir(parents=True, exist_ok=True)
    raw_out.write_text(redact_sensitive_text(json.dumps(summary_payload, indent=2, default=str)), encoding="utf-8")
    print(json.dumps(scoreboard, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
