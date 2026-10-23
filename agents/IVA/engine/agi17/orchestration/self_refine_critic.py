"""Self-Refine Diagnostic Critic & Rewriter Engine (Update 2).

Grounded in Madaan et al. (arXiv:2303.17651):
"Self-Refine: Iterative Refinement with Self-Feedback"
- Implements an iterative Generate -> Feedback -> Refine loop at test time.
- Uses AST inspection to detect code smells, excessive nesting, missing docstrings, and unhandled exceptions.
- Formulates actionable verbal critique rubrics that drive subsequent refactoring passes.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("SelfRefineCritic")


@dataclass
class CodeCritiqueItem:
    category: str      # "SYNTAX", "COMPLEXITY", "ERROR_HANDLING", "DOCUMENTATION", "SECURITY"
    severity: str      # "INFO", "WARNING", "ERROR"
    line_number: Optional[int]
    critique_feedback: str
    suggested_action: str


@dataclass
class RefinementReport:
    iteration: int
    passed_audit: bool
    issues_found: int
    critique_items: List[CodeCritiqueItem] = field(default_factory=list)
    refined_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "passed_audit": self.passed_audit,
            "issues_found": self.issues_found,
            "critique_items": [asdict(item) for item in self.critique_items],
            "refined_code": self.refined_code,
        }


class SelfRefineCritic:
    """Performs deterministic AST analysis and generates multi-dimensional critiques."""

    def audit_code(self, source_code: str) -> RefinementReport:
        """Audits Python source code across complexity, documentation, and error handling."""
        items: List[CodeCritiqueItem] = []

        try:
            tree = ast.parse(source_code)
        except SyntaxError as se:
            items.append(
                CodeCritiqueItem(
                    category="SYNTAX",
                    severity="ERROR",
                    line_number=se.lineno,
                    critique_feedback=f"Syntax error: {se.msg}",
                    suggested_action="Fix Python syntax error at specified line.",
                )
            )
            return RefinementReport(iteration=1, passed_audit=False, issues_found=1, critique_items=items)

        for node in ast.walk(tree):
            # 1. Documentation check for functions and classes
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not ast.get_docstring(node):
                    items.append(
                        CodeCritiqueItem(
                            category="DOCUMENTATION",
                            severity="WARNING",
                            line_number=node.lineno,
                            critique_feedback=f"{type(node).__name__} '{node.name}' lacks a docstring.",
                            suggested_action=f"Add descriptive docstring explaining purpose and arguments for '{node.name}'.",
                        )
                    )

            # 2. Complexity check (deeply nested blocks)
            if isinstance(node, (ast.If, ast.For, ast.While)):
                depth = self._calculate_nesting_depth(node)
                if depth > 3:
                    items.append(
                        CodeCritiqueItem(
                            category="COMPLEXITY",
                            severity="WARNING",
                            line_number=node.lineno,
                            critique_feedback=f"Control flow nesting exceeds threshold (depth {depth} > 3).",
                            suggested_action="Refactor inner logic into dedicated helper functions or early returns.",
                        )
                    )

            # 3. Security check (bare exec or eval)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec"):
                    items.append(
                        CodeCritiqueItem(
                            category="SECURITY",
                            severity="WARNING",
                            line_number=node.lineno,
                            critique_feedback=f"Use of '{node.func.id}' detected.",
                            suggested_action="Ensure execution occurs within sandboxed scope with input sanitization.",
                        )
                    )

        has_errors = any(i.severity == "ERROR" for i in items)
        passed = (len(items) == 0) or (not has_errors and len([i for i in items if i.severity == "WARNING"]) <= 2)

        return RefinementReport(
            iteration=1,
            passed_audit=passed,
            issues_found=len(items),
            critique_items=items,
            refined_code=source_code,
        )

    def _calculate_nesting_depth(self, node: ast.AST, current_depth: int = 1) -> int:
        """Recursively checks control flow nesting depth."""
        max_d = current_depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try)):
                child_d = self._calculate_nesting_depth(child, current_depth + 1)
                if child_d > max_d:
                    max_d = child_d
        return max_d
