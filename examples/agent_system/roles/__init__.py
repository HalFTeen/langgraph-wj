"""Agent roles for the multi-agent system.

This module provides role abstractions for building multi-agent workflows.
Each role encapsulates:
- A specific capability (coding, reviewing, testing, orchestrating)
- LLM integration with configurable prompts
- State transformation logic

Usage:
    from examples.agent_system.roles import CoderRole, ReviewerRole, RoleRegistry

    # Create roles with LLM
    coder = CoderRole(llm=get_llm())
    reviewer = ReviewerRole(llm=get_llm())

    # Use as LangGraph nodes
    graph.add_node("coder", coder.as_node())
    graph.add_node("reviewer", reviewer.as_node())

    # Or use the registry for dynamic role management
    registry = RoleRegistry()
    registry.register("coder", coder)
    node_fn = registry.get("coder").as_node()
"""

from examples.agent_system.roles.base import AgentRole, PassthroughRole, RoleResult
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.orchestrator import OrchestratorRole
from examples.agent_system.roles.registry import RoleRegistry, create_default_registry
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.roles.tester import TesterRole

__all__ = [
    "AgentRole",
    "CoderRole",
    "OrchestratorRole",
    "PassthroughRole",
    "ReviewerRole",
    "RoleRegistry",
    "RoleResult",
    "TesterRole",
    "create_default_registry",
]
