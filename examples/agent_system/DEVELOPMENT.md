# Agent System Development Notes

Last updated: 2026-02-03

## Scope

Build a standalone example that demonstrates a multi-role, self-iterating agent system with
human-in-the-loop control and remote intervention via Discord. The system is intentionally
minimal but structured for extension.

## Design goals

- Clear separation of roles: Orchestrator, Coder, Reviewer, Tester, Executor.
- Deterministic loop behavior: reviewer gate controls Coder retry; tester gate controls retry.
- Interruptible high-risk actions with checkpointing and state persistence.
- Remote approval via Discord as the only initial channel.
- Self-iterating toolchain: agent can update skills and hot-reload them.

## System overview

- LangGraph StateGraph with conditional edges for approval and retry loops.
- Checkpointing via SqliteSaver for pause/resume and state inspection.
- Gateway service (FastAPI) exposes:
  - /approval/request to create an approval record
  - /approval/resolve to approve or deny and call update_state
- Discord bot posts approval requests and receives approvals/denials.
- Executor runs code in a sandbox (Docker/E2B hook).

## State model (proposed)

```
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    code_files: dict
    iteration_count: int
    approval: dict
    last_result: dict
```

## Iteration logic (proposed)

- Coder writes code into code_files, increments iteration_count.
- Reviewer inspects code_files and sets approval.status = "approved" or "changes".
- If changes: edge to Coder. If approved: edge to Tester.
- Tester executes tests via Executor. On failure -> Coder with feedback.
- On pass -> END.

## Human-in-the-loop (proposed)

- Gate any action labeled "execute_code" with interrupt_before.
- When interrupted, persist checkpoint.
- Gateway receives request, sends to Discord, awaits response.
- On approval/deny, Gateway calls update_state and resumes graph.

## Discord gateway (current)

- FastAPI endpoints:
  - /approval/request: create approval record and notify Discord.
  - /approval/resolve: resolve record and update graph state.
- Discord bot runner listens for approve/deny commands and calls resolve.

## Self-iterating skills (proposed)

- skills/ directory stores Python modules with tool wrappers.
- Coding_Agent modifies skills modules when errors recur.
- Reload_Skill imports updated module and refreshes the tool registry.

## Self-iterating skills (current)

- skills/ package includes arithmetic skill and registry/reloader.
- SkillRegistry loads modules by import path and supports reload.
- SkillReloader exposes a minimal reload result structure.
- SkillEditor can overwrite skill source with templates and trigger reload.

## Testing strategy

- Unit tests for loop edges and termination.
- Integration tests for checkpoint interruption + resume.
- Mocked Discord flow for approval lifecycle.

## Open questions

- Whether to include a small CLI runner or only a Python entrypoint.
- Which sandbox runtime (Docker or E2B) will be default in the example.
