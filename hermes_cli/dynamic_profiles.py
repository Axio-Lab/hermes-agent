"""Hot attach/detach of multiplex profiles for the Verxio worker pool.

The registry is file-backed so the dashboard process (which receives
``/internal/profiles/{tenant}/attach``) and the gateway process (which serves
``/v1/runs`` and channel turns) agree on the tenant → home mapping. Readers
cache on mtime, so lookups stay cheap on the hot path.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_CACHE: Dict[str, Path] = {}
_CACHE_MTIME: float = -1.0
_CACHE_PATH: Path | None = None


def registry_path() -> Path:
    explicit = os.getenv("VERXIO_DYNAMIC_PROFILES_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    # Process (worker) home, never the per-request tenant override: the
    # registry must be one file shared by every tenant scope.
    from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(None)
    try:
        base = get_hermes_home()
    finally:
        reset_hermes_home_override(token)
    return base / "verxio" / "dynamic_profiles.json"


def _load_locked() -> Dict[str, Path]:
    global _CACHE, _CACHE_MTIME, _CACHE_PATH
    path = registry_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        if _CACHE_PATH != path or _CACHE:
            _CACHE, _CACHE_MTIME, _CACHE_PATH = {}, -1.0, path
        return _CACHE
    if _CACHE_PATH == path and mtime == _CACHE_MTIME:
        return _CACHE
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        logger.warning("Dynamic profile registry unreadable at %s", path, exc_info=True)
        raw = {}
    loaded: Dict[str, Path] = {}
    if isinstance(raw, dict):
        for name, home in raw.items():
            if isinstance(name, str) and isinstance(home, str) and name and home:
                loaded[name] = Path(home)
    _CACHE, _CACHE_MTIME, _CACHE_PATH = loaded, mtime, path
    return _CACHE


def _save_locked(entries: Dict[str, Path]) -> None:
    global _CACHE, _CACHE_MTIME, _CACHE_PATH
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({name: str(home) for name, home in sorted(entries.items())}, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    # Force a distinct mtime for sub-second consecutive writes.
    now = time.time()
    try:
        os.utime(path, (now, now))
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    _CACHE, _CACHE_MTIME, _CACHE_PATH = dict(entries), mtime, path


def attach_profile(name: str, home: str | Path) -> Path:
    profile = _safe_name(name)
    path = Path(home).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        entries = dict(_load_locked())
        entries[profile] = path
        _save_locked(entries)
    logger.info("Attached dynamic profile %s home=%s", profile, path)
    return path


def detach_profile(name: str) -> bool:
    profile = _safe_name(name)
    with _LOCK:
        entries = dict(_load_locked())
        removed = entries.pop(profile, None)
        if removed is not None:
            _save_locked(entries)
    if removed is not None:
        logger.info("Detached dynamic profile %s", profile)
        return True
    return False


def list_dynamic_profiles() -> List[Tuple[str, Path]]:
    with _LOCK:
        return sorted(_load_locked().items(), key=lambda item: item[0])


def get_dynamic_home(name: str) -> Path | None:
    with _LOCK:
        return _load_locked().get(_safe_name(name))


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
