"""Only one process may start a turn for a run (spec §8).

Resume was guarded by ``asyncio.Lock``. That protects one event loop in one process, and OpenAgent
is explicitly a multi-process tool: a TUI in one terminal, a CLI in another, both pointed at the same
global database. Two of them could each pass the lock check and both start a backend for the same
run — duplicate turn numbers, interleaved event sequences, two terminal events, and two processes
writing the same artifact directory.

The lease lives in the database, so the database picks the winner. These tests use **real
subprocesses**: a thread-based test would pass against the very ``asyncio.Lock`` that is the bug.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from openagent.core.models import Run, RunStatus
from openagent.storage.db import Database
from openagent.storage.repositories import RunRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

RUN_ID = "run_lease"


def _seed(db_path: Path, *, status: RunStatus = RunStatus.COMPLETED) -> RunRepository:
    repo = RunRepository(Database.open(db_path))
    repo.upsert(Run(id=RUN_ID, agent="codex", status=status, workspace="/tmp/proj"))
    return repo


def _claimer_script(db_path: Path, turn_id: str) -> str:
    return textwrap.dedent(
        f"""
        import json, sys
        sys.path.insert(0, {str(SRC)!r})
        from pathlib import Path
        from openagent.storage.db import Database
        from openagent.storage.repositories import RunRepository

        repo = RunRepository(Database.open(Path({str(db_path)!r})))
        won = repo.claim_turn(
            {RUN_ID!r},
            turn_id={turn_id!r},
            pid=1234,
            create_time=1.0,
            started_at="2026-01-01T00:00:00+00:00",
        )
        print(json.dumps({{"turn_id": {turn_id!r}, "won": won}}), flush=True)
        """
    ).strip()


def _run_claimers(db_path: Path, count: int) -> list[dict]:
    """Start ``count`` separate processes that all try to claim the same run at once."""

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _claimer_script(db_path, f"turn-{n}")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for n in range(count)
    ]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, f"claimer failed: {err}"
        results.append(json.loads(out.strip().splitlines()[-1]))
    return results


def test_only_one_process_wins_the_turn(tmp_path: Path) -> None:
    """The headline: N processes race, exactly one may proceed."""

    db_path = tmp_path / "openagent.db"
    repo = _seed(db_path)

    results = _run_claimers(db_path, 6)

    winners = [result for result in results if result["won"]]
    assert len(winners) == 1, f"{len(winners)} processes each believed they owned the turn"

    owner = repo.turn_owner(RUN_ID)
    assert owner is not None
    assert owner[0] == winners[0]["turn_id"], (
        "the database records a different owner than the winner"
    )


def test_the_loser_does_not_change_the_row(tmp_path: Path) -> None:
    """A losing claim must be a no-op, not a partial write."""

    db_path = tmp_path / "openagent.db"
    repo = _seed(db_path)

    assert repo.claim_turn(
        RUN_ID, turn_id="first", pid=1, create_time=1.0, started_at="2026-01-01T00:00:00+00:00"
    )
    revision_after_win = repo.revision_of(RUN_ID)

    assert not repo.claim_turn(
        RUN_ID, turn_id="second", pid=2, create_time=2.0, started_at="2026-01-01T00:00:01+00:00"
    )

    assert repo.revision_of(RUN_ID) == revision_after_win, "the losing claim wrote to the row"
    owner = repo.turn_owner(RUN_ID)
    assert owner is not None and owner[0] == "first"


def test_a_released_lease_can_be_claimed_again(tmp_path: Path) -> None:
    db_path = tmp_path / "openagent.db"
    repo = _seed(db_path)

    assert repo.claim_turn(
        RUN_ID, turn_id="first", pid=1, create_time=1.0, started_at="2026-01-01T00:00:00+00:00"
    )
    # A run mid-turn is running, so it must be put back into a resumable state on release.
    run = repo.get(RUN_ID)
    assert run is not None
    run.status = RunStatus.COMPLETED
    repo.upsert(run)
    assert repo.release_turn(RUN_ID, turn_id="first")
    assert repo.turn_owner(RUN_ID) is None

    assert repo.claim_turn(
        RUN_ID, turn_id="second", pid=2, create_time=2.0, started_at="2026-01-01T00:00:02+00:00"
    )


def test_only_the_owner_may_release(tmp_path: Path) -> None:
    """A second process must not be able to drop someone else's lease."""

    db_path = tmp_path / "openagent.db"
    repo = _seed(db_path)
    assert repo.claim_turn(
        RUN_ID, turn_id="mine", pid=1, create_time=1.0, started_at="2026-01-01T00:00:00+00:00"
    )

    assert not repo.release_turn(RUN_ID, turn_id="not-mine")
    owner = repo.turn_owner(RUN_ID)
    assert owner is not None and owner[0] == "mine"


@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.ORPHANED])
def test_a_run_in_a_non_resumable_state_cannot_be_claimed(
    tmp_path: Path, status: RunStatus
) -> None:
    """The lease is not a way around the resume policy."""

    db_path = tmp_path / "openagent.db"
    repo = _seed(db_path, status=status)

    assert not repo.claim_turn(
        RUN_ID, turn_id="turn", pid=1, create_time=1.0, started_at="2026-01-01T00:00:00+00:00"
    )


# --------------------------------------------------------------------------- stale-write guard


def test_a_stale_run_object_cannot_overwrite_a_newer_status(tmp_path: Path) -> None:
    """The §9.3 case: a long-lived in-memory Run must not resurrect an old state.

    One process reads a run, another finishes and cancels it, and the first then writes its stale
    copy back. Without a revision check the last writer wins and the run silently returns to
    "running" — with a revision check the stale write is refused.
    """

    db_path = tmp_path / "openagent.db"
    repo = _seed(db_path, status=RunStatus.RUNNING)

    stale = repo.get(RUN_ID)
    assert stale is not None
    stale_revision = repo.revision_of(RUN_ID)
    assert stale_revision is not None

    # Another actor reaches a terminal state.
    current = repo.get(RUN_ID)
    assert current is not None
    current.status = RunStatus.CANCELLED
    repo.upsert(current)

    # The stale holder tries to write its old view back.
    stale.status = RunStatus.RUNNING
    assert not repo.update_if_unchanged(stale, expected_revision=stale_revision), (
        "a stale Run object overwrote a newer status"
    )

    stored = repo.get(RUN_ID)
    assert stored is not None
    assert stored.status is RunStatus.CANCELLED


def test_run_updates_never_delete_the_row(tmp_path: Path) -> None:
    """§9.1: an update must keep the row's identity, not replace it.

    Checked through SQLite's own ``rowid``: a DELETE + INSERT gives the row a new one, so this fails
    loudly if the old upsert shape ever comes back.
    """

    db_path = tmp_path / "openagent.db"
    repo = _seed(db_path, status=RunStatus.RUNNING)

    def _rowid() -> int:
        with repo.db.engine.connect() as conn:
            row = conn.exec_driver_sql(
                f"SELECT rowid FROM runs WHERE id = '{RUN_ID}'"  # noqa: S608 - fixed test constant
            ).first()
        assert row is not None
        return int(row[0])

    original = _rowid()
    for status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        run = repo.get(RUN_ID)
        assert run is not None
        run.status = status
        repo.upsert(run)
        assert _rowid() == original, "the run row was deleted and re-inserted rather than updated"


def test_upsert_bumps_the_revision(tmp_path: Path) -> None:
    """Optimistic concurrency needs the token to actually move."""

    db_path = tmp_path / "openagent.db"
    repo = _seed(db_path, status=RunStatus.RUNNING)

    first = repo.revision_of(RUN_ID)
    run = repo.get(RUN_ID)
    assert run is not None and first is not None
    repo.upsert(run)
    second = repo.revision_of(RUN_ID)
    assert second is not None and second > first
