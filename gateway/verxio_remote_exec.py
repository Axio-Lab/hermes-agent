"""Remote execution for Verxio channel gateways.

When ``VERXIO_REMOTE_EXEC=1`` a gateway shard owns the *connections* (Telegram
polling, Discord socket, WhatsApp session) but does not run the agent. Inbound
messages are enqueued to Verxio (``POST /api/runtime/turns``); the agent worker
pool runs the turn and queues the reply, which this module long-polls
(``GET /api/runtime/deliveries``) and sends through the tenant's adapter.

Tenant identity (workspace/agent/runtime token) is resolved per profile from
that profile's ``.env`` — never from the process environment — so one shard
can serve many tenants without cross-talk.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_TENANT_KEYS = ("VERXIO_WORKSPACE_ID", "VERXIO_AGENT_ID", "VERXIO_RUNTIME_TOKEN")


def remote_exec_enabled() -> bool:
    return os.getenv("VERXIO_REMOTE_EXEC", "").strip().lower() in {"1", "true", "yes", "on"}


def verxio_api_url() -> str:
    return os.getenv("VERXIO_API_URL", "").strip().rstrip("/")


@dataclass(frozen=True)
class TenantIdentity:
    profile: str
    workspace_id: str
    agent_id: str
    token: str

    @property
    def key(self) -> str:
        return f"{self.workspace_id}:{self.agent_id}"


def _home_for_profile(profile: Optional[str]) -> Optional[Path]:
    name = (profile or "").strip()
    try:
        from hermes_cli.dynamic_profiles import get_dynamic_home

        if name:
            home = get_dynamic_home(name)
            if home is not None:
                return Path(home)
    except Exception:
        pass
    try:
        from hermes_cli.profiles import get_active_profile_name, get_profile_dir

        return Path(get_profile_dir(name or get_active_profile_name() or "default"))
    except Exception:
        from hermes_constants import get_hermes_home

        return get_hermes_home()


def tenant_for_profile(profile: Optional[str]) -> Optional[TenantIdentity]:
    """Resolve the Verxio tenant a profile belongs to from its ``.env``.

    Falls back to ``os.environ`` only for the process's own (single-tenant)
    profile so the per-user runtime container keeps working unchanged.
    """
    home = _home_for_profile(profile)
    values: Dict[str, str] = {}
    if home is not None:
        try:
            from agent.secret_scope import load_env_file

            values = load_env_file(home / ".env")
        except Exception:
            values = {}
    if not all(values.get(key) for key in _TENANT_KEYS) and not (profile or "").strip():
        values = {key: os.getenv(key, "") for key in _TENANT_KEYS}
    if not all(values.get(key) for key in _TENANT_KEYS):
        return None
    return TenantIdentity(
        profile=(profile or "").strip(),
        workspace_id=values["VERXIO_WORKSPACE_ID"],
        agent_id=values["VERXIO_AGENT_ID"],
        token=values["VERXIO_RUNTIME_TOKEN"],
    )


def _auth(tenant: TenantIdentity) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tenant.token}"}


async def enqueue_inbound(event: Any) -> bool:
    """POST an inbound message to Verxio. Return True when Verxio accepted it."""
    if not remote_exec_enabled():
        return False
    base = verxio_api_url()
    if not base:
        return False
    source = getattr(event, "source", None)
    tenant = tenant_for_profile(getattr(source, "profile", None))
    if tenant is None:
        logger.warning("Remote exec: no tenant identity for profile %r", getattr(source, "profile", None))
        return False
    platform = getattr(source, "platform", None)
    platform_value = getattr(platform, "value", platform) or getattr(event, "platform", "")
    payload = {
        "workspace_id": tenant.workspace_id,
        "agent_id": tenant.agent_id,
        "source": "channel",
        "platform": str(platform_value or ""),
        "text": getattr(event, "text", None) or getattr(event, "content", "") or "",
        "chat_id": str(getattr(source, "chat_id", "") or getattr(event, "chat_id", "") or ""),
        "user_id": str(getattr(source, "user_id", "") or getattr(event, "user_id", "") or ""),
        "message_id": str(getattr(source, "message_id", "") or getattr(event, "message_id", "") or ""),
        "thread_id": str(getattr(source, "thread_id", "") or ""),
        "connection_id": str(getattr(source, "connection_id", None) or "default"),
        "chat_type": str(getattr(source, "chat_type", "") or ""),
        "user_name": str(getattr(source, "user_name", "") or ""),
    }
    if not str(payload["text"]).strip():
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{base}/api/runtime/turns", json=payload, headers=_auth(tenant))
        if response.status_code >= 400:
            logger.warning("Verxio rejected inbound turn (%s): %s", response.status_code, response.text[:200])
            return False
        return True
    except Exception:
        logger.warning("Verxio remote exec enqueue failed", exc_info=True)
        return False


async def deliver_outbound(payload: Dict[str, Any], send: Callable[..., Any]) -> None:
    """Call ``adapter.send`` for a queued outbound payload."""
    text = str(payload.get("text") or "")
    chat_id = str(payload.get("chat_id") or "")
    if not text or not chat_id:
        return
    reply_to = payload.get("reply_to") or None
    await send(chat_id, text, reply_to=str(reply_to) if reply_to else None)


class DeliveryConsumer:
    """Long-poll Verxio for outbound messages of every tenant this gateway serves."""

    def __init__(self, runner: Any) -> None:
        self._runner = runner
        self._pollers: Dict[str, asyncio.Task] = {}
        self._stopped = asyncio.Event()

    # ---------------------------------------------------------- discovery
    def _served_profiles(self) -> Dict[str, Optional[str]]:
        """profile name -> profile (None for the active/default profile)."""
        served: Dict[str, Optional[str]] = {"": None}
        for name in list(getattr(self._runner, "_profile_adapters", {}) or {}):
            served[name] = name
        return served

    def _adapter_for(self, profile: str, platform_value: str) -> Optional[Any]:
        from gateway.config import Platform

        try:
            platform = Platform(platform_value)
        except ValueError:
            return None
        if profile:
            adapters = (getattr(self._runner, "_profile_adapters", {}) or {}).get(profile) or {}
            adapter = adapters.get(platform)
            if adapter is not None:
                return adapter
        return (getattr(self._runner, "adapters", {}) or {}).get(platform)

    # -------------------------------------------------------------- polling
    async def _poll_tenant(self, profile: str, tenant: TenantIdentity) -> None:
        base = verxio_api_url()
        backoff = 1.0
        while not self._stopped.is_set():
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0)) as client:
                    response = await client.get(
                        f"{base}/api/runtime/deliveries",
                        params={"wait": 25},
                        headers=_auth(tenant),
                    )
                if response.status_code == 401:
                    logger.warning("Delivery poll unauthorized for tenant %s; stopping poller", tenant.key)
                    return
                response.raise_for_status()
                body = response.json() if response.content else {}
                item = body.get("delivery") if isinstance(body, dict) else None
                backoff = 1.0
                if not item:
                    continue
                await self._dispatch(profile, tenant, item)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Delivery poll failed tenant=%s", tenant.key, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _dispatch(self, profile: str, tenant: TenantIdentity, item: Dict[str, Any]) -> None:
        job_id = str(item.get("job_id") or "")
        platform_value = str(item.get("platform") or "")
        adapter = self._adapter_for(profile, platform_value)
        ok = False
        error: Optional[str] = None
        if adapter is None:
            error = f"no connected adapter for {platform_value!r}"
        else:
            try:
                await deliver_outbound(item, adapter.send)
                ok = True
            except Exception as exc:
                error = str(exc)[:300]
                logger.warning("Delivery send failed job=%s: %s", job_id, exc)
        if job_id:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    await client.post(
                        f"{verxio_api_url()}/api/runtime/deliveries/{job_id}/ack",
                        json={"ok": ok, "error": error},
                        headers=_auth(tenant),
                    )
            except Exception:
                logger.debug("Delivery ack failed job=%s", job_id, exc_info=True)

    async def run(self) -> None:
        """Keep one poller per served tenant; re-scan as profiles attach/detach."""
        if not remote_exec_enabled() or not verxio_api_url():
            return
        try:
            while not self._stopped.is_set():
                served = self._served_profiles()
                wanted: Dict[str, TenantIdentity] = {}
                for name, profile in served.items():
                    tenant = tenant_for_profile(profile)
                    if tenant is not None:
                        wanted[name] = tenant
                for name in list(self._pollers):
                    if name not in wanted or self._pollers[name].done():
                        self._pollers.pop(name).cancel()
                for name, tenant in wanted.items():
                    if name not in self._pollers:
                        self._pollers[name] = asyncio.create_task(
                            self._poll_tenant(name, tenant), name=f"verxio-deliver-{tenant.key}"
                        )
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    pass
        finally:
            for task in self._pollers.values():
                task.cancel()
            self._pollers.clear()

    def stop(self) -> None:
        self._stopped.set()
