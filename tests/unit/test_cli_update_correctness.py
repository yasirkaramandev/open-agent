"""An update reports success only when it can be proven to have worked (spec §8).

Three defects, all of which let a broken or absent update look fine.

1. **Version comparison discarded prerelease metadata.** ``_version_tuple`` was
   ``re.search(r"\\d+(?:\\.\\d+)+")`` followed by a tuple compare, so ``1.2.0`` and ``1.2.0rc1``
   both parsed to ``(1, 2, 0)`` and compared **equal**. An installed release candidate was reported
   as already current and never updated to the real release.

2. **Verification treated "cannot tell" as success.** ``perform_update`` ended with
   ``state = CURRENT if available is False else UNKNOWN`` and returned that as a normal result. So
   when the post-update binary was still the old version, or its version could not be parsed, the
   command exited 0 and the TUI showed no error while nothing had changed.

3. **npm provenance failed open.** ``_npm_owns`` ended with ``return not prefix or <match>``, so a
   failing ``npm prefix -g`` — npm absent, a permissions error, a timeout — produced an empty
   prefix and returned **True**. Absence of evidence became proof of ownership, and OpenAgent would
   then run ``npm install -g`` against an installation npm does not manage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openagent.core.models import (
    CliInstallation,
    CliInstallSource,
    CliUpdateState,
    CliUpdateStatus,
)
from openagent.runtimes.cli.installations import _npm_owns
from openagent.runtimes.cli.locator import CommandResult, ExecutableCandidate
from openagent.runtimes.cli.updates import _is_newer, parse_version, perform_update

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- version comparison


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        # The regression: a prerelease is older than its release, not equal to it.
        ("1.2.0", "1.2.0rc1", True),
        ("1.2.0", "1.2.0-rc.1", True),
        ("1.2.0rc1", "1.2.0", False),
        # Ordinary ordering still works.
        ("1.2.1", "1.2.0", True),
        ("1.2.0", "1.2.0", False),
        ("2.0.0", "1.99.99", True),
        ("1.10.0", "1.9.0", True),
        # A local version sorts *above* its base under PEP 440 (unlike SemVer build metadata,
        # which is ignored for ordering). Asserted explicitly so the difference is deliberate.
        ("1.2.0+build5", "1.2.0", True),
        # Post-releases are newer.
        ("1.2.0.post1", "1.2.0", True),
        # Unparseable input is "unknown", never a silent equal.
        ("not-a-version", "1.2.0", None),
        (None, "1.2.0", None),
        ("1.2.0", None, None),
    ],
)
def test_version_ordering(latest: str | None, current: str | None, expected: bool | None) -> None:
    assert _is_newer(latest, current) is expected


def test_version_is_extracted_from_a_noisy_version_line() -> None:
    """`--version` output is rarely just a version."""

    assert parse_version("claude 1.2.3 (Claude Code)") == parse_version("1.2.3")
    assert parse_version("codex-cli 0.5.0") == parse_version("0.5.0")


def test_prerelease_is_not_equal_to_release() -> None:
    """The precise assertion the old tuple parser got wrong."""

    assert parse_version("1.2.0rc1") != parse_version("1.2.0")
    assert parse_version("1.2.0rc1") < parse_version("1.2.0")


# --------------------------------------------------------------------------- update verification


def _installation(tmp_path: Path) -> CliInstallation:
    executable = tmp_path / "faketool"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    return CliInstallation(
        id="cli_fake",
        type="codex",
        executable=str(executable),
        resolved_executable=str(executable),
        version="1.0.0",
        install_source=CliInstallSource.NPM,
    )


def _status() -> CliUpdateStatus:
    return CliUpdateStatus(
        current_version="1.0.0",
        latest_version="1.2.0",
        update_available=True,
        state=CliUpdateState.AVAILABLE,
        install_source=CliInstallSource.NPM,
        update_method="npm-install-latest",
    )


def test_update_that_leaves_the_old_version_is_a_failure(tmp_path: Path) -> None:
    """The headline bug: updater exits 0, binary is unchanged, result used to be a success."""

    installation = _installation(tmp_path)

    def runner(argv, _timeout, _max_bytes):
        if argv[0] == "npm":
            return CommandResult(returncode=0, stdout="updated")
        if argv == [installation.executable, "--version"]:
            return CommandResult(returncode=0, stdout="1.0.0")  # still the old build
        raise AssertionError(argv)

    result = perform_update(installation, _status(), runner=runner, locks_dir=tmp_path / "locks")

    assert result.ran is True
    assert result.status.state is CliUpdateState.CHECK_FAILED
    assert "still running 1.0.0" in result.detail


def test_unparseable_post_update_version_is_a_failure(tmp_path: Path) -> None:
    """ "I cannot tell whether it worked" is not success, once an update has actually run."""

    installation = _installation(tmp_path)

    def runner(argv, _timeout, _max_bytes):
        if argv[0] == "npm":
            return CommandResult(returncode=0, stdout="updated")
        if argv == [installation.executable, "--version"]:
            return CommandResult(returncode=0, stdout="unreleased-build")
        raise AssertionError(argv)

    result = perform_update(installation, _status(), runner=runner, locks_dir=tmp_path / "locks")

    assert result.status.state is CliUpdateState.CHECK_FAILED
    assert "not comparable" in result.detail


def test_successful_update_is_reported_as_current(tmp_path: Path) -> None:
    """The fix must not make every update look broken."""

    installation = _installation(tmp_path)

    def runner(argv, _timeout, _max_bytes):
        if argv[0] == "npm":
            return CommandResult(returncode=0, stdout="updated")
        if argv == [installation.executable, "--version"]:
            return CommandResult(returncode=0, stdout="1.2.0")
        raise AssertionError(argv)

    result = perform_update(installation, _status(), runner=runner, locks_dir=tmp_path / "locks")

    assert result.status.state is CliUpdateState.CURRENT
    assert result.status.current_version == "1.2.0"


def test_vanished_executable_is_a_failure(tmp_path: Path) -> None:
    """An updater that wrote somewhere else leaves the path OpenAgent invokes gone."""

    installation = _installation(tmp_path)

    def runner(argv, _timeout, _max_bytes):
        if argv[0] == "npm":
            Path(installation.executable).unlink()
            return CommandResult(returncode=0, stdout="updated")
        raise AssertionError(argv)

    result = perform_update(installation, _status(), runner=runner, locks_dir=tmp_path / "locks")

    assert result.status.state is CliUpdateState.CHECK_FAILED
    assert "no longer exists" in result.detail


def test_a_second_updater_is_refused_while_one_holds_the_lock(tmp_path: Path) -> None:
    """Two package managers rewriting one binary interleave into a corrupt install."""

    from openagent.runtimes.cli.updates import update_lock_path
    from openagent.security.file_lock import file_lock

    installation = _installation(tmp_path)
    locks = tmp_path / "locks"

    def runner(argv, _timeout, _max_bytes):
        raise AssertionError("the second updater must not have run any command")

    with file_lock(update_lock_path(installation.type, locks), timeout=5):
        result = perform_update(
            installation,
            _status(),
            runner=runner,
            locks_dir=locks,
            lock_timeout=0.2,
        )

    assert result.status.state is CliUpdateState.BLOCKED
    assert "already updating" in result.detail
    assert result.ran is False


# --------------------------------------------------------------------------- npm provenance


def _candidate(path: str) -> ExecutableCandidate:
    return ExecutableCandidate(path=path, resolved_path=path, origin="npm")


def test_npm_ownership_fails_closed_when_prefix_cannot_be_read() -> None:
    """The exact fail-open: an unreadable prefix used to return True.

    Claiming NPM when npm does not own the binary means a later ``npm install -g pkg@latest``
    updates a copy in another prefix while the executable the user runs stays behind — and, because
    that command exits 0, the whole thing reports as a success.
    """

    def runner(argv, _timeout, _max_bytes):
        if argv[:3] == ["npm", "-g", "ls"]:
            return CommandResult(
                returncode=0, stdout='{"dependencies": {"@openai/codex": {"version": "1.0.0"}}}'
            )
        # Both path queries fail — npm is broken, or the user has no permission to read them.
        return CommandResult(returncode=1, stdout="", stderr="EACCES")

    assert _npm_owns("codex", _candidate("/usr/local/bin/codex"), runner) is False


def test_npm_ownership_requires_the_executable_to_live_under_an_npm_root() -> None:
    """A package npm knows about does not mean *this* binary is the one it installed."""

    def runner(argv, _timeout, _max_bytes):
        if argv[:3] == ["npm", "-g", "ls"]:
            return CommandResult(
                returncode=0, stdout='{"dependencies": {"@openai/codex": {"version": "1.0.0"}}}'
            )
        if argv == ["npm", "prefix", "-g"]:
            return CommandResult(returncode=0, stdout="/opt/homebrew\n")
        if argv == ["npm", "root", "-g"]:
            return CommandResult(returncode=0, stdout="/opt/homebrew/lib/node_modules\n")
        raise AssertionError(argv)

    # Installed somewhere npm does not manage.
    assert _npm_owns("codex", _candidate("/Users/x/.local/bin/codex"), runner) is False
    # Installed under the reported prefix.
    assert _npm_owns("codex", _candidate("/opt/homebrew/bin/codex"), runner) is True


def test_npm_ownership_accepts_the_module_root_too() -> None:
    """`npm root -g` is the other legitimate location, and either one is positive evidence."""

    def runner(argv, _timeout, _max_bytes):
        if argv[:3] == ["npm", "-g", "ls"]:
            return CommandResult(
                returncode=0, stdout='{"dependencies": {"@openai/codex": {"version": "1.0.0"}}}'
            )
        if argv == ["npm", "prefix", "-g"]:
            return CommandResult(returncode=1, stdout="")
        if argv == ["npm", "root", "-g"]:
            return CommandResult(returncode=0, stdout="/usr/lib/node_modules\n")
        raise AssertionError(argv)

    candidate = _candidate("/usr/lib/node_modules/@openai/codex/bin/codex.js")
    assert _npm_owns("codex", candidate, runner) is True


def test_npm_ownership_requires_the_package_to_be_installed() -> None:
    def runner(argv, _timeout, _max_bytes):
        if argv[:3] == ["npm", "-g", "ls"]:
            return CommandResult(returncode=1, stdout="{}")
        raise AssertionError(argv)

    assert _npm_owns("codex", _candidate("/opt/homebrew/bin/codex"), runner) is False
