"""Tests for the LLM provider abstraction layer."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from examples.agent_system.llm.provider import (
    DEFAULT_MODELS,
    LLMProvider,
    _PROVIDER_FACTORIES,
    get_default_llm,
    get_llm,
)


class TestLLMProvider:
    """Tests for LLMProvider enum."""

    def test_provider_values(self) -> None:
        """Test that provider enum has expected values."""
        assert LLMProvider.OPENAI.value == "openai"
        assert LLMProvider.ANTHROPIC.value == "anthropic"
        assert LLMProvider.ZHIPU.value == "zhipu"
        assert LLMProvider.MINIMAX.value == "minimax"
        assert LLMProvider.QWEN.value == "qwen"

    def test_default_models_defined(self) -> None:
        """Test that default models are defined for all providers."""
        for provider in LLMProvider:
            assert provider in DEFAULT_MODELS
            assert isinstance(DEFAULT_MODELS[provider], str)

    def test_all_providers_have_factories(self) -> None:
        """Test that all providers have factory functions."""
        for provider in LLMProvider:
            assert provider in _PROVIDER_FACTORIES


class TestGetLLM:
    """Tests for get_llm function."""

    def test_get_llm_openai_default(self) -> None:
        """Test getting OpenAI LLM with defaults."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        with patch.dict(
            _PROVIDER_FACTORIES, {LLMProvider.OPENAI: mock_factory}
        ):
            result = get_llm(provider="openai")

        mock_factory.assert_called_once_with(DEFAULT_MODELS[LLMProvider.OPENAI])
        assert result == mock_llm

    def test_get_llm_anthropic(self) -> None:
        """Test getting Anthropic LLM."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        with patch.dict(
            _PROVIDER_FACTORIES, {LLMProvider.ANTHROPIC: mock_factory}
        ):
            result = get_llm(provider="anthropic")

        mock_factory.assert_called_once_with(DEFAULT_MODELS[LLMProvider.ANTHROPIC])
        assert result == mock_llm

    def test_get_llm_custom_model(self) -> None:
        """Test getting LLM with custom model."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        with patch.dict(
            _PROVIDER_FACTORIES, {LLMProvider.OPENAI: mock_factory}
        ):
            result = get_llm(provider="openai", model="gpt-4")

        mock_factory.assert_called_once_with("gpt-4")
        assert result == mock_llm

    def test_get_llm_with_kwargs(self) -> None:
        """Test that kwargs are passed through."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        with patch.dict(
            _PROVIDER_FACTORIES, {LLMProvider.OPENAI: mock_factory}
        ):
            get_llm(provider="openai", temperature=0.5)

        mock_factory.assert_called_once_with(
            DEFAULT_MODELS[LLMProvider.OPENAI], temperature=0.5
        )

    def test_get_llm_invalid_provider(self) -> None:
        """Test that invalid provider raises ValueError."""
        with pytest.raises(ValueError, match="not a valid LLMProvider"):
            get_llm(provider="invalid_provider")

    def test_get_llm_from_env(self) -> None:
        """Test getting LLM based on environment variables."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        env_vars = {
            "AGENT_LLM_PROVIDER": "openai",
            "AGENT_LLM_MODEL": "gpt-4-turbo",
        }
        with (
            patch.dict(os.environ, env_vars, clear=False),
            patch.dict(_PROVIDER_FACTORIES, {LLMProvider.OPENAI: mock_factory}),
        ):
            result = get_llm()

        mock_factory.assert_called_once_with("gpt-4-turbo")
        assert result == mock_llm

    def test_get_llm_provider_enum(self) -> None:
        """Test that LLMProvider enum can be passed directly."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        with patch.dict(
            _PROVIDER_FACTORIES, {LLMProvider.OPENAI: mock_factory}
        ):
            result = get_llm(provider=LLMProvider.OPENAI)

        assert result == mock_llm


class TestGetDefaultLLM:
    """Tests for get_default_llm function."""

    @patch("examples.agent_system.llm.provider.get_llm")
    def test_get_default_llm_delegates(self, mock_get_llm: MagicMock) -> None:
        """Test that get_default_llm delegates to get_llm."""
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        result = get_default_llm(temperature=0.7)

        mock_get_llm.assert_called_once_with(temperature=0.7)
        assert result == mock_llm


class TestLLMCreation:
    """Integration tests for actual LLM creation (requires mocking)."""

    def test_openai_missing_api_key(self) -> None:
        """Test that OpenAI raises error without API key."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing key
            os.environ.pop("OPENAI_API_KEY", None)
            with pytest.raises(ValueError, match="OpenAI API key required"):
                get_llm(provider="openai")

    def test_anthropic_missing_api_key(self) -> None:
        """Test that Anthropic raises error without API key."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing key
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(ValueError, match="Anthropic API key required"):
                get_llm(provider="anthropic")

    def test_zhipu_missing_api_key(self) -> None:
        """Test that ZhipuAI raises error without API key."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ZHIPU_API_KEY", None)
            with pytest.raises(ValueError, match="ZhipuAI API key required"):
                get_llm(provider="zhipu")

    def test_minimax_missing_api_key(self) -> None:
        """Test that Minimax raises error without API key."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MINIMAX_API_KEY", None)
            with pytest.raises(ValueError, match="Minimax API key required"):
                get_llm(provider="minimax")

    def test_qwen_missing_api_key(self) -> None:
        """Test that Qwen (DashScope) raises error without API key."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DASHSCOPE_API_KEY", None)
            with pytest.raises(ValueError, match="Qwen.*API key required"):
                get_llm(provider="qwen")


class TestNewProviderFactories:
    """Tests for new provider factory functions."""

    def test_get_llm_zhipu(self) -> None:
        """Test getting ZhipuAI LLM."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        with patch.dict(
            _PROVIDER_FACTORIES, {LLMProvider.ZHIPU: mock_factory}
        ):
            result = get_llm(provider="zhipu")

        mock_factory.assert_called_once_with(DEFAULT_MODELS[LLMProvider.ZHIPU])
        assert result == mock_llm

    def test_get_llm_minimax(self) -> None:
        """Test getting Minimax LLM."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        with patch.dict(
            _PROVIDER_FACTORIES, {LLMProvider.MINIMAX: mock_factory}
        ):
            result = get_llm(provider="minimax")

        mock_factory.assert_called_once_with(DEFAULT_MODELS[LLMProvider.MINIMAX])
        assert result == mock_llm

    def test_get_llm_qwen(self) -> None:
        """Test getting Qwen LLM."""
        mock_factory = MagicMock()
        mock_llm = MagicMock()
        mock_factory.return_value = mock_llm

        with patch.dict(
            _PROVIDER_FACTORIES, {LLMProvider.QWEN: mock_factory}
        ):
            result = get_llm(provider="qwen")

        mock_factory.assert_called_once_with(DEFAULT_MODELS[LLMProvider.QWEN])
        assert result == mock_llm
