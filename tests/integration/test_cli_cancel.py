"""CLI cancellation actually terminates the process tree and records a cancelled run (spec §45).

Uses a real long-running subprocess via the fake adapter, driven through the full RunService so the
app-scoped adapter registry, immediate PID persistence, process-tree kill, ``run.cancelled`` event,
and idempotency are all exercised.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from openagent.app import OpenAgentApp
from openagent.config import Paths
from openagent.core.models import RunStatus, RuntimeType
from openagent.security.process import is_pid_alive
from tests.fakecli import FakeCliAdapter, install_fake_cli, write_fake_script


@pytest.fixture()
def app(tmp_path: Path) -> OpenAgentApp:
    project = tmp_path / "proj"
    project.mkdir()
    paths = Paths(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "openagent.db",
        project_root=project,
    )
    oa = OpenAgentApp(paths)
    oa.agents.create(
        name="fake-coder", runtime_type=RuntimeType.CLI, cli="fake", permission_profile="safe-edit"
    )
    return oa


@pytest.fixture()
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCliAdapter:
    script = write_fake_script(tmp_path)
    adapter = FakeCliAdapter(script, mode="longrun")
    install_fake_cli(monkeypatch, adapter)
    return adapter


async def _wait_for_pid(app: OpenAgentApp, run_id: str, timeout: float = 30.0) -> int:
    """Wait for the run to persist its pid.

    The timeout is a **safety net against hanging**, not an assertion about how fast startup is —
    nothing here is measuring performance. It used to be 5 seconds against roughly 3.5 seconds of
    real work (preflight, worktree creation, spawning an actual subprocess), a 1.4x margin, and the
    test failed intermittently: measured at roughly 1 in 20 runs in isolation and more often under
    full-suite load, with observed durations ranging from 3.4s to 4.5s.

    That is a flaky release gate, and the fix is not to retry it. The condition being waited on is
    "the pid was persisted", which either happens in well under a second or does not happen at all;
    a generous ceiling still catches a genuine hang while leaving no room for a slow CI runner to
    produce a false failure.
    """

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        run = app.runs.get(run_id)
        if run and run.pid:
            return run.pid
        await asyncio.sleep(0.02)
    raise AssertionError(f"pid was never persisted within {timeout}s")


async def test_cancel_terminates_process_and_marks_cancelled(app: OpenAgentApp, fake):
    run = app.runs.create(agent_name="fake-coder", prompt="do a long thing", worktree="auto")
    task = asyncio.create_task(app.runs.execute(run))

    pid = await _wait_for_pid(app, run.id)
    assert is_pid_alive(pid)
    # PID identity was captured immediately for safe later termination (spec §45).
    assert app.runs.get(run.id).pid_started_at is not None

    await app.runs.cancel(run.id)
    result = await task

    assert result.status == RunStatus.CANCELLED
    assert app.runs.get(run.id).status == RunStatus.CANCELLED
    # The whole process tree is gone.
    await asyncio.sleep(0.1)
    assert not is_pid_alive(pid)
    # A cancelled run must record run.cancelled and not be overwritten by completed.
    events = app.runs.output(run.id, "events")
    assert "run.cancelled" in events
    assert "run.completed" not in events
    # The terminal event is the LAST log entry (item 1) and the projection settles on cancelled,
    # never "cancelled/finalizing".
    parsed = [json.loads(line) for line in events.splitlines() if line.strip()]
    assert parsed[-1]["type"] == "run.cancelled"
    proj = app.runs.projection(run.id)
    assert proj.status == "cancelled"
    assert proj.phase == "cancelled"


async def test_cancel_is_idempotent(app: OpenAgentApp, fake):
    run = app.runs.create(agent_name="fake-coder", prompt="x", worktree="auto")
    task = asyncio.create_task(app.runs.execute(run))
    await _wait_for_pid(app, run.id)
    await app.runs.cancel(run.id)
    await task
    # A second cancel on an already-terminal run is a no-op, not an error.
    await app.runs.cancel(run.id)
    assert app.runs.get(run.id).status == RunStatus.CANCELLED


async def test_completed_run_not_marked_cancelled(
    app: OpenAgentApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    adapter = FakeCliAdapter(write_fake_script(tmp_path), mode="complete")
    install_fake_cli(monkeypatch, adapter)
    run = app.runs.create(agent_name="fake-coder", prompt="quick", worktree="auto")
    result = await app.runs.execute(run)
    assert result.status == RunStatus.COMPLETED
    assert "run.completed" in app.runs.output(run.id, "events")
