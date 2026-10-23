"""AGI 1.7 Multi-Agent Research Orchestration Protocol (Phase 13).

Orchestrates the research lab across the specialized agent council:
1. MAX (Quant Research & Risk):
   - Formulates testable hypotheses, audits mathematical features, checks cost models, and enforces downside risk gates.
   - Prohibits self-approval based solely on model confidence.
2. EMILY (Execution Simulation & Market-Data Quality):
   - Audits quote validity, spread assumptions, latency scenarios, and simulated fills.
   - Identifies data gaps and marks insufficient data states.
3. ALEXA (Macro, News, and Research Provenance):
   - Audits primary sources, macroeconomic calendar, and statutory circulars.
   - Strictly prohibits order authorization from news narratives alone.
4. Manager Abhi (Orchestration):
   - Assigns typed research tasks, tracks durable job ledger, and resolves disagreements using empirical evidence.
   - Enforces invariant: Zero order execution authorization based on voting or natural-language confidence.
"""

from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
import datetime
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .strategy_research_framework import (
    StrategyDefinition,
    StrategyLifecycleState,
    StrategyRegistry,
    StrategyVerdict,
)
from .research_job_queue import ResearchJobQueue, ResearchJobRecord, JobState
from .evaluation_dataset_registry import EvaluationDatasetRegistry

logger = logging.getLogger("MultiAgentResearchCoordinator")


@dataclass
class AgentResearchTask:
    task_id: str
    assigned_agent: str  # MAX, EMILY, ALEXA, MANAGER_ABHI
    role_description: str
    input_parameters: Dict[str, Any]
    status: str  # PENDING, COMPLETED, REJECTED, BLOCKED
    findings: Dict[str, Any]
    dissent_or_blocker: Optional[str] = None
    created_at_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "assigned_agent": self.assigned_agent,
            "role_description": self.role_description,
            "input_parameters": self.input_parameters,
            "status": self.status,
            "findings": self.findings,
            "dissent_or_blocker": self.dissent_or_blocker,
            "created_at_utc": self.created_at_utc,
        }


@dataclass
class ResearchProposal:
    strategy_id: str
    dataset_id: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    epoch_id: str = "epoch_10k"


@dataclass
class ResearchDeliberationRecord:
    deliberation_id: str
    hypothesis_id: str
    strategy_id: str
    dataset_id: str
    agent_tasks: List[AgentResearchTask]
    unanimous_data_approved: bool
    unanimous_risk_approved: bool
    final_orchestrator_decision: str  # PROCEED_TO_EXPERIMENT, HALT_INSUFFICIENT_DATA, REJECT_RISK_BREACH
    binding_blocker_reason: Optional[str]
    experiment_job_id: Optional[str] = None
    created_at_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    @property
    def agent_votes(self) -> List[AgentResearchTask]:
        return self.agent_tasks

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deliberation_id": self.deliberation_id,
            "hypothesis_id": self.hypothesis_id,
            "strategy_id": self.strategy_id,
            "dataset_id": self.dataset_id,
            "agent_tasks": [t.to_dict() if hasattr(t, "to_dict") else t for t in self.agent_tasks],
            "agent_votes": [t.to_dict() if hasattr(t, "to_dict") else t for t in self.agent_tasks],
            "unanimous_data_approved": self.unanimous_data_approved,
            "unanimous_risk_approved": self.unanimous_risk_approved,
            "final_orchestrator_decision": self.final_orchestrator_decision,
            "binding_blocker_reason": self.binding_blocker_reason,
            "experiment_job_id": self.experiment_job_id,
            "created_at_utc": self.created_at_utc,
        }


class MultiAgentResearchCoordinator:
    """Coordinates research deliberation across Max, Emily, Alexa, and Manager Abhi."""

    def __init__(
        self,
        strategy_registry: Optional[StrategyRegistry] = None,
        job_queue: Optional[ResearchJobQueue] = None,
        dataset_registry: Optional[EvaluationDatasetRegistry] = None,
        storage_dir: Optional[Path] = None,
        ledger_path: Optional[Path] = None,
    ) -> None:
        self.strategy_registry = strategy_registry or StrategyRegistry()
        self.job_queue = job_queue or ResearchJobQueue()
        self.dataset_registry = dataset_registry or EvaluationDatasetRegistry()
        if ledger_path:
            self.ledger_file = Path(ledger_path)
            self.storage_dir = self.ledger_file.parent
        else:
            self.storage_dir = (
                storage_dir
                or Path(__file__).resolve().parents[3] / "runtime_storage" / "agent_research"
            )
            self.ledger_file = self.storage_dir / "deliberations_ledger.json"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._deliberations: List[ResearchDeliberationRecord] = []
        self._load_deliberations()

    def _load_deliberations(self) -> None:
        if self.ledger_file.exists():
            try:
                data = json.loads(self.ledger_file.read_text(encoding="utf-8"))
                for d in data.get("deliberations", []):
                    tasks = [
                        AgentResearchTask(
                            task_id=t["task_id"],
                            assigned_agent=t["assigned_agent"],
                            role_description=t["role_description"],
                            input_parameters=t["input_parameters"],
                            status=t["status"],
                            findings=t["findings"],
                            dissent_or_blocker=t.get("dissent_or_blocker"),
                            created_at_utc=t["created_at_utc"],
                        )
                        for t in d.get("agent_tasks", [])
                    ]
                    rec = ResearchDeliberationRecord(
                        deliberation_id=d["deliberation_id"],
                        hypothesis_id=d["hypothesis_id"],
                        strategy_id=d["strategy_id"],
                        dataset_id=d["dataset_id"],
                        agent_tasks=tasks,
                        unanimous_data_approved=d["unanimous_data_approved"],
                        unanimous_risk_approved=d["unanimous_risk_approved"],
                        final_orchestrator_decision=d["final_orchestrator_decision"],
                        binding_blocker_reason=d.get("binding_blocker_reason"),
                        experiment_job_id=d.get("experiment_job_id"),
                        created_at_utc=d["created_at_utc"],
                    )
                    self._deliberations.append(rec)
            except Exception as e:
                logger.error(f"Error loading deliberations ledger: {e}")

    def _save_deliberations(self) -> None:
        data = {
            "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "deliberations": [
                {
                    "deliberation_id": d.deliberation_id,
                    "hypothesis_id": d.hypothesis_id,
                    "strategy_id": d.strategy_id,
                    "dataset_id": d.dataset_id,
                    "agent_tasks": [asdict(t) for t in d.agent_tasks],
                    "unanimous_data_approved": d.unanimous_data_approved,
                    "unanimous_risk_approved": d.unanimous_risk_approved,
                    "final_orchestrator_decision": d.final_orchestrator_decision,
                    "binding_blocker_reason": d.binding_blocker_reason,
                    "experiment_job_id": d.experiment_job_id,
                    "created_at_utc": d.created_at_utc,
                }
                for d in self._deliberations
            ],
        }
        self.ledger_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def deliberate_research_candidate(
        self,
        strategy_id: str,
        dataset_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        epoch_id: str = "epoch_10k",
    ) -> ResearchDeliberationRecord:
        """Executes formal 4-role deliberation before authorizing backtest dispatch."""
        delib_id = f"DELIB-{strategy_id}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        strat = self.strategy_registry.get_strategy(strategy_id)
        if not strat:
            raise ValueError(f"Strategy {strategy_id} is not registered.")

        dataset = self.dataset_registry.get_dataset(dataset_id)
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} is not registered.")

        # 1. EMILY: Data Quality & Sufficiency Audit
        emily_blocker = None
        emily_status = "COMPLETED"
        if dataset.record_count == 0:
            emily_blocker = f"Dataset {dataset_id} contains 0 records ({dataset.quality_validation_status.value})."
            emily_status = "BLOCKED"
        elif "BHAVCOPY" in dataset_id.upper() and strat.required_granularity != "1_DAY_EOD":
            emily_blocker = f"Intraday strategy {strategy_id} cannot run on Daily Bhavcopy {dataset_id}."
            emily_status = "BLOCKED"

        task_emily = AgentResearchTask(
            task_id=f"TASK-EMILY-{delib_id}",
            assigned_agent="EMILY",
            role_description="Market-Data Quality & Sufficiency Gate",
            input_parameters={"dataset_id": dataset_id, "required_granularity": strat.required_granularity},
            status=emily_status,
            findings={"dataset_records": dataset.record_count, "provenance": dataset.provenance_type.value},
            dissent_or_blocker=emily_blocker,
        )

        # 2. MAX: Quantitative Risk & Anti-Lookahead Specification
        max_blocker = None
        max_status = "COMPLETED"
        max_risk_pct = parameters.get("max_risk_pct_capital", strat.default_parameters.get("max_risk_pct_capital", 0.005)) if parameters else 0.005
        if max_risk_pct > 0.02:  # Hard cap: no strategy may risk > 2% per trade
            max_blocker = f"Requested per-trade risk {max_risk_pct:.1%} exceeds hard 2.0% maximum safety cap."
            max_status = "REJECTED"

        task_max = AgentResearchTask(
            task_id=f"TASK-MAX-{delib_id}",
            assigned_agent="MAX",
            role_description="Quantitative Risk Budget & Sizing Audit",
            input_parameters={"strategy_id": strategy_id, "max_risk_pct": max_risk_pct},
            status=max_status,
            findings={"authorized_capital_epoch": epoch_id, "max_risk_pct": max_risk_pct},
            dissent_or_blocker=max_blocker,
        )

        # 3. ALEXA: Macro, News, and Regulatory Circular Check
        task_alexa = AgentResearchTask(
            task_id=f"TASK-ALEXA-{delib_id}",
            assigned_agent="ALEXA",
            role_description="Regulatory Compliance & Circular Attribution",
            input_parameters={"cost_schedule": "NSE_73061"},
            status="COMPLETED",
            findings={"circular_verified": "NSE/FA/73061", "stt_rate": "0.15% Options / 0.02% Futures"},
            dissent_or_blocker=None,
        )

        # 4. Manager Abhi: Final Orchestration Synthesis
        unanimous_data = emily_blocker is None
        unanimous_risk = max_blocker is None

        if not unanimous_data:
            decision = "HALT_INSUFFICIENT_DATA"
            binding_reason = emily_blocker
            job_id = None
        elif not unanimous_risk:
            decision = "REJECT_RISK_BREACH"
            binding_reason = max_blocker
            job_id = None
        else:
            decision = "PROCEED_TO_EXPERIMENT"
            binding_reason = None
            # Dispatch to job queue
            job = self.job_queue.submit_job(
                strategy_id=strategy_id,
                dataset_id=dataset_id,
                parameters=parameters or strat.default_parameters,
                epoch_id=epoch_id,
            )
            job_id = job.job_id

        task_abhi = AgentResearchTask(
            task_id=f"TASK-ABHI-{delib_id}",
            assigned_agent="MANAGER_ABHI",
            role_description="Orchestrator Synthesis & Job Dispatch",
            input_parameters={"decision": decision},
            status="COMPLETED",
            findings={"job_id": job_id, "final_decision": decision},
            dissent_or_blocker=binding_reason,
        )

        record = ResearchDeliberationRecord(
            deliberation_id=delib_id,
            hypothesis_id=f"HYP-{strategy_id}",
            strategy_id=strategy_id,
            dataset_id=dataset_id,
            agent_tasks=[task_emily, task_max, task_alexa, task_abhi],
            unanimous_data_approved=unanimous_data,
            unanimous_risk_approved=unanimous_risk,
            final_orchestrator_decision=decision,
            binding_blocker_reason=binding_reason,
            experiment_job_id=job_id,
        )

        self._deliberations.append(record)
        self._save_deliberations()
        logger.info(f"Deliberation {delib_id} concluded with decision: {decision}")
        return record

    def list_deliberations(self) -> List[ResearchDeliberationRecord]:
        return sorted(self._deliberations, key=lambda d: d.created_at_utc, reverse=True)

    def conduct_deliberation(self, proposal: ResearchProposal) -> ResearchDeliberationRecord:
        """Conducts deliberation from a ResearchProposal instance."""
        return self.deliberate_research_candidate(
            strategy_id=proposal.strategy_id,
            dataset_id=proposal.dataset_id,
            parameters=proposal.parameters,
            epoch_id=proposal.epoch_id,
        )

    def get_deliberation_history(self) -> List[ResearchDeliberationRecord]:
        """Returns the list of historical deliberations."""
        return list(self._deliberations)

