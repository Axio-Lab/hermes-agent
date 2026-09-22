"""Verxio hosted sandbox: hardened remote Docker container per tenant.

In the worker pool the agent process must never run tenant commands on its
own host, and the Docker daemon lives on dedicated sandbox hosts
(``DOCKER_HOST=tcp://...:2376`` with ``DOCKER_TLS_VERIFY``/``DOCKER_CERT_PATH``).
That daemon cannot bind-mount the worker's filesystem, so the tenant's
workspace is *copied in* before each command and *copied out* after:

* one long-lived container per tenant (``verxio-tenant`` label, reused across
  sessions), all capabilities dropped, ``--pids-limit``, ``--memory``,
  ``--cpus``, tmpfs ``/workspace`` and ``/tmp``, ``--network none`` unless
  egress is explicitly enabled;
* incremental upload of changed files (mtime+size) via ``docker cp`` tar
  streams, deletions mirrored with ``rm -rf``;
* full ``/workspace`` download after every command, applied to the tenant's
  local workspace so the worker's artifact indexer and home sync see the
  result.

Enabled when ``VERXIO_HOSTED=1`` and the terminal backend is ``docker``.
"""

from __future__ import annotations

import io
import logging
import os
import shlex
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from tools.environments.docker import DockerEnvironment

logger = logging.getLogger(__name__)

_SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".cache", ".next", ".turbo"}
_MAX_FILE_BYTES = 256 * 1024 * 1024


def hosted_sandbox_enabled() -> bool:
    return os.getenv("VERXIO_HOSTED", "").strip() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def sandbox_limits() -> Dict[str, object]:
    """Per-run limits (deploy/sandbox/README.md): memory 1g, 1 cpu, 256 pids, no net."""
    return {
        "memory_mb": _int_env("VERXIO_SANDBOX_MEMORY_MB", 1024),
        "cpus": _float_env("VERXIO_SANDBOX_CPUS", 1.0),
        "pids": _int_env("VERXIO_SANDBOX_PIDS", 256),
        "disk_mb": _int_env("VERXIO_SANDBOX_DISK_MB", 4096),
        "network": os.getenv("VERXIO_SANDBOX_NETWORK", "none").strip().lower() not in {"none", "off", "0", "false"},
        "workspace_tmpfs_mb": _int_env("VERXIO_SANDBOX_WORKSPACE_MB", 4096),
    }


def tenant_identity() -> str:
    """Tenant key for container naming/labels, from the active secret scope."""
    try:
        from agent.secret_scope import get_secret

        workspace = get_secret("VERXIO_WORKSPACE_ID", "") or ""
        agent = get_secret("VERXIO_AGENT_ID", "") or ""
    except Exception:
        workspace = os.getenv("VERXIO_WORKSPACE_ID", "")
        agent = os.getenv("VERXIO_AGENT_ID", "")
    key = f"{workspace}-{agent}".strip("-")
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key) or "default"


def tenant_workspace_dir() -> Path:
    """Local (worker-side) workspace for the active tenant.

    Prefers ``VERXIO_WORKSPACE_DIR`` from the tenant's ``.env`` (secret scope),
    then the pool layout ``{root}/{ws}/{agent}/{hermes-home,workspace}``, then
    ``TERMINAL_CWD``.
    """
    try:
        from agent.secret_scope import get_secret

        explicit = get_secret("VERXIO_WORKSPACE_DIR", "") or ""
    except Exception:
        explicit = ""
    if explicit:
        return Path(explicit)
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    sibling = home.parent / "workspace"
    if home.name == "hermes-home":
        return sibling
    cwd = os.getenv("TERMINAL_CWD", "").strip()
    if cwd:
        return Path(cwd)
    return sibling


class _WorkspaceMirror:
    """Tracks the local workspace so uploads are incremental."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._seen: Dict[str, Tuple[float, int]] = {}

    def scan(self) -> Dict[str, Tuple[float, int]]:
        state: Dict[str, Tuple[float, int]] = {}
        if not self.root.is_dir():
            return state
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.endswith(".sync")]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    st = path.lstat()
                except OSError:
                    continue
                if not path.is_file() or st.st_size > _MAX_FILE_BYTES:
                    continue
                rel = path.relative_to(self.root).as_posix()
                state[rel] = (st.st_mtime, st.st_size)
        return state

    def diff(self) -> Tuple[list[str], list[str]]:
        current = self.scan()
        changed = [rel for rel, sig in current.items() if self._seen.get(rel) != sig]
        removed = [rel for rel in self._seen if rel not in current]
        self._seen = current
        return changed, removed

    def reset(self) -> None:
        self._seen = self.scan()


class VerxioSandboxEnvironment(DockerEnvironment):
    def __init__(
        self,
        *,
        image: str,
        timeout: int,
        tenant: str,
        host_workspace: Path,
        extra_args: Optional[list] = None,
        forward_env: Optional[list] = None,
        env: Optional[dict] = None,
    ) -> None:
        limits = sandbox_limits()
        self._tenant = tenant
        self._host_workspace = host_workspace
        self._mirror = _WorkspaceMirror(host_workspace)
        host_workspace.mkdir(parents=True, exist_ok=True)
        hardened = [
            "--pids-limit",
            str(limits["pids"]),
            "--label",
            f"verxio-tenant={tenant}",
            "--tmpfs",
            "/tmp:rw,exec,size=1g",
            "--memory-swap",
            f"{int(limits['memory_mb'])}m",
        ]
        super().__init__(
            image=image,
            cwd="/workspace",
            timeout=timeout,
            cpu=float(limits["cpus"]),
            memory=int(limits["memory_mb"]),
            disk=0,  # no --storage-opt on tmpfs workspaces; size capped below
            persistent_filesystem=False,
            task_id=f"verxio-{tenant}",
            volumes=[],
            forward_env=forward_env,
            env=env,
            network=bool(limits["network"]),
            host_cwd=None,
            auto_mount_cwd=False,
            run_as_host_user=False,
            extra_args=hardened + list(extra_args or []),
            persist_across_processes=True,
        )
        self._mirror.reset()
        self._upload(list(self._mirror._seen), [])

    # ------------------------------------------------------------- transfer
    def _docker(self, *args: str, input_bytes: Optional[bytes] = None, timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self._docker_exe, *args],
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
            stdin=None if input_bytes is not None else subprocess.DEVNULL,
        )

    def _upload(self, changed: list[str], removed: list[str]) -> None:
        if not self._container_id:
            return
        if removed:
            quoted = " ".join(shlex.quote(f"/workspace/{rel}") for rel in removed[:500])
            self._docker("exec", self._container_id, "sh", "-c", f"rm -rf -- {quoted}", timeout=60)
        if not changed:
            return
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for rel in changed:
                path = self._host_workspace / rel
                try:
                    tar.add(path, arcname=rel, recursive=False)
                except (OSError, ValueError):
                    continue
        buf.seek(0)
        result = self._docker("cp", "-", f"{self._container_id}:/workspace", input_bytes=buf.getvalue())
        if result.returncode != 0:
            logger.warning(
                "Sandbox upload failed tenant=%s: %s",
                self._tenant,
                result.stderr.decode("utf-8", "replace")[:300],
            )

    def _download(self) -> None:
        if not self._container_id:
            return
        result = self._docker("cp", f"{self._container_id}:/workspace/.", "-", timeout=600)
        if result.returncode != 0:
            logger.warning(
                "Sandbox download failed tenant=%s: %s",
                self._tenant,
                result.stderr.decode("utf-8", "replace")[:300],
            )
            return
        staging = Path(tempfile.mkdtemp(prefix=".sandbox-", dir=str(self._host_workspace.parent)))
        try:
            with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r") as tar:
                members = [m for m in tar.getmembers() if _safe_member(m)]
                try:
                    tar.extractall(staging, members=members, filter="data")
                except TypeError:  # Python < 3.12
                    tar.extractall(staging, members=members)
            # Mirror: staging is the truth for /workspace.
            keep: set[str] = set()
            for dirpath, dirnames, filenames in os.walk(staging):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                for name in filenames:
                    src = Path(dirpath) / name
                    rel = src.relative_to(staging).as_posix()
                    keep.add(rel)
                    dest = self._host_workspace / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        st_src = src.stat()
                        st_dest = dest.stat() if dest.exists() else None
                        if st_dest and st_dest.st_size == st_src.st_size and int(st_dest.st_mtime) == int(st_src.st_mtime):
                            continue
                        os.replace(src, dest)
                    except OSError:
                        continue
            for rel in list(self._mirror.scan()):
                if rel not in keep:
                    try:
                        (self._host_workspace / rel).unlink()
                    except OSError:
                        pass
        finally:
            _rmtree(staging)
        self._mirror.reset()

    # -------------------------------------------------------------- execute
    def execute(self, command: str, cwd: str = "", **kwargs) -> dict:
        changed, removed = self._mirror.diff()
        self._upload(changed, removed)
        started = time.monotonic()
        result = super().execute(command, cwd, **kwargs)
        try:
            self._download()
        except Exception:
            logger.warning("Sandbox workspace download failed tenant=%s", self._tenant, exc_info=True)
        logger.debug("Sandbox exec tenant=%s took %.1fs", self._tenant, time.monotonic() - started)
        return result

    def _recreate_container(self) -> bool:
        ok = super()._recreate_container()
        if ok:
            self._mirror.reset()
            self._upload(list(self._mirror._seen), [])
        return ok


def _safe_member(member: tarfile.TarInfo) -> bool:
    name = member.name
    if name.startswith("/") or ".." in Path(name).parts:
        return False
    if member.issym() or member.islnk() or member.isdev():
        return False
    return member.isfile() or member.isdir()


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def create_sandbox_environment(*, image: str, timeout: int, container_config: dict) -> VerxioSandboxEnvironment:
    cc = container_config or {}
    return VerxioSandboxEnvironment(
        image=os.getenv("VERXIO_SANDBOX_IMAGE", "").strip() or image,
        timeout=timeout,
        tenant=tenant_identity(),
        host_workspace=tenant_workspace_dir(),
        extra_args=cc.get("docker_extra_args", []),
        forward_env=cc.get("docker_forward_env", []),
        env=cc.get("docker_env", {}),
    )
