"""Regulatory and Broker Compliance Gate for AGI 1.7 OMEGA COMMAND.

Implements Phase 5 Objective 14:
- Verifies regulatory compliance with SEBI Algorithmic Trading Framework and NSE/BSE Circulars.
- Evaluates Paytm Money Terms of Service regarding visible browser UI automation.
- Invariant: If written broker authorization or regulatory clarification is absent, live order
  submission is blocked while preserving 100% of research, intelligence, and paper-trading runtime.
- Strictly prohibits silent switching to undocumented APIs or hidden HTTP endpoints.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class RegulatoryStatus(str, Enum):
    RESEARCH_AND_PAPER_AUTHORIZED = "RESEARCH_AND_PAPER_AUTHORIZED"
    LIVE_BLOCKED_PENDING_BROKER_APPROVAL = "LIVE_BLOCKED_PENDING_BROKER_APPROVAL"
    LIVE_PERMITTED_WITH_DISCLOSURE = "LIVE_PERMITTED_WITH_DISCLOSURE"


@dataclass
class RegulatoryAuditResult:
    status: RegulatoryStatus
    is_live_order_permitted: bool
    sebi_framework_notes: str
    broker_terms_notes: str
    remediation_required: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "is_live_order_permitted": self.is_live_order_permitted,
            "sebi_framework_notes": self.sebi_framework_notes,
            "broker_terms_notes": self.broker_terms_notes,
            "remediation_required": self.remediation_required,
            "timestamp": self.timestamp,
        }


class RegulatoryComplianceGate:
    """Deterministic legal and broker terms guard."""

    def __init__(self) -> None:
        self.sebi_circular_reference = "SEBI/HO/MRD/DP/CIR/P/2018/62 (Algorithmic Trading & API Governance)"
        self.broker_name = "Paytm Money Limited (SEBI Reg: INZ000240532)"

    def audit_live_execution_permission(
        self,
        account_id: str,
        has_written_broker_clearance: bool = False,
    ) -> RegulatoryAuditResult:
        """Audits regulatory and broker permissions before live execution is admitted."""
        if not has_written_broker_clearance:
            return RegulatoryAuditResult(
                status=RegulatoryStatus.LIVE_BLOCKED_PENDING_BROKER_APPROVAL,
                is_live_order_permitted=False,
                sebi_framework_notes=(
                    f"Audited against {self.sebi_circular_reference}. Automated order generation from client-side "
                    "software without formal algorithmic ID tagging requires explicit broker written clarification."
                ),
                broker_terms_notes=(
                    f"Paytm Money web interface terms prohibit automated scraping or non-API unattended bot actuation "
                    "unless explicitly registered or approved under authorized developer programs."
                ),
                remediation_required=(
                    "Live order submission blocked. Request written clarification from Paytm Money Compliance. "
                    "All research, market radar, options pricing, and paper-trading features remain 100% operational."
                ),
            )

        return RegulatoryAuditResult(
            status=RegulatoryStatus.LIVE_PERMITTED_WITH_DISCLOSURE,
            is_live_order_permitted=True,
            sebi_framework_notes=f"Compliance confirmed under {self.sebi_circular_reference}.",
            broker_terms_notes="Written authorization on file for account " + account_id[-4:].rjust(len(account_id), "*"),
            remediation_required="None. Live orders admitted under explicit risk controls.",
        )
