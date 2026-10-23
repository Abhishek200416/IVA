"""HippoRAG: Neurobiologically Inspired Long-Term Memory Engine (Update 9).

Grounded in Gutierrez et al. (arXiv:2405.14831):
"HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models"
- Models the division of labor between neocortex (generalized knowledge) and hippocampus (indexing).
- Constructs an associative entity-relation knowledge graph over disparate operational passages.
- Executes Personalized PageRank (PPR) as a computational analog of hippocampal pattern completion.
- Enables single-step multi-hop associative retrieval across disjoint documents with zero iterative LLM overhead.
"""

from __future__ import annotations

import collections
import hashlib
import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("HippoRAGMemoryEngine")


@dataclass
class KnowledgeNode:
    node_id: str
    name: str
    node_type: str  # "ENTITY", "CONCEPT", "DOCUMENT"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeEdge:
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0


class HippoRAGMemoryEngine:
    """Associative memory engine powered by Personalized PageRank over an entity-relation graph."""

    def __init__(self, damping_factor: float = 0.85, max_iter: int = 40, tol: float = 1e-5) -> None:
        self.damping_factor = damping_factor
        self.max_iter = max_iter
        self.tol = tol

        self.nodes: Dict[str, KnowledgeNode] = {}
        self.adjacency: Dict[str, List[Tuple[str, float]]] = collections.defaultdict(list)
        self.doc_registry: Dict[str, Dict[str, Any]] = {}

    def add_document(self, doc_id: str, content: str, entities: List[str], metadata: Optional[Dict[str, Any]] = None) -> None:
        """Indexes a document and establishes bidirectional edges to its mentioned entities."""
        doc_node_id = f"DOC:{doc_id}"
        self.nodes[doc_node_id] = KnowledgeNode(
            node_id=doc_node_id,
            name=doc_id,
            node_type="DOCUMENT",
            metadata=metadata or {},
        )
        self.doc_registry[doc_id] = {
            "content": content,
            "entities": entities,
            "metadata": metadata or {},
        }

        # Index entities and create edges
        for ent in entities:
            ent_node_id = f"ENT:{ent.lower().strip()}"
            if ent_node_id not in self.nodes:
                self.nodes[ent_node_id] = KnowledgeNode(
                    node_id=ent_node_id,
                    name=ent.strip(),
                    node_type="ENTITY",
                )

            # Bidirectional connection between Document and Entity
            self.adjacency[doc_node_id].append((ent_node_id, 1.0))
            self.adjacency[ent_node_id].append((doc_node_id, 1.0))

    def add_relation(self, entity1: str, relation: str, entity2: str, weight: float = 1.0) -> None:
        """Adds an associative knowledge link between two entities."""
        ent1_id = f"ENT:{entity1.lower().strip()}"
        ent2_id = f"ENT:{entity2.lower().strip()}"

        if ent1_id not in self.nodes:
            self.nodes[ent1_id] = KnowledgeNode(node_id=ent1_id, name=entity1.strip(), node_type="ENTITY")
        if ent2_id not in self.nodes:
            self.nodes[ent2_id] = KnowledgeNode(node_id=ent2_id, name=entity2.strip(), node_type="ENTITY")

        self.adjacency[ent1_id].append((ent2_id, weight))
        self.adjacency[ent2_id].append((ent1_id, weight))

    def run_personalized_pagerank(self, seed_entities: List[str]) -> Dict[str, float]:
        """Runs power iteration Personalized PageRank restart-biased toward seed entities."""
        all_node_ids = list(self.nodes.keys())
        n = len(all_node_ids)
        if n == 0:
            return {}

        # Construct personalization preference vector p
        p: Dict[str, float] = {nid: 0.0 for nid in all_node_ids}
        matched_seeds = [f"ENT:{s.lower().strip()}" for s in seed_entities if f"ENT:{s.lower().strip()}" in self.nodes]

        if not matched_seeds:
            # Fallback to uniform distribution if no seeds matched
            uniform = 1.0 / n
            for nid in all_node_ids:
                p[nid] = uniform
        else:
            seed_weight = 1.0 / len(matched_seeds)
            for sid in matched_seeds:
                p[sid] = seed_weight

        # Initialize rank vector r
        r: Dict[str, float] = dict(p)

        # Precompute out-degree weights
        out_weights: Dict[str, float] = {}
        for u in all_node_ids:
            out_weights[u] = sum(w for _, w in self.adjacency[u])

        # Power iteration
        for _ in range(self.max_iter):
            r_next: Dict[str, float] = {nid: 0.0 for nid in all_node_ids}
            dangling_sum = 0.0

            for u in all_node_ids:
                total_w = out_weights[u]
                if total_w > 0:
                    flow = (self.damping_factor * r[u]) / total_w
                    for v, w in self.adjacency[u]:
                        r_next[v] += flow * w
                else:
                    dangling_sum += r[u]

            # Distribute teleport and dangling mass according to personalization vector p
            dangling_alloc = self.damping_factor * dangling_sum
            teleport_alloc = 1.0 - self.damping_factor
            for nid in all_node_ids:
                r_next[nid] += (dangling_alloc + teleport_alloc) * p[nid]

            # Check convergence L1 norm
            diff = sum(abs(r_next[nid] - r[nid]) for nid in all_node_ids)
            r = r_next
            if diff < self.tol:
                break

        return r

    def associative_query(self, query_entities: List[str], top_k: int = 5) -> List[Dict[str, Any]]:
        """Performs single-step multi-hop retrieval and returns top-ranked documents."""
        ranks = self.run_personalized_pagerank(query_entities)
        doc_scores: List[Tuple[float, str]] = []

        for nid, score in ranks.items():
            if nid.startswith("DOC:"):
                doc_id = nid[4:]
                doc_scores.append((score, doc_id))

        doc_scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, doc_id in doc_scores[:top_k]:
            doc_data = self.doc_registry.get(doc_id, {})
            results.append({
                "doc_id": doc_id,
                "ppr_score": round(score, 6),
                "content": doc_data.get("content", ""),
                "entities": doc_data.get("entities", []),
                "metadata": doc_data.get("metadata", {}),
            })
        return results
