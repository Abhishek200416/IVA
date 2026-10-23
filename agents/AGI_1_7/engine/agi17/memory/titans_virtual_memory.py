"""Titans & MemGPT Neural Test-Time Virtual Memory Architecture.

Implements research-grounded autonomous memory management:
1. Titans (Behrouz et al., Google Research 2025 - arXiv:2501.00663):
   - Surprise-driven test-time memorization.
   - Calculates information novelty / prediction surprise to dynamically update test-time state.
2. MemGPT (Packer et al., UC Berkeley 2023 - arXiv:2310.08560):
   - Hierarchical OS-level virtual memory paging (Core Registers, Recall Memory, Archival Storage).
   - Interrupt-driven page-fault handling and context swapping.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MemoryPage:
    page_id: str
    tier: str  # "CORE", "RECALL", "ARCHIVAL"
    key: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    surprise_score: float = 0.0
    access_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TitansMemoryModule:
    """Surprise-guided test-time neural memory inspired by Google Research Titans."""

    def __init__(self, surprise_threshold: float = 0.45, decay_rate: float = 0.05) -> None:
        self.surprise_threshold = surprise_threshold
        self.decay_rate = decay_rate
        # Memory state vector simulation: key -> (importance_weight, surprise_history)
        self.memory_weights: Dict[str, float] = {}

    def compute_surprise(self, key: str, content: str, context_keys: List[str]) -> float:
        """Computes information novelty/surprise based on lexical/semantic overlap and historical weights."""
        if not key:
            return 0.0

        # Frequency / historical weight
        historical_weight = self.memory_weights.get(key, 0.0)

        # Content novelty: checks unexpected tokens like error signatures, new protocols, or anomalies
        novelty_score = 0.0
        unexpected_tokens = ["error", "exception", "failed", "critical", "unexpected", "divergence", "novel", "shift"]
        content_lower = content.lower()
        for tok in unexpected_tokens:
            if tok in content_lower:
                novelty_score += 0.35

        # Contextual distance: is the key already in active context keys?
        unseen_bonus = 0.15 if key not in context_keys else 0.0

        # Familiarity dampening
        familiarity_decay = 1.0 / (1.0 + historical_weight)

        raw_surprise = novelty_score + unseen_bonus * familiarity_decay
        surprise = min(1.0, max(0.0, raw_surprise))
        return surprise

    def update_at_test_time(self, key: str, surprise: float) -> bool:
        """Updates internal memory representation dynamically if surprise exceeds threshold."""
        prev = self.memory_weights.get(key, 0.0)
        # Apply decay to existing representation and integrate new gradient/surprise
        new_weight = prev * (1.0 - self.decay_rate) + surprise * 1.5
        self.memory_weights[key] = new_weight
        return surprise >= self.surprise_threshold


class MemGPTPagedMemoryEngine:
    """Hierarchical OS-level virtual memory manager for LLM agents."""

    def __init__(
        self,
        core_capacity: int = 8,
        recall_capacity: int = 32,
        titans_threshold: float = 0.45,
    ) -> None:
        self.core_capacity = core_capacity
        self.recall_capacity = recall_capacity
        self.titans = TitansMemoryModule(surprise_threshold=titans_threshold)

        # Memory tiers
        self.core_memory: Dict[str, MemoryPage] = {}
        self.recall_memory: Dict[str, MemoryPage] = {}
        self.archival_memory: Dict[str, MemoryPage] = {}

        # Telemetry
        self.page_faults: int = 0
        self.page_hits: int = 0
        self.evictions: int = 0

    def write(
        self,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        force_tier: Optional[str] = None,
    ) -> MemoryPage:
        """Ingests new observation or memory with Titans-evaluated surprise routing."""
        active_keys = list(self.core_memory.keys()) + list(self.recall_memory.keys())
        surprise = self.titans.compute_surprise(key, content, active_keys)
        self.titans.update_at_test_time(key, surprise)

        page_id = f"PAGE-{hashlib.sha256(f'{key}:{time.time()}'.encode()).hexdigest()[:10]}"
        tier = force_tier or ("CORE" if surprise >= self.titans.surprise_threshold else "RECALL")

        page = MemoryPage(
            page_id=page_id,
            tier=tier,
            key=key,
            content=content,
            metadata=metadata or {},
            surprise_score=surprise,
            access_count=1,
        )

        if tier == "CORE":
            self._insert_core(page)
        elif tier == "RECALL":
            self._insert_recall(page)
        else:
            self.archival_memory[key] = page

        return page

    def read(self, key: str) -> Optional[MemoryPage]:
        """Reads key with interrupt-driven virtual page fault resolution."""
        # 1. Check Core (Fast Register)
        if key in self.core_memory:
            page = self.core_memory[key]
            page.access_count += 1
            page.last_accessed_at = time.time()
            self.page_hits += 1
            return page

        # 2. Check Recall (Working Context)
        if key in self.recall_memory:
            page = self.recall_memory[key]
            page.access_count += 1
            page.last_accessed_at = time.time()
            self.page_hits += 1
            # Promote to Core if frequently accessed
            if page.access_count > 3 and len(self.core_memory) < self.core_capacity:
                self._promote_to_core(page)
            return page

        # 3. Page Fault -> Fetch from Archival Storage
        if key in self.archival_memory:
            self.page_faults += 1
            page = self.archival_memory[key]
            page.access_count += 1
            page.last_accessed_at = time.time()
            # Page into Recall
            self._insert_recall(page)
            return page

        return None

    def search_archival(self, query: str, limit: int = 5) -> List[MemoryPage]:
        """Searches deep archival memory by keyword or semantic tags."""
        q_lower = query.lower()
        results: List[Tuple[float, MemoryPage]] = []
        for page in self.archival_memory.values():
            score = 0.0
            if q_lower in page.key.lower():
                score += 2.0
            if q_lower in page.content.lower():
                score += 1.0
            if any(q_lower in str(v).lower() for v in page.metadata.values()):
                score += 1.5
            if score > 0.0:
                results.append((score, page))

        results.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in results[:limit]]

    def _insert_core(self, page: MemoryPage) -> None:
        if len(self.core_memory) >= self.core_capacity:
            # Evict least recently accessed page to Recall
            lru_key = min(self.core_memory.keys(), key=lambda k: self.core_memory[k].last_accessed_at)
            evicted = self.core_memory.pop(lru_key)
            evicted.tier = "RECALL"
            self.evictions += 1
            self._insert_recall(evicted)

        page.tier = "CORE"
        self.core_memory[page.key] = page

    def _insert_recall(self, page: MemoryPage) -> None:
        if len(self.recall_memory) >= self.recall_capacity:
            # Evict least recently accessed to Archival
            lru_key = min(self.recall_memory.keys(), key=lambda k: self.recall_memory[k].last_accessed_at)
            evicted = self.recall_memory.pop(lru_key)
            evicted.tier = "ARCHIVAL"
            self.archival_memory[lru_key] = evicted
            self.evictions += 1

        page.tier = "RECALL"
        self.recall_memory[page.key] = page

    def _promote_to_core(self, page: MemoryPage) -> None:
        if page.key in self.recall_memory:
            self.recall_memory.pop(page.key)
        self._insert_core(page)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "core_count": len(self.core_memory),
            "recall_count": len(self.recall_memory),
            "archival_count": len(self.archival_memory),
            "page_hits": self.page_hits,
            "page_faults": self.page_faults,
            "evictions": self.evictions,
            "hit_ratio": (
                round(self.page_hits / (self.page_hits + self.page_faults), 4)
                if (self.page_hits + self.page_faults) > 0
                else 1.0
            ),
        }
