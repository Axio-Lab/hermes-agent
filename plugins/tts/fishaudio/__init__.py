"""Bundled Fish Audio TTS backend."""

from plugins.tts.fishaudio.provider import FishAudioTTSProvider
from plugins.tts.fishaudio.transcription_provider import (
    FishAudioTranscriptionProvider,
)
from plugins.tts.fishaudio.tools import REGISTERED_TOOLS, TOOLSET, api_key

__all__ = ["FishAudioTTSProvider", "FishAudioTranscriptionProvider", "register"]


def register(ctx) -> None:
    ctx.register_tts_provider(FishAudioTTSProvider())
    ctx.register_transcription_provider(FishAudioTranscriptionProvider())
    for name, schema, handler, emoji in REGISTERED_TOOLS:
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            check_fn=lambda: bool(api_key()),
            requires_env=["FISH_AUDIO_API_KEY"],
            emoji=emoji,
        )
