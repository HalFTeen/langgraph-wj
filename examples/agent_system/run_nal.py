#!/usr/bin/env python3
"""NAL Runner - Start a real NAL pipeline with Claude Code agents.
Usage:
    # 1. Clone target repo
    git clone anker@10.34.1.195:/Users/anker/git-server/langgraph-wj.git /tmp/nal-workspace
    # 2. Run NAL
    python -m examples.agent_system.run_nal \
        --repo /tmp/nal-workspace \
        --remote "anker@10.34.1.195:/Users/anker/git-server/langgraph-wj.git" \
        --task "Create a Python function add(a, b) that returns the sum, with tests"
    # Or with environment variables:
    REPO_PATH=/tmp/nal-workspace \
    GIT_REMOTE="anker@10.34.1.195:/Users/anker/git-server/langgraph-wj.git" \
    python -m examples.agent_system.run_nal \
        --task "Create a Python function add(a, b) that returns the sum, with tests"
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nal.runner")

def main() -> None:
    parser = argparse.ArgumentParser(description="NAL Pipeline Runner")
    parser.add_argument(
        "--repo",
        default=os.getenv("REPO_PATH", ""),
        help="Path to the target git repository",
    )
    parser.add_argument(
        "--remote",
        default=os.getenv("GIT_REMOTE", ""),
        help="Git remote URL (e.g. anker@10.34.1.195:/Users/anker/git-server/repo.git)",
    )
    parser.add_argument(
        "--task",
        required=True,
        help="The requirement / task description for the agents",
    )
    parser.add_argument(
        "--engine",
        choices=["claude-code", "fallback", "mixed"],
        default="claude-code",
        help="Agent execution engine: claude-code, fallback, or mixed (per-role via NAL_*_ENGINE env vars)",
    )
    parser.add_argument(
        "--thread-id",
        default="nal-run-001",
        help="Thread ID for checkpoint persistence",
    )
    parser.add_argument(
        "--scan-repo",
        action="store_true",
        help="Scan the repo codebase before planning (for existing projects)",
    )
    parser.add_argument(
        "--context-file",
        default="",
        help="Path to a context file (PRD, spec doc) to include in the requirement",
    )
    args = parser.parse_args()
    if not args.repo:
        logger.error("--repo is required. Set REPO_PATH env or pass --repo /path/to/repo")
        sys.exit(1)
    repo_path = os.path.abspath(args.repo)
    if not os.path.isdir(repo_path):
        logger.error("Repo path does not exist: %s", repo_path)
        sys.exit(1)
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        logger.error("Not a git repository: %s", repo_path)
        sys.exit(1)
    logger.info("=" * 60)
    logger.info("NAL Pipeline Runner")
    logger.info("=" * 60)
    logger.info("Repo:    %s", repo_path)
    logger.info("Remote:  %s", args.remote or "(none)")
    logger.info("Engine:  %s", args.engine)
    logger.info("Task:    %s", args.task)
    logger.info("=" * 60)
    # --- Step 1: Initialize GitOps ---
    from examples.agent_system.core.git_ops import GitOps
    git_ops = GitOps(repo_path=repo_path, remote_url=args.remote or None)
    if args.remote:
        try:
            git_ops.setup_remote(args.remote)
            logger.info("Remote configured: %s", args.remote)
        except Exception as exc:
            logger.warning("Remote setup: %s (may already exist)", exc)
    status = git_ops.get_status()
    logger.info("Repo status: branch=%s, clean=%s", status["branch"], status["clean"])
    # --- Step 1.5: Collect context (optional) ---
    enriched_task = args.task
    if args.context_file:
        context_path = os.path.abspath(args.context_file)
        if os.path.isfile(context_path):
            context_content = open(context_path).read()
            enriched_task = (
                f"{args.task}\n\n"
                f"=== Context Document: {os.path.basename(context_path)} ===\n"
                f"{context_content[:5000]}\n"
                f"=== End Context Document ===\n"
            )
            logger.info("Loaded context file: %s (%d chars)", context_path, len(context_content))
        else:
            logger.warning("Context file not found: %s", context_path)
    if args.scan_repo:
        logger.info("Scanning repo codebase...")
        from examples.agent_system.core.agent_interface import ClaudeExplorerAdapter
        # Quick local scan (no LLM, instant)
        repo_summary = ClaudeExplorerAdapter.scan_repo_structure(repo_path)
        if repo_summary:
            enriched_task = (
                f"{enriched_task}\n\n"
                f"=== Codebase Analysis ===\n"
                f"{repo_summary}\n"
                f"=== End Codebase Analysis ===\n"
            )
            logger.info("Repo scan complete (%d chars)", len(repo_summary))
        # Deep scan with Claude (optional, slower but more insightful)
        explorer = ClaudeExplorerAdapter(repo_path=repo_path)
        explore_result = explorer.execute_task(args.task)
        if explore_result.success and explore_result.message:
            enriched_task = (
                f"{enriched_task}\n\n"
                f"=== AI Codebase Analysis ===\n"
                f"{explore_result.message[:3000]}\n"
                f"=== End AI Codebase Analysis ===\n"
            )
            logger.info("AI code analysis complete")
        else:
            logger.warning("AI code analysis failed: %s", explore_result.message[:200])
    if enriched_task != args.task:
        logger.info("Task enriched with %d chars of context", len(enriched_task) - len(args.task))
    # --- Step 2: Initialize Agents ---
    from examples.agent_system.core.agent_interface import (
        AgentRole,
        ClaudeCodeAdapter,
        ClaudePlannerAdapter,
        ClaudeReviewerAdapter,
        FallbackAdapter,
        build_agents_from_config,
    )
    if args.engine == "mixed":
        from examples.agent_system.config import EngineConfig
        engine_config = EngineConfig.from_env()
        logger.info("Using mixed engine mode (per-role configuration)")
        agents = build_agents_from_config(engine_config, repo_path)
        for name, agent in agents.items():
            logger.info("  %s: %s (%s)", name, type(agent).__name__, agent.agent_id)
    elif args.engine == "claude-code":
        logger.info("Using Claude Code CLI as agent engine")
        agents = {
            "planner": ClaudePlannerAdapter(agent_id="claude-planner-1"),
            "coder": ClaudeCodeAdapter(
                worktree_path=repo_path,
                claude_md_content="",
                agent_role=AgentRole.CODER,
                agent_id="claude-coder-1",
                timeout_seconds=180,
            ),
            "reviewer": ClaudeReviewerAdapter(agent_id="claude-reviewer-1"),
            "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER, agent_id="explorer-1"),
        }
    else:
        logger.info("Using Fallback (deterministic) agent engine")
        agents = {
            "planner": FallbackAdapter(agent_role=AgentRole.PLANNER, agent_id="planner-1"),
            "coder": FallbackAdapter(agent_role=AgentRole.CODER, agent_id="coder-1"),
            "reviewer": FallbackAdapter(agent_role=AgentRole.REVIEWER, agent_id="reviewer-1"),
            "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER, agent_id="explorer-1"),
        }
    # --- Step 3: Initialize Feishu notifier ---
    from examples.agent_system.integrations.feishu_notifier import FeishuNotifier
    notifier = FeishuNotifier.from_env()
    if notifier.enabled:
        logger.info("Feishu notifications enabled")
    else:
        logger.info("Feishu notifications disabled (set FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_CHAT_ID to enable)")
    # --- Step 4: Build and run Coordinator ---
    from examples.agent_system.coordinator import (
        build_coordinator_graph,
        build_coordinator_initial_state,
    )
    graph = build_coordinator_graph(
        agents=agents,
        git_ops=git_ops,
        work_dir=repo_path,
        notifier=notifier,
    )
    state = build_coordinator_initial_state(enriched_task)
    config = {"configurable": {"thread_id": args.thread_id}}
    logger.info("Starting pipeline...")
    logger.info("-" * 60)
    # --- Run pipeline with Feishu command loop ---
    from examples.agent_system.integrations.feishu_command import FeishuCommandListener
    final_state = _run_pipeline_with_commands(
        graph, state, config, notifier, git_ops, agents, repo_path
    )
    # --- Step 5: Summary ---
    logger.info("-" * 60)
    logger.info("Pipeline finished.")
    final_status = git_ops.get_status()
    logger.info("Final repo status: branch=%s, clean=%s", final_status["branch"], final_status["clean"])
    recent_log = git_ops.get_log(n=5)
    if recent_log:
        logger.info("Recent commits:")
        for entry in recent_log:
            logger.info("  %s %s", entry["hash"][:8], entry["message"])

def _run_pipeline_with_commands(graph, state, config, notifier, git_ops, agents, repo_path):
    """Run pipeline, and if blocked, listen for Feishu commands to resume."""
    from examples.agent_system.integrations.feishu_command import FeishuCommandListener
    from examples.agent_system.coordinator import build_coordinator_graph
    max_rounds = 10  # Prevent infinite loops
    current_state = state
    for round_num in range(max_rounds):
        # Run the pipeline
        last_output = {}
        try:
            for event in graph.stream(current_state, config):
                for node_name, output in event.items():
                    last_output = output
                    phase = output.get("phase", "")
                    completed = output.get("tasks_completed", "")
                    failed = output.get("tasks_failed", "")
                    msgs = output.get("messages", [])
                    msg_text = msgs[0].content if msgs else ""
                    logger.info(
                        "[%s] %s | completed=%s failed=%s",
                        node_name, msg_text, completed, failed,
                    )
        except KeyboardInterrupt:
            logger.info("Pipeline interrupted by user")
            return last_output
        except Exception as exc:
            logger.error("Pipeline error: %s", exc, exc_info=True)
            return last_output
        # Check if pipeline is blocked (has failed tasks, needs human input)
        task_graph = last_output.get("task_graph", {})
        tasks = task_graph.get("tasks", {})
        has_failed = any(t.get("status") == "failed" for t in tasks.values())
        all_done = all(t.get("status") == "done" for t in tasks.values())
        if all_done or not has_failed:
            logger.info("Pipeline completed (round %d)", round_num + 1)
            return last_output
        # Pipeline is blocked - listen for Feishu commands
        logger.info("Pipeline blocked with failed tasks. Waiting for Feishu commands...")
        listener = FeishuCommandListener.from_env(
            task_graph_dict=task_graph,
            notifier=notifier,
        )
        if listener is None:
            logger.info("Feishu not configured, cannot listen for commands. Pipeline ended.")
            return last_output
        result = listener.wait_for_command(timeout=600)
        if result is None:
            logger.info("Command listener timed out. Pipeline ended.")
            return last_output
        if result.action == "stop":
            logger.info("Pipeline stopped by user command.")
            return last_output
        if result.action in ("resume", "skip"):
            # Rebuild state with modified task graph and re-run
            logger.info("Re-running pipeline after command: %s", result.action)
            modified_graph = listener._task_graph
            # Rebuild coordinator graph (reset singletons)
            graph = build_coordinator_graph(
                agents=agents,
                git_ops=git_ops,
                work_dir=repo_path,
                notifier=notifier,
            )
            # Build new state preserving the modified task graph
            from langchain_core.messages import HumanMessage
            current_state = {
                "messages": [HumanMessage(content="Resume pipeline after command")],
                "task_graph": modified_graph,
                "current_task_id": "",
                "phase": "idle",
                "active_agents": [],
                "agent_result": {},
                "tdd_result": {},
                "last_review_feedback": "",
                "tasks_completed": last_output.get("tasks_completed", 0),
                "tasks_failed": 0,
                "total_iterations": last_output.get("total_iterations", 0),
            }
            # Don't go through plan_node again, jump to idle directly
            continue
    logger.info("Max rounds (%d) reached. Pipeline ended.", max_rounds)
    return last_output

if __name__ == "__main__":
    main()

