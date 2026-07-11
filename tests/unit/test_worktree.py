import subprocess
from pathlib import Path

import pytest

from openagent.workspaces.worktree import WorktreeManager, is_git_repo


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture()
def git_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@t.com"], root)
    _git(["config", "user.name", "t"], root)
    (root / "main.py").write_text("print('v1')\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "init"], root)
    return root


def test_creates_worktree_and_branch(git_project: Path):
    mgr = WorktreeManager(git_project, git_project / ".openagent" / "worktrees")
    ws = mgr.create("run_01ABC")
    assert ws.is_git and not ws.is_copy
    assert ws.branch == "openagent/run_01ABC"
    assert (ws.root / "main.py").exists()
    # editing in the worktree does not touch the source working tree
    (ws.root / "main.py").write_text("print('v2')\n")
    assert (git_project / "main.py").read_text() == "print('v1')\n"
    assert "main.py" in mgr.changed_files(ws)
    assert "v2" in mgr.diff(ws)
    mgr.discard(ws)
    assert not ws.root.exists()


def test_non_git_fallback_is_copy(tmp_path: Path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    assert not is_git_repo(root)
    mgr = WorktreeManager(root, root / ".openagent" / "worktrees")
    ws = mgr.create("run_x")
    assert ws.is_copy is True
    assert ws.lower_safety is True
    assert (ws.root / "a.txt").read_text() == "hello"
    mgr.discard(ws)
    assert not ws.root.exists()
