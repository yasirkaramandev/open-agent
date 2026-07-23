from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from enum import StrEnum


class ProposalState(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


ALLOWED_TRANSITIONS = {
    ProposalState.DRAFT: {ProposalState.PENDING_APPROVAL, ProposalState.CANCELLED},
    ProposalState.PENDING_APPROVAL: {
        ProposalState.APPROVED,
        ProposalState.CANCELLED,
        ProposalState.EXPIRED,
    },
    ProposalState.APPROVED: {
        ProposalState.EXECUTING,
        ProposalState.CANCELLED,
        ProposalState.EXPIRED,
    },
    ProposalState.EXECUTING: {ProposalState.SUCCEEDED, ProposalState.FAILED},
}


class InvalidTransition(ValueError):
    pass


def transition(current: ProposalState, target: ProposalState) -> ProposalState:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"transition {current} -> {target} is not allowed")
    return target


def canonical_payload_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def new_idempotency_key() -> str:
    return f"act_{secrets.token_urlsafe(24)}"


@dataclass(frozen=True)
class Approval:
    proposal_id: str
    account_id: str
    payload_hash: str
    approved_by: str
    confirmation_version: int = 1

    def matches(self, *, account_id: str, payload: dict[str, object]) -> bool:
        return self.account_id == account_id and self.payload_hash == canonical_payload_hash(
            payload
        )


def reject_cross_account_duplicate(
    *,
    account_id: str,
    comment_hash: str,
    prior_account_comment_hashes: set[tuple[str, str]],
) -> None:
    if any(
        existing_account != account_id and existing_hash == comment_hash
        for existing_account, existing_hash in prior_account_comment_hashes
    ):
        raise PermissionError("policy_blocked_duplicate_cross_account_comment")
