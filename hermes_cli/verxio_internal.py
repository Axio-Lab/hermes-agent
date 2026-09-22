"""Internal control + per-tenant dashboard scoping for hosted Verxio workers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from hermes_cli.dynamic_profiles import attach_profile, detach_profile, get_dynamic_home, list_dynamic_profiles

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["verxio-internal"])


class AttachRequest(BaseModel):
    home: str = Field(min_length=1)
    tenant: str | None = None


def _internal_token() -> str:
    return os.getenv("VERXIO_INTERNAL_TOKEN", "").strip()


def _authorize(request: Request) -> None:
    expected = _internal_token()
    if not expected:
        return
    provided = (request.headers.get("X-Verxio-Internal-Token") or "").strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="Internal token required")


@router.post("/profiles/{tenant}/attach")
def attach(tenant: str, payload: AttachRequest, request: Request) -> dict[str, Any]:
    _authorize(request)
    home = attach_profile(payload.tenant or tenant, payload.home)
    return {"ok": True, "tenant": tenant, "home": str(home)}


@router.post("/profiles/{tenant}/detach")
def detach(tenant: str, request: Request) -> dict[str, Any]:
    _authorize(request)
    return {"ok": detach_profile(tenant), "tenant": tenant}


@router.get("/profiles")
def list_profiles(request: Request) -> dict[str, Any]:
    _authorize(request)
    return {
        "profiles": [{"name": name, "home": str(home)} for name, home in list_dynamic_profiles()]
    }


class TenantScopeMiddleware(BaseHTTPMiddleware):
    """Honor ``/p/{tenant}/...`` and ``X-Hermes-Profile`` for dashboard calls."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        tenant = request.headers.get("X-Hermes-Profile", "").strip()
        prefix = ""
        if path.startswith("/p/"):
            parts = path.split("/", 3)
            if len(parts) >= 3 and parts[2]:
                tenant = parts[2]
                prefix = f"/p/{tenant}"
                remainder = "/" + parts[3] if len(parts) > 3 else "/"
                request.scope["path"] = remainder or "/"
                request.scope["raw_path"] = remainder.encode("utf-8")
        if tenant:
            home = get_dynamic_home(tenant)
            if home is None:
                try:
                    from hermes_cli.profiles import get_profile_dir

                    home = get_profile_dir(tenant)
                except Exception:
                    home = None
            if home is not None:
                from hermes_constants import reset_hermes_home_override, set_hermes_home_override

                # Same two seams as gateway._profile_runtime_scope: the tenant's
                # home for config/skills/sessions AND its .env as the only
                # credential source, so oneshot/model calls never read a
                # neighbour's keys from the worker process environment.
                secret_token = None
                token = set_hermes_home_override(str(home))
                try:
                    from agent.secret_scope import build_profile_secret_scope, set_secret_scope

                    secret_token = set_secret_scope(build_profile_secret_scope(Path(home)))
                except Exception:
                    logger.debug("secret scope unavailable for tenant %s", tenant, exc_info=True)
                try:
                    response = await call_next(request)
                finally:
                    if secret_token is not None:
                        from agent.secret_scope import reset_secret_scope

                        reset_secret_scope(secret_token)
                    reset_hermes_home_override(token)
                if prefix:
                    response.headers["X-Hermes-Profile"] = tenant
                return response
        return await call_next(request)


def mount_verxio_routes(app: FastAPI) -> None:
    if getattr(app.state, "verxio_routes_mounted", False):
        return
    app.add_middleware(TenantScopeMiddleware)
    app.include_router(router)
    app.state.verxio_routes_mounted = True
    logger.info("Mounted Verxio internal profile routes")
