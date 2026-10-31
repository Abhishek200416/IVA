"""AGI 1.7 Unified Master Platform Adapter (`AGI17Adapter`).

Binds all AGI 1.7 — OMEGA COMMAND subsystems into a single cohesive runtime:
  - CapabilityProfiler & ResourceSnapshot
  - DurableTaskManager, TaskStore, CheckpointManager, DependencyManager, CommandInbox
  - ProcessSupervisor, StreamParser, CompletionNotifier, RecoveryManager
  - 10-Layer OmegaCommandMemory & ACONCompressor
  - 100-Specialist SpecialistFactory, CapabilityRouter, RegistryValidator, EcosystemCoordinator
  - ResourceGovernor & HierarchicalOrchestrator
  - AdaptiveTokenController & ProgressService
  - EvidenceVerifier & GroundedResearchEngine
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from agents.IVA.ecosystem.agent_registry.ecosystem_coordinator import EcosystemCoordinator
from agents.IVA.ecosystem.agent_registry.specialist_factory import SpecialistFactory
from ..capabilities.capability_profiler import CapabilityProfiler
from ..capabilities.resource_snapshot import ResourceSnapshot
from ..memory.omega_command_memory import OmegaCommandMemory
from ..orchestration.ci_repair_agent import CIRepairAgent
from ..orchestration.hierarchical_orchestrator import HierarchicalOrchestrator, SubtaskSpec
from ..orchestration.resource_governor import ResourceGovernor
from ..orchestration.self_evolution_engine import AutonomousSelfEvolutionEngine
from ..process_supervision.process_supervisor import ProcessSupervisor
from ..process_supervision.sandbox_runner import (
    DisposableSandboxRunner,
    HighImpactApprovalGate,
    SandboxPolicy,
)
from ..research.grounded_research import GroundedResearchEngine
from ..security.model_disclosure_policy import ModelDisclosurePolicy
from ..task_control.task_manager import DurableTaskManager
from ..telemetry.progress_service import ProgressService
from ..telemetry.token_economy import AdaptiveTokenController
from ..verification.evidence_verifier import EvidenceVerifier
from .model_adapter import ModelAdapter


class AGI17Adapter:
    """Master runtime entrypoint for AGI 1.7.0 — OMEGA COMMAND."""

    VERSION = "1.7.0"
    CODENAME = "OMEGA COMMAND"

    def __init__(
        self,
        *,
        storage_root: str | Path = r"D:\AGI_Storage\AGI_1_7",
        eval_root: str | Path = r"D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND",
        sandbox_policy: Optional[SandboxPolicy] = None,
        sandbox_runner: Optional[DisposableSandboxRunner] = None,
        approval_gate: Optional[HighImpactApprovalGate] = None,
        model_adapter: Optional[ModelAdapter] = None,
        disclosure_policy: Optional[ModelDisclosurePolicy] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        import os as _os
        import sys as _sys
        fallback_base = Path(__file__).resolve().parents[3] / "state_fallback"
        if str(storage_root).upper().startswith("D:") and (_sys.platform != "win32" or not _os.path.exists("D:\\")):
            self.storage_root = fallback_base / "storage"
        else:
            self.storage_root = Path(storage_root)
        if str(eval_root).upper().startswith("D:") and (_sys.platform != "win32" or not _os.path.exists("D:\\")):
            self.eval_root = fallback_base / "eval"
        else:
            self.eval_root = Path(eval_root)

        self.profiler = CapabilityProfiler(
            storage_root=str(self.storage_root),
            eval_root=str(self.eval_root),
        )
        self.task_manager = DurableTaskManager(
            db_path=self.storage_root / "state" / "agi17_tasks.db",
            events_jsonl_path=self.storage_root / "journals" / "task_events.jsonl",
            checkpoints_dir=self.storage_root / "checkpoints",
        )
        self.memory = OmegaCommandMemory(
            primary_dir=self.storage_root / "memory",
        )
        self.governor = ResourceGovernor()
        self.token_controller = AdaptiveTokenController(
            ledger_dir=self.storage_root / "token_ledger",
            isolated_benchmark_cwd=self.eval_root / "isolated_cwd",
        )
        self.specialist_factory = SpecialistFactory()
        self.ecosystem_coordinator = EcosystemCoordinator()
        self.supervisor = ProcessSupervisor(
            task_manager=self.task_manager,
            logs_dir=self.storage_root / "logs" / "processes",
        )
        self.disclosure_policy = disclosure_policy or (
            getattr(model_adapter, "disclosure_policy", None)
            if model_adapter is not None
            else ModelDisclosurePolicy.production_strict()
        )
        self.model_adapter = model_adapter or ModelAdapter(
            token_controller=self.token_controller,
            governor=self.governor,
            supervisor=self.supervisor,
            disclosure_policy=self.disclosure_policy,
            api_key=api_key,
            model_name=model,
        )
        self.approval_gate = approval_gate or (
            sandbox_runner.approval_gate if sandbox_runner is not None else HighImpactApprovalGate()
        )
        self.sandbox_policy = sandbox_policy or (
            sandbox_runner.policy if sandbox_runner is not None else SandboxPolicy.production()
        )
        self.sandbox_runner = sandbox_runner or DisposableSandboxRunner(
            policy=self.sandbox_policy,
            approval_gate=self.approval_gate,
        )
        self.orchestrator = HierarchicalOrchestrator(
            task_manager=self.task_manager,
            memory=self.memory,
            governor=self.governor,
            token_controller=self.token_controller,
            specialist_factory=self.specialist_factory,
            ecosystem_coordinator=self.ecosystem_coordinator,
            model_adapter=self.model_adapter,
            supervisor=self.supervisor,
            sandbox_runner=self.sandbox_runner,
            approval_gate=self.approval_gate,
            disclosure_policy=self.disclosure_policy,
        )
        self.ci_repair_agent = CIRepairAgent(
            model_adapter=self.model_adapter,
            sandbox_runner=self.sandbox_runner,
            specialist_factory=self.specialist_factory,
            ecosystem_coordinator=self.ecosystem_coordinator,
            approval_gate=self.approval_gate,
            disclosure_policy=self.disclosure_policy,
        )
        self.progress_service = ProgressService(
            task_store=self.task_manager.store,
            token_controller=self.token_controller,
            output_dir=self.storage_root / "telemetry",
        )
        self.research_engine = GroundedResearchEngine(memory=self.memory)
        self.verifier = EvidenceVerifier()
        self.evolution_engine = AutonomousSelfEvolutionEngine(
            specialist_factory=self.specialist_factory,
            memory=self.memory,
            task_store=self.task_manager.store,
        )

    def get_security_diagnostics(self) -> Dict[str, Any]:
        """Returns a safe, credential-free diagnostic representation of the effective sandbox policy and runner identity across all subsystems."""
        shared_runner = bool(
            self.sandbox_runner is self.orchestrator.sandbox_runner is self.ci_repair_agent.sandbox_runner
        )
        shared_gate = bool(
            self.approval_gate
            is self.orchestrator.approval_gate
            is self.ci_repair_agent.approval_gate
            is self.sandbox_runner.approval_gate
        )
        shared_disclosure = bool(
            self.disclosure_policy
            is self.orchestrator.disclosure_policy
            is self.ci_repair_agent.disclosure_policy
            is self.model_adapter.disclosure_policy
        )
        return {
            "adapter_instance_id": id(self),
            "adapter_runner_id": id(self.sandbox_runner),
            "sandbox_runner_instance_id": id(self.sandbox_runner),
            "orchestrator_runner_instance_id": id(self.orchestrator.sandbox_runner),
            "ci_repair_runner_instance_id": id(self.ci_repair_agent.sandbox_runner),
            "shared_runner_identity_verified": shared_runner,
            "shared_sandbox_runner_verified": shared_runner,
            "adapter_approval_gate_id": id(self.approval_gate),
            "approval_gate_instance_id": id(self.approval_gate),
            "shared_approval_gate_identity_verified": shared_gate,
            "shared_approval_gate_verified": shared_gate,
            "adapter_disclosure_policy_id": id(self.disclosure_policy),
            "disclosure_policy_instance_id": id(self.disclosure_policy),
            "shared_disclosure_policy_verified": shared_disclosure,
            "effective_policy": self.sandbox_runner.policy.to_dict(),
            "disclosure_policy": {
                "mode": self.disclosure_policy.mode.value,
                "allow_workspace_model_disclosure": self.disclosure_policy.allow_workspace_model_disclosure,
                "local_only": self.disclosure_policy.local_only,
                "redact_secrets_outbound": self.disclosure_policy.redact_secrets_outbound,
            },
            "orchestrator_diagnostics": self.orchestrator.get_security_diagnostics(),
            "ci_repair_diagnostics": self.ci_repair_agent.get_security_diagnostics(),
        }

    def run_startup_reconciliation(self) -> Dict[str, Any]:
        """Reconciles orphan tasks after restart and refreshes hardware capability profile."""
        reconciled = self.task_manager.reconcile_after_restart()
        snap = ResourceSnapshot.capture().to_dict()
        limits = self.governor.get_limits_summary()
        return {
            "version": self.VERSION,
            "codename": self.CODENAME,
            "reconciliation": reconciled,
            "limits": limits,
            "resource_snapshot": snap,
            "ecosystem": self.ecosystem_coordinator.get_inventory_summary(),
            "security_diagnostics": self.get_security_diagnostics(),
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
        apply_approved_patch: bool = False,
        allow_workspace_model_disclosure: bool = False,
    ) -> list[SubtaskSpec]:
        """Delegates to `HierarchicalOrchestrator.build_code_and_test_subtasks`."""
        return self.orchestrator.build_code_and_test_subtasks(
            title=title,
            prompt=prompt,
            code_task_dir=code_task_dir,
            module_filename=module_filename,
            test_filename=test_filename,
            inject_deliberate_test_failure=inject_deliberate_test_failure,
            fallback_module_code=fallback_module_code,
            fallback_test_code=fallback_test_code,
            apply_approved_patch=apply_approved_patch,
            allow_workspace_model_disclosure=allow_workspace_model_disclosure,
        )

    def run_ci_repair(
        self,
        *,
        workspace_dir: str | Path,
        module_filename: str,
        test_pattern: str = "test_*.py",
        issue_description: str = "Fix failing Python unit tests with minimal diff.",
        write_patch_to_workspace: bool = False,
        apply_approved_patch: Optional[bool] = None,
        allow_workspace_model_disclosure: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Executes the focused Python CI-Repair product workflow inside a disposable sandbox."""
        res = self.ci_repair_agent.repair_workspace(
            workspace_dir=workspace_dir,
            module_filename=module_filename,
            test_pattern=test_pattern,
            issue_description=issue_description,
            write_patch_to_workspace=write_patch_to_workspace,
            apply_approved_patch=apply_approved_patch,
            allow_workspace_model_disclosure=allow_workspace_model_disclosure,
        )
        out = res.to_dict()
        out["security_diagnostics"] = self.get_security_diagnostics()
        return out

    def execute(
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
        max_wall_clock_sec: Optional[float] = None,
        max_mission_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Executes a mission through `HierarchicalOrchestrator.execute_mission()`."""
        res = self.orchestrator.execute_mission(
            title=title,
            prompt=prompt,
            task_id=task_id,
            subtasks=subtasks,
            force_hierarchical=force_hierarchical,
            use_live_model=use_live_model,
            code_task_dir=code_task_dir,
            module_filename=module_filename,
            test_filename=test_filename,
            inject_deliberate_test_failure=inject_deliberate_test_failure,
            apply_approved_patch=apply_approved_patch,
            allow_workspace_model_disclosure=allow_workspace_model_disclosure,
            max_wall_clock_sec=max_wall_clock_sec,
            max_mission_tokens=max_mission_tokens,
        )
        if isinstance(res, dict):
            res.setdefault("security_diagnostics", self.get_security_diagnostics())
        self.progress_service.render_html_dashboard()
        return res

    execute_mission = execute

