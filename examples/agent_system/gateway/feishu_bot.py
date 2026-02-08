"""Feishu bot for human-in-the-loop approval workflow.

This module provides a FastAPI-based webhook handler for Feishu events,
supporting message receiving, command processing (approve/deny/status),
and integration with the agent graph.

Usage:
    # Run the Feishu webhook server
    uvicorn examples.agent_system.gateway.feishu_bot:app --reload

    # Or integrate with main app
    from examples.agent_system.gateway.feishu_bot import create_feishu_router
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel

from examples.agent_system.gateway.feishu_client import FeishuClient, FeishuConfig


# ============================================================================
# Data Models
# =========================================================================


@dataclass
class ApprovalRequest:
    """Represents a pending approval request."""

    request_id: str
    thread_id: str
    user_id: str
    chat_id: str
    title: str
    description: str
    created_at: float
    status: str = "pending"  # pending, approved, denied
    approve_url: str = ""
    deny_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class FeishuEvent(BaseModel):
    """Incoming Feishu event payload."""

    challenge: str | None = None
    header: dict[str, Any] = {}
    event: dict[str, Any] = {}


class MessageReceiveEvent(BaseModel):
    """Message receive event from Feishu."""

    message_id: str
    sender: dict[str, Any]
    message_type: str
    content: str
    chat_id: str
    create_time: str


# ============================================================================
# Approval Store (in-memory for demo, use Redis/database in production)
# =========================================================================


class ApprovalStore:
    """In-memory storage for approval requests."""

    def __init__(self) -> None:
        self._approvals: dict[str, ApprovalRequest] = {}
        self._user_sessions: dict[str, str] = {}  # user_id -> thread_id mapping

    def create_approval(
        self,
        request_id: str,
        thread_id: str,
        user_id: str,
        chat_id: str,
        title: str,
        description: str,
        approve_url: str,
        deny_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Create a new approval request."""
        approval = ApprovalRequest(
            request_id=request_id,
            thread_id=thread_id,
            user_id=user_id,
            chat_id=chat_id,
            title=title,
            description=description,
            created_at=time.time(),
            approve_url=approve_url,
            deny_url=deny_url,
            metadata=metadata or {},
        )
        self._approvals[request_id] = approval
        self._user_sessions[user_id] = thread_id
        return approval

    def get_approval(self, request_id: str) -> ApprovalRequest | None:
        """Get an approval by request ID."""
        return self._approvals.get(request_id)

    def get_approval_by_thread(self, thread_id: str) -> list[ApprovalRequest]:
        """Get all pending approvals for a thread."""
        return [
            a for a in self._approvals.values()
            if a.thread_id == thread_id and a.status == "pending"
        ]

    def update_status(
        self, request_id: str, status: str
    ) -> ApprovalRequest | None:
        """Update approval status."""
        if request_id in self._approvals:
            self._approvals[request_id].status = status
            return self._approvals[request_id]
        return None

    def get_pending_for_user(self, user_id: str) -> list[ApprovalRequest]:
        """Get pending approvals for a user."""
        return [
            a for a in self._approvals.values()
            if a.user_id == user_id and a.status == "pending"
        ]


# Global approval store
approval_store = ApprovalStore()


# ============================================================================
# Command Parser
# =========================================================================


def parse_command(content: str) -> tuple[str, list[str]]:
    """Parse a command message.

    Args:
        content: Message content (may include /command and args)

    Returns:
        Tuple of (command, args)
    """
    content = content.strip()
    if not content.startswith("/"):
        return "", []

    parts = content.split()
    command = parts[0].lower().lstrip("/")
    args = parts[1:] if len(parts) > 1 else []
    return command, args


# ============================================================================
# FastAPI Router
# =========================================================================


def create_feishu_router(
    *,
    config: FeishuConfig | None = None,
    app_secret: str | None = None,
    webhook_path: str = "/feishu/events",
) -> tuple[APIRouter, dict[str, Any]]:
    """Create the Feishu event handler router.

    Args:
        config: Feishu configuration. If None, loads from environment.
        app_secret: Feishu app secret for signature verification.
        webhook_path: URL path for webhook endpoint.

    Returns:
        Tuple of (router, dependency kwargs dict)
    """
    router = APIRouter()
    feishu_config = config or FeishuConfig.from_env()

    # Get app_secret for signature verification
    _app_secret = app_secret or os.getenv("FEISHU_APP_SECRET", "")

    async def verify_signature(
        request: Request, x_feishu_signature: str = Header(None)
    ) -> bool:
        """Verify the request signature from Feishu."""
        if not _app_secret:
            return True  # Skip verification if no secret configured

        body = await request.body()
        timestamp = request.headers.get("x_feishu_timestamp", "")

        # Build signature string
        sign_str = f"{timestamp}{_app_secret}"
        signature = hmac.new(
            sign_str.encode(), body, hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, x_feishu_signature or "")

    def get_client() -> FeishuClient:
        """Dependency to get Feishu client."""
        return FeishuClient(config=feishu_config)

    def get_store() -> ApprovalStore:
        """Dependency to get approval store."""
        return approval_store

    @router.get(webhook_path)
    async def feishu_verify_url(
        challenge: str,
    ) -> dict[str, str]:
        """Feishu URL verification endpoint.

        Feishu sends a challenge token to verify the webhook URL.
        """
        return {"challenge": challenge}

    @router.post(webhook_path)
    async def feishu_event(
        request: Request,
        event: FeishuEvent,
        client: FeishuClient = Depends(get_client),
        store: ApprovalStore = Depends(get_store),
        # signature_valid: bool = Depends(verify_signature),
    ) -> dict[str, Any]:
        """Handle incoming Feishu events.

        Supports:
        - im.message.receive_v1: Message receiving
        - im.message.message_read_v1: Message read receipts
        - im.chat.member.bot.added_v1: Bot added to chat
        - im.chat.member.bot.deleted_v1: Bot removed from chat
        """
        # Handle URL verification
        if event.challenge:
            return {"challenge": event.challenge}

        event_type = event.header.get("event_type", "")

        # Handle message events
        if event_type == "im.message.receive_v1":
            return await handle_message_event(event.event, client, store)

        # Handle other events (acknowledge but don't process)
        if event_type in (
            "im.message.message_read_v1",
            "im.chat.member.bot.added_v1",
            "im.chat.member.bot.deleted_v1",
        ):
            return {"code": 0}

        return {"code": 0, "msg": "Event type not handled"}

    async def handle_message_event(
        event_data: dict[str, Any],
        client: FeishuClient,
        store: ApprovalStore,
    ) -> dict[str, Any]:
        """Process incoming message event."""
        message = event_data.get("message", {})
        if not message:
            return {"code": 1, "msg": "No message in event"}

        message_id = message.get("message_id")
        message_type = message.get("message_type")
        chat_id = message.get("chat_id")
        sender = message.get("sender", {})
        user_id = sender.get("open_id", "")
        content = message.get("content", "")

        # Decode content (base64 encoded by Feishu)
        import base64

        try:
            text = base64.b64decode(content).decode("utf-8")
        except Exception:
            text = content

        # Parse command
        command, args = parse_command(text)

        # Handle commands
        if command == "approve":
            return await handle_approve(user_id, chat_id, args, client, store)
        elif command == "deny":
            return await handle_deny(user_id, chat_id, args, client, store)
        elif command == "status":
            return await handle_status(user_id, chat_id, client, store)
        elif command == "help":
            return await handle_help(user_id, chat_id, client)

        # Handle request approval link
        if command == "request":
            return await handle_request(user_id, chat_id, args, client, store)

        # Echo unknown commands
        if command:
            await client.send_text_message(
                user_id,
                f"Unknown command: /{command}. Use /help for available commands.",
            )
            return {"code": 0}

        # Default: echo back (for testing)
        await client.send_text_message(user_id, f"Received: {text}")
        return {"code": 0}

    async def handle_approve(
        user_id: str,
        chat_id: str,
        args: list[str],
        client: FeishuClient,
        store: ApprovalStore,
    ) -> dict[str, Any]:
        """Handle /approve command."""
        request_id = args[0] if args else ""

        if not request_id:
            # Find most recent pending approval
            approvals = store.get_pending_for_user(user_id)
            if not approvals:
                await client.send_text_message(
                    user_id,
                    "No pending approvals found. Use /request <description> to create one.",
                )
                return {"code": 0}
            approval = approvals[-1]
            request_id = approval.request_id

        approval = store.get_approval(request_id)
        if not approval:
            await client.send_text_message(
                user_id, f"Approval request not found: {request_id}"
            )
            return {"code": 0}

        # Update status
        store.update_status(request_id, "approved")

        await client.send_text_message(
            user_id,
            f"✅ Approved: {approval.title}\n\n"
            f"You can now check the agent status.",
        )

        return {"code": 0}

    async def handle_deny(
        user_id: str,
        chat_id: str,
        args: list[str],
        client: FeishuClient,
        store: ApprovalStore,
    ) -> dict[str, Any]:
        """Handle /deny command."""
        request_id = args[0] if args else ""

        if not request_id:
            approvals = store.get_pending_for_user(user_id)
            if not approvals:
                await client.send_text_message(
                    user_id,
                    "No pending approvals found.",
                )
                return {"code": 0}
            approval = approvals[-1]
            request_id = approval.request_id

        approval = store.get_approval(request_id)
        if not approval:
            await client.send_text_message(
                user_id, f"Approval request not found: {request_id}"
            )
            return {"code": 0}

        # Update status
        store.update_status(request_id, "denied")

        await client.send_text_message(
            user_id,
            f"❌ Denied: {approval.title}",
        )

        return {"code": 0}

    async def handle_status(
        user_id: str,
        chat_id: str,
        client: FeishuClient,
        store: ApprovalStore,
    ) -> dict[str, Any]:
        """Handle /status command."""
        approvals = store.get_pending_for_user(user_id)

        if not approvals:
            await client.send_text_message(
                user_id,
                "No pending approvals.",
            )
        else:
            status_lines = ["**Pending Approvals:**\n"]
            for a in approvals:
                status_lines.append(
                    f"- [{a.request_id}] {a.title}\n  {a.description[:50]}..."
                )
            await client.send_text_message(user_id, "\n".join(status_lines))

        return {"code": 0}

    async def handle_request(
        user_id: str,
        chat_id: str,
        args: list[str],
        client: FeishuClient,
        store: ApprovalStore,
    ) -> dict[str, Any]:
        """Handle /request command to create approval request."""
        description = " ".join(args) if args else "General approval requested"

        import uuid

        request_id = str(uuid.uuid4())[:8]

        # Create approval
        approval = store.create_approval(
            request_id=request_id,
            thread_id=user_id,
            user_id=user_id,
            chat_id=chat_id,
            title="Agent Approval Request",
            description=description,
            approve_url=f"/feishu/approve/{request_id}",
            deny_url=f"/feishu/deny/{request_id}",
        )

        # Send interactive card
        await client.send_approval_card(
            receive_id=user_id,
            title="🔔 Approval Request",
            description=f"**Request ID:** `{request_id}`\n\n{description}",
            approve_url=f"/feishu/approve/{request_id}",
            deny_url=f"/feishu/deny/{request_id}",
        )

        return {"code": 0}

    async def handle_help(
        user_id: str,
        chat_id: str,
        client: FeishuClient,
    ) -> dict[str, Any]:
        """Handle /help command."""
        help_text = """
**🤖 Agent System Commands**

Available commands:
- `/request <description>` - Create approval request
- `/approve [request_id]` - Approve pending request (uses most recent if not specified)
- `/deny [request_id]` - Deny pending request
- `/status` - List pending approvals
- `/help` - Show this help message

**Note:** When agent execution requires approval, you'll receive an interactive card.
        """.strip()

        await client.send_text_message(user_id, help_text)
        return {"code": 0}

    # Return router and dependencies
    deps = {
        "feishu_config": feishu_config,
        "app_secret": _app_secret,
        "webhook_path": webhook_path,
    }

    return router, deps


# ============================================================================
# App Factory
# =========================================================================


def create_app() -> tuple[Any, dict[str, Any]]:
    """Create FastAPI app with Feishu webhook.

    Returns:
        Tuple of (FastAPI app, dependency kwargs)
    """
    from fastapi import FastAPI

    app = FastAPI(title="Feishu Gateway")
    router, deps = create_feishu_router()

    app.include_router(router)

    return app, deps


# ============================================================================
# Entry Point
# =========================================================================


if __name__ == "__main__":
    import uvicorn

    app, _ = create_app()
    port = int(os.getenv("FEISHU_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
