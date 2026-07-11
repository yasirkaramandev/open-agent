"""Control-flow tools (spec §2.1).

``ask_user`` surfaces a question (routed through the approval gate / callback); ``finish_task``
signals the agent loop to stop with a final summary.
"""

from __future__ import annotations

from .base import ToolContext, ToolResult


class TaskFinished(Exception):
    """Raised by ``finish_task`` to end the agent loop cleanly."""

    def __init__(self, summary: str) -> None:
        super().__init__(summary)
        self.summary = summary


def ask_user(ctx: ToolContext, question: str) -> ToolResult:
    # In non-interactive runs there is no human to answer; record the question and continue.
    if ctx.emit:
        ctx.emit("approval.requested", {"kind": "question", "question": question})
    return ToolResult.success(
        "No interactive user is available; proceed with your best judgment and note assumptions.",
        question=question,
    )


def finish_task(ctx: ToolContext, summary: str) -> ToolResult:
    raise TaskFinished(summary)
