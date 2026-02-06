"""Tests for graph with Role class integration.

This test module validates the refactored graph that uses Role classes
instead of the legacy create_*_node() factory functions.

TDD approach: These tests are written BEFORE the refactoring to define
the expected behavior of the new implementation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from examples.agent_system.graph import (
    AgentState,
    build_graph,
    build_initial_state,
)
from examples.agent_system.roles.base import AgentRole
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.registry import RoleRegistry, create_default_registry
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.roles.tester import TesterRole


class TestBuildGraphWithRoles:
    """Tests for build_graph with Role class support."""

    def test_build_graph_accepts_registry(self) -> None:
        """Test that build_graph accepts a RoleRegistry parameter."""
        registry = create_default_registry()
        graph = build_graph(registry=registry)

        assert graph is not None

    def test_build_graph_uses_registry_roles(self) -> None:
        """Test that build_graph uses roles from the registry."""
        # Create registry with custom roles
        registry = RoleRegistry()
        mock_coder = MagicMock(spec=CoderRole)
        mock_coder.as_node.return_value = lambda state: {
            "code_files": {"app.py": "# mock"},
            "iteration_count": 1,
            "messages": [],
        }
        registry.register("coder", mock_coder)
        registry.register("reviewer", ReviewerRole())
        registry.register("tester", TesterRole())

        graph = build_graph(registry=registry)

        # The graph should have been built with the registry roles
        assert graph is not None
        mock_coder.as_node.assert_called_once()

    def test_build_graph_without_registry_uses_defaults(self) -> None:
        """Test that build_graph works without registry (backward compatibility)."""
        graph = build_graph()

        assert graph is not None

    def test_build_graph_with_llm_passed_to_roles(self) -> None:
        """Test that LLM is passed to role constructors when using default registry."""
        mock_llm = MagicMock()
        graph = build_graph(llm=mock_llm)

        assert graph is not None


class TestGraphExecutionWithRoles:
    """Integration tests for graph execution using Role classes."""

    def test_coder_reviewer_loop_completes(self) -> None:
        """Test that coder/reviewer loop completes with role classes."""
        registry = create_default_registry()
        graph = build_graph(registry=registry)

        initial_state = build_initial_state()
        initial_state["approval_status"] = "approved"

        result = graph.invoke(initial_state)

        assert result["review_status"] == "approved"
        assert result["iteration_count"] >= 2
        assert "return a + b" in result["code_files"]["app.py"]

    def test_fallback_behavior_matches_legacy(self) -> None:
        """Test that fallback behavior matches legacy implementation."""
        # Build graph with registry (new way)
        registry = create_default_registry()
        graph_new = build_graph(registry=registry)

        # Build graph without registry (legacy way)
        graph_legacy = build_graph()

        initial_state = build_initial_state()
        initial_state["approval_status"] = "approved"

        result_new = graph_new.invoke(initial_state.copy())
        result_legacy = graph_legacy.invoke(initial_state.copy())

        # Both should produce equivalent results
        assert result_new["review_status"] == result_legacy["review_status"]
        assert result_new["code_files"]["app.py"] == result_legacy["code_files"]["app.py"]


class TestRoleAsNodeIntegration:
    """Tests for Role.as_node() integration with StateGraph."""

    def test_coder_role_as_node_in_graph(self) -> None:
        """Test CoderRole.as_node() works in a graph context."""
        coder = CoderRole()
        node_fn = coder.as_node()

        state: AgentState = {
            "messages": [HumanMessage(content="Write add function")],
            "code_files": {},
            "iteration_count": 0,
            "review_status": "changes",
            "reviewer_feedback": "",
            "pending_action": "",
            "approval_status": "pending",
            "last_execution": "",
            "skill_result": 0,
            "skill_repair_attempted": False,
            "test_code": "",
            "test_status": "pending",
        }

        result = node_fn(state)

        assert "code_files" in result
        assert "messages" in result
        assert result["iteration_count"] == 1

    def test_reviewer_role_as_node_in_graph(self) -> None:
        """Test ReviewerRole.as_node() works in a graph context."""
        reviewer = ReviewerRole()
        node_fn = reviewer.as_node()

        state: AgentState = {
            "messages": [HumanMessage(content="Write add function")],
            "code_files": {"app.py": "def add(a, b):\n    return a + b\n"},
            "iteration_count": 1,
            "review_status": "changes",
            "reviewer_feedback": "",
            "pending_action": "",
            "approval_status": "pending",
            "last_execution": "",
            "skill_result": 0,
            "skill_repair_attempted": False,
            "test_code": "",
            "test_status": "pending",
        }

        result = node_fn(state)

        assert "review_status" in result
        assert result["review_status"] == "approved"

    def test_tester_role_as_node_in_graph(self) -> None:
        """Test TesterRole.as_node() works in a graph context."""
        tester = TesterRole()
        node_fn = tester.as_node()

        state: AgentState = {
            "messages": [HumanMessage(content="Write add function")],
            "code_files": {"app.py": "def add(a, b):\n    return a + b\n"},
            "iteration_count": 1,
            "review_status": "approved",
            "reviewer_feedback": "",
            "pending_action": "",
            "approval_status": "pending",
            "last_execution": "",
            "skill_result": 0,
            "skill_repair_attempted": False,
            "test_code": "",
            "test_status": "pending",
        }

        result = node_fn(state)

        assert "test_code" in result
        assert "test_status" in result
        assert result["test_status"] == "generated"
