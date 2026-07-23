"""Worker allowlist: monitoring is automatic; engagement execution requires approval evidence."""

from __future__ import annotations

from dataclasses import dataclass

AUTOMATIC_TASKS = frozenset(
    {
        "token_health_check",
        "target_channel_monitor",
        "webhook_process",
        "metadata_refresh",
        "quota_accounting",
        "notification",
        "analytics_snapshot",
        "expired_proposal_cleanup",
    }
)


@dataclass(frozen=True)
class ExecutionEnvelope:
    proposal_id: str
    account_id: str
    approval_hash: str
    idempotency_key: str
    feature_flag_enabled: bool


def enqueue_automatic(task_name: str) -> str:
    if task_name not in AUTOMATIC_TASKS:
        raise PermissionError("background_engagement_blocked")
    return f"queued:{task_name}"


def execute_youtube_write(envelope: ExecutionEnvelope) -> str:
    if not all(
        (
            envelope.proposal_id,
            envelope.account_id,
            envelope.approval_hash,
            envelope.idempotency_key,
        )
    ):
        raise PermissionError("approval_evidence_incomplete")
    if not envelope.feature_flag_enabled:
        return "feature_flag_disabled"
    return "requires_official_youtube_adapter"
