from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from openagent.core.cancellation import RunCancelled
from openagent.security.execution_backend import (
    ContainerSandboxBackend,
    ExecutionBackendError,
    _extract_workspace_archive,
    _write_workspace_archive,
    detect_container_runtime,
)
from openagent.services.run_service import RunError


def test_runtime_auto_detection_prefers_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    assert detect_container_runtime() == "docker"


def test_runtime_detection_never_falls_back_to_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(ExecutionBackendError, match="requires Docker or Podman"):
        detect_container_runtime()


def test_container_requires_explicit_image_and_isolated_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    with pytest.raises(ExecutionBackendError, match="explicit local image"):
        ContainerSandboxBackend(workspace=tmp_path, image="")
    with pytest.raises(ExecutionBackendError, match="worktree=none"):
        ContainerSandboxBackend(workspace=tmp_path, image="local:test", worktree_strategy="none")


def test_missing_image_fails_without_pull_or_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    backend = ContainerSandboxBackend(workspace=tmp_path, image="missing:test")
    calls: list[list[str]] = []

    def control(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, "", "not found")

    monkeypatch.setattr(backend, "_control", control)
    with pytest.raises(ExecutionBackendError, match="will not pull or build"):
        backend.validate()
    assert calls == [["image", "inspect", "missing:test"]]


def test_validation_uses_read_only_no_network_shell_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    backend = ContainerSandboxBackend(workspace=tmp_path, image="local:test")
    calls: list[list[str]] = []

    def control(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(backend, "_control", control)
    backend.validate()
    probe = calls[1]
    assert calls[0] == ["image", "inspect", "local:test"]
    assert "--network" in probe and "none" in probe
    assert "--read-only" in probe
    assert ["--cap-drop", "ALL"] == probe[probe.index("--cap-drop") : probe.index("--cap-drop") + 2]
    assert ["--user", "65532:65532"] == probe[probe.index("--user") : probe.index("--user") + 2]
    assert "--pid=" in probe
    assert ["--ipc", "private"] == probe[probe.index("--ipc") : probe.index("--ipc") + 2]
    assert ["--pull", "never"] == probe[probe.index("--pull") : probe.index("--pull") + 2]
    assert not any("unconfined" in value for value in probe)
    assert probe[-3:] == ["/bin/sh", "-c", "command -v tar >/dev/null 2>&1"]


def test_container_execution_uses_tmpfs_and_hard_resource_limits_without_host_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "input.txt").write_text("input")
    backend = ContainerSandboxBackend(
        workspace=workspace, image="local:test", worktree_strategy="copy"
    )
    backend._validated = True  # noqa: SLF001 - isolate execution argv from validation probe
    calls: list[list[str]] = []

    def control(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backend, "_control", control)
    monkeypatch.setattr(backend, "_import_workspace", lambda *_args: None)

    def export_workspace(_container: str, exported: Path) -> None:
        (exported / "input.txt").write_text("input")
        (exported / "result.txt").write_text("result")

    monkeypatch.setattr(backend, "_export_workspace", export_workspace)
    monkeypatch.setattr(
        "openagent.security.execution_backend.run_capture",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "ok", ""),
    )

    result = backend.execute(
        ["/bin/sh", "-c", "true"],
        cwd=workspace,
        env={},
        timeout=10,
        shell=False,
        max_output_bytes=1024,
        cancellation=None,
    )

    assert result.returncode == 0
    create = next(args for args in calls if args[0] == "create")
    assert ["--network", "none"] == create[
        create.index("--network") : create.index("--network") + 2
    ]
    assert "--read-only" in create
    assert ["--cap-drop", "ALL"] == create[
        create.index("--cap-drop") : create.index("--cap-drop") + 2
    ]
    assert ["--security-opt", "no-new-privileges"] == create[
        create.index("--security-opt") : create.index("--security-opt") + 2
    ]
    assert ["--user", "65532:65532"] == create[create.index("--user") : create.index("--user") + 2]
    assert "--pid=" in create
    assert ["--ipc", "private"] == create[create.index("--ipc") : create.index("--ipc") + 2]
    assert ["--pull", "never"] == create[create.index("--pull") : create.index("--pull") + 2]
    assert not any("unconfined" in value for value in create)
    for flag, value in (
        ("--cpus", "2"),
        ("--memory", "2g"),
        ("--memory-swap", "2g"),
        ("--pids-limit", "256"),
    ):
        assert [flag, value] == create[create.index(flag) : create.index(flag) + 2]
    assert create.count("--tmpfs") == 2
    assert "/workspace:rw,size=1g,mode=0700,uid=65532,gid=65532" in create
    assert "/tmp:rw,size=256m,mode=1777" in create
    assert not {"--mount", "--volume", "-v"}.intersection(create)
    assert not any(args[0] == "cp" for args in calls)
    assert (workspace / "result.txt").read_text() == "result"


@pytest.mark.parametrize(
    "failure",
    [subprocess.TimeoutExpired(["pytest"], 1), RunCancelled("cancel test")],
)
def test_container_timeout_and_cancel_always_force_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "input.txt").write_text("input")
    backend = ContainerSandboxBackend(
        workspace=workspace, image="local:test", worktree_strategy="copy"
    )
    backend._validated = True  # noqa: SLF001
    calls: list[list[str]] = []

    def control(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    def fail_capture(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(backend, "_control", control)
    monkeypatch.setattr(backend, "_import_workspace", lambda *_args: None)
    monkeypatch.setattr(
        backend,
        "_export_workspace",
        lambda *_args: pytest.fail("workspace export must not run after timeout/cancellation"),
    )
    monkeypatch.setattr("openagent.security.execution_backend.run_capture", fail_capture)

    with pytest.raises(type(failure)):
        backend.execute(
            ["pytest", "-q"],
            cwd=workspace,
            env={},
            timeout=1,
            shell=False,
            max_output_bytes=1024,
            cancellation=None,
        )
    assert calls[-1][0:2] == ["rm", "--force"]


def test_sync_back_refuses_concurrent_host_change_before_writing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "input.txt").write_text("original")
    backend = ContainerSandboxBackend(
        workspace=workspace, image="local:test", worktree_strategy="copy"
    )
    backend._validated = True  # noqa: SLF001
    calls: list[list[str]] = []

    def control(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backend, "_control", control)
    monkeypatch.setattr(backend, "_import_workspace", lambda *_args: None)

    def export_workspace(_container: str, output: Path) -> None:
        (output / "input.txt").write_text("container edit")
        (output / "result.txt").write_text("new file")
        (workspace / "input.txt").write_text("concurrent human edit")

    monkeypatch.setattr(backend, "_export_workspace", export_workspace)
    monkeypatch.setattr(
        "openagent.security.execution_backend.run_capture",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "ok", ""),
    )

    with pytest.raises(ExecutionBackendError, match="changed concurrently"):
        backend.execute(
            ["pytest", "-q"],
            cwd=workspace,
            env={},
            timeout=10,
            shell=False,
            max_output_bytes=1024,
            cancellation=None,
        )
    assert (workspace / "input.txt").read_text() == "concurrent human edit"
    assert not (workspace / "result.txt").exists()
    assert calls[-1][0:2] == ["rm", "--force"]


def test_workspace_archive_round_trip_preserves_regular_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "nested").mkdir()
    (source / "nested" / "data.txt").write_bytes(b"safe payload\n")
    archive = io.BytesIO()

    _write_workspace_archive(source, archive)
    archive.seek(0)
    _extract_workspace_archive(archive, output)

    assert (output / "nested" / "data.txt").read_bytes() == b"safe payload\n"


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/escape.txt"])
def test_workspace_archive_rejects_path_escape(tmp_path: Path, name: str) -> None:
    output = tmp_path / "output"
    output.mkdir()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        member = tarfile.TarInfo(name)
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    archive.seek(0)

    with pytest.raises(ExecutionBackendError, match="unsafe path"):
        _extract_workspace_archive(archive, output)

    assert list(output.rglob("*")) == []


def test_workspace_archive_rejects_links(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        member = tarfile.TarInfo("link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../escape"
        bundle.addfile(member)
    archive.seek(0)

    with pytest.raises(ExecutionBackendError, match="unsafe entry"):
        _extract_workspace_archive(archive, output)


def test_cli_run_never_silently_falls_back_from_container_to_host(paths) -> None:
    from openagent.app import OpenAgentApp
    from openagent.core.models import RuntimeType

    app = OpenAgentApp(paths)
    app.agents.create(name="cli-agent", runtime_type=RuntimeType.CLI, cli="codex")
    with pytest.raises(RunError, match="refused rather than falling back"):
        app.runs.create(
            agent_name="cli-agent",
            prompt="test",
            execution_backend="container-sandbox",
            container_image="local:test",
        )
