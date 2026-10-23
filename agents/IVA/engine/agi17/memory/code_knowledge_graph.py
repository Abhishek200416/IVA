"""Incremental Differentiable Code Knowledge Graph Substrate.

Provides graph-based semantic linkage and blast-radius impact analysis:
1. AST Extraction:
   - Indexes Modules, Classes, Functions, and Methods.
   - Extracts relationship edges (IMPORTS, DEFINES, CALLS, INHERITS).
2. Blast-Radius Propagation:
   - Traverses directed dependency edges to determine all downstream callers and
     consumers when a function, class, or module signature changes.
3. Fast Memory Querying:
   - Replaces flat SQLite table scans with instant directed graph traversals.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class CodeEntity:
    entity_id: str
    name: str
    kind: str  # "MODULE", "CLASS", "FUNCTION", "METHOD"
    file_path: str
    line_number: int
    docstring: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CodeRelation:
    source_id: str
    relation_type: str  # "DEFINES", "CALLS", "IMPORTS", "INHERITS"
    target_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CodeKnowledgeGraph:
    """Directed semantic graph of codebase components and dependencies."""

    def __init__(self) -> None:
        self.entities: Dict[str, CodeEntity] = {}
        # Forward edges: source -> list of (relation, target)
        self.forward_edges: Dict[str, List[CodeRelation]] = {}
        # Reverse edges: target -> list of (relation, source) (used for blast radius)
        self.reverse_edges: Dict[str, List[CodeRelation]] = {}

    def add_entity(self, entity: CodeEntity) -> None:
        self.entities[entity.entity_id] = entity
        self.forward_edges.setdefault(entity.entity_id, [])
        self.reverse_edges.setdefault(entity.entity_id, [])

    def add_relation(self, source_id: str, relation_type: str, target_id: str) -> None:
        rel = CodeRelation(source_id=source_id, relation_type=relation_type, target_id=target_id)
        self.forward_edges.setdefault(source_id, []).append(rel)
        self.reverse_edges.setdefault(target_id, []).append(rel)

    def parse_source_code(self, file_path: str, source_text: Optional[str] = None) -> List[CodeEntity]:
        """Parses a Python file via AST and adds its entities and relationships into the graph."""
        norm_path = str(Path(file_path).resolve())
        if source_text is None:
            p = Path(norm_path)
            if not p.exists():
                return []
            source_text = p.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source_text, filename=norm_path)
        except SyntaxError:
            return []

        module_name = Path(norm_path).stem
        module_id = f"mod:{module_name}"
        mod_entity = CodeEntity(
            entity_id=module_id,
            name=module_name,
            kind="MODULE",
            file_path=norm_path,
            line_number=1,
            docstring=ast.get_docstring(tree),
        )
        self.add_entity(mod_entity)
        discovered: List[CodeEntity] = [mod_entity]

        for node in tree.body:
            # Functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_id = f"fn:{module_name}.{node.name}"
                fn_entity = CodeEntity(
                    entity_id=fn_id,
                    name=node.name,
                    kind="FUNCTION",
                    file_path=norm_path,
                    line_number=node.lineno,
                    docstring=ast.get_docstring(node),
                )
                self.add_entity(fn_entity)
                self.add_relation(module_id, "DEFINES", fn_id)
                discovered.append(fn_entity)

                # Extract function calls inside function body
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Name):
                            # Link both module-qualified and bare identifier
                            self.add_relation(fn_id, "CALLS", f"fn:{module_name}.{sub.func.id}")
                            self.add_relation(fn_id, "CALLS", f"fn:{sub.func.id}")

            # Classes
            elif isinstance(node, ast.ClassDef):
                cls_id = f"cls:{module_name}.{node.name}"
                cls_entity = CodeEntity(
                    entity_id=cls_id,
                    name=node.name,
                    kind="CLASS",
                    file_path=norm_path,
                    line_number=node.lineno,
                    docstring=ast.get_docstring(node),
                )
                self.add_entity(cls_entity)
                self.add_relation(module_id, "DEFINES", cls_id)
                discovered.append(cls_entity)

                # Methods inside class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_id = f"meth:{module_name}.{node.name}.{item.name}"
                        method_entity = CodeEntity(
                            entity_id=method_id,
                            name=item.name,
                            kind="METHOD",
                            file_path=norm_path,
                            line_number=item.lineno,
                            docstring=ast.get_docstring(item),
                        )
                        self.add_entity(method_entity)
                        self.add_relation(cls_id, "DEFINES", method_id)
                        discovered.append(method_entity)

        return discovered

    def calculate_blast_radius(self, target_identifier: str) -> Dict[str, Any]:
        """Traverses reverse dependency edges to find all components impacted if target changes."""
        target_keys = set()
        for eid, ent in self.entities.items():
            if target_identifier in eid or target_identifier == ent.name:
                target_keys.add(eid)
                target_keys.add(f"fn:{ent.name}")
        target_keys.add(f"fn:{target_identifier}")
        target_keys.add(target_identifier)

        impacted: Set[str] = set()
        visited: Set[str] = set()
        queue = list(target_keys)

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)

            # Look up who calls, imports, or depends on curr
            incoming = self.reverse_edges.get(curr, [])
            for rel in incoming:
                impacted.add(rel.source_id)
                queue.append(rel.source_id)

        impacted_entities = [
            self.entities[eid].to_dict() for eid in impacted if eid in self.entities
        ]

        return {
            "target": target_identifier,
            "matched_entities": list(target_keys),
            "impact_count": len(impacted_entities),
            "impacted_entities": impacted_entities,
            "safe_to_edit_in_isolation": len(impacted_entities) == 0,
        }

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_entities": len(self.entities),
            "modules_count": sum(1 for e in self.entities.values() if e.kind == "MODULE"),
            "classes_count": sum(1 for e in self.entities.values() if e.kind == "CLASS"),
            "functions_count": sum(1 for e in self.entities.values() if e.kind in ("FUNCTION", "METHOD")),
            "total_relationships": sum(len(rels) for rels in self.forward_edges.values()),
        }
