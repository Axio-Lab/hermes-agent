"""Scheduling policy for tool subprocesses spawned inside the Hermes process.

The dashboard (uvicorn, one asyncio loop) and the gateway share a container
with every shell command the agent runs. A tenant ``npm ci`` or ``git clone``
at normal priority starves ``/api/healthz`` and the websocket, which is what
the browser reports as "Reconnecting to Verxio". Unprivileged processes may
always *lower* their own priority, so tool children drop to a higher nice
value and ``SCHED_BATCH`` before exec. CFS then keeps the dashboard responsive
no matter how many builds a turn kicks off.

Enabled automatically in hosted mode; opt in elsewhere with ``HERMES_TOOL_NICE``.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

DEFAULT_HOSTED_NICE = 10


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def tool_nice_level() -> int:
    """Nice increment for tool children (0 disables the policy)."""
    raw = os.getenv("HERMES_TOOL_NICE", "").strip()
    if raw:
        try:
            return max(0, min(19, int(raw)))
        except ValueError:
            logger.warning("Ignoring invalid HERMES_TOOL_NICE=%r", raw)
    if _truthy(os.getenv("VERXIO_HOSTED")):
        return DEFAULT_HOSTED_NICE
    return 0


def tool_sched_batch() -> bool:
    """Whether tool children switch to ``SCHED_BATCH`` (Linux only)."""
    raw = os.getenv("HERMES_TOOL_SCHED_BATCH", "").strip()
    if raw:
        return _truthy(raw)
    return tool_nice_level() > 0


def apply_tool_priority() -> None:
    """Lower the *current* process priority. Safe to call from ``preexec_fn``.

    Everything here is best effort and must never raise: a failed
    ``sched_setscheduler`` must not turn into a failed tool call.
    """
    nice = tool_nice_level()
    if nice > 0:
        try:
            os.nice(nice)
        except (OSError, AttributeError):
            pass
    if tool_sched_batch():
        batch = getattr(os, "SCHED_BATCH", None)
        setter = getattr(os, "sched_setscheduler", None)
        if batch is not None and setter is not None:
            try:
                setter(0, batch, os.sched_param(0))
            except (OSError, AttributeError):
                pass


def tool_preexec_fn(*, new_session: bool = True) -> Optional[Callable[[], None]]:
    """``preexec_fn`` for tool subprocesses.

    Combines the existing ``os.setsid`` (own process group so kill-by-group
    still works) with the low-priority policy. Returns ``None`` on Windows,
    where ``preexec_fn`` is unsupported.
    """
    if _IS_WINDOWS:
        return None

    def _preexec() -> None:
        if new_session:
            os.setsid()
        apply_tool_priority()

    return _preexec
