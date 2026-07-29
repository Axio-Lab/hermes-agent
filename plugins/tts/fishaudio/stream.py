"""Fish Audio WebSocket live TTS session.

Speaks the fixed ``wss://api.fish.audio/v1/tts/live`` MessagePack protocol.
Host overrides are rejected (SSRF-safe). Audio bytes never leave this module
except through the caller-supplied ``on_audio`` callback.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional

from plugins._fishaudio_common import ALLOWED_API_HOSTS, api_key, redact_secret

logger = logging.getLogger(__name__)

LIVE_WS_URL = "wss://api.fish.audio/v1/tts/live"
DEFAULT_FORMAT = "mp3"
DEFAULT_CONNECT_TIMEOUT_S = 15.0
DEFAULT_IDLE_TIMEOUT_S = 60.0
DEFAULT_TOTAL_TIMEOUT_S = 300.0
MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_CHUNK_AUDIO_BYTES = 512 * 1024
MAX_TOTAL_AUDIO_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHUNK_CHARS = 2_000
MAX_TOTAL_TEXT_CHARS = 50_000
MAX_OUTBOUND_QUEUE = 64

OnAudio = Callable[[bytes], None]
OnEnd = Callable[[str, Optional[str]], None]


def _validate_live_url(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "wss":
        raise ValueError("Fish Audio live TTS must use wss")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_API_HOSTS:
        raise ValueError(f"Fish Audio host not allowed: {host or '<missing>'}")
    return url


class FishAudioTTSStreamSession:
    """Thread-backed bidirectional Fish live TTS session."""

    def __init__(
        self,
        *,
        request: Dict[str, Any],
        model: str,
        on_audio: Optional[OnAudio] = None,
        on_end: Optional[OnEnd] = None,
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
        idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_S,
        total_timeout_s: float = DEFAULT_TOTAL_TIMEOUT_S,
        ws_url: str = LIVE_WS_URL,
        key: Optional[str] = None,
    ) -> None:
        self._request = dict(request)
        self._model = str(model or "").strip() or "s2.1-pro-free"
        self._on_audio = on_audio
        self._on_end = on_end
        self._connect_timeout_s = max(1.0, float(connect_timeout_s))
        self._idle_timeout_s = max(1.0, float(idle_timeout_s))
        self._total_timeout_s = max(self._connect_timeout_s, float(total_timeout_s))
        self._ws_url = _validate_live_url(ws_url)
        self._key = (key or api_key()).strip()
        if not self._key:
            raise RuntimeError("FISH_AUDIO_API_KEY is not set")
        if not self._model:
            raise ValueError("model is required")

        self._cmds: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=MAX_OUTBOUND_QUEUE)
        self._ready = threading.Event()
        self._start_error: Optional[str] = None
        self._lock = threading.Lock()
        self._ended = False
        self._closed = False
        self._cancel_requested = False
        self._text_chars = 0
        self._audio_bytes = 0
        self._thread = threading.Thread(
            target=self._thread_main,
            name="fishaudio-tts-stream",
            daemon=True,
        )

    def start(self) -> None:
        """Connect and send the StartEvent. Raises on connect failure."""
        with self._lock:
            if self._closed:
                raise RuntimeError("stream already closed")
            if self._thread.is_alive():
                return
            self._thread.start()
        if not self._ready.wait(timeout=self._connect_timeout_s + 2.0):
            self.stop(cancel=True)
            raise RuntimeError("Fish Audio live TTS connect timed out")
        if self._start_error:
            raise RuntimeError(self._start_error)

    def send_text(self, text: str) -> None:
        clean = (text or "").strip()
        if not clean:
            return
        if len(clean) > MAX_TEXT_CHUNK_CHARS:
            raise ValueError(
                f"text chunk exceeds {MAX_TEXT_CHUNK_CHARS} characters"
            )
        with self._lock:
            if self._ended or self._closed or self._cancel_requested:
                raise RuntimeError("stream is closed")
            next_total = self._text_chars + len(clean)
            if next_total > MAX_TOTAL_TEXT_CHARS:
                raise ValueError(
                    f"stream text exceeds {MAX_TOTAL_TEXT_CHARS} characters"
                )
            self._text_chars = next_total
        try:
            from plugins.tts.fishaudio.usage import check_and_consume

            check_and_consume("tts_chars", len(clean))
        except Exception:
            with self._lock:
                self._text_chars = max(0, self._text_chars - len(clean))
            raise
        try:
            self._cmds.put_nowait(("text", clean))
        except queue.Full as exc:
            raise RuntimeError("Fish Audio stream backpressured") from exc

    def flush(self) -> None:
        with self._lock:
            if self._ended or self._closed or self._cancel_requested:
                return
        try:
            self._cmds.put_nowait(("flush", None))
        except queue.Full as exc:
            raise RuntimeError("Fish Audio stream backpressured") from exc

    def stop(self, *, cancel: bool = False) -> None:
        with self._lock:
            if self._ended and cancel:
                return
            if cancel:
                self._cancel_requested = True
        try:
            self._cmds.put_nowait(("stop", bool(cancel)))
        except queue.Full:
            # Force wake the loop by draining one and re-queuing cancel.
            try:
                self._cmds.get_nowait()
            except queue.Empty:
                pass
            try:
                self._cmds.put_nowait(("stop", True))
            except queue.Full:
                pass

    def close(self) -> None:
        self.stop(cancel=True)
        with self._lock:
            self._closed = True

    def _finish(self, reason: str, error: Optional[str] = None) -> None:
        with self._lock:
            if self._ended:
                return
            self._ended = True
        safe_error = redact_secret(error) if error else None
        callback = self._on_end
        if callback is not None:
            try:
                callback(reason, safe_error)
            except Exception:
                logger.debug("Fish stream on_end callback failed", exc_info=True)

    def _emit_audio(self, chunk: bytes) -> None:
        if not chunk:
            return
        if len(chunk) > MAX_CHUNK_AUDIO_BYTES:
            self.stop(cancel=True)
            self._finish("error", "audio chunk too large")
            return
        with self._lock:
            next_total = self._audio_bytes + len(chunk)
            if next_total > MAX_TOTAL_AUDIO_BYTES:
                self.stop(cancel=True)
                self._finish("error", "audio stream exceeded size limit")
                return
            self._audio_bytes = next_total
            if self._cancel_requested or self._ended:
                return
        callback = self._on_audio
        if callback is not None:
            try:
                callback(chunk)
            except Exception:
                logger.debug("Fish stream on_audio callback failed", exc_info=True)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            msg = redact_secret(str(exc)) or "Fish Audio live TTS failed"
            self._start_error = self._start_error or msg
            self._ready.set()
            self._finish("error", msg)

    async def _run(self) -> None:
        import msgpack
        import websockets
        import websockets.exceptions

        started = time.monotonic()
        last_activity = started
        ws = None
        try:
            ws = await asyncio.wait_for(
                websockets.connect(
                    self._ws_url,
                    additional_headers={
                        "Authorization": f"Bearer {self._key}",
                        "model": self._model,
                    },
                    max_size=MAX_FRAME_BYTES,
                    open_timeout=self._connect_timeout_s,
                    close_timeout=5.0,
                ),
                timeout=self._connect_timeout_s,
            )
            start_frame = msgpack.packb(
                {"event": "start", "request": self._request},
                use_bin_type=True,
            )
            await ws.send(start_frame)
            self._ready.set()

            stopping = False
            while True:
                now = time.monotonic()
                if now - started > self._total_timeout_s:
                    raise TimeoutError("Fish Audio live TTS total timeout")
                if now - last_activity > self._idle_timeout_s:
                    raise TimeoutError("Fish Audio live TTS idle timeout")

                # Drain outbound commands without blocking the receive path.
                while True:
                    try:
                        kind, payload = self._cmds.get_nowait()
                    except queue.Empty:
                        break
                    last_activity = time.monotonic()
                    if kind == "text":
                        await ws.send(
                            msgpack.packb(
                                {"event": "text", "text": payload},
                                use_bin_type=True,
                            )
                        )
                    elif kind == "flush":
                        await ws.send(
                            msgpack.packb({"event": "flush"}, use_bin_type=True)
                        )
                    elif kind == "stop":
                        cancel = bool(payload)
                        if cancel:
                            self._finish("cancelled", None)
                            return
                        if not stopping:
                            stopping = True
                            await ws.send(
                                msgpack.packb(
                                    {"event": "stop"}, use_bin_type=True
                                )
                            )

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed as exc:
                    if stopping and not self._ended:
                        self._finish("complete", None)
                        return
                    raise RuntimeError(
                        f"Fish Audio live TTS closed ({exc.code})"
                    ) from exc

                last_activity = time.monotonic()
                if isinstance(raw, str):
                    # Protocol is MessagePack binary; ignore unexpected text.
                    continue
                if len(raw) > MAX_FRAME_BYTES:
                    raise RuntimeError("Fish Audio frame exceeded size limit")

                try:
                    frame = msgpack.unpackb(raw, raw=False)
                except Exception as exc:
                    raise RuntimeError("invalid Fish Audio MessagePack frame") from exc
                if not isinstance(frame, dict):
                    continue
                event = str(frame.get("event") or "").strip().lower()
                if event == "audio":
                    audio = frame.get("audio")
                    if isinstance(audio, memoryview):
                        audio = audio.tobytes()
                    elif isinstance(audio, bytearray):
                        audio = bytes(audio)
                    if isinstance(audio, bytes):
                        self._emit_audio(audio)
                    continue
                if event in {"finish", "done"}:
                    reason = "complete"
                    err = frame.get("error") or frame.get("message")
                    if err:
                        self._finish("error", str(err))
                    else:
                        self._finish(reason, None)
                    return
                if event == "error":
                    message = frame.get("message") or frame.get("error") or "Fish Audio stream error"
                    self._finish("error", str(message))
                    return
                # Ignore unknown future events.
        except Exception as exc:
            msg = redact_secret(str(exc)) or "Fish Audio live TTS failed"
            if not self._ready.is_set():
                self._start_error = msg
                self._ready.set()
            if not self._ended:
                reason = "cancelled" if self._cancel_requested else "error"
                self._finish(reason, None if reason == "cancelled" else msg)
        finally:
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass
            if not self._ready.is_set():
                self._ready.set()
            if not self._ended:
                self._finish(
                    "cancelled" if self._cancel_requested else "error",
                    None if self._cancel_requested else "stream ended unexpectedly",
                )


def build_start_request(
    *,
    format: str = DEFAULT_FORMAT,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build the StartEvent ``request`` payload from Fish provider config."""
    cfg = dict(config or {})
    resolved_format = str(format or cfg.get("format") or DEFAULT_FORMAT).strip().lower()
    if resolved_format == "ogg":
        resolved_format = "opus"
    if resolved_format not in {"mp3", "wav", "opus", "pcm"}:
        resolved_format = DEFAULT_FORMAT

    request: Dict[str, Any] = {
        "text": "",
        "format": resolved_format,
        "temperature": _number(extra.get("temperature", cfg.get("temperature", 0.7)), 0.7),
        "top_p": _number(extra.get("top_p", cfg.get("top_p", 0.7)), 0.7),
    }
    reference = (
        voice
        or cfg.get("reference_id")
        or cfg.get("voice")
        or cfg.get("voice_id")
    )
    if reference:
        request["reference_id"] = str(reference).strip()

    for key, default in (
        ("sample_rate", 44100),
        ("mp3_bitrate", 128),
        ("opus_bitrate", None),
        ("latency", None),
        ("language", None),
        ("normalize", None),
    ):
        value = extra.get(key, cfg.get(key, default))
        if value is not None and value != "":
            request[key] = value
    if resolved_format == "opus":
        request["sample_rate"] = 48000

    speed = extra.get("speed", cfg.get("speed"))
    volume = cfg.get("volume")
    normalize_loudness = cfg.get("normalize_loudness")
    prosody: Dict[str, Any] = {}
    if speed is not None:
        prosody["speed"] = _number(speed, 1.0)
    if volume is not None:
        prosody["volume"] = _number(volume, 0.0)
    if normalize_loudness is not None:
        prosody["normalize_loudness"] = bool(normalize_loudness)
    if prosody:
        request["prosody"] = prosody
    return request


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
