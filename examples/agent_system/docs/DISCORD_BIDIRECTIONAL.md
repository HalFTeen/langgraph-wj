# Discord Bidirectional Communication Plan

## Current Architecture

### Components
```
discord_bot.py (Discord client)
├── DiscordGateway (HTTP API to Discord)
└── Command parser (approve/deny)
    └── Post approval to Discord

app.py (FastAPI Gateway)
├── POST /approval/request → ApprovalStore
├── POST /approval/resolve → DiscordGateway
└── POST /graph/update-state → LangGraph
```

### Current Limitations
1. **Single-direction flow**: Discord → LangGraph update_state only
2. **No progress feedback**: Agent cannot send status updates to Discord
3. **No task dispatching**: Cannot queue tasks via Discord

---

## Proposed Features

### Feature 1: Progress Report to Discord

**Goal**: Agent sends execution progress to Discord for real-time monitoring

**Flow:**
```
Agent State → Discord Gateway → Discord Message
```

**Message Format:**
```
🔄 [Agent] Executing step X of Y
📊 Code generated successfully
✅ Review approved by ReviewerAgent
❌ Reviewer requested changes
📝 Tests passed: 5/5
```

**Implementation:**
```python
# In agent roles (coder.py, reviewer.py, etc.)
def update_progress(status_message: str) -> dict[str, Any]:
    return {
        "discord_status": status_message,
        # Mark that this should be sent to Discord
    }

# In gateway/app.py
def send_progress_notification(status_message: str):
    discord = _get_discord_gateway()
    discord.post_message(channel_id, status_message)
```

### Feature 2: Agent-to-User Messaging

**Goal**: Agent can send questions/confirmations to user via Discord

**Flow:**
```
Agent → Discord Gateway → Discord Message
```

**Message Format:**
```
❓ [Question from CoderAgent]
I'm about to refactor the file structure. This may affect readability.
Should I proceed?

Options:
1. ✅ Proceed
2. ⏸️ Use simpler approach
3. ❓ Let me review first
```

**Implementation:**
```python
# New Discord command
class DiscordCommand(Enum):
    ASK_USER = "ask"
    CONFIRM_ACTION = "confirm"
    SEND_STATUS = "status"

# In discord_bot.py
def _parse_command(content: str) -> tuple[str, str, str]:
    # Parse: ask|confirm|status <message>
    return command, param, message

# In gateway/app.py
def handle_agent_message(command: DiscordCommand, param: str, message: str):
    if command == DiscordCommand.ASK_USER:
        # Store as pending user question
        user_questions.store(question_id=gen_id(), question=message)
    elif command == DiscordCommand.CONFIRM_ACTION:
        # Resume from checkpoint with action
        approve_action(message_id, action=param)
```

### Feature 3: Task Dispatch via Discord

**Goal**: User can assign new task via Discord command

**Flow:**
```
Discord Message → Discord Gateway → Task Queue → Agent picks up task
```

**Command Format:**
```
/task add "Implement new authentication module"
  - Priority: high
  - Assigned: coder
```

**Implementation:**
```python
# New command in discord_bot.py
def handle_task_command(command: str, task_data: dict):
    task = task_store.create(task_data)
    # Add to message queue for agent
    message_queue.enqueue(AgentMessage(
        sender="user",
        receiver="orchestrator",
        message_type=MessageType.REQUEST,
        content=task_data,
    ))

# In agent_state (extend)
class AgentState(TypedDict):
    # Add new fields
    task_queue: list[dict]  # Pending tasks
    active_task: dict | None  # Current task
```

---

## Integration Points

### 1. Progress Hook
```python
# In roles/base.py
class AgentRole(ABC):
    def on_progress(self, progress: str) -> None:
        """Called at key points. Override in subclasses."""
        pass

# In coder.py
def process(self, state: AgentState) -> RoleResult:
    # Before coding
    if self.llm:
        self.on_progress("Starting code generation...")

    # After coding
    self.on_progress(f"Generated {file_count} files")
```

### 2. Message Gateway Extension
```python
# In gateway/app.py
@app.post("/agent/message")
async def agent_message(request: AgentMessageRequest):
    # Agent sends message to user
    discord.post_message(request.channel_id, request.message)
    return {"status": "sent"}
```

### 3. Task Management
```python
# New file: agent_system/tasks/task_queue.py
class TaskQueue:
    def enqueue(self, task: dict) -> str:
        task_id = gen_id()
        self.tasks[task_id] = task
        return task_id

    def dequeue(self, agent_name: str) -> dict | None:
        # Get next task for agent
        for task_id, task in self.tasks.items():
            if task["assigned_to"] == agent_name and not task["picked_up"]:
                task["picked_up"] = True
                return task
        return None
```

---

## Testing Strategy

### Test 1: Progress Notifications
```python
def test_progress_sends_to_discord():
    # Mock DiscordGateway
    mock_discord = Mock(spec=DiscordGateway)
    # Agent sends progress
    result = coder_node(test_state)
    # Verify progress was sent
    mock_discord.post_message.assert_called_once()
    mock_discord.post_message.assert_called_with(
        channel_id="test-channel",
        message=ANY
    )
```

### Test 2: Agent Questions
```python
def test_agent_question_pauses_execution():
    # Agent asks question
    state = {"discord_command": "ask User to proceed"}
    # Verify execution pauses
    result = graph.invoke(state, config)
    # Should trigger interrupt
    assert run.config.get("next") == "user_response_needed"
```

### Test 3: Task Assignment
```python
def test_task_dispatched_to_agent():
    # User creates task via Discord
    payload = {
        "command": "task",
        "action": "add",
        "task_data": {"description": "Fix auth bug", "priority": "high"}
    }
    response = client.post("/agent/message", json=payload)
    # Verify task was queued
    task = task_store.get(response.task_id)
    assert task["assigned_to"] == "coder"
```

---

## Migration Plan

### Phase 1: Message Queue Extension
1. Extend `ApprovalStore` to also store agent→user messages
2. Add new Gateway endpoint `/agent/message`

### Phase 2: Progress Hooks
1. Add `on_progress()` to `AgentRole` base class
2. Call from each role at key execution points

### Phase 3: Task System
1. Create `TaskQueue` class
2. Extend `AgentState` with `task_queue`, `active_task`
3. Add Discord command handler for task dispatch

### Phase 4: Testing
1. Unit tests for progress notifications
2. Integration tests for agent questions
3. End-to-end tests for task lifecycle

---

## OpenAI Reference

Search Discord bot implementations that support:
- Rich embeds with file attachments
- Thread management for multi-part workflows
- Component-based message construction
- Webhook-driven event processing

Use librarian agent to find production Discord bot examples.
