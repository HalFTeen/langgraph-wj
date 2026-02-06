"""LLM-powered node implementations for the agent graph.

This module provides node functions that use LLM for code generation and review.
Each node function can operate in two modes:
1. LLM mode: Uses configured LLM to generate responses
2. Fallback mode: Uses deterministic logic (for testing without API keys)

Usage:
    from examples.agent_system.nodes import create_coder_node, create_reviewer_node

    # Create LLM-powered nodes
    coder_node = create_coder_node(llm=get_llm())
    reviewer_node = create_reviewer_node(llm=get_llm())

    # Or use fallback mode (for testing)
    coder_node = create_coder_node()  # Uses fallback logic
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.prompts.templates import (
    get_coder_prompt,
    get_reviewer_prompt,
)

if TYPE_CHECKING:
    from examples.agent_system.graph import AgentState


def _extract_task_from_messages(state: "AgentState") -> str:
    """Extract the original task from state messages."""
    messages = state.get("messages", [])
    for msg in messages:
        if isinstance(msg, HumanMessage):
            return msg.content
    return "No task specified"


def _extract_code_from_response(response: str) -> str:
    """Extract code block from LLM response.

    Handles markdown code blocks with or without language specifier.
    """
    # Try to extract code from markdown code block
    pattern = r"```(?:python)?\s*\n?(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        return matches[0].strip()
    # If no code block, return the response as-is (might be raw code)
    return response.strip()


def _parse_review_decision(response: str) -> tuple[str, str]:
    """Parse review decision from LLM response.

    Returns:
        Tuple of (status, feedback) where status is "approved" or "changes"
    """
    response_upper = response.upper()

    if "APPROVED" in response_upper and "CHANGES_REQUESTED" not in response_upper:
        return "approved", response
    elif "CHANGES_REQUESTED" in response_upper or "CHANGES REQUESTED" in response_upper:
        return "changes", response
    else:
        # Default to changes if unclear
        return "changes", response


# =============================================================================
# Fallback implementations (for testing without LLM)
# =============================================================================


def _fallback_coder(state: "AgentState") -> dict:
    """Deterministic coder implementation for testing."""
    iteration = state.get("iteration_count", 0)
    code_files = dict(state.get("code_files", {}))

    if iteration == 0:
        # First iteration: write bad code
        code_files["app.py"] = """def add(a, b):
    # TODO: fix math
    return a - b
"""
        summary = "initial implementation"
    else:
        # Subsequent iterations: fix the code
        code_files["app.py"] = """def add(a, b):
    return a + b
"""
        summary = "fixed math logic"

    return {
        "code_files": code_files,
        "iteration_count": iteration + 1,
        "messages": [
            AIMessage(
                content=f"Coder: {summary}.",
                additional_kwargs={"role": "coder", "summary": summary},
            )
        ],
    }


def _fallback_reviewer(state: "AgentState") -> dict:
    """Deterministic reviewer implementation for testing."""
    code = state.get("code_files", {}).get("app.py", "")

    if "return a + b" in code and "TODO" not in code:
        status = "approved"
        feedback = "Reviewer: approved."
    else:
        status = "changes"
        feedback = "Reviewer: add() is incorrect; please fix math."

    return {
        "review_status": status,
        "reviewer_feedback": feedback,
        "messages": [
            AIMessage(
                content=feedback,
                additional_kwargs={"role": "reviewer", "status": status},
            )
        ],
    }


# =============================================================================
# LLM-powered implementations
# =============================================================================


def _llm_coder(state: "AgentState", llm: BaseChatModel) -> dict:
    """LLM-powered coder implementation."""
    iteration = state.get("iteration_count", 0)
    code_files = dict(state.get("code_files", {}))
    task = _extract_task_from_messages(state)

    # Build prompt
    existing_code = code_files.get("app.py")
    feedback = state.get("reviewer_feedback") if iteration > 0 else None

    messages = get_coder_prompt(
        task=task,
        feedback=feedback,
        existing_code=existing_code,
    )

    # Call LLM
    response = llm.invoke(messages)
    response_content = (
        response.content if hasattr(response, "content") else str(response)
    )

    # Extract code from response
    code = _extract_code_from_response(response_content)
    code_files["app.py"] = code

    summary = "fixed code per feedback" if iteration > 0 else "initial implementation"

    return {
        "code_files": code_files,
        "iteration_count": iteration + 1,
        "messages": [
            AIMessage(
                content=f"Coder: {summary}.\n\n```python\n{code}\n```",
                additional_kwargs={"role": "coder", "summary": summary},
            )
        ],
    }


def _llm_reviewer(state: "AgentState", llm: BaseChatModel) -> dict:
    """LLM-powered reviewer implementation."""
    code = state.get("code_files", {}).get("app.py", "")
    task = _extract_task_from_messages(state)
    iteration = state.get("iteration_count", 1)
    previous_feedback = state.get("reviewer_feedback") if iteration > 1 else None

    # Build prompt
    messages = get_reviewer_prompt(
        code=code,
        task=task,
        iteration=iteration,
        previous_feedback=previous_feedback,
    )

    # Call LLM
    response = llm.invoke(messages)
    response_content = (
        response.content if hasattr(response, "content") else str(response)
    )

    # Parse decision
    status, feedback = _parse_review_decision(response_content)

    return {
        "review_status": status,
        "reviewer_feedback": feedback,
        "messages": [
            AIMessage(
                content=feedback,
                additional_kwargs={"role": "reviewer", "status": status},
            )
        ],
    }


# =============================================================================
# Factory functions
# =============================================================================


def create_coder_node(
    llm: BaseChatModel | None = None,
) -> Callable[["AgentState"], dict]:
    """Create a coder node function.

    Args:
        llm: Optional LLM instance. If None, uses fallback deterministic logic.

    Returns:
        A node function compatible with LangGraph.

    Example:
        >>> from examples.agent_system.llm import get_llm
        >>> coder_node = create_coder_node(llm=get_llm())
        >>> graph.add_node("coder", coder_node)
    """
    if llm is None:
        return _fallback_coder
    return lambda state: _llm_coder(state, llm)


def create_reviewer_node(
    llm: BaseChatModel | None = None,
) -> Callable[["AgentState"], dict]:
    """Create a reviewer node function.

    Args:
        llm: Optional LLM instance. If None, uses fallback deterministic logic.

    Returns:
        A node function compatible with LangGraph.

    Example:
        >>> from examples.agent_system.llm import get_llm
        >>> reviewer_node = create_reviewer_node(llm=get_llm())
        >>> graph.add_node("reviewer", reviewer_node)
    """
    if llm is None:
        return _fallback_reviewer
    return lambda state: _llm_reviewer(state, llm)
