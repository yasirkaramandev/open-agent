"""CLI adapter contract + shared helpers (spec §6.2).

A CLI adapter does not build an agent loop; it runs an installed coding CLI as a subprocess and
converts its native output into OpenAgent :class:`NormalizedEvent`s. The five-method Protocol mirrors
spec §6.2.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ...core.events import EventType, NormalizedEvent
from ...core.models import CliInstallation
from ...security.process import ManagedProcess

#: Signature of a pure event mapper (``map_codex_event`` / ``map_claude_event``).
EventMapper = Callable[[dict[str, Any], str], list[NormalizedEvent]]

#: The terminal event types every CLI adapter must resolve a run to exactly one of (spec §6.2).
TERMINAL_EVENT_TYPES = frozenset({
    EventType.RUN_COMPLETED.value,
    EventType.RUN_FAILED.value,
    EventType.RUN_CANCELLED.value,
})


@dataclass
class CliRunRequest:
    run_id: str
    prompt: str
    workspace: Path
    permission_profile: str = "safe-edit"
    #: Credentials to inject only into the child environment (spec §7), e.g. {"CODEX_API_KEY": ...}.
    credential_env: dict[str, str] = field(default_factory=dict)
    session_id: str | None = None


@dataclass
class AuthStatus:
    authenticated: bool
    detail: str = ""


@dataclass
class CliCapabilities:
    structured_events: bool
    resumable: bool
    edits_files: bool
    runs_commands: bool
    experimental: bool = False


@runtime_checkable
class CliAdapter(Protocol):
    """The CLI adapter contract (spec §6.2)."""

    async def detect(self) -> CliInstallation | None: ...

    async def inspect_auth(self) -> AuthStatus: ...

    async def capabilities(self) -> CliCapabilities: ...

    def start_run(self, request: CliRunRequest) -> AsyncIterator[NormalizedEvent]: ...

    def resume_run(self, session_id: str, prompt: str, request: CliRunRequest) -> AsyncIterator[NormalizedEvent]: ...

    async def cancel(self, run_id: str) -> None: ...


def find_executable(*names: str) -> str | None:
    """Locate a CLI on PATH, including the common ``~/.local/bin`` install location."""

    for name in names:
        found = shutil.which(name)
        if found:
            return found
    # Fallback: user-local bin (codex/agy install here and may be off PATH in some shells).
    for name in names:
        candidate = Path.home() / ".local" / "bin" / name
        if candidate.exists():
            return str(candidate)
    return None


def is_terminal_event(event: NormalizedEvent) -> bool:
    etype = event.type if isinstance(event.type, str) else event.type.value
    return etype in TERMINAL_EVENT_TYPES


def parse_json_line(line: str) -> dict[str, Any] | None:
    """Parse one JSONL line to a dict, or ``None`` for blank/invalid/non-object lines."""

    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


@dataclass
class TerminalObservations:
    """The distinct terminal events a CLI stream produced, kept for fail-closed reconciliation.

    The first event of each outcome is retained (later duplicates of the *same* outcome are
    dropped); a mix of different outcomes is a **conflict** (spec §43).
    """

    completed: NormalizedEvent | None = None
    failed: NormalizedEvent | None = None
    cancelled: NormalizedEvent | None = None

    def observe(self, event: NormalizedEvent) -> None:
        etype = event.type if isinstance(event.type, str) else event.type.value
        if etype == EventType.RUN_COMPLETED.value and self.completed is None:
            self.completed = event
        elif etype == EventType.RUN_FAILED.value and self.failed is None:
            self.failed = event
        elif etype == EventType.RUN_CANCELLED.value and self.cancelled is None:
            self.cancelled = event

    @property
    def conflicting(self) -> bool:
        return sum(x is not None for x in (self.completed, self.failed, self.cancelled)) > 1


def reconcile_terminal(
    *,
    run_id: str,
    source: str,
    observations: TerminalObservations,
    exit_code: int | None,
    cancelled: bool,
    stderr: str = "",
) -> NormalizedEvent:
    """Produce the single terminal event for a run, **fail-closed** (spec §6.2, §43).

    Precedence — ``cancelled > failed > completed`` — never silently drops a later failure:

    * explicit user/process **cancellation** always wins → ``run.cancelled`` (a killed "success" is
      not success);
    * any native ``run.failed`` makes the result **failed** — a zero exit never rescues it. When it
      conflicts with a ``run.completed`` the failure is tagged ``terminal_conflict``;
    * a native ``run.cancelled`` (with no failure) makes the result **cancelled**, even if the stream
      also claimed completion;
    * ``run.completed`` is honored **only** when it is the sole outcome *and* the process exited
      cleanly (0/None); a non-zero exit turns it into ``run.failed`` (``exit_code_mismatch``);
    * no terminal event at all → ``run.failed`` (clean-exit-but-no-result or a non-zero exit).
    """

    def fail(error_type: str, message: str) -> NormalizedEvent:
        return NormalizedEvent(
            run_id=run_id, type=EventType.RUN_FAILED, source=source,
            data={"error_type": error_type, "exit_code": exit_code, "message": message,
                  "stderr": (stderr or "")[-2000:]},
        )

    if cancelled:
        return NormalizedEvent(
            run_id=run_id, type=EventType.RUN_CANCELLED, source=source,
            data={"reason": "cancelled by user", "exit_code": exit_code},
        )

    comp, failed, canc = observations.completed, observations.failed, observations.cancelled

    # A native failure always wins over a completion (fail-closed); flag genuine contradictions.
    if failed is not None:
        if comp is not None or canc is not None:
            return fail("terminal_conflict",
                        "CLI emitted conflicting terminal events; a failure was reported")
        return failed
    # A native cancellation (no failure) stands, even alongside a completion claim.
    if canc is not None:
        return canc
    if comp is not None:
        if exit_code in (0, None):
            return comp
        return fail("exit_code_mismatch",
                    f"CLI reported success but exited with code {exit_code}")

    clean = exit_code in (0, None)
    detail = "clean exit but no terminal event" if clean else f"exit code {exit_code}"
    return fail("no_terminal_event" if clean else "command_failed",
                f"CLI produced no successful result ({detail})")


async def run_managed_cli(
    *, proc: ManagedProcess, run_id: str, source: str, mapper: EventMapper,
) -> AsyncIterator[NormalizedEvent]:
    """Start ``proc``, normalize its JSONL output, and enforce the terminal-state contract.

    Shared by every CLI adapter (codex, claude, and the test fake) so they finalize identically:

    * emits ``run.started`` (with pid/create_time) up front;
    * yields non-terminal events as they stream;
    * **buffers every** terminal event (never surfacing one mid-stream) and after the process exits
      yields exactly one terminal event reconciled fail-closed against the exit code
      (:func:`reconcile_terminal`): a success event + non-zero exit becomes failed; a killed process
      becomes cancelled; a completion followed by a failure becomes failed (``terminal_conflict``);
      duplicate completions collapse to one.
    """

    await proc.start()
    yield NormalizedEvent(
        run_id=run_id, type=EventType.RUN_STARTED, source=source,
        data={"pid": proc.pid, "create_time": proc.create_time},
    )
    observations = TerminalObservations()
    async for line in proc.stream_stdout():
        obj = parse_json_line(line)
        if obj is None:
            continue
        for event in mapper(obj, run_id):
            if is_terminal_event(event):
                observations.observe(event)  # buffer all outcomes; reconciled once at the end
                continue
            yield event
    code = await proc.wait()
    yield reconcile_terminal(
        run_id=run_id, source=source, observations=observations,
        exit_code=code, cancelled=proc.cancelled, stderr=proc.stderr,
    )


def detect_version(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
        out = (result.stdout or result.stderr).strip()
        return out.splitlines()[0] if out else None
    except (OSError, subprocess.TimeoutExpired):
        return None
