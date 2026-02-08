# 飞书 + Discord 集成使用文档

本文档详细介绍如何配置和使用 Agent System 的人机协作功能，支持通过飞书 (Feishu/Lark) 和 Discord 两个平台进行审批交互。

---

## 目录

1. [功能概述](#功能概述)
2. [飞书配置指南](#飞书配置指南)
3. [Discord 配置指南](#discord-配置指南)
4. [启动服务](#启动服务)
5. [使用说明](#使用说明)
6. [API 参考](#api-参考)
7. [常见问题](#常见问题)

---

## 功能概述

Agent System 支持两种即时通讯平台的人机协作审批：

| 特性 | 飞书 | Discord |
|------|------|---------|
| 审批请求卡片 | ✅ 交互式卡片 | ✅ Discord Embed |
| 审批命令 | `/approve`, `/deny`, `/status` | `!approve`, `!deny`, `!status` |
| 消息类型 | 文本 + 富文本卡片 | 文本 + Embed |
| 事件接收 | Webhook | Bot API |
| 配置复杂度 | 中等 | 简单 |

---

## 飞书配置指南

### 步骤 1：创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn)
2. 点击「创建企业自建应用」
3. 填写应用名称（如 `Agent审批助手`）和描述
4. 点击「创建应用」

### 步骤 2：获取凭证

在应用详情页的「凭证与基础信息」中获取：

- **App ID**: 形如 `cli_xxxxxxxxxxxxx`
- **App Secret**: 点击「获取」按钮获取

### 步骤 3：配置权限

在「权限管理」中申请以下权限：

| 权限 | 用途 |
|------|------|
| `im:message` | 发送和接收消息 |
| `im:message.p2p_msg:readonly` | 读取私聊消息 |
| `im:message.group_at_msg:readonly` | 接收群 @机器人消息 |
| `im:message:send_as_bot` | 以机器人身份发送消息 |

> **注意**: 部分敏感权限需要申请企业审核。

### 步骤 4：配置事件订阅

在「事件与回调」中配置：

1. **事件配置方式**: 选择「使用长连接接收事件」（推荐）
2. **添加事件订阅**:
   - `im.message.receive_v1` - 接收消息（必需）
   - `im.message.message_read_v1` - 消息已读回执（可选）
   - `im.chat.member.bot.added_v1` - 机器人进群（可选）
   - `im.chat.member.bot.deleted_v1` - 机器人被移出群（可选）

3. **回调 URL**: 配置你的服务器地址
   - 格式: `https://your-domain.com/feishu/events`
   - 需要公网可访问

### 步骤 5：发布应用

在「版本管理与发布」中：

1. 点击「创建版本」
2. 填写版本号和描述
3. 选择发布范围（测试人员/全体成员）
4. 点击「申请发布」

### 步骤 6：配置环境变量

```bash
# 飞书凭证
export FEISHU_APP_ID="cli_xxxxxxxxxxxxx"
export FEISHU_APP_SECRET="your_app_secret"

# 飞书域名 (feishu=国内, lark=国际)
export FEISHU_DOMAIN="feishu"

# Webhook 路径 (默认 /feishu/events)
export FEISHU_WEBHOOK_PATH="/feishu/events"

# 启用飞书 (默认 false)
export FEISHU_ENABLED="true"

# Webhook 服务器端口
export FEISHU_PORT="8001"
```

### 步骤 7：测试飞书机器人

1. 在飞书搜索框中搜索你的机器人名称
2. 发起私聊
3. 发送 `/help` 测试是否正常工作

---

## Discord 配置指南

### 步骤 1：创建 Discord 应用

1. 访问 [Discord Developer Portal](https://discord.com/developers/applications)
2. 点击「New Application」
3. 填写应用名称

### 步骤 2：创建 Bot

1. 在「Bot」标签页点击「Add Bot」
2. 确认添加
3. 复制 **Bot Token**（需要妥善保管）

### 步骤 3：配置 Bot 权限

在「OAuth2」→「URL Generator」中：

1. 选择权限:
   - `Send Messages` - 发送消息
   - `Embed Links` - 发送嵌入链接
   - `Use Slash Commands` - 使用斜杠命令

2. 复制生成的 OAuth2 URL
3. 在浏览器中授权并添加到服务器

### 步骤 4：配置 Intent

在「Bot」标签页中：

1. 启用 **MESSAGE CONTENT INTENT**（必需）
2. 启用 **SERVER MEMBERS INTENT**（可选，用于获取用户信息）

### 步骤 5：配置环境变量

```bash
# Discord Bot Token
export DISCORD_BOT_TOKEN="your_bot_token"

# 服务器 ID (Server ID)
export DISCORD_GUILD_ID="1234567890"

# 审批频道 ID
export DISCORD_CHANNEL_ID="0987654321"

# Webhook URL (可选，用于审批通知)
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/xxx"

# 启用 Discord (默认 false)
export DISCORD_ENABLED="true"
```

### 步骤 6：测试 Bot

1. 在 Discord 服务器中看到 Bot 在线
2. 发送 `/help` 测试是否正常工作

---

## 启动服务

### 方式 1：独立启动飞书服务

```bash
# 启动飞书 Webhook 服务
uvicorn examples.agent_system.gateway.feishu_bot:app --host 0.0.0.0 --port 8001 --reload
```

### 方式 2：独立启动 Discord 服务

```bash
# 启动 Discord Bot
python examples/agent_system/gateway/run_discord_bot.py
```

### 方式 3：同时启动所有服务

使用 Docker Compose 或手动启动多个进程：

```bash
# 终端 1: 飞书 Webhook
uvicorn examples.agent_system.gateway.feishu_bot:app --host 0.0.0.0 --port 8001

# 终端 2: FastAPI 主服务
uvicorn examples.agent_system.gateway.app:app --reload

# 终端 3: Discord Bot
python examples/agent_system/gateway/run_discord_bot.py
```

---

## 使用说明

### 审批流程

当 Agent 执行需要审批的操作时（如执行代码、修改文件），系统会：

1. **暂停执行**并创建检查点
2. 发送审批请求到配置的通讯平台
3. 等待用户响应

### 飞书命令

在飞书中发送以下命令：

| 命令 | 说明 |
|------|------|
| `/request <描述>` | 创建审批请求 |
| `/approve [request_id]` | 批准请求（省略则批准最新的） |
| `/deny [request_id]` | 拒绝请求（省略则拒绝最新的） |
| `/status` | 查看待审批请求 |
| `/help` | 显示帮助信息 |

### Discord 命令

在 Discord 中发送以下命令：

| 命令 | 说明 |
|------|------|
| `!request <描述>` | 创建审批请求 |
| `!approve [request_id]` | 批准请求 |
| `!deny [request_id]` | 拒绝请求 |
| `!status` | 查看待审批请求 |
| `!help` | 显示帮助信息 |

### 审批卡片示例

审批请求会发送交互式卡片，包含：

- 请求标题和描述
- approve/deny 按钮（飞书）
- 审批状态追踪

---

## API 参考

### 飞书 API 客户端

```python
from examples.agent_system.gateway.feishu_client import FeishuClient, FeishuConfig

# 创建客户端
config = FeishuConfig.from_env()
client = FeishuClient(config=config)

# 发送文本消息
client.send_text_message("user_open_id", "Hello!")

# 发送审批卡片
client.send_approval_card(
    receive_id="user_open_id",
    title="代码审查请求",
    description="请审查生成的代码",
    approve_url="https://.../approve/xxx",
    deny_url="https://.../deny/xxx",
)
```

### 审批存储

```python
from examples.agent_system.gateway.feishu_bot import approval_store

# 创建审批
approval_store.create_approval(
    request_id="req_123",
    thread_id="thread_456",
    user_id="user_789",
    chat_id="chat_abc",
    title="Test",
    description="Test description",
    approve_url="/approve/123",
    deny_url="/deny/123",
)

# 获取审批
approval = approval_store.get_approval("req_123")

# 更新状态
approval_store.update_status("req_123", "approved")
```

### Webhook 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/feishu/events` | GET | 飞书 URL 验证 |
| `/feishu/events` | POST | 飞书事件接收 |

---

## 常见问题

### 飞书收不到消息

检查以下配置：

1. ✅ 是否配置了**事件订阅**？
2. ✅ 事件配置方式是否选择**长连接**？
3. ✅ 是否添加了 `im.message.receive_v1` 事件？
4. ✅ 相关权限是否已审核通过？
5. ✅ 回调 URL 是否公网可访问？

### Discord Bot 无响应

1. 检查 Bot Token 是否正确
2. 确认 Bot 已在服务器中
3. 检查 MESSAGE CONTENT INTENT 是否启用
4. 查看控制台错误日志

### 审批按钮点击无效

飞书卡片按钮需要配置 URL：
- 确保 URL 可公网访问
- 按钮点击后会跳转到指定 URL
- 需要在服务端处理审批逻辑

### 如何清除历史会话

当前版本暂不支持自动清除。可以重启服务或清除数据库。

### 多平台同时使用

Agent System 支持同时配置飞书和 Discord：

```bash
# 配置两个平台
export FEISHU_ENABLED="true"
export FEISHU_APP_ID="..."
export DISCORD_ENABLED="true"
export DISCORD_BOT_TOKEN="..."
```

审批请求会同时发送到两个平台。

---

## 架构说明

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent System                             │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ 飞书 Gateway │  │ Discord Bot  │  │  Main App    │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         ▼                 ▼                 ▼               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Checkpoint + State Store                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              LangGraph Agent Execution                │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 下一步

- [查看开发文档](../DEVELOPMENT.md)
- [查看示例代码](../EXAMPLES.md)
- [查看故障排除指南](../FAILURE_MODES.md)
