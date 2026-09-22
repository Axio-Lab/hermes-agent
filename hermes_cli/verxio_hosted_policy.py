"""Hosted-mode tool policy: remote Docker terminal, workspace-only files."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def hosted_mode() -> bool:
    return os.getenv("VERXIO_HOSTED", "").strip() in {"1", "true", "yes", "on"}


class SandboxPolicyError(RuntimeError):
    """The hosted worker is configured to talk to an unsafe Docker daemon."""


def sandbox_daemon_config() -> dict[str, str]:
    """Validate and return the remote sandbox daemon settings.

    Hosted workers must never use the local ``docker.sock``: the daemon has to
    be a TCP endpoint on a sandbox host, and unless
    ``VERXIO_SANDBOX_ALLOW_INSECURE=1`` (local compose only) it must be TLS
    with client certs (``DOCKER_TLS_VERIFY=1`` + ``DOCKER_CERT_PATH`` holding
    ``ca.pem``/``cert.pem``/``key.pem``). The Docker CLI reads these same
    variables, so validating them here is enough to enforce the transport.
    """
    host = os.getenv("DOCKER_HOST", "").strip()
    allow_insecure = os.getenv("VERXIO_SANDBOX_ALLOW_INSECURE", "").strip() in {"1", "true", "yes", "on"}
    if not host:
        raise SandboxPolicyError("VERXIO_HOSTED=1 requires DOCKER_HOST pointing at a sandbox daemon")
    if host.startswith("unix://") or host.startswith("npipe://"):
        raise SandboxPolicyError(f"hosted workers may not use a local Docker socket ({host})")
    tls_verify = os.getenv("DOCKER_TLS_VERIFY", "").strip() in {"1", "true", "yes", "on"}
    cert_path = os.getenv("DOCKER_CERT_PATH", "").strip()
    if not tls_verify or not cert_path:
        if not allow_insecure:
            raise SandboxPolicyError(
                "sandbox daemon must use TLS (DOCKER_TLS_VERIFY=1, DOCKER_CERT_PATH=...) "
                "or set VERXIO_SANDBOX_ALLOW_INSECURE=1 for local development"
            )
        logger.warning("Hosted sandbox daemon %s is configured WITHOUT TLS", host)
        return {"host": host, "tls": "0", "cert_path": ""}
    missing = [n for n in ("ca.pem", "cert.pem", "key.pem") if not (Path(cert_path) / n).is_file()]
    if missing:
        raise SandboxPolicyError(f"DOCKER_CERT_PATH={cert_path} is missing {', '.join(missing)}")
    return {"host": host, "tls": "1", "cert_path": cert_path}


def apply_hosted_tool_policy(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mutate Hermes config so dangerous tools cannot touch the worker host."""
    cfg = dict(config or {})
    if not hosted_mode():
        return cfg

    terminal = dict(cfg.get("terminal") or {})
    terminal["backend"] = os.getenv("VERXIO_TERMINAL_BACKEND", "docker")
    docker_cfg = dict(terminal.get("docker") or {})
    # Channel shards (VERXIO_REMOTE_EXEC=1) never execute tools locally — every
    # turn is enqueued to the pool — so they don't need a sandbox daemon.
    remote_exec = os.getenv("VERXIO_REMOTE_EXEC", "").strip() in {"1", "true", "yes", "on"}
    if terminal["backend"] == "docker" and not remote_exec:
        daemon = sandbox_daemon_config()
        docker_cfg["host"] = daemon["host"]
        docker_cfg["tls_verify"] = daemon["tls"] == "1"
        if daemon["cert_path"]:
            docker_cfg["cert_path"] = daemon["cert_path"]
        # Copy-in/copy-out sandbox: never mount host paths, never persist.
        docker_cfg["mount_cwd"] = False
        docker_cfg["volumes"] = []
        docker_cfg["run_as_host_user"] = False
        docker_cfg["persist_across_processes"] = True
    docker_cfg.setdefault("image", os.getenv("VERXIO_SANDBOX_IMAGE", "verxio-sandbox:local"))
    docker_cfg.setdefault("network", os.getenv("VERXIO_SANDBOX_NETWORK", "none"))
    terminal["docker"] = docker_cfg
    # Resource caps mirrored into the terminal config so both the Hermes
    # DockerEnvironment and the Verxio sandbox subclass see the same limits.
    terminal.setdefault("container_cpu", float(os.getenv("VERXIO_SANDBOX_CPUS", "1") or 1))
    terminal.setdefault("container_memory", int(os.getenv("VERXIO_SANDBOX_MEMORY_MB", "1024") or 1024))
    terminal["container_persistent"] = False
    cfg["terminal"] = terminal

    security = dict(cfg.get("security") or {})
    workspace = os.getenv("TERMINAL_CWD", "").strip() or "/workspace"
    security["workspace_root"] = workspace
    security["deny_host_fs"] = True
    cfg["security"] = security

    browser = dict(cfg.get("browser") or {})
    cdp = os.getenv("VERXIO_SANDBOX_CDP", "").strip()
    if cdp:
        browser["cdp_url"] = cdp
    cfg["browser"] = browser

    cron = dict(cfg.get("cron") or {})
    cron["provider"] = os.getenv("VERXIO_CRON_PROVIDER", cron.get("provider") or "verxio")
    cfg["cron"] = cron
    return cfg


def workspace_path_allowed(path: str | Path) -> bool:
    """True when *path* is inside the active tenant's workspace.

    Pool workers host many tenants; the workspace root comes from the tenant
    scope (``VERXIO_WORKSPACE_DIR`` in the tenant ``.env``), falling back to
    the process-wide ``TERMINAL_CWD``.
    """
    if not hosted_mode():
        return True
    try:
        from tools.environments.verxio_sandbox import tenant_workspace_dir

        root = tenant_workspace_dir().resolve()
    except Exception:
        root = Path(os.getenv("TERMINAL_CWD", "/workspace")).resolve()
    try:
        Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False
