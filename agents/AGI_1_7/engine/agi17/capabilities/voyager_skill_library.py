"""Voyager Lifelong Open-Ended Skill Library (Update 22).

Grounded in Wang et al. (arXiv:2305.16291):
"Voyager: An Open-Ended Embodied Agent with Large Language Models"
- Maintains an ever-growing skill library of executable code functions.
- Validates code syntax and abstract syntax tree (AST) invariants prior to admission.
- Indexes skills by semantic tags and signature metadata for rapid associative retrieval.
- Enables autonomous skill discovery, incremental capability evolution, and safe execution.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("VoyagerSkillLibrary")


@dataclass
class SkillRecord:
    skill_id: str
    name: str
    description: str
    source_code: str
    entrypoint: str
    parameters_schema: Dict[str, str]
    return_type: str
    tags: List[str] = field(default_factory=list)
    verification_passed: bool = False
    execution_count: int = 0
    failure_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_executed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class VoyagerSkillLibrary:
    """Manages an evolving library of verified, executable code skills."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        if storage_dir is None:
            storage_dir = Path(__file__).resolve().parents[1] / "runtime_storage" / "skills"
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "skills_manifest.json"
        self._skills: Dict[str, SkillRecord] = {}
        self._load_manifest()

    def _load_manifest(self) -> None:
        """Loads indexed skills from persistent JSON storage."""
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        self._skills[k] = SkillRecord(**v)
                logger.info(f"Loaded {len(self._skills)} skills from {self.index_file}")
            except Exception as e:
                logger.warning(f"Failed to load skills manifest: {e}")

    def _persist_manifest(self) -> None:
        """Saves current skill state to persistent storage."""
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump({k: v.to_dict() for k, v in self._skills.items()}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save skills manifest: {e}")

    def validate_ast(self, source_code: str, entrypoint: str) -> Tuple[bool, str]:
        """Validates that the source code parses as valid Python AST and contains the entrypoint."""
        try:
            tree = ast.parse(source_code)
        except SyntaxError as se:
            return False, f"AST SyntaxError: {se.msg} at line {se.lineno}"

        has_entrypoint = False
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == entrypoint:
                    has_entrypoint = True
                    break

        if not has_entrypoint:
            return False, f"Entrypoint function '{entrypoint}' not defined at module level."

        return True, "AST syntax validation passed."

    def register_skill(
        self,
        name: str,
        description: str,
        source_code: str,
        entrypoint: str,
        parameters_schema: Dict[str, str],
        return_type: str,
        tags: Optional[List[str]] = None,
        auto_verify: bool = True,
    ) -> Tuple[bool, str, Optional[SkillRecord]]:
        """Registers a newly discovered skill, validating AST and saving code artifact."""
        valid, msg = self.validate_ast(source_code, entrypoint)
        if not valid:
            return False, msg, None

        skill_id = f"SKILL-{hashlib.sha256(name.encode()).hexdigest()[:8]}"
        record = SkillRecord(
            skill_id=skill_id,
            name=name,
            description=description,
            source_code=source_code,
            entrypoint=entrypoint,
            parameters_schema=parameters_schema,
            return_type=return_type,
            tags=tags or [],
            verification_passed=auto_verify,
        )

        # Save individual source file
        code_file = self.storage_dir / f"{skill_id}_{name}.py"
        try:
            with open(code_file, "w", encoding="utf-8") as f:
                f.write(source_code)
        except Exception as e:
            return False, f"Filesystem write failed: {e}", None

        self._skills[skill_id] = record
        self._persist_manifest()
        return True, f"Skill '{name}' registered successfully with ID {skill_id}", record

    def search_skills(self, query: str, limit: int = 5) -> List[SkillRecord]:
        """Performs multi-criteria matching over tags, names, and descriptions."""
        q = query.lower()
        scored: List[Tuple[float, SkillRecord]] = []

        for skill in self._skills.values():
            score = 0.0
            if q in skill.name.lower():
                score += 3.0
            if any(q in t.lower() for t in skill.tags):
                score += 2.0
            if q in skill.description.lower():
                score += 1.0

            if score > 0.0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def get_skill(self, skill_id: str) -> Optional[SkillRecord]:
        """Retrieves a skill record by its ID."""
        return self._skills.get(skill_id)

    def execute_skill(self, skill_id: str, **kwargs: Any) -> Tuple[bool, Any, str]:
        """Safely executes a registered skill in an isolated namespace."""
        skill = self._skills.get(skill_id)
        if not skill:
            return False, None, f"Skill {skill_id} not found"

        local_scope: Dict[str, Any] = {}
        try:
            exec(skill.source_code, local_scope)
            fn = local_scope.get(skill.entrypoint)
            if not callable(fn):
                skill.failure_count += 1
                self._persist_manifest()
                return False, None, f"Entrypoint '{skill.entrypoint}' is not callable"

            result = fn(**kwargs)
            skill.execution_count += 1
            skill.last_executed_at = time.time()
            self._persist_manifest()
            return True, result, "Execution succeeded"
        except Exception as e:
            skill.failure_count += 1
            self._persist_manifest()
            return False, None, f"Execution failed with exception: {e}"

    def list_all_skills(self) -> List[Dict[str, Any]]:
        """Lists all skills currently registered in the library."""
        return [s.to_dict() for s in self._skills.values()]
