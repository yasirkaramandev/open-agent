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

### Tester agent

- Name: `agy-tester`
- Runtime: `antigravity-cli`
- Tags: `tester`
- Description: Go tester agent

<!-- OPENAGENT:AGENTS:END -->

