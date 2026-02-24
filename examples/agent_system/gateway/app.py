from __future__ import annotations
import os
import threading
import traceback
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, SystemMessage
from examples.agent_system.gateway.discord_bot import DiscordConfig, DiscordGateway
from examples.agent_system.gateway.models import (
    ApprovalRecord,
    ApprovalRequest,
    ApprovalResolution,
    TaskResult,
    TaskSubmission,
)
from examples.agent_system.gateway.state_store import ApprovalStore
from examples.agent_system.graph import AgentState, build_graph

# Application-level singletons initialized at startup
_checkpointer: SqliteSaver | None = None
_graph = None
approval_store = ApprovalStore.empty()
# Track running tasks: thread_id -> TaskResult
_task_results: dict[str, TaskResult] = {}


def _init_graph() -> None:
    """Initialize the shared checkpointer and graph (called at startup)."""
    import sqlite3

    global _checkpointer_cm, _checkpointer, _graph
    # check_same_thread=False is required because _run_task
    # executes graph in a background thread
    conn = sqlite3.connect("agent_system.db", check_same_thread=False)
    _checkpointer = SqliteSaver(conn)
    _checkpointer.setup()
    # Try to create LLM from environment; fall back to deterministic mode
    llm = None
    try:
        from examples.agent_system.llm import get_llm

        llm = get_llm()
        print(f"[gateway] LLM initialized: {type(llm).__name__}")
    except Exception as exc:
        print(f"[gateway] No LLM configured ({exc}), using fallback mode")
    _graph = build_graph(
        llm=llm,
        interrupt_before=["executor"],
        checkpointer=_checkpointer,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_graph()
    yield
    if _checkpointer is not None:
        _checkpointer.conn.close()


app = FastAPI(lifespan=lifespan)


def _get_discord_gateway() -> DiscordGateway:
    token = os.getenv("DISCORD_TOKEN", "")
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "")
    return DiscordGateway(DiscordConfig(token=token, channel_id=channel_id))


def _run_task(thread_id: str, task: str) -> None:
    """Run agent graph for a task in a background thread."""
    if _graph is None:
        _task_results[thread_id] = TaskResult(
            thread_id=thread_id,
            task=task,
            status="error: graph not initialized",
        )
        return
    import time

    initial_state: AgentState = {
        "messages": [
            SystemMessage(
                content="You are a multi-role coding agent. Follow reviewer feedback."
            ),
            HumanMessage(content=task),
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
    config = {"configurable": {"thread_id": thread_id}}
    # Retry loop for rate limit (429) errors
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[task:{thread_id}] starting graph execution (attempt {attempt})...")
            for step in _graph.stream(
                initial_state if attempt == 1 else None,
                config,
            ):
                for node_name in step:
                    if node_name == "__interrupt__":
                        print(f"[task:{thread_id}] interrupted before executor")
                    else:
                        print(f"[task:{thread_id}] {node_name} done")
            # Success — read state after interrupt
            state = _graph.get_state(config)
            values = state.values
            approval_store.create(
                ApprovalRequest(
                    thread_id=thread_id,
                    pending_action="execute code",
                    summary=f"Task: {task}",
                )
            )
            code_files = values.get("code_files", {})
            code = next(iter(code_files.values()), None) if code_files else None
            _task_results[thread_id] = TaskResult(
                thread_id=thread_id,
                task=task,
                status="awaiting_approval",
                review_status=values.get("review_status"),
                test_status=values.get("test_status"),
                code=code,
                iteration_count=values.get("iteration_count", 0),
            )
            print(
                f"[task:{thread_id}] awaiting approval (iterations={values.get('iteration_count')})"
            )
            return  # success
        except Exception as exc:
            err_str = str(exc)
            is_rate_limit = (
                "429" in err_str
                or "Too Many Requests" in err_str
                or "timed out" in err_str
                or "ReadTimeout" in err_str
            )
            if is_rate_limit and attempt < max_retries:
                wait = attempt * 5  # 5s, 10s, 15s, 20s
                print(
                    f"[task:{thread_id}] rate limited, retrying in {wait}s (attempt {attempt}/{max_retries})"
                )
                _task_results[thread_id] = TaskResult(
                    thread_id=thread_id,
                    task=task,
                    status=f"running (retry {attempt}, waiting {wait}s for rate limit)",
                )
                time.sleep(wait)
                continue
            tb = traceback.format_exc()
            print(f"[task:{thread_id}] ERROR: {exc}\n{tb}")
            _task_results[thread_id] = TaskResult(
                thread_id=thread_id,
                task=task,
                status=f"error: {exc}",
            )
            return


# ---- Task endpoints ----
@app.post("/task/submit", response_model=TaskResult)
def submit_task(payload: TaskSubmission) -> TaskResult:
    """Submit a coding task to the agent system."""
    if _graph is None:
        raise HTTPException(status_code=503, detail="graph not initialized")
    thread_id = payload.thread_id or str(uuid.uuid4())[:12]
    # Placeholder result
    result = TaskResult(
        thread_id=thread_id,
        task=payload.task,
        status="running",
    )
    _task_results[thread_id] = result
    # Run in a real thread (not BackgroundTasks) so it doesn't block the server
    t = threading.Thread(target=_run_task, args=(thread_id, payload.task), daemon=True)
    t.start()
    return result


@app.get("/task/{thread_id}", response_model=TaskResult)
def get_task_status(thread_id: str) -> TaskResult:
    """Get the current status of a task."""
    result = _task_results.get(thread_id)
    if result is None:
        raise HTTPException(status_code=404, detail="task not found")
    return result


# ---- Approval endpoints ----
@app.post("/approval/request", response_model=ApprovalRecord)
def request_approval(payload: ApprovalRequest) -> ApprovalRecord:
    record = approval_store.create(payload)
    discord = _get_discord_gateway()
    if discord.config.token and discord.config.channel_id:
        discord.post_approval_request(payload.thread_id, payload.summary)
    return record


@app.post("/approval/resolve", response_model=ApprovalRecord)
def resolve_approval(payload: ApprovalResolution) -> ApprovalRecord:
    record = approval_store.get(payload.thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if _graph is None:
        raise HTTPException(status_code=503, detail="graph not initialized")
    status = payload.decision
    updated = approval_store.resolve(
        payload.thread_id,
        status=status,
        reviewer=payload.reviewer,
        reason=payload.reason,
    )
    # Resume the graph from the interrupt point
    config = {"configurable": {"thread_id": payload.thread_id}}
    _graph.update_state(config, {"approval_status": status})
    _graph.invoke(None, config)
    # Update task result
    state = _graph.get_state(config)
    values = state.values
    if payload.thread_id in _task_results:
        _task_results[payload.thread_id].status = (
            "completed" if status == "approved" else "denied"
        )
        code_files = values.get("code_files", {})
        _task_results[payload.thread_id].code = (
            next(iter(code_files.values()), None) if code_files else None
        )
    return updated


# ===========================================================================
# Coordinator API endpoints (NAL pipeline)
# ===========================================================================
from examples.agent_system.gateway.models import (
    PipelineStartRequest,
    PipelineStatus,
    TaskDetail,
)

# Track coordinator pipelines: thread_id -> last known state
_pipeline_states: dict[str, dict] = {}


def _build_agents_from_config(repo_path: str = "") -> dict:
    """Build agent registry based on NAL_ENGINE environment variable.
    Supported engines:
        - "fallback" (default): deterministic, no external dependencies
        - "opencode": OpenCode CLI subprocess
        - "claude-code": Claude Code CLI subprocess
        - "llm": LangChain LLM API (requires API key)
    """
    from examples.agent_system.core.agent_interface import AgentRole, FallbackAdapter

    engine = os.getenv("NAL_ENGINE", "fallback")
    work_dir = repo_path or os.getenv("REPO_PATH", os.getcwd())
    if engine == "opencode":
        from examples.agent_system.core.agent_interface import (
            OpenCodeAdapter,
            OpenCodeExplorerAdapter,
            OpenCodePlannerAdapter,
            OpenCodeReviewerAdapter,
        )

        return {
            "planner": OpenCodePlannerAdapter(),
            "coder": OpenCodeAdapter(
                worktree_path=work_dir,
                agent_role=AgentRole.CODER,
            ),
            "reviewer": OpenCodeReviewerAdapter(worktree_path=work_dir),
            "explorer": OpenCodeExplorerAdapter(repo_path=work_dir),
        }
    if engine == "claude-code":
        from examples.agent_system.core.agent_interface import (
            ClaudeCodeAdapter,
            ClaudeExplorerAdapter,
            ClaudePlannerAdapter,
            ClaudeReviewerAdapter,
        )

        return {
            "planner": ClaudePlannerAdapter(),
            "coder": ClaudeCodeAdapter(
                worktree_path=work_dir,
                agent_role=AgentRole.CODER,
            ),
            "reviewer": ClaudeReviewerAdapter(),
            "explorer": ClaudeExplorerAdapter(repo_path=work_dir),
        }
    if engine == "llm":
        try:
            from examples.agent_system.core.agent_interface import LLMAgentAdapter
            from examples.agent_system.llm import get_llm
            from examples.agent_system.roles.coder import CoderRole
            from examples.agent_system.roles.reviewer import ReviewerRole

            llm = get_llm()
            return {
                "planner": FallbackAdapter(agent_role=AgentRole.PLANNER),
                "coder": LLMAgentAdapter(
                    CoderRole(llm=llm), agent_role=AgentRole.CODER
                ),
                "reviewer": LLMAgentAdapter(
                    ReviewerRole(llm=llm), agent_role=AgentRole.REVIEWER
                ),
                "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER),
            }
        except Exception as exc:
            print(f"[gateway] LLM engine init failed ({exc}), falling back")
    return {
        "planner": FallbackAdapter(agent_role=AgentRole.PLANNER),
        "coder": FallbackAdapter(agent_role=AgentRole.CODER),
        "reviewer": FallbackAdapter(agent_role=AgentRole.REVIEWER),
        "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER),
    }


@app.post("/api/pipeline/start", response_model=PipelineStatus)
def start_pipeline(payload: PipelineStartRequest) -> PipelineStatus:
    """Start a new NAL pipeline.
    Triggers PlannerRole → Coordinator main loop.
    Agent engine is selected via NAL_ENGINE env var.
    """
    from examples.agent_system.coordinator import (
        build_coordinator_graph,
        build_coordinator_initial_state,
    )
    from examples.agent_system.integrations.feishu_notifier import FeishuNotifier

    thread_id = payload.thread_id or str(uuid.uuid4())[:12]
    agents = _build_agents_from_config(repo_path=payload.repo_path)
    work_dir = payload.repo_path or os.getenv("REPO_PATH", "") or os.getcwd()
    git_ops = None
    if work_dir and os.path.isdir(os.path.join(work_dir, ".git")):
        from examples.agent_system.core.git_ops import GitOps

        git_ops = GitOps(repo_path=work_dir)
    notifier = FeishuNotifier.from_env()

    def _run_pipeline() -> None:
        import traceback

        try:
            compiled = build_coordinator_graph(
                agents=agents,
                git_ops=git_ops,
                work_dir=work_dir or None,
                notifier=notifier,
            )
            state = build_coordinator_initial_state(payload.requirement)
            config = {"configurable": {"thread_id": thread_id}}
            _pipeline_states[thread_id] = {"phase": "planning"}
            for event in compiled.stream(state, config):
                for node_name, node_output in event.items():
                    if thread_id not in _pipeline_states:
                        _pipeline_states[thread_id] = {}
                    _pipeline_states[thread_id].update(node_output)
                    print(
                        f"[pipeline:{thread_id}] node={node_name} phase={node_output.get('phase', '?')}"
                    )
            # Capture agent_result error info if pipeline ended in failure
            final = _pipeline_states.get(thread_id, {})
            agent_result = final.get("agent_result", {})
            if agent_result and not agent_result.get("success"):
                final["error"] = agent_result.get("message", "") or agent_result.get(
                    "test_output", ""
                )
        except Exception as exc:
            tb = traceback.format_exc()
            print(f"[pipeline:{thread_id}] ERROR: {exc}\n{tb}")
            _pipeline_states[thread_id] = {
                "phase": "error",
                "error": str(exc),
            }

    t = threading.Thread(target=_run_pipeline, daemon=True)
    t.start()
    engine = os.getenv("NAL_ENGINE", "fallback")
    print(
        f"[pipeline:{thread_id}] started (engine={engine}, work_dir={work_dir or 'none'})"
    )
    return PipelineStatus(
        thread_id=thread_id,
        phase="planning",
    )


@app.get("/api/status", response_model=PipelineStatus)
def get_pipeline_status(thread_id: str = "") -> PipelineStatus:
    """Get current pipeline status."""
    if not thread_id:
        # Return most recent pipeline
        if not _pipeline_states:
            return PipelineStatus(thread_id="none", phase="idle")
        thread_id = list(_pipeline_states.keys())[-1]
    state = _pipeline_states.get(thread_id)
    if state is None:
        raise HTTPException(status_code=404, detail="pipeline not found")
    task_graph = state.get("task_graph", {})
    tasks = task_graph.get("tasks", {})
    status_counts = {}
    for t in tasks.values():
        s = t.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    return PipelineStatus(
        thread_id=thread_id,
        phase=state.get("phase", "unknown"),
        tasks_total=len(tasks),
        tasks_completed=status_counts.get("done", 0),
        tasks_failed=status_counts.get("failed", 0),
        tasks_ready=status_counts.get("ready", 0),
        tasks_blocked=status_counts.get("blocked", 0),
        error=state.get("error", ""),
    )


@app.post("/api/pipeline/stop")
def stop_pipeline(thread_id: str = "") -> dict:
    """Stop/pause a running pipeline."""
    # In MVP, we just mark it. Full implementation would interrupt the thread.
    if thread_id and thread_id in _pipeline_states:
        _pipeline_states[thread_id]["phase"] = "stopped"
    return {"status": "stopped", "thread_id": thread_id}


@app.post("/api/task/{task_id}/resume")
def resume_task(task_id: str) -> dict:
    """Resume a failed task (human intervention)."""
    # Find the pipeline containing this task
    for tid, state in _pipeline_states.items():
        task_graph = state.get("task_graph", {})
        tasks = task_graph.get("tasks", {})
        if task_id in tasks:
            tasks[task_id]["status"] = "ready"
            tasks[task_id]["retry_count"] = 0
            return {"status": "resumed", "task_id": task_id, "pipeline": tid}
    raise HTTPException(status_code=404, detail=f"task {task_id} not found")


@app.get("/api/task/{task_id}", response_model=TaskDetail)
def get_task_detail(task_id: str) -> TaskDetail:
    """Get detail of a specific task."""
    for state in _pipeline_states.values():
        task_graph = state.get("task_graph", {})
        tasks = task_graph.get("tasks", {})
        if task_id in tasks:
            t = tasks[task_id]
            return TaskDetail(
                task_id=t["id"],
                title=t.get("title", ""),
                description=t.get("description", ""),
                status=t.get("status", "unknown"),
                assigned_agent=t.get("assigned_agent"),
                tdd_mode=t.get("tdd_mode", "full"),
                retry_count=t.get("retry_count", 0),
                depends_on=t.get("depends_on", []),
            )
    raise HTTPException(status_code=404, detail=f"task {task_id} not found")


@app.get("/metrics")
def prometheus_metrics() -> str:
    """Expose Prometheus metrics."""
    try:
        from prometheus_client import generate_latest

        return generate_latest().decode("utf-8")
    except ImportError:
        return "# prometheus_client not installed\n"
