"""Verxio cron provider: no in-process ticker; sync job defs to the control plane.

On the worker pool one Hermes process serves many tenants, so this provider
never uses process-wide state:

* the tenant identity and runtime token come from the active secret scope
  (the tenant's ``.env``), falling back to process env for single-tenant
  containers;
* job definitions are read from the *tenant's* ``{home}/cron/jobs.json``
  (``get_hermes_home()`` honours the per-request tenant override), not from
  ``cron.jobs`` whose paths are fixed at import time.

``verxio-scheduler`` fires due jobs as ``cron`` turns; the worker posts the
result back into ``tenant_cron_jobs`` and this same ``jobs.json``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import httpx

from cron.scheduler_provider import CronScheduler

logger = logging.getLogger("cron.verxio")

_PUBLISH_FIELDS = (
    "id",
    "name",
    "schedule",
    "prompt",
    "script",
    "no_agent",
    "instructions",
    "model",
    "enabled",
    "state",
    "deliver",
    "origin",
    "next_run_at",
    "created_at",
    "enabled_toolsets",
    "workdir",
)


def _scoped(name: str) -> str:
    try:
        from agent.secret_scope import get_secret

        value = get_secret(name, None)
        if value:
            return str(value).strip()
    except Exception:
        pass
    return os.getenv(name, "").strip()


def _tenant_home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def load_tenant_jobs(home: Path | None = None) -> list[dict[str, Any]]:
    jobs_file = (home or _tenant_home()) / "cron" / "jobs.json"
    if not jobs_file.is_file():
        return []
    try:
        data = json.loads(jobs_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read %s", jobs_file, exc_info=True)
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(jobs, list):
        return []
    out: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("state") == "completed":
            continue
        out.append({key: job[key] for key in _PUBLISH_FIELDS if key in job})
    return out


class VerxioCronScheduler(CronScheduler):
    @property
    def name(self) -> str:
        return "verxio"

    def is_available(self) -> bool:
        return bool(_scoped("VERXIO_API_URL") or os.getenv("VERXIO_API_URL", "").strip())

    def start(self, stop_event: threading.Event, *, adapters: Any = None, loop: Any = None, interval: int = 60) -> None:
        self.on_jobs_changed()
        # Do not tick. Verxio's scheduler fires turns. Honor stop_event for teardown.
        stop_event.wait()

    def on_jobs_changed(self) -> None:
        self.publish()

    def reconcile(self) -> None:
        self.publish()

    def publish(self, home: Path | None = None) -> bool:
        base = (_scoped("VERXIO_API_URL") or os.getenv("VERXIO_API_URL", "")).strip().rstrip("/")
        token = _scoped("VERXIO_RUNTIME_TOKEN")
        workspace_id = _scoped("VERXIO_WORKSPACE_ID")
        agent_id = _scoped("VERXIO_AGENT_ID")
        if not base or not token:
            logger.debug("Verxio cron publish skipped: no API url/token in scope")
            return False
        payload = {
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "jobs": load_tenant_jobs(home),
        }
        try:
            response = httpx.post(
                f"{base}/api/runtime/cron",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            response.raise_for_status()
            return True
        except Exception:
            logger.warning("Failed to publish cron jobs to Verxio (%s:%s)", workspace_id, agent_id, exc_info=True)
            return False


def register(ctx) -> None:
    ctx.register_cron_scheduler(VerxioCronScheduler())
