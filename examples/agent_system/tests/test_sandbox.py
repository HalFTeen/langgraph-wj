"""Tests for sandboxed code execution.

This module tests the sandbox execution system that provides isolated
environments for running generated code safely.

Key concepts:
- SandboxExecutor: Abstract interface for code execution
- DockerExecutor: Docker-based sandboxed execution
- LocalExecutor: Local execution (for testing without Docker)
- ExecutionResult: Structured result from code execution
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from examples.agent_system.sandbox import (
    DockerExecutor,
    ExecutionResult,
    ExecutionStatus,
    LocalExecutor,
    SandboxExecutor,
)


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_create_success_result(self) -> None:
        """Test creating a successful execution result."""
        result = ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            stdout="Hello World",
            stderr="",
            exit_code=0,
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert result.stdout == "Hello World"
        assert result.exit_code == 0
        assert result.is_success()

    def test_create_error_result(self) -> None:
        """Test creating an error execution result."""
        result = ExecutionResult(
            status=ExecutionStatus.ERROR,
            stdout="",
            stderr="NameError: name 'x' is not defined",
            exit_code=1,
        )

        assert result.status == ExecutionStatus.ERROR
        assert "NameError" in result.stderr
        assert not result.is_success()

    def test_create_timeout_result(self) -> None:
        """Test creating a timeout execution result."""
        result = ExecutionResult(
            status=ExecutionStatus.TIMEOUT,
            stdout="",
            stderr="Execution timed out after 30s",
            exit_code=-1,
        )

        assert result.status == ExecutionStatus.TIMEOUT
        assert not result.is_success()

    def test_result_has_duration(self) -> None:
        """Test that result can track execution duration."""
        result = ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=1234,
        )

        assert result.duration_ms == 1234


class TestExecutionStatus:
    """Tests for ExecutionStatus enum."""

    def test_status_values(self) -> None:
        """Test that status enum has expected values."""
        assert ExecutionStatus.SUCCESS.value == "success"
        assert ExecutionStatus.ERROR.value == "error"
        assert ExecutionStatus.TIMEOUT.value == "timeout"
        assert ExecutionStatus.CANCELLED.value == "cancelled"


class TestLocalExecutor:
    """Tests for LocalExecutor (non-Docker execution)."""

    def test_execute_simple_code(self) -> None:
        """Test executing simple Python code."""
        executor = LocalExecutor()
        code = "print('Hello World')"

        result = executor.execute(code)

        assert result.is_success()
        assert "Hello World" in result.stdout

    def test_execute_with_syntax_error(self) -> None:
        """Test executing code with syntax error."""
        executor = LocalExecutor()
        code = "print('unclosed string"

        result = executor.execute(code)

        assert result.status == ExecutionStatus.ERROR
        assert result.exit_code != 0

    def test_execute_with_runtime_error(self) -> None:
        """Test executing code with runtime error."""
        executor = LocalExecutor()
        code = "x = 1 / 0"

        result = executor.execute(code)

        assert result.status == ExecutionStatus.ERROR
        assert "ZeroDivisionError" in result.stderr

    def test_execute_with_timeout(self) -> None:
        """Test that execution respects timeout."""
        executor = LocalExecutor(timeout_seconds=1)
        code = "import time; time.sleep(10)"

        result = executor.execute(code)

        assert result.status == ExecutionStatus.TIMEOUT

    def test_execute_captures_stdout(self) -> None:
        """Test that stdout is captured."""
        executor = LocalExecutor()
        code = """
for i in range(3):
    print(f"Line {i}")
"""

        result = executor.execute(code)

        assert result.is_success()
        assert "Line 0" in result.stdout
        assert "Line 1" in result.stdout
        assert "Line 2" in result.stdout

    def test_execute_captures_stderr(self) -> None:
        """Test that stderr is captured."""
        executor = LocalExecutor()
        code = "import sys; sys.stderr.write('warning message')"

        result = executor.execute(code)

        assert result.is_success()
        assert "warning message" in result.stderr

    def test_execute_returns_duration(self) -> None:
        """Test that execution duration is tracked."""
        executor = LocalExecutor()
        code = "x = 1 + 1"

        result = executor.execute(code)

        assert result.duration_ms is not None
        assert result.duration_ms >= 0


class TestDockerExecutor:
    """Tests for DockerExecutor (Docker-based sandboxed execution)."""

    def test_docker_executor_init(self) -> None:
        """Test DockerExecutor initialization."""
        executor = DockerExecutor(image="python:3.11-slim")

        assert executor.image == "python:3.11-slim"
        assert executor.timeout_seconds > 0

    def test_docker_executor_with_custom_timeout(self) -> None:
        """Test DockerExecutor with custom timeout."""
        executor = DockerExecutor(timeout_seconds=60)

        assert executor.timeout_seconds == 60

    @patch("subprocess.run")
    def test_docker_execute_calls_subprocess(self, mock_run: MagicMock) -> None:
        """Test that Docker execution calls subprocess."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Hello Docker",
            stderr="",
        )

        executor = DockerExecutor()
        result = executor.execute("print('Hello Docker')")

        mock_run.assert_called_once()
        # Verify docker command is in args
        call_args = mock_run.call_args[0][0]
        assert "docker" in call_args[0]

    @patch("subprocess.run")
    def test_docker_execute_handles_error(self, mock_run: MagicMock) -> None:
        """Test that Docker execution handles errors."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error in container",
        )

        executor = DockerExecutor()
        result = executor.execute("invalid code")

        assert result.status == ExecutionStatus.ERROR
        assert result.exit_code == 1

    @patch("subprocess.run")
    def test_docker_execute_handles_timeout(self, mock_run: MagicMock) -> None:
        """Test that Docker execution handles timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=30)

        executor = DockerExecutor(timeout_seconds=30)
        result = executor.execute("import time; time.sleep(100)")

        assert result.status == ExecutionStatus.TIMEOUT

    def test_docker_executor_is_sandbox_executor(self) -> None:
        """Test that DockerExecutor implements SandboxExecutor interface."""
        executor = DockerExecutor()

        assert isinstance(executor, SandboxExecutor)


class TestSandboxExecutorInterface:
    """Tests for SandboxExecutor abstract interface."""

    def test_local_executor_is_sandbox_executor(self) -> None:
        """Test that LocalExecutor implements SandboxExecutor."""
        executor = LocalExecutor()

        assert isinstance(executor, SandboxExecutor)

    def test_executors_have_execute_method(self) -> None:
        """Test that all executors have execute method."""
        local = LocalExecutor()
        docker = DockerExecutor()

        assert hasattr(local, "execute")
        assert hasattr(docker, "execute")
        assert callable(local.execute)
        assert callable(docker.execute)
