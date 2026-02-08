"""Tests for multi-agent coordination and collaboration.

This module tests the ability of multiple agents (Coder, Reviewer, Tester, Orchestrator)
to work together effectively through the messaging protocol and shared state.

Key concepts:
- Message passing between agents
- Coordination through shared execution plan
- State synchronization across agent boundaries
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.graph import AgentState, build_initial_state, build_graph
from examples.agent_system.dynamic_graph import build_orchestrated_graph
from examples.agent_system.messaging import (
    AgentMessage,
    MessageQueue,
    MessagePriority,
    MessageType,
)
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.orchestrator import OrchestratorRole
from examples.agent_system.roles.registry import create_default_registry, RoleRegistry
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.roles.tester import TesterRole


class TestMultiAgentMessaging:
    """Tests for inter-agent message passing."""

    def test_agent_message_creation(self) -> None:
        """Test creating messages between agents."""
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Please review this code",
            message_type=MessageType.REQUEST,
            priority=MessagePriority.HIGH,
        )

        assert msg.sender == "coder"
        assert msg.receiver == "reviewer"
        assert msg.message_type == MessageType.REQUEST
        assert msg.priority == MessagePriority.HIGH
        assert msg.id is not None

    def test_message_serialization(self) -> None:
        """Test message serialization for state storage."""
        msg = AgentMessage(
            sender="tester",
            receiver="orchestrator",
            content="Tests failed",
            message_type=MessageType.NOTIFICATION,
            priority=MessagePriority.HIGH,
            metadata={"test_results": "failed"},
        )

        # Convert to dict
        msg_dict = msg.to_dict()
        assert msg_dict["sender"] == "tester"
        assert msg_dict["receiver"] == "orchestrator"
        assert msg_dict["metadata"]["test_results"] == "failed"

        # Convert back
        restored = AgentMessage.from_dict(msg_dict)
        assert restored.sender == msg.sender
        assert restored.receiver == msg.receiver

    def test_message_queue_priority(self) -> None:
        """Test that message queue respects priority."""
        queue = MessageQueue()

        # Add messages with different priorities
        low_msg = AgentMessage(
            sender="a", receiver="b", content="low",
            message_type=MessageType.REQUEST, priority=MessagePriority.LOW
        )
        high_msg = AgentMessage(
            sender="c", receiver="b", content="high",
            message_type=MessageType.REQUEST, priority=MessagePriority.HIGH
        )
        normal_msg = AgentMessage(
            sender="d", receiver="b", content="normal",
            message_type=MessageType.REQUEST, priority=MessagePriority.NORMAL
        )

        queue.enqueue(low_msg)
        queue.enqueue(high_msg)
        queue.enqueue(normal_msg)

        # Dequeue should return highest priority first
        assert queue.dequeue() == high_msg
        assert queue.dequeue() == normal_msg
        assert queue.dequeue() == low_msg


class TestMultiAgentCoordination:
    """Tests for multi-agent coordination workflows."""

    def test_coder_reviewer_feedback_loop(self) -> None:
        """Test the coder-reviewer feedback loop."""
        registry = create_default_registry()
        coder = registry.get("coder")
        reviewer = registry.get("reviewer")

        # Initial state
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
            "execution_plan": [],
            "orchestrator_status": "planning",
        }

        # Coder generates code
        coder_result = coder.process(state)
        assert "app.py" in coder_result.state_updates["code_files"]

        # Update state for reviewer
        state.update(coder_result.to_state_dict())

        # Reviewer checks code
        reviewer_result = reviewer.process(state)
        assert "review_status" in reviewer_result.state_updates

    def test_coder_reviewer_tester_workflow(self) -> None:
        """Test the full coder -> reviewer -> tester workflow."""
        registry = create_default_registry()
        coder = registry.get("coder")
        reviewer = registry.get("reviewer")
        tester = registry.get("tester")

        # Initial state
        state: AgentState = {
            "messages": [HumanMessage(content="Write a calculator")],
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
            "execution_plan": [],
            "orchestrator_status": "planning",
        }

        # Coder writes code
        coder_result = coder.process(state)
        state.update(coder_result.to_state_dict())

        # Reviewer approves
        state["code_files"]["app.py"] = "def add(a, b): return a + b"
        state["review_status"] = "approved"
        state["reviewer_feedback"] = "Looks good!"

        reviewer_result = reviewer.process(state)
        assert reviewer_result.state_updates["review_status"] == "approved"

        state.update(reviewer_result.to_state_dict())

        # Tester runs tests
        tester_result = tester.process(state)
        assert "test_status" in tester_result.state_updates

    def test_orchestrator_coordinates_agents(self) -> None:
        """Test orchestrator creating and managing agent execution plan."""
        registry = create_default_registry()
        orchestrator = registry.get("orchestrator")

        # Initial task
        state: AgentState = {
            "messages": [HumanMessage(content="Build a REST API")],
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
            "execution_plan": [],
            "orchestrator_status": "planning",
        }

        # Orchestrator creates plan
        result = orchestrator.process(state)
        plan = result.state_updates["execution_plan"]

        # Plan should include multiple agents
        agent_names = {step["agent"] for step in plan}
        assert "coder" in agent_names
        assert "reviewer" in agent_names

        # Simulate progress
        state.update(result.to_state_dict())
        state["iteration_count"] = 1
        state["review_status"] = "approved"

        # Orchestrator updates plan
        result2 = orchestrator.process(state)
        updated_plan = result2.state_updates["execution_plan"]

        # Coder step should be marked completed
        coder_step = next(s for s in updated_plan if s["agent"] == "coder")
        assert coder_step["status"] == "completed"


class TestRoleRegistryIntegration:
    """Tests for role registry with multiple agents."""

    def test_registry_provides_all_roles(self) -> None:
        """Test that default registry provides all expected roles."""
        registry = create_default_registry()

        assert registry.has("coder")
        assert registry.has("reviewer")
        assert registry.has("tester")
        assert registry.has("orchestrator")

        # Each role should be retrievable
        coder = registry.get("coder")
        reviewer = registry.get("reviewer")
        tester = registry.get("tester")
        orchestrator = registry.get("orchestrator")

        assert isinstance(coder, CoderRole)
        assert isinstance(reviewer, ReviewerRole)
        assert isinstance(tester, TesterRole)
        assert isinstance(orchestrator, OrchestratorRole)

    def test_roles_can_be_converted_to_nodes(self) -> None:
        """Test that roles can be converted to graph nodes."""
        registry = create_default_registry()

        coder = registry.get("coder")
        reviewer = registry.get("reviewer")

        coder_node = coder.as_node()
        reviewer_node = reviewer.as_node()

        assert callable(coder_node)
        assert callable(reviewer_node)

        # Test node invocation
        state: AgentState = {
            "messages": [HumanMessage(content="Test")],
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
            "execution_plan": [],
            "orchestrator_status": "planning",
        }

        coder_result = coder_node(state)
        assert "messages" in coder_result
        assert "code_files" in coder_result


class TestFullGraphExecution:
    """Integration tests for full graph execution with multiple agents."""

    def test_build_graph_with_registry(self) -> None:
        """Test building graph with role registry."""
        registry = create_default_registry()
        graph = build_graph(registry=registry)

        assert graph is not None

    def test_build_orchestrated_graph_with_registry(self) -> None:
        """Test building orchestrated graph with role registry."""
        registry = create_default_registry()
        graph = build_orchestrated_graph(registry=registry)

        assert graph is not None

    def test_fallback_mode_with_all_roles(self) -> None:
        """Test that all roles work in fallback (no LLM) mode."""
        # Create roles without LLM
        coder = CoderRole()
        reviewer = ReviewerRole()
        tester = TesterRole()

        # Initial state
        state: AgentState = {
            "messages": [HumanMessage(content="Test task")],
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
            "execution_plan": [],
            "orchestrator_status": "planning",
        }

        # Coder should work without LLM
        coder_result = coder.process(state)
        assert "code_files" in coder_result.state_updates

        state.update(coder_result.to_state_dict())
        state["code_files"]["app.py"] = "def add(a, b): return a + b"

        # Reviewer should work without LLM
        reviewer_result = reviewer.process(state)
        assert "review_status" in reviewer_result.state_updates

        state.update(reviewer_result.to_state_dict())

        # Tester should work without LLM
        tester_result = tester.process(state)
        assert "test_status" in tester_result.state_updates
