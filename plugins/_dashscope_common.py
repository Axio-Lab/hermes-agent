"""Shared DashScope REST helpers for media plugins (image / video / TTS).

Uses urllib only — no ``dashscope`` SDK dependency in the Hermes runtime.
Intl base URL matches Qwen Cloud / Hermes Alibaba provider config.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
ENV_API_KEY = "DASHSCOPE_API_KEY"
ENV_BASE_URL = "DASHSCOPE_BASE_URL"


def api_key() -> str:
    return (os.environ.get(ENV_API_KEY) or "").strip()


def base_url() -> str:
    raw = (os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL).strip().rstrip("/")
    return raw or DEFAULT_BASE_URL


def request_json(
    method: str,
    path: str,
    *,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 120.0,
    key: Optional[str] = None,
) -> Tuple[int, Dict[str, Any]]:
    """HTTP JSON request against the DashScope native API.

    ``path`` may be absolute (``https://...``) or relative to :func:`base_url`.
    Returns ``(status_code, parsed_json)``. On HTTP errors with a JSON body,
    returns that status and body instead of raising.
    """
    token = (key or api_key()).strip()
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = f"{base_url().rstrip('/')}/{path.lstrip('/')}"

    req_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "hermes-agent-dashscope/1.0",
    }
    if headers:
        req_headers.update(headers)

    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"message": raw[:2000], "code": f"http_{exc.code}"}
        if not isinstance(payload, dict):
            payload = {"message": str(payload)}
        return exc.code, payload
    except Exception as exc:  # noqa: BLE001 — surface as transport error
        logger.debug("DashScope request failed: %s %s", method, url, exc_info=True)
        return 0, {"message": str(exc), "code": "transport_error"}


def poll_task(
    task_id: str,
    *,
    key: Optional[str] = None,
    timeout_seconds: float = 300.0,
    poll_interval: float = 4.0,
) -> Dict[str, Any]:
    """Poll ``GET /tasks/{task_id}`` until terminal status or timeout."""
    deadline = time.time() + timeout_seconds
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        status_code, payload = request_json(
            "GET",
            f"tasks/{task_id}",
            key=key,
            timeout=30.0,
        )
        last = payload if isinstance(payload, dict) else {"raw": payload}
        output = last.get("output") if isinstance(last.get("output"), dict) else {}
        task_status = output.get("task_status") or last.get("task_status")
        if status_code and status_code >= 400 and not task_status:
            return {
                "ok": False,
                "status": "failed",
                "http_status": status_code,
                "body": last,
            }
        if task_status in ("SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"):
            return {
                "ok": task_status == "SUCCEEDED",
                "status": str(task_status).lower(),
                "http_status": status_code,
                "body": last,
            }
        time.sleep(poll_interval)
    return {
        "ok": False,
        "status": "timeout",
        "http_status": 0,
        "body": last,
    }


def error_message(payload: Dict[str, Any], fallback: str = "DashScope request failed") -> str:
    if not isinstance(payload, dict):
        return fallback
    message = payload.get("message") or payload.get("error")
    code = payload.get("code")
    if message and code:
        return f"{code}: {message}"
    if message:
        return str(message)
    if code:
        return str(code)
    return fallback
