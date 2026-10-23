"""AGI 1.7 Specialist Agent Contract & Execution Modes.

Defines the strict schema for all 100 specialist roles in the AGI 1.7 registry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List


class ExecutionMode(str, Enum):
    IN_PROCESS_TOOL_WORKER = "IN_PROCESS_TOOL_WORKER"
    SUPERVISED_SUBPROCESS_WORKER = "SUPERVISED_SUBPROCESS_WORKER"
    MODEL_SPECIALIST_WORKER = "MODEL_SPECIALIST_WORKER"
    ISOLATED_CONTAINER_WORKER = "ISOLATED_CONTAINER_WORKER"


REQUIRED_FAMILIES_COUNTS: Dict[str, int] = {
    "Planning & Architecture": 6,
    "Research & Evidence Synthesis": 8,
    "Mathematics & Symbolic Reasoning": 6,
    "Physics & Physical Sciences": 6,
    "Chemistry & Molecular Sciences": 5,
    "Biology & Biomedical Sciences": 5,
    "Software Engineering": 10,
    "Terminal, Shell & OS Operations": 8,
    "Containers, Virtualization & Cloud": 6,
    "Browser & Web Automation": 6,
    "Desktop & Computer Use": 6,
    "Data, Storage & Databases": 6,
    "Testing, QA & Verification": 8,
    "Security, Permissions & Safety": 6,
    "Performance, Token & Resource Optimization": 4,
    "Release, Governance & Reporting": 4,
}


@dataclass
class AgentContract:
    agent_id: str
    display_name: str
    family: str
    primary_capabilities: List[str]
    non_goals: List[str]
    required_tools: List[str]
    forbidden_tools: List[str]
    execution_mode: str
    resource_class: str  # "LIGHT" | "MEDIUM" | "HEAVY" | "CONTAINER"
    default_effort_tier: str  # "low" | "medium" | "high" | "xhigh"
    max_token_budget: int
    max_wall_clock_seconds: int
    max_retries: int
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    verification_hook: str
    smoke_test_case: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentContract":
        return cls(**data)
