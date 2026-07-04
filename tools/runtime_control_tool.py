"""Reload environment variables or restart the agent runtime after config changes."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _reload_env() -> dict[str, Any]:
    from hermes_cli.config import reload_env

    updated = int(reload_env())
    return {
        "ok": True,
        "action": "reload_env",
        "updated": updated,
        "message": (
            f"Reloaded {updated} environment variable(s) from ~/.hermes/.env. "
            "Start a new chat (or send your next message) so the agent picks up provider changes."
        ),
    }


def _restart_gateway(profile: str | None = None) -> dict[str, Any]:
    from hermes_cli.web_server import _spawn_gateway_restart

    reload_result = _reload_env()
    proc, reused = _spawn_gateway_restart(profile)
    return {
        "ok": True,
        "action": "restart_gateway",
        "updated": reload_result.get("updated", 0),
        "restart_started": True,
        "restart_reused": reused,
        "restart_pid": proc.pid,
        "message": (
            "Reloaded credentials and started a gateway restart. "
            "The UI reconnects automatically; start a new chat if the model still looks stale."
        ),
    }


def runtime_control(action: str, profile: str | None = None) -> str:
    """Apply runtime changes after updating providers, models, or .env keys."""
    normalized = (action or "").strip().lower().replace("-", "_")
    if normalized in {"reload", "reload_env", "env_reload"}:
        return json.dumps(_reload_env(), ensure_ascii=False)
    if normalized in {"restart", "restart_gateway", "gateway_restart", "runtime_restart"}:
        try:
            return json.dumps(_restart_gateway(profile), ensure_ascii=False)
        except RuntimeError as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        except Exception as exc:
            logger.exception("runtime_control restart failed")
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": False,
            "error": "Unknown action. Use reload_env or restart_gateway.",
        },
        ensure_ascii=False,
    )


def check_runtime_control_requirements() -> bool:
    from utils import env_var_enabled

    return (
        env_var_enabled("HERMES_INTERACTIVE")
        or env_var_enabled("HERMES_GATEWAY_SESSION")
        or env_var_enabled("HERMES_EXEC_ASK")
    )


RUNTIME_CONTROL_SCHEMA = {
    "name": "runtime_control",
    "description": (
        "Reload ~/.hermes/.env or restart the agent gateway after changing providers, "
        "models, API keys, or custom endpoints. Prefer reload_env for credential-only "
        "changes; use restart_gateway when config.yaml or messaging platforms need a full refresh."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["reload_env", "restart_gateway"],
                "description": "reload_env re-reads .env; restart_gateway reloads .env then restarts the gateway process.",
            },
        },
        "required": ["action"],
    },
}

from tools.registry import registry

registry.register(
    name="runtime_control",
    toolset="runtime",
    schema=RUNTIME_CONTROL_SCHEMA,
    handler=lambda args, **kw: runtime_control(
        action=args.get("action", ""),
        profile=kw.get("profile"),
    ),
    check_fn=check_runtime_control_requirements,
    emoji="🔄",
)
