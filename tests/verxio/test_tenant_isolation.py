"""Isolation contracts for multiplexed Verxio tenants in one Hermes process."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_hosted_policy_forces_docker_backend(monkeypatch, tmp_path):
    certs = tmp_path / "certs"
    certs.mkdir()
    for name in ("ca.pem", "cert.pem", "key.pem"):
        (certs / name).write_text("x")
    monkeypatch.setenv("VERXIO_HOSTED", "1")
    monkeypatch.setenv("DOCKER_HOST", "tcp://sandbox:2376")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setenv("DOCKER_CERT_PATH", str(certs))
    monkeypatch.delenv("VERXIO_REMOTE_EXEC", raising=False)
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    cfg = apply_hosted_tool_policy({"terminal": {"backend": "local", "docker": {"mount_cwd": True}}})
    assert cfg["terminal"]["backend"] == "docker"
    assert cfg["terminal"]["docker"]["host"] == "tcp://sandbox:2376"
    assert cfg["terminal"]["docker"]["tls_verify"] is True
    assert cfg["terminal"]["docker"]["mount_cwd"] is False
    assert cfg["terminal"]["docker"]["volumes"] == []
    assert cfg["terminal"]["container_persistent"] is False
    assert workspace_path_allowed("/workspace/out.txt")
    assert not workspace_path_allowed("/tenants/other/secret")


def test_hosted_policy_rejects_local_socket_and_plaintext(monkeypatch):
    from hermes_cli.verxio_hosted_policy import SandboxPolicyError

    monkeypatch.setenv("VERXIO_HOSTED", "1")
    monkeypatch.delenv("VERXIO_REMOTE_EXEC", raising=False)
    monkeypatch.delenv("VERXIO_SANDBOX_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    with pytest.raises(SandboxPolicyError):
        apply_hosted_tool_policy({})
    monkeypatch.setenv("DOCKER_HOST", "tcp://sandbox:2375")
    monkeypatch.delenv("DOCKER_TLS_VERIFY", raising=False)
    with pytest.raises(SandboxPolicyError):
        apply_hosted_tool_policy({})
    monkeypatch.setenv("VERXIO_SANDBOX_ALLOW_INSECURE", "1")
    cfg = apply_hosted_tool_policy({})
    assert cfg["terminal"]["docker"]["tls_verify"] is False
    # Channel shards enqueue turns remotely and skip the daemon check.
    monkeypatch.delenv("VERXIO_SANDBOX_ALLOW_INSECURE", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setenv("VERXIO_REMOTE_EXEC", "1")
    assert apply_hosted_tool_policy({})["terminal"]["backend"] == "docker"


def test_sandbox_environment_workspace_mirror(tmp_path):
    from tools.environments.verxio_sandbox import _WorkspaceMirror, tenant_workspace_dir
    from agent.secret_scope import set_secret_scope

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "a.txt").write_text("1")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "big.js").write_text("skip")
    mirror = _WorkspaceMirror(ws)
    changed, removed = mirror.diff()
    assert changed == ["a.txt"] and removed == []
    (ws / "a.txt").unlink()
    (ws / "b.txt").write_text("2")
    changed, removed = mirror.diff()
    assert changed == ["b.txt"] and removed == ["a.txt"]

    token = set_secret_scope({"VERXIO_WORKSPACE_DIR": str(ws)})
    try:
        assert tenant_workspace_dir() == ws
    finally:
        from agent.secret_scope import reset_secret_scope

        reset_secret_scope(token)
