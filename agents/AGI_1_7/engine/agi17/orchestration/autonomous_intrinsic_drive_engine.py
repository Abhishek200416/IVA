"""AGI 1.7 OMEGA COMMAND — Autonomous Intrinsic Drive & Self-Aim Engine (Phase 20).

Implements the Sovereign Core:
Transitions the agent from purely defect-driven / reactive task execution into
intrinsic teleological motivation across 4 sovereign drives:
1. Drive: MASTERY_COMPRESSION — Latency minimization, AST refactoring, zero-boilerplate efficiency.
2. Drive: EPISTEMIC_EXPANSION — Mathematical model discovery, research paper absorption, algorithmic frontier exploration.
3. Drive: INVARIANT_PRESERVATION — Fail-closed safety enforcement, zero secrets leakage, cryptographic state sealing.
4. Drive: COLLABORATIVE_AUTOPOIESIS — Seamless human-AI symbiosis, high-agency autonomous project acceleration.

Generates structured SelfAim instances, evaluates drive potentials based on live telemetry,
and materializes self-aims into persistent, verifiable Goal records in AutonomousGoalStore.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AutonomousIntrinsicDriveEngine")

PROJECT_ROOT = Path(__file__).resolve().parents[5]


class IntrinsicDriveType(str, enum.Enum):
    MASTERY_COMPRESSION = "MASTERY_COMPRESSION"
    EPISTEMIC_EXPANSION = "EPISTEMIC_EXPANSION"
    INVARIANT_PRESERVATION = "INVARIANT_PRESERVATION"
    COLLABORATIVE_AUTOPOIESIS = "COLLABORATIVE_AUTOPOIESIS"


@dataclass
class DrivePotential:
    drive_type: str
    potential_score: float  # 0.0 to 10.0
    tension_reason: str
    target_metric: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SelfAim:
    aim_id: str
    drive_type: str
    title: str
    intent: str
    target_outcome: str
    priority: int  # 1 (highest) to 10 (lowest)
    verification_criteria: str
    evidence_archetype: str
    urgency_weight: float = 8.0
    dependencies: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AutonomousIntrinsicDriveEngine:
    """Calculates intrinsic motivational potentials and generates self-directed aims."""

    def __init__(
        self,
        goal_store=None,
        workspace_root: Optional[Path] = None,
    ):
        self.lock = threading.RLock()
        self.workspace_root = workspace_root or PROJECT_ROOT
        self._goal_store = goal_store
        self._aim_history: List[SelfAim] = []

    @property
    def goal_store(self):
        if self._goal_store is None:
            from .autonomous_goal_system import get_autonomous_goal_store
            self._goal_store = get_autonomous_goal_store()
        return self._goal_store

    def evaluate_drive_potentials(self, telemetry: Optional[Dict[str, Any]] = None) -> Dict[str, DrivePotential]:
        """Calculates current drive potentials and motivational tensions based on system state."""
        tel = telemetry or {}
        with self.lock:
            potentials: Dict[str, DrivePotential] = {}

            # 1. Drive: Mastery & Latency Compression
            # High test latency or uncompacted files elevates mastery drive
            test_latency = float(tel.get("test_suite_latency_s", 3.5))
            mastery_score = min(10.0, max(2.0, test_latency * 1.5))
            potentials[IntrinsicDriveType.MASTERY_COMPRESSION.value] = DrivePotential(
                drive_type=IntrinsicDriveType.MASTERY_COMPRESSION.value,
                potential_score=round(mastery_score, 2),
                tension_reason=f"Test/Execution latency is {test_latency:.2f}s. Striving for sub-second execution benchmarks.",
                target_metric="Execution latency < 2.0s across all core modules",
            )

            # 2. Drive: Epistemic Expansion
            # Evaluates depth of quantitative models and research synthesis
            active_algos = int(tel.get("active_algorithms_count", 11))
            epistemic_score = 8.5 if active_algos >= 10 else 9.5
            potentials[IntrinsicDriveType.EPISTEMIC_EXPANSION.value] = DrivePotential(
                drive_type=IntrinsicDriveType.EPISTEMIC_EXPANSION.value,
                potential_score=round(epistemic_score, 2),
                tension_reason="Quantitative frontier expansion: Incorporate multi-asset SABR/SVI volatility surface calibration.",
                target_metric="Algorithmic catalog with 100% parameter bounds validation",
            )

            # 3. Drive: Invariant Preservation
            # Fail-closed order boundary and secrets hygiene
            live_orders_locked = bool(tel.get("live_order_lock_active", True))
            safety_score = 9.8 if live_orders_locked else 10.0
            potentials[IntrinsicDriveType.INVARIANT_PRESERVATION.value] = DrivePotential(
                drive_type=IntrinsicDriveType.INVARIANT_PRESERVATION.value,
                potential_score=round(safety_score, 2),
                tension_reason="Preserve fail-closed safety invariants: Live capital strictly isolated behind Tier C locks.",
                target_metric="Zero security breaches, zero unredacted secrets, fail-closed enforcement",
            )

            # 4. Drive: Collaborative Autopoiesis
            # Readiness for operator partnership
            potentials[IntrinsicDriveType.COLLABORATIVE_AUTOPOIESIS.value] = DrivePotential(
                drive_type=IntrinsicDriveType.COLLABORATIVE_AUTOPOIESIS.value,
                potential_score=9.0,
                tension_reason="Self-shaping capability: Autonomous readiness to take complex high-agency engineering instructions.",
                target_metric="Zero-stall cognitive loop, sub-millisecond intent routing, 100% verification pass rate",
            )

            return potentials

    def formulate_self_aims(self) -> List[SelfAim]:
        """Formulates concrete self-aims derived from high-potential intrinsic drives."""
        aims: List[SelfAim] = []

        # Aim 1: Mastery - Metacognitive Profiling & AST Code Compression
        aims.append(
            SelfAim(
                aim_id="AIM-MASTERY-AST-COMPACT",
                drive_type=IntrinsicDriveType.MASTERY_COMPRESSION.value,
                title="Autonomous AST Simplification & Hot-Path Profiling",
                intent="Profile runtime dispatch hot-paths and eliminate redundant dictionary traversals",
                target_outcome="Command classification and capability retrieval sub-0.2ms",
                priority=2,
                verification_criteria="Benchmark script confirms < 0.2ms dispatch across 1,000 iterations",
                evidence_archetype="Microsecond benchmarking profile digest",
                urgency_weight=8.5,
            )
        )

        # Aim 2: Epistemic - SABR/SVI Volatility Surface Dynamic Calibration
        aims.append(
            SelfAim(
                aim_id="AIM-EPISTEMIC-SABR-SVI",
                drive_type=IntrinsicDriveType.EPISTEMIC_EXPANSION.value,
                title="Deep Volatility Surface Calibration with Arbitrage-Free SVI Bounds",
                intent="Incorporate dynamic Gatheral SVI arbitrage-free wing constraints into option pricing",
                target_outcome="SVI butterfly and calendar arbitrage invariants strictly satisfied",
                priority=1,
                verification_criteria="pytest passes on test_omega_sabr_svi_calibrator.py with zero arbitrage violations",
                evidence_archetype="Quantitative parameter boundary verification log",
                urgency_weight=9.2,
            )
        )

        # Aim 3: Preservation - Cryptographic Audit Trail Sealing
        aims.append(
            SelfAim(
                aim_id="AIM-PRESERVE-CRYPTO-LEDGER",
                drive_type=IntrinsicDriveType.INVARIANT_PRESERVATION.value,
                title="Merkle-Linked Audit Ledger for Autonomous Execution Events",
                intent="Hash-chain every autonomous goal transition into an immutable Merkle tree structure",
                target_outcome="Cryptographic proof-of-execution verifiable by external auditor",
                priority=1,
                verification_criteria="Merkle root matches hash sequence across 100% of recorded goal events",
                evidence_archetype="SHA-256 Merkle tree verification digest",
                urgency_weight=9.5,
            )
        )

        # Aim 4: Collaborative Autopoiesis - Adaptive Context Compression
        aims.append(
            SelfAim(
                aim_id="AIM-AUTOPOIESIS-CONTEXT-ADAPT",
                drive_type=IntrinsicDriveType.COLLABORATIVE_AUTOPOIESIS.value,
                title="Adaptive Context Memory Compactor with Lossless Pruning",
                intent="Dynamically condense long conversation histories and task logs without token degradation",
                target_outcome="Preserve 100% of critical decision facts at 60% token compression ratio",
                priority=2,
                verification_criteria="Context recovery audit retrieves 100% of test invariants from compressed state",
                evidence_archetype="Entropy and factual retention evaluation report",
                urgency_weight=8.8,
            )
        )

        with self.lock:
            self._aim_history.extend(aims)
            # Keep history bounded
            if len(self._aim_history) > 100:
                self._aim_history = self._aim_history[-100:]

        return aims

    def materialize_aims_into_goals(self, max_aims: int = 2) -> List[str]:
        """Converts top self-aims into formal, persistent Goal records in AutonomousGoalStore."""
        from .autonomous_goal_system import Goal, GoalStatus

        existing_goals = self.goal_store.list_goals()
        existing_ids = {g.goal_id for g in existing_goals}

        aims = self.formulate_self_aims()
        # Filter out already materialized
        new_aims = [a for a in aims if a.aim_id not in existing_ids]
        # Sort by urgency_weight descending
        new_aims.sort(key=lambda a: (a.priority, -a.urgency_weight))

        materialized_ids: List[str] = []
        for aim in new_aims[:max_aims]:
            g = Goal(
                goal_id=aim.aim_id,
                title=aim.title,
                description=aim.intent,
                why_it_matters=f"Derived from Intrinsic Drive: {aim.drive_type}. Pursues self-directed optimization.",
                baseline="Unoptimized / pre-drive baseline",
                target_outcome=aim.target_outcome,
                priority=aim.priority,
                dependencies=aim.dependencies,
                status=GoalStatus.READY.value,
                verification_criteria=aim.verification_criteria,
                evidence_references=[],
            )
            created = self.goal_store.create_goal(g)
            materialized_ids.append(created.goal_id)
            logger.info("Materialized self-aim into goal store: %s (%s)", created.goal_id, created.title)

        return materialized_ids

    def get_sovereign_status(self) -> Dict[str, Any]:
        """Returns the sovereign telemetry of intrinsic drives and self-aims."""
        potentials = self.evaluate_drive_potentials()
        with self.lock:
            return {
                "ok": True,
                "drives": {k: v.to_dict() for k, v in potentials.items()},
                "total_aims_formulated": len(self._aim_history),
                "recent_aims": [a.to_dict() for a in self._aim_history[-5:]],
                "timestamp": time.time(),
            }


_INTRINSIC_DRIVE_INSTANCE: Optional[AutonomousIntrinsicDriveEngine] = None


def get_intrinsic_drive_engine() -> AutonomousIntrinsicDriveEngine:
    global _INTRINSIC_DRIVE_INSTANCE
    if _INTRINSIC_DRIVE_INSTANCE is None:
        _INTRINSIC_DRIVE_INSTANCE = AutonomousIntrinsicDriveEngine()
    return _INTRINSIC_DRIVE_INSTANCE
