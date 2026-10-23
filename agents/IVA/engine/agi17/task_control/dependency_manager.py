"""
engine/agi17/task_control/dependency_manager.py
AGI 1.7 OMEGA COMMAND — Parent-Child Hierarchy & DAG Dependency Manager
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from .task_state_machine import TaskState


class DependencyCycleError(ValueError):
    """Raised when a circular dependency is detected in a task graph."""


class DelegationLimitError(ValueError):
    """Raised when delegation depth or child task count exceeds policy bounds."""


class DependencyManager:
    """Manages task dependency graphs and parent-child limits."""

    def __init__(self, task_store: Any, max_delegation_depth: int = 3, max_logical_children: int = 100):
        self.task_store = task_store
        self.max_delegation_depth = max_delegation_depth
        self.max_logical_children = max_logical_children

    def get_task_depth(self, task_id: str) -> int:
        depth = 0
        curr_id = task_id
        visited = set()
        while curr_id:
            if curr_id in visited:
                raise DependencyCycleError(f"Parent-child cycle detected involving {curr_id}")
            visited.add(curr_id)
            t = self.task_store.get_task(curr_id)
            if not t or not t.get("parent_task_id"):
                break
            curr_id = t["parent_task_id"]
            depth += 1
        return depth

    def validate_child_creation(self, job_id: str, parent_task_id: str) -> Tuple[int, int]:
        parent_depth = self.get_task_depth(parent_task_id)
        new_depth = parent_depth + 1
        if new_depth > self.max_delegation_depth:
            raise DelegationLimitError(
                f"Delegation depth {new_depth} exceeds max_delegation_depth={self.max_delegation_depth}"
            )
        job_tasks = self.task_store.list_tasks(job_id=job_id)
        child_count = sum(1 for t in job_tasks if t.get("parent_task_id") is not None)
        if child_count >= self.max_logical_children:
            raise DelegationLimitError(
                f"Logical child task count {child_count} reached MAX_LOGICAL_CHILD_TASKS={self.max_logical_children}"
            )
        return new_depth, child_count + 1

    @staticmethod
    def detect_cycles(adjacency: Dict[str, List[str]]) -> bool:
        visited: Set[str] = set()
        in_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            for dep in adjacency.get(node, []):
                if dep not in visited:
                    if dfs(dep):
                        return True
                elif dep in in_stack:
                    return True
            in_stack.remove(node)
            return False

        for n in list(adjacency.keys()):
            if n not in visited:
                if dfs(n):
                    return True
        return False

    def validate_no_cycle(self, job_id: Optional[str], new_task_id: str, new_dependencies: List[str]) -> None:
        tasks = self.task_store.list_tasks(job_id=job_id) if job_id else self.task_store.list_tasks()
        adj = {t["task_id"]: list(t.get("dependencies", [])) for t in tasks}
        adj[new_task_id] = list(new_dependencies)
        if self.detect_cycles(adj):
            raise DependencyCycleError(
                f"Adding dependencies {new_dependencies} to {new_task_id} creates a circular dependency"
            )

    def validate_dag(self, job_id: Optional[str] = None) -> bool:
        tasks = self.task_store.list_tasks(job_id=job_id) if job_id else self.task_store.list_tasks()
        adj = {t["task_id"]: list(t.get("dependencies", [])) for t in tasks}
        if self.detect_cycles(adj):
            raise DependencyCycleError("Circular dependency detected in task DAG")
        return True

    def refresh_ready_and_blocked_tasks(
        self,
        job_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        if parent_task_id:
            tasks = self.task_store.list_tasks(parent_task_id=parent_task_id)
        elif job_id:
            tasks = self.task_store.list_tasks(job_id=job_id)
        else:
            tasks = self.task_store.list_tasks()

        all_tasks = self.task_store.list_tasks()
        state_map = {t["task_id"]: t["state"] for t in all_tasks}
        promoted_ready = []
        marked_blocked = []

        for t in tasks:
            tid = t["task_id"]
            st = t["state"]
            if st not in {TaskState.PLANNED.value, TaskState.QUEUED.value}:
                continue
            deps = t.get("dependencies", [])
            if not deps:
                self.task_store.transition_task(tid, TaskState.READY, {"reason": "no_dependencies"})
                promoted_ready.append(tid)
                continue

            if any(
                state_map.get(d) in {TaskState.FAILED.value, TaskState.CANCELED.value, TaskState.BLOCKED.value}
                for d in deps
            ):
                self.task_store.transition_task(
                    tid, TaskState.BLOCKED, {"reason": "upstream_dependency_failed_or_blocked"}
                )
                marked_blocked.append(tid)
            elif all(state_map.get(d) == TaskState.SUCCEEDED.value for d in deps):
                self.task_store.transition_task(
                    tid, TaskState.READY, {"reason": "all_dependencies_succeeded"}
                )
                promoted_ready.append(tid)

        return {"ready": promoted_ready, "blocked": marked_blocked}

    def resolve_ready_tasks(
        self,
        parent_task_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        return self.refresh_ready_and_blocked_tasks(job_id=job_id, parent_task_id=parent_task_id)
