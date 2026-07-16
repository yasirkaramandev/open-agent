from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openagent.security.execution_backend import (
    ContainerSandboxBackend,
    ExecutionBackendError,
    detect_container_runtime,
)


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
    assert probe[-3:] == ["/bin/sh", "-c", "exit 0"]
