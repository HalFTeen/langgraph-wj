"""Feishu/Lark API client for approval requests and messaging.

This module provides a client for interacting with the Feishu Open Platform API,
including tenant token management, message sending, and approval card formatting.

Usage:
    from examples.agent_system.gateway.feishu_client import FeishuClient

    client = FeishuClient(app_id="cli_xxx", app_secret="yyy")
    client.send_approval_request(
        chat_id="oc_xxx",
        title="Code Review Request",
        description="Please review the generated code",
        approve_url="https://...",
        deny_url="https://...",
    )
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class FeishuConfig:
    """Configuration for Feishu client."""

    app_id: str
    app_secret: str
    domain: str = "feishu"  # "feishu" for China, "lark" for international

    @classmethod
    def from_env(cls) -> "FeishuConfig | None":
        """Create config from environment variables.

        Returns None if app_id is not configured.
        """
        app_id = os.getenv("FEISHU_APP_ID")
        if not app_id:
            return None

        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        domain = os.getenv("FEISHU_DOMAIN", "feishu")

        return cls(app_id=app_id, app_secret=app_secret, domain=domain)

    def get_base_url(self) -> str:
        """Get the API base URL based on domain."""
        if self.domain == "feishu":
            return "https://open.feishu.cn"
        elif self.domain == "lark":
            return "https://open.larksuite.com"
        else:
            # Custom domain (e.g., private deployment)
            return self.domain.rstrip("/")


class FeishuClient:
    """Client for Feishu Open Platform API.

    Handles authentication, tenant token caching, and API requests.
    """

    def __init__(self, config: FeishuConfig) -> None:
        """Initialize the Feishu client.

        Args:
            config: Feishu configuration (required).
        """
        self.config = config
        self._tenant_access_token: str | None = None
        self._token_expires_at: float = 0

    def _get_base_url(self) -> str:
        """Get the API base URL."""
        assert self.config is not None, "Feishu config is not initialized"
        return self.config.get_base_url()

    def _get_tenant_access_token(self) -> str:
        """Get cached tenant access token or fetch a new one."""
        now = time.time()
        if self._tenant_access_token and now < self._token_expires_at - 60:
            return self._tenant_access_token

        # Fetch new token
        url = f"{self._get_base_url()}/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.config.app_id,
            "app_secret": self.config.app_secret,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get tenant access token: {data}")

        self._tenant_access_token = data["tenant_access_token"]
        # Token typically expires in 2 hours, refresh slightly earlier
        self._token_expires_at = now + 7200 - 300
        return self._tenant_access_token

    def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> dict[str, Any]:
        """Make an authenticated API request."""
        token = self._get_tenant_access_token()
        url = f"{self._get_base_url()}/open-apis{endpoint}"

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json"

        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method, url, headers=headers, **kwargs
            )
            response.raise_for_status()
            return response.json()

    def send_message(
        self,
        receive_id: str,
        msg_type: str = "text",
        content: str | dict[str, Any] | None = None,
        *,
        chat_type: str = "p2p",
    ) -> dict[str, Any]:
        """Send a message to a user or chat.

        Args:
            receive_id: The user_id or chat_id to send to
            msg_type: Message type (text, card, etc.)
            content: Message content
            chat_type: "p2p" for direct message, "group" for group chat

        Returns:
            API response data
        """
        payload: dict[str, Any] = {
            "receive_id": receive_id,
            "msg_type": msg_type,
        }
        if isinstance(content, dict):
            payload["content"] = content
        elif content is not None:
            payload["content"] = content

        # Use different endpoint for cards
        if msg_type == "card":
            endpoint = "/im/v1/messages/cards"
            params = {"receive_id_type": "open_id"}
        else:
            endpoint = "/im/v1/messages"
            params = {"receive_id_type": "open_id" if chat_type == "p2p" else "chat_id"}

        return self._request("POST", f"{endpoint}?{params}", json=payload)

    def send_text_message(
        self, receive_id: str, text: str, *, chat_type: str = "p2p"
    ) -> dict[str, Any]:
        """Send a text message.

        Args:
            receive_id: The user_id or chat_id
            text: Text content
            chat_type: "p2p" or "group"

        Returns:
            API response
        """
        import json

        content = json.dumps({"text": text})
        return self.send_message(
            receive_id, msg_type="text", content=content, chat_type=chat_type
        )

    def send_approval_card(
        self,
        receive_id: str,
        title: str,
        description: str,
        approve_url: str,
        deny_url: str,
        *,
        extra_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an interactive approval card message.

        This creates a rich card with approve/deny buttons for human-in-the-loop control.

        Args:
            receive_id: The user_id or chat_id
            title: Card title
            description: Card description
            approve_url: URL to handle approval
            deny_url: URL to handle denial
            extra_info: Additional information to include

        Returns:
            API response
        """
        import json

        # Build card content with interactive buttons
        card_content: dict[str, Any] = {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {"title": {"tag": "plain_text", "content": title}},
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": description,
                    },
                },
            ],
        }

        # Add extra info if provided
        if extra_info:
            extra_lines = []
            for key, value in extra_info.items():
                extra_lines.append(f"**{key}:** {value}")
            if extra_lines:
                card_content["elements"].append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "\n".join(extra_lines),
                        },
                    }
                )

        # Add action buttons
        card_content["elements"].extend(
            [
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "✅ Approve"},
                            "type": "primary",
                            "url": approve_url,
                            "action_id": "approve",
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "❌ Deny"},
                            "type": "default",
                            "url": deny_url,
                            "action_id": "deny",
                        },
                    ],
                },
            ]
        )

        content = json.dumps(card_content)

        # Use card message type for rich interactivity
        return self.send_message(receive_id, msg_type="card", content=content)

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get user information.

        Args:
            user_id: The user ID (open_id)

        Returns:
            User info dictionary
        """
        return self._request(
            "GET", f"/contact/v3/users/{user_id}"
        )

    def revoke_message(self, message_id: str) -> dict[str, Any]:
        """Recall (delete) a sent message.

        Args:
            message_id: The message ID to revoke

        Returns:
            API response
        """
        return self._request(
            "DELETE", f"/im/v1/messages/{message_id}"
        )

    def update_message(
        self, message_id: str, content: str | dict[str, Any]
    ) -> dict[str, Any]:
        """Update a sent message.

        Args:
            message_id: The message ID to update
            content: New content

        Returns:
            API response
        """
        import json

        if isinstance(content, dict):
            content = json.dumps(content)

        return self._request(
            "PUT",
            f"/im/v1/messages/{message_id}",
            json={"content": content},
        )


def get_feishu_client() -> "FeishuClient | None":
    """Get a FeishuClient instance from environment configuration.

    Returns:
        Configured FeishuClient instance, or None if not configured
    """
    config = FeishuConfig.from_env()
    if config is None:
        return None
    return FeishuClient(config=config)
