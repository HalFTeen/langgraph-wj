"""Feishu bot using long-connection (WebSocket) mode.
Interaction model:
  NAL Pipeline commands:
  - /pipeline <requirement> - start a NAL pipeline (multi-task, TDD, git)
  - /pstatus [thread_id] - check pipeline progress
  - /resume <task_id> - resume a failed pipeline task
  - /pstop [thread_id] - stop a running pipeline
  Legacy commands:
  - /new <description> - create a single coding task (old linear flow)
  - /approve - approve current task and execute
  - /deny [reason] - deny current task
  - /status - check current task progress
  - /tasks - list all tasks
  - /switch <id> - switch to a different task
  - /help - show help
Usage:
    export FEISHU_APP_ID="cli_xxx"
    export FEISHU_APP_SECRET="xxx"
    export GATEWAY_URL="http://localhost:8000"
    python -m examples.agent_system.gateway.run_feishu_bot
"""

from __future__ import annotations
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
import httpx
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
# Bot's own open_id, fetched at startup
_bot_open_id: str = ""
# Message deduplication: track processed message_ids
_processed_msgs: dict[str, float] = {}
_MSG_CACHE_SIZE = 200
# Global repo path for git operations
_repo_path: str = os.getenv("REPO_PATH", os.getcwd())
# Per-user state (persisted to disk)
_user_state: dict[str, dict] = {}
_USER_STATE_FILE = "/tmp/feishu_user_state.json"


def _load_user_state() -> None:
    global _user_state
    try:
        if os.path.exists(_USER_STATE_FILE):
            with open(_USER_STATE_FILE, "r") as f:
                _user_state = json.load(f)
    except Exception:
        pass


def _save_user_state() -> None:
    try:
        with open(_USER_STATE_FILE, "w") as f:
            json.dump(_user_state, f)
    except Exception:
        pass


_load_user_state()


def _fetch_bot_open_id(app_id: str, app_secret: str) -> str:
    """Get the bot's own open_id from Feishu API."""
    with httpx.Client(timeout=10) as http:
        r = http.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        token = r.json().get("tenant_access_token", "")
        r2 = http.get(
            "https://open.feishu.cn/open-apis/bot/v3/info/",
            headers={"Authorization": f"Bearer {token}"},
        )
        return r2.json().get("bot", {}).get("open_id", "")


@dataclass
class ChatContext:
    """Where the message came from — determines where replies go."""

    chat_id: str  # group chat ID or p2p chat ID
    chat_type: str  # "group" or "p2p"
    user_id: str  # sender's open_id
    message_id: str  # for replying to the specific message


# Per-user state
_user_state: dict[str, dict] = {}


def _get_user(user_id: str) -> dict:
    if user_id not in _user_state:
        _user_state[user_id] = {
            "current": None,
            "tasks": [],
            "current_pipeline": None,
            "pipelines": [],
        }
    user = _user_state[user_id]
    user.setdefault("current_pipeline", None)
    user.setdefault("pipelines", [])
    return user


def _new_thread_id() -> str:
    return str(uuid.uuid4())[:8]


def _build_client() -> lark.Client:
    return (
        lark.Client.builder()
        .app_id(os.getenv("FEISHU_APP_ID", ""))
        .app_secret(os.getenv("FEISHU_APP_SECRET", ""))
        .build()
    )


# ---- Feishu messaging ----
def _reply(client: lark.Client, ctx: ChatContext, text: str) -> None:
    """Reply to the original message (works in both group and DM)."""
    body = (
        ReplyMessageRequestBody.builder()
        .msg_type("text")
        .content(json.dumps({"text": text}))
        .build()
    )
    req = (
        ReplyMessageRequest.builder()
        .message_id(ctx.message_id)
        .request_body(body)
        .build()
    )
    resp = client.im.v1.message.reply(req)
    if not resp.success():
        print(f"[reply error] {resp.code}: {resp.msg}")


def _send_message(client: lark.Client, ctx: ChatContext, text: str) -> None:
    """Send a proactive message to the same place the original came from."""
    if ctx.chat_type == "group":
        receive_id = ctx.chat_id
        receive_id_type = "chat_id"
    else:
        receive_id = ctx.user_id
        receive_id_type = "open_id"
    body = (
        CreateMessageRequestBody.builder()
        .receive_id(receive_id)
        .msg_type("text")
        .content(json.dumps({"text": text}))
        .build()
    )
    req = (
        CreateMessageRequest.builder()
        .receive_id_type(receive_id_type)
        .request_body(body)
        .build()
    )
    resp = client.im.v1.message.create(req)
    if not resp.success():
        print(f"[send error] {resp.code}: {resp.msg}")


# ---- Gateway API ----
def _submit_task(task: str, thread_id: str) -> dict | None:
    try:
        with httpx.Client(timeout=10) as http:
            resp = http.post(
                f"{GATEWAY_URL}/task/submit",
                json={"task": task, "thread_id": thread_id},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        print(f"[gateway] submit error: {exc}")
        return None


def _get_task_status(thread_id: str) -> dict | None:
    try:
        with httpx.Client(timeout=5) as http:
            resp = http.get(f"{GATEWAY_URL}/task/{thread_id}")
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        print(f"[gateway] status error: {exc}")
    return None


def _resolve_task(
    thread_id: str, decision: str, reviewer: str, reason: str | None = None
) -> bool:
    try:
        with httpx.Client(timeout=60) as http:
            resp = http.post(
                f"{GATEWAY_URL}/approval/resolve",
                json={
                    "thread_id": thread_id,
                    "decision": decision,
                    "reviewer": reviewer,
                    "reason": reason,
                },
            )
            resp.raise_for_status()
            return True
    except Exception as exc:
        print(f"[gateway] resolve error: {exc}")
        return False


# ---- NAL Pipeline Gateway API ----
def _start_pipeline(
    requirement: str, thread_id: str, repo_path: str = ""
) -> dict | None:
    try:
        with httpx.Client(timeout=10) as http:
            resp = http.post(
                f"{GATEWAY_URL}/api/pipeline/start",
                json={
                    "requirement": requirement,
                    "thread_id": thread_id,
                    "repo_path": repo_path,
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        print(f"[gateway] pipeline start error: {exc}")
        return None


def _get_pipeline_status(thread_id: str = "") -> dict | None:
    try:
        params = {"thread_id": thread_id} if thread_id else {}
        with httpx.Client(timeout=5) as http:
            resp = http.get(f"{GATEWAY_URL}/api/status", params=params)
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        print(f"[gateway] pipeline status error: {exc}")
    return None


def _resume_pipeline_task(task_id: str) -> dict | None:
    try:
        with httpx.Client(timeout=10) as http:
            resp = http.post(f"{GATEWAY_URL}/api/task/{task_id}/resume")
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        print(f"[gateway] resume error: {exc}")
    return None


def _stop_pipeline(thread_id: str = "") -> dict | None:
    try:
        with httpx.Client(timeout=5) as http:
            resp = http.post(
                f"{GATEWAY_URL}/api/pipeline/stop", params={"thread_id": thread_id}
            )
            return resp.json()
    except Exception as exc:
        print(f"[gateway] stop error: {exc}")
    return None


def _get_pipeline_task_detail(task_id: str) -> dict | None:
    try:
        with httpx.Client(timeout=5) as http:
            resp = http.get(f"{GATEWAY_URL}/api/task/{task_id}")
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        print(f"[gateway] task detail error: {exc}")
    return None


# ---- Command handlers ----
def _handle_new_task(client: lark.Client, ctx: ChatContext, task_desc: str) -> None:
    thread_id = _new_thread_id()
    user = _get_user(ctx.user_id)
    result = _submit_task(task_desc, thread_id)
    if result is None:
        _reply(
            client,
            ctx,
            f"Failed to submit task. Is the gateway running at {GATEWAY_URL}?",
        )
        return
    user["current"] = thread_id
    user["tasks"].append(thread_id)
    _reply(
        client,
        ctx,
        f"Task [{thread_id}] submitted.\n"
        f"Agent is working...\n"
        f"I'll notify you when it's ready for review.",
    )

    # Poll in background, notify in the SAME chat when done
    def _poll():
        poll_client = _build_client()
        for _ in range(90):
            time.sleep(2)
            d = _get_task_status(thread_id)
            if d is None:
                continue
            status = d.get("status", "")
            if status == "awaiting_approval":
                code = d.get("code") or "(no code)"
                review = d.get("review_status", "?")
                test = d.get("test_status", "?")
                iters = d.get("iteration_count", 0)
                _send_message(
                    poll_client,
                    ctx,
                    f"Task [{thread_id}] done! ({iters} iterations)\n"
                    f"Review: {review} | Tests: {test}\n\n"
                    f"=== Code ===\n{code}\n=== End ===\n\n"
                    f"/approve to execute, /deny [reason] to reject.",
                )
                return
            if status.startswith("error"):
                _send_message(poll_client, ctx, f"Task [{thread_id}] failed:\n{status}")
                return
        _send_message(
            poll_client,
            ctx,
            f"Task [{thread_id}] still running. Send /status to check.",
        )

    threading.Thread(target=_poll, daemon=True).start()


def _handle_approve(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    user = _get_user(ctx.user_id)
    thread_id = args[0] if args else user.get("current")
    if not thread_id:
        _reply(client, ctx, "No active task. Use /new <description> to create one.")
        return
    _reply(client, ctx, f"Approving [{thread_id}]...")
    ok = _resolve_task(thread_id, "approved", f"feishu:{ctx.user_id[:8]}")
    if not ok:
        _send_message(
            client, ctx, f"Approve failed for [{thread_id}]. Check gateway logs."
        )
        return
    d = _get_task_status(thread_id)
    if d and d.get("code"):
        _send_message(
            client,
            ctx,
            f"Executed! [{thread_id}]\n"
            f"Status: {d.get('status')}\n\n"
            f"=== Final Code ===\n{d.get('code')}\n=== End ===",
        )
    else:
        _send_message(client, ctx, f"Approved and executed [{thread_id}].")


def _handle_deny(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    user = _get_user(ctx.user_id)
    if args and len(args[0]) == 8 and args[0] in user.get("tasks", []):
        thread_id = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else None
    else:
        thread_id = user.get("current")
        reason = " ".join(args) if args else None
    if not thread_id:
        _reply(client, ctx, "No active task.")
        return
    ok = _resolve_task(thread_id, "denied", f"feishu:{ctx.user_id[:8]}", reason)
    _reply(
        client,
        ctx,
        f"Denied [{thread_id}]." if ok else f"Deny failed. Check gateway logs.",
    )


def _handle_status(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    user = _get_user(ctx.user_id)
    thread_id = args[0] if args else user.get("current")
    if not thread_id:
        _reply(client, ctx, "No active task. Use /new <description> to create one.")
        return
    d = _get_task_status(thread_id)
    if d is None:
        _reply(client, ctx, f"Task [{thread_id}] not found.")
        return
    code_preview = ""
    if d.get("code"):
        lines = d["code"].strip().split("\n")
        preview = "\n".join(lines[:5])
        if len(lines) > 5:
            preview += f"\n... ({len(lines)} lines total)"
        code_preview = f"\n\nCode preview:\n{preview}"
    _reply(
        client,
        ctx,
        f"Task [{thread_id}]\n"
        f"Description: {d.get('task', '?')}\n"
        f"Status: {d.get('status')}\n"
        f"Review: {d.get('review_status', '-')}\n"
        f"Tests: {d.get('test_status', '-')}\n"
        f"Iterations: {d.get('iteration_count', 0)}"
        f"{code_preview}",
    )


def _handle_tasks(client: lark.Client, ctx: ChatContext) -> None:
    user = _get_user(ctx.user_id)
    tasks = user.get("tasks", [])
    if not tasks:
        _reply(client, ctx, "No tasks yet. Use /new <description> to create one.")
        return
    lines = []
    for tid in tasks:
        marker = " (current)" if tid == user.get("current") else ""
        d = _get_task_status(tid)
        if d:
            lines.append(
                f"[{tid}]{marker} {d.get('status', '?')} - {d.get('task', '?')[:40]}"
            )
        else:
            lines.append(f"[{tid}]{marker} unknown")
    _reply(client, ctx, "Your tasks:\n" + "\n".join(lines))


def _handle_switch(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    user = _get_user(ctx.user_id)
    if not args:
        _reply(client, ctx, "Usage: /switch <id>\nUse /tasks to see all tasks.")
        return
    tid = args[0]
    if tid not in user.get("tasks", []):
        _reply(client, ctx, f"Task [{tid}] not found. Use /tasks to see your tasks.")
        return
    user["current"] = tid
    d = _get_task_status(tid)
    status = d.get("status", "?") if d else "?"
    _reply(client, ctx, f"Switched to [{tid}] (status: {status})")


def _handle_help(client: lark.Client, ctx: ChatContext) -> None:
    _reply(
        client,
        ctx,
        "Agent System\n\n"
        "NAL Pipeline:\n"
        "  /pipeline <desc> - 启动Pipeline(多任务TDD)\n"
        "  /pstatus [id] - 查看Pipeline进度\n"
        "  /resume <task_id> - 恢复失败任务\n"
        "  /pstop [id] - 停止Pipeline\n"
        "  /ptask <task_id> - 查看任务详情\n\n"
        "Legacy:\n"
        "  /new <desc> - 单任务(旧流程)\n"
        "  /approve - 审批执行\n"
        "  /deny [reason] - 拒绝\n"
        "  /status - 查看任务状态\n"
        "  /tasks - 列出所有任务\n"
        "  /switch <id> - 切换任务\n"
        "  /help - 显示帮助\n\n"
        "示例:\n"
        "  /pipeline 用Python写一个REST API",
    )


# ---- NAL Pipeline command handlers ----
def _handle_pipeline(client: lark.Client, ctx: ChatContext, requirement: str) -> None:
    """Start a NAL pipeline."""
    thread_id = _new_thread_id()
    user = _get_user(ctx.user_id)
    repo_path = user.get("repo_path", _repo_path)
    result = _start_pipeline(requirement, thread_id, repo_path)
    if result is None:
        _reply(client, ctx, f"Pipeline启动失败，Gateway是否运行? {GATEWAY_URL}")
        return
    user["current_pipeline"] = thread_id
    user["pipelines"].append(thread_id)
    engine = os.getenv("NAL_ENGINE", "fallback")
    _reply(
        client,
        ctx,
        f"Pipeline [{thread_id}] 已启动\n"
        f"Engine: {engine}\n"
        f"Phase: {result.get('phase', 'planning')}\n\n"
        f"我会在状态变化时通知你。\n"
        f"发送 /pstatus 查看进度",
    )

    def _poll():
        poll_client = _build_client()
        last_phase = ""
        for _ in range(600):  # 20 minutes max
            time.sleep(2)
            d = _get_pipeline_status(thread_id)
            if d is None:
                continue
            phase = d.get("phase", "")
            completed = d.get("tasks_completed", 0)
            total = d.get("tasks_total", 0)
            failed = d.get("tasks_failed", 0)
            # Notify on phase change
            if phase != last_phase and phase not in ("", "unknown"):
                if phase in ("done", "error", "stopped", "failed"):
                    msg = (
                        f"Pipeline [{thread_id}] 结束\n"
                        f"Phase: {phase}\n"
                        f"Tasks: {completed}/{total} 完成"
                    )
                    if failed > 0:
                        msg += f", {failed} 失败\n发送 /resume <task_id> 恢复"
                    _send_message(poll_client, ctx, msg)
                    return
                last_phase = phase
        _send_message(
            poll_client, ctx, f"Pipeline [{thread_id}] 仍在运行，发送 /pstatus 查看"
        )

    threading.Thread(target=_poll, daemon=True).start()


def _handle_pstatus(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    """Show NAL pipeline status."""
    user = _get_user(ctx.user_id)
    thread_id = args[0] if args else user.get("current_pipeline")
    if not thread_id:
        _reply(client, ctx, "无活跃Pipeline，发送 /pipeline <需求> 启动")
        return
    d = _get_pipeline_status(thread_id)
    if d is None:
        _reply(client, ctx, f"Pipeline [{thread_id}] 未找到")
        return
    _reply(
        client,
        ctx,
        f"Pipeline [{thread_id}]\n"
        f"Phase: {d.get('phase', '?')}\n"
        f"任务总数: {d.get('tasks_total', 0)}\n"
        f"已完成: {d.get('tasks_completed', 0)}\n"
        f"失败: {d.get('tasks_failed', 0)}\n"
        f"就绪: {d.get('tasks_ready', 0)}\n"
        f"阻塞: {d.get('tasks_blocked', 0)}",
    )


def _handle_resume(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    """Resume a failed pipeline task."""
    if not args:
        _reply(client, ctx, "用法: /resume <task_id>\n示例: /resume step-3")
        return
    task_id = args[0]
    d = _resume_pipeline_task(task_id)
    if d is None:
        _reply(client, ctx, f"恢复任务 [{task_id}] 失败，请检查Gateway日志")
        return
    _reply(
        client,
        ctx,
        f"任务 [{task_id}] 已恢复\n"
        f"Pipeline: {d.get('pipeline', '?')}\n"
        f"Pipeline将继续执行",
    )


def _handle_pstop(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    """Stop a running pipeline."""
    user = _get_user(ctx.user_id)
    thread_id = args[0] if args else user.get("current_pipeline", "")
    if not thread_id:
        _reply(client, ctx, "无活跃Pipeline")
        return
    d = _stop_pipeline(thread_id)
    if d is None:
        _reply(client, ctx, "停止Pipeline失败")
        return
    _reply(client, ctx, f"Pipeline [{d.get('thread_id', thread_id)}] 已停止")


def _handle_ptask(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    """Show detail of a specific pipeline task."""
    if not args:
        _reply(client, ctx, "用法: /ptask <task_id>\n示例: /ptask step-1")
        return
    task_id = args[0]
    d = _get_pipeline_task_detail(task_id)
    if d is None:
        _reply(client, ctx, f"任务 [{task_id}] 未找到")
        return
    deps = ", ".join(d.get("depends_on", [])) or "无"
    _reply(
        client,
        ctx,
        f"Task [{d.get('task_id', task_id)}]\n"
        f"Title: {d.get('title', '?')}\n"
        f"Status: {d.get('status', '?')}\n"
        f"Agent: {d.get('assigned_agent') or '未分配'}\n"
        f"TDD: {d.get('tdd_mode', 'full')}\n"
        f"重试: {d.get('retry_count', 0)}次\n"
        f"依赖: {deps}\n\n"
        f"{d.get('description', '')[:200]}",
    )


def _handle_repo(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    global _repo_path
    import subprocess

    if not args:
        user = _get_user(ctx.user_id)
        current = user.get("repo_path", _repo_path)
        _reply(client, ctx, f"当前工作目录: {current}\n用法: /repo <路径或github-url>")
        return
    input_path = " ".join(args)
    if (
        input_path.startswith("http://")
        or input_path.startswith("https://")
        or input_path.endswith(".git")
    ):
        parent_dir = os.path.dirname(_repo_path) or os.getcwd()
        repo_name = input_path.rstrip("/").split("/")[-1].replace(".git", "")
        target_path = os.path.join(parent_dir, repo_name)
        try:
            result = subprocess.run(
                ["git", "clone", input_path, target_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                _repo_path = target_path
                user = _get_user(ctx.user_id)
                user["repo_path"] = target_path
                _reply(client, ctx, f"已克隆仓库到: {target_path}")
            else:
                _reply(client, ctx, f"克隆失败: {result.stderr}")
            return
        except Exception as exc:
            _reply(client, ctx, f"克隆失败: {exc}")
            return
    path = input_path
    if not os.path.isdir(path):
        _reply(client, ctx, f"目录不存在: {path}\n提供GitHub URL我来克隆")
        return
    if not os.path.isdir(os.path.join(path, ".git")):
        try:
            subprocess.run(["git", "init"], cwd=path, check=True)
            subprocess.run(
                ["git", "checkout", "-b", "main"],
                cwd=path,
                check=True,
                capture_output=True,
            )
            _reply(client, ctx, f"已初始化Git仓库: {path}")
        except Exception as exc:
            _reply(client, ctx, f"初始化失败: {exc}")
            return
    _repo_path = path
    user = _get_user(ctx.user_id)
    user["repo_path"] = path
    _reply(client, ctx, f"工作目录已设置: {path}")


def _handle_branch(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    if not args:
        _reply(client, ctx, "用法: /branch <分支名>")
        return
    branch_name = " ".join(args)
    user = _get_user(ctx.user_id)
    repo_path = user.get("repo_path", _repo_path)
    try:
        from examples.agent_system.core.git_ops import GitOps

        git = GitOps(repo_path=repo_path)
        git.create_branch(branch_name)
        git.checkout(branch_name)
        user["current_branch"] = branch_name
        _reply(client, ctx, f"已创建并切换到分支: {branch_name}")
    except Exception as exc:
        _reply(client, ctx, f"分支操作失败: {exc}")


def _handle_commit(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    user = _get_user(ctx.user_id)
    repo_path = user.get("repo_path", _repo_path)
    import subprocess

    try:
        from examples.agent_system.core.git_ops import GitOps

        git = GitOps(repo_path=repo_path)
        branch = git.get_current_branch()
        if not args:
            subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
            result = subprocess.run(
                ["git", "diff", "--cached", "--stat"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            diff_stat = result.stdout.strip() if result.stdout else "无变更"
            result = subprocess.run(
                [
                    "opencode",
                    "run",
                    "--model",
                    "minimax/MiniMax-M2.5",
                    f"根据以下变更生成简洁commit message:\n{diff_stat}",
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            message = (
                result.stdout.strip()
                if result.stdout and result.returncode == 0
                else f"chore: 更新代码"
            )
        else:
            message = " ".join(args)
        commit_hash = git.commit(
            message=message,
            agent_id=f"feishu-{ctx.user_id[:8]}",
            task_id="manual-commit",
        )
        user["current_branch"] = branch
        _reply(
            client, ctx, f"已提交: {commit_hash[:8]}\n分支: {branch}\n信息: {message}"
        )
    except Exception as exc:
        _reply(client, ctx, f"提交失败: {exc}")


def _handle_push(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    user = _get_user(ctx.user_id)
    repo_path = user.get("repo_path", _repo_path)
    try:
        from examples.agent_system.core.git_ops import GitOps

        git = GitOps(repo_path=repo_path)
        branch = git.get_current_branch()
        git.push(branch)
        _reply(client, ctx, f"已推送到远程，分支: {branch}")
    except Exception as exc:
        _reply(client, ctx, f"推送失败: {exc}")


def _handle_pr(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    if not args:
        _reply(client, ctx, "用法: /pr <PR标题>")
        return
    title = " ".join(args)
    user = _get_user(ctx.user_id)
    repo_path = user.get("repo_path", _repo_path)
    import subprocess

    try:
        from examples.agent_system.core.git_ops import GitOps

        git = GitOps(repo_path=repo_path)
        branch = git.get_current_branch()
        default_branch = git.get_default_branch()
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--base",
                default_branch,
                "--head",
                branch,
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            _reply(client, ctx, f"PR已创建: {result.stdout.strip()}")
        else:
            _reply(client, ctx, f"PR创建失败: {result.stderr}")
    except FileNotFoundError:
        _reply(client, ctx, "gh CLI未安装")
    except Exception as exc:
        _reply(client, ctx, f"PR创建失败: {exc}")


def _handle_merge(client: lark.Client, ctx: ChatContext, args: list[str]) -> None:
    if not args:
        _reply(client, ctx, "用法: /merge <PR编号>")
        return
    pr_input = " ".join(args)
    import re

    pr_match = re.search(r"(?:pull/|issues/)(\d+)", pr_input)
    if not pr_match:
        _reply(client, ctx, "请提供PR编号")
        return
    pr_number = pr_match.group(1)
    user = _get_user(ctx.user_id)
    repo_path = user.get("repo_path", _repo_path)
    import subprocess

    try:
        result = subprocess.run(
            ["gh", "pr", "merge", pr_number, "--admin", "--auto"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            _reply(client, ctx, f"PR #{pr_number} 已合并")
        else:
            _reply(client, ctx, f"合并失败: {result.stderr}")
    except FileNotFoundError:
        _reply(client, ctx, "gh CLI未安装")
    except Exception as exc:
        _reply(client, ctx, f"合并失败: {exc}")


# ---- Main event handler ----
def _on_message(data: P2ImMessageReceiveV1) -> None:
    msg = data.event.message
    sender = data.event.sender
    msg_type = msg.message_type
    if msg_type != "text":
        return
    # Deduplication: skip if we've already processed this message
    msg_id = msg.message_id
    if msg_id in _processed_msgs:
        return
    _processed_msgs[msg_id] = time.time()
    if len(_processed_msgs) > _MSG_CACHE_SIZE:
        oldest = sorted(_processed_msgs, key=_processed_msgs.get)[
            : _MSG_CACHE_SIZE // 2
        ]
        for k in oldest:
            _processed_msgs.pop(k, None)
    user_id = sender.sender_id.open_id if sender.sender_id else "unknown"
    chat_id = msg.chat_id or ""
    chat_type = msg.chat_type or "p2p"
    # In group chats, only respond when THIS bot is @mentioned
    if chat_type == "group":
        mentions = getattr(msg, "mentions", None) or []
        bot_mentioned = any(
            getattr(getattr(m, "id", None), "open_id", None) == _bot_open_id
            for m in mentions
        )
        if not bot_mentioned:
            return
    ctx = ChatContext(
        chat_id=chat_id,
        chat_type=chat_type,
        user_id=user_id,
        message_id=msg.message_id,
    )
    try:
        content_obj = json.loads(msg.content)
        text = content_obj.get("text", "").strip()
    except (json.JSONDecodeError, TypeError):
        text = (msg.content or "").strip()
    import sys

    print(f"[bot] msg_id={msg_id} raw={repr(text[:120])}", file=sys.stderr, flush=True)
    if not text:
        return
    # Strip @mention placeholders (Feishu sends them as @_user_1 etc.)
    import re

    text = re.sub(r"@_user_\d+\s*", "", text).strip()
    if not text:
        return
    print(f"[bot] clean={repr(text[:120])}", file=sys.stderr, flush=True)
    client = _build_client()
    # Parse commands
    if text.startswith("/"):
        parts = text.split()
        cmd = parts[0].lower().lstrip("/")
        args = parts[1:]
        print(f"[bot] cmd={repr(cmd)} nargs={len(args)}", file=sys.stderr, flush=True)
        # NAL Pipeline commands
        if cmd == "pipeline" or cmd == "nal":
            if not args:
                _reply(
                    client,
                    ctx,
                    "用法: /pipeline <需求描述>\n示例: /pipeline 用Python写一个REST API",
                )
            else:
                _handle_pipeline(client, ctx, " ".join(args))
        elif cmd == "pstatus":
            _handle_pstatus(client, ctx, args)
        elif cmd == "resume":
            _handle_resume(client, ctx, args)
        elif cmd == "pstop":
            _handle_pstop(client, ctx, args)
        elif cmd == "ptask":
            _handle_ptask(client, ctx, args)
        # Git commands
        elif cmd == "repo":
            _handle_repo(client, ctx, args)
        elif cmd == "branch":
            _handle_branch(client, ctx, args)
        elif cmd == "commit":
            _handle_commit(client, ctx, args)
        elif cmd == "push":
            _handle_push(client, ctx, args)
        elif cmd == "pr":
            _handle_pr(client, ctx, args)
        elif cmd == "merge":
            _handle_merge(client, ctx, args)
        # Legacy commands
        elif cmd == "new":
            if not args:
                _reply(
                    client,
                    ctx,
                    "用法: /new <任务描述>\n示例: /new 用Python写一个冒泡排序函数",
                )
            else:
                _handle_new_task(client, ctx, " ".join(args))
        elif cmd == "approve":
            _handle_approve(client, ctx, args)
        elif cmd == "deny":
            _handle_deny(client, ctx, args)
        elif cmd == "status":
            _handle_status(client, ctx, args)
        elif cmd == "tasks":
            _handle_tasks(client, ctx)
        elif cmd == "switch":
            _handle_switch(client, ctx, args)
        elif cmd == "help":
            _handle_help(client, ctx)
        else:
            _reply(client, ctx, f"未知命令: /{cmd}\n发送 /help 查看帮助")
        return
    _reply(client, ctx, "发送 /pipeline <需求> 启动Pipeline，或 /help 查看帮助")


def main() -> None:
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("Error: FEISHU_APP_ID and FEISHU_APP_SECRET must be set")
        return
    global _bot_open_id
    try:
        _bot_open_id = _fetch_bot_open_id(app_id, app_secret)
        print(f"Bot open_id: {_bot_open_id}")
    except Exception as exc:
        print(
            f"Warning: failed to get bot open_id ({exc}), group @mention filter disabled"
        )
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(lambda d: None)
        .build()
    )
    cli = lark.ws.Client(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    engine = os.getenv("NAL_ENGINE", "fallback")
    print(f"Feishu bot started (long connection)")
    print(f"Gateway: {GATEWAY_URL}")
    print(f"NAL Engine: {engine}")
    print(f"Send /pipeline <requirement> to start a NAL pipeline")
    print(f"Send /help for all commands")
    cli.start()


if __name__ == "__main__":
    main()
