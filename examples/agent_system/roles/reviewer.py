"""Reviewer role implementation.

The Reviewer role is responsible for:
1. Reviewing code for correctness and quality
2. Providing feedback for improvements
3. Approving code that meets requirements
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.prompts.templates import get_reviewer_prompt
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


def _parse_review_decision(response: str) -> tuple[Literal["approved", "changes"], str]:
    """Parse review decision from LLM response."""
    response_upper = response.upper()

    if "APPROVED" in response_upper and "CHANGES_REQUESTED" not in response_upper:
        return "approved", response
    elif "CHANGES_REQUESTED" in response_upper or "CHANGES REQUESTED" in response_upper:
        return "changes", response
    else:
        return "changes", response


class ReviewerRole(AgentRole):
    """Role for code review and quality control.

    The Reviewer examines code against requirements and provides
    feedback or approval.

    Example:
        >>> reviewer = ReviewerRole(llm=get_llm())
        >>> result = reviewer.process(state)
        >>> if result.state_updates["review_status"] == "approved":
        ...     print("Code approved!")
    """

    def __init__(self, *, llm: BaseChatModel | None = None) -> None:
        """Initialize the Reviewer role.

        Args:
            llm: Optional LLM for code review. If None, uses fallback logic.
        """
        super().__init__(
            name="reviewer",
            llm=llm,
            description="Reviews code for correctness, quality, and completeness",
        )

    def process(self, state: "AgentState") -> RoleResult:
        """Process the state and review the code.

        Args:
            state: Current graph state

        Returns:
            RoleResult with review_status and reviewer_feedback
        """
        if self.llm is None:
            return self._fallback_process(state)
        return self._llm_process(state)

    def _fallback_process(self, state: "AgentState") -> RoleResult:
        """Deterministic fallback for testing without LLM."""
        code = state.get("code_files", {}).get("app.py", "")

        if "return a + b" in code and "TODO" not in code:
            status: Literal["approved", "changes"] = "approved"
            feedback = "Reviewer: approved."
        else:
            status = "changes"
            feedback = "Reviewer: add() is incorrect; please fix math."

        return RoleResult(
            message=AIMessage(
                content=feedback,
                additional_kwargs={"role": "reviewer", "status": status},
            ),
            state_updates={
                "review_status": status,
                "reviewer_feedback": feedback,
            },
        )

    def _llm_process(self, state: "AgentState") -> RoleResult:
        """LLM-powered code review."""
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
        response = self.llm.invoke(messages)
        response_content = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Parse decision
        status, feedback = _parse_review_decision(response_content)

        return RoleResult(
            message=AIMessage(
                content=feedback,
                additional_kwargs={"role": "reviewer", "status": status},
            ),
            state_updates={
                "review_status": status,
                "reviewer_feedback": feedback,
            },
            metadata={
                "task": task,
                "iteration": iteration,
                "decision": status,
            },
        )
