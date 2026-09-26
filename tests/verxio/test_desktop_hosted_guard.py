"""Desktop Hermes must ignore VERXIO_HOSTED even if the env var leaks in."""

from hermes_cli.verxio_hosted_policy import hosted_mode


def test_desktop_disables_hosted_policy(monkeypatch):
    monkeypatch.setenv("VERXIO_HOSTED", "1")
    monkeypatch.setenv("VERXIO_DESKTOP", "1")
    assert hosted_mode() is False


def test_cloud_worker_stays_hosted(monkeypatch):
    monkeypatch.setenv("VERXIO_HOSTED", "1")
    monkeypatch.delenv("VERXIO_DESKTOP", raising=False)
    assert hosted_mode() is True
