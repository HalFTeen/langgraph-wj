from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph, add_messages
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.registry import RoleRegistry
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.roles.tester import TesterRole
from examples.agent_system.skills.registry import SkillRegistry
from examples.agent_system.skills.reloader import SkillReloader
from examples.agent_system.skills.editor import SkillEditor
from examples.agent_system.skills.templates import arithmetic_template

class PlanStep(TypedDict):
    """A single step in the orchestrator's execution plan."""
    agent: str
    task: str
    status: Literal["pending", "completed", "failed"]

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    code_files: dict[str, str]
    iteration_count: int
    review_status: Literal["approved", "changes"]
    reviewer_feedback: str
    pending_action: str
    approval_status: Literal["pending", "approved", "denied"]
    last_execution: str
    skill_result: str
    # Tester-related state
    test_code: str
    test_status: Literal["pending", "generated", "passed", "failed", "skipped"]
    # Orchestrator-related state
    execution_plan: list[PlanStep]
    orchestrator_status: Literal["planning", "executing", "completed"]

def approver_node(state: AgentState) -> dict:
    approval = state.get("approval_status", "pending")
    return {
        "approval_status": approval,
        "pending_action": "execute:app.py:add()",
        "messages": [
            AIMessage(
                content="Approval requested for executing app.py.",
                additional_kwargs={
                    "role": "approver",
                    "status": "pending",
                },
            )
        ],
    }

def executor_node(state: AgentState) -> dict:
    """Execute code from code_files using the sandbox.
    Falls back to skill registry execution for backward compatibility
    when no code_files are available.
    """
    if state.get("approval_status") != "approved":
        raise RuntimeError("Execution denied or not approved.")
    code_files = state.get("code_files", {})
    if code_files:
        # Execute actual generated code via sandbox
        from examples.agent_system.sandbox import LocalExecutor
        executor = LocalExecutor(timeout_seconds=30)
        # Combine all code files for execution
        combined_code = "\n".join(code_files.values())
        exec_result = executor.execute(combined_code)
        return {
            "last_execution": f"Executed {len(code_files)} file(s)",
            "skill_result": exec_result.stdout if exec_result.is_success() else exec_result.stderr,
            "messages": [
                AIMessage(
                    content=f"Executor: {'success' if exec_result.is_success() else 'error'}.",
                    additional_kwargs={
                        "role": "executor",
                        "result": "success" if exec_result.is_success() else "error",
                        "exit_code": exec_result.exit_code,
                    },
                )
            ],
        }
    # Fallback: skill registry execution for backward compatibility
    registry = SkillRegistry()
    registry.register("arithmetic", "examples.agent_system.skills.arithmetic")
    skill = registry.get("arithmetic").module
    try:
        result = skill.add(2, 3)
        return {
            "last_execution": "Executed app.py:add()",
            "skill_result": str(result),
            "messages": [
                AIMessage(
                    content="Executor: execution completed.",
                    additional_kwargs={
                        "role": "executor",
                        "result": "success",
                    },
                )
            ],
        }
    except Exception as exc:  # noqa: BLE001
        editor = SkillEditor(registry)
        editor.update_source("arithmetic", arithmetic_template("add"))
        reloader = SkillReloader(registry)
        reloader.reload("arithmetic")
        skill = registry.get("arithmetic").module
        result = skill.add(2, 3)
        return {
            "last_execution": f"Executed app.py:add() after repair: {exc}",
            "skill_result": str(result),
            "messages": [
                AIMessage(
                    content="Executor: repaired skill and executed.",
                    additional_kwargs={
                        "role": "executor",
                        "result": "repaired",
                    },
                )
            ],
        }

_MAX_ITERATIONS = 10

def _route_after_review(state: AgentState) -> str:
    """Route after reviewer: changes -> coder, approved -> tester.
    Enforces max_iterations to prevent infinite loops.
    """
    if state.get("iteration_count", 0) >= _MAX_ITERATIONS:
        return "tester"
    return "coder" if state.get("review_status") == "changes" else "tester"

def _route_after_tester(state: AgentState) -> str:
    """Route after tester: failed -> coder (for fixes), otherwise -> approver.
    Enforces max_iterations to prevent infinite loops.
    """
    if state.get("iteration_count", 0) >= _MAX_ITERATIONS:
        return "approver"
    test_status = state.get("test_status", "pending")
    if test_status == "failed":
        return "coder"
    return "approver"

def _resolve_roles(
    *,
    llm: BaseChatModel | None = None,
    registry: RoleRegistry | None = None,
    role_names: tuple[str, ...] = ("coder", "reviewer", "tester"),
) -> tuple:
    """Resolve role node functions from registry or create defaults.
    Returns:
        Tuple of node callables in the same order as role_names.
    """
    nodes = []
    role_classes = {"coder": CoderRole, "reviewer": ReviewerRole, "tester": TesterRole}
    for name in role_names:
        if registry is not None:
            role = registry.get(name)
        else:
            role = role_classes[name](llm=llm)
        nodes.append(role.as_node())
    return tuple(nodes)

def build_graph(
    *,
    llm: BaseChatModel | None = None,
    registry: RoleRegistry | None = None,
    interrupt_before: list[str] | None = None,
    checkpointer=None,
) -> StateGraph:
    """Build the agent graph.
    Args:
        llm: Optional LLM instance for code generation and review.
            If None, uses fallback deterministic logic (for testing).
        registry: Optional RoleRegistry with pre-configured roles.
            If provided, roles are retrieved from the registry.
            If None, creates roles using legacy factory functions or default Role classes.
        interrupt_before: Nodes to interrupt before (for human-in-the-loop).
        checkpointer: Checkpoint saver for state persistence.
    Returns:
        Compiled StateGraph ready for execution.
    Example:
        >>> from examples.agent_system.llm import get_llm
        >>> from examples.agent_system.roles.registry import create_default_registry
        >>> # With LLM
        >>> graph = build_graph(llm=get_llm())
        >>> # With registry
        >>> graph = build_graph(registry=create_default_registry())
        >>> # Without LLM (fallback mode)
        >>> graph = build_graph()
    """
    coder, reviewer, tester = _resolve_roles(llm=llm, registry=registry)
    graph = StateGraph(AgentState)
    graph.add_node("coder", coder)
    graph.add_node("reviewer", reviewer)
    graph.add_node("tester", tester)
    graph.add_node("approver", approver_node)
    graph.add_node("executor", executor_node)
    graph.add_edge(START, "coder")
    graph.add_edge("coder", "reviewer")
    graph.add_conditional_edges("reviewer", _route_after_review)
    graph.add_conditional_edges("tester", _route_after_tester)
    graph.add_edge("approver", "executor")
    graph.add_edge("executor", END)
    return graph.compile(
        interrupt_before=interrupt_before,
        checkpointer=checkpointer,
    )

def build_initial_state() -> AgentState:
    return {
        "messages": [
            SystemMessage(
                content="You are a multi-role coding agent. Follow reviewer feedback."
            ),
            HumanMessage(content="Implement add(a, b) in app.py.")
        ],
        "code_files": {},
        "iteration_count": 0,
        "review_status": "changes",
        "reviewer_feedback": "",
        "pending_action": "",
        "approval_status": "pending",
        "last_execution": "",
        "skill_result": "",
        "test_code": "",
        "test_status": "pending",
        "execution_plan": [],
        "orchestrator_status": "planning",
    }

@dataclass
class CheckpointedRun:
    graph: object
    thread_id: str
    config: dict

def build_checkpointed_graph(
    checkpointer,
    *,
    interrupt_before: list[str],
    llm: BaseChatModel | None = None,
    registry: RoleRegistry | None = None,
) -> CheckpointedRun:
    """Build a checkpointed graph for human-in-the-loop workflows.
    Args:
        checkpointer: Checkpoint saver for state persistence.
        interrupt_before: Nodes to interrupt before.
        llm: Optional LLM instance for code generation and review.
        registry: Optional RoleRegistry with pre-configured roles.
    Returns:
        CheckpointedRun with graph, thread_id, and config.
    """
    graph = build_graph(
        llm=llm,
        registry=registry,
        interrupt_before=interrupt_before,
        checkpointer=checkpointer,
    )
    thread_id = "agent-system"
    config = {"configurable": {"thread_id": thread_id}}
    return CheckpointedRun(graph=graph, thread_id=thread_id, config=config)

