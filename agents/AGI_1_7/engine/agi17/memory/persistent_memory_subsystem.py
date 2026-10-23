"""AGI 1.7 Persistent Memory Subsystem (Phase 17.25).

Extends OmegaCommandMemory with:
1. Strict categorical taxonomy:
   - VERIFIED_FACT: Grounded, empirical, test-validated truths.
   - HYPOTHESIS: Testable claims awaiting empirical verification.
   - USER_PREFERENCE: Explicit human collaborator preferences and directives.
   - HISTORICAL_REPORT: Completed milestone summaries and evaluation snapshots.
   - UNVERIFIED_CLAIM: External claims not yet independently confirmed.
   - TEMPORARY_OBSERVATION: Short-lived runtime scratchpad telemetry.
   - LESSON_LEARNED: Concise engineering patterns from successes or failures.
2. Contradiction supersession history (never silent deletion of past reality).
3. Automatic payload deduplication using content hashing (prevents DB bloating).
4. Goal, task, and artifact linkage.
5. Targeted, fast indexed SQLite WAL retrieval.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import math
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .omega_command_memory import OmegaCommandMemory, MemoryEntry

logger = logging.getLogger("PersistentMemorySubsystem")


class MemoryCategory(str, enum.Enum):
    VERIFIED_FACT = "VERIFIED_FACT"
    HYPOTHESIS = "HYPOTHESIS"
    USER_PREFERENCE = "USER_PREFERENCE"
    HISTORICAL_REPORT = "HISTORICAL_REPORT"
    UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"
    TEMPORARY_OBSERVATION = "TEMPORARY_OBSERVATION"
    LESSON_LEARNED = "LESSON_LEARNED"


class VerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    HYPOTHESIS = "HYPOTHESIS"
    SUPERSEDED = "SUPERSEDED"


# Mapping from categorical type to standard 10-layer memory hierarchy
CATEGORY_LAYER_MAP: Dict[MemoryCategory, int] = {
    MemoryCategory.TEMPORARY_OBSERVATION: 1,  # ACTIVE_TURN_SCRATCHPAD
    MemoryCategory.HYPOTHESIS: 2,             # TASK_WORKING_MEMORY
    MemoryCategory.USER_PREFERENCE: 5,       # CROSS_SESSION_SEMANTIC_FACTS
    MemoryCategory.VERIFIED_FACT: 5,          # CROSS_SESSION_SEMANTIC_FACTS
    MemoryCategory.LESSON_LEARNED: 6,         # PROCEDURAL_WORKFLOW_RECIPES (or 7 if failure)
    MemoryCategory.UNVERIFIED_CLAIM: 9,       # VERIFIED_RESEARCH_CACHE (unverified)
    MemoryCategory.HISTORICAL_REPORT: 10,     # IMMUTABLE_AUDIT_AND_BENCHMARK_LEDGER
}
 
# Recency-weighted exponential decay rates per category:
# score = confidence * exp(-lambda * (now - created_at) / 86400)
# lambda = 0.0: Immutable facts, user preferences, historical audit reports (zero decay)
# lambda = 0.1: Lessons learned from successes or failures (half-life ~6.93 days)
# lambda = 0.2: Working hypotheses (half-life ~3.47 days)
# lambda = 0.3: External unverified claims (half-life ~2.31 days)
# lambda = 0.5: Temporary runtime observations & scratchpad telemetry (half-life ~1.39 days)
DEFAULT_CATEGORY_DECAY_LAMBDA: Dict[MemoryCategory, float] = {
    MemoryCategory.VERIFIED_FACT: 0.0,
    MemoryCategory.USER_PREFERENCE: 0.0,
    MemoryCategory.HISTORICAL_REPORT: 0.0,
    MemoryCategory.LESSON_LEARNED: 0.1,
    MemoryCategory.HYPOTHESIS: 0.2,
    MemoryCategory.UNVERIFIED_CLAIM: 0.3,
    MemoryCategory.TEMPORARY_OBSERVATION: 0.5,
}


@dataclass
class StructuredMemoryRecord:
    record_id: str
    category: MemoryCategory
    layer: int
    subject_key: str
    content: str
    confidence: float
    verification_status: VerificationStatus
    source_task_id: Optional[str] = None
    source_url: Optional[str] = None
    provenance_type: str = "INTERNAL_ENGINEERING"
    related_goal_id: Optional[str] = None
    related_task_id: Optional[str] = None
    related_project: str = "AGI_1_7_OMEGA_COMMAND"
    artifact_paths: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    review_at: Optional[float] = None
    content_hash: str = ""
    supersedes_id: Optional[str] = None
    superseded_by_id: Optional[str] = None
    is_active: bool = True
    decayed_score: Optional[float] = None
    decayed_confidence: Optional[float] = None

    def calculate_hash(self) -> str:
        payload = f"{self.category.value}:{self.subject_key}:{self.content.strip()}"
        self.content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.content_hash

    def compute_decayed_confidence(
        self,
        now: Optional[float] = None,
        decay_lambda: Optional[float] = None,
    ) -> float:
        """Computes confidence with exponential recency decay: conf * exp(-lambda * dt_days)."""
        curr_t = now if now is not None else time.time()
        lam = (
            decay_lambda
            if decay_lambda is not None
            else DEFAULT_CATEGORY_DECAY_LAMBDA.get(self.category, 0.1)
        )
        age_days = max(0.0, (curr_t - self.created_at) / 86400.0)
        self.decayed_confidence = round(self.confidence * math.exp(-lam * age_days), 6)
        return self.decayed_confidence

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["verification_status"] = self.verification_status.value
        return d


class PersistentMemorySubsystem:
    """Authoritative persistent memory manager with deduplication and supersession."""

    _instance: Optional["PersistentMemorySubsystem"] = None

    def __init__(self, memory_core: Optional[OmegaCommandMemory] = None):
        self.core = memory_core or OmegaCommandMemory()

    @classmethod
    def get_instance(cls, memory_core: Optional[OmegaCommandMemory] = None) -> "PersistentMemorySubsystem":
        if cls._instance is None:
            cls._instance = PersistentMemorySubsystem(memory_core)
        return cls._instance

    def store_record(
        self,
        *,
        category: MemoryCategory,
        subject_key: str,
        content: str,
        confidence: float = 1.0,
        verification_status: VerificationStatus = VerificationStatus.VERIFIED,
        source_task_id: Optional[str] = None,
        source_url: Optional[str] = None,
        provenance_type: str = "INTERNAL_ENGINEERING",
        related_goal_id: Optional[str] = None,
        related_task_id: Optional[str] = None,
        artifact_paths: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        ttl_seconds: Optional[float] = None,
        is_failure_lesson: bool = False,
    ) -> StructuredMemoryRecord:
        """Stores a structured memory record with automatic deduplication and supersession."""
        # Determine memory layer
        layer = CATEGORY_LAYER_MAP.get(category, 5)
        if category == MemoryCategory.LESSON_LEARNED and is_failure_lesson:
            layer = 7  # FAILURE_PATTERNS_AND_PLAYBOOKS

        # Create candidate record
        record_id = f"MEM-{category.value[:4]}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        now = time.time()
        expires_at = (now + ttl_seconds) if ttl_seconds else None

        record = StructuredMemoryRecord(
            record_id=record_id,
            category=category,
            layer=layer,
            subject_key=subject_key,
            content=content.strip(),
            confidence=confidence,
            verification_status=verification_status,
            source_task_id=source_task_id,
            source_url=source_url,
            provenance_type=provenance_type,
            related_goal_id=related_goal_id,
            related_task_id=related_task_id,
            artifact_paths=artifact_paths or [],
            tags=tags or [],
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        c_hash = record.calculate_hash()

        # Deduplication check: Search active entries in this layer and subject_key
        existing_entries = self.core.retrieve(
            subject_key=subject_key,
            layers=[layer],
            active_only=True,
            limit=5,
        )

        for existing in existing_entries:
            s_data = existing.structured_data or {}
            existing_hash = s_data.get("content_hash", "")
            if existing_hash == c_hash or existing.content.strip() == record.content:
                # Deduplication hit: update timestamp, avoid redundant DB write
                logger.info(f"Deduplication hit for memory record '{subject_key}' ({existing.entry_id})")
                record.record_id = existing.entry_id
                record.created_at = existing.created_at
                record.updated_at = now
                record.is_active = True
                return record

        # Pack structured payload for storage
        structured_payload = {
            "category": category.value,
            "verification_status": verification_status.value,
            "content_hash": c_hash,
            "provenance_type": provenance_type,
            "source_url": source_url,
            "related_goal_id": related_goal_id,
            "related_task_id": related_task_id,
            "artifact_paths": artifact_paths or [],
        }

        # Store in core SQLite WAL engine
        core_entry = self.core.store(
            layer=layer,
            subject_key=subject_key,
            content=content,
            structured_data=structured_payload,
            tags=tags or [category.value.lower()],
            source_task_id=source_task_id,
            confidence=confidence,
            ttl_seconds=ttl_seconds,
            supersede_existing_subject=True,
            entry_id=record_id,
        )

        record.supersedes_id = core_entry.supersedes_id
        return record

    def record_lesson(
        self,
        *,
        title: str,
        lesson: str,
        source_task_id: Optional[str] = None,
        is_failure: bool = False,
        artifact_paths: Optional[List[str]] = None,
    ) -> StructuredMemoryRecord:
        """Stores a concise, actionable lesson from completed tasks or failures."""
        cat = MemoryCategory.LESSON_LEARNED
        subject = f"lesson:{'failure' if is_failure else 'success'}:{title.lower().replace(' ', '_')}"
        tags = ["lesson", "pattern", "failure" if is_failure else "success"]
        return self.store_record(
            category=cat,
            subject_key=subject,
            content=lesson,
            source_task_id=source_task_id,
            artifact_paths=artifact_paths,
            tags=tags,
            is_failure_lesson=is_failure,
        )

    def retrieve_records(
        self,
        *,
        query: str = "",
        category: Optional[MemoryCategory] = None,
        subject_key: Optional[str] = None,
        related_goal_id: Optional[str] = None,
        active_only: bool = True,
        limit: int = 15,
        apply_decay: bool = True,
        category_decay_rates: Optional[Dict[MemoryCategory, float]] = None,
        min_score: float = 0.0,
    ) -> List[StructuredMemoryRecord]:
        """Performs targeted, indexed search across memory records with recency-weighted exponential decay.
        
        Scoring formula:
            score = (confidence * exp(-lambda * (now - created_at) / 86400)) * (1.0 + 2.0 * matches) + min(1.0, useful_count * 0.2)
        where lambda is category-specific (e.g. 0.0 for VERIFIED_FACT, 0.1 for LESSON_LEARNED, 0.5 for TEMPORARY_OBSERVATION).
        """
        if category == MemoryCategory.LESSON_LEARNED:
            layers = [6, 7]
        elif category:
            layers = [CATEGORY_LAYER_MAP[category]]
        else:
            layers = None

        # Fetch candidate buffer so post-filtering and recency re-ranking do not prematurely truncate results
        candidate_limit = max(limit * 4, 60) if (category is None or apply_decay or related_goal_id) else limit
        entries = self.core.retrieve(
            query=query,
            layers=layers,
            subject_key=subject_key,
            active_only=active_only,
            limit=candidate_limit,
        )

        decay_rates = category_decay_rates or DEFAULT_CATEGORY_DECAY_LAMBDA
        now = time.time()
        q_tokens = {tok.lower() for tok in re.findall(r"\w+", query) if len(tok) >= 2}

        scored_records: List[Tuple[float, StructuredMemoryRecord]] = []
        for e in entries:
            s_data = e.structured_data or {}
            cat_str = s_data.get("category", MemoryCategory.VERIFIED_FACT.value)
            try:
                cat_enum = MemoryCategory(cat_str)
            except ValueError:
                cat_enum = MemoryCategory.VERIFIED_FACT

            if category and cat_enum != category:
                continue

            if related_goal_id and s_data.get("related_goal_id") != related_goal_id:
                continue

            ver_status_str = s_data.get("verification_status", VerificationStatus.VERIFIED.value)
            try:
                ver_status_enum = VerificationStatus(ver_status_str)
            except ValueError:
                ver_status_enum = VerificationStatus.VERIFIED

            rec = StructuredMemoryRecord(
                record_id=e.entry_id,
                category=cat_enum,
                layer=e.layer,
                subject_key=e.subject_key,
                content=e.content,
                confidence=e.confidence,
                verification_status=ver_status_enum,
                source_task_id=e.source_task_id,
                source_url=s_data.get("source_url"),
                provenance_type=s_data.get("provenance_type", "INTERNAL"),
                related_goal_id=s_data.get("related_goal_id"),
                related_task_id=s_data.get("related_task_id"),
                artifact_paths=s_data.get("artifact_paths", []),
                tags=e.tags,
                created_at=e.created_at,
                updated_at=e.updated_at,
                expires_at=e.expires_at,
                content_hash=s_data.get("content_hash", ""),
                supersedes_id=e.supersedes_id,
                superseded_by_id=e.superseded_by_id,
                is_active=e.is_active,
            )

            # Recency-weighted exponential decay
            if apply_decay:
                lam = decay_rates.get(cat_enum, 0.1)
                age_days = max(0.0, (now - e.created_at) / 86400.0)
                decayed_conf = e.confidence * math.exp(-lam * age_days)
            else:
                decayed_conf = e.confidence

            rec.decayed_confidence = round(decayed_conf, 6)

            # Query relevance multiplier
            if q_tokens:
                haystack = f"{e.subject_key} {e.content} {' '.join(e.tags)}".lower()
                matches = sum(1 for tok in q_tokens if tok in haystack)
                relevance_mult = 1.0 + (matches * 2.0)
            else:
                relevance_mult = 1.0

            useful_boost = min(1.0, e.useful_count * 0.2)
            total_score = (decayed_conf * relevance_mult) + useful_boost

            if total_score < min_score:
                continue

            rec.decayed_score = round(total_score, 6)
            scored_records.append((total_score, rec))

        # Rank by total_score descending, tie-breaking by created_at descending
        scored_records.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [item[1] for item in scored_records[:limit]]

    def get_memory_stats(self) -> Dict[str, Any]:
        """Returns statistics on stored memory records by category and layer."""
        stats: Dict[str, Any] = {
            "total_entries": 0,
            "active_entries": 0,
            "by_layer": {},
            "db_path": str(self.core.db_path),
            "journal_mode": "WAL",
        }
        with self.core._lock:
            conn = self.core._connect()
            try:
                tot = conn.execute("SELECT count(*) as c FROM memory_entries").fetchone()["c"]
                act = conn.execute("SELECT count(*) as c FROM memory_entries WHERE is_active = 1").fetchone()["c"]
                stats["total_entries"] = tot
                stats["active_entries"] = act
                layer_rows = conn.execute("SELECT layer, count(*) as c FROM memory_entries GROUP BY layer").fetchall()
                for r in layer_rows:
                    stats["by_layer"][r["layer"]] = r["c"]
            finally:
                conn.close()
        return stats
