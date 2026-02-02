from __future__ import annotations

from dataclasses import dataclass

from examples.agent_system.gateway.models import ApprovalRecord, ApprovalRequest


@dataclass
class ApprovalStore:
    approvals: dict[str, ApprovalRecord]

    @classmethod
    def empty(cls) -> "ApprovalStore":
        return cls(approvals={})

    def create(self, request: ApprovalRequest) -> ApprovalRecord:
        record = ApprovalRecord(
            thread_id=request.thread_id,
            pending_action=request.pending_action,
            summary=request.summary,
            status="pending",
        )
        self.approvals[request.thread_id] = record
        return record

    def get(self, thread_id: str) -> ApprovalRecord | None:
        return self.approvals.get(thread_id)

    def resolve(
        self,
        thread_id: str,
        status: str,
        reviewer: str,
        reason: str | None,
    ) -> ApprovalRecord:
        record = self.approvals[thread_id]
        record.status = status
        record.reviewer = reviewer
        record.reason = reason
        return record
