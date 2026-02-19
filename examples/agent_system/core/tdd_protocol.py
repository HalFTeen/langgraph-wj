"""TDD Protocol - Test-driven development enforcement for NAL.
Two modes:
- FULL: Functional code. Write test (red) → write code (green) → verify (no regression) → commit.
- LITE: Non-functional changes (config, docs, UI). Modify → verify (no regression) → commit.
Failure handling: retry from Step 1, escalate to FAILED after max_retries.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol
if TYPE_CHECKING:
    from examples.agent_system.core.git_ops import GitOps
    from examples.agent_system.core.task_graph import Task
    from examples.agent_system.sandbox import ExecutionResult, SandboxExecutor
logger = logging.getLogger(__name__)

class TDDMode(Enum):
    """TDD enforcement mode."""
    FULL = "full"  # Functional code: red → green → verify → commit
    LITE = "lite"  # Non-functional: modify → verify → commit

class TDDStep(Enum):
    """Steps in the TDD protocol."""
    # Full mode steps
    WRITE_TEST = "write_test"
    WRITE_CODE = "write_code"
    VERIFY = "verify"
    COMMIT = "commit"
    # Lite mode steps
    MODIFY = "modify"
    # VERIFY and COMMIT are shared

@dataclass
class TestResult:
    """Result of running tests."""
    passed: bool
    output: str
    failures: list[str] = field(default_factory=list)
    total: int = 0
    failed_count: int = 0
    error_count: int = 0

@dataclass
class LintResult:
    """Result of running linter."""
    passed: bool
    output: str
    issues: list[str] = field(default_factory=list)

@dataclass
class TDDResult:
    """Result of a TDD protocol execution."""
    step: TDDStep
    success: bool
    error_message: str = ""
    test_output: str = ""
    diff_lines: int = 0
    commit_hash: str = ""
    @property
    def failed(self) -> bool:
        return not self.success

class AgentWork(Protocol):
    """Protocol for agent work output (duck typing, no hard dependency)."""
    @property
    def files_modified(self) -> dict[str, str]: ...
    @property
    def test_files(self) -> dict[str, str]: ...
    @property
    def success(self) -> bool: ...
    @property
    def message(self) -> str: ...

class TestRunner:
    """Runs tests and linters using a SandboxExecutor.
    Reuses the existing sandbox infrastructure (Local/Docker).
    """
    def __init__(self, executor: SandboxExecutor) -> None:
        self.executor = executor
    def run_tests(self, test_code: str, source_code: str = "") -> TestResult:
        """Run a specific test file against source code."""
        combined = ""
        if source_code:
            combined += source_code + "\n\n"
        combined += test_code
        result = self.executor.execute(combined)
        passed = result.is_success()
        return TestResult(
            passed=passed,
            output=result.stdout + result.stderr,
            total=1,
            failed_count=0 if passed else 1,
        )
    def run_all_tests(self, test_dir: str = "tests") -> TestResult:
        """Run all tests in a directory via pytest."""
        code = f"""
import subprocess
import sys
result = subprocess.run(
    [sys.executable, "-m", "pytest", "{test_dir}", "-v", "--tb=short"],
    capture_output=True, text=True, timeout=120
)
print(result.stdout)
print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
"""
        result = self.executor.execute(code)
        passed = result.is_success()
        return TestResult(
            passed=passed,
            output=result.stdout + result.stderr,
        )
    def run_linter(self, files: list[str] | None = None) -> LintResult:
        """Run linter on specified files or entire project."""
        targets = repr(files) if files else '["."]'
        code = f"""
import subprocess
import sys
result = subprocess.run(
    [sys.executable, "-m", "ruff", "check"] + {targets},
    capture_output=True, text=True, timeout=60
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
"""
        result = self.executor.execute(code)
        return LintResult(
            passed=result.is_success(),
            output=result.stdout + result.stderr,
        )
    def detect_framework(self, repo_path: str) -> str:
        """Auto-detect test framework from project files."""
        from pathlib import Path
        root = Path(repo_path)
        if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
            return "pytest"
        if (root / "package.json").exists():
            return "jest"
        if (root / "go.mod").exists():
            return "go_test"
        return "pytest"  # default

class TDDProtocol:
    """Enforces TDD baby-step discipline.
    Coordinates between Agent (writes code/tests), TestRunner (validates),
    and GitOps (commits). Does NOT contain any LLM/agent logic itself.
    """
    def __init__(
        self,
        git_ops: GitOps | None = None,
        test_runner: TestRunner | None = None,
    ) -> None:
        self.git_ops = git_ops
        self.test_runner = test_runner
    def validate_red(
        self, test_code: str, source_code: str = ""
    ) -> TDDResult:
        """Step 1 of full TDD: verify the test FAILS (red light).
        The test must fail on the current code. If it passes,
        the test is not testing new behavior.
        """
        if self.test_runner is None:
            # No runner available, skip validation
            return TDDResult(step=TDDStep.WRITE_TEST, success=True)
        result = self.test_runner.run_tests(test_code, source_code)
        if result.passed:
            return TDDResult(
                step=TDDStep.WRITE_TEST,
                success=False,
                error_message="Test should FAIL on current code (red light), but it PASSED. "
                "The test is not testing new behavior.",
                test_output=result.output,
            )
        return TDDResult(
            step=TDDStep.WRITE_TEST,
            success=True,
            test_output=result.output,
        )
    def validate_green(
        self, test_code: str, source_code: str
    ) -> TDDResult:
        """Step 2 of full TDD: verify the test PASSES (green light).
        After writing implementation, the test must pass.
        """
        if self.test_runner is None:
            return TDDResult(step=TDDStep.WRITE_CODE, success=True)
        result = self.test_runner.run_tests(test_code, source_code)
        if not result.passed:
            return TDDResult(
                step=TDDStep.WRITE_CODE,
                success=False,
                error_message="Test should PASS after implementation (green light), but it FAILED.",
                test_output=result.output,
            )
        return TDDResult(
            step=TDDStep.WRITE_CODE,
            success=True,
            test_output=result.output,
        )
    def validate_no_regression(self) -> TDDResult:
        """Step 3: verify no regression (all existing tests still pass)."""
        if self.test_runner is None:
            return TDDResult(step=TDDStep.VERIFY, success=True)
        result = self.test_runner.run_all_tests()
        if not result.passed:
            return TDDResult(
                step=TDDStep.VERIFY,
                success=False,
                error_message="Regression detected: existing tests failed.",
                test_output=result.output,
            )
        return TDDResult(
            step=TDDStep.VERIFY,
            success=True,
            test_output=result.output,
        )
    def validate_diff_limit(self, diff_lines: int, limit: int) -> TDDResult:
        """Check that the diff doesn't exceed the baby-step limit."""
        if diff_lines > limit:
            return TDDResult(
                step=TDDStep.WRITE_CODE,
                success=False,
                error_message=f"Diff too large: {diff_lines} lines exceeds limit of {limit}.",
                diff_lines=diff_lines,
            )
        return TDDResult(
            step=TDDStep.WRITE_CODE,
            success=True,
            diff_lines=diff_lines,
        )
    def do_commit(
        self,
        message: str,
        agent_id: str,
        task_id: str,
        step_info: str | None = None,
    ) -> TDDResult:
        """Step 4: commit changes via GitOps."""
        if self.git_ops is None:
            return TDDResult(
                step=TDDStep.COMMIT,
                success=True,
                commit_hash="no-git",
            )
        try:
            commit_hash = self.git_ops.commit(
                message=message,
                agent_id=agent_id,
                task_id=task_id,
                step_info=step_info,
            )
            return TDDResult(
                step=TDDStep.COMMIT,
                success=True,
                commit_hash=commit_hash,
            )
        except Exception as exc:
            return TDDResult(
                step=TDDStep.COMMIT,
                success=False,
                error_message=f"Commit failed: {exc}",
            )
    def execute_full(
        self,
        task_id: str,
        agent_id: str,
        test_code: str,
        source_code_before: str,
        source_code_after: str,
        diff_lines: int,
        diff_limit: int = 100,
        commit_message: str = "",
    ) -> TDDResult:
        """Execute complete TDD cycle: red → green → verify → commit.
        Returns the result of the first failing step, or success after commit.
        """
        # Step 1: Red light - test must fail on old code
        result = self.validate_red(test_code, source_code_before)
        if result.failed:
            return result
        # Step 2: Green light - test must pass on new code
        result = self.validate_green(test_code, source_code_after)
        if result.failed:
            return result
        # Step 2b: Diff limit check
        result = self.validate_diff_limit(diff_lines, diff_limit)
        if result.failed:
            return result
        # Step 3: No regression
        result = self.validate_no_regression()
        if result.failed:
            return result
        # Step 4: Commit
        msg = commit_message or f"feat: implement for task {task_id}"
        return self.do_commit(msg, agent_id, task_id)
    def execute_lite(
        self,
        task_id: str,
        agent_id: str,
        diff_lines: int,
        diff_limit: int = 100,
        commit_message: str = "",
    ) -> TDDResult:
        """Execute lite verification: modify → verify → commit.
        For non-functional changes (config, docs, UI).
        """
        # Step 1: Diff limit check
        result = self.validate_diff_limit(diff_lines, diff_limit)
        if result.failed:
            return result
        # Step 2: No regression
        result = self.validate_no_regression()
        if result.failed:
            return result
        # Step 3: Commit
        msg = commit_message or f"chore: update for task {task_id}"
        return self.do_commit(msg, agent_id, task_id)
    @staticmethod
    def should_retry(task_retry_count: int, max_retries: int) -> bool:
        """Check if the task should be retried."""
        return task_retry_count < max_retries
    @staticmethod
    def select_mode(tdd_mode: str) -> TDDMode:
        """Convert string mode to enum."""
        return TDDMode(tdd_mode)

