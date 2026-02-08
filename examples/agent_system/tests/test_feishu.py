"""Tests for Feishu gateway integration."""

from __future__ import annotations

import base64
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from examples.agent_system.gateway.feishu_client import (
    FeishuClient,
    FeishuConfig,
    get_feishu_client,
)
from examples.agent_system.gateway.feishu_bot import (
    ApprovalStore,
    create_feishu_router,
    parse_command,
)


class TestFeishuConfig:
    """Tests for FeishuConfig."""

    def test_from_env_returns_none_without_app_id(self) -> None:
        """Test that from_env returns None when app_id is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FEISHU_APP_ID", None)
            config = FeishuConfig.from_env()
            assert config is None

    def test_from_env_creates_config(self) -> None:
        """Test that from_env creates config when app_id is set."""
        env_vars = {
            "FEISHU_APP_ID": "test_app_id",
            "FEISHU_APP_SECRET": "test_secret",
            "FEISHU_DOMAIN": "lark",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            config = FeishuConfig.from_env()
            assert config is not None
            assert config.app_id == "test_app_id"
            assert config.app_secret == "test_secret"
            assert config.domain == "lark"

    def test_get_base_url_feishu(self) -> None:
        """Test base URL for Feishu China."""
        config = FeishuConfig(app_id="id", app_secret="secret", domain="feishu")
        assert config.get_base_url() == "https://open.feishu.cn"

    def test_get_base_url_lark(self) -> None:
        """Test base URL for Lark International."""
        config = FeishuConfig(app_id="id", app_secret="secret", domain="lark")
        assert config.get_base_url() == "https://open.larksuite.com"

    def test_get_base_url_custom(self) -> None:
        """Test base URL for custom domain."""
        config = FeishuConfig(
            app_id="id", app_secret="secret", domain="https://open.custom.cn"
        )
        assert config.get_base_url() == "https://open.custom.cn"


class TestFeishuClient:
    """Tests for FeishuClient."""

    def test_client_initialization(self) -> None:
        """Test client can be initialized with config."""
        config = FeishuConfig(app_id="test_id", app_secret="test_secret")
        client = FeishuClient(config=config)
        assert client.config.app_id == "test_id"

    def test_send_text_message(self) -> None:
        """Test sending text message."""
        config = FeishuConfig(app_id="test_id", app_secret="test_secret")
        client = FeishuClient(config=config)

        # Mock the _request method
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {"code": 0, "data": {"message_id": "123"}}

            result = client.send_text_message("user_123", "Hello!")

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert "POST" in str(call_args)
            assert "messages" in str(call_args)


class TestApprovalStore:
    """Tests for ApprovalStore."""

    def test_create_approval(self) -> None:
        """Test creating an approval request."""
        store = ApprovalStore()

        approval = store.create_approval(
            request_id="req_123",
            thread_id="thread_456",
            user_id="user_789",
            chat_id="chat_abc",
            title="Test Approval",
            description="Test description",
            approve_url="/approve/123",
            deny_url="/deny/123",
        )

        assert approval.request_id == "req_123"
        assert approval.status == "pending"
        assert store.get_approval("req_123") == approval

    def test_get_pending_for_user(self) -> None:
        """Test getting pending approvals for a user."""
        store = ApprovalStore()

        store.create_approval(
            request_id="req_1",
            thread_id="thread_1",
            user_id="user_1",
            chat_id="chat_1",
            title="Approval 1",
            description="Desc 1",
            approve_url="/a1",
            deny_url="/d1",
        )
        store.create_approval(
            request_id="req_2",
            thread_id="thread_2",
            user_id="user_1",
            chat_id="chat_2",
            title="Approval 2",
            description="Desc 2",
            approve_url="/a2",
            deny_url="/d2",
        )
        store.create_approval(
            request_id="req_3",
            thread_id="thread_3",
            user_id="user_2",
            chat_id="chat_3",
            title="Approval 3",
            description="Desc 3",
            approve_url="/a3",
            deny_url="/d3",
        )

        # Update one to approved
        store.update_status("req_2", "approved")

        pending = store.get_pending_for_user("user_1")
        assert len(pending) == 1
        assert pending[0].request_id == "req_1"

    def test_update_status(self) -> None:
        """Test updating approval status."""
        store = ApprovalStore()

        store.create_approval(
            request_id="req_123",
            thread_id="thread_1",
            user_id="user_1",
            chat_id="chat_1",
            title="Test",
            description="Test",
            approve_url="/a",
            deny_url="/d",
        )

        result = store.update_status("req_123", "approved")
        assert result is not None
        assert result.status == "approved"

        # Verify in store
        approval = store.get_approval("req_123")
        assert approval is not None
        assert approval.status == "approved"


class TestParseCommand:
    """Tests for command parsing."""

    def test_parse_empty(self) -> None:
        """Test parsing empty content."""
        cmd, args = parse_command("")
        assert cmd == ""
        assert args == []

    def test_parse_non_command(self) -> None:
        """Test parsing non-command text."""
        cmd, args = parse_command("Hello world")
        assert cmd == ""
        assert args == []

    def test_parse_approve(self) -> None:
        """Test parsing /approve command."""
        cmd, args = parse_command("/approve req_123")
        assert cmd == "approve"
        assert args == ["req_123"]

    def test_parse_approve_without_args(self) -> None:
        """Test parsing /approve without arguments."""
        cmd, args = parse_command("/approve")
        assert cmd == "approve"
        assert args == []

    def test_parse_deny(self) -> None:
        """Test parsing /deny command."""
        cmd, args = parse_command("/deny req_456 extra info")
        assert cmd == "deny"
        assert args == ["req_456", "extra", "info"]

    def test_parse_status(self) -> None:
        """Test parsing /status command."""
        cmd, args = parse_command("/status")
        assert cmd == "status"
        assert args == []

    def test_parse_case_insensitive(self) -> None:
        """Test command parsing is case insensitive."""
        cmd, args = parse_command("/APPROVE req_123")
        assert cmd == "approve"


class TestFeishuRouter:
    """Tests for Feishu webhook router."""

    def test_verify_url_endpoint(self) -> None:
        """Test URL verification endpoint."""
        router, deps = create_feishu_router()
        app = MagicMock()
        app.include_router = MagicMock()

        # Create test client
        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)

        client = TestClient(test_app)

        response = client.get("/feishu/events", params={"challenge": "test_challenge"})

        assert response.status_code == 200
        assert response.json()["challenge"] == "test_challenge"

    def test_event_endpoint_exists(self) -> None:
        """Test that event endpoint exists."""
        router, deps = create_feishu_router()

        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)

        client = TestClient(test_app)

        # POST should be accepted (may fail validation but endpoint exists)
        response = client.post("/feishu/events", json={"header": {}})
        # Will fail validation but endpoint is found
        assert response.status_code in [200, 422, 400]


class TestFeishuClientApprovalCard:
    """Tests for approval card functionality."""

    def test_send_approval_card_structure(self) -> None:
        """Test that approval card has correct structure."""
        config = FeishuConfig(app_id="test_id", app_secret="test_secret")
        client = FeishuClient(config=config)

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {"code": 0, "data": {"message_id": "msg_123"}}

            result = client.send_approval_card(
                receive_id="user_123",
                title="Test Title",
                description="Test description",
                approve_url="http://example.com/approve",
                deny_url="http://example.com/deny",
            )

            # Verify the call was made with card message type
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert "POST" in str(call_args)
            assert "card" in str(call_args)


class TestGetFeishuClient:
    """Tests for get_feishu_client function."""

    @patch("examples.agent_system.gateway.feishu_client.FeishuConfig.from_env")
    def test_get_client_from_env(self, mock_from_env: MagicMock) -> None:
        """Test getting client from environment."""
        mock_config = FeishuConfig(app_id="env_id", app_secret="env_secret")
        mock_from_env.return_value = mock_config

        client = get_feishu_client()

        assert client is not None
        assert client.config.app_id == "env_id"

    @patch("examples.agent_system.gateway.feishu_client.FeishuConfig.from_env")
    def test_get_client_returns_none_when_not_configured(
        self, mock_from_env: MagicMock
    ) -> None:
        """Test that get_feishu_client returns None when not configured."""
        mock_from_env.return_value = None

        client = get_feishu_client()

        assert client is None
