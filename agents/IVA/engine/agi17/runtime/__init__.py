"""AGI 1.7 OMEGA COMMAND — Runtime Orchestration & Supervisor Subsystem (Phase 17.19).

Provides deterministic conversational command routing, authoritative service supervision,
three-role browser topology management, dual-index data synchronization, and bounded news intelligence.
"""

from .command_router import CommandRouter, CommandIntent, SetupSession
from .runtime_supervisor import RuntimeSupervisor, ServiceState, ServiceStatus
from .tri_tab_topology import TriTabTopology, TabRole, BrowserTarget
from .dual_index_pipeline import DualIndexEventPipeline, MarketDataProvenance, NormalizedObservation
from .news_monitor import NewsMonitorService
from .omega_control_center import (
    AlgorithmCatalogService,
    AgentCatalogService,
    OrchestrationServiceProvider,
    DeploymentReadinessAssessor,
    get_algorithm_catalog,
    get_agent_catalog,
    get_orchestration_service,
    get_readiness_assessor,
)

__all__ = [
    "CommandRouter",
    "CommandIntent",
    "SetupSession",
    "RuntimeSupervisor",
    "ServiceState",
    "ServiceStatus",
    "TriTabTopology",
    "TabRole",
    "BrowserTarget",
    "DualIndexEventPipeline",
    "MarketDataProvenance",
    "NormalizedObservation",
    "NewsMonitorService",
    "AlgorithmCatalogService",
    "AgentCatalogService",
    "OrchestrationServiceProvider",
    "DeploymentReadinessAssessor",
    "get_algorithm_catalog",
    "get_agent_catalog",
    "get_orchestration_service",
    "get_readiness_assessor",
]
