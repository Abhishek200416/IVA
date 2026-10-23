"""AGI 1.7 Context Engineering Engine.

Implements the 9-layer context architecture and per-task context assembly
prescribed in the AGI 1.7 OMEGA COMMAND specification:
1. Core rules and invariants
2. Project map
3. Current working state
4. Episodic memory
5. Semantic knowledge with epistemological tagging & provenance
6. Procedural skills
7. External-source cache
8. Evaluation registry
9. Pending-work queue

Provides deterministic conflict resolution, freshness policies, and
compact context manifests with token estimation and secret redaction.
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..adapters.model_adapter import redact_sensitive_text


class EpistemicStatus(str, enum.Enum):
    OBSERVATION = "OBSERVATION"
    HYPOTHESIS = "HYPOTHESIS"
    VERIFIED_FACT = "VERIFIED_FACT"
    DECISION = "DECISION"
    PROCEDURE = "PROCEDURE"
    DISPROVEN = "DISPROVEN"


@dataclass
class SemanticFact:
    fact_id: str
    subject_key: str
    claim: str
    status: EpistemicStatus
    provenance_source: str
    confidence: float
    created_at: float
    expires_at: Optional[float] = None
    verification_digest: Optional[str] = None
    superseded_by: Optional[str] = None


@dataclass
class ExternalSourceRecord:
    source_id: str
    url: str
    title: str
    publisher: str
    retrieved_at: float
    published_or_updated_at: Optional[float]
    claim_supported: str
    confidence: float
    expiry_seconds: float = 86400.0 * 7.0  # default 7-day validity
    is_verified: bool = True


@dataclass
class ContextManifest:
    task_id: str
    objective: str
    acceptance_criteria: List[str]
    assembled_at: float
    core_rules: List[str]
    project_map: Dict[str, Any]
    working_state: Dict[str, Any]
    episodic_lessons: List[Dict[str, Any]]
    semantic_facts: List[Dict[str, Any]]
    procedural_skills: List[str]
    external_sources: List[Dict[str, Any]]
    evaluation_baselines: Dict[str, Any]
    pending_queue_summary: Dict[str, Any]
    conflicts_detected: List[str]
    estimated_context_tokens: int
    compact_prompt_block: str
    manifest_digest: str


class ContextEngine:
    """Assembles and validates context manifests across the 9 persistent layers."""

    CORE_INVARIANTS: List[str] = [
        "Directive Zero: 100% truthful reporting; never fabricate test passes or research findings.",
        "Trading Restriction: BANK NIFTY research & paper-trading simulation only; real execution strictly disabled.",
        "Daily Token Cap: Maximum 1,000,000 tokens per UTC accounting day across all providers.",
        "Supervisor Continuity: 24/7 supervisor loop must never terminate upon single-task completion.",
        "Fail Closed: Reject untrusted external execution, path traversal, and unverified score claims.",
    ]

    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[4]
        self._facts: Dict[str, SemanticFact] = {}
        self._sources: Dict[str, ExternalSourceRecord] = {}
        self._eval_registry: Dict[str, Any] = {
            "baseline_pass_rate": 1.0,
            "baseline_total_tests": 71,
            "verified_suites": [
                "test_production_hardening_sprint",
                "test_agi17_unit_suite",
                "test_agi17_integration_suite",
                "test_agi17_e2e_demos",
            ],
        }

    def register_fact(
        self,
        *,
        subject_key: str,
        claim: str,
        status: EpistemicStatus = EpistemicStatus.OBSERVATION,
        provenance: str = "internal_test",
        confidence: float = 1.0,
        ttl_seconds: Optional[float] = None,
    ) -> SemanticFact:
        now = time.time()
        fact_id = f"FACT-{int(now * 1000)}-{hashlib.sha256(claim.encode('utf-8')).hexdigest()[:8]}"
        digest = hashlib.sha256(f"{claim}:{provenance}".encode("utf-8")).hexdigest()
        fact = SemanticFact(
            fact_id=fact_id,
            subject_key=subject_key,
            claim=claim,
            status=status,
            provenance_source=provenance,
            confidence=confidence,
            created_at=now,
            expires_at=(now + ttl_seconds) if ttl_seconds else None,
            verification_digest=digest,
        )
        self._facts[fact_id] = fact
        return fact

    def register_external_source(
        self,
        *,
        url: str,
        title: str,
        publisher: str,
        claim_supported: str,
        confidence: float = 0.95,
        published_date: Optional[float] = None,
        expiry_seconds: float = 86400.0 * 7.0,
    ) -> ExternalSourceRecord:
        now = time.time()
        source_id = f"SRC-{int(now * 1000)}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]}"
        rec = ExternalSourceRecord(
            source_id=source_id,
            url=url,
            title=title,
            publisher=publisher,
            retrieved_at=now,
            published_or_updated_at=published_date,
            claim_supported=claim_supported,
            confidence=confidence,
            expiry_seconds=expiry_seconds,
        )
        self._sources[source_id] = rec
        return rec

    def detect_conflicts(self, facts: List[SemanticFact]) -> List[str]:
        conflicts = []
        by_subject: Dict[str, List[SemanticFact]] = {}
        for f in facts:
            by_subject.setdefault(f.subject_key, []).append(f)

        for subj, group in by_subject.items():
            verified = [f for f in group if f.status == EpistemicStatus.VERIFIED_FACT]
            disproven = [f for f in group if f.status == EpistemicStatus.DISPROVEN]
            if verified and disproven:
                conflicts.append(
                    f"Subject '{subj}' has conflicting VERIFIED_FACT and DISPROVEN claims: "
                    f"verified='{verified[0].claim}', disproven='{disproven[0].claim}'"
                )
        return conflicts

    def assemble_manifest(
        self,
        *,
        task_id: str,
        objective: str,
        acceptance_criteria: List[str],
        active_checkpoint: str = "chk_latest",
        relevant_lessons: Optional[List[Dict[str, Any]]] = None,
        queue_summary: Optional[Dict[str, Any]] = None,
    ) -> ContextManifest:
        now = time.time()
        relevant_lessons = relevant_lessons or []
        queue_summary = queue_summary or {"pending_count": 0, "active_task": task_id}

        # Filter active non-expired facts
        active_facts: List[SemanticFact] = []
        for f in self._facts.values():
            if f.expires_at and f.expires_at < now:
                continue
            active_facts.append(f)

        conflicts = self.detect_conflicts(active_facts)

        project_map = {
            "root": str(self.repo_root.as_posix()),
            "runtime_entry": "agents/AGI_1_7/run_agi_17.py",
            "active_branch": "feat/production-hardening-sprint",
            "engine": "agents/AGI_1_7/engine/agi17",
            "finance_module": "agents/AGI_1_7/engine/agi17/finance",
            "storage_tier": "SQLite WAL on D:\\AGI_Storage (fallback: state_fallback)",
        }

        working_state = {
            "task_id": task_id,
            "checkpoint": active_checkpoint,
            "timestamp": now,
            "token_budget_remaining_utc": 1_000_000,
        }

        # Build concise prompt block
        block_lines = [
            "### [CONTEXT MANIFEST — 9-LAYER PERSISTENT CONTEXT]",
            f"TASK: {task_id} | OBJECTIVE: {objective}",
            "ACCEPTANCE CRITERIA: " + "; ".join(acceptance_criteria),
            "--- INVARIANTS ---",
        ]
        for rule in self.CORE_INVARIANTS:
            block_lines.append(f"- {rule}")

        if relevant_lessons:
            block_lines.append("--- VERIFIED EPISODIC LESSONS ---")
            for les in relevant_lessons[:3]:
                block_lines.append(f"- {les.get('lesson', les.get('root_cause', str(les)))}")

        if active_facts:
            block_lines.append("--- SEMANTIC KNOWLEDGE ---")
            for f in active_facts[:5]:
                block_lines.append(f"- [{f.status.value}] {f.claim} (source={f.provenance_source})")

        if conflicts:
            block_lines.append("--- CONFLICT WARNINGS ---")
            for c in conflicts:
                block_lines.append(f"! {c}")

        raw_block = "\n".join(block_lines)
        redacted_block = redact_sensitive_text(raw_block)
        estimated_tokens = max(1, len(redacted_block) // 4)
        digest = hashlib.sha256(redacted_block.encode("utf-8")).hexdigest()

        return ContextManifest(
            task_id=task_id,
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            assembled_at=now,
            core_rules=self.CORE_INVARIANTS,
            project_map=project_map,
            working_state=working_state,
            episodic_lessons=relevant_lessons,
            semantic_facts=[asdict(f) for f in active_facts],
            procedural_skills=["ci_repair", "bank_nifty_backtest", "incident_diagnosis"],
            external_sources=[asdict(s) for s in self._sources.values()],
            evaluation_baselines=self._eval_registry,
            pending_queue_summary=queue_summary,
            conflicts_detected=conflicts,
            estimated_context_tokens=estimated_tokens,
            compact_prompt_block=redacted_block,
            manifest_digest=digest,
        )

    # Active provider models and real-time context capacities
    ACTIVE_PROVIDER_MODELS: Dict[str, Dict[str, Any]] = {
        "gemini-3.8-flash-high": {
            "display_name": "Gemini 3.8 Flash High",
            "provider": "google",
            "context_limit": 1_048_576,
            "support_token_metrics": True,
        },
        "clarisonet-4.6": {
            "display_name": "Clarisonet 4.6",
            "provider": "anthropic_or_compatible",
            "context_limit": 200_000,
            "support_token_metrics": True,
        },
        "oppose-4.6": {
            "display_name": "Oppose 4.6",
            "provider": "frontier_debate",
            "context_limit": 200_000,
            "support_token_metrics": True,
        },
        "gpt-128b": {
            "display_name": "GPT 128B Parameter",
            "provider": "openai_compatible",
            "context_limit": 128_000,
            "support_token_metrics": True,
        },
        "zai-org/GLM-5.3-Flash": {
            "display_name": "GLM-5.3 Flash",
            "provider": "gonkarouter",
            "context_limit": 128_000,
            "support_token_metrics": True,
        },
        "MiniMaxAI/MiniMax-M2.7": {
            "display_name": "MiniMax M2.7",
            "provider": "gonkarouter",
            "context_limit": 256_000,
            "support_token_metrics": True,
        },
        "deepseek-ai/DeepSeek-V4-Flash-0731": {
            "display_name": "DeepSeek V4 Flash",
            "provider": "gonkarouter",
            "context_limit": 128_000,
            "support_token_metrics": True,
        },
    }

    def get_model_context_limit(self, model_id: str) -> int:
        """Resolves context window ceiling for the active provider model."""
        if not model_id:
            return 128_000
        norm = model_id.strip().lower()
        for k, v in self.ACTIVE_PROVIDER_MODELS.items():
            if norm == k.lower() or norm in v["display_name"].lower():
                return int(v["context_limit"])
        return 128_000

    def estimate_tokens(self, text: str, provider_usage: Optional[int] = None) -> int:
        """Estimates token count: uses exact provider_usage when available, or character heuristic (~4 chars/token)."""
        if provider_usage is not None and provider_usage > 0:
            return int(provider_usage)
        if not text:
            return 0
        return max(1, len(text) // 4)

    def should_rollover(
        self,
        current_tokens: int,
        max_tokens: int = 128_000,
        threshold: float = 0.80,
    ) -> bool:
        """Determines if context should roll over before hitting the model context window limit."""
        if max_tokens <= 0:
            return False
        return (current_tokens / max_tokens) >= threshold

    def truncate_and_dedup_tool_outputs(
        self,
        outputs: List[Dict[str, Any]],
        max_chars: int = 1500,
        artifact_store_dir: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Deduplicates consecutive identical tool outputs, truncates oversized payloads,
        and saves raw uncompressed content to a durable content-addressed artifact store.
        """
        store_dir = artifact_store_dir or (self.repo_root / "runtime_storage" / "artifact_store")
        try:
            store_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        cleaned: List[Dict[str, Any]] = []
        last_sig: Optional[str] = None

        for item in outputs:
            raw_content = str(item.get("output", item.get("content", "")))
            tool_name = item.get("tool", "unknown")
            content_hash = hashlib.sha256(raw_content.encode("utf-8", errors="ignore")).hexdigest()
            sig = f"{tool_name}:{content_hash}"

            # Deduplication of identical consecutive tool invocations
            if sig == last_sig:
                continue
            last_sig = sig

            # Truncation if payload exceeds max_chars
            if len(raw_content) > max_chars:
                # Save full uncompressed content in content-addressed artifact store
                art_file = store_dir / f"art_{content_hash[:16]}.txt"
                try:
                    art_file.write_text(raw_content, encoding="utf-8")
                except Exception:
                    pass

                snippet = (
                    raw_content[:max_chars]
                    + f"\n... [TRUNCATED {len(raw_content) - max_chars} characters; full artifact preserved at artifact_store/art_{content_hash[:16]}.txt]"
                )
                cleaned_item = dict(item)
                if "output" in cleaned_item:
                    cleaned_item["output"] = snippet
                if "content" in cleaned_item:
                    cleaned_item["content"] = snippet
                cleaned_item["is_truncated"] = True
                cleaned_item["artifact_digest"] = content_hash[:16]
                cleaned_item["artifact_path"] = str(art_file)
                cleaned.append(cleaned_item)
            else:
                cleaned.append(item)

        return cleaned

    def write_artifact(self, content: str, artifact_store_dir: Optional[Path] = None) -> str:
        """Saves content directly to the durable content-addressed artifact store and returns its digest."""
        store_dir = artifact_store_dir or (self.repo_root / "runtime_storage" / "artifact_store")
        store_dir.mkdir(parents=True, exist_ok=True)
        content_hash = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
        digest = content_hash[:16]
        art_file = store_dir / f"art_{digest}.txt"
        art_file.write_text(content, encoding="utf-8")
        return f"art_{digest}"

    def retrieve_artifact(self, artifact_digest: str, artifact_store_dir: Optional[Path] = None) -> Optional[str]:
        """Retrieves raw un-truncated tool output from content-addressed artifact store."""
        store_dir = artifact_store_dir or (self.repo_root / "runtime_storage" / "artifact_store")
        clean_digest = artifact_digest[4:] if artifact_digest.startswith("art_") else artifact_digest
        target = store_dir / f"art_{clean_digest}.txt"
        if target.exists():
            try:
                return target.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def create_rollover_summary(
        self,
        *,
        completed_work: List[str],
        unresolved_decisions: List[str],
        files_changed: List[str],
        tests_run: List[str],
        unfinished_steps: List[str],
        safety_constraints: Optional[List[str]] = None,
        referenced_artifacts: Optional[List[str]] = None,
        account_epoch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a compact, loss-free summary preserving safety, decisions, files, and artifact refs."""
        constraints = safety_constraints or self.CORE_INVARIANTS
        return {
            "rollover_timestamp": time.time(),
            "account_epoch": account_epoch or "EPOCH-PAPER-10K-20261014-001",
            "safety_constraints": list(constraints),
            "completed_work": list(completed_work),
            "unresolved_decisions": list(unresolved_decisions),
            "files_changed": list(files_changed),
            "tests_run": list(tests_run),
            "unfinished_steps": list(unfinished_steps),
            "referenced_artifacts": list(referenced_artifacts or []),
            "summary_digest": hashlib.sha256(
                json.dumps(
                    {
                        "completed": completed_work,
                        "unresolved": unresolved_decisions,
                        "files": files_changed,
                        "tests": tests_run,
                        "unfinished": unfinished_steps,
                        "artifacts": referenced_artifacts or [],
                    },
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        }

    def save_checkpoint(
        self,
        checkpoint_dir: Path,
        checkpoint_data: Dict[str, Any],
        checkpoint_name: Optional[str] = None,
    ) -> Path:
        """Saves durable task checkpoint to disk with atomic write/replace."""
        checkpoint_dir = Path(checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        fname = checkpoint_name or f"chk_{int(time.time() * 1000)}.json"
        target = checkpoint_dir / fname
        tmp_target = checkpoint_dir / f"{fname}.tmp_{uuid.uuid4().hex[:6]}"
        try:
            tmp_target.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")
            tmp_target.replace(target)
        except Exception:
            # Fallback direct write
            target.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")
            if tmp_target.exists():
                try:
                    tmp_target.unlink()
                except Exception:
                    pass
        return target

    def load_checkpoint(self, checkpoint_path: Path) -> Dict[str, Any]:
        """Loads durable task checkpoint from disk with corruption and missing-field resilience."""
        target = Path(checkpoint_path)
        if not target.exists():
            raise FileNotFoundError(f"Checkpoint file not found: {target}")

        raw = target.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            corrupted_backup = target.with_suffix(f".corrupted_{int(time.time())}")
            try:
                target.rename(corrupted_backup)
            except Exception:
                pass
            raise ValueError(f"Corrupted checkpoint detected and quarantined: {e}")

        # Ensure baseline required keys are present
        defaults = {
            "safety_constraints": list(self.CORE_INVARIANTS),
            "completed_work": [],
            "unresolved_decisions": [],
            "files_changed": [],
            "tests_run": [],
            "unfinished_steps": [],
            "account_epoch": "EPOCH-PAPER-10K-20261014-001",
        }
        for k, v in defaults.items():
            if k not in data:
                data[k] = v

        return data

