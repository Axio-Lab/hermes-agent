"""Hosted-mode tool policy: remote Docker terminal, workspace-only files."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def hosted_mode() -> bool:
    return os.getenv("VERXIO_HOSTED", "").strip() in {"1", "true", "yes", "on"}


def apply_hosted_tool_policy(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mutate Hermes config so dangerous tools cannot touch the worker host."""
    cfg = dict(config or {})
    if not hosted_mode():
        return cfg

    terminal = dict(cfg.get("terminal") or {})
    terminal["backend"] = os.getenv("VERXIO_TERMINAL_BACKEND", "docker")
    docker_cfg = dict(terminal.get("docker") or {})
    if os.getenv("DOCKER_HOST", "").strip():
        docker_cfg["host"] = os.getenv("DOCKER_HOST", "").strip()
    docker_cfg.setdefault("image", os.getenv("VERXIO_SANDBOX_IMAGE", "verxio-sandbox:local"))
    docker_cfg.setdefault("network", os.getenv("VERXIO_SANDBOX_NETWORK", "none"))
    terminal["docker"] = docker_cfg
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
    if not hosted_mode():
        return True
    root = Path(os.getenv("TERMINAL_CWD", "/workspace")).resolve()
    try:
        Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False
