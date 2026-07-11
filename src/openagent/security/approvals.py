"""Approval flow (spec §29).

When the command policy returns ``APPROVAL``, the runtime pauses and asks. An :class:`ApprovalGate`
decides how that question is answered: auto-deny (non-interactive default), auto-accept (full-access
or an explicit ``--yes``), or a caller-supplied callback (TUI prompt / CLI confirm).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class ApprovalOutcome(str, Enum):
    ACCEPTED = "accepted"
    DENIED = "denied"


@dataclass
class ApprovalRequest:
    run_id: str
    action: str
    detail: str


ApprovalCallback = Callable[[ApprovalRequest], bool]


class ApprovalGate:
    """Resolves approval requests according to a policy or a callback."""

    def __init__(
        self,
        *,
        auto_approve: bool = False,
        callback: ApprovalCallback | None = None,
    ) -> None:
        self.auto_approve = auto_approve
        self.callback = callback

    def decide(self, request: ApprovalRequest) -> ApprovalOutcome:
        if self.callback is not None:
            accepted = self.callback(request)
        else:
            accepted = self.auto_approve
        return ApprovalOutcome.ACCEPTED if accepted else ApprovalOutcome.DENIED
