"""Inter-agent messaging protocol.

This module provides structured messaging between agents in the multi-agent system.
Messages are typed, prioritized, and support metadata for rich communication.

Key components:
- AgentMessage: Structured message between agents
- MessageType: Type of message (request, response, notification, handoff)
- MessagePriority: Priority level for queue ordering
- MessageQueue: Priority queue for pending messages

Usage:
    from examples.agent_system.messaging import AgentMessage, MessageQueue, MessageType

    # Create a message
    msg = AgentMessage(
        sender="coder",
        receiver="reviewer",
        content="Please review this code",
        message_type=MessageType.REQUEST,
    )

    # Use a queue in state
    queue = MessageQueue()
    queue.enqueue(msg)
    next_msg = queue.dequeue()
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageType(Enum):
    """Type of message for routing and handling."""

    REQUEST = "request"  # Request for action
    RESPONSE = "response"  # Response to a request
    NOTIFICATION = "notification"  # Informational, no response needed
    HANDOFF = "handoff"  # Task transfer to another agent


class MessagePriority(Enum):
    """Priority levels for message queue ordering."""

    LOW = 1
    NORMAL = 2
    HIGH = 3


@dataclass
class AgentMessage:
    """Structured message between agents.

    Attributes:
        sender: Name of the sending agent
        receiver: Name of the receiving agent
        content: Message content (text or structured data)
        message_type: Type of message for routing
        priority: Queue priority (higher = processed first)
        metadata: Optional additional data
        id: Unique message identifier (auto-generated)
    """

    sender: str
    receiver: str
    content: str | dict[str, Any]
    message_type: MessageType
    priority: MessagePriority = MessagePriority.NORMAL
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Convert message to dictionary for serialization."""
        return {
            "id": self.id,
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "message_type": self.message_type.value,
            "priority": self.priority.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentMessage":
        """Create message from dictionary (deserialization)."""
        return cls(
            id=data["id"],
            sender=data["sender"],
            receiver=data["receiver"],
            content=data["content"],
            message_type=MessageType(data["message_type"]),
            priority=MessagePriority(data["priority"]),
            metadata=data.get("metadata", {}),
        )


class MessageQueue:
    """Priority queue for agent messages.

    Messages are ordered by priority (high -> low) and then by insertion order.
    Designed to be easily serializable for LangGraph state.

    Example:
        queue = MessageQueue()
        queue.enqueue(message)
        next_message = queue.dequeue()
    """

    def __init__(self) -> None:
        """Initialize an empty queue."""
        self._messages: list[AgentMessage] = []

    def enqueue(self, message: AgentMessage) -> None:
        """Add a message to the queue."""
        self._messages.append(message)

    def dequeue(self) -> AgentMessage | None:
        """Remove and return the highest priority message.

        Returns:
            The highest priority message, or None if queue is empty.
        """
        if not self._messages:
            return None

        # Sort by priority (descending), then by insertion order
        self._messages.sort(key=lambda m: m.priority.value, reverse=True)
        return self._messages.pop(0)

    def peek(self) -> AgentMessage | None:
        """View the next message without removing it.

        Returns:
            The highest priority message, or None if queue is empty.
        """
        if not self._messages:
            return None

        # Sort to find highest priority
        sorted_msgs = sorted(
            self._messages, key=lambda m: m.priority.value, reverse=True
        )
        return sorted_msgs[0]

    def get_for_receiver(self, receiver: str) -> list[AgentMessage]:
        """Get all messages for a specific receiver.

        Args:
            receiver: Name of the receiving agent

        Returns:
            List of messages for the receiver (not removed from queue)
        """
        return [m for m in self._messages if m.receiver == receiver]

    def is_empty(self) -> bool:
        """Check if queue has no messages."""
        return len(self._messages) == 0

    def __len__(self) -> int:
        """Return number of messages in queue."""
        return len(self._messages)

    def to_list(self) -> list[dict[str, Any]]:
        """Convert queue to list of dicts for state serialization."""
        return [m.to_dict() for m in self._messages]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]]) -> "MessageQueue":
        """Create queue from list of dicts (state loading)."""
        queue = cls()
        for item in data:
            queue.enqueue(AgentMessage.from_dict(item))
        return queue
