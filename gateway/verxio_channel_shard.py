"""Verxio channel-gateway shard: rebuild tenant connections from the control plane.

A shard (``VERXIO_CHANNEL_SHARD=<index>``) owns the sticky socket connections
(WhatsApp, Discord, Telegram polling, Slack socket mode) of every tenant whose
``shard_for(workspace, agent)`` hashes to it. It has no durable state of its
own: on boot it pulls its tenant list + decrypted credentials from
``GET /api/internal/shards/{i}/tenants``, materialises one dynamic profile per
tenant (``.env`` + WhatsApp session files) and lets the multiplexed gateway
start those adapters. A watch loop keeps the set in sync (new pairings, moved
tenants) and writes changed credentials back to the API so a replacement shard
can restore them.

Credential plaintext is always a JSON object:

* messaging bots — ``{"TELEGRAM_BOT_TOKEN": "..."}`` (env keys for the
  profile's ``.env``);
* whatsapp — ``{"creds.json": "...", "app-state-sync-key-*.json": "..."}``
  (file name → UTF-8 content of the Baileys session directory).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

WHATSAPP_SESSION_SUBDIR = Path("platforms/whatsapp/sessions/default")
_ENV_PLATFORM_KEYS: Dict[str, Tuple[str, ...]] = {
    "telegram": ("TELEGRAM_BOT_TOKEN",),
    "discord": ("DISCORD_BOT_TOKEN",),
    "slack": ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET"),
    "whatsapp_cloud": ("WHATSAPP_CLOUD_PHONE_NUMBER_ID", "WHATSAPP_CLOUD_ACCESS_TOKEN", "WHATSAPP_CLOUD_VERIFY_TOKEN"),
}
_WRITEBACK_STATE: Dict[str, str] = {}


def shard_index() -> Optional[int]:
    """Shard ordinal for this process.

    ``VERXIO_CHANNEL_SHARD`` wins. Otherwise, when running as a Kubernetes
    StatefulSet pod, derive it from the pod name's trailing ordinal
    (``VERXIO_POD_NAME=verxio-channel-gateway-3`` -> ``3``) so the image's
    s6 entrypoint does not need a shell wrapper.
    """
    raw = os.getenv("VERXIO_CHANNEL_SHARD", "").strip()
    if raw == "":
        pod = os.getenv("VERXIO_POD_NAME", "").strip()
        if "-" not in pod:
            return None
        raw = pod.rsplit("-", 1)[1]
    try:
        return int(raw)
    except ValueError:
        return None


def shard_enabled() -> bool:
    return shard_index() is not None and bool(os.getenv("VERXIO_API_URL", "").strip())


def _api() -> str:
    return os.getenv("VERXIO_API_URL", "").strip().rstrip("/")


def _internal_headers() -> Dict[str, str]:
    token = os.getenv("VERXIO_INTERNAL_TOKEN", "").strip()
    return {"X-Verxio-Internal-Token": token} if token else {}


def tenant_profile_name(workspace_id: str, agent_id: str) -> str:
    from hermes_cli.dynamic_profiles import _safe_name

    return _safe_name(f"{workspace_id}:{agent_id}")


def tenants_root() -> Path:
    explicit = os.getenv("VERXIO_TENANT_HOMES_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(None)
    try:
        base = get_hermes_home()
    finally:
        reset_hermes_home_override(token)
    return base / "verxio" / "tenants"


# ----------------------------------------------------------------- materialise
def _write_env(home: Path, values: Dict[str, str]) -> None:
    from agent.secret_scope import load_env_file

    home.mkdir(parents=True, exist_ok=True)
    env_path = home / ".env"
    current = load_env_file(env_path) if env_path.exists() else {}
    current.update({k: v for k, v in values.items() if k})
    lines = []
    for key in sorted(current):
        value = str(current[key])
        if any(ch in value for ch in (" ", "#", '"', "'", "\n")) or value == "":
            value = '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
        lines.append(f"{key}={value}")
    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)


def _write_whatsapp_session(home: Path, files: Dict[str, str]) -> None:
    session_dir = home / WHATSAPP_SESSION_SUBDIR
    session_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        safe = Path(name).name
        if not safe or safe.startswith(".."):
            continue
        target = session_dir / safe
        tmp = target.with_name(f".{safe}.tmp")
        tmp.write_text(str(content), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)


def _ensure_profile_config(home: Path, platforms: List[str]) -> None:
    """Minimal config.yaml so ``load_gateway_config`` enables the tenant's platforms."""
    import yaml

    config_path = home / "config.yaml"
    data: Dict[str, Any] = {}
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    platforms_cfg = data.get("platforms")
    if not isinstance(platforms_cfg, dict):
        platforms_cfg = {}
        data["platforms"] = platforms_cfg
    changed = False
    for platform in platforms:
        entry = platforms_cfg.get(platform)
        if not isinstance(entry, dict):
            entry = {}
            platforms_cfg[platform] = entry
        if entry.get("enabled") is not True:
            entry["enabled"] = True
            changed = True
    if changed or not config_path.exists():
        config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def materialise_tenant(tenant: Dict[str, Any]) -> Tuple[str, Path]:
    """Write a tenant's profile home from a control-plane record. Returns (name, home)."""
    workspace_id = str(tenant.get("workspace_id") or "")
    agent_id = str(tenant.get("agent_id") or "")
    name = tenant_profile_name(workspace_id, agent_id)
    home = tenants_root() / name
    env: Dict[str, str] = {
        "VERXIO_WORKSPACE_ID": workspace_id,
        "VERXIO_AGENT_ID": agent_id,
        "VERXIO_RUNTIME_TOKEN": str(tenant.get("runtime_token") or ""),
        "VERXIO_HOSTED": "1",
    }
    platforms: List[str] = []
    for cred in tenant.get("credentials") or []:
        platform = str(cred.get("platform") or "").strip().lower()
        try:
            blob = json.loads(str(cred.get("plaintext") or "{}"))
        except json.JSONDecodeError:
            blob = {}
        if not isinstance(blob, dict) or not platform:
            continue
        if platform == "whatsapp":
            _write_whatsapp_session(home, {str(k): str(v) for k, v in blob.items()})
            env["WHATSAPP_ENABLED"] = "true"
        else:
            for key, value in blob.items():
                if isinstance(key, str) and key.isupper():
                    env[key] = str(value)
        platforms.append(platform)
    _write_env(home, env)
    _ensure_profile_config(home, platforms)
    return name, home


# --------------------------------------------------------------------- fetch
async def fetch_shard_tenants() -> List[Dict[str, Any]]:
    index = shard_index()
    if index is None:
        return []
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{_api()}/api/internal/shards/{index}/tenants", headers=_internal_headers())
        response.raise_for_status()
        body = response.json()
    tenants = body.get("tenants") if isinstance(body, dict) else None
    return [t for t in (tenants or []) if isinstance(t, dict)]


async def bootstrap() -> Dict[str, Path]:
    """Materialise every tenant of this shard and register them as dynamic profiles.

    Called before secondary-profile adapters start so ``profiles_to_serve``
    already lists the tenants. Failures are logged; the gateway still boots so
    the watch loop can retry.
    """
    if not shard_enabled():
        return {}
    from hermes_cli.dynamic_profiles import attach_profile

    served: Dict[str, Path] = {}
    try:
        tenants = await fetch_shard_tenants()
    except Exception:
        logger.error("Shard %s bootstrap: could not fetch tenants", shard_index(), exc_info=True)
        return served
    for tenant in tenants:
        try:
            name, home = materialise_tenant(tenant)
            attach_profile(name, home)
            served[name] = home
        except Exception:
            logger.exception("Shard bootstrap: tenant %s failed", tenant.get("workspace_id"))
    logger.info("Shard %s bootstrap: %d tenant profile(s)", shard_index(), len(served))
    return served


# ---------------------------------------------------------------------- watch
async def _reconcile(runner: Any) -> None:
    from hermes_cli.dynamic_profiles import attach_profile, detach_profile, list_dynamic_profiles

    tenants = await fetch_shard_tenants()
    wanted: Dict[str, Path] = {}
    for tenant in tenants:
        try:
            name, home = materialise_tenant(tenant)
            wanted[name] = home
        except Exception:
            logger.exception("Shard reconcile: tenant %s failed", tenant.get("workspace_id"))
    current = dict(list_dynamic_profiles())
    profile_adapters = getattr(runner, "_profile_adapters", {})

    # New tenants: register + start adapters.
    claimed: Dict[tuple, str] = {}
    for name, home in wanted.items():
        if name not in current:
            attach_profile(name, home)
        if name not in profile_adapters:
            try:
                connected = await runner._start_one_profile_adapters(name, home, claimed)
                logger.info("Shard: started %d adapter(s) for tenant %s", connected, name)
            except Exception:
                logger.exception("Shard: adapter start failed for %s", name)

    # Tenants that moved away (rehash / drain): stop adapters, drop the profile.
    for name in list(current):
        if name in wanted or not str(current[name]).startswith(str(tenants_root())):
            continue
        adapters = profile_adapters.pop(name, {}) if isinstance(profile_adapters, dict) else {}
        for platform, adapter in list(adapters.items()):
            try:
                await runner._safe_adapter_disconnect(adapter, platform)
            except Exception:
                pass
        detach_profile(name)
        logger.info("Shard: released tenant %s", name)


def writeback_enabled() -> bool:
    """Shards always write back; single-tenant hosted runtimes do too (migration path)."""
    if shard_enabled():
        return True
    hosted = os.getenv("VERXIO_HOSTED", "").strip() == "1"
    return hosted and bool(os.getenv("VERXIO_RUNTIME_TOKEN", "").strip()) and bool(_api())


def _writeback_targets() -> List[Tuple[str, Path]]:
    from hermes_cli.dynamic_profiles import list_dynamic_profiles

    targets: List[Tuple[str, Path]] = []
    root = str(tenants_root())
    for name, home in list_dynamic_profiles():
        if str(home).startswith(root):
            targets.append((name, Path(home)))
    if not shard_enabled():
        # Per-user runtime container: its own home is the tenant.
        from hermes_constants import get_hermes_home

        targets.append(("", get_hermes_home()))
    return targets


async def _writeback(runner: Any) -> None:
    """Push changed tenant credentials (bot tokens, WhatsApp session) to Verxio."""
    from agent.secret_scope import load_env_file
    from gateway.verxio_remote_exec import tenant_for_profile

    for name, home in _writeback_targets():
        tenant = tenant_for_profile(name or None)
        if tenant is None:
            continue
        env = load_env_file(Path(home) / ".env")
        payloads: Dict[str, Dict[str, str]] = {}
        for platform, keys in _ENV_PLATFORM_KEYS.items():
            values = {key: env[key] for key in keys if env.get(key)}
            if values.get(keys[0]):
                payloads[platform] = values
        session_dir = Path(home) / WHATSAPP_SESSION_SUBDIR
        for candidate in (
            session_dir,
            Path(home) / "platforms/whatsapp/session",
            Path(home) / "whatsapp/sessions/default",
            Path(home) / "whatsapp/session",
        ):
            if (candidate / "creds.json").is_file():
                session_dir = candidate
                break
        if (session_dir / "creds.json").is_file():
            files: Dict[str, str] = {}
            for file in sorted(session_dir.glob("*.json")):
                try:
                    files[file.name] = file.read_text(encoding="utf-8")
                except OSError:
                    continue
            if files:
                payloads["whatsapp"] = files
        for platform, blob in payloads.items():
            plaintext = json.dumps(blob, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
            state_key = f"{tenant.key}:{platform}"
            if _WRITEBACK_STATE.get(state_key) == digest:
                continue
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.put(
                        f"{_api()}/api/runtime/channels/credentials",
                        json={"platform": platform, "plaintext": plaintext},
                        headers={"Authorization": f"Bearer {tenant.token}"},
                    )
                if response.status_code < 400:
                    _WRITEBACK_STATE[state_key] = digest
                else:
                    logger.warning("Credential write-back rejected (%s) tenant=%s platform=%s", response.status_code, tenant.key, platform)
            except Exception:
                logger.warning("Credential write-back failed tenant=%s platform=%s", tenant.key, platform, exc_info=True)


async def watch(runner: Any) -> None:
    """Periodic reconcile (shards) + credential write-back (shards and hosted runtimes)."""
    if not writeback_enabled():
        return
    interval = float(os.getenv("VERXIO_SHARD_SYNC_SECONDS", "60") or "60")
    while True:
        if shard_enabled():
            try:
                await _reconcile(runner)
            except Exception:
                logger.warning("Shard reconcile failed", exc_info=True)
        try:
            await _writeback(runner)
        except Exception:
            logger.warning("Shard credential write-back failed", exc_info=True)
        await asyncio.sleep(max(15.0, interval))
