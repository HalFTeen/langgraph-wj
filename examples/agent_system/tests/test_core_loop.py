from examples.agent_system.graph import build_graph, build_initial_state


def test_core_loop_reaches_approval() -> None:
    graph = build_graph()
    initial_state = build_initial_state()
    initial_state["approval_status"] = "approved"
    result = graph.invoke(initial_state)

    assert result["review_status"] == "approved"
    assert result["iteration_count"] >= 2
    assert "return a + b" in result["code_files"]["app.py"]
    assert any(
        getattr(message, "content", "").find("approved") >= 0
        for message in result["messages"]
    )
