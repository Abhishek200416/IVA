"""AGI 1.7 OMEGA COMMAND — Least-Privilege Enforcer & Secrets Hygiene (Phase 17.22).

Implements Track 51 & Track 53:
1. Least-Privilege Enforcer:
   - Role-based tool access validation (READ_ONLY vs CODE_EDIT vs RUNTIME_OPS vs FINANCIAL_EXECUTION).
   - Validates requested tool against the calling specialist's contract manifest.
   - Permanent fail-closed block on live real-money order routing (`GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK`).

2. Secrets Hygiene Auditor:
   - High-precision regex pattern scanning for API tokens (OpenAI, Gemini, Paytm, JWTs, private keys).
   - In-place redaction before writing to logs, memory DB, or HTTP dashboard responses.
   - Secrets scanner for workspace files and commits.
"""

from __future__ import annotations

import enum
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("LeastPrivilegeEnforcer")


class SecurityPermissionTier(str, enum.Enum):
    READ_ONLY = "READ_ONLY"
    WORKSPACE_CODE_EDIT = "WORKSPACE_CODE_EDIT"
    RUNTIME_MANAGEMENT = "RUNTIME_MANAGEMENT"
    FINANCIAL_EXECUTION = "FINANCIAL_EXECUTION"
    EXTERNAL_NETWORK = "EXTERNAL_NETWORK"


# High-precision patterns for secret detection
SECRET_PATTERNS = [
    ("OPENAI_KEY", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GEMINI_KEY", re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b")),
    ("GENERIC_BEARER", re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{25,}\b", re.IGNORECASE)),
    ("PAYTM_TOKEN", re.compile(r"\b(?:paytm|jwt)[_-]token\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{30,})['\"]?", re.IGNORECASE)),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    ("PASSWORD_FIELD", re.compile(r"(?:password|passwd|secret_key)[^\S\r\n]*[:=][^\S\r\n]*['\"]([^'\r\n\"]{8,})['\"]", re.IGNORECASE)),
]


class PermissionDeniedError(PermissionError):
    """Raised when an agent attempts an action outside its authorized permission tier."""


class LeastPrivilegeEnforcer:
    """Enforces role-based tool restrictions and prevents privilege escalation."""

    # Explicit role-to-tier mappings
    ROLE_TIERS: Dict[str, Set[SecurityPermissionTier]] = {
        # Strategy / Research specialists: Read-only + External research
        "alexa_strategy_coordinator": {SecurityPermissionTier.READ_ONLY, SecurityPermissionTier.EXTERNAL_NETWORK},
        "res_primary_source_hunter": {SecurityPermissionTier.READ_ONLY, SecurityPermissionTier.EXTERNAL_NETWORK},
        "res_citation_auditor": {SecurityPermissionTier.READ_ONLY},
        # Software engineers: Read + Code edit + Local test commands
        "swe_python_runtime_engineer": {SecurityPermissionTier.READ_ONLY, SecurityPermissionTier.WORKSPACE_CODE_EDIT},
        "swe_ast_refactoring_specialist": {SecurityPermissionTier.READ_ONLY, SecurityPermissionTier.WORKSPACE_CODE_EDIT},
        # Risk / Execution specialists: Read + Financial paper execution (Live locked)
        "max_quant_risk_specialist": {SecurityPermissionTier.READ_ONLY, SecurityPermissionTier.FINANCIAL_EXECUTION},
        "emily_execution_warden": {SecurityPermissionTier.READ_ONLY, SecurityPermissionTier.FINANCIAL_EXECUTION},
        # System supervisors: Runtime ops
        "overlay_guardian_daemon": {SecurityPermissionTier.READ_ONLY, SecurityPermissionTier.RUNTIME_MANAGEMENT},
        "standalone_dashboard_daemon": {SecurityPermissionTier.READ_ONLY, SecurityPermissionTier.RUNTIME_MANAGEMENT},
        # Executive Orchestrator: All tiers EXCEPT live real-money execution
        "agi_omega_orchestrator": {
            SecurityPermissionTier.READ_ONLY,
            SecurityPermissionTier.WORKSPACE_CODE_EDIT,
            SecurityPermissionTier.RUNTIME_MANAGEMENT,
            SecurityPermissionTier.EXTERNAL_NETWORK,
            SecurityPermissionTier.FINANCIAL_EXECUTION,
        },
    }

    @classmethod
    def validate_tool_invocation(
        cls,
        agent_id: str,
        tool_name: str,
        required_tier: SecurityPermissionTier,
        is_live_order: bool = False,
    ) -> Dict[str, Any]:
        """Validates whether agent_id is permitted to invoke tool_name."""
        # Universal Invariant 1: Live broker real-money order routing is strictly locked
        if is_live_order or "live_order" in tool_name.lower():
            raise PermissionDeniedError(
                f"GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK: Real-money live broker dispatch is permanently locked. "
                f"Agent '{agent_id}' attempted live order dispatch."
            )

        allowed_tiers = cls.ROLE_TIERS.get(agent_id, {SecurityPermissionTier.READ_ONLY})
        if required_tier not in allowed_tiers:
            raise PermissionDeniedError(
                f"Privilege violation: Agent '{agent_id}' has tiers {allowed_tiers}, "
                f"but tool '{tool_name}' requires {required_tier.value}"
            )

        return {
            "authorized": True,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "tier": required_tier.value,
        }


class SecretsHygieneAuditor:
    """Detects, audits, and redacts sensitive credentials from strings, logs, and dicts."""

    @staticmethod
    def audit_text(text: str) -> Tuple[bool, List[str]]:
        """Returns (has_secrets, list_of_detected_pattern_names)."""
        if not text:
            return False, []
        detected = []
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                detected.append(name)
        return len(detected) > 0, detected

    @classmethod
    def redact_text(cls, text: str) -> str:
        """Redacts all discovered credentials with [REDACTED_<TYPE>]."""
        if not text:
            return text
        sanitized = text
        for name, pattern in SECRET_PATTERNS:
            sanitized = pattern.sub(f"[REDACTED_{name}]", sanitized)
        return sanitized

    @classmethod
    def redact_data_structure(cls, data: Any) -> Any:
        """Recursively traverses dictionaries/lists and redacts secrets in string values."""
        if isinstance(data, str):
            return cls.redact_text(data)
        elif isinstance(data, dict):
            return {k: cls.redact_data_structure(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls.redact_data_structure(item) for item in data]
        return data

    @classmethod
    def audit_environment(cls, search_dir: Optional[Path] = None) -> Dict[str, Any]:
        """Audits workspace files for unredacted sensitive API tokens."""
        target_dir = search_dir or Path(__file__).resolve().parents[5]
        files_scanned = 0
        violations = []
        skip_dirs = {".git", ".venv", ".osworld_venv", "node_modules", "__pycache__", ".pytest_cache"}

        for root, dirs, files in os.walk(str(target_dir)):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for file in files:
                if file.endswith((".py", ".json", ".toml", ".env.example")):
                    # Avoid false positives on test mocks or self
                    if "test_" in file or file == "least_privilege_enforcer.py":
                        continue
                    files_scanned += 1
                    fp = os.path.join(root, file)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read(50000)
                        has_sec, patterns = cls.audit_text(content)
                        if has_sec:
                            violations.append({"file": file, "patterns": patterns})
                    except Exception:
                        pass

        return {
            "files_scanned": files_scanned,
            "secrets_leak_detected": len(violations) > 0,
            "violations": violations,
            "violations_count": len(violations),
        }
