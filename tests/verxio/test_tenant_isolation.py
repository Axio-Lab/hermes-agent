"""Isolation contracts for multiplexed Verxio tenants in one Hermes process."""

from __future__ import annotations

from pathlib import Path

from hermes_cli.dynamic_profiles import attach_profile, detach_profile, get_dynamic_home, list_dynamic_profiles
from hermes_cli.verxio_hosted_policy import apply_hosted_tool_policy, workspace_path_allowed
from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override


def test_dynamic_profiles_are_isolated(tmp_path):
    a = tmp_path / "tenant_a"
    b = tmp_path / "tenant_b"
    attach_profile("tenant_a", a)
    attach_profile("tenant_b", b)
    assert get_dynamic_home("tenant_a") == a.resolve()
    assert get_dynamic_home("tenant_b") == b.resolve()
    names = {name for name, _home in list_dynamic_profiles()}
    assert {"tenant_a", "tenant_b"} <= names
    token = set_hermes_home_override(str(a.resolve()))
    try:
        assert get_hermes_home() == a.resolve()
    finally:
        reset_hermes_home_override(token)
    token = set_hermes_home_override(str(b.resolve()))
    try:
        assert get_hermes_home() == b.resolve()
    finally:
        reset_hermes_home_override(token)
    assert detach_profile("tenant_a")
    assert get_dynamic_home("tenant_a") is None


def test_hosted_policy_forces_docker_backend(monkeypatch):
    monkeypatch.setenv("VERXIO_HOSTED", "1")
    monkeypatch.setenv("DOCKER_HOST", "tcp://sandbox:2376")
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    cfg = apply_hosted_tool_policy({"terminal": {"backend": "local"}})
    assert cfg["terminal"]["backend"] == "docker"
    assert cfg["terminal"]["docker"]["host"] == "tcp://sandbox:2376"
    assert workspace_path_allowed("/workspace/out.txt")
    assert not workspace_path_allowed("/tenants/other/secret")
