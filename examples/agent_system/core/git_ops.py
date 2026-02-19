"""GitOps - Git operations and coordination for multi-agent collaboration.
Manages branches, locks, worktrees, commits, and merges.
Uses subprocess to call git commands directly (simple, controllable).
Lock storage via git tags (zero extra infrastructure).
"""
from __future__ import annotations
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

class GitOpsError(Exception):
    """Raised for git operation failures."""

@dataclass
class BranchLock:
    """Represents a branch lock held by an agent.
    Tag format: lock/<branch>/<agent_id>/<expires_at>
    expires_at is a Unix timestamp. The lock is expired when time.time() > expires_at.
    """
    branch: str
    agent_id: str
    acquired_at: float  # Unix timestamp
    expires_at: float  # Unix timestamp
    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    def to_tag_name(self) -> str:
        return f"lock/{self.branch}/{self.agent_id}/{int(self.expires_at)}"
    @classmethod
    def from_tag_name(cls, tag: str) -> BranchLock | None:
        parts = tag.split("/")
        if len(parts) < 4 or parts[0] != "lock":
            return None
        # lock/<branch-parts>/<agent_id>/<expires_at>
        # Branch can contain slashes, so we join all middle parts
        expires_str = parts[-1]
        agent_id = parts[-2]
        branch = "/".join(parts[1:-2])
        try:
            expires_at = float(expires_str)
        except ValueError:
            return None
        return cls(
            branch=branch,
            agent_id=agent_id,
            acquired_at=0.0,  # not recoverable from tag
            expires_at=expires_at,
        )

@dataclass
class MergeResult:
    """Result of a merge operation."""
    success: bool
    commit_hash: str | None = None
    conflicts: list[str] | None = None
    error: str | None = None

class GitOps:
    """Git operations for NAL multi-agent coordination.
    All operations use subprocess for simplicity and control.
    Lock mechanism uses git tags (zero extra infrastructure).
    Branch naming convention (PRD Section 3.2):
        task/issue-{id}                  # top-level task branch
        task/issue-{id}/step-{NNN}       # leaf task branch
        self-improve/proposal-{NNN}      # self-improvement branch
    """
    def __init__(self, repo_path: str, remote_url: str | None = None) -> None:
        self.repo_path = Path(repo_path)
        self.remote_url = remote_url
        self._default_lock_ttl = 600
        if not (self.repo_path / ".git").exists():
            if not self.repo_path.exists():
                raise GitOpsError(f"Path does not exist: {repo_path}")
            # Could be a worktree - check for .git file
            git_file = self.repo_path / ".git"
            if not git_file.exists():
                raise GitOpsError(f"Not a git repository: {repo_path}")
    # --- Branch operations ---
    def get_default_branch(self) -> str:
        """Detect the default branch name (main or master)."""
        branches = self.list_branches()
        for candidate in ("main", "master"):
            if candidate in branches:
                return candidate
        return branches[0] if branches else "main"
    def create_branch(self, name: str, base: str = "") -> None:
        """Create a new branch from base. Auto-detects default branch if base is empty."""
        if not base:
            base = self.get_default_branch()
        self._run(["git", "checkout", "-b", name, base])
    def delete_branch(self, name: str) -> None:
        """Delete a branch (safe, fails if not fully merged)."""
        self._run(["git", "branch", "-d", name])
    def delete_branch_force(self, name: str) -> None:
        """Force delete a branch."""
        self._run(["git", "branch", "-D", name])
    def list_branches(self) -> list[str]:
        """List all local branches."""
        result = self._run(["git", "branch", "--format=%(refname:short)"])
        return [b.strip() for b in result.stdout.strip().split("\n") if b.strip()]
    def get_current_branch(self) -> str:
        """Get current branch name."""
        result = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        return result.stdout.strip()
    def checkout(self, branch: str) -> None:
        """Switch to a branch."""
        self._run(["git", "checkout", branch])
    # --- Worktree management ---
    def create_worktree(self, branch: str, path: str) -> str:
        """Create a git worktree for a branch. Returns the worktree path."""
        worktree_path = Path(path)
        self._run(["git", "worktree", "add", str(worktree_path), branch])
        return str(worktree_path)
    def remove_worktree(self, path: str) -> None:
        """Remove a git worktree."""
        self._run(["git", "worktree", "remove", path, "--force"])
    def list_worktrees(self) -> list[dict[str, str]]:
        """List all worktrees."""
        result = self._run(["git", "worktree", "list", "--porcelain"])
        worktrees = []
        current: dict[str, str] = {}
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree ") :]
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD ") :]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch ") :]
            elif line == "bare":
                current["bare"] = "true"
        if current:
            worktrees.append(current)
        return worktrees
    # --- Lock mechanism (git tags) ---
    def acquire_lock(
        self, branch: str, agent_id: str, ttl: int | None = None
    ) -> bool:
        """Acquire a branch lock. Returns False if already locked by another agent."""
        ttl = ttl or self._default_lock_ttl
        existing = self.is_locked(branch)
        if existing is not None:
            if existing.agent_id == agent_id:
                return True  # Already locked by this agent
            if existing.is_expired:
                self._delete_lock_tag(existing)
            else:
                return False  # Locked by another agent
        now = time.time()
        lock = BranchLock(
            branch=branch,
            agent_id=agent_id,
            acquired_at=now,
            expires_at=now + ttl,
        )
        tag_name = lock.to_tag_name()
        try:
            self._run(["git", "tag", tag_name])
            return True
        except GitOpsError:
            return False
    def release_lock(self, branch: str, agent_id: str) -> bool:
        """Release a branch lock. Returns False if not locked by this agent."""
        existing = self.is_locked(branch)
        if existing is None:
            return False
        if existing.agent_id != agent_id:
            return False
        self._delete_lock_tag(existing)
        return True
    def is_locked(self, branch: str) -> BranchLock | None:
        """Check if a branch is locked. Returns the lock or None."""
        tags = self._get_lock_tags()
        for tag in tags:
            lock = BranchLock.from_tag_name(tag)
            if lock and lock.branch == branch:
                return lock
        return None
    def cleanup_expired_locks(self) -> list[str]:
        """Remove all expired lock tags. Returns list of cleaned branch names."""
        cleaned = []
        tags = self._get_lock_tags()
        for tag in tags:
            lock = BranchLock.from_tag_name(tag)
            if lock and lock.is_expired:
                self._delete_lock_tag(lock)
                cleaned.append(lock.branch)
        return cleaned
    # --- Commit operations ---
    def commit(
        self,
        message: str,
        agent_id: str,
        task_id: str,
        step_info: str | None = None,
    ) -> str:
        """Commit staged changes with NAL metadata. Returns commit hash.
        Commit message format (PRD Section 3.2):
            <type>(<scope>): <description>
            Agent: <agent_id>
            Task: <task_id>
            Step: <step_info>
        """
        full_message = f"{message}\n\nAgent: {agent_id}\nTask: {task_id}"
        if step_info:
            full_message += f"\nStep: {step_info}"
        self._run(["git", "add", "-A"])
        self._run(["git", "commit", "-m", full_message])
        result = self._run(["git", "rev-parse", "HEAD"])
        return result.stdout.strip()
    def stage_files(self, files: list[str]) -> None:
        """Stage specific files."""
        self._run(["git", "add"] + files)
    def get_diff_stats(self) -> dict[str, int]:
        """Get diff statistics for staged changes."""
        result = self._run(["git", "diff", "--cached", "--stat"])
        stats: dict[str, int] = {"files_changed": 0, "insertions": 0, "deletions": 0}
        lines = result.stdout.strip().split("\n")
        if lines and lines[-1]:
            summary = lines[-1]
            parts = summary.split(",")
            for part in parts:
                part = part.strip()
                if "file" in part:
                    stats["files_changed"] = int(part.split()[0])
                elif "insertion" in part:
                    stats["insertions"] = int(part.split()[0])
                elif "deletion" in part:
                    stats["deletions"] = int(part.split()[0])
        return stats
    def get_diff_line_count(self) -> int:
        """Get total number of changed lines (insertions + deletions)."""
        stats = self.get_diff_stats()
        return stats["insertions"] + stats["deletions"]
    # --- Remote operations ---
    def push(self, branch: str | None = None) -> None:
        """Push to remote."""
        cmd = ["git", "push"]
        if branch:
            cmd += ["origin", branch]
        self._run(cmd)
    def pull(self, branch: str | None = None) -> None:
        """Pull from remote."""
        cmd = ["git", "pull"]
        if branch:
            cmd += ["origin", branch]
        self._run(cmd)
    def setup_remote(self, url: str, name: str = "origin") -> None:
        """Add or update a remote."""
        try:
            self._run(["git", "remote", "add", name, url])
        except GitOpsError:
            self._run(["git", "remote", "set-url", name, url])
    # --- Merge operations ---
    def rebase(self, branch: str, onto: str = "main") -> bool:
        """Rebase branch onto target. Returns True if successful."""
        original = self.get_current_branch()
        try:
            self.checkout(branch)
            result = self._run(
                ["git", "rebase", onto],
                check=False,
            )
            if result.returncode != 0:
                self._run(["git", "rebase", "--abort"], check=False)
                return False
            return True
        finally:
            if self.get_current_branch() != original:
                try:
                    self.checkout(original)
                except GitOpsError:
                    pass
    def pull_rebase(self, branch: str = "main") -> bool:
        """Pull with rebase to sync with remote. Returns True if successful."""
        original = self.get_current_branch()
        try:
            self.checkout(branch)
            result = self._run(
                ["git", "pull", "--rebase", "origin", branch],
                check=False,
            )
            if result.returncode != 0:
                self._run(["git", "rebase", "--abort"], check=False)
                return False
            return True
        except GitOpsError:
            return False
        finally:
            if self.get_current_branch() != original:
                try:
                    self.checkout(original)
                except GitOpsError:
                    pass
    def merge(self, source: str, target: str) -> MergeResult:
        """Merge source branch into target branch.
        Strategy: first try normal merge, if conflict try auto-resolve
        favoring the source branch (task branch has latest work).
        """
        original_branch = self.get_current_branch()
        try:
            self.checkout(target)
            result = self._run(
                ["git", "merge", source, "--no-ff"],
                check=False,
            )
            if result.returncode != 0:
                conflicts = self._get_conflict_files()
                if conflicts:
                    # Abort and retry with auto-resolve favoring task branch
                    self._run(["git", "merge", "--abort"])
                    result2 = self._run(
                        ["git", "merge", source, "--no-ff", "-X", "theirs"],
                        check=False,
                    )
                    if result2.returncode == 0:
                        commit_hash = self._run(
                            ["git", "rev-parse", "HEAD"]
                        ).stdout.strip()
                        return MergeResult(success=True, commit_hash=commit_hash)
                    # Still failed, abort
                    self._run(["git", "merge", "--abort"], check=False)
                    return MergeResult(
                        success=False,
                        conflicts=conflicts,
                        error="Merge conflicts (auto-resolve failed)",
                    )
                return MergeResult(success=False, error=result.stderr.strip())
            commit_hash = self._run(
                ["git", "rev-parse", "HEAD"]
            ).stdout.strip()
            return MergeResult(success=True, commit_hash=commit_hash)
        finally:
            if self.get_current_branch() != original_branch:
                try:
                    self.checkout(original_branch)
                except GitOpsError:
                    pass
    def has_conflicts(self, source: str, target: str) -> bool:
        """Check if merging source into target would cause conflicts (dry run)."""
        try:
            self._run(["git", "merge-tree", target, source])
            return False
        except GitOpsError:
            return True
    # --- Utility ---
    def get_log(self, n: int = 10) -> list[dict[str, str]]:
        """Get recent commit log."""
        fmt = "%H%n%an%n%s%n---"
        result = self._run(
            ["git", "log", f"-{n}", f"--format={fmt}"]
        )
        commits = []
        lines = result.stdout.strip().split("\n---\n")
        for entry in lines:
            parts = entry.strip().split("\n")
            if len(parts) >= 3:
                commits.append(
                    {"hash": parts[0], "author": parts[1], "message": parts[2]}
                )
        return commits
    def get_status(self) -> dict[str, Any]:
        """Get repo status summary."""
        branch = self.get_current_branch()
        result = self._run(["git", "status", "--porcelain"])
        changed = [
            line.strip() for line in result.stdout.strip().split("\n") if line.strip()
        ]
        return {
            "branch": branch,
            "changed_files": len(changed),
            "clean": len(changed) == 0,
        }
    # --- Private helpers ---
    def _run(
        self,
        cmd: list[str],
        check: bool = True,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a git command."""
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if check and result.returncode != 0:
                raise GitOpsError(
                    f"Git command failed: {' '.join(cmd)}\n"
                    f"stderr: {result.stderr.strip()}"
                )
            return result
        except subprocess.TimeoutExpired as exc:
            raise GitOpsError(f"Git command timed out: {' '.join(cmd)}") from exc
        except FileNotFoundError as exc:
            raise GitOpsError(f"Git not found: {exc}") from exc
    def _get_lock_tags(self) -> list[str]:
        """Get all lock tags."""
        try:
            result = self._run(["git", "tag", "-l", "lock/*"])
            return [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]
        except GitOpsError:
            return []
    def _delete_lock_tag(self, lock: BranchLock) -> None:
        """Delete a lock tag."""
        tag_name = lock.to_tag_name()
        try:
            self._run(["git", "tag", "-d", tag_name])
        except GitOpsError:
            pass
    def _get_conflict_files(self) -> list[str]:
        """Get list of files with merge conflicts."""
        try:
            result = self._run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                check=False,
            )
            return [
                f.strip()
                for f in result.stdout.strip().split("\n")
                if f.strip()
            ]
        except GitOpsError:
            return []

# --- Branch name helpers ---

def task_branch_name(issue_id: str | int) -> str:
    """Generate top-level task branch name."""
    return f"task/issue-{issue_id}"

def step_branch_name(issue_id: str | int, step: int) -> str:
    """Generate leaf task branch name."""
    return f"task/issue-{issue_id}/step-{step:03d}"

def self_improve_branch_name(proposal_id: int) -> str:
    """Generate self-improvement branch name."""
    return f"self-improve/proposal-{proposal_id:03d}"

