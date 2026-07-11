# OpenAgent

**Local-first control plane for AI APIs, coding CLIs, and autonomous agents.**

> Register every AI agent once. Run all of them through one standard interface.

OpenAgent unifies two kinds of AI backends behind a single terminal UI, CLI, and (soon) MCP server:

1. **API agents** — OpenAI, Anthropic, DeepSeek, Qwen, Kimi, GLM, MiniMax, OpenRouter, Ollama, and
   any OpenAI-/Anthropic-compatible endpoint. These only emit text and tool calls, so OpenAgent runs
   its **own agent loop** with a safe toolset (read / search / patch / run / test).
2. **CLI agents** — Codex CLI, Claude Code, and more. These have their own loops; OpenAgent runs them
   as subprocesses and **normalizes their output** into one event stream.

Whichever backend does the work, every run produces the **same standard artifact bundle** in an
isolated git worktree — that standardization is the point.

```
.openagent/runs/run_01ABC/
├── request.json   status.json   events.jsonl   output.md
├── result.json    logs.txt      changes.diff   tests.json   handoff.md
```

## Status

**v0.1 (alpha).** Working core: TUI + CLI, OpenAI (Chat + Responses) / Anthropic / generic
OpenAI-compatible API agents with a tool loop, live **Codex CLI** adapter, **Claude Code** adapter
(fixture-validated), isolated worktrees, permission profiles, OS-keychain credentials, and the
standard run bundle. See [ROADMAP.md](ROADMAP.md) for what's next.

## Install

Requires **Python 3.10+**. From a clone:

```bash
python3.10 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Quickstart

```bash
# Open the full-screen TUI
openagent

# Or drive it from the CLI:
openagent init                       # set up local state
openagent discover                   # detect installed coding CLIs (codex, claude, …)
openagent doctor                     # system diagnostics

# Register an installed CLI as an agent
openagent add --name codex-coder --title "Codex Coder" --cli codex --tag coder

# Register an API provider (key is prompted with hidden input, stored in the OS keychain)
openagent provider add deepseek-main --type deepseek
openagent add --name deepseek-coder --provider deepseek-main --model <model-id> --tag backend

# Run a task in an isolated worktree, then read the result
openagent run --name codex-coder --prompt "update the WSS client in main.py" --worktree auto
openagent output --id <run-id> --format md
openagent output --id <run-id> --format diff
```

## How it works

```
Interfaces:     TUI · CLI · (MCP, SDK — planned)
                        │
Services:       Agent · Provider · Model · Run · Discovery · Doctor
                        │
Runtimes:       API agent loop (own tools)   │   CLI adapters (codex, claude)
                        │
Workspace:      git worktree · permission profiles · command policy · secret redaction
                        │
Storage:        SQLite (index) · events.jsonl (source of truth) · artifacts
```

* **Providers vs. Agents.** A *provider* is an API account (no prompt, no role). An *agent* binds a
  runtime + prompt + tags + permission profile. Many agents can share one provider; the key is
  stored once.
* **Dynamic models.** Model IDs are never hardcoded — OpenAgent discovers them and probes
  capabilities per model.
* **Safety first.** Every file-changing run happens in an isolated git worktree. A command policy
  blocks pushes/publishes/credential reads; secrets are redacted from every artifact and never
  passed as command arguments.

## Permission profiles

| Profile | Edits | Commands | Network | Codex sandbox |
|---|---|---|---|---|
| `read-only` | no | limited | no | `read-only` |
| `safe-edit` (default) | yes | tests/build | no | `workspace-write` |
| `development` | yes | yes | yes | `workspace-write` |
| `full-access` | yes | yes | yes | `danger-full-access` |

## Security

See [SECURITY.md](SECURITY.md). Highlights: OS-keychain credentials, minimal subprocess
environments, worktree isolation, a command denylist, and secret redaction across
logs/events/reports.

## Development

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
```

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
