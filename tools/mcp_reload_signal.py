"""Cross-process MCP reload signal for dashboard → messaging gateway.

Verxio soft-reloads Composio via the Hermes dashboard ``POST /api/mcp/reload``.
That only refreshes the dashboard/TUI process. All messaging platforms
(Telegram, WhatsApp, Slack, Discord, and any other gateway adapter) share one
supervised ``gateway run`` process with its own MCP registry — so without this
signal those chats keep stale/missing ``mcp_composio_*`` tools and Connected
Apps context until a full restart or interactive ``/reload-mcp``.

The dashboard writes ``{HERMES_HOME}/mcp_reload.request``; the shared gateway
watcher consumes it and rediscovers MCP servers for every messaging platform.
"""

from __future__ import annotations

import time
from pathlib import Path

from hermes_constants import get_hermes_home

MCP_RELOAD_REQUEST_FILENAME = "mcp_reload.request"


def mcp_reload_request_path(hermes_home: Path | None = None) -> Path:
    home = hermes_home if hermes_home is not None else get_hermes_home()
    return Path(home) / MCP_RELOAD_REQUEST_FILENAME


def request_gateway_mcp_reload(hermes_home: Path | None = None) -> Path:
    """Ask the co-located messaging gateway to reload MCP servers from disk."""
    path = mcp_reload_request_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.time():.6f}\n", encoding="utf-8")
    return path


def consume_gateway_mcp_reload_request(hermes_home: Path | None = None) -> bool:
    """Return True once if a reload was requested (and clear the marker)."""
    path = mcp_reload_request_path(hermes_home)
    if not path.exists():
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        # Another consumer may have raced us; treat as consumed if gone.
        return not path.exists()
    return True
