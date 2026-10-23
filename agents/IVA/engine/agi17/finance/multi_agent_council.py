"""AGI 1.7 OMEGA COMMAND — Multi-Agent Council & Governance Engine (Phase 17.15).

Implements Section 1:
Formalizes the 5-Agent Council structure, role contracts, delegation protocols,
performance metrics, and strict authority boundaries:
1. ABHI: Human Manager & Final Decision Authority (Personal financial sovereignty).
2. MAX: Chief Orchestrator & Operations Coordinator.
3. MATT: Quantitative Research & Algorithm Specialist.
4. EMILY: Browser, Screen-Cycle & Operator-Workflow Specialist.
5. ALEXA: New-Cycle Coordinator & Validation Scheduler.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class AgentRole(str, Enum):
    ABHI_MANAGER = "ABHI_MANAGER"
    MAX_ORCHESTRATOR = "MAX_ORCHESTRATOR"
    MATT_QUANT = "MATT_QUANT"
    EMILY_BROWSER = "EMILY_BROWSER"
    ALEXA_CYCLES = "ALEXA_CYCLES"


class TaskStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    AWAITING_ABHI_APPROVAL = "AWAITING_ABHI_APPROVAL"


@dataclass
class CouncilTask:
    task_id: str
    title: str
    assigned_agent: AgentRole
    created_by: AgentRole
    description: str
    acceptance_criteria: List[str]
    status: TaskStatus = TaskStatus.PROPOSED
    requires_abhi_approval: bool = False
    abhi_decision: Optional[str] = None       # APPROVED, REJECTED, DEFERRED
    evidence_path: Optional[str] = None
    created_at_ist: str = field(
        default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    )
    completed_at_ist: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["assigned_agent"] = self.assigned_agent.value
        d["created_by"] = self.created_by.value
        d["status"] = self.status.value
        return d


@dataclass
class AgentPerformanceMetrics:
    agent: AgentRole
    tasks_assigned: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_blocked: int = 0
    defects_discovered: int = 0
    tests_added: int = 0
    accuracy_rate_pct: float = 100.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["agent"] = self.agent.value
        return d


class MultiAgentCouncilCoordinator:
    """Coordinates task routing, agent performance metrics, and manager approvals."""

    def __init__(self) -> None:
        self.tasks: Dict[str, CouncilTask] = {}
        self.metrics: Dict[AgentRole, AgentPerformanceMetrics] = {
            role: AgentPerformanceMetrics(agent=role) for role in AgentRole
        }

    def create_task(
        self,
        title: str,
        assigned_agent: AgentRole,
        created_by: AgentRole,
        description: str,
        acceptance_criteria: List[str],
        requires_abhi_approval: bool = False,
    ) -> CouncilTask:
        """Max creates and routes a task with acceptance criteria."""
        uid = hashlib.sha256(f"{title}-{datetime.datetime.now().isoformat()}".encode()).hexdigest()[:8].upper()
        tid = f"TASK-{assigned_agent.name[:4]}-{uid}"

        initial_status = TaskStatus.AWAITING_ABHI_APPROVAL if requires_abhi_approval else TaskStatus.PROPOSED

        task = CouncilTask(
            task_id=tid,
            title=title,
            assigned_agent=assigned_agent,
            created_by=created_by,
            description=description,
            acceptance_criteria=acceptance_criteria,
            status=initial_status,
            requires_abhi_approval=requires_abhi_approval,
        )

        self.tasks[tid] = task
        self.metrics[assigned_agent].tasks_assigned += 1
        return task

    def record_manager_decision(
        self,
        task_id: str,
        decision: str,  # APPROVED, REJECTED, DEFERRED
        manager_notes: str = "",
    ) -> CouncilTask:
        """Abhi renders a formal manager decision on a pending task."""
        if task_id not in self.tasks:
            raise KeyError(f"Task '{task_id}' not found.")

        task = self.tasks[task_id]
        if not task.requires_abhi_approval:
            raise ValueError(f"Task '{task_id}' does not require manager approval.")

        task.abhi_decision = decision.upper()
        task.notes += f" [Manager Abhi Decision: {decision.upper()} - {manager_notes}]"

        if decision.upper() == "APPROVED":
            task.status = TaskStatus.IN_PROGRESS
        elif decision.upper() == "REJECTED":
            task.status = TaskStatus.BLOCKED
            self.metrics[task.assigned_agent].tasks_blocked += 1
        else:
            task.status = TaskStatus.AWAITING_ABHI_APPROVAL

        return task

    def complete_task(
        self,
        task_id: str,
        evidence_path: str,
        defects_found: int = 0,
        tests_added: int = 0,
    ) -> CouncilTask:
        """Records task completion backed by an empirical evidence path."""
        if task_id not in self.tasks:
            raise KeyError(f"Task '{task_id}' not found.")

        task = self.tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.evidence_path = evidence_path
        task.completed_at_ist = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

        m = self.metrics[task.assigned_agent]
        m.tasks_completed += 1
        m.defects_discovered += defects_found
        m.tests_added += tests_added

        # Recalculate accuracy rate
        total_finished = m.tasks_completed + m.tasks_failed
        if total_finished > 0:
            m.accuracy_rate_pct = round((m.tasks_completed / total_finished) * 100.0, 2)

        return task

    def get_council_summary(self) -> Dict[str, Any]:
        """Provides a consolidated operational summary of council activity."""
        return {
            "total_tasks": len(self.tasks),
            "pending_abhi_approvals": sum(1 for t in self.tasks.values() if t.status == TaskStatus.AWAITING_ABHI_APPROVAL),
            "active_tasks": sum(1 for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS),
            "completed_tasks": sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED),
            "blocked_tasks": sum(1 for t in self.tasks.values() if t.status == TaskStatus.BLOCKED),
            "agent_performance": {role.value: m.to_dict() for role, m in self.metrics.items()},
        }
