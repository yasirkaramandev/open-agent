"""A single undecodable provider row degrades cleanly, never a raw ValidationError (spec §7.3).

The dashboard crash the user hit was ``providers.list`` letting one bad row blow up with a Pydantic
traceback — which also *prints the payload*, and a provider payload can hold a credential reference,
header or URL. The repository must raise a typed, redacted :class:`DataValidationError` instead, and
doctor must be able to survey the store without dying on the first bad row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from openagent.core.errors import DataValidationError
from openagent.storage.db import Database
from openagent.storage.repositories import Repositories


def _insert_corrupt_provider(database: Database, provider_id: str) -> None:
    with database.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO provider_connections "
                "(id, name, normalized_name, provider_type, enabled, state_revision, updated_at, "
                "data) VALUES (:id, :id, :id, 'openai', 1, 0, '', :data)"
            ),
            {"id": provider_id, "data": '{"totally": "not a provider"}'},
        )


def test_list_raises_typed_redacted_error_on_a_corrupt_row() -> None:
    database = Database.in_memory()
    _insert_corrupt_provider(database, "provider_bad")
    repos = Repositories(database)

    with pytest.raises(DataValidationError) as excinfo:
        repos.providers.list()

    error = excinfo.value
    assert error.record_id == "provider_bad"
    assert error.table == "provider_connections"
    # Redacted: the record id and error count only — never the offending payload.
    assert "not a provider" not in str(error)
    assert "provider_bad" in str(error)
    assert "openagent doctor" in str(error)


def test_get_raises_typed_error_on_a_corrupt_row() -> None:
    database = Database.in_memory()
    _insert_corrupt_provider(database, "provider_bad")
    repos = Repositories(database)

    with pytest.raises(DataValidationError):
        repos.providers.get("provider_bad")


def test_decode_report_does_not_raise_and_separates_good_from_bad() -> None:
    database = Database.in_memory()
    _insert_corrupt_provider(database, "provider_bad")
    repos = Repositories(database)

    providers, errors = repos.providers.decode_report()

    assert list(providers) == []
    assert len(errors) == 1
    assert errors[0]["record_id"] == "provider_bad"
    assert errors[0]["table"] == "provider_connections"
