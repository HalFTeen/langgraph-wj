"""LLM Provider abstraction using langchain-core ChatModel interface.

This module provides a unified interface for accessing different LLM providers
(OpenAI, Anthropic, etc.) through the langchain-core ChatModel abstraction.

Usage:
    from examples.agent_system.llm import get_llm

    # Get default LLM (from environment)
    llm = get_llm()

    # Get specific provider
    llm = get_llm(provider="openai", model="gpt-4")
    llm = get_llm(provider="anthropic", model="claude-3-sonnet-20240229")

    # Use the LLM
    response = llm.invoke([HumanMessage(content="Hello")])
"""

from __future__ import annotations

import os
from enum import Enum
from typing import TYPE_CHECKING

from langchain_core.language_models.chat_models import BaseChatModel

if TYPE_CHECKING:
    pass


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    ZHIPU = "zhipu"
    MINIMAX = "minimax"
    QWEN = "qwen"


# Default models for each provider
DEFAULT_MODELS: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "gpt-4o-mini",
    LLMProvider.ANTHROPIC: "claude-3-5-sonnet-20241022",
    LLMProvider.ZHIPU: "glm-4-plus",
    LLMProvider.MINIMAX: "abab6.5s-chat",
    LLMProvider.QWEN: "qwen-turbo",
}


def _create_openai_llm(model: str, **kwargs) -> BaseChatModel:
    """Create an OpenAI ChatModel instance."""
    from langchain_openai import ChatOpenAI

    api_key = kwargs.pop("api_key", None) or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OpenAI API key required. Set OPENAI_API_KEY environment variable "
            "or pass api_key parameter."
        )

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        temperature=kwargs.pop("temperature", 0.0),
        **kwargs,
    )


def _create_anthropic_llm(model: str, **kwargs) -> BaseChatModel:
    """Create an Anthropic ChatModel instance."""
    from langchain_anthropic import ChatAnthropic

    api_key = kwargs.pop("api_key", None) or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
            "or pass api_key parameter."
        )

    return ChatAnthropic(
        model=model,
        api_key=api_key,
        temperature=kwargs.pop("temperature", 0.0),
        **kwargs,
    )


def _create_zhipu_llm(model: str, **kwargs) -> BaseChatModel:
    """Create a ZhipuAI (ChatGLM) ChatModel instance."""
    try:
        from langchain_community.chat_models import ChatZhipuAI
    except ImportError:
        raise ValueError(
            "ZhipuAI integration not installed. Install with: pip install langchain-community zhipuai"
        )

    api_key = kwargs.pop("api_key", None) or os.getenv("ZHIPU_API_KEY")
    if not api_key:
        raise ValueError(
            "ZhipuAI API key required. Set ZHIPU_API_KEY environment variable "
            "or pass api_key parameter."
        )

    return ChatZhipuAI(
        model=model,
        api_key=api_key,
        temperature=kwargs.pop("temperature", 0.0),
        **kwargs,
    )


def _create_minimax_llm(model: str, **kwargs) -> BaseChatModel:
    """Create a Minimax ChatModel instance."""
    try:
        from langchain_community.chat_models import ChatMinimax
    except ImportError:
        raise ValueError(
            "Minimax integration not installed. Install with: pip install langchain-community"
        )

    api_key = kwargs.pop("api_key", None) or os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError(
            "Minimax API key required. Set MINIMAX_API_KEY environment variable "
            "or pass api_key parameter."
        )

    base_url = kwargs.pop("base_url", None) or os.getenv("MINIMAX_BASE_URL")

    return ChatMinimax(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=kwargs.pop("temperature", 0.0),
        **kwargs,
    )


def _create_qwen_llm(model: str, **kwargs) -> BaseChatModel:
    """Create a Qwen (DashScope) ChatModel instance."""
    try:
        from langchain_community.chat_models import ChatQwen
    except ImportError:
        raise ValueError(
            "Qwen (DashScope) integration not installed. Install with: pip install langchain-community"
        )

    api_key = kwargs.pop("api_key", None) or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError(
            "Qwen (DashScope) API key required. Set DASHSCOPE_API_KEY environment variable "
            "or pass api_key parameter."
        )

    return ChatQwen(
        model=model,
        api_key=api_key,
        temperature=kwargs.pop("temperature", 0.0),
        **kwargs,
    )


_PROVIDER_FACTORIES = {
    LLMProvider.OPENAI: _create_openai_llm,
    LLMProvider.ANTHROPIC: _create_anthropic_llm,
    LLMProvider.ZHIPU: _create_zhipu_llm,
    LLMProvider.MINIMAX: _create_minimax_llm,
    LLMProvider.QWEN: _create_qwen_llm,
}


def get_llm(
    provider: str | LLMProvider | None = None,
    model: str | None = None,
    **kwargs,
) -> BaseChatModel:
    """Get an LLM instance for the specified provider.

    Args:
        provider: LLM provider name ("openai", "anthropic"). If None, uses
            AGENT_LLM_PROVIDER environment variable, defaulting to "openai".
        model: Model name. If None, uses provider's default model.
        **kwargs: Additional arguments passed to the LLM constructor
            (temperature, api_key, etc.)

    Returns:
        A langchain-core BaseChatModel instance.

    Raises:
        ValueError: If the provider is not supported or API key is missing.

    Examples:
        >>> llm = get_llm()  # Uses default provider and model
        >>> llm = get_llm(provider="anthropic")
        >>> llm = get_llm(provider="openai", model="gpt-4", temperature=0.5)
    """
    # Determine provider
    if provider is None:
        provider_str = os.getenv("AGENT_LLM_PROVIDER", "openai")
        provider = LLMProvider(provider_str.lower())
    elif isinstance(provider, str):
        provider = LLMProvider(provider.lower())

    # Determine model
    if model is None:
        model = os.getenv("AGENT_LLM_MODEL") or DEFAULT_MODELS[provider]

    # Get factory and create LLM
    factory = _PROVIDER_FACTORIES.get(provider)
    if factory is None:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported providers: {list(LLMProvider)}"
        )

    return factory(model, **kwargs)


def get_default_llm(**kwargs) -> BaseChatModel:
    """Get the default LLM based on environment configuration.

    This is a convenience function that calls get_llm() with no provider/model
    arguments, using environment variables for configuration.

    Environment variables:
        AGENT_LLM_PROVIDER: "openai" or "anthropic" (default: "openai")
        AGENT_LLM_MODEL: Model name (default: provider's default)
        OPENAI_API_KEY: Required if using OpenAI
        ANTHROPIC_API_KEY: Required if using Anthropic

    Args:
        **kwargs: Additional arguments passed to get_llm()

    Returns:
        A langchain-core BaseChatModel instance.
    """
    return get_llm(**kwargs)
