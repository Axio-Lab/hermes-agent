"""Consent-gated Fish Audio voice management tools.

The Fish API is deliberately kept behind a profile-local ownership catalog.
Model-supplied IDs and filesystem paths are never accepted.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from gateway.session_context import get_session_env
from hermes_constants import get_hermes_home
from plugins._fishaudio_common import api_key, error_message, multipart_post, request_json

TOOLSET = "fishaudio"
LEDGER_VERSION = 1
MAX_AUDIO_BYTES = 25 * 1024 * 1024
ATTACHMENT_TTL_SECONDS = 30 * 60
CONFIRMATION_TTL_SECONDS = 5 * 60
_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".ogg", ".opus", ".flac", ".m4a", ".mp4"})
_DENIED_GATEWAY_PLATFORMS = frozenset({"webhook", "api_server", "cron"})
_lock = threading.RLock()
_attachments: dict[str, dict[str, Any]] = {}
_confirmations: dict[str, dict[str, Any]] = {}
_confirmation_callbacks: dict[str, Callable[[dict[str, Any]], Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger_path() -> Path:
    return get_hermes_home() / "fishaudio" / "voice-ledger.v1.json"


def _empty_ledger() -> dict[str, Any]:
    return {"version": LEDGER_VERSION, "owner_actor": "", "voices": [], "tombstones": []}


def _load_ledger() -> dict[str, Any]:
    path = _ledger_path()
    with _lock:
        if not path.exists():
            return _empty_ledger()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise RuntimeError("Fish voice ownership ledger is unreadable")
        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION:
            raise RuntimeError("Unsupported Fish voice ownership ledger version")
        if not isinstance(data.get("voices"), list) or not isinstance(data.get("tombstones"), list):
            raise RuntimeError("Fish voice ownership ledger is malformed")
        return data


def _save_ledger(data: dict[str, Any]) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(f".tmp-{secrets.token_hex(4)}")
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with _lock:
        tmp.write_text(payload, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)


def _context() -> dict[str, str]:
    platform = get_session_env("HERMES_SESSION_PLATFORM", "").strip().lower()
    source = get_session_env("HERMES_SESSION_SOURCE", "").strip().lower()
    user_id = get_session_env("HERMES_SESSION_USER_ID", "").strip()
    session = (
        get_session_env("HERMES_SESSION_ID", "").strip()
        or get_session_env("HERMES_SESSION_KEY", "").strip()
    )
    chat_type = get_session_env("HERMES_SESSION_CHAT_TYPE", "").strip().lower()
    user_text = get_session_env("HERMES_SESSION_USER_TEXT", "")
    is_gateway = bool(platform and platform not in {"local", "cli", "tui"})
    actor = f"{platform}:{user_id}" if is_gateway else "profile:local-owner"
    if source == "tui":
        actor = "profile:local-owner"
    return {
        "platform": platform,
        "actor": actor,
        "session": session,
        "chat_type": chat_type,
        "user_text": user_text,
        "is_gateway": "1" if is_gateway else "",
        "user_id": user_id,
    }


def _authorize(*, require_owned_voice: bool = False) -> tuple[dict[str, str], dict[str, Any]]:
    ctx = _context()
    ledger = _load_ledger()
    if ctx["is_gateway"]:
        if (
            ctx["platform"] in _DENIED_GATEWAY_PLATFORMS
            or ctx["chat_type"] != "dm"
            or not ctx["user_id"]
        ):
            raise PermissionError("Fish voice management is allowed only in an authenticated owner direct message")
        owner = _configured_gateway_owner(ctx["platform"])
        if not owner:
            raise PermissionError(
                "Fish voice management requires a configured gateway owner"
            )
        if ctx["user_id"] != owner:
            raise PermissionError("Fish voice management is restricted to the profile owner")
    if not ctx["session"]:
        raise PermissionError("Fish voice management requires an active session")
    return ctx, ledger


def _configured_gateway_owner(platform: str) -> str:
    env_name = {
        "discord": "DISCORD_ALLOWED_USERS",
        "matrix": "MATRIX_ALLOWED_USERS",
        "mattermost": "MATTERMOST_ALLOWED_USERS",
        "signal": "SIGNAL_ALLOWED_USERS",
        "slack": "SLACK_ALLOWED_USERS",
        "telegram": "TELEGRAM_ALLOWED_USERS",
        "whatsapp": "WHATSAPP_ALLOWED_USERS",
    }.get(platform)
    if not env_name:
        return ""
    try:
        from hermes_cli.config import get_env_value

        raw = get_env_value(env_name) or ""
    except Exception:
        raw = os.environ.get(env_name, "")
    owners = [item.strip() for item in str(raw).split(",") if item.strip()]
    return owners[0] if owners else ""


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_audio(path: Path) -> tuple[str, int, str]:
    if path.is_symlink():
        raise ValueError("Audio attachment symlinks are not allowed")
    try:
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise ValueError("Audio attachment is no longer available") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Audio attachment must be a regular file")
    if resolved.suffix.lower() not in _AUDIO_SUFFIXES:
        raise ValueError("Unsupported audio attachment type")
    if info.st_size <= 0 or info.st_size > MAX_AUDIO_BYTES:
        raise ValueError(f"Audio attachment must be between 1 and {MAX_AUDIO_BYTES} bytes")
    with resolved.open("rb") as fh:
        header = fh.read(16)
    valid_magic = (
        (header.startswith(b"RIFF") and header[8:12] == b"WAVE")
        or header.startswith(b"ID3")
        or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)
        or header.startswith(b"OggS")
        or header.startswith(b"fLaC")
        or (len(header) >= 12 and header[4:8] == b"ftyp")
    )
    if not valid_magic:
        raise ValueError("Audio attachment is malformed or has unsupported encoding")
    return str(resolved), info.st_size, _digest_file(resolved)


def register_audio_attachment(
    path: str | Path,
    *,
    session_id: str,
    actor: str,
    profile: str = "",
) -> dict[str, str]:
    """Register a trusted inbound file and return an opaque, scoped handle."""
    if not session_id or not actor:
        raise ValueError("Attachment session and actor are required")
    resolved, size, digest = _validate_audio(Path(path))
    handle = f"fishatt_{secrets.token_urlsafe(24)}"
    with _lock:
        _prune_transient()
        _attachments[handle] = {
            "path": resolved,
            "size": size,
            "digest": digest,
            "session": session_id,
            "actor": actor,
            "profile": profile,
            "expires": time.time() + ATTACHMENT_TTL_SECONDS,
        }
    return {"handle": handle, "digest": digest, "expires_in": str(ATTACHMENT_TTL_SECONDS)}


def register_current_attachment(path: str | Path, *, session_id: str | None = None) -> dict[str, str]:
    ctx = _context()
    return register_audio_attachment(
        path,
        session_id=session_id or ctx["session"],
        actor=ctx["actor"],
        profile=str(get_hermes_home()),
    )


def _prune_transient() -> None:
    now = time.time()
    for mapping in (_attachments, _confirmations):
        for key, value in list(mapping.items()):
            if float(value.get("expires", 0)) <= now:
                mapping.pop(key, None)


def _resolve_attachment(handle: str, ctx: dict[str, str]) -> dict[str, Any]:
    if not handle.startswith("fishatt_") or "/" in handle or "\\" in handle or ".." in handle:
        raise ValueError("A valid audio attachment handle is required; raw paths are not accepted")
    with _lock:
        _prune_transient()
        entry = _attachments.get(handle)
        if not entry:
            raise ValueError("Audio attachment handle is invalid or stale")
        if entry["session"] != ctx["session"] or entry["actor"] != ctx["actor"]:
            raise PermissionError("Audio attachment belongs to another actor or session")
        if entry["profile"] != str(get_hermes_home()):
            raise PermissionError("Audio attachment belongs to another profile")
    resolved, size, digest = _validate_audio(Path(entry["path"]))
    if size != entry["size"] or digest != entry["digest"] or resolved != entry["path"]:
        raise ValueError("Audio attachment changed after authorization")
    return entry


def _read_attachment_bytes(entry: dict[str, Any]) -> bytes:
    """Read the authorized inode without following a last-second symlink."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(entry["path"], flags)
    except OSError as exc:
        raise ValueError("Audio attachment is no longer safely readable") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != entry["size"]:
            raise ValueError("Audio attachment changed after authorization")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_AUDIO_BYTES:
                raise ValueError("Audio attachment exceeds the size limit")
            chunks.append(chunk)
    finally:
        os.close(fd)
    content = b"".join(chunks)
    if hashlib.sha256(content).hexdigest() != entry["digest"]:
        raise ValueError("Audio attachment changed after authorization")
    return content


def _challenge(action: str, ctx: dict[str, str], binding_digest: str) -> str:
    token = secrets.token_hex(4).upper()
    phrase = f"CONFIRM FISH VOICE {action.upper()} {token}"
    with _lock:
        _prune_transient()
        _confirmations[phrase] = {
            "action": action,
            "actor": ctx["actor"],
            "session": ctx["session"],
            "digest": binding_digest,
            "expires": time.time() + CONFIRMATION_TTL_SECONDS,
        }
    return phrase


def _consume_confirmation(
    confirmation: str,
    *,
    action: str,
    ctx: dict[str, str],
    binding_digest: str,
    require_typed: bool = True,
) -> None:
    phrase = str(confirmation or "").strip()
    if not phrase:
        raise ValueError("confirmation required")
    with _lock:
        _prune_transient()
        pending = _confirmations.pop(phrase, None)
    if not pending:
        raise PermissionError("Confirmation is invalid, expired, or already used")
    if (
        pending["action"] != action
        or pending["actor"] != ctx["actor"]
        or pending["session"] != ctx["session"]
        or pending["digest"] != binding_digest
    ):
        raise PermissionError("Confirmation is not bound to this actor, session, attachment, and action")
    if require_typed and ctx["user_text"].strip() != phrase:
        raise PermissionError("Type the confirmation exactly in a new message from the same session")


def register_confirmation_callback(
    session_id: str, callback: Callable[[dict[str, Any]], Any]
) -> None:
    if session_id:
        with _lock:
            _confirmation_callbacks[session_id] = callback


def unregister_confirmation_callback(session_id: str) -> None:
    with _lock:
        _confirmation_callbacks.pop(session_id, None)


def _confirm_action(
    *,
    action: str,
    action_label: str,
    binding_digest: str,
    ctx: dict[str, str],
    attachment_digest: str = "",
    supplied_confirmation: str = "",
) -> str | None:
    phrase = _challenge(action, ctx, binding_digest)
    with _lock:
        callback = _confirmation_callbacks.get(ctx["session"])

    if callback is not None:
        expires_at = datetime.fromtimestamp(
            time.time() + CONFIRMATION_TTL_SECONDS, tz=timezone.utc
        ).isoformat()
        response = callback(
            {
                "action": action,
                "action_label": action_label,
                "attachment_digest": attachment_digest or None,
                "confirmation": {"token": phrase},
                "description": (
                    "Confirm that you are authorized to perform this private "
                    "Fish Audio voice operation."
                ),
                "expires_at": expires_at,
            }
        )
        approved = isinstance(response, dict) and response.get("approved") is True
        confirmation = response.get("confirmation") if isinstance(response, dict) else None
        token = confirmation.get("token") if isinstance(confirmation, dict) else ""
        if not approved:
            with _lock:
                _confirmations.pop(phrase, None)
            raise PermissionError("Fish voice operation was cancelled")
        _consume_confirmation(
            str(token or ""),
            action=action,
            ctx=ctx,
            binding_digest=binding_digest,
            require_typed=False,
        )
        return phrase

    if not supplied_confirmation:
        with _lock:
            _confirmations.pop(phrase, None)
        return None

    # The gateway path confirms in a later message. Discard this invocation's
    # fresh challenge and consume the earlier actor/session-bound phrase.
    with _lock:
        _confirmations.pop(phrase, None)
    _consume_confirmation(
        supplied_confirmation,
        action=action,
        ctx=ctx,
        binding_digest=binding_digest,
    )
    return supplied_confirmation


def _receipt_digest(receipt: str) -> str:
    clean = str(receipt or "").strip()
    if len(clean) < 8:
        raise ValueError("A consent receipt is required")
    return f"sha256:{hashlib.sha256(clean.encode('utf-8')).hexdigest()}"


def _voice_id(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return str(data.get("_id") or data.get("id") or "").strip()


def _visibility(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return str(data.get("visibility") or "").strip().lower()


def _owned_voice(ledger: dict[str, Any], selector: str) -> dict[str, Any]:
    clean = str(selector or "").strip()
    matches = [
        voice
        for voice in ledger["voices"]
        if clean in {str(voice.get("voice_id") or ""), str(voice.get("alias") or "")}
    ]
    if len(matches) != 1:
        raise ValueError("Voice was not found in the caller-owned catalog")
    return matches[0]


def _json_result(**values: Any) -> str:
    return json.dumps(values, ensure_ascii=False)


def _error(exc: Exception) -> str:
    return _json_result(success=False, error=str(exc), error_type=type(exc).__name__)


def fishaudio_voice_create(args: dict[str, Any], **_: Any) -> str:
    try:
        ctx, ledger = _authorize()
        alias = str(args.get("alias") or "").strip()
        if not alias or len(alias) > 80:
            raise ValueError("alias is required and must be at most 80 characters")
        attachment = _resolve_attachment(str(args.get("attachment_handle") or ""), ctx)
        binding = hashlib.sha256(
            f"{attachment['digest']}:{alias}".encode("utf-8")
        ).hexdigest()
        confirmation = str(args.get("confirmation") or "").strip()
        confirmed = _confirm_action(
            action="create",
            action_label=f"Create private voice “{alias}”",
            attachment_digest=attachment["digest"],
            binding_digest=binding,
            ctx=ctx,
            supplied_confirmation=confirmation,
        )
        if not confirmed:
            phrase = _challenge("create", ctx, binding)
            return _json_result(
                success=False,
                confirmation_required=True,
                confirmation_phrase=phrase,
                expires_in=CONFIRMATION_TTL_SECONDS,
            )
        receipt = _receipt_digest(confirmed)
        if not api_key():
            raise RuntimeError("FISH_AUDIO_API_KEY is not set")
        path = Path(attachment["path"])
        content = _read_attachment_bytes(attachment)
        status, payload = multipart_post(
            "model",
            fields={
                "title": alias,
                "visibility": "private",
                "type": "tts",
                "train_mode": "fast",
                "enhance_audio_quality": True,
            },
            files=[("voices", path.name, content, _audio_content_type(path))],
        )
        if status not in {200, 201}:
            raise RuntimeError(error_message(payload, f"Fish Audio create failed (HTTP {status})"))
        voice_id = _voice_id(payload)
        if not voice_id:
            raise RuntimeError("Fish Audio create response did not include a voice ID")
        if _visibility(payload) != "private":
            # Never catalog a provider response that violated the forced privacy contract.
            try:
                request_json("DELETE", f"model/{voice_id}")
            except Exception:
                pass
            raise RuntimeError("Fish Audio did not confirm private visibility; voice was not accepted")
        timestamp = _now()
        with _lock:
            # Reload under the write lock so concurrent voice operations do
            # not overwrite catalog entries created while the API call ran.
            ledger = _load_ledger()
            ledger["voices"].append(
                {
                    "voice_id": voice_id,
                    "alias": alias,
                    "actor": ctx["actor"],
                    "source_digest": attachment["digest"],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "consent_receipt": receipt,
                }
            )
            _save_ledger(ledger)
        with _lock:
            _attachments.pop(str(args.get("attachment_handle") or ""), None)
        return _json_result(
            success=True,
            voice_id=voice_id,
            alias=alias,
            visibility="private",
            refresh_voices=True,
            can_set_default=True,
        )
    except Exception as exc:
        return _error(exc)


def _audio_content_type(path: Path) -> str:
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
    }.get(path.suffix.lower(), "application/octet-stream")


def fishaudio_voice_list(args: dict[str, Any], **_: Any) -> str:
    try:
        ctx, ledger = _authorize()
        voices = [
            {
                "voice_id": voice["voice_id"],
                "alias": voice["alias"],
                "created_at": voice["created_at"],
                "updated_at": voice["updated_at"],
            }
            for voice in ledger["voices"]
        ]
        return _json_result(success=True, voices=voices, count=len(voices), refresh_voices=True)
    except Exception as exc:
        return _error(exc)


def fishaudio_voice_get(args: dict[str, Any], **_: Any) -> str:
    try:
        ctx, ledger = _authorize(require_owned_voice=True)
        owned = _owned_voice(ledger, str(args.get("voice") or ""))
        remote: dict[str, Any] = {}
        if api_key():
            status, payload = request_json("GET", f"model/{owned['voice_id']}")
            if status == 200:
                remote = {
                    "state": str(payload.get("state") or ""),
                    "visibility": _visibility(payload),
                }
        return _json_result(
            success=True,
            voice_id=owned["voice_id"],
            alias=owned["alias"],
            created_at=owned["created_at"],
            **remote,
        )
    except Exception as exc:
        return _error(exc)


def _write_default_voice(voice_id: str) -> None:
    path = get_hermes_home() / "config.yaml"
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, yaml.YAMLError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    tts = config.setdefault("tts", {})
    if not isinstance(tts, dict):
        tts = {}
        config["tts"] = tts
    fish = tts.setdefault("fishaudio", {})
    if not isinstance(fish, dict):
        fish = {}
        tts["fishaudio"] = fish
    fish["reference_id"] = voice_id
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{secrets.token_hex(4)}")
    tmp.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def fishaudio_voice_set_default(args: dict[str, Any], **_: Any) -> str:
    try:
        ctx, ledger = _authorize(require_owned_voice=True)
        owned = _owned_voice(ledger, str(args.get("voice") or ""))
        _write_default_voice(owned["voice_id"])
        return _json_result(
            success=True,
            voice_id=owned["voice_id"],
            alias=owned["alias"],
            is_default=True,
            refresh_voices=True,
        )
    except Exception as exc:
        return _error(exc)


def fishaudio_voice_delete(args: dict[str, Any], **_: Any) -> str:
    try:
        ctx, ledger = _authorize(require_owned_voice=True)
        owned = _owned_voice(ledger, str(args.get("voice") or ""))
        binding = hashlib.sha256(
            f"{owned['voice_id']}:{owned['actor']}:delete".encode("utf-8")
        ).hexdigest()
        confirmation = str(args.get("confirmation") or "").strip()
        confirmed = _confirm_action(
            action="delete",
            action_label=f"Delete private voice “{owned['alias']}”",
            binding_digest=binding,
            ctx=ctx,
            supplied_confirmation=confirmation,
        )
        if not confirmed:
            phrase = _challenge("delete", ctx, binding)
            return _json_result(
                success=False,
                confirmation_required=True,
                confirmation_phrase=phrase,
                expires_in=CONFIRMATION_TTL_SECONDS,
            )
        status, payload = request_json("DELETE", f"model/{owned['voice_id']}")
        if status not in {200, 202, 204}:
            raise RuntimeError(error_message(payload, f"Fish Audio delete failed (HTTP {status})"))
        with _lock:
            ledger = _load_ledger()
            ledger["voices"] = [
                voice
                for voice in ledger["voices"]
                if not (
                    voice.get("voice_id") == owned["voice_id"]
                    and voice.get("actor") == owned["actor"]
                )
            ]
            ledger["tombstones"].append(
                {
                    "voice_id": owned["voice_id"],
                    "actor": owned["actor"],
                    "deleted_at": _now(),
                }
            )
            _save_ledger(ledger)
        return _json_result(
            success=True,
            voice_id=owned["voice_id"],
            deleted=True,
            refresh_voices=True,
        )
    except Exception as exc:
        return _error(exc)


CREATE_SCHEMA = {
    "name": "fishaudio_voice_create",
    "description": "Create a private Fish Audio voice from an authorized audio attachment. Requires a second, typed confirmation.",
    "parameters": {
        "type": "object",
        "properties": {
            "attachment_handle": {"type": "string", "description": "Opaque fishatt_ handle supplied by Hermes for an uploaded audio file."},
            "alias": {"type": "string", "description": "Private display alias for the voice."},
            "confirmation": {"type": "string", "description": "Exact phrase the owner typed in a later message after the tool requested confirmation."},
        },
        "required": ["attachment_handle", "alias"],
    },
}
LIST_SCHEMA = {
    "name": "fishaudio_voice_list",
    "description": "List voices in the caller-owned, profile-scoped Fish catalog.",
    "parameters": {"type": "object", "properties": {}},
}
GET_SCHEMA = {
    "name": "fishaudio_voice_get",
    "description": "Get one caller-owned Fish voice by catalog alias or ID.",
    "parameters": {
        "type": "object",
        "properties": {"voice": {"type": "string", "description": "Owned catalog alias or voice ID."}},
        "required": ["voice"],
    },
}
SET_DEFAULT_SCHEMA = {
    "name": "fishaudio_voice_set_default",
    "description": "Set a caller-owned Fish voice as the profile's default TTS voice.",
    "parameters": {
        "type": "object",
        "properties": {"voice": {"type": "string", "description": "Owned catalog alias or voice ID."}},
        "required": ["voice"],
    },
}
DELETE_SCHEMA = {
    "name": "fishaudio_voice_delete",
    "description": "Delete a caller-owned Fish voice. Requires a second, typed confirmation.",
    "parameters": {
        "type": "object",
        "properties": {
            "voice": {"type": "string", "description": "Owned catalog alias or voice ID."},
            "confirmation": {"type": "string", "description": "Exact phrase the owner typed in a later message after the tool requested confirmation."},
        },
        "required": ["voice"],
    },
}

REGISTERED_TOOLS = (
    ("fishaudio_voice_create", CREATE_SCHEMA, fishaudio_voice_create, "🐟"),
    ("fishaudio_voice_list", LIST_SCHEMA, fishaudio_voice_list, "🐟"),
    ("fishaudio_voice_get", GET_SCHEMA, fishaudio_voice_get, "🐟"),
    ("fishaudio_voice_set_default", SET_DEFAULT_SCHEMA, fishaudio_voice_set_default, "🔊"),
    ("fishaudio_voice_delete", DELETE_SCHEMA, fishaudio_voice_delete, "🗑️"),
)
