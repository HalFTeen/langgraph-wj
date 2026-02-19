"""Feishu Notifier - Push pipeline events to Feishu.
Sends structured notifications at each Coordinator phase:
- Pipeline started (plan complete)
- Task dispatched to agent
- Task completed (with commit info)
- Task failed (with retry info or escalation)
- Pipeline completed (all done)
- Human intervention needed (FAILED task)
Uses the existing FeishuClient for API calls.
If Feishu is not configured, all methods are silent no-ops.
"""
from __future__ import annotations
import logging
import os
from typing import Any
logger = logging.getLogger(__name__)

class FeishuNotifier:
    """High-level notifier for NAL pipeline events.
    Wraps FeishuClient. If not configured, all calls are silent no-ops.
    Usage:
        notifier = FeishuNotifier.from_env()
        notifier.notify_pipeline_started("thread-1", "Build auth module", 3)
        notifier.notify_task_completed("thread-1", "step-1", "Create models", "abc123")
        notifier.notify_pipeline_done("thread-1", completed=3, failed=0)
    """
    def __init__(self, client: Any = None, chat_id: str = "") -> None:
        """Initialize the notifier.
        Args:
            client: FeishuClient instance. If None, notifications are disabled.
            chat_id: Default chat_id to send notifications to.
        """
        self._client = client
        self._chat_id = chat_id
        self._enabled = client is not None and bool(chat_id)
    @classmethod
    def from_env(cls) -> FeishuNotifier:
        """Create a FeishuNotifier from environment variables.
        Required env vars:
            FEISHU_APP_ID: Feishu app ID
            FEISHU_APP_SECRET: Feishu app secret
            FEISHU_CHAT_ID: Chat ID to send notifications to
        If any are missing, returns a disabled notifier (silent no-ops).
        """
        chat_id = os.getenv("FEISHU_CHAT_ID", "")
        app_id = os.getenv("FEISHU_APP_ID", "")
        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        if not all([chat_id, app_id, app_secret]):
            logger.info("Feishu not configured, notifications disabled")
            return cls(client=None, chat_id="")
        try:
            from examples.agent_system.config import FeishuConfig
            from examples.agent_system.gateway.feishu_client import FeishuClient
            config = FeishuConfig(app_id=app_id, app_secret=app_secret)
            client = FeishuClient(config=config)
            logger.info("Feishu notifier initialized, chat_id=%s", chat_id)
            return cls(client=client, chat_id=chat_id)
        except Exception as exc:
            logger.warning("Failed to initialize Feishu notifier: %s", exc)
            return cls(client=None, chat_id="")
    @property
    def enabled(self) -> bool:
        return self._enabled
    # --- Pipeline events ---
    def notify_pipeline_started(
        self, thread_id: str, requirement: str, task_count: int
    ) -> None:
        """Notify that a pipeline has started with task decomposition."""
        self._send(
            f"🚀 **Pipeline 启动**\n\n"
            f"**ID:** `{thread_id}`\n"
            f"**需求:** {requirement[:200]}\n"
            f"**拆解:** {task_count} 个任务\n"
        )
    def notify_pipeline_done(
        self, thread_id: str, completed: int, failed: int
    ) -> None:
        """Notify that a pipeline has completed."""
        if failed == 0:
            self._send(
                f"✅ **Pipeline 完成**\n\n"
                f"**ID:** `{thread_id}`\n"
                f"**完成:** {completed} 个任务\n"
                f"**状态:** 全部成功"
            )
        else:
            self._send(
                f"⚠️ **Pipeline 结束（有失败）**\n\n"
                f"**ID:** `{thread_id}`\n"
                f"**完成:** {completed} 个任务\n"
                f"**失败:** {failed} 个任务\n"
                f"**操作:** 发送 `/resume <task_id>` 恢复失败任务"
            )
    # --- Task events ---
    def notify_task_dispatched(
        self, thread_id: str, task_id: str, task_title: str, agent_id: str
    ) -> None:
        """Notify that a task has been assigned to an agent."""
        self._send(
            f"📋 **任务分发**\n\n"
            f"**Pipeline:** `{thread_id}`\n"
            f"**任务:** [{task_id}] {task_title}\n"
            f"**Agent:** {agent_id}"
        )
    def notify_task_completed(
        self,
        thread_id: str,
        task_id: str,
        task_title: str,
        commit_hash: str = "",
    ) -> None:
        """Notify that a task has been completed."""
        commit_info = f"\n**Commit:** `{commit_hash[:8]}`" if commit_hash else ""
        self._send(
            f"✅ **任务完成**\n\n"
            f"**Pipeline:** `{thread_id}`\n"
            f"**任务:** [{task_id}] {task_title}{commit_info}"
        )
    def notify_task_retry(
        self,
        thread_id: str,
        task_id: str,
        task_title: str,
        retry_count: int,
        max_retries: int,
        reason: str = "",
    ) -> None:
        """Notify that a task is being retried."""
        reason_info = f"\n**原因:** {reason[:100]}" if reason else ""
        self._send(
            f"🔄 **任务重试**\n\n"
            f"**Pipeline:** `{thread_id}`\n"
            f"**任务:** [{task_id}] {task_title}\n"
            f"**重试:** {retry_count}/{max_retries}{reason_info}"
        )
    def notify_task_failed(
        self,
        thread_id: str,
        task_id: str,
        task_title: str,
        max_retries: int,
    ) -> None:
        """Notify that a task has failed and needs human intervention."""
        self._send(
            f"❌ **任务失败 - 需要人工介入**\n\n"
            f"**Pipeline:** `{thread_id}`\n"
            f"**任务:** [{task_id}] {task_title}\n"
            f"**重试:** 已达上限 ({max_retries}次)\n\n"
            f"请排查问题后恢复任务：\n"
            f"发送 `/resume {task_id}` 恢复执行"
        )
    # --- Merge events ---
    def notify_merge_success(
        self, thread_id: str, task_id: str, branch: str, commit_hash: str = ""
    ) -> None:
        """Notify successful merge."""
        commit_info = f"\n**Commit:** `{commit_hash[:8]}`" if commit_hash else ""
        self._send(
            f"🔀 **分支合并**\n\n"
            f"**Pipeline:** `{thread_id}`\n"
            f"**分支:** {branch} → main{commit_info}"
        )
    def notify_merge_conflict(
        self, thread_id: str, task_id: str, branch: str, conflicts: list[str]
    ) -> None:
        """Notify merge conflict."""
        conflict_files = "\n".join(f"  - {f}" for f in conflicts[:5])
        self._send(
            f"⚠️ **合并冲突**\n\n"
            f"**Pipeline:** `{thread_id}`\n"
            f"**分支:** {branch} → main\n"
            f"**冲突文件:**\n{conflict_files}"
        )
    # --- Internal ---
    def _send(self, text: str) -> None:
        """Send a text message to the configured chat."""
        if not self._enabled:
            return
        try:
            self._client.send_text_message(
                self._chat_id, text, chat_type="group"
            )
        except Exception as exc:
            logger.warning("Feishu notification failed: %s", exc)
    def _send_card(self, title: str, description: str) -> None:
        """Send an interactive card to the configured chat."""
        if not self._enabled:
            return
        try:
            self._client.send_approval_card(
                receive_id=self._chat_id,
                title=title,
                description=description,
                approve_url="",
                deny_url="",
            )
        except Exception as exc:
            logger.warning("Feishu card notification failed: %s", exc)

