"""DashScope / Qwen Cloud TTS backend.

Uses the native multimodal-generation speech path validated on intl:
``POST /api/v1/services/aigc/multimodal-generation/generation`` with
``model=qwen3-tts-*`` and ``parameters.voice``.

CosyVoice IDs are listed for accounts/regions that expose them; on intl
the validated default is ``qwen3-tts-flash``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.tts_provider import TTSProvider
from plugins._dashscope_common import api_key, error_message, request_json

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3-tts-flash"
DEFAULT_VOICE = "Cherry"

_MODELS: Dict[str, Dict[str, Any]] = {
    "qwen3-tts-flash": {
        "display": "Qwen3 TTS Flash",
        "strengths": "Speech synthesis (simple one-shot) — default on intl",
    },
    "qwen3-tts-instruct-flash": {
        "display": "Qwen3 TTS Instruct",
        "strengths": "Speech synthesis with instruction control",
    },
    "cosyvoice-v3-plus": {
        "display": "CosyVoice v3 Plus",
        "strengths": "Speech synthesis (best CosyVoice; region-dependent)",
    },
    "cosyvoice-v3-flash": {
        "display": "CosyVoice v3 Flash",
        "strengths": "Speech synthesis (faster CosyVoice; region-dependent)",
    },
    "cosyvoice-v3.5-plus": {
        "display": "CosyVoice v3.5 Plus",
        "strengths": "Speech synthesis (newer CosyVoice; region-dependent)",
    },
}

# Documented Qwen3-TTS system voices (intl multimodal path).
_VOICES: List[Dict[str, Any]] = [
    {"id": "Cherry", "display": "Cherry", "language": "en", "gender": "female"},
    {"id": "Serena", "display": "Serena", "language": "en", "gender": "female"},
    {"id": "Ethan", "display": "Ethan", "language": "en", "gender": "male"},
    {"id": "Chelsie", "display": "Chelsie", "language": "en", "gender": "female"},
]


def _load_tts_section() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("tts") if isinstance(cfg, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as exc:
        logger.debug("Could not load tts config: %s", exc)
        return {}


def _resolve_model(explicit: Optional[str] = None) -> str:
    candidates = [
        explicit,
        os.environ.get("DASHSCOPE_TTS_MODEL"),
    ]
    cfg = _load_tts_section()
    nested = cfg.get("dashscope") if isinstance(cfg.get("dashscope"), dict) else {}
    if isinstance(nested, dict):
        candidates.append(nested.get("model") if isinstance(nested.get("model"), str) else None)
    for raw in candidates:
        if isinstance(raw, str) and raw.strip() in _MODELS:
            return raw.strip()
    return DEFAULT_MODEL


def _resolve_voice(explicit: Optional[str] = None) -> str:
    candidates = [
        explicit,
        os.environ.get("DASHSCOPE_TTS_VOICE"),
    ]
    cfg = _load_tts_section()
    nested = cfg.get("dashscope") if isinstance(cfg.get("dashscope"), dict) else {}
    if isinstance(nested, dict):
        candidates.append(nested.get("voice") if isinstance(nested.get("voice"), str) else None)
    known = {v["id"] for v in _VOICES}
    for raw in candidates:
        if isinstance(raw, str) and raw.strip():
            # Allow custom / cloned voice ids through even if not in catalog.
            return raw.strip() if raw.strip() not in known else raw.strip()
    return DEFAULT_VOICE


def _extract_audio_url(payload: Dict[str, Any]) -> Optional[str]:
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    audio = output.get("audio")
    if isinstance(audio, dict):
        url = audio.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
        data = audio.get("data")
        if isinstance(data, str) and data.strip():
            return f"data:audio/wav;base64,{data.strip()}"
    return None


def _download_audio(url: str, output_path: str) -> str:
    import base64

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if url.startswith("data:"):
        _, _, b64 = url.partition(",")
        path.write_bytes(base64.b64decode(b64))
        return str(path.resolve())

    import requests

    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return str(path.resolve())


class DashScopeTTSProvider(TTSProvider):
    """DashScope multimodal TTS (qwen3-tts / CosyVoice when available)."""

    @property
    def name(self) -> str:
        return "dashscope"

    @property
    def display_name(self) -> str:
        return "DashScope (Qwen Cloud)"

    @property
    def voice_compatible(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(api_key())

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": model_id,
                "display": meta["display"],
                "strengths": meta.get("strengths", ""),
            }
            for model_id, meta in _MODELS.items()
        ]

    def list_voices(self) -> List[Dict[str, Any]]:
        return list(_VOICES)

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def default_voice(self) -> Optional[str]:
        return DEFAULT_VOICE

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "DashScope (Qwen Cloud)",
            "badge": "paid",
            "tag": "Qwen3-TTS / CosyVoice — speech synthesis",
            "env_vars": [
                {
                    "key": "DASHSCOPE_API_KEY",
                    "prompt": "DashScope / Qwen Cloud API key",
                    "url": "https://modelstudio.console.alibabacloud.com/",
                },
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
        format: str = "mp3",
        **extra: Any,
    ) -> str:
        del format, extra
        text = (text or "").strip()
        if not text:
            raise ValueError("text is required for DashScope TTS")
        if not api_key():
            raise RuntimeError(
                "DASHSCOPE_API_KEY not set. Connect Qwen Cloud / DashScope "
                "or set tts.provider=dashscope after configuring the key."
            )

        model_id = _resolve_model(model)
        voice_id = _resolve_voice(voice)
        parameters: Dict[str, Any] = {"voice": voice_id}
        if speed is not None:
            try:
                parameters["speech_rate"] = float(speed)
            except (TypeError, ValueError):
                pass

        body = {
            "model": model_id,
            "input": {"text": text},
            "parameters": parameters,
        }
        status, payload = request_json(
            "POST",
            "services/aigc/multimodal-generation/generation",
            body=body,
            timeout=90.0,
        )
        if status != 200:
            raise RuntimeError(
                error_message(payload, f"DashScope TTS failed (HTTP {status})")
            )

        audio_url = _extract_audio_url(payload)
        if not audio_url:
            raise RuntimeError("DashScope TTS returned no audio URL")

        return _download_audio(audio_url, output_path)


def register(ctx) -> None:
    ctx.register_tts_provider(DashScopeTTSProvider())
