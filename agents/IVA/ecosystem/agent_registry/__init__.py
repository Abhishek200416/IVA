"""AGI 1.7 100-Specialist Agent Registry Package."""

from .agent_contract import REQUIRED_FAMILIES_COUNTS, AgentContract, ExecutionMode
from .capability_router import CapabilityRouter
from .registry_validator import RegistryValidationError, RegistryValidator
from .specialist_factory import (
    SPECIALIST_SPECS,
    SpecialistFactory,
    SpecialistInstance,
    build_default_contracts,
)

__all__ = [
    "ExecutionMode",
    "REQUIRED_FAMILIES_COUNTS",
    "AgentContract",
    "RegistryValidationError",
    "RegistryValidator",
    "CapabilityRouter",
    "SPECIALIST_SPECS",
    "build_default_contracts",
    "SpecialistInstance",
    "SpecialistFactory",
]
