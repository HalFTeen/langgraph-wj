"""Feishu Command Listener - Receive and execute commands from Feishu group chat.
Polls the Feishu chat for messages mentioning the bot, parses commands,
and executes them against the running pipeline state.
Supported commands:
    /new <task>     - Submit a new task
    /status         - Show pipeline status (tasks, phases)
    /list           - List all tasks with status
    /resume <id>    - Resume a failed task (reset to READY)
    /skip <id>      - Skip a failed task (mark as DONE)
    /retry <id>     - Retry a specific task
    /stop           - Stop the pipeline/daemon
    /help           - Show available commands
Also supports natural language feedback (non-command messages):
    @bot 把黑色主题改为浅色  → injected as feedback into Agent prompt
    @bot 确认 / ok / 好的    → treated as confirmation
Usage:
    # One-shot (existing): waits for pipeline-modifying command
    listener = FeishuCommandListener.from_env(task_graph_dict, notifier)
    action = listener.wait_for_command()
    # Continuous (daemon): polls in background thread, feeds Queue
    poller = FeishuMessagePoller.from_env(message_queue)
    poller.start()
"""
from __future__ import annotations
import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
logger = logging.getLogger(__name__)

# --- Message classification ---

class MessageType(Enum):
    """Type of incoming Feishu message."""
    COMMAND = "command"
    CONFIRMATION = "confirm"
    FEEDBACK = "feedback"

_CONFIRM_WORDS = {"确认", "ok", "好的", "通过", "继续", "yes", "可以", "没问题", "同意"}

def classify_message(text: str) -> MessageType:
    """Classify a message as command, confirmation, or feedback."""
    stripped = text.strip()
    if stripped.startswith("/"):
        return MessageType.COMMAND
    if stripped.lower() in _CONFIRM_WORDS:
        return MessageType.CONFIRMATION
    return MessageType.FEEDBACK

@dataclass
class FeishuMessage:
    """Parsed message from Feishu chat."""
    type: MessageType
    text: str
    sender: str = ""
    raw: dict = field(default_factory=dict)

class CommandType(Enum):
    STATUS = "status"
    LIST = "list"
    RESUME = "resume"
    SKIP = "skip"
    RETRY = "retry"
    STOP = "stop"
    HELP = "help"
    NEW = "new"
    QUEUE = "queue"
    UNKNOWN = "unknown"

@dataclass
class Command:
    type: CommandType
    args: list[str]
    raw_text: str
    sender: str = ""

@dataclass
class CommandResult:
    success: bool
    message: str
    action: str = ""  # "resume", "skip", "stop", "new", "" (no pipeline action)

class FeishuCommandListener:
    """Listen for commands from Feishu group chat.
    Uses the message list API to poll for new messages.
    Requires the im:message or im:message:readonly scope.
    """
    def __init__(
        self,
        client: Any,
        chat_id: str,
        task_graph_dict: dict,
        notifier: Any = None,
        poll_interval: float = 5.0,
        bot_name: str = "NAL",
    ) -> None:
        self._client = client
        self._chat_id = chat_id
        self._task_graph = task_graph_dict
        self._notifier = notifier
        self._poll_interval = poll_interval
        self._bot_name = bot_name
        self._last_message_id: str = ""
        self._running = False
        self._bot_open_id: str = ""
    @classmethod
    def from_env(
        cls,
        task_graph_dict: dict,
        notifier: Any = None,
    ) -> FeishuCommandListener | None:
        """Create from environment variables."""
        import os
        chat_id = os.getenv("FEISHU_CHAT_ID", "")
        app_id = os.getenv("FEISHU_APP_ID", "")
        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        if not all([chat_id, app_id, app_secret]):
            return None
        try:
            from examples.agent_system.config import FeishuConfig
            from examples.agent_system.gateway.feishu_client import FeishuClient
            config = FeishuConfig(app_id=app_id, app_secret=app_secret)
            client = FeishuClient(config=config)
            return cls(
                client=client,
                chat_id=chat_id,
                task_graph_dict=task_graph_dict,
                notifier=notifier,
            )
        except Exception as exc:
            logger.warning("Failed to create command listener: %s", exc)
            return None
    def update_task_graph(self, task_graph_dict: dict) -> None:
        """Update the task graph reference (called after pipeline state changes)."""
        self._task_graph = task_graph_dict
    def wait_for_command(self, timeout: float = 600) -> CommandResult | None:
        """Block until a pipeline-modifying command is received.
        Returns a CommandResult with action="resume"/"skip"/"stop" when
        a command that changes pipeline state is received.
        Read-only commands (status, list, help) are answered inline.
        Args:
            timeout: Max wait time in seconds (default 10 minutes).
        Returns:
            CommandResult if a modifying command was received, None on timeout.
        """
        self._running = True
        start = time.time()
        # Get initial message position
        self._init_message_cursor()
        logger.info("Listening for commands in Feishu chat (timeout=%ds)...", timeout)
        self._send_response(
            "🤖 **Pipeline 等待指令**\n\n"
            "发送以下命令控制 Pipeline：\n"
            "- `/status` - 查看状态\n"
            "- `/list` - 查看任务列表\n"
            "- `/resume <task_id>` - 恢复失败任务\n"
            "- `/skip <task_id>` - 跳过失败任务\n"
            "- `/stop` - 停止 Pipeline\n"
            "- `/help` - 帮助"
        )
        while self._running and (time.time() - start) < timeout:
            try:
                messages = self._fetch_new_messages()
                for msg in messages:
                    command = self._parse_command(msg)
                    if command is None:
                        continue
                    result = self._execute_command(command)
                    self._send_response(result.message)
                    # Pipeline-modifying commands return immediately
                    if result.action in ("resume", "skip", "stop"):
                        self._running = False
                        return result
            except Exception as exc:
                logger.warning("Command poll error: %s", exc)
            time.sleep(self._poll_interval)
        logger.info("Command listener timed out")
        return None
    # --- Message fetching ---
    def _init_message_cursor(self) -> None:
        """Set the cursor to the latest message so we only see new ones."""
        try:
            messages = self._list_messages(page_size=1)
            if messages:
                self._last_message_id = messages[0].get("message_id", "")
        except Exception as exc:
            logger.warning("Failed to init message cursor: %s", exc)
    def _fetch_new_messages(self) -> list[dict]:
        """Fetch messages newer than the last seen."""
        try:
            messages = self._list_messages(page_size=20)
        except Exception as exc:
            logger.debug("Failed to fetch messages: %s", exc)
            return []
        if not messages:
            return []
        new_messages = []
        for msg in messages:
            msg_id = msg.get("message_id", "")
            if msg_id == self._last_message_id:
                break
            new_messages.append(msg)
        if new_messages:
            self._last_message_id = new_messages[0].get("message_id", "")
        # Reverse so oldest is first
        new_messages.reverse()
        return new_messages
    def _list_messages(self, page_size: int = 20) -> list[dict]:
        """Call Feishu API to list messages in the chat."""
        data = self._client._request(
            "GET",
            f"/im/v1/messages?container_id_type=chat&container_id={self._chat_id}"
            f"&page_size={page_size}&sort_type=ByCreateTimeDesc",
        )
        items = data.get("data", {}).get("items", [])
        return items
    # --- Command parsing ---
    def _parse_command(self, msg: dict) -> Command | None:
        """Parse a Feishu message into a Command, or None if not a command."""
        msg_type = msg.get("msg_type", "")
        if msg_type != "text":
            return None
        # Extract text content
        body = msg.get("body", {})
        content_str = body.get("content", "{}")
        try:
            content = json.loads(content_str)
        except (json.JSONDecodeError, TypeError):
            return None
        text = content.get("text", "").strip()
        if not text:
            return None
        # Remove @mention prefix (Feishu adds @_user_N for mentions)
        # Pattern: @_user_1 /command args
        import re
        text = re.sub(r"@_user_\d+\s*", "", text).strip()
        # Must start with /
        if not text.startswith("/"):
            return None
        parts = text.split()
        cmd_str = parts[0][1:].lower()  # Remove leading /
        args = parts[1:]
        sender = msg.get("sender", {}).get("id", "")
        type_map = {
            "status": CommandType.STATUS,
            "list": CommandType.LIST,
            "resume": CommandType.RESUME,
            "skip": CommandType.SKIP,
            "retry": CommandType.RETRY,
            "stop": CommandType.STOP,
            "help": CommandType.HELP,
            "new": CommandType.NEW,
            "queue": CommandType.QUEUE,
        }
        cmd_type = type_map.get(cmd_str, CommandType.UNKNOWN)
        return Command(type=cmd_type, args=args, raw_text=text, sender=sender)
    # --- Command execution ---
    def _execute_command(self, cmd: Command) -> CommandResult:
        """Execute a parsed command."""
        handlers = {
            CommandType.STATUS: self._cmd_status,
            CommandType.LIST: self._cmd_list,
            CommandType.RESUME: self._cmd_resume,
            CommandType.SKIP: self._cmd_skip,
            CommandType.RETRY: self._cmd_retry,
            CommandType.STOP: self._cmd_stop,
            CommandType.HELP: self._cmd_help,
        }
        handler = handlers.get(cmd.type, self._cmd_unknown)
        return handler(cmd)
    def _cmd_status(self, cmd: Command) -> CommandResult:
        """Show pipeline status."""
        tasks = self._task_graph.get("tasks", {})
        total = len(tasks)
        by_status: dict[str, int] = {}
        for t in tasks.values():
            status = t.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        lines = [f"📊 **Pipeline 状态**\n", f"**总任务:** {total}"]
        for status, count in sorted(by_status.items()):
            emoji = {"done": "✅", "failed": "❌", "pending": "⏳", "ready": "🟢",
                     "assigned": "🔵", "coding": "💻", "blocked": "🚫"}.get(status, "⚪")
            lines.append(f"  {emoji} {status}: {count}")
        return CommandResult(success=True, message="\n".join(lines))
    def _cmd_list(self, cmd: Command) -> CommandResult:
        """List all tasks."""
        tasks = self._task_graph.get("tasks", {})
        if not tasks:
            return CommandResult(success=True, message="📋 没有任务")
        lines = ["📋 **任务列表**\n"]
        for tid, t in tasks.items():
            status = t.get("status", "unknown")
            title = t.get("title", "")[:40]
            emoji = {"done": "✅", "failed": "❌", "pending": "⏳", "ready": "🟢",
                     "blocked": "🚫"}.get(status, "⚪")
            lines.append(f"  {emoji} `{tid}` {title} [{status}]")
        return CommandResult(success=True, message="\n".join(lines))
    def _cmd_resume(self, cmd: Command) -> CommandResult:
        """Resume a failed task."""
        if not cmd.args:
            return CommandResult(
                success=False,
                message="❌ 用法: `/resume <task_id>`\n例: `/resume step-6`",
            )
        task_id = cmd.args[0]
        tasks = self._task_graph.get("tasks", {})
        # Find task by ID (exact or partial match)
        matched = self._find_task(task_id, tasks)
        if not matched:
            return CommandResult(
                success=False,
                message=f"❌ 未找到任务: `{task_id}`",
            )
        tid, task = matched
        status = task.get("status", "")
        if status not in ("failed", "blocked"):
            return CommandResult(
                success=False,
                message=f"⚠️ 任务 `{tid}` 状态为 `{status}`，只能恢复 failed/blocked 任务",
            )
        # Reset task for retry
        task["status"] = "pending"
        task["retry_count"] = 0
        # Also unblock downstream tasks
        self._unblock_downstream(tid, tasks)
        logger.info("Command: resume task %s", tid)
        return CommandResult(
            success=True,
            message=f"✅ 任务 `{tid}` 已恢复，Pipeline 将继续执行",
            action="resume",
        )
    def _cmd_skip(self, cmd: Command) -> CommandResult:
        """Skip a failed task (mark as done)."""
        if not cmd.args:
            return CommandResult(
                success=False,
                message="❌ 用法: `/skip <task_id>`\n例: `/skip step-6`",
            )
        task_id = cmd.args[0]
        tasks = self._task_graph.get("tasks", {})
        matched = self._find_task(task_id, tasks)
        if not matched:
            return CommandResult(
                success=False,
                message=f"❌ 未找到任务: `{task_id}`",
            )
        tid, task = matched
        task["status"] = "done"
        self._unblock_downstream(tid, tasks)
        logger.info("Command: skip task %s", tid)
        return CommandResult(
            success=True,
            message=f"⏭️ 任务 `{tid}` 已跳过，后续任务解锁",
            action="skip",
        )
    def _cmd_retry(self, cmd: Command) -> CommandResult:
        """Retry a task (same as resume)."""
        return self._cmd_resume(cmd)
    def _cmd_stop(self, cmd: Command) -> CommandResult:
        """Stop the pipeline."""
        logger.info("Command: stop pipeline")
        return CommandResult(
            success=True,
            message="🛑 Pipeline 已停止",
            action="stop",
        )
    def _cmd_help(self, cmd: Command) -> CommandResult:
        """Show help."""
        return CommandResult(
            success=True,
            message=(
                "🤖 **NAL Pipeline 命令**\n\n"
                "  `/status` - 查看 Pipeline 状态\n"
                "  `/list` - 查看所有任务\n"
                "  `/resume <id>` - 恢复失败任务\n"
                "  `/skip <id>` - 跳过失败任务\n"
                "  `/retry <id>` - 重试任务\n"
                "  `/stop` - 停止 Pipeline\n\n"
                "**任务 ID 示例:** `step-6`, `6`\n"
                "**@ 机器人发送命令即可**"
            ),
        )
    def _cmd_unknown(self, cmd: Command) -> CommandResult:
        return CommandResult(
            success=False,
            message=f"❓ 未知命令: `{cmd.raw_text}`\n发送 `/help` 查看可用命令",
        )
    # --- Helpers ---
    def _find_task(self, query: str, tasks: dict) -> tuple[str, dict] | None:
        """Find a task by exact or partial ID match."""
        # Exact match
        if query in tasks:
            return query, tasks[query]
        # Partial match (e.g., "6" matches "step-6")
        for tid, task in tasks.items():
            if query in tid:
                return tid, task
        # Numeric match (e.g., "6" matches any task with "6" in ID)
        if query.isdigit():
            for tid, task in tasks.items():
                if query in tid.split("-"):
                    return tid, task
        return None
    def _unblock_downstream(self, done_task_id: str, tasks: dict) -> None:
        """Unblock tasks that depended on the now-done task."""
        for tid, task in tasks.items():
            if task.get("status") == "blocked":
                deps = task.get("depends_on", [])
                if done_task_id in deps:
                    # Check if ALL dependencies are done
                    all_done = all(
                        tasks.get(d, {}).get("status") == "done"
                        for d in deps
                    )
                    if all_done:
                        task["status"] = "pending"
    def _send_response(self, text: str) -> None:
        """Send a response message to the chat."""
        if self._notifier and hasattr(self._notifier, '_send'):
            self._notifier._send(text)
        elif self._client:
            try:
                self._client.send_text_message(
                    self._chat_id, text, chat_type="group"
                )
            except Exception as exc:
                logger.warning("Failed to send response: %s", exc)

# --- Continuous message poller (for daemon mode) ---

class FeishuMessagePoller(threading.Thread):
    """Background thread that continuously polls Feishu for messages.
    Only processes messages that @mention the bot.
    Parsed messages are placed into a thread-safe Queue for the main thread.
    Usage:
        q = queue.Queue()
        poller = FeishuMessagePoller.from_env(q)
        poller.start()
        msg = q.get(timeout=10)  # FeishuMessage
    """
    def __init__(
        self,
        client: Any,
        chat_id: str,
        message_queue: queue.Queue,
        poll_interval: float = 3.0,
    ) -> None:
        super().__init__(daemon=True, name="feishu-poller")
        self._client = client
        self._chat_id = chat_id
        self._queue = message_queue
        self._poll_interval = poll_interval
        self._running = False
        self._last_message_id: str = ""
    @classmethod
    def from_env(cls, message_queue: queue.Queue) -> FeishuMessagePoller | None:
        """Create from environment variables."""
        import os
        chat_id = os.getenv("FEISHU_CHAT_ID", "")
        app_id = os.getenv("FEISHU_APP_ID", "")
        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        if not all([chat_id, app_id, app_secret]):
            return None
        try:
            from examples.agent_system.config import FeishuConfig
            from examples.agent_system.gateway.feishu_client import FeishuClient
            config = FeishuConfig(app_id=app_id, app_secret=app_secret)
            client = FeishuClient(config=config)
            return cls(client=client, chat_id=chat_id, message_queue=message_queue)
        except Exception as exc:
            logger.warning("Failed to create message poller: %s", exc)
            return None
    def run(self) -> None:
        """Main polling loop (runs in background thread)."""
        self._running = True
        self._init_cursor()
        logger.info("Feishu message poller started (interval=%ss)", self._poll_interval)
        while self._running:
            try:
                raw_messages = self._fetch_new_messages()
                for raw in raw_messages:
                    if not self._is_mentioned(raw):
                        continue
                    parsed = self._parse_to_feishu_message(raw)
                    if parsed:
                        self._queue.put(parsed)
                        logger.info("Queued message: type=%s text=%s",
                                    parsed.type.value, parsed.text[:50])
            except Exception as exc:
                logger.debug("Poller error: %s", exc)
            time.sleep(self._poll_interval)
    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
    def send_message(self, text: str) -> None:
        """Send a message to the chat (thread-safe)."""
        try:
            self._client.send_text_message(self._chat_id, text, chat_type="group")
        except Exception as exc:
            logger.warning("Failed to send message: %s", exc)
    # --- Internal ---
    def _init_cursor(self) -> None:
        """Set cursor to latest message."""
        try:
            messages = self._list_messages(page_size=1)
            if messages:
                self._last_message_id = messages[0].get("message_id", "")
        except Exception:
            pass
    def _fetch_new_messages(self) -> list[dict]:
        """Fetch messages newer than cursor."""
        try:
            messages = self._list_messages(page_size=20)
        except Exception:
            return []
        new = []
        for msg in messages:
            if msg.get("message_id") == self._last_message_id:
                break
            new.append(msg)
        if new:
            self._last_message_id = new[0].get("message_id", "")
        new.reverse()
        return new
    def _list_messages(self, page_size: int = 20) -> list[dict]:
        """Call Feishu API to list messages."""
        data = self._client._request(
            "GET",
            f"/im/v1/messages?container_id_type=chat&container_id={self._chat_id}"
            f"&page_size={page_size}&sort_type=ByCreateTimeDesc",
        )
        return data.get("data", {}).get("items", [])
    def _is_mentioned(self, msg: dict) -> bool:
        """Check if the bot is @mentioned in the message."""
        mentions = msg.get("mentions", [])
        if mentions:
            return True
        body = msg.get("body", {})
        content_str = body.get("content", "")
        return "@_user_" in content_str
    def _parse_to_feishu_message(self, raw: dict) -> FeishuMessage | None:
        """Parse a raw Feishu message into a FeishuMessage."""
        if raw.get("msg_type") != "text":
            return None
        body = raw.get("body", {})
        content_str = body.get("content", "{}")
        try:
            content = json.loads(content_str)
        except (json.JSONDecodeError, TypeError):
            return None
        text = content.get("text", "").strip()
        if not text:
            return None
        # Remove @mention prefix
        text = re.sub(r"@_user_\d+\s*", "", text).strip()
        if not text:
            return None
        msg_type = classify_message(text)
        sender = raw.get("sender", {}).get("id", "")
        return FeishuMessage(type=msg_type, text=text, sender=sender, raw=raw)

