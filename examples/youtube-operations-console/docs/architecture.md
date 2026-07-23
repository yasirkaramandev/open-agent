# Architecture

Signal separates monitoring from engagement:

1. Official YouTube push notifications enter a replay-protected webhook boundary.
2. The worker treats webhook XML as data, verifies video metadata with the official API, deduplicates
   by channel/video/event identity, and records quota.
3. OpenAgent routes draft work through the GLM orchestrator to implementation agents.
4. QA and security review are mandatory; YouTube writes also require compliance review.
5. Agents may create a proposal. They cannot approve or execute one.
6. The operator opens one proposal, chooses one account, reviews the exact payload, and confirms.
7. Approval stores the canonical payload hash. An edit invalidates approval.
8. Execution claims a unique idempotency key and reconciles unknown remote outcomes before retrying.
9. Every state change extends an append-only audit hash chain.

Bounded contexts are application identity/RBAC, OAuth credentials, monitoring, proposals/approvals,
write execution, own-channel operations, quota, and audit. Own-channel moderation is not coupled to
target-channel engagement.
