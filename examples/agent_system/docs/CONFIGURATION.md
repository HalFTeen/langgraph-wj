# Agent System Configuration Guide

## Quick Start

```python
from examples.agent_system.graph import build_graph, build_initial_state
from examples.agent_system.roles.registry import create_default_registry

# Basic usage (fallback mode, no LLM)
graph = build_graph()
result = graph.invoke(build_initial_state())

# With role registry
registry = create_default_registry()
graph = build_graph(registry=registry)
```

## LLM Configuration

### Environment Variables

```bash
export OPENAI_API_KEY="sk-..."
export AGENT_LLM_MODEL="gpt-4"
export AGENT_LLM_TEMPERATURE="0.7"
```

### Programmatic Configuration

```python
from examples.agent_system.llm import get_llm
from examples.agent_system.graph import build_graph

llm = get_llm(model="gpt-4", temperature=0.7)
graph = build_graph(llm=llm)
```

## Role Registry

### Default Roles

```python
from examples.agent_system.roles.registry import create_default_registry

registry = create_default_registry()
# Includes: coder, reviewer, tester, orchestrator
```

### Custom Role Registration

```python
from examples.agent_system.roles.registry import RoleRegistry
from examples.agent_system.roles.coder import CoderRole

registry = RoleRegistry()
registry.register("coder", CoderRole(llm=my_llm))
registry.register_factory("reviewer", lambda: ReviewerRole())
```

## Execution Modes

### Static Graph (Fixed Flow)

```python
from examples.agent_system.graph import build_graph

# coder -> reviewer -> tester -> approver -> executor
graph = build_graph(registry=registry)
```

### Dynamic Graph (Orchestrator-Driven)

```python
from examples.agent_system.dynamic_graph import build_orchestrated_graph

# orchestrator decides execution plan dynamically
graph = build_orchestrated_graph(registry=registry)
```

## Sandbox Execution

### Local Execution (Testing)

```python
from examples.agent_system.sandbox import LocalExecutor

executor = LocalExecutor(timeout_seconds=30)
result = executor.execute("print('Hello')")
```

### Docker Execution (Production)

```python
from examples.agent_system.sandbox import DockerExecutor

executor = DockerExecutor(
    image="python:3.11-slim",
    timeout_seconds=30,
    memory_limit="256m",
    cpu_limit="0.5"
)
result = executor.execute(code)
```

## Human-in-the-Loop

### Checkpointed Execution

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from examples.agent_system.graph import build_checkpointed_graph

with SqliteSaver.from_conn_string(":memory:") as saver:
    run = build_checkpointed_graph(
        saver,
        interrupt_before=["executor"],
        llm=llm
    )
    
    # First run - stops at executor
    result = run.graph.invoke(initial_state, run.config)
    
    # Approve and continue
    run.graph.update_state(
        run.config,
        {"approval_status": "approved"}
    )
    result = run.graph.invoke(None, run.config)
```

## State Schema

```python
class AgentState(TypedDict):
    messages: list[BaseMessage]
    code_files: dict[str, str]
    iteration_count: int
    review_status: Literal["approved", "changes"]
    reviewer_feedback: str
    pending_action: str
    approval_status: Literal["pending", "approved", "denied"]
    last_execution: str
    skill_result: int
    skill_repair_attempted: bool
    test_code: str
    test_status: Literal["pending", "generated", "passed", "failed", "skipped"]
    execution_plan: list[dict]
    orchestrator_status: Literal["planning", "executing", "completed"]
```
