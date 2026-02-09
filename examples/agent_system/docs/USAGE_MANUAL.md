# Agent System 使用手册

## 目录

1. [项目概述](#1-项目概述)
2. [安装与配置](#2-安装与配置)
3. [核心概念](#3-核心概念)
4. [架构详解](#4-架构详解)
5. [飞书集成指南](#5-飞书集成指南)
6. [完整示例：抖音评论爬取与摘要](#6-完整示例抖音评论爬取与摘要)
7. [自迭代开发指南](#7-自迭代开发指南)
8. [最佳实践](#8-最佳实践)
9. [常见问题](#9-常见问题)

---

## 1. 项目概述

### 1.1 简介

Agent System 是一个基于 LangGraph 构建的多角色、自迭代智能体系统。该系统实现了完整的软件开发工作流，包括代码编写、代码审查、测试执行以及人工审批等环节。系统设计遵循模块化原则，支持通过飞书（Feishu）或 Discord 进行远程干预和任务管理。

本系统的核心价值在于提供了一个可扩展、可控的AI编程助手框架。它不仅能够自动完成代码编写任务，还能够在关键节点等待人工审批，确保代码质量和安全性。系统支持多种大语言模型提供商，包括 OpenAI、Anthropic、智谱AI（ZhipuAI）、MiniMax 和阿里云通义千问，用户可以根据需求灵活选择。

项目的技术栈以 Python 为主，使用 LangGraph 作为状态机框架，结合 LangChain 提供的 LLM 抽象层，实现了高度解耦的架构设计。系统通过 FastAPI 构建网关服务，支持 Webhook 方式与飞书等外部平台集成，实现了真正的远程协作能力。

### 1.2 核心特性

多角色协作架构是本系统最显著的特点。整个开发流程被分解为五个核心角色：Orchestrator（协调者）负责任务分解和流程控制，Coder（编码者）负责代码生成和修改，Reviewer（审查者）负责代码质量检查，Tester（测试者）负责编写和执行测试用例，Executor（执行者）负责在沙箱环境中运行代码。每个角色都有明确的职责边界，通过状态机协调工作。

自迭代能力是系统的另一大亮点。当代码执行失败时，系统能够自动分析错误原因，尝试修复技能代码，并热重载后重新执行。这一过程不需要人工干预，大大提高了自动化程度。系统会记录每次迭代的状态，确保可以随时中断和恢复。

人机协作机制通过 Checkpoint 和中断点实现。在执行高风险操作前，系统会将状态持久化到 SQLite 数据库，然后等待人工审批。用户可以通过飞书或 Discord 发送 approve 或 deny 命令，控制工作流的继续或终止。这种设计既保证了自动化效率，又不失人工监督能力。

### 1.3 应用场景

本系统适用于多种开发场景。在日常开发中，它可以作为AI编程助手，帮助开发者快速实现功能原型、编写测试用例、修复代码缺陷。开发者只需要描述需求，系统就能自动完成编码、审查、测试的完整流程。

在持续集成环境中，系统可以作为自动化代码质量关卡。当有新的代码提交时，系统自动执行代码审查和测试，只有通过所有检查的代码才能合并到主分支。这种自动化流程大大减轻了人工代码审查的负担。

对于需要远程协作的团队，系统提供了完美的解决方案。通过飞书集成，团队成员可以在手机上接收审批请求、查看开发进度、分配新任务。即使不在电脑前，也能保持对开发流程的掌控。

---

## 2. 安装与配置

### 2.1 环境准备

在开始安装之前，请确保你的开发环境满足以下要求。Python 版本需要 3.10 或更高版本，因为系统使用了较新的类型注解特性。推荐使用 Python 3.11 或 3.12 以获得最佳性能。你可以通过以下命令检查当前 Python 版本：

```bash
python --version
# 或者
python3 --version
```

系统需要安装多个 Python 包依赖，包括 LangGraph、LangChain、FastAPI 等核心库。最简便的安装方式是进入项目根目录，使用 pip 安装所有依赖：

```bash
cd /Users/ican/coding/langgraph-wj
pip install -e "examples/agent_system[all]"
```

如果你只需要核心功能，可以只安装基础依赖：

```bash
pip install -e "examples/agent_system"
```

可选的依赖包括 Docker（用于沙箱执行）和各种 LLM 提供商的特定包。根据你计划使用的 LLM 提供商，你可能需要额外安装相应的包。例如，使用 OpenAI 时需要 langchain-openai，使用 Anthropic 时需要 langchain-anthropic。

### 2.2 环境变量配置

系统通过环境变量进行配置，这是推荐的配置方式，因为它可以避免将敏感信息硬编码在代码中。创建一个名为 `.env` 的文件放在项目根目录或 agent_system 目录下，内容如下：

```bash
# LLM 配置
AGENT_LLM_PROVIDER=openai  # 可选值：openai, anthropic, zhipu, minimax, qwen
AGENT_LLM_MODEL=gpt-4o-mini
AGENT_LLM_TEMPERATURE=0.0
OPENAI_API_KEY=your_api_key_here

# Agent 行为配置
AGENT_MAX_ITERATIONS=10      # 最大迭代次数
AGENT_TIMEOUT_SECONDS=300    # 单步超时时间（秒）
AGENT_RETRY_ON_ERROR=true    # 错误时是否自动重试
AGENT_MAX_RETRIES=3          # 最大重试次数

# 飞书配置
FEISHU_APP_ID=your_feishu_app_id
FEISHU_APP_SECRET=your_feishu_app_secret
FEISHU_DOMAIN=feishu        # 中国版用 feishu，国际版用 lark
FEISHU_WEBHOOK_PATH=/feishu/events
FEISHU_PORT=8001
FEISHU_ENABLED=true

# Discord 配置（可选）
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=your_guild_id
DISCORD_CHANNEL_ID=your_channel_id
DISCORD_ENABLED=false

# 可观测性配置
LANGCHAIN_TRACING_V2=false
LANGCHAIN_PROJECT=agent-system
AGENT_LOG_LEVEL=INFO
```

获取飞书应用凭证的步骤如下：首先登录[飞书开放平台](https://open.feishu.cn/)，创建一个企业自建应用，获取应用凭证（App ID 和 App Secret）。然后配置应用的能力，启用消息相关的事件订阅和 API 权限。最后将服务器地址配置为 Webhook 回调地址。

### 2.3 目录结构说明

理解项目目录结构对于有效使用系统至关重要。以下是主要目录和文件的说明：

```
agent_system/
├── cli.py                 # 命令行入口
├── config.py              # 配置管理模块
├── graph.py               # LangGraph 状态机定义
├── nodes.py               # 节点实现
├── messaging.py           # Agent 间通信协议
├── sandbox.py             # 沙箱执行环境
│
├── roles/                 # Agent 角色实现
│   ├── base.py            # 角色基类
│   ├── coder.py           # Coder 角色
│   ├── reviewer.py        # Reviewer 角色
│   ├── tester.py          # Tester 角色
│   ├── orchestrator.py    # Orchestrator 角色
│   └── registry.py        # 角色注册表
│
├── skills/                # 可复用技能模块
│   ├── registry.py        # 技能注册表
│   ├── reloader.py        # 技能热重载
│   ├── editor.py          # 技能编辑器
│   ├── templates.py       # 技能模板
│   └── arithmetic.py      # 示例技能
│
├── prompts/               # 提示词模板
│   └── templates.py       # 各角色的系统提示词
│
├── gateway/               # 网关服务
│   ├── app.py             # FastAPI 应用
│   ├── feishu_bot.py      # 飞书 Bot 实现
│   ├── feishu_client.py   # 飞书 API 客户端
│   ├── discord_bot.py     # Discord Bot 实现
│   └── state_store.py     # 状态存储
│
├── llm/                   # LLM 集成
│   └── provider.py        # LLM 提供商抽象层
│
├── tests/                 # 测试用例
│   ├── test_core_loop.py
│   ├── test_interrupt_flow.py
│   ├── test_feishu.py
│   └── ...
│
└── docs/                  # 文档
    └── USAGE_MANUAL.md    # 本使用手册
```

### 2.4 快速验证安装

安装完成后，可以通过运行内置的 CLI 工具来验证安装是否正确。这个命令会使用内置的 fallback 逻辑执行一个简单的演示任务，不需要配置任何 API Key：

```bash
python examples/agent_system/cli.py
```

如果看到类似以下输出，说明安装成功：

```json
{
  "messages": [...],
  "code_files": {"app.py": "..."},
  "iteration_count": 1,
  "review_status": "approved",
  ...
}
```

你也可以运行测试套件来验证所有功能：

```bash
# 运行所有测试
python -m pytest examples/agent_system/tests/

# 运行特定测试文件
python -m pytest examples/agent_system/tests/test_core_loop.py -v
python -m pytest examples/agent_system/tests/test_feishu.py -v
```

---

## 3. 核心概念

### 3.1 Agent State（智能体状态）

Agent State 是贯穿整个工作流的核心数据结构，它记录了当前执行上下文的所有信息。理解状态结构对于掌握系统工作原理至关重要：

```python
class AgentState(TypedDict):
    # 消息历史，记录所有对话
    messages: Annotated[list[BaseMessage], add_messages]
    
    # 代码文件内容，键为文件名，值为代码内容
    code_files: dict[str, str]
    
    # 当前迭代次数，用于控制循环和避免无限迭代
    iteration_count: int
    
    # 审查结果：approved 或 changes_requested
    review_status: Literal["approved", "changes"]
    
    # 审查者反馈，用于指导 Coder 下次迭代
    reviewer_feedback: str
    
    # 待执行操作描述
    pending_action: str
    
    # 审批状态：pending, approved, denied
    approval_status: Literal["pending", "approved", "denied"]
    
    # 最后执行结果
    last_execution: str
    
    # 技能执行结果
    skill_result: int
    
    # 是否已尝试修复技能
    skill_repair_attempted: bool
    
    # 测试相关状态
    test_code: str
    test_status: Literal["pending", "generated", "passed", "failed", "skipped"]
    
    # 协调者相关状态
    execution_plan: list[dict]    # 执行计划列表
    orchestrator_status: Literal["planning", "executing", "completed"]
```

状态在整个图中流动，每个节点读取状态、进行处理、返回更新后的状态。这种设计确保了工作流的可追溯性和可恢复性。

### 3.2 角色（Roles）

系统中的每个角色都是一个独立的处理单元，有自己的职责和输出格式。角色设计遵循单一职责原则，每个角色只做一件事并做好。

**CoderRole** 是代码生成的核心角色。它的输入是任务描述和（可选的）现有代码和审查反馈，输出是更新后的代码文件。Coder 会根据反馈迭代改进代码，直到审查通过。这个角色的关键配置包括使用的 LLM 模型、温度参数等。

**ReviewerRole** 负责代码质量把关。它会检查代码是否满足需求、是否有明显 bug、是否符合编码规范。审查结果只有两种：通过（approved）或要求修改（changes_requested）。如果要求修改，Reviewer 必须提供具体的反馈说明需要修改什么。

**TesterRole** 专注于测试。它会为生成的代码编写测试用例，包括正常流程测试和边界情况测试。测试失败会触发 Coder 的新一轮迭代。

**OrchestratorRole** 是任务协调者。它负责将复杂任务分解为可管理的子任务，并协调各角色的工作顺序。Orchestrator 可以根据任务特点动态决定使用哪些角色、以什么顺序执行。

### 3.3 技能（Skills）

技能是可热重载的代码模块，与普通代码不同，技能可以被动态修改和重新加载，而无需重启整个系统。这种设计使得系统可以在运行时学习和改进。

技能的注册和使用流程如下：首先定义一个 Python 模块（例如 `skills/arithmetic.py`），模块中包含可被调用的函数；然后通过 SkillRegistry 注册这个模块；最后在需要时从注册表获取模块并调用其函数。当技能执行失败时，系统可以自动更新技能代码、重新加载、然后重试。

```python
# skills/arithmetic.py
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b
```

```python
# 注册和使用技能
from examples.agent_system.skills.registry import SkillRegistry

registry = SkillRegistry()
registry.register("arithmetic", "examples.agent_system.skills.arithmetic")

skill = registry.get("arithmetic").module
result = skill.add(2, 3)  # 返回 5
```

### 3.4 消息协议（Messaging Protocol）

Agent 间通信采用结构化的消息协议，支持多种消息类型和优先级：

```python
class MessageType(Enum):
    REQUEST = "request"      # 请求执行某个操作
    RESPONSE = "response"   # 响应请求
    NOTIFICATION = "notification"  # 通知，不期望响应
    HANDOFF = "handoff"      # 任务交接

class MessagePriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
```

消息队列按照优先级排序，高优先级的消息会被优先处理。这种设计确保了紧急任务（如错误修复请求）能够被及时响应。

---

## 4. 架构详解

### 4.1 状态机架构

系统使用 LangGraph 构建状态机，工作流图结构如下：

```
START
  │
  ▼
Orchestrator (可选)
  │
  ▼
Coder ──► Reviewer ──┬──► Tester ──► Approver ──► Executor ──► END
        ▲            │
        │            └──失败────────┘
        │                         │
        └───────需要修改──────────┘
```

这个流程展示了标准的编码-审查-测试循环。Coder 生成代码后由 Reviewer 审查，如果通过则进入测试阶段，如果失败则返回 Coder 重新修改。测试失败同样会返回 Coder，形成完整的质量保证闭环。

Approver 节点是人工审批的入口点。在执行高风险操作（如运行外部代码）前，工作流会在此处中断，等待人工批准。审批通过后，Executor 在沙箱中执行代码。

### 4.2 工作流执行流程

一次完整的工作流执行包含以下步骤：

**第一步：初始化**。系统根据配置创建 LLM 实例、角色实例、状态图。初始状态包含任务描述和空代码文件。

**第二步：Coder 处理**。Coder 读取任务描述和当前代码状态，调用 LLM 生成或修改代码。生成的代码会被解析并存储到 `code_files` 中。

**第三步：Reviewer 审查**。Reviewer 读取 Coder 生成的代码，按照预定义的质量标准进行评估。输出是 `review_status`（approved 或 changes）和详细的反馈信息。

**第四步：条件分支**。根据 Reviewer 的结果决定下一步：如果需要修改，返回 Coder 进入下一轮迭代；如果通过，进入测试阶段。

**第五步：Tester 测试**。Tester 为代码编写测试用例，执行测试，根据结果设置 `test_status`。测试失败返回 Coder，测试通过则进入审批阶段。

**第六步：人工审批**。工作流在 Approver 节点暂停，等待审批。用户通过飞书或 Discord 发送审批指令。

**第七步：执行**。获得批准后，Executor 在沙箱中运行代码。结果存储在 `last_execution` 中。

### 4.3 Checkpoint 与恢复

系统使用 SQLite 作为 Checkpoint 存储，支持工作流的中断和恢复。这对于长时间运行的任务特别有用，可以在需要时暂停、稍后继续。

```python
from langgraph.checkpoint import MemorySaver, SqliteSaver
from examples.agent_system.graph import build_graph, build_initial_state

# 使用 SQLite 持久化（推荐）
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")

# 构建图，配置中断点
graph = build_graph(
    llm=llm,
    interrupt_before=["approver"],  # 在审批前中断
    checkpointer=checkpointer,
)

# 执行工作流
thread_id = "task-001"
config = {"configurable": {"thread_id": thread_id}}
result = graph.invoke(initial_state, config=config)

# 检查是否需要审批
if graph.get_state(config).tasks:
    # 工作流暂停，等待审批
    print("需要人工审批...")
    
    # 审批后继续执行
    graph.invoke(None, config=config)
```

### 4.4 LLM 提供商抽象

系统通过统一的接口支持多种 LLM 提供商，这种设计使得切换模型变得非常简单：

```python
from examples.agent_system.llm import get_llm

# 使用 OpenAI（默认）
llm = get_llm()  # 读取环境变量 AGENT_LLM_PROVIDER

# 明确指定
llm = get_llm(provider="openai", model="gpt-4o")

# 使用 Anthropic
llm = get_llm(provider="anthropic", model="claude-3-5-sonnet-20241022")

# 使用智谱 AI
llm = get_llm(provider="zhipu", model="glm-4-plus")

# 使用 MiniMax
llm = get_llm(provider="minimax", model="abab6.5s-chat")

# 使用通义千问
llm = get_llm(provider="qwen", model="qwen-turbo")
```

每个提供商都有默认模型配置，如果不指定模型名，系统会使用默认值。温度参数可以调整生成内容的随机性，低温度（0.0）产生更确定性的输出，高温度产生更多样化的输出。

---

## 5. 飞书集成指南

### 5.1 飞书应用配置

在开始配置之前，你需要在飞书开放平台创建一个企业自建应用。登录 [飞书开放平台](https://open.feishu.cn/)，选择"创建企业自建应用"，填写应用名称和描述。

创建应用后，需要配置以下权限：

- `im:message:send_as_bot` - 以机器人身份发送消息
- `im:message:receive` - 接收消息
- `im:chat:read` - 读取群聊信息
- `im:chat:write` - 发送群聊消息

还需要配置事件订阅，包括 `im.message.receive_v1` 事件类型。回调 URL 需要配置为你的服务器地址（可以是 ngrok 暴露的本地地址用于测试）。

### 5.2 启动飞书网关服务

配置完成后，启动飞书 Webhook 服务：

```bash
# 直接运行
uvicorn examples.agent_system.gateway.feishu_bot:app --reload --port 8001

# 或者通过模块运行
python -c "from examples.agent_system.gateway.feishu_bot import create_app; app, _ = create_app(); import uvicorn; uvicorn.run(app, host='0.0.0.0', port=8001)"
```

服务启动后，它会监听配置的 Webhook 路径（默认 `/feishu/events`），接收飞书的事件推送。

### 5.3 飞书命令使用

飞书 Bot 支持以下命令：

| 命令 | 功能 |
|------|------|
| `/request <描述>` | 创建审批请求 |
| `/approve [request_id]` | 审批通过（省略 ID 则审批最新的） |
| `/deny [request_id]` | 拒绝请求 |
| `/status` | 查看待审批请求 |
| `/help` | 显示帮助信息 |

审批流程示例：

```
用户：/request 确认执行代码更新

Bot：🔔 审批请求已创建
     请求 ID: abc12345
     描述: 确认执行代码更新

用户：/approve abc12345

Bot：✅ 已批准：确认执行代码更新
     工作流将继续执行...
```

### 5.4 在代码中集成飞书审批

在工作流中集成飞书审批，需要配置中断点并使用 Gateway API：

```python
from examples.agent_system.graph import build_graph, build_initial_state
from examples.agent_system.config import get_config
from langgraph.checkpoint import SqliteSaver

# 加载配置
config = get_config()

# 创建检查点存储
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")

# 构建图，在审批前中断
graph = build_graph(
    llm=llm,
    interrupt_before=["approver"],
    checkpointer=checkpointer,
)

# 初始状态
initial_state = build_initial_state()

# 设置任务
initial_state["messages"].append(
    HumanMessage(content="实现一个计算斐波那契数列的函数")
)

# 开始执行
thread_id = "fibonacci-task"
config = {"configurable": {"thread_id": thread_id}}
result = graph.invoke(initial_state, config=config)

# 检查状态
state = graph.get_state(config)
if state.tasks:
    print("工作流暂停，等待飞书审批...")
    print(f"当前节点: {state.tasks[0].name}")
```

审批后，调用更新状态接口继续执行。飞书 Bot 会自动处理这个流程。

### 5.5 接收飞书任务消息

你可以配置系统监听飞书的特定消息格式来触发任务执行：

```python
# 在 feishu_bot.py 中扩展消息处理
async def handle_task_message(event_data, client, store):
    # 解析任务描述
    text = decode_message_content(event_data)
    
    if text.startswith("/task"):
        task_description = text[5:].strip()
        
        # 创建新任务
        thread_id = f"task-{uuid.uuid4().hex[:8]}"
        
        # 初始化工作流
        initial_state = build_initial_state()
        initial_state["messages"].append(
            HumanMessage(content=task_description)
        )
        
        # 开始执行
        task_config = {"configurable": {"thread_id": thread_id}}
        graph.invoke(initial_state, config=task_config)
        
        # 发送确认消息
        await client.send_text_message(
            user_id,
            f"✅ 任务已创建: {task_description[:50]}...\n"
            f"任务 ID: {thread_id}\n"
            f"使用 /status 查看进度"
        )
```

---

## 6. 完整示例：抖音评论爬取与摘要

### 6.1 项目概述

本示例展示如何构建一个自动化系统，爬取指定抖音视频的评论区，使用大语言模型对评论进行情感分析和摘要，最后通过飞书推送结果。这个例子涵盖了技能开发、LLM 集成、外部 API 调用、数据处理等核心功能。

### 6.2 第一步：创建抖音爬取技能

首先创建一个可重用的技能模块，用于爬取抖音评论：

```python
# skills/douyin_crawler.py
"""
抖音评论爬取技能

依赖安装：
pip install requests httpx beautifulsoup4 lxml

注意：抖音有反爬机制，生产环境建议使用官方 API 或第三方服务
"""

import json
import re
from typing import List, Dict, Optional
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup


@dataclass
class DouyinComment:
    """评论数据结构"""
    user_id: str
    username: str
    content: str
    create_time: str
    like_count: int
    reply_count: int


class DouyinCrawlerSkill:
    """抖音评论爬取技能类"""
    
    BASE_URL = "https://www.douyin.com"
    
    def __init__(self, timeout: int = 30):
        """初始化爬虫
        
        Args:
            timeout: 请求超时时间（秒）
        """
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
    
    def get_video_id_from_url(self, url: str) -> Optional[str]:
        """从 URL 提取视频 ID
        
        支持多种 URL 格式：
        - https://v.douyin.com/xxxxxx
        - https://www.douyin.com/video/xxxxxx
        """
        # 短链接格式
        match = re.search(r"v\.douyin\.com/(\w+)", url)
        if match:
            return match.group(1)
        
        # 长链接格式
        match = re.search(r"video/(\d+)", url)
        if match:
            return match.group(1)
        
        return None
    
    def expand_short_url(self, short_url: str) -> str:
        """展开短链接"""
        try:
            response = self.client.head(short_url, follow_redirects=True)
            return str(response.url)
        except Exception:
            return short_url
    
    def fetch_video_info(self, video_url: str) -> Dict:
        """获取视频信息
        
        Args:
            video_url: 视频链接
            
        Returns:
            包含视频信息的字典
        """
        expanded_url = self.expand_short_url(video_url)
        video_id = self.get_video_id_from_url(expanded_url)
        
        if not video_id:
            raise ValueError(f"无法解析视频 ID: {video_url}")
        
        # 实际场景中，这里需要调用抖音 API 或使用 Selenium 等工具
        # 以下为示例代码
        try:
            response = self.client.get(expanded_url)
            soup = BeautifulSoup(response.text, "lxml")
            
            # 提取视频信息
            title = soup.find("meta", {"property": "og:title"})["content"] if soup.find("meta", {"property": "og:title"}) else ""
            description = soup.find("meta", {"property": "og:description"})["content"] if soup.find("meta", {"property": "og:description"}) else ""
            
            return {
                "video_id": video_id,
                "url": expanded_url,
                "title": title,
                "description": description,
            }
        except Exception as e:
            raise RuntimeError(f"获取视频信息失败: {e}")
    
    def fetch_comments(
        self,
        video_url: str,
        max_comments: int = 100,
        offset: int = 0,
    ) -> List[DouyinComment]:
        """获取视频评论
        
        Args:
            video_url: 视频链接
            max_comments: 最大获取评论数
            offset: 偏移量
            
        Returns:
            评论列表
        """
        video_info = self.fetch_video_info(video_url)
        video_id = video_info["video_id"]
        
        comments = []
        
        # 调用抖音评论 API（示例 URL，实际需要从页面获取）
        api_url = f"{self.BASE_URL}/aweme/v2/web/comment/list/"
        params = {
            "video_id": video_id,
            "count": min(max_comments, 20),
            "cursor": offset,
        }
        
        try:
            # 实际调用需要处理签名等反爬机制
            # response = self.client.get(api_url, params=params)
            # data = response.json()
            
            # 示例数据
            example_comments = [
                DouyinComment(
                    user_id="user001",
                    username="张三",
                    content="这个视频太棒了！",
                    create_time="2024-01-15 10:30:00",
                    like_count=1234,
                    reply_count=56,
                ),
                DouyinComment(
                    user_id="user002",
                    username="李四",
                    content="内容很实用，学到了",
                    create_time="2024-01-15 11:20:00",
                    like_count=892,
                    reply_count=34,
                ),
            ]
            
            return example_comments[:max_comments]
            
        except Exception as e:
            raise RuntimeError(f"获取评论失败: {e}")
    
    def export_comments_to_dict(self, comments: List[DouyinComment]) -> List[Dict]:
        """将评论导出为字典列表"""
        return [
            {
                "user_id": c.user_id,
                "username": c.username,
                "content": c.content,
                "create_time": c.create_time,
                "like_count": c.like_count,
                "reply_count": c.reply_count,
            }
            for c in comments
        ]


# 便捷函数
def crawl_douyin_comments(
    video_url: str,
    max_comments: int = 100,
) -> str:
    """
    爬取抖音视频评论（供 Agent 调用）
    
    Args:
        video_url: 抖音视频链接
        max_comments: 最大评论数
        
    Returns:
        JSON 格式的评论数据
    """
    crawler = DouyinCrawlerSkill()
    comments = crawler.fetch_comments(video_url, max_comments)
    return json.dumps(crawler.export_comments_to_dict(comments), ensure_ascii=False, indent=2)
```

### 6.3 第二步：创建评论摘要技能

接下来创建一个使用 LLM 进行情感分析和摘要的技能：

```python
# skills/comment_analyzer.py
"""
评论分析技能

使用大语言模型对评论进行情感分析和摘要
"""

import json
from typing import Dict, List, TypedDict
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


class CommentSummary(TypedDict):
    """摘要结果数据结构"""
    total_comments: int
    positive_count: int
    neutral_count: int
    negative_count: int
    key_topics: List[str]
    summary: str
    highlights: List[str]  # 高赞评论摘要


class CommentAnalyzerSkill:
    """评论分析技能类"""
    
    SYSTEM_PROMPT = """你是一个专业的社交媒体评论分析师。你的任务是：
    
1. 对评论进行情感分析（积极、中性、消极）
2. 识别评论中的关键主题和话题
3. 总结评论的整体观点和用户反馈
4. 提取高赞评论的核心观点

请保持分析的客观性和准确性，用简洁的语言表达分析结果。"""
    
    def __init__(self, llm: BaseChatModel):
        """初始化分析器
        
        Args:
            llm: LangChain LLM 实例
        """
        self.llm = llm
    
    def analyze_sentiment(self, comments: List[Dict]) -> Dict[str, int]:
        """情感分析
        
        Args:
            comments: 评论列表
            
        Returns:
            各情感类别的数量统计
        """
        comment_texts = [c["content"] for c in comments[:50]]  # 限制数量
        
        prompt = f"""
对以下抖音视频评论进行情感分析，统计积极、中性、消极评论的数量。

评论内容：
{chr(10).join(f'- {c}' for c in comment_texts)}

请以 JSON 格式返回结果：
{{
    "positive_count": <数量>,
    "neutral_count": <数量>,
    "negative_count": <数量>
}}
"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        
        response = self.llm.invoke(messages)
        
        # 解析 JSON 结果
        try:
            result = json.loads(response.content)
            return result
        except json.JSONDecodeError:
            # 如果解析失败，尝试提取关键数字
            return {"positive_count": 0, "neutral_count": 0, "negative_count": 0}
    
    def extract_topics(self, comments: List[Dict]) -> List[str]:
        """提取关键主题
        
        Args:
            comments: 评论列表
            
        Returns:
            主题列表
        """
        comment_texts = [c["content"] for c in comments[:30]]
        
        prompt = f"""
从以下抖音视频评论中提取关键主题和话题，最多返回 5 个最重要的主题。

评论内容：
{chr(10).join(f'- {c}' for c in comment_texts)}

请直接返回主题列表，用换行分隔。
"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        
        response = self.llm.invoke(messages)
        
        topics = [
            line.strip().lstrip("-0123456789. ")
            for line in response.content.split("\n")
            if line.strip()
        ]
        
        return topics[:5]
    
    def summarize_comments(self, comments: List[Dict]) -> str:
        """生成评论摘要
        
        Args:
            comments: 评论列表
            
        Returns:
            摘要文本
        """
        # 按点赞数排序，取前 10 条高赞评论
        top_comments = sorted(comments, key=lambda x: x.get("like_count", 0), reverse=True)[:10]
        
        prompt = f"""
根据以下抖音视频的高赞评论，生成一段简短的摘要（150 字以内），总结用户的整体反馈和观点。

高赞评论：
{chr(10).join(f'- [{c.get("like_count", 0)}赞] {c["content"]}' for c in top_comments)}

请直接返回摘要内容，不需要额外格式。
"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        
        response = self.llm.invoke(messages)
        return response.content.strip()
    
    def analyze(self, comments_json: str) -> CommentSummary:
        """完整的评论分析流程
        
        Args:
            comments_json: JSON 格式的评论数据
            
        Returns:
            完整的分析结果
        """
        comments = json.loads(comments_json)
        
        if not comments:
            return CommentSummary(
                total_comments=0,
                positive_count=0,
                neutral_count=0,
                negative_count=0,
                key_topics=[],
                summary="没有找到评论",
                highlights=[],
            )
        
        # 并行执行分析任务
        sentiment = self.analyze_sentiment(comments)
        topics = self.extract_topics(comments)
        summary = self.summarize_comments(comments)
        
        # 提取高赞评论摘要
        top_comments = sorted(comments, key=lambda x: x.get("like_count", 0), reverse=True)[:3]
        highlights = [c["content"][:100] for c in top_comments]
        
        return CommentSummary(
            total_comments=len(comments),
            positive_count=sentiment.get("positive_count", 0),
            neutral_count=sentiment.get("neutral_count", 0),
            negative_count=sentiment.get("negative_count", 0),
            key_topics=topics,
            summary=summary,
            highlights=highlights,
        )


# 便捷函数
def analyze_douyin_comments(
    comments_json: str,
    llm_provider: str = "openai",
) -> str:
    """
    分析抖音评论（供 Agent 调用）
    
    Args:
        comments_json: JSON 格式的评论数据
        llm_provider: LLM 提供商
        
    Returns:
        JSON 格式的分析结果
    """
    from examples.agent_system.llm import get_llm
    
    llm = get_llm(provider=llm_provider)
    analyzer = CommentAnalyzerSkill(llm)
    result = analyzer.analyze(comments_json)
    
    return json.dumps(dict(result), ensure_ascii=False, indent=2)
```

### 6.4 第三步：创建飞书通知技能

创建一个将结果推送到飞书的技能：

```python
# skills/feishu_notifier.py
"""
飞书通知技能

将分析结果推送到飞书
"""

import json
from typing import Dict, Optional
from langchain_core.language_models import BaseChatModel


class FeishuNotifierSkill:
    """飞书通知技能类"""
    
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        receiver_id: str,
        receiver_type: str = "open_id",
    ):
        """初始化飞书通知器
        
        Args:
            app_id: 飞书应用 ID
            app_secret: 飞书应用密钥
            receiver_id: 接收者 ID（open_id 或 chat_id）
            receiver_type: 接收者类型
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.receiver_id = receiver_id
        self.receiver_type = receiver_type
        self._access_token = None
    
    def _get_access_token(self) -> str:
        """获取访问令牌"""
        import httpx
        
        if self._access_token:
            return self._access_token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }
        
        response = httpx.post(url, json=payload)
        data = response.json()
        
        if data.get("code") == 0:
            self._access_token = data["tenant_access_token"]
            return self._access_token"]
        else:
            raise RuntimeError(f"获取访问令牌失败: {data}")
    
    def send_summary_card(self, summary_data: Dict) -> bool:
        """发送摘要卡片消息
        
        Args:
            summary_data: 分析结果数据
            
        Returns:
            是否发送成功
        """
        import httpx
        
        access_token = self._get_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        
        # 构建消息内容
        params = {
            "receive_id_type": self.receiver_type,
        }
        
        content = self._build_card_content(summary_data)
        
        payload = {
            "receive_id": self.receiver_id,
            "msg_type": "interactive",
            "content": json.dumps(content, ensure_ascii=False),
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        response = httpx.post(url, params=params, json=payload, headers=headers)
        return response.status_code == 200
    
    def _build_card_content(self, data: Dict) -> Dict:
        """构建卡片消息内容"""
        # 计算积极率
        total = data["total_comments"]
        positive = data["positive_count"]
        positive_rate = (positive / total * 100) if total > 0 else 0
        
        # 构建主题列表
        topics_text = "\n".join(f"• {t}" for t in data.get("key_topics", []))
        
        # 构建高赞评论列表
        highlights_text = "\n".join(
            f"📌 {h}" for h in data.get("highlights", [])
        )
        
        card_content = {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "title": {
                    "tag": "text",
                    "content": "📊 抖音评论分析报告",
                },
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**视频评论分析结果**\n\n"
                                   f"📈 **统计概览**\n"
                                   f"- 总评论数：{total}\n"
                                   f"- 👍 积极：{data['positive_count']} ({positive_rate:.1f}%)\n"
                                   f"- 😐 中性：{data['neutral_count']}\n"
                                   f"- 👎 消极：{data['negative_count']}\n\n"
                                   f"🏷️ **热门话题**\n{topics_text}",
                    },
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"💡 **摘要**\n\n{data.get('summary', '无')}\n\n"
                                   f"🔥 **热门评论**\n\n{highlights_text}",
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "刷新数据"},
                            "type": "primary",
                            "action_type": 1,
                        },
                    ],
                },
            ],
        }
        
        return card_content


# 便捷函数
def notify_feishu(
    summary_json: str,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
    receiver_id: Optional[str] = None,
) -> str:
    """
    通过飞书发送分析结果（供 Agent 调用）
    
    Args:
        summary_json: JSON 格式的分析结果
        app_id: 飞书应用 ID（可选，从环境变量读取）
        app_secret: 飞书应用密钥
        receiver_id: 接收者 ID
        
    Returns:
        操作结果
    """
    import os
    
    app_id = app_id or os.getenv("FEISHU_APP_ID")
    app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")
    
    if not app_id or not app_secret:
        return json.dumps({"success": False, "error": "缺少飞书配置"})
    
    data = json.loads(summary_json)
    
    # 如果没有指定 receiver_id，发送到应用所在的群聊
    chat_id = receiver_id or os.getenv("FEISHU_CHAT_ID")
    
    notifier = FeishuNotifierSkill(
        app_id=app_id,
        app_secret=app_secret,
        receiver_id=chat_id or app_id,
    )
    
    success = notifier.send_summary_card(data)
    
    return json.dumps({
        "success": success,
        "message": "发送成功" if success else "发送失败",
    }, ensure_ascii=False)
```

### 6.5 第四步：创建任务 Orchestrator

现在创建一个协调整个流程的 Orchestrator：

```python
# roles/douyin_orchestrator.py
"""
抖音评论分析任务协调器

协调爬取、分析、通知的完整流程
"""

from typing import Dict, List, TypedDict
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.roles.base import AgentRole, RoleResult
from examples.agent_system.prompts.templates import get_orchestrator_prompt


class TaskResult(TypedDict):
    """任务结果数据结构"""
    video_url: str
    comments_count: int
    analysis_result: Dict
    notification_sent: bool


class DouyinOrchestratorRole(AgentRole):
    """抖音评论分析任务协调器"""
    
    def __init__(self, *, llm: BaseChatModel | None = None):
        """初始化协调器
        
        Args:
            llm: LLM 实例（可选，不使用 LLM 时使用默认流程）
        """
        super().__init__(
            name="douyin_orchestrator",
            llm=llm,
            description="协调抖音评论爬取、分析和通知流程",
        )
    
    def process(self, state) -> RoleResult:
        """处理任务"""
        if self.llm is None:
            return self._fallback_process(state)
        return self._llm_process(state)
    
    def _fallback_process(self, state) -> RoleResult:
        """默认处理流程"""
        messages = state.get("messages", [])
        
        # 提取视频 URL
        task_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                task_msg = msg.content
                break
        
        if not task_msg:
            return RoleResult(
                message=AIMessage(content="错误：未找到任务描述"),
                state_updates={},
            )
        
        # 解析任务
        video_url = self._extract_video_url(task_msg)
        
        if not video_url:
            return RoleResult(
                message=AIMessage(content="错误：未找到视频 URL"),
                state_updates={},
            )
        
        # 生成执行计划
        plan = [
            {"agent": "douyin_crawler", "task": f"爬取视频 {video_url} 的评论", "status": "pending"},
            {"agent": "comment_analyzer", "task": "分析评论内容", "status": "pending"},
            {"agent": "feishu_notifier", "task": "发送分析结果到飞书", "status": "pending"},
        ]
        
        return RoleResult(
            message=AIMessage(
                content=f"抖音评论分析任务已创建\n\n视频: {video_url}\n计划: {len(plan)} 个步骤",
            ),
            state_updates={
                "execution_plan": plan,
                "orchestrator_status": "executing",
                "task_video_url": video_url,
            },
        )
    
    def _llm_process(self, state) -> RoleResult:
        """LLM 驱动的任务协调"""
        task = self._extract_task(state)
        
        messages = get_orchestrator_prompt(
            task=f"分析抖音视频评论\n\n{task}",
            available_agents=[
                "douyin_crawler",
                "comment_analyzer",
                "feishu_notifier",
            ],
            current_state=self._get_current_state(state),
        )
        
        response = self.llm.invoke(messages)
        
        # 解析执行计划
        plan = self._parse_plan(response.content)
        
        return RoleResult(
            message=AIMessage(content=response.content),
            state_updates={
                "execution_plan": plan,
                "orchestrator_status": "executing",
            },
        )
    
    def _extract_video_url(self, text: str) -> str:
        """从文本提取视频 URL"""
        import re
        
        patterns = [
            r"https?://[^\s]+douyin[^\s]*",
            r"https?://v\.douyin\.com/[^\s]+",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        
        return ""
    
    def _extract_task(self, state) -> str:
        """从状态提取任务描述"""
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage):
                return msg.content
        return ""
    
    def _get_current_state(self, state) -> str:
        """获取当前状态描述"""
        plan = state.get("execution_plan", [])
        if not plan:
            return "任务刚开始，等待分析视频链接"
        
        completed = sum(1 for s in plan if s["status"] == "completed")
        return f"已完成 {completed}/{len(plan)} 个步骤"
    
    def _parse_plan(self, response: str) -> List[Dict]:
        """解析执行计划"""
        import re
        
        plan = []
        lines = response.strip().split("\n")
        pattern = r"^\d+\.\s*\[(\w+)\]\s*(.+)$"
        
        for line in lines:
            match = re.match(pattern, line.strip())
            if match:
                plan.append({
                    "agent": match.group(1),
                    "task": match.group(2).strip(),
                    "status": "pending",
                })
        
        return plan if plan else [
            {"agent": "douyin_crawler", "task": "爬取评论", "status": "pending"},
            {"agent": "comment_analyzer", "task": "分析评论", "status": "pending"},
            {"agent": "feishu_notifier", "task": "发送结果", "status": "pending"},
        ]
```

### 6.6 第五步：组装完整工作流

最后，将所有组件组装成完整的工作流：

```python
# examples/douyin_analysis_workflow.py
"""
抖音评论分析完整工作流示例

使用方法：
python examples/douyin_analysis_workflow.py --video-url "https://v.douyin.com/..."
"""

import argparse
import json
from typing import Dict

from langgraph.checkpoint import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage

from examples.agent_system.graph import build_graph, AgentState
from examples.agent_system.llm import get_llm
from examples.agent_system.config import get_config
from examples.agent_system.roles.base import RoleResult


# 导入技能
from examples.agent_system.skills.douyin_crawler import crawl_douyin_comments
from examples.agent_system.skills.comment_analyzer import analyze_douyin_comments
from examples.agent_system.skills.feishu_notifier import notify_feishu


def create_douyin_workflow():
    """创建抖音分析工作流图"""
    
    config = get_config()
    llm = get_llm(
        provider=config.llm.provider.value,
        model=config.llm.model,
        temperature=config.llm.temperature,
    )
    
    # 创建节点
    def crawler_node(state: AgentState) -> Dict:
        """爬取节点"""
        video_url = state.get("task_video_url", "")
        
        if not video_url:
            return {"messages": [AIMessage(content="错误：缺少视频 URL")]}
        
        try:
            comments = crawl_douyin_comments(video_url, max_comments=100)
            
            return {
                "messages": [
                    AIMessage(content=f"✅ 成功爬取评论\n\n数据已存储，可供分析"))
                ],
                "task_comments": comments,
            }
        except Exception as e:
            return {
                "messages": [AIMessage(content=f"❌ 爬取失败: {e}")],
                "task_comments": "[]",
            }
    
    def analyzer_node(state: AgentState) -> Dict:
        """分析节点"""
        comments = state.get("task_comments", "[]")
        
        if not comments or comments == "[]":
            return {"messages": [AIMessage(content="⚠️ 没有评论数据可分析")]}
        
        try:
            analysis = analyze_douyin_comments(
                comments_json=comments,
                llm_provider=config.llm.provider.value,
            )
            
            return {
                "messages": [
                    AIMessage(content="✅ 评论分析完成")
                ],
                "task_analysis": analysis,
            }
        except Exception as e:
            return {
                "messages": [AIMessage(content=f"❌ 分析失败: {e}")],
                "task_analysis": "{}",
            }
    
    def notifier_node(state: AgentState) -> Dict:
        """通知节点"""
        analysis = state.get("task_analysis", "{}")
        
        if not analysis or analysis == "{}":
            return {"messages": [AIMessage(content="⚠️ 没有分析结果可发送")]}
        
        try:
            result = notify_feishu(summary_json=analysis)
            result_obj = json.loads(result)
            
            return {
                "messages": [
                    AIMessage(
                        content=f"📤 {'✅ 飞书通知已发送' if result_obj.get('success') else '❌ 发送失败'}"
                    )
                ],
                "notification_sent": result_obj.get("success", False),
            }
        except Exception as e:
            return {
                "messages": [AIMessage(content=f"❌ 发送失败: {e}")],
                "notification_sent": False,
            }
    
    # 构建图
    graph = AgentState.__annotations__
    
    from langgraph.graph import START, END, StateGraph
    
    wf = StateGraph(AgentState)
    
    wf.add_node("crawler", crawler_node)
    wf.add_node("analyzer", analyzer_node)
    wf.add_node("notifier", notifier_node)
    
    wf.add_edge(START, "crawler")
    wf.add_edge("crawler", "analyzer")
    wf.add_edge("analyzer", "notifier")
    wf.add_edge("notifier", END)
    
    return wf.compile()


def run_analysis(video_url: str):
    """运行分析"""
    
    print("🚀 启动抖音评论分析工作流...")
    print(f"📹 视频 URL: {video_url}\n")
    
    # 创建工作流
    workflow = create_douyin_workflow()
    
    # 初始状态
    initial_state: AgentState = {
        "messages": [
            SystemMessage(content="你是一个抖音评论分析助手"),
            HumanMessage(content=f"分析这个视频的评论：{video_url}"),
        ],
        "code_files": {},
        "iteration_count": 0,
        "review_status": "approved",
        "reviewer_feedback": "",
        "pending_action": "",
        "approval_status": "pending",
        "last_execution": "",
        "skill_result": 0,
        "skill_repair_attempted": False,
        "test_code": "",
        "test_status": "pending",
        "execution_plan": [],
        "orchestrator_status": "planning",
        "task_video_url": video_url,
    }
    
    # 执行工作流
    result = workflow.invoke(initial_state)
    
    # 打印结果
    print("\n" + "="*50)
    print("📋 执行结果")
    print("="*50)
    
    messages = result.get("messages", [])
    for msg in messages:
        if hasattr(msg, "content"):
            print(f"\n{msg.content}")
    
    print("\n" + "="*50)
    print("✅ 分析完成")
    print("="*50)
    
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抖音评论分析工作流")
    parser.add_argument(
        "--video-url",
        "-u",
        required=True,
        help="抖音视频链接",
    )
    
    args = parser.parse_args()
    run_analysis(args.video_url)
```

### 6.7 运行示例

配置好 LLM 和飞书后，运行以下命令：

```bash
# 设置环境变量
export OPENAI_API_KEY="your_api_key"
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_secret"

# 运行工作流
python examples/douyin_analysis_workflow.py -u "https://v.douyin.com/xxxxxx"
```

预期输出：

```
🚀 启动抖音评论分析工作流...
📹 视频 URL: https://v.douyin.com/xxxxxx

==================================================
📋 执行结果
================================================--

✅ 成功爬取评论

数据已存储，可供分析

✅ 评论分析完成

📤 飞书通知已发送

==================================================
✅ 分析完成
==================================================
```

飞书收到的消息卡片会显示：

- 📊 抖音评论分析报告
- 📈 统计概览：总评论数、积极/中性/消极比例
- 🏷️ 热门话题列表
- 💡 摘要和高赞评论

---

## 7. 自迭代开发指南

### 7.1 什么是自迭代

自迭代是本系统的核心创新特性之一。当代码执行失败时，系统不是简单地抛出错误，而是能够自动分析失败原因，尝试修复代码，然后重新执行。这个过程可以重复多次，直到成功或达到最大迭代次数。

这种能力对于自动化任务特别有价值。在传统的 CI/CD 流程中，构建失败需要人工介入修复；而自迭代系统可以自动处理常见的错误类型，如依赖缺失、API 变更、配置错误等。

### 7.2 自迭代工作流程

当系统检测到执行失败时，会进入以下流程：

**错误检测阶段**。Executor 捕获异常，分析错误类型。常见错误类型包括：语法错误（代码无法解析）、运行时错误（执行时异常）、依赖错误（缺少模块或包）、超时错误（执行时间过长）。

**根因分析阶段**。系统使用 LLM 分析错误信息和上下文，尝试确定失败的根本原因。例如，如果错误信息是 "ModuleNotFoundError: No module named 'requests'"，系统会识别这是依赖缺失问题。

**修复计划阶段**。基于根因分析，系统生成修复方案。对于依赖缺失，方案是安装缺失的包；对于 API 变更，方案是更新调用代码；对于逻辑错误，方案是修改代码逻辑。

**修复执行阶段**。Coder 角色根据修复方案更新代码或配置。这个过程可能涉及修改代码文件、创建requirements.txt、更新配置文件等。

**验证阶段**。修复后，系统重新执行代码，验证问题是否解决。如果仍然失败，会进入新一轮迭代；如果成功，继续执行后续流程。

### 7.3 自迭代配置

你可以通过环境变量配置自迭代行为：

```bash
# 启用自动修复
AGENT_RETRY_ON_ERROR=true

# 最大重试次数
AGENT_MAX_RETRIES=3

# 最大总迭代次数（包含代码生成迭代）
AGENT_MAX_ITERATIONS=10
```

在代码中配置更详细的参数：

```python
from examples.agent_system.config import get_config

config = get_config()
print(f"自动重试: {config.agent.retry_on_error}")
print(f"最大重试次数: {config.agent.max_retries}")
print(f"最大总迭代: {config.agent.max_iterations}")
```

### 7.4 自迭代技能开发

要实现某个功能的自迭代能力，你需要创建一个对应的技能模块，并实现错误处理逻辑。以下是一个网络请求技能的自迭代示例：

```python
# skills/web_fetcher.py
"""
网络请求技能

支持自动重试和常见错误修复
"""

import json
from typing import Optional
import httpx


class WebFetcherSkill:
    """网络请求技能"""
    
    # 常见错误及修复方案
    ERROR_REMEDIES = {
        "ModuleNotFoundError": {
            "pattern": r"No module named ['\"](\w+)['\"]",
            "fix": "请安装依赖包：pip install {module_name}",
            "action": "install",
        },
        "ConnectionError": {
            "pattern": r"(ConnectionError|Timeout|Failed to establish)",
            "fix": "网络连接失败，请检查网络或重试",
            "action": "retry",
        },
        "HTTPError": {
            "pattern": r"HTTP(?:Error|Status \d+)",
            "fix": "HTTP 请求失败，状态码：{status_code}",
            "action": "retry",
        },
    }
    
    def __init__(self, max_retries: int = 3, timeout: int = 30):
        """初始化
        
        Args:
            max_retries: 最大重试次数
            timeout: 请求超时（秒）
        """
        self.max_retries = max_retries
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)
    
    def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        body: Optional[dict] = None,
    ) -> dict:
        """发送请求，支持自动重试
        
        Args:
            url: 请求 URL
            method: HTTP 方法
            headers: 请求头
            body: 请求体
            
        Returns:
            包含状态、数据、错误的字典
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # 发送请求
                if method.upper() == "GET":
                    response = self.client.get(url, headers=headers)
                elif method.upper() == "POST":
                    response = self.client.post(
                        url, headers=headers, json=body
                    )
                else:
                    raise ValueError(f"不支持的 HTTP 方法: {method}")
                
                # 检查状态码
                response.raise_for_status()
                
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "data": response.json() if response.headers.get(
                        "content-type", ""
                    ).startswith("application/json") else response.text,
                    "attempt": attempt + 1,
                }
                
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                
                # 4xx 错误可能是请求问题，不重试
                if 400 <= e.response.status_code < 500:
                    break
                    
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = str(e)
                
            except Exception as e:
                last_error = str(e)
            
            # 重试前等待
            if attempt < self.max_retries:
                import time
                time.sleep(2 ** attempt)  # 指数退避
        
        return {
            "success": False,
            "error": last_error or "未知错误",
            "attempt": self.max_retries + 1,
        }


# 便捷函数
def fetch_url(
    url: str,
    method: str = "GET",
    headers: Optional[str] = None,
    body: Optional[str] = None,
) -> str:
    """获取 URL 内容（供 Agent 调用）"""
    
    fetcher = WebFetcherSkill()
    
    h = json.loads(headers) if headers else None
    b = json.loads(body) if body else None
    
    result = fetcher.fetch(url, method, h, b)
    
    return json.dumps(result, ensure_ascii=False, indent=2)
```

### 7.5 自迭代最佳实践

**设计可恢复的任务**。将大任务分解为小的、可独立执行的步骤。每个步骤都应该能够从中间状态恢复，这样即使某次迭代失败，也不会丢失所有进度。

**使用幂等操作**。确保技能函数可以安全地重复执行。例如，安装依赖的函数多次执行应该返回相同的结果，而不是重复安装。

**记录迭代历史**。系统会记录每次迭代的状态，你可以利用这个历史来优化未来的迭代。分析失败模式，改进错误处理逻辑。

**设置合理的超时**。对于网络请求等可能长时间运行的操作，设置合理的超时时间。避免因为单个操作卡住而影响整个流程。

---

## 8. 最佳实践

### 8.1 提示词优化

系统的各个角色都依赖 LLM 生成高质量的输出。优化提示词可以显著提升系统表现：

**提供清晰的上下文**。在任务描述中包含必要的背景信息，如代码库结构、已有实现、约束条件等。上下文越完整，生成的代码质量越高。

**使用结构化的输出格式**。要求 LLM 使用特定的格式输出，如 JSON、Markdown 代码块等。这使得解析和验证输出变得更加容易。

**设置明确的验收标准**。告诉 LLM 什么算"完成"，什么算"通过"。例如："函数应该正确处理边界情况，如空输入、None 值、超大数值等。"

**迭代反馈要具体**。Reviewer 给出的反馈应该具体且可操作。"代码质量差"没有帮助；"第 15 行的循环没有处理空列表情况，请添加边界检查"才有价值。

### 8.2 错误处理

健壮的错误处理是生产级系统的必要条件：

**捕获特定异常**。使用 try-except 捕获特定类型的异常，而不是使用空的 except 块。记录异常信息以便调试。

```python
try:
    result = skill.execute()
except ValueError as e:
    # 处理值错误，可能是输入参数问题
    logger.error(f"无效输入: {e}")
    return {"error": "invalid_input", "message": str(e)}
except RuntimeError as e:
    # 处理运行时错误，可能是外部服务问题
    logger.error(f"运行时错误: {e}")
    return {"error": "runtime_error", "message": str(e)}
```

**实现重试逻辑**。对于网络请求等可能临时失败的操作，实现指数退避重试。

**保留错误上下文**。当向上层报告错误时，包含足够的上下文信息，包括失败的操作、输入参数、之前的状态等。

### 8.3 性能优化

对于长时间运行的任务，性能优化可以显著减少执行时间和资源消耗：

**缓存重复调用**。如果某个技能可能被多次调用相同参数，考虑实现缓存机制。

**使用异步 IO**。对于网络请求，使用 httpx 或 aiohttp 的异步版本，可以显著提高吞吐量。

**限制输入大小**。LLM 有上下文长度限制，过大的输入会导致错误或性能下降。对输入进行截断或分块处理。

**并行执行独立任务**。如果工作流中有相互独立的任务，可以让它们并行执行。

### 8.4 安全考虑

在生产环境中使用本系统时，需要特别注意安全问题：

**沙箱执行**。永远不要在生产环境中直接执行未经审查的代码。使用 Docker 或其他沙箱技术隔离执行环境。

**敏感信息处理**。API Key、密码等敏感信息不要硬编码在代码中。使用环境变量或专门的密钥管理服务。

**输入验证**。对所有外部输入进行验证，防止注入攻击。特别是当这些输入会被传递给 LLM 或执行环境时。

**审计日志**。记录所有执行历史，包括谁在什么时候执行了什么操作。这对于调试和合规都很重要。

### 8.5 监控与可观测性

建立完善的监控体系，及时发现和解决问题：

**日志级别配置**。开发环境使用 DEBUG 级别，生产环境使用 INFO 或 WARNING 级别。关键操作使用 Structured Logging。

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "task_completed",
    task_id=task_id,
    duration_ms=duration,
    result_summary=summary,
)
```

**指标收集**。收集关键指标，如任务执行时间、成功率、各阶段耗时等。可以集成 Prometheus 或其他监控系统。

**链路追踪**。对于复杂的工作流，使用 LangSmith 或 Jaeger 进行分布式追踪，了解请求在各阶段的流转情况。

---

## 9. 常见问题

### Q1: 如何切换不同的 LLM 提供商？

系统支持多种 LLM 提供商，切换非常简单。只需要修改环境变量：

```bash
# 使用 OpenAI
export AGENT_LLM_PROVIDER=openai
export OPENAI_API_KEY="your_key"

# 使用 Anthropic
export AGENT_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY="your_key"

# 使用智谱 AI
export AGENT_LLM_PROVIDER=zhipu
export ZHIPU_API_KEY="your_key"

# 使用 MiniMax
export AGENT_LLM_PROVIDER=minimax
export MINIMAX_API_KEY="your_key"

# 使用通义千问
export AGENT_LLM_PROVIDER=qwen
export DASHSCOPE_API_KEY="your_key"
```

或者在代码中直接指定：

```python
from examples.agent_system.llm import get_llm

llm = get_llm(provider="anthropic", model="claude-3-5-sonnet")
```

### Q2: 飞书 Webhook 接收不到消息怎么办？

首先检查以下几点：

1. **URL 验证**。飞书会先发送 URL 验证请求，确认你的服务器能够响应。确保返回了正确的 challenge 参数。

2. **签名验证**。如果配置了 app_secret，确保正确验证签名。检查时间戳和签名计算是否正确。

3. **网络可达性**。确保你的服务器可以从公网访问。测试环境可以使用 ngrok 暴露本地服务：`ngrok http 8001`

4. **应用权限**。确认飞书应用有正确的权限配置，特别是消息发送和接收权限。

5. **日志检查**。查看服务器日志，确认是否收到了请求、处理是否成功。

### Q3: 如何调试工作流？

有几种调试方式可供选择：

**使用内置 fallback 模式**。如果不配置 LLM，系统会使用 deterministic fallback 模式，可以预测每一步的输出：

```python
from examples.agent_system.graph import build_graph, build_initial_state

# 不传入 llm，使用 fallback 模式
graph = build_graph()  # llm=None
result = graph.invoke(build_initial_state())
```

**启用详细日志**：

```bash
export AGENT_LOG_LEVEL=DEBUG
```

**检查 Checkpoint 状态**：

```python
from examples.agent_system.graph import build_graph
from langgraph.checkpoint import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("checkpoints.db")
graph = build_graph(checkpointer=checkpointer)

# 查看当前状态
state = graph.get_state(config)
print(state)
```

**逐步执行**。使用 interrupt_before 参数暂停在特定节点，手动检查状态后继续。

### Q4: 如何添加自定义角色？

继承 AgentRole 基类实现自定义角色：

```python
from examples.agent_system.roles.base import AgentRole, RoleResult
from langchain_core.messages import AIMessage

class MyCustomRole(AgentRole):
    def __init__(self, llm=None):
        super().__init__(
            name="my_custom",
            llm=llm,
            description="我的自定义角色描述",
        )
    
    def process(self, state) -> RoleResult:
        # 实现角色逻辑
        return RoleResult(
            message=AIMessage(content="处理完成"),
            state_updates={"key": "value"},
            metadata={},
        )
```

然后在图中使用：

```python
from examples.agent_system.graph import StateGraph

custom_role = MyCustomRole(llm=llm)

graph = StateGraph(AgentState)
graph.add_node("custom", custom_role.as_node())
```

### Q5: 工作流卡住不动怎么办？

工作流卡住通常有以下几个原因：

**等待审批**。检查是否在 Approver 节点等待人工审批。通过飞书或 Discord 发送审批命令继续执行。

**迭代次数耗尽**。检查 iteration_count 是否达到 AGENT_MAX_ITERATIONS。增加限制或优化代码质量。

**LLM 调用超时**。检查网络连接和 API 状态。增加 AGENT_TIMEOUT_SECONDS。

**死循环**。检查边的条件逻辑，确保有明确的退出条件。

### Q6: 如何在不同环境间迁移配置？

配置主要通过环境变量管理。推荐使用 `.env` 文件管理配置，添加到 .gitignore 避免泄露：

```bash
# .env 文件示例
AGENT_LLM_PROVIDER=openai
OPENAI_API_KEY=xxx
FEISHU_APP_ID=xxx
FEISHU_APP_SECRET=xxx
```

部署时，通过 CI/CD 或容器环境变量覆盖：

```yaml
# docker-compose.yml
services:
  agent:
    image: agent-system:latest
    environment:
      - AGENT_LLM_PROVIDER=${LLM_PROVIDER}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
```

### Q7: 如何贡献代码或报告问题？

1. Fork 项目仓库
2. 创建功能分支：`git checkout -b feature/my-feature`
3. 提交更改：`git commit -m "Add my feature"`
4. 推送到分支：`git push origin feature/my-feature`
5. 创建 Pull Request

报告问题时，请包含：
- 复现步骤
- 期望行为
- 实际行为
- 环境信息（Python 版本、依赖版本等）
- 错误日志

---

## 附录

### A. 环境变量速查表

| 变量 | 说明 | 默认值 | 必需 |
|------|------|--------|------|
| AGENT_LLM_PROVIDER | LLM 提供商 | openai | 否 |
| AGENT_LLM_MODEL | 模型名称 | 视提供商而定 | 否 |
| AGENT_LLM_TEMPERATURE | 生成温度 | 0.0 | 否 |
| OPENAI_API_KEY | OpenAI 密钥 | - | 当使用 OpenAI 时 |
| ANTHROPIC_API_KEY | Anthropic 密钥 | - | 当使用 Anthropic 时 |
| FEISHU_APP_ID | 飞书应用 ID | - | 当使用飞书时 |
| FEISHU_APP_SECRET | 飞书应用密钥 | - | 当使用飞书时 |
| AGENT_MAX_ITERATIONS | 最大迭代次数 | 10 | 否 |
| AGENT_TIMEOUT_SECONDS | 单步超时 | 300 | 否 |

### B. API 端点参考

**飞书网关**

| 端点 | 方法 | 功能 |
|------|------|------|
| /feishu/events | GET | URL 验证 |
| /feishu/events | POST | 事件接收 |

**审批 API（内部）**

| 端点 | 方法 | 功能 |
|------|------|------|
| /approval/request | POST | 创建审批请求 |
| /approval/resolve | POST | 处理审批结果 |

### C. 推荐阅读

- [LangGraph 官方文档](https://python.langchain.com/docs/langgraph)
- [LangChain 文档](https://python.langchain.com/docs)
- [飞书开放平台文档](https://open.feishu.cn/document/)
- [LangSmith 追踪配置](https://smith.langchain.com/)

---

*文档版本：1.0*
*最后更新：2026-02-08*
