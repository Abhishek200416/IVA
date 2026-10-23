"""Confidence-Aware Test-Time Scaling (CATTS) & Dynamic Compute Governor.

Implements research-grounded inference compute allocation:
1. CATTS Methodology (Confidence-Aware Scaling - arXiv:2602.04948):
   - Rather than uniform compute spending, dynamically assesses uncertainty and entropy.
   - Allocates compute budgets (rollouts, PRM step depths, candidate branches) proportionally
     to decision risk and ambiguity.
2. Routing Paths:
   - FAST_PATH: Low uncertainty, deterministic safe actions -> Minimal overhead.
   - VERIFIED_PATH: Moderate uncertainty, standard code refactors -> Step PRM check.
   - DEEP_SEARCH_PATH: High uncertainty, complex multi-file changes, financial operations -> Multi-candidate MCTS tree search.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ComputeAllocation:
    route: str  # "FAST_PATH", "VERIFIED_PATH", "DEEP_SEARCH_PATH"
    uncertainty_score: float  # 0.0 to 1.0
    candidate_branch_budget: int
    prm_verification_depth: int
    max_timeout_sec: float
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConfidenceAwareComputeGovernor:
    """Dynamically scales test-time compute based on task complexity and uncertainty entropy."""

    def __init__(
        self,
        fast_path_threshold: float = 0.25,
        deep_search_threshold: float = 0.65,
    ) -> None:
        self.fast_path_threshold = fast_path_threshold
        self.deep_search_threshold = deep_search_threshold
        self.history: List[ComputeAllocation] = []

    def assess_uncertainty(
        self,
        task_description: str,
        files_affected_count: int = 1,
        is_financial_or_live: bool = False,
        historical_failures_count: int = 0,
    ) -> float:
        """Estimates task entropy/uncertainty score between 0.0 (trivial) and 1.0 (critical)."""
        desc_lower = task_description.lower()
        score = 0.1  # baseline minimal uncertainty

        # 1. Linguistic complexity indicators
        complex_signals = [
            "refactor", "migrate", "concurrency", "deadlock", "race condition",
            "security", "auth", "permission", "crypto", "distributed", "protocol",
            "blast radius", "breaking change", "rollback"
        ]
        for signal in complex_signals:
            if signal in desc_lower:
                score += 0.15

        moderate_signals = ["update", "edit", "patch", "implement", "write", "modify", "wire"]
        for signal in moderate_signals:
            if signal in desc_lower:
                score += 0.10

        # 2. File blast-radius multiplier
        if files_affected_count > 3:
            score += 0.25
        elif files_affected_count > 1:
            score += 0.12

        # 3. High-stakes domain (financial invariants / broker executions)
        if is_financial_or_live or "broker" in desc_lower or "options" in desc_lower:
            score += 0.35

        # 4. Past failure history penalty
        if historical_failures_count > 0:
            score += min(0.30, historical_failures_count * 0.10)

        # 5. Routine fast-path signals (discount uncertainty)
        fast_signals = ["view", "inspect", "list", "check status", "cat", "echo", "docstring", "comment"]
        for signal in fast_signals:
            if signal in desc_lower and "refactor" not in desc_lower:
                score -= 0.15

        return min(1.0, max(0.0, score))

    def allocate_compute(
        self,
        task_description: str,
        files_affected_count: int = 1,
        is_financial_or_live: bool = False,
        historical_failures_count: int = 0,
    ) -> ComputeAllocation:
        """Determines the optimal test-time compute budget and execution trajectory."""
        uncertainty = self.assess_uncertainty(
            task_description=task_description,
            files_affected_count=files_affected_count,
            is_financial_or_live=is_financial_or_live,
            historical_failures_count=historical_failures_count,
        )

        if uncertainty <= self.fast_path_threshold:
            allocation = ComputeAllocation(
                route="FAST_PATH",
                uncertainty_score=round(uncertainty, 3),
                candidate_branch_budget=1,
                prm_verification_depth=1,
                max_timeout_sec=5.0,
                rationale="Low uncertainty; routine read/inspection action dispatched with minimal compute overhead.",
            )
        elif uncertainty <= self.deep_search_threshold:
            allocation = ComputeAllocation(
                route="VERIFIED_PATH",
                uncertainty_score=round(uncertainty, 3),
                candidate_branch_budget=2,
                prm_verification_depth=2,
                max_timeout_sec=25.0,
                rationale="Moderate uncertainty; intermediate code modifications verified via Copy-on-Write PRM sandbox.",
            )
        else:
            allocation = ComputeAllocation(
                route="DEEP_SEARCH_PATH",
                uncertainty_score=round(uncertainty, 3),
                candidate_branch_budget=4,
                prm_verification_depth=3,
                max_timeout_sec=60.0,
                rationale="High uncertainty/risk; deep multi-path tree search with speculative simulation and Reflexion verification.",
            )

        self.history.append(allocation)
        return allocation

    def get_allocation_telemetry(self) -> Dict[str, Any]:
        if not self.history:
            return {"total_decisions": 0, "distribution": {}}

        total = len(self.history)
        dist: Dict[str, int] = {}
        for h in self.history:
            dist[h.route] = dist.get(h.route, 0) + 1

        return {
            "total_decisions": total,
            "fast_path_ratio": round(dist.get("FAST_PATH", 0) / total, 3),
            "verified_path_ratio": round(dist.get("VERIFIED_PATH", 0) / total, 3),
            "deep_search_ratio": round(dist.get("DEEP_SEARCH_PATH", 0) / total, 3),
            "mean_uncertainty": round(sum(h.uncertainty_score for h in self.history) / total, 3),
        }
