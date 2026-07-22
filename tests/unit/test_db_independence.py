"""``version`` and ``update`` must not open the database (spec §6.2).

The whole point of the compatibility gate is that an old binary which cannot read a newer database
can still repair itself. That only holds if the repair commands never instantiate the app or open
the DB. Proven here against a database poisoned so *any* current binary is refused: ``provider list``
is refused (the poison works), while ``version`` and ``update --check`` succeed regardless.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from openagent.cli.app import app
from openagent.core.errors import DatabaseReaderCompatibilityError
from openagent.storage.db import Database


def _poison_db(data_dir: Path) -> None:
    """A real DB whose recorded minimum reader version is far in the future, so no current binary
    may open it — the exact shape a genuinely-too-new database has."""

    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "openagent.db"
    Database.open(db_path).engine.dispose()
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO schema_meta (key, value) VALUES ('minimum_reader_version', '99.0.0') "
                "ON CONFLICT(key) DO UPDATE SET value='99.0.0'"
            )
        )
    engine.dispose()


@pytest.fixture
def poisoned_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    _poison_db(data_dir)
    monkeypatch.setenv("OPENAGENT_DATA_DIR", str(data_dir))
    return data_dir


def test_a_command_that_opens_the_db_is_refused(poisoned_env: Path) -> None:
    """Proves the poison is effective: anything that opens the DB hits the compatibility gate."""

    result = CliRunner().invoke(app, ["provider", "list"])
    assert isinstance(result.exception, DatabaseReaderCompatibilityError)


def test_version_never_opens_the_database(poisoned_env: Path) -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.exception is None


def test_update_check_never_opens_the_database(poisoned_env: Path) -> None:
    result = CliRunner().invoke(app, ["update", "--check"])
    # It may or may not find an update, but it must never fail by opening the unreadable DB.
    assert not isinstance(result.exception, DatabaseReaderCompatibilityError)
