"""Tests for inter-agent messaging protocol.

This module tests the messaging system that enables agents to communicate
with each other in a structured way.

Key concepts:
- AgentMessage: Structured message between agents (sender, receiver, content_type)
- MessageQueue: State-based queue for pending messages per agent
- MessageRouter: Routes messages to appropriate handlers
"""

from __future__ import annotations

from typing import Literal

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from examples.agent_system.messaging import (
    AgentMessage,
    MessagePriority,
    MessageQueue,
    MessageType,
)


class TestAgentMessage:
    """Tests for AgentMessage dataclass."""

    def test_create_message_with_required_fields(self) -> None:
        """Test creating a message with required fields."""
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Please review this code",
            message_type=MessageType.REQUEST,
        )

        assert msg.sender == "coder"
        assert msg.receiver == "reviewer"
        assert msg.content == "Please review this code"
        assert msg.message_type == MessageType.REQUEST

    def test_message_has_default_priority(self) -> None:
        """Test that messages have default priority."""
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Test",
            message_type=MessageType.REQUEST,
        )

        assert msg.priority == MessagePriority.NORMAL

    def test_message_can_have_metadata(self) -> None:
        """Test that messages can carry metadata."""
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Code review",
            message_type=MessageType.REQUEST,
            metadata={"file": "app.py", "lines": 50},
        )

        assert msg.metadata["file"] == "app.py"
        assert msg.metadata["lines"] == 50

    def test_message_has_auto_generated_id(self) -> None:
        """Test that messages get auto-generated IDs."""
        msg1 = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Test 1",
            message_type=MessageType.REQUEST,
        )
        msg2 = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Test 2",
            message_type=MessageType.REQUEST,
        )

        assert msg1.id is not None
        assert msg2.id is not None
        assert msg1.id != msg2.id


class TestMessageTypes:
    """Tests for message type enumeration."""

    def test_request_type(self) -> None:
        """Test REQUEST message type."""
        assert MessageType.REQUEST.value == "request"

    def test_response_type(self) -> None:
        """Test RESPONSE message type."""
        assert MessageType.RESPONSE.value == "response"

    def test_notification_type(self) -> None:
        """Test NOTIFICATION message type."""
        assert MessageType.NOTIFICATION.value == "notification"

    def test_handoff_type(self) -> None:
        """Test HANDOFF message type for task transfer."""
        assert MessageType.HANDOFF.value == "handoff"


class TestMessagePriority:
    """Tests for message priority enumeration."""

    def test_priority_ordering(self) -> None:
        """Test that priorities have correct ordering."""
        assert MessagePriority.HIGH.value > MessagePriority.NORMAL.value
        assert MessagePriority.NORMAL.value > MessagePriority.LOW.value


class TestMessageQueue:
    """Tests for MessageQueue in state."""

    def test_empty_queue_initialization(self) -> None:
        """Test creating an empty queue."""
        queue = MessageQueue()

        assert queue.is_empty()
        assert len(queue) == 0

    def test_enqueue_message(self) -> None:
        """Test adding a message to the queue."""
        queue = MessageQueue()
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Review needed",
            message_type=MessageType.REQUEST,
        )

        queue.enqueue(msg)

        assert not queue.is_empty()
        assert len(queue) == 1

    def test_dequeue_message(self) -> None:
        """Test removing a message from the queue."""
        queue = MessageQueue()
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Review needed",
            message_type=MessageType.REQUEST,
        )
        queue.enqueue(msg)

        dequeued = queue.dequeue()

        assert dequeued == msg
        assert queue.is_empty()

    def test_dequeue_respects_priority(self) -> None:
        """Test that higher priority messages are dequeued first."""
        queue = MessageQueue()
        low = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Low priority",
            message_type=MessageType.REQUEST,
            priority=MessagePriority.LOW,
        )
        high = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="High priority",
            message_type=MessageType.REQUEST,
            priority=MessagePriority.HIGH,
        )

        queue.enqueue(low)
        queue.enqueue(high)

        # High priority should come first regardless of enqueue order
        assert queue.dequeue() == high
        assert queue.dequeue() == low

    def test_get_messages_for_receiver(self) -> None:
        """Test filtering messages by receiver."""
        queue = MessageQueue()
        for_reviewer = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="For reviewer",
            message_type=MessageType.REQUEST,
        )
        for_tester = AgentMessage(
            sender="coder",
            receiver="tester",
            content="For tester",
            message_type=MessageType.REQUEST,
        )
        queue.enqueue(for_reviewer)
        queue.enqueue(for_tester)

        reviewer_messages = queue.get_for_receiver("reviewer")

        assert len(reviewer_messages) == 1
        assert reviewer_messages[0] == for_reviewer

    def test_peek_does_not_remove(self) -> None:
        """Test that peek shows message without removing."""
        queue = MessageQueue()
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Test",
            message_type=MessageType.REQUEST,
        )
        queue.enqueue(msg)

        peeked = queue.peek()

        assert peeked == msg
        assert not queue.is_empty()

    def test_to_list_for_serialization(self) -> None:
        """Test converting queue to list for state serialization."""
        queue = MessageQueue()
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Test",
            message_type=MessageType.REQUEST,
        )
        queue.enqueue(msg)

        as_list = queue.to_list()

        assert isinstance(as_list, list)
        assert len(as_list) == 1

    def test_from_list_for_deserialization(self) -> None:
        """Test creating queue from list (state loading)."""
        msg = AgentMessage(
            sender="coder",
            receiver="reviewer",
            content="Test",
            message_type=MessageType.REQUEST,
        )
        original_queue = MessageQueue()
        original_queue.enqueue(msg)
        as_list = original_queue.to_list()

        restored = MessageQueue.from_list(as_list)

        assert len(restored) == 1
        assert restored.peek().content == "Test"
