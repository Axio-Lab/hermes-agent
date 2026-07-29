"""Whole-file Fish Audio ASR through Hermes' transcription provider API."""

from __future__ import annotations

import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Dict, Optional

import time

from agent.transcription_provider import TranscriptionProvider
from plugins._fishaudio_common import api_key, error_message, multipart_post
from plugins.tts.fishaudio.audit import audit_event
from plugins.tts.fishaudio.usage import (
    check_and_consume,
    record_failure,
    record_success,
    request_slot,
)

ASR_ENDPOINT = "https://api.fish.audio/v1/asr"
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 4 * 1024 * 1024
MAX_SEGMENTS = 100_000
_AUDIO_SUFFIXES = frozenset({
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
})
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


def _load_provider_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        config = load_config()
    except Exception:
        return {}
    stt = config.get("stt") if isinstance(config, dict) else None
    section = stt.get("fishaudio") if isinstance(stt, dict) else None
    return section if isinstance(section, dict) else {}


def _audio_content_type(path: Path) -> str:
    return {
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".mpeg": "audio/mpeg",
        ".mpga": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
    }.get(path.suffix.lower(), "application/octet-stream")


def _has_audio_magic(suffix: str, header: bytes) -> bool:
    if suffix == ".wav":
        return header.startswith(b"RIFF") and header[8:12] == b"WAVE"
    if suffix in {".mp3", ".mpeg", ".mpga"}:
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
        )
    if suffix in {".ogg", ".opus"}:
        return header.startswith(b"OggS")
    if suffix == ".flac":
        return header.startswith(b"fLaC")
    if suffix in {".m4a", ".mp4"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if suffix == ".webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if suffix == ".aac":
        return len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xF6) == 0xF0
    return False


def _read_validated_audio(file_path: str) -> tuple[Path, bytes]:
    path = Path(file_path)
    if path.is_symlink():
        raise ValueError("Audio file symlinks are not allowed")
    if path.suffix.lower() not in _AUDIO_SUFFIXES:
        raise ValueError("Unsupported audio file type")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Audio file is unavailable") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Audio input must be a regular file")
        if info.st_size <= 0 or info.st_size > MAX_AUDIO_BYTES:
            raise ValueError(
                f"Audio file must be between 1 and {MAX_AUDIO_BYTES} bytes"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_AUDIO_BYTES:
                raise ValueError("Audio file exceeds the 25MB limit")
            chunks.append(chunk)
    finally:
        os.close(fd)

    content = b"".join(chunks)
    if len(content) != info.st_size:
        raise ValueError("Audio file changed while it was being read")
    if not _has_audio_magic(path.suffix.lower(), content[:16]):
        raise ValueError("Audio file is malformed or has unsupported encoding")
    return path, content


def _language_tag(value: Optional[str]) -> Optional[str]:
    language = str(value or "").strip()
    if not language:
        return None
    if len(language) > 35 or not _LANGUAGE_RE.fullmatch(language):
        raise ValueError("language must be a valid BCP-47 language tag")
    return language


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Fish Audio ASR returned an invalid {name}")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Fish Audio ASR returned an invalid {name}")
    return number


def _parse_response(payload: Dict[str, Any]) -> tuple[str, float, list[dict[str, Any]]]:
    text = payload.get("text")
    if not isinstance(text, str) or len(text) > MAX_TRANSCRIPT_CHARS:
        raise ValueError("Fish Audio ASR returned an invalid transcript")
    duration = _finite_number(payload.get("duration"), "duration")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or len(raw_segments) > MAX_SEGMENTS:
        raise ValueError("Fish Audio ASR returned invalid segments")

    segments: list[dict[str, Any]] = []
    total_chars = 0
    for item in raw_segments:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("Fish Audio ASR returned an invalid segment")
        segment_text = item["text"]
        total_chars += len(segment_text)
        if total_chars > MAX_TRANSCRIPT_CHARS:
            raise ValueError("Fish Audio ASR segments exceeded the response limit")
        start = _finite_number(item.get("start"), "segment start")
        end = _finite_number(item.get("end"), "segment end")
        if end < start:
            raise ValueError("Fish Audio ASR returned an invalid segment range")
        segments.append({"text": segment_text, "start": start, "end": end})
    return text, duration, segments


class FishAudioTranscriptionProvider(TranscriptionProvider):
    """Fish Audio's fixed-endpoint, whole-file ASR provider."""

    @property
    def name(self) -> str:
        return "fishaudio"

    @property
    def display_name(self) -> str:
        return "Fish Audio"

    def is_available(self) -> bool:
        return bool(api_key())

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Fish Audio",
            "badge": "cloud",
            "tag": "Whole-file multilingual transcription",
            "env_vars": [
                {
                    "key": "FISH_AUDIO_API_KEY",
                    "prompt": "Fish Audio API key",
                    "url": "https://fish.audio/app/api-keys",
                }
            ],
        }

    def transcribe(
        self,
        file_path: str,
        *,
        model: Optional[str] = None,
        language: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        del model
        try:
            path, content = _read_validated_audio(file_path)
            return self.transcribe_authorized_audio(
                content,
                filename=path.name,
                language=language,
                **extra,
            )
        except Exception as exc:
            return self._failure(exc)

    def transcribe_authorized_audio(
        self,
        content: bytes,
        *,
        filename: str,
        language: Optional[str] = None,
        ignore_timestamps: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Transcribe trusted bytes already resolved by a scoped server handle."""
        try:
            if not api_key():
                raise RuntimeError("FISH_AUDIO_API_KEY is not set")
            if not content or len(content) > MAX_AUDIO_BYTES:
                raise ValueError("Audio file exceeds the 25MB limit")
            safe_name = Path(filename).name
            suffix = Path(safe_name).suffix.lower()
            if suffix not in _AUDIO_SUFFIXES or not _has_audio_magic(
                suffix, content[:16]
            ):
                raise ValueError("Audio file is malformed or has unsupported encoding")

            config = _load_provider_config()
            resolved_language = _language_tag(
                language if language is not None else config.get("language")
            )
            resolved_ignore = (
                config.get("ignore_timestamps", False)
                if ignore_timestamps is None
                else ignore_timestamps
            )
            if not isinstance(resolved_ignore, bool):
                raise ValueError("ignore_timestamps must be true or false")

            check_and_consume("asr_bytes", len(content))
            started = time.monotonic()
            try:
                with request_slot():
                    status, payload = multipart_post(
                        ASR_ENDPOINT,
                        fields={
                            "language": resolved_language,
                            "ignore_timestamps": resolved_ignore,
                        },
                        files=[
                            (
                                "audio",
                                safe_name,
                                content,
                                _audio_content_type(Path(safe_name)),
                            )
                        ],
                        max_bytes=12 * 1024 * 1024,
                    )
            except Exception as exc:
                record_failure()
                audit_event(
                    op="asr.transcribe",
                    outcome="error",
                    provider_op="asr",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    units=len(content),
                    error_class=type(exc).__name__,
                )
                raise
            duration_ms = int((time.monotonic() - started) * 1000)
            if status != 200:
                record_failure()
                audit_event(
                    op="asr.transcribe",
                    outcome="error",
                    provider_op="asr",
                    http_status=status,
                    duration_ms=duration_ms,
                    units=len(content),
                    error_class="HTTPError",
                )
                raise RuntimeError(
                    error_message(payload, f"Fish Audio ASR failed (HTTP {status})")
                )
            text, duration, segments = _parse_response(payload)
            check_and_consume("asr_duration_sec", duration)
            record_success()
            audit_event(
                op="asr.transcribe",
                outcome="success",
                provider_op="asr",
                http_status=status,
                duration_ms=duration_ms,
                units=len(content),
            )
            return {
                "success": True,
                "transcript": text,
                "duration": duration,
                "segments": segments,
                "provider": self.name,
            }
        except Exception as exc:
            return self._failure(exc)

    def _failure(self, exc: Exception) -> Dict[str, Any]:
        return {
            "success": False,
            "transcript": "",
            "error": error_message(str(exc), "Fish Audio ASR failed"),
            "provider": self.name,
        }
