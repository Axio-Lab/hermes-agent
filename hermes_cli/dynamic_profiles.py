"""Hot attach/detach of multiplex profiles for the Verxio worker pool."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_DYNAMIC: Dict[str, Path] = {}


def attach_profile(name: str, home: str | Path) -> Path:
    profile = _safe_name(name)
    path = Path(home).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        _DYNAMIC[profile] = path
    logger.info("Attached dynamic profile %s home=%s", profile, path)
    return path


def detach_profile(name: str) -> bool:
    profile = _safe_name(name)
    with _LOCK:
        removed = _DYNAMIC.pop(profile, None)
    if removed is not None:
        logger.info("Detached dynamic profile %s", profile)
        return True
    return False


def list_dynamic_profiles() -> List[Tuple[str, Path]]:
    with _LOCK:
        return sorted(_DYNAMIC.items(), key=lambda item: item[0])


def get_dynamic_home(name: str) -> Path | None:
    with _LOCK:
        return _DYNAMIC.get(_safe_name(name))


def profiles_to_serve_extended(multiplex: bool) -> List[Tuple[str, Path]]:
    """``profiles_to_serve`` plus hot-attached Verxio tenants."""
    from hermes_cli.profiles import profiles_to_serve

    base = list(profiles_to_serve(multiplex))
    seen = {name for name, _home in base}
    extra: List[Tuple[str, Path]] = []
    for name, home in list_dynamic_profiles():
        if name not in seen:
            extra.append((name, home))
    return base + extra


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in (name or "").strip())
    return cleaned or "tenant"
