"""Security and persistence tests for Fish Audio voice management."""

from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from plugins.tts.fishaudio import tools


def _wav_bytes(size: int = 96) -> bytes:
    return b"RIFF" + (size - 8).to_bytes(4, "little") + b"WAVEfmt " + b"\0" * (size - 16)


@pytest.fixture(autouse=True)
def _fish_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "not-a-real-key")
    monkeypatch.setenv("HERMES_SESSION_SOURCE", "tui")
    monkeypatch.setenv("HERMES_SESSION_KEY", "session-a")
    monkeypatch.setenv("HERMES_SESSION_USER_TEXT", "initial request")
    for name in (
        "HERMES_SESSION_PLATFORM",
        "HERMES_SESSION_USER_ID",
        "HERMES_SESSION_CHAT_TYPE",
        "HERMES_SESSION_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    tools._attachments.clear()
    tools._confirmations.clear()
    tools._confirmation_callbacks.clear()
    yield tmp_path
    tools._attachments.clear()
    tools._confirmations.clear()
    tools._confirmation_callbacks.clear()


def _audio(tmp_path: Path, name: str = "sample.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(_wav_bytes())
    return path


def _handle(tmp_path: Path, *, session: str = "session-a", actor: str = "profile:local-owner") -> str:
    return tools.register_audio_attachment(
        _audio(tmp_path),
        session_id=session,
        actor=actor,
        profile=str(tmp_path),
    )["handle"]


def _confirm_create(tmp_path: Path, monkeypatch, *, visibility: str = "private") -> dict:
    handle = _handle(tmp_path)
    args = {
        "attachment_handle": handle,
        "alias": "My private voice",
        "consent_receipt": "I own this recording and consent to voice creation",
    }
    first = json.loads(tools.fishaudio_voice_create(args))
    phrase = first["confirmation_phrase"]
    monkeypatch.setenv("HERMES_SESSION_USER_TEXT", phrase)
    with patch.object(
        tools,
        "multipart_post",
        return_value=(201, {"_id": "voice-123", "visibility": visibility}),
    ) as request:
        result = json.loads(
            tools.fishaudio_voice_create({**args, "confirmation": phrase})
        )
    result["_request"] = request
    return result


def test_create_forces_private_and_persists_minimal_ledger(tmp_path, monkeypatch):
    result = _confirm_create(tmp_path, monkeypatch)

    assert result["success"] is True
    assert result["visibility"] == "private"
    assert result["refresh_voices"] is True
    fields = result["_request"].call_args.kwargs["fields"]
    assert fields["visibility"] == "private"
    assert fields["train_mode"] == "fast"
    ledger = json.loads(tools._ledger_path().read_text())
    assert ledger["version"] == 1
    assert set(ledger["voices"][0]) == {
        "voice_id",
        "alias",
        "actor",
        "source_digest",
        "created_at",
        "updated_at",
        "consent_receipt",
    }
    serialized = json.dumps(ledger)
    assert str(tmp_path) not in serialized
    assert "recording and consent" not in serialized
    assert "not-a-real-key" not in serialized


def test_create_rejects_provider_visibility_regression(tmp_path, monkeypatch):
    result = _confirm_create(tmp_path, monkeypatch, visibility="public")

    assert result["success"] is False
    assert "private visibility" in result["error"]
    assert tools._load_ledger()["voices"] == []


def test_create_api_error_is_redacted(tmp_path, monkeypatch):
    handle = _handle(tmp_path)
    args = {
        "attachment_handle": handle,
        "alias": "Voice",
        "consent_receipt": "consent receipt 123",
    }
    first = json.loads(tools.fishaudio_voice_create(args))
    phrase = first["confirmation_phrase"]
    monkeypatch.setenv("HERMES_SESSION_USER_TEXT", phrase)
    with patch.object(
        tools,
        "multipart_post",
        return_value=(401, {"message": "Authorization: Bearer not-a-real-key"}),
    ):
        result = json.loads(tools.fishaudio_voice_create({**args, "confirmation": phrase}))

    assert result["success"] is False
    assert "not-a-real-key" not in result["error"]


def test_attachment_rejects_raw_path_stale_cross_session_and_malformed(tmp_path):
    ctx = tools._context()
    with pytest.raises(ValueError, match="raw paths"):
        tools._resolve_attachment(str(_audio(tmp_path)), ctx)

    handle = _handle(tmp_path)
    with pytest.raises(PermissionError, match="another actor or session"):
        tools._resolve_attachment(handle, {**ctx, "session": "other"})
    with pytest.raises(PermissionError, match="another profile"):
        with patch.object(tools, "get_hermes_home", return_value=tmp_path / "other-profile"):
            tools._resolve_attachment(handle, ctx)

    tools._attachments[handle]["expires"] = 0
    with pytest.raises(ValueError, match="invalid or stale"):
        tools._resolve_attachment(handle, ctx)

    malformed = tmp_path / "bad.mp3"
    malformed.write_bytes(b"this is not audio")
    with pytest.raises(ValueError, match="malformed"):
        tools.register_audio_attachment(
            malformed,
            session_id="session-a",
            actor="profile:local-owner",
            profile=str(tmp_path),
        )


def test_attachment_rejects_symlink_and_oversize(tmp_path, monkeypatch):
    target = _audio(tmp_path)
    symlink = tmp_path / "linked.wav"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        tools.register_audio_attachment(
            symlink,
            session_id="session-a",
            actor="profile:local-owner",
            profile=str(tmp_path),
        )

    monkeypatch.setattr(tools, "MAX_AUDIO_BYTES", 8)
    with pytest.raises(ValueError, match="between"):
        tools.register_audio_attachment(
            target,
            session_id="session-a",
            actor="profile:local-owner",
            profile=str(tmp_path),
        )

    if Path("/dev/null").exists():
        with pytest.raises(ValueError, match="regular file"):
            tools.register_audio_attachment(
                Path("/dev/null"),
                session_id="session-a",
                actor="profile:local-owner",
                profile=str(tmp_path),
            )


def test_confirmation_expiry_replay_and_binding(monkeypatch):
    ctx = tools._context()
    phrase = tools._challenge("delete", ctx, "digest-a")
    monkeypatch.setenv("HERMES_SESSION_USER_TEXT", phrase)
    ctx = tools._context()

    with pytest.raises(PermissionError, match="not bound"):
        tools._consume_confirmation(
            phrase, action="delete", ctx=ctx, binding_digest="digest-b"
        )
    with pytest.raises(PermissionError, match="already used"):
        tools._consume_confirmation(
            phrase, action="delete", ctx=ctx, binding_digest="digest-a"
        )

    phrase = tools._challenge("delete", ctx, "digest-a")
    tools._confirmations[phrase]["expires"] = 0
    with pytest.raises(PermissionError, match="expired"):
        tools._consume_confirmation(
            phrase, action="delete", ctx=ctx, binding_digest="digest-a"
        )


def test_confirmation_must_be_typed_in_current_user_message(tmp_path):
    handle = _handle(tmp_path)
    args = {
        "attachment_handle": handle,
        "alias": "Voice",
        "consent_receipt": "consent receipt 123",
    }
    phrase = json.loads(tools.fishaudio_voice_create(args))["confirmation_phrase"]

    result = json.loads(tools.fishaudio_voice_create({**args, "confirmation": phrase}))
    assert result["success"] is False
    assert "Type the confirmation exactly" in result["error"]


def test_session_popup_confirmation_is_server_bound(tmp_path):
    handle = _handle(tmp_path)
    seen = {}

    def approve(payload):
        seen.update(payload)
        return {"approved": True, "confirmation": payload["confirmation"]}

    tools.register_confirmation_callback("session-a", approve)
    with patch.object(
        tools,
        "multipart_post",
        return_value=(201, {"_id": "voice-popup", "visibility": "private"}),
    ):
        result = json.loads(
            tools.fishaudio_voice_create(
                {"attachment_handle": handle, "alias": "Popup voice"}
            )
        )

    assert result["success"] is True
    assert seen["action"] == "create"
    assert seen["attachment_digest"]
    assert isinstance(seen["confirmation"], dict)
    assert seen["confirmation"]["token"].startswith("CONFIRM FISH VOICE CREATE ")
    ledger = tools._load_ledger()
    assert ledger["voices"][0]["consent_receipt"].startswith("sha256:")


def test_delete_uses_owned_id_and_leaves_minimal_tombstone(tmp_path, monkeypatch):
    created = _confirm_create(tmp_path, monkeypatch)
    assert created["success"]
    monkeypatch.setenv("HERMES_SESSION_USER_TEXT", "delete request")
    first = json.loads(tools.fishaudio_voice_delete({"voice": "My private voice"}))
    phrase = first["confirmation_phrase"]
    monkeypatch.setenv("HERMES_SESSION_USER_TEXT", phrase)
    with patch.object(tools, "request_json", return_value=(204, {})) as request:
        deleted = json.loads(
            tools.fishaudio_voice_delete(
                {"voice": "My private voice", "confirmation": phrase}
            )
        )

    assert deleted["deleted"] is True
    request.assert_called_once_with("DELETE", "model/voice-123")
    ledger = tools._load_ledger()
    assert ledger["voices"] == []
    assert set(ledger["tombstones"][0]) == {"voice_id", "actor", "deleted_at"}


def test_arbitrary_delete_id_never_reaches_provider(tmp_path):
    with patch.object(tools, "request_json") as request:
        result = json.loads(tools.fishaudio_voice_delete({"voice": "attacker-id"}))
    assert result["success"] is False
    assert "caller-owned catalog" in result["error"]
    request.assert_not_called()


def test_get_resolves_owned_alias_before_api_call(tmp_path, monkeypatch):
    assert _confirm_create(tmp_path, monkeypatch)["success"]
    with patch.object(
        tools,
        "request_json",
        return_value=(200, {"_id": "voice-123", "visibility": "private", "state": "trained"}),
    ) as request:
        result = json.loads(tools.fishaudio_voice_get({"voice": "My private voice"}))

    assert result["visibility"] == "private"
    assert result["state"] == "trained"
    request.assert_called_once_with("GET", "model/voice-123")


def test_set_default_resolves_owned_alias_and_signals_refresh(tmp_path, monkeypatch):
    assert _confirm_create(tmp_path, monkeypatch)["success"]
    result = json.loads(tools.fishaudio_voice_set_default({"voice": "My private voice"}))

    assert result["is_default"] is True
    assert result["refresh_voices"] is True
    config = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert config["tts"]["fishaudio"]["reference_id"] == "voice-123"


def test_gateway_owner_dm_allowed_but_group_and_other_actor_denied(tmp_path, monkeypatch):
    ledger = {
        "version": 1,
        "owner_actor": "",
        "voices": [
            {
                "voice_id": "voice-owned",
                "alias": "Owner voice",
                "actor": "profile:local-owner",
                "source_digest": "abc",
                "created_at": "now",
                "updated_at": "now",
                "consent_receipt": "sha256:abc",
            }
        ],
        "tombstones": [],
    }
    tools._save_ledger(ledger)
    monkeypatch.setenv("HERMES_SESSION_SOURCE", "")
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_TYPE", "dm")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "owner")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "owner,other-allowed")

    allowed = json.loads(tools.fishaudio_voice_list({}))
    assert allowed["voices"][0]["voice_id"] == "voice-owned"

    monkeypatch.setenv("HERMES_SESSION_CHAT_TYPE", "group")
    denied_group = json.loads(tools.fishaudio_voice_list({}))
    assert denied_group["success"] is False
    assert "direct message" in denied_group["error"]

    monkeypatch.setenv("HERMES_SESSION_CHAT_TYPE", "dm")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "other")
    denied_actor = json.loads(tools.fishaudio_voice_list({}))
    assert denied_actor["success"] is False
    assert "profile owner" in denied_actor["error"]


def test_gateway_voice_management_denied_without_configured_owner(monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_SOURCE", "")
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_TYPE", "dm")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "claimant")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)

    result = json.loads(tools.fishaudio_voice_list({}))

    assert result["success"] is False
    assert "configured gateway owner" in result["error"]


@pytest.mark.parametrize("platform", ["webhook", "api_server", "cron"])
def test_gateway_shared_or_automation_surfaces_denied(monkeypatch, platform):
    monkeypatch.setenv("HERMES_SESSION_SOURCE", "")
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", platform)
    monkeypatch.setenv("HERMES_SESSION_CHAT_TYPE", "dm")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "owner")
    result = json.loads(tools.fishaudio_voice_list({}))
    assert result["success"] is False
    assert "direct message" in result["error"]


def test_tui_file_upload_returns_scoped_fish_handle(tmp_path, monkeypatch):
    from tui_gateway import server

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = {"cwd": str(workspace), "session_key": "session-a"}
    monkeypatch.setattr(server, "_sess", lambda params, rid: (session, None))
    payload = base64.b64encode(_wav_bytes()).decode()

    response = server._methods["file.attach"](
        "r1",
        {
            "session_id": "session-a",
            "name": "authorized.wav",
            "data_url": f"data:audio/wav;base64,{payload}",
        },
    )

    handle = response["result"]["fishaudio_attachment_handle"]
    assert handle.startswith("fishatt_")
    assert tools._attachments[handle]["session"] == "session-a"
    assert tools._attachments[handle]["actor"] == "profile:local-owner"
    assert session["attached_fishaudio_handles"] == [handle]


def test_tui_confirmation_response_is_session_bound():
    from tui_gateway import server

    event = threading.Event()
    server._sessions["session-a"] = {"session_key": "session-a"}
    server._pending["request-a"] = ("session-a", event)
    try:
        response = server._methods["fishaudio.confirmation.respond"](
            "r1",
            {
                "approved": True,
                "confirmation": {"token": "opaque"},
                "request_id": "request-a",
                "session_id": "session-a",
            },
        )
        assert "result" in response
        assert server._answers["request-a"] == {
            "approved": True,
            "confirmation": {"token": "opaque"},
        }
        assert event.is_set()
    finally:
        server._pending.pop("request-a", None)
        server._answers.pop("request-a", None)
        server._sessions.pop("session-a", None)


@pytest.mark.asyncio
async def test_gateway_audio_message_surfaces_handle_without_fish_path(monkeypatch):
    from gateway.config import GatewayConfig, Platform
    from gateway.platforms.base import MessageEvent, MessageType
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource

    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(stt_enabled=False)
    runner.adapters = {}
    runner._model = "test"
    runner._base_url = ""
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="chat",
        chat_type="dm",
        user_id="owner",
    )
    event = MessageEvent(
        text="clone this voice",
        message_type=MessageType.AUDIO,
        source=source,
        media_urls=["/gateway/cache/voice.wav"],
        media_types=["audio/wav"],
    )
    monkeypatch.setattr(
        tools,
        "register_current_attachment",
        lambda path, session_id=None: {
            "handle": "fishatt_opaque",
            "digest": "abc",
            "expires_in": "1800",
        },
    )

    result = await runner._prepare_inbound_message_text(
        event=event,
        source=source,
        history=[],
    )

    assert "fishatt_opaque" in result
    assert "/gateway/cache/voice.wav" not in result
