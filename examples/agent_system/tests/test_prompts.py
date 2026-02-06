"""Tests for prompt templates."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from examples.agent_system.prompts.templates import (
    CODER_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    TESTER_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    get_coder_prompt,
    get_orchestrator_prompt,
    get_reviewer_prompt,
    get_tester_prompt,
)


class TestSystemPrompts:
    """Tests for system prompt constants."""

    def test_coder_system_prompt_not_empty(self) -> None:
        """Test that coder system prompt is defined."""
        assert len(CODER_SYSTEM_PROMPT) > 100
        assert "code" in CODER_SYSTEM_PROMPT.lower()

    def test_reviewer_system_prompt_not_empty(self) -> None:
        """Test that reviewer system prompt is defined."""
        assert len(REVIEWER_SYSTEM_PROMPT) > 100
        assert "review" in REVIEWER_SYSTEM_PROMPT.lower()

    def test_tester_system_prompt_not_empty(self) -> None:
        """Test that tester system prompt is defined."""
        assert len(TESTER_SYSTEM_PROMPT) > 100
        assert "test" in TESTER_SYSTEM_PROMPT.lower()

    def test_orchestrator_system_prompt_not_empty(self) -> None:
        """Test that orchestrator system prompt is defined."""
        assert len(ORCHESTRATOR_SYSTEM_PROMPT) > 100
        assert "orchestrat" in ORCHESTRATOR_SYSTEM_PROMPT.lower()


class TestGetCoderPrompt:
    """Tests for get_coder_prompt function."""

    def test_returns_system_and_human_messages(self) -> None:
        """Test that function returns correct message types."""
        messages = get_coder_prompt(task="Write a hello world function")

        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)

    def test_system_message_is_coder_prompt(self) -> None:
        """Test that system message uses coder prompt."""
        messages = get_coder_prompt(task="Write a function")

        assert messages[0].content == CODER_SYSTEM_PROMPT

    def test_task_included_in_human_message(self) -> None:
        """Test that task is included in human message."""
        task = "Implement a fibonacci function"
        messages = get_coder_prompt(task=task)

        assert task in messages[1].content

    def test_context_included_when_provided(self) -> None:
        """Test that context is included when provided."""
        context = "This is for the math utilities module"
        messages = get_coder_prompt(task="Write a function", context=context)

        assert context in messages[1].content

    def test_feedback_included_when_provided(self) -> None:
        """Test that feedback is included when provided."""
        feedback = "Please add error handling"
        messages = get_coder_prompt(task="Write a function", feedback=feedback)

        assert feedback in messages[1].content
        assert "MUST ADDRESS" in messages[1].content

    def test_existing_code_included_when_provided(self) -> None:
        """Test that existing code is included when provided."""
        existing_code = "def old_func(): pass"
        messages = get_coder_prompt(task="Update the function", existing_code=existing_code)

        assert existing_code in messages[1].content


class TestGetReviewerPrompt:
    """Tests for get_reviewer_prompt function."""

    def test_returns_system_and_human_messages(self) -> None:
        """Test that function returns correct message types."""
        messages = get_reviewer_prompt(code="def foo(): pass", task="Write foo")

        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)

    def test_system_message_is_reviewer_prompt(self) -> None:
        """Test that system message uses reviewer prompt."""
        messages = get_reviewer_prompt(code="def foo(): pass", task="Write foo")

        assert messages[0].content == REVIEWER_SYSTEM_PROMPT

    def test_code_and_task_included(self) -> None:
        """Test that code and task are included in human message."""
        code = "def my_function(): return 42"
        task = "Return the answer to everything"
        messages = get_reviewer_prompt(code=code, task=task)

        assert code in messages[1].content
        assert task in messages[1].content

    def test_iteration_number_included(self) -> None:
        """Test that iteration number is shown."""
        messages = get_reviewer_prompt(code="x", task="y", iteration=3)

        assert "Iteration 3" in messages[1].content

    def test_previous_feedback_included_when_provided(self) -> None:
        """Test that previous feedback is included when provided."""
        feedback = "Previous issues: no error handling"
        messages = get_reviewer_prompt(
            code="x", task="y", previous_feedback=feedback
        )

        assert feedback in messages[1].content

    def test_instructions_request_approved_or_changes(self) -> None:
        """Test that instructions mention APPROVED and CHANGES_REQUESTED."""
        messages = get_reviewer_prompt(code="x", task="y")

        assert "APPROVED" in messages[1].content
        assert "CHANGES_REQUESTED" in messages[1].content


class TestGetTesterPrompt:
    """Tests for get_tester_prompt function."""

    def test_returns_system_and_human_messages(self) -> None:
        """Test that function returns correct message types."""
        messages = get_tester_prompt(code="def foo(): pass", task="Write foo")

        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)

    def test_system_message_is_tester_prompt(self) -> None:
        """Test that system message uses tester prompt."""
        messages = get_tester_prompt(code="def foo(): pass", task="Write foo")

        assert messages[0].content == TESTER_SYSTEM_PROMPT

    def test_code_and_task_included(self) -> None:
        """Test that code and task are included."""
        code = "def add(a, b): return a + b"
        task = "Implement addition"
        messages = get_tester_prompt(code=code, task=task)

        assert code in messages[1].content
        assert task in messages[1].content

    def test_test_requirements_included_when_provided(self) -> None:
        """Test that test requirements are included when provided."""
        requirements = "Must test with negative numbers"
        messages = get_tester_prompt(
            code="x", task="y", test_requirements=requirements
        )

        assert requirements in messages[1].content


class TestGetOrchestratorPrompt:
    """Tests for get_orchestrator_prompt function."""

    def test_returns_system_and_human_messages(self) -> None:
        """Test that function returns correct message types."""
        messages = get_orchestrator_prompt(task="Build a calculator")

        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)

    def test_system_message_is_orchestrator_prompt(self) -> None:
        """Test that system message uses orchestrator prompt."""
        messages = get_orchestrator_prompt(task="Build something")

        assert messages[0].content == ORCHESTRATOR_SYSTEM_PROMPT

    def test_default_agents_included(self) -> None:
        """Test that default agents are listed."""
        messages = get_orchestrator_prompt(task="Build something")

        assert "coder" in messages[1].content.lower()
        assert "reviewer" in messages[1].content.lower()

    def test_custom_agents_included(self) -> None:
        """Test that custom agent list is used."""
        agents = ["coder", "deployer"]
        messages = get_orchestrator_prompt(task="Deploy app", available_agents=agents)

        assert "coder" in messages[1].content.lower()
        assert "deployer" in messages[1].content.lower()
        # Default agents should not be present if not in list
        assert "tester" not in messages[1].content.lower()

    def test_current_state_included_when_provided(self) -> None:
        """Test that current state is included when provided."""
        state = "Step 1 completed, awaiting review"
        messages = get_orchestrator_prompt(task="Build app", current_state=state)

        assert state in messages[1].content
