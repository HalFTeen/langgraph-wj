# Agent System Example

This example demonstrates a multi-role, self-iterating agent with human-in-the-loop control.
It is scoped as a standalone example (not a core library) and focuses on:

- multi-role orchestration (coder, reviewer, tester, executor)
- looped self-iteration with quality gates
- Discord-only remote intervention (initial version)
- checkpointed interruption and resume

Docs
- Development plan and progress: `examples/agent_system/PROGRESS.md`
- Design and implementation notes: `examples/agent_system/DEVELOPMENT.md`

Run
- `python examples/agent_system/cli.py`
- `python examples/agent_system/interrupt_demo.py`
- Gateway API: `uvicorn examples.agent_system.gateway.app:app --reload`
- Discord bot: `python examples/agent_system/gateway/run_discord_bot.py`

Tests
- `python -m pytest examples/agent_system/tests/test_core_loop.py`
- `python -m pytest examples/agent_system/tests/test_interrupt_flow.py`
- `python -m pytest examples/agent_system/tests/test_discord_bot.py`
