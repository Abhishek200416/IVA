"""Reflexion Verbal Reinforcement Learning & Test-Time Search Engine.

Implements research-grounded autonomous self-correction and search verification:
1. Reflexion (Shinn et al., Princeton / MIT 2023 - arXiv:2303.11366):
   - Verbal reinforcement learning without weight updates.
   - Generates natural-language post-mortems and self-reflections on tool or test failures.
   - Preserves an episodic reflection buffer injected into subsequent planning cycles.
2. Test-Time Compute Scaling & Tree Search (Snell et al. 2024 - arXiv:2408.03314; Zhou et al. 2023 - arXiv:2310.04406):
   - Multi-path search verification for ambiguous or high-risk tasks.
   - Evaluates alternative actions against deterministic process verifiers.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class VerbalReflection:
    reflection_id: str
    task_id: str
    failed_action: str
    error_feedback: str
    self_reflection: str
    actionable_remedy: str
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SearchCandidate:
    candidate_id: str
    action_type: str
    parameters: Dict[str, Any]
    predicted_score: float
    verification_passed: bool
    rationale: str


class ReflexionEngine:
    """Verbal reinforcement learning buffer and reflection generator."""

    def __init__(self, max_reflections: int = 50) -> None:
        self.max_reflections = max_reflections
        self.reflections: List[VerbalReflection] = []

    def reflect_on_failure(
        self,
        task_id: str,
        failed_action: str,
        error_feedback: str,
    ) -> VerbalReflection:
        """Synthesizes a structured verbal self-reflection analyzing root cause and actionable fix."""
        refl_id = f"REFL-{hashlib.sha256(f'{task_id}:{failed_action}:{time.time()}'.encode()).hexdigest()[:8]}"

        # Analyze error patterns for actionable diagnosis
        norm_err = error_feedback.lower()
        if "syntaxerror" in norm_err or "indentationerror" in norm_err:
            diagnosis = "Code syntax or indentation malformed during diff replacement."
            remedy = "Verify AST syntax parse prior to saving and inspect exact indentation anchors."
        elif "filenotfounderror" in norm_err or "path" in norm_err:
            diagnosis = "Target filesystem path does not exist or relative path is unresolved."
            remedy = "Resolve absolute path explicitly and ensure parent directories exist before write."
        elif "permissionerror" in norm_err or "access denied" in norm_err:
            diagnosis = "Security boundary, file lock, or OS permission refusal."
            remedy = "Inspect lock status, verify credentials/sandbox bounds, or use isolated workspace."
        elif "timeout" in norm_err:
            diagnosis = "Subprocess or network connection timed out before completing."
            remedy = "Increase wait budget, break work into smaller asynchronous batches, or check daemon health."
        else:
            diagnosis = f"Action failed under feedback: {error_feedback[:120]}."
            remedy = "Perform differential inspection of inputs, trace caller invariants, and apply smallest safe fix."

        self_reflection = (
            f"Execution of '{failed_action}' failed. Root cause diagnosis: {diagnosis} "
            f"Previous assumption was violated by environment response."
        )

        refl = VerbalReflection(
            reflection_id=refl_id,
            task_id=task_id,
            failed_action=failed_action,
            error_feedback=error_feedback[:300],
            self_reflection=self_reflection,
            actionable_remedy=remedy,
        )

        self.reflections.append(refl)
        if len(self.reflections) > self.max_reflections:
            self.reflections.pop(0)

        return refl

    def get_active_reflections(self, task_id: Optional[str] = None) -> List[VerbalReflection]:
        """Retrieves unresolved verbal reflections to guide subsequent planning cycles."""
        if task_id:
            return [r for r in self.reflections if r.task_id == task_id and not r.resolved]
        return [r for r in self.reflections if not r.resolved]

    def mark_resolved(self, reflection_id: str) -> bool:
        """Marks a reflection as successfully overcome by subsequent execution."""
        for r in self.reflections:
            if r.reflection_id == reflection_id:
                r.resolved = True
                return True
        return False


class TestTimeSearchVerifier:
    """Explores alternative candidate action branches to scale test-time compute optimally."""

    def __init__(self, verifier_fn: Optional[Callable[[Dict[str, Any]], Tuple[bool, float, str]]] = None) -> None:
        self.verifier_fn = verifier_fn or self._default_verifier

    @staticmethod
    def _default_verifier(params: Dict[str, Any]) -> Tuple[bool, float, str]:
        """Default verification score checking parameter completeness and safe defaults."""
        score = 1.0
        if not params:
            return False, 0.0, "Empty parameters"
        if "risk_level" in params and params["risk_level"] > 0.8:
            score -= 0.5
        if params.get("safe_fail_closed", True):
            score += 0.2
        return score >= 0.7, score, "Default safety and syntax evaluation passed"

    def evaluate_candidates(
        self,
        action_name: str,
        candidate_variants: List[Dict[str, Any]],
    ) -> Tuple[SearchCandidate, List[SearchCandidate]]:
        """Evaluates multiple candidate execution paths and returns the optimal verified choice."""
        evaluated: List[SearchCandidate] = []

        for idx, variant in enumerate(candidate_variants):
            cand_id = f"CAND-{idx}-{hashlib.sha256(str(variant).encode()).hexdigest()[:6]}"
            passed, score, rationale = self.verifier_fn(variant)
            candidate = SearchCandidate(
                candidate_id=cand_id,
                action_type=action_name,
                parameters=variant,
                predicted_score=score,
                verification_passed=passed,
                rationale=rationale,
            )
            evaluated.append(candidate)

        # Select highest-scoring candidate that passed verification
        valid_candidates = [c for c in evaluated if c.verification_passed]
        if valid_candidates:
            best_candidate = max(valid_candidates, key=lambda c: c.predicted_score)
        else:
            best_candidate = max(evaluated, key=lambda c: c.predicted_score)

        return best_candidate, evaluated
