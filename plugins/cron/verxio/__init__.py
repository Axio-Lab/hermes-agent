"""Verxio cron provider: no in-process ticker; sync job defs to the control plane."""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

import httpx

from cron.scheduler_provider import CronScheduler

logger = logging.getLogger("cron.verxio")


class VerxioCronScheduler(CronScheduler):
    @property
    def name(self) -> str:
        return "verxio"

    def is_available(self) -> bool:
        return bool(os.getenv("VERXIO_API_URL", "").strip() and os.getenv("VERXIO_RUNTIME_TOKEN", "").strip())

    def start(self, stop_event: threading.Event, *, adapters: Any = None, loop: Any = None, interval: int = 60) -> None:
        self.on_jobs_changed()
        # Do not tick. Verxio's scheduler fires turns. Honor stop_event for teardown.
        stop_event.wait()

    def on_jobs_changed(self) -> None:
        self._publish()

    def reconcile(self) -> None:
        self._publish()

    def _publish(self) -> None:
        base = os.getenv("VERXIO_API_URL", "").strip().rstrip("/")
        token = os.getenv("VERXIO_RUNTIME_TOKEN", "").strip()
        if not base or not token:
            return
        try:
            from cron.jobs import list_jobs

            jobs = list_jobs()
        except Exception:
            logger.debug("Could not list hermes cron jobs", exc_info=True)
            return
        payload = {
            "workspace_id": os.getenv("VERXIO_WORKSPACE_ID", ""),
            "agent_id": os.getenv("VERXIO_AGENT_ID", ""),
            "jobs": jobs if isinstance(jobs, list) else [],
        }
        try:
            httpx.post(
                f"{base}/api/runtime/cron",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
        except Exception:
            logger.warning("Failed to publish cron jobs to Verxio", exc_info=True)


def register(ctx) -> None:
    ctx.register_cron_scheduler(VerxioCronScheduler())
