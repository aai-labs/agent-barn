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


def _status_file(tmp_path: Path, platforms: dict) -> Path:
    path = tmp_path / "gateway_state.json"
    path.write_text(json.dumps({"platforms": platforms}), encoding="utf-8")
    return path


def _stages(plugin) -> list[tuple[str, str]]:
    return [(entry["stage"], entry["platform"]) for entry in plugin._buffer]


def test_a_bot_reports_only_its_own_platforms(tmp_path) -> None:
    plugin = _load_plugin()
    status = _status_file(
        tmp_path,
        {
            "api_server": {"state": "connected"},
            "bot-a:slack": {"state": "connected"},
            "bot-b:telegram": {"state": "fatal", "error_code": "invalid_token"},
        },
    )

    plugin.poll_platform_health(status, {}, "bot-a")

    assert _stages(plugin) == [("connection_connected", "slack")]


def test_a_bot_reports_a_failure_and_its_recovery(tmp_path) -> None:
    plugin = _load_plugin()
    health: dict[str, str] = {}

    plugin.poll_platform_health(_status_file(tmp_path, {"bot-a:slack": {"state": "fatal"}}), health, "bot-a")
    plugin.poll_platform_health(_status_file(tmp_path, {"bot-a:slack": {"state": "connected"}}), health, "bot-a")

    assert _stages(plugin) == [("connection_error", "slack"), ("connection_connected", "slack")]


def test_a_parent_ignores_its_bots_platforms(tmp_path) -> None:
    plugin = _load_plugin()
    status = _status_file(tmp_path, {"slack": {"state": "connected"}, "bot-a:telegram": {"state": "connected"}})

    plugin.poll_platform_health(status, {})

    assert _stages(plugin) == [("connection_connected", "slack")]


def test_a_bot_reads_the_gateway_status_from_its_parents_home() -> None:
    plugin = _load_plugin()

    assert plugin._status_source(Path("/opt/data/profiles/bot-a")) == (Path("/opt/data/gateway_state.json"), "bot-a")


def test_a_parent_reads_the_gateway_status_from_its_own_home() -> None:
    plugin = _load_plugin()

    assert plugin._status_source(Path("/opt/data")) == (Path("/opt/data/gateway_state.json"), None)
