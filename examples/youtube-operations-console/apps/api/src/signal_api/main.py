from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

from .domain import Approval, ProposalState, canonical_payload_hash, new_idempotency_key
from .models import ActionProposal
from .security import opaque_token, pkce_challenge, validate_redirect_uri, verify_state

app = FastAPI(
    title="Signal YouTube Operations API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)

_proposals: dict[str, ActionProposal] = {}
_approvals: dict[str, Approval] = {}
_executions: dict[str, str] = {}


class ProposalCreate(BaseModel):
    workspace_id: str
    youtube_account_id: str
    target_type: str
    target_id: str
    action_type: str
    draft_payload: dict[str, object]
    created_by_agent: str


class ApprovalRequest(BaseModel):
    user_id: str
    expected_revision: int
    payload: dict[str, object]


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def ready() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/auth/google/start")
def oauth_start() -> dict[str, str]:
    state, nonce, verifier = opaque_token(), opaque_token(), opaque_token(48)
    return {"state": state, "nonce": nonce, "pkce_challenge": pkce_challenge(verifier)}


@app.get("/auth/google/callback")
def oauth_callback(
    state: str, expected_state: str, redirect_uri: str, expected_redirect_uri: str
) -> dict[str, str]:
    verify_state(expected_state, state)
    validate_redirect_uri(expected_redirect_uri, redirect_uri)
    return {"status": "code_exchange_requires_server_secret"}


@app.post("/proposals", status_code=201)
def create_proposal(request: ProposalCreate) -> ActionProposal:
    proposal = ActionProposal(**request.model_dump())
    _proposals[proposal.id] = proposal
    return proposal


@app.post("/proposals/{proposal_id}/approve")
def approve(
    proposal_id: str, request: ApprovalRequest, x_workspace_id: str = Header()
) -> dict[str, str]:
    proposal = _proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(404, "proposal_not_found")
    if proposal.workspace_id != x_workspace_id:
        raise HTTPException(404, "proposal_not_found")
    if proposal.revision != request.expected_revision:
        raise HTTPException(409, "proposal_revision_conflict")
    approval = Approval(
        proposal_id=proposal.id,
        account_id=proposal.youtube_account_id,
        payload_hash=canonical_payload_hash(request.payload),
        approved_by=request.user_id,
    )
    _approvals[proposal.id] = approval
    proposal.revision += 1
    proposal.status = ProposalState.APPROVED
    return {"status": "approved", "payload_hash": approval.payload_hash}


@app.post("/proposals/{proposal_id}/execute", status_code=202)
def execute(
    proposal_id: str,
    request: ApprovalRequest,
    response: Response,
    x_workspace_id: str = Header(),
    idempotency_key: str | None = Header(default=None),
) -> dict[str, str]:
    proposal = _proposals.get(proposal_id)
    approval = _approvals.get(proposal_id)
    if proposal is None or proposal.workspace_id != x_workspace_id:
        raise HTTPException(404, "proposal_not_found")
    if approval is None or not approval.matches(
        account_id=proposal.youtube_account_id, payload=request.payload
    ):
        raise HTTPException(409, "approval_payload_mismatch")
    key = idempotency_key or new_idempotency_key()
    if key in _executions:
        response.status_code = 200
        return {"status": "already_accepted", "execution_id": _executions[key]}
    execution_id = f"exec_{canonical_payload_hash({'proposal': proposal_id, 'key': key})[:20]}"
    _executions[key] = execution_id
    return {"status": "queued_feature_flagged", "execution_id": execution_id}
