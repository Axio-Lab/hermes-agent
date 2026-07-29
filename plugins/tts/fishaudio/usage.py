"""Profile-local Fish Audio usage quotas, concurrency, and failure breaker."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

USAGE_VERSION = 1
DEFAULT_QUOTAS: Dict[str, Any] = {
    "enabled": True,
    "tts_chars_per_day": 500_000,
    "asr_bytes_per_day": 524_288_000,
    "asr_minutes_per_day": 600,
    "voice_create_per_day": 10,
    "voice_design_per_5m": 3,
    "voice_persist_per_day": 10,
    "transcribe_tool_per_day": 100,
}
DEFAULT_LIMITS: Dict[str, Any] = {
    "max_concurrent_requests": 3,
    "failure_window_seconds": 300,
    "max_failures_per_window": 8,
}

_lock = threading.RLock()
_request_sema: Optional[threading.BoundedSemaphore] = None
_request_sema_size = 0
_failures: list[float] = []
_circuit_open_until = 0.0


class QuotaExceededError(RuntimeError):
    """Raised when a local Fish Audio quota would be exceeded."""


class CircuitOpenError(RuntimeError):
    """Raised when Fish Audio is temporarily unavailable due to failures."""


def _usage_path() -> Path:
    return get_hermes_home() / "fishaudio" / "usage.v1.json"


def _load_fishaudio_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
    except Exception:
        return {}
    section = cfg.get("fishaudio") if isinstance(cfg, dict) else None
    return section if isinstance(section, dict) else {}


def quota_config() -> Dict[str, Any]:
    section = _load_fishaudio_config()
    quotas = section.get("quotas") if isinstance(section.get("quotas"), dict) else {}
    merged = dict(DEFAULT_QUOTAS)
    for key, default in DEFAULT_QUOTAS.items():
        value = quotas.get(key, default)
        if key == "enabled":
            merged[key] = bool(value)
        else:
            try:
                merged[key] = max(0, int(value))
            except (TypeError, ValueError):
                merged[key] = default
    return merged


def limits_config() -> Dict[str, Any]:
    section = _load_fishaudio_config()
    limits = section.get("limits") if isinstance(section.get("limits"), dict) else {}
    merged = dict(DEFAULT_LIMITS)
    for key, default in DEFAULT_LIMITS.items():
        value = limits.get(key, default)
        try:
            merged[key] = max(1, int(value))
        except (TypeError, ValueError):
            merged[key] = default
    return merged


def _day_key(now: Optional[float] = None) -> str:
    stamp = datetime.fromtimestamp(now or time.time(), tz=timezone.utc)
    return stamp.strftime("%Y-%m-%d")


def _empty_usage(day: str) -> Dict[str, Any]:
    return {
        "version": USAGE_VERSION,
        "day": day,
        "tts_chars": 0,
        "asr_bytes": 0,
        "asr_duration_sec": 0.0,
        "voice_create": 0,
        "voice_persist": 0,
        "transcribe_tool_calls": 0,
        "voice_design_windows": {},
    }


def _load_usage() -> Dict[str, Any]:
    path = _usage_path()
    day = _day_key()
    if not path.is_file():
        return _empty_usage(day)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_usage(day)
    if not isinstance(data, dict) or data.get("day") != day:
        return _empty_usage(day)
    data.setdefault("voice_design_windows", {})
    return data


def _save_usage(data: Dict[str, Any]) -> None:
    path = _usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def check_and_consume(
    operation: str,
    units: int | float = 1,
    *,
    session_key: Optional[str] = None,
) -> None:
    """Atomically check and consume units for ``operation``."""
    quotas = quota_config()
    if not quotas.get("enabled", True):
        return
    if units < 0:
        raise ValueError("units must be non-negative")
    if units == 0:
        return

    with _lock:
        data = _load_usage()
        now = time.time()

        if operation == "tts_chars":
            nxt = int(data.get("tts_chars", 0)) + int(units)
            if nxt > int(quotas["tts_chars_per_day"]):
                raise QuotaExceededError(
                    "Fish Audio daily TTS character quota exceeded"
                )
            data["tts_chars"] = nxt
        elif operation == "asr_bytes":
            nxt = int(data.get("asr_bytes", 0)) + int(units)
            if nxt > int(quotas["asr_bytes_per_day"]):
                raise QuotaExceededError("Fish Audio daily ASR byte quota exceeded")
            data["asr_bytes"] = nxt
        elif operation == "asr_duration_sec":
            nxt = float(data.get("asr_duration_sec", 0.0)) + float(units)
            if nxt > float(quotas["asr_minutes_per_day"]) * 60.0:
                raise QuotaExceededError(
                    "Fish Audio daily ASR minutes quota exceeded"
                )
            data["asr_duration_sec"] = nxt
        elif operation == "voice_create":
            nxt = int(data.get("voice_create", 0)) + int(units)
            if nxt > int(quotas["voice_create_per_day"]):
                raise QuotaExceededError(
                    "Fish Audio daily voice create quota exceeded"
                )
            data["voice_create"] = nxt
        elif operation == "voice_persist":
            nxt = int(data.get("voice_persist", 0)) + int(units)
            if nxt > int(quotas["voice_persist_per_day"]):
                raise QuotaExceededError(
                    "Fish Audio daily voice persist quota exceeded"
                )
            data["voice_persist"] = nxt
        elif operation == "transcribe_tool":
            nxt = int(data.get("transcribe_tool_calls", 0)) + int(units)
            if nxt > int(quotas["transcribe_tool_per_day"]):
                raise QuotaExceededError(
                    "Fish Audio daily transcription tool quota exceeded"
                )
            data["transcribe_tool_calls"] = nxt
        elif operation == "voice_design":
            windows = data.setdefault("voice_design_windows", {})
            if not isinstance(windows, dict):
                windows = {}
                data["voice_design_windows"] = windows
            bucket = int(now // 300)
            bucket_key = f"{bucket}:{session_key or 'profile'}"
            count = int(windows.get(bucket_key, 0)) + int(units)
            if count > int(quotas["voice_design_per_5m"]):
                raise QuotaExceededError(
                    "Fish Audio voice design rate limit exceeded "
                    f"({quotas['voice_design_per_5m']} per 5 minutes)"
                )
            windows[bucket_key] = count
            cutoff = bucket - 3
            for stale in list(windows):
                try:
                    stale_bucket = int(str(stale).split(":", 1)[0])
                except ValueError:
                    windows.pop(stale, None)
                    continue
                if stale_bucket < cutoff:
                    windows.pop(stale, None)
        else:
            raise ValueError(f"unknown Fish Audio quota operation: {operation}")

        _save_usage(data)


def _ensure_semaphore() -> threading.BoundedSemaphore:
    global _request_sema, _request_sema_size
    size = int(limits_config()["max_concurrent_requests"])
    if _request_sema is None or _request_sema_size != size:
        _request_sema = threading.BoundedSemaphore(size)
        _request_sema_size = size
    return _request_sema


def assert_circuit_closed() -> None:
    with _lock:
        if time.time() < _circuit_open_until:
            raise CircuitOpenError(
                "Fish Audio temporarily unavailable after repeated failures"
            )


def record_success() -> None:
    global _circuit_open_until
    with _lock:
        _failures.clear()
        _circuit_open_until = 0.0


def record_failure() -> None:
    global _circuit_open_until
    limits = limits_config()
    window = float(limits["failure_window_seconds"])
    max_failures = int(limits["max_failures_per_window"])
    now = time.time()
    with _lock:
        _failures[:] = [ts for ts in _failures if now - ts <= window]
        _failures.append(now)
        if len(_failures) >= max_failures:
            _circuit_open_until = now + window
            logger.warning(
                "Fish Audio circuit open for %.0fs after %d failures",
                window,
                len(_failures),
            )


@contextmanager
def request_slot() -> Iterator[None]:
    """Acquire concurrency slot and enforce the failure circuit breaker."""
    assert_circuit_closed()
    sema = _ensure_semaphore()
    acquired = sema.acquire(blocking=True, timeout=30.0)
    if not acquired:
        raise RuntimeError("Fish Audio is busy; try again shortly")
    try:
        yield
    finally:
        sema.release()


def reset_for_tests() -> None:
    """Clear in-memory breaker/semaphore state (tests only)."""
    global _request_sema, _request_sema_size, _circuit_open_until
    with _lock:
        _failures.clear()
        _circuit_open_until = 0.0
        _request_sema = None
        _request_sema_size = 0
        path = _usage_path()
        if path.is_file():
            path.unlink(missing_ok=True)
