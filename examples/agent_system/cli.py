from __future__ import annotations
import json
from langgraph.checkpoint.sqlite import SqliteSaver
from examples.agent_system.graph import build_checkpointed_graph, build_initial_state

def main() -> None:
    with SqliteSaver.from_conn_string(":memory:") as checkpointer:
        run = build_checkpointed_graph(
            checkpointer=checkpointer, interrupt_before=["executor"]
        )
        graph = run.graph
        config = run.config
        print("=== Phase 1: coder → reviewer → tester → approver (interrupt) ===")
        for step in graph.stream(build_initial_state(), config):
            for node, output in step.items():
                if node == "__interrupt__":
                    print(f"\n[INTERRUPT] Graph paused before executor.")
                else:
                    role = ""
                    msgs = output.get("messages", [])
                    if msgs:
                        role = getattr(msgs[-1], "additional_kwargs", {}).get("role", node)
                    print(f"[{role or node}] done")
        print("\n=== Phase 2: approve and resume ===")
        graph.update_state(config, {"approval_status": "approved"})
        for step in graph.stream(None, config):
            for node, output in step.items():
                print(f"[{node}] done")
        state = graph.get_state(config)
        result = state.values
        print("\n=== Result ===")
        print(f"  review_status:    {result.get('review_status')}")
        print(f"  iteration_count:  {result.get('iteration_count')}")
        print(f"  test_status:      {result.get('test_status')}")
        print(f"  approval_status:  {result.get('approval_status')}")
        print(f"  skill_result:     {result.get('skill_result', '')[:80]}")
        print(f"  code:\n{result.get('code_files', {}).get('app.py', '(none)')}")

if __name__ == "__main__":
    main()
