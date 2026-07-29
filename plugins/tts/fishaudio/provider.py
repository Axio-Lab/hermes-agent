"""Fish Audio TTS provider implemented through Hermes' public plugin API."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.tts_provider import DEFAULT_OUTPUT_FORMAT, TTSProvider
from plugins._fishaudio_common import (
    api_key,
    error_message,
    request_bytes,
    request_json,
)
from plugins.tts.fishaudio.stream import (
    FishAudioTTSStreamSession,
    build_start_request,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "s2.1-pro-free"
DEFAULT_FORMAT = "mp3"
DEFAULT_TIMEOUT_SECONDS = 120.0
SUPPORTED_OUTPUT_FORMATS = frozenset({"mp3", "wav", "opus"})
MODELS: List[Dict[str, Any]] = [
    {
        "id": "s2.1-pro-free",
        "display": "S2.1 Pro Free",
        "languages": ["multilingual"],
    },
    {
        "id": "s2.1-pro",
        "display": "S2.1 Pro",
        "languages": ["multilingual"],
    },
    {
        "id": "s2-pro",
        "display": "S2 Pro",
        "languages": ["multilingual"],
    },
]


def _load_provider_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        config = load_config()
    except Exception as exc:
        logger.debug("Could not load Fish Audio config: %s", exc)
        return {}

    tts = config.get("tts") if isinstance(config, dict) else None
    if not isinstance(tts, dict):
        return {}
    section = tts.get("fishaudio")
    return section if isinstance(section, dict) else {}


class FishAudioTTSProvider(TTSProvider):
    """Fish Audio buffered HTTP TTS backend."""

    @property
    def name(self) -> str:
        return "fishaudio"

    @property
    def display_name(self) -> str:
        return "Fish Audio"

    @property
    def voice_compatible(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(api_key())

    def list_models(self) -> List[Dict[str, Any]]:
        return list(MODELS)

    def list_voices(self) -> List[Dict[str, Any]]:
        if not api_key():
            return []

        status, payload = request_json(
            "GET",
            "model",
            query={
                "self": True,
                "page_size": 100,
                "page_number": 1,
                "sort_by": "created_at",
            },
            timeout=15.0,
        )
        if status != 200:
            logger.warning(
                "Fish Audio voice list failed: %s",
                error_message(payload, f"HTTP {status}"),
            )
            return []

        voices: List[Dict[str, Any]] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            voice_id = str(item.get("_id") or item.get("id") or "").strip()
            if not voice_id:
                continue
            if str(item.get("type") or "tts").lower() != "tts":
                continue
            if str(item.get("visibility") or "").lower() not in {
                "private",
                "unlist",
                "public",
            }:
                continue
            title = str(item.get("title") or voice_id).strip()
            state = str(item.get("state") or "").strip()
            visibility = str(item.get("visibility") or "").strip()
            suffix = " · ".join(part for part in (state, visibility) if part)
            voices.append(
                {
                    "id": voice_id,
                    "display": f"{title} ({suffix})" if suffix else title,
                    "languages": item.get("languages") or [],
                    "visibility": visibility,
                    "state": state,
                }
            )
        return voices

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def default_voice(self) -> Optional[str]:
        config = _load_provider_config()
        value = (
            config.get("reference_id")
            or config.get("voice")
            or config.get("voice_id")
        )
        return str(value).strip() if value else None

    def supports_streaming(self) -> bool:
        config = _load_provider_config()
        # Default on; operators can disable live WSS without changing provider.
        return bool(config.get("streaming", True))

    def open_stream(
        self,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        format: str = DEFAULT_OUTPUT_FORMAT,
        on_audio: Optional[Callable[[bytes], None]] = None,
        on_end: Optional[Callable[[str, Optional[str]], None]] = None,
        **extra: Any,
    ) -> FishAudioTTSStreamSession:
        if not api_key():
            raise RuntimeError("FISH_AUDIO_API_KEY is not set")
        config = _load_provider_config()
        resolved_model = str(
            model or config.get("model") or DEFAULT_MODEL
        ).strip()
        request = build_start_request(
            format=format,
            voice=voice,
            config=config,
            **extra,
        )
        session = FishAudioTTSStreamSession(
            request=request,
            model=resolved_model,
            on_audio=on_audio,
            on_end=on_end,
            connect_timeout_s=float(
                config.get("stream_connect_timeout", 15.0) or 15.0
            ),
            idle_timeout_s=float(config.get("stream_idle_timeout", 60.0) or 60.0),
            total_timeout_s=float(
                config.get("stream_total_timeout", 300.0) or 300.0
            ),
        )
        session.start()
        return session

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Fish Audio",
            "badge": "cloud",
            "tag": "Multilingual TTS with owned and cloned voices",
            "env_vars": [
                {
                    "key": "FISH_AUDIO_API_KEY",
                    "prompt": "Fish Audio API key",
                    "url": "https://fish.audio/app/api-keys",
                }
            ],
        }

    def synthesize(
        self,
        text: str,
        output_path: str,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        speed: Optional[float] = None,
        format: str = DEFAULT_OUTPUT_FORMAT,
        **extra: Any,
    ) -> str:
        clean_text = (text or "").strip()
        if not clean_text:
            raise ValueError("text is required for Fish Audio TTS")
        if not api_key():
            raise RuntimeError("FISH_AUDIO_API_KEY is not set")

        config = _load_provider_config()
        resolved_format = self._resolve_format(format, output_path)
        resolved_model = str(
            model or config.get("model") or DEFAULT_MODEL
        ).strip()
        resolved_voice = (
            voice
            or config.get("reference_id")
            or config.get("voice")
            or config.get("voice_id")
        )

        payload: Dict[str, Any] = {
            "text": clean_text,
            "format": resolved_format,
            "temperature": self._number(
                extra.get("temperature", config.get("temperature", 0.7)), 0.7
            ),
            "top_p": self._number(
                extra.get("top_p", config.get("top_p", 0.7)), 0.7
            ),
        }
        if resolved_voice:
            payload["reference_id"] = str(resolved_voice).strip()

        for key, default in (
            ("sample_rate", 44100),
            ("mp3_bitrate", 128),
            ("opus_bitrate", None),
            ("latency", None),
            ("language", None),
            ("normalize", None),
        ):
            value = extra.get(key, config.get(key, default))
            if value is not None and value != "":
                payload[key] = value
        if resolved_format == "opus":
            # Fish's Opus encoder accepts 48 kHz only. Messaging gateways use
            # Opus voice notes, so normalize this even when the buffered MP3
            # default is configured at 44.1 kHz.
            payload["sample_rate"] = 48000

        resolved_speed = speed if speed is not None else config.get("speed")
        volume = config.get("volume")
        normalize_loudness = config.get("normalize_loudness")
        prosody: Dict[str, Any] = {}
        if resolved_speed is not None:
            prosody["speed"] = self._number(resolved_speed, 1.0)
        if volume is not None:
            prosody["volume"] = self._number(volume, 0.0)
        if normalize_loudness is not None:
            prosody["normalize_loudness"] = bool(normalize_loudness)
        if prosody:
            payload["prosody"] = prosody

        timeout = self._number(config.get("timeout", DEFAULT_TIMEOUT_SECONDS), DEFAULT_TIMEOUT_SECONDS)
        status, audio, _headers = request_bytes(
            "POST",
            "v1/tts",
            body=payload,
            headers={"model": resolved_model},
            timeout=max(1.0, min(timeout, 300.0)),
            max_bytes=25 * 1024 * 1024,
        )
        if status != 200:
            try:
                detail: Any = json.loads(audio.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                detail = audio.decode("utf-8", errors="replace")
            raise RuntimeError(
                error_message(detail, f"Fish Audio TTS failed (HTTP {status})")
            )
        if not audio:
            raise RuntimeError("Fish Audio returned an empty audio response")

        out = Path(output_path).expanduser().resolve()
        if out.suffix.lower().lstrip(".") not in SUPPORTED_OUTPUT_FORMATS:
            out = out.with_suffix(f".{resolved_format}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(audio)
        return str(out)

    @staticmethod
    def _resolve_format(requested: Optional[str], output_path: str) -> str:
        suffix = Path(output_path).suffix.lower().lstrip(".")
        if suffix == "ogg":
            return "opus"
        if suffix in SUPPORTED_OUTPUT_FORMATS:
            return suffix
        clean = str(requested or DEFAULT_FORMAT).strip().lower()
        if clean == "ogg":
            return "opus"
        return clean if clean in SUPPORTED_OUTPUT_FORMATS else DEFAULT_FORMAT

    @staticmethod
    def _number(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
