from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Membership(Base):
    __tablename__ = "memberships"
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32))


class YoutubeAccount(Base):
    __tablename__ = "youtube_accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel_id", name="uq_youtube_account_workspace_channel"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    google_subject: Mapped[str] = mapped_column(String(255))
    channel_id: Mapped[str] = mapped_column(String(128))
    channel_title: Mapped[str] = mapped_column(String(255))
    channel_handle: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    granted_scopes: Mapped[list[str]] = mapped_column(JSON)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_revision: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    youtube_account_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_refresh_token: Mapped[bytes] = mapped_column()
    encrypted_access_token: Mapped[bytes | None] = mapped_column()
    encryption_key_version: Mapped[str] = mapped_column(String(64))
    revision: Mapped[str] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return (
            "OAuthCredential(youtube_account_id=***, encrypted_refresh_token=[REDACTED], "
            "encrypted_access_token=[REDACTED], encryption_key_version=***, revision=***)"
        )


class TargetChannel(Base):
    __tablename__ = "target_channels"
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel_id", name="uq_target_workspace_channel"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(255))
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_mode: Mapped[str] = mapped_column(String(32))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TargetVideo(Base):
    __tablename__ = "target_videos"
    __table_args__ = (
        UniqueConstraint("target_channel_id", "video_id", name="uq_target_video_remote"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_channel_id: Mapped[str] = mapped_column(
        ForeignKey("target_channels.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(500))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_metadata_refresh: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VideoSnapshot(Base):
    __tablename__ = "video_snapshots"
    video_id: Mapped[str] = mapped_column(
        ForeignKey("target_videos.id", ondelete="CASCADE"), primary_key=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    description_hash: Mapped[str] = mapped_column(String(64))
    statistics: Mapped[dict[str, object]] = mapped_column(JSON)
    etag: Mapped[str | None] = mapped_column(String(255))


class ActionProposal(Base):
    __tablename__ = "action_proposals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    youtube_account_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_accounts.id", ondelete="RESTRICT"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(128))
    action_type: Mapped[str] = mapped_column(String(32))
    draft_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_by_agent: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    risk_level: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=0)


class ActionApproval(Base):
    __tablename__ = "action_approvals"
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("action_proposals.id", ondelete="CASCADE"), primary_key=True
    )
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_hash: Mapped[str] = mapped_column(String(64))
    confirmation_version: Mapped[int] = mapped_column(Integer)


class ActionExecution(Base):
    __tablename__ = "action_executions"
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("action_proposals.id", ondelete="CASCADE"), primary_key=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    remote_resource_id: Mapped[str | None] = mapped_column(String(255))
    safe_error_code: Mapped[str | None] = mapped_column(String(128))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(128))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(128))
    safe_metadata: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    hash_chain_previous: Mapped[str] = mapped_column(String(64))
    hash_chain_current: Mapped[str] = mapped_column(String(64), unique=True)


class QuotaUsage(Base):
    __tablename__ = "quota_usage"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    method: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("youtube_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_units: Mapped[int] = mapped_column(BigInteger, default=0)
    successful_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    openagent_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    artifact_path: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "ix_proposal_duplicate_guard",
    ActionProposal.youtube_account_id,
    ActionProposal.target_id,
    ActionProposal.action_type,
    ActionProposal.status,
)
