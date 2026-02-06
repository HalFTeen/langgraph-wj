"""Tests for agent role implementations."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.roles.base import AgentRole, PassthroughRole, RoleResult
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.orchestrator import OrchestratorRole
from examples.agent_system.roles.registry import RoleRegistry, create_default_registry
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.roles.tester import TesterRole


class TestRoleResult:
    """Tests for RoleResult dataclass."""

    def test_to_state_dict_includes_message(self) -> None:
        """Test that to_state_dict includes message in messages list."""
        message = AIMessage(content="Test message")
        result = RoleResult(message=message)

        state_dict = result.to_state_dict()

        assert "messages" in state_dict
        assert state_dict["messages"] == [message]

    def test_to_state_dict_includes_updates(self) -> None:
        """Test that to_state_dict includes state_updates."""
        message = AIMessage(content="Test")
        result = RoleResult(
            message=message,
            state_updates={"review_status": "approved", "count": 5},
        )

        state_dict = result.to_state_dict()

        assert state_dict["review_status"] == "approved"
        assert state_dict["count"] == 5

    def test_default_empty_updates(self) -> None:
        """Test that state_updates defaults to empty dict."""
        message = AIMessage(content="Test")
        result = RoleResult(message=message)

        assert result.state_updates == {}
        assert result.metadata == {}


class TestPassthroughRole:
    """Tests for PassthroughRole."""

    def test_returns_role_result(self) -> None:
        """Test that process returns a RoleResult."""
        role = PassthroughRole()
        state = {"messages": [], "code_files": {}}

        result = role.process(state)

        assert isinstance(result, RoleResult)
        assert isinstance(result.message, AIMessage)

    def test_custom_message(self) -> None:
        """Test custom message parameter."""
        role = PassthroughRole(message="Custom message here")
        state = {}

        result = role.process(state)

        assert result.message.content == "Custom message here"

    def test_as_node_returns_callable(self) -> None:
        """Test that as_node returns a callable function."""
        role = PassthroughRole()
        node_fn = role.as_node()

        assert callable(node_fn)

        state = {}
        output = node_fn(state)

        assert isinstance(output, dict)
        assert "messages" in output


class TestCoderRole:
    """Tests for CoderRole."""

    def test_init_without_llm(self) -> None:
        """Test initialization without LLM."""
        coder = CoderRole()

        assert coder.name == "coder"
        assert coder.llm is None

    def test_init_with_llm(self) -> None:
        """Test initialization with LLM."""
        mock_llm = MagicMock()
        coder = CoderRole(llm=mock_llm)

        assert coder.llm == mock_llm

    def test_fallback_first_iteration(self) -> None:
        """Test fallback behavior on first iteration."""
        coder = CoderRole()
        state = {"iteration_count": 0, "code_files": {}, "messages": []}

        result = coder.process(state)

        assert "TODO" in result.state_updates["code_files"]["app.py"]
        assert result.state_updates["iteration_count"] == 1

    def test_fallback_second_iteration(self) -> None:
        """Test fallback behavior on second iteration."""
        coder = CoderRole()
        state = {
            "iteration_count": 1,
            "code_files": {"app.py": "old code"},
            "messages": [],
            "reviewer_feedback": "Fix the math",
        }

        result = coder.process(state)

        assert "return a + b" in result.state_updates["code_files"]["app.py"]
        assert result.state_updates["iteration_count"] == 2

    def test_llm_mode_calls_llm(self) -> None:
        """Test that LLM mode calls the LLM."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "```python\ndef add(a, b): return a + b\n```"

        coder = CoderRole(llm=mock_llm)
        state = {
            "iteration_count": 0,
            "code_files": {},
            "messages": [HumanMessage(content="Write add function")],
            "reviewer_feedback": "",
        }

        result = coder.process(state)

        mock_llm.invoke.assert_called_once()
        assert "add" in result.state_updates["code_files"]["app.py"]

    def test_as_node_integration(self) -> None:
        """Test as_node integration."""
        coder = CoderRole()
        node_fn = coder.as_node()

        state = {"iteration_count": 0, "code_files": {}, "messages": []}
        output = node_fn(state)

        assert "code_files" in output
        assert "messages" in output


class TestReviewerRole:
    """Tests for ReviewerRole."""

    def test_init_without_llm(self) -> None:
        """Test initialization without LLM."""
        reviewer = ReviewerRole()

        assert reviewer.name == "reviewer"
        assert reviewer.llm is None

    def test_fallback_approves_correct_code(self) -> None:
        """Test fallback approves correct code."""
        reviewer = ReviewerRole()
        state = {
            "code_files": {"app.py": "def add(a, b):\n    return a + b\n"},
            "messages": [],
            "iteration_count": 1,
        }

        result = reviewer.process(state)

        assert result.state_updates["review_status"] == "approved"

    def test_fallback_rejects_bad_code(self) -> None:
        """Test fallback rejects incorrect code."""
        reviewer = ReviewerRole()
        state = {
            "code_files": {"app.py": "# TODO\ndef add(a, b): return a - b"},
            "messages": [],
            "iteration_count": 1,
        }

        result = reviewer.process(state)

        assert result.state_updates["review_status"] == "changes"

    def test_llm_mode_approved(self) -> None:
        """Test LLM mode with approval."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "APPROVED - looks great!"

        reviewer = ReviewerRole(llm=mock_llm)
        state = {
            "code_files": {"app.py": "def add(a, b): return a + b"},
            "messages": [HumanMessage(content="Write add")],
            "iteration_count": 1,
            "reviewer_feedback": "",
        }

        result = reviewer.process(state)

        assert result.state_updates["review_status"] == "approved"

    def test_llm_mode_changes_requested(self) -> None:
        """Test LLM mode with changes requested."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "CHANGES_REQUESTED - add error handling"

        reviewer = ReviewerRole(llm=mock_llm)
        state = {
            "code_files": {"app.py": "def add(a, b): return a + b"},
            "messages": [HumanMessage(content="Write add")],
            "iteration_count": 1,
            "reviewer_feedback": "",
        }

        result = reviewer.process(state)

        assert result.state_updates["review_status"] == "changes"
        assert "error handling" in result.state_updates["reviewer_feedback"]

    def test_as_node_integration(self) -> None:
        """Test as_node integration."""
        reviewer = ReviewerRole()
        node_fn = reviewer.as_node()

        state = {
            "code_files": {"app.py": "def add(a, b): return a + b"},
            "messages": [],
            "iteration_count": 1,
        }
        output = node_fn(state)

        assert "review_status" in output
        assert "messages" in output


class TestAgentRoleRepr:
    """Tests for AgentRole __repr__."""

    def test_repr_without_llm(self) -> None:
        """Test repr without LLM."""
        coder = CoderRole()
        repr_str = repr(coder)

        assert "CoderRole" in repr_str
        assert "coder" in repr_str
        assert "None" in repr_str

    def test_repr_with_llm(self) -> None:
        """Test repr with LLM."""
        mock_llm = MagicMock()
        mock_llm.__class__.__name__ = "MockChatModel"
        coder = CoderRole(llm=mock_llm)
        repr_str = repr(coder)

        assert "MockChatModel" in repr_str


class TestTesterRole:
    """Tests for TesterRole."""

    def test_init_without_llm(self) -> None:
        tester = TesterRole()
        assert tester.name == "tester"
        assert tester.llm is None

    def test_fallback_generates_tests_for_add(self) -> None:
        tester = TesterRole()
        state = {
            "code_files": {"app.py": "def add(a, b): return a + b"},
            "messages": [],
        }

        result = tester.process(state)

        assert result.state_updates["test_status"] == "generated"
        assert "test_add" in result.state_updates["test_code"]
        assert "pytest" in result.state_updates["test_code"]

    def test_fallback_skips_when_no_code(self) -> None:
        tester = TesterRole()
        state = {"code_files": {"app.py": "# empty"}, "messages": []}

        result = tester.process(state)

        assert result.state_updates["test_status"] == "skipped"

    def test_llm_mode_calls_llm(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "```python\ndef test_foo(): pass\n```"

        tester = TesterRole(llm=mock_llm)
        state = {
            "code_files": {"app.py": "def foo(): pass"},
            "messages": [HumanMessage(content="Write foo")],
        }

        result = tester.process(state)

        mock_llm.invoke.assert_called_once()
        assert "test_foo" in result.state_updates["test_code"]


class TestOrchestratorRole:
    """Tests for OrchestratorRole."""

    def test_init_without_llm(self) -> None:
        orchestrator = OrchestratorRole()
        assert orchestrator.name == "orchestrator"
        assert orchestrator.llm is None
        assert "coder" in orchestrator.available_agents

    def test_fallback_creates_plan(self) -> None:
        orchestrator = OrchestratorRole()
        state = {
            "messages": [HumanMessage(content="Build a calculator")],
            "execution_plan": [],
        }

        result = orchestrator.process(state)

        plan = result.state_updates["execution_plan"]
        assert len(plan) == 3
        assert plan[0]["agent"] == "coder"
        assert result.state_updates["orchestrator_status"] == "planning"

    def test_fallback_updates_existing_plan(self) -> None:
        orchestrator = OrchestratorRole()
        state = {
            "messages": [HumanMessage(content="Task")],
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "pending"},
                {"agent": "reviewer", "task": "Review", "status": "pending"},
            ],
            "iteration_count": 1,
            "review_status": "",
        }

        result = orchestrator.process(state)

        plan = result.state_updates["execution_plan"]
        assert plan[0]["status"] == "completed"
        assert result.state_updates["orchestrator_status"] == "executing"

    def test_get_next_agent(self) -> None:
        orchestrator = OrchestratorRole()
        state = {
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "completed"},
                {"agent": "reviewer", "task": "Review", "status": "pending"},
            ]
        }

        next_agent = orchestrator.get_next_agent(state)
        assert next_agent == "reviewer"

    def test_get_next_agent_returns_none_when_complete(self) -> None:
        orchestrator = OrchestratorRole()
        state = {
            "execution_plan": [
                {"agent": "coder", "task": "Code", "status": "completed"},
                {"agent": "reviewer", "task": "Review", "status": "completed"},
            ]
        }

        next_agent = orchestrator.get_next_agent(state)
        assert next_agent is None


class TestRoleRegistry:
    """Tests for RoleRegistry."""

    def test_register_and_get(self) -> None:
        registry = RoleRegistry()
        coder = CoderRole()
        registry.register("coder", coder)

        result = registry.get("coder")
        assert result is coder

    def test_get_raises_for_unknown(self) -> None:
        registry = RoleRegistry()

        try:
            registry.get("unknown")
            assert False, "Should raise KeyError"
        except KeyError:
            pass

    def test_register_factory(self) -> None:
        registry = RoleRegistry()
        registry.register_factory("coder", lambda: CoderRole())

        result = registry.get("coder")
        assert isinstance(result, CoderRole)

    def test_get_or_create_uses_default(self) -> None:
        registry = RoleRegistry()

        result = registry.get_or_create("coder")
        assert isinstance(result, CoderRole)

    def test_has(self) -> None:
        registry = RoleRegistry()
        assert registry.has("coder")  # default class
        assert not registry.has("unknown")

        registry.register("custom", PassthroughRole())
        assert registry.has("custom")

    def test_list_available(self) -> None:
        registry = RoleRegistry()
        available = registry.list_available()

        assert "coder" in available
        assert "reviewer" in available
        assert "tester" in available
        assert "orchestrator" in available

    def test_clear(self) -> None:
        registry = RoleRegistry()
        registry.register("test", PassthroughRole())
        registry.clear()

        assert registry.list_roles() == []


class TestCreateDefaultRegistry:
    """Tests for create_default_registry."""

    def test_creates_all_roles(self) -> None:
        registry = create_default_registry()

        assert "coder" in registry.list_roles()
        assert "reviewer" in registry.list_roles()
        assert "tester" in registry.list_roles()
        assert "orchestrator" in registry.list_roles()

    def test_passes_llm_to_roles(self) -> None:
        mock_llm = MagicMock()
        registry = create_default_registry(llm=mock_llm)

        coder = registry.get("coder")
        assert coder.llm is mock_llm
