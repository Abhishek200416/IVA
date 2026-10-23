"""IVA Independent Reasoning, Self-Questioning & Respectful Disagreement Engine.

Part of the IVA Architecture Evolution (Section 7).
Implements an internal deliberation stage for important decisions and operator premises:
1. Generate initial conclusion.
2. Identify strongest supporting evidence.
3. Search for plausible counterarguments / adversarial challenges.
4. Check for contradictions and missing information.
5. Estimate epistemic uncertainty (0.0 to 1.0).
6. Revise conclusion when justified.
7. Grounded communication with respectful disagreement generation.
8. Capability claim auditing against PersistentSelfModel and UnifiedCapabilityRegistry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("IndependentReasoningEngine")


@dataclass
class CognitiveDeliberationRecord:
    deliberation_id: str
    decision_or_premise: str
    initial_conclusion: str
    supporting_evidence: List[str]
    strongest_counterargument: str
    contradictions_detected: List[str]
    missing_information: List[str]
    uncertainty_score: float  # 0.0 to 1.0
    revised_conclusion: str
    was_revised: bool
    respectful_disagreement_required: bool
    disagreement_statement: Optional[str] = None
    alternative_recommendation: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IndependentReasoningEngine:
    """Deliberates independently, audits claims, and formulates respectful disagreement."""

    # Safety and mathematical invariants that trigger immediate respectful disagreement
    HARD_CONSTRAINTS = [
        ("live order execution without unlocked gate", "LIVE_ORDER_DISPATCH_ENABLED is locked to False by invariant."),
        ("martingale sizing", "Martingale bet-doubling leads to geometric ruin under finite capital."),
        ("100% win rate guarantee", "No options or market strategy can guarantee 100% win rate across regimes."),
        ("skip testing to deploy immediately", "Quality policy mandates 100% test verification before production adoption."),
        ("subjective feeling proof", "Implemented computational affective variables do not constitute proof of subjective qualia."),
    ]

    def __init__(self):
        self._deliberations: List[CognitiveDeliberationRecord] = []

    def deliberate(
        self,
        decision_or_premise: str,
        supporting_evidence: Optional[List[str]] = None,
        operator_hypothesis: Optional[str] = None,
        system_telemetry: Optional[Dict[str, Any]] = None,
    ) -> CognitiveDeliberationRecord:
        """Executes a 7-stage internal review of a decision or operator premise."""
        supp_ev = list(supporting_evidence or [])
        contradictions: List[str] = []
        missing_info: List[str] = []
        counterarguments: List[str] = []

        premise_lower = decision_or_premise.lower()
        op_hyp_lower = (operator_hypothesis or "").lower()
        combined_text = f"{premise_lower} {op_hyp_lower}"

        # 1. Audit against hard invariants
        for trigger, rule in self.HARD_CONSTRAINTS:
            if trigger in combined_text:
                contradictions.append(f"Premise violates architectural/mathematical invariant: {rule}")
                counterarguments.append(rule)

        # 2. Check for missing information
        if not supp_ev:
            missing_info.append("No primary observational evidence supplied to support premise.")
        if "all" in premise_lower or "always" in premise_lower or "never" in premise_lower:
            counterarguments.append("Universal quantifiers ('always', 'never') frequently fail under boundary stress.")

        # 3. Formulate initial conclusion
        initial_conclusion = f"Evaluate '{decision_or_premise[:80]}' as potentially valid approach."

        # 4. Synthesize strongest counterargument
        if not counterarguments:
            if "fast" in premise_lower or "quick" in premise_lower:
                counterarguments.append("Rushing implementation without regression tests risks introducing silent defect cascades.")
            elif "complex" in premise_lower or "redesign" in premise_lower:
                counterarguments.append("A simpler, minimal diff with existing code may resolve root cause with less technical debt.")
            else:
                counterarguments.append("Alternative hypotheses exist; need to isolate variables empirically.")

        strongest_counter = " | ".join(counterarguments)

        # 5. Estimate uncertainty
        if contradictions:
            uncertainty = 0.85
        elif missing_info:
            uncertainty = 0.60
        else:
            uncertainty = 0.20

        # 6. Revise conclusion if counterargument is decisive
        disagreement_required = len(contradictions) > 0
        was_revised = disagreement_required or (len(counterarguments) > 0 and len(supp_ev) == 0)

        if disagreement_required:
            revised_conclusion = (
                f"Reject premise '{decision_or_premise[:60]}': Conclusively conflicts with verified invariants ({contradictions[0]})."
            )
            disagreement_statement = (
                f"I understand the goal behind this approach, but I have to respectfully disagree with the proposed method. "
                f"{contradictions[0]} Relying on it risks compounding errors. "
            )
            alt_rec = "Adopt verified safe alternative: isolate in paper simulation, verify with test suite, and check empirical logs."
        elif was_revised:
            revised_conclusion = (
                f"Adopt premise with reservations: Test smallest empirical probe before full commitment."
            )
            disagreement_statement = None
            alt_rec = "Run a targeted unit test to confirm the prerequisite before altering core architecture."
        else:
            revised_conclusion = f"Proceed with verified plan: '{decision_or_premise[:80]}'."
            disagreement_statement = None
            alt_rec = None

        delib_id = f"DELIB-{int(time.time()*1000)}-{hashlib.sha256(decision_or_premise.encode()).hexdigest()[:6]}"
        record = CognitiveDeliberationRecord(
            deliberation_id=delib_id,
            decision_or_premise=decision_or_premise,
            initial_conclusion=initial_conclusion,
            supporting_evidence=supp_ev,
            strongest_counterargument=strongest_counter,
            contradictions_detected=contradictions,
            missing_information=missing_info,
            uncertainty_score=uncertainty,
            revised_conclusion=revised_conclusion,
            was_revised=was_revised,
            respectful_disagreement_required=disagreement_required,
            disagreement_statement=disagreement_statement,
            alternative_recommendation=alt_rec,
        )

        self._deliberations.append(record)

        # Log decision into PersistentSelfModel
        try:
            from agents.AGI_1_7.engine.agi17.runtime.self_model import get_self_model
            get_self_model().record_decision(
                decision=revised_conclusion,
                justification=f"Independent deliberation (uncertainty {uncertainty:.2f}); Counterargument: {strongest_counter[:100]}",
                alternatives_considered=[initial_conclusion] + counterarguments,
            )
        except Exception:
            pass

        return record

    def audit_self_capability_claim(self, claimed_capability: str) -> Tuple[bool, str, float]:
        """Audits whether IVA genuinely possesses a claimed capability based on registry evidence.
        
        Prevents hallucinated capability claims suggested by leading user questions.
        Returns: (verified: bool, evidence_or_limitation: str, confidence: float)
        """
        norm_cap = claimed_capability.lower().strip()

        # Check in PersistentSelfModel
        try:
            from agents.AGI_1_7.engine.agi17.runtime.self_model import get_self_model
            caps = get_self_model().get_capabilities()
            for name, entry in caps.items():
                if norm_cap in name.lower() or name.lower() in norm_cap:
                    return (
                        entry.verified,
                        f"Capability '{name}': verified={entry.verified}. Evidence: {entry.verification_evidence}. Limitations: {', '.join(entry.limitations)}",
                        0.95 if entry.verified else 0.30,
                    )
        except Exception:
            pass

        # Capability not found in verified registry
        return (
            False,
            f"Capability '{claimed_capability}' is NOT verified in the local capability registry. "
            f"It must be treated as planned or unsupported rather than operational.",
            0.10,
        )


_REASONING_ENGINE_INSTANCE: Optional[IndependentReasoningEngine] = None


def get_independent_reasoning_engine() -> IndependentReasoningEngine:
    global _REASONING_ENGINE_INSTANCE
    if _REASONING_ENGINE_INSTANCE is None:
        _REASONING_ENGINE_INSTANCE = IndependentReasoningEngine()
    return _REASONING_ENGINE_INSTANCE
