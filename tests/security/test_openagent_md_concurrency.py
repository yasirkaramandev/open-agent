"""OPENAGENT.md is jointly owned, and the user's half is never recoverable (spec §33).

OpenAgent owns the block between the markers; the user owns everything else. The database can
regenerate OpenAgent's half at any time, so losing it costs nothing — losing the user's prose costs
work that exists nowhere else.

Two independent defects, both of which destroyed that prose:

**Malformed markers replaced the whole file.** ``write_openagent_md`` looked for both markers and,
failing to find them, fell through to ``render_document()`` — which returns a *fresh* document. A
file with a ``BEGIN`` but no ``END`` (a truncated write, a bad merge resolution, a hand-edit) took
that path, and every hand-written line was replaced by boilerplate. Reproduced against the previous
implementation before the fix.

**Concurrent regeneration lost an edit.** The write was atomic, which means no reader ever saw a
half-written file. It does not mean two writers are safe: each read, regenerated, and replaced, and
whichever called ``os.replace`` second silently won. Durability and concurrency are different
properties, and the atomic write only ever provided the first.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from openagent.config import OPENAGENT_MD_END, OPENAGENT_MD_START
from openagent.core.models import AgentProfile, AgentRuntime, RuntimeType
from openagent.reporting.openagent_md import (
    OpenAgentMdConflict,
    document_lock_path,
    plan_openagent_md,
    write_openagent_md,
)

pytestmark = [pytest.mark.security, pytest.mark.multiprocess]

USER_PROSE = "Important project context that exists nowhere else."


def _agent(name: str) -> AgentProfile:
    return AgentProfile(name=name, runtime=AgentRuntime(type=RuntimeType.CLI, cli="codex"))


def _document(path: Path, *, body: str = "generated") -> None:
    path.write_text(
        f"# Notes\n\n{USER_PROSE}\n\n{OPENAGENT_MD_START}\n{body}\n{OPENAGENT_MD_END}\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- prose preservation


def test_regeneration_preserves_user_prose(tmp_path: Path) -> None:
    path = tmp_path / "OPENAGENT.md"
    _document(path)

    write_openagent_md(path, [_agent("coder")])

    text = path.read_text(encoding="utf-8")
    assert USER_PROSE in text
    assert "coder" in text


def test_truncated_block_is_refused_not_overwritten(tmp_path: Path) -> None:
    """The headline regression: a missing END marker used to delete the entire file."""

    path = tmp_path / "OPENAGENT.md"
    path.write_text(
        f"# Notes\n\n{USER_PROSE}\n\n{OPENAGENT_MD_START}\ntruncated\n", encoding="utf-8"
    )

    with pytest.raises(OpenAgentMdConflict) as excinfo:
        write_openagent_md(path, [_agent("coder")])

    assert USER_PROSE in path.read_text(encoding="utf-8"), "user prose was destroyed"
    assert "start marker" in str(excinfo.value)
    assert "sync-document" in str(excinfo.value), "the error must say how to fix it"


def test_orphan_end_marker_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "OPENAGENT.md"
    path.write_text(f"# Notes\n\n{USER_PROSE}\n\n{OPENAGENT_MD_END}\n", encoding="utf-8")

    with pytest.raises(OpenAgentMdConflict):
        write_openagent_md(path, [_agent("coder")])

    assert USER_PROSE in path.read_text(encoding="utf-8")


def test_duplicated_block_is_refused(tmp_path: Path) -> None:
    """Two generated blocks: rewriting either one silently discards the other."""

    path = tmp_path / "OPENAGENT.md"
    block = f"{OPENAGENT_MD_START}\nfirst\n{OPENAGENT_MD_END}\n"
    path.write_text(f"{USER_PROSE}\n\n{block}\n{block}", encoding="utf-8")

    with pytest.raises(OpenAgentMdConflict):
        write_openagent_md(path, [_agent("coder")])

    assert USER_PROSE in path.read_text(encoding="utf-8")


def test_inverted_markers_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "OPENAGENT.md"
    path.write_text(
        f"{USER_PROSE}\n{OPENAGENT_MD_END}\nbody\n{OPENAGENT_MD_START}\n", encoding="utf-8"
    )

    with pytest.raises(OpenAgentMdConflict):
        write_openagent_md(path, [_agent("coder")])

    assert USER_PROSE in path.read_text(encoding="utf-8")


def test_prose_without_a_block_gains_one_without_losing_anything(tmp_path: Path) -> None:
    """A user who deleted the block, or wrote the file themselves, keeps what they wrote."""

    path = tmp_path / "OPENAGENT.md"
    path.write_text(f"# My own file\n\n{USER_PROSE}\n", encoding="utf-8")

    write_openagent_md(path, [_agent("coder")])

    text = path.read_text(encoding="utf-8")
    assert USER_PROSE in text
    assert OPENAGENT_MD_START in text and OPENAGENT_MD_END in text


def test_invalid_utf8_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "OPENAGENT.md"
    path.write_bytes(b"# Notes\n\n\xff\xfe not utf-8 \n")

    with pytest.raises(OpenAgentMdConflict):
        write_openagent_md(path, [_agent("coder")])

    assert path.read_bytes().startswith(b"# Notes")


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific here")
def test_symlink_is_refused(tmp_path: Path) -> None:
    """Writing through a symlink would modify a file the user never nominated."""

    target = tmp_path / "elsewhere.md"
    target.write_text(USER_PROSE, encoding="utf-8")
    path = tmp_path / "OPENAGENT.md"
    path.symlink_to(target)

    with pytest.raises(OpenAgentMdConflict):
        write_openagent_md(path, [_agent("coder")])

    assert target.read_text(encoding="utf-8") == USER_PROSE


def test_missing_file_is_created(tmp_path: Path) -> None:
    """The refusals must not make a first-time write impossible."""

    path = tmp_path / "OPENAGENT.md"

    write_openagent_md(path, [_agent("coder")])

    assert "coder" in path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- dry run


def test_plan_does_not_touch_the_file(tmp_path: Path) -> None:
    path = tmp_path / "OPENAGENT.md"
    _document(path)
    before = path.read_bytes()

    planned = plan_openagent_md(path, [_agent("coder")])

    assert path.read_bytes() == before, "a dry run wrote to the file"
    assert "coder" in planned and USER_PROSE in planned


# --------------------------------------------------------------------------- concurrency


def test_concurrent_regeneration_does_not_lose_the_user_half(tmp_path: Path) -> None:
    path = tmp_path / "OPENAGENT.md"
    _document(path)
    barrier = Barrier(4)

    def regenerate(index: int) -> None:
        barrier.wait()
        write_openagent_md(path, [_agent(f"agent-{index}")])

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(regenerate, range(4)))

    text = path.read_text(encoding="utf-8")
    assert USER_PROSE in text
    assert text.count(OPENAGENT_MD_START) == 1, "concurrent writers duplicated the block"
    assert text.count(OPENAGENT_MD_END) == 1


_WRITER = textwrap.dedent(
    """
    import sys, time
    sys.path.insert(0, {src!r})
    from pathlib import Path
    from openagent.core.models import AgentProfile, AgentRuntime, RuntimeType
    from openagent.reporting.openagent_md import write_openagent_md

    path, name, start_at = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])
    while time.time() < start_at:
        time.sleep(0.001)
    write_openagent_md(
        path, [AgentProfile(name=name, runtime=AgentRuntime(type=RuntimeType.CLI, cli="codex"))]
    )
    print("ok")
    """
)


def test_separate_processes_do_not_corrupt_the_document(tmp_path: Path) -> None:
    """Real processes, because a threading lock proves nothing about two ``openagent`` commands."""

    import time

    path = tmp_path / "OPENAGENT.md"
    _document(path)
    script = tmp_path / "writer.py"
    script.write_text(_WRITER.format(src=str(Path("src").resolve())), encoding="utf-8")

    start_at = time.time() + 2.0
    processes = [
        subprocess.Popen(
            [sys.executable, str(script), str(path), f"agent-{index}", str(start_at)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(4)
    ]
    for process in processes:
        _stdout, stderr = process.communicate(timeout=90)
        assert process.returncode == 0, f"writer failed: {stderr[:2000]}"

    text = path.read_text(encoding="utf-8")
    assert USER_PROSE in text
    assert text.count(OPENAGENT_MD_START) == 1
    assert text.count(OPENAGENT_MD_END) == 1


def test_lock_lives_beside_the_project(tmp_path: Path) -> None:
    """A shared temp directory would let unrelated projects block each other."""

    path = tmp_path / "OPENAGENT.md"

    assert document_lock_path(path).is_relative_to(tmp_path)


# --------------------------------------------------------------------------- startup


def test_a_conflicted_document_does_not_block_startup(tmp_path: Path) -> None:
    """Refusing to write must never make OpenAgent unstartable.

    Startup replays pending journal operations, one of which regenerates this document. If that
    raised, a file the user has to fix by hand would take down the only interface that can fix it —
    strictly worse than the data loss being prevented.
    """

    from openagent.app import OpenAgentApp
    from openagent.config import Paths

    project = tmp_path / "proj"
    project.mkdir()
    document = project / "OPENAGENT.md"
    document.write_text(f"{USER_PROSE}\n{OPENAGENT_MD_START}\ntruncated\n", encoding="utf-8")

    paths = Paths(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        db_path=tmp_path / "data" / "openagent.db",
        project_root=project,
    )
    app = OpenAgentApp(paths)
    app.journal.begin("agent_document_sync", {"path": str(document)})

    # The pending operation is replayed here; it must not raise.
    OpenAgentApp(paths)

    assert USER_PROSE in document.read_text(encoding="utf-8")
