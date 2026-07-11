"""Process-tree management for CLI subprocesses (spec §7, §45).

Responsibilities:

* Build a **minimal environment** for children so secrets in the parent env don't leak, and inject
  only the credentials a specific run needs (spec §7).
* Launch a subprocess, expose its stdout as an async line stream, and capture stderr.
* Cancel = terminate the whole process tree (graceful ``SIGTERM`` → force ``SIGKILL``), so a
  cancelled agent never leaves orphaned children (spec §45).
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path

import psutil

#: Environment variables that are safe/necessary to inherit for a child CLI to function.
_SAFE_ENV_KEYS = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TMPDIR", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "SYSTEMROOT", "SystemRoot", "COMSPEC", "PATHEXT",  # Windows
)


def minimal_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """A stripped-down environment: only safe keys from the parent, plus explicit ``extra``.

    Notably this does **not** carry provider API keys from the parent process (spec §7) — the caller
    injects exactly the credential a run needs via ``extra``.
    """

    env = {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}
    if extra:
        env.update(extra)
    return env


class ManagedProcess:
    """An async-launched subprocess whose whole tree can be cancelled cleanly."""

    def __init__(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.args = list(args)
        self.cwd = cwd
        self.env = dict(env) if env is not None else minimal_environment()
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr: list[str] = []

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self.args,
            cwd=str(self.cwd),
            env=self.env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )

    async def stream_stdout(self) -> AsyncIterator[str]:
        """Yield decoded stdout lines. Drains stderr concurrently to avoid buffer deadlock."""

        assert self._proc is not None and self._proc.stdout is not None
        stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            async for raw in self._proc.stdout:
                yield raw.decode("utf-8", errors="replace").rstrip("\n")
        finally:
            await stderr_task

    async def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        async for raw in self._proc.stderr:
            self._stderr.append(raw.decode("utf-8", errors="replace").rstrip("\n"))

    @property
    def stderr(self) -> str:
        return "\n".join(self._stderr)

    async def wait(self) -> int:
        assert self._proc is not None
        return await self._proc.wait()

    async def cancel(self, grace: float = 3.0) -> None:
        """Terminate the process and every descendant (spec §45)."""

        if self._proc is None or self._proc.returncode is not None:
            return
        pid = self._proc.pid
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            return

        for proc in [*children, parent]:
            _safe_signal(proc, terminate=True)

        _, alive = psutil.wait_procs([*children, parent], timeout=grace)
        for proc in alive:  # force-kill survivors
            _safe_signal(proc, terminate=False)


def _safe_signal(proc: psutil.Process, *, terminate: bool) -> None:
    try:
        if terminate:
            proc.terminate()
        else:
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):  # pragma: no cover - race/perm
        pass


def is_pid_alive(pid: int | None) -> bool:
    """Whether a previously recorded run PID is still running (orphan recovery, spec §45)."""

    if not pid:
        return False
    try:
        return psutil.pid_exists(pid)
    except Exception:  # pragma: no cover - platform dependent
        return False


IS_WINDOWS = sys.platform.startswith("win")
