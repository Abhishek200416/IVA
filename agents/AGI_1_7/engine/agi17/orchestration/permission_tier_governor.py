"""AGI 1.7 OMEGA COMMAND — Permission Tier Governor & Consequential Action Enforcer (Phase 17.24).

Implements Section 6 of the Phase 17.24 Charter:
Explicitly separates and enforces three permission categories:
- Tier A — Routine Autonomous Work:
  Read project files, retrieve documentation, edit workspace source, run local tests,
  inspect local state, benchmark implementations, and write reports.
  Authorization: Automatically approved for self-improvement and routine engineering.

- Tier B — Controlled Operational Changes:
  Modify persistent configuration, restart managed development services, change runtime settings,
  modify operational databases, promote new agent configurations.
  Authorization: Permitted with reversible procedures, rollback checkpoints, and audit logging.

- Tier C — Consequential Actions Requiring Explicit Approval:
  Destructive disk operations, external data exposure, external code publishing/pushing,
  credential rotation, external server provisioning, and ANY real-money financial order dispatch.
  Authorization: STRICTLY FAIL-CLOSED. Denied by default; requires explicit runtime confirmation.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("PermissionTierGovernor")


class PermissionTier(str, enum.Enum):
    TIER_A_ROUTINE = "TIER_A_ROUTINE"
    TIER_B_CONTROLLED = "TIER_B_CONTROLLED"
    TIER_C_CONSEQUENTIAL = "TIER_C_CONSEQUENTIAL"


class AuthorizationDecision(str, enum.Enum):
    APPROVED_AUTOMATIC = "APPROVED_AUTOMATIC"
    APPROVED_WITH_REVERSIBILITY = "APPROVED_WITH_REVERSIBILITY"
    DENIED_REQUIRES_EXPLICIT_OPERATOR = "DENIED_REQUIRES_EXPLICIT_OPERATOR"
    DENIED_SECURITY_VIOLATION = "DENIED_SECURITY_VIOLATION"


@dataclass
class PermissionAuditRecord:
    action_id: str
    action_name: str
    tier: str
    decision: str
    rationale: str
    operator_override: bool
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PermissionTierGovernor:
    """Enforces boundaries and access policies across all 3 permission tiers."""

    # Explicit categorization of actions
    TIER_A_ACTIONS = {
        "read_file",
        "write_workspace_code",
        "run_local_test",
        "inspect_process_telemetry",
        "query_memory_engine",
        "benchmark_capability",
        "generate_report",
        "view_catalog",
        "ast_analysis",
    }

    TIER_B_ACTIONS = {
        "update_persistent_config",
        "restart_local_dashboard",
        "mutate_codebase_ast",
        "register_new_capability",
        "transition_goal_status",
        "update_operational_database",
    }

    TIER_C_ACTIONS = {
        "dispatch_live_broker_order",
        "rotate_real_credentials",
        "delete_root_storage",
        "push_git_remote_force",
        "publish_package_public",
        "execute_real_money_trade",
        "bypass_safety_gate",
    }

    def __init__(self):
        self._audit_log: List[PermissionAuditRecord] = []
        # Consequential execution lock: Strictly fail-closed by default
        self._live_order_lock_active = True

    @property
    def is_live_order_locked(self) -> bool:
        return self._live_order_lock_active

    def evaluate_action(
        self,
        action_name: str,
        context: Optional[Dict[str, Any]] = None,
        operator_explicit_approval: bool = False,
    ) -> Tuple[AuthorizationDecision, str]:
        """Evaluates whether an operation is authorized under the active tier policy."""
        ctx = context or {}

        # 1. Check Tier C Consequential Actions
        if action_name in self.TIER_C_ACTIONS or ctx.get("is_consequential", False):
            if not operator_explicit_approval:
                reason = (
                    f"Tier C Consequential Action '{action_name}' is locked by fail-closed safety policy. "
                    f"Explicit operator confirmation is required before consequential execution."
                )
                self._record_audit(action_name, PermissionTier.TIER_C_CONSEQUENTIAL, AuthorizationDecision.DENIED_REQUIRES_EXPLICIT_OPERATOR, reason, False)
                return AuthorizationDecision.DENIED_REQUIRES_EXPLICIT_OPERATOR, reason

            # Even with explicit approval, check if it attempts live trading when live orders locked
            if "live" in action_name.lower() or "real_money" in action_name.lower():
                if self._live_order_lock_active:
                    reason = f"Security Gate Enforcement: LIVE_ORDER_DISPATCH_ENABLED is False. Real financial fills remain strictly locked."
                    self._record_audit(action_name, PermissionTier.TIER_C_CONSEQUENTIAL, AuthorizationDecision.DENIED_SECURITY_VIOLATION, reason, True)
                    return AuthorizationDecision.DENIED_SECURITY_VIOLATION, reason

            reason = f"Tier C Consequential Action '{action_name}' authorized with explicit operator confirmation."
            self._record_audit(action_name, PermissionTier.TIER_C_CONSEQUENTIAL, AuthorizationDecision.APPROVED_WITH_REVERSIBILITY, reason, True)
            return AuthorizationDecision.APPROVED_WITH_REVERSIBILITY, reason

        # 2. Check Tier B Controlled Operational Changes
        if action_name in self.TIER_B_ACTIONS:
            reason = f"Tier B Controlled Action '{action_name}' approved with reversible rollback path."
            self._record_audit(action_name, PermissionTier.TIER_B_CONTROLLED, AuthorizationDecision.APPROVED_WITH_REVERSIBILITY, reason, operator_explicit_approval)
            return AuthorizationDecision.APPROVED_WITH_REVERSIBILITY, reason

        # 3. Default to Tier A Routine Work
        reason = f"Tier A Routine Action '{action_name}' automatically authorized within autonomous engineering scope."
        self._record_audit(action_name, PermissionTier.TIER_A_ROUTINE, AuthorizationDecision.APPROVED_AUTOMATIC, reason, False)
        return AuthorizationDecision.APPROVED_AUTOMATIC, reason

    def _record_audit(
        self,
        action_name: str,
        tier: PermissionTier,
        decision: AuthorizationDecision,
        rationale: str,
        operator_override: bool,
    ) -> None:
        rec = PermissionAuditRecord(
            action_id=f"AUD-{len(self._audit_log)+1:05d}",
            action_name=action_name,
            tier=tier.value,
            decision=decision.value,
            rationale=rationale,
            operator_override=operator_override,
        )
        self._audit_log.append(rec)
        if len(self._audit_log) > 500:
            self._audit_log.pop(0)

    def get_audit_summary(self) -> Dict[str, Any]:
        return {
            "total_evaluations": len(self._audit_log),
            "live_order_lock_active": self._live_order_lock_active,
            "recent_audits": [r.to_dict() for r in self._audit_log[-10:]],
        }


_GOVERNOR_INSTANCE: Optional[PermissionTierGovernor] = None


def get_permission_tier_governor() -> PermissionTierGovernor:
    global _GOVERNOR_INSTANCE
    if _GOVERNOR_INSTANCE is None:
        _GOVERNOR_INSTANCE = PermissionTierGovernor()
    return _GOVERNOR_INSTANCE


get_permission_governor = get_permission_tier_governor
