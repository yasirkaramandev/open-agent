from fastapi.testclient import TestClient
from signal_api.db_models import Base, OAuthCredential
from signal_api.domain import (
    Approval,
    InvalidTransition,
    ProposalState,
    canonical_payload_hash,
    transition,
)
from signal_api.main import app
from signal_api.security import pkce_challenge, validate_redirect_uri, verify_state

client = TestClient(app)


def test_state_machine_and_payload_approval_are_exact() -> None:
    assert (
        transition(ProposalState.DRAFT, ProposalState.PENDING_APPROVAL)
        is ProposalState.PENDING_APPROVAL
    )
    try:
        transition(ProposalState.DRAFT, ProposalState.SUCCEEDED)
    except InvalidTransition:
        pass
    else:
        raise AssertionError("invalid transition was accepted")
    payload = {"comment": "Specific draft", "video_id": "video_1"}
    approval = Approval("p1", "account_1", canonical_payload_hash(payload), "user_1")
    assert approval.matches(account_id="account_1", payload=payload)
    assert not approval.matches(account_id="account_2", payload=payload)


def test_oauth_state_pkce_and_redirect_fail_closed() -> None:
    assert pkce_challenge("verifier") != "verifier"
    verify_state("same", "same")
    for call in (
        lambda: verify_state("expected", "attacker"),
        lambda: validate_redirect_uri(
            "https://app.example/callback", "https://evil.example/callback"
        ),
    ):
        try:
            call()
        except PermissionError:
            pass
        else:
            raise AssertionError("OAuth boundary accepted attacker-controlled input")


def test_health_contract() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_database_schema_covers_the_operations_boundary_without_plaintext_tokens() -> None:
    expected = {
        "users",
        "workspaces",
        "memberships",
        "youtube_accounts",
        "oauth_credentials",
        "target_channels",
        "target_videos",
        "video_snapshots",
        "action_proposals",
        "action_approvals",
        "action_executions",
        "audit_logs",
        "quota_usage",
        "agent_runs",
    }
    assert set(Base.metadata.tables) == expected
    credential_columns = set(Base.metadata.tables["oauth_credentials"].columns.keys())
    assert credential_columns == {
        "youtube_account_id",
        "encrypted_refresh_token",
        "encrypted_access_token",
        "encryption_key_version",
        "revision",
        "revoked_at",
    }
    credential = OAuthCredential(
        youtube_account_id="account_1",
        encrypted_refresh_token=b"ciphertext",
        encrypted_access_token=b"ciphertext",
        encryption_key_version="key_1",
        revision="rev_1",
        revoked_at=None,
    )
    assert b"ciphertext".decode() not in repr(credential)
