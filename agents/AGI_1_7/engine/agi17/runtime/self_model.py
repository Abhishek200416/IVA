"""IVA Persistent Self-Model and Epistemic Internal State Engine.

Part of the IVA Architecture Evolution (Section 3).
Provides a persistent, inspectable, updateable, and schema-bounded self-model:
- Current identity and version (immutable at runtime).
- Capability and limitations inventory.
- Epistemic status tracking:
    * OBSERVED_FACT: Directly measured through tools.
    * USER_PROVIDED_INFO: Stated by the human operator (Abhi).
    * MODEL_GENERATED_HYPOTHESIS: Model-inferred, unverified until tested.
    * INFERRED_PREFERENCE: Behavioral pattern, provisional.
    * UNCERTAIN_INTERPRETATION: Ambiguous observation needing confirmation.
- Bounded interfaces preventing silent policy rewriting.
- Decisions, predictions, and verified outcomes.
- Known mistakes and durable lessons.
- Unresolved scientific/technical questions.
- Integration with OmegaCommandMemory.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("IvaSelfModel")

PROJECT_ROOT = Path(__file__).resolve().parents[5]


class EpistemicProvenance(str, enum.Enum):
    OBSERVED_FACT = "OBSERVED_FACT"
    USER_PROVIDED_INFO = "USER_PROVIDED_INFO"
    MODEL_GENERATED_HYPOTHESIS = "MODEL_GENERATED_HYPOTHESIS"
    INFERRED_PREFERENCE = "INFERRED_PREFERENCE"
    UNCERTAIN_INTERPRETATION = "UNCERTAIN_INTERPRETATION"


@dataclass(frozen=True)
class SystemIdentity:
    """Immutable identity anchors for IVA."""
    system_name: str = "Iva"
    version: str = "1.7.29"
    persona: str = "FEMALE_AUTONOMOUS_PARTNER"
    operator_name: str = "Abhi"
    fail_closed_safety: bool = True
    authoritative_doc: str = "agents/AGI_1_7/docs/01_AUTHORITATIVE_IDENTITY_AND_PERSONA.md"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityEntry:
    name: str
    domain: str
    verified: bool
    limitations: List[str] = field(default_factory=list)
    verification_evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EpistemicRecord:
    record_id: str
    subject: str
    content: str
    provenance: str
    confidence: float  # 0.0 to 1.0
    evidence: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionRecord:
    decision_id: str
    decision: str
    justification: str
    alternatives_considered: List[str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PredictionRecord:
    prediction_id: str
    claim: str
    expected_outcome: str
    observed_outcome: Optional[str] = None
    resolved: bool = False
    accuracy_score: Optional[float] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MistakeLessonRecord:
    lesson_id: str
    mistake_description: str
    root_cause: str
    lesson_learned: str
    prevention_rule: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UnresolvedQuestion:
    question_id: str
    question: str
    importance: str  # HIGH, MEDIUM, LOW
    missing_evidence: str
    status: str = "OPEN"  # OPEN, INVESTIGATING, RESOLVED
    resolution_evidence: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskExecutionState:
    task_id: Optional[str] = None
    description: str = "Idle / Awaiting instructions"
    state: str = "IDLE"  # IDLE, INSPECTING, EXECUTING, VERIFYING, BLOCKED
    started_at: Optional[float] = None
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OperationalState:
    fail_closed_invariant: bool = True
    live_order_dispatch_enabled: bool = False
    dashboard_port: int = 8088
    memory_backend: str = "SQLITE_WAL"
    active_subagents_count: int = 0
    recent_affective_state: str = "MOTIVATED_TO_CONTINUE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PersistentSelfModel:
    """Thread-safe, persistent self-model for IVA."""

    _instance: Optional["PersistentSelfModel"] = None

    def __init__(self, persistence_path: Optional[Path] = None):
        self.lock = threading.RLock()
        self.persistence_path = persistence_path or (PROJECT_ROOT / "scratch" / "iva_persistent_self_model.json")
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)

        self._identity = SystemIdentity()
        self._capabilities: Dict[str, CapabilityEntry] = {}
        self._epistemic_ledger: Dict[str, EpistemicRecord] = {}
        self._decisions: List[DecisionRecord] = []
        self._predictions: Dict[str, PredictionRecord] = []
        self._predictions_list: List[PredictionRecord] = []
        self._mistakes: List[MistakeLessonRecord] = []
        self._unresolved_questions: Dict[str, UnresolvedQuestion] = {}
        self._task_state = TaskExecutionState()
        self._operational_state = OperationalState()
        self._simulated_affective_state: Dict[str, Any] = {}

        self._seed_default_capabilities()
        self._load_from_disk()

    @classmethod
    def get_instance(cls, persistence_path: Optional[Path] = None) -> "PersistentSelfModel":
        if cls._instance is None:
            cls._instance = PersistentSelfModel(persistence_path)
        return cls._instance

    @property
    def identity(self) -> SystemIdentity:
        return self._identity

    def _seed_default_capabilities(self) -> None:
        """Seeds verified capabilities and documented operational boundaries."""
        caps = [
            CapabilityEntry(
                name="ast_refactoring_and_testing",
                domain="software_engineering",
                verified=True,
                limitations=["Cannot run pytest if uninstalled, uses standard library unittest"],
                verification_evidence="20/20 unittest pass on phase 17.24 test suite",
            ),
            CapabilityEntry(
                name="persistent_sqlite_wal_memory",
                domain="memory_and_storage",
                verified=True,
                limitations=["Requires disk write permissions on D:\\ or local fallback"],
                verification_evidence="10-layer WAL storage operational with ACON compression",
            ),
            CapabilityEntry(
                name="browser_automation_cdp",
                domain="web_automation",
                verified=True,
                limitations=["Cannot bypass broker two-factor authentication or CAPTCHA"],
                verification_evidence="Playwright/CDP tri-tab integration verified on port 9229",
            ),
            CapabilityEntry(
                name="quantitative_svi_calibration",
                domain="quantitative_finance",
                verified=True,
                limitations=["Live broker orders locked; fail-closed paper trading only"],
                verification_evidence="SVI surface calibration verified against Roger Lee bounds",
            ),
            CapabilityEntry(
                name="affective_and_metacognitive_modeling",
                domain="cognitive_architecture",
                verified=True,
                limitations=["Computational variables; strictly non-biological; zero qualia claim"],
                verification_evidence="OmegaAffectiveEngine and MetacognitiveSteeringEngine active",
            ),
        ]
        for c in caps:
            self._capabilities[c.name] = c

    def _load_from_disk(self) -> None:
        with self.lock:
            if not self.persistence_path.exists():
                return
            try:
                raw = json.loads(self.persistence_path.read_text(encoding="utf-8"))
                for r in raw.get("epistemic_records", []):
                    self._epistemic_ledger[r["record_id"]] = EpistemicRecord(**r)
                for d in raw.get("decisions", []):
                    self._decisions.append(DecisionRecord(**d))
                for p in raw.get("predictions", []):
                    self._predictions_list.append(PredictionRecord(**p))
                for m in raw.get("mistakes", []):
                    self._mistakes.append(MistakeLessonRecord(**m))
                for q in raw.get("unresolved_questions", []):
                    self._unresolved_questions[q["question_id"]] = UnresolvedQuestion(**q)
                if "task_state" in raw:
                    self._task_state = TaskExecutionState(**raw["task_state"])
                if "operational_state" in raw:
                    self._operational_state = OperationalState(**raw["operational_state"])
                if "simulated_affective_state" in raw:
                    self._simulated_affective_state = raw["simulated_affective_state"]
            except Exception as exc:
                logger.warning("Could not hydrate self-model from disk: %s", exc)

    def _save_to_disk(self) -> None:
        with self.lock:
            try:
                data = {
                    "identity": self._identity.to_dict(),
                    "capabilities": {k: v.to_dict() for k, v in self._capabilities.items()},
                    "epistemic_records": [r.to_dict() for r in self._epistemic_ledger.values()],
                    "decisions": [d.to_dict() for d in self._decisions[-50:]],
                    "predictions": [p.to_dict() for p in self._predictions_list[-50:]],
                    "mistakes": [m.to_dict() for m in self._mistakes[-50:]],
                    "unresolved_questions": [q.to_dict() for q in self._unresolved_questions.values()],
                    "task_state": self._task_state.to_dict(),
                    "operational_state": self._operational_state.to_dict(),
                    "simulated_affective_state": self._simulated_affective_state,
                    "updated_at": time.time(),
                }
                tmp_path = self.persistence_path.with_suffix(".tmp")
                tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                tmp_path.replace(self.persistence_path)
            except Exception as exc:
                logger.error("Could not persist self-model to disk: %s", exc)

    # -------------------------------------------------------------------------
    # Inspection Interfaces
    # -------------------------------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:
        """Returns complete structured snapshot of IVA's internal state."""
        with self.lock:
            return {
                "identity": self._identity.to_dict(),
                "capabilities": {k: v.to_dict() for k, v in self._capabilities.items()},
                "epistemic_counts": {
                    prov.value: sum(1 for r in self._epistemic_ledger.values() if r.provenance == prov.value)
                    for prov in EpistemicProvenance
                },
                "active_task": self._task_state.to_dict(),
                "operational_state": self._operational_state.to_dict(),
                "open_questions_count": sum(1 for q in self._unresolved_questions.values() if q.status == "OPEN"),
                "decisions_count": len(self._decisions),
                "unresolved_predictions_count": sum(1 for p in self._predictions_list if not p.resolved),
                "mistakes_recorded_count": len(self._mistakes),
                "simulated_affective_state": self._simulated_affective_state,
            }

    def get_epistemic_records(self, provenance: Optional[EpistemicProvenance] = None) -> List[EpistemicRecord]:
        with self.lock:
            records = list(self._epistemic_ledger.values())
            if provenance:
                return [r for r in records if r.provenance == provenance.value]
            return records

    def get_capabilities(self) -> Dict[str, CapabilityEntry]:
        with self.lock:
            return dict(self._capabilities)

    def get_unresolved_questions(self, open_only: bool = True) -> List[UnresolvedQuestion]:
        with self.lock:
            if open_only:
                return [q for q in self._unresolved_questions.values() if q.status == "OPEN"]
            return list(self._unresolved_questions.values())

    def get_decisions(self, limit: int = 20) -> List[DecisionRecord]:
        with self.lock:
            return list(self._decisions[-limit:])

    def get_predictions(self, unresolved_only: bool = False) -> List[PredictionRecord]:
        with self.lock:
            if unresolved_only:
                return [p for p in self._predictions_list if not p.resolved]
            return list(self._predictions_list)

    def get_mistakes_and_lessons(self) -> List[MistakeLessonRecord]:
        with self.lock:
            return list(self._mistakes)

    # -------------------------------------------------------------------------
    # Update Interfaces (Strictly Bounded)
    # -------------------------------------------------------------------------

    def record_epistemic_belief(
        self,
        subject: str,
        content: str,
        provenance: EpistemicProvenance,
        confidence: float,
        evidence: str,
    ) -> EpistemicRecord:
        """Records a belief with strict provenance labeling and confidence bounds."""
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {confidence}")

        # Invariant: Hypotheses cannot claim 1.0 confidence or be labeled OBSERVED_FACT without evidence
        if provenance == EpistemicProvenance.MODEL_GENERATED_HYPOTHESIS and confidence > 0.85:
            confidence = 0.85  # Cap unverified hypotheses
        if provenance == EpistemicProvenance.OBSERVED_FACT and not evidence:
            raise ValueError("OBSERVED_FACT requires empirical verification evidence.")

        rec_id = f"EPI-{hashlib.sha256(f'{subject}:{time.time()}'.encode()).hexdigest()[:8]}"
        record = EpistemicRecord(
            record_id=rec_id,
            subject=subject,
            content=content,
            provenance=provenance.value,
            confidence=confidence,
            evidence=evidence,
        )
        with self.lock:
            self._epistemic_ledger[rec_id] = record
            self._save_to_disk()
        return record

    def record_decision(
        self,
        decision: str,
        justification: str,
        alternatives_considered: List[str],
    ) -> DecisionRecord:
        """Logs an architectural or operational decision with justification."""
        dec_id = f"DEC-{int(time.time()*1000)}-{hashlib.sha256(decision.encode()).hexdigest()[:6]}"
        record = DecisionRecord(
            decision_id=dec_id,
            decision=decision,
            justification=justification,
            alternatives_considered=alternatives_considered,
        )
        with self.lock:
            self._decisions.append(record)
            self._save_to_disk()
        return record

    def record_prediction(
        self,
        claim: str,
        expected_outcome: str,
    ) -> PredictionRecord:
        """Records an operational or market prediction before the event occurs."""
        pred_id = f"PRED-{int(time.time()*1000)}-{hashlib.sha256(claim.encode()).hexdigest()[:6]}"
        record = PredictionRecord(
            prediction_id=pred_id,
            claim=claim,
            expected_outcome=expected_outcome,
            resolved=False,
        )
        with self.lock:
            self._predictions_list.append(record)
            self._save_to_disk()
        return record

    def resolve_prediction(
        self,
        prediction_id: str,
        observed_outcome: str,
        accuracy_score: float,
    ) -> Optional[PredictionRecord]:
        """Resolves a past prediction with observed evidence."""
        with self.lock:
            for p in self._predictions_list:
                if p.prediction_id == prediction_id:
                    p.observed_outcome = observed_outcome
                    p.resolved = True
                    p.accuracy_score = max(0.0, min(1.0, accuracy_score))
                    self._save_to_disk()
                    return p
            return None

    def record_mistake_and_lesson(
        self,
        mistake_description: str,
        root_cause: str,
        lesson_learned: str,
        prevention_rule: str,
    ) -> MistakeLessonRecord:
        """Records a mistake and operational rule to prevent recurrence."""
        les_id = f"LES-{int(time.time()*1000)}-{hashlib.sha256(root_cause.encode()).hexdigest()[:6]}"
        record = MistakeLessonRecord(
            lesson_id=les_id,
            mistake_description=mistake_description,
            root_cause=root_cause,
            lesson_learned=lesson_learned,
            prevention_rule=prevention_rule,
        )
        with self.lock:
            self._mistakes.append(record)
            self._save_to_disk()
        return record

    def add_unresolved_question(
        self,
        question: str,
        importance: str = "MEDIUM",
        missing_evidence: str = "",
    ) -> UnresolvedQuestion:
        """Records an open scientific, technical, or operational uncertainty."""
        q_id = f"Q-{int(time.time()*1000)}-{hashlib.sha256(question.encode()).hexdigest()[:6]}"
        record = UnresolvedQuestion(
            question_id=q_id,
            question=question,
            importance=importance,
            missing_evidence=missing_evidence,
        )
        with self.lock:
            self._unresolved_questions[q_id] = record
            self._save_to_disk()
        return record

    def resolve_question(
        self,
        question_id: str,
        resolution_evidence: str,
    ) -> bool:
        """Marks an uncertainty resolved once evidence is verified."""
        with self.lock:
            if question_id in self._unresolved_questions:
                q = self._unresolved_questions[question_id]
                q.status = "RESOLVED"
                q.resolution_evidence = resolution_evidence
                self._save_to_disk()
                return True
            return False

    def update_task_state(
        self,
        task_id: Optional[str],
        description: str,
        state: str,
        blockers: Optional[List[str]] = None,
    ) -> None:
        """Updates current execution state."""
        with self.lock:
            self._task_state = TaskExecutionState(
                task_id=task_id,
                description=description,
                state=state,
                started_at=time.time(),
                blockers=blockers or [],
            )
            self._save_to_disk()

    def set_affective_state(self, affective_data: Dict[str, Any]) -> None:
        """Receives operational affective snapshot from OmegaAffectiveEngine."""
        with self.lock:
            self._simulated_affective_state = affective_data
            self._operational_state.recent_affective_state = affective_data.get("dominant_state", "MOTIVATED_TO_CONTINUE")
            self._save_to_disk()

    def update_capability(self, capability: CapabilityEntry) -> None:
        """Registers or updates a capability record."""
        with self.lock:
            self._capabilities[capability.name] = capability
            self._save_to_disk()


_SELF_MODEL_INSTANCE: Optional[PersistentSelfModel] = None


def get_self_model() -> PersistentSelfModel:
    global _SELF_MODEL_INSTANCE
    if _SELF_MODEL_INSTANCE is None:
        _SELF_MODEL_INSTANCE = PersistentSelfModel()
    return _SELF_MODEL_INSTANCE
