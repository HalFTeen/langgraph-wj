from __future__ import annotations

import asyncio
import os

from examples.agent_system.gateway.discord_bot import DiscordBotRunner, DiscordConfig


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "")
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "")
    gateway_url = os.getenv("GATEWAY_URL", "http://localhost:8000")
    runner = DiscordBotRunner(
        DiscordConfig(token=token, channel_id=channel_id), gateway_url=gateway_url
    )
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
