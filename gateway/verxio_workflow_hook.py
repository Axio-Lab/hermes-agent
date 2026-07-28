"""Route inbound gateway messages through configured Verxio workflow triggers."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx


logger = logging.getLogger(__name__)
_SUPPORTED_CHANNELS = {"discord", "email", "slack", "telegram", "webchat", "whatsapp"}


def _channel(platform: str) -> str:
    normalized = platform.strip().lower()
    if normalized == "whatsapp_cloud":
        return "whatsapp"
    return normalized if normalized in _SUPPORTED_CHANNELS else "other"


async def handle_verxio_workflow(event_type: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Return a handled response when an enabled Verxio trigger matches."""
    if event_type != "agent:start":
        return None

    base_url = os.getenv("VERXIO_API_URL", "").strip().rstrip("/")
    token = os.getenv("VERXIO_RUNTIME_TOKEN", "").strip()
    if not base_url or not token:
        return None

    payload = {
        "channel": _channel(str(context.get("platform") or "")),
        "connection_id": str(context.get("connection_id") or "default"),
        "conversation_id": str(context.get("chat_id") or ""),
        "event_name": "message.received",
        "input": {
            "chat_type": str(context.get("chat_type") or ""),
            "platform": str(context.get("platform") or ""),
        },
        "message": str(context.get("message_full") or context.get("message") or ""),
        "message_id": str(context.get("message_id") or ""),
        "sender_id": str(context.get("user_id") or ""),
        "sender_name": str(context.get("sender_name") or ""),
        "thread_id": str(context.get("thread_id") or ""),
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
            response = await client.post(
                f"{base_url}/api/workflow-agents/triggers/messaging",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        logger.warning("Verxio messaging trigger dispatch failed: %s", exc)
        return None

    runs = body.get("runs") if isinstance(body, dict) else None
    if not isinstance(runs, list) or not runs:
        return None

    outputs = [
        str(run.get("output_text") or "").strip()
        for run in runs
        if isinstance(run, dict) and str(run.get("status") or "") == "completed"
    ]
    output = "\n\n".join(item for item in outputs if item)
    if not output:
        output = "I couldn't complete the configured workflow for this message. Check the agent run history for details."
    return {"handled": True, "response": output, "source": "verxio_workflow"}
