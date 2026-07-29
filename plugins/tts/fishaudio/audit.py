"""Append-only Fish Audio ops audit log (no secrets, transcripts, or paths)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

ALLOWED_FIELDS = frozenset(
    {
        "ts",
        "op",
        "outcome",
        "http_status",
        "duration_ms",
        "units",
        "provider_op",
        "session_id_hash",
        "actor_hash",
        "error_class",
    }
)
FORBIDDEN_SUBSTRINGS = (
    "transcript",
    "path",
    "handle",
    "preview",
    "authorization",
    "api_key",
    "bearer",
    "fishatt_",
    "fishpreview_",
)
DEFAULT_AUDIT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_AUDIT_ROTATE_KEEP = 3

_lock = threading.Lock()


def _load_audit_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("fishaudio") if isinstance(cfg, dict) else None
        audit = section.get("audit") if isinstance(section, dict) else None
        return audit if isinstance(audit, dict) else {}
    except Exception:
        return {}


def _load_retention_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("fishaudio") if isinstance(cfg, dict) else None
        retention = section.get("retention") if isinstance(section, dict) else None
        return retention if isinstance(retention, dict) else {}
    except Exception:
        return {}


def audit_enabled() -> bool:
    cfg = _load_audit_config()
    return bool(cfg.get("enabled", True))


def audit_path() -> Path:
    return get_hermes_home() / "logs" / "fishaudio-audit.jsonl"


def _hash_id(value: Optional[str]) -> Optional[str]:
    clean = str(value or "").strip()
    if not clean:
        return None
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


def _rotate_if_needed(path: Path) -> None:
    retention = _load_retention_config()
    try:
        max_bytes = int(retention.get("audit_max_bytes", DEFAULT_AUDIT_MAX_BYTES))
    except (TypeError, ValueError):
        max_bytes = DEFAULT_AUDIT_MAX_BYTES
    try:
        keep = int(retention.get("audit_rotate_keep", DEFAULT_AUDIT_ROTATE_KEEP))
    except (TypeError, ValueError):
        keep = DEFAULT_AUDIT_ROTATE_KEEP
    max_bytes = max(1024, max_bytes)
    keep = max(1, min(20, keep))
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < max_bytes:
        return
    # Rotate: .jsonl -> .jsonl.1 ... keep N.
    for index in range(keep, 0, -1):
        src = path if index == 1 else path.with_suffix(path.suffix + f".{index - 1}")
        dst = path.with_suffix(path.suffix + f".{index}")
        if index == keep and dst.exists():
            try:
                dst.unlink()
            except OSError:
                pass
        if src.exists():
            try:
                os.replace(src, dst)
            except OSError:
                pass


def audit_event(
    *,
    op: str,
    outcome: str,
    provider_op: str,
    http_status: Optional[int] = None,
    duration_ms: Optional[int] = None,
    units: Optional[int | float] = None,
    session_id: Optional[str] = None,
    actor: Optional[str] = None,
    error_class: Optional[str] = None,
) -> None:
    """Append one redacted audit line. Never logs bodies, paths, or transcripts."""
    if not audit_enabled():
        return
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "op": str(op)[:80],
        "outcome": str(outcome)[:40],
        "provider_op": str(provider_op)[:40],
    }
    if http_status is not None:
        record["http_status"] = int(http_status)
    if duration_ms is not None:
        record["duration_ms"] = max(0, int(duration_ms))
    if units is not None:
        record["units"] = units if isinstance(units, (int, float)) else 0
    session_hash = _hash_id(session_id)
    if session_hash:
        record["session_id_hash"] = session_hash
    actor_hash = _hash_id(actor)
    if actor_hash:
        record["actor_hash"] = actor_hash
    if error_class:
        record["error_class"] = str(error_class)[:80]

    # Defense in depth: drop unexpected keys and scan serialized text.
    clean = {key: value for key, value in record.items() if key in ALLOWED_FIELDS}
    line = json.dumps(clean, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    lowered = line.lower()
    if any(token in lowered for token in FORBIDDEN_SUBSTRINGS):
        logger.warning("Fish audit line suppressed due to forbidden content")
        return

    path = audit_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        _rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
