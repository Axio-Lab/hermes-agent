"""Orphan preview GC for Fish Audio design artifacts."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from plugins.tts.fishaudio import tools


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with tools._lock:
        tools._previews.clear()
    yield


def test_orphan_preview_files_removed_on_gc(tmp_path):
    root = tools._preview_artifact_root()
    orphan = root / "orphan.wav"
    orphan.write_bytes(b"RIFF....WAVE")
    old = time.time() - tools.PREVIEW_TTL_SECONDS - 10
    # Force mtime into the past.
    import os

    os.utime(orphan, (old, old))

    live = root / "live.wav"
    live.write_bytes(b"RIFF....WAVE")
    tools._previews["fishpreview_live"] = {
        "artifact_path": str(live.resolve()),
        "expires": time.time() + 60,
    }

    removed = tools.gc_fishaudio_artifacts()
    assert removed >= 1
    assert not orphan.exists()
    assert live.exists()
