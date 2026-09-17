import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

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
