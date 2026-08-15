"""Tests for multi-account messaging connections + session key isolation."""

from gateway.connections import (
    DEFAULT_CONNECTION_ID,
    ConnectionRecord,
    connection_env_key,
    ensure_default_connection,
    is_default_connection,
    join_csv_tokens,
    split_csv_tokens,
)
from gateway.config import Platform
from gateway.session import SessionSource, build_session_key


def test_connection_env_key_default_is_legacy():
    assert connection_env_key("TELEGRAM_BOT_TOKEN", None) == "TELEGRAM_BOT_TOKEN"
    assert connection_env_key("TELEGRAM_BOT_TOKEN", DEFAULT_CONNECTION_ID) == "TELEGRAM_BOT_TOKEN"
    assert connection_env_key("TELEGRAM_BOT_TOKEN", "sales") == "TELEGRAM_BOT_TOKEN__CONN_SALES"


def test_ensure_default_connection_when_legacy_present():
    records = ensure_default_connection(
        "telegram",
        [],
        has_legacy_credentials=True,
        label="Default",
    )
    assert len(records) == 1
    assert records[0].id == DEFAULT_CONNECTION_ID


def test_ensure_default_connection_skips_empty_without_credentials():
    records = ensure_default_connection(
        "discord",
        [],
        has_legacy_credentials=False,
        label="Default",
    )
    assert records == []


def test_recover_skips_platforms_without_env_credentials(tmp_path, monkeypatch):
    from gateway.connections import recover_connections_for_platform

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "\n".join(
            [
                "platforms:",
                "  discord:",
                "    enabled: true",
                "    connections:",
                "      - id: default",
                "        label: Default",
                "        enabled: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    records, changed = recover_connections_for_platform(
        "discord", {}, persist=True
    )
    assert records == []
    assert changed is True
    saved = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "enabled: false" in saved
    assert "id: default" not in saved


def test_session_key_unchanged_without_connection_id():
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="99", chat_type="dm")
    assert build_session_key(source) == "agent:main:telegram:dm:99"


def test_session_key_suffix_for_non_default_connection():
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="99",
        chat_type="dm",
        connection_id="sales",
    )
    assert build_session_key(source) == "agent:main:telegram:dm:99:c_sales"


def test_session_key_default_connection_id_omitted():
    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="chan",
        chat_type="channel",
        connection_id="default",
    )
    assert build_session_key(source) == "agent:main:discord:channel:chan"


def test_csv_token_helpers():
    assert split_csv_tokens("a, b,,c") == ["a", "b", "c"]
    assert join_csv_tokens(["a", "b"]) == "a,b"


def test_connection_record_roundtrip():
    record = ConnectionRecord(
        id="conn_ab12",
        label="Ops",
        enabled=True,
        identity="@ops_bot",
        meta={"team_id": "T1"},
    )
    restored = ConnectionRecord.from_dict(record.to_dict())
    assert restored.id == "conn_ab12"
    assert restored.identity == "@ops_bot"
    assert restored.meta["team_id"] == "T1"
    assert is_default_connection(DEFAULT_CONNECTION_ID)
    assert not is_default_connection("sales")


def test_merge_env_discovered_connections_restores_unique_tokens():
    from gateway.connections import merge_env_discovered_connections

    env = {
        "TELEGRAM_BOT_TOKEN": "default-token",
        "TELEGRAM_BOT_TOKEN__CONN_TELE_AAAA1111": "extra-token",
        # Orphan that duplicates Default — must not become a second row.
        "TELEGRAM_BOT_TOKEN__CONN_TELE_BBBB2222": "default-token",
    }
    records, changed = merge_env_discovered_connections(
        "telegram",
        [ConnectionRecord(id=DEFAULT_CONNECTION_ID, label="Default")],
        env,
    )
    assert changed is True
    ids = [r.id for r in records]
    assert ids == [DEFAULT_CONNECTION_ID, "tele_aaaa1111"]
    assert "tele_bbbb2222" not in ids


def test_merge_env_discovered_connections_noop_when_already_present():
    from gateway.connections import merge_env_discovered_connections

    env = {"TELEGRAM_BOT_TOKEN__CONN_TELE_AAAA1111": "extra-token"}
    records, changed = merge_env_discovered_connections(
        "telegram",
        [
            ConnectionRecord(id=DEFAULT_CONNECTION_ID, label="Default"),
            ConnectionRecord(id="tele_aaaa1111", label="AI Pundit"),
        ],
        env,
    )
    assert changed is False
    assert len(records) == 2


def test_expand_slack_connections_from_csv():
    from gateway.connections import expand_slack_connections

    env = {"SLACK_BOT_TOKEN": "xoxb-a,xoxb-b"}
    records, changed = expand_slack_connections([], env)
    assert changed is True
    assert [r.id for r in records] == [DEFAULT_CONNECTION_ID, "slack_1"]
    assert records[1].meta.get("token_index") == 1


def test_recover_connections_discord_from_env(tmp_path, monkeypatch):
    from gateway.connections import recover_connections_for_platform

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("platforms: {}\n", encoding="utf-8")
    env = {
        "DISCORD_BOT_TOKEN": "default-discord",
        "DISCORD_BOT_TOKEN__CONN_DISC_ABCDEF12": "second-discord",
        "DISCORD_CONNECTION_LABEL__CONN_DISC_ABCDEF12": "Ops Bot",
    }
    records, changed = recover_connections_for_platform(
        "discord", env, persist=True
    )
    assert changed is True
    assert [r.id for r in records] == [DEFAULT_CONNECTION_ID, "disc_abcdef12"]
    assert records[1].label == "Ops Bot"
    saved = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "disc_abcdef12" in saved
    assert "Ops Bot" in saved


def test_persist_and_read_connection_label(tmp_path, monkeypatch):
    from gateway.connections import persist_connection_label, read_connection_label

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    persist_connection_label("telegram", "tele_f4f2e55f", "AI Pundit")
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_CONNECTION_LABEL__CONN_TELE_F4F2E55F=AI Pundit" in env_text
    assert read_connection_label("telegram", "tele_f4f2e55f") == "AI Pundit"


def test_webhook_and_api_server_are_shared_multi_account():
    from gateway.connections import (
        MULTI_ACCOUNT_PLATFORMS,
        PRIMARY_CREDENTIAL_ENV,
        SHARED_ADAPTER_PLATFORMS,
        connection_env_key,
    )

    assert "webhook" in MULTI_ACCOUNT_PLATFORMS
    assert "api_server" in MULTI_ACCOUNT_PLATFORMS
    assert "webhook" in SHARED_ADAPTER_PLATFORMS
    assert "api_server" in SHARED_ADAPTER_PLATFORMS
    assert PRIMARY_CREDENTIAL_ENV["webhook"] == "WEBHOOK_SECRET"
    assert PRIMARY_CREDENTIAL_ENV["api_server"] == "API_SERVER_KEY"
    assert connection_env_key("WEBHOOK_SECRET", "sales") == "WEBHOOK_SECRET__CONN_SALES"
    assert connection_env_key("API_SERVER_KEY", "ops") == "API_SERVER_KEY__CONN_OPS"


def test_webhook_recover_keeps_default_when_enabled(tmp_path, monkeypatch):
    from gateway.connections import DEFAULT_CONNECTION_ID, recover_connections_for_platform

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "\n".join(
            [
                "platforms:",
                "  webhook:",
                "    enabled: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    records, _ = recover_connections_for_platform(
        "webhook", {"WEBHOOK_ENABLED": "true"}, persist=True
    )
    assert [r.id for r in records] == [DEFAULT_CONNECTION_ID]


def test_resolve_whatsapp_session_dir_prefers_legacy_creds(tmp_path, monkeypatch):
    from gateway.connections import resolve_whatsapp_session_dir

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    legacy = tmp_path / "platforms" / "whatsapp" / "session"
    legacy.mkdir(parents=True)
    (legacy / "creds.json").write_text("{}", encoding="utf-8")

    assert resolve_whatsapp_session_dir() == legacy
    assert resolve_whatsapp_session_dir("default") == legacy


def test_resolve_whatsapp_session_dir_uses_multi_session_default(tmp_path, monkeypatch):
    from gateway.connections import resolve_whatsapp_session_dir

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    expected = tmp_path / "platforms" / "whatsapp" / "sessions" / "default"

    assert resolve_whatsapp_session_dir() == expected
    assert resolve_whatsapp_session_dir("default") == expected
