# NAL Daemon 操作手册
NAL Daemon 是 NAL 系统的后台服务模式。启动后持续运行，通过飞书群聊或命令行接收任务，自动拆解、编码、测试、提交，全程可在飞书中查看进度和干预。
---
## 1. 前置条件
### 1.1 环境要求
| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 运行环境 |
| Claude Code CLI | 最新 | Agent 执行引擎 |
| Git | 2.x | 代码管理 |
### 1.2 飞书配置
需要 3 个环境变量（从飞书开发者后台获取）：
```bash
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_app_secret"
export FEISHU_CHAT_ID="your_chat_id"
```
获取方式：
1. 登录 [飞书开发者后台](https://open.feishu.cn)
2. 创建企业自建应用 → 获取 `APP_ID` 和 `APP_SECRET`
3. 开通权限：`im:message`、`im:message:readonly`
4. 将机器人添加到目标群聊
5. 通过 API 获取 `CHAT_ID`（群聊 ID）
### 1.3 目标项目仓库
Daemon 操作的目标必须是一个 git 仓库：
```bash
# 新建项目
mkdir /path/to/my-project && cd /path/to/my-project
git init && git commit --allow-empty -m "init"
# 或使用已有项目
cd /path/to/existing-project
git status  # 确认是 git 仓库
```
**重要**：Daemon 只在本地操作，不会 push 到任何远程仓库。
---
## 2. 启动服务
### 2.1 前台运行（开发调试，推荐首次使用）
```bash
cd /path/to/langgraph-wj
FEISHU_APP_ID=cli_a90035a79438dcef \
FEISHU_APP_SECRET=4HS2N9Akkm6PPXJgeomARfW0JZxtcBOe \
FEISHU_CHAT_ID=oc_98ac84efa01320efc96fc4c06fc1b5a9 \
python -m examples.agent_system.run_nal_daemon \
    --repo /path/to/my-project
```
启动成功标志：
```
10:20:06 [nal.daemon] INFO: NAL Daemon started. Waiting for tasks...
```
飞书群收到消息：`🤖 NAL Daemon 已启动`
按 `Ctrl+C` 停止。
### 2.2 后台运行（生产使用）
```bash
cd /path/to/langgraph-wj
nohup env \
    FEISHU_APP_ID=cli_a90035a79438dcef \
    FEISHU_APP_SECRET=4HS2N9Akkm6PPXJgeomARfW0JZxtcBOe \
    FEISHU_CHAT_ID=oc_98ac84efa01320efc96fc4c06fc1b5a9 \
    python -m examples.agent_system.run_nal_daemon \
        --repo /path/to/my-project \
    > /tmp/nal-daemon.log 2>&1 &
echo "Daemon PID: $!"
```
查看日志：
```bash
tail -f /tmp/nal-daemon.log
```
### 2.3 启动参数
| 参数 | 说明 | 示例 |
|------|------|------|
| `--repo` | 默认目标仓库路径（必须） | `--repo /tmp/my-project` |
| `--remote` | Git 远程地址（可选，daemon模式不push） | `--remote git@server:repo.git` |
| `--engine` | Agent 引擎（默认 claude-code） | `--engine fallback` |
| `--task` | 启动时立即执行一个任务 | `--task "创建hello world"` |
### 2.4 启动时提交任务
```bash
python -m examples.agent_system.run_nal_daemon \
    --repo /path/to/project \
    --task "创建一个Python计算器，支持加减乘除"
```
任务执行完毕后，Daemon 继续待命等待飞书指令。
---
## 3. 飞书入口（主要交互方式）
所有命令需要 **@机器人** 触发，普通群消息不会被处理。
### 3.1 提交新任务
在飞书群中发送：
```
@bot /new 创建一个TODO应用，支持增删改查
```
指定仓库：
```
@bot /new --repo /path/to/another-project 创建一个REST API服务
```
机器人回复：
```
📋 收到任务
创建一个TODO应用，支持增删改查
正在拆解...
📝 任务拆解完成（6 个子任务）
  1. 创建pytest测试文件
  2. 创建Todo数据模型
  3. 添加增加功能
  4. 添加删除功能
  5. 添加修改功能
  6. 添加查询功能
请 @bot 确认 或提出修改意见。
（10分钟未回复将自动按当前方案执行）
```
### 3.2 确认任务
```
@bot 确认
```
或者：
```
@bot ok
@bot 好的
@bot 通过
@bot 继续
```
### 3.3 修改任务（自然语言反馈）
收到任务拆解后，直接 @机器人 说修改意见：
```
@bot 把TODO模型改为SQLite持久化，不要用内存存储，再加一个按优先级排序的功能
```
机器人会根据反馈重新拆解，再次发送给你确认。可以反复修改，直到满意后回复"确认"。
**10 分钟不回复会自动按当前方案执行。**
### 3.4 执行中干预
任务执行过程中，可以 @机器人 发送反馈：
```
@bot 函数命名要用驼峰式而不是下划线
```
机器人回复：
```
📝 收到反馈，将在后续任务中应用。
> 函数命名要用驼峰式而不是下划线
```
反馈会注入到后续任务的 Agent prompt 中。
### 3.5 查看状态
```
@bot /status
```
空闲时回复：
```
💤 空闲中
当前没有正在执行的任务。
发送 @bot /new 任务描述 提交新任务。
```
执行中回复：
```
🔄 执行中...
直接 @bot 回复可修改后续任务行为。
```
### 3.6 查看帮助
```
@bot /help
```
### 3.7 停止服务
```
@bot /stop
```
机器人回复 `🛑 Daemon 已停止`，进程退出。
### 3.8 命令速查表
| 命令 | 说明 | 示例 |
|------|------|------|
| `/new <描述>` | 提交新任务 | `@bot /new 创建登录模块` |
| `/new --repo /path <描述>` | 指定仓库提交任务 | `@bot /new --repo /tmp/api 创建REST API` |
| `/status` | 查看当前状态 | `@bot /status` |
| `/help` | 查看帮助 | `@bot /help` |
| `/stop` | 停止 Daemon | `@bot /stop` |
| 自然语言 | 修改反馈 | `@bot 把颜色改成蓝色` |
| 确认词 | 确认并执行 | `@bot 确认` |
---
## 4. 命令行入口
### 4.1 CLI 直接提交任务
Daemon 运行中，也可以通过命令行提交任务：
```bash
# 方式1：启动 daemon 时带 --task
python -m examples.agent_system.run_nal_daemon \
    --repo /tmp/project \
    --task "你的需求描述"
# 方式2：使用原始 run_nal.py（一次性执行，非 daemon 模式）
python -m examples.agent_system.run_nal \
    --repo /tmp/project \
    --task "你的需求描述"
```
### 4.2 run_nal.py 与 run_nal_daemon.py 对比
| 特性 | run_nal.py | run_nal_daemon.py |
|------|-----------|-------------------|
| 运行模式 | 一次性执行 | 后台常驻 |
| 飞书交互 | 仅通知 | 双向交互（命令+反馈） |
| 人工确认 | 无 | 有（10分钟超时自动继续） |
| 任务来源 | CLI `--task` | CLI + 飞书 `/new` |
| Git push | 可配置 | 禁止 |
| 多任务 | 不支持 | 排队执行 |
| 进程管理 | 执行完退出 | 持续运行 |
---
## 5. 完整交互流程示例
### 示例：从零创建一个 Python Web API
**第一步：启动 Daemon**
```bash
mkdir /tmp/web-api && cd /tmp/web-api
git init && git commit --allow-empty -m "init" && git branch -m master main
nohup env FEISHU_APP_ID=xxx FEISHU_APP_SECRET=xxx FEISHU_CHAT_ID=xxx \
    python -m examples.agent_system.run_nal_daemon \
        --repo /tmp/web-api > /tmp/nal-daemon.log 2>&1 &
```
**第二步：在飞书提交任务**
```
@bot /new 创建一个Flask REST API，包含用户CRUD接口，使用SQLite数据库
```
**第三步：收到任务拆解，提出修改**
```
@bot 加上JWT认证，所有接口需要登录后才能访问
```
**第四步：确认执行**
```
@bot 确认
```
**第五步：等待执行，观察飞书通知**
飞书群会收到每个子任务的进度通知：
- 📋 任务分发：[step-1] 创建数据库模型
- ✅ 任务完成：[step-1] 创建数据库模型 Commit: abc123
- 📋 任务分发：[step-2] 创建用户CRUD接口
- ...
**第六步：执行中追加要求（可选）**
```
@bot 密码要用bcrypt加密，不要明文存储
```
**第七步：完成**
飞书收到：`🏁 Pipeline 执行完成`
查看结果：
```bash
cd /tmp/web-api
ls          # 查看生成的文件
git log     # 查看提交历史
pytest      # 运行测试
```
**第八步：提交下一个任务（Daemon 继续待命）**
```
@bot /new 给API加上Swagger文档
```
---
## 6. 监控与运维
### 6.1 查看日志
```bash
# 实时日志
tail -f /tmp/nal-daemon.log
# 最近 50 行
tail -50 /tmp/nal-daemon.log
# 搜索错误
grep "ERROR" /tmp/nal-daemon.log
```
### 6.2 检查进程状态
```bash
ps aux | grep run_nal_daemon | grep -v grep
```
### 6.3 强制停止
```bash
# 方式1：飞书
@bot /stop
# 方式2：命令行
kill $(ps aux | grep run_nal_daemon | grep -v grep | awk '{print $2}')
```
### 6.4 重启
```bash
# 停止
kill $(ps aux | grep run_nal_daemon | grep -v grep | awk '{print $2}')
# 重启
nohup env FEISHU_APP_ID=xxx ... python -m examples.agent_system.run_nal_daemon \
    --repo /path/to/project > /tmp/nal-daemon.log 2>&1 &
```
### 6.5 查看项目产出
```bash
cd /path/to/project
git log --oneline         # 查看所有提交
git diff HEAD~3           # 查看最近3次提交的改动
pytest                    # 运行测试
```
---
## 7. 注意事项
### 7.1 安全
- Daemon 模式**严禁 git push**，所有代码仅保留在本地
- 确认产出质量后，由人工决定是否 push 到远程仓库
- 飞书 App Secret 不要提交到代码仓库
### 7.2 资源
- 每个任务调用 Claude Code CLI，会消耗 API 额度
- 复杂任务（10+ 子任务）可能运行较长时间
- 建议在稳定网络环境下运行
### 7.3 局限
- 当前为单任务串行执行，不支持并行
- 不支持 GPU/硬件依赖的项目验证
- Feishu 消息轮询间隔 3 秒，响应有轻微延迟
### 7.4 最佳实践
1. **需求描述尽量具体**：越具体，Planner 拆解越准确
2. **先确认再执行**：审查任务拆解，避免方向偏差
3. **小步迭代**：一次提交一个功能需求，而不是整个系统
4. **查看 git log**：每次执行完检查提交历史和代码质量
5. **测试先行**：NAL 自动生成测试并验证通过后才提交

