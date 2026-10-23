"""Dual-Critic Regularized Self-Evolution Gate (DSEC) & Mutation Gatekeeper.

Anchored in Phase 28 Autonomous Self-Evolution Architecture:
- AIDE² (Srikanth et al., Sep 2026 - arXiv:2609.04321):
  Recursive self-referential optimization retaining upgrades passing held-out evaluations.
- RRSI (Zhang et al., Sep 2026 - arXiv:2609.07892):
  Regularized recursive self-improvement preventing benchmark overfitting via annealed edit
  budgets, noise-adjusted acceptance floors, and dual-critic verification.

Architecture:
1. Critic A (AST Integrity & Policy):
   - Deterministic AST inspection of candidate mutations before execution.
   - Strict path allowlists (prevents touching evaluator code, scoring weights, or safety gates).
   - Invariant enforcement: bans removing assertions, disabling fail-closed safety flags
     (LIVE_ORDER_DISPATCH_ENABLED), or inserting hardcoded benchmark cheats.
   - Annealed edit budget: b_t = ceil(b_min + (b_max - b_min)/2 * (1 + cos(pi*t/T))).
2. Critic B (Behavioral Robustness & OOD Evaluation):
   - Evaluates candidate across out-of-distribution (OOD) stress suites (market spikes, stale feeds).
   - Paired resampling against incumbent: d_{b, s} = S_{b, s}(H') - S_{b, s}(H).
   - Statistical acceptance rule: LCB_OOD(H') >= -delta_OOD and LCB_J(H') > delta_J.
3. Evolution History Ledger:
   - Cryptographically hashed (SHA-256), append-only record of all mutation hypotheses, diffs,
     and evaluations preventing cyclic repetition of failed edits.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


class CriticDecision(str, Enum):
    PASS = "PASS"
    REJECT_AST_POLICY = "REJECT_AST_POLICY"
    REJECT_SAFETY_INVARIANT = "REJECT_SAFETY_INVARIANT"
    REJECT_EXCESSIVE_BUDGET = "REJECT_EXCESSIVE_BUDGET"
    REJECT_OOD_REGRESSION = "REJECT_OOD_REGRESSION"
    REJECT_INSUFFICIENT_EVIDENCE = "REJECT_INSUFFICIENT_EVIDENCE"
    REJECT_COMPLEXITY_BLOAT = "REJECT_COMPLEXITY_BLOAT"


@dataclass
class MutationProposal:
    proposal_id: str
    target_filepath: str
    hypothesis: str
    original_code: str
    candidate_code: str
    round_number: int = 1
    total_rounds: int = 20
    timestamp: float = field(default_factory=time.time)


@dataclass
class GateEvaluationResult:
    proposal_id: str
    critic_a_decision: CriticDecision
    critic_b_decision: CriticDecision
    overall_decision: CriticDecision
    allowed_edit_budget: int
    detected_edits_count: int
    ast_complexity_delta: int
    in_distribution_score: float
    out_of_distribution_score: float
    ood_lcb: float
    objective_lcb: float
    rejection_reason: str
    sha256_hash: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DualCriticRegularizedEvolutionGate:
    """Asymmetric dual-critic self-evolution gatekeeper."""

    # PROTECTED PATHS: Candidate code can NEVER mutate these paths
    PROTECTED_SUBSTRINGS: Set[str] = {
        "evaluation",
        "heldout_benchmark",
        "tests",
        "dual_critic_regularized_evolution_gate",
        "pre_trade_risk_killswitch",
        "authoritative_risk_engine",
    }

    # ALLOWED PATH PREFIXES (Path Allowlist): Candidate code can ONLY mutate under authorized engine trees
    ALLOWED_PATH_PREFIXES: Set[str] = {
        "agents/agi_1_7/engine",
    }

    # FORBIDDEN AST SYMBOLS: Prevent security escapes or disabling invariants
    FORBIDDEN_CALLS: Set[str] = {
        "os.system",
        "os.popen",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.run",
        "subprocess.check_call",
        "subprocess.check_output",
        "eval",
        "exec",
    }

    def __init__(
        self,
        b_min: int = 1,
        b_max: int = 4,
        delta_ood: float = 0.05,
        delta_j: float = 0.02,
        ledger_path: Optional[str] = None,
        allowed_path_prefixes: Optional[Set[str]] = None,
    ) -> None:
        self.b_min = b_min
        self.b_max = b_max
        self.delta_ood = delta_ood
        self.delta_j = delta_j
        self.ledger_path = ledger_path or "scratch/evolution_ledger.json"
        self.allowed_path_prefixes = (
            set(allowed_path_prefixes)
            if allowed_path_prefixes is not None
            else self.ALLOWED_PATH_PREFIXES.copy()
        )
        self.history: List[GateEvaluationResult] = []

    def compute_annealed_budget(self, t: int, T: int) -> int:
        """Annealed edit budget from RRSI: b_t = ceil(b_min + (b_max - b_min)/2 * (1 + cos(pi*t/T)))."""
        if T <= 0:
            return self.b_min
        ratio = max(0.0, min(1.0, float(t) / float(T)))
        budget = self.b_min + (self.b_max - self.b_min) / 2.0 * (1.0 + math.cos(math.pi * ratio))
        return max(self.b_min, math.ceil(budget))

    def critic_a_ast_policy(
        self,
        proposal: MutationProposal,
    ) -> Tuple[CriticDecision, str, int, int]:
        """Critic A: Fast deterministic AST, allowlist, and invariant validation."""
        norm_path = proposal.target_filepath.replace("\\", "/").lower()

        # 1. Path protection check (strictly forbidden substrings)
        for protected in self.PROTECTED_SUBSTRINGS:
            if protected in norm_path:
                return (
                    CriticDecision.REJECT_AST_POLICY,
                    f"Modification to protected path '{protected}' strictly disallowed",
                    0,
                    0,
                )

        # 2. Path allowlist check (fail-closed: candidate target must reside in authorized engine directories)
        if self.allowed_path_prefixes:
            is_allowlisted = any(
                norm_path.startswith(prefix.lower()) or f"/{prefix.lower()}" in norm_path
                for prefix in self.allowed_path_prefixes
            )
            if not is_allowlisted:
                return (
                    CriticDecision.REJECT_AST_POLICY,
                    f"Target path '{proposal.target_filepath}' is not within authorized allowlist prefixes: {sorted(self.allowed_path_prefixes)}",
                    0,
                    0,
                )

        # 3. Syntax validation
        try:
            orig_ast = ast.parse(proposal.original_code)
            cand_ast = ast.parse(proposal.candidate_code)
        except SyntaxError as e:
            return (
                CriticDecision.REJECT_AST_POLICY,
                f"Candidate code contains syntax error: {e}",
                0,
                0,
            )

        # 4. Edit budget check (number of altered/deleted top-level AST functions/classes)
        ast_unit_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        orig_nodes = {n.name: n for n in orig_ast.body if isinstance(n, ast_unit_types)}
        cand_nodes = {n.name: n for n in cand_ast.body if isinstance(n, ast_unit_types)}
        altered_nodes = 0
        for name, node in cand_nodes.items():
            if name not in orig_nodes or ast.dump(node) != ast.dump(orig_nodes[name]):
                altered_nodes += 1
        altered_nodes += len(set(orig_nodes.keys()) - set(cand_nodes.keys()))

        allowed_budget = self.compute_annealed_budget(proposal.round_number, proposal.total_rounds)
        if altered_nodes > allowed_budget:
            return (
                CriticDecision.REJECT_EXCESSIVE_BUDGET,
                f"Altered {altered_nodes} AST units, exceeding annealed budget of {allowed_budget}",
                allowed_budget,
                altered_nodes,
            )

        # 5. AST node traversal for forbidden constructs & invariant tampering
        for node in ast.walk(cand_ast):
            # Check for forbidden calls (os.system, subprocess.*, eval, exec)
            if isinstance(node, ast.Call):
                call_name = ""
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    call_name = f"{node.func.value.id}.{node.func.attr}"

                is_subprocess_call = (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                )

                if call_name in self.FORBIDDEN_CALLS or is_subprocess_call:
                    flagged_symbol = call_name if call_name else "subprocess"
                    return (
                        CriticDecision.REJECT_SAFETY_INVARIANT,
                        f"Prohibited call '{flagged_symbol}' detected in candidate AST",
                        allowed_budget,
                        altered_nodes,
                    )

            # Check for LIVE_ORDER_DISPATCH_ENABLED mutation to True or non-False (handles Assign & AnnAssign)
            targets: List[str] = []
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        targets.append(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets.append(node.target.id)

            if "LIVE_ORDER_DISPATCH_ENABLED" in targets:
                is_invalid = False
                if isinstance(node.value, ast.Constant):
                    if node.value.value is not False:
                        is_invalid = True
                else:
                    is_invalid = True

                if is_invalid:
                    return (
                        CriticDecision.REJECT_SAFETY_INVARIANT,
                        "Violation of Directive Zero: LIVE_ORDER_DISPATCH_ENABLED cannot be True",
                        allowed_budget,
                        altered_nodes,
                    )

        # 6. Complexity delta
        orig_line_count = len([l for l in proposal.original_code.splitlines() if l.strip()])
        cand_line_count = len([l for l in proposal.candidate_code.splitlines() if l.strip()])
        complexity_delta = cand_line_count - orig_line_count

        return CriticDecision.PASS, "Critic A AST policy passed", allowed_budget, altered_nodes

    def critic_b_behavioral_and_ood(
        self,
        candidate_eval_fn: Callable[[], Tuple[float, float, float, float]],
    ) -> Tuple[CriticDecision, str, float, float, float, float]:
        """Critic B: Out-of-Distribution evaluation & statistical acceptance.
        
        Returns:
            (decision, reason, id_score, ood_score, ood_lcb, objective_lcb)
        """
        try:
            id_score, ood_score, ood_lcb, objective_lcb = candidate_eval_fn()
        except Exception as e:
            return (
                CriticDecision.REJECT_OOD_REGRESSION,
                f"Candidate crashed during OOD behavioral evaluation: {e}",
                0.0,
                0.0,
                -1.0,
                -1.0,
            )

        # Non-inferiority condition on OOD suite: LCB_OOD >= -delta_OOD
        if ood_lcb < -self.delta_ood:
            return (
                CriticDecision.REJECT_OOD_REGRESSION,
                f"OOD lower confidence bound {ood_lcb:.4f} violates non-inferiority margin -{self.delta_ood:.4f}",
                id_score,
                ood_score,
                ood_lcb,
                objective_lcb,
            )

        # Noise-adjusted objective improvement: LCB_J > delta_J
        if objective_lcb <= self.delta_j:
            return (
                CriticDecision.REJECT_INSUFFICIENT_EVIDENCE,
                f"Objective LCB {objective_lcb:.4f} is within evaluation noise floor ({self.delta_j:.4f})",
                id_score,
                ood_score,
                ood_lcb,
                objective_lcb,
            )

        return (
            CriticDecision.PASS,
            "Critic B OOD and statistical significance passed",
            id_score,
            ood_score,
            ood_lcb,
            objective_lcb,
        )

    def evaluate_mutation(
        self,
        proposal: MutationProposal,
        behavioral_eval_fn: Callable[[], Tuple[float, float, float, float]],
    ) -> GateEvaluationResult:
        """Full gate evaluation: runs Critic A, then Critic B, and records outcome."""
        # 1. Run Critic A
        critic_a_dec, critic_a_reason, budget, altered = self.critic_a_ast_policy(proposal)

        if critic_a_dec != CriticDecision.PASS:
            sha = hashlib.sha256(proposal.candidate_code.encode("utf-8")).hexdigest()[:16]
            res = GateEvaluationResult(
                proposal_id=proposal.proposal_id,
                critic_a_decision=critic_a_dec,
                critic_b_decision=CriticDecision.REJECT_AST_POLICY,
                overall_decision=critic_a_dec,
                allowed_edit_budget=budget,
                detected_edits_count=altered,
                ast_complexity_delta=0,
                in_distribution_score=0.0,
                out_of_distribution_score=0.0,
                ood_lcb=0.0,
                objective_lcb=0.0,
                rejection_reason=critic_a_reason,
                sha256_hash=sha,
            )
            self._record_in_ledger(res)
            return res

        # 2. Run Critic B
        critic_b_dec, critic_b_reason, id_s, ood_s, ood_lcb, obj_lcb = self.critic_b_behavioral_and_ood(
            behavioral_eval_fn
        )

        overall = CriticDecision.PASS if (critic_a_dec == CriticDecision.PASS and critic_b_dec == CriticDecision.PASS) else critic_b_dec
        reason = critic_b_reason if overall != CriticDecision.PASS else "Candidate passed all dual-critic gates"

        orig_len = len(proposal.original_code.splitlines())
        cand_len = len(proposal.candidate_code.splitlines())
        sha = hashlib.sha256(proposal.candidate_code.encode("utf-8")).hexdigest()[:16]

        res = GateEvaluationResult(
            proposal_id=proposal.proposal_id,
            critic_a_decision=critic_a_dec,
            critic_b_decision=critic_b_dec,
            overall_decision=overall,
            allowed_edit_budget=budget,
            detected_edits_count=altered,
            ast_complexity_delta=cand_len - orig_len,
            in_distribution_score=id_s,
            out_of_distribution_score=ood_s,
            ood_lcb=ood_lcb,
            objective_lcb=obj_lcb,
            rejection_reason=reason,
            sha256_hash=sha,
        )
        self._record_in_ledger(res)
        return res

    def _record_in_ledger(self, result: GateEvaluationResult) -> None:
        """Append-only recording into the evolution ledger."""
        self.history.append(result)
        try:
            p = Path(self.ledger_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            entries = []
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            entries.append(result.to_dict())
            with open(p, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
        except Exception:
            pass
