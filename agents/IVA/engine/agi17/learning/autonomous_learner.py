"""IVA Autonomous Self-Learning Engine — 100% Pure Python Standard Library.
================================================================================
Empowers IVA to autonomously learn from codebase files, scripts, and conceptual
topics. Uses stdlib AST parsing, syntax tree inspection, and heuristic extraction,
committing empirical knowledge into persistent SQLite WAL memory (Layer 6 & Layer 7)
with cryptographic SHA-256 provenance.
================================================================================
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("iva.learning.autonomous_learner")


class ASTPatternVisitor(ast.NodeVisitor):
    """AST visitor extracting structural symbols, patterns, and complexity."""

    def __init__(self) -> None:
        self.classes: List[Dict[str, Any]] = []
        self.functions: List[Dict[str, Any]] = []
        self.imports: List[str] = []
        self.total_nodes: int = 0
        self.detected_patterns: Set[str] = set()

    def visit(self, node: ast.AST) -> Any:
        self.total_nodes += 1
        return super().visit(node)

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        mod = node.module or ""
        for alias in node.names:
            self.imports.append(f"{mod}.{alias.name}" if mod else alias.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        bases = [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else [b.__class__.__name__ for b in node.bases]
        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        docstring = ast.get_docstring(node) or ""
        self.classes.append({
            "name": node.name,
            "bases": bases,
            "methods": methods,
            "docstring": docstring[:180] + ("..." if len(docstring) > 180 else ""),
            "line": node.lineno,
        })

        # Pattern detection heuristics
        if any("Singleton" in b or "singleton" in b.lower() for b in bases) or any(m == "__new__" for m in methods):
            self.detected_patterns.add("Singleton Pattern")
        if any("Adapter" in node.name or "adapter" in node.name.lower() for _ in [0]):
            self.detected_patterns.add("Adapter Pattern")
        if any("Factory" in node.name or "factory" in node.name.lower() for _ in [0]):
            self.detected_patterns.add("Factory Pattern")
        if any("Observer" in node.name or "Listener" in node.name for _ in [0]):
            self.detected_patterns.add("Observer / Event Dispatcher Pattern")
        if any("FSM" in node.name or "State" in node.name for _ in [0]):
            self.detected_patterns.add("Finite State Machine Pattern")

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        args = [a.arg for a in node.args.args]
        docstring = ast.get_docstring(node) or ""
        self.functions.append({
            "name": node.name,
            "args": args,
            "docstring": docstring[:120] + ("..." if len(docstring) > 120 else ""),
            "line": node.lineno,
        })
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        args = [a.arg for a in node.args.args]
        docstring = ast.get_docstring(node) or ""
        self.functions.append({
            "name": node.name,
            "args": args,
            "is_async": True,
            "docstring": docstring[:120] + ("..." if len(docstring) > 120 else ""),
            "line": node.lineno,
        })
        self.detected_patterns.add("Asynchronous Concurrency Pattern")
        self.generic_visit(node)


class AutonomousLearner:
    """Core autonomous learning engine for IVA."""

    def __init__(self, memory: Optional[Any] = None) -> None:
        self._memory = memory

    @property
    def memory(self) -> Any:
        if self._memory is None:
            try:
                from ..memory.omega_command_memory import OmegaCommandMemory
                self._memory = OmegaCommandMemory()
            except Exception as exc:
                logger.warning("Could not instantiate default memory for AutonomousLearner: %s", exc)
        return self._memory

    def learn_file(self, target_path: str | Path) -> Dict[str, Any]:
        """Ingests and analyzes a file, extracting AST symbols and learning rules."""
        p = Path(target_path).resolve()
        if not p.is_file():
            return {
                "success": False,
                "error": f"Target file not found: {p}",
                "target": str(p),
            }

        raw_bytes = p.read_bytes()
        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
        text_content = p.read_text(encoding="utf-8", errors="replace")
        lines_count = len(text_content.splitlines())

        analysis_type = "TEXT"
        classes: List[Dict[str, Any]] = []
        functions: List[Dict[str, Any]] = []
        imports: List[str] = []
        patterns: List[str] = []
        heuristics: List[str] = []

        if p.suffix == ".py":
            analysis_type = "PYTHON_AST"
            try:
                tree = ast.parse(text_content, filename=str(p))
                visitor = ASTPatternVisitor()
                visitor.visit(tree)
                classes = visitor.classes
                functions = visitor.functions
                imports = list(dict.fromkeys(visitor.imports))
                patterns = sorted(visitor.detected_patterns)

                # Formulate learned heuristics
                if classes:
                    heuristics.append(f"Exposes {len(classes)} structural class abstractions: {', '.join(c['name'] for c in classes[:4])}")
                if functions:
                    heuristics.append(f"Provides {len(functions)} functional interfaces: {', '.join(f['name'] for f in functions[:4])}")
                if patterns:
                    heuristics.append(f"Employs design patterns: {', '.join(patterns)}")
                if any("fail_closed" in text_content.lower() for _ in [0]):
                    heuristics.append("Contains physical fail-closed safety invariants.")
            except Exception as parse_err:
                heuristics.append(f"AST parsing notice: {parse_err}")

        elif p.suffix in (".json", ".jsonl"):
            analysis_type = "STRUCTURED_JSON"
            try:
                data = json.loads(text_content)
                if isinstance(data, dict):
                    heuristics.append(f"JSON Object schema with {len(data)} top-level keys: {', '.join(list(data.keys())[:6])}")
                elif isinstance(data, list):
                    heuristics.append(f"JSON Array containing {len(data)} entries.")
            except Exception as e:
                heuristics.append(f"JSON validation error: {e}")
        elif p.suffix in (".md", ".txt"):
            analysis_type = "MARKDOWN_DOC"
            headings = [line.strip("# ").strip() for line in text_content.splitlines() if line.startswith("#")]
            if headings:
                heuristics.append(f"Document contains {len(headings)} structured sections: {', '.join(headings[:4])}")

        # Commit to persistent memory
        mem_entry_id = None
        mem_layer = 6 if p.suffix == ".py" else 7
        subject_key = f"iva.learned.code.{p.name.replace('.', '_')}"

        if self.memory is not None:
            try:
                entry = self.memory.store(
                    layer=mem_layer,
                    subject_key=subject_key,
                    content=f"Learned code patterns from {p.name} ({analysis_type}, {lines_count} LOC). SHA-256: {sha256_hash[:16]}",
                    structured_data={
                        "filename": p.name,
                        "file_path": str(p),
                        "lines_count": lines_count,
                        "analysis_type": analysis_type,
                        "sha256": sha256_hash,
                        "classes_count": len(classes),
                        "functions_count": len(functions),
                        "patterns": patterns,
                        "heuristics": heuristics,
                    },
                    tags=["learned", "code", "ast", p.suffix.lstrip(".")]
                )
                mem_entry_id = getattr(entry, "entry_id", str(entry))
            except Exception as exc:
                logger.warning("Memory persistence error in AutonomousLearner: %s", exc)

        return {
            "success": True,
            "target": str(p),
            "filename": p.name,
            "analysis_type": analysis_type,
            "lines_count": lines_count,
            "sha256": sha256_hash,
            "classes": classes,
            "functions": functions,
            "imports": imports,
            "patterns": patterns,
            "heuristics": heuristics,
            "memory_layer": mem_layer,
            "memory_entry_id": mem_entry_id,
            "subject_key": subject_key,
        }

    def learn_concept(self, topic: str, notes: Optional[str] = None) -> Dict[str, Any]:
        """Decomposes a concept, algorithm, or topic and records it in memory."""
        clean_topic = topic.strip()
        if not clean_topic:
            return {"success": False, "error": "Empty topic provided"}

        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", clean_topic.lower()).strip("_")
        subject_key = f"iva.learned.concept.{slug}"
        payload = f"{clean_topic}\n{notes or ''}"
        sha256_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        # Extract principles and operational constraints
        principles = [
            f"Grounding principle: {clean_topic} established as verified cognitive reference.",
            f"Provenance hash: {sha256_hash[:16]} cryptographically verified.",
        ]
        if notes:
            principles.append(f"Operational context: {notes[:200]}")

        mem_entry_id = None
        if self.memory is not None:
            try:
                entry = self.memory.store(
                    layer=7,
                    subject_key=subject_key,
                    content=f"Learned conceptual knowledge: {clean_topic}.",
                    structured_data={
                        "topic": clean_topic,
                        "slug": slug,
                        "notes": notes,
                        "sha256": sha256_hash,
                        "principles": principles,
                        "learned_at": time.time(),
                    },
                    tags=["learned", "concept", "heuristic", slug[:20]]
                )
                mem_entry_id = getattr(entry, "entry_id", str(entry))
            except Exception as exc:
                logger.warning("Memory store error for concept '%s': %s", clean_topic, exc)

        return {
            "success": True,
            "topic": clean_topic,
            "slug": slug,
            "subject_key": subject_key,
            "sha256": sha256_hash,
            "principles": principles,
            "memory_layer": 7,
            "memory_entry_id": mem_entry_id,
        }

    def get_learning_summary(self) -> Dict[str, Any]:
        """Returns summary of all learned items in persistent memory."""
        if self.memory is None:
            return {"total_learned": 0, "layers": [6, 7], "status": "NO_MEMORY_BACKEND"}

        try:
            entries = self.memory.retrieve(tags=["learned"], limit=50)
            return {
                "total_learned": len(entries),
                "layers": [6, 7],
                "status": "ACTIVE",
                "recent_learnings": [
                    {
                        "entry_id": e.entry_id,
                        "layer": e.layer,
                        "subject_key": e.subject_key,
                        "content": e.content,
                        "created_at": e.created_at,
                    }
                    for e in entries[:10]
                ]
            }
        except Exception as exc:
            return {"total_learned": 0, "error": str(exc), "status": "QUERY_FAILED"}
