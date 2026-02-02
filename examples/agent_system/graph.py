from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph, add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    code_files: dict[str, str]
    iteration_count: int
    review_status: Literal["approved", "changes"]
    reviewer_feedback: str
    pending_action: str
    approval_status: Literal["pending", "approved", "denied"]
    last_execution: str


def _render_bad_code() -> str:
    return """def add(a, b):
    # TODO: fix math
    return a - b
"""


def _render_good_code() -> str:
    return """def add(a, b):
    return a + b
"""


def coder_node(state: AgentState) -> dict:
    iteration = state.get("iteration_count", 0)
    code_files = dict(state.get("code_files", {}))
    if iteration == 0:
        code_files["app.py"] = _render_bad_code()
        message = AIMessage(
            content="Coder: wrote initial add() implementation.",
            additional_kwargs={
                "role": "coder",
                "summary": "initial implementation",
            },
        )
    else:
        code_files["app.py"] = _render_good_code()
        message = AIMessage(
            content="Coder: fixed add() implementation.",
            additional_kwargs={
                "role": "coder",
                "summary": "fixed math logic",
            },
        )

    return {
        "code_files": code_files,
        "iteration_count": iteration + 1,
        "messages": [message],
    }


def reviewer_node(state: AgentState) -> dict:
    code = state.get("code_files", {}).get("app.py", "")
    if "return a + b" in code and "TODO" not in code:
        review_status: Literal["approved", "changes"] = "approved"
        feedback = "Reviewer: approved."
    else:
        review_status = "changes"
        feedback = "Reviewer: add() is incorrect; please fix math."

    review_message = AIMessage(
        content=feedback,
        additional_kwargs={
            "role": "reviewer",
            "status": review_status,
        },
    )

    return {
        "review_status": review_status,
        "reviewer_feedback": feedback,
        "messages": [review_message],
    }


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
    if state.get("approval_status") != "approved":
        raise RuntimeError("Execution denied or not approved.")
    return {
        "last_execution": "Executed app.py:add()",
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


def _route_from_reviewer(state: AgentState) -> str:
    return "coder" if state.get("review_status") == "changes" else END


def _route_after_review(state: AgentState) -> str:
    return "coder" if state.get("review_status") == "changes" else "approver"


def build_graph(
    *,
    interrupt_before: list[str] | None = None,
    checkpointer=None,
) -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("coder", coder_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("approver", approver_node)
    graph.add_node("executor", executor_node)
    graph.add_edge(START, "coder")
    graph.add_edge("coder", "reviewer")
    graph.add_conditional_edges("reviewer", _route_after_review)
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
    }


@dataclass
class CheckpointedRun:
    graph: object
    thread_id: str
    config: dict


def build_checkpointed_graph(
    checkpointer, *, interrupt_before: list[str]
) -> CheckpointedRun:
    graph = build_graph(interrupt_before=interrupt_before, checkpointer=checkpointer)
    thread_id = "agent-system"
    config = {"configurable": {"thread_id": thread_id}}
    return CheckpointedRun(graph=graph, thread_id=thread_id, config=config)
