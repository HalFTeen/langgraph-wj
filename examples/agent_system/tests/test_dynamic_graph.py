"""Tests for dynamic graph composition with Orchestrator.

This module tests the ability to build graphs dynamically based on
orchestrator decisions rather than hard-coded structure.

Key concepts:
- OrchestratorRole decides which agents to invoke
- Graph routes based on orchestrator's execution_plan
- Dynamic node inclusion based on task requirements
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from examples.agent_system.graph import AgentState, build_initial_state
from examples.agent_system.dynamic_graph import (
    build_orchestrated_graph,
    OrchestratorRouter,
)
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.orchestrator import OrchestratorRole
from examples.agent_system.roles.registry import create_default_registry, RoleRegistry
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.roles.tester import TesterRole


class TestBuildOrchestratedGraph:
    """Tests for building orchestrator-driven graphs."""

    def test_build_orchestrated_graph_creates_graph(self) -> None:
        """Test that build_orchestrated_graph returns a valid graph."""
        registry = create_default_registry()
        graph = build_orchestrated_graph(registry=registry)

        assert graph is not None

    def test_orchestrator_creates_plan_on_empty_state(self) -> None:
        """Test that orchestrator creates a plan when started with empty plan."""
        registry = create_default_registry()
        orchestrator_role = registry.get("orchestrator")

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

        result = orchestrator_role.process(state)

        # Orchestrator should create a plan
        plan = result.state_updates.get("execution_plan", [])
        assert len(plan) > 0
        assert plan[0]["agent"] == "coder"
        # Status should be executing so router can dispatch
        assert result.state_updates.get("orchestrator_status") == "executing"

    def test_orchestrator_updates_plan_on_progress(self) -> None:
        """Test that orchestrator updates plan when steps are completed."""
        registry = create_default_registry()
        orchestrator_role = registry.get("orchestrator")

        state: AgentState = {
            "messages": [HumanMessage(content="Write add function")],
            "code_files": {"app.py": "def add(a, b): return a + b"},
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
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "pending"},
                {"agent": "reviewer", "task": "Review", "status": "pending"},
            ],
            "orchestrator_status": "executing",
        }

        result = orchestrator_role.process(state)

        # Orchestrator should update completed steps
        plan = result.state_updates.get("execution_plan", [])
        coder_step = next(s for s in plan if s["agent"] == "coder")
        reviewer_step = next(s for s in plan if s["agent"] == "reviewer")
        assert coder_step["status"] == "completed"
        assert reviewer_step["status"] == "completed"


class TestOrchestratorRouter:
    """Tests for orchestrator-based routing."""

    def test_router_returns_next_agent(self) -> None:
        """Test that router returns next agent from plan."""
        router = OrchestratorRouter()

        state: AgentState = {
            "messages": [],
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
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "pending"},
                {"agent": "reviewer", "task": "Review", "status": "pending"},
            ],
            "orchestrator_status": "executing",
        }

        next_agent = router.get_next(state)
        assert next_agent == "coder"

    def test_router_skips_completed_steps(self) -> None:
        """Test that router skips completed steps."""
        router = OrchestratorRouter()

        state: AgentState = {
            "messages": [],
            "code_files": {},
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
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "completed"},
                {"agent": "reviewer", "task": "Review", "status": "pending"},
            ],
            "orchestrator_status": "executing",
        }

        next_agent = router.get_next(state)
        assert next_agent == "reviewer"

    def test_router_returns_end_when_plan_complete(self) -> None:
        """Test that router returns END when all steps are complete."""
        router = OrchestratorRouter()

        state: AgentState = {
            "messages": [],
            "code_files": {},
            "iteration_count": 2,
            "review_status": "approved",
            "reviewer_feedback": "",
            "pending_action": "",
            "approval_status": "approved",
            "last_execution": "",
            "skill_result": 0,
            "skill_repair_attempted": False,
            "test_code": "",
            "test_status": "passed",
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "completed"},
                {"agent": "reviewer", "task": "Review", "status": "completed"},
            ],
            "orchestrator_status": "completed",
        }

        next_agent = router.get_next(state)
        assert next_agent == "__end__"

    def test_router_returns_to_orchestrator_on_failure(self) -> None:
        """Test that router returns to orchestrator when step fails."""
        router = OrchestratorRouter()

        state: AgentState = {
            "messages": [],
            "code_files": {},
            "iteration_count": 1,
            "review_status": "changes",  # Reviewer requested changes
            "reviewer_feedback": "Fix the bug",
            "pending_action": "",
            "approval_status": "pending",
            "last_execution": "",
            "skill_result": 0,
            "skill_repair_attempted": False,
            "test_code": "",
            "test_status": "pending",
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "completed"},
                {"agent": "reviewer", "task": "Review", "status": "failed"},
            ],
            "orchestrator_status": "executing",
        }

        next_agent = router.get_next(state)
        assert next_agent == "orchestrator"


class TestDynamicPlanExecution:
    """Integration tests for dynamic plan execution."""

    def test_router_with_completed_plan_ends(self) -> None:
        """Test that router ends when plan is complete."""
        router = OrchestratorRouter()

        # All steps completed
        state: AgentState = {
            "messages": [],
            "code_files": {"app.py": "def add(a, b): return a + b"},
            "iteration_count": 2,
            "review_status": "approved",
            "reviewer_feedback": "",
            "pending_action": "",
            "approval_status": "approved",
            "last_execution": "",
            "skill_result": 0,
            "skill_repair_attempted": False,
            "test_code": "def test_add(): pass",
            "test_status": "generated",
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "completed"},
                {"agent": "reviewer", "task": "Review", "status": "completed"},
                {"agent": "tester", "task": "Test", "status": "completed"},
            ],
            "orchestrator_status": "completed",
        }

        next_agent = router.get_next(state)
        assert next_agent == "__end__"

    def test_router_dispatches_to_pending_agent(self) -> None:
        """Test that router dispatches to next pending agent."""
        router = OrchestratorRouter()

        state: AgentState = {
            "messages": [],
            "code_files": {"app.py": "def add(a, b): return a + b"},
            "iteration_count": 2,
            "review_status": "approved",
            "reviewer_feedback": "",
            "pending_action": "",
            "approval_status": "approved",
            "last_execution": "",
            "skill_result": 0,
            "skill_repair_attempted": False,
            "test_code": "",
            "test_status": "pending",
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "completed"},
                {"agent": "reviewer", "task": "Review", "status": "completed"},
                {"agent": "tester", "task": "Test", "status": "pending"},
            ],
            "orchestrator_status": "executing",
        }

        next_agent = router.get_next(state)
        assert next_agent == "tester"
