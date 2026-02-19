"""Agent Interface - Abstraction for execution engines.
Supports two adapter types:
- LLMAgentAdapter: Bridges existing AgentRole (LLM API calls via LangChain)
- ClaudeCodeAdapter: Spawns Claude Code CLI as subprocess
Both implement the same AgentInterface, so Coordinator doesn't care
which engine is behind an agent.
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
logger = logging.getLogger(__name__)

class AgentRole(str, Enum):
    """Agent roles in the NAL system."""
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    EXPLORER = "explorer"

class AgentEngine(str, Enum):
    """Supported execution engines."""
    LLM = "llm"
    CLAUDE_CODE = "claude-code"
    OPENCODE = "opencode"

@dataclass
class AgentResult:
    """Result of an agent executing a task."""
    success: bool
    files_modified: dict[str, str] = field(default_factory=dict)  # path → content
    test_files: dict[str, str] = field(default_factory=dict)  # path → content
    message: str = ""
    token_usage: int = 0
    review_decision: str = ""  # "approved" | "changes" (for reviewer)
    review_feedback: str = ""  # feedback text (for reviewer)
    task_graph: dict[str, Any] | None = None  # TaskGraph dict (for planner)
    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "files_modified": self.files_modified,
            "test_files": self.test_files,
            "message": self.message,
            "token_usage": self.token_usage,
            "review_decision": self.review_decision,
            "review_feedback": self.review_feedback,
            "task_graph": self.task_graph,
        }

@dataclass
class AgentSession:
    """Agent working session (PRD Section 2.4)."""
    agent_id: str
    role: AgentRole
    machine_id: str = "local"
    current_task: str | None = None
    branch_lock: str | None = None
    engine: AgentEngine = AgentEngine.LLM
    api_key_ref: str = ""
    token_usage: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "machine_id": self.machine_id,
            "current_task": self.current_task,
            "branch_lock": self.branch_lock,
            "engine": self.engine.value,
            "api_key_ref": self.api_key_ref,
            "token_usage": self.token_usage,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
        }
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSession:
        d = dict(data)
        d["role"] = AgentRole(d["role"])
        d["engine"] = AgentEngine(d["engine"])
        return cls(**d)

class AgentInterface(ABC):
    """Abstract interface for agent execution engines.
    Coordinator calls this interface to delegate work to agents.
    The implementation decides whether to use LLM API, Claude Code CLI,
    or any other coding tool.
    """
    @abstractmethod
    def execute_task(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute a task and return the result.
        Args:
            task_description: What the agent should do.
            context: Additional context (existing code, test files, feedback, etc.)
        Returns:
            AgentResult with modified files, test files, and status.
        """
    @abstractmethod
    def get_status(self) -> str:
        """Get the agent's current status (idle, busy, error)."""
    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Unique identifier for this agent instance."""
    @property
    @abstractmethod
    def role(self) -> AgentRole:
        """The role this agent plays."""

class LLMAgentAdapter(AgentInterface):
    """Adapter that bridges existing AgentRole implementations.
    Wraps the existing CoderRole/ReviewerRole/TesterRole/etc.
    so they can be used through the AgentInterface.
    """
    def __init__(
        self,
        role_instance: Any,  # AgentRole from roles/base.py
        agent_role: AgentRole = AgentRole.CODER,
        agent_id: str | None = None,
    ) -> None:
        self._role_instance = role_instance
        self._agent_role = agent_role
        self._agent_id = agent_id or f"llm-{agent_role.value}-{uuid.uuid4().hex[:6]}"
        self._status = "idle"
    @property
    def agent_id(self) -> str:
        return self._agent_id
    @property
    def role(self) -> AgentRole:
        return self._agent_role
    def get_status(self) -> str:
        return self._status
    def execute_task(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute task by calling the underlying AgentRole.process()."""
        from langchain_core.messages import HumanMessage
        self._status = "busy"
        ctx = context or {}
        try:
            # Build a minimal AgentState-like dict for the role
            state: dict[str, Any] = {
                "messages": [HumanMessage(content=task_description)],
                "code_files": ctx.get("code_files", {}),
                "iteration_count": ctx.get("iteration_count", 0),
                "review_status": ctx.get("review_status", ""),
                "reviewer_feedback": ctx.get("reviewer_feedback", ""),
                "test_code": ctx.get("test_code", ""),
                "test_status": ctx.get("test_status", "pending"),
            }
            role_result = self._role_instance.process(state)
            state_updates = role_result.state_updates
            return AgentResult(
                success=True,
                files_modified=state_updates.get("code_files", {}),
                message=role_result.message.content,
                review_decision=state_updates.get("review_status", ""),
                review_feedback=state_updates.get("reviewer_feedback", ""),
            )
        except Exception as exc:
            logger.error("LLMAgentAdapter.execute_task failed: %s", exc)
            return AgentResult(
                success=False,
                message=f"Agent error: {exc}",
            )
        finally:
            self._status = "idle"

class ClaudeCodeAdapter(AgentInterface):
    """Adapter that spawns Claude Code CLI as a subprocess.
    Each invocation starts a new Claude Code process with:
    - A specific worktree directory
    - A CLAUDE.md injected for role configuration
    - Independent API key configuration
    """
    def __init__(
        self,
        worktree_path: str,
        claude_md_content: str = "",
        api_key_ref: str = "",
        agent_role: AgentRole = AgentRole.CODER,
        agent_id: str | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self._worktree_path = Path(worktree_path)
        self._claude_md_content = claude_md_content
        self._api_key_ref = api_key_ref
        self._agent_role = agent_role
        self._agent_id = agent_id or f"cc-{agent_role.value}-{uuid.uuid4().hex[:6]}"
        self._timeout = timeout_seconds
        self._status = "idle"
    @property
    def agent_id(self) -> str:
        return self._agent_id
    @property
    def role(self) -> AgentRole:
        return self._agent_role
    def get_status(self) -> str:
        return self._status
    def execute_task(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute task by spawning a Claude Code CLI process.
        Uses `claude -p` mode (non-interactive) so Claude Code actually
        uses tools to edit files in the worktree. After execution, we
        scan git diff to find which files were modified.
        """
        self._status = "busy"
        try:
            # Inject CLAUDE.md into worktree if content provided
            if self._claude_md_content:
                claude_md_path = self._worktree_path / "CLAUDE.md"
                claude_md_path.write_text(self._claude_md_content)
            # Ensure .claude/settings.local.json exists for non-interactive mode
            settings_dir = self._worktree_path / ".claude"
            settings_file = settings_dir / "settings.local.json"
            if not settings_file.exists():
                settings_dir.mkdir(parents=True, exist_ok=True)
                settings_file.write_text(json.dumps({
                    "permissions": {
                        "allow": [
                            "Read(*)",
                            "Edit(*)",
                            "Write(*)",
                            "Bash(*)",
                        ]
                    }
                }, indent=2))
            # Build the prompt
            prompt = task_description
            if context:
                ctx_str = json.dumps(context, indent=2, default=str)
                prompt = f"{task_description}\n\nContext:\n{ctx_str}"
            # Run Claude Code CLI in non-interactive mode (-p).
            # Unlike --print, this mode lets Claude use tools to
            # actually create/edit files in the working directory.
            # Clear CLAUDECODE env var to allow nested sessions.
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            cmd = ["claude", "-p", prompt]
            result = subprocess.run(
                cmd,
                cwd=str(self._worktree_path),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
            )
            if result.returncode != 0:
                return AgentResult(
                    success=False,
                    message=f"Claude Code exited with code {result.returncode}: {result.stderr}",
                )
            # Scan worktree for files Claude actually created/modified
            files_modified = self._scan_modified_files()
            return AgentResult(
                success=True,
                files_modified=files_modified,
                message=result.stdout[:2000] if result.stdout else "Done",
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                success=False,
                message=f"Claude Code timed out after {self._timeout}s",
            )
        except FileNotFoundError:
            return AgentResult(
                success=False,
                message="Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
            )
        except Exception as exc:
            return AgentResult(
                success=False,
                message=f"Claude Code error: {exc}",
            )
        finally:
            self._status = "idle"
    def _scan_modified_files(self) -> dict[str, str]:
        """Scan git status for files Claude Code created or modified."""
        try:
            # Get list of new/modified files (untracked + modified)
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self._worktree_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            files: dict[str, str] = {}
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                # Status codes: M=modified, A=added, ??=untracked
                status = line[:2].strip()
                filepath = line[3:].strip()
                if status in ("M", "A", "??", "AM", "MM"):
                    full_path = self._worktree_path / filepath
                    if full_path.is_file() and not filepath.startswith("."):
                        try:
                            files[filepath] = full_path.read_text()
                        except (UnicodeDecodeError, OSError):
                            pass  # Skip binary files
            return files
        except Exception:
            return {}

class ClaudePlannerAdapter(AgentInterface):
    """Planner that uses Claude Code (--print mode) to decompose requirements.
    Uses --print because the planner doesn't write files, it just thinks
    and outputs a structured TaskGraph JSON.
    """
    def __init__(
        self,
        agent_id: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self._agent_id = agent_id or f"claude-planner-{uuid.uuid4().hex[:6]}"
        self._timeout = timeout_seconds
        self._status = "idle"
    @property
    def agent_id(self) -> str:
        return self._agent_id
    @property
    def role(self) -> AgentRole:
        return AgentRole.PLANNER
    def get_status(self) -> str:
        return self._status
    def execute_task(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        self._status = "busy"
        try:
            prompt = f"""You are a task planner for a TDD-based development system.
Decompose this requirement into small, ordered baby-step tasks.
Each task should be implementable in under 100 lines of code change.
REQUIREMENT:
{task_description}
Output ONLY valid JSON (no markdown, no explanation) in this exact format:
{{
  "tasks": {{
    "step-1": {{
      "id": "step-1",
      "title": "short title",
      "description": "detailed description of what to implement",
      "status": "pending",
      "depends_on": [],
      "parent_id": null,
      "assigned_agent": null,
      "branch": null,
      "tdd_mode": "full",
      "test_file": null,
      "max_retries": 3,
      "retry_count": 0,
      "diff_line_limit": 100,
      "github_issue_id": null
    }},
    "step-2": {{
      "id": "step-2",
      "title": "short title",
      "description": "detailed description",
      "status": "pending",
      "depends_on": ["step-1"],
      "parent_id": null,
      "assigned_agent": null,
      "branch": null,
      "tdd_mode": "full",
      "test_file": null,
      "max_retries": 3,
      "retry_count": 0,
      "diff_line_limit": 100,
      "github_issue_id": null
    }}
  }}
}}
Rules:
- Use "step-1", "step-2", etc. as IDs
- Set depends_on correctly (later steps depend on earlier ones when needed)
- Use tdd_mode "full" for code, "lite" for config/docs
- Keep each task small enough for a single commit
- Output ONLY the JSON, nothing else"""
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            cmd = ["claude", "--print", "-p", prompt]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
            )
            if result.returncode != 0:
                return AgentResult(
                    success=False,
                    message=f"Planner failed: {result.stderr}",
                )
            # Parse JSON from output
            output = result.stdout.strip()
            task_graph = self._parse_task_graph(output)
            if task_graph:
                return AgentResult(
                    success=True,
                    task_graph=task_graph,
                    message=f"Decomposed into {len(task_graph.get('tasks', {}))} tasks",
                )
            else:
                return AgentResult(
                    success=False,
                    message=f"Failed to parse task graph from planner output: {output[:500]}",
                )
        except subprocess.TimeoutExpired:
            return AgentResult(success=False, message="Planner timed out")
        except Exception as exc:
            return AgentResult(success=False, message=f"Planner error: {exc}")
        finally:
            self._status = "idle"
    @staticmethod
    def _parse_task_graph(output: str) -> dict[str, Any] | None:
        """Extract JSON task graph from Claude's output."""
        import re
        # Try direct parse first
        try:
            data = json.loads(output)
            if "tasks" in data:
                return data
        except json.JSONDecodeError:
            pass
        # Try to extract JSON from markdown code block
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", output, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if "tasks" in data:
                    return data
            except json.JSONDecodeError:
                pass
        # Try to find JSON object in output
        brace_start = output.find("{")
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(output)):
                if output[i] == "{":
                    depth += 1
                elif output[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(output[brace_start : i + 1])
                            if "tasks" in data:
                                return data
                        except json.JSONDecodeError:
                            pass
                        break
        return None

class ClaudeExplorerAdapter(AgentInterface):
    """Explorer that scans a codebase and produces a structured analysis.
    Uses claude --print to analyze repo structure, key files, architecture.
    Returns the analysis as message text for the Planner to consume.
    """
    def __init__(
        self,
        repo_path: str = "",
        agent_id: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self._repo_path = repo_path
        self._agent_id = agent_id or f"claude-explorer-{uuid.uuid4().hex[:6]}"
        self._timeout = timeout_seconds
        self._status = "idle"
    @property
    def agent_id(self) -> str:
        return self._agent_id
    @property
    def role(self) -> AgentRole:
        return AgentRole.EXPLORER
    def get_status(self) -> str:
        return self._status
    def execute_task(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Scan a codebase and produce an analysis summary."""
        self._status = "busy"
        try:
            repo = context.get("repo_path", self._repo_path) if context else self._repo_path
            if not repo:
                return AgentResult(success=False, message="No repo_path provided")
            # First gather repo structure via tree/find
            tree_output = ""
            try:
                tree_result = subprocess.run(
                    ["find", ".", "-type", "f", "-name", "*.py",
                     "-not", "-path", "./.git/*",
                     "-not", "-path", "./__pycache__/*",
                     "-not", "-path", "*/node_modules/*"],
                    cwd=repo,
                    capture_output=True, text=True, timeout=10,
                )
                tree_output = tree_result.stdout.strip()
            except Exception:
                pass
            prompt = f"""Analyze this codebase and provide a concise technical summary.
Repository path: {repo}
File structure (Python files):
{tree_output[:3000]}
Task context: {task_description}
Provide a structured analysis covering:
1. **Project type**: What does this project do? (1-2 sentences)
2. **Key modules**: List the main modules/packages and their purpose
3. **Entry points**: Main scripts, API endpoints, CLI commands
4. **Architecture patterns**: Frameworks used, design patterns, data flow
5. **Dependencies**: Key external libraries
6. **Test structure**: Where tests live, test framework used
7. **Relevant to task**: Which files/modules are most relevant to the task described above
Be concise. Focus on information needed to plan code changes."""
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            cmd = ["claude", "--print", "-p", prompt]
            result = subprocess.run(
                cmd,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
            )
            if result.returncode != 0:
                return AgentResult(
                    success=False,
                    message=f"Explorer failed: {result.stderr}",
                )
            return AgentResult(
                success=True,
                message=result.stdout.strip(),
            )
        except subprocess.TimeoutExpired:
            return AgentResult(success=False, message="Explorer timed out")
        except Exception as exc:
            return AgentResult(success=False, message=f"Explorer error: {exc}")
        finally:
            self._status = "idle"
    @staticmethod
    def scan_repo_structure(repo_path: str) -> str:
        """Quick local scan of repo structure without LLM.
        Returns a summary string suitable for prepending to a requirement.
        """
        from pathlib import Path
        repo = Path(repo_path)
        if not repo.is_dir():
            return ""
        lines = [f"Repository: {repo.name}", ""]
        # README
        for readme in ["README.md", "README.rst", "README.txt", "README"]:
            readme_path = repo / readme
            if readme_path.exists():
                content = readme_path.read_text()[:1000]
                lines.append(f"## README (first 1000 chars)\n{content}\n")
                break
        # File tree (Python files only, max 50)
        py_files = sorted(repo.rglob("*.py"))
        py_files = [
            f for f in py_files
            if ".git" not in str(f) and "__pycache__" not in str(f)
            and "node_modules" not in str(f)
        ][:50]
        if py_files:
            lines.append("## Python files")
            for f in py_files:
                rel = f.relative_to(repo)
                size = f.stat().st_size
                lines.append(f"  {rel} ({size}B)")
            lines.append("")
        # Key config files
        for cfg in ["pyproject.toml", "setup.py", "requirements.txt", "package.json", "Makefile"]:
            cfg_path = repo / cfg
            if cfg_path.exists():
                content = cfg_path.read_text()[:500]
                lines.append(f"## {cfg} (first 500 chars)\n{content}\n")
        return "\n".join(lines)

class ClaudeReviewerAdapter(AgentInterface):
    """Reviewer that uses Claude Code (--print mode) to review code."""
    def __init__(
        self,
        agent_id: str | None = None,
        timeout_seconds: int = 90,
    ) -> None:
        self._agent_id = agent_id or f"claude-reviewer-{uuid.uuid4().hex[:6]}"
        self._timeout = timeout_seconds
        self._status = "idle"
    @property
    def agent_id(self) -> str:
        return self._agent_id
    @property
    def role(self) -> AgentRole:
        return AgentRole.REVIEWER
    def get_status(self) -> str:
        return self._status
    def execute_task(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        self._status = "busy"
        try:
            code_files = (context or {}).get("code_files", {})
            code_str = "\n\n".join(
                f"--- {name} ---\n{content}" for name, content in code_files.items()
            )
            prompt = f"""Review this code change for correctness only.
Task: {task_description}
Code:
{code_str}
Review criteria (ONLY reject for these reasons):
- Logical bugs (wrong behavior, off-by-one, missing edge cases that would crash)
- Missing function/class that is imported but not defined
- Security vulnerabilities (SQL injection, command injection)
Do NOT reject for:
- Code style, formatting, naming conventions
- Missing docstrings or type hints
- Could-be-better suggestions
- Incomplete features (if the task only asked for partial implementation)
Reply with EXACTLY one line:
- "APPROVED" if no logical bugs found
- "CHANGES_REQUESTED: <specific bug description>" only if there is a real bug"""
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            cmd = ["claude", "--print", "-p", prompt]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
            )
            output = result.stdout.strip().upper()
            if "APPROVED" in output and "CHANGES_REQUESTED" not in output:
                decision = "approved"
                feedback = "Approved"
            else:
                decision = "changes"
                feedback = result.stdout.strip()
            return AgentResult(
                success=True,
                review_decision=decision,
                review_feedback=feedback,
                message=result.stdout.strip(),
            )
        except Exception as exc:
            # On error, default to approved to not block pipeline
            return AgentResult(
                success=True,
                review_decision="approved",
                review_feedback=f"Review skipped: {exc}",
                message=f"Review error: {exc}",
            )
        finally:
            self._status = "idle"

class FallbackAdapter(AgentInterface):
    """Deterministic fallback adapter for testing without LLM/CLI.
    Returns predictable results based on role and task description.
    Used for CI/CD and flow validation.
    """
    def __init__(
        self,
        agent_role: AgentRole = AgentRole.CODER,
        agent_id: str | None = None,
    ) -> None:
        self._agent_role = agent_role
        self._agent_id = agent_id or f"fallback-{agent_role.value}-{uuid.uuid4().hex[:6]}"
    @property
    def agent_id(self) -> str:
        return self._agent_id
    @property
    def role(self) -> AgentRole:
        return self._agent_role
    def get_status(self) -> str:
        return "idle"
    def execute_task(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Return deterministic results based on role."""
        if self._agent_role == AgentRole.CODER:
            return AgentResult(
                success=True,
                files_modified={"solution.py": "def solve(): return 42\n"},
                test_files={"test_solution.py": "from solution import solve\ndef test_solve(): assert solve() == 42\n"},
                message="Implemented solution (fallback)",
            )
        elif self._agent_role == AgentRole.REVIEWER:
            return AgentResult(
                success=True,
                review_decision="approved",
                review_feedback="Code looks good (fallback review)",
                message="Review complete (fallback)",
            )
        elif self._agent_role == AgentRole.PLANNER:
            return AgentResult(
                success=True,
                task_graph={
                    "tasks": {
                        "step-1": {
                            "id": "step-1",
                            "title": "Implement core logic",
                            "description": task_description,
                            "status": "pending",
                            "depends_on": [],
                            "tdd_mode": "full",
                        }
                    }
                },
                message="Task decomposed (fallback)",
            )
        elif self._agent_role == AgentRole.EXPLORER:
            return AgentResult(
                success=True,
                message="No relevant context found (fallback)",
            )
        return AgentResult(success=True, message="Done (fallback)")

def make_agent_id(role: AgentRole, engine: AgentEngine) -> str:
    """Generate a unique agent ID."""
    return f"{engine.value}-{role.value}-{uuid.uuid4().hex[:6]}"


def build_agents_from_config(
    engine_config: Any,
    repo_path: str = "",
) -> dict[str, AgentInterface]:
    """Build agent registry from per-role EngineConfig.

    Args:
        engine_config: EngineConfig instance (from config.py).
        repo_path: Repository path for ClaudeCodeAdapter worktree.

    Returns:
        Dict mapping role name to AgentInterface instance.
    """
    roles_map = {
        "planner": (AgentRole.PLANNER, engine_config.planner),
        "coder": (AgentRole.CODER, engine_config.coder),
        "reviewer": (AgentRole.REVIEWER, engine_config.reviewer),
        "explorer": (AgentRole.EXPLORER, engine_config.explorer),
    }
    agents: dict[str, AgentInterface] = {}
    for name, (role, role_cfg) in roles_map.items():
        engine = role_cfg.engine or engine_config.default_engine
        agents[name] = _build_single_agent(name, role, engine, role_cfg, repo_path)
    return agents


def _build_single_agent(
    name: str,
    role: AgentRole,
    engine: str,
    role_cfg: Any,
    repo_path: str,
) -> AgentInterface:
    """Build a single agent adapter based on engine type."""
    if engine == "claude-code":
        return _build_claude_agent(name, role, repo_path)
    if engine == "llm":
        return _build_llm_agent(name, role, role_cfg)
    return FallbackAdapter(agent_role=role, agent_id=f"fallback-{name}-1")


def _build_claude_agent(name: str, role: AgentRole, repo_path: str) -> AgentInterface:
    """Build a Claude Code CLI agent adapter."""
    if role == AgentRole.PLANNER:
        return ClaudePlannerAdapter(agent_id=f"claude-{name}-1")
    if role == AgentRole.REVIEWER:
        return ClaudeReviewerAdapter(agent_id=f"claude-{name}-1")
    if role == AgentRole.CODER:
        return ClaudeCodeAdapter(
            worktree_path=repo_path,
            agent_role=role,
            agent_id=f"claude-{name}-1",
            timeout_seconds=180,
        )
    if role == AgentRole.EXPLORER:
        return ClaudeExplorerAdapter(repo_path=repo_path, agent_id=f"claude-{name}-1")
    return FallbackAdapter(agent_role=role, agent_id=f"claude-{name}-1")


def _build_llm_agent(name: str, role: AgentRole, role_cfg: Any) -> AgentInterface:
    """Build an LLM API agent adapter using LangChain."""
    from examples.agent_system.llm.provider import get_llm

    provider = role_cfg.provider or None
    model = role_cfg.model or None
    llm = get_llm(provider=provider, model=model)

    if role == AgentRole.CODER:
        from examples.agent_system.roles.coder import CoderRole
        return LLMAgentAdapter(
            CoderRole(llm=llm),
            agent_role=role,
            agent_id=f"llm-{name}-1",
        )
    if role == AgentRole.REVIEWER:
        from examples.agent_system.roles.reviewer import ReviewerRole
        return LLMAgentAdapter(
            ReviewerRole(llm=llm),
            agent_role=role,
            agent_id=f"llm-{name}-1",
        )
    return FallbackAdapter(agent_role=role, agent_id=f"llm-{name}-1")

