# Architecture

A short map of the codebase. The guiding idea: **one normalized event stream and one artifact bundle**
regardless of which backend runs the work.

## Layers

```
Interfaces      tui/ (Textual)   ·   cli/ (Typer)        [MCP, SDK planned]
                        │
Services        services/  — the single business layer (agent, provider, model,
                             run, discovery, doctor). CLI + TUI both call these.
                        │
Runtimes        runtimes/api_agent/  — OpenAgent's own loop for API models
                runtimes/cli/        — subprocess adapters (codex, claude, generic)
                        │
Substrate       providers/  tools/  workspaces/  security/  credentials/
                        │
Storage         storage/ (SQLite index)  ·  events.jsonl (source of truth)  ·  reporting/
```

## Key contracts

- **`ProviderAdapter`** (`providers/base.py`): `test_connection`, `list_models`, `probe_model`,
  `stream_response`, `count_tokens`. The agent loop speaks only normalized types.
- **`CliAdapter`** (`runtimes/cli/base.py`): `detect`, `inspect_auth`, `capabilities`, `start_run`,
  `resume_run`, `cancel`. Each maps native output to `NormalizedEvent`s via a **pure** function
  (e.g. `map_codex_event`) that is unit-tested against recorded fixtures.
- **`NormalizedEvent`** (`core/events.py`): the shared vocabulary (`run.*`, `message.*`, `tool.*`,
  `command.*`, `file.*`, `usage.updated`, …) written to `events.jsonl`.

## Data model separation

- `ProviderConnection` — an API account (no prompt/role); key stored once.
- `ModelProfile` — a concrete model + probed capabilities.
- `AgentProfile` — what the user runs: runtime (API or CLI) + prompt + tags + permission profile.
- `Run` / `Session` — an execution and its resumable conversation.

## Run pipeline (`services/run_service.py`)

1. Allocate a run id; snapshot the branch/commit.
2. Create an isolated git worktree (`openagent/run_<id>`), or a temp copy for non-git projects.
3. Dispatch to the API loop or a CLI adapter; stream `NormalizedEvent`s to `events.jsonl`.
4. Collect the diff, changed files, and test results.
5. Write the standard bundle and set the final status.
6. Support resume (CLI), cancel (process-tree kill), and orphan recovery.

## Why httpx-native providers

Most providers are OpenAI- or Anthropic-compatible variants. A single transport per protocol family
maximizes reuse and gives full control over streaming/usage/error normalization. Vendor SDKs can be
swapped into individual adapters later without changing the `ProviderAdapter` contract.
