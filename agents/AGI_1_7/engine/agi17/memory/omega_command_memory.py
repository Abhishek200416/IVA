"""AGI 1.7 Omega Command 10-Layer Persistent Memory & ACON Context Compressor.

Provides durable SQLite WAL storage on D:\\AGI_Storage\\AGI_1_7\\memory (with
automatic local fallback if D:\\ is unavailable), 10 distinct memory layers,
mandatory pre-planning retrieval with audit logs, fact supersession history,
and ACON-style structural observation compression.
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


class MemoryCategory(str, enum.Enum):
    IDENTITY = "IDENTITY"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    PROCEDURAL = "PROCEDURAL"
    PROJECT = "PROJECT"
    PROJECT_STATE = "PROJECT"
    REFLECTION = "REFLECTION"
    REFLECTION_LESSON = "REFLECTION"
    LESSON_LEARNED = "REFLECTION"
    AFFECTIVE_HISTORY = "AFFECTIVE_HISTORY"


MEMORY_LAYERS: Dict[int, str] = {
    1: "ACTIVE_TURN_SCRATCHPAD",
    2: "TASK_WORKING_MEMORY",
    3: "SUBAGENT_SHARED_ARTIFACTS",
    4: "COMPRESSED_EPISODIC_TRACE",
    5: "CROSS_SESSION_SEMANTIC_FACTS",
    6: "PROCEDURAL_WORKFLOW_RECIPES",
    7: "FAILURE_PATTERNS_AND_PLAYBOOKS",
    8: "RESOURCE_AND_ENV_PROFILES",
    9: "VERIFIED_RESEARCH_CACHE",
    10: "IMMUTABLE_AUDIT_AND_BENCHMARK_LEDGER",
}

# Regexes for ACON preservation of critical tokens
SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
EXIT_CODE_RE = re.compile(r"(?:exit[_\s-]?code|returncode|status)\s*[:=]\s*(-?\d+)", re.IGNORECASE)
FILE_PATH_RE = re.compile(r"(?:[a-zA-Z]:\\[^\s\"',;]+|/[\w.\-/]+\.[\w]+)")
ERROR_NAME_RE = re.compile(r"\b([A-Z][a-zA-Z0-9_]*(?:Error|Exception|Timeout|Failure|Fault))\b")
TASK_ID_RE = re.compile(r"\b(?:TASK|SUBTASK|MISSION|CAMPAIGN|NOTIF|CHK)-[A-Za-z0-9_\-]+\b")


@dataclass
class MemoryEntry:
    entry_id: str
    layer: int
    layer_name: str
    subject_key: str
    content: str
    structured_data: Dict[str, Any]
    tags: List[str]
    source_task_id: Optional[str]
    session_id: str
    confidence: float
    created_at: float
    updated_at: float
    expires_at: Optional[float] = None
    access_count: int = 0
    useful_count: int = 0
    supersedes_id: Optional[str] = None
    superseded_by_id: Optional[str] = None
    is_active: bool = True
    category: str = "SEMANTIC"
    provenance: str = "OBSERVED_FACT"


class ACONCompressor:
    """ACON-inspired observation and history compressor preserving critical execution anchors."""

    @staticmethod
    def compress_observation(
        raw_text: str,
        max_chars: int = 600,
        preserve_identifiers: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        raw_len = len(raw_text)
        raw_est_tokens = max(1, raw_len // 4)

        sha256_hashes = list(dict.fromkeys(SHA256_RE.findall(raw_text)))
        exit_codes = list(dict.fromkeys(EXIT_CODE_RE.findall(raw_text)))
        file_paths = list(dict.fromkeys(FILE_PATH_RE.findall(raw_text)))[:10]
        error_names = list(dict.fromkeys(ERROR_NAME_RE.findall(raw_text)))[:10]
        task_ids = list(dict.fromkeys(TASK_ID_RE.findall(raw_text)))[:10]
        extra_ids = [ident for ident in (preserve_identifiers or []) if ident in raw_text]

        if raw_len <= max_chars:
            compressed_text = raw_text
        else:
            lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
            head = lines[:3]
            tail = lines[-4:] if len(lines) > 3 else []
            preserved_parts: List[str] = []
            if task_ids:
                preserved_parts.append(f"tasks={','.join(task_ids[:4])}")
            if exit_codes:
                preserved_parts.append(f"exit_codes={','.join(exit_codes[:3])}")
            if error_names:
                preserved_parts.append(f"errors={','.join(error_names[:4])}")
            if file_paths:
                preserved_parts.append(f"paths={','.join(file_paths[:3])}")
            if sha256_hashes:
                preserved_parts.append(f"sha256={','.join(sha256_hashes[:2])}")
            if extra_ids:
                preserved_parts.append(f"anchors={','.join(extra_ids[:4])}")

            anchor_summary = " | ".join(preserved_parts)
            body = " ... ".join(head + ([f"[{anchor_summary}]"] if anchor_summary else []) + tail)
            if len(body) > max_chars:
                # Guarantee preserved anchors stay intact at the start
                prefix = f"[{anchor_summary}] " if anchor_summary else ""
                remaining = max(60, max_chars - len(prefix))
                half = remaining // 2
                body = prefix + raw_text[:half].strip() + " ... " + raw_text[-half:].strip()
            compressed_text = body

        comp_len = len(compressed_text)
        comp_est_tokens = max(1, comp_len // 4)
        reduction_ratio = round(1.0 - (comp_len / max(1, raw_len)), 4) if raw_len > comp_len else 0.0

        return {
            "compressed_text": compressed_text,
            "raw_chars": raw_len,
            "compressed_chars": comp_len,
            "raw_estimated_tokens": raw_est_tokens,
            "compressed_estimated_tokens": comp_est_tokens,
            "reduction_ratio": reduction_ratio,
            "preserved_anchors": {
                "task_ids": task_ids,
                "exit_codes": exit_codes,
                "error_names": error_names,
                "file_paths": file_paths,
                "sha256_hashes": sha256_hashes,
                "extra_identifiers": extra_ids,
            },
        }


class OmegaCommandMemory:
    """10-Layer cross-session SQLite WAL persistent memory with mandatory pre-planning retrieval."""

    def __init__(
        self,
        primary_dir: str | Path = r"D:\AGI_Storage\AGI_1_7\memory",
        fallback_dir: Optional[str | Path] = None,
        session_id: Optional[str] = None,
        force_fallback: bool = False,
        mirror_dir: Optional[str | Path] = None,
    ) -> None:
        import os as _os
        import sys as _sys

        env_dir = _os.environ.get("OMEGA_MEMORY_DIR")
        if env_dir:
            primary_dir = env_dir
        elif primary_dir == r"D:\AGI_Storage\AGI_1_7\memory":
            # If default D:\ drive is not mounted, default to clean user-home or workspace memory
            if _sys.platform != "win32" or not _os.path.exists("D:\\"):
                primary_dir = Path.home() / ".iva" / "memory"

        self.primary_dir = Path(primary_dir)
        default_fb = Path(__file__).resolve().parents[3] / "state_fallback" / "memory"
        resolved_fb = fallback_dir if fallback_dir is not None else mirror_dir
        self.fallback_dir = Path(resolved_fb) if resolved_fb is not None else default_fb
        self.session_id = session_id or f"SESSION-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        self.using_fallback = False
        self._lock = threading.RLock()

        raw_prim = str(primary_dir)
        unmounted_drive = (
            len(raw_prim) >= 2
            and raw_prim[1] == ":"
            and (_sys.platform != "win32" or not _os.path.exists(raw_prim[:2] + "\\"))
        )

        if force_fallback or unmounted_drive:
            self.active_dir = self.fallback_dir
            self.using_fallback = True
            self.active_dir.mkdir(parents=True, exist_ok=True)
        else:
            try:
                self.primary_dir.mkdir(parents=True, exist_ok=True)
                probe = self.primary_dir / ".write_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                self.active_dir = self.primary_dir
            except Exception:
                self.active_dir = self.fallback_dir
                self.using_fallback = True
                self.active_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.active_dir / "omega_memory.db"
        self.audit_jsonl_path = self.active_dir / "memory_retrieval_audit.jsonl"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.executescript(
                        """
                        CREATE TABLE IF NOT EXISTS memory_entries (
                            entry_id TEXT PRIMARY KEY,
                            layer INTEGER NOT NULL,
                            layer_name TEXT NOT NULL,
                            subject_key TEXT NOT NULL,
                            content TEXT NOT NULL,
                            structured_json TEXT NOT NULL DEFAULT '{}',
                            tags_json TEXT NOT NULL DEFAULT '[]',
                            source_task_id TEXT,
                            session_id TEXT NOT NULL,
                            confidence REAL NOT NULL DEFAULT 1.0,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL,
                            expires_at REAL,
                            access_count INTEGER NOT NULL DEFAULT 0,
                            useful_count INTEGER NOT NULL DEFAULT 0,
                            supersedes_id TEXT,
                            superseded_by_id TEXT,
                            is_active INTEGER NOT NULL DEFAULT 1,
                            category TEXT DEFAULT 'SEMANTIC',
                            provenance TEXT DEFAULT 'OBSERVED_FACT'
                        );
                        CREATE INDEX IF NOT EXISTS idx_mem_layer_active ON memory_entries(layer, is_active);
                        CREATE INDEX IF NOT EXISTS idx_mem_subject ON memory_entries(subject_key, is_active);

                        CREATE TABLE IF NOT EXISTS retrieval_audit (
                            retrieval_id TEXT PRIMARY KEY,
                            session_id TEXT NOT NULL,
                            task_id TEXT,
                            query_text TEXT NOT NULL,
                            retrieved_entry_ids_json TEXT NOT NULL,
                            retrieved_count INTEGER NOT NULL,
                            timestamp REAL NOT NULL
                        );
                        """
                    )
                    cols = [r["name"] for r in conn.execute("PRAGMA table_info(memory_entries);").fetchall()]
                    if "category" not in cols:
                        conn.execute("ALTER TABLE memory_entries ADD COLUMN category TEXT DEFAULT 'SEMANTIC';")
                    if "provenance" not in cols:
                        conn.execute("ALTER TABLE memory_entries ADD COLUMN provenance TEXT DEFAULT 'OBSERVED_FACT';")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_category ON memory_entries(category, is_active);")
            finally:
                conn.close()

    def store(
        self,
        *,
        layer: int,
        subject_key: str,
        content: str,
        structured_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        source_task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        confidence: float = 1.0,
        ttl_seconds: Optional[float] = None,
        supersede_existing_subject: bool = True,
        entry_id: Optional[str] = None,
        category: Optional[str] = None,
        provenance: Optional[str] = None,
    ) -> MemoryEntry:
        if layer not in MEMORY_LAYERS:
            raise ValueError(f"Invalid memory layer {layer}. Valid layers: 1..10")
        if layer == 10:
            # Layer 10 is append-only immutable audit ledger: never supersede existing records
            supersede_existing_subject = False
        # Secrets Hygiene Guard: Never persist passwords, OTPs, or session tokens in persistent memory
        combined_text = f"{subject_key} {content} {json.dumps(structured_data or {})} {json.dumps(tags or [])}".lower()
        for sensitive_pat in ("password=", "passwd=", "otp=", "totp=", "auth_token=", "bearer ey", "client_secret="):
            if sensitive_pat in combined_text:
                raise PermissionError(
                    f"SECRETS_HYGIENE_VIOLATION: Attempted to persist raw credential pattern '{sensitive_pat}' in memory database."
                )

        now = time.time()
        eid = entry_id or f"MEM-L{layer}-{int(now * 1000)}-{uuid.uuid4().hex[:6]}"
        expires_at = (now + ttl_seconds) if ttl_seconds else None
        layer_name = MEMORY_LAYERS[layer]
        s_data = structured_data or {}
        tag_list = tags or []
        supersedes_id: Optional[str] = None
        sess = session_id or self.session_id

        layer_cat_map = {
            1: "PROJECT",
            2: "PROJECT",
            3: "PROJECT",
            4: "EPISODIC",
            5: "SEMANTIC",
            6: "PROCEDURAL",
            7: "REFLECTION",
            8: "PROJECT",
            9: "SEMANTIC",
            10: "AFFECTIVE_HISTORY",
        }
        entry_cat = category or layer_cat_map.get(layer, "SEMANTIC")
        entry_prov = provenance or "OBSERVED_FACT"

        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    if supersede_existing_subject:
                        prev = conn.execute(
                            """
                            SELECT entry_id FROM memory_entries
                            WHERE layer = ? AND subject_key = ? AND is_active = 1
                            ORDER BY created_at DESC LIMIT 1
                            """,
                            (layer, subject_key),
                        ).fetchone()
                        if prev:
                            supersedes_id = str(prev["entry_id"])
                            conn.execute(
                                """
                                UPDATE memory_entries
                                SET is_active = 0, superseded_by_id = ?, updated_at = ?
                                WHERE entry_id = ?
                                """,
                                (eid, now, supersedes_id),
                            )

                    conn.execute(
                        """
                        INSERT INTO memory_entries (
                            entry_id, layer, layer_name, subject_key, content,
                            structured_json, tags_json, source_task_id, session_id,
                            confidence, created_at, updated_at, expires_at,
                            access_count, useful_count, supersedes_id, superseded_by_id, is_active,
                            category, provenance
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, NULL, 1, ?, ?)
                        """,
                        (
                            eid,
                            layer,
                            layer_name,
                            subject_key,
                            content,
                            json.dumps(s_data, ensure_ascii=False),
                            json.dumps(tag_list, ensure_ascii=False),
                            source_task_id,
                            sess,
                            confidence,
                            now,
                            now,
                            expires_at,
                            supersedes_id,
                            entry_cat,
                            entry_prov,
                        ),
                    )
            finally:
                conn.close()

        return MemoryEntry(
            entry_id=eid,
            layer=layer,
            layer_name=layer_name,
            subject_key=subject_key,
            content=content,
            structured_data=s_data,
            tags=tag_list,
            source_task_id=source_task_id,
            session_id=sess,
            confidence=confidence,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
            supersedes_id=supersedes_id,
            is_active=True,
            category=entry_cat,
            provenance=entry_prov,
        )

    def retrieve(
        self,
        *,
        query: str = "",
        layers: Optional[Sequence[int]] = None,
        subject_key: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        active_only: bool = True,
        limit: int = 15,
        max_results: Optional[int] = None,
        task_id: Optional[str] = None,
        category: Optional[str] = None,
        provenance: Optional[str] = None,
    ) -> List[MemoryEntry]:
        if max_results is not None:
            limit = max_results
        now = time.time()
        sql = "SELECT * FROM memory_entries WHERE (expires_at IS NULL OR expires_at > ?)"
        params: List[Any] = [now]

        if active_only:
            sql += " AND is_active = 1"
        if layers:
            placeholders = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({placeholders})"
            params.extend(layers)
        if subject_key:
            sql += " AND subject_key = ?"
            params.append(subject_key)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if provenance:
            sql += " AND provenance = ?"
            params.append(provenance)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, tuple(params)).fetchall()
                entries = [self._row_to_entry(r) for r in rows]

                # Score by relevance, recency, confidence, and usefulness
                q_tokens = {tok.lower() for tok in re.findall(r"\w+", query) if len(tok) >= 2}
                req_tags = {t.lower() for t in (tags or [])}

                scored: List[tuple[float, MemoryEntry]] = []
                for e in entries:
                    if req_tags:
                        entry_tags = {t.lower() for t in e.tags}
                        if not (req_tags & entry_tags) and not q_tokens:
                            continue

                    score = e.confidence * 2.0 + min(3.0, e.useful_count * 0.5)
                    # Recency boost
                    age_hours = max(0.0, (now - e.updated_at) / 3600.0)
                    score += 1.5 / (1.0 + age_hours * 0.1)

                    if q_tokens:
                        haystack = f"{e.subject_key} {e.content} {' '.join(e.tags)}".lower()
                        matches = sum(1 for tok in q_tokens if tok in haystack)
                        if matches == 0 and not subject_key and not req_tags:
                            continue
                        score += matches * 3.0

                    if req_tags:
                        entry_tags = {t.lower() for t in e.tags}
                        score += len(req_tags & entry_tags) * 4.0

                    scored.append((score, e))

                scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
                selected = [item[1] for item in scored[:limit]]

                if selected:
                    with conn:
                        for e in selected:
                            conn.execute(
                                "UPDATE memory_entries SET access_count = access_count + 1 WHERE entry_id = ?",
                                (e.entry_id,),
                            )
                            e.access_count += 1
                        retrieval_id = f"RET-{int(now * 1000)}-{uuid.uuid4().hex[:6]}"
                        conn.execute(
                            """
                            INSERT INTO retrieval_audit (
                                retrieval_id, session_id, task_id, query_text,
                                retrieved_entry_ids_json, retrieved_count, timestamp
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                retrieval_id,
                                self.session_id,
                                task_id,
                                query or (subject_key or "*"),
                                json.dumps([e.entry_id for e in selected]),
                                len(selected),
                                now,
                            ),
                        )
                    self._append_audit_jsonl(
                        {
                            "retrieval_id": retrieval_id,
                            "session_id": self.session_id,
                            "task_id": task_id,
                            "query": query or (subject_key or "*"),
                            "retrieved_entry_ids": [e.entry_id for e in selected],
                            "retrieved_count": len(selected),
                            "timestamp": now,
                        }
                    )
                return selected
            finally:
                conn.close()

    def retrieve_before_planning(
        self,
        task_id: str,
        task_description: str = "",
        *,
        query: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Mandatory pre-planning memory lookup across semantic, procedural, failure, and episodic layers."""
        task_description = task_description or (query or "")
        semantic_facts = self.retrieve(
            query=task_description,
            layers=[5],
            tags=tags,
            active_only=True,
            limit=8,
            task_id=task_id,
        )
        procedural_recipes = self.retrieve(
            query=task_description,
            layers=[6],
            tags=tags,
            active_only=True,
            limit=5,
            task_id=task_id,
        )
        failure_playbooks = self.retrieve(
            query=task_description,
            layers=[7],
            tags=tags,
            active_only=True,
            limit=5,
            task_id=task_id,
        )
        episodic_traces = self.retrieve(
            query=task_description,
            layers=[4, 8, 9],
            tags=tags,
            active_only=True,
            limit=5,
            task_id=task_id,
        )

        # Even if specific keyword matches are empty, fetch top active preferences/constraints from Layer 5
        if not semantic_facts:
            semantic_facts = self.retrieve(
                query="",
                layers=[5],
                active_only=True,
                limit=5,
                task_id=task_id,
            )
        if not failure_playbooks:
            failure_playbooks = self.retrieve(
                query="",
                layers=[7],
                active_only=True,
                limit=3,
                task_id=task_id,
            )

        all_ids = [
            e.entry_id
            for group in (semantic_facts, procedural_recipes, failure_playbooks, episodic_traces)
            for e in group
        ]
        now = time.time()
        audit_id = f"PREPLAN-RET-{task_id}-{int(now * 1000)}"
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO retrieval_audit (
                            retrieval_id, session_id, task_id, query_text,
                            retrieved_entry_ids_json, retrieved_count, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            audit_id,
                            self.session_id,
                            task_id,
                            f"PREPLAN:{task_description[:200]}",
                            json.dumps(all_ids),
                            len(all_ids),
                            now,
                        ),
                    )
            finally:
                conn.close()

        self._append_audit_jsonl(
            {
                "retrieval_id": audit_id,
                "event": "PRE_PLANNING_MEMORY_RETRIEVAL",
                "session_id": self.session_id,
                "task_id": task_id,
                "retrieved_entry_ids": all_ids,
                "retrieved_count": len(all_ids),
                "timestamp": now,
            }
        )

        payload = {
            "audit_id": audit_id,
            "task_id": task_id,
            "session_id": self.session_id,
            "using_fallback_storage": self.using_fallback,
            "retrieved_entry_ids": all_ids,
            "semantic_facts": [asdict(e) for e in semantic_facts],
            "procedural_recipes": [asdict(e) for e in procedural_recipes],
            "failure_playbooks": [asdict(e) for e in failure_playbooks],
            "episodic_traces": [asdict(e) for e in episodic_traces],
        }
        payload["compact_guardrails_prompt_block"] = self.build_compact_memory_prompt_block(payload)
        return payload

    def record_failure_lesson(
        self,
        *,
        subject_key: Optional[str] = None,
        module_name: Optional[str] = None,
        error_signature: Optional[str] = None,
        failing_assertion: Optional[str] = None,
        root_cause: str = "",
        minimal_fix_rule: Optional[str] = None,
        minimal_patch_rule: Optional[str] = None,
        source_task_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Records a structured failure-to-repair lesson in Layer 7 (`FAILURE_PATTERNS_AND_PLAYBOOKS`)."""
        subj = (subject_key or module_name or "general").strip()
        err = (error_signature or failing_assertion or "VerificationFailure").strip()
        rule = (minimal_fix_rule or minimal_patch_rule or "").strip()
        src_task = source_task_id or task_id
        sig_short = err.splitlines()[-1][:140] if err else "VerificationFailure"
        content = f"[GUARDRAIL {subj}] Error: {sig_short} | RootCause: {root_cause[:140]} | FixRule: {rule[:160]}"
        entry = self.store(
            layer=7,
            subject_key=f"lesson:{subj}",
            content=content,
            structured_data={
                "subject_key": subj,
                "error_signature": sig_short,
                "root_cause": root_cause[:240],
                "minimal_fix_rule": rule[:240],
            },
            tags=["failure_lesson", "self_improvement", subj],
            source_task_id=src_task,
            supersede_existing_subject=True,
        )
        return {
            "stored": True,
            "entry_id": entry.entry_id,
            "layer": entry.layer_name,
            "subject_key": entry.subject_key,
            "content": content,
            "entry": asdict(entry),
        }

    def record_success_pattern(
        self,
        *,
        pattern_name: str,
        domain: str = "software_engineering",
        implementation_recipe: str = "",
        test_evidence: str = "",
        constraints: Optional[List[str]] = None,
        source_task_id: Optional[str] = None,
        confidence: float = 1.0,
    ) -> Dict[str, Any]:
        """Records a verified successful implementation pattern in Layer 6 (`PROCEDURAL_WORKFLOW_RECIPES`).
        
        Preserves test evidence, constraints, and circumstances in which the pattern is appropriate.
        """
        subj = f"recipe:{domain}:{pattern_name}".strip().lower()
        content = (
            f"[VERIFIED PATTERN {pattern_name}] Domain: {domain} | "
            f"Recipe: {implementation_recipe[:200]} | Evidence: {test_evidence[:140]}"
        )
        entry = self.store(
            layer=6,
            subject_key=subj,
            content=content,
            structured_data={
                "pattern_name": pattern_name,
                "domain": domain,
                "implementation_recipe": implementation_recipe,
                "test_evidence": test_evidence,
                "constraints": constraints or [],
                "verified_at": time.time(),
            },
            tags=["success_pattern", "verified_recipe", domain],
            source_task_id=source_task_id,
            confidence=confidence,
            supersede_existing_subject=True,
        )
        return {
            "stored": True,
            "entry_id": entry.entry_id,
            "layer": entry.layer_name,
            "subject_key": entry.subject_key,
            "content": content,
            "entry": asdict(entry),
        }

    def get_success_patterns(self, domain: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves verified procedural success patterns from Layer 6."""
        query = domain or ""
        entries = self.retrieve(query=query, layers=[6], active_only=True, limit=limit)
        return [asdict(e) for e in entries]

    def get_failure_lessons(self, subject_key: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves structured failure lessons and playbooks from Layer 7."""
        query = subject_key or ""
        entries = self.retrieve(query=query, layers=[7], active_only=True, limit=limit)
        return [asdict(e) for e in entries]

    def build_compact_memory_prompt_block(
        self,
        retrieval_result: Dict[str, Any] | str,
        max_chars: int = 480,
    ) -> str:
        """Builds a <=120-token guardrail block from retrieved Layer 7 failure lessons and Layer 5 facts."""
        if isinstance(retrieval_result, str):
            playbooks = [asdict(e) for e in self.retrieve(query=retrieval_result, layers=[7], limit=3)]
            facts = [asdict(e) for e in self.retrieve(query=retrieval_result, layers=[5], limit=2)]
        else:
            playbooks = retrieval_result.get("failure_playbooks", [])[:3]
            facts = retrieval_result.get("semantic_facts", [])[:2]
        bullets: List[str] = []
        for fb in playbooks:
            c = str(fb.get("content", "")).strip()
            if c:
                bullets.append(f"- LESSON: {c[:165]}")
        for sf in facts:
            c = str(sf.get("content", "")).strip()
            if c:
                bullets.append(f"- FACT: {c[:120]}")
        if not bullets:
            return ""
        joined = "\n".join(bullets)
        header = "LEARNED MEMORY GUARDRAILS (Avoid Repeating Past Failures):\n"
        full = header + joined
        if len(full) > max_chars:
            full = full[: max_chars - 3] + "..."
        return full

    def get_fact_history(self, subject_key: str, layer: int = 5) -> List[MemoryEntry]:
        """Returns the complete chronological supersession chain for a subject_key."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM memory_entries
                    WHERE layer = ? AND subject_key = ?
                    ORDER BY created_at ASC
                    """,
                    (layer, subject_key),
                ).fetchall()
                return [self._row_to_entry(r) for r in rows]
            finally:
                conn.close()

    def mark_useful(self, entry_id: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(
                        "UPDATE memory_entries SET useful_count = useful_count + 1 WHERE entry_id = ?",
                        (entry_id,),
                    )
            finally:
                conn.close()

    def store_compressed_episode(
        self,
        *,
        subject_key: str,
        raw_observation: str,
        source_task_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        max_chars: int = 600,
    ) -> MemoryEntry:
        compressed = ACONCompressor.compress_observation(raw_observation, max_chars=max_chars)
        return self.store(
            layer=4,
            subject_key=subject_key,
            content=compressed["compressed_text"],
            structured_data=compressed,
            tags=tags or ["episodic", "acon"],
            source_task_id=source_task_id,
            supersede_existing_subject=False,
        )

    def get_retrieval_audits(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                if task_id:
                    rows = conn.execute(
                        "SELECT * FROM retrieval_audit WHERE task_id = ? ORDER BY timestamp ASC",
                        (task_id,),
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM retrieval_audit ORDER BY timestamp ASC").fetchall()
                return [
                    {
                        "retrieval_id": r["retrieval_id"],
                        "session_id": r["session_id"],
                        "task_id": r["task_id"],
                        "query_text": r["query_text"],
                        "retrieved_entry_ids": json.loads(r["retrieved_entry_ids_json"] or "[]"),
                        "retrieved_count": r["retrieved_count"],
                        "timestamp": r["timestamp"],
                    }
                    for r in rows
                ]
            finally:
                conn.close()

    def _append_audit_jsonl(self, record: Dict[str, Any]) -> None:
        try:
            with open(self.audit_jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _parse_ts(val: Any) -> Optional[float]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                try:
                    import datetime
                    return datetime.datetime.fromisoformat(val).timestamp()
                except Exception:
                    return time.time()
        return time.time()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
        created_val = OmegaCommandMemory._parse_ts(row["created_at"]) or time.time()
        updated_val = OmegaCommandMemory._parse_ts(row["updated_at"]) or time.time()
        expires_val = OmegaCommandMemory._parse_ts(row["expires_at"]) if row["expires_at"] is not None else None
        keys = row.keys() if hasattr(row, "keys") else []
        cat_val = str(row["category"]) if "category" in keys and row["category"] else "SEMANTIC"
        prov_val = str(row["provenance"]) if "provenance" in keys and row["provenance"] else "OBSERVED_FACT"

        return MemoryEntry(
            entry_id=str(row["entry_id"]),
            layer=int(row["layer"]),
            layer_name=str(row["layer_name"]),
            subject_key=str(row["subject_key"]),
            content=str(row["content"]),
            structured_data=json.loads(row["structured_json"] or "{}"),
            tags=json.loads(row["tags_json"] or "[]"),
            source_task_id=row["source_task_id"],
            session_id=str(row["session_id"]),
            confidence=float(row["confidence"]),
            created_at=created_val,
            updated_at=updated_val,
            expires_at=expires_val,
            access_count=int(row["access_count"]),
            useful_count=int(row["useful_count"]),
            supersedes_id=row["supersedes_id"],
            superseded_by_id=row["superseded_by_id"],
            is_active=bool(row["is_active"]),
            category=cat_val,
            provenance=prov_val,
        )

    def store_categorized(
        self,
        category: MemoryCategory | str,
        subject_key: str,
        content: str,
        provenance: str = "OBSERVED_FACT",
        confidence: float = 1.0,
        structured_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        source_task_id: Optional[str] = None,
    ) -> MemoryEntry:
        """Stores a memory entry mapped to one of the 7 official memory categories."""
        cat_str = category.value if isinstance(category, MemoryCategory) else str(category)
        cat_to_layer = {
            "IDENTITY": 5,
            "EPISODIC": 4,
            "SEMANTIC": 5,
            "PROCEDURAL": 6,
            "PROJECT": 2,
            "REFLECTION": 7,
            "AFFECTIVE_HISTORY": 10,
        }
        layer = cat_to_layer.get(cat_str, 5)
        tag_list = list(tags or [])
        if cat_str.lower() not in [t.lower() for t in tag_list]:
            tag_list.append(cat_str.lower())

        return self.store(
            layer=layer,
            subject_key=subject_key,
            content=content,
            structured_data=structured_data or {},
            tags=tag_list,
            source_task_id=source_task_id,
            confidence=confidence,
            category=cat_str,
            provenance=provenance,
            supersede_existing_subject=(layer != 10),
        )

    def retrieve_by_category(
        self,
        category: MemoryCategory | str,
        query: str = "",
        limit: int = 10,
    ) -> List[MemoryEntry]:
        """Retrieves active memory entries under an explicit category."""
        cat_str = category.value if isinstance(category, MemoryCategory) else str(category)
        return self.retrieve(query=query, category=cat_str, active_only=True, limit=limit)

    def correct_memory(
        self,
        entry_id: str,
        corrected_content: str,
        reason: str,
        corrected_structured_data: Optional[Dict[str, Any]] = None,
        new_confidence: float = 1.0,
    ) -> MemoryEntry:
        """Explicitly corrects a previous memory belief, creating an audited supersession chain."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM memory_entries WHERE entry_id = ? AND is_active = 1",
                    (entry_id,),
                ).fetchone()
                if not row:
                    raise KeyError(f"Active memory entry '{entry_id}' not found for correction.")
                old_entry = self._row_to_entry(row)
            finally:
                conn.close()

        updated_data = dict(corrected_structured_data or old_entry.structured_data)
        updated_data["correction_reason"] = reason
        updated_data["corrected_from_id"] = entry_id

        # Store superseding memory with new content
        return self.store(
            layer=old_entry.layer,
            subject_key=old_entry.subject_key,
            content=corrected_content,
            structured_data=updated_data,
            tags=list(set(old_entry.tags + ["corrected", "self_correction"])),
            source_task_id=old_entry.source_task_id,
            confidence=new_confidence,
            category=old_entry.category,
            provenance=old_entry.provenance,
            supersede_existing_subject=True,
        )

    def forget_memory(self, entry_id: str, reason: str) -> bool:
        """Explicitly soft-deletes a memory entry with justification audit. Layer 10 is immutable."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT layer, structured_json FROM memory_entries WHERE entry_id = ?",
                    (entry_id,),
                ).fetchone()
                if not row:
                    return False
                if int(row["layer"]) == 10:
                    raise PermissionError("Layer 10 (IMMUTABLE_AUDIT) entries cannot be forgotten.")

                s_data = json.loads(row["structured_json"] or "{}")
                s_data["forgotten_reason"] = reason
                s_data["forgotten_at"] = time.time()

                with conn:
                    conn.execute(
                        "UPDATE memory_entries SET is_active = 0, structured_json = ?, updated_at = ? WHERE entry_id = ?",
                        (json.dumps(s_data), time.time(), entry_id),
                    )
                return True
            finally:
                conn.close()

    def forget_by_subject(self, subject_key: str, reason: str, layer: Optional[int] = None) -> int:
        """Forgets all active memories for a specific subject_key (except Layer 10)."""
        with self._lock:
            conn = self._connect()
            try:
                sql = "SELECT entry_id, layer FROM memory_entries WHERE subject_key = ? AND is_active = 1"
                params: List[Any] = [subject_key]
                if layer is not None:
                    sql += " AND layer = ?"
                    params.append(layer)
                rows = conn.execute(sql, tuple(params)).fetchall()

                count = 0
                now = time.time()
                with conn:
                    for r in rows:
                        if int(r["layer"]) == 10:
                            continue
                        conn.execute(
                            "UPDATE memory_entries SET is_active = 0, updated_at = ? WHERE entry_id = ?",
                            (now, str(r["entry_id"])),
                        )
                        count += 1
                return count
            finally:
                conn.close()

    def detect_contradictions(
        self,
        subject_key: str,
        candidate_content: str,
        layer: int = 5,
    ) -> List[Dict[str, Any]]:
        """Detects polarity and value contradictions between candidate content and active memories."""
        active = self.retrieve(subject_key=subject_key, layers=[layer], active_only=True, limit=5)
        contradictions = []

        cand_lower = candidate_content.lower()
        # Opposing polarity token pairs
        polarity_pairs = [
            ("enabled", "disabled"),
            ("true", "false"),
            ("locked", "unlocked"),
            ("permitted", "forbidden"),
            ("pass", "fail"),
            ("allowed", "blocked"),
        ]

        for e in active:
            prev_lower = e.content.lower()
            for pos, neg in polarity_pairs:
                if (pos in cand_lower and neg in prev_lower) or (neg in cand_lower and pos in prev_lower):
                    contradictions.append({
                        "existing_entry_id": e.entry_id,
                        "subject_key": e.subject_key,
                        "existing_content": e.content,
                        "candidate_content": candidate_content,
                        "conflicting_polarity": f"{pos} vs {neg}",
                    })
                    break
        return contradictions

    def load_session_continuity(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Hydrates clean session continuity context across restarts."""
        identity_entries = self.retrieve_by_category("IDENTITY", limit=5)
        project_entries = self.retrieve_by_category("PROJECT", limit=5)
        reflection_lessons = self.retrieve_by_category("REFLECTION", limit=5)
        recent_episodes = self.retrieve_by_category("EPISODIC", limit=3)

        return {
            "session_id": session_id or self.session_id,
            "using_fallback": self.using_fallback,
            "identity_anchors": [asdict(e) for e in identity_entries],
            "active_project_state": [asdict(e) for e in project_entries],
            "recent_reflections": [asdict(e) for e in reflection_lessons],
            "recent_episodes": [asdict(e) for e in recent_episodes],
            "timestamp": time.time(),
        }

    # =========================================================================
    # Phase 8: Four-Tier 10M-Token Knowledge Corpus & RULER Needle Retrieval
    # =========================================================================

    def get_corpus_profile(self) -> KnowledgeCorpusProfile:
        """Returns the truthful capacity profile distinguishing 10M persistent storage from model active window."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as count, SUM(LENGTH(content)) as total_chars FROM memory_entries WHERE is_active = 1"
                ).fetchone()
                total_chars = int(row["total_chars"] or 0)
                entry_count = int(row["count"] or 0)
                # Heuristic estimation: 1 token ~= 4 characters in English / code
                est_tokens = total_chars // 4
            finally:
                conn.close()

        return KnowledgeCorpusProfile(
            model_name="gemini-2.5-pro / claude-3-7-sonnet",
            provider="google / anthropic",
            documented_context_window=1_000_000,
            practical_input_budget=32_000,
            practical_output_budget=4_096,
            persistent_corpus_token_capacity=10_000_000,
            current_stored_tokens=est_tokens,
            current_stored_chars=total_chars,
            active_entries_count=entry_count,
        )

    def store_layer_a_immutable_source(
        self,
        source_id: str,
        source_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """Layer A: Immutable source records (original news, raw quotes, circulars, filings)."""
        return self.store(
            layer=10,  # IMMUTABLE_AUDIT_AND_BENCHMARK_LEDGER
            subject_key=f"SOURCE-{source_type.upper()}-{source_id}",
            content=content,
            structured_data=metadata or {},
            tags=["layer_a", "immutable_source", source_type.lower()],
            confidence=1.0,
            supersede_existing_subject=False,
        )

    def store_layer_b_domain_record(
        self,
        domain_table: str,
        record_id: str,
        content: str,
        structured_data: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """Layer B: Structured domain storage (market observations, forecasts, candidate orders)."""
        return self.store(
            layer=5,  # CROSS_SESSION_SEMANTIC_FACTS
            subject_key=f"DOMAIN-{domain_table.upper()}-{record_id}",
            content=content,
            structured_data=structured_data or {},
            tags=["layer_b", "domain_storage", domain_table.lower()],
            confidence=1.0,
            supersede_existing_subject=True,
        )

    def store_layer_c_episodic_summary(
        self,
        session_id: str,
        decision_summary: str,
        root_causes: Optional[List[str]] = None,
        key_lessons: Optional[List[str]] = None,
    ) -> MemoryEntry:
        """Layer C: Episodic and semantic memory (post-mortems, session summaries, regime patterns)."""
        data = {
            "session_id": session_id,
            "root_causes": root_causes or [],
            "key_lessons": key_lessons or [],
            "timestamp": time.time(),
        }
        return self.store(
            layer=4,  # COMPRESSED_EPISODIC_TRACE
            subject_key=f"EPISODE-{session_id}",
            content=decision_summary,
            structured_data=data,
            tags=["layer_c", "episodic_memory", "session_post_mortem"],
            confidence=1.0,
            supersede_existing_subject=True,
        )

    def build_layer_d_active_context(
        self,
        task_id: str,
        query_text: str,
        max_tokens: int = 8000,
    ) -> Dict[str, Any]:
        """Layer D: Active working context assembled via deterministic + semantic search within strict token budget."""
        profile = self.get_corpus_profile()
        capped_budget = min(max_tokens, profile.practical_input_budget)

        # 1. Mandatory pre-planning retrieval
        retrieved_entries = self.retrieve(query=query_text, max_results=15, task_id=task_id)

        # 2. Pack entries within capped token budget (4 chars/token)
        char_budget = capped_budget * 4
        current_chars = 0
        packed_passages: List[Dict[str, Any]] = []

        for entry in retrieved_entries:
            entry_chars = len(entry.content)
            if current_chars + entry_chars <= char_budget:
                packed_passages.append({
                    "entry_id": entry.entry_id,
                    "layer": entry.layer_name,
                    "subject": entry.subject_key,
                    "content": entry.content,
                    "confidence": entry.confidence,
                    "created_at": entry.created_at,
                })
                current_chars += entry_chars
            else:
                # Truncate final passage if space permits
                remaining = char_budget - current_chars
                if remaining > 100:
                    packed_passages.append({
                        "entry_id": entry.entry_id,
                        "layer": entry.layer_name,
                        "subject": entry.subject_key,
                        "content": entry.content[:remaining] + " ... [TRUNCATED_AT_BUDGET]",
                        "confidence": entry.confidence,
                        "created_at": entry.created_at,
                    })
                    current_chars += remaining
                break

        return {
            "task_id": task_id,
            "query_text": query_text,
            "active_passages": packed_passages,
            "passages_count": len(packed_passages),
            "estimated_tokens_used": current_chars // 4,
            "budget_limit_tokens": capped_budget,
            "corpus_profile": asdict(profile),
        }

    def run_ruler_needle_evaluation(
        self,
        needles: List[Tuple[str, str]],  # (subject_key, needle_value)
        distractor_count: int = 50,
    ) -> Dict[str, Any]:
        """RULER-inspired Needle-in-a-Haystack evaluation testing retrieval across corpus positions."""
        start_time = time.time()
        # 1. Ingest distractors to build a haystack
        for i in range(distractor_count):
            self.store(
                layer=5,
                subject_key=f"HAYSTACK-DISTRACTOR-{i:04d}",
                content=f"Market observation record {i}: NIFTY index fluctuations within range, volume normal.",
                tags=["haystack", "distractor"],
                confidence=0.9,
                supersede_existing_subject=True,
            )

        # 2. Ingest needles at distinct positions
        needle_keys = []
        for key, val in needles:
            self.store(
                layer=5,
                subject_key=key,
                content=val,
                tags=["ruler_needle"],
                confidence=1.0,
                supersede_existing_subject=True,
            )
            needle_keys.append(key)

        # 3. Retrieve each needle and verify exact recall
        retrieved_count = 0
        latencies_ms = []

        for key, val in needles:
            t0 = time.time()
            res = self.retrieve(query=key, max_results=3)
            elapsed = (time.time() - t0) * 1000.0
            latencies_ms.append(elapsed)
            # Check if needle text is present in retrieved results
            found = any(key == r.subject_key or val in r.content for r in res)
            if found:
                retrieved_count += 1

        total_needles = len(needles)
        recall = (retrieved_count / total_needles) if total_needles > 0 else 0.0
        avg_latency = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0

        return {
            "total_needles_tested": total_needles,
            "needles_retrieved": retrieved_count,
            "recall_score": round(recall, 4),
            "average_latency_ms": round(avg_latency, 2),
            "haystack_distractor_count": distractor_count,
            "elapsed_seconds": round(time.time() - start_time, 3),
            "is_flawless": (recall == 1.0),
        }

    def compact_session_context(
        self,
        session_id: str,
        max_chars: int = 1200,
        preserve_anchors: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Compacts working turn memory into Layer C episodic summary while preserving critical anchors."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT content FROM memory_entries WHERE session_id = ? AND layer IN (1, 2) AND is_active = 1",
                    (session_id,),
                ).fetchall()
                raw_texts = [r["content"] for r in rows]
            finally:
                conn.close()

        if not raw_texts:
            return {"status": "NOOP", "session_id": session_id, "message": "No active working entries to compact."}

        combined_text = "\n".join(raw_texts)
        comp_res = ACONCompressor.compress_observation(
            combined_text,
            max_chars=max_chars,
            preserve_identifiers=preserve_anchors,
        )

        # Store compacted result in Layer C
        episodic_entry = self.store_layer_c_episodic_summary(
            session_id=session_id,
            decision_summary=comp_res["compressed_text"],
            root_causes=[],
            key_lessons=[f"Compacted {len(raw_texts)} working turns with {comp_res['reduction_ratio']*100:.1f}% reduction."],
        )

        # Deactivate raw turns in layer 1 & 2
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(
                        "UPDATE memory_entries SET is_active = 0 WHERE session_id = ? AND layer IN (1, 2)",
                        (session_id,),
                    )
            finally:
                conn.close()

        return {
            "status": "COMPACTED",
            "session_id": session_id,
            "episodic_entry_id": episodic_entry.entry_id,
            "raw_characters": comp_res["raw_chars"],
            "compressed_characters": comp_res["compressed_chars"],
            "reduction_ratio": comp_res["reduction_ratio"],
            "preserved_anchors": comp_res["preserved_anchors"],
        }

    def store_categorized(
        self,
        category: Any,
        subject: Optional[str] = None,
        subject_key: Optional[str] = None,
        content: str = "",
        confidence: float = 1.0,
        source: Optional[str] = None,
        source_task_id: Optional[str] = None,
        provenance: str = "OBSERVED_FACT",
        structured_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        layer: Optional[int] = None,
    ) -> str:
        """Stores a memory entry mapped cleanly to one of the 7 cognitive memory categories."""
        cat_str = category.value if hasattr(category, "value") else str(category)
        subj = (subject or subject_key or "general").strip()
        cat_layer_map = {
            "IDENTITY": 1,
            "PROJECT": 2,
            "PROJECT_STATE": 2,
            "EPISODIC": 4,
            "SEMANTIC": 5,
            "PROCEDURAL": 6,
            "REFLECTION": 7,
            "REFLECTION_LESSON": 7,
            "LESSON_LEARNED": 7,
            "AFFECTIVE_HISTORY": 10,
        }
        chosen_layer = layer or cat_layer_map.get(cat_str, 5)
        entry = self.store(
            layer=chosen_layer,
            subject_key=subj,
            content=content,
            structured_data=structured_data or {},
            tags=tags or [cat_str.lower()],
            source_task_id=source or source_task_id,
            confidence=confidence,
            category=cat_str,
            provenance=provenance,
            supersede_existing_subject=False,
        )
        return entry.entry_id

    def retrieve_by_category(
        self,
        category: Any,
        include_superseded: bool = False,
        limit: int = 20,
    ) -> List[MemoryEntry]:
        """Retrieves active or all records filed under a specific cognitive category."""
        cat_str = category.value if hasattr(category, "value") else str(category)
        return self.retrieve(
            category=cat_str,
            active_only=not include_superseded,
            limit=limit,
        )

    def correct_memory(
        self,
        original_entry_id: str,
        corrected_content: str,
        justification: str = "",
        new_confidence: float = 1.0,
    ) -> Optional[str]:
        """Applies explicit fact correction, marking the old entry superseded with a forward pointer."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM memory_entries WHERE entry_id = ?", (original_entry_id,)).fetchone()
                if not row:
                    return None
                orig = self._row_to_entry(row)
            finally:
                conn.close()

        # Create corrected entry
        s_data = dict(orig.structured_data)
        s_data["superseded_entry_id"] = original_entry_id
        s_data["correction_justification"] = justification

        new_entry = self.store(
            layer=orig.layer,
            subject_key=orig.subject_key,
            content=corrected_content,
            structured_data=s_data,
            tags=orig.tags,
            source_task_id=orig.source_task_id,
            confidence=new_confidence,
            category=orig.category,
            provenance=orig.provenance,
            supersede_existing_subject=False,
        )

        # Mark original entry as superseded
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(
                        "UPDATE memory_entries SET is_active = 0, superseded_by_id = ? WHERE entry_id = ?",
                        (new_entry.entry_id, original_entry_id),
                    )
            finally:
                conn.close()

        return new_entry.entry_id

    def forget_memory(self, entry_id: str, reason: str = "") -> bool:
        """Soft-forgets an entry by deactivating it and preserving audit trace."""
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    res = conn.execute("UPDATE memory_entries SET is_active = 0 WHERE entry_id = ?", (entry_id,))
                    return res.rowcount > 0
            finally:
                conn.close()

    def forget_by_subject(self, subject_key: str, reason: str = "") -> int:
        """Soft-forgets all active entries under a subject key."""
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    res = conn.execute("UPDATE memory_entries SET is_active = 0 WHERE subject_key = ?", (subject_key,))
                    return res.rowcount
            finally:
                conn.close()

    def detect_contradictions(self, subject_key: str) -> List[Tuple[MemoryEntry, MemoryEntry]]:
        """Identifies conflicting active records filed under the same subject key."""
        entries = self.retrieve(subject_key=subject_key, active_only=True, limit=50)
        conflicts = []
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                e1, e2 = entries[i], entries[j]
                if e1.content.strip().lower() != e2.content.strip().lower():
                    conflicts.append((e1, e2))
        return conflicts

    def load_session_continuity(self, limit_per_category: int = 3) -> Dict[str, List[Dict[str, Any]]]:
        """Loads cross-session continuity state across key memory categories."""
        categories = [
            "IDENTITY",
            "PROJECT",
            "PROJECT_STATE",
            "EPISODIC",
            "SEMANTIC",
            "PROCEDURAL",
            "REFLECTION",
            "AFFECTIVE_HISTORY",
        ]
        result: Dict[str, List[Dict[str, Any]]] = {}
        for cat in categories:
            entries = self.retrieve(category=cat, active_only=True, limit=limit_per_category)
            if entries:
                result[cat] = [asdict(e) for e in entries]
        return result


@dataclass
class KnowledgeCorpusProfile:
    """Truthful memory profile distinguishing persistent 10M token storage from model active context."""
    model_name: str
    provider: str
    documented_context_window: int
    practical_input_budget: int
    practical_output_budget: int
    persistent_corpus_token_capacity: int
    current_stored_tokens: int
    current_stored_chars: int
    active_entries_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
