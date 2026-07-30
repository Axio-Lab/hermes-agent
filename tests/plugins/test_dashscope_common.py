"""Tests for shared DashScope credential resolution."""

from __future__ import annotations

import plugins._dashscope_common as dashscope_common


def test_api_key_from_process_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "process-key")
    assert dashscope_common.api_key() == "process-key"


def test_api_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=from-file\n", encoding="utf-8")
    assert dashscope_common.api_key() == "from-file"


def test_api_key_alias_dashscope_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_KEY", "alias-key")
    assert dashscope_common.api_key() == "alias-key"


def test_api_key_alias_bare_dashscope(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE", "bare-key")
    assert dashscope_common.api_key() == "bare-key"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE", raising=False)
    monkeypatch.setenv("HERMES_HOME", "/tmp/hermes-missing-dashscope")
    assert dashscope_common.api_key() == ""
