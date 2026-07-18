"""Multi-account messaging connections under a single platform.

Stores connection metadata in ``platforms.<id>.connections`` (config.yaml)
and connection-scoped credentials in ``.env`` using:

- default connection → legacy env keys (``TELEGRAM_BOT_TOKEN``, …)
- additional connections → ``{KEY}__CONN_{ID}``

Legacy single-token setups migrate to a synthetic ``default`` connection
with zero user action.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_CONNECTION_ID = "default"

# Platforms that expose multi-account UI + connection CRUD in Verxio Messaging.
MULTI_ACCOUNT_PLATFORMS = frozenset(
    {
        "slack",
        "telegram",
        "discord",
        "whatsapp",
        "whatsapp_cloud",
    }
)

# Primary credential env key per platform (used for configured/identity checks).
PRIMARY_CREDENTIAL_ENV: Dict[str, str] = {
    "slack": "SLACK_BOT_TOKEN",
    "telegram": "TELEGRAM_BOT_TOKEN",
    "discord": "DISCORD_BOT_TOKEN",
    "whatsapp": "WHATSAPP_ENABLED",
    "whatsapp_cloud": "WHATSAPP_CLOUD_PHONE_NUMBER_ID",
}

# Env keys that are app-level (shared across connections) — not cloned per connection.
APP_LEVEL_ENV: Dict[str, frozenset[str]] = {
    "slack": frozenset({"SLACK_APP_TOKEN", "SLACK_HOME_CHANNEL", "SLACK_HOME_CHANNEL_NAME"}),
    "telegram": frozenset(
        {
            "TELEGRAM_REPLY_TO_MODE",
            "TELEGRAM_FALLBACK_IPS",
            "TELEGRAM_PROXY",
            "TELEGRAM_HOME_CHANNEL",
            "TELEGRAM_HOME_CHANNEL_NAME",
            "TELEGRAM_HOME_CHANNEL_THREAD_ID",
        }
    ),
    "discord": frozenset(
        {
            "DISCORD_REPLY_TO_MODE",
            "DISCORD_ALLOW_ALL_USERS",
            "DISCORD_HOME_CHANNEL",
            "DISCORD_HOME_CHANNEL_NAME",
        }
    ),
    "whatsapp": frozenset({"WHATSAPP_MODE", "WHATSAPP_ENABLED"}),
    "whatsapp_cloud": frozenset(
        {
            "WHATSAPP_CLOUD_VERIFY_TOKEN",
            "WHATSAPP_CLOUD_APP_ID",
            "WHATSAPP_CLOUD_APP_SECRET",
            "WHATSAPP_CLOUD_WEBHOOK_HOST",
            "WHATSAPP_CLOUD_WEBHOOK_PORT",
            "WHATSAPP_CLOUD_WEBHOOK_PATH",
            "WHATSAPP_CLOUD_API_VERSION",
            "WHATSAPP_CLOUD_WABA_ID",
        }
    ),
}


@dataclass
class ConnectionRecord:
    """One messaging account under a platform (bot, workspace, or phone number)."""

    id: str
    label: str = ""
    enabled: bool = True
    # Optional display identity (bot username, team name, phone E.164).
    identity: str = ""
    # Extra platform-specific fields (e.g. slack team_id, phone_number_id).
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "enabled": self.enabled,
        }
        if self.identity:
            payload["identity"] = self.identity
        if self.meta:
            payload["meta"] = dict(self.meta)
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectionRecord":
        return cls(
            id=str(data.get("id") or DEFAULT_CONNECTION_ID).strip() or DEFAULT_CONNECTION_ID,
            label=str(data.get("label") or "").strip(),
            enabled=bool(data.get("enabled", True)),
            identity=str(data.get("identity") or "").strip(),
            meta=dict(data.get("meta") or {}) if isinstance(data.get("meta"), dict) else {},
        )


def new_connection_id(prefix: str = "conn") -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def sanitize_connection_id(connection_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", (connection_id or "").strip())
    return cleaned or DEFAULT_CONNECTION_ID


def is_default_connection(connection_id: Optional[str]) -> bool:
    return not connection_id or connection_id == DEFAULT_CONNECTION_ID


def connection_env_key(base_key: str, connection_id: Optional[str]) -> str:
    """Map a catalog env key onto the storage key for a connection."""
    if is_default_connection(connection_id):
        return base_key
    safe = sanitize_connection_id(connection_id).upper()
    return f"{base_key}__CONN_{safe}"


def parse_connection_env_key(env_key: str) -> tuple[str, Optional[str]]:
    """Return ``(base_key, connection_id|None)`` for a possibly scoped env key."""
    marker = "__CONN_"
    if marker not in env_key:
        return env_key, None
    base, _, suffix = env_key.partition(marker)
    if not base or not suffix:
        return env_key, None
    return base, suffix.lower()


def adapter_registry_key(platform: str, connection_id: Optional[str] = None) -> str:
    if is_default_connection(connection_id):
        return platform
    return f"{platform}:{sanitize_connection_id(connection_id)}"


def connections_from_platform_dict(data: Dict[str, Any]) -> List[ConnectionRecord]:
    raw = data.get("connections")
    if not isinstance(raw, list) or not raw:
        return []
    out: List[ConnectionRecord] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        record = ConnectionRecord.from_dict(item)
        if record.id in seen:
            continue
        seen.add(record.id)
        out.append(record)
    return out


def ensure_default_connection(
    platform_id: str,
    records: List[ConnectionRecord],
    *,
    has_legacy_credentials: bool,
    label: str = "Default",
) -> List[ConnectionRecord]:
    """Guarantee a default row when legacy credentials exist or list is empty."""
    if any(r.id == DEFAULT_CONNECTION_ID for r in records):
        return records
    if has_legacy_credentials or not records:
        return [
            ConnectionRecord(
                id=DEFAULT_CONNECTION_ID,
                label=label,
                enabled=True,
            ),
            *records,
        ]
    return records


def load_connections_for_platform(platform_id: str) -> List[ConnectionRecord]:
    """Read connection metadata from config.yaml for a platform."""
    try:
        from hermes_cli.config import load_config
    except Exception:
        return []

    try:
        config = load_config()
    except Exception:
        return []

    platforms = config.get("platforms") if isinstance(config, dict) else None
    if not isinstance(platforms, dict):
        return []
    entry = platforms.get(platform_id)
    if not isinstance(entry, dict):
        return []
    return connections_from_platform_dict(entry)


def save_connections_for_platform(platform_id: str, records: List[ConnectionRecord]) -> None:
    """Persist connection metadata (not secrets) under platforms.<id>.connections."""
    from hermes_cli.config import load_config, save_config

    config = load_config()
    if not isinstance(config, dict):
        config = {}
    platforms = config.setdefault("platforms", {})
    if not isinstance(platforms, dict):
        platforms = {}
        config["platforms"] = platforms
    entry = platforms.setdefault(platform_id, {})
    if not isinstance(entry, dict):
        entry = {}
        platforms[platform_id] = entry
    entry["connections"] = [r.to_dict() for r in records]
    save_config(config)


def connection_credential_keys(platform_id: str, catalog_env_vars: list[str]) -> list[str]:
    """Env keys that are per-connection (exclude app-level shared keys)."""
    shared = APP_LEVEL_ENV.get(platform_id, frozenset())
    return [key for key in catalog_env_vars if key not in shared]


def split_csv_tokens(raw: str) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def join_csv_tokens(tokens: list[str]) -> str:
    return ",".join(token for token in tokens if token.strip())
