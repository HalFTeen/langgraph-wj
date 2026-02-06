"""Base class for agent roles.

This module defines the abstract base class for all agent roles in the system.
Roles are responsible for:
1. Processing state and generating outputs
2. Integrating with LLMs for intelligent behavior
3. Producing structured results for graph state updates

Usage:
    class MyRole(AgentRole):
        def __init__(self, llm=None):
            super().__init__(name="my_role", llm=llm)

        def process(self, state: AgentState) -> RoleResult:
            # Implement role logic
            return RoleResult(...)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

if TYPE_CHECKING:
    from examples.agent_system.graph import AgentState


@dataclass
class RoleResult:
    """Result from a role's processing.

    Attributes:
        message: The message to add to conversation history
        state_updates: Dictionary of state fields to update
        metadata: Optional metadata about the processing
    """

    message: AIMessage
    state_updates: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_state_dict(self) -> dict[str, Any]:
        """Convert result to a state update dictionary.

        Returns:
            Dictionary suitable for LangGraph state update.
        """
        result = dict(self.state_updates)
        result["messages"] = [self.message]
        return result


class AgentRole(ABC):
    """Abstract base class for agent roles.

    An AgentRole encapsulates a specific capability in the multi-agent system.
    Subclasses must implement the `process` method to define role behavior.

    Attributes:
        name: Unique identifier for the role
        llm: Optional LLM instance for intelligent processing
    """

    def __init__(
        self,
        name: str,
        *,
        llm: BaseChatModel | None = None,
        description: str = "",
    ) -> None:
        """Initialize the role.

        Args:
            name: Unique identifier for this role
            llm: Optional LLM for intelligent processing
            description: Human-readable description of the role's purpose
        """
        self.name = name
        self.llm = llm
        self.description = description

    @abstractmethod
    def process(self, state: "AgentState") -> RoleResult:
        """Process the current state and produce a result.

        This is the main entry point for role logic. Subclasses must
        implement this method to define their specific behavior.

        Args:
            state: Current graph state

        Returns:
            RoleResult containing the output message and state updates
        """
        pass

    def as_node(self) -> Callable[["AgentState"], dict[str, Any]]:
        """Create a LangGraph-compatible node function.

        Returns:
            A function that can be used with graph.add_node()

        Example:
            >>> role = MyRole(llm=get_llm())
            >>> graph.add_node("my_role", role.as_node())
        """
        def node_fn(state: "AgentState") -> dict[str, Any]:
            result = self.process(state)
            return result.to_state_dict()
        return node_fn

    def __repr__(self) -> str:
        llm_str = type(self.llm).__name__ if self.llm else "None"
        return f"{self.__class__.__name__}(name={self.name!r}, llm={llm_str})"


class PassthroughRole(AgentRole):
    """A simple role that passes state through with a message.

    Useful for testing and as a placeholder during development.
    """

    def __init__(
        self,
        name: str = "passthrough",
        *,
        message: str = "Passthrough completed.",
    ) -> None:
        super().__init__(name=name, description="Passes state through unchanged")
        self._message = message

    def process(self, state: "AgentState") -> RoleResult:
        """Pass through state with a simple message."""
        return RoleResult(
            message=AIMessage(
                content=self._message,
                additional_kwargs={"role": self.name, "type": "passthrough"},
            ),
            state_updates={},
        )
