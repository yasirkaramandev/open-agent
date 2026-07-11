"""Command-execution tools (spec §2.1, §27, §29).

Every command is screened by the command policy first, then run inside the workspace with a bounded
timeout. Output is truncated to keep events small.
"""

from __future__ import annotations

import subprocess

from ..security.command_policy import Decision, evaluate
from .base import ToolContext, ToolError, ToolResult

_MAX_OUTPUT = 20_000
_DEFAULT_TIMEOUT = 300


def _run(ctx: ToolContext, command: str, timeout: int) -> subprocess.CompletedProcess[str]:
    policy = evaluate(command, network_allowed=ctx.profile.network_allowed)
    if policy.decision is Decision.DENY:
        raise ToolError(f"command denied by policy: {policy.reason}")
    if policy.decision is Decision.APPROVAL:
        if not ctx.request_approval("run_command", f"{command}\n({policy.reason})"):
            raise ToolError(f"command not approved: {policy.reason}")
    if ctx.emit:
        ctx.emit("command.started", {"command": command, "cwd": str(ctx.workspace_root)})
    try:
        return subprocess.run(
            command, shell=True, cwd=str(ctx.workspace_root),
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"command timed out after {timeout}s") from exc


def run_command(ctx: ToolContext, command: str, timeout: int = _DEFAULT_TIMEOUT) -> ToolResult:
    if not ctx.profile.can_run_commands:
        raise ToolError("this permission profile does not allow running commands")
    proc = _run(ctx, command, timeout)
    output = ((proc.stdout or "") + (proc.stderr or ""))[:_MAX_OUTPUT]
    if ctx.emit:
        ctx.emit("command.completed", {"command": command, "exit_code": proc.returncode})
    ok = proc.returncode == 0
    return ToolResult(ok=ok, content=output, data={"exit_code": proc.returncode, "command": command})


def run_tests(ctx: ToolContext, command: str = "pytest -q", timeout: int = _DEFAULT_TIMEOUT) -> ToolResult:
    if not ctx.profile.can_run_commands:
        raise ToolError("this permission profile does not allow running commands")
    proc = _run(ctx, command, timeout)
    output = ((proc.stdout or "") + (proc.stderr or ""))[:_MAX_OUTPUT]
    passed = proc.returncode == 0
    if ctx.emit:
        ctx.emit("test.completed", {"command": command, "passed": passed, "exit_code": proc.returncode})
    return ToolResult(
        ok=passed, content=output,
        data={"exit_code": proc.returncode, "passed": passed, "command": command},
    )
