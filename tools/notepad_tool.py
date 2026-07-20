"""Verxio Notepad bridge — list/read/create/update notes and public share URLs.

Hosted Verxio runtimes call verxio-api with ``VERXIO_RUNTIME_TOKEN`` (Bearer).
This makes the same Notepad the web UI uses available from Telegram/Slack/
WhatsApp and the web chat agent.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _api_base() -> str:
    return (os.environ.get("VERXIO_API_URL") or "").strip().rstrip("/")


def _runtime_token() -> str:
    return (
        os.environ.get("VERXIO_RUNTIME_TOKEN")
        or os.environ.get("HERMES_DASHBOARD_SESSION_TOKEN")
        or ""
    ).strip()


def check_notepad_requirements() -> bool:
    return bool(_api_base() and _runtime_token())


def _request(
    method: str,
    path: str,
    *,
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    base = _api_base()
    token = _runtime_token()
    if not base or not token:
        return {
            "ok": False,
            "error": (
                "Verxio Notepad is not configured in this runtime. "
                "Restart the Verxio agent runtime so VERXIO_API_URL and "
                "VERXIO_RUNTIME_TOKEN are injected."
            ),
            "error_type": "not_configured",
        }

    url = f"{base}{path}"
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw.strip() else {}
            if isinstance(payload, dict):
                payload.setdefault("ok", True)
                return payload
            return {"ok": True, "data": payload}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
            parsed = json.loads(detail)
            if isinstance(parsed, dict) and parsed.get("detail"):
                detail = str(parsed["detail"])
        except Exception:
            detail = detail or str(exc)
        return {
            "ok": False,
            "error": detail or f"HTTP {exc.code}",
            "error_type": "http_error",
            "status": exc.code,
        }
    except Exception as exc:
        logger.warning("notepad API call failed: %s", exc)
        return {
            "ok": False,
            "error": str(exc),
            "error_type": "request_failed",
        }


def _note_summary_row(note: Dict[str, Any]) -> Dict[str, Any]:
    token = note.get("share_token")
    public_base = (os.environ.get("VERXIO_PUBLIC_WEB_URL") or "").strip().rstrip("/")
    share_url = None
    if token and public_base:
        share_url = f"{public_base}/share/notepad/{token}"
    elif token:
        # API share endpoint returns the canonical URL; list rows only have token.
        share_url = f"/share/notepad/{token}"
    return {
        "id": note.get("id"),
        "title": note.get("title"),
        "folder_id": note.get("folder_id"),
        "meeting_type": note.get("meeting_type"),
        "updated_at": note.get("updated_at"),
        "has_summary": bool((note.get("summary") or "").strip()),
        "share_token": token,
        "share_url": share_url,
    }


def _handle_notepad(args: Dict[str, Any], **_kw: Any) -> str:
    action = str(args.get("action") or "").strip().lower()
    note_id = str(args.get("note_id") or "").strip()
    folder_id = args.get("folder_id")
    folder_id = str(folder_id).strip() if folder_id not in (None, "") else None

    if action == "list":
        result = _request("GET", "/api/notepad")
        if not result.get("ok", True) and result.get("error"):
            return json.dumps(result, ensure_ascii=False)
        notes = result.get("notes") or []
        folders = result.get("folders") or []
        return json.dumps(
            {
                "ok": True,
                "folders": [
                    {
                        "id": f.get("id"),
                        "name": f.get("name"),
                        "sort_order": f.get("sort_order"),
                    }
                    for f in folders
                    if isinstance(f, dict)
                ],
                "notes": [
                    _note_summary_row(n) for n in notes if isinstance(n, dict)
                ],
                "count": len(notes),
            },
            ensure_ascii=False,
        )

    if action == "get":
        if not note_id:
            return json.dumps(
                {"ok": False, "error": "note_id is required for get"},
                ensure_ascii=False,
            )
        listing = _request("GET", "/api/notepad")
        if listing.get("error") and not listing.get("ok", True):
            return json.dumps(listing, ensure_ascii=False)
        for note in listing.get("notes") or []:
            if isinstance(note, dict) and note.get("id") == note_id:
                row = dict(note)
                summary = _note_summary_row(note)
                if summary.get("share_url"):
                    row["share_url"] = summary["share_url"]
                return json.dumps({"ok": True, "note": row}, ensure_ascii=False)
        return json.dumps(
            {"ok": False, "error": f"Note not found: {note_id}", "error_type": "not_found"},
            ensure_ascii=False,
        )

    if action == "create":
        body: Dict[str, Any] = {
            "title": str(args.get("title") or "Untitled note").strip() or "Untitled note",
            "content": str(args.get("content") or ""),
            "transcript": str(args.get("transcript") or ""),
            "summary": str(args.get("summary") or ""),
            "meeting_type": str(args.get("meeting_type") or "general"),
            "source": str(args.get("source") or "agent"),
        }
        if folder_id:
            body["folder_id"] = folder_id
        result = _request("POST", "/api/notepad/notes", body=body)
        return json.dumps(result, ensure_ascii=False)

    if action == "update":
        if not note_id:
            return json.dumps(
                {"ok": False, "error": "note_id is required for update"},
                ensure_ascii=False,
            )
        body = {}
        for key in ("title", "content", "transcript", "summary", "meeting_type", "source"):
            if key in args and args[key] is not None:
                body[key] = args[key]
        if "folder_id" in args:
            body["folder_id"] = folder_id
        if not body:
            return json.dumps(
                {"ok": False, "error": "Provide at least one field to update"},
                ensure_ascii=False,
            )
        result = _request(
            "PATCH",
            f"/api/notepad/notes/{quote(note_id, safe='')}",
            body=body,
        )
        return json.dumps(result, ensure_ascii=False)

    if action == "share":
        if not note_id:
            return json.dumps(
                {"ok": False, "error": "note_id is required for share"},
                ensure_ascii=False,
            )
        result = _request(
            "POST",
            f"/api/notepad/notes/{quote(note_id, safe='')}/share",
        )
        if result.get("url"):
            result["share_url"] = result["url"]
            result["ok"] = True
            result["message"] = (
                f"Public summary URL: {result['url']}. "
                "Anyone with this link can view the shared note summary."
            )
        return json.dumps(result, ensure_ascii=False)

    if action == "revoke_share":
        if not note_id:
            return json.dumps(
                {"ok": False, "error": "note_id is required for revoke_share"},
                ensure_ascii=False,
            )
        result = _request(
            "DELETE",
            f"/api/notepad/notes/{quote(note_id, safe='')}/share",
        )
        return json.dumps(result, ensure_ascii=False)

    if action == "summarize":
        if not note_id:
            return json.dumps(
                {"ok": False, "error": "note_id is required for summarize"},
                ensure_ascii=False,
            )
        result = _request(
            "POST",
            f"/api/notepad/notes/{quote(note_id, safe='')}/summarize",
            timeout=300.0,
        )
        return json.dumps(result, ensure_ascii=False)

    return json.dumps(
        {
            "ok": False,
            "error": (
                "Unknown action. Use list, get, create, update, share, "
                "revoke_share, or summarize."
            ),
        },
        ensure_ascii=False,
    )


NOTEPAD_SCHEMA = {
    "name": "notepad",
    "description": (
        "Access the user's Verxio Notepad (same notes as Verxio Web → Notepad). "
        "Use this from chat or messaging (Telegram/Slack/WhatsApp) to list notes, "
        "read a note, create/update notes, generate a summary, or create a public "
        "summary share URL. Prefer this over inventing local .md files when the "
        "user asks about their notepad or notes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list",
                    "get",
                    "create",
                    "update",
                    "share",
                    "revoke_share",
                    "summarize",
                ],
                "description": (
                    "list: all folders + note titles; get: full note by note_id; "
                    "create/update: write note fields; share: public summary URL; "
                    "revoke_share: disable the public link; summarize: regenerate summary."
                ),
            },
            "note_id": {
                "type": "string",
                "description": "Required for get, update, share, revoke_share, summarize.",
            },
            "folder_id": {
                "type": "string",
                "description": "Optional folder id when creating/updating a note.",
            },
            "title": {"type": "string", "description": "Note title (create/update)."},
            "content": {
                "type": "string",
                "description": "Written note body / markdown (create/update).",
            },
            "transcript": {
                "type": "string",
                "description": "Optional meeting transcript text (create/update).",
            },
            "summary": {
                "type": "string",
                "description": "Optional summary markdown (create/update).",
            },
            "meeting_type": {
                "type": "string",
                "description": "Optional label such as general, standup, interview.",
            },
            "source": {
                "type": "string",
                "description": "Optional source tag (default agent).",
            },
        },
        "required": ["action"],
    },
}

from tools.registry import registry  # noqa: E402

registry.register(
    name="notepad",
    toolset="notepad",
    schema=NOTEPAD_SCHEMA,
    handler=_handle_notepad,
    check_fn=check_notepad_requirements,
    emoji="📝",
)
