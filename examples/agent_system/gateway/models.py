from __future__ import annotations
from typing import Literal
from pydantic import BaseModel

class TaskSubmission(BaseModel):
    task: str
    thread_id: str | None = None

class TaskResult(BaseModel):
    thread_id: str
    task: str
    status: str
    review_status: str | None = None
    test_status: str | None = None
    code: str | None = None
    iteration_count: int = 0

class ApprovalRequest(BaseModel):
    thread_id: str
    pending_action: str
    summary: str

class ApprovalResolution(BaseModel):
    thread_id: str
    decision: Literal["approved", "denied"]
    reviewer: str
    reason: str | None = None

class ApprovalRecord(BaseModel):
    thread_id: str
    pending_action: str
    summary: str
    status: Literal["pending", "approved", "denied"]
    reviewer: str | None = None
    reason: str | None = None

# --- Coordinator API models (NAL) ---

class PipelineStartRequest(BaseModel):
    """Start a new NAL pipeline with a requirement."""
    requirement: str
    thread_id: str | None = None
    repo_path: str = ""

class PipelineStatus(BaseModel):
    """Current status of the NAL pipeline."""
    thread_id: str
    phase: str
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_ready: int = 0
    tasks_blocked: int = 0
    error: str = ""

class TaskDetail(BaseModel):
    """Detail of a single task in the pipeline."""
    task_id: str
    title: str
    description: str
    status: str
    assigned_agent: str | None = None
    tdd_mode: str = "full"
    retry_count: int = 0
    depends_on: list[str] = []

