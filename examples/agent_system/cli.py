from __future__ import annotations

import json

from examples.agent_system.graph import build_graph, build_initial_state


def main() -> None:
    graph = build_graph()
    initial_state = build_initial_state()
    result = graph.invoke(initial_state)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
