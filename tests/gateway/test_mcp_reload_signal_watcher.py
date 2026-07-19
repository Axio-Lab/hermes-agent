"""Gateway watcher applies dashboard MCP reload signals."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from gateway.run import GatewayRunner
from tools.mcp_reload_signal import request_gateway_mcp_reload


@pytest.mark.asyncio
async def test_mcp_reload_signal_watcher_executes_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = GatewayRunner.__new__(GatewayRunner)
    runner._running = True
    runner._execute_mcp_reload = AsyncMock(return_value="reloaded")

    request_gateway_mcp_reload(tmp_path)

    async def stop_soon():
        await asyncio.sleep(0.05)
        runner._running = False

    await asyncio.gather(
        runner._mcp_reload_signal_watcher(interval=0.01),
        stop_soon(),
    )

    runner._execute_mcp_reload.assert_awaited()
    assert runner._execute_mcp_reload.await_args.kwargs.get("event") is None
