from __future__ import annotations

import httpx
import pytest

from gateway.verxio_workflow_hook import handle_verxio_workflow


@pytest.mark.asyncio
async def test_verxio_workflow_hook_returns_matching_agent_output(monkeypatch):
    monkeypatch.setenv("VERXIO_API_URL", "https://verxio.test")
    monkeypatch.setenv("VERXIO_RUNTIME_TOKEN", "runtime-token")
    request_payload = {}

    def respond(request: httpx.Request) -> httpx.Response:
        request_payload.update(__import__("json").loads(request.content))
        assert request.headers["Authorization"] == "Bearer runtime-token"
        return httpx.Response(
            200,
            json={
                "runs": [
                    {
                        "status": "completed",
                        "output_text": "The workflow handled this message.",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(respond)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "gateway.verxio_workflow_hook.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    result = await handle_verxio_workflow(
        "agent:start",
        {
            "chat_id": "channel-1",
            "connection_id": "conn_123",
            "message_full": "Please check the blocker.",
            "platform": "slack",
            "user_id": "user-1",
        },
    )

    assert result == {
        "handled": True,
        "response": "The workflow handled this message.",
        "source": "verxio_workflow",
    }
    assert request_payload["channel"] == "slack"
    assert request_payload["connection_id"] == "conn_123"
    assert request_payload["message"] == "Please check the blocker."


@pytest.mark.asyncio
async def test_verxio_workflow_hook_does_not_claim_unmatched_message(monkeypatch):
    monkeypatch.setenv("VERXIO_API_URL", "https://verxio.test")
    monkeypatch.setenv("VERXIO_RUNTIME_TOKEN", "runtime-token")
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"runs": []}))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "gateway.verxio_workflow_hook.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    result = await handle_verxio_workflow(
        "agent:start",
        {"message_full": "hello", "platform": "telegram"},
    )

    assert result is None
