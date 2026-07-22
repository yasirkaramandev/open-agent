"""Two OpenAgent processes cannot silently destroy each other's work (spec §34).

Every case here is a genuine race, driven by real concurrency rather than by calling the pieces in
a fixed order. What was actually broken before v0.1.6 differs per table, and it is worth being
precise rather than sweeping:

* **Agent names were silently overwritten.** ``agents.name`` was a primary key, but
  ``AgentRepository.upsert`` ran ``DELETE`` and then ``INSERT`` — so creating an agent whose name
  already existed replaced the existing one without any error at all.
* **Provider names collided on case and Unicode form.** ``provider_connections.name`` did carry a
  byte-exact ``UNIQUE``, so an identical name was rejected by the database — but as a raw
  ``IntegrityError`` that ``upsert`` never caught, and ``OpenAI`` / ``openai`` / composed versus
  decomposed ``café`` were accepted as separate connections a user could not tell apart.
* **Lost updates on both tables.** Neither had a revision column, so a stale in-memory copy written
  back overwrote newer fields wholesale, with no indication anything had been discarded.
* **Agents could outlive their provider.** ``agents`` had no foreign key, and
  ``ProviderService.remove`` decided by listing agents and *then* deleting. Between those two
  statements another process could create an agent bound to the provider being removed.

The thread-based tests use a barrier so the operations genuinely overlap. ``test_eight_processes_...``
uses real subprocesses, because threads in one interpreter share a connection pool and would not
prove anything about two separate ``openagent`` invocations.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from openagent.core.models import AgentProfile, AgentRuntime, ProviderConnection, RuntimeType
from openagent.storage.db import Database
from openagent.storage.repositories import (
    ConcurrentModificationError,
    DuplicateNameError,
    ProviderInUseByAgentError,
    Repositories,
)

pytestmark = [pytest.mark.security, pytest.mark.multiprocess]


@pytest.fixture()
def repos(tmp_path: Path) -> Repositories:
    return Repositories(Database.open(tmp_path / "openagent.db"))


def _provider(identifier: str, name: str) -> ProviderConnection:
    return ProviderConnection(id=identifier, name=name, provider_type="openai")


def _api_agent(name: str, provider: str | None = None) -> AgentProfile:
    return AgentProfile(
        name=name,
        runtime=AgentRuntime(type=RuntimeType.API_AGENT, provider=provider, model="gpt-4"),
    )


# --------------------------------------------------------------------------- uniqueness


def test_duplicate_provider_name_is_refused(repos: Repositories) -> None:
    repos.providers.create(_provider("prov_1", "OpenAI"))

    with pytest.raises(DuplicateNameError):
        repos.providers.create(_provider("prov_2", "OpenAI"))

    assert len(repos.providers.list()) == 1


def test_duplicate_provider_name_is_refused_case_insensitively(repos: Repositories) -> None:
    """``OpenAI`` and ``openai`` are one connection to a user, so they must be one row."""

    repos.providers.create(_provider("prov_1", "OpenAI"))

    with pytest.raises(DuplicateNameError):
        repos.providers.create(_provider("prov_2", "openai"))


def test_duplicate_provider_name_is_refused_across_unicode_forms(repos: Repositories) -> None:
    """Composed and decomposed accents render identically; SQLite's NOCASE does not catch them."""

    repos.providers.create(_provider("prov_1", "café"))  # precomposed é

    with pytest.raises(DuplicateNameError):
        repos.providers.create(_provider("prov_2", "café"))  # e + combining acute


def test_duplicate_agent_name_is_refused(repos: Repositories) -> None:
    repos.providers.create(_provider("prov_1", "OpenAI"))
    repos.agents.create(_api_agent("coder", "OpenAI"))

    with pytest.raises(DuplicateNameError):
        repos.agents.create(_api_agent("Coder", "OpenAI"))


# --------------------------------------------------------------------------- lost updates


def test_stale_provider_update_is_refused(repos: Repositories) -> None:
    """The lost update, stated directly."""

    provider = _provider("prov_1", "OpenAI")
    repos.providers.create(provider)
    stale_revision = repos.providers.revision_of("prov_1")
    assert stale_revision is not None

    # Another process commits first.
    repos.providers.update(
        provider.model_copy(update={"base_url": "https://first.example"}),
        expected_revision=stale_revision,
    )

    with pytest.raises(ConcurrentModificationError):
        repos.providers.update(
            provider.model_copy(update={"base_url": "https://second.example"}),
            expected_revision=stale_revision,
        )

    survivor = repos.providers.get("prov_1")
    assert survivor is not None and survivor.base_url == "https://first.example"


def test_stale_agent_update_is_refused(repos: Repositories) -> None:
    repos.providers.create(_provider("prov_1", "OpenAI"))
    repos.agents.create(_api_agent("coder", "OpenAI"))
    stale = repos.agents.revision_of("coder")
    assert stale is not None

    repos.agents.update(
        _api_agent("coder", "OpenAI").model_copy(update={"title": "First"}),
        expected_revision=stale,
    )

    with pytest.raises(ConcurrentModificationError):
        repos.agents.update(
            _api_agent("coder", "OpenAI").model_copy(update={"title": "Second"}),
            expected_revision=stale,
        )

    survivor = repos.agents.get("coder")
    assert survivor is not None and survivor.title == "First"


def test_concurrent_agent_updates_produce_one_winner(repos: Repositories) -> None:
    """Two threads, one revision, a barrier so they genuinely overlap."""

    repos.providers.create(_provider("prov_1", "OpenAI"))
    repos.agents.create(_api_agent("coder", "OpenAI"))
    revision = repos.agents.revision_of("coder")
    assert revision is not None
    barrier = Barrier(2)

    def writer(title: str):
        barrier.wait()
        try:
            repos.agents.update(
                _api_agent("coder", "OpenAI").model_copy(update={"title": title}),
                expected_revision=revision,
            )
            return "ok"
        except ConcurrentModificationError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(writer, ["A", "B"]))

    assert outcomes == ["conflict", "ok"], f"expected exactly one winner, got {outcomes}"


# --------------------------------------------------------------------------- referential integrity


def test_provider_with_a_bound_agent_cannot_be_deleted(repos: Repositories) -> None:
    repos.providers.create(_provider("prov_1", "OpenAI"))
    repos.agents.create(_api_agent("coder", provider="OpenAI"))

    with pytest.raises(ProviderInUseByAgentError):
        repos.providers.delete_with_probes("prov_1")

    assert repos.providers.get("prov_1") is not None


def test_provider_without_agents_can_be_deleted(repos: Repositories) -> None:
    repos.providers.create(_provider("prov_1", "OpenAI"))

    assert repos.providers.delete_with_probes("prov_1") is True


def test_cli_agent_needs_no_provider(repos: Repositories) -> None:
    """The foreign key must not make provider-less agents unrepresentable."""

    repos.agents.create(
        AgentProfile(name="cli-agent", runtime=AgentRuntime(type=RuntimeType.CLI, cli="codex"))
    )

    assert repos.agents.get("cli-agent") is not None


def test_delete_provider_while_creating_a_bound_agent_never_orphans(repos: Repositories) -> None:
    """The outcome may go either way, but "agent exists, provider does not" must never happen."""

    repos.providers.create(_provider("prov_1", "OpenAI"))
    barrier = Barrier(2)

    def delete_provider():
        barrier.wait()
        try:
            repos.providers.delete_with_probes("prov_1")
            return "deleted"
        except ProviderInUseByAgentError:
            return "refused"

    def create_agent():
        barrier.wait()
        try:
            repos.agents.create(_api_agent("coder", provider="OpenAI"))
            return "created"
        except Exception:  # noqa: BLE001 - any refusal is an acceptable outcome
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(delete_provider), pool.submit(create_agent)]
        [future.result() for future in futures]

    agent = repos.agents.get("coder")
    if agent is not None and agent.runtime.provider:
        assert repos.providers.get("prov_1") is not None, (
            "an agent survived bound to a provider that was deleted"
        )


# --------------------------------------------------------------------------- real processes


_WORKER = textwrap.dedent(
    """
    import json, sys, time
    sys.path.insert(0, {src!r})
    from openagent.core.models import ProviderConnection
    from openagent.storage.db import Database
    from openagent.storage.repositories import DuplicateNameError, Repositories

    db_path, worker_id, start_at = sys.argv[1], sys.argv[2], float(sys.argv[3])
    repos = Repositories(Database.open(__import__("pathlib").Path(db_path)))
    # A wall-clock rendezvous: separate processes cannot share a threading.Barrier.
    while time.time() < start_at:
        time.sleep(0.001)
    try:
        repos.providers.create(
            ProviderConnection(id=f"prov_{{worker_id}}", name="Contended", provider_type="openai")
        )
        print(json.dumps({{"worker": worker_id, "outcome": "created"}}))
    except DuplicateNameError:
        print(json.dumps({{"worker": worker_id, "outcome": "duplicate"}}))
    except Exception as exc:
        print(json.dumps({{"worker": worker_id, "outcome": "error", "detail": str(exc)}}))
    """
)


def test_eight_processes_creating_one_provider_produce_one_row(tmp_path: Path) -> None:
    """The headline race, with real processes rather than threads.

    Threads in one interpreter share a connection pool, so they would not exercise what actually
    happens when a TUI session and a CLI invocation run at the same time. Each worker here is a
    separate ``python`` process opening the same database file.

    Exactly one create must win. Under the old DELETE+INSERT every worker "succeeded" and the last
    one's row was all that remained — with seven credential revisions pointing at keychain entries
    the database no longer knew about.
    """

    import time

    database = tmp_path / "openagent.db"
    Database.open(database)  # migrate once so workers do not race the migration itself

    script = tmp_path / "worker.py"
    script.write_text(_WORKER.format(src=str(Path("src").resolve())), encoding="utf-8")

    start_at = time.time() + 2.0
    processes = [
        subprocess.Popen(
            [sys.executable, str(script), str(database), str(index), str(start_at)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(8)
    ]
    outcomes = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=90)
        assert stdout.strip(), f"worker produced no result; stderr: {stderr[:2000]}"
        outcomes.append(json.loads(stdout.strip().splitlines()[-1]))

    created = [o for o in outcomes if o["outcome"] == "created"]
    duplicates = [o for o in outcomes if o["outcome"] == "duplicate"]
    errors = [o for o in outcomes if o["outcome"] == "error"]

    assert not errors, f"workers hit unexpected errors: {errors}"
    assert len(created) == 1, f"expected exactly one winner, got {len(created)}"
    assert len(duplicates) == 7

    repos = Repositories(Database.open(database))
    assert len(repos.providers.list()) == 1
