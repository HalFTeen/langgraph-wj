"""Shared Context - Inter-agent communication via markdown files.
All agents read/write to .nal/context/ directory in the repository.
Files are tracked by git, providing history and audit trail.
Zero extra infrastructure — just markdown files in the repo.
Predefined files (PRD Section 4.3):
- architecture_decisions.md  (Planner writes, everyone reads)
- api_contracts.md           (Coder-to-Coder interface agreements)
- known_issues.md            (Any agent can write)
- exploration_notes.md       (Explorer writes)
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from examples.agent_system.core.git_ops import GitOps
logger = logging.getLogger(__name__)
CONTEXT_DIR = ".nal/context"
PREDEFINED_FILES = [
    "architecture_decisions.md",
    "api_contracts.md",
    "known_issues.md",
    "exploration_notes.md",
]

class SharedContext:
    """Manages the .nal/context/ directory for inter-agent communication.
    Each write automatically commits via GitOps (if provided),
    so all changes are tracked and auditable.
    """
    def __init__(
        self,
        repo_path: str,
        git_ops: GitOps | None = None,
    ) -> None:
        self.repo_path = Path(repo_path)
        self.git_ops = git_ops
        self.context_dir = self.repo_path / CONTEXT_DIR
    def init(self) -> None:
        """Initialize the context directory and predefined files."""
        self.context_dir.mkdir(parents=True, exist_ok=True)
        for filename in PREDEFINED_FILES:
            filepath = self.context_dir / filename
            if not filepath.exists():
                title = filename.replace("_", " ").replace(".md", "").title()
                filepath.write_text(f"# {title}\n\n")
    def read(self, filename: str) -> str:
        """Read a context file. Returns empty string if not found."""
        filepath = self.context_dir / filename
        if not filepath.exists():
            return ""
        return filepath.read_text()
    def write(
        self,
        filename: str,
        content: str,
        agent_id: str = "system",
        auto_commit: bool = True,
    ) -> None:
        """Write content to a context file.
        Overwrites existing content. Auto-commits if GitOps is available.
        """
        self.context_dir.mkdir(parents=True, exist_ok=True)
        filepath = self.context_dir / filename
        filepath.write_text(content)
        if auto_commit and self.git_ops:
            try:
                self.git_ops.commit(
                    message=f"context: update {filename}",
                    agent_id=agent_id,
                    task_id="context",
                )
            except Exception as exc:
                logger.warning("Failed to commit context update: %s", exc)
    def append(
        self,
        filename: str,
        section: str,
        content: str,
        agent_id: str = "system",
        auto_commit: bool = True,
    ) -> None:
        """Append a section to a context file.
        Adds a timestamped entry under the given section heading.
        """
        self.context_dir.mkdir(parents=True, exist_ok=True)
        filepath = self.context_dir / filename
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n## {section}\n\n*{timestamp} by {agent_id}*\n\n{content}\n"
        existing = ""
        if filepath.exists():
            existing = filepath.read_text()
        filepath.write_text(existing + entry)
        if auto_commit and self.git_ops:
            try:
                self.git_ops.commit(
                    message=f"context: append to {filename} [{section}]",
                    agent_id=agent_id,
                    task_id="context",
                )
            except Exception as exc:
                logger.warning("Failed to commit context append: %s", exc)
    def list_files(self) -> list[str]:
        """List all context files."""
        if not self.context_dir.exists():
            return []
        return [f.name for f in self.context_dir.iterdir() if f.is_file()]
    def exists(self, filename: str) -> bool:
        """Check if a context file exists."""
        return (self.context_dir / filename).exists()

