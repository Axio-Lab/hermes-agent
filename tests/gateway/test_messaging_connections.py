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
