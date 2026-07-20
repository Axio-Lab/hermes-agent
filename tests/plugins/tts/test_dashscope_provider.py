"""Tests for the bundled DashScope TTS plugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

import plugins.tts.dashscope as dashscope_tts


@pytest.fixture(autouse=True)
def _tmp_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    return dashscope_tts.DashScopeTTSProvider()


class TestMetadata:
    def test_name(self, provider):
        assert provider.name == "dashscope"

    def test_default_model_is_intl_validated(self, provider):
        assert provider.default_model() == "qwen3-tts-flash"

    def test_list_models_have_strengths(self, provider):
        models = provider.list_models()
        assert any(m["id"] == "qwen3-tts-flash" for m in models)
        assert any(m["id"] == "cosyvoice-v3-plus" for m in models)
        for entry in models:
            assert entry.get("strengths")

    def test_voices(self, provider):
        voices = provider.list_voices()
        assert any(v["id"] == "Cherry" for v in voices)

    def test_setup_schema(self, provider):
        assert "speech" in provider.get_setup_schema()["tag"].lower()


class TestSynthesize:
    def test_missing_key(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
            dashscope_tts.DashScopeTTSProvider().synthesize(
                "hello", str(tmp_path / "out.wav")
            )

    def test_success_downloads_audio(self, provider, tmp_path):
        out = tmp_path / "speech.wav"
        payload = {
            "output": {
                "audio": {
                    "url": "https://example.com/a.wav",
                    "data": "",
                },
                "finish_reason": "stop",
            }
        }

        with patch.object(
            dashscope_tts, "request_json", return_value=(200, payload)
        ) as mock_req, patch.object(
            dashscope_tts, "_download_audio", return_value=str(out)
        ) as mock_dl:
            path = provider.synthesize("Hello from Verxio", str(out), voice="Cherry")

        assert path == str(out)
        body = mock_req.call_args.kwargs["body"]
        assert body["model"] == "qwen3-tts-flash"
        assert body["input"]["text"] == "Hello from Verxio"
        assert body["parameters"]["voice"] == "Cherry"
        mock_dl.assert_called_once()

    def test_config_model_and_voice(self, provider, tmp_path):
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "tts": {
                        "provider": "dashscope",
                        "dashscope": {
                            "model": "qwen3-tts-instruct-flash",
                            "voice": "Ethan",
                        },
                    }
                }
            )
        )
        out = tmp_path / "out.wav"
        payload = {"output": {"audio": {"url": "https://example.com/a.wav"}}}
        with patch.object(
            dashscope_tts, "request_json", return_value=(200, payload)
        ) as mock_req, patch.object(
            dashscope_tts, "_download_audio", return_value=str(out)
        ):
            provider.synthesize("hi", str(out))
        body = mock_req.call_args.kwargs["body"]
        assert body["model"] == "qwen3-tts-instruct-flash"
        assert body["parameters"]["voice"] == "Ethan"

    def test_register(self):
        ctx = MagicMock()
        dashscope_tts.register(ctx)
        ctx.register_tts_provider.assert_called_once()
