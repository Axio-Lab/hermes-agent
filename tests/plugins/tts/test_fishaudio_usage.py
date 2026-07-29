"""Tests for Fish Audio profile quotas and circuit breaker."""

from __future__ import annotations

import threading
import time

import pytest

from plugins.tts.fishaudio import usage


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    usage.reset_for_tests()
    yield
    usage.reset_for_tests()


def test_tts_chars_allow_then_deny(monkeypatch):
    monkeypatch.setattr(
        usage,
        "quota_config",
        lambda: {**usage.DEFAULT_QUOTAS, "tts_chars_per_day": 10},
    )
    usage.check_and_consume("tts_chars", 6)
    usage.check_and_consume("tts_chars", 4)
    with pytest.raises(usage.QuotaExceededError):
        usage.check_and_consume("tts_chars", 1)


def test_asr_bytes_and_minutes(monkeypatch):
    monkeypatch.setattr(
        usage,
        "quota_config",
        lambda: {
            **usage.DEFAULT_QUOTAS,
            "asr_bytes_per_day": 100,
            "asr_minutes_per_day": 1,
        },
    )
    usage.check_and_consume("asr_bytes", 100)
    with pytest.raises(usage.QuotaExceededError):
        usage.check_and_consume("asr_bytes", 1)
    usage.check_and_consume("asr_duration_sec", 60)
    with pytest.raises(usage.QuotaExceededError):
        usage.check_and_consume("asr_duration_sec", 0.1)


def test_voice_design_window(monkeypatch):
    monkeypatch.setattr(
        usage,
        "quota_config",
        lambda: {**usage.DEFAULT_QUOTAS, "voice_design_per_5m": 2},
    )
    usage.check_and_consume("voice_design", 1, session_key="a")
    usage.check_and_consume("voice_design", 1, session_key="a")
    with pytest.raises(usage.QuotaExceededError):
        usage.check_and_consume("voice_design", 1, session_key="a")


def test_circuit_opens_after_failures(monkeypatch):
    monkeypatch.setattr(
        usage,
        "limits_config",
        lambda: {
            "max_concurrent_requests": 2,
            "failure_window_seconds": 60,
            "max_failures_per_window": 3,
        },
    )
    usage.record_failure()
    usage.record_failure()
    usage.assert_circuit_closed()
    usage.record_failure()
    with pytest.raises(usage.CircuitOpenError):
        usage.assert_circuit_closed()
    usage.record_success()
    usage.assert_circuit_closed()


def test_request_slot_limits_concurrency(monkeypatch):
    monkeypatch.setattr(
        usage,
        "limits_config",
        lambda: {
            "max_concurrent_requests": 1,
            "failure_window_seconds": 60,
            "max_failures_per_window": 8,
        },
    )
    usage.reset_for_tests()
    entered = threading.Event()
    release = threading.Event()
    results = []

    def worker():
        try:
            with usage.request_slot():
                entered.set()
                release.wait(timeout=2)
                results.append("ok")
        except Exception as exc:
            results.append(type(exc).__name__)

    t1 = threading.Thread(target=worker)
    t1.start()
    assert entered.wait(timeout=1)
    # Second acquire should block until first releases; use short timeout path
    # by monkeypatching BoundedSemaphore acquire via a parallel thread check.
    blocked = threading.Event()

    def waiter():
        sema = usage._ensure_semaphore()
        ok = sema.acquire(blocking=True, timeout=0.2)
        results.append("acquired" if ok else "blocked")
        if ok:
            sema.release()
        blocked.set()

    t2 = threading.Thread(target=waiter)
    t2.start()
    assert blocked.wait(timeout=1)
    release.set()
    t1.join(timeout=2)
    t2.join(timeout=2)
    assert "blocked" in results
    assert "ok" in results
