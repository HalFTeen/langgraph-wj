"""Role registry for dynamic role management.

The registry provides:
1. Central storage for role instances
2. Factory functions for role creation
3. Dynamic role lookup and instantiation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Type

from langchain_core.language_models.chat_models import BaseChatModel

from examples.agent_system.roles.base import AgentRole
from examples.agent_system.roles.coder import CoderRole
from examples.agent_system.roles.reviewer import ReviewerRole
from examples.agent_system.roles.tester import TesterRole
from examples.agent_system.roles.orchestrator import OrchestratorRole

if TYPE_CHECKING:
    pass


# Default role classes
_DEFAULT_ROLE_CLASSES: dict[str, Type[AgentRole]] = {
    "coder": CoderRole,
    "reviewer": ReviewerRole,
    "tester": TesterRole,
    "orchestrator": OrchestratorRole,
}


class RoleRegistry:
    """Registry for managing agent roles.

    The registry allows dynamic registration and retrieval of roles,
    supporting both pre-configured instances and factory-based creation.

    Example:
        >>> registry = RoleRegistry()
        >>> registry.register("coder", CoderRole(llm=get_llm()))
        >>> coder = registry.get("coder")
        >>> node_fn = coder.as_node()
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._roles: dict[str, AgentRole] = {}
        self._factories: dict[str, Callable[[], AgentRole]] = {}

    def register(self, name: str, role: AgentRole) -> None:
        """Register a role instance.

        Args:
            name: Unique identifier for the role
            role: Role instance to register
        """
        self._roles[name] = role

    def register_factory(
        self, name: str, factory: Callable[[], AgentRole]
    ) -> None:
        """Register a factory function for lazy role creation.

        Args:
            name: Unique identifier for the role
            factory: Function that creates a role instance
        """
        self._factories[name] = factory

    def get(self, name: str) -> AgentRole:
        """Get a role by name.

        If a role instance exists, returns it. Otherwise, tries to use
        a registered factory to create one.

        Args:
            name: Role identifier

        Returns:
            The role instance

        Raises:
            KeyError: If no role or factory is registered with that name
        """
        if name in self._roles:
            return self._roles[name]

        if name in self._factories:
            role = self._factories[name]()
            self._roles[name] = role
            return role

        raise KeyError(f"No role registered with name: {name}")

    def get_or_create(
        self,
        name: str,
        llm: BaseChatModel | None = None,
    ) -> AgentRole:
        """Get a role or create it using default class.

        Args:
            name: Role identifier
            llm: Optional LLM to pass to role constructor

        Returns:
            The role instance

        Raises:
            KeyError: If no role exists and no default class is defined
        """
        if name in self._roles:
            return self._roles[name]

        if name in self._factories:
            role = self._factories[name]()
            self._roles[name] = role
            return role

        if name in _DEFAULT_ROLE_CLASSES:
            role_class = _DEFAULT_ROLE_CLASSES[name]
            role = role_class(llm=llm)
            self._roles[name] = role
            return role

        raise KeyError(
            f"No role registered and no default class for: {name}. "
            f"Available defaults: {list(_DEFAULT_ROLE_CLASSES.keys())}"
        )

    def has(self, name: str) -> bool:
        """Check if a role is registered or has a factory.

        Args:
            name: Role identifier

        Returns:
            True if role exists or can be created
        """
        return (
            name in self._roles
            or name in self._factories
            or name in _DEFAULT_ROLE_CLASSES
        )

    def list_roles(self) -> list[str]:
        """List all registered role names.

        Returns:
            List of registered role names
        """
        return list(self._roles.keys())

    def list_available(self) -> list[str]:
        """List all available roles (registered + defaults).

        Returns:
            List of available role names
        """
        available = set(self._roles.keys())
        available.update(self._factories.keys())
        available.update(_DEFAULT_ROLE_CLASSES.keys())
        return sorted(available)

    def clear(self) -> None:
        """Clear all registered roles and factories."""
        self._roles.clear()
        self._factories.clear()


def create_default_registry(llm: BaseChatModel | None = None) -> RoleRegistry:
    """Create a registry with all default roles registered.

    Args:
        llm: Optional LLM to pass to all roles

    Returns:
        Registry with coder, reviewer, tester, orchestrator roles
    """
    registry = RoleRegistry()
    registry.register("coder", CoderRole(llm=llm))
    registry.register("reviewer", ReviewerRole(llm=llm))
    registry.register("tester", TesterRole(llm=llm))
    registry.register("orchestrator", OrchestratorRole(llm=llm))
    return registry
