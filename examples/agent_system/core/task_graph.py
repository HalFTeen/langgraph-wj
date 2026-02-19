"""TaskGraph - DAG-based task dependency management.
Core data structures and logic for managing atomic baby-step tasks
with dependency tracking, status flow enforcement, and cascading effects.
"""
from __future__ import annotations
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class TaskStatus(Enum):
    """Task lifecycle states.
    Flow: PENDING → READY → ASSIGNED → TESTING → CODING → VERIFYING → DONE
                                         ↓                              ↓
                                      (timeout)                      (fail)
                                         ↓                              ↓
                                       READY ←──────────── retry < max?
                                                                ↓ (exceeded)
                                                             FAILED → human
    BLOCKED: downstream of a FAILED task.
    """
    PENDING = "pending"
    READY = "ready"
    ASSIGNED = "assigned"
    TESTING = "testing"
    CODING = "coding"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"

# Legal state transitions. Key = current status, value = set of allowed next statuses.
_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.READY, TaskStatus.BLOCKED},
    TaskStatus.READY: {TaskStatus.ASSIGNED, TaskStatus.BLOCKED},
    TaskStatus.ASSIGNED: {TaskStatus.TESTING, TaskStatus.CODING, TaskStatus.READY},
    TaskStatus.TESTING: {TaskStatus.CODING, TaskStatus.READY, TaskStatus.FAILED},
    TaskStatus.CODING: {TaskStatus.VERIFYING, TaskStatus.READY, TaskStatus.FAILED},
    TaskStatus.VERIFYING: {TaskStatus.DONE, TaskStatus.READY, TaskStatus.FAILED},
    TaskStatus.DONE: set(),  # terminal
    TaskStatus.FAILED: {TaskStatus.READY},  # human can resume
    TaskStatus.BLOCKED: {TaskStatus.PENDING, TaskStatus.READY},  # unblock when upstream recovers
}

@dataclass
class Task:
    """Atomic task unit - a single baby-step in the task tree."""
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    parent_id: str | None = None
    depends_on: list[str] = field(default_factory=list)
    assigned_agent: str | None = None
    branch: str | None = None
    tdd_mode: str = "full"  # "full" | "lite"
    test_file: str | None = None
    max_retries: int = 3
    retry_count: int = 0
    diff_line_limit: int = 100
    github_issue_id: int | None = None
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "parent_id": self.parent_id,
            "depends_on": list(self.depends_on),
            "assigned_agent": self.assigned_agent,
            "branch": self.branch,
            "tdd_mode": self.tdd_mode,
            "test_file": self.test_file,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "diff_line_limit": self.diff_line_limit,
            "github_issue_id": self.github_issue_id,
        }
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        d = dict(data)
        d["status"] = TaskStatus(d["status"])
        return cls(**d)

class TaskGraphError(Exception):
    """Raised for invalid task graph operations."""

class TaskGraph:
    """DAG-based task dependency graph.
    Manages task lifecycle, enforces legal state transitions,
    handles cascading effects (DONE unlocks downstream, FAILED blocks downstream),
    and provides topological ordering for scheduling.
    """
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
    @property
    def tasks(self) -> dict[str, Task]:
        return dict(self._tasks)
    def add_task(self, task: Task) -> None:
        """Add a task to the graph."""
        if task.id in self._tasks:
            raise TaskGraphError(f"Task {task.id} already exists")
        # Validate that all dependencies reference existing tasks
        for dep_id in task.depends_on:
            if dep_id not in self._tasks:
                raise TaskGraphError(
                    f"Dependency {dep_id} not found for task {task.id}"
                )
        self._tasks[task.id] = task
    def remove_task(self, task_id: str) -> None:
        """Remove a task. Fails if other tasks depend on it."""
        if task_id not in self._tasks:
            raise TaskGraphError(f"Task {task_id} not found")
        # Check no other task depends on this one
        for t in self._tasks.values():
            if task_id in t.depends_on:
                raise TaskGraphError(
                    f"Cannot remove {task_id}: task {t.id} depends on it"
                )
        del self._tasks[task_id]
    def add_dependency(self, task_id: str, depends_on_id: str) -> None:
        """Add a dependency edge: task_id depends on depends_on_id."""
        if task_id not in self._tasks:
            raise TaskGraphError(f"Task {task_id} not found")
        if depends_on_id not in self._tasks:
            raise TaskGraphError(f"Task {depends_on_id} not found")
        if depends_on_id == task_id:
            raise TaskGraphError("Task cannot depend on itself")
        task = self._tasks[task_id]
        if depends_on_id not in task.depends_on:
            task.depends_on.append(depends_on_id)
        # Validate no cycle was introduced
        if not self.validate_dag():
            task.depends_on.remove(depends_on_id)
            raise TaskGraphError(
                f"Adding dependency {task_id} → {depends_on_id} creates a cycle"
            )
    def get_task(self, task_id: str) -> Task:
        """Get a task by ID."""
        if task_id not in self._tasks:
            raise TaskGraphError(f"Task {task_id} not found")
        return self._tasks[task_id]
    def get_subtasks(self, parent_id: str) -> list[Task]:
        """Get all direct children of a parent task."""
        return [t for t in self._tasks.values() if t.parent_id == parent_id]
    def get_ready_tasks(self) -> list[Task]:
        """Return tasks whose dependencies are all DONE and status is PENDING.
        Automatically promotes PENDING → READY when all deps are satisfied.
        Returns tasks ordered by critical path priority (more downstream dependents first).
        """
        ready = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            if self._all_deps_done(task):
                task.status = TaskStatus.READY
                ready.append(task)
        # Also include tasks already in READY state (e.g., re-queued after failure)
        for task in self._tasks.values():
            if task.status == TaskStatus.READY and task not in ready:
                ready.append(task)
        # Sort by number of downstream dependents (critical path heuristic)
        ready.sort(key=lambda t: self._count_downstream(t.id), reverse=True)
        return ready
    def update_status(self, task_id: str, new_status: TaskStatus) -> None:
        """Update task status with transition validation and cascading effects."""
        task = self.get_task(task_id)
        old_status = task.status
        if new_status == old_status:
            return
        if new_status not in _TRANSITIONS.get(old_status, set()):
            raise TaskGraphError(
                f"Invalid transition: {task_id} {old_status.value} → {new_status.value}"
            )
        task.status = new_status
        # Cascading effects
        if new_status == TaskStatus.DONE:
            self._cascade_done(task_id)
        elif new_status == TaskStatus.FAILED:
            self._cascade_failed(task_id)
        elif new_status == TaskStatus.READY and old_status == TaskStatus.FAILED:
            # Human resumed a failed task → unblock downstream
            self._cascade_unblock(task_id)
    def validate_dag(self) -> bool:
        """Check that the dependency graph has no cycles (Kahn's algorithm)."""
        in_degree: dict[str, int] = {tid: 0 for tid in self._tasks}
        for task in self._tasks.values():
            for dep_id in task.depends_on:
                if dep_id in in_degree:
                    in_degree[task.id] += 1
        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for task in self._tasks.values():
                if current in task.depends_on:
                    in_degree[task.id] -= 1
                    if in_degree[task.id] == 0:
                        queue.append(task.id)
        return visited == len(self._tasks)
    def get_all_tasks(self) -> list[Task]:
        """Return all tasks."""
        return list(self._tasks.values())
    def get_tasks_by_status(self, status: TaskStatus) -> list[Task]:
        """Return all tasks with a given status."""
        return [t for t in self._tasks.values() if t.status == status]
    def is_complete(self) -> bool:
        """Check if all tasks are DONE."""
        return all(t.status == TaskStatus.DONE for t in self._tasks.values())
    def has_failed(self) -> bool:
        """Check if any task is FAILED (needs human intervention)."""
        return any(t.status == TaskStatus.FAILED for t in self._tasks.values())
    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
        }
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskGraph:
        graph = cls()
        # Reconstruct tasks in dependency order
        tasks_data = data["tasks"]
        added: set[str] = set()
        def _add_with_deps(tid: str) -> None:
            if tid in added:
                return
            task_data = tasks_data[tid]
            for dep_id in task_data.get("depends_on", []):
                if dep_id in tasks_data:
                    _add_with_deps(dep_id)
            graph._tasks[tid] = Task.from_dict(task_data)
            added.add(tid)
        for tid in tasks_data:
            _add_with_deps(tid)
        return graph
    # --- Private helpers ---
    def _all_deps_done(self, task: Task) -> bool:
        """Check if all dependencies of a task are DONE."""
        for dep_id in task.depends_on:
            dep = self._tasks.get(dep_id)
            if dep is None or dep.status != TaskStatus.DONE:
                return False
        return True
    def _count_downstream(self, task_id: str) -> int:
        """Count tasks that directly or indirectly depend on this task."""
        count = 0
        for task in self._tasks.values():
            if task_id in task.depends_on:
                count += 1 + self._count_downstream(task.id)
        return count
    def _cascade_done(self, task_id: str) -> None:
        """When a task is DONE, check if downstream PENDING tasks can become READY."""
        for task in self._tasks.values():
            if task_id in task.depends_on and task.status == TaskStatus.PENDING:
                if self._all_deps_done(task):
                    task.status = TaskStatus.READY
    def _cascade_failed(self, task_id: str) -> None:
        """When a task FAILS, block all downstream dependents recursively."""
        for task in self._tasks.values():
            if task_id in task.depends_on and task.status not in (
                TaskStatus.DONE,
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
            ):
                task.status = TaskStatus.BLOCKED
                self._cascade_failed(task.id)
    def _cascade_unblock(self, task_id: str) -> None:
        """When a failed task is resumed (→ READY), unblock downstream if possible."""
        for task in self._tasks.values():
            if task_id in task.depends_on and task.status == TaskStatus.BLOCKED:
                # Only unblock if ALL deps are either DONE or no longer FAILED/BLOCKED
                all_ok = all(
                    self._tasks[d].status
                    not in (TaskStatus.FAILED, TaskStatus.BLOCKED)
                    for d in task.depends_on
                    if d in self._tasks
                )
                if all_ok:
                    task.status = TaskStatus.PENDING
                    self._cascade_unblock(task.id)

def make_task_id() -> str:
    """Generate a unique task ID."""
    return str(uuid.uuid4())[:8]

