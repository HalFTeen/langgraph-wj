"""Coder role implementation.

The Coder role is responsible for:
1. Writing code based on task requirements
2. Iterating on code based on reviewer feedback
3. Managing code files in the state
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.prompts.templates import get_coder_prompt
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


def _extract_code_from_response(response: str) -> str:
    """Extract code block from LLM response."""
    pattern = r"```(?:python)?\s*\n?(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        return matches[0].strip()
    return response.strip()


class CoderRole(AgentRole):
    """Role for code generation and modification.

    The Coder receives task requirements and reviewer feedback,
    then generates or updates code accordingly.

    Example:
        >>> coder = CoderRole(llm=get_llm())
        >>> result = coder.process(state)
        >>> # result.state_updates contains updated code_files
    """

    def __init__(self, *, llm: BaseChatModel | None = None) -> None:
        """Initialize the Coder role.

        Args:
            llm: Optional LLM for code generation. If None, uses fallback logic.
        """
        super().__init__(
            name="coder",
            llm=llm,
            description="Generates and modifies code based on requirements and feedback",
        )

    def process(self, state: "AgentState") -> RoleResult:
        """Process the state and generate/update code.

        Args:
            state: Current graph state

        Returns:
            RoleResult with updated code_files and iteration_count
        """
        if self.llm is None:
            return self._fallback_process(state)
        return self._llm_process(state)

    def _fallback_process(self, state: "AgentState") -> RoleResult:
        """Deterministic fallback for testing without LLM."""
        iteration = state.get("iteration_count", 0)
        code_files = dict(state.get("code_files", {}))

        if iteration == 0:
            code_files["app.py"] = """def add(a, b):
    # TODO: fix math
    return a - b
"""
            summary = "initial implementation"
        else:
            code_files["app.py"] = """def add(a, b):
    return a + b
"""
            summary = "fixed math logic"

        return RoleResult(
            message=AIMessage(
                content=f"Coder: {summary}.",
                additional_kwargs={"role": "coder", "summary": summary},
            ),
            state_updates={
                "code_files": code_files,
                "iteration_count": iteration + 1,
            },
        )

    def _llm_process(self, state: "AgentState") -> RoleResult:
        """LLM-powered code generation."""
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
        response = self.llm.invoke(messages)
        response_content = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Extract code
        code = _extract_code_from_response(response_content)
        code_files["app.py"] = code

        summary = "fixed code per feedback" if iteration > 0 else "initial implementation"

        return RoleResult(
            message=AIMessage(
                content=f"Coder: {summary}.\n\n```python\n{code}\n```",
                additional_kwargs={"role": "coder", "summary": summary},
            ),
            state_updates={
                "code_files": code_files,
                "iteration_count": iteration + 1,
            },
            metadata={
                "task": task,
                "iteration": iteration + 1,
                "has_feedback": feedback is not None,
            },
        )
