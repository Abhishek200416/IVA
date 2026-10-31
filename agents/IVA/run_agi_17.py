"""AGI 1.7.0 — OMEGA COMMAND Primary Runtime Entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.IVA.engine.agi17.adapters.agi_17_adapter import AGI17Adapter


def _resolve_storage_root(preferred: str | None) -> Path:
    if preferred:
        candidate = Path(preferred)
    elif sys.platform == "win32" and os.path.exists("D:\\"):
        candidate = Path(r"D:\AGI_Storage\AGI_1_7")
    else:
        candidate = Path.home() / ".iva" / "storage"

    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return candidate
    except OSError:
        fallback = REPO_ROOT / "agents" / "IVA" / "runtime_storage"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _spawn_detached(args: argparse.Namespace, storage_root: Path, effective_code_dir: str | None) -> int:
    """Spawns run_agi_17.py in an OS-detached process group that survives closing Antigravity IDE."""
    detached_dir = storage_root / "logs" / "detached"
    detached_dir.mkdir(parents=True, exist_ok=True)
    task_id = args.task_id or f"MISSION-DETACHED-{int(time.time())}"
    log_path = detached_dir / f"{task_id}.log"
    pid_path = detached_dir / f"{task_id}.pid.json"

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--title",
        args.title,
        "--task-id",
        task_id,
        "--storage-root",
        str(storage_root),
        "--module-filename",
        args.module_filename,
        "--test-filename",
        args.test_filename,
        "--detached-pid-file",
        str(pid_path),
    ]
    if args.prompt:
        cmd.extend(["--prompt", args.prompt])
    if effective_code_dir:
        cmd.extend(["--code-task-dir", str(effective_code_dir)])
    if args.text_only:
        cmd.append("--text-only")
    if args.profile_only:
        cmd.append("--profile-only")
    if args.force_hierarchical:
        cmd.append("--force-hierarchical")
    if args.inject_deliberate_test_failure:
        cmd.append("--inject-deliberate-test-failure")
    if args.save_execution_log:
        cmd.extend(["--save-execution-log", str(args.save_execution_log)])
    if getattr(args, "ci_repair_dir", None):
        cmd.extend(["--ci-repair-dir", str(args.ci_repair_dir)])
    if getattr(args, "apply_approved_patch", False):
        cmd.append("--apply-approved-patch")
    if getattr(args, "test_pattern", None):
        cmd.extend(["--test-pattern", str(args.test_pattern)])
    if getattr(args, "api_key", None):
        cmd.extend(["--api-key", str(args.api_key)])
    if getattr(args, "model", None):
        cmd.extend(["--model", str(args.model)])

    creationflags = 0
    if os.name == "nt":
        # MSDN: CREATE_NO_WINDOW + CREATE_NEW_PROCESS_GROUP detaches from parent console
        # while preserving redirected stdout/stderr file handles.
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )

    log_fh = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=(os.name != "nt"),
        close_fds=(os.name != "nt"),
    )
    log_fh.close()

    payload = {
        "status": "DETACHED_RUNNING",
        "terminal_outcome": "DETACHED_LAUNCHED_UNVERIFIED",
        "mission_verified": False,
        "survives_antigravity_close": True,
        "started_at_epoch": time.time(),
        "pid": proc.pid,
        "task_id": task_id,
        "title": args.title,
        "code_task_dir": str(effective_code_dir) if effective_code_dir else None,
        "storage_root": str(storage_root),
        "log_path": str(log_path),
        "pid_file": str(pid_path),
        "command_spawned": cmd,
    }
    pid_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2), flush=True)
    return 0


def _update_detached_pid_file(
    pid_file_path: str | None,
    status: str,
    final_state: str,
    exit_code: int,
    terminal_outcome: str | None = None,
) -> None:
    if not pid_file_path:
        return
    p = Path(pid_file_path)
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        eff_outcome = terminal_outcome or final_state
        data["status"] = status
        data["final_state"] = final_state
        data["terminal_outcome"] = eff_outcome
        data["mission_verified"] = bool(exit_code == 0 and eff_outcome == "SUCCEEDED_AND_VERIFIED")
        data["exit_code"] = exit_code
        data["completed_at_epoch"] = time.time()
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


TERMINAL_OUTCOME_EXIT_CODES: dict[str, int] = {
    "SUCCEEDED_AND_VERIFIED": 0,
    "PROFILE_ONLY_OK": 0,
    "ALREADY_PASSING": 0,
    "FAILED": 1,
    "BLOCKED_BY_POLICY": 2,
    "TIMED_OUT": 3,
    "CANCELLED": 4,
    "BUDGET_EXCEEDED": 5,
    "SUCCEEDED_UNVERIFIED": 6,
}


def compute_cli_exit_code(result: dict) -> int:
    """Returns 0 strictly for SUCCEEDED_AND_VERIFIED (or PROFILE_ONLY_OK/ALREADY_PASSING), and distinct non-zero codes otherwise."""
    outcome = str(result.get("terminal_outcome") or "")
    if outcome in TERMINAL_OUTCOME_EXIT_CODES:
        return TERMINAL_OUTCOME_EXIT_CODES[outcome]
    status = str(result.get("status") or "")
    if outcome == "PENDING_APPROVAL" or status == "PENDING_APPROVAL":
        return 6
    if status == "ALREADY_PASSING":
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AGI 1.7.0 — OMEGA COMMAND Runtime")
    parser.add_argument("--title", default="AGI 1.7 Mission", help="Mission title")
    parser.add_argument("--prompt", default=None, help="Mission prompt to execute")
    parser.add_argument("--task-id", default=None, help="Optional explicit mission task ID")
    parser.add_argument("--storage-root", default=None, help="Optional storage root path (falls back locally if D:\\ unavailable)")
    parser.add_argument("--profile-only", action="store_true", help="Run capability profiler and startup reconciliation only")
    parser.add_argument("--force-hierarchical", action="store_true", help="Force hierarchical DAG planning")
    parser.add_argument(
        "--code-task-dir",
        default=None,
        help="Directory for live-model Python code & unit-test generation + self-healing verification (defaults to agents/AGI_1_7/live_code_mission_workspace unless --text-only is set)",
    )
    parser.add_argument("--text-only", action="store_true", help="Run text-only mission without writing/testing code files")
    parser.add_argument("--module-filename", default="token_bucket.py", help="Target Python module filename for coding workflow")
    parser.add_argument("--test-filename", default="test_token_bucket.py", help="Target unittest filename for coding workflow")
    parser.add_argument("--test-pattern", default="test_*.py", help="Strict unittest discovery pattern (e.g., test_*.py)")
    parser.add_argument(
        "--inject-deliberate-test-failure",
        action="store_true",
        help="Inject a deliberate defect after Stage 2 code generation so Stage 3 detects a real unittest failure, escalates to swe_patch_minimizer via ModelAdapter.invoke(), and re-runs tests",
    )
    parser.add_argument(
        "--ci-repair-dir",
        default=None,
        help="Run the focused Python CI-Repair Agent on the specified workspace directory (reproduces failing tests in disposable sandbox, generates minimal patch, verifies tests, outputs PR payload)",
    )
    parser.add_argument(
        "--apply-approved-patch",
        action="store_true",
        help="Explicitly approve writing the verified CI-Repair or coding patch to the target workspace (default stages candidate patch externally only)",
    )
    parser.add_argument("--save-execution-log", default=None, help="Optional path to save full JSON execution trace")
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Run in an OS-detached background process that keeps working even after closing Antigravity IDE",
    )
    parser.add_argument("command", nargs="?", default=None, help="Optional command (e.g. 'trading')")
    parser.add_argument("--trading", action="store_true", help="Launch Autonomous Paper-Trading System")
    parser.add_argument("--improvement-worker", action="store_true", help="Run Persistent Autonomous Improvement Worker")
    parser.add_argument("--worker-start", action="store_true", help="Launch Improvement Worker in detached background process")
    parser.add_argument("--worker-stop", action="store_true", help="Authoritative STOP signal to Improvement Worker")
    parser.add_argument("--worker-pause", action="store_true", help="Authoritative PAUSE signal to Improvement Worker")
    parser.add_argument("--worker-resume", action="store_true", help="Authoritative RESUME signal to Improvement Worker")
    parser.add_argument("--worker-status", action="store_true", help="Check Improvement Worker status and heartbeat")
    parser.add_argument("--worker-single-cycle", action="store_true", help="Run exactly one improvement cycle and exit")
    parser.add_argument("--worker-stop-after-cycle", action="store_true", help="Stop Improvement Worker after completing current cycle")
    parser.add_argument("--query", default=None, help="Process conversational or operational query through CommandRouter and LLM communication layer")
    parser.add_argument("--api-key", default=None, help="Universal LLM API Key (Google Gemini, OpenAI, Groq, OpenRouter). If omitted, auto-discovered from .env or environment variables.")
    parser.add_argument("--model", default=None, help="LLM model name override (e.g. gemini-2.5-flash, gemini-2.0-flash, gpt-4o, etc.)")
    parser.add_argument(
        "-i", "--interactive", "--cli",
        dest="interactive",
        action="store_true",
        help="Launch the interactive terminal session with Iva (zero GUI/voice overlays, pure terminal CLI)",
    )
    parser.add_argument("--detached-pid-file", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    # Conversational & Operational Query Fast-Path (Phase 17.26)
    if args.query:
        from agents.IVA.engine.agi17.runtime.command_router import CommandRouter
        router = CommandRouter()
        routing_res = router.handle_command(args.query)
        print(json.dumps(routing_res, indent=2, default=str), flush=True)
        return 0 if routing_res.get("permissible", True) else 2

    # Autonomous Improvement Worker Handlers (Phase 17.25)
    if args.worker_stop or (args.command and args.command.lower() in ("worker-stop", "omega-stop")):
        from agents.IVA.engine.agi17.orchestration.persistent_improvement_worker import PersistentImprovementWorker
        w = PersistentImprovementWorker()
        w.set_control_signal("STOP", reason="run_agi_17.py --worker-stop")
        print(json.dumps({"status": "STOP_SIGNAL_SENT", "persisted": True}, indent=2))
        return 0

    if args.worker_pause or (args.command and args.command.lower() in ("worker-pause", "omega-pause")):
        from agents.IVA.engine.agi17.orchestration.persistent_improvement_worker import PersistentImprovementWorker
        w = PersistentImprovementWorker()
        w.set_control_signal("PAUSE", reason="run_agi_17.py --worker-pause")
        print(json.dumps({"status": "PAUSE_SIGNAL_SENT"}, indent=2))
        return 0

    if args.worker_resume or (args.command and args.command.lower() in ("worker-resume", "omega-resume")):
        from agents.IVA.engine.agi17.orchestration.persistent_improvement_worker import PersistentImprovementWorker
        w = PersistentImprovementWorker()
        w.set_control_signal("RESUME", reason="run_agi_17.py --worker-resume")
        print(json.dumps({"status": "RESUME_SIGNAL_SENT"}, indent=2))
        return 0

    if args.worker_status or (args.command and args.command.lower() in ("worker-status", "omega-status")):
        from agents.IVA.engine.agi17.orchestration.persistent_improvement_worker import PersistentImprovementWorker
        w = PersistentImprovementWorker()
        hb = json.loads(w.heartbeat_file.read_text(encoding="utf-8")) if w.heartbeat_file.exists() else {}
        cp = json.loads(w.checkpoint_file.read_text(encoding="utf-8")) if w.checkpoint_file.exists() else {}
        print(json.dumps({"heartbeat": hb, "checkpoint": cp}, indent=2))
        return 0

    if args.worker_single_cycle or (args.command and args.command.lower() == "worker-single-cycle"):
        from agents.IVA.engine.agi17.orchestration.persistent_improvement_worker import PersistentImprovementWorker
        w = PersistentImprovementWorker()
        w.acquire_worker_lock(force=True)
        try:
            res = w.execute_cycle()
            print(json.dumps(res.to_dict(), indent=2))
            return 0 if res.test_passed else 1
        finally:
            w.release_worker_lock()

    if args.worker_start or (args.command and args.command.lower() in ("worker-start", "worker")):
        # Spawn persistent worker in OS-detached background process
        worker_script = REPO_ROOT / "agents" / "IVA" / "engine" / "agi17" / "orchestration" / "persistent_improvement_worker.py"
        log_dir = REPO_ROOT / "scratch" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "improvement_worker.log"
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                | 0x00000008  # DETACHED_PROCESS
            )
            log_fd = os.open(str(log_file), os.O_CREAT | os.O_WRONLY | os.O_APPEND)
            proc = subprocess.Popen(
                [sys.executable, str(worker_script), "--interval", "15"],
                cwd=str(REPO_ROOT),
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=False,
            )
            os.close(log_fd)
        else:
            log_fh = open(log_file, "a", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, str(worker_script), "--interval", "15"],
                cwd=str(REPO_ROOT),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        print(json.dumps({
            "status": "WORKER_DETACHED_STARTED",
            "pid": proc.pid,
            "log_file": str(log_file),
            "survives_console_close": True
        }, indent=2))
        return 0

    if args.command == "trading" or args.trading or (args.prompt and args.prompt.strip().lower() == "trading"):
        from agents.IVA.engine.agi17.finance.trading_orchestrator import run_trading_command
        return run_trading_command()

    if (args.command and args.command.lower() in ("go-real", "goreal", "live")) or (args.prompt and args.prompt.strip().lower() in ("go real", "goreal", "go-real", "live")):
        from agents.IVA.engine.agi17.finance.trading_orchestrator import run_go_real_command
        return run_go_real_command()

    storage_root = _resolve_storage_root(args.storage_root)

    if not args.prompt and args.command and args.command.lower() not in (
        "trading", "go-real", "goreal", "live", "worker-stop", "worker-pause", "worker-resume", "omega-stop", "omega-pause", "omega-resume"
    ):
        cmd_low = args.command.lower().strip()
        from agents.IVA.engine.agi17.runtime.terminal_client import TerminalClient, run_single_prompt
        adapter = AGI17Adapter(storage_root=storage_root, api_key=args.api_key, model=args.model)
        tc = TerminalClient(adapter=adapter, api_key=args.api_key, model=args.model, storage_root=storage_root)
        if cmd_low in ("specialists", "specialist", "skills"):
            tc.print_specialists()
            return 0
        elif cmd_low in ("plugins", "plugin", "agency", "ponytail"):
            tc.print_plugins_notice()
            return 0
        elif cmd_low in ("models", "model", "providers"):
            tc.print_models()
            return 0
        elif cmd_low in ("sysmatch", "match", "compat"):
            tc.print_sysmatch()
            return 0
        elif cmd_low in ("mcp", "mcp list", "mcps"):
            tc.print_mcp_list()
            return 0
        elif cmd_low.startswith("mcp install ") or cmd_low.startswith("mcp add "):
            srv = args.command.split(" ", 2)[2].strip()
            tc.execute_mcp_install(srv)
            return 0
        elif cmd_low.startswith("mcp test "):
            srv = args.command.split(" ", 2)[2].strip()
            tc.execute_mcp_test(srv)
            return 0
        elif cmd_low.startswith("learn "):
            tgt = args.command[6:].strip()
            tc.execute_learn(tgt)
            return 0
        elif cmd_low in ("memory", "mem"):
            tc.print_memory_status()
            return 0
        elif cmd_low.startswith("remember "):
            tc.execute_remember(args.command[9:].strip())
            return 0
        elif cmd_low.startswith("forget "):
            tc.execute_forget(args.command[7:].strip())
            return 0
        elif cmd_low in ("evolve", "loop", "24", "self-improve"):
            tc.execute_evolve()
            return 0
        elif cmd_low in ("audit", "security", "guard"):
            tc.print_audit()
            return 0
        elif cmd_low in ("quant", "volatility", "alpha"):
            tc.print_quant()
            return 0
        elif cmd_low in ("safety", "gate"):
            tc.print_safety()
            return 0
        elif cmd_low in ("benchmark", "bench", "scores"):
            tc.print_benchmark()
            return 0
        elif cmd_low in ("version", "ver"):
            tc.print_version()
            return 0
        elif cmd_low in ("status", "health"):
            tc.print_status()
            return 0
        elif cmd_low in ("profile", "hardware"):
            tc.print_profile()
            return 0
        elif cmd_low in ("test", "tests", "verify", "selftest"):
            return tc.run_self_tests()
        elif cmd_low in ("help", "?"):
            tc.print_help()
            return 0
        elif not args.code_task_dir and not args.ci_repair_dir:
            return run_single_prompt(
                args.command,
                adapter=adapter,
                api_key=args.api_key,
                model=args.model,
                storage_root=storage_root,
            )
        else:
            args.prompt = args.command

    # Normal CLI runs the complete coding workflow by default whenever a prompt is given
    # unless --text-only or --profile-only or --ci-repair-dir is specified.
    effective_code_dir: str | None = args.code_task_dir
    if effective_code_dir is None and args.prompt and not args.text_only and not args.profile_only and not args.ci_repair_dir:
        effective_code_dir = str(REPO_ROOT / "agents" / "IVA" / "live_code_mission_workspace")

    if args.detach:
        return _spawn_detached(args, storage_root, effective_code_dir)

    adapter = AGI17Adapter(storage_root=storage_root, api_key=args.api_key, model=args.model)

    startup = adapter.run_startup_reconciliation()

    if args.ci_repair_dir:
        try:
            repair_res = adapter.run_ci_repair(
                workspace_dir=args.ci_repair_dir,
                module_filename=args.module_filename,
                test_pattern=args.test_pattern,
                issue_description=args.prompt or "Fix failing Python unit tests with minimal diff.",
                write_patch_to_workspace=bool(args.apply_approved_patch),
                apply_approved_patch=bool(args.apply_approved_patch),
            )
        except Exception as exc:
            exc_name = type(exc).__name__
            if "BudgetExceeded" in exc_name:
                term = "BUDGET_EXCEEDED"
            elif any(
                k in exc_name
                for k in (
                    "Sandbox",
                    "PathTraversal",
                    "UntrustedContent",
                    "HighImpactAction",
                    "Policy",
                    "InvalidTestPattern",
                    "DirectiveZeroViolation",
                )
            ):
                term = "BLOCKED_BY_POLICY"
            elif "Timeout" in exc_name:
                term = "TIMED_OUT"
            elif "Cancel" in exc_name:
                term = "CANCELLED"
            else:
                term = "FAILED"
            repair_res = {
                "status": "REPAIR_FAILED",
                "terminal_outcome": term,
                "error": {"exception_type": exc_name, "message": str(exc)},
            }
        if args.save_execution_log:
            out_p = Path(args.save_execution_log)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(json.dumps(repair_res, indent=2, default=str), encoding="utf-8")
        ci_exit_code = compute_cli_exit_code(repair_res)
        _update_detached_pid_file(
            args.detached_pid_file,
            "DETACHED_COMPLETED" if ci_exit_code == 0 else "DETACHED_FAILED",
            str(repair_res.get("status", "UNKNOWN")),
            ci_exit_code,
            terminal_outcome=str(repair_res.get("terminal_outcome", "FAILED")),
        )
        print(json.dumps(repair_res, indent=2, default=str), flush=True)
        return ci_exit_code

    # Interactive Terminal Session Launch (Phase 17.30)
    # Triggered explicitly via -i / --interactive / --cli, OR when run without arguments on an interactive terminal (isatty)
    is_interactive_terminal = getattr(args, "interactive", False) or (
        not args.prompt
        and not args.profile_only
        and not args.ci_repair_dir
        and hasattr(sys.stdin, "isatty")
        and sys.stdin.isatty()
    )
    if is_interactive_terminal and not args.profile_only:
        from agents.IVA.engine.agi17.runtime.terminal_client import run_terminal_session
        return run_terminal_session(
            adapter=adapter,
            api_key=args.api_key,
            model=args.model,
            storage_root=storage_root,
        )

    if args.profile_only or not args.prompt:
        profile = adapter.profiler.build_full_profile()
        out_payload = {
            "runtime": "AGI 1.7.0 — OMEGA COMMAND",
            "terminal_outcome": "PROFILE_ONLY_OK",
            "startup": startup,
            "capability_profile_summary": {
                "logical_cores": profile["cpu_and_compute"]["logical_processors"],
                "avail_phys_mb": profile["memory"]["available_physical_ram_mb"],
                "d_drive_verified": profile["storage_and_persistence"]["d_drive_verified"],
                "d_probe_sha256": profile["storage_and_persistence"]["d_probe_sha256"],
                "agy_available": profile["network_and_model_services"]["agy_cli_available"],
                "docker_available": profile["virtualization_and_runtimes"]["docker_engine_available"],
            },
        }
        _update_detached_pid_file(
            args.detached_pid_file,
            "DETACHED_COMPLETED",
            "PROFILE_ONLY_OK",
            0,
            terminal_outcome="PROFILE_ONLY_OK",
        )
        print(json.dumps(out_payload, indent=2), flush=True)
        return 0

    if args.prompt:
        from agents.IVA.engine.agi17.runtime.command_router import CommandRouter, CommandIntent
        router = CommandRouter()
        intent = router.classify_intent(args.prompt)
        if intent == CommandIntent.GENUINE_SAFETY_GATE:
            gate_res = router.handle_command(args.prompt)
            print(json.dumps(gate_res, indent=2), flush=True)
            return 2  # BLOCKED_BY_POLICY

    result = adapter.execute(
        title=args.title,
        prompt=args.prompt,
        task_id=args.task_id,
        force_hierarchical=args.force_hierarchical,
        code_task_dir=effective_code_dir,
        module_filename=args.module_filename,
        test_filename=args.test_filename,
        inject_deliberate_test_failure=args.inject_deliberate_test_failure,
        apply_approved_patch=bool(args.apply_approved_patch),
    )
    if args.save_execution_log:
        out_p = Path(args.save_execution_log)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    exit_code = compute_cli_exit_code(result)
    term_out = str(result.get("terminal_outcome") or result.get("final_state", "UNKNOWN"))
    _update_detached_pid_file(
        args.detached_pid_file,
        "DETACHED_COMPLETED" if exit_code == 0 else "DETACHED_FAILED",
        str(result.get("final_state", term_out)),
        exit_code,
        terminal_outcome=term_out,
    )
    print(json.dumps(result, indent=2, default=str), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
