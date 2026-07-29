"""Unit tests for Fish Audio live TTS streaming (no network)."""

from __future__ import annotations

import base64
import threading
from unittest.mock import MagicMock, patch

import msgpack
import pytest

from plugins.tts.fishaudio.provider import FishAudioTTSProvider
from plugins.tts.fishaudio.stream import (
    LIVE_WS_URL,
    FishAudioTTSStreamSession,
    build_start_request,
    _validate_live_url,
)


@pytest.fixture(autouse=True)
def _tmp_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "test-key")
    yield tmp_path


class TestUrlGuard:
    def test_rejects_non_wss(self):
        with pytest.raises(ValueError, match="wss"):
            _validate_live_url("https://api.fish.audio/v1/tts/live")

    def test_rejects_foreign_host(self):
        with pytest.raises(ValueError, match="not allowed"):
            _validate_live_url("wss://evil.example/v1/tts/live")

    def test_allows_fish_host(self):
        assert _validate_live_url(LIVE_WS_URL) == LIVE_WS_URL


class TestBuildRequest:
    def test_empty_text_and_voice(self):
        request = build_start_request(
            format="mp3",
            voice="voice-1",
            config={"temperature": 0.5, "top_p": 0.8},
        )
        assert request["text"] == ""
        assert request["format"] == "mp3"
        assert request["reference_id"] == "voice-1"
        assert request["temperature"] == 0.5

    def test_opus_forces_48k(self):
        request = build_start_request(format="opus", config={"sample_rate": 44100})
        assert request["format"] == "opus"
        assert request["sample_rate"] == 48000


class TestProviderStreaming:
    def test_supports_streaming_default(self):
        provider = FishAudioTTSProvider()
        assert provider.supports_streaming() is True

    def test_supports_streaming_can_disable(self, monkeypatch):
        monkeypatch.setattr(
            "plugins.tts.fishaudio.provider._load_provider_config",
            lambda: {"streaming": False},
        )
        assert FishAudioTTSProvider().supports_streaming() is False

    def test_open_stream_wires_session(self):
        provider = FishAudioTTSProvider()
        fake = MagicMock()
        with patch(
            "plugins.tts.fishaudio.provider.FishAudioTTSStreamSession",
            return_value=fake,
        ) as ctor:
            session = provider.open_stream(format="mp3", voice="v1")
        assert session is fake
        fake.start.assert_called_once()
        kwargs = ctor.call_args.kwargs
        assert kwargs["model"]
        assert kwargs["request"]["format"] == "mp3"
        assert kwargs["request"]["reference_id"] == "v1"


class FakeWS:
    def __init__(self, inbound):
        self.inbound = list(inbound)
        self.sent = []
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if not self.inbound:
            await asyncio.sleep(3600)
            return b""
        item = self.inbound.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, float):
            await asyncio.sleep(item)
            return await self.recv()
        return item

    async def close(self):
        self.closed = True


import asyncio  # noqa: E402  — kept near FakeWS for readability in tests


class TestStreamSessionProtocol:
    def test_frame_order_audio_and_finish(self):
        audio_chunks = []
        ended = threading.Event()
        end_reason = {}
        release_audio = threading.Event()

        class GatedWS(FakeWS):
            async def recv(self):
                # Wait until the client has sent text/flush/stop so outbound
                # framing is observable before the server finish event.
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: release_audio.wait(timeout=5.0)
                )
                return await super().recv()

        frames = [
            msgpack.packb({"event": "audio", "audio": b"abc"}, use_bin_type=True),
            msgpack.packb({"event": "audio", "audio": b"def"}, use_bin_type=True),
            msgpack.packb({"event": "finish"}, use_bin_type=True),
        ]
        fake_ws = GatedWS(frames)

        async def fake_connect(*_a, **_k):
            return fake_ws

        def on_audio(chunk: bytes):
            audio_chunks.append(chunk)

        def on_end(reason: str, error):
            end_reason["reason"] = reason
            end_reason["error"] = error
            ended.set()

        with patch("websockets.connect", side_effect=fake_connect):
            session = FishAudioTTSStreamSession(
                request={"text": "", "format": "mp3"},
                model="s2.1-pro-free",
                on_audio=on_audio,
                on_end=on_end,
                connect_timeout_s=5.0,
                idle_timeout_s=5.0,
                total_timeout_s=10.0,
            )
            session.start()
            session.send_text("Hello world.")
            session.flush()
            session.stop(cancel=False)
            release_audio.set()
            assert ended.wait(timeout=5.0)

        assert audio_chunks == [b"abc", b"def"]
        assert end_reason["reason"] == "complete"
        assert end_reason["error"] is None

        decoded = [msgpack.unpackb(frame, raw=False) for frame in fake_ws.sent]
        assert decoded[0]["event"] == "start"
        assert decoded[0]["request"]["text"] == ""
        assert any(item.get("event") == "text" for item in decoded)
        assert any(item.get("event") == "flush" for item in decoded)
        assert any(item.get("event") == "stop" for item in decoded)

    def test_cancel_short_circuits(self):
        ended = threading.Event()
        end_reason = {}

        async def fake_connect(*_a, **_k):
            return FakeWS([3600.0])

        def on_end(reason: str, error):
            end_reason["reason"] = reason
            ended.set()

        with patch("websockets.connect", side_effect=fake_connect):
            session = FishAudioTTSStreamSession(
                request={"text": "", "format": "mp3"},
                model="s2.1-pro-free",
                on_end=on_end,
                connect_timeout_s=5.0,
            )
            session.start()
            session.stop(cancel=True)
            assert ended.wait(timeout=5.0)

        assert end_reason["reason"] == "cancelled"

    def test_rejects_oversized_text_chunk(self):
        async def fake_connect(*_a, **_k):
            return FakeWS([3600.0])

        with patch("websockets.connect", side_effect=fake_connect):
            session = FishAudioTTSStreamSession(
                request={"text": "", "format": "mp3"},
                model="s2.1-pro-free",
                connect_timeout_s=5.0,
            )
            session.start()
            with pytest.raises(ValueError, match="characters"):
                session.send_text("x" * 3000)
            session.close()


class TestGatewayRpcContract:
    def test_open_falls_back_when_provider_missing(self, monkeypatch):
        import tui_gateway.server as server

        monkeypatch.setattr(server, "_resolve_streaming_tts_provider", lambda: None)
        sid = "sess-1"
        server._sessions[sid] = {"session_key": "k"}
        try:
            result = server._methods["tts.stream.open"](
                1, {"session_id": sid, "format": "mp3"}
            )
            assert result["result"]["streaming"] is False
            assert result["result"]["stream_id"] is None
        finally:
            server._sessions.pop(sid, None)

    def test_open_emits_chunks_and_end(self, monkeypatch):
        import tui_gateway.server as server

        emitted = []

        def capture(event, sid, payload=None):
            emitted.append((event, sid, payload))

        class StubSession:
            def __init__(self):
                self.on_audio = None
                self.on_end = None

            def send_text(self, text):
                assert text
                self.on_audio(b"hi")

            def flush(self):
                pass

            def stop(self, *, cancel=False):
                self.on_end("complete" if not cancel else "cancelled", None)

            def close(self):
                pass

        stub = StubSession()

        class StubProvider:
            name = "fishaudio"

            def open_stream(self, **kwargs):
                stub.on_audio = kwargs["on_audio"]
                stub.on_end = kwargs["on_end"]
                return stub

        monkeypatch.setattr(
            server, "_resolve_streaming_tts_provider", lambda: StubProvider()
        )
        monkeypatch.setattr(server, "_emit", capture)

        sid = "sess-stream"
        server._sessions[sid] = {"session_key": "k"}
        try:
            opened = server._methods["tts.stream.open"](
                1, {"session_id": sid, "format": "mp3"}
            )
            assert opened["result"]["streaming"] is True
            stream_id = opened["result"]["stream_id"]
            assert stream_id

            text_resp = server._methods["tts.stream.text"](
                2, {"session_id": sid, "stream_id": stream_id, "text": "Hello"}
            )
            assert text_resp["result"]["status"] == "ok"

            close_resp = server._methods["tts.stream.close"](
                3, {"session_id": sid, "stream_id": stream_id, "cancel": False}
            )
            assert close_resp["result"]["status"] == "ok"

            chunk_events = [e for e in emitted if e[0] == "tts.stream.chunk"]
            end_events = [e for e in emitted if e[0] == "tts.stream.end"]
            assert len(chunk_events) == 1
            assert chunk_events[0][2]["seq"] == 1
            assert base64.b64decode(chunk_events[0][2]["data_b64"]) == b"hi"
            assert end_events[-1][2]["reason"] == "complete"
            assert stream_id not in server._tts_streams
        finally:
            server._sessions.pop(sid, None)
            server._tts_streams.clear()
