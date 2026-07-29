"""Bundled Fish Audio TTS backend."""

from plugins.tts.fishaudio.provider import FishAudioTTSProvider

__all__ = ["FishAudioTTSProvider", "register"]


def register(ctx) -> None:
    ctx.register_tts_provider(FishAudioTTSProvider())
