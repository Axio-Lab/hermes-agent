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

# Per-connection credential keys scanned for ``__CONN_{id}`` orphans on rebuild.
CONNECTION_SCOPED_ENV_KEYS: Dict[str, tuple[str, ...]] = {
    "slack": ("SLACK_BOT_TOKEN",),
    "telegram": ("TELEGRAM_BOT_TOKEN",),
    "discord": ("DISCORD_BOT_TOKEN",),
    "whatsapp": (),  # Baileys pairing uses session dirs, not scoped tokens
    "whatsapp_cloud": (
        "WHATSAPP_CLOUD_PHONE_NUMBER_ID",
        "WHATSAPP_CLOUD_ACCESS_TOKEN",
    ),
}

# Survives config.yaml wipes — labels are not secrets but must outlive rebuilds.
CONNECTION_LABEL_ENV: Dict[str, str] = {
    "slack": "SLACK_CONNECTION_LABEL",
    "telegram": "TELEGRAM_CONNECTION_LABEL",
    "discord": "DISCORD_CONNECTION_LABEL",
    "whatsapp": "WHATSAPP_CONNECTION_LABEL",
    "whatsapp_cloud": "WHATSAPP_CLOUD_CONNECTION_LABEL",
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


def connection_label_env_key(platform_id: str, connection_id: Optional[str]) -> Optional[str]:
    base = CONNECTION_LABEL_ENV.get(platform_id)
    if not base:
        return None
    return connection_env_key(base, connection_id)


def read_connection_label(
    platform_id: str,
    connection_id: Optional[str],
    env: Optional[Dict[str, str]] = None,
) -> str:
    key = connection_label_env_key(platform_id, connection_id)
    if not key:
        return ""
    if env is None:
        try:
            from hermes_cli.config import load_env
        except Exception:
            return ""
        env = load_env()
    return str(env.get(key) or "").strip()


def persist_connection_label(platform_id: str, connection_id: str, label: str) -> None:
    """Write a human label into ``.env`` so rebuilds can restore it."""
    key = connection_label_env_key(platform_id, connection_id)
    if not key or is_default_connection(connection_id):
        return
    trimmed = (label or "").strip()
    if not trimmed or trimmed.lower() == "default" or trimmed.startswith("Restored "):
        return
    try:
        from hermes_cli.config import save_env_value

        save_env_value(key, trimmed)
    except Exception:
        pass


def resolve_bot_display_name(platform_id: str, token: str) -> str:
    """Best-effort live identity for Telegram/Discord bots (username / name)."""
    token = (token or "").strip()
    if not token:
        return ""
    try:
        import urllib.error
        import urllib.request
    except Exception:
        return ""

    try:
        if platform_id == "telegram":
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/getMe",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                import json

                payload = json.loads(resp.read().decode("utf-8"))
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, dict):
                return ""
            username = str(result.get("username") or "").strip()
            first = str(result.get("first_name") or "").strip()
            if username:
                return f"@{username}"
            return first
        if platform_id == "discord":
            req = urllib.request.Request(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                import json

                payload = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, dict):
                return ""
            username = str(payload.get("username") or "").strip()
            global_name = str(payload.get("global_name") or "").strip()
            return global_name or username
    except Exception:
        return ""
    return ""


def _needs_label_enrichment(label: str) -> bool:
    cleaned = (label or "").strip()
    return (not cleaned) or cleaned.startswith("Restored ") or cleaned.lower() == "default"


def enrich_connection_labels(
    platform_id: str,
    records: List[ConnectionRecord],
    env: Optional[Dict[str, str]] = None,
) -> tuple[List[ConnectionRecord], bool]:
    """Fill missing/restored labels from ``.env`` metadata or live bot identity."""
    if env is None:
        try:
            from hermes_cli.config import load_env
        except Exception:
            env = {}
        else:
            env = load_env()

    changed = False
    for record in records:
        stored = read_connection_label(platform_id, record.id, env)
        if stored and (not record.label or record.label.startswith("Restored ")):
            record.label = stored
            changed = True
            continue
        if not _needs_label_enrichment(record.label) and record.identity:
            continue
        if platform_id not in {"telegram", "discord"}:
            if stored and not record.label:
                record.label = stored
                changed = True
            continue
        token = _connection_primary_token(platform_id, record, env)
        display = resolve_bot_display_name(platform_id, token) if token else ""
        if not display:
            continue
        if not record.identity:
            record.identity = display
            changed = True
        if _needs_label_enrichment(record.label) and not is_default_connection(record.id):
            # Prefer @botname over opaque Restored <hex> ids.
            record.label = display.lstrip("@") or display
            changed = True
            persist_connection_label(platform_id, record.id, record.label)
    return records, changed


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
    """Guarantee a default row when legacy credentials exist.

    Does **not** invent a Default row for empty platforms — that made Discord /
    WhatsApp look like “needs setup” after rebuilds when they were simply off.
    """
    if any(r.id == DEFAULT_CONNECTION_ID for r in records):
        return records
    if has_legacy_credentials:
        return [
            ConnectionRecord(
                id=DEFAULT_CONNECTION_ID,
                label=label,
                enabled=True,
            ),
            *records,
        ]
    return records


def platform_has_recoverable_credentials(
    platform_id: str,
    env: Optional[Dict[str, str]] = None,
) -> bool:
    """True only when this platform still has real credentials or a paired session."""
    if platform_id not in MULTI_ACCOUNT_PLATFORMS:
        return False
    if env is None:
        try:
            from hermes_cli.config import load_env
        except Exception:
            env = {}
        else:
            env = load_env()

    if platform_id == "whatsapp":
        if any(path.is_file() for path in _whatsapp_default_creds_paths()):
            return True
        if discover_whatsapp_session_connection_ids():
            return True
        return False

    if platform_id == "slack":
        if split_csv_tokens(env.get("SLACK_BOT_TOKEN") or ""):
            return True
        return bool(discover_connection_ids_from_env(platform_id, env))

    primary = PRIMARY_CREDENTIAL_ENV.get(platform_id, "")
    if primary and primary != "WHATSAPP_ENABLED" and (env.get(primary) or "").strip():
        return True
    if discover_connection_ids_from_env(platform_id, env):
        return True
    return False


def _connection_primary_token(
    platform_id: str,
    record: ConnectionRecord,
    env: Dict[str, str],
) -> str:
    primary = PRIMARY_CREDENTIAL_ENV.get(platform_id, "")
    if not primary:
        return ""
    scoped = (env.get(connection_env_key(primary, record.id)) or "").strip()
    if scoped:
        return scoped
    if is_default_connection(record.id):
        return (env.get(primary) or "").strip()
    return ""


def discover_connection_ids_from_env(
    platform_id: str,
    env: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Return connection ids that still have scoped credentials in ``.env``."""
    scoped_keys = CONNECTION_SCOPED_ENV_KEYS.get(platform_id) or ()
    primary = PRIMARY_CREDENTIAL_ENV.get(platform_id, "")
    bases = tuple(dict.fromkeys([*scoped_keys, primary] if primary else scoped_keys))
    if not bases:
        return []
    if env is None:
        try:
            from hermes_cli.config import load_env
        except Exception:
            return []
        env = load_env()

    found: List[str] = []
    seen: set[str] = set()
    for base in bases:
        prefix = f"{base}__CONN_"
        for key, value in env.items():
            if not key.startswith(prefix) or not str(value or "").strip():
                continue
            parsed_base, conn_id = parse_connection_env_key(key)
            if parsed_base != base or not conn_id or conn_id == DEFAULT_CONNECTION_ID:
                continue
            if conn_id in seen:
                continue
            seen.add(conn_id)
            found.append(conn_id)
    return found


def discover_whatsapp_session_connection_ids() -> List[str]:
    """Return WhatsApp connection ids that still have a paired ``creds.json``."""
    try:
        from hermes_constants import get_hermes_dir
    except Exception:
        return []

    roots = [
        get_hermes_dir("platforms/whatsapp/sessions", "whatsapp/sessions"),
    ]
    found: List[str] = []
    seen: set[str] = set()
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                conn_id = sanitize_connection_id(child.name)
                if conn_id == DEFAULT_CONNECTION_ID or conn_id in seen:
                    continue
                if (child / "creds.json").is_file():
                    seen.add(conn_id)
                    found.append(conn_id)
        except Exception:
            continue
    return found


def expand_slack_connections(
    records: List[ConnectionRecord],
    env: Optional[Dict[str, str]] = None,
    *,
    team_by_token: Optional[Dict[str, Dict[str, Any]]] = None,
) -> tuple[List[ConnectionRecord], bool]:
    """Expand Slack workspace rows from CSV ``SLACK_BOT_TOKEN`` (+ optional team map)."""
    if env is None:
        try:
            from hermes_cli.config import load_env
        except Exception:
            return records, False
        env = load_env()

    tokens = split_csv_tokens(env.get("SLACK_BOT_TOKEN") or "")
    if not tokens:
        return records, False

    if team_by_token is None:
        team_by_token = {}
        try:
            from hermes_constants import get_hermes_home

            tokens_path = get_hermes_home() / "slack_tokens.json"
            if tokens_path.is_file():
                import json

                raw = json.loads(tokens_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for team_id, info in raw.items():
                        if not isinstance(info, dict):
                            continue
                        tok = str(info.get("bot_token") or info.get("token") or "").strip()
                        if tok:
                            team_by_token[tok] = {
                                "team_id": str(team_id),
                                "team_name": str(
                                    info.get("team_name") or info.get("name") or team_id
                                ),
                            }
        except Exception:
            team_by_token = {}

    if len(records) >= len(tokens) and all(
        isinstance(r, ConnectionRecord) for r in records
    ):
        return records, False

    expanded: List[ConnectionRecord] = []
    for index, token in enumerate(tokens):
        team = team_by_token.get(token, {})
        conn_id = DEFAULT_CONNECTION_ID if index == 0 else f"slack_{index}"
        existing = next((r for r in records if r.meta.get("token_index") == index), None)
        if existing is None and index == 0:
            existing = next((r for r in records if r.id == DEFAULT_CONNECTION_ID), None)
        if existing is not None:
            if not existing.identity and team.get("team_name"):
                existing.identity = str(team["team_name"])
            existing.meta = {
                **(existing.meta or {}),
                "token_index": index,
                **({"team_id": team["team_id"]} if team.get("team_id") else {}),
            }
            expanded.append(existing)
            continue
        expanded.append(
            ConnectionRecord(
                id=conn_id,
                label=str(
                    team.get("team_name")
                    or ("Default" if index == 0 else f"Workspace {index + 1}")
                ),
                enabled=True,
                identity=str(team.get("team_name") or ""),
                meta={
                    "token_index": index,
                    **({"team_id": team["team_id"]} if team.get("team_id") else {}),
                },
            )
        )
    changed = [r.to_dict() for r in expanded] != [r.to_dict() for r in records]
    return expanded, changed


def merge_env_discovered_connections(
    platform_id: str,
    records: List[ConnectionRecord],
    env: Optional[Dict[str, str]] = None,
) -> tuple[List[ConnectionRecord], bool]:
    """Rehydrate connection rows wiped from config.yaml but still present in ``.env``.

    Dedupes by primary credential value so orphan ``__CONN_*`` keys that already
    match Default (or another row) are not shown as duplicate bots.
    """
    if platform_id not in MULTI_ACCOUNT_PLATFORMS:
        return records, False
    if env is None:
        try:
            from hermes_cli.config import load_env
        except Exception:
            return records, False
        env = load_env()

    existing_ids = {r.id for r in records}
    used_tokens = {
        token
        for record in records
        if (token := _connection_primary_token(platform_id, record, env))
    }
    # Default often stores the token only on the legacy unscoped key.
    primary = PRIMARY_CREDENTIAL_ENV.get(platform_id, "")
    if primary and primary != "WHATSAPP_ENABLED":
        legacy = (env.get(primary) or "").strip()
        if legacy:
            used_tokens.add(legacy)

    out = list(records)
    changed = False
    for conn_id in discover_connection_ids_from_env(platform_id, env):
        if conn_id in existing_ids:
            continue
        token = ""
        if primary and primary != "WHATSAPP_ENABLED":
            token = (env.get(connection_env_key(primary, conn_id)) or "").strip()
        if not token:
            for key in CONNECTION_SCOPED_ENV_KEYS.get(platform_id, ()):
                token = (env.get(connection_env_key(key, conn_id)) or "").strip()
                if token:
                    break
        if token and token in used_tokens:
            continue
        if not token:
            continue
        stored_label = read_connection_label(platform_id, conn_id, env)
        label_suffix = conn_id.split("_", 1)[-1][:8]
        label = stored_label or f"Restored {label_suffix}"
        identity = ""
        if platform_id in {"telegram", "discord"} and (
            not stored_label or stored_label.startswith("Restored ")
        ):
            display = resolve_bot_display_name(platform_id, token)
            if display:
                identity = display
                if not stored_label:
                    label = display.lstrip("@") or display
                    persist_connection_label(platform_id, conn_id, label)
        out.append(
            ConnectionRecord(
                id=conn_id,
                label=label,
                enabled=True,
                identity=identity,
            )
        )
        existing_ids.add(conn_id)
        used_tokens.add(token)
        changed = True

    if platform_id == "whatsapp":
        for conn_id in discover_whatsapp_session_connection_ids():
            if conn_id in existing_ids:
                continue
            stored_label = read_connection_label(platform_id, conn_id, env)
            label_suffix = conn_id.split("_", 1)[-1][:8]
            out.append(
                ConnectionRecord(
                    id=conn_id,
                    label=stored_label or f"Restored {label_suffix}",
                    enabled=True,
                )
            )
            existing_ids.add(conn_id)
            changed = True

    return out, changed


def _whatsapp_default_creds_paths():
    try:
        from hermes_constants import get_hermes_dir
    except Exception:
        return ()
    return (
        get_hermes_dir("platforms/whatsapp/session", "whatsapp/session") / "creds.json",
        get_hermes_dir(
            f"platforms/whatsapp/sessions/{DEFAULT_CONNECTION_ID}",
            f"whatsapp/sessions/{DEFAULT_CONNECTION_ID}",
        )
        / "creds.json",
    )


def _clear_platform_connection_stubs(platform_id: str) -> bool:
    """Remove connection stubs + force disabled when a platform has no credentials."""
    from hermes_cli.config import read_raw_config, save_config

    config = read_raw_config()
    if not isinstance(config, dict):
        return False
    platforms = config.get("platforms")
    if not isinstance(platforms, dict):
        return False
    entry = platforms.get(platform_id)
    if not isinstance(entry, dict):
        return False
    changed = False
    if entry.get("connections"):
        entry["connections"] = []
        changed = True
    if entry.get("enabled") is True:
        entry["enabled"] = False
        changed = True
    if changed:
        platforms[platform_id] = entry
        config["platforms"] = platforms
        save_config(config)
    return changed


def recover_connections_for_platform(
    platform_id: str,
    env: Optional[Dict[str, str]] = None,
    *,
    persist: bool = False,
) -> tuple[List[ConnectionRecord], bool]:
    """Rebuild the full connection list for a platform after config loss.

    Only restores platforms that still have credentials in ``.env`` (or a
    WhatsApp paired session). Disabled platforms with nothing to restore are
    left empty/off — never stubbed into a “needs setup” Default row.
    """
    if platform_id not in MULTI_ACCOUNT_PLATFORMS:
        return [], False

    if env is None:
        try:
            from hermes_cli.config import load_env
        except Exception:
            env = {}
        else:
            env = load_env()

    if not platform_has_recoverable_credentials(platform_id, env):
        cleared = False
        if persist:
            try:
                cleared = _clear_platform_connection_stubs(platform_id)
            except Exception:
                cleared = False
        return [], cleared

    records = load_connections_for_platform(
        platform_id, hydrate_env=False, env=env
    )
    records, env_changed = merge_env_discovered_connections(platform_id, records, env)

    slack_changed = False
    if platform_id == "slack":
        records, slack_changed = expand_slack_connections(records, env)

    primary = PRIMARY_CREDENTIAL_ENV.get(platform_id, "")
    if platform_id == "whatsapp":
        legacy_set = any(path.is_file() for path in _whatsapp_default_creds_paths())
    else:
        legacy_set = bool((env.get(primary) or "").strip()) if primary else False

    before = [r.to_dict() for r in records]
    records = ensure_default_connection(
        platform_id,
        records,
        has_legacy_credentials=legacy_set,
        label="Default",
    )
    default_changed = [r.to_dict() for r in records] != before
    records, label_changed = enrich_connection_labels(platform_id, records, env)
    changed = env_changed or slack_changed or default_changed or label_changed

    if persist and records:
        persisted = load_connections_for_platform(
            platform_id, hydrate_env=False, env=env
        )
        if changed or [r.to_dict() for r in persisted] != [r.to_dict() for r in records]:
            save_connections_for_platform(platform_id, records)
            changed = True

    return records, changed


def load_connections_for_platform(
    platform_id: str,
    *,
    hydrate_env: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> List[ConnectionRecord]:
    """Read connection metadata from config.yaml for a platform.

    When ``hydrate_env`` is true (default), also reattach rows that still have
    ``{KEY}__CONN_{id}`` credentials on disk even if config.yaml lost them
    (common after a Docker config migration / slim rewrite).
    """
    records: List[ConnectionRecord] = []
    try:
        from hermes_cli.config import load_config

        config = load_config()
        platforms = config.get("platforms") if isinstance(config, dict) else None
        if isinstance(platforms, dict):
            entry = platforms.get(platform_id)
            if isinstance(entry, dict):
                records = connections_from_platform_dict(entry)
    except Exception:
        records = []

    if hydrate_env:
        records, _ = merge_env_discovered_connections(platform_id, records, env)
        if platform_id == "slack":
            records, _ = expand_slack_connections(records, env)
    return records


def save_connections_for_platform(platform_id: str, records: List[ConnectionRecord]) -> None:
    """Persist connection metadata (not secrets) under platforms.<id>.connections.

    Uses the raw on-disk config (not the defaults-merged view) so a connection
    save cannot rewrite the whole file from DEFAULT_CONFIG and drop unrelated
    user keys in a race with Verxio control-plane writers.
    """
    from hermes_cli.config import read_raw_config, save_config

    config = read_raw_config()
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
    # Never force-enable here. Gateway env overrides still auto-enable when a
    # real token exists; disabled platforms without credentials stay off.
    save_config(config)
    for record in records:
        if record.label:
            persist_connection_label(platform_id, record.id, record.label)


def recover_all_messaging_connections(*, persist: bool = True) -> Dict[str, List[ConnectionRecord]]:
    """Recover every multi-account platform; used on gateway / dashboard boot."""
    recovered: Dict[str, List[ConnectionRecord]] = {}
    try:
        from hermes_cli.config import load_env

        env = load_env()
    except Exception:
        env = {}
    for platform_id in sorted(MULTI_ACCOUNT_PLATFORMS):
        try:
            records, _ = recover_connections_for_platform(
                platform_id, env, persist=persist
            )
            if records:
                recovered[platform_id] = records
        except Exception:
            continue
    return recovered


def connection_credential_keys(platform_id: str, catalog_env_vars: list[str]) -> list[str]:
    """Env keys that are per-connection (exclude app-level shared keys)."""
    shared = APP_LEVEL_ENV.get(platform_id, frozenset())
    return [key for key in catalog_env_vars if key not in shared]


def split_csv_tokens(raw: str) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def join_csv_tokens(tokens: list[str]) -> str:
    return ",".join(token for token in tokens if token.strip())
