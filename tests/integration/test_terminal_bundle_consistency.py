"""Every terminal path must leave one consistent story behind (spec §7).

A run's outcome is recorded in several places at once: the SQLite row, the event log, and the
artifact bundle (``status.json``, ``result.json``, ``output.md``, ``timeline.md``, ``integrity.json``
…). Users and tooling read *different* ones of those. Before v0.1.4 only the mainline
completion/failure path updated them all; orphan recovery updated the database and wrote a ``log``
event, and cross-process cancel updated the database, wrote ``run.cancelled``, and refreshed only
``status.json``. So a recovered run could say, simultaneously:

    SQLite       orphaned
    events       (no terminal event at all)
    status.json  running
    result.json  running
    output.md    running

Which of those is "the" answer depends entirely on which file you happened to open. These tests pin
the invariant instead: whatever route a run took to a terminal state, everything that records that
state agrees, and exactly one terminal event exists.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from openagent.app import OpenAgentApp
from openagent.config import Paths
from openagent.core.events import EventType, NormalizedEvent
from openagent.core.models import ProcessIdentity, Run, RunStatus
from openagent.security.process import capture_process_identity
from openagent.services.run_service import CancelOutcome
from openagent.storage.event_log import EventLog

_SLEEPER = "import time; time.sleep(120)"


def _dead_identity() -> ProcessIdentity:
    """An identity for a PID that cannot be alive, so recovery classifies it as pid_gone."""

    return ProcessIdentity(
        pid=2**22 - 1,
        create_time=1.0,
        executable="/nonexistent/ghost",
        command_identity="ghost",
    )


#: Files whose contents state the run's outcome and must therefore agree with each other.
BUNDLE_STATUS_FILES = ("status.json", "result.json")


@pytest.fixture()
def app(tmp_path: Path) -> OpenAgentApp:
    project = tmp_path / "proj"
    project.mkdir()
    return OpenAgentApp(
        Paths(
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            db_path=tmp_path / "data" / "openagent.db",
            project_root=project,
        )
    )


def _seed_running(app: OpenAgentApp, *, run_id: str, identity: ProcessIdentity | None) -> Run:
    """A RUNNING run with a realistic run_dir, owned by nobody in this process."""

    run = Run(
        id=run_id,
        agent="ghost",
        status=RunStatus.RUNNING,
        project_id=app.runs.project_id,
        project_root=str(app.paths.project_root),
        artifact_dir=str(app.paths.run_dir(run_id)),
        pid=identity.pid if identity else None,
        pid_started_at=identity.create_time if identity else None,
        process_identity=identity,
    )
    app.repos.runs.upsert(run)
    run_dir = app.paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    log = EventLog(run_dir, index=app.repos.event_index, run_id=run_id)
    log.append(
        NormalizedEvent(run_id=run_id, type=EventType.RUN_STARTED, source="openagent", data={})
    )
    log.flush()
    return run


def _events(app: OpenAgentApp, run_id: str) -> list[dict]:
    path = app.paths.run_dir(run_id) / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _terminal_events(events: list[dict]) -> list[dict]:
    terminal = {"run.completed", "run.failed", "run.cancelled", "run.orphaned"}
    return [event for event in events if event["type"] in terminal]


def _assert_bundle_agrees(app: OpenAgentApp, run_id: str, expected_status: str) -> None:
    """The whole record of the run tells one story."""

    run_dir = app.paths.run_dir(run_id)

    # 1. The database.
    stored = app.repos.runs.get(run_id)
    assert stored is not None
    actual = stored.status.value if hasattr(stored.status, "value") else stored.status
    assert actual == expected_status, f"DB says {actual!r}, expected {expected_status!r}"

    # 2. The event log: exactly one terminal event, and it is last.
    events = _events(app, run_id)
    terminal = _terminal_events(events)
    assert terminal, "a terminal run recorded no terminal event"
    # One event per *outcome*: reconciling the same outcome twice must not duplicate it. A run may
    # legitimately pass through more than one terminal state (orphaned, then cancelled by the user),
    # so what is forbidden is a repeat of the same type, not a second transition.
    kinds = [event["type"] for event in terminal]
    assert len(kinds) == len(set(kinds)), f"duplicate terminal events: {kinds}"
    assert events[-1]["type"] == f"run.{expected_status}", (
        f"the log ends on {events[-1]['type']!r}, not the run's outcome run.{expected_status}"
    )

    # 3. The artifact bundle.
    for name in BUNDLE_STATUS_FILES:
        path = run_dir / name
        assert path.exists(), f"{name} was never written for a terminal run"
        payload = json.loads(path.read_text())
        assert payload.get("status") == expected_status, (
            f"{name} says {payload.get('status')!r} but the run is {expected_status!r}"
        )

    for name in ("output.md", "timeline.md", "integrity.json"):
        assert (run_dir / name).exists(), f"{name} is missing from a terminal run's bundle"

    # 4. The integrity manifest covers the bundle it shipped with.
    manifest = json.loads((run_dir / "integrity.json").read_text())
    covered = set(manifest.get("files", manifest))
    for name in (*BUNDLE_STATUS_FILES, "output.md", "timeline.md"):
        assert name in covered, f"integrity.json does not cover {name}"


# --------------------------------------------------------------------------- orphan recovery


@pytest.mark.parametrize(
    ("reason", "make_identity"),
    [
        ("orphaned_pid_gone", lambda: _dead_identity()),
        ("orphaned_pid_unknown", lambda: None),
    ],
)
def test_orphan_recovery_leaves_a_consistent_bundle(
    app: OpenAgentApp, reason: str, make_identity
) -> None:
    """Recovering an orphan must update everything that records the outcome, not just the row."""

    run_id = "run_orphan"
    _seed_running(app, run_id=run_id, identity=make_identity())

    recovered = app.runs.recover_orphans()
    assert run_id in recovered

    _assert_bundle_agrees(app, run_id, "orphaned")


def test_orphan_recovery_of_a_live_unattached_process_is_consistent(
    app: OpenAgentApp, tmp_path: Path
) -> None:
    """The live-process case additionally records the PID and that it was left running."""

    proc = subprocess.Popen([sys.executable, "-c", _SLEEPER], start_new_session=True)  # noqa: S603
    try:
        identity = capture_process_identity(proc.pid)
        assert identity is not None
        run_id = "run_orphan_live"
        _seed_running(app, run_id=run_id, identity=identity)

        assert run_id in app.runs.recover_orphans()
        _assert_bundle_agrees(app, run_id, "orphaned")

        stored = app.repos.runs.get(run_id)
        assert stored is not None
        assert stored.failure_type == "orphaned_unattached_process"

        # The audit note that the process was NOT killed must survive alongside the terminal event.
        events = _events(app, run_id)
        orphan_notes = [e for e in events if e["data"].get("kind") == "orphan"]
        assert orphan_notes and orphan_notes[0]["data"]["killed"] is False
        assert proc.poll() is None, "orphan recovery must never kill the process"
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_orphan_recovery_is_idempotent(app: OpenAgentApp) -> None:
    """Running recovery twice must not produce a second terminal event."""

    run_id = "run_orphan_twice"
    _seed_running(app, run_id=run_id, identity=_dead_identity())

    app.runs.recover_orphans()
    app.runs.recover_orphans()

    _assert_bundle_agrees(app, run_id, "orphaned")


def test_an_orphaned_run_refuses_resume(app: OpenAgentApp) -> None:
    # A real agent, so the refusal is about the orphan status rather than a missing agent.
    from openagent.core.models import RuntimeType

    app.agents.create(name="ghost", runtime_type=RuntimeType.CLI, cli="codex")
    run_id = "run_orphan_resume"
    _seed_running(app, run_id=run_id, identity=_dead_identity())
    app.runs.recover_orphans()

    stored = app.repos.runs.get(run_id)
    assert stored is not None
    supported, why = app.runs.resume_support(stored)
    assert not supported
    assert "orphan" in why.lower(), f"refused for the wrong reason: {why!r}"


# --------------------------------------------------------------------------- cross-process cancel


async def test_cancelling_an_orphan_records_a_second_real_transition(app: OpenAgentApp) -> None:
    """Idempotence must not swallow a genuine state change.

    Reconciliation is idempotent per outcome — running orphan recovery twice appends one
    ``run.orphaned``. But an orphaned run that the user then explicitly cancels really has changed
    state, so ``run.cancelled`` must be recorded and must end the log. Suppressing it would leave the
    log finishing on an audit note while the database said "cancelled".
    """

    proc = subprocess.Popen([sys.executable, "-c", _SLEEPER], start_new_session=True)  # noqa: S603
    try:
        identity = capture_process_identity(proc.pid)
        assert identity is not None
        run_id = "run_orphan_then_cancel"
        _seed_running(app, run_id=run_id, identity=identity)

        assert run_id in app.runs.recover_orphans()
        assert await app.runs.cancel(run_id, reason="user requested") is CancelOutcome.TERMINATED

        events = _events(app, run_id)
        kinds = [event["type"] for event in _terminal_events(events)]
        assert kinds == ["run.orphaned", "run.cancelled"], (
            f"expected both real transitions to be recorded, got {kinds}"
        )
        assert events[-1]["type"] == "run.cancelled"
        _assert_bundle_agrees(app, run_id, "cancelled")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


async def test_cross_process_cancel_leaves_a_consistent_bundle(app: OpenAgentApp) -> None:
    """Cancelling a run this process does not own must refresh the whole bundle, not status.json."""

    proc = subprocess.Popen([sys.executable, "-c", _SLEEPER], start_new_session=True)  # noqa: S603
    try:
        identity = capture_process_identity(proc.pid)
        assert identity is not None
        run_id = "run_xproc_cancel"
        _seed_running(app, run_id=run_id, identity=identity)

        outcome = await app.runs.cancel(run_id, reason="user requested")
        assert outcome is CancelOutcome.TERMINATED, f"cancel failed: {outcome}"

        _assert_bundle_agrees(app, run_id, "cancelled")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
