# NAL (Nested Agent Loop) 使用指南
## 目录
1. [概述](#1-概述)
2. [架构总览](#2-架构总览)
3. [快速开始](#3-快速开始)
4. [Core Layer 详细说明](#4-core-layer-详细说明)
   - 4.1 [TaskGraph - 任务依赖图](#41-taskgraph---任务依赖图)
   - 4.2 [GitOps - Git操作与协调](#42-gitops---git操作与协调)
   - 4.3 [TDD Protocol - 测试驱动开发协议](#43-tdd-protocol---测试驱动开发协议)
   - 4.4 [Agent Interface - Agent引擎抽象](#44-agent-interface---agent引擎抽象)
   - 4.5 [Shared Context - 共享上下文板](#45-shared-context---共享上下文板)
5. [Coordinator 系统调度器](#5-coordinator-系统调度器)
6. [Integration Layer](#6-integration-layer)
   - 6.1 [Prometheus 指标](#61-prometheus-指标)
   - 6.2 [Gateway API](#62-gateway-api)
7. [测试](#7-测试)
8. [配置参考](#8-配置参考)
---
## 1. 概述
NAL 是一个**多Agent持续协同开发框架**。多个AI Agent围绕git仓库，按TDD baby-step流程自动拆解任务、编写测试、实现代码、验证提交。
**核心理念**：
| 理念 | 说明 |
|------|------|
| **Baby-step** | 每次变更足够小、可验证、可回滚 |
| **Git-as-Protocol** | Git仓库是唯一事实来源，分支即锁，commit即同步点 |
| **TDD-Enforced** | 功能代码强制TDD（红→绿→提交），非功能变更走轻量验证 |
| **Observable** | 每一步操作都产生Prometheus指标，全程可观测 |
**完整流程**：
```
需求输入 → Coordinator接收
  → PlannerAgent 拆解为 TaskGraph (DAG)
  → ReviewerAgent 审查 TaskGraph 粒度
  → Coordinator 并行分发无依赖任务给多个 CoderAgent
  → 每个 CoderAgent 执行 TDD Protocol (写测试→实现→验证→提交)
  → ReviewerAgent 审查代码质量
  → 逐步 merge 到父分支（完成即合并，解锁下游）
  → 所有任务 DONE → 创建 PR → 合并到 main
```
---
## 2. 架构总览
```
┌─────────────────────────────────────────────────────┐
│  Layer 3: Integration                                │
│  integrations/metrics.py  ← Prometheus指标           │
│  gateway/app.py           ← HTTP API                 │
├─────────────────────────────────────────────────────┤
│  Layer 2: Coordinator（系统调度器）                    │
│  coordinator.py           ← LangGraph StateGraph     │
│  主循环: plan→dispatch→execute→evaluate→merge        │
├─────────────────────────────────────────────────────┤
│  Layer 1: Core（纯Python，零框架依赖）                │
│  core/task_graph.py       ← DAG任务依赖管理          │
│  core/git_ops.py          ← Git分支/锁/worktree      │
│  core/tdd_protocol.py     ← TDD红→绿→验证→提交       │
│  core/agent_interface.py  ← Agent引擎抽象             │
│  core/shared_context.py   ← .nal/context/ 共享板      │
├─────────────────────────────────────────────────────┤
│  执行层: Agent Workers                               │
│  LLMAgentAdapter          ← 现有AgentRole(LLM API)   │
│  ClaudeCodeAdapter        ← Claude Code CLI子进程     │
│  FallbackAdapter          ← 确定性回退(测试用)        │
└─────────────────────────────────────────────────────┘
```
**术语**：
| 术语 | 本质 | 职责 |
|------|------|------|
| **Coordinator** | 系统级调度器 | 主循环：选任务→分配Agent→检查结果→合并代码 |
| **PlannerRole** | Agent角色 | 把需求拆解为TaskGraph |
| **CoderRole** | Agent角色 | 执行TDD Protocol编写代码 |
| **ReviewerRole** | Agent角色 | 审查TaskGraph粒度 + 代码质量 |
| **ExplorerRole** | Agent角色 | 搜索代码库上下文 |
Coordinator是调度系统（类比Linux的`schedule()`），Agent是被调度的进程。
---
## 3. 快速开始
### 3.1 安装依赖
```bash
pip install langgraph langchain-core
# 可选: Prometheus指标
pip install prometheus_client
# 可选: HTTP网关
pip install fastapi uvicorn
```
### 3.2 最简示例：使用Fallback模式（无需LLM）
```python
from examples.agent_system.coordinator import (
    build_coordinator_graph,
    build_coordinator_initial_state,
)
from examples.agent_system.core.agent_interface import AgentRole, FallbackAdapter
# 1. 创建Agent（使用确定性回退，不需要API Key）
agents = {
    "planner": FallbackAdapter(agent_role=AgentRole.PLANNER),
    "coder": FallbackAdapter(agent_role=AgentRole.CODER),
    "reviewer": FallbackAdapter(agent_role=AgentRole.REVIEWER),
    "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER),
}
# 2. 构建Coordinator图
graph = build_coordinator_graph(agents=agents)
# 3. 创建初始状态
state = build_coordinator_initial_state("Implement add(a, b) function")
# 4. 运行
config = {"configurable": {"thread_id": "demo-1"}}
for event in graph.stream(state, config):
    for node_name, output in event.items():
        print(f"[{node_name}] phase={output.get('phase', '?')}")
```
输出：
```
[plan] phase=dispatch
[dispatch] phase=execute
[execute] phase=evaluate
[evaluate] phase=merge
[merge] phase=done
```
### 3.3 使用LLM API模式
```python
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.llm import get_llm
from examples.agent_system.core.agent_interface import (
    AgentRole, FallbackAdapter, LLMAgentAdapter,
)
llm = get_llm(provider="openai", model="gpt-4o-mini")
agents = {
    "planner": FallbackAdapter(agent_role=AgentRole.PLANNER),
    "coder": LLMAgentAdapter(CoderRole(llm=llm), agent_role=AgentRole.CODER),
    "reviewer": LLMAgentAdapter(ReviewerRole(llm=llm), agent_role=AgentRole.REVIEWER),
    "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER),
}
graph = build_coordinator_graph(agents=agents)
# ... 同上
```
### 3.4 使用Claude Code CLI模式
```python
from examples.agent_system.core.agent_interface import (
    AgentRole, ClaudeCodeAdapter, FallbackAdapter,
)
agents = {
    "planner": FallbackAdapter(agent_role=AgentRole.PLANNER),
    "coder": ClaudeCodeAdapter(
        worktree_path="/path/to/worktree",
        claude_md_content="# Coder\nYou write clean Python code following TDD.",
        agent_role=AgentRole.CODER,
    ),
    "reviewer": ClaudeCodeAdapter(
        worktree_path="/path/to/worktree",
        claude_md_content="# Reviewer\nReview code for correctness and style.",
        agent_role=AgentRole.REVIEWER,
    ),
    "explorer": FallbackAdapter(agent_role=AgentRole.EXPLORER),
}
graph = build_coordinator_graph(agents=agents)
# ... 同上
```
### 3.5 通过HTTP API启动
```bash
# 启动Gateway
uvicorn examples.agent_system.gateway.app:app --reload --port 8000
# 启动Pipeline
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"requirement": "Implement add(a, b) function"}'
# 查询状态
curl http://localhost:8000/api/status?thread_id=xxx
# 查看Prometheus指标
curl http://localhost:8000/metrics
```
---
## 4. Core Layer 详细说明
### 4.1 TaskGraph - 任务依赖图
**文件**: `core/task_graph.py`
TaskGraph 管理原子baby-step任务的DAG依赖关系。
#### 4.1.1 TaskStatus 枚举
9种状态，严格限制合法转换：
```
PENDING → READY → ASSIGNED → TESTING → CODING → VERIFYING → DONE
                     ↓                              ↓
                  (timeout)                       (fail)
                     ↓                              ↓
                   READY ←──────────────── retry < max?
                                                ↓ (exceeded)
                                             FAILED → 人工介入
BLOCKED: 上游FAILED时，下游自动标记为BLOCKED
```
```python
from examples.agent_system.core.task_graph import TaskStatus
TaskStatus.PENDING     # 等待依赖
TaskStatus.READY       # 依赖已满足，可分配
TaskStatus.ASSIGNED    # 已分配给Agent
TaskStatus.TESTING     # Agent正在写测试
TaskStatus.CODING      # Agent正在写实现
TaskStatus.VERIFYING   # 正在跑测试验证
TaskStatus.DONE        # 完成（终态）
TaskStatus.FAILED      # 超过重试上限（需人工）
TaskStatus.BLOCKED     # 被上游FAILED阻塞
```
**合法转换表**：
| 当前状态 | 允许转换到 |
|---------|-----------|
| PENDING | READY, BLOCKED |
| READY | ASSIGNED, BLOCKED |
| ASSIGNED | TESTING, CODING, READY(超时回队列) |
| TESTING | CODING, READY(重试), FAILED |
| CODING | VERIFYING, READY(重试), FAILED |
| VERIFYING | DONE, READY(重试), FAILED |
| DONE | (终态) |
| FAILED | READY(人工恢复) |
| BLOCKED | PENDING, READY(上游恢复) |
非法转换会抛出 `TaskGraphError`。
#### 4.1.2 Task 数据类
```python
from examples.agent_system.core.task_graph import Task
task = Task(
    id="step-001",              # 唯一ID
    title="Implement add()",     # 一句话描述
    description="Add function that sums two numbers",  # 详细描述
    status=TaskStatus.PENDING,   # 初始状态
    parent_id="issue-42",        # 父任务ID（构成任务树）
    depends_on=["step-000"],     # 前置依赖任务ID列表
    assigned_agent=None,         # 分配的Agent ID
    branch="task/issue-42/step-001",  # 对应git分支
    tdd_mode="full",             # "full"(完整TDD) | "lite"(轻量验证)
    test_file="test_add.py",     # 测试文件路径
    max_retries=3,               # 最大重试次数
    retry_count=0,               # 当前重试次数
    diff_line_limit=100,         # 单步diff行数上限
    github_issue_id=42,          # 关联的GitHub Issue
)
# 序列化
d = task.to_dict()
task2 = Task.from_dict(d)
```
#### 4.1.3 TaskGraph 类
```python
from examples.agent_system.core.task_graph import Task, TaskGraph, TaskStatus, make_task_id
graph = TaskGraph()
# --- 添加任务 ---
t1 = Task(id="t1", title="Create models", description="Define data models")
t2 = Task(id="t2", title="Add API", description="REST endpoints", depends_on=["t1"])
t3 = Task(id="t3", title="Write docs", description="API docs", depends_on=["t1"])
t4 = Task(id="t4", title="Integration test", description="E2E test", depends_on=["t2", "t3"])
graph.add_task(t1)
graph.add_task(t2)
graph.add_task(t3)
graph.add_task(t4)
# --- 动态添加依赖（会自动检测环） ---
graph.add_dependency("t3", "t2")  # t3现在也依赖t2
# graph.add_dependency("t1", "t4")  # 会抛出TaskGraphError: cycle!
# --- 查询 ---
graph.get_task("t1")                          # 获取单个任务
graph.get_subtasks("issue-42")                # 获取子任务
graph.get_all_tasks()                         # 所有任务
graph.get_tasks_by_status(TaskStatus.PENDING)  # 按状态过滤
graph.validate_dag()                          # 检测是否有环
# --- 获取就绪任务（自动PENDING→READY提升） ---
ready = graph.get_ready_tasks()
# 返回所有依赖已DONE的任务，按关键路径优先排序（下游依赖越多越优先）
# --- 状态更新（含级联效果） ---
graph.update_status("t1", TaskStatus.READY)
graph.update_status("t1", TaskStatus.ASSIGNED)
graph.update_status("t1", TaskStatus.TESTING)
graph.update_status("t1", TaskStatus.CODING)
graph.update_status("t1", TaskStatus.VERIFYING)
graph.update_status("t1", TaskStatus.DONE)
# → t2和t3自动提升为READY（如果所有依赖都DONE）
graph.update_status("t2", TaskStatus.READY)
graph.update_status("t2", TaskStatus.ASSIGNED)
graph.update_status("t2", TaskStatus.TESTING)
graph.update_status("t2", TaskStatus.FAILED)
# → t4自动标记为BLOCKED
graph.update_status("t2", TaskStatus.READY)  # 人工恢复
# → t4自动从BLOCKED恢复为PENDING
# --- 完成检查 ---
graph.is_complete()  # 所有任务DONE?
graph.has_failed()   # 有FAILED任务?
# --- 序列化/反序列化 ---
d = graph.to_dict()
graph2 = TaskGraph.from_dict(d)
# --- 生成唯一任务ID ---
task_id = make_task_id()  # 例如 "a1b2c3d4"（8位hex）
```
**级联效果详解**：
- **DONE级联**：任务完成时，检查所有依赖它的下游任务。如果下游任务的所有依赖都已DONE，则自动提升为READY。
- **FAILED级联**：任务失败时，所有直接和间接依赖它的下游任务标记为BLOCKED。
- **恢复级联**：FAILED任务被人工恢复为READY时，检查下游BLOCKED任务，如果上游不再有FAILED/BLOCKED，则恢复为PENDING。
---
### 4.2 GitOps - Git操作与协调
**文件**: `core/git_ops.py`
管理分支、worktree、锁（git tag实现）、提交、合并。
#### 4.2.1 初始化
```python
from examples.agent_system.core.git_ops import GitOps
ops = GitOps(
    repo_path="/path/to/repo",        # 本地git仓库路径
    remote_url="http://git.server/repo.git",  # 可选，远程地址
)
```
#### 4.2.2 分支操作
```python
# 创建分支
ops.create_branch("task/issue-42", base="main")
# 查看当前分支
branch = ops.get_current_branch()  # "main"
# 列出所有分支
branches = ops.list_branches()  # ["main", "task/issue-42"]
# 切换分支
ops.checkout("task/issue-42")
# 删除分支
ops.checkout("main")
ops.delete_branch("task/issue-42")
```
**分支命名规范**（辅助函数）：
```python
from examples.agent_system.core.git_ops import (
    task_branch_name,
    step_branch_name,
    self_improve_branch_name,
)
task_branch_name(42)          # "task/issue-42"
step_branch_name(42, 1)       # "task/issue-42/step-001"
step_branch_name(42, 12)      # "task/issue-42/step-012"
self_improve_branch_name(7)   # "self-improve/proposal-007"
```
#### 4.2.3 Worktree管理
每个Agent拥有独立的工作目录（git worktree），互不干扰：
```python
# 创建worktree
ops.create_branch("agent-1-branch", "main")
ops.checkout("main")
wt_path = ops.create_worktree("agent-1-branch", "/tmp/worktree-agent-1")
# 列出所有worktree
worktrees = ops.list_worktrees()
# [{"path": "/path/to/repo", "branch": "refs/heads/main", "head": "abc123"},
#  {"path": "/tmp/worktree-agent-1", "branch": "refs/heads/agent-1-branch", ...}]
# 清理worktree
ops.remove_worktree("/tmp/worktree-agent-1")
```
#### 4.2.4 分支锁机制
锁通过git tag实现，格式 `lock/<branch>/<agent_id>/<expires_at>`。零额外基础设施。
```python
# 获取锁
success = ops.acquire_lock("task/issue-42", "coder-1", ttl=600)  # 10分钟TTL
# True: 成功获取
# False: 已被其他Agent锁定
# 检查锁状态
lock = ops.is_locked("task/issue-42")
if lock:
    print(f"Locked by {lock.agent_id}, expires: {lock.is_expired}")
# 释放锁
ops.release_lock("task/issue-42", "coder-1")
# 同一Agent重复获取 → 幂等，返回True
ops.acquire_lock("main", "coder-1")
ops.acquire_lock("main", "coder-1")  # True（幂等）
# 不同Agent争用 → 被阻塞
ops.acquire_lock("main", "coder-1")
ops.acquire_lock("main", "coder-2")  # False（被coder-1锁定）
# 过期锁自动释放
ops.acquire_lock("main", "coder-1", ttl=0)
# ... 时间过去 ...
ops.acquire_lock("main", "coder-2")  # True（coder-1的锁已过期）
# 清理所有过期锁
cleaned = ops.cleanup_expired_locks()  # 返回清理的分支名列表
```
**BranchLock 数据类**：
```python
from examples.agent_system.core.git_ops import BranchLock
lock = BranchLock(
    branch="task/issue-42",
    agent_id="coder-1",
    acquired_at=1700000000.0,   # 获取时间（Unix时间戳）
    expires_at=1700000600.0,    # 过期时间
)
lock.is_expired          # bool: 是否已过期
lock.to_tag_name()       # "lock/task/issue-42/coder-1/1700000600"
BranchLock.from_tag_name("lock/task/issue-42/coder-1/1700000600")  # 反序列化
```
#### 4.2.5 提交操作
```python
# 提交（自动 git add -A + commit，附带NAL元数据）
commit_hash = ops.commit(
    message="feat(core): implement add function",
    agent_id="coder-1",
    task_id="step-001",
    step_info="1/3",
)
# commit message 自动追加:
#   Agent: coder-1
#   Task: step-001
#   Step: 1/3
# 精确暂存
ops.stage_files(["src/add.py", "tests/test_add.py"])
# 查看diff统计
stats = ops.get_diff_stats()
# {"files_changed": 2, "insertions": 15, "deletions": 3}
lines = ops.get_diff_line_count()  # 18（insertions + deletions）
```
#### 4.2.6 远程操作
```python
# 设置远程（add或update）
ops.setup_remote("http://git.server/repo.git", name="origin")
# 推送
ops.push("task/issue-42")
# 拉取
ops.pull("main")
```
#### 4.2.7 合并操作
```python
# 合并（source → target）
result = ops.merge("task/issue-42/step-001", "task/issue-42")
if result.success:
    print(f"Merged: {result.commit_hash}")
else:
    print(f"Conflicts: {result.conflicts}")
    print(f"Error: {result.error}")
# 冲突检测（dry run）
has = ops.has_conflicts("branch-a", "main")
```
**MergeResult 数据类**：
```python
@dataclass
class MergeResult:
    success: bool
    commit_hash: str | None       # 合并commit的hash
    conflicts: list[str] | None   # 冲突文件列表
    error: str | None             # 错误信息
```
#### 4.2.8 辅助功能
```python
# 仓库状态
status = ops.get_status()
# {"branch": "main", "changed_files": 0, "clean": True}
# 提交日志
log = ops.get_log(n=5)
# [{"hash": "abc123", "author": "Test", "message": "feat: add"}, ...]
```
---
### 4.3 TDD Protocol - 测试驱动开发协议
**文件**: `core/tdd_protocol.py`
强制每个baby-step遵循质量验证流程。
#### 4.3.1 两种模式
```python
from examples.agent_system.core.tdd_protocol import TDDMode
TDDMode.FULL  # 功能代码：红→绿→验证→提交
TDDMode.LITE  # 非功能变更（配置/文档/UI）：改→验证→提交
```
**FULL模式流程**：
```
Step 1: WRITE_TEST（红灯） — 测试必须在当前代码上FAIL
Step 2: WRITE_CODE（绿灯） — 写最小实现使测试通过，diff不超限，不许改测试文件
Step 3: VERIFY — 运行当前测试(PASS) + 全量测试(不回归) + linter
Step 4: COMMIT — git commit + push + 更新Task状态
```
**LITE模式流程**：
```
Step 1: MODIFY — 执行变更，diff不超限
Step 2: VERIFY — 全量测试(不回归) + linter + 构建检查
Step 3: COMMIT — git commit + push + 更新Task状态
```
#### 4.3.2 TestRunner
复用现有的 `SandboxExecutor`（Local/Docker）运行测试：
```python
from examples.agent_system.sandbox import LocalExecutor
from examples.agent_system.core.tdd_protocol import TestRunner
executor = LocalExecutor(timeout_seconds=30)
runner = TestRunner(executor)
# 运行单个测试
result = runner.run_tests(
    test_code="def test_add(): assert add(1,1) == 2",
    source_code="def add(a,b): return a+b",
)
print(result.passed)   # True
print(result.output)   # stdout + stderr
# 运行全量测试
result = runner.run_all_tests(test_dir="tests")
# 运行linter
lint = runner.run_linter(files=["src/add.py"])
print(lint.passed)   # True/False
print(lint.issues)   # 问题列表
# 自动检测测试框架
framework = runner.detect_framework("/path/to/repo")  # "pytest" | "jest" | "go_test"
```
#### 4.3.3 TDDProtocol 类
```python
from examples.agent_system.core.tdd_protocol import TDDProtocol
protocol = TDDProtocol(
    git_ops=ops,           # 可选，传入GitOps实例
    test_runner=runner,     # 可选，传入TestRunner实例
)
# --- 逐步调用 ---
# Step 1: 验证红灯（测试必须在旧代码上FAIL）
result = protocol.validate_red(
    test_code="def test_add(): assert add(1,1) == 2",
    source_code="",  # 旧代码，没有add函数
)
# result.success == True（测试确实失败了 → 红灯确认）
# Step 2: 验证绿灯（测试在新代码上PASS）
result = protocol.validate_green(
    test_code="def test_add(): assert add(1,1) == 2",
    source_code="def add(a,b): return a+b",
)
# result.success == True（测试通过了 → 绿灯确认）
# Step 3: Diff限制检查
result = protocol.validate_diff_limit(diff_lines=42, limit=100)
# result.success == True（42 < 100）
# Step 4: 全量回归测试
result = protocol.validate_no_regression()
# Step 5: 提交
result = protocol.do_commit("feat: add function", "coder-1", "step-001", "1/3")
# result.commit_hash == "abc123..."
# --- 一键执行完整TDD ---
result = protocol.execute_full(
    task_id="step-001",
    agent_id="coder-1",
    test_code="def test_add(): assert add(1,1) == 2",
    source_code_before="",                    # 实现前的代码
    source_code_after="def add(a,b): return a+b",  # 实现后的代码
    diff_lines=15,
    diff_limit=100,
    commit_message="feat(core): implement add",
)
# 自动执行: 红灯→绿灯→diff检查→回归测试→提交
# result.success: 第一个失败步骤返回False，全部通过返回True
# --- 一键执行轻量验证 ---
result = protocol.execute_lite(
    task_id="step-002",
    agent_id="coder-1",
    diff_lines=8,
    diff_limit=100,
    commit_message="chore: update config",
)
# --- 重试判断 ---
TDDProtocol.should_retry(retry_count=1, max_retries=3)  # True
TDDProtocol.should_retry(retry_count=3, max_retries=3)  # False
# --- 模式选择 ---
mode = TDDProtocol.select_mode("full")   # TDDMode.FULL
mode = TDDProtocol.select_mode("lite")   # TDDMode.LITE
```
**TDDResult 数据类**：
```python
@dataclass
class TDDResult:
    step: TDDStep          # 当前步骤
    success: bool          # 是否成功
    error_message: str     # 错误信息
    test_output: str       # 测试输出
    diff_lines: int        # diff行数
    commit_hash: str       # commit哈希
    @property
    def failed(self) -> bool  # success的反义
```
---
### 4.4 Agent Interface - Agent引擎抽象
**文件**: `core/agent_interface.py`
抽象层让Coordinator不关心Agent底层是LLM API还是Claude Code CLI。
#### 4.4.1 角色和引擎枚举
```python
from examples.agent_system.core.agent_interface import AgentRole, AgentEngine
# 角色
AgentRole.PLANNER    # 需求拆解
AgentRole.CODER      # 编写代码
AgentRole.REVIEWER   # 代码审查
AgentRole.EXPLORER   # 搜索上下文
# 引擎
AgentEngine.LLM          # LLM API (LangChain)
AgentEngine.CLAUDE_CODE   # Claude Code CLI
AgentEngine.OPENCODE      # OpenCode CLI
```
#### 4.4.2 AgentInterface 抽象基类
所有Agent适配器必须实现：
```python
class AgentInterface(ABC):
    def execute_task(self, task_description: str, context: dict | None = None) -> AgentResult
    def get_status(self) -> str       # "idle" | "busy" | "error"
    @property
    def agent_id(self) -> str         # 唯一标识
    @property
    def role(self) -> AgentRole       # 角色
```
#### 4.4.3 三种适配器
**FallbackAdapter（确定性回退，测试用）**：
```python
from examples.agent_system.core.agent_interface import FallbackAdapter, AgentRole
agent = FallbackAdapter(agent_role=AgentRole.CODER, agent_id="test-coder")
result = agent.execute_task("implement add function")
# Coder返回: files_modified + test_files
# Reviewer返回: review_decision="approved"
# Planner返回: task_graph
# Explorer返回: context message
```
**LLMAgentAdapter（桥接现有AgentRole）**：
```python
from examples.agent_system.core.agent_interface import LLMAgentAdapter, AgentRole
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.llm import get_llm
llm = get_llm()
coder_role = CoderRole(llm=llm)
adapter = LLMAgentAdapter(coder_role, agent_role=AgentRole.CODER)
result = adapter.execute_task(
    "Implement add(a, b)",
    context={"code_files": {}, "iteration_count": 0},
)
print(result.files_modified)  # {"app.py": "def add(a,b): ..."}
```
**ClaudeCodeAdapter（Claude Code CLI子进程）**：
```python
from examples.agent_system.core.agent_interface import ClaudeCodeAdapter, AgentRole
adapter = ClaudeCodeAdapter(
    worktree_path="/path/to/worktree",
    claude_md_content="# Coder Role\nWrite clean Python. Follow TDD.",
    api_key_ref="ANTHROPIC_API_KEY",
    agent_role=AgentRole.CODER,
    timeout_seconds=300,
)
result = adapter.execute_task("Implement add(a, b) function")
# 自动:
# 1. 将CLAUDE.md写入worktree
# 2. 执行 claude --print -p "Implement add(a, b) function"
# 3. 解析stdout为AgentResult
```
#### 4.4.4 AgentResult 数据类
```python
@dataclass
class AgentResult:
    success: bool
    files_modified: dict[str, str]     # 路径 → 内容
    test_files: dict[str, str]         # 测试文件
    message: str                       # Agent输出消息
    token_usage: int                   # Token消耗
    review_decision: str               # "approved" | "changes"（仅Reviewer）
    review_feedback: str               # 审查反馈（仅Reviewer）
    task_graph: dict | None            # TaskGraph（仅Planner）
```
#### 4.4.5 AgentSession 数据类
```python
from examples.agent_system.core.agent_interface import AgentSession
session = AgentSession(
    agent_id="coder-1",
    role=AgentRole.CODER,
    machine_id="mac-mini-a",
    current_task="step-001",
    branch_lock="task/issue-42/step-001",
    engine=AgentEngine.CLAUDE_CODE,
    api_key_ref="key-ref-1",
    token_usage=15000,
    tasks_completed=5,
    tasks_failed=1,
)
d = session.to_dict()
s2 = AgentSession.from_dict(d)
```
---
### 4.5 Shared Context - 共享上下文板
**文件**: `core/shared_context.py`
Agent间通过仓库内的markdown文件通信，git追踪变更历史。
```python
from examples.agent_system.core.shared_context import SharedContext
ctx = SharedContext(
    repo_path="/path/to/repo",
    git_ops=ops,  # 可选，传入GitOps实例自动commit
)
# 初始化（创建目录和预定义文件）
ctx.init()
# 创建 .nal/context/ 目录和4个文件:
# - architecture_decisions.md
# - api_contracts.md
# - known_issues.md
# - exploration_notes.md
# 写入（覆盖）
ctx.write(
    filename="architecture_decisions.md",
    content="# Architecture Decisions\n\n## Use REST over gRPC\n...",
    agent_id="planner-1",
    auto_commit=True,  # 自动git commit
)
# 追加（带时间戳和Agent标记）
ctx.append(
    filename="known_issues.md",
    section="Login endpoint bug",
    content="The /auth/login endpoint returns 500 when password is empty.",
    agent_id="explorer-1",
)
# 追加内容格式:
# ## Login endpoint bug
# *2026-02-11 08:00 UTC by explorer-1*
# The /auth/login endpoint returns 500 when password is empty.
# 读取
content = ctx.read("api_contracts.md")
# 查询
files = ctx.list_files()      # ["architecture_decisions.md", ...]
exists = ctx.exists("foo.md")  # False
```
**预定义文件用途**：
| 文件 | 写入者 | 读取者 | 用途 |
|------|--------|--------|------|
| `architecture_decisions.md` | Planner | 所有人 | 架构决策记录 |
| `api_contracts.md` | Coder | Coder | Coder间的API接口约定 |
| `known_issues.md` | 任何Agent | 所有人 | 已知问题记录 |
| `exploration_notes.md` | Explorer | Coder, Planner | 代码库调研结果 |
---
## 5. Coordinator 系统调度器
**文件**: `coordinator.py`
Coordinator 是系统级调度器，用 LangGraph StateGraph 实现主循环。它调用 Core 层模块和 Agent，自身不包含任何业务逻辑。
### 5.1 状态定义
```python
class CoordinatorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # 消息历史
    task_graph: dict            # TaskGraph序列化
    current_task_id: str        # 当前正在处理的任务ID
    phase: str                  # 当前阶段
    active_agents: list[dict]   # AgentSession列表
    agent_result: dict          # 最近一次AgentResult
    tdd_result: dict            # 最近一次TDDResult
    tasks_completed: int        # 已完成任务数
    tasks_failed: int           # 已失败任务数
    total_iterations: int       # 总迭代次数
```
### 5.2 主循环状态机
```
START → plan → dispatch → execute → evaluate → merge → dispatch (loop)
                                       ↓ (retry)
                                    dispatch
                                       ↓ (failed, exceeded retries)
                                     idle → END
```
**6个节点**（每个是普通函数，不是Agent角色）：
| 节点 | 职责 |
|------|------|
| `plan_node` | 调用PlannerAgent拆解需求为TaskGraph |
| `idle_node` | 检查是否有READY任务，决定继续或结束 |
| `dispatch_node` | 选最高优先级READY任务，分配给Agent，获取锁 |
| `execute_node` | 调用CoderAgent执行任务（TDD Protocol） |
| `evaluate_node` | 检查结果，可调用Reviewer；成功→merge，失败→重试/升级 |
| `merge_node` | 合并完成的任务分支，检查是否解锁了下游任务 |
### 5.3 构建和运行
```python
from examples.agent_system.coordinator import (
    build_coordinator_graph,
    build_coordinator_initial_state,
)
# 构建
graph = build_coordinator_graph(
    agents={...},                    # Agent字典
    checkpointer=None,               # 可选: SqliteSaver
    interrupt_before=["execute"],     # 可选: 人工门控
)
# 初始状态
state = build_coordinator_initial_state("Build a REST API for user management")
# 运行
config = {"configurable": {"thread_id": "pipeline-001"}}
for event in graph.stream(state, config):
    for node_name, output in event.items():
        phase = output.get("phase", "?")
        completed = output.get("tasks_completed", "?")
        print(f"[{node_name}] phase={phase} completed={completed}")
```
### 5.4 调度策略
Coordinator在`dispatch_node`中选择任务的策略：
1. **关键路径优先**：下游依赖越多的任务越优先（`TaskGraph.get_ready_tasks()` 已排序）
2. **同Agent连续性**：同一顶层任务的叶子任务尽量分配给同一个Agent
3. **角色匹配**：代码任务给Coder，文档任务给Writer
### 5.5 失败处理
```
任务执行失败
  ↓
retry_count++
  ↓
retry_count < max_retries?
  ├── 是 → 任务回到READY队列 → 从dispatch重新开始
  └── 否 → 标记FAILED
              ↓
              下游任务标记BLOCKED
              ↓
              发通知（飞书/GitHub Issue）
              ↓
              pipeline继续处理其他无依赖任务
              ↓
              人工恢复: POST /api/task/{id}/resume
```
---
## 6. Integration Layer
### 6.1 Prometheus 指标
**文件**: `integrations/metrics.py`
三级指标体系。如果 `prometheus_client` 未安装，所有方法自动降级为no-op。
```python
from examples.agent_system.integrations.metrics import metrics
# --- Agent级指标 ---
metrics.record_task_completed("coder-1", "coder", "done")
metrics.record_task_failed("coder-1", "coder")
metrics.record_tokens("coder-1", "coder", 1500, model="opus")
metrics.record_retry("coder-1", "coder")
with metrics.track_task_duration("coder-1", "coder"):
    # ... agent执行任务 ...
    pass
# --- 任务级指标 ---
metrics.update_task_status_gauge({
    "pending": 3, "ready": 1, "coding": 2, "done": 5, "failed": 1
})
with metrics.track_tdd_step("write_test"):
    # ... 写测试 ...
    pass
metrics.record_diff_lines("task-001", 42)
metrics.record_test_pass_rate("task-001", 0.95)
with metrics.track_task_e2e(priority="high"):
    # ... 任务从READY到DONE ...
    pass
# --- 系统级指标 ---
metrics.set_active_agents(4)
metrics.set_active_locks(2)
with metrics.track_lock_wait():
    # ... 等待获取锁 ...
    pass
with metrics.track_dispatch_latency():
    # ... dispatch逻辑 ...
    pass
metrics.set_system_info({"version": "0.1", "machine": "mac-mini-a"})
```
**Prometheus指标清单**：
| 指标名 | 类型 | 标签 | 说明 |
|--------|------|------|------|
| `nal_agent_tasks_total` | Counter | agent_id, role, status | Agent任务完成计数 |
| `nal_agent_tokens_total` | Counter | agent_id, role, model | Agent token用量 |
| `nal_agent_task_duration_seconds` | Histogram | agent_id, role | Agent单任务耗时 |
| `nal_agent_retries_total` | Counter | agent_id, role | Agent重试次数 |
| `nal_tasks_by_status` | Gauge | status | 各状态任务数量 |
| `nal_tdd_step_duration_seconds` | Histogram | step | TDD各步骤耗时 |
| `nal_commit_diff_lines` | Histogram | task_id | 每次commit的diff行数 |
| `nal_test_pass_rate` | Gauge | task_id | 测试通过率 |
| `nal_task_e2e_duration_seconds` | Histogram | priority | 任务端到端耗时 |
| `nal_active_agents` | Gauge | - | 活跃Agent数 |
| `nal_active_locks` | Gauge | - | 活跃分支锁数 |
| `nal_lock_wait_seconds` | Histogram | - | 锁等待时间 |
| `nal_dispatch_latency_seconds` | Histogram | - | 调度延迟 |
| `nal_system_info` | Info | - | 系统信息 |
### 6.2 Gateway API
**文件**: `gateway/app.py`
两套端点并存：旧的线性流程 + 新的Coordinator API。
#### 6.2.1 Coordinator API端点（新增）
**启动Pipeline**：
```
POST /api/pipeline/start
Body: {"requirement": "Implement user auth", "thread_id": "optional-id"}
Response: {"thread_id": "abc123", "phase": "planning", "tasks_total": 0, ...}
```
**查询Pipeline状态**：
```
GET /api/status?thread_id=abc123
Response: {
    "thread_id": "abc123",
    "phase": "done",
    "tasks_total": 3,
    "tasks_completed": 3,
    "tasks_failed": 0,
    "tasks_ready": 0,
    "tasks_blocked": 0
}
```
**暂停Pipeline**：
```
POST /api/pipeline/stop?thread_id=abc123
Response: {"status": "stopped", "thread_id": "abc123"}
```
**恢复失败任务（人工介入）**：
```
POST /api/task/step-001/resume
Response: {"status": "resumed", "task_id": "step-001", "pipeline": "abc123"}
```
**查询任务详情**：
```
GET /api/task/step-001
Response: {
    "task_id": "step-001",
    "title": "Implement add()",
    "description": "Add function that sums two numbers",
    "status": "done",
    "assigned_agent": "coder-1",
    "tdd_mode": "full",
    "retry_count": 0,
    "depends_on": []
}
```
**Prometheus指标**：
```
GET /metrics
Response: (Prometheus text format)
```
#### 6.2.2 旧端点（保留，向后兼容）
```
POST /task/submit       → 提交任务（线性流程: coder→reviewer→tester→executor）
GET  /task/{thread_id}  → 查询任务状态
POST /approval/request  → 请求审批
POST /approval/resolve  → 审批决策
```
---
## 7. 测试
### 7.1 运行全量测试
```bash
cd examples/agent_system
# 运行所有NAL测试（161个）
python -m pytest tests/test_task_graph.py tests/test_git_ops.py \
  tests/test_tdd_protocol.py tests/test_agent_interface.py \
  tests/test_coordinator.py tests/test_integration.py -v
# 运行单个模块测试
python -m pytest tests/test_task_graph.py -v      # 41 tests
python -m pytest tests/test_git_ops.py -v          # 35 tests
python -m pytest tests/test_tdd_protocol.py -v     # 28 tests
python -m pytest tests/test_agent_interface.py -v   # 18 tests
python -m pytest tests/test_coordinator.py -v       # 16 tests (含E2E)
python -m pytest tests/test_integration.py -v       # 23 tests
```
### 7.2 测试覆盖说明
| 测试文件 | 覆盖模块 | 关键测试点 |
|---------|---------|-----------|
| `test_task_graph.py` | TaskGraph | DAG构建、状态流转、级联阻塞/解锁、环检测、序列化、关键路径排序 |
| `test_git_ops.py` | GitOps | 分支CRUD、锁获取/释放/过期/竞争、worktree、提交元数据、合并/冲突 |
| `test_tdd_protocol.py` | TDD Protocol | 红灯验证、绿灯验证、diff限制、回归检测、完整/轻量流程、重试逻辑 |
| `test_agent_interface.py` | Agent Interface | FallbackAdapter四角色、LLMAdapter+mock、ClaudeCodeAdapter健壮性、Session序列化 |
| `test_coordinator.py` | Coordinator | 每个节点独立测试、单任务E2E流水线、依赖链E2E流水线 |
| `test_integration.py` | Metrics+Context+Models | MetricsCollector所有方法、SharedContext CRUD+追加、Gateway Pydantic模型 |
### 7.3 不依赖外部服务的测试
所有161个测试均可在**无LLM API、无git.server、无Docker**的环境下运行：
- Agent使用 `FallbackAdapter`（确定性回退）
- Git操作使用 `tmp_path` fixture（pytest临时目录）
- 代码执行使用 `FakeExecutor`（可控mock）
---
## 8. 配置参考
### 8.1 环境变量
```bash
# LLM配置
AGENT_LLM_PROVIDER=openai       # openai | anthropic | zhipu | minimax | qwen
AGENT_LLM_MODEL=gpt-4o-mini      # 模型名
AGENT_LLM_TEMPERATURE=0.0        # 温度
# Discord集成
DISCORD_TOKEN=xxx
DISCORD_CHANNEL_ID=xxx
# 飞书集成
FEISHU_APP_ID=xxx
FEISHU_APP_SECRET=xxx
```
### 8.2 TaskGraph 关键参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_retries` | 3 | 任务最大重试次数 |
| `diff_line_limit` | 100 | 单步变更行数上限 |
| `tdd_mode` | "full" | TDD模式: "full" 或 "lite" |
### 8.3 GitOps 关键参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ttl` (锁) | 600秒 | 分支锁过期时间 |
| 命令超时 | 30秒 | git命令执行超时 |
### 8.4 Agent 关键参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `timeout_seconds` (ClaudeCode) | 300秒 | Claude Code CLI执行超时 |
| `max_iterations` (旧流程) | 10 | coder↔reviewer循环上限 |
---
## 文件结构参考
```
examples/agent_system/
├── core/                          # Layer 1: 纯Python核心层
│   ├── __init__.py
│   ├── task_graph.py              # TaskStatus, Task, TaskGraph, make_task_id
│   ├── git_ops.py                 # BranchLock, MergeResult, GitOps, branch helpers
│   ├── tdd_protocol.py            # TDDMode, TDDStep, TDDResult, TestRunner, TDDProtocol
│   ├── agent_interface.py         # AgentRole, AgentEngine, AgentResult, AgentSession,
│   │                              # AgentInterface, LLMAgentAdapter, ClaudeCodeAdapter,
│   │                              # FallbackAdapter, make_agent_id
│   └── shared_context.py          # SharedContext, PREDEFINED_FILES
├── coordinator.py                 # CoordinatorState, 6 nodes, 5 routers,
│                                  # build_coordinator_graph, build_coordinator_initial_state
├── integrations/
│   ├── __init__.py
│   └── metrics.py                 # 14 Prometheus metrics, MetricsCollector
├── gateway/
│   ├── app.py                     # FastAPI: 6 Coordinator endpoints + 4 legacy endpoints
│   └── models.py                  # PipelineStartRequest, PipelineStatus, TaskDetail + legacy
├── tests/
│   ├── test_task_graph.py         # 41 tests
│   ├── test_git_ops.py            # 35 tests
│   ├── test_tdd_protocol.py       # 28 tests
│   ├── test_agent_interface.py    # 18 tests
│   ├── test_coordinator.py        # 16 tests
│   └── test_integration.py        # 23 tests
├── tests/
│   ├── test_feishu_notifier.py    # 15 tests
│   └── ...
└── NAL_USAGE_GUIDE.md             # 本文档
```
---
## 9. 项目状态与开发历程
### 9.1 当前版本
**版本**: v0.2.0 (2026-02-11)
**测试**: 176个测试全部通过
**完成率**: 100%（修复后，3/3任务通过E2E验证）
### 9.2 Git提交历史
```
4f84fc5c feat(nal): add optional codebase scanning and context file support
108cbfae fix(nal): pass reviewer feedback to coder, run tests before commit, calibrate reviewer
a85248c3 fix(nal): use text message for task_failed notification
dad14594 feat(nal): integrate Feishu notifications into Coordinator
ea6e3049 feat(nal): add Coordinator, Integration layer, runner and docs
902ee81f feat(nal): add Core layer - TaskGraph, GitOps, TDD Protocol, Agent Interface
```
### 9.3 开发迭代与修复记录
| 迭代 | 问题 | 修复 | 效果 |
|------|------|------|------|
| v0.1.0 | Coordinator纯逻辑，不写文件不调git | 串联GitOps+文件写入到execute/merge节点 | 代码真正写入磁盘并提交 |
| v0.1.1 | `claude --print`模式不使用工具 | 改用`claude -p`模式（无--print） | Claude Code实际创建文件 |
| v0.1.2 | `claude -p`需要Write权限确认 | 创建`.claude/settings.local.json`预授权 | 非交互模式下正常写文件 |
| v0.1.3 | SSH push要密码导致超时 | `ssh-keygen` + `ssh-copy-id`免密 | push到远程成功 |
| v0.1.4 | Reviewer是FallbackAdapter(永远approved) | 实现ClaudeReviewerAdapter(真实审查) | 代码质量有门控 |
| v0.1.5 | Planner是FallbackAdapter(固定单任务) | 实现ClaudePlannerAdapter(智能拆解) | 需求被拆成多步有依赖的任务 |
| v0.1.6 | Reviewer误拒率高(风格/文档也拒) | 校准prompt: 只拒真实bug | 误拒率大幅下降 |
| v0.1.7 | Coder重试不知道被拒原因 | 存储review_feedback传给Coder | 重试定向修复而非盲试 |
| v0.1.8 | commit前不跑测试 | execute_node加pytest验证 | 不通过测试不允许commit |
| v0.1.9 | pytest扫全仓库触发无关依赖错误 | 只跑任务相关的test_*.py | 测试精准命中 |
| v0.2.0 | Planner不了解现有代码库 | 加`--scan-repo`和`--context-file` | 支持复杂项目上下文 |
### 9.4 E2E验证记录
**测试1: calculator.py（单任务）**
- 输入: "Create calculator.py with add/subtract/multiply/divide + tests"
- 结果: ✅ 1/1完成，12个pytest通过，commit+merge成功
**测试2: TODO API（多任务，Planner拆解）**
- 输入: "Build TODO list API: model + store + tests"
- 结果: ✅ 2/3完成（修复前），Reviewer发现真实bug
**测试3: string_utils.py（多任务+修复后）**
- 输入: "Create string_utils.py with reverse/is_palindrome/word_count + tests"
- 结果: ✅ 3/3完成，16个pytest通过，飞书全程实时通知
- Reviewer拒了2次（发现import缺失的真实bug），Coder收到反馈后修复通过
### 9.5 已知限制
| 限制 | 影响 | 计划 |
|------|------|------|
| 单Agent串行执行 | 无法并行处理无依赖任务 | 后续迭代 |
| 无checkpoint持久化 | pipeline中断状态丢失 | 后续迭代 |
| 不支持GPU/硬件依赖项目 | 本地pytest无法测试GPU代码 | 需远程执行 |
| 飞书只有通知，无命令交互 | 不能通过飞书发命令触发pipeline | 后续接入 |
| 无Grafana看板 | Prometheus指标已采集但无可视化 | 后续部署 |
### 9.6 文件统计
| 类别 | 文件数 | 代码行数 |
|------|--------|---------|
| Core Layer | 6 | ~1800 |
| Coordinator | 1 | ~620 |
| Integration | 3 | ~450 |
| Runner | 1 | ~200 |
| Tests | 7 | ~1100 |
| Documentation | 1 | ~1300 |
| **总计** | **19** | **~5470** |


