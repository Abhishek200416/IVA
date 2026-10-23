"""AGI 1.7 Hierarchical Self-Orchestrating Multi-Agent Runtime.

Coordinates:
1. Pre-planning memory retrieval (`OmegaCommandMemory.retrieve_before_planning`).
2. Automatic task complexity classification:
   - Small/direct tasks -> lightweight Fast Path (zero unnecessary child agent overhead).
   - Substantial/multi-stage tasks -> Planned Hierarchical DAG execution.
3. Up to 100 logical child tasks represented in the durable SQLite `TaskStore`,
   routed to distinct specialists from the 100-agent registry (`SpecialistFactory`),
   while concurrent execution is bounded by `ResourceGovernor`.
4. Genuine inter-agent context passing (`context["upstream_outputs"]`), live
   `ModelAdapter` (`gemini-3.8-flash-high`) invocation, supervised command/test
   execution (`ProcessSupervisor`), and automatic disagreement / test-failure
   self-healing (`RUNNING -> FAILED -> RETRYING -> READY -> RUNNING -> VERIFYING -> SUCCEEDED`).
5. Safe checkpoint processing of live `CommandInbox` instructions (`ADD_CHILD_TASK`,
   `PAUSE_CURRENT_AND_SWITCH`, `CANCEL_AND_REPLACE`, `UPDATE_CONSTRAINTS`, etc.)
   between waves and subtasks.
6. Mandatory post-execution `EvidenceVerifier` check and episodic memory commit.
"""

from __future__ import annotations

import concurrent.futures
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agents.AGI_1_7.ecosystem.agent_registry.agent_contract import AgentContract
from agents.AGI_1_7.ecosystem.agent_registry.ecosystem_coordinator import EcosystemCoordinator
from agents.AGI_1_7.ecosystem.agent_registry.specialist_factory import SpecialistFactory
from ..capabilities.resource_snapshot import LiveResourceMetrics
from ..memory.omega_command_memory import OmegaCommandMemory
from ..process_supervision.process_supervisor import ProcessSupervisor
from ..process_supervision.sandbox_runner import (
    DisposableSandboxRunner,
    HighImpactApprovalGate,
    PathTraversalBlockedError,
    SandboxCleanupUnverifiedError,
    SandboxPolicy,
    SandboxPolicyViolationError,
    SandboxSecurityError,
    atomic_write_workspace_file,
    scan_untrusted_content,
    stage_candidate_outside_workspace,
    validate_relative_sandbox_path,
    validate_test_pattern,
)
from ..security.model_disclosure_policy import (
    DisclosureContext,
    ExternalProviderBlockedInLocalOnlyModeError,
    ModelDisclosureDeniedError,
    ModelDisclosurePolicy,
)
from ..task_control.task_manager import DurableTaskManager
from ..task_control.task_state_machine import TERMINAL_STATES, TaskState
from ..telemetry.token_economy import AdaptiveTokenController, TokenBudgetExceededError
from .resource_governor import (
    MAX_AGENT_SPECIALIZATIONS,
    MAX_LOGICAL_CHILD_TASKS,
    ResourceGovernor,
)


import hashlib
import re
import shutil
import sys


def _extract_python_code(text: str) -> str:
    """Extracts Python source code from a markdown fenced block or raw model response."""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip() + "\n"


def _is_valid_python_syntax(code_str: str) -> bool:
    """Returns True if code_str is non-empty and compiles as valid Python syntax."""
    stripped = code_str.strip()
    if not stripped:
        return False
    try:
        compile(stripped, "<generated>", "exec")
        return True
    except SyntaxError:
        return False


@dataclass
class SubtaskSpec:
    title: str
    description: str
    preferred_specialist_id: Optional[str] = None
    required_capabilities: List[str] = field(default_factory=list)
    depends_on_indices: List[int] = field(default_factory=list)
    queue_type: str = "light_in_process"
    priority: int = 50
    token_budget: int = 6000
    use_live_model: bool = False
    target_file_path: Optional[str] = None
    repair_target_file: Optional[str] = None
    fallback_code: Optional[str] = None
    repair_fallback_code: Optional[str] = None
    post_write_fault_injector: Optional[Callable[..., Dict[str, Any]]] = None
    executor_fn: Optional[Callable[[AgentContract, Dict[str, Any]], Dict[str, Any]]] = None
    verification_command: Optional[List[str]] = None
    verification_cwd: Optional[str] = None
    use_disposable_sandbox: bool = False
    repair_specialist_id: str = "swe_patch_minimizer"
    repair_fn: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None
    apply_approved_patch: bool = False


class HierarchicalOrchestrator:
    """Self-orchestrating multi-agent runtime with fast-path vs hierarchical DAG execution."""

    SUBSTANTIAL_KEYWORDS = (
        "multi-stage",
        "decompose",
        "hierarchical",
        "orchestrate",
        "campaign",
        "audit and implement",
        "end-to-end",
        "parallel subtasks",
        "comprehensive",
        "pipeline",
    )

    def __init__(
        self,
        *,
        task_manager: Optional[DurableTaskManager] = None,
        memory: Optional[OmegaCommandMemory] = None,
        governor: Optional[ResourceGovernor] = None,
        token_controller: Optional[AdaptiveTokenController] = None,
        specialist_factory: Optional[SpecialistFactory] = None,
        ecosystem_coordinator: Optional[EcosystemCoordinator] = None,
        model_adapter: Optional[Any] = None,
        supervisor: Optional[ProcessSupervisor] = None,
        sandbox_runner: Optional[DisposableSandboxRunner] = None,
        approval_gate: Optional[HighImpactApprovalGate] = None,
        disclosure_policy: Optional[ModelDisclosurePolicy] = None,
    ) -> None:
        self.task_manager = task_manager or DurableTaskManager()
        self.memory = memory or OmegaCommandMemory()
        self.governor = governor or ResourceGovernor()
        self.token_controller = token_controller or AdaptiveTokenController()
        self.specialist_factory = specialist_factory or SpecialistFactory()
        self.ecosystem_coordinator = ecosystem_coordinator or EcosystemCoordinator()
        self.supervisor = supervisor or ProcessSupervisor(task_manager=self.task_manager)
        if sandbox_runner is not None:
            self.sandbox_runner = sandbox_runner
            self.approval_gate = approval_gate or getattr(sandbox_runner, "approval_gate", None) or HighImpactApprovalGate()
        else:
            self.approval_gate = approval_gate or HighImpactApprovalGate()
            self.sandbox_runner = DisposableSandboxRunner(
                policy=SandboxPolicy.production(),
                approval_gate=self.approval_gate,
            )
        self.model_adapter = model_adapter
        self.disclosure_policy = disclosure_policy or getattr(
            self.model_adapter, "disclosure_policy", None
        ) or ModelDisclosurePolicy.production_strict()

    def get_security_diagnostics(self) -> Dict[str, Any]:
        """Returns safe diagnostic metadata for the orchestrator's runner and approval gate."""
        return {
            "orchestrator_instance_id": id(self),
            "sandbox_runner_instance_id": id(self.sandbox_runner),
            "approval_gate_instance_id": id(self.approval_gate),
            "disclosure_policy_instance_id": id(self.disclosure_policy),
            "effective_policy": self.sandbox_runner.policy.to_dict(),
            "disclosure_policy": {
                "mode": self.disclosure_policy.mode.value,
                "allow_workspace_model_disclosure": self.disclosure_policy.allow_workspace_model_disclosure,
                "local_only": self.disclosure_policy.local_only,
            },
            "sandbox_diagnostics": self.sandbox_runner.get_security_diagnostics(),
        }

    def build_code_and_test_subtasks(
        self,
        *,
        title: str,
        prompt: str,
        code_task_dir: str | Path,
        module_filename: str = "token_bucket.py",
        test_filename: str = "test_token_bucket.py",
        inject_deliberate_test_failure: bool = False,
        fallback_module_code: Optional[str] = None,
        fallback_test_code: Optional[str] = None,
        adaptive_reuse_existing_tests: bool = True,
        apply_approved_patch: bool = False,
        allow_workspace_model_disclosure: bool = False,
    ) -> List[SubtaskSpec]:
        """Builds a 3-specialist live-model coding + unit-testing + self-healing DAG."""
        ws_raw = Path(code_task_dir)
        if ws_raw.exists() and ws_raw.is_symlink():
            raise PathTraversalBlockedError(f"Symlink workspace root blocked: {code_task_dir}")
        ws = ws_raw.resolve()
        ws.mkdir(parents=True, exist_ok=True)

        # Enforce path containment and test pattern validation BEFORE reading any file or calling any model
        module_path = validate_relative_sandbox_path(ws, module_filename, require_py_extension=True)
        test_path = validate_relative_sandbox_path(ws, test_filename, require_py_extension=True)
        validate_test_pattern(test_path.name)
        module_stem = module_path.stem

        # Evaluate model disclosure authorization before injecting workspace files into model prompts
        has_workspace_content = bool(module_path.exists() or len(list(ws.glob("test_*.py"))) > 0)
        eff_disclosure = bool(
            allow_workspace_model_disclosure
            or getattr(self.disclosure_policy, "allow_workspace_model_disclosure", False)
        )
        if has_workspace_content and not eff_disclosure:
            ctx = DisclosureContext(
                task_id=title,
                agent_id="orchestrator",
                workspace_root=ws,
                target_files=[module_filename] + [tf.name for tf in ws.glob("test_*.py")],
                has_workspace_content=True,
                is_external_provider=True,
                provider_name="gemini-3.8-flash-high",
                operation_type="build_subtasks_prompt_assembly",
            )
            decision = self.disclosure_policy.evaluate(ctx)
            eff_disclosure = decision.authorized

        existing_source_block = ""
        if eff_disclosure and not self.approval_gate.block_workspace_mutations and module_path.exists():
            try:
                existing_src = module_path.read_text(encoding="utf-8")
                if existing_src.strip():
                    existing_source_block = (
                        f"\n\nEXISTING `{module_filename}` IN WORKSPACE (inspect and fix/complete as needed):\n"
                        f"```python\n{existing_src}\n```"
                    )
            except Exception:
                pass

        existing_test_files: List[Path] = []
        existing_tests_snippets: List[str] = []
        for tf in sorted(ws.glob("test_*.py")):
            if tf.is_symlink():
                raise PathTraversalBlockedError(f"Symlink test file blocked in workspace: {tf}")
            if tf.is_file():
                validate_relative_sandbox_path(ws, tf.name, require_py_extension=True)
                existing_test_files.append(tf)
                if eff_disclosure and not self.approval_gate.block_workspace_mutations:
                    try:
                        t_content = tf.read_text(encoding="utf-8", errors="replace")
                        if t_content.strip():
                            existing_tests_snippets.append(f"# {tf.name}\n{t_content}")
                    except Exception:
                        pass

        existing_tests_block = ""
        if existing_tests_snippets:
            existing_tests_block = (
                "\n\nEXISTING WORKSPACE UNIT TESTS (all tested methods, signatures, and return structures MUST be satisfied):\n"
                "```python\n" + "\n\n".join(existing_tests_snippets) + "\n```"
            )

        reuse_existing_tests_in_stage3 = bool(
            adaptive_reuse_existing_tests
            and len(existing_test_files) > 0
            and not inject_deliberate_test_failure
        )

        def _inject_deliberate_fault(
            _target: Path,
            staged_candidates: Optional[Dict[str, Dict[str, Any]]] = None,
        ) -> Dict[str, Any]:
            staged_mod = staged_candidates.get(str(module_path)) if isinstance(staged_candidates, dict) else None
            if not inject_deliberate_test_failure or (staged_mod is None and not module_path.exists()):
                return {"injected": False}
            self.approval_gate.check_preflight_access(
                workspace_root=ws,
                target_path=module_path,
                explicit_approval=apply_approved_patch,
                operation="deliberate_fault_injection",
            )
            original = (
                str(staged_mod["content"])
                if staged_mod is not None
                else module_path.read_text(encoding="utf-8")
            )
            lines = original.splitlines()
            mutated_lines: List[str] = []
            mutation_desc = ""
            mutated_flag = False
            for line in lines:
                stripped = line.lstrip()
                if not mutated_flag and not stripped.startswith("#") and not stripped.startswith(('"""', "'''")):
                    if "self.tokens >= tokens" in line:
                        line = line.replace("self.tokens >= tokens", "self.tokens > tokens", 1)
                        mutation_desc = "Mutated `self.tokens >= tokens` to strict `>` (breaks exact-capacity token acquisition)"
                        mutated_flag = True
                    elif "<=" in line and ("if " in line or "while " in line or "return " in line):
                        line = line.replace("<=", "<", 1)
                        mutation_desc = "Mutated executable `<=` boundary comparison to strict `<`"
                        mutated_flag = True
                    elif ">=" in line and ("if " in line or "while " in line or "return " in line):
                        line = line.replace(">=", ">", 1)
                        mutation_desc = "Mutated executable `>=` boundary comparison to strict `>`"
                        mutated_flag = True
                mutated_lines.append(line)
            if not mutated_flag:
                mutated_lines.append("raise RuntimeError('Deliberate injected fault')")
                mutation_desc = "Appended runtime fault trigger"
            mutated = "\n".join(mutated_lines) + "\n"
            rel_mod = module_path.relative_to(ws)
            ext_fault_dir, _staged_fault_file, staged_fault_sha = stage_candidate_outside_workspace(
                ws,
                rel_mod,
                mutated,
                stage_label="deliberate_fault_injection",
            )
            shutil.rmtree(ext_fault_dir, ignore_errors=True)
            if isinstance(staged_candidates, dict):
                staged_candidates[str(module_path)] = {
                    "ws_root": ws,
                    "target_path": module_path,
                    "rel_path": rel_mod,
                    "content": mutated,
                    "sha256": staged_fault_sha,
                    "stage": "deliberate_fault_injection",
                    "apply_approved_patch": apply_approved_patch,
                }
            return {
                "injected": True,
                "target_file": str(module_path),
                "staged_outside_workspace": True,
                "faulty_file_sha256": staged_fault_sha,
                "mutation_description": mutation_desc,
            }

        return [
            SubtaskSpec(
                title=f"{title} — Stage 1: Architecture & Edge-Case Specification",
                description=(
                    f"Specify the exact Python class/function signatures, type annotations, and edge-case invariants for `{module_filename}`: {prompt} "
                    f"Ensure all methods and return formats required by existing workspace tests are included, and invalid arguments raise `ValueError`. "
                    f"Keep your specification concise (4-6 bullet points)."
                    f"{existing_source_block}"
                    f"{existing_tests_block}"
                ),
                preferred_specialist_id="plan_systems_architect",
                depends_on_indices=[],
                queue_type="model_call",
                token_budget=16000,
                use_live_model=True,
                verification_cwd=str(ws),
                apply_approved_patch=apply_approved_patch,
            ),
            SubtaskSpec(
                title=f"{title} — Stage 2: Live Model Python Implementation (`{module_filename}`)",
                description=(
                    f"Implement the complete Python module `{module_filename}` fulfilling `{prompt}` and the upstream specification. "
                    f"Ensure all methods/contracts in existing workspace unit tests and `ValueError` input validations are implemented accurately. "
                    f"Return ONLY the complete Python code inside a ```python ... ``` block."
                    f"{existing_source_block}"
                    f"{existing_tests_block}"
                ),
                preferred_specialist_id="swe_python_runtime_engineer",
                depends_on_indices=[0],
                queue_type="model_call",
                token_budget=20000,
                use_live_model=True,
                target_file_path=str(module_path),
                fallback_code=fallback_module_code,
                verification_cwd=str(ws),
                apply_approved_patch=apply_approved_patch,
            ),
            SubtaskSpec(
                title=f"{title} — Stage 3: Live Model Unit Test Generation, Execution & Self-Healing (`{test_filename}`)",
                description=(
                    f"Execute existing repository unit tests in disposable sandbox and escalate to `{module_filename}` self-healing repair if any assertion fails."
                    if reuse_existing_tests_in_stage3
                    else (
                        f"Write a Python `unittest` suite `{test_filename}` that imports from `{module_stem}` and tests "
                        f"normal operation, boundary conditions, and exception handling (`ValueError`) as specified in the upstream implementation. "
                        f"Return ONLY the complete `{test_filename}` code inside a ```python ... ``` block."
                    )
                ),
                preferred_specialist_id="qa_unit_suite_runner",
                depends_on_indices=[0, 1],
                queue_type="light_in_process" if reuse_existing_tests_in_stage3 else "model_call",
                token_budget=24000,
                use_live_model=not reuse_existing_tests_in_stage3,
                target_file_path=None if reuse_existing_tests_in_stage3 else str(test_path),
                repair_target_file=str(module_path),
                fallback_code=fallback_test_code,
                repair_fallback_code=fallback_module_code,
                post_write_fault_injector=_inject_deliberate_fault if inject_deliberate_test_failure else None,
                verification_command=None,
                verification_cwd=str(ws),
                use_disposable_sandbox=True,
                repair_specialist_id="swe_patch_minimizer",
                apply_approved_patch=apply_approved_patch,
            ),
        ]

    def _run_sandboxed_workspace_tests(
        self,
        verification_cwd: str | Path,
        sandbox_id: str,
        staged_candidates: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Executes workspace Python unit tests inside the disposable container / ephemeral sandbox."""
        ws_raw = Path(verification_cwd)
        if ws_raw.exists() and ws_raw.is_symlink():
            raise PathTraversalBlockedError(f"Symlink verification_cwd blocked: {verification_cwd}")
        ws_dir = ws_raw.resolve()
        files_map: Dict[str, str] = {}
        if ws_dir.is_dir():
            for py_file in sorted(ws_dir.glob("*.py")):
                if py_file.is_symlink():
                    raise PathTraversalBlockedError(f"Symlink Python file blocked in workspace: {py_file}")
                if py_file.is_file():
                    validate_relative_sandbox_path(ws_dir, py_file.name, require_py_extension=True)
                    files_map[py_file.name] = py_file.read_text(encoding="utf-8", errors="replace")
        if staged_candidates:
            for cand_info in staged_candidates.values():
                cand_ws = cand_info.get("ws_root")
                if cand_ws is not None and Path(cand_ws).resolve() == ws_dir:
                    rel_str = str(cand_info["rel_path"]).replace("\\", "/")
                    validate_relative_sandbox_path(ws_dir, rel_str, require_py_extension=True)
                    files_map[rel_str] = str(cand_info["content"])
        sbx_res = self.sandbox_runner.run_python_unittest_sandbox(
            files=files_map,
            test_pattern="test_*.py",
            sandbox_id=sandbox_id,
        )
        if not sbx_res.cleanup_verified:
            raise SandboxCleanupUnverifiedError(
                f"Disposable sandbox cleanup unverified for {sandbox_id} "
                f"(filesystem_cleanup_verified={sbx_res.filesystem_cleanup_verified}, "
                f"container_cleanup_verified={sbx_res.container_cleanup_verified})"
            )
        return {
            "passed": sbx_res.passed,
            "exit_code": sbx_res.exit_code,
            "timed_out": sbx_res.timed_out,
            "stdout": sbx_res.stdout,
            "stderr": sbx_res.stderr,
            "notification_id": sbx_res.sandbox_id,
            "isolation_backend": sbx_res.isolation_backend,
            "container_image": sbx_res.container_image,
            "network_disabled": sbx_res.network_disabled,
            "verified_network_isolated": getattr(sbx_res, "verified_network_isolated", False),
            "cleanup_verified": sbx_res.cleanup_verified,
            "filesystem_cleanup_verified": sbx_res.filesystem_cleanup_verified,
            "container_cleanup_verified": sbx_res.container_cleanup_verified,
            "duration_sec": sbx_res.duration_sec,
        }

    def requires_hierarchical_planning(
        self,
        prompt: str,
        explicit_subtasks: Optional[Sequence[SubtaskSpec]] = None,
        force_hierarchical: bool = False,
    ) -> bool:
        if force_hierarchical:
            return True
        if explicit_subtasks and len(explicit_subtasks) > 1:
            return True
        lower = prompt.lower()
        if len(prompt) >= 450:
            return True
        if sum(1 for kw in self.SUBSTANTIAL_KEYWORDS if kw in lower) >= 1:
            return True
        return False

    def execute_mission(
        self,
        *,
        title: str,
        prompt: str,
        task_id: Optional[str] = None,
        subtasks: Optional[Sequence[SubtaskSpec]] = None,
        force_hierarchical: bool = False,
        use_live_model: Optional[bool] = None,
        code_task_dir: Optional[str | Path] = None,
        module_filename: str = "token_bucket.py",
        test_filename: str = "test_token_bucket.py",
        inject_deliberate_test_failure: bool = False,
        apply_approved_patch: bool = False,
        allow_workspace_model_disclosure: bool = False,
        custom_subtask_hook: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        simulated_resource_snapshot: Optional[LiveResourceMetrics] = None,
        max_wall_clock_sec: Optional[float] = None,
        max_mission_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Executes a mission via Fast Path or Planned Hierarchical Delegation.

        When `code_task_dir` is provided and `subtasks is None`, automatically builds
        and runs the complete 3-specialist live-model coding, unit-testing, and
        self-healing repair workflow.
        """
        started_at = time.time()
        root_id = task_id or f"MISSION-{int(started_at * 1000)}-{uuid.uuid4().hex[:6]}"
        is_hierarchical = force_hierarchical or (subtasks is not None and len(subtasks) > 1) or (code_task_dir is not None)

        try:
            if code_task_dir is not None and subtasks is None:
                subtasks = self.build_code_and_test_subtasks(
                    title=title,
                    prompt=prompt,
                    code_task_dir=code_task_dir,
                    module_filename=module_filename,
                    test_filename=test_filename,
                    inject_deliberate_test_failure=inject_deliberate_test_failure,
                    apply_approved_patch=apply_approved_patch,
                    allow_workspace_model_disclosure=allow_workspace_model_disclosure,
                )
                force_hierarchical = True

            effective_live_model = (
                use_live_model
                if use_live_model is not None
                else bool(self.model_adapter is not None and subtasks is None)
            )

            # Step 1: Mandatory pre-planning memory retrieval
            retrieved_memory = self.memory.retrieve_before_planning(
                task_id=root_id,
                task_description=f"{title}: {prompt}",
            )

            is_hierarchical = self.requires_hierarchical_planning(
                prompt=prompt,
                explicit_subtasks=subtasks,
                force_hierarchical=force_hierarchical,
            )

            # Create root task in durable SQLite store
            tier = "COMPLEX" if is_hierarchical else "SIMPLE"
            budget_info = self.token_controller.allocate_budget(
                task_id=root_id,
                tier=tier,
                custom_task_budget=max_mission_tokens,
            )

            existing = self.task_manager.store.get_task(root_id)
            if not existing:
                self.task_manager.create_task(
                    task_id=root_id,
                    title=title,
                    description=prompt,
                    specialist_role="plan_mission_decomposer" if is_hierarchical else "swe_python_runtime_engineer",
                    token_budget=budget_info["max_task_tokens"],
                    metadata={
                        "execution_path": "HIERARCHICAL_DAG" if is_hierarchical else "DIRECT_FAST_PATH",
                        "use_live_model": effective_live_model,
                        "memory_retrieval_audit_id": retrieved_memory["audit_id"],
                        "retrieved_memory_ids": retrieved_memory["retrieved_entry_ids"],
                    },
                )

            self.task_manager.transition(root_id, TaskState.PLANNED, reason="Completed pre-planning memory lookup & classification")
            self.task_manager.transition(root_id, TaskState.QUEUED, reason="Queued root mission")
            self.task_manager.transition(root_id, TaskState.READY, reason="Root mission ready")
            self.task_manager.transition(root_id, TaskState.RUNNING, reason="Root mission execution started")

            if max_wall_clock_sec is not None and (time.time() - started_at) > max_wall_clock_sec:
                raise TimeoutError(f"Mission {root_id} exceeded max_wall_clock_sec ({max_wall_clock_sec}s) before execution")

            if not is_hierarchical:
                return self._execute_fast_path(
                    root_id=root_id,
                    title=title,
                    prompt=prompt,
                    retrieved_memory=retrieved_memory,
                    started_at=started_at,
                    use_live_model=effective_live_model,
                )

            return self._execute_hierarchical_dag(
                root_id=root_id,
                title=title,
                prompt=prompt,
                retrieved_memory=retrieved_memory,
                explicit_subtasks=subtasks,
                use_live_model=effective_live_model,
                apply_approved_patch=apply_approved_patch,
                custom_subtask_hook=custom_subtask_hook,
                simulated_resource_snapshot=simulated_resource_snapshot,
                started_at=started_at,
                max_wall_clock_sec=max_wall_clock_sec,
            )
        except Exception as exc:
            exc_name = type(exc).__name__
            if "BudgetExceeded" in exc_name:
                term_outcome = "BUDGET_EXCEEDED"
            elif any(
                k in exc_name
                for k in (
                    "DirectiveZeroViolation",
                    "Sandbox",
                    "Policy",
                    "PathTraversal",
                    "UntrustedContent",
                    "HighImpactAction",
                    "InvalidTestPattern",
                )
            ):
                term_outcome = "BLOCKED_BY_POLICY"
            elif "Timeout" in exc_name:
                term_outcome = "TIMED_OUT"
            elif "Cancel" in exc_name:
                term_outcome = "CANCELLED"
            else:
                term_outcome = "FAILED"
            try:
                cur_rec = self.task_manager.store.get_task(root_id)
                if cur_rec and TaskState(cur_rec["state"]) not in TERMINAL_STATES:
                    self.task_manager.transition(
                        root_id,
                        TaskState.CANCELED if term_outcome == "CANCELLED" else TaskState.FAILED,
                        reason=f"Mission terminated with {term_outcome}: {exc}",
                        error={"exception_type": exc_name, "message": str(exc)},
                    )
            except Exception:
                pass
            return {
                "mission_id": root_id,
                "execution_path": "HIERARCHICAL_DAG" if is_hierarchical else "DIRECT_FAST_PATH",
                "final_state": TaskState.FAILED.value,
                "terminal_outcome": term_outcome,
                "error": {"exception_type": exc_name, "message": str(exc)},
                "memory_retrieval": locals().get("retrieved_memory"),
                "duration_sec": round(time.time() - started_at, 4),
            }

    def _execute_fast_path(
        self,
        *,
        root_id: str,
        title: str,
        prompt: str,
        retrieved_memory: Dict[str, Any],
        started_at: float,
        use_live_model: bool = False,
    ) -> Dict[str, Any]:
        routed = self.specialist_factory.router.route(task_description=prompt, top_k=1)[0]
        custom_exec = (
            self._build_live_model_executor(root_id=root_id, child_id=root_id)
            if (use_live_model and self.model_adapter is not None)
            else None
        )
        specialist = self.specialist_factory.instantiate(routed["agent_id"], custom_executor=custom_exec)

        out = specialist.run(
            {
                "task_id": root_id,
                "task_prompt": prompt,
                "context": {
                    "mode": "DIRECT_FAST_PATH",
                    "retrieved_memory_count": len(retrieved_memory["retrieved_entry_ids"]),
                },
            }
        )

        if custom_exec is None:
            self.token_controller.record_usage(
                task_id=root_id,
                agent_id=routed["agent_id"],
                prompt_text=prompt,
                response_text=out["output_summary"],
                cwd_used=self.token_controller.get_execution_cwd(is_benchmark_or_single_shot=True),
            )

        self.task_manager.save_checkpoint(
            root_id,
            step_index=1,
            state_payload={"fast_path_output": out},
        )
        self.task_manager.transition(root_id, TaskState.VERIFYING, reason="Verifying fast-path result")
        self.task_manager.transition(
            root_id,
            TaskState.SUCCEEDED,
            reason="Fast-path execution verified",
            result=out,
        )

        self.memory.store_compressed_episode(
            subject_key=f"episode:{root_id}",
            raw_observation=f"FastPath mission '{title}' ({root_id}) succeeded via {routed['agent_id']}: {out['output_summary']}",
            source_task_id=root_id,
        )

        verified_flag = bool(out.get("task_correctness_verified") is True)
        return {
            "mission_id": root_id,
            "execution_path": "DIRECT_FAST_PATH",
            "final_state": TaskState.SUCCEEDED.value,
            "terminal_outcome": "SUCCEEDED_AND_VERIFIED" if verified_flag else "SUCCEEDED_UNVERIFIED",
            "logical_children_created": 0,
            "specialist_used": routed["agent_id"],
            "memory_retrieval": retrieved_memory,
            "output": out,
            "duration_sec": round(time.time() - started_at, 4),
        }

    def _build_default_subtasks(self, title: str, prompt: str, use_live_model: bool = False) -> List[SubtaskSpec]:
        q_type = "model_call" if use_live_model else "light_in_process"
        return [
            SubtaskSpec(
                title=f"{title} - Decomposition & Architecture",
                description=f"Decompose mission and define interfaces for: {prompt}",
                preferred_specialist_id="plan_mission_decomposer",
                depends_on_indices=[],
                queue_type=q_type,
                use_live_model=use_live_model,
            ),
            SubtaskSpec(
                title=f"{title} - Grounded Evidence & Context Synthesis",
                description=f"Synthesize evidence and memory constraints for: {prompt}",
                preferred_specialist_id="res_citation_auditor",
                depends_on_indices=[0],
                queue_type=q_type,
                use_live_model=use_live_model,
            ),
            SubtaskSpec(
                title=f"{title} - Core Implementation & Execution",
                description=f"Execute primary engineering deliverables for: {prompt}",
                preferred_specialist_id="swe_python_runtime_engineer",
                depends_on_indices=[0],
                queue_type=q_type,
                use_live_model=use_live_model,
            ),
            SubtaskSpec(
                title=f"{title} - Verification & Telemetry Reconciliation",
                description=f"Verify outputs, checksums, and ledger reconciliation for: {prompt}",
                preferred_specialist_id="qa_claim_to_evidence_verifier",
                depends_on_indices=[1, 2],
                queue_type=q_type,
                use_live_model=use_live_model,
            ),
        ]

    def _resolve_validated_workspace_target(
        self,
        raw_target_path: str | Path,
        verification_cwd: Optional[str | Path] = None,
    ) -> Tuple[Path, Path]:
        """Validates that `raw_target_path` is a contained `.py` file inside `ws_root`."""
        cand_path = Path(raw_target_path)
        if verification_cwd:
            ws_raw = Path(verification_cwd)
            if ws_raw.exists() and ws_raw.is_symlink():
                raise PathTraversalBlockedError(f"Symlink workspace root blocked: {verification_cwd}")
            ws_root = ws_raw.resolve()
            if cand_path.is_absolute():
                try:
                    rel_part = cand_path.resolve().relative_to(ws_root)
                except ValueError as exc:
                    raise PathTraversalBlockedError(
                        f"Target path '{raw_target_path}' escapes workspace root '{ws_root}'"
                    ) from exc
                validated = validate_relative_sandbox_path(ws_root, rel_part, require_py_extension=True)
            else:
                validated = validate_relative_sandbox_path(ws_root, cand_path, require_py_extension=True)
            return ws_root, validated

        ws_root = cand_path.resolve().parent
        validated = validate_relative_sandbox_path(ws_root, cand_path.name, require_py_extension=True)
        return ws_root, validated

    def _build_live_model_executor(
        self,
        root_id: str,
        child_id: str,
        sp_spec: Optional[SubtaskSpec] = None,
        staged_candidates: Optional[Dict[str, Dict[str, Any]]] = None,
        apply_approved_patch: bool = False,
    ) -> Callable[[AgentContract, Dict[str, Any]], Dict[str, Any]]:
        """Creates a custom executor that invokes `gemini-3.8-flash-high` via `ModelAdapter`."""

        def _exec(contract: AgentContract, payload: Dict[str, Any]) -> Dict[str, Any]:
            if self.model_adapter is None:
                raise RuntimeError(f"use_live_model=True requested for {child_id}, but ModelAdapter is not configured")
            eff_approval = bool(apply_approved_patch or getattr(sp_spec, "apply_approved_patch", False))
            if sp_spec and sp_spec.target_file_path:
                # Validate target file path containment and preflight policy BEFORE invoking the model
                pre_ws_root, pre_target = self._resolve_validated_workspace_target(
                    sp_spec.target_file_path,
                    sp_spec.verification_cwd,
                )
                self.approval_gate.check_preflight_access(
                    workspace_root=pre_ws_root,
                    target_path=pre_target,
                    explicit_approval=eff_approval,
                    operation="orchestrator_stage_write_precheck",
                )

            upstream = payload.get("context", {}).get("upstream_outputs", {})
            upstream_summary = ""
            if upstream:
                upstream_summary = "\n\nUPSTREAM SPECIALIST OUTPUTS:\n" + json.dumps(
                    {
                        k: {
                            "agent_id": v.get("agent_id"),
                            "output_summary": v.get("output_summary"),
                            "artifacts": v.get("artifacts"),
                        }
                        for k, v in upstream.items()
                    },
                    indent=2,
                    default=str,
                )
            coord = self.ecosystem_coordinator.build_coordination_railings(contract, is_repair=False)
            mem_guardrails = self.memory.build_compact_memory_prompt_block(
                f"{contract.agent_id} {payload.get('task_prompt', '')}"
            )
            guardrail_section = f"\n{mem_guardrails}\n" if mem_guardrails else "\n"
            full_prompt = (
                f"You are AGI 1.7 Embedded Specialist `{contract.agent_id}` ({contract.display_name}, Family: {contract.family}).\n"
                f"Primary Capabilities: {', '.join(contract.primary_capabilities)}\n"
                f"{coord['railings_prompt_block']}"
                f"{guardrail_section}"
                f"IMPORTANT: Do NOT call any tools, shell commands, or file views. Respond directly in this turn.\n"
                f"Task ({child_id}): {payload['task_prompt']}"
                f"{upstream_summary}"
            )
            model_res = self.model_adapter.invoke(
                task_id=root_id,
                child_task_id=child_id,
                prompt=full_prompt,
                agent_id=contract.agent_id,
                effort="high",
                is_benchmark_or_single_shot=True,
                tier="COMPLEX",
            )
            result_dict: Dict[str, Any] = {
                "execution_origin": "LIVE_MODEL_ADAPTER",
                "ecosystem_coordination": {
                    "agency_profile_matched": coord["agency_profile_matched"],
                    "mcp_servers_bound": coord["mcp_servers_bound"],
                    "plugins_applied": coord["plugins_applied"],
                    "skills_applied": coord["skills_applied"],
                },
                "memory_guardrails_injected": bool(mem_guardrails),
                "fallback_used": False,
                "fallback_reason": None,
                "analysis": model_res["response_text"],
                "model_invoked": model_res["model"],
                "model_status": model_res["status"],
                "model_duration_sec": model_res["duration_sec"],
                "token_usage": model_res["token_usage"],
                "notification_id": model_res["notification_id"],
                "stdout_log_path": model_res.get("stdout_log_path"),
                "artifact_verification_passed": None,
                "task_correctness_verified": None,
            }
            if sp_spec and sp_spec.target_file_path:
                ws_root, target_path = self._resolve_validated_workspace_target(
                    sp_spec.target_file_path,
                    sp_spec.verification_cwd,
                )
                rel_target = target_path.relative_to(ws_root)
                extracted_code = _extract_python_code(model_res["response_text"])
                if not _is_valid_python_syntax(extracted_code) and sp_spec.fallback_code:
                    extracted_code = sp_spec.fallback_code
                    result_dict["fallback_used"] = True
                    result_dict["fallback_reason"] = (
                        f"Model response had invalid/empty Python syntax (status={model_res['status']}, "
                        f"exit_code={model_res['exit_code']}); deterministic fallback applied."
                    )
                    result_dict["execution_origin"] = "DETERMINISTIC_FALLBACK_AFTER_MODEL_FAILURE"
                scan_untrusted_content(extracted_code, source_label=f"generated:{target_path.name}")
                ext_stage_dir, staged_file, staged_sha256 = stage_candidate_outside_workspace(
                    ws_root,
                    rel_target,
                    extracted_code,
                    stage_label=child_id,
                )
                try:
                    self.approval_gate.validate_workspace_path_containment(
                        workspace_root=ws_root,
                        target_path=target_path,
                    )
                    staged_bytes = staged_file.read_bytes()
                    actual_staged_sha = hashlib.sha256(staged_bytes).hexdigest()
                finally:
                    shutil.rmtree(ext_stage_dir, ignore_errors=True)
                expected_sha256 = hashlib.sha256(extracted_code.encode("utf-8")).hexdigest()
                sha_matches = (
                    len(staged_bytes) > 0
                    and actual_staged_sha == expected_sha256
                    and actual_staged_sha == staged_sha256
                )
                if not sha_matches:
                    raise RuntimeError(
                        f"Staged artifact SHA-256 verification failed for {target_path}: "
                        f"expected={expected_sha256}, actual={actual_staged_sha}"
                    )
                if staged_candidates is not None:
                    staged_candidates[str(target_path)] = {
                        "ws_root": ws_root,
                        "target_path": target_path,
                        "rel_path": rel_target,
                        "content": extracted_code,
                        "sha256": staged_sha256,
                        "stage": child_id,
                        "apply_approved_patch": eff_approval,
                    }
                result_dict["staged_outside_workspace"] = True
                result_dict["staged_candidate_sha256"] = staged_sha256
                result_dict["written_file_path"] = str(target_path)
                result_dict["staged_target_file_path"] = str(target_path)
                result_dict["patch_applied_to_workspace"] = False
                result_dict["clean_generated_code"] = extracted_code
                result_dict["clean_file_sha256"] = staged_sha256
                result_dict["expected_file_sha256"] = expected_sha256
                result_dict["artifact_verification_passed"] = sha_matches
                if sp_spec.post_write_fault_injector is not None:
                    try:
                        fault_meta = sp_spec.post_write_fault_injector(target_path, staged_candidates)
                    except TypeError:
                        fault_meta = sp_spec.post_write_fault_injector(target_path)
                    result_dict["deliberate_fault_injected"] = fault_meta
                    if isinstance(fault_meta, dict) and fault_meta.get("faulty_file_sha256"):
                        result_dict["faulty_file_sha256"] = fault_meta["faulty_file_sha256"]
                    elif staged_candidates is not None and str(target_path) in staged_candidates:
                        result_dict["faulty_file_sha256"] = staged_candidates[str(target_path)]["sha256"]
            return result_dict

        return _exec

    def _default_live_model_repair(
        self,
        *,
        root_id: str,
        child_id: str,
        sp_spec: SubtaskSpec,
        failed_result: Dict[str, Any],
        failure_details: Dict[str, Any],
        staged_candidates: Optional[Dict[str, Dict[str, Any]]] = None,
        apply_approved_patch: bool = False,
    ) -> Dict[str, Any]:
        """Invokes `ModelAdapter.invoke()` with `sp_spec.repair_specialist_id` to patch failing code."""
        raw_repair_target = (
            sp_spec.repair_target_file
            or sp_spec.target_file_path
            or failed_result.get("artifacts", {}).get("written_file_path", "")
        )
        ws_root, repair_file = self._resolve_validated_workspace_target(
            raw_repair_target,
            sp_spec.verification_cwd,
        )
        eff_approval = bool(apply_approved_patch or getattr(sp_spec, "apply_approved_patch", False))
        self.approval_gate.check_preflight_access(
            workspace_root=ws_root,
            target_path=repair_file,
            explicit_approval=eff_approval,
            operation="orchestrator_self_healing_repair_precheck",
        )
        disk_bytes = repair_file.read_bytes() if repair_file.is_file() else None
        disk_sha256 = hashlib.sha256(disk_bytes).hexdigest() if disk_bytes is not None else None
        staged_existing = staged_candidates.get(str(repair_file)) if isinstance(staged_candidates, dict) else None
        if staged_existing is not None:
            broken_code = str(staged_existing["content"])
            original_sha256 = str(staged_existing["sha256"])
        else:
            broken_code = disk_bytes.decode("utf-8", errors="replace") if disk_bytes is not None else ""
            original_sha256 = disk_sha256

        # Step: Authorize disclosure BEFORE reading test files into prompt or constructing repair prompt
        has_workspace_content = bool(broken_code.strip() or (ws_root.is_dir() and any(ws_root.glob("test_*.py"))))
        ctx = DisclosureContext(
            task_id=root_id,
            agent_id=sp_spec.repair_specialist_id,
            workspace_root=ws_root,
            target_files=[repair_file.name],
            has_workspace_content=has_workspace_content,
            is_external_provider=bool(getattr(self.model_adapter, "mock_provider", None) is None or getattr(self.model_adapter.mock_provider, "is_external", False)),
            provider_name=getattr(getattr(self.model_adapter, "config", None), "model_name", "gemini-3.8-flash-high"),
            operation_type="self_healing_repair_model_invocation",
        )
        self.disclosure_policy.authorize_or_raise(ctx)

        stderr_trace = failure_details.get("stderr") or failure_details.get("stdout") or str(failure_details)
        try:
            repair_contract = self.specialist_factory.get_contract(sp_spec.repair_specialist_id)
        except Exception:
            repair_contract = self.specialist_factory.get_contract("swe_patch_minimizer")
        coord = self.ecosystem_coordinator.build_coordination_railings(repair_contract, is_repair=True)
        mem_guardrails = self.memory.build_compact_memory_prompt_block(
            f"{repair_file.name} {stderr_trace[:200]}"
        )
        guardrail_section = f"\n{mem_guardrails}\n" if mem_guardrails else "\n"
        test_files_block = ""
        test_map: Dict[str, str] = {}
        if ws_root.is_dir():
            for tf in sorted(ws_root.glob("test_*.py")):
                if tf.is_symlink():
                    raise PathTraversalBlockedError(f"Symlink test file blocked during repair: {tf}")
                if tf.is_file():
                    validate_relative_sandbox_path(ws_root, tf.name, require_py_extension=True)
                    try:
                        test_map[tf.name] = tf.read_text(encoding="utf-8")
                    except Exception:
                        pass
        if staged_candidates:
            for cand_info in staged_candidates.values():
                cand_ws = cand_info.get("ws_root")
                if cand_ws is not None and Path(cand_ws).resolve() == ws_root:
                    c_name = Path(str(cand_info.get("rel_path", ""))).name
                    if c_name.startswith("test_") and c_name.endswith(".py"):
                        test_map[c_name] = str(cand_info["content"])
        if test_map:
            test_snippets = [f"# {k}\n{v}" for k, v in sorted(test_map.items())]
            test_files_block = "\n\nWORKSPACE TEST FILES:\n```python\n" + "\n\n".join(test_snippets) + "\n```"

        repair_prompt = (
            f"You are AGI 1.7 Embedded Specialist `{sp_spec.repair_specialist_id}` (Minimal Diff & Root-Cause Patch Engineer).\n"
            f"{coord['railings_prompt_block']}"
            f"{guardrail_section}"
            f"IMPORTANT: Do NOT call any tools or shell commands. Return ONLY the complete corrected Python file for `{repair_file.name}` inside a ```python ... ``` block.\n\n"
            f"BROKEN PYTHON FILE (`{repair_file.name}`):\n```python\n{broken_code}\n```"
            f"{test_files_block}\n\n"
            f"UNITTEST FAILURE OUTPUT (exit_code={failure_details.get('exit_code')}):\n```text\n{stderr_trace}\n```\n\n"
            f"Fix all bugs causing the test failures and return the complete corrected `{repair_file.name}` in a ```python ... ``` fenced code block."
        )

        model_res = self.model_adapter.invoke(
            task_id=root_id,
            child_task_id=f"{child_id}-REPAIR",
            prompt=repair_prompt,
            agent_id=sp_spec.repair_specialist_id,
            effort="high",
            is_benchmark_or_single_shot=True,
            tier="COMPLEX",
        )
        patched_code = _extract_python_code(model_res["response_text"])
        fallback_used = False
        fallback_reason = None
        repair_fallback = getattr(sp_spec, "repair_fallback_code", None) or sp_spec.fallback_code
        if not _is_valid_python_syntax(patched_code) and repair_fallback:
            patched_code = repair_fallback
            fallback_used = True
            fallback_reason = (
                f"Repair model response had invalid/empty Python syntax (status={model_res['status']}, "
                f"exit_code={model_res['exit_code']}); deterministic fallback applied."
            )
        repaired_sha256: Optional[str] = None
        expected_repaired_sha256: Optional[str] = None
        staged_repair_sha256: Optional[str] = None
        if repair_file.name and _is_valid_python_syntax(patched_code):
            scan_untrusted_content(patched_code, source_label=f"repair:{repair_file.name}")
            rel_repair = repair_file.relative_to(ws_root)
            ext_stage_dir, staged_file, staged_repair_sha256 = stage_candidate_outside_workspace(
                ws_root,
                rel_repair,
                patched_code,
                stage_label=f"{child_id}_repair",
            )
            try:
                self.approval_gate.validate_workspace_path_containment(
                    workspace_root=ws_root,
                    target_path=repair_file,
                )
                staged_rep_bytes = staged_file.read_bytes()
                repaired_sha256 = hashlib.sha256(staged_rep_bytes).hexdigest()
            finally:
                shutil.rmtree(ext_stage_dir, ignore_errors=True)
            expected_repaired_sha256 = hashlib.sha256(patched_code.encode("utf-8")).hexdigest()
            if repaired_sha256 != expected_repaired_sha256 or repaired_sha256 != staged_repair_sha256:
                raise RuntimeError(
                    f"Repair staged artifact SHA-256 mismatch for {repair_file}: "
                    f"expected={expected_repaired_sha256}, actual={repaired_sha256}"
                )
            if staged_candidates is not None:
                staged_candidates[str(repair_file)] = {
                    "ws_root": ws_root,
                    "target_path": repair_file,
                    "rel_path": rel_repair,
                    "content": patched_code,
                    "sha256": staged_repair_sha256,
                    "stage": f"{child_id}_repair",
                    "apply_approved_patch": eff_approval,
                }
        return {
            "execution_origin": "DETERMINISTIC_FALLBACK_AFTER_MODEL_FAILURE" if fallback_used else "LIVE_MODEL_ADAPTER",
            "ecosystem_coordination": {
                "agency_profile_matched": coord["agency_profile_matched"],
                "mcp_servers_bound": coord["mcp_servers_bound"],
                "plugins_applied": coord["plugins_applied"],
                "skills_applied": coord["skills_applied"],
            },
            "memory_guardrails_injected": bool(mem_guardrails),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "repair_specialist_id": sp_spec.repair_specialist_id,
            "model_invoked": model_res["model"],
            "model_status": model_res["status"],
            "model_duration_sec": model_res["duration_sec"],
            "token_usage": model_res["token_usage"],
            "notification_id": model_res["notification_id"],
            "stdout_log_path": model_res.get("stdout_log_path"),
            "staged_outside_workspace": True,
            "staged_candidate_sha256": staged_repair_sha256,
            "patch_applied_to_workspace": False,
            "repaired_file_path": str(repair_file),
            "repaired_file_sha256": repaired_sha256,
            "expected_repaired_file_sha256": expected_repaired_sha256,
            "pre_repair_file_sha256": original_sha256,
            "_rollback_bytes": disk_bytes,
            "_prev_staged_entry": staged_existing,
            "patched_code": patched_code,
        }

    def _execute_hierarchical_dag(
        self,
        *,
        root_id: str,
        title: str,
        prompt: str,
        retrieved_memory: Dict[str, Any],
        explicit_subtasks: Optional[Sequence[SubtaskSpec]],
        use_live_model: bool = False,
        apply_approved_patch: bool = False,
        custom_subtask_hook: Optional[Callable[[str, Dict[str, Any]], None]],
        simulated_resource_snapshot: Optional[LiveResourceMetrics],
        started_at: float,
        max_wall_clock_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        specs = (
            list(explicit_subtasks)
            if explicit_subtasks
            else self._build_default_subtasks(title, prompt, use_live_model=use_live_model)
        )
        if len(specs) > MAX_LOGICAL_CHILD_TASKS:
            raise ValueError(
                f"Requested {len(specs)} child tasks exceeds MAX_LOGICAL_CHILD_TASKS ({MAX_LOGICAL_CHILD_TASKS})"
            )

        # Pre-flight path containment and policy check across all subtasks BEFORE any model or sandbox call
        for sp in specs:
            eff_sp_approval = bool(apply_approved_patch or getattr(sp, "apply_approved_patch", False))
            for candidate_target in (sp.target_file_path, sp.repair_target_file):
                if candidate_target:
                    try:
                        pre_ws_root, pre_target = self._resolve_validated_workspace_target(
                            candidate_target,
                            sp.verification_cwd,
                        )
                        self.approval_gate.check_preflight_access(
                            workspace_root=pre_ws_root,
                            target_path=pre_target,
                            explicit_approval=eff_sp_approval,
                            operation="orchestrator_dag_preflight_check",
                        )
                    except SandboxSecurityError as sec_exc:
                        self.task_manager.transition(
                            root_id,
                            TaskState.FAILED,
                            reason=f"Blocked by security policy preflight ({type(sec_exc).__name__}): {sec_exc}",
                        )
                        return {
                            "mission_id": root_id,
                            "execution_path": "HIERARCHICAL_DAG",
                            "final_state": TaskState.FAILED.value,
                            "terminal_outcome": "BLOCKED_BY_POLICY",
                            "policy_error": str(sec_exc),
                            "verified_children_count": 0,
                            "logical_children_created": 0,
                            "succeeded_children": 0,
                            "max_concurrent_workers_used": 0,
                            "memory_retrieval": retrieved_memory,
                            "child_results": {},
                            "duration_sec": round(time.time() - started_at, 4),
                        }

        spec_by_cid: Dict[str, SubtaskSpec] = {}
        child_ids: List[str] = []
        for idx, sp in enumerate(specs):
            cid = f"{root_id}-SUB-{idx + 1:03d}"
            child_ids.append(cid)
            spec_by_cid[cid] = sp
            deps = [child_ids[d_idx] for d_idx in sp.depends_on_indices if 0 <= d_idx < idx]

            if sp.preferred_specialist_id:
                spec_id = sp.preferred_specialist_id
            else:
                routed = self.specialist_factory.router.route(
                    task_description=f"{sp.title} {sp.description}",
                    required_capabilities=sp.required_capabilities,
                    top_k=1,
                )[0]
                spec_id = routed["agent_id"]

            self.token_controller.allocate_budget(
                task_id=root_id,
                tier="COMPLEX",
                child_task_id=cid,
                custom_child_budget=sp.token_budget,
            )
            self.task_manager.create_task(
                task_id=cid,
                parent_task_id=root_id,
                title=sp.title,
                description=sp.description,
                depends_on=deps,
                priority=sp.priority,
                specialist_role=spec_id,
                token_budget=sp.token_budget,
                metadata={"queue_type": sp.queue_type, "subtask_index": idx},
            )
            self.task_manager.transition(cid, TaskState.PLANNED, reason="Subtask planned in DAG")
            self.task_manager.transition(cid, TaskState.QUEUED, reason="Subtask queued in DAG")

        # Initial dependency resolution (marks independent tasks READY)
        self.task_manager.dep_mgr.resolve_ready_tasks(parent_task_id=root_id)

        completed_results: Dict[str, Any] = {}
        staged_candidates: Dict[str, Dict[str, Any]] = {}
        max_Observed_concurrency = 0
        wave_index = 0
        step_counter = 0

        while True:
            if max_wall_clock_sec is not None and (time.time() - started_at) > max_wall_clock_sec:
                raise TimeoutError(
                    f"Mission {root_id} exceeded max_wall_clock_sec ({max_wall_clock_sec}s)"
                )
            # 1. Process live CommandInbox at safe wave checkpoint
            inbox_actions = self.task_manager.process_inbox_checkpoint(active_task_id=root_id)
            root_rec = self.task_manager.store.get_task(root_id)
            if not root_rec:
                break

            if root_rec["state"] in (
                TaskState.CANCELED.value,
                TaskState.INTERRUPTED.value,
                TaskState.WAITING_FOR_INPUT.value,
            ):
                if root_rec["state"] == TaskState.CANCELED.value:
                    for ch in self.task_manager.store.list_tasks(parent_task_id=root_id):
                        if TaskState(ch["state"]) not in TERMINAL_STATES:
                            self.task_manager.transition(
                                ch["task_id"],
                                TaskState.CANCELED,
                                reason="Parent task canceled via CommandInbox",
                            )
                return {
                    "mission_id": root_id,
                    "execution_path": "HIERARCHICAL_DAG",
                    "final_state": root_rec["state"],
                    "terminal_outcome": (
                        "CANCELLED"
                        if root_rec["state"] == TaskState.CANCELED.value
                        else "FAILED"
                    ),
                    "inbox_actions_applied": inbox_actions,
                    "completed_subtasks": len(completed_results),
                    "duration_sec": round(time.time() - started_at, 4),
                }

            # Refresh children list (in case ADD_CHILD_TASK added new children mid-run!)
            all_children = self.task_manager.store.list_tasks(parent_task_id=root_id)
            for ch in all_children:
                if ch["state"] == TaskState.CREATED.value:
                    self.task_manager.transition(ch["task_id"], TaskState.PLANNED, reason="Dynamic child planned")
                    self.task_manager.transition(ch["task_id"], TaskState.QUEUED, reason="Dynamic child queued")

            self.task_manager.dep_mgr.resolve_ready_tasks(parent_task_id=root_id)
            all_children = self.task_manager.store.list_tasks(parent_task_id=root_id)

            ready_children = [
                ch
                for ch in all_children
                if ch["state"] in (TaskState.READY.value, TaskState.WAITING_FOR_RESOURCE.value)
            ]
            non_terminal = [
                ch for ch in all_children if TaskState(ch["state"]) not in TERMINAL_STATES
            ]

            if not non_terminal:
                break

            if not ready_children:
                break

            wave_index += 1
            dyn_cap = self.governor.compute_dynamic_active_cap(simulated_resource_snapshot)
            batch = ready_children[: max(1, dyn_cap)]
            max_Observed_concurrency = max(max_Observed_concurrency, len(batch))

            # Park any overflow ready tasks in WAITING_FOR_RESOURCE
            for overflow_ch in ready_children[len(batch) :]:
                if overflow_ch["state"] == TaskState.READY.value:
                    self.task_manager.transition(
                        overflow_ch["task_id"],
                        TaskState.WAITING_FOR_RESOURCE,
                        reason=f"Throttled by ResourceGovernor (MAX_ACTIVE_EXECUTIONS={dyn_cap})",
                    )

            def _run_child(child_record: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
                cid = child_record["task_id"]
                if max_wall_clock_sec is not None and (time.time() - started_at) > max_wall_clock_sec:
                    raise TimeoutError(
                        f"Child task {cid} aborted: mission {root_id} exceeded max_wall_clock_sec ({max_wall_clock_sec}s)"
                    )
                sp_spec = spec_by_cid.get(cid)
                q_type = child_record.get("metadata", {}).get("queue_type", "light_in_process")
                decision = self.governor.acquire_slot(queue_type=q_type, snap=simulated_resource_snapshot)
                if not decision.admitted:
                    if child_record["state"] == TaskState.READY.value:
                        self.task_manager.transition(
                            cid,
                            TaskState.WAITING_FOR_RESOURCE,
                            reason=decision.reason,
                        )
                    time.sleep(0.02)
                    self.governor.acquire_slot(queue_type="light_in_process", snap=simulated_resource_snapshot)
                    q_type = "light_in_process"

                try:
                    cur = self.task_manager.store.get_task(cid)
                    if cur and cur["state"] == TaskState.WAITING_FOR_RESOURCE.value:
                        self.task_manager.transition(cid, TaskState.READY, reason="Resource slot acquired")
                    self.task_manager.transition(cid, TaskState.RUNNING, reason="Executing specialist subtask")

                    role_id = child_record.get("specialist_role") or "swe_python_runtime_engineer"
                    custom_exec = None
                    if sp_spec is not None:
                        if sp_spec.executor_fn is not None:
                            custom_exec = sp_spec.executor_fn
                        elif sp_spec.use_live_model:
                            custom_exec = self._build_live_model_executor(
                                root_id=root_id,
                                child_id=cid,
                                sp_spec=sp_spec,
                                staged_candidates=staged_candidates,
                                apply_approved_patch=apply_approved_patch,
                            )

                    try:
                        inst = self.specialist_factory.instantiate(role_id, custom_executor=custom_exec)
                    except KeyError:
                        inst = self.specialist_factory.instantiate("swe_python_runtime_engineer", custom_executor=custom_exec)

                    # Pass upstream outputs from dependency tasks into context
                    deps = child_record.get("depends_on", [])
                    upstream_outputs = {
                        dep_id: completed_results[dep_id]
                        for dep_id in deps
                        if dep_id in completed_results
                    }

                    # Pre-action budget enforcement BEFORE specialist execution
                    with self.token_controller._lock:
                        t_used_pre = self.token_controller._task_consumed.get(root_id, 0)
                        t_lim_pre = self.token_controller._task_budgets.get(root_id)
                        if t_lim_pre is not None and t_used_pre >= t_lim_pre:
                            raise TokenBudgetExceededError(
                                f"Task {root_id} cumulative token budget exhausted before {cid}: used={t_used_pre} >= limit={t_lim_pre}"
                            )
                    if sp_spec is None or not sp_spec.use_live_model:
                        self.token_controller.check_pre_call_admission(
                            task_id=root_id,
                            child_task_id=cid,
                            estimated_tokens=max(1, len(child_record["description"]) // 4),
                            tier="COMPLEX",
                        )

                    res = inst.run(
                        {
                            "task_id": cid,
                            "task_prompt": f"{child_record['title']}: {child_record['description']}",
                            "context": {
                                "parent_task_id": root_id,
                                "wave_index": wave_index,
                                "upstream_outputs": upstream_outputs,
                                "root_metadata": self.task_manager.store.get_task(root_id).get("metadata", {}),
                            },
                        }
                    )

                    if sp_spec is None or not sp_spec.use_live_model:
                        self.token_controller.record_usage(
                            task_id=root_id,
                            child_task_id=cid,
                            agent_id=inst.contract.agent_id,
                            prompt_text=child_record["description"],
                            response_text=res["output_summary"],
                            cwd_used=self.token_controller.get_execution_cwd(is_benchmark_or_single_shot=True),
                        )

                    # Post-call cumulative budget check
                    with self.token_controller._lock:
                        t_used = self.token_controller._task_consumed.get(root_id, 0)
                        t_lim = self.token_controller._task_budgets.get(root_id)
                        if t_lim is not None and t_used > t_lim:
                            raise TokenBudgetExceededError(
                                f"Task {root_id} cumulative token budget exceeded: used={t_used} > limit={t_lim}"
                            )
                        c_used = self.token_controller._child_consumed.get(cid, 0)
                        c_lim = self.token_controller._child_budgets.get(cid)
                        if c_lim is not None and c_used > c_lim:
                            raise TokenBudgetExceededError(
                                f"Child task {cid} token budget exceeded: used={c_used} > limit={c_lim}"
                            )

                    self.task_manager.transition(cid, TaskState.VERIFYING, reason="Verifying specialist output")

                    # Check verification command or custom executor verification flag
                    verification_failed = False
                    failure_details: Dict[str, Any] = {}
                    artifacts = res.get("artifacts") or {}
                    if artifacts.get("verification_passed") is False or artifacts.get("artifact_verification_passed") is False:
                        verification_failed = True
                        failure_details = dict(artifacts)

                    if sp_spec and (sp_spec.verification_command or (sp_spec.use_disposable_sandbox and sp_spec.verification_cwd)):
                        if sp_spec.use_disposable_sandbox and sp_spec.verification_cwd:
                            artifacts["initial_verification_run"] = self._run_sandboxed_workspace_tests(
                                sp_spec.verification_cwd,
                                sandbox_id=f"{cid}-VERIFY-ATT1",
                                staged_candidates=staged_candidates,
                            )
                            init_passed = bool(
                                artifacts["initial_verification_run"].get(
                                    "passed",
                                    artifacts["initial_verification_run"]["exit_code"] == 0,
                                )
                            )
                        else:
                            if self.sandbox_runner.policy.require_container_isolation:
                                raise SandboxPolicyViolationError(
                                    f"Host verification_command is forbidden for {cid} when require_container_isolation=True; "
                                    "use disposable sandbox execution."
                                )
                            ver_notif = self.supervisor.run_supervised(
                                task_id=f"{cid}-VERIFY-ATT1",
                                command=sp_spec.verification_command,
                                cwd=sp_spec.verification_cwd,
                                wall_timeout_sec=60.0,
                                idle_timeout_sec=30.0,
                            )
                            stdout_txt = Path(ver_notif.stdout_log_path).read_text(encoding="utf-8", errors="replace") if Path(ver_notif.stdout_log_path).exists() else ""
                            stderr_txt = Path(ver_notif.stderr_log_path).read_text(encoding="utf-8", errors="replace") if Path(ver_notif.stderr_log_path).exists() else ""
                            artifacts["initial_verification_run"] = {
                                "passed": ver_notif.exit_code == 0,
                                "exit_code": ver_notif.exit_code,
                                "stdout": stdout_txt,
                                "stderr": stderr_txt,
                                "notification_id": ver_notif.notification_id,
                            }
                            init_passed = ver_notif.exit_code == 0
                        if not init_passed:
                            verification_failed = True
                            failure_details = artifacts["initial_verification_run"]
                            res["task_correctness_verified"] = False
                        else:
                            res["task_correctness_verified"] = True

                    # Self-healing retry loop when verification fails or specialists disagree
                    can_repair = sp_spec is not None and (
                        sp_spec.repair_fn is not None
                        or (
                            self.model_adapter is not None
                            and bool(sp_spec.repair_target_file or sp_spec.target_file_path)
                        )
                    )
                    if verification_failed and can_repair and sp_spec is not None:
                        if max_wall_clock_sec is not None and (time.time() - started_at) > max_wall_clock_sec:
                            raise TimeoutError(
                                f"Repair aborted for {cid}: mission {root_id} exceeded max_wall_clock_sec ({max_wall_clock_sec}s)"
                            )
                        with self.token_controller._lock:
                            t_used_rep = self.token_controller._task_consumed.get(root_id, 0)
                            t_lim_rep = self.token_controller._task_budgets.get(root_id)
                            if t_lim_rep is not None and t_used_rep >= t_lim_rep:
                                raise TokenBudgetExceededError(
                                    f"Task {root_id} cumulative token budget exhausted before repair on {cid}: used={t_used_rep} >= limit={t_lim_rep}"
                                )
                        self.task_manager.transition(
                            cid,
                            TaskState.FAILED,
                            reason="Verification failed; initiating specialist repair",
                            error=failure_details,
                        )
                        self.task_manager.transition(
                            cid,
                            TaskState.QUEUED,
                            reason=f"Escalating failure to repair specialist '{sp_spec.repair_specialist_id}'",
                        )
                        self.task_manager.transition(cid, TaskState.READY, reason="Repair specialist ready")
                        self.task_manager.transition(cid, TaskState.RUNNING, reason="Executing specialist repair & re-test")

                        if sp_spec.repair_fn is not None:
                            repair_out = sp_spec.repair_fn(res, failure_details)
                        else:
                            repair_out = self._default_live_model_repair(
                                root_id=root_id,
                                child_id=cid,
                                sp_spec=sp_spec,
                                failed_result=res,
                                failure_details=failure_details,
                                staged_candidates=staged_candidates,
                                apply_approved_patch=apply_approved_patch,
                            )
                        rollback_bytes = repair_out.pop("_rollback_bytes", None) if isinstance(repair_out, dict) else None
                        prev_staged_entry = repair_out.pop("_prev_staged_entry", None) if isinstance(repair_out, dict) else None
                        artifacts["repair_specialist_id"] = sp_spec.repair_specialist_id
                        artifacts["repair_execution"] = repair_out

                        self.task_manager.transition(cid, TaskState.VERIFYING, reason="Re-verifying after specialist patch")
                        if sp_spec.use_disposable_sandbox and sp_spec.verification_cwd:
                            artifacts["post_repair_verification_run"] = self._run_sandboxed_workspace_tests(
                                sp_spec.verification_cwd,
                                sandbox_id=f"{cid}-VERIFY-ATT2",
                                staged_candidates=staged_candidates,
                            )
                            re_passed = bool(
                                artifacts["post_repair_verification_run"].get(
                                    "passed",
                                    artifacts["post_repair_verification_run"]["exit_code"] == 0,
                                )
                            )
                            verification_failed = not re_passed
                            res["task_correctness_verified"] = re_passed
                        elif sp_spec.verification_command:
                            if self.sandbox_runner.policy.require_container_isolation:
                                raise SandboxPolicyViolationError(
                                    f"Host verification_command is forbidden for {cid} when require_container_isolation=True"
                                )
                            re_notif = self.supervisor.run_supervised(
                                task_id=f"{cid}-VERIFY-ATT2",
                                command=sp_spec.verification_command,
                                cwd=sp_spec.verification_cwd,
                                wall_timeout_sec=60.0,
                                idle_timeout_sec=30.0,
                            )
                            re_stdout = Path(re_notif.stdout_log_path).read_text(encoding="utf-8", errors="replace") if Path(re_notif.stdout_log_path).exists() else ""
                            re_stderr = Path(re_notif.stderr_log_path).read_text(encoding="utf-8", errors="replace") if Path(re_notif.stderr_log_path).exists() else ""
                            artifacts["post_repair_verification_run"] = {
                                "passed": re_notif.exit_code == 0,
                                "exit_code": re_notif.exit_code,
                                "stdout": re_stdout,
                                "stderr": re_stderr,
                                "notification_id": re_notif.notification_id,
                            }
                            verification_failed = re_notif.exit_code != 0
                            res["task_correctness_verified"] = (re_notif.exit_code == 0)
                        else:
                            verification_failed = not bool(repair_out.get("verification_passed", True))
                            res["task_correctness_verified"] = not verification_failed

                        if verification_failed and isinstance(repair_out, dict):
                            rep_path_str = repair_out.get("repaired_file_path")
                            if rep_path_str:
                                if prev_staged_entry is not None:
                                    staged_candidates[rep_path_str] = prev_staged_entry
                                else:
                                    staged_candidates.pop(rep_path_str, None)
                                ws_root_rb, rep_target_rb = self._resolve_validated_workspace_target(
                                    rep_path_str,
                                    sp_spec.verification_cwd,
                                )
                                if rollback_bytes is not None and rep_target_rb.is_file():
                                    rb_sha = hashlib.sha256(rep_target_rb.read_bytes()).hexdigest()
                                    repair_out["rolled_back_on_failed_verification"] = True
                                    repair_out["rollback_restored_sha256"] = rb_sha
                                    repair_out["rollback_verified"] = (
                                        rb_sha == repair_out.get("pre_repair_file_sha256")
                                    )

                        if not verification_failed:
                            target_mod = Path(
                                sp_spec.repair_target_file
                                or sp_spec.target_file_path
                                or "module.py"
                            ).name
                            err_trace = str(failure_details.get("stderr") or failure_details.get("stdout") or "verification_failure")
                            err_line = next(
                                (
                                    ln.strip()
                                    for ln in reversed(err_trace.splitlines())
                                    if any(k in ln for k in ("Error", "FAIL:", "AssertionError", "ValueError"))
                                ),
                                "test_assertion_failure",
                            )
                            lesson = self.memory.record_failure_lesson(
                                task_id=cid,
                                module_name=target_mod,
                                failing_assertion=err_line[:120],
                                root_cause=f"Initial implementation of {target_mod} failed {err_line[:80]}",
                                minimal_patch_rule=(
                                    f"For {target_mod}, enforce boundary equality (`<=`/`>=`), input ValueError guards, "
                                    f"and exact return contracts tested in repository unit tests ({err_line[:80]})."
                                ),
                            )
                            artifacts["self_learning_lesson_recorded"] = lesson

                    if verification_failed:
                        self.task_manager.transition(
                            cid,
                            TaskState.FAILED,
                            reason="Specialist verification failed after retry",
                            error=failure_details,
                        )
                        res["status"] = "FAILED"
                        res["task_correctness_verified"] = False
                        return cid, res

                    self.task_manager.transition(
                        cid,
                        TaskState.SUCCEEDED,
                        reason="Specialist verification hook passed",
                        result=res,
                    )
                    return cid, res
                except Exception as child_exc:
                    try:
                        cur_ch = self.task_manager.store.get_task(cid)
                        if cur_ch and TaskState(cur_ch["state"]) not in TERMINAL_STATES:
                            self.task_manager.transition(
                                cid,
                                TaskState.FAILED,
                                reason=f"Child task raised {type(child_exc).__name__}: {child_exc}",
                                error={"exception_type": type(child_exc).__name__, "message": str(child_exc)},
                            )
                    except Exception:
                        pass
                    raise
                finally:
                    self.governor.release_slot(queue_type=q_type)

            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(batch))) as pool:
                futures = [pool.submit(_run_child, ch) for ch in batch]
                for fut in concurrent.futures.as_completed(futures):
                    cid, res = fut.result()
                    completed_results[cid] = res
                    step_counter += 1
                    self.task_manager.save_checkpoint(
                        root_id,
                        step_index=step_counter,
                        state_payload={
                            "last_completed_child": cid,
                            "completed_count": len(completed_results),
                            "wave_index": wave_index,
                        },
                    )
                    if custom_subtask_hook:
                        custom_subtask_hook(cid, res)

        # Final check of all children
        final_children = self.task_manager.store.list_tasks(parent_task_id=root_id)
        succeeded_cnt = sum(1 for c in final_children if c["state"] == TaskState.SUCCEEDED.value)
        all_ok = succeeded_cnt == len(final_children)

        fallback_events: List[Dict[str, Any]] = []
        verified_children_count = 0
        any_timed_out = False
        for cid_key, ch_res in completed_results.items():
            if isinstance(ch_res, dict):
                if ch_res.get("task_correctness_verified") is True:
                    verified_children_count += 1
                if ch_res.get("timed_out"):
                    any_timed_out = True
            art = ch_res.get("artifacts") if isinstance(ch_res, dict) else {}
            if isinstance(art, dict):
                if art.get("task_correctness_verified") is True and ch_res.get("task_correctness_verified") is not True:
                    verified_children_count += 1
                if art.get("timed_out"):
                    any_timed_out = True
                if art.get("fallback_used"):
                    fallback_events.append(
                        {
                            "child_task_id": cid_key,
                            "stage": "initial_generation",
                            "reason": art.get("fallback_reason"),
                        }
                    )
                rep_exec = art.get("repair_execution")
                if isinstance(rep_exec, dict) and rep_exec.get("fallback_used"):
                    fallback_events.append(
                        {
                            "child_task_id": cid_key,
                            "stage": "repair_generation",
                            "reason": rep_exec.get("fallback_reason"),
                        }
                    )

        has_staged_candidates = len(staged_candidates) > 0
        patch_applied_to_workspace = False
        pending_approval = False
        approval_status = "NOT_APPLICABLE"
        applied_workspace_files: List[str] = []

        if all_ok and has_staged_candidates:
            eff_mission_approval = bool(
                apply_approved_patch
                or any(bool(c.get("apply_approved_patch")) for c in staged_candidates.values())
            )
            # Check authorization across all staged candidates before writing any file to workspace
            all_authorized = True
            for cand_info in staged_candidates.values():
                if not self.approval_gate.is_workspace_mutation_authorized(
                    workspace_root=cand_info["ws_root"],
                    target_path=cand_info["target_path"],
                    explicit_approval=eff_mission_approval,
                    operation="orchestrator_apply_verified_candidate",
                ):
                    all_authorized = False
                    break

            if all_authorized and verified_children_count > 0:
                for cand_info in staged_candidates.values():
                    ext_app_dir, staged_app_file, staged_app_sha = stage_candidate_outside_workspace(
                        cand_info["ws_root"],
                        cand_info["rel_path"],
                        cand_info["content"],
                        stage_label=f"{root_id}_apply",
                    )
                    try:
                        self.approval_gate.validate_workspace_path_containment(
                            workspace_root=cand_info["ws_root"],
                            target_path=cand_info["target_path"],
                        )
                        atomic_write_workspace_file(
                            cand_info["ws_root"],
                            cand_info["rel_path"],
                            staged_app_file.read_bytes(),
                        )
                    finally:
                        shutil.rmtree(ext_app_dir, ignore_errors=True)
                    disk_sha = hashlib.sha256(cand_info["target_path"].read_bytes()).hexdigest()
                    if disk_sha != cand_info["sha256"] or disk_sha != staged_app_sha:
                        raise RuntimeError(
                            f"Verified candidate SHA-256 mismatch on apply for {cand_info['target_path']}: "
                            f"expected={cand_info['sha256']}, actual={disk_sha}"
                        )
                    applied_workspace_files.append(str(cand_info["target_path"]))
                patch_applied_to_workspace = True
                pending_approval = False
                approval_status = "APPROVED_AND_APPLIED"
                for ch_res in completed_results.values():
                    art = ch_res.get("artifacts") if isinstance(ch_res, dict) else None
                    if isinstance(art, dict):
                        if "patch_applied_to_workspace" in art:
                            art["patch_applied_to_workspace"] = True
                        rep_ex = art.get("repair_execution")
                        if isinstance(rep_ex, dict) and "patch_applied_to_workspace" in rep_ex:
                            rep_ex["patch_applied_to_workspace"] = True
            else:
                patch_applied_to_workspace = False
                pending_approval = True
                approval_status = "PENDING_APPROVAL"

        if all_ok:
            self.task_manager.transition(root_id, TaskState.VERIFYING, reason="All DAG subtasks succeeded; verifying root")
            self.task_manager.transition(
                root_id,
                TaskState.SUCCEEDED,
                reason=(
                    f"All {succeeded_cnt}/{len(final_children)} child tasks verified in external staging (pending approval)"
                    if pending_approval
                    else f"All {succeeded_cnt}/{len(final_children)} child tasks verified"
                ),
                result={
                    "total_logical_children": len(final_children),
                    "succeeded_children": succeeded_cnt,
                    "max_concurrent_workers_used": max_Observed_concurrency,
                    "waves_executed": wave_index,
                    "pending_approval": pending_approval,
                    "patch_applied_to_workspace": patch_applied_to_workspace,
                },
            )
            final_state = TaskState.SUCCEEDED.value
        else:
            self.task_manager.transition(
                root_id,
                TaskState.FAILED,
                reason=f"Only {succeeded_cnt}/{len(final_children)} child tasks succeeded",
            )
            final_state = TaskState.FAILED.value

        self.memory.store_compressed_episode(
            subject_key=f"episode:{root_id}",
            raw_observation=(
                f"Hierarchical mission '{title}' ({root_id}) finished with state={final_state}, "
                f"children={succeeded_cnt}/{len(final_children)}, max_concurrency={max_Observed_concurrency}"
            ),
            source_task_id=root_id,
        )

        if all_ok:
            if pending_approval:
                terminal_outcome = "PENDING_APPROVAL"
            elif len(fallback_events) == 0 and verified_children_count > 0:
                terminal_outcome = "SUCCEEDED_AND_VERIFIED"
            else:
                terminal_outcome = "SUCCEEDED_UNVERIFIED"
        else:
            terminal_outcome = "TIMED_OUT" if any_timed_out else "FAILED"

        staged_summary = {
            str(k): {
                "target_path": str(v["target_path"]),
                "rel_path": str(v["rel_path"]),
                "sha256": str(v["sha256"]),
                "stage": str(v["stage"]),
            }
            for k, v in staged_candidates.items()
        }

        return {
            "mission_id": root_id,
            "execution_path": "HIERARCHICAL_DAG",
            "status": "PENDING_APPROVAL" if pending_approval else final_state,
            "final_state": final_state,
            "terminal_outcome": terminal_outcome,
            "approval_status": approval_status,
            "pending_approval": pending_approval,
            "requires_human_approval": pending_approval,
            "staged_outside_workspace": has_staged_candidates,
            "patch_applied_to_workspace": patch_applied_to_workspace,
            "applied_workspace_files": applied_workspace_files,
            "staged_candidates": staged_summary,
            "verified_children_count": verified_children_count,
            "logical_children_created": len(final_children),
            "succeeded_children": succeeded_cnt,
            "max_concurrent_workers_used": max_Observed_concurrency,
            "fallback_summary": {
                "any_fallback_used": len(fallback_events) > 0,
                "fallback_count": len(fallback_events),
                "fallback_events": fallback_events,
            },
            "ecosystem_coordination_summary": self.ecosystem_coordinator.get_inventory_summary(),
            "limits_enforced": {
                "MAX_AGENT_SPECIALIZATIONS": MAX_AGENT_SPECIALIZATIONS,
                "MAX_LOGICAL_CHILD_TASKS": MAX_LOGICAL_CHILD_TASKS,
                "MAX_ACTIVE_EXECUTIONS": self.governor.compute_dynamic_active_cap(simulated_resource_snapshot),
            },
            "memory_retrieval": retrieved_memory,
            "child_results": completed_results,
            "duration_sec": round(time.time() - started_at, 4),
        }
