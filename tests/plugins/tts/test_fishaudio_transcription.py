"""Fish Audio whole-file ASR provider and handle-only tool contracts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import plugins.tts.fishaudio as fishaudio
from agent import transcription_registry
from plugins.tts.fishaudio import tools
from plugins.tts.fishaudio.transcription_provider import (
    ASR_ENDPOINT,
    MAX_AUDIO_BYTES,
    FishAudioTranscriptionProvider,
)


def _wav_bytes(size: int = 96) -> bytes:
    return (
        b"RIFF" + (size - 8).to_bytes(4, "little") + b"WAVEfmt " + b"\0" * (size - 16)
    )


@pytest.fixture(autouse=True)
def _fish_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "secret-fish-key")
    monkeypatch.setenv("HERMES_SESSION_SOURCE", "tui")
    monkeypatch.setenv("HERMES_SESSION_KEY", "session-a")
    tools._attachments.clear()
    transcription_registry._reset_for_tests()
    yield
    tools._attachments.clear()
    transcription_registry._reset_for_tests()


def _audio(tmp_path: Path, name: str = "sample.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(_wav_bytes())
    return path


def _handle(tmp_path: Path) -> str:
    return tools.register_audio_attachment(
        _audio(tmp_path),
        session_id="session-a",
        actor="profile:local-owner",
        profile=str(tmp_path),
    )["handle"]


def _response() -> dict:
    return {
        "text": "Hello world.",
        "duration": 1.25,
        "segments": [
            {"text": "Hello ", "start": 0, "end": 0.5},
            {"text": "world.", "start": 0.5, "end": 1.25},
        ],
    }


def test_registers_transcription_provider_and_noncolliding_tool():
    ctx = MagicMock()
    fishaudio.register(ctx)

    provider = ctx.register_transcription_provider.call_args.args[0]
    assert isinstance(provider, FishAudioTranscriptionProvider)
    assert provider.name == "fishaudio"
    names = {call.kwargs["name"] for call in ctx.register_tool.call_args_list}
    assert "fishaudio_transcribe" in names
    assert "transcribe_audio" not in names


def test_dashboard_schema_exposes_fish_asr():
    from hermes_cli.web_server import CONFIG_SCHEMA

    assert "fishaudio" in CONFIG_SCHEMA["stt.provider"]["options"]
    assert CONFIG_SCHEMA["stt.fishaudio.model"]["options"] == ["fish-audio-asr-beta"]


def test_standard_dispatch_preserves_duration_and_segments(tmp_path):
    transcription_registry.register_provider(FishAudioTranscriptionProvider())
    audio = _audio(tmp_path)
    config = {
        "enabled": True,
        "provider": "fishaudio",
        "fishaudio": {"language": "en-US", "ignore_timestamps": False},
    }
    with (
        patch("tools.transcription_tools._load_stt_config", return_value=config),
        patch(
            "tools.transcription_tools._ensure_plugins_discovered",
            create=True,
        ),
        patch(
            "plugins.tts.fishaudio.transcription_provider.multipart_post",
            return_value=(200, _response()),
        ),
    ):
        from tools.transcription_tools import transcribe_audio

        result = transcribe_audio(str(audio))

    assert result == {
        "success": True,
        "transcript": "Hello world.",
        "duration": 1.25,
        "segments": [
            {"text": "Hello ", "start": 0.0, "end": 0.5},
            {"text": "world.", "start": 0.5, "end": 1.25},
        ],
        "provider": "fishaudio",
    }


def test_multipart_contract_language_and_timestamps(tmp_path):
    provider = FishAudioTranscriptionProvider()
    with patch(
        "plugins.tts.fishaudio.transcription_provider.multipart_post",
        return_value=(200, _response()),
    ) as request:
        result = provider.transcribe(
            str(_audio(tmp_path)),
            language="pt-BR",
            ignore_timestamps=True,
        )

    assert result["success"] is True
    request.assert_called_once()
    assert request.call_args.args == (ASR_ENDPOINT,)
    assert request.call_args.kwargs["fields"] == {
        "language": "pt-BR",
        "ignore_timestamps": True,
    }
    upload = request.call_args.kwargs["files"][0]
    assert upload[0] == "audio"
    assert upload[1] == "sample.wav"
    assert upload[2].startswith(b"RIFF")
    assert upload[3] == "audio/wav"


def test_provider_config_controls_language_and_timestamps(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "stt:\n  fishaudio:\n    language: ja-JP\n    ignore_timestamps: true\n",
        encoding="utf-8",
    )
    with patch(
        "plugins.tts.fishaudio.transcription_provider.multipart_post",
        return_value=(200, _response()),
    ) as request:
        result = FishAudioTranscriptionProvider().transcribe(str(_audio(tmp_path)))

    assert result["success"] is True
    assert request.call_args.kwargs["fields"] == {
        "language": "ja-JP",
        "ignore_timestamps": True,
    }


def test_api_failure_is_bounded_and_redacted(tmp_path):
    secret_body = "Authorization: Bearer secret-fish-key " + ("provider detail " * 100)
    with patch(
        "plugins.tts.fishaudio.transcription_provider.multipart_post",
        return_value=(401, {"message": secret_body}),
    ):
        result = FishAudioTranscriptionProvider().transcribe(str(_audio(tmp_path)))

    assert result["success"] is False
    assert result["transcript"] == ""
    assert "secret-fish-key" not in result["error"]
    assert len(result["error"]) <= 400
    assert "segments" not in result


@pytest.mark.parametrize(
    "payload",
    [
        {"text": 123, "duration": 1, "segments": []},
        {"text": "ok", "duration": float("nan"), "segments": []},
        {
            "text": "ok",
            "duration": 1,
            "segments": [{"text": "bad", "start": 1, "end": 0}],
        },
    ],
)
def test_malformed_provider_response_is_rejected(tmp_path, payload):
    with patch(
        "plugins.tts.fishaudio.transcription_provider.multipart_post",
        return_value=(200, payload),
    ):
        result = FishAudioTranscriptionProvider().transcribe(str(_audio(tmp_path)))

    assert result["success"] is False
    assert result["transcript"] == ""


def test_provider_rejects_size_malformed_symlink_and_language(tmp_path, monkeypatch):
    provider = FishAudioTranscriptionProvider()
    malformed = tmp_path / "bad.wav"
    malformed.write_bytes(b"not audio")
    assert "malformed" in provider.transcribe(str(malformed))["error"]

    target = _audio(tmp_path)
    link = tmp_path / "link.wav"
    link.symlink_to(target)
    assert "symlinks" in provider.transcribe(str(link))["error"]

    monkeypatch.setattr(
        "plugins.tts.fishaudio.transcription_provider.MAX_AUDIO_BYTES", 8
    )
    assert "between 1 and 8 bytes" in provider.transcribe(str(target))["error"]
    monkeypatch.setattr(
        "plugins.tts.fishaudio.transcription_provider.MAX_AUDIO_BYTES",
        MAX_AUDIO_BYTES,
    )
    assert "BCP-47" in provider.transcribe(str(target), language="../private")["error"]


def test_handle_tool_returns_only_normalized_contract(tmp_path):
    handle = _handle(tmp_path)
    with patch.object(
        FishAudioTranscriptionProvider,
        "transcribe_authorized_audio",
        return_value={
            "success": True,
            "transcript": "Scoped transcript",
            "duration": 2.0,
            "segments": [{"text": "Scoped transcript", "start": 0, "end": 2}],
            "provider": "fishaudio",
            "provider_body": {"private": "detail"},
        },
    ) as transcribe:
        result = json.loads(
            tools.fishaudio_transcribe({
                "attachment_handle": handle,
                "language": "en",
                "ignore_timestamps": False,
            })
        )

    assert result == {
        "success": True,
        "transcript": "Scoped transcript",
        "duration": 2.0,
        "segments": [{"text": "Scoped transcript", "start": 0, "end": 2}],
    }
    assert str(tmp_path) not in json.dumps(result)
    assert transcribe.call_args.kwargs["filename"] == "sample.wav"
    assert transcribe.call_args.args[0].startswith(b"RIFF")


def test_handle_tool_denies_path_stale_and_cross_context(tmp_path):
    raw_path = str(_audio(tmp_path))
    path_result = json.loads(
        tools.fishaudio_transcribe({"attachment_handle": raw_path})
    )
    assert path_result["success"] is False
    assert "raw paths" in path_result["error"]

    handle = _handle(tmp_path)
    tools._attachments[handle]["expires"] = 0
    stale = json.loads(tools.fishaudio_transcribe({"attachment_handle": handle}))
    assert "invalid or stale" in stale["error"]

    handle = _handle(tmp_path)
    tools._attachments[handle]["session"] = "other-session"
    cross_session = json.loads(
        tools.fishaudio_transcribe({"attachment_handle": handle})
    )
    assert "another actor or session" in cross_session["error"]

    tools._attachments[handle]["session"] = "session-a"
    tools._attachments[handle]["profile"] = "/another/profile"
    cross_profile = json.loads(
        tools.fishaudio_transcribe({"attachment_handle": handle})
    )
    assert "another profile" in cross_profile["error"]


def test_other_transcription_provider_remains_unchanged(tmp_path):
    class OtherProvider(FishAudioTranscriptionProvider):
        @property
        def name(self) -> str:
            return "other-asr"

        def transcribe(self, file_path, **kwargs):
            return {
                "success": True,
                "transcript": "other",
                "provider": self.name,
            }

    transcription_registry.register_provider(FishAudioTranscriptionProvider())
    transcription_registry.register_provider(OtherProvider())
    with (
        patch(
            "tools.transcription_tools._load_stt_config",
            return_value={"enabled": True, "provider": "other-asr"},
        ),
        patch(
            "tools.transcription_tools._ensure_plugins_discovered",
            create=True,
        ),
    ):
        from tools.transcription_tools import transcribe_audio

        result = transcribe_audio(str(_audio(tmp_path)))

    assert result == {
        "success": True,
        "transcript": "other",
        "provider": "other-asr",
    }
