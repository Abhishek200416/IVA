"""AGI 1.7 Focused Product Workflow: Automated Python CI-Repair & Test-Healing Agent.

Provides a fail-closed, auditable Python CI-repair workflow:
1. Validates `test_pattern` (`validate_test_pattern`) and `module_filename`
   (`validate_relative_sandbox_path`) BEFORE any file read or model call.
2. Enforces `HighImpactApprovalGate` and token/cost/wall-clock budgets end-to-end.
3. Reproduces the failing Python `unittest` suite inside `DisposableSandboxRunner`
   using `SandboxPolicy.production()` by default (no silent host fallback).
4. Synthesizes a minimal root-cause patch via `swe_patch_minimizer` and stages it
   in memory without mutating the protected workspace before approval.
5. Verifies AST syntax, targeted tests, and the full independent regression suite
   (`test_*.py`) inside the container, plus exact SHA-256 artifact hash matching.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.AGI_1_7.ecosystem.agent_registry.ecosystem_coordinator import EcosystemCoordinator
from agents.AGI_1_7.ecosystem.agent_registry.specialist_factory import SpecialistFactory
from ..adapters.model_adapter import (
    ModelAdapter,
    ModelCostBudgetExceededError,
    ModelProviderConfig,
    redact_sensitive_text,
)
from ..process_supervision.sandbox_runner import (
    DisposableSandboxRunner,
    HighImpactApprovalGate,
    PathTraversalViolationError,
    SandboxCleanupUnverifiedError,
    SandboxPolicy,
    SandboxSecurityError,
    atomic_write_workspace_file,
    scan_untrusted_content,
    stage_candidate_outside_workspace,
    validate_relative_sandbox_path,
    validate_test_pattern,
)
from ..security.model_disclosure_policy import (
    DisclosureContext,
    DisclosureDecision,
    ExternalProviderBlockedInLocalOnlyModeError,
    ModelDisclosureDeniedError,
    ModelDisclosurePolicy,
)
from ..telemetry.token_economy import TokenBudgetExceededError
from .hierarchical_orchestrator import _extract_python_code, _is_valid_python_syntax


@dataclass
class CIRepairBudget:
    """Strict resource, token, wall-clock, and USD cost ceilings for a single CI-repair job."""

    max_repair_attempts: int = 2
    max_tokens: int = 80_000
    max_cost_usd: float = 0.25
    sandbox_timeout_sec: float = 30.0
    wall_timeout_sec: float = 180.0
    max_total_tokens: Optional[int] = None
    max_wall_clock_sec: Optional[float] = None

    def __post_init__(self) -> None:
        if self.max_total_tokens is not None:
            self.max_tokens = int(self.max_total_tokens)
        if self.max_wall_clock_sec is not None:
            self.wall_timeout_sec = float(self.max_wall_clock_sec)


@dataclass
class CIRepairResult:
    """Complete, auditable output of an automated Python CI-repair run."""

    repair_id: str
    status: str  # "REPAIRED_AND_VERIFIED" | "ALREADY_PASSING" | "REPAIR_FAILED" | "REPAIR_TIMED_OUT" | "BLOCKED_BY_SECURITY"
    terminal_outcome: str  # "SUCCEEDED_AND_VERIFIED" | "FAILED" | "TIMED_OUT" | "BUDGET_EXCEEDED" | "BLOCKED_BY_POLICY"
    workspace_dir: str
    target_module: str
    test_pattern: str
    initial_test_run: Dict[str, Any]
    final_test_run: Dict[str, Any]
    attempts_used: int
    syntax_check_passed: bool
    tests_verified_in_sandbox: bool
    test_files_unmodified_verified: bool
    patch_applied_to_workspace: bool
    isolation_backend: str
    original_sha256: str
    patched_sha256: str
    unified_diff: str
    diff_lines_changed: int
    total_tokens_consumed: int
    total_cost_usd: float
    duration_sec: float
    verified_artifact_sha256: Optional[str] = None
    staged_outside_workspace: bool = True
    pending_approval: bool = False
    approval_status: str = "PENDING_APPROVAL"
    independent_regression_run: Dict[str, Any] = field(default_factory=dict)
    security_warnings: List[str] = field(default_factory=list)
    attempt_history: List[Dict[str, Any]] = field(default_factory=list)
    pull_request_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CIRepairAgent:
    """End-to-end automated Python test-failure reproduction, minimal patching, and sandboxed verification."""

    def __init__(
        self,
        *,
        model_adapter: Optional[ModelAdapter] = None,
        sandbox_runner: Optional[DisposableSandboxRunner] = None,
        specialist_factory: Optional[SpecialistFactory] = None,
        ecosystem_coordinator: Optional[EcosystemCoordinator] = None,
        approval_gate: Optional[HighImpactApprovalGate] = None,
        budget: Optional[CIRepairBudget] = None,
        disclosure_policy: Optional[ModelDisclosurePolicy] = None,
    ) -> None:
        self.budget = budget or CIRepairBudget()
        self.approval_gate = approval_gate or (
            sandbox_runner.approval_gate if sandbox_runner is not None else HighImpactApprovalGate()
        )
        self.model_adapter = model_adapter or ModelAdapter(
            config=ModelProviderConfig(
                max_request_cost_usd=self.budget.max_cost_usd,
                max_mission_cost_usd=self.budget.max_cost_usd,
            )
        )
        self.disclosure_policy = disclosure_policy or getattr(
            self.model_adapter, "disclosure_policy", None
        ) or ModelDisclosurePolicy.production_strict()
        self.sandbox_runner = sandbox_runner or DisposableSandboxRunner(
            policy=SandboxPolicy.production(wall_timeout_sec=self.budget.sandbox_timeout_sec),
            approval_gate=self.approval_gate,
        )
        self.specialist_factory = specialist_factory or SpecialistFactory()
        self.ecosystem_coordinator = ecosystem_coordinator or EcosystemCoordinator()

    def get_security_diagnostics(self) -> Dict[str, Any]:
        """Returns safe diagnostic metadata for the CI-Repair agent's runner and approval gate."""
        return {
            "ci_repair_agent_instance_id": id(self),
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

    @staticmethod
    def _collect_workspace_py_files(ws_dir: Path) -> Dict[str, str]:
        files_map: Dict[str, str] = {}
        ignored_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
        if ws_dir.is_symlink():
            raise PathTraversalViolationError(f"Workspace root must not be a symlink: '{ws_dir}'")
        for py_file in sorted(ws_dir.rglob("*.py")):
            rel_parts = py_file.relative_to(ws_dir).parts
            if any(part in ignored_dirs for part in rel_parts):
                continue
            rel_posix = py_file.relative_to(ws_dir).as_posix()
            if py_file.is_symlink():
                raise PathTraversalViolationError(
                    f"Symlink file rejected in CI-Repair workspace: '{rel_posix}'"
                )
            validate_relative_sandbox_path(ws_dir, rel_posix, require_py_extension=True)
            if py_file.is_file():
                files_map[rel_posix] = py_file.read_text(encoding="utf-8", errors="replace")
        return files_map

    @staticmethod
    def _run_static_quality_check(code_str: str, filename: str) -> Dict[str, Any]:
        """Verifies Python AST validity and checks for bare excepts or syntax defects."""
        try:
            tree = ast.parse(code_str, filename=filename)
        except SyntaxError as exc:
            return {"passed": False, "error": f"SyntaxError: {exc}", "ast_nodes": 0}
        bare_excepts = sum(
            1 for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.type is None
        )
        return {
            "passed": True,
            "error": None,
            "ast_nodes": sum(1 for _ in ast.walk(tree)),
            "bare_except_handlers": bare_excepts,
        }

    def _enforce_budgets_precheck(self, started_perf: float, total_tokens: int, total_cost: float) -> None:
        if self.budget.max_repair_attempts <= 0 or self.budget.max_tokens <= 0:
            raise TokenBudgetExceededError(
                f"CI-Repair token/attempt budget exhausted: max_tokens={self.budget.max_tokens}, max_repair_attempts={self.budget.max_repair_attempts}"
            )
        if self.budget.max_cost_usd <= 0:
            raise ModelCostBudgetExceededError(
                f"CI-Repair cost budget exhausted: max_cost_usd={self.budget.max_cost_usd}"
            )
        if self.budget.wall_timeout_sec <= 0 or self.budget.sandbox_timeout_sec <= 0:
            raise TimeoutError("CI-Repair timeout budget exhausted (<= 0s).")
        if (time.perf_counter() - started_perf) > self.budget.wall_timeout_sec:
            raise TimeoutError(
                f"CI-Repair exceeded wall_timeout_sec ({self.budget.wall_timeout_sec}s)."
            )
        if total_tokens >= self.budget.max_tokens:
            raise TokenBudgetExceededError(
                f"CI-Repair token budget exceeded: used={total_tokens} >= max_tokens={self.budget.max_tokens}"
            )
        if total_cost >= self.budget.max_cost_usd:
            raise ModelCostBudgetExceededError(
                f"CI-Repair cost budget exceeded: used=${total_cost:.6f} >= max_cost_usd=${self.budget.max_cost_usd:.6f}"
            )

    def repair_workspace(
        self,
        *,
        workspace_dir: str | Path,
        module_filename: str,
        test_pattern: str = "test_*.py",
        issue_description: str = "Fix failing Python unit tests with minimal diff.",
        write_patch_to_workspace: bool = False,
        apply_approved_patch: Optional[bool] = None,
        allow_workspace_model_disclosure: Optional[bool] = None,
        repair_id: Optional[str] = None,
    ) -> CIRepairResult:
        """Reproduces failing tests in the sandbox, synthesizes a minimal patch, verifies in sandbox, and builds a PR payload.

        By default (`write_patch_to_workspace=False` and `apply_approved_patch=None`), candidate patches
        are staged and verified strictly inside the disposable sandbox without mutating the workspace
        unless an approval callback or explicit caller approval authorizes patch application.
        """
        t0 = time.perf_counter()
        rid = repair_id or f"CI-REPAIR-{int(time.time() * 1000)}"

        # Step 0: Validate test_pattern, path containment, approval gate, and budgets BEFORE reading any file
        validated_pattern = validate_test_pattern(test_pattern)
        ws_raw = Path(workspace_dir)
        if ws_raw.is_symlink():
            raise PathTraversalViolationError(f"Workspace directory must not be a symlink: '{workspace_dir}'")
        ws = ws_raw.resolve()
        module_path = validate_relative_sandbox_path(ws, module_filename, require_py_extension=True)
        norm_module_rel = module_path.relative_to(ws).as_posix()

        self._enforce_budgets_precheck(t0, total_tokens=0, total_cost=0.0)

        caller_explicitly_declined = (apply_approved_patch is False and not write_patch_to_workspace)
        should_apply = bool(write_patch_to_workspace or (apply_approved_patch is True))
        self.approval_gate.check_preflight_access(
            workspace_root=ws,
            target_rel_path=norm_module_rel,
            explicit_approval=should_apply,
            action_type="apply_workspace_patch" if should_apply else "ci_repair_preflight",
            action_description=f"Preflight CI-Repair containment and policy check for {norm_module_rel}",
        )

        if not module_path.is_file():
            raise FileNotFoundError(f"Target Python module not found: {module_path}")

        original_code = module_path.read_text(encoding="utf-8")
        original_sha = hashlib.sha256(original_code.encode("utf-8")).hexdigest()
        py_files = self._collect_workspace_py_files(ws)
        test_file_hashes_before = {
            k: hashlib.sha256(v.encode("utf-8")).hexdigest()
            for k, v in py_files.items()
            if k != norm_module_rel
        }

        # Step 1: Pre-scan workspace files and issue description for prompt injection or dangerous code
        all_warnings: List[str] = []
        all_warnings.extend(
            scan_untrusted_content(issue_description, source_name="issue_description", block_on_code_hazards=True)
        )
        for fname, content in py_files.items():
            w = scan_untrusted_content(content, source_name=fname, block_on_code_hazards=True)
            all_warnings.extend(w)

        # Allocate cumulative token budget for this repair task
        self.model_adapter.token_controller.allocate_budget(
            task_id=rid,
            tier="COMPLEX",
            custom_task_budget=self.budget.max_tokens,
        )

        # Step 2: Reproduce failure inside disposable sandbox
        initial_sbx = self.sandbox_runner.run_python_unittest_sandbox(
            files=py_files,
            test_pattern=validated_pattern,
            sandbox_id=f"{rid}-INIT",
        )
        if not initial_sbx.cleanup_verified:
            raise SandboxCleanupUnverifiedError(
                f"Initial sandbox cleanup could not be verified for '{rid}-INIT'."
            )

        if initial_sbx.passed:
            return CIRepairResult(
                repair_id=rid,
                status="ALREADY_PASSING",
                terminal_outcome="SUCCEEDED_AND_VERIFIED",
                workspace_dir=redact_sensitive_text(str(ws)),
                target_module=norm_module_rel,
                test_pattern=validated_pattern,
                initial_test_run=initial_sbx.to_dict(),
                final_test_run=initial_sbx.to_dict(),
                attempts_used=0,
                syntax_check_passed=True,
                tests_verified_in_sandbox=True,
                test_files_unmodified_verified=True,
                patch_applied_to_workspace=False,
                isolation_backend=initial_sbx.isolation_backend,
                original_sha256=original_sha,
                patched_sha256=original_sha,
                unified_diff="",
                diff_lines_changed=0,
                total_tokens_consumed=0,
                total_cost_usd=0.0,
                duration_sec=round(time.perf_counter() - t0, 4),
                verified_artifact_sha256=original_sha,
                independent_regression_run=initial_sbx.to_dict(),
                security_warnings=all_warnings,
                attempt_history=[],
                pull_request_payload={
                    "title": f"[NO-OP] Tests already passing for {norm_module_rel}",
                    "requires_human_approval": True,
                },
            )

        # Step 3: Model Disclosure Authorization check BEFORE assembling prompt or invoking model
        has_workspace_content = bool(original_code.strip() or py_files)
        ctx = DisclosureContext(
            task_id=rid,
            agent_id="swe_patch_minimizer",
            workspace_root=ws,
            target_files=[norm_module_rel] + [k for k in py_files.keys() if k != norm_module_rel],
            has_workspace_content=has_workspace_content,
            is_external_provider=bool(self.model_adapter.mock_provider is None or getattr(self.model_adapter.mock_provider, "is_external", False)),
            provider_name=self.model_adapter.config.model_name,
            operation_type="ci_repair_model_invocation",
        )
        if self.disclosure_policy.local_only and ctx.is_external_provider:
            decision = self.disclosure_policy.evaluate(ctx)
            raise ExternalProviderBlockedInLocalOnlyModeError(decision.reason)
        if allow_workspace_model_disclosure is not None:
            if not allow_workspace_model_disclosure:
                raise ModelDisclosureDeniedError(
                    f"DISCLOSURE_DENIED: Explicit allow_workspace_model_disclosure=False for '{norm_module_rel}'"
                )
            decision = DisclosureDecision(
                authorized=True,
                mode=self.disclosure_policy.mode,
                reason="DISCLOSURE_PERMITTED: Explicit call-site allow_workspace_model_disclosure=True grant.",
            )
            self.disclosure_policy._record_audit(ctx, decision)
        else:
            self.disclosure_policy.authorize_or_raise(ctx)

        contract = self.specialist_factory.get_contract("swe_patch_minimizer")
        coord = self.ecosystem_coordinator.build_coordination_railings(contract, is_repair=True)
        test_sources = "\n\n".join(
            f"# {k}\n{v}" for k, v in py_files.items() if k != norm_module_rel
        )

        current_code = original_code
        current_failure_output = (initial_sbx.stderr or initial_sbx.stdout).strip()
        attempt_history: List[Dict[str, Any]] = []
        final_sbx = initial_sbx
        regression_sbx_dict: Dict[str, Any] = {}
        total_tokens = 0
        total_cost = 0.0
        repaired_ok = False
        best_code = original_code
        verified_candidate_sha256: Optional[str] = None
        test_files_unmodified = True
        any_timed_out = bool(initial_sbx.timed_out)

        for attempt in range(1, self.budget.max_repair_attempts + 1):
            self._enforce_budgets_precheck(t0, total_tokens=total_tokens, total_cost=total_cost)

            prompt = (
                f"You are AGI 1.7 CI-Repair Specialist `swe_patch_minimizer`.\n"
                f"{coord['railings_prompt_block']}\n"
                f"Issue Description: {issue_description}\n"
                f"IMPORTANT: Do NOT call any tools or shell commands. Return ONLY the complete corrected Python file for `{norm_module_rel}` inside a ```python ... ``` block.\n\n"
                f"CURRENT BROKEN `{norm_module_rel}`:\n```python\n{current_code}\n```\n\n"
                f"TEST SUITE:\n```python\n{test_sources}\n```\n\n"
                f"SANDBOXED UNITTEST FAILURE TRACEBACK (Attempt {attempt}):\n```text\n{current_failure_output}\n```\n\n"
                f"Fix the root cause with the smallest working change and return the complete `{norm_module_rel}` in a ```python ... ``` block."
            )

            model_res = self.model_adapter.invoke(
                task_id=rid,
                child_task_id=f"{rid}-ATT{attempt}",
                prompt=prompt,
                agent_id="swe_patch_minimizer",
                effort="high",
                is_benchmark_or_single_shot=True,
                tier="COMPLEX",
            )
            call_tokens = int(model_res.get("token_usage", {}).get("total_tokens", 0))
            call_cost = float(model_res.get("cost_usd", 0.0))
            total_tokens += call_tokens
            total_cost = round(total_cost + call_cost, 6)

            if total_tokens > self.budget.max_tokens:
                raise TokenBudgetExceededError(
                    f"CI-Repair cumulative tokens ({total_tokens}) exceeded max_tokens ({self.budget.max_tokens})"
                )
            if total_cost > self.budget.max_cost_usd:
                raise ModelCostBudgetExceededError(
                    f"CI-Repair cumulative cost (${total_cost:.6f}) exceeded max_cost_usd (${self.budget.max_cost_usd:.6f})"
                )
            if (time.perf_counter() - t0) > self.budget.wall_timeout_sec:
                raise TimeoutError(
                    f"CI-Repair exceeded wall_timeout_sec ({self.budget.wall_timeout_sec}s) during attempt {attempt}."
                )

            candidate_code = _extract_python_code(model_res.get("response_text", ""))
            cand_warnings = scan_untrusted_content(
                candidate_code,
                source_name=f"{norm_module_rel}:attempt_{attempt}",
                block_on_code_hazards=True,
            )
            all_warnings.extend(cand_warnings)

            static_check = self._run_static_quality_check(candidate_code, norm_module_rel)
            if not static_check["passed"]:
                attempt_history.append(
                    {
                        "attempt": attempt,
                        "model_status": model_res.get("status"),
                        "static_quality_check": static_check,
                        "sandbox_passed": False,
                        "tokens": call_tokens,
                        "cost_usd": call_cost,
                    }
                )
                current_failure_output = f"Generated code had invalid Python syntax: {static_check['error']}"
                continue

            ext_stage_dir, staged_cand_file, candidate_sha = stage_candidate_outside_workspace(
                ws,
                norm_module_rel,
                candidate_code,
                stage_label=f"{rid}_att{attempt}",
            )
            try:
                staged_text = staged_cand_file.read_text(encoding="utf-8")
            finally:
                shutil.rmtree(ext_stage_dir, ignore_errors=True)

            candidate_files = dict(py_files)
            candidate_files[norm_module_rel] = staged_text

            # Verify test files remain 100% unmodified
            for tf_name, tf_sha in test_file_hashes_before.items():
                cur_sha = hashlib.sha256(candidate_files.get(tf_name, "").encode("utf-8")).hexdigest()
                if cur_sha != tf_sha:
                    test_files_unmodified = False

            sbx_res = self.sandbox_runner.run_python_unittest_sandbox(
                files=candidate_files,
                test_pattern=validated_pattern,
                sandbox_id=f"{rid}-ATT{attempt}",
            )
            if not sbx_res.cleanup_verified:
                raise SandboxCleanupUnverifiedError(
                    f"Sandbox container/filesystem cleanup could not be verified for '{rid}-ATT{attempt}'."
                )
            if sbx_res.timed_out:
                any_timed_out = True

            # Step 4: Always run independent full-suite regression check (`test_*.py`) on passing candidate
            if sbx_res.passed:
                reg_sbx = self.sandbox_runner.run_python_unittest_sandbox(
                    files=candidate_files,
                    test_pattern="test_*.py",
                    sandbox_id=f"{rid}-ATT{attempt}-REG",
                )
                if not reg_sbx.cleanup_verified:
                    raise SandboxCleanupUnverifiedError(
                        f"Independent regression sandbox cleanup could not be verified for '{rid}-ATT{attempt}-REG'."
                    )
                if reg_sbx.timed_out:
                    any_timed_out = True
                regression_sbx_dict = reg_sbx.to_dict()
                if not reg_sbx.passed:
                    sbx_res = reg_sbx

            final_sbx = sbx_res
            attempt_history.append(
                {
                    "attempt": attempt,
                    "model_status": model_res.get("status"),
                    "static_quality_check": static_check,
                    "staged_outside_workspace": True,
                    "candidate_sha256": candidate_sha,
                    "sandbox_passed": sbx_res.passed,
                    "sandbox_exit_code": sbx_res.exit_code,
                    "sandbox_timed_out": sbx_res.timed_out,
                    "cleanup_verified": sbx_res.cleanup_verified,
                    "isolation_backend": sbx_res.isolation_backend,
                    "tokens": call_tokens,
                    "cost_usd": call_cost,
                }
            )
            current_code = candidate_code
            if sbx_res.passed and test_files_unmodified and not sbx_res.timed_out and sbx_res.cleanup_verified:
                repaired_ok = True
                best_code = candidate_code
                verified_candidate_sha256 = candidate_sha
                break
            current_failure_output = (sbx_res.stderr or sbx_res.stdout).strip()

        patch_applied = False
        if repaired_ok and (should_apply or self.approval_gate.approval_callback is not None):
            authorized = self.approval_gate.is_workspace_mutation_authorized(
                workspace_root=ws,
                target_rel_path=norm_module_rel,
                explicit_approval=should_apply,
                action_type="apply_workspace_patch",
                action_description=f"Apply verified CI-Repair patch to {norm_module_rel}",
            )
            if authorized and not caller_explicitly_declined:
                ext_apply_dir, staged_apply_file, staged_apply_sha = stage_candidate_outside_workspace(
                    ws,
                    norm_module_rel,
                    best_code,
                    stage_label=f"{rid}_apply",
                )
                try:
                    self.approval_gate.validate_workspace_path_containment(
                        workspace_root=ws,
                        target_rel_path=norm_module_rel,
                    )
                    current_disk_sha = hashlib.sha256(module_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
                    if current_disk_sha != staged_apply_sha:
                        atomic_write_workspace_file(ws, norm_module_rel, staged_apply_file.read_bytes())
                        patch_applied = True
                finally:
                    shutil.rmtree(ext_apply_dir, ignore_errors=True)
                on_disk_after_sha = hashlib.sha256(module_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
                if on_disk_after_sha != verified_candidate_sha256:
                    atomic_write_workspace_file(ws, norm_module_rel, original_code)
                    raise SandboxSecurityError(
                        f"Post-apply artifact hash mismatch: on_disk={on_disk_after_sha} != verified={verified_candidate_sha256}; rolled back."
                    )

        final_code = best_code if repaired_ok else original_code
        patched_sha = hashlib.sha256(final_code.encode("utf-8")).hexdigest()
        if repaired_ok and patched_sha != verified_candidate_sha256:
            raise SandboxSecurityError(
                f"Final artifact SHA-256 ({patched_sha}) does not match sandbox-verified SHA-256 ({verified_candidate_sha256})."
            )

        diff_lines = list(
            difflib.unified_diff(
                original_code.splitlines(keepends=True),
                final_code.splitlines(keepends=True),
                fromfile=f"a/{norm_module_rel}",
                tofile=f"b/{norm_module_rel}",
            )
        )
        unified_diff_str = "".join(diff_lines)
        changed_line_count = sum(
            1
            for ln in diff_lines
            if (ln.startswith("+") and not ln.startswith("+++"))
            or (ln.startswith("-") and not ln.startswith("---"))
        )

        pending_approval_flag = bool(repaired_ok and not patch_applied)
        approval_status_str = (
            "APPROVED_AND_APPLIED"
            if patch_applied
            else ("PENDING_APPROVAL" if repaired_ok else "NOT_APPLICABLE")
        )

        pr_payload = {
            "title": f"fix({norm_module_rel}): automated CI test-failure repair ({rid})",
            "target_module": norm_module_rel,
            "verified_in_sandbox": repaired_ok,
            "verified_artifact_sha256": verified_candidate_sha256,
            "test_files_unmodified_verified": test_files_unmodified,
            "patch_staged_only": not patch_applied,
            "patch_applied_to_workspace": patch_applied,
            "pending_approval": pending_approval_flag,
            "approval_status": approval_status_str,
            "isolation_backend": final_sbx.isolation_backend,
            "diff_lines_changed": changed_line_count,
            "requires_human_approval": True,
            "auto_push_blocked_by_gate": True,
        }

        if repaired_ok:
            final_status = "REPAIRED_AND_VERIFIED"
            final_outcome = "SUCCEEDED_AND_VERIFIED"
        elif any_timed_out:
            final_status = "REPAIR_TIMED_OUT"
            final_outcome = "TIMED_OUT"
        else:
            final_status = "REPAIR_FAILED"
            final_outcome = "FAILED"

        return CIRepairResult(
            repair_id=rid,
            status=final_status,
            terminal_outcome=final_outcome,
            workspace_dir=redact_sensitive_text(str(ws)),
            target_module=norm_module_rel,
            test_pattern=validated_pattern,
            initial_test_run=initial_sbx.to_dict(),
            final_test_run=final_sbx.to_dict(),
            attempts_used=len(attempt_history),
            syntax_check_passed=_is_valid_python_syntax(final_code),
            tests_verified_in_sandbox=repaired_ok,
            test_files_unmodified_verified=test_files_unmodified,
            patch_applied_to_workspace=patch_applied,
            isolation_backend=final_sbx.isolation_backend,
            original_sha256=original_sha,
            patched_sha256=patched_sha,
            unified_diff=unified_diff_str,
            diff_lines_changed=changed_line_count,
            total_tokens_consumed=total_tokens,
            total_cost_usd=total_cost,
            duration_sec=round(time.perf_counter() - t0, 4),
            verified_artifact_sha256=verified_candidate_sha256,
            staged_outside_workspace=True,
            pending_approval=pending_approval_flag,
            approval_status=approval_status_str,
            independent_regression_run=regression_sbx_dict,
            security_warnings=all_warnings,
            attempt_history=attempt_history,
            pull_request_payload=pr_payload,
        )
