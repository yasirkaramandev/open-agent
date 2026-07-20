"""``CliUpdatePolicy.ASK`` actually asks (spec §8).

Before v0.1.5 it did not. ``preflight.py`` handled ``NEVER`` and ``AUTO`` explicitly and then fell
through to a single warning line for everything else — so ``ASK``, which is the **default** policy,
behaved exactly like ``NOTIFY``: print a message and start the run. A user who chose "ask me before
updating" was never asked, and nothing in the output revealed that.

The two things that make this dangerous to fix carelessly get their own cases:

* an ASK that cannot be answered must not hang a cron job or a CI run;
* "don't ask again" must not silence future versions, including security updates.
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
from openagent.runtimes.cli.update_policy import (
    UpdateChoice,
    UpdatePrompt,
    UpdatePromptSuppressions,
    decide_update,
    is_non_interactive,
    suppression_key,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def installation(tmp_path: Path) -> CliInstallation:
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    return CliInstallation(
        id="cli_codex",
        type="codex",
        executable=str(executable),
        resolved_executable=str(executable),
        version="1.0.0",
        install_source=CliInstallSource.NPM,
    )


@pytest.fixture()
def status() -> CliUpdateStatus:
    return CliUpdateStatus(
        current_version="1.0.0",
        latest_version="1.2.0",
        update_available=True,
        state=CliUpdateState.AVAILABLE,
        install_source=CliInstallSource.NPM,
        detail="1.0.0 -> 1.2.0",
    )


# --------------------------------------------------------------------------- it asks


def test_the_user_is_actually_asked(installation, status) -> None:
    """The regression, stated directly: the callback is invoked."""

    asked: list[UpdatePrompt] = []

    def callback(prompt: UpdatePrompt) -> UpdateChoice:
        asked.append(prompt)
        return UpdateChoice.CONTINUE_WITHOUT_UPDATING

    decide_update(installation, status, callback=callback, environ={})

    assert len(asked) == 1
    assert asked[0].cli_type == "codex"
    assert asked[0].current_version == "1.0.0"
    assert asked[0].latest_version == "1.2.0"
    assert "1.0.0" in asked[0].question() and "1.2.0" in asked[0].question()


@pytest.mark.parametrize(
    "choice",
    [
        UpdateChoice.UPDATE_NOW,
        UpdateChoice.CONTINUE_WITHOUT_UPDATING,
        UpdateChoice.CANCEL_RUN,
        UpdateChoice.SKIP_THIS_VERSION,
    ],
)
def test_every_choice_is_returned_to_the_caller(installation, status, choice) -> None:
    decision = decide_update(installation, status, callback=lambda _p: choice, environ={})

    assert decision.choice is choice


# --------------------------------------------------------------------------- it never hangs


def test_no_callback_degrades_to_notify(installation, status) -> None:
    """OpenAgent runs from cron and from pipes; ASK must not wait for input that never comes."""

    decision = decide_update(installation, status, callback=None, environ={})

    assert decision.choice is UpdateChoice.CONTINUE_WITHOUT_UPDATING
    assert decision.degraded is True


def test_ci_environment_is_not_prompted(installation, status) -> None:
    def callback(_prompt: UpdatePrompt) -> UpdateChoice:
        raise AssertionError("CI must never be prompted")

    decision = decide_update(installation, status, callback=callback, environ={"CI": "true"})

    assert decision.choice is UpdateChoice.CONTINUE_WITHOUT_UPDATING
    assert decision.degraded is True


def test_callback_returning_none_degrades(installation, status) -> None:
    """The authoritative "no UI attached" signal, since only the callback knows."""

    decision = decide_update(installation, status, callback=lambda _p: None, environ={})

    assert decision.choice is UpdateChoice.CONTINUE_WITHOUT_UPDATING
    assert decision.degraded is True


def test_a_crashing_prompt_does_not_take_the_run_with_it(installation, status) -> None:
    def callback(_prompt: UpdatePrompt) -> UpdateChoice:
        raise RuntimeError("the TUI modal blew up")

    decision = decide_update(installation, status, callback=callback, environ={})

    assert decision.choice is UpdateChoice.CONTINUE_WITHOUT_UPDATING
    assert "failed" in decision.detail


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, False),
        ({"CI": "true"}, True),
        ({"CI": "false"}, False),
        ({"OPENAGENT_NON_INTERACTIVE": "1"}, True),
    ],
)
def test_non_interactive_detection(environ, expected) -> None:
    assert is_non_interactive(environ) is expected


# --------------------------------------------------------------------------- suppression scope


def test_skip_this_version_suppresses_only_that_version(
    installation, status, tmp_path: Path
) -> None:
    """A suppression keyed on the CLI alone would silence every future update, including a fix."""

    suppressions = UpdatePromptSuppressions(tmp_path / "prompts.json")
    calls: list[UpdatePrompt] = []

    def callback(prompt: UpdatePrompt) -> UpdateChoice:
        calls.append(prompt)
        return UpdateChoice.SKIP_THIS_VERSION

    decide_update(installation, status, callback=callback, suppressions=suppressions, environ={})
    # Same question again: not re-asked.
    decide_update(installation, status, callback=callback, suppressions=suppressions, environ={})
    assert len(calls) == 1

    # A *newer* release is a different question and must be asked.
    newer = status.model_copy(update={"latest_version": "1.3.0"})
    decide_update(installation, newer, callback=callback, suppressions=suppressions, environ={})
    assert len(calls) == 2


def test_suppression_expires_when_the_binary_changes(installation, status, tmp_path: Path) -> None:
    """Reinstalling or updating by hand makes the old answer meaningless."""

    before = suppression_key(installation, status)

    Path(installation.executable).write_text("#!/bin/sh\necho different\n", encoding="utf-8")

    assert suppression_key(installation, status) != before


def test_suppression_file_records_no_readable_machine_details(
    installation, status, tmp_path: Path
) -> None:
    """The file is a set of answered-question identities, not a description of the machine."""

    path = tmp_path / "prompts.json"
    suppressions = UpdatePromptSuppressions(path)
    decide_update(
        installation,
        status,
        callback=lambda _p: UpdateChoice.SKIP_THIS_VERSION,
        suppressions=suppressions,
        environ={},
    )

    content = path.read_text(encoding="utf-8")
    assert installation.executable not in content


def test_unreadable_suppression_file_is_not_fatal(installation, status, tmp_path: Path) -> None:
    path = tmp_path / "prompts.json"
    path.write_text("{ this is not json", encoding="utf-8")
    suppressions = UpdatePromptSuppressions(path)

    decision = decide_update(
        installation,
        status,
        callback=lambda _p: UpdateChoice.CONTINUE_WITHOUT_UPDATING,
        suppressions=suppressions,
        environ={},
    )

    assert decision.choice is UpdateChoice.CONTINUE_WITHOUT_UPDATING
