"""Tests for Fish Audio append-only audit log."""

from __future__ import annotations

import json

import pytest

from plugins.tts.fishaudio import audit


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield


def test_writes_allowlisted_success_line():
    audit.audit_event(
        op="tts.synthesize",
        outcome="success",
        provider_op="tts",
        http_status=200,
        duration_ms=12,
        units=40,
        session_id="session-secret",
        actor="profile:local-owner",
    )
    path = audit.audit_path()
    assert path.is_file()
    line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = json.loads(line)
    assert set(payload) <= audit.ALLOWED_FIELDS
    assert payload["op"] == "tts.synthesize"
    assert "session_id_hash" in payload
    assert "session-secret" not in line
    assert "transcript" not in line
    assert "fishatt_" not in line


def test_disabled_audit_writes_nothing(monkeypatch):
    monkeypatch.setattr(audit, "audit_enabled", lambda: False)
    audit.audit_event(op="x", outcome="success", provider_op="tts")
    assert not audit.audit_path().exists()


def test_rotation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        audit,
        "_load_retention_config",
        lambda: {"audit_max_bytes": 80, "audit_rotate_keep": 2},
    )
    for index in range(20):
        audit.audit_event(
            op=f"tts.synthesize.{index}",
            outcome="success",
            provider_op="tts",
            units=index,
        )
    path = audit.audit_path()
    rotated = list(path.parent.glob("fishaudio-audit.jsonl*"))
    assert len(rotated) >= 2
