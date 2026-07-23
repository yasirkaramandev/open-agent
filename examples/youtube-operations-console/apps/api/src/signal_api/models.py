from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .domain import ProposalState


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AccountStatus(StrEnum):
    HEALTHY = "healthy"
    REAUTH_REQUIRED = "reauth_required"
    REVOKED = "revoked"


class YoutubeAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: f"acct_{uuid4().hex}")
    workspace_id: str
    google_subject: str
    channel_id: str
    channel_title: str
    channel_handle: str | None = None
    status: AccountStatus = AccountStatus.HEALTHY
    granted_scopes: frozenset[str] = frozenset()
    credential_revision: str = Field(default_factory=lambda: uuid4().hex)
    token_expiry: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: f"proposal_{uuid4().hex}")
    workspace_id: str
    youtube_account_id: str
    target_type: str
    target_id: str
    action_type: str
    draft_payload: dict[str, object]
    status: ProposalState = ProposalState.DRAFT
    created_by_agent: str
    risk_level: str = "medium"
    revision: int = 0


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: f"audit_{uuid4().hex}")
    workspace_id: str
    actor_type: str
    actor_id: str
    event_type: str
    resource_type: str
    resource_id: str
    safe_metadata: dict[str, object] = Field(default_factory=dict)
    correlation_id: str
    hash_chain_previous: str
    hash_chain_current: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
