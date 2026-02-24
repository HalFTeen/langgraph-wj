"""Coordinator - System-level scheduler for NAL.
The Coordinator is NOT an Agent role. It is the main loop that:
1. Checks for READY tasks (idle)
2. Dispatches tasks to agents (dispatch)
3. Waits for agent execution via TDD Protocol (execute)
4. Evaluates results (evaluate)
5. Merges completed work (merge)
Built on LangGraph StateGraph, uses Core layer modules
(TaskGraph, GitOps, TDDProtocol, AgentInterface) for all operations.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Annotated, Any, TypedDict
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph, add_messages
from examples.agent_system.core.agent_interface import (
    AgentInterface,
    AgentResult,
    AgentRole,
    FallbackAdapter,
)
from examples.agent_system.core.git_ops import GitOps, GitOpsError, step_branch_name
from examples.agent_system.core.task_graph import Task, TaskGraph, TaskStatus
from examples.agent_system.integrations.feishu_notifier import FeishuNotifier

logger = logging.getLogger(__name__)

# --- Coordinator State ---


class CoordinatorState(TypedDict):
    """State managed by the Coordinator loop."""

    messages: Annotated[list[BaseMessage], add_messages]
    # TaskGraph (serialized)
    task_graph: dict
    current_task_id: str
    # Coordinator phase
    phase: (
        str  # idle | planning | dispatch | execute | evaluate | merge | done | failed
    )
    # Agent sessions
    active_agents: list[dict]
    # Current execution
    agent_result: dict  # AgentResult serialized
    tdd_result: dict  # TDDResult serialized
    # Reviewer feedback (passed to Coder on retry)
    last_review_feedback: str
    # Counters
    tasks_completed: int
    tasks_failed: int
    total_iterations: int


# --- Coordinator Nodes ---


def plan_node(state: CoordinatorState) -> dict:
    """Call PlannerRole to decompose requirement into TaskGraph.
    If task_graph already has tasks (resume mode), skip planning.
    """
    existing_graph = state.get("task_graph", {})
    if existing_graph.get("tasks"):
        logger.info(
            "Skipping plan (resume mode, %d existing tasks)",
            len(existing_graph["tasks"]),
        )
        return {"phase": "dispatch"}
    agents = _get_agents(state)
    planner = agents.get("planner")
    if planner is None:
        planner = FallbackAdapter(agent_role=AgentRole.PLANNER)
    requirement = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            requirement = msg.content
            break
    result = planner.execute_task(requirement)
    if result.task_graph:
        task_graph = result.task_graph
    else:
        task_graph = {
            "tasks": {
                "step-1": {
                    "id": "step-1",
                    "title": requirement[:80],
                    "description": requirement,
                    "status": "pending",
                    "depends_on": [],
                    "parent_id": None,
                    "assigned_agent": None,
                    "branch": None,
                    "tdd_mode": "full",
                    "test_file": None,
                    "max_retries": 3,
                    "retry_count": 0,
                    "diff_line_limit": 100,
                    "github_issue_id": None,
                }
            }
        }
    task_count = len(task_graph.get("tasks", {}))
    # Feishu notification
    notifier = _get_notifier()
    notifier.notify_pipeline_started(
        thread_id=state.get("current_task_id", "nal"),
        requirement=requirement[:200],
        task_count=task_count,
    )
    return {
        "task_graph": task_graph,
        "phase": "dispatch",
        "messages": [
            AIMessage(
                content=f"Planner: decomposed into {task_count} task(s).",
                additional_kwargs={"role": "coordinator", "action": "plan"},
            )
        ],
    }


def idle_node(state: CoordinatorState) -> dict:
    """Check if there are READY tasks to dispatch."""
    graph = TaskGraph.from_dict(state.get("task_graph", {"tasks": {}}))
    notifier = _get_notifier()
    if graph.is_complete():
        completed = len(graph.get_tasks_by_status(TaskStatus.DONE))
        failed = len(graph.get_tasks_by_status(TaskStatus.FAILED))
        notifier.notify_pipeline_done("nal", completed=completed, failed=failed)
        return {
            "phase": "done",
            "messages": [
                AIMessage(
                    content="Coordinator: all tasks completed.",
                    additional_kwargs={"role": "coordinator", "action": "complete"},
                )
            ],
        }
    if graph.has_failed():
        ready = graph.get_ready_tasks()
        if not ready:
            completed = len(graph.get_tasks_by_status(TaskStatus.DONE))
            failed = len(graph.get_tasks_by_status(TaskStatus.FAILED))
            notifier.notify_pipeline_done("nal", completed=completed, failed=failed)
            return {
                "phase": "failed",
                "messages": [
                    AIMessage(
                        content="Coordinator: pipeline blocked. Failed tasks need human intervention.",
                        additional_kwargs={"role": "coordinator", "action": "blocked"},
                    )
                ],
            }
    ready = graph.get_ready_tasks()
    if ready:
        return {"phase": "dispatch"}
    return {"phase": "done"}


def dispatch_node(state: CoordinatorState) -> dict:
    """Select a READY task, create branch, acquire lock, assign agent."""
    graph = TaskGraph.from_dict(state.get("task_graph", {"tasks": {}}))
    ready = graph.get_ready_tasks()
    if not ready:
        return {"phase": "idle"}
    task = ready[0]
    task_id = task.id
    graph.update_status(task_id, TaskStatus.ASSIGNED)
    agents = _get_agents(state)
    coder = agents.get("coder")
    agent_id = coder.agent_id if coder else "unassigned"
    task.assigned_agent = agent_id
    # --- Real Git: create or checkout branch + acquire lock ---
    git_ops = _get_git_ops()
    if git_ops:
        branch = step_branch_name("nal", _task_seq(task_id))
        task.branch = branch
        default_branch = git_ops.get_default_branch()
        existing_branches = git_ops.list_branches()
        try:
            if branch in existing_branches:
                # Retry: rebase onto latest default branch so agent sees all previous work
                git_ops.checkout(branch)
                if git_ops.rebase(branch, default_branch):
                    logger.info("Rebased %s onto %s (retry)", branch, default_branch)
                else:
                    # Rebase failed, delete and recreate from default branch
                    git_ops.checkout(default_branch)
                    git_ops.delete_branch_force(branch)
                    git_ops.create_branch(branch, base=default_branch)
                    logger.info(
                        "Recreated branch %s from %s (rebase failed)",
                        branch,
                        default_branch,
                    )
            else:
                git_ops.create_branch(branch, base=default_branch)
                logger.info("Created branch %s", branch)
            git_ops.acquire_lock(branch, agent_id)
        except GitOpsError as exc:
            logger.warning("Git branch/lock: %s (continuing)", exc)
    return {
        "task_graph": graph.to_dict(),
        "current_task_id": task_id,
        "phase": "execute",
        "messages": [
            AIMessage(
                content=f"Coordinator: dispatched task '{task.title}' to {agent_id}.",
                additional_kwargs={
                    "role": "coordinator",
                    "action": "dispatch",
                    "task_id": task_id,
                },
            )
        ],
    }


def execute_node(state: CoordinatorState) -> dict:
    """Execute task: agent writes code → files written to disk → git commit."""
    graph = TaskGraph.from_dict(state.get("task_graph", {"tasks": {}}))
    task_id = state.get("current_task_id", "")
    if not task_id or task_id not in graph.tasks:
        return {"phase": "idle", "agent_result": {}}
    task = graph.get_task(task_id)
    graph.update_status(task_id, TaskStatus.CODING)
    agents = _get_agents(state)
    coder = agents.get("coder")
    if coder is None:
        coder = FallbackAdapter(agent_role=AgentRole.CODER)
    git_ops = _get_git_ops()
    work_dir = _get_work_dir()
    # --- Checkout task branch ---
    if git_ops and task.branch:
        try:
            git_ops.checkout(task.branch)
        except GitOpsError as exc:
            logger.warning("Checkout failed: %s", exc)
    # --- Build context with previous feedback ---
    previous_feedback = state.get("last_review_feedback", "")
    task_prompt = task.description
    if previous_feedback:
        task_prompt = (
            f"{task.description}\n\n"
            f"IMPORTANT - Previous attempt was rejected by reviewer:\n"
            f"{previous_feedback}\n\n"
            f"Fix the issues mentioned above."
        )
        logger.info("Retry with reviewer feedback: %s", previous_feedback[:100])
    context = {
        "task_id": task_id,
        "tdd_mode": task.tdd_mode,
        "diff_line_limit": task.diff_line_limit,
        "working_dir": str(work_dir) if work_dir else "",
    }
    result = coder.execute_task(task_prompt, context)
    # --- Write files to disk ---
    if result.files_modified and work_dir:
        for filepath, content in result.files_modified.items():
            full_path = Path(work_dir) / filepath
            if not full_path.exists():
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
                logger.info("Wrote file: %s", full_path)
            else:
                logger.info("File already exists (written by agent): %s", full_path)
    if result.test_files and work_dir:
        for filepath, content in result.test_files.items():
            full_path = Path(work_dir) / filepath
            if not full_path.exists():
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
                logger.info("Wrote test file: %s", full_path)
    # --- Run tests before commit (only on task-related test files) ---
    tests_passed = True
    test_output = ""
    if work_dir:
        import subprocess as _sp
        import glob as _glob

        # Find test files created by the agent (in root or tests/ dir)
        test_files = []
        all_modified = list(result.files_modified.keys()) + list(
            result.test_files.keys()
        )
        for f in all_modified:
            if "test_" in f or "_test.py" in f:
                full = Path(work_dir) / f
                if full.exists():
                    test_files.append(str(full))
        # Also scan for any test_*.py in repo root (agent may have created them)
        for tf in _glob.glob(str(Path(work_dir) / "test_*.py")):
            if tf not in test_files:
                test_files.append(tf)
        if test_files:
            test_result = _sp.run(
                ["python", "-m", "pytest", "--tb=short", "-q"] + test_files,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            tests_passed = test_result.returncode == 0
            test_output = test_result.stdout + test_result.stderr
            if tests_passed:
                logger.info("Tests passed (%d file(s))", len(test_files))
            else:
                logger.warning("Tests FAILED:\n%s", test_output[-500:])
        else:
            logger.info("No test files found, skipping test validation")
    if not tests_passed:
        # Tests failed → mark as failure, Coordinator will retry
        result_dict = result.to_dict()
        result_dict["success"] = False
        result_dict["test_output"] = test_output[-500:]
        return {
            "task_graph": graph.to_dict(),
            "agent_result": result_dict,
            "last_review_feedback": f"Tests failed:\n{test_output[-500:]}",
            "phase": "evaluate",
            "messages": [
                AIMessage(
                    content=f"Agent {coder.agent_id}: tests FAILED for task '{task.title}'.",
                    additional_kwargs={
                        "role": "coordinator",
                        "action": "execute",
                        "success": False,
                    },
                )
            ],
        }
    # Git commit is now handled by user via /commit command (not auto-committed)
    commit_hash = ""
    result_dict = result.to_dict()
    result_dict["commit_hash"] = commit_hash
    return {
        "task_graph": graph.to_dict(),
        "agent_result": result_dict,
        "phase": "evaluate",
        "messages": [
            AIMessage(
                content=f"Agent {coder.agent_id}: {'completed' if result.success else 'failed'} task '{task.title}'."
                + (
                    f" Files: {len(result.files_modified)}"
                    if result.files_modified
                    else ""
                ),
                additional_kwargs={
                    "role": "coordinator",
                    "action": "execute",
                    "task_id": task_id,
                    "success": result.success,
                },
            )
        ],
    }


def evaluate_node(state: CoordinatorState) -> dict:
    """Evaluate execution result. Route to merge, retry, or fail."""
    graph = TaskGraph.from_dict(state.get("task_graph", {"tasks": {}}))
    task_id = state.get("current_task_id", "")
    agent_result = state.get("agent_result", {})
    if not task_id or task_id not in graph.tasks:
        return {"phase": "idle"}
    task = graph.get_task(task_id)
    success = agent_result.get("success", False)
    if success:
        agents = _get_agents(state)
        reviewer = agents.get("reviewer")
        review_passed = True
        if reviewer:
            review_result = reviewer.execute_task(
                f"Review code for task: {task.description}",
                {"code_files": agent_result.get("files_modified", {})},
            )
            review_passed = review_result.review_decision == "approved"
        if review_passed:
            graph.update_status(task_id, TaskStatus.VERIFYING)
            graph.update_status(task_id, TaskStatus.DONE)
            git_ops = _get_git_ops()
            if git_ops and task.branch and task.assigned_agent:
                git_ops.release_lock(task.branch, task.assigned_agent)
            notifier = _get_notifier()
            notifier.notify_task_completed(
                "nal",
                task_id,
                task.title,
                agent_result.get("commit_hash", ""),
            )
            return {
                "task_graph": graph.to_dict(),
                "phase": "merge",
                "last_review_feedback": "",  # Clear feedback on success
                "tasks_completed": state.get("tasks_completed", 0) + 1,
                "messages": [
                    AIMessage(
                        content=f"Coordinator: task '{task.title}' verified and done.",
                        additional_kwargs={
                            "role": "coordinator",
                            "action": "evaluate",
                            "result": "done",
                        },
                    )
                ],
            }
        else:
            task.retry_count += 1
            feedback = (
                review_result.review_feedback if review_result else "Review rejected"
            )
            if task.retry_count < task.max_retries:
                graph.update_status(task_id, TaskStatus.READY)
                notifier = _get_notifier()
                notifier.notify_task_retry(
                    "nal",
                    task_id,
                    task.title,
                    task.retry_count,
                    task.max_retries,
                    reason=feedback[:100],
                )
                return {
                    "task_graph": graph.to_dict(),
                    "phase": "dispatch",
                    "last_review_feedback": feedback,  # Pass to Coder on retry
                    "messages": [
                        AIMessage(
                            content=f"Coordinator: review rejected, retrying ({task.retry_count}/{task.max_retries}).",
                            additional_kwargs={
                                "role": "coordinator",
                                "action": "retry",
                            },
                        )
                    ],
                }
    # Failure path
    task.retry_count += 1
    # Get failure reason from agent_result or test output
    failure_reason = agent_result.get("test_output", "") or agent_result.get(
        "message", "Execution failed"
    )
    notifier = _get_notifier()
    if task.retry_count < task.max_retries:
        graph.update_status(task_id, TaskStatus.READY)
        notifier.notify_task_retry(
            "nal",
            task_id,
            task.title,
            task.retry_count,
            task.max_retries,
            reason=failure_reason[:100],
        )
        return {
            "task_graph": graph.to_dict(),
            "phase": "dispatch",
            "total_iterations": state.get("total_iterations", 0) + 1,
            "messages": [
                AIMessage(
                    content=f"Coordinator: task failed, retrying ({task.retry_count}/{task.max_retries}).",
                    additional_kwargs={"role": "coordinator", "action": "retry"},
                )
            ],
        }
    graph.update_status(task_id, TaskStatus.FAILED)
    git_ops = _get_git_ops()
    if git_ops and task.branch and task.assigned_agent:
        git_ops.release_lock(task.branch, task.assigned_agent)
    # Feishu notification: FAILED, needs human
    notifier.notify_task_failed("nal", task_id, task.title, task.max_retries)
    return {
        "task_graph": graph.to_dict(),
        "phase": "idle",
        "tasks_failed": state.get("tasks_failed", 0) + 1,
        "messages": [
            AIMessage(
                content=f"Coordinator: task '{task.title}' FAILED after {task.max_retries} retries.",
                additional_kwargs={
                    "role": "coordinator",
                    "action": "failed",
                    "task_id": task_id,
                },
            )
        ],
    }


def merge_node(state: CoordinatorState) -> dict:
    """Merge completed task branch into main. Then check for more tasks."""
    graph = TaskGraph.from_dict(state.get("task_graph", {"tasks": {}}))
    task_id = state.get("current_task_id", "")
    # --- Real Git merge ---
    git_ops = _get_git_ops()
    if git_ops and task_id and task_id in graph.tasks:
        task = graph.get_task(task_id)
        if task.branch:
            default_branch = git_ops.get_default_branch()
            try:
                result = git_ops.merge(task.branch, default_branch)
                if result.success:
                    logger.info(
                        "Merged %s → %s: %s",
                        task.branch,
                        default_branch,
                        result.commit_hash,
                    )
                    # Sync with remote before push (skip in daemon mode)
                    if not _is_daemon_mode():
                        try:
                            git_ops.pull_rebase(default_branch)
                            git_ops.push(default_branch)
                        except GitOpsError as exc:
                            logger.warning("Push failed: %s", exc)
                    else:
                        logger.info("Daemon mode: skip push (local only)")
                else:
                    logger.error(
                        "Merge conflict %s → %s: %s",
                        task.branch,
                        default_branch,
                        result.conflicts,
                    )
            except GitOpsError as exc:
                logger.warning("Merge failed: %s", exc)
    if graph.is_complete():
        return {
            "phase": "done",
            "messages": [
                AIMessage(
                    content="Coordinator: all tasks completed. Pipeline done.",
                    additional_kwargs={"role": "coordinator", "action": "complete"},
                )
            ],
        }
    ready = graph.get_ready_tasks()
    if ready:
        return {
            "task_graph": graph.to_dict(),
            "phase": "dispatch",
            "messages": [
                AIMessage(
                    content=f"Coordinator: {len(ready)} task(s) unlocked, continuing.",
                    additional_kwargs={"role": "coordinator", "action": "merge"},
                )
            ],
        }
    return {"task_graph": graph.to_dict(), "phase": "idle"}


# --- Routing ---


def route_after_plan(state: CoordinatorState) -> str:
    phase = state.get("phase", "dispatch")
    return "dispatch" if phase == "dispatch" else "idle"


def route_after_idle(state: CoordinatorState) -> str:
    phase = state.get("phase", "done")
    if phase == "dispatch":
        return "dispatch"
    return END


def route_after_dispatch(state: CoordinatorState) -> str:
    phase = state.get("phase", "idle")
    return "execute" if phase == "execute" else "idle"


def route_after_evaluate(state: CoordinatorState) -> str:
    phase = state.get("phase", "idle")
    if phase == "merge":
        return "merge"
    if phase == "dispatch":
        return "dispatch"
    return "idle"


def route_after_merge(state: CoordinatorState) -> str:
    phase = state.get("phase", "done")
    if phase == "dispatch":
        return "dispatch"
    if phase == "done":
        return END
    return "idle"


# --- Graph Builder ---


def build_coordinator_graph(
    agents: dict[str, AgentInterface] | None = None,
    git_ops: GitOps | None = None,
    work_dir: str | None = None,
    notifier: FeishuNotifier | None = None,
    checkpointer=None,
    interrupt_before: list[str] | None = None,
    daemon_mode: bool = False,
) -> StateGraph:
    """Build the Coordinator's main loop as a LangGraph StateGraph.
    Args:
        agents: Dict of role_name → AgentInterface. If None, uses FallbackAdapters.
        git_ops: GitOps instance for real git operations. If None, git ops are skipped.
        work_dir: Working directory where files are written. If None, file writes are skipped.
        notifier: FeishuNotifier for push notifications. If None, creates from env.
        checkpointer: Optional checkpoint saver for persistence.
        interrupt_before: Optional nodes to pause before (human gate).
    Returns:
        Compiled StateGraph.
    """
    agent_registry = agents or {
        "planner": FallbackAdapter(agent_role=AgentRole.PLANNER),
        "coder": FallbackAdapter(agent_role=AgentRole.CODER),
        "reviewer": FallbackAdapter(agent_role=AgentRole.REVIEWER),
        "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER),
    }
    _set_agent_registry(agent_registry)
    _set_git_ops(git_ops)
    _set_work_dir(work_dir)
    _set_notifier(notifier or FeishuNotifier())
    _set_daemon_mode(daemon_mode)
    graph = StateGraph(CoordinatorState)
    graph.add_node("plan", plan_node)
    graph.add_node("idle", idle_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("execute", execute_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("merge", merge_node)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", route_after_plan)
    graph.add_conditional_edges("idle", route_after_idle)
    graph.add_conditional_edges("dispatch", route_after_dispatch)
    graph.add_edge("execute", "evaluate")
    graph.add_conditional_edges("evaluate", route_after_evaluate)
    graph.add_conditional_edges("merge", route_after_merge)
    return graph.compile(
        interrupt_before=interrupt_before,
        checkpointer=checkpointer,
    )


def build_coordinator_initial_state(requirement: str) -> CoordinatorState:
    """Build initial state for the Coordinator."""
    return {
        "messages": [HumanMessage(content=requirement)],
        "task_graph": {"tasks": {}},
        "current_task_id": "",
        "phase": "planning",
        "active_agents": [],
        "agent_result": {},
        "tdd_result": {},
        "last_review_feedback": "",
        "tasks_completed": 0,
        "tasks_failed": 0,
        "total_iterations": 0,
    }


# --- Module-level singletons (accessed by nodes) ---
_agent_registry: dict[str, AgentInterface] = {}
_git_ops_instance: GitOps | None = None
_work_dir_path: str | None = None
_notifier_instance: FeishuNotifier = FeishuNotifier()
_daemon_mode: bool = False


def _set_agent_registry(registry: dict[str, AgentInterface]) -> None:
    global _agent_registry
    _agent_registry = registry


def _get_agents(state: CoordinatorState) -> dict[str, AgentInterface]:
    return _agent_registry


def _set_git_ops(ops: GitOps | None) -> None:
    global _git_ops_instance
    _git_ops_instance = ops


def _get_git_ops() -> GitOps | None:
    return _git_ops_instance


def _set_work_dir(path: str | None) -> None:
    global _work_dir_path
    _work_dir_path = path


def _get_work_dir() -> str | None:
    return _work_dir_path


def _set_notifier(notifier: FeishuNotifier) -> None:
    global _notifier_instance
    _notifier_instance = notifier


def _get_notifier() -> FeishuNotifier:
    return _notifier_instance


def _set_daemon_mode(enabled: bool) -> None:
    global _daemon_mode
    _daemon_mode = enabled


def _is_daemon_mode() -> bool:
    return _daemon_mode


def run_planner_standalone(requirement: str, feedback: str = "") -> dict:
    """Run Planner independently, return task_graph dict.
    Used by daemon mode to call Planner outside the LangGraph graph,
    allowing human feedback loop before dispatching.
    Args:
        requirement: Original task description.
        feedback: Human feedback (e.g., "change dark theme to light").
    Returns:
        task_graph dict with tasks.
    """
    planner = _agent_registry.get("planner")
    if planner is None:
        planner = FallbackAdapter(agent_role=AgentRole.PLANNER)
    prompt = requirement
    if feedback:
        prompt = f"{requirement}\n\n用户反馈：{feedback}\n请根据反馈调整任务拆解。"
    result = planner.execute_task(prompt)
    if result.task_graph:
        return result.task_graph
    return {
        "tasks": {
            "step-1": {
                "id": "step-1",
                "title": requirement[:80],
                "description": requirement,
                "status": "pending",
                "depends_on": [],
                "parent_id": None,
                "assigned_agent": None,
                "branch": None,
                "tdd_mode": "full",
                "test_file": None,
                "max_retries": 3,
                "retry_count": 0,
                "diff_line_limit": 100,
                "github_issue_id": None,
            }
        }
    }


def _task_seq(task_id: str) -> int:
    """Extract numeric sequence from task ID, or hash to int."""
    digits = "".join(c for c in task_id if c.isdigit())
    if digits:
        return int(digits)
    return abs(hash(task_id)) % 10000
