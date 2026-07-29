"""SSRF / redaction / bound checks for shared Fish HTTP helpers."""

from __future__ import annotations

import pytest

from plugins import _fishaudio_common as common


def test_rejects_http_url():
    with pytest.raises(ValueError, match="https"):
        common._validate_url("http://api.fish.audio/v1/tts")


def test_rejects_foreign_https_host():
    with pytest.raises(ValueError, match="not allowed"):
        common._validate_url("https://evil.example/v1/tts")


def test_redacts_api_key(monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "super-secret-key")
    text = common.redact_secret("Authorization: Bearer super-secret-key failed")
    assert "super-secret-key" not in text
    assert "redacted" in text.lower() or "<redacted>" in text


def test_json_response_bounded(monkeypatch):
    class FakeResp:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self, n=-1):
            return b"{" + (b"a" * (n if n > 0 else 10))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(common.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "k")
    # request_json surfaces oversize as a transport error tuple rather than raising.
    status, payload = common.request_json("GET", "model", max_bytes=16)
    assert status == 0
    assert "exceeded" in str(payload.get("message") or "").lower()
