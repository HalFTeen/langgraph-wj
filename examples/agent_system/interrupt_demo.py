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

        first = list(graph.stream(build_initial_state(), config))
        print("First run (interrupted):")
        print(json.dumps(first, indent=2, default=str))

        graph.update_state(config, {"approval_status": "approved"})
        second = list(graph.stream(None, config))
        print("Resume (approved):")
        print(json.dumps(second, indent=2, default=str))


if __name__ == "__main__":
    main()
