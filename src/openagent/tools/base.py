"""Tool context, result, and path-safety helpers shared by all tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.permissions import PermissionProfile
from ..security.approvals import ApprovalGate, ApprovalRequest


class ToolError(Exception):
    """Raised by tools for expected, reportable failures (bad path, denied command…)."""


@dataclass
class ToolResult:
    ok: bool
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, content: str = "", **data: Any) -> ToolResult:
        return cls(ok=True, content=content, data=data)

    @classmethod
    def failure(cls, content: str, **data: Any) -> ToolResult:
        return cls(ok=False, content=content, data=data)


#: Signature for the optional event sink a runtime passes so tools can emit fine-grained events.
EventSink = Callable[[str, dict], None]


@dataclass
class ToolContext:
    """Everything a tool needs, scoped to one run."""

    workspace_root: Path
    profile: PermissionProfile
    approval_gate: ApprovalGate
    run_id: str = ""
    emit: EventSink | None = None

    def request_approval(self, action: str, detail: str) -> bool:
        outcome = self.approval_gate.decide(ApprovalRequest(self.run_id, action, detail))
        return outcome.value == "accepted"

    def resolve_path(self, relative: str) -> Path:
        """Resolve ``relative`` inside the workspace, rejecting escapes and symlink breakouts.

        Prevents path traversal (``../../etc/passwd``) and absolute-path escapes (spec §40 security
        tests). Returns an absolute path guaranteed to live under ``workspace_root``.
        """

        root = self.workspace_root.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ToolError(f"path {relative!r} escapes the workspace") from exc
        return candidate
