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


def test_cron_store_follows_tenant_home_override(tmp_path, monkeypatch):
    from cron import jobs as cron_jobs

    tenant_home = tmp_path / "tenant_c"
    token = set_hermes_home_override(str(tenant_home))
    try:
        assert cron_jobs._jobs_file() == tenant_home / "cron" / "jobs.json"
        cron_jobs.save_jobs([{"id": "j1", "name": "daily", "schedule": {"kind": "cron", "expr": "0 9 * * *"}}])
        assert (tenant_home / "cron" / "jobs.json").is_file()
        assert [j["id"] for j in cron_jobs.load_jobs()] == ["j1"]
    finally:
        reset_hermes_home_override(token)
    # Without the override the module-level path is untouched.
    assert cron_jobs._jobs_file() == cron_jobs.JOBS_FILE
    assert not (Path(cron_jobs.JOBS_FILE).exists() and "tenant_c" in str(cron_jobs.JOBS_FILE))


def test_verxio_cron_provider_publishes_tenant_jobs(tmp_path, monkeypatch):
    import importlib

    provider = importlib.import_module("plugins.cron.verxio")
    from agent.secret_scope import reset_secret_scope, set_secret_scope

    home = tmp_path / "tenant_d"
    (home / "cron").mkdir(parents=True)
    (home / "cron" / "jobs.json").write_text(
        '{"jobs": [{"id": "a", "name": "n", "schedule": {"kind": "interval", "minutes": 5}, "prompt": "hi", '
        '"deliver": "origin", "origin": {"platform": "telegram", "chat_id": "42"}, "secret_field": "x"}, '
        '{"id": "b", "name": "done", "state": "completed", "schedule": {"kind": "once", "run_at": "2020-01-01T00:00:00+00:00"}}]}'
    )
    posted: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, headers=None, timeout=None):
        posted.update({"url": url, "json": json, "headers": headers})
        return _Resp()

    monkeypatch.setattr(provider.httpx, "post", fake_post)
    monkeypatch.delenv("VERXIO_API_URL", raising=False)
    scope = set_secret_scope(
        {
            "VERXIO_API_URL": "http://api.test",
            "VERXIO_RUNTIME_TOKEN": "tok",
            "VERXIO_WORKSPACE_ID": "ws",
            "VERXIO_AGENT_ID": "ag",
        }
    )
    home_token = set_hermes_home_override(str(home))
    try:
        assert provider.VerxioCronScheduler().publish() is True
    finally:
        reset_hermes_home_override(home_token)
        reset_secret_scope(scope)
    assert posted["url"] == "http://api.test/api/runtime/cron"
    assert posted["headers"]["Authorization"] == "Bearer tok"
    assert posted["json"]["workspace_id"] == "ws" and posted["json"]["agent_id"] == "ag"
    jobs = posted["json"]["jobs"]
    assert [j["id"] for j in jobs] == ["a"]  # completed one-shots are not republished
    assert "secret_field" not in jobs[0]
    assert jobs[0]["origin"] == {"platform": "telegram", "chat_id": "42"}


def test_channel_shard_index_falls_back_to_pod_ordinal(monkeypatch):
    from gateway import verxio_channel_shard as shard

    monkeypatch.delenv("VERXIO_CHANNEL_SHARD", raising=False)
    monkeypatch.setenv("VERXIO_POD_NAME", "verxio-channel-gateway-3")
    assert shard.shard_index() == 3

    monkeypatch.setenv("VERXIO_CHANNEL_SHARD", "1")
    assert shard.shard_index() == 1

    monkeypatch.delenv("VERXIO_CHANNEL_SHARD", raising=False)
    monkeypatch.setenv("VERXIO_POD_NAME", "not-a-statefulset-pod")
    assert shard.shard_index() is None
