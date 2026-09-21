"""Remote-execution hook: enqueue inbound turns to Verxio instead of running inline."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def remote_exec_enabled() -> bool:
    return os.getenv("VERXIO_REMOTE_EXEC", "").strip().lower() in {"1", "true", "yes", "on"}


async def enqueue_inbound(event: Any) -> bool:
    """POST an inbound message to Verxio. Return True when Verxio accepted it."""
    if not remote_exec_enabled():
        return False
    base = os.getenv("VERXIO_API_URL", "").strip().rstrip("/")
    token = os.getenv("VERXIO_RUNTIME_TOKEN", "").strip()
    if not base or not token:
        return False
    payload = {
        "workspace_id": os.getenv("VERXIO_WORKSPACE_ID", ""),
        "agent_id": os.getenv("VERXIO_AGENT_ID", ""),
        "source": "channel",
        "platform": getattr(getattr(event, "source", None), "platform", None)
        or getattr(event, "platform", ""),
        "text": getattr(event, "text", None) or getattr(event, "content", ""),
        "chat_id": getattr(event, "chat_id", ""),
        "user_id": getattr(event, "user_id", ""),
        "message_id": getattr(event, "message_id", ""),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base}/api/runtime/turns",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        return response.status_code < 400
    except Exception:
        logger.warning("Verxio remote exec enqueue failed", exc_info=True)
        return False


async def deliver_outbound(payload: dict[str, Any], send) -> None:
    """Call ``adapter.send_message`` for a queued outbound payload."""
    text = str(payload.get("text") or "")
    chat_id = payload.get("chat_id")
    if not text:
        return
    await send(text, chat_id=chat_id)
