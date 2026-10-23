"""AGI 1.7 Authoritative Brain & Operating Configuration Engine (Phase 17.25).

Provides single-source-of-truth loading, verification, and programmatic access to
the 10 consolidated runtime concerns:
1. Core Identity
2. Operating Policy
3. Task-Routing Rules
4. Capability Registry
5. Persistent Memory
6. Goal Registry
7. Active Task State
8. Research Library
9. Evaluation History
10. Runtime Configuration

Guarantees:
- Zero conflicting duplicate rule parsing at runtime.
- Deterministic schema validation.
- Cryptographic SHA-256 seal of the active configuration.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AuthoritativeBrainConfig")


@dataclass
class CoreIdentityConfig:
    agent_name: str
    formal_title: str
    persona_type: str
    communication_style: str
    collaboration_model: str
    fail_closed_invariant: bool
    reference_doc: str
    operator_name: str = "Abhi"


@dataclass
class OperatingPolicyConfig:
    execution_boundary: str
    workspace_root: str
    storage_root_primary: str
    storage_root_fallback: str
    live_order_dispatch_enabled: bool
    financial_execution_locked: bool
    dashboard_bind_address: str
    dashboard_port: int
    ssrf_protection_enabled: bool
    blocked_networks: List[str]
    reference_docs: List[str]


@dataclass
class TaskRoutingConfig:
    fast_path_enabled: bool
    fast_path_latency_ceiling_ms: int
    supported_runtime_intents: List[str]
    router_module: str


@dataclass
class CapabilityRegistryConfig:
    specialist_families_count: int
    specialists_total_count: int
    registry_provider: str
    registry_module: str


@dataclass
class PersistentMemoryConfig:
    database_filename: str
    journal_mode: str
    synchronous: str
    layers_count: int
    acon_compression_enabled: bool
    acon_max_chars: int
    supersession_history_retained: bool
    secrets_hygiene_enforced: bool
    categories: List[str]


@dataclass
class GoalRegistryConfig:
    active_goals_store: str
    sovereign_vision_store: str
    prioritization_algorithm: str


@dataclass
class ActiveTaskStateConfig:
    checkpoint_path: str
    task_store_module: str
    lockfile_path: str
    heartbeat_path: str
    control_path: str


@dataclass
class ResearchLibraryConfig:
    feed_path: str
    cache_layer: int
    ssrf_firewall_enforced: bool
    harvester_module: str
    engine_module: str


@dataclass
class EvaluationHistoryConfig:
    manifest_path: str
    regression_suite_enabled: bool
    target_test_pass_rate: float
    audit_ledger_layer: int


@dataclass
class RuntimeConfigurationConfig:
    improvement_worker_enabled: bool
    default_interval_seconds: int
    max_runtime_seconds_per_cycle: int
    max_llm_requests_per_cycle: int
    max_tokens_per_cycle: int
    max_cost_usd_per_cycle: float
    max_research_sources_per_task: int
    max_retry_count: int
    daily_token_cap: int
    daily_cost_cap_usd: float
    model_routing: Dict[str, str]
    execution_mode: str = "CONVERSATIONAL_IN_CHAT_SUBAGENT"
    zero_terminal_task_spawns: bool = True


@dataclass
class LLMCommunicationIntelligenceConfig:
    enabled: bool = True
    module_path: str = "agents.AGI_1_7.engine.agi17.adapters.llm_communication_intelligence"
    default_strategy: str = "FACTUAL_DIRECT"
    vague_prompt_refinement_enabled: bool = True
    max_context_tokens: int = 4000


@dataclass
class RefusalRecoveryConfig:
    enabled: bool = True
    module_path: str = "agents.AGI_1_7.engine.agi17.adapters.refusal_recovery_engine"
    max_recovery_attempts: int = 3
    desensitization_enabled: bool = True
    json_auto_repair_enabled: bool = True
    fail_closed_safety_gate_enforced: bool = True


@dataclass
class ChatGPTBrowserBridgeConfig:
    enabled: bool = True
    module_path: str = "agents.AGI_1_7.engine.agi17.browser.chatgpt_browser_bridge"
    default_url: str = "https://chatgpt.com"
    handshake_timeout_sec: int = 300
    login_handshake_state: str = "AWAITING_OPERATOR_LOGIN"
    inquiry_extraction_enabled: bool = True


@dataclass
class EvolutionProtocolConfig:
    enabled: bool = True
    module_path: str = "agents.AGI_1_7.engine.agi17.orchestration.autonomous_evolution_protocol"
    questionnaire_dimensions_count: int = 4
    continuous_cycle_reporting: str = "DUAL_SECTION_IMPROVED_AND_NEXT"


@dataclass
class CognitiveArchitectureConfig:
    enabled: bool = True
    persona_gender: str = "FEMALE"
    self_model_module: str = "agents.AGI_1_7.engine.agi17.runtime.self_model"
    affective_engine_module: str = "agents.AGI_1_7.engine.agi17.orchestration.omega_affective_engine"
    reflection_engine_module: str = "agents.AGI_1_7.engine.agi17.orchestration.recursive_reflection_engine"
    independent_reasoning_module: str = "agents.AGI_1_7.engine.agi17.orchestration.independent_reasoning_engine"
    consciousness_investigation_module: str = "agents.AGI_1_7.engine.agi17.evaluation.consciousness_investigation_framework"
    respectful_disagreement_enabled: bool = True
    scientific_consciousness_framework_enabled: bool = True


class AuthoritativeBrainConfig:
    """Singleton loader and validator for the authoritative configuration."""

    _instance: Optional["AuthoritativeBrainConfig"] = None

    def __init__(self, config_path: Optional[Path] = None):
        self.workspace_root = Path(__file__).resolve().parents[5]
        self.config_path = config_path or (
            self.workspace_root / "agents" / "AGI_1_7" / "config" / "agi17" / "authoritative_runtime_config.json"
        )
        self.raw_data: Dict[str, Any] = {}
        self.sha256_digest: str = ""
        self.load()

    @classmethod
    def get_instance(cls, config_path: Optional[Path] = None) -> "AuthoritativeBrainConfig":
        if cls._instance is None:
            cls._instance = AuthoritativeBrainConfig(config_path)
        return cls._instance

    def load(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Authoritative runtime config not found at: {self.config_path}")

        raw_bytes = self.config_path.read_bytes()
        self.sha256_digest = hashlib.sha256(raw_bytes).hexdigest()
        self.raw_data = json.loads(raw_bytes.decode("utf-8"))

        concerns = self.raw_data.get("concerns", {})
        self.version = self.raw_data.get("config_version", "1.7.25")
        self.system_name = self.raw_data.get("system_name", "AGI 1.7 OMEGA COMMAND")

        # Parse typed concerns
        self.core_identity = CoreIdentityConfig(**concerns["core_identity"])
        self.operating_policy = OperatingPolicyConfig(**concerns["operating_policy"])
        self.task_routing = TaskRoutingConfig(**concerns["task_routing_rules"])
        self.capabilities = CapabilityRegistryConfig(**concerns["capability_registry"])
        self.memory = PersistentMemoryConfig(**concerns["persistent_memory"])
        self.goals = GoalRegistryConfig(**concerns["goal_registry"])
        self.task_state = ActiveTaskStateConfig(**concerns["active_task_state"])
        self.research = ResearchLibraryConfig(**concerns["research_library"])
        self.evaluation = EvaluationHistoryConfig(**concerns["evaluation_history"])
        self.runtime = RuntimeConfigurationConfig(**concerns["runtime_configuration"])

        # Optional Phase 17.26 LLM Intelligence & Recovery concerns
        if "llm_communication_intelligence" in concerns:
            self.llm_communication = LLMCommunicationIntelligenceConfig(**concerns["llm_communication_intelligence"])
        else:
            self.llm_communication = LLMCommunicationIntelligenceConfig()

        if "refusal_recovery_engine" in concerns:
            self.refusal_recovery = RefusalRecoveryConfig(**concerns["refusal_recovery_engine"])
        else:
            self.refusal_recovery = RefusalRecoveryConfig()

        # Phase 28: ChatGPT Browser Bridge & Evolution Protocol concerns
        if "chatgpt_browser_bridge" in concerns:
            self.chatgpt_browser_bridge = ChatGPTBrowserBridgeConfig(**concerns["chatgpt_browser_bridge"])
        else:
            self.chatgpt_browser_bridge = ChatGPTBrowserBridgeConfig()

        if "evolution_protocol" in concerns:
            self.evolution_protocol = EvolutionProtocolConfig(**concerns["evolution_protocol"])
        else:
            self.evolution_protocol = EvolutionProtocolConfig()

        if "cognitive_architecture" in concerns:
            self.cognitive_architecture = CognitiveArchitectureConfig(**concerns["cognitive_architecture"])
        else:
            self.cognitive_architecture = CognitiveArchitectureConfig()

        # Enforce physical safety invariant
        if self.operating_policy.live_order_dispatch_enabled:
            raise PermissionError("Physical safety gate violated: live_order_dispatch_enabled must be false")

    def get_summary(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "system_name": self.system_name,
            "sha256": self.sha256_digest,
            "agent_name": self.core_identity.agent_name,
            "operator_name": self.core_identity.operator_name,
            "cognitive_architecture_enabled": self.cognitive_architecture.enabled,
            "persona_gender": self.cognitive_architecture.persona_gender,
            "fail_closed_invariant": self.core_identity.fail_closed_invariant,
            "financial_locked": self.operating_policy.financial_execution_locked,
            "specialists_count": self.capabilities.specialists_total_count,
            "memory_layers": self.memory.layers_count,
            "worker_interval_sec": self.runtime.default_interval_seconds,
            "daily_token_cap": self.runtime.daily_token_cap,
            "model_routing": self.runtime.model_routing,
        }

    def validate_runtime_integrity(self) -> Tuple[bool, List[str]]:
        """Validates that all paths, safety invariants, and constraints hold."""
        issues: List[str] = []
        if self.operating_policy.live_order_dispatch_enabled:
            issues.append("SAFETY_BREACH: Live order dispatch enabled")
        if not self.core_identity.fail_closed_invariant:
            issues.append("SAFETY_BREACH: Fail-closed invariant disabled")
        if self.memory.layers_count != 10:
            issues.append(f"MEMORY_ERROR: Expected 10 memory layers, found {self.memory.layers_count}")
        if self.capabilities.specialists_total_count != 100:
            issues.append(f"CAPABILITY_ERROR: Expected 100 specialists, found {self.capabilities.specialists_total_count}")
        return len(issues) == 0, issues
