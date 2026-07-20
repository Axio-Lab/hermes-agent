"""Unit tests for the Verxio Notepad bridge tool."""

from __future__ import annotations

import json

import pytest

from tools import notepad_tool


def test_check_notepad_requirements(monkeypatch):
    monkeypatch.delenv("VERXIO_API_URL", raising=False)
    monkeypatch.delenv("VERXIO_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("HERMES_DASHBOARD_SESSION_TOKEN", raising=False)
    assert notepad_tool.check_notepad_requirements() is False

    monkeypatch.setenv("VERXIO_API_URL", "http://verxio-api:8787")
    monkeypatch.setenv("VERXIO_RUNTIME_TOKEN", "secret")
    assert notepad_tool.check_notepad_requirements() is True


def test_notepad_list_and_share(monkeypatch):
    monkeypatch.setenv("VERXIO_API_URL", "http://verxio-api:8787")
    monkeypatch.setenv("VERXIO_RUNTIME_TOKEN", "secret")
    monkeypatch.setenv("VERXIO_PUBLIC_WEB_URL", "http://127.0.0.1:8080")

    calls: list[tuple[str, str]] = []

    def fake_request(method, path, *, body=None, timeout=60.0):
        calls.append((method, path))
        if method == "GET" and path == "/api/notepad":
            return {
                "ok": True,
                "folders": [{"id": "folder_1", "name": "Work", "sort_order": 0}],
                "notes": [
                    {
                        "id": "note_1",
                        "title": "Standup",
                        "folder_id": "folder_1",
                        "meeting_type": "general",
                        "updated_at": "2026-07-20T00:00:00Z",
                        "summary": "Done.",
                        "share_token": "np_abc",
                        "content": "full body",
                    }
                ],
            }
        if method == "POST" and path.endswith("/share"):
            return {
                "token": "np_abc",
                "url": "http://127.0.0.1:8080/share/notepad/np_abc",
                "note": {"id": "note_1", "title": "Standup"},
            }
        return {"ok": False, "error": f"unexpected {method} {path}"}

    monkeypatch.setattr(notepad_tool, "_request", fake_request)

    listed = json.loads(notepad_tool._handle_notepad({"action": "list"}))
    assert listed["ok"] is True
    assert listed["count"] == 1
    assert listed["notes"][0]["share_url"] == "http://127.0.0.1:8080/share/notepad/np_abc"

    got = json.loads(notepad_tool._handle_notepad({"action": "get", "note_id": "note_1"}))
    assert got["ok"] is True
    assert got["note"]["content"] == "full body"

    shared = json.loads(notepad_tool._handle_notepad({"action": "share", "note_id": "note_1"}))
    assert shared["ok"] is True
    assert "share/notepad/np_abc" in shared["share_url"]
    assert ("POST", "/api/notepad/notes/note_1/share") in calls


def test_notepad_create_requires_config(monkeypatch):
    monkeypatch.delenv("VERXIO_API_URL", raising=False)
    monkeypatch.delenv("VERXIO_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("HERMES_DASHBOARD_SESSION_TOKEN", raising=False)
    result = json.loads(
        notepad_tool._handle_notepad({"action": "create", "title": "Hi", "content": "Body"})
    )
    assert result["ok"] is False
    assert result["error_type"] == "not_configured"
