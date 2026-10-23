"""
🌟 IVA — Autonomous Cognitive Engineering Partner & Multi-Agent Runtime.
================================================================================
"Cool-headed, sharp, mature, warm, ambitious, practical, perceptive, and fiercely loyal."
================================================================================
"""

__version__ = "1.7.29"
__author__ = "Abhishek"

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Primary cognitive architecture & runtime exports
from agents.IVA.engine.agi17.runtime.authoritative_brain_config import (
    AuthoritativeBrainConfig,
    CoreIdentityConfig,
    OperatingPolicyConfig,
)
from agents.IVA.engine.agi17.runtime.self_model import PersistentSelfModel
from agents.IVA.engine.agi17.memory.omega_command_memory import OmegaCommandMemory
from agents.IVA.engine.agi17.capabilities.unified_capability_registry import UnifiedCapabilityRegistry
from agents.IVA.ecosystem.agent_registry.ecosystem_coordinator import EcosystemCoordinator
from agents.IVA.engine.agi17.adapters.agi_17_adapter import AGI17Adapter
from agents.IVA.engine.agi17.orchestration.ci_repair_agent import CIRepairAgent

__all__ = [
    "AuthoritativeBrainConfig",
    "CoreIdentityConfig",
    "OperatingPolicyConfig",
    "PersistentSelfModel",
    "OmegaCommandMemory",
    "UnifiedCapabilityRegistry",
    "EcosystemCoordinator",
    "AGI17Adapter",
    "CIRepairAgent",
    "__version__",
]
