"""Orchestrator role implementation.

The Orchestrator role is responsible for:
1. Breaking down complex tasks into sub-tasks
2. Assigning tasks to appropriate agents
3. Coordinating workflow between agents
4. Tracking progress and handling blockers
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.prompts.templates import get_orchestrator_prompt
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


def _parse_plan_from_response(response: str) -> list[dict]:
    """Parse execution plan from LLM response.

    Expected format:
    1. [coder] Write the function
    2. [reviewer] Review the code
    3. [tester] Write tests
    """
    plan = []
    lines = response.strip().split("\n")

    pattern = r"^\d+\.\s*\[(\w+)\]\s*(.+)$"

    for line in lines:
        match = re.match(pattern, line.strip())
        if match:
            agent = match.group(1).lower()
            task = match.group(2).strip()
            plan.append({"agent": agent, "task": task, "status": "pending"})

    return plan


class OrchestratorRole(AgentRole):
    """Role for task orchestration and agent coordination.

    The Orchestrator breaks down complex tasks and coordinates
    work between specialized agents.

    Example:
        >>> orchestrator = OrchestratorRole(llm=get_llm())
        >>> result = orchestrator.process(state)
        >>> # result.state_updates contains execution_plan
    """

    def __init__(
        self,
        *,
        llm: BaseChatModel | None = None,
        available_agents: list[str] | None = None,
    ) -> None:
        """Initialize the Orchestrator role.

        Args:
            llm: Optional LLM for planning. If None, uses fallback logic.
            available_agents: List of agent names that can be coordinated.
        """
        super().__init__(
            name="orchestrator",
            llm=llm,
            description="Coordinates work between agents and manages task execution",
        )
        self.available_agents = available_agents or ["coder", "reviewer", "tester"]

    def process(self, state: "AgentState") -> RoleResult:
        """Process the state and create/update execution plan.

        Args:
            state: Current graph state

        Returns:
            RoleResult with execution_plan and orchestrator_status
        """
        if self.llm is None:
            return self._fallback_process(state)
        return self._llm_process(state)

    def _fallback_process(self, state: "AgentState") -> RoleResult:
        """Deterministic fallback for testing without LLM."""
        task = _extract_task_from_messages(state)
        current_plan = state.get("execution_plan", [])

        if not current_plan:
            # Create default plan
            plan = [
                {"agent": "coder", "task": f"Implement: {task}", "status": "pending"},
                {"agent": "reviewer", "task": "Review the implementation", "status": "pending"},
                {"agent": "tester", "task": "Write and run tests", "status": "pending"},
            ]
            status: Literal["planning", "executing", "completed"] = "planning"
            message_content = "Orchestrator: created execution plan."
        else:
            # Update plan status based on current state
            plan = list(current_plan)
            review_status = state.get("review_status", "")

            # Mark completed steps
            if state.get("iteration_count", 0) > 0:
                for step in plan:
                    if step["agent"] == "coder" and step["status"] == "pending":
                        step["status"] = "completed"
                        break

            if review_status == "approved":
                for step in plan:
                    if step["agent"] == "reviewer" and step["status"] == "pending":
                        step["status"] = "completed"
                        break

            # Determine overall status
            pending_count = sum(1 for s in plan if s["status"] == "pending")
            if pending_count == 0:
                status = "completed"
            else:
                status = "executing"

            message_content = f"Orchestrator: updated plan. {len(plan) - pending_count}/{len(plan)} steps completed."

        return RoleResult(
            message=AIMessage(
                content=message_content,
                additional_kwargs={
                    "role": "orchestrator",
                    "status": status,
                    "plan_steps": len(plan),
                },
            ),
            state_updates={
                "execution_plan": plan,
                "orchestrator_status": status,
            },
        )

    def _llm_process(self, state: "AgentState") -> RoleResult:
        """LLM-powered orchestration."""
        task = _extract_task_from_messages(state)
        current_plan = state.get("execution_plan", [])

        # Determine current state description
        if current_plan:
            completed = [s for s in current_plan if s["status"] == "completed"]
            pending = [s for s in current_plan if s["status"] == "pending"]
            current_state = (
                f"Completed: {len(completed)} steps. "
                f"Pending: {len(pending)} steps. "
                f"Review status: {state.get('review_status', 'unknown')}"
            )
        else:
            current_state = "No plan created yet. Starting fresh."

        # Build prompt
        messages = get_orchestrator_prompt(
            task=task,
            available_agents=self.available_agents,
            current_state=current_state,
        )

        # Call LLM
        response = self.llm.invoke(messages)
        response_content = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Parse plan
        plan = _parse_plan_from_response(response_content)
        if not plan:
            # Fallback to default plan if parsing fails
            plan = [
                {"agent": "coder", "task": f"Implement: {task}", "status": "pending"},
                {"agent": "reviewer", "task": "Review the implementation", "status": "pending"},
            ]

        # Determine status
        pending_count = sum(1 for s in plan if s["status"] == "pending")
        if pending_count == 0:
            status: Literal["planning", "executing", "completed"] = "completed"
        elif pending_count == len(plan):
            status = "planning"
        else:
            status = "executing"

        return RoleResult(
            message=AIMessage(
                content=f"Orchestrator: {status}.\n\n{response_content}",
                additional_kwargs={
                    "role": "orchestrator",
                    "status": status,
                    "plan_steps": len(plan),
                },
            ),
            state_updates={
                "execution_plan": plan,
                "orchestrator_status": status,
            },
            metadata={
                "task": task,
                "available_agents": self.available_agents,
            },
        )

    def get_next_agent(self, state: "AgentState") -> str | None:
        """Determine the next agent to execute based on plan.

        Args:
            state: Current graph state

        Returns:
            Name of the next agent, or None if plan is complete.
        """
        plan = state.get("execution_plan", [])
        for step in plan:
            if step["status"] == "pending":
                return step["agent"]
        return None
