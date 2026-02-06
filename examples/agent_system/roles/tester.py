"""Tester role implementation.

The Tester role is responsible for:
1. Writing test cases based on code and requirements
2. Validating code functionality through tests
3. Reporting test results and coverage
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.prompts.templates import get_tester_prompt
from examples.agent_system.roles.base import AgentRole, RoleResult

if TYPE_CHECKING:
    from examples.agent_system.graph import AgentState


def _extract_task_from_messages(state: "AgentState") -> str:
    """Extract the original task from state messages."""
    messages = state.get("messages", [])
    for msg in messages:
        if isinstance(msg, HumanMessage):
            return msg.content
    return "No task specified"


def _extract_test_code_from_response(response: str) -> str:
    """Extract test code from LLM response."""
    pattern = r"```(?:python)?\s*\n?(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        return matches[0].strip()
    return response.strip()


class TesterRole(AgentRole):
    """Role for test generation and execution.

    The Tester examines code and generates appropriate test cases
    to verify correctness.

    Example:
        >>> tester = TesterRole(llm=get_llm())
        >>> result = tester.process(state)
        >>> # result.state_updates contains test_code and test_status
    """

    def __init__(self, *, llm: BaseChatModel | None = None) -> None:
        """Initialize the Tester role.

        Args:
            llm: Optional LLM for test generation. If None, uses fallback logic.
        """
        super().__init__(
            name="tester",
            llm=llm,
            description="Generates and runs tests to verify code correctness",
        )

    def process(self, state: "AgentState") -> RoleResult:
        """Process the state and generate tests.

        Args:
            state: Current graph state

        Returns:
            RoleResult with test_code and test_status
        """
        if self.llm is None:
            return self._fallback_process(state)
        return self._llm_process(state)

    def _fallback_process(self, state: "AgentState") -> RoleResult:
        """Deterministic fallback for testing without LLM."""
        code = state.get("code_files", {}).get("app.py", "")

        # Generate simple test based on code content
        if "def add" in code:
            test_code = '''import pytest

def test_add_positive_numbers():
    from app import add
    assert add(2, 3) == 5

def test_add_negative_numbers():
    from app import add
    assert add(-1, -2) == -3

def test_add_zero():
    from app import add
    assert add(0, 5) == 5
'''
            test_status = "generated"
        else:
            test_code = "# No testable code found"
            test_status = "skipped"

        return RoleResult(
            message=AIMessage(
                content=f"Tester: {test_status} tests.\n\n```python\n{test_code}\n```",
                additional_kwargs={"role": "tester", "status": test_status},
            ),
            state_updates={
                "test_code": test_code,
                "test_status": test_status,
            },
        )

    def _llm_process(self, state: "AgentState") -> RoleResult:
        """LLM-powered test generation."""
        code = state.get("code_files", {}).get("app.py", "")
        task = _extract_task_from_messages(state)

        # Build prompt
        messages = get_tester_prompt(
            code=code,
            task=task,
        )

        # Call LLM
        response = self.llm.invoke(messages)
        response_content = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Extract test code
        test_code = _extract_test_code_from_response(response_content)
        test_status = "generated"

        return RoleResult(
            message=AIMessage(
                content=f"Tester: generated tests.\n\n```python\n{test_code}\n```",
                additional_kwargs={"role": "tester", "status": test_status},
            ),
            state_updates={
                "test_code": test_code,
                "test_status": test_status,
            },
            metadata={
                "task": task,
                "code_length": len(code),
            },
        )
