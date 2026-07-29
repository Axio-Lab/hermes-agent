"""Tests for the bundled Fish Audio TTS plugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

import plugins.tts.fishaudio as fishaudio
from plugins.tts.fishaudio.provider import FishAudioTTSProvider


@pytest.fixture(autouse=True)
def _tmp_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "test-key")
    return FishAudioTTSProvider()


class TestMetadata:
    def test_name_and_models(self, provider):
        assert provider.name == "fishaudio"
        assert provider.default_model() == "s2.1-pro-free"
        assert {item["id"] for item in provider.list_models()} == {
            "s2.1-pro-free",
            "s2.1-pro",
            "s2-pro",
        }

    def test_setup_schema(self, provider):
        schema = provider.get_setup_schema()
        assert schema["name"] == "Fish Audio"
        assert schema["env_vars"][0]["key"] == "FISH_AUDIO_API_KEY"

    def test_register(self):
        ctx = MagicMock()
        fishaudio.register(ctx)
        ctx.register_tts_provider.assert_called_once()


class TestVoices:
    def test_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
        monkeypatch.delenv("FISH_API_KEY", raising=False)
        assert FishAudioTTSProvider().list_voices() == []

    def test_lists_owned_voices(self, provider):
        payload = {
            "items": [
                {
                    "_id": "voice-1",
                    "type": "tts",
                    "title": "Support",
                    "state": "trained",
                    "visibility": "private",
                    "languages": ["en"],
                },
                {
                    "_id": "skip",
                    "type": "svc",
                    "title": "Not TTS",
                    "state": "trained",
                    "visibility": "private",
                },
            ]
        }
        with patch(
            "plugins.tts.fishaudio.provider.request_json",
            return_value=(200, payload),
        ) as request:
            voices = provider.list_voices()

        assert voices == [
            {
                "id": "voice-1",
                "display": "Support (trained · private)",
                "languages": ["en"],
                "visibility": "private",
                "state": "trained",
            }
        ]
        assert request.call_args.kwargs["query"]["self"] is True


class TestSynthesize:
    def test_missing_key(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
        monkeypatch.delenv("FISH_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="FISH_AUDIO_API_KEY"):
            FishAudioTTSProvider().synthesize(
                "hello", str(tmp_path / "out.mp3")
            )

    def test_success_writes_audio(self, provider, tmp_path):
        out = tmp_path / "speech.mp3"
        with patch(
            "plugins.tts.fishaudio.provider.request_bytes",
            return_value=(200, b"ID3audio", {"Content-Type": "audio/mpeg"}),
        ) as request:
            path = provider.synthesize(
                "Hello from Verxio",
                str(out),
                voice="voice-123",
                model="s2.1-pro",
            )

        assert path == str(out.resolve())
        assert out.read_bytes() == b"ID3audio"
        assert request.call_args.kwargs["headers"]["model"] == "s2.1-pro"
        body = request.call_args.kwargs["body"]
        assert body["text"] == "Hello from Verxio"
        assert body["reference_id"] == "voice-123"

    def test_config_model_and_voice(self, provider, tmp_path):
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "tts": {
                        "provider": "fishaudio",
                        "fishaudio": {
                            "model": "s2-pro",
                            "reference_id": "voice-config",
                            "format": "mp3",
                        },
                    }
                }
            )
        )
        with patch(
            "plugins.tts.fishaudio.provider.request_bytes",
            return_value=(200, b"audio", {}),
        ) as request:
            provider.synthesize("hi", str(tmp_path / "out.mp3"))

        assert request.call_args.kwargs["headers"]["model"] == "s2-pro"
        assert request.call_args.kwargs["body"]["reference_id"] == "voice-config"

    def test_opus_forces_supported_sample_rate(self, provider, tmp_path):
        with patch(
            "plugins.tts.fishaudio.provider.request_bytes",
            return_value=(200, b"opus", {}),
        ) as request:
            provider.synthesize("hi", str(tmp_path / "voice.ogg"))

        body = request.call_args.kwargs["body"]
        assert body["format"] == "opus"
        assert body["sample_rate"] == 48000

    def test_error_does_not_expose_api_key(self, provider, tmp_path):
        with patch(
            "plugins.tts.fishaudio.provider.request_bytes",
            return_value=(
                401,
                b'{"message":"Authorization: Bearer test-key"}',
                {},
            ),
        ):
            with pytest.raises(RuntimeError) as exc:
                provider.synthesize("hello", str(tmp_path / "out.mp3"))

        assert "test-key" not in str(exc.value)
