"""Sleep must not look like a stalled Grok, NVIDIA, or Anthropic stream.

Those providers share ``interruptible_streaming_api_call``. The stall detector
measures awake time (``time.monotonic``), which does not advance while the
machine is asleep. A wall-clock jump on wake used to exceed the 180s threshold
and kill a live stream.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest

sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())


def _chunk(content, finish_reason=None):
    delta = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning_content=None,
        reasoning=None,
    )
    choice = SimpleNamespace(index=0, delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model="test-model", usage=None)


def test_wall_clock_jump_does_not_kill_shared_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_STREAM_STALE_TIMEOUT", "180")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")

    from run_agent import AIAgent
    import agent.chat_completion_helpers as helpers

    started = threading.Event()
    release = threading.Event()

    def chunks():
        yield _chunk("Hello")
        started.set()
        assert release.wait(timeout=5), "test failed to release the stream"
        yield _chunk(" there", finish_reason="stop")

    mock_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **_kwargs: chunks())
        )
    )
    agent = AIAgent(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/test",
        provider="nvidia",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    agent.api_mode = "chat_completions"
    agent._interrupt_requested = False
    agent._create_request_openai_client = lambda **_kwargs: mock_client
    agent._close_request_openai_client = lambda *a, **k: None
    abort_reasons = []

    def _abort(client, *, reason):
        abort_reasons.append(reason)

    agent._abort_request_openai_client = _abort

    real_time = time.time
    origin = {"wall": None}
    jump = {"on": False}

    def frozen_then_jumped():
        now = real_time()
        if origin["wall"] is None:
            origin["wall"] = now
        if jump["on"]:
            return origin["wall"] + 5000.0
        return origin["wall"]

    result = {}

    def runner():
        try:
            result["response"] = agent._interruptible_streaming_api_call({})
        except Exception as exc:  # pragma: no cover - assertion below
            result["error"] = exc

    with pytest.MonkeyPatch.context() as clock:
        clock.setattr(helpers.time, "time", frozen_then_jumped)
        worker = threading.Thread(target=runner, daemon=True)
        worker.start()
        assert started.wait(timeout=5), "stream never delivered the first chunk"
        jump["on"] = True
        time.sleep(1.2)
        assert "stale_stream_kill" not in abort_reasons
        release.set()
        worker.join(timeout=5)

    assert "error" not in result, result.get("error")
    assert worker.is_alive() is False
    response = result["response"]
    assert response.choices[0].message.content == "Hello there"
    assert "stale_stream_kill" not in abort_reasons
