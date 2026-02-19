"""Prometheus metrics for NAL observability.
Three levels of metrics (PRD Section 5.1):
- Agent-level: tasks completed, token usage, task duration
- Task-level: status distribution, TDD step duration, diff lines
- System-level: active agents, active locks, dispatch latency
"""
from __future__ import annotations
import time
from contextlib import contextmanager
from typing import Any, Generator
try:
    from prometheus_client import Counter, Gauge, Histogram, Info
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

# --- Agent-level metrics ---
if _PROMETHEUS_AVAILABLE:
    nal_agent_tasks_total = Counter(
        "nal_agent_tasks_total",
        "Total tasks processed by agent",
        ["agent_id", "role", "status"],
    )
    nal_agent_tokens_total = Counter(
        "nal_agent_tokens_total",
        "Total tokens consumed by agent",
        ["agent_id", "role", "model"],
    )
    nal_agent_task_duration_seconds = Histogram(
        "nal_agent_task_duration_seconds",
        "Time spent on a single task by agent",
        ["agent_id", "role"],
        buckets=(1, 5, 10, 30, 60, 120, 300, 600),
    )
    nal_agent_retries_total = Counter(
        "nal_agent_retries_total",
        "Total retry count by agent",
        ["agent_id", "role"],
    )
    # --- Task-level metrics ---
    nal_tasks_by_status = Gauge(
        "nal_tasks_by_status",
        "Number of tasks in each status",
        ["status"],
    )
    nal_tdd_step_duration_seconds = Histogram(
        "nal_tdd_step_duration_seconds",
        "Duration of each TDD step",
        ["step"],
        buckets=(0.5, 1, 2, 5, 10, 30, 60),
    )
    nal_commit_diff_lines = Histogram(
        "nal_commit_diff_lines",
        "Number of changed lines per commit",
        ["task_id"],
        buckets=(5, 10, 25, 50, 100, 200, 500),
    )
    nal_test_pass_rate = Gauge(
        "nal_test_pass_rate",
        "Test pass rate for a task",
        ["task_id"],
    )
    nal_task_e2e_duration_seconds = Histogram(
        "nal_task_e2e_duration_seconds",
        "End-to-end duration from READY to DONE",
        ["priority"],
        buckets=(10, 30, 60, 120, 300, 600, 1800),
    )
    # --- System-level metrics ---
    nal_active_agents = Gauge(
        "nal_active_agents",
        "Number of currently active agents",
    )
    nal_active_locks = Gauge(
        "nal_active_locks",
        "Number of active branch locks",
    )
    nal_lock_wait_seconds = Histogram(
        "nal_lock_wait_seconds",
        "Time spent waiting for a branch lock",
        buckets=(0.1, 0.5, 1, 5, 10, 30),
    )
    nal_dispatch_latency_seconds = Histogram(
        "nal_dispatch_latency_seconds",
        "Latency of the dispatch step",
        buckets=(0.01, 0.05, 0.1, 0.5, 1, 5),
    )
    nal_system_info = Info(
        "nal_system",
        "NAL system information",
    )

class MetricsCollector:
    """High-level interface for recording NAL metrics.
    Wraps prometheus_client calls. If prometheus_client is not installed,
    all methods are no-ops.
    """
    def __init__(self) -> None:
        self._available = _PROMETHEUS_AVAILABLE
    @property
    def available(self) -> bool:
        return self._available
    # --- Agent metrics ---
    def record_task_completed(
        self, agent_id: str, role: str, status: str = "done"
    ) -> None:
        if self._available:
            nal_agent_tasks_total.labels(
                agent_id=agent_id, role=role, status=status
            ).inc()
    def record_task_failed(self, agent_id: str, role: str) -> None:
        if self._available:
            nal_agent_tasks_total.labels(
                agent_id=agent_id, role=role, status="failed"
            ).inc()
    def record_tokens(
        self, agent_id: str, role: str, tokens: int, model: str = "unknown"
    ) -> None:
        if self._available:
            nal_agent_tokens_total.labels(
                agent_id=agent_id, role=role, model=model
            ).inc(tokens)
    def record_retry(self, agent_id: str, role: str) -> None:
        if self._available:
            nal_agent_retries_total.labels(agent_id=agent_id, role=role).inc()
    @contextmanager
    def track_task_duration(
        self, agent_id: str, role: str
    ) -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
        finally:
            if self._available:
                duration = time.monotonic() - start
                nal_agent_task_duration_seconds.labels(
                    agent_id=agent_id, role=role
                ).observe(duration)
    # --- Task metrics ---
    def update_task_status_gauge(self, status_counts: dict[str, int]) -> None:
        """Update the task status distribution gauge.
        Args:
            status_counts: dict of status_name → count.
        """
        if self._available:
            for status, count in status_counts.items():
                nal_tasks_by_status.labels(status=status).set(count)
    @contextmanager
    def track_tdd_step(self, step: str) -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
        finally:
            if self._available:
                duration = time.monotonic() - start
                nal_tdd_step_duration_seconds.labels(step=step).observe(duration)
    def record_diff_lines(self, task_id: str, lines: int) -> None:
        if self._available:
            nal_commit_diff_lines.labels(task_id=task_id).observe(lines)
    def record_test_pass_rate(self, task_id: str, rate: float) -> None:
        if self._available:
            nal_test_pass_rate.labels(task_id=task_id).set(rate)
    @contextmanager
    def track_task_e2e(self, priority: str = "normal") -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
        finally:
            if self._available:
                duration = time.monotonic() - start
                nal_task_e2e_duration_seconds.labels(priority=priority).observe(
                    duration
                )
    # --- System metrics ---
    def set_active_agents(self, count: int) -> None:
        if self._available:
            nal_active_agents.set(count)
    def set_active_locks(self, count: int) -> None:
        if self._available:
            nal_active_locks.set(count)
    @contextmanager
    def track_lock_wait(self) -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
        finally:
            if self._available:
                duration = time.monotonic() - start
                nal_lock_wait_seconds.observe(duration)
    @contextmanager
    def track_dispatch_latency(self) -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
        finally:
            if self._available:
                duration = time.monotonic() - start
                nal_dispatch_latency_seconds.observe(duration)
    def set_system_info(self, info: dict[str, str]) -> None:
        if self._available:
            nal_system_info.info(info)
    def get_snapshot(self) -> dict[str, Any]:
        """Get a plain dict snapshot of key metrics (for state serialization)."""
        # This doesn't read from prometheus; it's for CoordinatorState.metrics
        return {
            "available": self._available,
        }

# Module-level singleton
metrics = MetricsCollector()

