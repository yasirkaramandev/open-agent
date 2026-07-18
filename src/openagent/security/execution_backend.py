"""Host policy and opt-in container execution backends."""

from __future__ import annotations

import hashlib
import io
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Protocol

from ..core.cancellation import RunCancellation
from .filesystem import (
    SafeWorkspaceWalker,
    UnsafeWorkspacePath,
    WalkerLimits,
    WorkspaceBudgetExceeded,
)
from .process import minimal_environment, run_capture

HOST_RESTRICTED = "host-restricted"
CONTAINER_SANDBOX = "container-sandbox"
EXECUTION_BACKENDS = (HOST_RESTRICTED, CONTAINER_SANDBOX)
CONTAINER_RUNTIMES = ("docker", "podman")


class ExecutionBackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class _FileSnapshot:
    digest: str
    executable: bool


class ExecutionBackend(Protocol):
    name: str

    def validate(self) -> None: ...

    def execute(
        self,
        argv: Sequence[str] | str,
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: int,
        shell: bool,
        max_output_bytes: int,
        cancellation: RunCancellation | None,
    ) -> subprocess.CompletedProcess[str]: ...


class HostRestrictedBackend:
    """Policy-screened host execution. This is explicitly not an OS sandbox."""

    name = HOST_RESTRICTED

    def validate(self) -> None:
        return

    def execute(
        self,
        argv: Sequence[str] | str,
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: int,
        shell: bool,
        max_output_bytes: int,
        cancellation: RunCancellation | None,
    ) -> subprocess.CompletedProcess[str]:
        return run_capture(
            argv,
            cwd=cwd,
            env=env,
            timeout=timeout,
            shell=shell,
            max_output_bytes=max_output_bytes,
            cancellation=cancellation,
        )


def detect_container_runtime(requested: str | None = None) -> str:
    if requested:
        if requested not in CONTAINER_RUNTIMES:
            raise ExecutionBackendError(
                f"unsupported container runtime {requested!r}; choose docker or podman"
            )
        if shutil.which(requested) is None:
            raise ExecutionBackendError(f"container runtime {requested!r} is not installed")
        return requested
    for candidate in CONTAINER_RUNTIMES:
        if shutil.which(candidate):
            return candidate
    raise ExecutionBackendError("container-sandbox requires Docker or Podman")


class ContainerSandboxBackend:
    """Run structured argv in a no-network, resource-limited container snapshot.

    No host path is mounted. A no-follow snapshot is copied into a quota-limited ``/workspace``
    tmpfs and safe regular-file changes are copied back after execution.
    """

    name = CONTAINER_SANDBOX

    def __init__(
        self,
        *,
        workspace: Path,
        image: str,
        runtime: str | None = None,
        worktree_strategy: str = "auto",
    ) -> None:
        if not image.strip():
            raise ExecutionBackendError("container-sandbox requires an explicit local image")
        if worktree_strategy == "none":
            raise ExecutionBackendError("container-sandbox refuses worktree=none")
        self.workspace = workspace.absolute()
        self.image = image
        self.runtime = detect_container_runtime(runtime)
        self._validated = False

    def _control(self, args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # noqa: S603 - fixed runtime argv, never a shell
                [self.runtime, *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=minimal_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExecutionBackendError(f"{self.runtime} control command failed: {exc}") from exc

    def _archive_control(
        self,
        args: list[str],
        *,
        stdin: BinaryIO | None = None,
        stdout: int | BinaryIO = subprocess.PIPE,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run a binary container control command for bounded tar transport."""

        try:
            return subprocess.run(  # noqa: S603 - fixed runtime argv, never a shell
                [self.runtime, *args],
                stdin=stdin,
                stdout=stdout,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
                env=minimal_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExecutionBackendError(f"{self.runtime} archive command failed: {exc}") from exc

    def validate(self) -> None:
        if self._validated:
            return
        inspect = self._control(["image", "inspect", self.image])
        if inspect.returncode != 0:
            raise ExecutionBackendError(
                f"container image {self.image!r} is not present locally; OpenAgent will not pull or build it"
            )
        shell = self._control(
            [
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "65532:65532",
                "--pid=",
                "--ipc",
                "private",
                "--pull",
                "never",
                self.image,
                "/bin/sh",
                "-c",
                "command -v tar >/dev/null 2>&1",
            ]
        )
        if shell.returncode != 0:
            detail = _bounded_detail(shell.stderr or shell.stdout)
            suffix = f": {detail}" if detail else ""
            raise ExecutionBackendError(
                f"container image {self.image!r} must provide a Linux-compatible /bin/sh and tar"
                f"{suffix}"
            )
        self._validated = True

    def _import_workspace(self, container: str, source: Path) -> None:
        with tempfile.TemporaryFile() as archive:
            _write_workspace_archive(source, archive)
            archive.seek(0)
            result = self._archive_control(
                [
                    "exec",
                    "-i",
                    container,
                    "/bin/sh",
                    "-c",
                    "tar -xf - -C /workspace",
                ],
                stdin=archive,
            )
        if result.returncode != 0:
            raise ExecutionBackendError(_binary_detail(result.stderr, "workspace import failed"))

    def _export_workspace(self, container: str, output: Path) -> None:
        with tempfile.TemporaryFile() as archive:
            result = self._archive_control(
                [
                    "exec",
                    container,
                    "/bin/sh",
                    "-c",
                    "tar -cf - -C /workspace .",
                ],
                stdout=archive,
            )
            if result.returncode != 0:
                raise ExecutionBackendError(
                    _binary_detail(result.stderr, "workspace export failed")
                )
            archive.seek(0)
            _extract_workspace_archive(archive, output)

    def execute(
        self,
        argv: Sequence[str] | str,
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: int,
        shell: bool,
        max_output_bytes: int,
        cancellation: RunCancellation | None,
    ) -> subprocess.CompletedProcess[str]:
        self.validate()
        if shell or isinstance(argv, str):
            raise ExecutionBackendError("container-sandbox accepts structured argv only")
        if cwd.absolute() != self.workspace:
            raise ExecutionBackendError("container backend cwd must be its workspace root")

        container = f"openagent-{uuid.uuid4().hex[:16]}"
        with (
            tempfile.TemporaryDirectory(prefix="openagent-container-in-") as source_tmp,
            tempfile.TemporaryDirectory(prefix="openagent-container-out-") as output_tmp,
        ):
            source = Path(source_tmp)
            output = Path(output_tmp)
            source_walker = SafeWorkspaceWalker(self.workspace)
            source_walker.copy_to(source, ignore_dirs={".git", ".openagent"})
            original = {
                path.relative_to(source): _snapshot(path)
                for path in SafeWorkspaceWalker(source).iter_files()
            }

            create = self._control(
                [
                    "create",
                    "--name",
                    container,
                    "--read-only",
                    "--network",
                    "none",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--user",
                    "65532:65532",
                    "--pid=",
                    "--ipc",
                    "private",
                    "--pull",
                    "never",
                    "--cpus",
                    "2",
                    "--memory",
                    "2g",
                    "--memory-swap",
                    "2g",
                    "--pids-limit",
                    "256",
                    "--tmpfs",
                    "/workspace:rw,size=1g,mode=0700,uid=65532,gid=65532",
                    "--tmpfs",
                    "/tmp:rw,size=256m,mode=1777",
                    "--workdir",
                    "/workspace",
                    self.image,
                    "/bin/sh",
                    "-c",
                    "trap 'exit 0' TERM INT; while :; do sleep 3600; done",
                ]
            )
            if create.returncode != 0:
                raise ExecutionBackendError(create.stderr.strip() or "container create failed")
            try:
                start = self._control(["start", container])
                if start.returncode != 0:
                    raise ExecutionBackendError(start.stderr.strip() or "container start failed")
                self._import_workspace(container, source)
                exec_argv = [self.runtime, "exec", "--workdir", "/workspace"]
                for key, value in env.items():
                    exec_argv.extend(["--env", f"{key}={value}"])
                exec_argv.extend([container, *argv])
                result = run_capture(
                    exec_argv,
                    cwd=self.workspace,
                    env=minimal_environment(),
                    timeout=timeout,
                    max_output_bytes=max_output_bytes,
                    cancellation=cancellation,
                )
                self._export_workspace(container, output)
                self._sync_back(output, original)
                return subprocess.CompletedProcess(
                    list(argv), result.returncode, result.stdout, result.stderr
                )
            finally:
                self._control(["rm", "--force", container])

    def _sync_back(self, output: Path, original: dict[Path, _FileSnapshot]) -> None:
        """Copy regular-file changes back only if the host snapshot did not change concurrently."""

        output_walker = SafeWorkspaceWalker(output)
        final_files = {
            path.relative_to(output): _snapshot(path) for path in output_walker.iter_files()
        }
        workspace_walker = SafeWorkspaceWalker(self.workspace)
        deleted = set(original) - set(final_files)
        changed = {
            relative
            for relative, snapshot in final_files.items()
            if original.get(relative) != snapshot
        }

        # Validate the complete plan before the first write so a detected conflict cannot leave a
        # known partial sync. The per-write walker still re-checks symlinks/reparse points.
        for relative in sorted(deleted | changed):
            try:
                target = workspace_walker.resolve(relative, allow_missing=True)
                info = target.lstat()
            except FileNotFoundError:
                if relative in original and relative in changed:
                    raise ExecutionBackendError(
                        f"workspace changed concurrently at {relative}; refusing sync-back"
                    ) from None
                continue
            except (UnsafeWorkspacePath, OSError) as exc:
                raise ExecutionBackendError(
                    f"unsafe sync-back target at {relative}; refusing sync-back"
                ) from exc
            if not stat.S_ISREG(info.st_mode):
                raise ExecutionBackendError(
                    f"unsafe sync-back target at {relative}; refusing sync-back"
                )
            before = original.get(relative)
            if before is None or _snapshot(target) != before:
                raise ExecutionBackendError(
                    f"workspace changed concurrently at {relative}; refusing sync-back"
                )

        for relative in sorted(deleted):
            try:
                workspace_walker.resolve(relative).unlink()
            except FileNotFoundError:
                pass
        for relative in sorted(changed):
            snapshot = final_files[relative]
            mode = 0o700 if snapshot.executable else 0o600
            workspace_walker.write_bytes(relative, output_walker.read_bytes(relative), mode=mode)


def _snapshot(path: Path) -> _FileSnapshot:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ExecutionBackendError(f"refused non-regular sandbox file {path.name!r}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return _FileSnapshot(digest=digest, executable=bool(info.st_mode & 0o111))


def _write_workspace_archive(root: Path, archive: BinaryIO) -> None:
    """Serialize safe regular files for extraction by the fixed non-root container user."""

    walker = SafeWorkspaceWalker(root)
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        for path in walker.iter_files():
            relative = path.relative_to(root)
            data = walker.read_bytes(relative)
            info = path.lstat()
            member = tarfile.TarInfo(relative.as_posix())
            member.size = len(data)
            member.mode = 0o777 if info.st_mode & 0o111 else 0o666
            member.uid = 65532
            member.gid = 65532
            member.mtime = 0
            bundle.addfile(member, fileobj=io.BytesIO(data))


def _extract_workspace_archive(
    archive: BinaryIO,
    output: Path,
    *,
    limits: WalkerLimits | None = None,
) -> None:
    """Extract only bounded regular files from an untrusted container tar stream."""

    active_limits = limits or WalkerLimits()
    walker = SafeWorkspaceWalker(output, limits=active_limits)
    seen: set[Path] = set()
    directories = 0
    files = 0
    total_bytes = 0
    deadline = time.monotonic() + active_limits.deadline_seconds
    try:
        with tarfile.open(fileobj=archive, mode="r:") as bundle:
            for member in bundle:
                if time.monotonic() >= deadline:
                    raise ExecutionBackendError("workspace archive deadline exceeded")
                relative = _safe_archive_relative(member.name)
                if relative is None:
                    if member.isdir():
                        continue
                    raise ExecutionBackendError("workspace archive contains an invalid root entry")
                if relative in seen:
                    raise ExecutionBackendError(
                        f"workspace archive contains duplicate path {relative.as_posix()!r}"
                    )
                seen.add(relative)
                if member.isdir():
                    directories += 1
                    if directories > active_limits.directories:
                        raise ExecutionBackendError("workspace archive directory budget exceeded")
                    continue
                if not member.isfile():
                    raise ExecutionBackendError(
                        f"workspace archive contains unsafe entry {member.name!r}"
                    )
                files += 1
                total_bytes += member.size
                if files > active_limits.files or files > active_limits.results:
                    raise ExecutionBackendError("workspace archive file budget exceeded")
                if member.size < 0 or total_bytes > active_limits.bytes:
                    raise ExecutionBackendError("workspace archive byte budget exceeded")
                source = bundle.extractfile(member)
                if source is None:
                    raise ExecutionBackendError(
                        f"workspace archive file {member.name!r} could not be read"
                    )
                data = source.read(member.size + 1)
                if len(data) != member.size:
                    raise ExecutionBackendError(
                        f"workspace archive file {member.name!r} has an invalid size"
                    )
                mode = 0o700 if member.mode & 0o111 else 0o600
                walker.write_bytes(relative, data, mode=mode)
    except (tarfile.TarError, OSError, UnsafeWorkspacePath, WorkspaceBudgetExceeded) as exc:
        raise ExecutionBackendError(f"unsafe workspace archive: {exc}") from exc


def _safe_archive_relative(raw: str) -> Path | None:
    if not raw or "\\" in raw or "\x00" in raw:
        raise ExecutionBackendError(f"workspace archive contains unsafe path {raw!r}")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
        raise ExecutionBackendError(f"workspace archive contains unsafe path {raw!r}")
    if any(part == ".." for part in (*posix.parts, *windows.parts)):
        raise ExecutionBackendError(f"workspace archive contains unsafe path {raw!r}")
    parts = tuple(part for part in posix.parts if part != ".")
    if not parts:
        return None
    return Path(*parts)


def _bounded_detail(value: str, *, limit: int = 2_000) -> str:
    cleaned = value.strip()
    return cleaned[-limit:]


def _binary_detail(value: bytes | None, fallback: str) -> str:
    if not value:
        return fallback
    return _bounded_detail(value.decode("utf-8", errors="replace")) or fallback


def build_execution_backend(
    name: str,
    *,
    workspace: Path,
    container_image: str | None = None,
    container_runtime: str | None = None,
    worktree_strategy: str = "auto",
) -> ExecutionBackend:
    if name == HOST_RESTRICTED:
        return HostRestrictedBackend()
    if name == CONTAINER_SANDBOX:
        return ContainerSandboxBackend(
            workspace=workspace,
            image=container_image or "",
            runtime=container_runtime,
            worktree_strategy=worktree_strategy,
        )
    raise ExecutionBackendError(f"unknown execution backend {name!r}")
