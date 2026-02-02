from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


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
