"""Paired WhatsApp accounts must be able to message without a manual allowlist."""

from __future__ import annotations

import json

from gateway.whatsapp_identity import (
    ensure_paired_whatsapp_allowlist,
    merge_whatsapp_allowed_users,
    paired_whatsapp_identities,
)


def _write_creds(session_dir, *, phone: str, lid: str) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "creds.json").write_text(
        json.dumps(
            {
                "me": {
                    "id": f"{phone}:10@s.whatsapp.net",
                    "lid": f"{lid}:10@lid",
                }
            }
        ),
        encoding="utf-8",
    )


def test_paired_whatsapp_identities_reads_phone_and_lid(tmp_path):
    session_dir = tmp_path / "sessions" / "default"
    _write_creds(session_dir, phone="2347068827272", lid="237889665401044")
    assert paired_whatsapp_identities(session_dir) == {"2347068827272", "237889665401044"}


def test_merge_keeps_star_and_existing_entries():
    assert merge_whatsapp_allowed_users("*", {"2347068827272"}) == "*"
    assert merge_whatsapp_allowed_users(
        "07068827272",
        {"2347068827272", "237889665401044"},
    ) == "07068827272,237889665401044"
    assert merge_whatsapp_allowed_users("", {"2347068827272"}) == "2347068827272"


def test_ensure_paired_allowlist_seeds_env_from_creds(tmp_path, monkeypatch):
    session_dir = tmp_path / "platforms" / "whatsapp" / "sessions" / "default"
    _write_creds(session_dir, phone="2347068827272", lid="237889665401044")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("WHATSAPP_ALLOWED_USERS", raising=False)
    saved: dict[str, str] = {}

    def fake_save(key, value):
        saved[key] = value

    monkeypatch.setattr("hermes_cli.config.save_env_value", fake_save)
    merged = ensure_paired_whatsapp_allowlist(persist=True)
    assert "2347068827272" in merged.split(",")
    assert "237889665401044" in merged.split(",")
    assert saved["WHATSAPP_ALLOWED_USERS"] == merged
