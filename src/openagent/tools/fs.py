"""Filesystem tools (spec §2.1, §27, §4, §11).

All paths are workspace-relative and validated by :meth:`ToolContext.resolve_path`. Edits prefer
``apply_patch`` (targeted, reviewable) over ``write_file`` (spec §27).

Two properties the recursive tools must hold, which they previously did not:

**They stay inside the workspace (§4).** ``read_file`` was always safe because ``resolve_path``
resolves symlinks and rejects escapes. The walkers were not: they used ``os.walk`` paths directly, so
a symlink in the workspace pointing at ``/etc/passwd`` was opened and its contents returned. Every
candidate is now resolved and re-checked against the root, and non-regular files (FIFO, socket,
device) are skipped — reading a FIFO blocks forever, and ``/dev/zero`` never ends.

**They are bounded (§11).** ``search_text`` did ``read_text().splitlines()``, materialising a whole
file *and* a list of its lines; the walk had no file, byte, result, time or cancellation limit; and
the 500-hit ``break`` escaped only the inner loop, so it kept walking everything anyway. Scans now
stream line by line and stop at explicit limits, reporting ``truncated``/``cancelled`` rather than
silently returning a partial answer that looks complete.
"""

from __future__ import annotations

import fnmatch
import time
from collections.abc import Iterator
from pathlib import Path

from ..security.filesystem import (
    SafeWorkspaceWalker,
    UnsafeWorkspacePath,
    WalkerLimits,
    WorkspaceBudgetExceeded,
)
from .base import ToolContext, ToolError, ToolResult

_MAX_READ_BYTES = 200_000
_IGNORE_DIRS = {".git", ".openagent", ".venv", "node_modules", "__pycache__", ".mypy_cache"}

# --------------------------------------------------------------------------- bounds (§11)

#: Skip any single file bigger than this when scanning content.
MAX_SCAN_FILE_BYTES = 2_000_000
#: Stop reading a file's content after this much has been consumed.
MAX_SCAN_TOTAL_BYTES = 64_000_000
#: Default caps. Callers may lower them; nothing may raise them past a full walk.
MAX_RESULTS = 500
MAX_LIST_RESULTS = 1000
MAX_FILES_SCANNED = 20_000
#: Wall-clock budget for one scan.
SCAN_DEADLINE_SECONDS = 20.0
#: A line longer than this is truncated in the *output* (the file is still streamed, never slurped).
_MAX_LINE_CHARS = 200


class _Budget:
    """Shared stop conditions for one scan: files, bytes, results, deadline, cancellation."""

    def __init__(
        self,
        ctx: ToolContext,
        *,
        max_results: int,
        max_files: int,
        deadline: float = SCAN_DEADLINE_SECONDS,
    ) -> None:
        self.ctx = ctx
        self.max_results = max_results
        self.max_files = max_files
        self.files_scanned = 0
        self.bytes_read = 0
        self.truncated = False
        self.cancelled = False
        self._end = time.monotonic() + deadline

    def stop(self) -> bool:
        """True when the scan must end. Sets the reason so the caller can report it honestly."""

        cancellation = getattr(self.ctx, "cancellation", None)
        if cancellation is not None and cancellation.cancelled:
            self.cancelled = True
            return True
        if self.files_scanned >= self.max_files:
            self.truncated = True
            return True
        if self.bytes_read >= MAX_SCAN_TOTAL_BYTES:
            self.truncated = True
            return True
        if time.monotonic() >= self._end:
            self.truncated = True
            return True
        return False

    def data(self, **extra: object) -> dict:
        return {
            "truncated": self.truncated,
            "cancelled": self.cancelled,
            "files_scanned": self.files_scanned,
            "bytes_read": self.bytes_read,
            **extra,
        }


def _walk(root: Path, budget: _Budget, *, depth: int | None = None) -> Iterator[Path]:
    """Walk through the central no-follow filesystem boundary."""

    workspace = budget.ctx.workspace_root.absolute()
    try:
        relative = root.absolute().relative_to(workspace)
        walker = SafeWorkspaceWalker(
            workspace,
            cancellation=budget.ctx.cancellation,
            limits=WalkerLimits(
                directories=MAX_FILES_SCANNED,
                files=budget.max_files,
                bytes=MAX_SCAN_TOTAL_BYTES,
                results=budget.max_files,
                deadline_seconds=SCAN_DEADLINE_SECONDS,
            ),
        )
        for candidate in walker.iter_files(relative, ignore_dirs=_IGNORE_DIRS, depth=depth):
            if budget.stop():
                return
            budget.files_scanned += 1
            yield candidate
    except (UnsafeWorkspacePath, WorkspaceBudgetExceeded, OSError):
        if budget.ctx.cancellation is not None and budget.ctx.cancellation.cancelled:
            budget.cancelled = True
        else:
            budget.truncated = True
        return


def list_files(
    ctx: ToolContext, path: str = ".", depth: int = 2, max_results: int = MAX_LIST_RESULTS
) -> ToolResult:
    root = ctx.resolve_path(path)
    if not root.exists():
        raise ToolError(f"{path} does not exist")
    workspace = ctx.workspace_root.resolve()
    budget = _Budget(ctx, max_results=max_results, max_files=MAX_FILES_SCANNED)
    entries: list[str] = []
    for file in _walk(root, budget, depth=depth):
        if len(entries) >= max_results:
            budget.truncated = True
            break
        entries.append(str(file.absolute().relative_to(workspace)))
    return ToolResult.success("\n".join(entries), count=len(entries), **budget.data())


def read_file(ctx: ToolContext, path: str) -> ToolResult:
    try:
        data = ctx.walker().read_bytes(path, max_bytes=_MAX_READ_BYTES)
    except UnsafeWorkspacePath as exc:
        raise ToolError(f"{path} escapes the workspace or is a symlink/reparse point") from exc
    except (WorkspaceBudgetExceeded, OSError) as exc:
        raise ToolError(f"{path} is not a safe regular file") from exc
    text = data.decode("utf-8", errors="replace")
    return ToolResult.success(text, path=path, bytes=len(data))


def search_files(
    ctx: ToolContext,
    pattern: str,
    max_results: int = MAX_RESULTS,
    max_files: int = MAX_FILES_SCANNED,
) -> ToolResult:
    root = ctx.workspace_root.resolve()
    budget = _Budget(ctx, max_results=max_results, max_files=max_files)
    matches: list[str] = []
    for file in _walk(root, budget):
        if fnmatch.fnmatch(file.name, pattern):
            if len(matches) >= max_results:
                budget.truncated = True
                break
            matches.append(str(file.absolute().relative_to(root)))
    return ToolResult.success("\n".join(sorted(matches)), count=len(matches), **budget.data())


def _scan_lines(path: Path, query: str, rel: str, budget: _Budget) -> Iterator[str]:
    """Stream one file line by line, never materialising it (§11)."""

    workspace = budget.ctx.workspace_root.absolute()
    relative = path.absolute().relative_to(workspace)
    try:
        data = budget.ctx.walker().read_bytes(relative, max_bytes=MAX_SCAN_FILE_BYTES + 1)
        if len(data) > MAX_SCAN_FILE_BYTES:
            budget.truncated = True
            return
        budget.bytes_read += len(data)
        for number, raw_line in enumerate(data.splitlines(), 1):
            if budget.stop():
                return
            line = raw_line.decode("utf-8", errors="replace")
            if query in line:
                yield f"{rel}:{number}: {line.strip()[:_MAX_LINE_CHARS]}"
    except (UnsafeWorkspacePath, WorkspaceBudgetExceeded, OSError, ValueError):
        return  # unreadable/binary-ish — skip it, never fail the whole scan


def _looks_binary(path: Path) -> bool:
    try:
        walker = SafeWorkspaceWalker(path.parent)
        return b"\0" in walker.read_bytes(path.name, max_bytes=4096)
    except (UnsafeWorkspacePath, WorkspaceBudgetExceeded, OSError):
        return True


def search_text(
    ctx: ToolContext,
    query: str,
    glob: str = "*",
    max_results: int = MAX_RESULTS,
    max_files: int = MAX_FILES_SCANNED,
) -> ToolResult:
    root = ctx.workspace_root.resolve()
    budget = _Budget(ctx, max_results=max_results, max_files=max_files)
    hits: list[str] = []
    for file in _walk(root, budget):
        if not fnmatch.fnmatch(file.name, glob):
            continue
        if _looks_binary(file):
            continue
        rel = str(file.absolute().relative_to(root))
        for hit in _scan_lines(file, query, rel, budget):
            hits.append(hit)
            if len(hits) >= max_results:
                budget.truncated = True
                break
        # The old code's `break` escaped only the inner loop and kept walking every remaining file.
        if len(hits) >= max_results or budget.stop():
            break
    return ToolResult.success("\n".join(hits), count=len(hits), **budget.data())


def write_file(ctx: ToolContext, path: str, content: str) -> ToolResult:
    if not ctx.profile.can_edit_files:
        raise ToolError("this permission profile does not allow file edits")
    target = ctx.resolve_path(path)
    existed = target.exists()
    try:
        ctx.walker().write_bytes(path, content.encode("utf-8"))
    except (UnsafeWorkspacePath, WorkspaceBudgetExceeded, OSError) as exc:
        raise ToolError(f"unsafe write path {path!r}") from exc
    if ctx.emit:
        ctx.emit("file.modified" if existed else "file.created", {"path": path})
    return ToolResult.success(
        f"wrote {len(content)} bytes to {path}", path=path, created=not existed
    )


def apply_patch(
    ctx: ToolContext, path: str, old_string: str, new_string: str, replace_all: bool = False
) -> ToolResult:
    """Targeted edit: replace ``old_string`` with ``new_string`` in ``path``.

    Reliable and reviewable (small diffs), preferred over ``write_file`` (spec §27). ``old_string``
    must be unique unless ``replace_all`` is set.
    """

    if not ctx.profile.can_edit_files:
        raise ToolError("this permission profile does not allow file edits")
    try:
        walker = ctx.walker()
        text = walker.read_bytes(path).decode("utf-8")
    except (UnicodeDecodeError, UnsafeWorkspacePath, WorkspaceBudgetExceeded, OSError) as exc:
        raise ToolError(f"{path} is not a safe UTF-8 regular file") from exc
    count = text.count(old_string)
    if count == 0:
        raise ToolError("old_string not found in file")
    if count > 1 and not replace_all:
        raise ToolError(
            f"old_string is not unique ({count} matches); set replace_all or add context"
        )
    updated = (
        text.replace(old_string, new_string)
        if replace_all
        else text.replace(old_string, new_string, 1)
    )
    try:
        ctx.walker().write_bytes(path, updated.encode("utf-8"))
    except (UnsafeWorkspacePath, WorkspaceBudgetExceeded, OSError) as exc:
        raise ToolError(f"unsafe write path {path!r}") from exc
    if ctx.emit:
        ctx.emit("file.modified", {"path": path})
    return ToolResult.success(
        f"patched {path} ({count if replace_all else 1} replacement(s))", path=path
    )
