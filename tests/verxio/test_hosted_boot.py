"""Hosted dashboard boot must open :9119 in seconds, not minutes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "VERXIO_HOSTED",
        "HERMES_DASHBOARD_BACKGROUND_SKILLS_SYNC",
        "HERMES_PLUGINS_SKIP_ENTRY_POINTS",
        "HERMES_PLUGINS_SCAN_ENTRY_POINTS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_dashboard_defers_skills_sync_only_when_hosted(monkeypatch):
    from hermes_cli.main import _dashboard_defers_skills_sync

    assert _dashboard_defers_skills_sync() is False
    monkeypatch.setenv("VERXIO_HOSTED", "1")
    assert _dashboard_defers_skills_sync() is True
    # Explicit override wins in both directions.
    monkeypatch.setenv("HERMES_DASHBOARD_BACKGROUND_SKILLS_SYNC", "0")
    assert _dashboard_defers_skills_sync() is False
    monkeypatch.delenv("VERXIO_HOSTED")
    monkeypatch.setenv("HERMES_DASHBOARD_BACKGROUND_SKILLS_SYNC", "1")
    assert _dashboard_defers_skills_sync() is True


def test_entry_point_scan_skipped_in_hosted_runtime(monkeypatch):
    from hermes_cli import plugins as plugins_mod

    registry = plugins_mod.PluginManager()
    calls = {"n": 0}

    def fake_entry_points():
        calls["n"] += 1
        return []

    monkeypatch.setattr(plugins_mod.importlib.metadata, "entry_points", fake_entry_points)

    registry._scan_entry_points()
    assert calls["n"] == 1

    monkeypatch.setenv("VERXIO_HOSTED", "1")
    registry._scan_entry_points()
    assert calls["n"] == 1, "hosted runtimes must not parse every dist-info at boot"

    monkeypatch.setenv("HERMES_PLUGINS_SCAN_ENTRY_POINTS", "1")
    registry._scan_entry_points()
    assert calls["n"] == 2


def test_dockerfile_precompiles_bytecode_before_locking_tree():
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compile_idx = text.index("-m compileall")
    lock_idx = text.index("chmod -R a-w /opt/hermes")
    assert compile_idx < lock_idx, "bytecode must be written while /opt/hermes is still writable"
    assert "--invalidation-mode unchecked-hash" in text
    assert re.search(r"compileall[^\n]*\\\n[^\n]*\n[^\n]*\n\s+/opt/hermes/\.venv/lib /opt/hermes", text)
