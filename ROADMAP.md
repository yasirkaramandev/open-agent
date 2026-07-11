# Roadmap

OpenAgent's core problem is running many different AI backends **reliably, safely, and in a
standard shape**. Once that core is solid, auto-routing and comparison features can be added on top
of real usage data.

## v0.1 — Working core ✅

- `openagent` TUI + `openagent` CLI (init, add, agent/provider management, run, output, doctor)
- SQLite storage, OS-keychain credentials, run IDs, `events.jsonl`, `output.md`, `result.json`
- Isolated git worktrees + permission profiles
- **Codex CLI** adapter (live) and **Claude Code** adapter (fixture-validated)
- **OpenAI** (Chat + Responses), **Anthropic** Messages, and generic **OpenAI-compatible** API agents
- `OPENAGENT.md` generation; secret redaction; command policy; process-tree cancel + orphan recovery

## v0.2 — Broader providers & CLIs

- Gemini CLI + Gemini API
- DeepSeek, Qwen, Kimi, GLM, MiniMax, OpenRouter, Ollama, LM Studio adapters wired end-to-end
- Full CLI discovery, richer doctor, model discovery + capability probe surfaced in the wizard
- Session resume across runtimes

## v0.3 — Orchestration

- Antigravity (`agy`) experimental adapter (worktree-required, version-gated, PTY fallback)
- **MCP server** (`openagent mcp serve`) exposing agents to other AIs
- Workflow engine (`openagent workflow run ...`) with explicit step DAGs
- Approval UI, provider health screen, usage & cost tracking
- Plugin SDK (providers, CLI adapters, tools, reports)

## v0.4 — Wider ecosystem

- ByteDance Doubao / Volcano Ark, Baidu Qianfan, Mistral, Together, Fireworks, vLLM
- OpenCode / Qwen Code / Kimi Code via the generic manifest adapter
- Custom-command agents

## v1.0 — Stable

- Frozen provider + CLI-adapter contracts
- Migrations, security audit, comprehensive docs, stable workflow format

## Explicitly out of scope (for now)

Auto agent-selection, ML router, cloud control plane, team sync, marketplace, mobile/web dashboards,
remote/distributed execution, and automatic `git push`/deploys. These are revisited only after the
core is proven.
