from __future__ import annotations

from pathlib import Path

import pytest

from openagent.security import atomic


def test_atomic_write_works_without_fchmod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(atomic.os, "fchmod", raising=False)
    target = tmp_path / "state.json"

    atomic.atomic_write_text(target, "safe")

    assert target.read_text() == "safe"


def test_unavailable_directory_fsync_is_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        atomic.os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError())
    )

    atomic._fsync_directory(tmp_path)
