"""Shared utility functions for agent roles."""
from __future__ import annotations
import re
from typing import TYPE_CHECKING, Literal
from langchain_core.messages import HumanMessage
if TYPE_CHECKING:
    from examples.agent_system.graph import AgentState

def extract_task_from_messages(state: "AgentState") -> str:
    """Extract the original task from state messages."""
    messages = state.get("messages", [])
    for msg in messages:
        if isinstance(msg, HumanMessage):
            return msg.content
    return "No task specified"

def extract_code_from_response(response: str) -> str:
    """Extract code block from LLM response.
    Handles markdown code blocks with or without language specifier.
    """
    pattern = r"```(?:python)?\s*\n?(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        return matches[0].strip()
    return response.strip()

def parse_review_decision(response: str) -> tuple[Literal["approved", "changes"], str]:
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
        return "changes", response

