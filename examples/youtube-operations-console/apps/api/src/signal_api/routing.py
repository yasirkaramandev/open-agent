from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TaskRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    category: str
    risk: str
    suggested_agents: list[str]
    requires_security_review: bool
    requires_compliance_review: bool
    dependencies: list[str]
    acceptance_tests: list[str]
    forbidden_changes: list[str]


def reject_forbidden_route(route: TaskRoute) -> None:
    forbidden = " ".join(route.forbidden_changes).lower()
    if any(term in forbidden for term in ("bulk", "automatic comment", "cross-account duplicate")):
        return
    if route.category == "youtube-write" and not route.requires_compliance_review:
        raise PermissionError("youtube writes require compliance review")
