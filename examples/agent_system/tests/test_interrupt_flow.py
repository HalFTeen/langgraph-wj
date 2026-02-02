from langgraph.checkpoint.sqlite import SqliteSaver

from examples.agent_system.graph import build_checkpointed_graph, build_initial_state


def test_interrupt_then_resume() -> None:
    with SqliteSaver.from_conn_string(":memory:") as checkpointer:
        run = build_checkpointed_graph(
            checkpointer=checkpointer, interrupt_before=["executor"]
        )
        graph = run.graph
        config = run.config

        first = list(graph.stream(build_initial_state(), config))
        assert first[-1] == {"__interrupt__": ()}

        graph.update_state(config, {"approval_status": "approved"})
        second = list(graph.stream(None, config))
        assert any("executor" in step for step in second)
