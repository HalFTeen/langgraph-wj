"""Tests for LLM-powered node implementations."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage, SystemMessage

from examples.agent_system.nodes import (
    _extract_code_from_response,
    _extract_task_from_messages,
    _fallback_coder,
    _fallback_reviewer,
    _parse_review_decision,
    create_coder_node,
    create_reviewer_node,
)


class TestExtractTaskFromMessages:
    """Tests for _extract_task_from_messages helper."""

    def test_extracts_human_message_content(self) -> None:
        """Test that human message content is extracted."""
        state = {
            "messages": [
                SystemMessage(content="System prompt"),
                HumanMessage(content="Implement a calculator"),
            ]
        }
        result = _extract_task_from_messages(state)
        assert result == "Implement a calculator"

    def test_returns_first_human_message(self) -> None:
        """Test that first human message is returned."""
        state = {
            "messages": [
                HumanMessage(content="First task"),
                HumanMessage(content="Second task"),
            ]
        }
        result = _extract_task_from_messages(state)
        assert result == "First task"

    def test_returns_default_when_no_human_message(self) -> None:
        """Test that default is returned when no human message."""
        state = {"messages": [SystemMessage(content="Only system")]}
        result = _extract_task_from_messages(state)
        assert result == "No task specified"

    def test_handles_empty_messages(self) -> None:
        """Test handling of empty messages list."""
        state = {"messages": []}
        result = _extract_task_from_messages(state)
        assert result == "No task specified"


class TestExtractCodeFromResponse:
    """Tests for _extract_code_from_response helper."""

    def test_extracts_from_python_code_block(self) -> None:
        """Test extraction from ```python code block."""
        response = '```python\ndef add(a, b):\n    return a + b\n```'
        result = _extract_code_from_response(response)
        assert result == "def add(a, b):\n    return a + b"

    def test_extracts_from_generic_code_block(self) -> None:
        """Test extraction from ``` code block without language."""
        response = '```\ndef add(a, b):\n    return a + b\n```'
        result = _extract_code_from_response(response)
        assert result == "def add(a, b):\n    return a + b"

    def test_returns_raw_code_if_no_block(self) -> None:
        """Test that raw code is returned if no markdown block."""
        response = "def add(a, b):\n    return a + b"
        result = _extract_code_from_response(response)
        assert result == "def add(a, b):\n    return a + b"

    def test_strips_whitespace(self) -> None:
        """Test that result is stripped of whitespace."""
        response = '```python\n\n  def foo(): pass  \n\n```'
        result = _extract_code_from_response(response)
        assert result == "def foo(): pass"


class TestParseReviewDecision:
    """Tests for _parse_review_decision helper."""

    def test_recognizes_approved(self) -> None:
        """Test that APPROVED is recognized."""
        response = "APPROVED - the code looks good."
        status, feedback = _parse_review_decision(response)
        assert status == "approved"
        assert feedback == response

    def test_recognizes_changes_requested(self) -> None:
        """Test that CHANGES_REQUESTED is recognized."""
        response = "CHANGES_REQUESTED - please fix the bug."
        status, feedback = _parse_review_decision(response)
        assert status == "changes"
        assert feedback == response

    def test_changes_requested_with_space(self) -> None:
        """Test recognition of CHANGES REQUESTED (with space)."""
        response = "CHANGES REQUESTED: missing error handling"
        status, feedback = _parse_review_decision(response)
        assert status == "changes"

    def test_defaults_to_changes_if_unclear(self) -> None:
        """Test that unclear response defaults to changes."""
        response = "Not sure about this code..."
        status, feedback = _parse_review_decision(response)
        assert status == "changes"

    def test_changes_requested_takes_precedence(self) -> None:
        """Test that CHANGES_REQUESTED takes precedence over APPROVED."""
        response = "Almost APPROVED but CHANGES_REQUESTED for edge cases."
        status, feedback = _parse_review_decision(response)
        assert status == "changes"


class TestFallbackCoder:
    """Tests for fallback coder implementation."""

    def test_first_iteration_returns_bad_code(self) -> None:
        """Test that first iteration returns intentionally bad code."""
        state = {"iteration_count": 0, "code_files": {}}
        result = _fallback_coder(state)

        assert "TODO" in result["code_files"]["app.py"]
        assert "return a - b" in result["code_files"]["app.py"]
        assert result["iteration_count"] == 1

    def test_subsequent_iterations_return_good_code(self) -> None:
        """Test that subsequent iterations return correct code."""
        state = {"iteration_count": 1, "code_files": {"app.py": "old code"}}
        result = _fallback_coder(state)

        assert "return a + b" in result["code_files"]["app.py"]
        assert "TODO" not in result["code_files"]["app.py"]
        assert result["iteration_count"] == 2

    def test_returns_messages(self) -> None:
        """Test that result includes messages."""
        state = {"iteration_count": 0, "code_files": {}}
        result = _fallback_coder(state)

        assert len(result["messages"]) == 1
        assert result["messages"][0].additional_kwargs["role"] == "coder"


class TestFallbackReviewer:
    """Tests for fallback reviewer implementation."""

    def test_approves_correct_code(self) -> None:
        """Test that correct code is approved."""
        state = {"code_files": {"app.py": "def add(a, b):\n    return a + b\n"}}
        result = _fallback_reviewer(state)

        assert result["review_status"] == "approved"

    def test_requests_changes_for_bad_code(self) -> None:
        """Test that bad code gets changes requested."""
        state = {"code_files": {"app.py": "# TODO: fix\ndef add(a, b): return a - b"}}
        result = _fallback_reviewer(state)

        assert result["review_status"] == "changes"

    def test_returns_messages(self) -> None:
        """Test that result includes messages."""
        state = {"code_files": {"app.py": "code"}}
        result = _fallback_reviewer(state)

        assert len(result["messages"]) == 1
        assert result["messages"][0].additional_kwargs["role"] == "reviewer"


class TestCreateCoderNode:
    """Tests for create_coder_node factory."""

    def test_returns_fallback_when_no_llm(self) -> None:
        """Test that fallback is returned when no LLM provided."""
        node = create_coder_node()
        assert node == _fallback_coder

    def test_returns_llm_wrapper_when_llm_provided(self) -> None:
        """Test that LLM wrapper is returned when LLM provided."""
        mock_llm = MagicMock()
        node = create_coder_node(llm=mock_llm)

        assert node != _fallback_coder
        assert callable(node)

    def test_llm_node_calls_llm(self) -> None:
        """Test that LLM node actually calls the LLM."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "```python\ndef add(a, b): return a + b\n```"

        node = create_coder_node(llm=mock_llm)
        state = {
            "iteration_count": 0,
            "code_files": {},
            "messages": [HumanMessage(content="Write add function")],
            "reviewer_feedback": "",
        }

        result = node(state)

        mock_llm.invoke.assert_called_once()
        assert "code_files" in result
        assert result["iteration_count"] == 1


class TestCreateReviewerNode:
    """Tests for create_reviewer_node factory."""

    def test_returns_fallback_when_no_llm(self) -> None:
        """Test that fallback is returned when no LLM provided."""
        node = create_reviewer_node()
        assert node == _fallback_reviewer

    def test_returns_llm_wrapper_when_llm_provided(self) -> None:
        """Test that LLM wrapper is returned when LLM provided."""
        mock_llm = MagicMock()
        node = create_reviewer_node(llm=mock_llm)

        assert node != _fallback_reviewer
        assert callable(node)

    def test_llm_node_calls_llm(self) -> None:
        """Test that LLM node actually calls the LLM."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "APPROVED - looks good!"

        node = create_reviewer_node(llm=mock_llm)
        state = {
            "iteration_count": 1,
            "code_files": {"app.py": "def add(a, b): return a + b"},
            "messages": [HumanMessage(content="Write add function")],
            "reviewer_feedback": "",
        }

        result = node(state)

        mock_llm.invoke.assert_called_once()
        assert result["review_status"] == "approved"

    def test_llm_node_handles_changes_response(self) -> None:
        """Test that LLM node correctly handles CHANGES_REQUESTED."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "CHANGES_REQUESTED - add error handling"

        node = create_reviewer_node(llm=mock_llm)
        state = {
            "iteration_count": 1,
            "code_files": {"app.py": "def add(a, b): return a + b"},
            "messages": [HumanMessage(content="Write add function")],
            "reviewer_feedback": "",
        }

        result = node(state)

        assert result["review_status"] == "changes"
        assert "error handling" in result["reviewer_feedback"]
