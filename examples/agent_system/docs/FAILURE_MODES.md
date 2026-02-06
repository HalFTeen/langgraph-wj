# Failure Mode Runbook

## Common Issues and Solutions

### 1. GraphRecursionError

**Symptom:**
```
langgraph.errors.GraphRecursionError: Recursion limit of 10000 reached
```

**Cause:** Graph enters infinite loop, typically when:
- Reviewer continuously rejects code
- Orchestrator status not set to "executing"
- Router returns same agent repeatedly

**Solution:**
```python
# Increase limit if needed
graph.invoke(state, {"recursion_limit": 50000})

# Or fix root cause - check orchestrator_status
state["orchestrator_status"] = "executing"  # Not "planning"
```

### 2. LLM API Failures

**Symptom:**
```
openai.APIError: Connection error
```

**Solution:**
```python
# Use fallback mode (no LLM)
graph = build_graph(llm=None)  # Uses deterministic fallback

# Or implement retry logic
from tenacity import retry, stop_after_attempt
@retry(stop=stop_after_attempt(3))
def invoke_with_retry(graph, state):
    return graph.invoke(state)
```

### 3. Role Not Found

**Symptom:**
```
KeyError: 'No role registered with name: tester'
```

**Solution:**
```python
# Use create_default_registry() which includes all roles
registry = create_default_registry()

# Or register missing role
registry.register("tester", TesterRole())
```

### 4. Execution Timeout

**Symptom:**
```
ExecutionStatus.TIMEOUT
```

**Solution:**
```python
# Increase timeout
executor = LocalExecutor(timeout_seconds=60)

# Or use Docker with resource limits
executor = DockerExecutor(
    timeout_seconds=120,
    memory_limit="512m"
)
```

### 5. Docker Not Available

**Symptom:**
```
Docker is not installed or not in PATH
```

**Solution:**
```python
# Fall back to local executor
from examples.agent_system.sandbox import get_executor

executor = get_executor(use_docker=False)
```

### 6. State Schema Mismatch

**Symptom:**
```
TypeError: Missing required key in AgentState
```

**Solution:**
```python
# Use build_initial_state() for complete state
from examples.agent_system.graph import build_initial_state

state = build_initial_state()
# Includes all required fields with defaults
```

## Debugging Tips

### Enable Debug Mode
```python
result = graph.invoke(state, {"debug": True})
```

### Check Execution Plan
```python
print(state.get("execution_plan"))
print(state.get("orchestrator_status"))
```

### Validate Role Registration
```python
print(registry.list_available())
print(registry.has("coder"))
```
