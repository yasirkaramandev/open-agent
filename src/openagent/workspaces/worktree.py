"""Worktree management (spec §28).

Default behavior (``--worktree auto``): for a git repo, snapshot the current commit, create a fresh
branch ``openagent/run_<id>`` and a git *worktree* under ``.openagent/worktrees/run_<id>``, run the
agent there, then let the user apply / merge / discard. Real ``git`` is invoked as a subprocess so
git's own behavior is preserved (spec §4).

Non-git projects fall back to a temporary directory copy, flagged as **lower safety** so the UI can
warn (spec §28).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def is_git_repo(path: Path) -> bool:
    try:
        out = _git(["rev-parse", "--is-inside-work-tree"], path)
        return out.strip() == "true"
    except GitError:
        return False


@dataclass
class Workspace:
    """A prepared place for a run to work in."""

    run_id: str
    root: Path            # where the agent runs (worktree dir, or copy, or the repo itself)
    source: Path          # the user's project root
    is_git: bool
    branch: str | None = None
    base_commit: str | None = None
    is_copy: bool = False  # True when using the non-git temp-copy fallback

    @property
    def lower_safety(self) -> bool:
        return self.is_copy


class WorktreeManager:
    def __init__(self, project_root: Path, worktrees_dir: Path) -> None:
        self.project_root = project_root
        self.worktrees_dir = worktrees_dir

    def create(self, run_id: str, *, use_worktree: bool = True) -> Workspace:
        """Prepare an isolated workspace for ``run_id``."""

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

        if is_git_repo(self.project_root) and use_worktree:
            base_commit = _git(["rev-parse", "HEAD"], self.project_root).strip()
            branch = f"openagent/{run_id}"
            target = self.worktrees_dir / run_id
            _git(["worktree", "add", "-b", branch, str(target), base_commit], self.project_root)
            return Workspace(
                run_id=run_id, root=target, source=self.project_root,
                is_git=True, branch=branch, base_commit=base_commit,
            )

        # Non-git fallback: temp copy (lower safety).
        target = self.worktrees_dir / run_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            self.project_root, target,
            ignore=shutil.ignore_patterns(".git", ".openagent", ".venv", "node_modules", "__pycache__"),
        )
        return Workspace(
            run_id=run_id, root=target, source=self.project_root,
            is_git=is_git_repo(self.project_root), is_copy=True,
        )

    # ------------------------------------------------------------------ inspection

    def changed_files(self, ws: Workspace) -> list[str]:
        if not ws.is_git or ws.is_copy:
            return []
        out = _git(["status", "--porcelain"], ws.root)
        files = []
        for line in out.splitlines():
            if line.strip():
                files.append(line[3:].strip())
        return files

    def diff(self, ws: Workspace) -> str:
        """Combined diff of tracked changes + newly added files in the worktree."""

        if not ws.is_git or ws.is_copy:
            return ""
        _git(["add", "-A", "-N"], ws.root)  # intent-to-add so new files show in diff
        return _git(["diff"], ws.root)

    # ------------------------------------------------------------------ disposition

    def discard(self, ws: Workspace) -> None:
        """Remove the worktree/copy and its branch (spec §28)."""

        if ws.is_copy:
            if ws.root.exists():
                shutil.rmtree(ws.root, ignore_errors=True)
            return
        try:
            _git(["worktree", "remove", "--force", str(ws.root)], self.project_root)
        except GitError:
            if ws.root.exists():
                shutil.rmtree(ws.root, ignore_errors=True)
        if ws.branch:
            try:
                _git(["branch", "-D", ws.branch], self.project_root)
            except GitError:
                pass

    def commit_all(self, ws: Workspace, message: str) -> str | None:
        """Commit everything in the worktree; returns the new commit sha (git only)."""

        if not ws.is_git or ws.is_copy:
            return None
        _git(["add", "-A"], ws.root)
        status = _git(["status", "--porcelain"], ws.root)
        if not status.strip():
            return None
        _git(["commit", "-m", message], ws.root)
        return _git(["rev-parse", "HEAD"], ws.root).strip()
