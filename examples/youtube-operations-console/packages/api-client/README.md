# API client

Generated clients should be produced from `apps/api` OpenAPI output. Every write method must require
an explicit `youtubeAccountId`, `proposalId`, `approvalPayloadHash`, and `Idempotency-Key`. No
convenience method may accept an array of accounts.
