# Agent System Common Workflows

## Workflow 1: Basic Coder-Reviewer Loop (Fallback Mode)

```python
from examples.agent_system.graph import build_graph, build_initial_state

# Create graph without LLM (fallback mode)
graph = build_graph()

# Initial state
state = build_initial_state()

# Execute the graph
# Result: code_files["app.py"] contains "return a + b"
result = graph.invoke(state)
```

**What happens:**
1. Coder generates code
2. Reviewer approves code
3. Loop ends on approval

---

## Workflow 2: LLM-Powered Code Generation

```python
from examples.agent_system.llm import get_llm
from examples.agent_system.graph import build_graph, build_initial_state

# Create graph with LLM
llm = get_llm(model="gpt-4")
graph = build_graph(llm=llm)

# Execute
state = build_initial_state()
result = graph.invoke(state)

# Result: LLM generates "def add(a, b): return a + b"
```

**What happens:**
1. CoderRole uses LLM to generate code
2. ReviewerRole uses LLM to review code
3. Both use prompt templates from prompts/

---

## Workflow 3: Orchestrator-Driven Multi-Agent Workflow

```python
from examples.agent_system.dynamic_graph import build_orchestrated_graph
from examples.agent_system.roles.registry import create_default_registry
from examples.agent_system.graph import build_initial_state

# Create registry with all roles
registry = create_default_registry()

# Build orchestrator-driven graph
graph = build_orchestrated_graph(registry=registry)

# Execute
state = build_initial_state()
result = graph.invoke(state)

# Orchestrator creates execution_plan:
# [
#   {"agent": "coder", "task": "Code", "status": "pending"},
#   {"agent": "reviewer", "task": "Review", "status": "pending"},
#   {"agent": "tester", "task": "Test", "status": "pending"},
# ]
```

**What happens:**
1. Orchestrator creates execution_plan with steps
2. OrchestratorRouter routes to each agent based on plan
3. Step tracking updates plan status as each agent completes

---

## Workflow 4: Human-in-the-Loop with Checkpointing

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from examples.agent_system.graph import build_checkpointed_graph

# Create checkpointer
saver = SqliteSaver.from_conn_string(":memory:")

# Build checkpointed graph
run = build_checkpointed_graph(
    saver,
    interrupt_before=["executor"],
)

# Execute - stops at executor for approval
result = run.graph.invoke(build_initial_state(), run.config)

print("Approval needed. State:")
print(run.graph.get_state(run.config))

# Approve and resume
run.graph.update_state(
    run.config,
    {"approval_status": "approved"}
)

# Continue to executor
final_result = run.graph.invoke(None, run.config)
```

**What happens:**
1. Graph executes until interrupt_before["executor"]
2. State is persisted to SQLite
3. Human reviews state and updates approval_status
4. Graph resumes from checkpoint

---

## Workflow 5: Docker Sandbox for Code Execution

```python
from examples.agent_system.sandbox import DockerExecutor
from examples.agent_system.graph import build_graph, build_initial_state

# Create graph
graph = build_graph()

# Create Docker executor
executor = DockerExecutor(
    image="python:3.11-slim",
    timeout_seconds=30,
    memory_limit="256m",
    cpu_limit="0.5",
)

# Execute code in sandbox
code = """
def add(a, b):
    return a + b

result = executor.execute(code)

print(f"Status: {result.status}")
print(f"Output: {result.stdout}")
print(f"Duration: {result.duration_ms}ms")
```

**What happens:**
1. Code runs in isolated Docker container
2. Timeout enforced (30s max)
3. Resources limited (256MB RAM, 0.5 CPU)
4. Output captured in ExecutionResult

---

## Workflow 6: Custom Role Registration

```python
from examples.agent_system.roles.base import AgentRole
from examples.agent_system.roles.registry import RoleRegistry
from langchain_core.messages import AIMessage
from examples.agent_system.graph import AgentState

# Create custom role
class CustomReviewer(AgentRole):
    def __init__(self, llm=None):
        super().__init__(name="custom_reviewer", llm=llm)

    def _process(self, state: AgentState) -> dict[str, Any]:
        # Custom review logic
        code = state.get("code_files", {}).get("app.py", "")
        if "TODO" in code:
            return {
                "review_status": "changes",
                "reviewer_feedback": "Remove TODOs before approval",
            }
        return {
            "review_status": "approved",
            "reviewer_feedback": "Code looks good!",
        }

# Register custom role
registry = RoleRegistry()
registry.register("custom_reviewer", CustomReviewer())

# Use in graph (need to provide this registry)
# graph = build_graph(registry=registry)
```

**What happens:**
1. Custom role registered with name "custom_reviewer"
2. RoleRegistry can get_or_create roles by name
3. Graph uses registered role instances

---

## Workflow 7: Inter-Agent Messaging

```python
from examples.agent_system.messaging import AgentMessage, MessageQueue, MessageType
from examples.agent_system.roles.registry import RoleRegistry

# Create message queue in state
queue = MessageQueue()

# Create a message
msg = AgentMessage(
    sender="coder",
    receiver="reviewer",
    content="Please review my code",
    message_type=MessageType.REQUEST,
    priority=MessagePriority.NORMAL,
)

# Enqueue message
queue.enqueue(msg)

# Dequeue next message (highest priority first)
next_msg = queue.dequeue()

# Filter messages by receiver
for_reviewer = queue.get_for_receiver("reviewer")
print(f"Messages for reviewer: {len(for_reviewer)}")
```

**What happens:**
1. Messages are typed (REQUEST, RESPONSE, NOTIFICATION, HANDOFF)
2. Priority queue orders messages (HIGH > NORMAL > LOW)
3. Messages can be filtered by receiver
4. Queue can be serialized/deserialized for state persistence

---

## Workflow 8: Dynamic Plan-Based Execution

```python
from examples.agent_system.dynamic_graph import build_orchestrated_graph
from examples.agent_system.roles.registry import RoleRegistry
from examples.agent_system.graph import AgentState

# Create registry
registry = RoleRegistry()

# Start with empty plan
initial_state: AgentState = {
    "messages": [],
    "code_files": {},
    "iteration_count": 0,
    "review_status": "changes",
    "reviewer_feedback": "",
    "pending_action": "",
    "approval_status": "pending",
    "last_execution": "",
    "skill_result": 0,
    "skill_repair_attempted": False,
    "test_code": "",
    "test_status": "pending",
    "execution_plan": [],  # Orchestrator creates this
    "orchestrator_status": "planning",
}

graph = build_orchestrated_graph(registry=registry)

# Execute
result = graph.invoke(initial_state)

# Check execution_plan
plan = result["execution_plan"]
print("Plan:")
for step in plan:
    print(f"  - {step['agent']}: {step['task']} [{step['status']}]")
```

**What happens:**
1. Orchestrator creates execution_plan when status is "planning"
2. OrchestratorRouter routes based on plan step statuses
3. Step tracking wrappers update plan as agents complete
4. If reviewer requests changes, coder step resets to "pending"

---

## Complete Example: Full Multi-Agent System

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from examples.agent_system.dynamic_graph import build_orchestrated_graph
from examples.agent_system.sandbox import DockerExecutor
from examples.agent_system.llm import get_llm
from examples.agent_system.roles.registry import create_default_registry

# Setup
llm = get_llm()
registry = create_default_registry()
saver = SqliteSaver.from_conn_string(":memory:")

# Build graph
graph = build_orchestrated_graph(
    llm=llm,
    registry=registry,
    checkpointer=saver,
    interrupt_before=["executor"],
)

# Create sandbox executor
executor = DockerExecutor(image="python:3.11-slim")

# Execute
state = build_initial_state()
config = {"configurable": {"thread_id": "agent-session-1"}}

# Step 1: Orchestrator creates plan
result = graph.invoke(state, config)

# Step 2: Human approves for execution
state = graph.get_state(config)
state["approval_status"] = "approved"
result = graph.invoke(state, config)

# Step 3: Execute code in sandbox
code = result["code_files"]["app.py"]
exec_result = executor.execute(code)

print(f"Execution: {exec_result.status}")
print(f"Output: {exec_result.stdout}")
```

**What happens:**
1. Orchestrator creates and manages execution_plan
2. Human-in-the-loop at executor for safety
3. Code runs in Docker sandbox
4. Full multi-agent workflow with LLM, checkpointing, and sandboxing
