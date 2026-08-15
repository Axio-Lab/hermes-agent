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
    assert request_payload["input"]["media_urls"] == []
    assert request_payload["input"]["image_url"] == ""


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


@pytest.mark.asyncio
async def test_verxio_workflow_hook_forwards_media_urls(monkeypatch):
    monkeypatch.setenv("VERXIO_API_URL", "https://verxio.test")
    monkeypatch.setenv("VERXIO_RUNTIME_TOKEN", "runtime-token")
    request_payload = {}

    def respond(request: httpx.Request) -> httpx.Response:
        request_payload.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={"runs": [{"status": "completed", "output_text": "Photo received."}]},
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
            "chat_id": "tg-1",
            "message_full": "kitchen",
            "platform": "telegram",
            "user_id": "42",
            "media_urls": ["https://files.example/kitchen.jpg"],
        },
    )

    assert result is not None
    assert request_payload["input"]["media_urls"] == ["https://files.example/kitchen.jpg"]
    assert request_payload["input"]["image_url"] == "https://files.example/kitchen.jpg"


@pytest.mark.asyncio
async def test_verxio_workflow_hook_inlines_local_image_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("VERXIO_API_URL", "https://verxio.test")
    monkeypatch.setenv("VERXIO_RUNTIME_TOKEN", "runtime-token")
    request_payload = {}
    photo = tmp_path / "kitchen.jpg"
    photo.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00" + (b"\x08" * 64) + b"\xff\xd9"
    )

    def respond(request: httpx.Request) -> httpx.Response:
        request_payload.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={"runs": [{"status": "completed", "output_text": "Photo received."}]},
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
            "chat_id": "tg-1",
            "message_full": "",
            "platform": "telegram",
            "user_id": "42",
            "media_urls": [str(photo)],
        },
    )

    assert result is not None
    image_url = request_payload["input"]["image_url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert request_payload["input"]["media_urls"] == [image_url]
