# Deployment boundary

Production needs managed PostgreSQL, Redis, a KMS-backed envelope-encryption key, fixed Google OAuth
redirect URIs, HTTPS, CSP/HSTS, a secret manager, metrics, traces, and append-only audit retention.
Set `YOUTUBE_WRITE_ACTIONS_ENABLED=false` until OAuth verification, quota budgets, security review,
compliance review, backup restore, and reconciliation tests are complete.

The API and worker must run non-root with a read-only filesystem. No production token may be put in
an image layer, GitHub Actions variable, repository file, ORM representation, structured log, or
error tracker breadcrumb.
