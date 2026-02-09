"""Configuration management for the agent system.

This module provides centralized configuration for the agent system,
supporting environment variables with sensible defaults.

Usage:
    from examples.agent_system.config import get_config, AgentConfig

    # Get full configuration
    config = get_config()
    print(config.llm.provider)
    print(config.llm.model)

    # Override via environment
    # AGENT_LLM_PROVIDER=anthropic
    # AGENT_LLM_MODEL=claude-3-5-sonnet-20241022
    # AGENT_LLM_TEMPERATURE=0.5

Environment Variables:
    LLM Configuration:
        AGENT_LLM_PROVIDER: LLM provider ("openai", "anthropic", "zhipu", "minimax", "qwen"). Default: "openai"
        AGENT_LLM_MODEL: Model name. Default: provider's default model
        AGENT_LLM_TEMPERATURE: Temperature for generation. Default: 0.0
        OPENAI_API_KEY: OpenAI API key (required if using OpenAI)
        ANTHROPIC_API_KEY: Anthropic API key (required if using Anthropic)
        ZHIPU_API_KEY: ZhipuAI API key (required if using zhipu)
        MINIMAX_API_KEY: Minimax API key (required if using minimax)
        MINIMAX_BASE_URL: Minimax API base URL (optional)
        DASHSCOPE_API_KEY: Alibaba DashScope API key (required if using qwen)

    Agent Configuration:
        AGENT_MAX_ITERATIONS: Maximum loop iterations. Default: 10
        AGENT_TIMEOUT_SECONDS: Timeout for each step. Default: 300

    Feishu Configuration:
        FEISHU_APP_ID: Feishu app ID (required for Feishu integration)
        FEISHU_APP_SECRET: Feishu app secret (required for Feishu integration)
        FEISHU_DOMAIN: Feishu domain ("feishu" for China, "lark" for international). Default: "feishu"
        FEISHU_WEBHOOK_PATH: Webhook path for Feishu events. Default: "/feishu/events"
        FEISHU_PORT: Port for Feishu webhook server. Default: 8001

    Observability:
        LANGCHAIN_TRACING_V2: Enable LangSmith tracing. Default: false
        LANGCHAIN_PROJECT: LangSmith project name. Default: "agent-system"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from examples.agent_system.llm.provider import DEFAULT_MODELS, LLMProvider


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for LLM provider."""

    provider: LLMProvider
    model: str
    temperature: float = 0.0
    max_tokens: int | None = None

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Create LLMConfig from environment variables."""
        provider_str = os.getenv("AGENT_LLM_PROVIDER", "openai").lower()
        provider = LLMProvider(provider_str)

        model = os.getenv("AGENT_LLM_MODEL") or DEFAULT_MODELS[provider]
        temperature = float(os.getenv("AGENT_LLM_TEMPERATURE", "0.0"))
        max_tokens_str = os.getenv("AGENT_LLM_MAX_TOKENS")
        max_tokens = int(max_tokens_str) if max_tokens_str else None

        return cls(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for agent behavior."""

    max_iterations: int = 10
    timeout_seconds: int = 300
    retry_on_error: bool = True
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> AgentConfig:
        """Create AgentConfig from environment variables."""
        return cls(
            max_iterations=int(os.getenv("AGENT_MAX_ITERATIONS", "10")),
            timeout_seconds=int(os.getenv("AGENT_TIMEOUT_SECONDS", "300")),
            retry_on_error=os.getenv("AGENT_RETRY_ON_ERROR", "true").lower() == "true",
            max_retries=int(os.getenv("AGENT_MAX_RETRIES", "3")),
        )


@dataclass(frozen=True)
class ObservabilityConfig:
    """Configuration for observability and tracing."""

    tracing_enabled: bool = False
    project_name: str = "agent-system"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @classmethod
    def from_env(cls) -> ObservabilityConfig:
        """Create ObservabilityConfig from environment variables."""
        tracing_enabled = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
        project_name = os.getenv("LANGCHAIN_PROJECT", "agent-system")
        log_level = os.getenv("AGENT_LOG_LEVEL", "INFO").upper()

        # Validate log level
        valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR")
        if log_level not in valid_levels:
            log_level = "INFO"

        return cls(
            tracing_enabled=tracing_enabled,
            project_name=project_name,
            log_level=log_level,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class FeishuConfig:
    """Configuration for Feishu integration."""

    app_id: str
    app_secret: str
    domain: str = "feishu"
    webhook_path: str = "/feishu/events"
    port: int = 8001
    enabled: bool = False

    @classmethod
    def from_env(cls) -> FeishuConfig | None:
        """Create FeishuConfig from environment variables.

        Returns None if app_id is not configured (Feishu not enabled).
        """
        app_id = os.getenv("FEISHU_APP_ID")
        if not app_id:
            return None

        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        domain = os.getenv("FEISHU_DOMAIN", "feishu")
        webhook_path = os.getenv("FEISHU_WEBHOOK_PATH", "/feishu/events")
        port = int(os.getenv("FEISHU_PORT", "8001"))
        enabled = os.getenv("FEISHU_ENABLED", "false").lower() == "true"

        return cls(
            app_id=app_id,
            app_secret=app_secret,
            domain=domain,
            webhook_path=webhook_path,
            port=port,
            enabled=enabled,
        )


@dataclass(frozen=True)
class DiscordConfig:
    """Configuration for Discord integration."""

    bot_token: str
    guild_id: str
    channel_id: str
    webhook_url: str | None = None
    enabled: bool = False

    @classmethod
    def from_env(cls) -> DiscordConfig | None:
        """Create DiscordConfig from environment variables.

        Returns None if bot_token is not configured (Discord not enabled).
        """
        bot_token = os.getenv("DISCORD_BOT_TOKEN")
        if not bot_token:
            return None

        guild_id = os.getenv("DISCORD_GUILD_ID", "")
        channel_id = os.getenv("DISCORD_CHANNEL_ID", "")
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        enabled = os.getenv("DISCORD_ENABLED", "false").lower() == "true"

        return cls(
            bot_token=bot_token,
            guild_id=guild_id,
            channel_id=channel_id,
            webhook_url=webhook_url,
            enabled=enabled,
        )


@dataclass(frozen=True)
class GatewayConfig:
    """Configuration for gateway services."""

    feishu: FeishuConfig | None = None
    discord: DiscordConfig | None = None

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        """Create GatewayConfig from environment variables."""
        return cls(
            feishu=FeishuConfig.from_env(),
            discord=DiscordConfig.from_env(),
        )


@dataclass(frozen=True)
class Config:
    """Root configuration for the agent system."""

    llm: LLMConfig
    agent: AgentConfig
    observability: ObservabilityConfig
    gateway: GatewayConfig

    @classmethod
    def from_env(cls) -> Config:
        """Create full Config from environment variables."""
        return cls(
            llm=LLMConfig.from_env(),
            agent=AgentConfig.from_env(),
            observability=ObservabilityConfig.from_env(),
            gateway=GatewayConfig.from_env(),
        )


# Singleton pattern for global config access
_config: Config | None = None


def get_config(*, reload: bool = False) -> Config:
    """Get the global configuration.

    Args:
        reload: If True, reload configuration from environment.
            Default False uses cached config.

    Returns:
        The global Config instance.

    Example:
        >>> config = get_config()
        >>> print(config.llm.provider)
        LLMProvider.OPENAI
    """
    global _config
    if _config is None or reload:
        _config = Config.from_env()
    return _config


def reset_config() -> None:
    """Reset the global configuration.

    Useful for testing to ensure fresh config on each test.
    """
    global _config
    _config = None
