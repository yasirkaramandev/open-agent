from pathlib import Path

from openagent.core.events import EventType, NormalizedEvent
from openagent.core.models import (
    AgentProfile,
    AgentRuntime,
    ModelProfile,
    Protocol,
    ProviderConnection,
    Run,
    RunStatus,
    RuntimeType,
)
from openagent.storage.event_log import EventLog
from openagent.storage.repositories import Repositories


def test_provider_roundtrip(repos: Repositories):
    provider = ProviderConnection(
        id="provider_deepseek_main",
        name="deepseek-main",
        provider_type="deepseek",
        protocol=Protocol.OPENAI_CHAT,
        base_url="https://api.deepseek.com",
    )
    repos.providers.upsert(provider)
    assert repos.providers.get("provider_deepseek_main").name == "deepseek-main"
    assert repos.providers.get_by_name("deepseek-main").provider_type == "deepseek"
    assert len(repos.providers.list()) == 1
    repos.providers.delete("provider_deepseek_main")
    assert repos.providers.get("provider_deepseek_main") is None


def test_agent_roundtrip(repos: Repositories):
    # An API agent must bind to a provider that exists (migration 0013 + fail-closed binding).
    repos.providers.upsert(
        ProviderConnection(
            id="provider_deepseek_main",
            name="deepseek-main",
            provider_type="deepseek",
            protocol=Protocol.OPENAI_CHAT,
            base_url="https://api.deepseek.com",
        )
    )
    agent = AgentProfile(
        name="deepseek-coder",
        title="DeepSeek Coder",
        runtime=AgentRuntime(type=RuntimeType.API_AGENT, provider="deepseek-main", model="m"),
        tags=["coder", "python"],
        permission_profile="safe-edit",
    )
    repos.agents.upsert(agent)
    loaded = repos.agents.get("deepseek-coder")
    assert loaded.runtime.type == RuntimeType.API_AGENT
    assert loaded.tags == ["coder", "python"]
    assert repos.agents.delete("deepseek-coder") is True
    assert repos.agents.delete("deepseek-coder") is False


def test_run_status_update(repos: Repositories):
    run = Run(id="run_01ABC", agent="codex-coder", workspace="/tmp/x")
    repos.runs.upsert(run)
    assert repos.runs.get("run_01ABC").status == RunStatus.QUEUED
    assert len(repos.runs.list_active()) == 1
    run.status = RunStatus.COMPLETED
    repos.runs.upsert(run)
    assert repos.runs.get("run_01ABC").status == RunStatus.COMPLETED
    assert repos.runs.list_active() == []


def test_event_log_writes_and_indexes(tmp_path: Path, repos: Repositories):
    run_dir = tmp_path / "run_01ABC"
    log = EventLog(run_dir, index=repos.event_index)
    log.append(NormalizedEvent(run_id="run_01ABC", type=EventType.RUN_STARTED, source="openagent"))
    log.append(
        NormalizedEvent(run_id="run_01ABC", type=EventType.RUN_COMPLETED, source="openagent")
    )
    events = list(log.read())
    assert [e.type for e in events] == ["run.started", "run.completed"]
    assert repos.event_index.count("run_01ABC") == 2
    # next_seq() is gone: allocating the sequence on a separate read connection from the insert that
    # consumed it was the §11 race. Assert the sequences actually allocated instead — a stronger
    # claim than what the next one would have been.
    assert repos.event_index.sequences_for("run_01ABC") == [1, 2]


def test_event_log_redacts_secrets(tmp_path: Path):
    log = EventLog(tmp_path / "run_x")
    log.append(
        NormalizedEvent(
            run_id="run_x",
            type=EventType.LOG,
            source="api-agent",
            data={"line": "exported OPENAI_API_KEY=sk-abcdEFGH1234567890zzzz"},
        )
    )
    body = (tmp_path / "run_x" / "events.jsonl").read_text()
    assert "sk-abcdEFGH1234567890zzzz" not in body
    assert "REDACTED" in body


def test_model_upsert_is_in_place_native_upsert(repos: Repositories) -> None:
    """Upsert updates the existing row atomically rather than deleting and re-inserting it (§18)."""

    repos.providers.create(ProviderConnection(id="p_x", name="prov-x", provider_type="openai"))
    repos.models.upsert(ModelProfile(id="m1", provider_connection="p_x", remote_model_id="r0"))
    repos.models.upsert(ModelProfile(id="m1", provider_connection="p_x", remote_model_id="r1"))

    stored = repos.models.get("m1")
    assert stored is not None and stored.remote_model_id == "r1"
    assert len(repos.models.list_for_provider("p_x")) == 1


def test_concurrent_model_upserts_never_expose_a_missing_row(tmp_path: Path) -> None:
    """A reader must never observe the row absent while it is being upserted (§18).

    Uses a file-backed DB with WAL so reads and writes genuinely run on separate connections.
    """

    import threading

    from openagent.storage.db import Database

    db = Database.open(tmp_path / "concurrent.db")
    repos = Repositories(db)
    repos.providers.create(ProviderConnection(id="p_c", name="prov-c", provider_type="openai"))
    repos.models.upsert(ModelProfile(id="mc", provider_connection="p_c", remote_model_id="r0"))

    stop = threading.Event()
    missing: list[int] = []

    def reader() -> None:
        while not stop.is_set():
            if repos.models.get("mc") is None:
                missing.append(1)

    watcher = threading.Thread(target=reader)
    watcher.start()
    try:
        for index in range(300):
            repos.models.upsert(
                ModelProfile(id="mc", provider_connection="p_c", remote_model_id=f"r{index}")
            )
    finally:
        stop.set()
        watcher.join()

    assert missing == [], "a concurrent reader saw the model row vanish during upsert"
    assert repos.models.get("mc") is not None
