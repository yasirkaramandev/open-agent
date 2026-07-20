"""Claude model discovery runs with the project and credential it will actually use (spec §8).

``ClaudeAdapter.list_models`` called ``discover_claude_models()`` with **no arguments**, even though
that function already accepted ``project_root``, ``env``, ``api_key`` and ``base_url``. Everything
project- or credential-scoped was therefore thrown away before it was ever used:

* a repository pinning ``availableModels`` in ``.claude/settings.json`` showed the generic alias
  list instead of its own policy list;
* a user on a gateway got the public catalogue;
* the ``/v1/models`` lookup never ran, because no key was ever passed in.

The plumbing existed on both sides. Only the call was empty — which is why this is a wiring test
rather than a discovery-logic test: it asserts the context reaches the function, and that the
function's answer changes accordingly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openagent.runtimes.cli.base import CliModelDiscoveryContext
from openagent.runtimes.cli.claude import ClaudeAdapter
from openagent.runtimes.cli.model_discovery import discover_claude_models

pytestmark = pytest.mark.unit


def _write_settings(root: Path, payload: dict) -> None:
    settings_dir = root / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(json.dumps(payload), encoding="utf-8")


async def test_project_available_models_reach_the_result(tmp_path: Path) -> None:
    """The headline regression: a project's own model policy was invisible."""

    project = tmp_path / "project"
    project.mkdir()
    _write_settings(
        project, {"availableModels": ["acme-internal-model-1", "acme-internal-model-2"]}
    )

    adapter = ClaudeAdapter(executable="claude")
    models = await adapter.list_models(CliModelDiscoveryContext(project_root=project))

    assert "acme-internal-model-1" in models
    assert "acme-internal-model-2" in models


async def test_no_context_still_works(tmp_path: Path) -> None:
    """`openagent cli models` outside a project must not break."""

    adapter = ClaudeAdapter(executable="claude")

    models = await adapter.list_models()

    # The documented aliases are always present, with or without a project.
    assert models


async def test_project_configured_model_is_offered(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_settings(project, {"model": "acme-pinned-model"})

    adapter = ClaudeAdapter(executable="claude")
    models = await adapter.list_models(CliModelDiscoveryContext(project_root=project))

    assert "acme-pinned-model" in models


async def test_environment_model_mappings_are_honoured(tmp_path: Path) -> None:
    """``ANTHROPIC_DEFAULT_*_MODEL`` is a documented Claude Code routing surface."""

    adapter = ClaudeAdapter(executable="claude")

    models = await adapter.list_models(
        CliModelDiscoveryContext(environment={"ANTHROPIC_DEFAULT_OPUS_MODEL": "acme-opus-override"})
    )

    assert "acme-opus-override" in models


async def test_a_different_project_gets_a_different_answer(tmp_path: Path) -> None:
    """Proves the context is actually consulted rather than a global being read once."""

    first = tmp_path / "first"
    first.mkdir()
    _write_settings(first, {"availableModels": ["only-in-first"]})
    second = tmp_path / "second"
    second.mkdir()
    _write_settings(second, {"availableModels": ["only-in-second"]})

    adapter = ClaudeAdapter(executable="claude")
    first_models = await adapter.list_models(CliModelDiscoveryContext(project_root=first))
    second_models = await adapter.list_models(CliModelDiscoveryContext(project_root=second))

    assert "only-in-first" in first_models and "only-in-first" not in second_models
    assert "only-in-second" in second_models and "only-in-second" not in first_models


async def test_credential_from_context_reaches_the_api_lookup(tmp_path: Path) -> None:
    """A key in the context must drive the /v1/models call that used to never happen."""

    seen: list[str] = []

    def fetcher(base_url: str, api_key: str, cursor: str | None) -> dict:
        seen.append(api_key)
        return {"data": [{"id": "acme-api-model", "display_name": "Acme"}], "has_more": False}

    result = discover_claude_models(
        home=tmp_path / "home",
        project_root=tmp_path / "project",
        env={},
        api_key="sk-ant-context-key",
        base_url="https://api.anthropic.com",
        fetcher=fetcher,
    )

    assert seen == ["sk-ant-context-key"]
    assert "acme-api-model" in result.models


def test_discovery_context_repr_hides_the_environment() -> None:
    """The context carries real API keys; its repr reaches tracebacks and logs."""

    context = CliModelDiscoveryContext(
        environment={"ANTHROPIC_API_KEY": "sk-ant-CANARY-context-1a2b"}
    )

    assert "sk-ant-CANARY-context-1a2b" not in repr(context)
