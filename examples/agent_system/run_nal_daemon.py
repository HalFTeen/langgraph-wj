#!/usr/bin/env python3
"""NAL Daemon - Background service with Feishu human-in-the-loop.
Runs NAL as a long-lived process. Tasks are submitted via CLI or Feishu.
At key checkpoints (after planning), the daemon posts to Feishu and waits
for human confirmation or feedback. Natural language feedback is injected
into Agent prompts.
Usage:
    # Start daemon (foreground, for development)
    FEISHU_APP_ID=xxx FEISHU_APP_SECRET=xxx FEISHU_CHAT_ID=xxx \
    python -m examples.agent_system.run_nal_daemon
    # Start daemon (background)
    nohup python -m examples.agent_system.run_nal_daemon > /tmp/nal-daemon.log 2>&1 &
    # Submit task via CLI (daemon must be running, or use --task directly)
    python -m examples.agent_system.run_nal_daemon --task "Create a website"
    # Submit task via Feishu:
    @bot /new 创建一个个人网站
"""
from __future__ import annotations
import argparse
import logging
import os
import queue
import sys
import time
from dataclasses import dataclass
from pathlib import Path
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nal.daemon")

@dataclass
class PipelineTask:
    """A task to be executed by the pipeline."""
    requirement: str
    repo_path: str
    remote_url: str = ""
    context_file: str = ""
    scan_repo: bool = False

class NALDaemon:
    """NAL background service with Feishu human-in-the-loop collaboration.
    Architecture:
    - Main thread: runs pipeline (LangGraph stream is blocking)
    - Poller thread: continuously polls Feishu for @bot messages
    - Queue bridges the two threads
    Interaction model:
    1. Task submitted (CLI or Feishu /new command)
    2. Planner decomposes → posted to Feishu for review
    3. Human confirms or gives feedback (10min timeout → auto-continue)
    4. Feedback injected into Planner, re-decomposes
    5. On confirmation, Coordinator executes tasks
    6. Each task result notified to Feishu
    7. Done → waits for next task
    """
    def __init__(
        self,
        default_repo: str = "",
        default_remote: str = "",
        engine: str = "claude-code",
    ) -> None:
        self._message_queue: queue.Queue = queue.Queue()
        self._task_queue: list[PipelineTask] = []
        self._poller = None
        self._notifier = None
        self._running = False
        self._default_repo = default_repo
        self._default_remote = default_remote
        self._engine = engine
        self._human_feedback_context: list[str] = []
    def start(self) -> None:
        """Start the daemon: init Feishu, listen for tasks."""
        self._running = True
        # Init Feishu
        from examples.agent_system.integrations.feishu_notifier import FeishuNotifier
        from examples.agent_system.integrations.feishu_command import FeishuMessagePoller
        self._notifier = FeishuNotifier.from_env()
        self._poller = FeishuMessagePoller.from_env(self._message_queue)
        if self._poller:
            self._poller.start()
            logger.info("Feishu message poller started")
            repo_info = f"\n**仓库:** `{self._default_repo}`" if self._default_repo else ""
            self._send(f"🤖 **NAL Daemon 已启动**{repo_info}\n\n"
                        "提交任务：`@bot /new 你的需求描述`\n"
                        "查看状态：`@bot /status`\n"
                        "帮助：`@bot /help`")
        else:
            logger.info("Feishu not configured, CLI-only mode")
        logger.info("NAL Daemon started. Waiting for tasks...")
        self._main_loop()
    def _main_loop(self) -> None:
        """Main loop: check for tasks, execute, repeat."""
        while self._running:
            # Check task queue
            if self._task_queue:
                task = self._task_queue.pop(0)
                self._run_pipeline(task)
                continue
            # Check Feishu messages for /new commands
            try:
                msg = self._message_queue.get(timeout=2)
                self._handle_message_idle(msg)
            except queue.Empty:
                pass
        logger.info("Daemon stopped.")
    def submit_task(self, task: PipelineTask) -> None:
        """Submit a task to the queue (thread-safe)."""
        self._task_queue.append(task)
        logger.info("Task queued: %s", task.requirement[:80])
    # --- Pipeline execution ---
    def _run_pipeline(self, task: PipelineTask) -> None:
        """Run a full pipeline with human-in-the-loop confirmation."""
        repo_path = task.repo_path or self._default_repo
        remote_url = task.remote_url or self._default_remote
        if not repo_path or not os.path.isdir(repo_path):
            self._send(f"❌ 仓库路径无效: `{repo_path}`")
            return
        logger.info("Starting pipeline: %s", task.requirement[:80])
        # --- Init infrastructure ---
        from examples.agent_system.core.git_ops import GitOps
        git_ops = GitOps(repo_path=repo_path, remote_url=remote_url or None)
        agents = self._build_agents(repo_path)
        from examples.agent_system.coordinator import (
            build_coordinator_graph,
            build_coordinator_initial_state,
            run_planner_standalone,
            _set_agent_registry,
            _set_git_ops,
            _set_work_dir,
            _set_notifier,
            _set_daemon_mode,
        )
        _set_agent_registry(agents)
        _set_git_ops(git_ops)
        _set_work_dir(repo_path)
        _set_notifier(self._notifier)
        _set_daemon_mode(True)
        # --- Step 1: Planner with human feedback loop ---
        task_graph = run_planner_standalone(task.requirement)
        self._send_plan_for_review(task_graph)
        feedback = self._wait_for_human_feedback(timeout=600)
        while not self._is_confirmation(feedback):
            if feedback is None:
                break  # Timeout, auto-continue
            self._send("🔄 根据反馈重新拆解...")
            task_graph = run_planner_standalone(task.requirement, feedback=feedback)
            self._send_plan_for_review(task_graph)
            feedback = self._wait_for_human_feedback(timeout=600)
        # --- Step 2: Run coordinator ---
        self._send("✅ 开始执行任务...")
        self._human_feedback_context.clear()
        graph = build_coordinator_graph(
            agents=agents,
            git_ops=git_ops,
            work_dir=repo_path,
            notifier=self._notifier,
            daemon_mode=True,
        )
        state = build_coordinator_initial_state("Execute approved plan")
        state["task_graph"] = task_graph  # Inject pre-approved plan
        config = {"configurable": {"thread_id": f"daemon-{int(time.time())}"}}
        try:
            for event in graph.stream(state, config):
                for node_name, output in event.items():
                    msgs = output.get("messages", [])
                    msg_text = msgs[0].content if msgs else ""
                    completed = output.get("tasks_completed", "")
                    failed = output.get("tasks_failed", "")
                    logger.info("[%s] %s | completed=%s failed=%s",
                                node_name, msg_text, completed, failed)
                    # Check for human feedback during execution
                    self._drain_feedback_during_execution()
        except KeyboardInterrupt:
            logger.info("Pipeline interrupted")
        except Exception as exc:
            logger.error("Pipeline error: %s", exc, exc_info=True)
            self._send(f"❌ Pipeline 执行出错: {exc}")
    # --- Human feedback ---
    def _wait_for_human_feedback(self, timeout: float = 600) -> str | None:
        """Wait for human feedback from Feishu. Returns text or None on timeout."""
        start = time.time()
        while (time.time() - start) < timeout:
            try:
                msg = self._message_queue.get(timeout=5)
            except queue.Empty:
                continue
            from examples.agent_system.integrations.feishu_command import MessageType
            if msg.type == MessageType.COMMAND:
                self._handle_command_during_pipeline(msg)
                continue
            if msg.type == MessageType.CONFIRMATION:
                return msg.text
            if msg.type == MessageType.FEEDBACK:
                return msg.text
        # Timeout
        self._send("⏰ 10分钟未收到反馈，自动按当前方案继续执行。")
        return None
    def _is_confirmation(self, text: str | None) -> bool:
        """Check if text is a confirmation."""
        if text is None:
            return True  # Timeout = auto-confirm
        from examples.agent_system.integrations.feishu_command import MessageType, classify_message
        return classify_message(text) == MessageType.CONFIRMATION
    def _drain_feedback_during_execution(self) -> None:
        """Check queue for feedback messages during execution (non-blocking)."""
        while True:
            try:
                msg = self._message_queue.get_nowait()
            except queue.Empty:
                break
            from examples.agent_system.integrations.feishu_command import MessageType
            if msg.type == MessageType.COMMAND:
                self._handle_command_during_pipeline(msg)
            elif msg.type == MessageType.FEEDBACK:
                self._human_feedback_context.append(msg.text)
                self._send(f"📝 收到反馈，将在后续任务中应用。\n\n> {msg.text[:100]}")
    # --- Message handling ---
    def _handle_message_idle(self, msg) -> None:
        """Handle a message when no pipeline is running."""
        from examples.agent_system.integrations.feishu_command import (
            MessageType, CommandType, classify_message,
        )
        if msg.type == MessageType.COMMAND:
            text = msg.text
            parts = text.split(maxsplit=1)
            cmd = parts[0][1:].lower() if parts[0].startswith("/") else ""
            if cmd == "new":
                self._handle_new_command(text)
            elif cmd == "stop":
                self._send("🛑 Daemon 已停止")
                self._running = False
            elif cmd == "status":
                self._send("💤 **空闲中**\n\n当前没有正在执行的任务。\n发送 `@bot /new 任务描述` 提交新任务。")
            elif cmd == "help":
                repo_info = f"\n**当前仓库:** `{self._default_repo}`" if self._default_repo else ""
                self._send(
                    f"🤖 **NAL Daemon 命令**{repo_info}\n\n"
                    "  `/new <描述>` - 提交新任务\n"
                    "  `/status` - 查看状态\n"
                    "  `/stop` - 停止 Daemon\n"
                    "  `/help` - 帮助\n\n"
                    "**执行中可用：**\n"
                    "  直接 @bot 回复反馈即可影响后续任务"
                )
            else:
                self._send(f"❓ 未知命令: `{text}`\n发送 `/help` 查看帮助")
        else:
            self._send("💤 当前没有正在执行的任务。\n发送 `@bot /new 任务描述` 提交新任务。")
    def _handle_new_command(self, text: str) -> None:
        """Parse /new command and submit task.
        Always uses daemon's configured repo (--repo at startup).
        """
        # Extract requirement: everything after "/new"
        import shlex
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = text.split()
        parts = parts[1:]  # Remove "/new"
        requirement = " ".join(parts)
        if not requirement:
            self._send("❌ 用法: `/new 任务描述`")
            return
        if not self._default_repo:
            self._send("❌ Daemon 启动时未配置仓库。\n"
                        "请用 `--repo /path` 重启 Daemon。")
            return
        task = PipelineTask(requirement=requirement, repo_path=self._default_repo)
        self.submit_task(task)
        self._send(f"✅ 任务已加入队列\n\n**仓库:** `{self._default_repo}`\n**需求:** {requirement[:200]}")
    def _handle_command_during_pipeline(self, msg) -> None:
        """Handle commands received during pipeline execution."""
        text = msg.text
        parts = text.split(maxsplit=1)
        cmd = parts[0][1:].lower() if parts[0].startswith("/") else ""
        if cmd == "status":
            self._send("🔄 **执行中...**\n\n直接 @bot 回复可修改后续任务行为。")
        elif cmd == "stop":
            self._send("🛑 Pipeline 将在当前任务完成后停止")
            self._running = False
        elif cmd == "new":
            self._handle_new_command(text)
        elif cmd == "help":
            self._send(
                "🤖 **执行中命令**\n\n"
                "  `@bot 你的反馈` - 影响后续任务\n"
                "  `@bot /status` - 查看状态\n"
                "  `@bot /stop` - 停止执行\n"
                "  `@bot /new ...` - 排队新任务"
            )
    # --- Helpers ---
    def _send_plan_for_review(self, task_graph: dict) -> None:
        """Post task decomposition to Feishu for review."""
        tasks = task_graph.get("tasks", {})
        lines = [f"📝 **任务拆解完成**（{len(tasks)} 个子任务）\n"]
        for i, (tid, t) in enumerate(tasks.items(), 1):
            title = t.get("title", t.get("description", "")[:40])
            lines.append(f"  {i}. {title}")
        lines.append("\n请 @bot 确认 或提出修改意见。")
        lines.append("（10分钟未回复将自动按当前方案执行）")
        self._send("\n".join(lines))
    def _send(self, text: str) -> None:
        """Send message to Feishu."""
        if self._poller:
            self._poller.send_message(text)
        elif self._notifier and self._notifier.enabled:
            self._notifier._send(text)
    def _build_agents(self, repo_path: str) -> dict:
        """Build agent registry."""
        from examples.agent_system.core.agent_interface import (
            AgentRole,
            ClaudeCodeAdapter,
            ClaudePlannerAdapter,
            ClaudeReviewerAdapter,
            FallbackAdapter,
            build_agents_from_config,
        )
        if self._engine == "mixed":
            from examples.agent_system.config import EngineConfig
            engine_config = EngineConfig.from_env()
            logger.info("Using mixed engine mode")
            agents = build_agents_from_config(engine_config, repo_path)
            for name, agent in agents.items():
                logger.info("  %s: %s", name, type(agent).__name__)
            return agents
        if self._engine == "claude-code":
            return {
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
        return {
            "planner": FallbackAdapter(agent_role=AgentRole.PLANNER, agent_id="planner-1"),
            "coder": FallbackAdapter(agent_role=AgentRole.CODER, agent_id="coder-1"),
            "reviewer": FallbackAdapter(agent_role=AgentRole.REVIEWER, agent_id="reviewer-1"),
            "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER, agent_id="explorer-1"),
        }

def main() -> None:
    parser = argparse.ArgumentParser(description="NAL Daemon")
    parser.add_argument("--repo", default=os.getenv("REPO_PATH", ""),
                        help="Default repository path")
    parser.add_argument("--remote", default=os.getenv("GIT_REMOTE", ""),
                        help="Default git remote URL")
    parser.add_argument("--engine", choices=["claude-code", "fallback", "mixed"],
                        default="claude-code", help="Agent engine")
    parser.add_argument("--task", default="",
                        help="Submit a task immediately (optional)")
    args = parser.parse_args()
    daemon = NALDaemon(
        default_repo=args.repo,
        default_remote=args.remote,
        engine=args.engine,
    )
    if args.task:
        daemon.submit_task(PipelineTask(
            requirement=args.task,
            repo_path=args.repo,
        ))
    try:
        daemon.start()
    except KeyboardInterrupt:
        logger.info("Daemon interrupted by Ctrl+C")

if __name__ == "__main__":
    main()

