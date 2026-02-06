"""Tests for configuration management."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from examples.agent_system.config import (
    AgentConfig,
    Config,
    LLMConfig,
    ObservabilityConfig,
    get_config,
    reset_config,
)
from examples.agent_system.llm.provider import DEFAULT_MODELS, LLMProvider


class TestLLMConfig:
    """Tests for LLMConfig."""

    def test_from_env_defaults(self) -> None:
        """Test default values when no env vars set."""
        with patch.dict(os.environ, {}, clear=True):
            config = LLMConfig.from_env()

        assert config.provider == LLMProvider.OPENAI
        assert config.model == DEFAULT_MODELS[LLMProvider.OPENAI]
        assert config.temperature == 0.0
        assert config.max_tokens is None

    def test_from_env_custom_values(self) -> None:
        """Test custom values from environment."""
        env_vars = {
            "AGENT_LLM_PROVIDER": "anthropic",
            "AGENT_LLM_MODEL": "claude-3-opus-20240229",
            "AGENT_LLM_TEMPERATURE": "0.7",
            "AGENT_LLM_MAX_TOKENS": "4096",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = LLMConfig.from_env()

        assert config.provider == LLMProvider.ANTHROPIC
        assert config.model == "claude-3-opus-20240229"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096

    def test_from_env_invalid_provider(self) -> None:
        """Test invalid provider raises error."""
        with patch.dict(os.environ, {"AGENT_LLM_PROVIDER": "invalid"}, clear=True):
            with pytest.raises(ValueError):
                LLMConfig.from_env()


class TestAgentConfig:
    """Tests for AgentConfig."""

    def test_from_env_defaults(self) -> None:
        """Test default values."""
        with patch.dict(os.environ, {}, clear=True):
            config = AgentConfig.from_env()

        assert config.max_iterations == 10
        assert config.timeout_seconds == 300
        assert config.retry_on_error is True
        assert config.max_retries == 3

    def test_from_env_custom_values(self) -> None:
        """Test custom values from environment."""
        env_vars = {
            "AGENT_MAX_ITERATIONS": "20",
            "AGENT_TIMEOUT_SECONDS": "600",
            "AGENT_RETRY_ON_ERROR": "false",
            "AGENT_MAX_RETRIES": "5",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = AgentConfig.from_env()

        assert config.max_iterations == 20
        assert config.timeout_seconds == 600
        assert config.retry_on_error is False
        assert config.max_retries == 5


class TestObservabilityConfig:
    """Tests for ObservabilityConfig."""

    def test_from_env_defaults(self) -> None:
        """Test default values."""
        with patch.dict(os.environ, {}, clear=True):
            config = ObservabilityConfig.from_env()

        assert config.tracing_enabled is False
        assert config.project_name == "agent-system"
        assert config.log_level == "INFO"

    def test_from_env_custom_values(self) -> None:
        """Test custom values from environment."""
        env_vars = {
            "LANGCHAIN_TRACING_V2": "true",
            "LANGCHAIN_PROJECT": "my-project",
            "AGENT_LOG_LEVEL": "DEBUG",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = ObservabilityConfig.from_env()

        assert config.tracing_enabled is True
        assert config.project_name == "my-project"
        assert config.log_level == "DEBUG"

    def test_from_env_invalid_log_level_defaults_to_info(self) -> None:
        """Test invalid log level falls back to INFO."""
        with patch.dict(os.environ, {"AGENT_LOG_LEVEL": "INVALID"}, clear=True):
            config = ObservabilityConfig.from_env()

        assert config.log_level == "INFO"


class TestConfig:
    """Tests for root Config."""

    def test_from_env_creates_all_sub_configs(self) -> None:
        """Test that from_env creates all sub-configurations."""
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        assert isinstance(config.llm, LLMConfig)
        assert isinstance(config.agent, AgentConfig)
        assert isinstance(config.observability, ObservabilityConfig)


class TestGetConfig:
    """Tests for get_config function."""

    def setup_method(self) -> None:
        """Reset config before each test."""
        reset_config()

    def teardown_method(self) -> None:
        """Reset config after each test."""
        reset_config()

    def test_get_config_returns_config(self) -> None:
        """Test that get_config returns a Config instance."""
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()

        assert isinstance(config, Config)

    def test_get_config_caches_result(self) -> None:
        """Test that get_config returns the same instance."""
        with patch.dict(os.environ, {}, clear=True):
            config1 = get_config()
            config2 = get_config()

        assert config1 is config2

    def test_get_config_reload(self) -> None:
        """Test that reload=True creates new config."""
        with patch.dict(os.environ, {"AGENT_LLM_PROVIDER": "openai"}, clear=True):
            config1 = get_config()

        with patch.dict(os.environ, {"AGENT_LLM_PROVIDER": "anthropic"}, clear=True):
            config2 = get_config(reload=True)

        assert config1 is not config2
        assert config1.llm.provider == LLMProvider.OPENAI
        assert config2.llm.provider == LLMProvider.ANTHROPIC


class TestResetConfig:
    """Tests for reset_config function."""

    def test_reset_config_clears_cache(self) -> None:
        """Test that reset_config clears the cached config."""
        with patch.dict(os.environ, {"AGENT_LLM_PROVIDER": "openai"}, clear=True):
            config1 = get_config()

        reset_config()

        with patch.dict(os.environ, {"AGENT_LLM_PROVIDER": "anthropic"}, clear=True):
            config2 = get_config()

        assert config1 is not config2
        assert config2.llm.provider == LLMProvider.ANTHROPIC
