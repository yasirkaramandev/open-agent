"""No-follow, bounded workspace traversal and copying.

Every recursive read/copy path uses this walker. Symlinks, reparse points, FIFOs, sockets and
devices are skipped; path components are checked lexically and with ``lstat`` before use.
"""

from __future__ import annotations

import os
import shutil
import stat
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..core.cancellation import RunCancellation
from .atomic import atomic_write_bytes


class UnsafeWorkspacePath(ValueError):
    pass


class WorkspaceBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class WalkerLimits:
    directories: int = 20_000
    files: int = 50_000
    bytes: int = 1 * 1024 * 1024 * 1024
    results: int = 50_000
    deadline_seconds: float = 30.0


@dataclass
class WalkerStats:
    directories: int = 0
    files: int = 0
    bytes: int = 0
    results: int = 0


def _is_reparse(stat_result: os.stat_result) -> bool:
    attributes = getattr(stat_result, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _unsafe_kind(stat_result: os.stat_result) -> bool:
    return stat.S_ISLNK(stat_result.st_mode) or _is_reparse(stat_result)


class SafeWorkspaceWalker:
    def __init__(
        self,
        root: Path,
        *,
        limits: WalkerLimits | None = None,
        cancellation: RunCancellation | None = None,
    ) -> None:
        self.root = root.absolute()
        self.limits = limits or WalkerLimits()
        self.cancellation = cancellation
        self.stats = WalkerStats()
        self._deadline = time.monotonic() + self.limits.deadline_seconds
        root_stat = self.root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or _unsafe_kind(root_stat):
            raise UnsafeWorkspacePath(f"workspace root is not a real directory: {root}")

    def _check(self) -> None:
        if self.cancellation is not None and self.cancellation.cancelled:
            raise WorkspaceBudgetExceeded("workspace operation cancelled")
        if time.monotonic() >= self._deadline:
            raise WorkspaceBudgetExceeded("workspace operation deadline exceeded")
        if self.stats.directories > self.limits.directories:
            raise WorkspaceBudgetExceeded("workspace directory budget exceeded")
        if self.stats.files > self.limits.files:
            raise WorkspaceBudgetExceeded("workspace file budget exceeded")
        if self.stats.bytes > self.limits.bytes:
            raise WorkspaceBudgetExceeded("workspace byte budget exceeded")
        if self.stats.results > self.limits.results:
            raise WorkspaceBudgetExceeded("workspace result budget exceeded")

    def resolve(self, relative: str | Path, *, allow_missing: bool = False) -> Path:
        raw = str(relative)
        posix = PurePosixPath(raw)
        windows = PureWindowsPath(raw)
        if posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
            raise UnsafeWorkspacePath(f"absolute path is outside the workspace: {raw!r}")
        parts = posix.parts
        windows_parts = windows.parts
        if not parts or any(part in {"", ".", ".."} for part in (*parts, *windows_parts)):
            if raw not in {"", "."}:
                raise UnsafeWorkspacePath(f"path traversal is not allowed: {raw!r}")
            parts = ()
        candidate = self.root.joinpath(*parts)
        current = self.root
        for index, part in enumerate(parts):
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                if allow_missing and index == len(parts) - 1:
                    return candidate
                if allow_missing:
                    # Missing parents are allowed only after every existing ancestor was verified.
                    return candidate
                raise
            if _unsafe_kind(info):
                raise UnsafeWorkspacePath(f"symlink/reparse path is not allowed: {raw!r}")
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise UnsafeWorkspacePath(f"non-directory path component: {raw!r}")
        return candidate

    def iter_files(
        self,
        relative: str | Path = ".",
        *,
        ignore_dirs: set[str] | frozenset[str] = frozenset(),
        depth: int | None = None,
    ) -> Iterator[Path]:
        start = self.resolve(relative)
        start_info = start.lstat()
        if not stat.S_ISDIR(start_info.st_mode) or _unsafe_kind(start_info):
            raise UnsafeWorkspacePath(f"walk root is not a real directory: {relative!s}")

        def visit(directory: Path, level: int) -> Iterator[Path]:
            self.stats.directories += 1
            self._check()
            try:
                with os.scandir(directory) as scan:
                    entries = sorted(scan, key=lambda entry: entry.name)
            except OSError as exc:
                raise UnsafeWorkspacePath(f"cannot scan {directory}") from exc
            for entry in entries:
                self._check()
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _unsafe_kind(info):
                    continue
                path = Path(entry.path)
                if stat.S_ISDIR(info.st_mode):
                    if entry.name not in ignore_dirs and (depth is None or level < depth):
                        yield from visit(path, level + 1)
                elif stat.S_ISREG(info.st_mode):
                    self.stats.files += 1
                    self.stats.results += 1
                    self._check()
                    yield path

        yield from visit(start, 0)

    def read_bytes(self, relative: str | Path, *, max_bytes: int | None = None) -> bytes:
        path = self.resolve(relative)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
                raise UnsafeWorkspacePath(f"not a regular file: {relative!s}")
            amount = info.st_size if max_bytes is None else min(info.st_size, max_bytes)
            chunks: list[bytes] = []
            remaining = amount
            while remaining > 0:
                block = os.read(fd, min(remaining, 64 * 1024))
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)
                self.stats.bytes += len(block)
                self._check()
            return b"".join(chunks)
        finally:
            os.close(fd)

    def write_bytes(self, relative: str | Path, data: bytes, *, mode: int = 0o600) -> Path:
        target = self.resolve(relative, allow_missing=True)
        # Verify/create each parent without following links.
        rel_parent = target.parent.relative_to(self.root)
        current = self.root
        for part in rel_parent.parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                current.mkdir()
                info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or _unsafe_kind(info):
                raise UnsafeWorkspacePath(f"unsafe parent for {relative!s}")
        atomic_write_bytes(target, data, mode=mode)
        self.stats.bytes += len(data)
        self._check()
        return target

    def copy_to(
        self,
        destination: Path,
        *,
        ignore_dirs: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for source in self.iter_files(ignore_dirs=ignore_dirs):
            relative = source.relative_to(self.root)
            data = self.read_bytes(relative)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, data, mode=(stat.S_IMODE(source.lstat().st_mode) & 0o777))


def safe_rmtree(path: Path, *, owner_root: Path) -> None:
    """Remove only a lexical child of ``owner_root`` whose root itself is not a link."""

    root, candidate = owner_root.absolute(), path.absolute()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeWorkspacePath(f"refused cleanup outside {root}") from exc
    if candidate == root:
        raise UnsafeWorkspacePath("refused to remove ownership root")
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        return
    if _unsafe_kind(info) or not stat.S_ISDIR(info.st_mode):
        raise UnsafeWorkspacePath(f"refused unsafe cleanup target {candidate}")
    shutil.rmtree(candidate)
