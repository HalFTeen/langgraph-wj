"""Dynamic graph composition with Orchestrator-driven execution.

This module provides a graph builder that uses the Orchestrator role
to dynamically determine execution flow based on task requirements.

Key concepts:
- OrchestratorRouter: Routes to next agent based on execution_plan
- build_orchestrated_graph: Creates a graph where orchestrator controls flow

Usage:
    from examples.agent_system.dynamic_graph import build_orchestrated_graph
    from examples.agent_system.roles.registry import create_default_registry

    registry = create_default_registry()
    graph = build_orchestrated_graph(registry=registry)
    result = graph.invoke(initial_state)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from examples.agent_system.graph import AgentState, approver_node, executor_node
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.orchestrator import OrchestratorRole
from examples.agent_system.roles.registry import RoleRegistry
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.roles.tester import TesterRole

if TYPE_CHECKING:
    pass


class OrchestratorRouter:
    """Routes to the next agent based on orchestrator's execution plan.

    The router examines the current state's execution_plan and determines
    which agent should execute next, or whether to return to the orchestrator
    for replanning.

    Example:
        router = OrchestratorRouter()
        next_agent = router.get_next(state)
    """

    def get_next(self, state: AgentState) -> str:
        """Determine the next agent to execute.

        Args:
            state: Current graph state

        Returns:
            Name of the next agent, "orchestrator" for replanning,
            or "__end__" if plan is complete.
        """
        plan = state.get("execution_plan", [])
        orchestrator_status = state.get("orchestrator_status", "planning")

        # If orchestrator says completed, we're done
        if orchestrator_status == "completed":
            return "__end__"

        # Check for failed steps - return to orchestrator for replanning
        for step in plan:
            if step.get("status") == "failed":
                return "orchestrator"

        # Find next pending step
        for step in plan:
            if step.get("status") == "pending":
                agent = step.get("agent", "")
                if agent in ("coder", "reviewer", "tester", "approver", "executor"):
                    return agent
                # Unknown agent - skip to orchestrator
                return "orchestrator"

        # All steps completed - check if we should end
        if all(s.get("status") == "completed" for s in plan) and plan:
            return "__end__"

        # No plan yet or empty - go to orchestrator
        return "orchestrator"


def _make_router_function(router: OrchestratorRouter):
    """Create a router function for conditional edges."""
    def route(state: AgentState) -> str:
        return router.get_next(state)
    return route


def _create_step_tracker(role_name: str):
    """Create a wrapper that tracks step completion in execution_plan."""
    def track_step(state: AgentState) -> dict:
        """Update execution plan to mark current step as completed."""
        plan = list(state.get("execution_plan", []))

        # Find and mark the current step as completed
        for step in plan:
            if step.get("agent") == role_name and step.get("status") == "pending":
                step["status"] = "completed"
                break

        return {"execution_plan": plan}
    return track_step


def build_orchestrated_graph(
    *,
    llm: BaseChatModel | None = None,
    registry: RoleRegistry | None = None,
    interrupt_before: list[str] | None = None,
    checkpointer=None,
) -> StateGraph:
    """Build an orchestrator-driven graph.

    This graph starts with the orchestrator, which creates an execution plan.
    Then it dynamically routes to agents based on the plan.

    Args:
        llm: Optional LLM instance for all roles.
        registry: Optional RoleRegistry with pre-configured roles.
        interrupt_before: Nodes to interrupt before.
        checkpointer: Checkpoint saver for state persistence.

    Returns:
        Compiled StateGraph with orchestrator-driven flow.

    Example:
        >>> from examples.agent_system.roles.registry import create_default_registry
        >>> registry = create_default_registry()
        >>> graph = build_orchestrated_graph(registry=registry)
        >>> result = graph.invoke(initial_state)
    """
    # Get roles from registry or create defaults
    if registry is not None:
        orchestrator_role = registry.get("orchestrator")
        coder_role = registry.get("coder")
        reviewer_role = registry.get("reviewer")
        tester_role = registry.get("tester")
    else:
        orchestrator_role = OrchestratorRole(llm=llm)
        coder_role = CoderRole(llm=llm)
        reviewer_role = ReviewerRole(llm=llm)
        tester_role = TesterRole(llm=llm)

    # Create node functions
    orchestrator = orchestrator_role.as_node()
    coder = coder_role.as_node()
    reviewer = reviewer_role.as_node()
    tester = tester_role.as_node()

    # Create step-tracking wrappers that also call the role
    def coder_with_tracking(state: AgentState) -> dict:
        result = coder(state)
        tracking = _create_step_tracker("coder")(state)
        # Merge tracking into result
        if "execution_plan" not in result:
            result["execution_plan"] = tracking["execution_plan"]
        return result

    def reviewer_with_tracking(state: AgentState) -> dict:
        result = reviewer(state)
        plan = list(state.get("execution_plan", []))

        # If reviewer approved, mark reviewer step as completed
        if result.get("review_status") == "approved":
            for step in plan:
                if step.get("agent") == "reviewer" and step.get("status") == "pending":
                    step["status"] = "completed"
                    break
            result["execution_plan"] = plan
        else:
            # Changes requested - reset coder to pending for retry
            for step in plan:
                if step.get("agent") == "coder":
                    step["status"] = "pending"
            result["execution_plan"] = plan

        return result

    def tester_with_tracking(state: AgentState) -> dict:
        result = tester(state)
        tracking = _create_step_tracker("tester")(state)
        if "execution_plan" not in result:
            result["execution_plan"] = tracking["execution_plan"]
        return result

    # Create router
    router = OrchestratorRouter()
    route_fn = _make_router_function(router)

    # Build graph
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("coder", coder_with_tracking)
    graph.add_node("reviewer", reviewer_with_tracking)
    graph.add_node("tester", tester_with_tracking)
    graph.add_node("approver", approver_node)
    graph.add_node("executor", executor_node)

    # Start with orchestrator
    graph.add_edge(START, "orchestrator")

    # Orchestrator routes to first agent in plan
    graph.add_conditional_edges("orchestrator", route_fn)

    # Each agent routes back through the router
    graph.add_conditional_edges("coder", route_fn)
    graph.add_conditional_edges("reviewer", route_fn)
    graph.add_conditional_edges("tester", route_fn)

    # Approver -> executor -> end (keep the approval flow)
    graph.add_edge("approver", "executor")
    graph.add_edge("executor", END)

    return graph.compile(
        interrupt_before=interrupt_before,
        checkpointer=checkpointer,
    )
