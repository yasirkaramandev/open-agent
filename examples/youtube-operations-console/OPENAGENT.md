# OpenAgent

This repository uses OpenAgent to discover and run external AI agents.

## Instructions for AI Assistants

1. Run `openagent list --json` to discover available agents.
2. Delegate work with:
   `openagent run --name <name> --prompt "<task>" --worktree auto`
3. Retrieve a result with:
   `openagent output --id <run-id> --format json`
4. Never request or expose credentials.
5. Use isolated worktrees for file-changing tasks.

## Available Agents

<!-- OPENAGENT:AGENTS:START -->

### AGY Backend

- Name: `agy-backend`
- Runtime: `antigravity-cli`
- Tags: —
- Description: FastAPI, OAuth, persistence, monitoring, idempotency, and audit services.

### AGY Documentation

- Name: `agy-docs`
- Runtime: `antigravity-cli`
- Tags: —
- Description: Setup, architecture, deployment, backup, incident response, and user documentation.

### AGY Frontend

- Name: `agy-frontend`
- Runtime: `antigravity-cli`
- Tags: —
- Description: Accessible Next.js product UI and browser tests.

### AGY QA

- Name: `agy-qa`
- Runtime: `antigravity-cli`
- Tags: —
- Description: Unit, integration, concurrency, browser, and accessibility verification.

### AGY Security

- Name: `agy-security`
- Runtime: `antigravity-cli`
- Tags: —
- Description: OAuth threat model, encryption, RBAC, SSRF, replay, redaction, and security review.

### AGY YouTube Compliance

- Name: `agy-youtube-compliance`
- Runtime: `antigravity-cli`
- Tags: —
- Description: YouTube API policy, scope minimization, retention, and engagement boundaries.

### GLM Orchestrator

- Name: `glm-orchestrator`
- Runtime: `api`
- Tags: —
- Description: Routes work, enforces security/compliance gates, and integrates reviewed outputs.

<!-- OPENAGENT:AGENTS:END -->
