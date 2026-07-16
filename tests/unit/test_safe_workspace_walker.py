from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from openagent.security.filesystem import (
    SafeWorkspaceWalker,
    UnsafeWorkspacePath,
    WalkerLimits,
    WorkspaceBudgetExceeded,
)


def test_walker_skips_symlink_fifo_socket_and_dangling_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "regular.txt").write_text("safe")
    (root / "link.txt").symlink_to(root / "regular.txt")
    (root / "dangling").symlink_to(root / "missing")
    os.mkfifo(root / "pipe")
    sock = socket.socket(socket.AF_UNIX)
    monkeypatch.chdir(root)
    sock.bind("socket")
    try:
        files = [path.name for path in SafeWorkspaceWalker(root).iter_files()]
    finally:
        sock.close()

    assert files == ["regular.txt"]


@pytest.mark.parametrize(
    "path", ["../outside", "/etc/passwd", r"C:\Windows\System32", r"\\host\share"]
)
def test_resolve_rejects_all_absolute_and_traversal_forms(tmp_path: Path, path: str) -> None:
    with pytest.raises(UnsafeWorkspacePath):
        SafeWorkspaceWalker(tmp_path).resolve(path, allow_missing=True)


def test_read_refuses_a_symlink_even_when_it_points_inside(tmp_path: Path) -> None:
    (tmp_path / "real").write_text("secret")
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(UnsafeWorkspacePath):
        SafeWorkspaceWalker(tmp_path).read_bytes("link")


def test_file_budget_stops_the_walk(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text("x")
    walker = SafeWorkspaceWalker(tmp_path, limits=WalkerLimits(files=1, results=1))
    with pytest.raises(WorkspaceBudgetExceeded):
        list(walker.iter_files())
