# Contributing to OpenAgent

Thanks for your interest! OpenAgent is early (v0.1). Contributions that strengthen the core —
provider adapters, CLI adapters, tests, and safety — are especially welcome.

## Setup

```bash
python3.10 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Checks (run before opening a PR)

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
```

CI must stay green **without** live API access. Tests that hit real APIs or CLIs are opt-in
(`@pytest.mark.integration` / `@pytest.mark.live_cli`) and gated behind environment variables.

## Architecture at a glance

- `core/` — domain models, events, errors, permission profiles
- `providers/` — API adapters + shared httpx transport + compatibility profiles
- `runtimes/api_agent/` — OpenAgent's own tool loop; `runtimes/cli/` — CLI subprocess adapters
- `tools/`, `workspaces/`, `security/`, `credentials/` — the safe execution substrate
- `services/` — the single business layer used by CLI, TUI, and (later) MCP
- `reporting/`, `storage/`, `cli/`, `tui/`

## Adding a provider

Most providers are OpenAI- or Anthropic-compatible. Prefer:

1. Add a `ProviderPreset` in `providers/factory.py` (base URLs + default protocol).
2. Add a `CompatibilityProfile` in `providers/compat/profiles.py` for any deviations
   (tool_choice support, temperature bounds, max-token field, etc.).
3. Add **contract tests** mirroring `tests/contract/` — every adapter must pass the same battery
   (text / streaming / tool_call / tool_result / usage / 429 / auth / malformed).

Only write a bespoke adapter class when the protocol genuinely differs.

## Adding a CLI adapter

Implement the `CliAdapter` Protocol (`runtimes/cli/base.py`) with a **pure** event-mapping function
(like `map_codex_event`) that you can unit-test against a recorded JSONL fixture — no live binary
required in CI. For simple text-only CLIs, use the manifest-driven `GenericCliAdapter`.

## Commit style

Small, focused commits with a clear subject. Reference the spec section where relevant. New behavior
needs tests.

## License

By contributing you agree that your contributions are licensed under Apache-2.0.
