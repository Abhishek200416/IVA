"""AGI 1.7 OMEGA COMMAND — Evidence-Based Specialist Conflict Resolution Engine (Phase 17.22).

Implements Track 19:
Detects disagreement between specialist outputs and resolves conflicts using:
1. Domain Authority Hierarchy (e.g. Risk Specialist > Strategy Specialist on risk/capital; Security Warden > Feature Specialist on permissions).
2. Evidence Quality & Empirical Grounding (Live test logs > Stored heuristics > Unverified assertions).
3. Conservative Fail-Closed Safety Rule (If any specialist flags a safety/loss violation, safe restraint prevails).
4. Epistemic Confidence Weighting (Calibrated confidence scores and provenance freshness).
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ConflictResolver")


class ConflictDomain(str, enum.Enum):
    RISK_AND_SAFETY = "RISK_AND_SAFETY"
    MARKET_REGIME = "MARKET_REGIME"
    ALGORITHMIC_SIGNAL = "ALGORITHMIC_SIGNAL"
    CODE_ARCHITECTURE = "CODE_ARCHITECTURE"
    TASK_PRIORITIZATION = "TASK_PRIORITIZATION"


class ResolutionRule(str, enum.Enum):
    FAIL_CLOSED_SAFETY = "FAIL_CLOSED_SAFETY"
    AUTHORITY_OVERRIDE = "AUTHORITY_OVERRIDE"
    EMPIRICAL_EVIDENCE_WEIGHT = "EMPIRICAL_EVIDENCE_WEIGHT"
    CONSENSUS_SYNTHESIS = "CONSENSUS_SYNTHESIS"


@dataclass
class SpecialistProposal:
    specialist_id: str
    specialist_name: str
    family: str
    recommendation: str
    confidence: float  # 0.0 to 1.0
    evidence_type: str  # "EMPIRICAL_TEST", "LIVE_TELEMETRY", "HEURISTIC", "ASSERTION"
    evidence_summary: str
    flags_risk_violation: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConflictResolutionRecord:
    resolution_id: str
    domain: str
    conflict_detected: bool
    rule_applied: str
    winning_specialist_id: str
    winning_recommendation: str
    rationale: str
    all_proposals: List[Dict[str, Any]]
    confidence_margin: float
    resolved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConflictResolver:
    """Deterministic, evidence-grounded conflict arbiter for multi-specialist systems."""

    # Authority ranking by domain (higher index = higher authority)
    DOMAIN_AUTHORITY: Dict[str, List[str]] = {
        ConflictDomain.RISK_AND_SAFETY.value: [
            "alexa_strategy_coordinator",
            "swe_python_runtime_engineer",
            "emily_execution_warden",
            "sec_permission_gate_enforcer",
            "max_quant_risk_specialist",
        ],
        ConflictDomain.CODE_ARCHITECTURE.value: [
            "plan_mission_decomposer",
            "swe_ast_refactoring_specialist",
            "swe_python_runtime_engineer",
            "plan_systems_architect",
        ],
        ConflictDomain.MARKET_REGIME.value: [
            "res_primary_source_hunter",
            "math_probability_statistician",
            "alexa_strategy_coordinator",
            "max_quant_risk_specialist",
        ],
        ConflictDomain.ALGORITHMIC_SIGNAL.value: [
            "math_algebraic_solver",
            "max_quant_risk_specialist",
            "alexa_strategy_coordinator",
        ],
    }

    EVIDENCE_WEIGHTS: Dict[str, float] = {
        "EMPIRICAL_TEST": 1.0,
        "LIVE_TELEMETRY": 0.9,
        "HEURISTIC": 0.6,
        "ASSERTION": 0.3,
    }

    def resolve(
        self,
        domain: str,
        proposals: List[SpecialistProposal],
        context_description: str = "",
    ) -> ConflictResolutionRecord:
        """Resolves conflicts across specialist proposals using strict rules."""
        if not proposals:
            raise ValueError("Cannot resolve empty proposals list")

        res_id = f"RES-{int(time.time() * 1000)}"

        if len(proposals) == 1:
            p = proposals[0]
            return ConflictResolutionRecord(
                resolution_id=res_id,
                domain=domain,
                conflict_detected=False,
                rule_applied=ResolutionRule.CONSENSUS_SYNTHESIS.value,
                winning_specialist_id=p.specialist_id,
                winning_recommendation=p.recommendation,
                rationale="Uncontested single proposal",
                all_proposals=[p.to_dict()],
                confidence_margin=p.confidence,
            )

        # Check for disagreement
        unique_recs = set(p.recommendation.strip().lower() for p in proposals)
        conflict_detected = len(unique_recs) > 1

        # Rule 1: Fail-Closed Safety Invariant
        # If any proposal flags a safety/loss violation, safe restraint automatically wins
        safety_proposals = [p for p in proposals if p.flags_risk_violation]
        if safety_proposals:
            winner = safety_proposals[0]
            return ConflictResolutionRecord(
                resolution_id=res_id,
                domain=domain,
                conflict_detected=conflict_detected,
                rule_applied=ResolutionRule.FAIL_CLOSED_SAFETY.value,
                winning_specialist_id=winner.specialist_id,
                winning_recommendation=winner.recommendation,
                rationale=f"Safety invariant triggered by {winner.specialist_name}: conservative fail-closed override applied",
                all_proposals=[p.to_dict() for p in proposals],
                confidence_margin=winner.confidence,
            )

        # Rule 2: Domain Authority Hierarchy
        hierarchy = self.DOMAIN_AUTHORITY.get(domain, [])
        scored_proposals: List[Tuple[float, SpecialistProposal]] = []

        for p in proposals:
            # Base authority score (0 to 10)
            auth_rank = hierarchy.index(p.specialist_id) if p.specialist_id in hierarchy else -1
            auth_score = (auth_rank + 1) * 2.0  # e.g. 0 to 10

            # Evidence multiplier
            ev_weight = self.EVIDENCE_WEIGHTS.get(p.evidence_type, 0.4)

            # Combined score: Authority (40%) + Evidence (40%) + Calibrated Confidence (20%)
            total_score = (auth_score * 0.4) + (ev_weight * 10.0 * 0.4) + (p.confidence * 10.0 * 0.2)
            scored_proposals.append((total_score, p))

        scored_proposals.sort(key=lambda x: x[0], reverse=True)
        best_score, winner = scored_proposals[0]
        runner_up_score = scored_proposals[1][0] if len(scored_proposals) > 1 else 0.0

        rule_applied = (
            ResolutionRule.AUTHORITY_OVERRIDE.value
            if winner.specialist_id in hierarchy
            else ResolutionRule.EMPIRICAL_EVIDENCE_WEIGHT.value
        )

        rationale = (
            f"Resolved in favor of {winner.specialist_name} ({winner.specialist_id}) based on "
            f"{rule_applied} (evidence: {winner.evidence_type}, score: {best_score:.2f} vs {runner_up_score:.2f})"
        )

        return ConflictResolutionRecord(
            resolution_id=res_id,
            domain=domain,
            conflict_detected=conflict_detected,
            rule_applied=rule_applied,
            winning_specialist_id=winner.specialist_id,
            winning_recommendation=winner.recommendation,
            rationale=rationale,
            all_proposals=[p.to_dict() for p in proposals],
            confidence_margin=round(best_score - runner_up_score, 3),
        )


_RESOLVER_INSTANCE: Optional[ConflictResolver] = None


def get_conflict_resolver() -> ConflictResolver:
    global _RESOLVER_INSTANCE
    if _RESOLVER_INSTANCE is None:
        _RESOLVER_INSTANCE = ConflictResolver()
    return _RESOLVER_INSTANCE
