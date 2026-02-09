from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DiscordCommand(Enum):
    """Discord commands supported by the bot."""
    APPROVE = "approve"
    DENY = "deny"
    STATUS = "status"
    TASK = "task"
    ASK_USER = "ask"
    CONFIRM_ACTION = "confirm"


@dataclass
class DiscordConfig:
    token: str
    channel_id: str


class DiscordGateway:
    def __init__(self, config: DiscordConfig) -> None:
        self.config = config

    def post_approval_request(self, thread_id: str, summary: str) -> None:
        if not self.config.token or not self.config.channel_id:
            raise ValueError("Discord token/channel_id required")

        url = f"https://discord.com/api/v10/channels/{self.config.channel_id}/messages"
        payload = {
            "content": (
                "Approval request\n"
                f"Thread: {thread_id}\n"
                f"Summary: {summary}\n"
                "Reply with: approve <thread_id> or deny <thread_id> <reason>"
            )
        }
        headers = {
            "Authorization": f"Bot {self.config.token}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Discord post failed: {response.status_code} {response.text}"
            )


def _parse_command(content: str) -> tuple[str, str, str | None] | None:
    parts = content.strip().split()
    if len(parts) < 2:
        return None
    command = parts[0].lower()
    thread_id = parts[1]
    if command not in {"approve", "deny"}:
        return None
    reason = " ".join(parts[2:]) if len(parts) > 2 else None
    return command, thread_id, reason


class DiscordBotRunner:
    def __init__(self, config: DiscordConfig, *, gateway_url: str) -> None:
        self.config = config
        self.gateway_url = gateway_url.rstrip("/")

    async def run(self) -> None:
        try:
            import discord
        except ImportError as exc:
            raise RuntimeError("discord.py is required to run the bot") from exc

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        async def _resolve(decision: str, thread_id: str, reason: str | None) -> None:
            import httpx

            payload: dict[str, Any] = {
                "thread_id": thread_id,
                "decision": "approved" if decision == "approve" else "denied",
                "reviewer": "discord",
                "reason": reason,
            }
            async with httpx.AsyncClient() as http:
                await http.post(f"{self.gateway_url}/approval/resolve", json=payload)

        @client.event
        async def on_message(message) -> None:
            if message.author == client.user:
                return
            parsed = _parse_command(message.content)
            if not parsed:
                return
            command, thread_id, reason = parsed
            await _resolve(command, thread_id, reason)
            await message.channel.send(
                f"Recorded {command} for thread {thread_id}."
            )

        await client.start(self.config.token)
