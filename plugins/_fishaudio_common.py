"""Shared Fish Audio REST helpers for TTS / voice / ASR plugins.

Uses urllib only. The API host is fixed to Fish Audio's production endpoint
to avoid SSRF from model-supplied base URLs.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.fish.audio"
ALLOWED_API_HOSTS = frozenset({"api.fish.audio"})
ENV_API_KEY = "FISH_AUDIO_API_KEY"
ENV_API_KEY_ALIASES = ("FISH_AUDIO_API_KEY", "FISH_API_KEY")
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_ERROR_BODY_CHARS = 400
_SECRET_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|bearer|token)\s*[:=]\s*([^\s,\"']+)"
)


def api_key() -> str:
    # Runtime startup normally loads profile credentials into the process
    # environment, so keep the common path dependency-free.
    for name in ENV_API_KEY_ALIASES:
        value = os.environ.get(name)
        if value and str(value).strip():
            return str(value).strip()

    # Long-running gateway workers may receive a credential update without a
    # process restart. get_env_value uses the mtime-cached profile .env parser,
    # so it is safe and cheap here and lets those workers observe the new key.
    try:
        from hermes_cli.config import get_env_value

        for name in ENV_API_KEY_ALIASES:
            value = get_env_value(name)
            if value and str(value).strip():
                return str(value).strip()
    except Exception:
        pass
    return ""


def api_base() -> str:
    """Return the fixed Fish Audio API origin.

    Config/env overrides are intentionally ignored so tool/model input cannot
    redirect requests to attacker-controlled hosts.
    """
    return DEFAULT_API_BASE


def redact_secret(text: str) -> str:
    if not text:
        return text
    redacted = _SECRET_RE.sub(r"\1=<redacted>", text)
    key = api_key()
    if key and key in redacted:
        redacted = redacted.replace(key, "<redacted>")
    return redacted


def error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "detail", "error", "msg"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return redact_secret(value.strip())[:MAX_ERROR_BODY_CHARS]
            if isinstance(value, dict):
                nested = value.get("message") or value.get("detail")
                if isinstance(nested, str) and nested.strip():
                    return redact_secret(nested.strip())[:MAX_ERROR_BODY_CHARS]
    if isinstance(payload, str) and payload.strip():
        return redact_secret(payload.strip())[:MAX_ERROR_BODY_CHARS]
    return fallback


def _validate_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Fish Audio requests must use https")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_API_HOSTS:
        raise ValueError(f"Fish Audio host not allowed: {host or '<missing>'}")
    return url


def request_json(
    method: str,
    path: str,
    *,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    query: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    key: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> Tuple[int, Dict[str, Any]]:
    """HTTP JSON request against the Fish Audio API.

    Returns ``(status_code, parsed_json)``. HTTP errors with a JSON body
    return that status and body instead of raising.
    """
    token = (key or api_key()).strip()
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = f"{api_base().rstrip('/')}/{path.lstrip('/')}"

    if query:
        filtered = {
            k: ("true" if v is True else "false" if v is False else v)
            for k, v in query.items()
            if v is not None
        }
        url = f"{url}?{urllib.parse.urlencode(filtered, doseq=True)}"

    url = _validate_url(url)
    req_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "hermes-agent-fishaudio/1.0",
    }
    data = None
    if body is not None:
        req_headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if headers:
        # Never allow callers to override Authorization or Host.
        safe = {
            k: v
            for k, v in headers.items()
            if k.lower() not in {"authorization", "host"}
        }
        req_headers.update(safe)

    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            chunks: List[bytes] = []
            total = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(
                        f"Fish Audio JSON response exceeded {max_bytes} bytes"
                    )
                chunks.append(chunk)
            raw = b"".join(chunks).decode("utf-8") or "{}"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"message": raw[:2000]}
            if not isinstance(payload, dict):
                payload = {"data": payload}
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read(64 * 1024).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"message": raw[:2000], "code": f"http_{exc.code}"}
        if not isinstance(payload, dict):
            payload = {"message": str(payload)}
        return exc.code, payload
    except Exception as exc:  # noqa: BLE001 — surface as transport error
        logger.debug("Fish Audio request failed: %s %s", method, url, exc_info=True)
        return 0, {"message": redact_secret(str(exc)), "code": "transport_error"}


def request_bytes(
    method: str,
    path: str,
    *,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    key: Optional[str] = None,
    max_bytes: int = 25 * 1024 * 1024,
) -> Tuple[int, bytes, Dict[str, str]]:
    """HTTP request that returns raw response bytes (used by TTS)."""
    token = (key or api_key()).strip()
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = f"{api_base().rstrip('/')}/{path.lstrip('/')}"
    url = _validate_url(url)

    req_headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "hermes-agent-fishaudio/1.0",
    }
    data = None
    if body is not None:
        req_headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if headers:
        safe = {
            k: v
            for k, v in headers.items()
            if k.lower() not in {"authorization", "host"}
        }
        req_headers.update(safe)

    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            chunks: List[bytes] = []
            total = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(
                        f"Fish Audio response exceeded {max_bytes} bytes"
                    )
                chunks.append(chunk)
            return resp.status, b"".join(chunks), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, raw, dict(exc.headers.items()) if exc.headers else {}


def multipart_post(
    path: str,
    *,
    fields: Dict[str, Any],
    files: List[Tuple[str, str, bytes, str]],
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    key: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> Tuple[int, Dict[str, Any]]:
    """POST multipart/form-data to Fish Audio.

    ``files`` entries are ``(field_name, filename, content, content_type)``.
    """
    import uuid

    token = (key or api_key()).strip()
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = f"{api_base().rstrip('/')}/{path.lstrip('/')}"
    url = _validate_url(url)

    boundary = f"----HermesFishBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(rendered.encode("utf-8"))
        body.extend(b"\r\n")

    for field_name, filename, content, content_type in files:
        guessed = (
            content_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        body.extend(f"Content-Type: {guessed}\r\n\r\n".encode())
        body.extend(content)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode())

    req_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
        "User-Agent": "hermes-agent-fishaudio/1.0",
    }
    if headers:
        safe = {
            k: v
            for k, v in headers.items()
            if k.lower() not in {"authorization", "host", "content-type"}
        }
        req_headers.update(safe)

    request = urllib.request.Request(
        url, data=bytes(body), headers=req_headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw_bytes = resp.read(max_bytes + 1)
            if len(raw_bytes) > max_bytes:
                raise RuntimeError(
                    f"Fish Audio JSON response exceeded {max_bytes} bytes"
                )
            raw = raw_bytes.decode("utf-8") or "{}"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"message": raw[:2000]}
            if not isinstance(payload, dict):
                payload = {"data": payload}
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read(64 * 1024).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"message": raw[:2000], "code": f"http_{exc.code}"}
        if not isinstance(payload, dict):
            payload = {"message": str(payload)}
        return exc.code, payload
    except Exception as exc:  # noqa: BLE001
        logger.debug("Fish Audio multipart failed: %s", url, exc_info=True)
        return 0, {"message": redact_secret(str(exc)), "code": "transport_error"}
