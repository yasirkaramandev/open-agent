# OpenAgent

[![CI](https://github.com/yasirkaramandev/open-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/yasirkaramandev/open-agent/actions/workflows/ci.yml)

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
OpenAI-compatible API agents with a tool loop, CLI adapters (Codex, Claude Code), isolated
worktrees, permission profiles, OS-keychain credentials, and the standard run bundle. See
[ROADMAP.md](ROADMAP.md) for what's next.

### Maturity — what's actually verified

We try to be precise about what is proven vs. pending, so nothing here is oversold.

| Area | State |
|---|---|
| API agents (OpenAI Chat/Responses, Anthropic, OpenAI-compatible) | Offline-tested end to end (mocked HTTP): tool loop, worktree diff, artifacts, redaction. Not yet exercised against a paid live key in CI. |
| **Codex CLI** | Event schema validated **live** against `codex-cli 0.142.5`; the full run/cancel/terminal-state pipeline is exercised via a real-subprocess fake-CLI harness. A **successful real model turn is pending account/usage-limit availability**. |
| **Claude Code** | **Fixture-validated** — the `stream-json` mapping and invocation are ready, but not yet run against an installed `claude` on this machine. Treat as unverified against a live CLI. |
| TUI (dashboard, agents, providers, add/edit agent, run, approvals) | Pilot-tested against **Textual 8.2.8**, including **real keyboard-driven** dropdown selection (open overlay + arrow keys, not just `.value` assignment): creating Codex/Claude agents, the unified API onboarding (reuse a saved connection *or* connect a new API — key, Test Connection, Load Models — inside Add Agent), empty-selection handling (no crash, inline "Choose a CLI"), validation, provider add, and the approval modal. Every `Select` empty state is normalised so no Textual sentinel reaches a service or model. |
| Security (minimal env, command allowlist, worktree isolation, redaction, process-tree cancel) | Unit + integration tested (see `tests/`). |
| **AGY** | **Not part of v0.1.** |
| **Gemini** | **Not part of v0.1.** |

Everything above except the live-CLI/live-API caveats runs in the **offline test suite in CI**
(Ubuntu 3.10/3.11/3.12) with no API keys and no installed CLIs.

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
#   --worktree auto|none|copy   (none needs -y to confirm running in place)
#   -y / --yes                   approve high-risk ops non-interactively (records approval events)
openagent run --name codex-coder --prompt "update the WSS client in main.py" --worktree auto
openagent output --id <run-id> --format md
openagent output --id <run-id> --format diff

# Continue the session with another turn; cancel a live run (terminates the process tree)
openagent message --id <run-id> -p "now add a test"
openagent cancel --id <run-id>
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
* **Safety first.** Every file-changing run happens in an isolated worktree. Commands run in a
  minimal environment (no inherited secrets) behind an executable **allowlist**; secrets are redacted
  from every artifact — including the prompt and the diff — and never passed as command arguments.

## Permission profiles

| Profile | Edits | Commands | Network | Codex sandbox |
|---|---|---|---|---|
| `read-only` | no | limited | no | `read-only` |
| `safe-edit` (default) | yes | tests/build | no | `workspace-write` |
| `development` | yes | yes | yes | `workspace-write` |
| `full-access` | yes | yes | yes | `danger-full-access` |

## Security

See [SECURITY.md](SECURITY.md). Highlights: OS-keychain credentials, minimal subprocess
environments (no inherited secrets), worktree isolation, an executable **allowlist** with approval
gating, process-tree cancellation with PID-identity verification, and secret redaction across every
artifact (prompt and diff included).

## Development

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
.venv/bin/python -m build
```

The same checks run in [GitHub Actions](.github/workflows/ci.yml) on every push and pull request:
`ruff` + `mypy` + the full offline `pytest` suite on Ubuntu (Python 3.10 / 3.11 / 3.12), a package
build, and a clean-venv wheel-install + entrypoint check, plus cross-platform smoke jobs on macOS and
Windows. The offline suite requires **no API keys and no installed CLIs** — CLI runs are exercised
with a real-subprocess fake, and providers with mocked HTTP.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
