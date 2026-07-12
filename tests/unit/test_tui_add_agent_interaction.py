"""Real-interaction pilot tests for the Add-Agent wizard (reproduce the Select.NULL crash).

Unlike the programmatic tests that assign ``select.value`` directly, these drive the widgets the way
a user does — focus a Select, open its overlay, and walk options with the keyboard — because that is
the path that left the CLI Select at ``Select.NULL`` and crashed on Create.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, Select

from openagent.app import OpenAgentApp
from openagent.config import Paths
from openagent.tui.app import OpenAgentTUI
from openagent.tui.screens.add_agent import AddAgentScreen
from openagent.tui.screens.lists import AgentsScreen


def _app(tmp_path: Path, *, with_provider: bool = False) -> OpenAgentApp:
    project = tmp_path / "proj"
    project.mkdir()
    oa = OpenAgentApp(Paths(
        data_dir=tmp_path / "data", config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "openagent.db", project_root=project,
    ))
    if with_provider:
        oa.providers.add(name="deepseek-main", provider_type="deepseek",
                         api_key="sk-x", store_key=False)
    return oa


async def _open_add(pilot) -> AddAgentScreen:
    pilot.app.open_section("add_agent")
    await pilot.pause()
    return pilot.app.screen


async def _pick(pilot, select: Select, value: str) -> None:
    """Choose ``value`` in ``select`` using only key presses (open overlay, walk, confirm).

    The overlay highlights the *currently selected* option, so navigate by the delta from the
    current value rather than a fixed count from the top.
    """
    options = [v for _, v in select._options]  # type: ignore[attr-defined]
    target = options.index(value)
    try:
        current = options.index(select.value)
    except ValueError:
        current = 0  # unselected (Select.NULL) -> overlay opens at the top
    pilot.app.screen.set_focus(select)
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    delta = target - current
    key = "down" if delta > 0 else "up"
    for _ in range(abs(delta)):
        await pilot.press(key)
    await pilot.press("enter")
    await pilot.pause()


# --------------------------------------------------------------------------- CLI: no selection

async def test_cli_with_no_selection_does_not_crash(tmp_path: Path):
    """The exact reported crash: CLI runtime, CLI left unselected (Select.NULL), Create pressed."""
    oa = _app(tmp_path)
    app = OpenAgentTUI(oa)
    async with app.run_test() as pilot:
        screen = await _open_add(pilot)
        await _pick(pilot, screen.query_one("#runtime", Select), "cli")
        # CLI select is genuinely unselected — the crashing precondition.
        assert screen.query_one("#cli", Select).value is Select.NULL
        screen.query_one("#name", Input).value = "no-cli"
        await pilot.click("#create")
        await pilot.pause()
        # No crash: form stays open, inline "Choose a CLI" shown, nothing created.
        assert isinstance(pilot.app.screen, AddAgentScreen)
        assert "Choose a CLI" in str(screen.query_one("#err-cli").render())
    assert oa.agents.list() == []


# --------------------------------------------------------------------------- CLI: real selection

async def test_real_codex_selection_via_keyboard(tmp_path: Path):
    oa = _app(tmp_path)
    app = OpenAgentTUI(oa)
    async with app.run_test() as pilot:
        screen = await _open_add(pilot)
        await _pick(pilot, screen.query_one("#runtime", Select), "cli")
        await _pick(pilot, screen.query_one("#cli", Select), "codex")
        screen.query_one("#name", Input).value = "codex-coder"
        await pilot.click("#create")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AgentsScreen)
    agent = oa.agents.get("codex-coder")
    assert agent is not None and agent.runtime.cli == "codex"


async def test_real_claude_selection_via_keyboard(tmp_path: Path):
    oa = _app(tmp_path)
    app = OpenAgentTUI(oa)
    async with app.run_test() as pilot:
        screen = await _open_add(pilot)
        await _pick(pilot, screen.query_one("#runtime", Select), "cli")
        await _pick(pilot, screen.query_one("#cli", Select), "claude")
        screen.query_one("#name", Input).value = "claude-coder"
        await pilot.click("#create")
        await pilot.pause()
    agent = oa.agents.get("claude-coder")
    assert agent is not None and agent.runtime.cli == "claude"


# --------------------------------------------------------------------------- API: new connection

async def test_api_new_connection_creates_provider_and_agent(tmp_path: Path):
    oa = _app(tmp_path)  # no providers -> defaults to the "connect new" path
    app = OpenAgentTUI(oa)
    async with app.run_test() as pilot:
        screen = await _open_add(pilot)
        # Runtime already API; api-mode defaults to "new" when there is nothing to reuse.
        assert screen.query_one("#api-new").display is True
        assert screen.query_one("#key-row").display is True  # keychain -> masked key field visible
        assert screen.query_one("#api_key", Input).password is True
        await _pick(pilot, screen.query_one("#preset", Select), "deepseek")
        screen.query_one("#conn_name", Input).value = "deepseek-main"
        screen.query_one("#api_key", Input).value = "sk-secret"
        screen.query_one("#model", Input).value = "deepseek-chat"
        screen.query_one("#name", Input).value = "ds-coder"
        with patch("openagent.credentials.store.CredentialStore.set_secret") as mock_set:
            await pilot.click("#create")
            await pilot.pause()
        assert mock_set.called  # key stored through the credential backend, not the agent record

    provider = oa.providers.get("deepseek-main")
    agent = oa.agents.get("ds-coder")
    assert provider is not None and provider.provider_type == "deepseek"
    assert agent is not None and agent.runtime.provider == "deepseek-main"
    assert agent.runtime.model == "deepseek-chat"
    # The secret never lands in the agent record or the project artifact.
    assert "sk-secret" not in agent.model_dump_json()
    md = tmp_path / "proj" / "OPENAGENT.md"
    if md.exists():
        assert "sk-secret" not in md.read_text()


# --------------------------------------------------------------------------- API: existing provider

async def test_api_existing_provider_no_key_field(tmp_path: Path):
    oa = _app(tmp_path, with_provider=True)  # a saved provider -> defaults to "existing"
    app = OpenAgentTUI(oa)
    async with app.run_test() as pilot:
        screen = await _open_add(pilot)
        assert screen.query_one("#api-existing").display is True
        assert screen.query_one("#api-new").display is False
        # No API-key field is shown for an existing connection.
        assert screen.query_one("#key-row").display is False
        await _pick(pilot, screen.query_one("#provider", Select), "deepseek-main")
        screen.query_one("#model", Input).value = "deepseek-chat"
        screen.query_one("#name", Input).value = "reuse-agent"
        await pilot.click("#create")
        await pilot.pause()
    agent = oa.agents.get("reuse-agent")
    assert agent is not None and agent.runtime.provider == "deepseek-main"


async def test_api_existing_without_provider_shows_error(tmp_path: Path):
    oa = _app(tmp_path, with_provider=True)
    app = OpenAgentTUI(oa)
    async with app.run_test() as pilot:
        screen = await _open_add(pilot)
        # Existing mode selected but no provider chosen, no model.
        screen.query_one("#name", Input).value = "incomplete"
        await pilot.click("#create")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AddAgentScreen)
        assert "required" in str(screen.query_one("#err-provider").render())
    assert oa.agents.get("incomplete") is None


# --------------------------------------------------------------------------- credential-source switching

async def test_credential_source_switching_toggles_fields(tmp_path: Path):
    oa = _app(tmp_path)
    app = OpenAgentTUI(oa)
    async with app.run_test() as pilot:
        screen = await _open_add(pilot)
        # keychain (default): masked key field visible, env field hidden.
        assert screen.query_one("#key-row").display is True
        assert screen.query_one("#env-row").display is False
        # env: env-var field visible, key field hidden.
        await _pick(pilot, screen.query_one("#cred", Select), "env")
        assert screen.query_one("#env-row").display is True
        assert screen.query_one("#key-row").display is False
        # none: neither key field visible.
        await _pick(pilot, screen.query_one("#cred", Select), "none")
        assert screen.query_one("#env-row").display is False
        assert screen.query_one("#key-row").display is False
