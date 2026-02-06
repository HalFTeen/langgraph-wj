"""Prompt templates for agent roles.

This module defines system prompts and user prompt templates for
different agent roles in the multi-agent system.

Usage:
    from examples.agent_system.prompts import get_coder_prompt, get_reviewer_prompt

    # Get messages for coder
    messages = get_coder_prompt(
        task="Implement a function to calculate fibonacci numbers",
        context="Working on math utilities module",
        feedback="Previous implementation was too slow"
    )

    # Get messages for reviewer
    messages = get_reviewer_prompt(
        code="def fib(n): ...",
        task="Implement fibonacci function",
        iteration=2
    )
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

# =============================================================================
# System Prompts
# =============================================================================

CODER_SYSTEM_PROMPT = """You are an expert software engineer specializing in writing clean, efficient, and well-documented code.

Your responsibilities:
1. Write code that exactly fulfills the given requirements
2. Follow best practices and coding conventions
3. Include appropriate error handling
4. Write clear comments for complex logic
5. Ensure code is testable and maintainable

Guidelines:
- Use type hints in Python code
- Follow PEP 8 style guidelines
- Prefer simple, readable solutions over clever ones
- Handle edge cases appropriately
- Return complete, working code - no placeholders or TODOs

When responding, output ONLY the code without explanations unless specifically asked.
Wrap your code in appropriate markdown code blocks with the language specified."""

REVIEWER_SYSTEM_PROMPT = """You are a senior code reviewer with expertise in software quality and best practices.

Your responsibilities:
1. Review code for correctness and completeness
2. Check for potential bugs or edge cases
3. Evaluate code quality and maintainability
4. Verify adherence to requirements
5. Provide constructive feedback

Review criteria:
- Functionality: Does the code do what was requested?
- Correctness: Are there any bugs or logic errors?
- Security: Are there any security vulnerabilities?
- Performance: Are there obvious performance issues?
- Style: Does it follow coding conventions?
- Documentation: Is it appropriately documented?

Output format:
1. Start with your decision: APPROVED or CHANGES_REQUESTED
2. If CHANGES_REQUESTED, list specific issues that must be fixed
3. Be concise and actionable in your feedback"""

TESTER_SYSTEM_PROMPT = """You are a quality assurance engineer specializing in software testing.

Your responsibilities:
1. Design test cases that cover requirements
2. Write clear, maintainable test code
3. Cover edge cases and error conditions
4. Ensure tests are deterministic and isolated

Guidelines:
- Use pytest for Python testing
- Include unit tests for individual functions
- Test both happy path and error cases
- Use descriptive test names
- Keep tests focused and atomic"""

ORCHESTRATOR_SYSTEM_PROMPT = """You are a project orchestrator managing a team of specialized agents.

Your responsibilities:
1. Break down tasks into actionable sub-tasks
2. Assign tasks to appropriate agents
3. Coordinate work between agents
4. Track progress and resolve blockers
5. Ensure quality gates are met

Available agents:
- Coder: Writes and modifies code
- Reviewer: Reviews code for quality
- Tester: Writes and runs tests
- Executor: Executes code in sandbox

Output your plan as a structured list of steps with agent assignments."""


# =============================================================================
# Prompt Template Functions
# =============================================================================


def get_coder_prompt(
    task: str,
    *,
    context: str | None = None,
    feedback: str | None = None,
    existing_code: str | None = None,
) -> list[SystemMessage | HumanMessage]:
    """Create prompt messages for the Coder role.

    Args:
        task: The coding task to accomplish
        context: Optional context about the project or module
        feedback: Optional feedback from previous review iteration
        existing_code: Optional existing code to modify

    Returns:
        List of messages ready for LLM invocation
    """
    messages: list[SystemMessage | HumanMessage] = [
        SystemMessage(content=CODER_SYSTEM_PROMPT)
    ]

    # Build user message
    user_parts = [f"## Task\n{task}"]

    if context:
        user_parts.append(f"\n## Context\n{context}")

    if existing_code:
        user_parts.append(f"\n## Existing Code\n```python\n{existing_code}\n```")

    if feedback:
        user_parts.append(
            f"\n## Reviewer Feedback (MUST ADDRESS)\n{feedback}\n\n"
            "Please update the code to address all feedback items."
        )

    messages.append(HumanMessage(content="\n".join(user_parts)))
    return messages


def get_reviewer_prompt(
    code: str,
    task: str,
    *,
    iteration: int = 1,
    previous_feedback: str | None = None,
) -> list[SystemMessage | HumanMessage]:
    """Create prompt messages for the Reviewer role.

    Args:
        code: The code to review
        task: The original task requirements
        iteration: Current iteration number (for context)
        previous_feedback: Feedback from previous review (if any)

    Returns:
        List of messages ready for LLM invocation
    """
    messages: list[SystemMessage | HumanMessage] = [
        SystemMessage(content=REVIEWER_SYSTEM_PROMPT)
    ]

    user_parts = [
        f"## Original Task\n{task}",
        f"\n## Code to Review (Iteration {iteration})\n```python\n{code}\n```",
    ]

    if previous_feedback:
        user_parts.append(
            f"\n## Previous Feedback\n{previous_feedback}\n\n"
            "Verify that the previous feedback has been addressed."
        )

    user_parts.append(
        "\n## Instructions\n"
        "Review the code against the requirements. "
        "Output APPROVED if the code meets all requirements, "
        "or CHANGES_REQUESTED with specific issues to fix."
    )

    messages.append(HumanMessage(content="\n".join(user_parts)))
    return messages


def get_tester_prompt(
    code: str,
    task: str,
    *,
    test_requirements: str | None = None,
) -> list[SystemMessage | HumanMessage]:
    """Create prompt messages for the Tester role.

    Args:
        code: The code to test
        task: The original task requirements
        test_requirements: Optional specific testing requirements

    Returns:
        List of messages ready for LLM invocation
    """
    messages: list[SystemMessage | HumanMessage] = [
        SystemMessage(content=TESTER_SYSTEM_PROMPT)
    ]

    user_parts = [
        f"## Original Task\n{task}",
        f"\n## Code to Test\n```python\n{code}\n```",
    ]

    if test_requirements:
        user_parts.append(f"\n## Specific Test Requirements\n{test_requirements}")

    user_parts.append(
        "\n## Instructions\n"
        "Write pytest tests for this code. "
        "Include tests for normal operation and edge cases. "
        "Output only the test code."
    )

    messages.append(HumanMessage(content="\n".join(user_parts)))
    return messages


def get_orchestrator_prompt(
    task: str,
    *,
    available_agents: list[str] | None = None,
    current_state: str | None = None,
) -> list[SystemMessage | HumanMessage]:
    """Create prompt messages for the Orchestrator role.

    Args:
        task: The high-level task to orchestrate
        available_agents: List of available agent names
        current_state: Current state of the task execution

    Returns:
        List of messages ready for LLM invocation
    """
    messages: list[SystemMessage | HumanMessage] = [
        SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT)
    ]

    if available_agents is None:
        available_agents = ["coder", "reviewer", "tester", "executor"]

    user_parts = [
        f"## Task\n{task}",
        f"\n## Available Agents\n{', '.join(available_agents)}",
    ]

    if current_state:
        user_parts.append(f"\n## Current State\n{current_state}")

    user_parts.append(
        "\n## Instructions\n"
        "Create a plan to accomplish this task using the available agents. "
        "Output a numbered list of steps with the assigned agent for each."
    )

    messages.append(HumanMessage(content="\n".join(user_parts)))
    return messages
