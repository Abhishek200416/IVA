"""AGI 1.7 Specialist Registry Validator.

Validates that registry.json contains exactly 100 distinct, non-duplicate
specialists across the 16 required functional families with valid schemas,
disjoint required/forbidden tool sets, bounded budgets, and verification hooks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .agent_contract import REQUIRED_FAMILIES_COUNTS, AgentContract, ExecutionMode


class RegistryValidationError(ValueError):
    """Raised when the 100-specialist registry fails contract validation."""


class RegistryValidator:
    """Validates the 100-specialist registry contract."""

    VALID_EXECUTION_MODES: Set[str] = {m.value for m in ExecutionMode}
    VALID_RESOURCE_CLASSES: Set[str] = {"LIGHT", "MEDIUM", "HEAVY", "CONTAINER"}
    VALID_EFFORT_TIERS: Set[str] = {"low", "medium", "high", "xhigh", "max"}

    @classmethod
    def validate_contracts(cls, contracts: List[AgentContract]) -> Dict[str, Any]:
        errors: List[str] = []

        if len(contracts) != 100:
            errors.append(f"Expected exactly 100 specialists, found {len(contracts)}")

        seen_ids: Set[str] = set()
        seen_names: Set[str] = set()
        seen_capability_signatures: Set[Tuple[str, ...]] = set()
        family_counts: Dict[str, int] = {fam: 0 for fam in REQUIRED_FAMILIES_COUNTS}

        for idx, c in enumerate(contracts):
            if not c.agent_id or c.agent_id in seen_ids:
                errors.append(f"Duplicate or empty agent_id at index {idx}: {c.agent_id}")
            seen_ids.add(c.agent_id)

            if not c.display_name or c.display_name in seen_names:
                errors.append(f"Duplicate or empty display_name for {c.agent_id}: {c.display_name}")
            seen_names.add(c.display_name)

            if c.family not in REQUIRED_FAMILIES_COUNTS:
                errors.append(f"Unknown family for {c.agent_id}: {c.family}")
            else:
                family_counts[c.family] += 1

            if len(c.primary_capabilities) < 2:
                errors.append(f"{c.agent_id} must define at least 2 primary_capabilities")

            cap_sig = tuple(sorted(cap.strip().lower() for cap in c.primary_capabilities))
            if cap_sig in seen_capability_signatures:
                errors.append(f"Duplicate primary_capabilities signature on {c.agent_id}: {cap_sig}")
            seen_capability_signatures.add(cap_sig)

            if not c.non_goals:
                errors.append(f"{c.agent_id} must specify non_goals")

            overlap_tools = set(c.required_tools) & set(c.forbidden_tools)
            if overlap_tools:
                errors.append(f"{c.agent_id} has overlapping required and forbidden tools: {overlap_tools}")

            if c.execution_mode not in cls.VALID_EXECUTION_MODES:
                errors.append(f"{c.agent_id} has invalid execution_mode: {c.execution_mode}")

            if c.resource_class not in cls.VALID_RESOURCE_CLASSES:
                errors.append(f"{c.agent_id} has invalid resource_class: {c.resource_class}")

            if c.default_effort_tier not in cls.VALID_EFFORT_TIERS:
                errors.append(f"{c.agent_id} has invalid default_effort_tier: {c.default_effort_tier}")

            if c.max_token_budget <= 0 or c.max_token_budget > 200_000:
                errors.append(f"{c.agent_id} has out-of-bounds max_token_budget: {c.max_token_budget}")

            if c.max_wall_clock_seconds <= 0 or c.max_wall_clock_seconds > 3600:
                errors.append(f"{c.agent_id} has out-of-bounds max_wall_clock_seconds: {c.max_wall_clock_seconds}")

            if c.max_retries < 0 or c.max_retries > 5:
                errors.append(f"{c.agent_id} has out-of-bounds max_retries: {c.max_retries}")

            if not isinstance(c.input_schema, dict) or "required" not in c.input_schema:
                errors.append(f"{c.agent_id} missing valid input_schema with 'required'")

            if not isinstance(c.output_schema, dict) or "required" not in c.output_schema:
                errors.append(f"{c.agent_id} missing valid output_schema with 'required'")

            if not c.verification_hook:
                errors.append(f"{c.agent_id} missing verification_hook")

            if not isinstance(c.smoke_test_case, dict) or "task_prompt" not in c.smoke_test_case:
                errors.append(f"{c.agent_id} missing valid smoke_test_case")

        for fam, expected_cnt in REQUIRED_FAMILIES_COUNTS.items():
            actual_cnt = family_counts.get(fam, 0)
            if actual_cnt != expected_cnt:
                errors.append(f"Family '{fam}' count mismatch: expected {expected_cnt}, got {actual_cnt}")

        if errors:
            raise RegistryValidationError("Registry validation failed:\n- " + "\n- ".join(errors[:25]))

        return {
            "valid": True,
            "total_specialists": len(contracts),
            "unique_ids": len(seen_ids),
            "unique_capability_signatures": len(seen_capability_signatures),
            "family_counts": family_counts,
        }

    @classmethod
    def validate_registry_file(cls, registry_path: str | Path) -> Dict[str, Any]:
        p = Path(registry_path)
        data = json.loads(p.read_text(encoding="utf-8"))
        raw_list = data.get("specialists", [])
        contracts = [AgentContract.from_dict(item) for item in raw_list]
        return cls.validate_contracts(contracts)
