"""Cross-process MCP reload signal (dashboard → messaging gateway)."""

from pathlib import Path

from tools.mcp_reload_signal import (
    consume_gateway_mcp_reload_request,
    mcp_reload_request_path,
    request_gateway_mcp_reload,
)


def test_request_and_consume_gateway_mcp_reload(tmp_path: Path):
    marker = mcp_reload_request_path(tmp_path)
    assert not marker.exists()
    assert consume_gateway_mcp_reload_request(tmp_path) is False

    written = request_gateway_mcp_reload(tmp_path)
    assert written == marker
    assert marker.is_file()
    assert marker.read_text(encoding="utf-8").strip()

    assert consume_gateway_mcp_reload_request(tmp_path) is True
    assert not marker.exists()
    assert consume_gateway_mcp_reload_request(tmp_path) is False


def test_consume_returns_false_when_marker_already_gone(tmp_path: Path, monkeypatch):
    request_gateway_mcp_reload(tmp_path)
    marker = mcp_reload_request_path(tmp_path)

    def missing_unlink(self, *args, **kwargs):
        if self == marker:
            raise FileNotFoundError(str(self))
        raise AssertionError(f"unexpected unlink: {self}")

    monkeypatch.setattr(Path, "unlink", missing_unlink)
    assert consume_gateway_mcp_reload_request(tmp_path) is False
