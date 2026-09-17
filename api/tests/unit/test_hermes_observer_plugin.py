import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_PLUGIN = (
    Path(__file__).parents[2]
    / "domains"
    / "agents"
    / "scripts"
    / "hermes"
    / "plugins"
    / "agentbarn-observer"
    / "__init__.py"
)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("test_agentbarn_observer", _PLUGIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(**overrides):
    values = {
        "platform": SimpleNamespace(value="discord"),
        "chat_id": "channel-1",
        "parent_chat_id": None,
        "chat_type": "group",
        "guild_id": "guild-1",
        "scope_id": "guild-1",
        "user_id": "user-1",
        "message_id": "message-1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_discord_observation_mirrors_a_transcript_without_reimplementing_native_adapter_policy() -> None:
    plugin = _load_plugin()
    event = SimpleNamespace(
        source=_source(chat_type="dm", guild_id=None, scope_id=None, chat_id="dm-1"),
        message_id="message-1",
        text="must not leave the runtime",
    )

    gateway = MagicMock()
    gateway._session_key_for_source.return_value = "agent:main:discord:dm:dm-1"
    result = plugin._on_pre_gateway_dispatch(event=event, gateway=gateway)

    assert result is None
    assert [(entry["stage"], entry.get("error_code")) for entry in plugin._buffer] == [
        ("provider_observed", None),
    ]
    assert all("text" not in entry for entry in plugin._buffer)
    assert plugin._messages == [
        {
            "platform": "discord",
            "provider_message_id": "message-1",
            "session_key": "agent:main:discord:dm:dm-1",
            "channel_id": "dm-1",
            "thread_id": None,
            "direction": "INBOUND",
            "conversation_type": "DM",
            "sender_id": "user-1",
            "sender_name": None,
            "channel_name": None,
            "content": "must not leave the runtime",
            "occurred_at": plugin._messages[0]["occurred_at"],
        }
    ]


def test_delivered_obligation_is_mirrored_when_attempting_was_not_observed(tmp_path) -> None:
    plugin = _load_plugin()
    database = tmp_path / "state.db"
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            CREATE TABLE delivery_obligations (
                obligation_id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                platform TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                thread_id TEXT,
                content TEXT NOT NULL,
                state TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO delivery_obligations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("reply-1", "agent:main:discord:channel:C1", "discord", "C1", "T1", "fast reply", "delivered", 1.0),
        )

    plugin.poll_obligations(database, [0.0])
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    with patch.object(plugin.urllib.request, "urlopen", return_value=response) as urlopen:
        plugin._flush("https://ingest.test/communication-events", "test-key")

    payload = json.loads(urlopen.call_args.args[0].data)
    assert payload["messages"] == [
        {
            "platform": "discord",
            "provider_message_id": "outbound:reply-1",
            "session_key": "agent:main:discord:channel:C1",
            "channel_id": "C1",
            "thread_id": "T1",
            "direction": "OUTBOUND",
            "conversation_type": "CHANNEL",
            "content": "fast reply",
            "occurred_at": payload["messages"][0]["occurred_at"],
        }
    ]
