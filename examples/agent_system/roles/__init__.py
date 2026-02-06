"""Agent roles for the multi-agent system.

This module provides role abstractions for building multi-agent workflows.
Each role encapsulates:
- A specific capability (coding, reviewing, testing, orchestrating)
- LLM integration with configurable prompts
- State transformation logic

Usage:
    from examples.agent_system.roles import CoderRole, ReviewerRole

    # Create roles with LLM
    coder = CoderRole(llm=get_llm())
    reviewer = ReviewerRole(llm=get_llm())

    # Use as LangGraph nodes
    graph.add_node("coder", coder.as_node())
    graph.add_node("reviewer", reviewer.as_node())
"""

from examples.agent_system.roles.base import AgentRole, RoleResult
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.reviewer import ReviewerRole

__all__ = [
    "AgentRole",
    "RoleResult",
    "CoderRole",
    "ReviewerRole",
]
