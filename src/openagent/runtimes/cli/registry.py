"""CLI adapter registry + discovery (spec §32 ``openagent discover``, §41 doctor)."""

from __future__ import annotations

from ...core.models import CliInstallation
from .base import CliAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter

#: Known first-class CLI adapters, keyed by type.
_BUILDERS = {
    "codex": CodexAdapter,
    "claude": ClaudeAdapter,
}


def build_cli_adapter(cli_type: str, executable: str | None = None) -> CliAdapter:
    builder = _BUILDERS.get(cli_type)
    if builder is None:
        raise KeyError(f"unknown CLI type {cli_type!r}; known: {sorted(_BUILDERS)}")
    return builder(executable) if executable else builder()


def known_cli_types() -> list[str]:
    return list(_BUILDERS)


def cli_install_status() -> list[tuple[str, bool]]:
    """``(cli_type, installed)`` for each known CLI, using each adapter's real executable lookup.

    The install check goes through the adapter (which knows its own executable name) rather than
    assuming the display/type name is the executable name.
    """

    status: list[tuple[str, bool]] = []
    for cli_type in _BUILDERS:
        adapter = build_cli_adapter(cli_type)
        installed = getattr(adapter, "executable", None) is not None
        status.append((cli_type, installed))
    return status


async def discover_installed() -> list[CliInstallation]:
    """Detect which known CLIs are installed on this machine (spec §32)."""

    found: list[CliInstallation] = []
    for cli_type in _BUILDERS:
        adapter = build_cli_adapter(cli_type)
        install = await adapter.detect()
        if install is not None:
            found.append(install)
    return found
