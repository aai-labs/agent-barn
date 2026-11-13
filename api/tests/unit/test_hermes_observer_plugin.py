import asyncio
import importlib.util
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

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

_PROFILE_BOT = "0000000a-0000-4000-8000-00000000000a"
_PARENT_INSTALL = "/opt/data/plugins/agentbarn-observer/__init__.py"
_BOT_INSTALL = f"/opt/data/profiles/{_PROFILE_BOT}/plugins/agentbarn-observer/__init__.py"


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


def test_identity_falls_back_to_the_environment_for_a_shallow_install() -> None:
    plugin = _load_plugin()
    plugin.__file__ = "/plugin/__init__.py"

    assert plugin._identity() is os.environ


def _gateway_runner():
    runner = MagicMock()
    runner._session_key_for_source.return_value = "agent:main:discord:channel:channel-1"
    return runner


def _inbound(**overrides):
    values = {"source": _source(), "message_id": "message-1", "text": "hello", "internal": False}
    values.update(overrides)
    return SimpleNamespace(**values)


def _adapter_class(calls: list):
    class Adapter:
        async def handle_message(self, event):
            calls.append(event)

    return Adapter


def _arrive(plugin, event, runner=None):
    calls: list = []
    adapter_class = _adapter_class(calls)
    plugin._patch_ingress(adapter_class)
    with patch.object(plugin, "_runner", return_value=runner or _gateway_runner()):
        asyncio.run(adapter_class().handle_message(event))
    return calls


def _inbound_rows(plugin) -> list:
    return [message for message in plugin._messages if message["direction"] == "INBOUND"]


def test_a_message_queued_behind_a_running_turn_is_recorded() -> None:
    plugin = _load_plugin()

    calls = _arrive(plugin, _inbound())

    assert len(calls) == 1
    rows = _inbound_rows(plugin)
    assert len(rows) == 1
    assert rows[0]["provider_message_id"] == "message-1"
    assert rows[0]["session_key"] == "agent:main:discord:channel:channel-1"
    assert rows[0]["channel_id"] == "channel-1"
    assert rows[0]["conversation_type"] == "CHANNEL"
    assert rows[0]["content"] == "hello"


def test_an_idle_message_seen_on_both_paths_is_recorded_once() -> None:
    plugin = _load_plugin()
    runner = _gateway_runner()
    event = _inbound()

    _arrive(plugin, event, runner)
    plugin._on_pre_gateway_dispatch(event=event, gateway=runner)

    assert len(_inbound_rows(plugin)) == 1


def test_a_message_seen_only_at_dispatch_is_still_recorded() -> None:
    plugin = _load_plugin()

    plugin._on_pre_gateway_dispatch(event=_inbound(), gateway=_gateway_runner())

    assert len(_inbound_rows(plugin)) == 1


def test_the_same_id_on_another_platform_is_a_different_message() -> None:
    plugin = _load_plugin()

    _arrive(plugin, _inbound())
    _arrive(plugin, _inbound(source=_source(platform=SimpleNamespace(value="slack"))))

    assert len(_inbound_rows(plugin)) == 2


def test_arrival_leaves_the_journal_to_the_dispatch_path() -> None:
    plugin = _load_plugin()
    runner = _gateway_runner()
    plugin._on_pre_gateway_dispatch(event=_inbound(message_id="running"), gateway=runner)
    plugin._buffer.clear()

    _arrive(plugin, _inbound(message_id="queued"), runner)

    assert plugin._buffer == []
    assert plugin._latest_inbound["agent:main:discord:channel:channel-1"] == "discord:running"


def test_seen_messages_stay_bounded() -> None:
    plugin = _load_plugin()
    runner = _gateway_runner()

    with patch.object(plugin, "_MAX_TRACKED", 2):
        for message_id in ("a", "b", "c"):
            plugin._on_pre_gateway_dispatch(event=_inbound(message_id=message_id), gateway=runner)

    assert list(plugin._seen_inbound) == ["discord:b", "discord:c"]


def test_internal_events_are_not_recorded_on_arrival() -> None:
    plugin = _load_plugin()

    calls = _arrive(plugin, _inbound(internal=True))

    assert len(calls) == 1
    assert plugin._messages == []


def test_a_message_without_text_or_id_is_not_recorded_on_arrival() -> None:
    plugin = _load_plugin()

    _arrive(plugin, _inbound(text=""))
    _arrive(plugin, _inbound(message_id=None, source=_source(message_id=None)))

    assert plugin._messages == []


def test_a_message_without_text_can_still_be_recorded_later_with_text() -> None:
    plugin = _load_plugin()
    runner = _gateway_runner()
    event = _inbound(text="")

    _arrive(plugin, event, runner)
    event.text = "a transcribed voice note"
    plugin._on_pre_gateway_dispatch(event=event, gateway=runner)

    assert [row["content"] for row in _inbound_rows(plugin)] == ["a transcribed voice note"]


def test_a_broken_observer_never_stops_a_message() -> None:
    plugin = _load_plugin()
    calls: list = []
    adapter_class = _adapter_class(calls)
    plugin._patch_ingress(adapter_class)

    with patch.object(plugin, "_runner", side_effect=RuntimeError("no gateway")):
        asyncio.run(adapter_class().handle_message(_inbound()))

    assert len(calls) == 1
    assert plugin._messages == []


def test_arrival_installs_the_first_response_patch_once() -> None:
    plugin = _load_plugin()
    runner = _gateway_runner()

    with patch.object(plugin, "_patch_first_response") as patch_first_response:
        _arrive(plugin, _inbound(message_id="a"), runner)
        _arrive(plugin, _inbound(message_id="b"), runner)

    patch_first_response.assert_called_once_with(type(runner))


def test_a_failed_first_response_patch_still_records_the_message() -> None:
    plugin = _load_plugin()

    with patch.object(plugin, "_patch_first_response", side_effect=AttributeError("renamed upstream")):
        _arrive(plugin, _inbound())

    assert len(_inbound_rows(plugin)) == 1


def _runner_class(deliver=None):
    class Runner:
        delivered: ClassVar[list] = []

        def _session_key_for_source(self, source):
            return "agent:main:discord:channel:channel-1"

        async def _deliver_queued_first_response(self, response, source, adapter, metadata=None, **kwargs):
            if deliver:
                deliver()
            self.delivered.append({"response": response, "metadata": metadata, **kwargs})

    return Runner


def _deliver(plugin, runner_class, response="The first answer.", source=None):
    with patch.object(
        plugin, "_visible_text", side_effect=lambda text, _adapter: text.replace("MEDIA:a.png", "").strip()
    ):
        asyncio.run(
            runner_class()._deliver_queued_first_response(
                response,
                source=source or _source(),
                adapter=MagicMock(),
                metadata={"thread_id": "t1"},
                event_message_id="message-1",
            )
        )


def _first_response(plugin, runner_class, **kwargs):
    plugin._patch_first_response(runner_class)
    _deliver(plugin, runner_class, **kwargs)


def _outbound_rows(plugin) -> list:
    return [message for message in plugin._messages if message["direction"] == "OUTBOUND"]


def test_a_first_response_before_a_queued_message_is_recorded() -> None:
    plugin = _load_plugin()
    runner_class = _runner_class()

    _first_response(plugin, runner_class, source=_source(thread_id="t1"))

    assert runner_class.delivered == [
        {"response": "The first answer.", "metadata": {"thread_id": "t1"}, "event_message_id": "message-1"}
    ]
    rows = _outbound_rows(plugin)
    assert len(rows) == 1
    assert rows[0]["provider_message_id"].startswith("outbound:")
    assert rows[0]["platform"] == "discord"
    assert rows[0]["session_key"] == "agent:main:discord:channel:channel-1"
    assert rows[0]["channel_id"] == "channel-1"
    assert rows[0]["thread_id"] == "t1"
    assert rows[0]["conversation_type"] == "CHANNEL"
    assert rows[0]["content"] == "The first answer."


def test_two_identical_first_responses_are_separate_rows() -> None:
    plugin = _load_plugin()
    runner_class = _runner_class()

    _first_response(plugin, runner_class)
    _deliver(plugin, runner_class)

    first, second = _outbound_rows(plugin)
    assert first["provider_message_id"] != second["provider_message_id"]


def test_a_first_response_is_recorded_without_its_attachments() -> None:
    plugin = _load_plugin()

    _first_response(plugin, _runner_class(), response="The chart. MEDIA:a.png")

    assert _outbound_rows(plugin)[0]["content"] == "The chart."


def test_a_first_response_with_only_attachments_has_no_row() -> None:
    plugin = _load_plugin()

    _first_response(plugin, _runner_class(), response="MEDIA:a.png")

    assert _outbound_rows(plugin) == []


def test_a_first_response_that_raises_has_no_row_and_still_raises() -> None:
    plugin = _load_plugin()

    def fail():
        raise RuntimeError("send failed")

    with pytest.raises(RuntimeError, match="send failed"):
        _first_response(plugin, _runner_class(deliver=fail))

    assert _outbound_rows(plugin) == []


def test_a_broken_record_does_not_fail_a_delivered_first_response() -> None:
    plugin = _load_plugin()
    runner_class = _runner_class()

    def broken(_self, _source):
        raise RuntimeError("no session")

    runner_class._session_key_for_source = broken

    _first_response(plugin, runner_class)

    assert len(runner_class.delivered) == 1
    assert _outbound_rows(plugin) == []


def test_register_observes_arrivals(monkeypatch, tmp_path) -> None:
    plugin = _load_plugin()
    monkeypatch.setenv("AGENT_ID", "agent-1")
    monkeypatch.setenv("INGEST_URL", "http://ingest")
    monkeypatch.setenv("INGEST_API_KEY", "key")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with (
        patch.object(plugin, "_install_ingress") as install,
        patch.object(plugin.threading, "Thread"),
    ):
        plugin.register(MagicMock())

    install.assert_called_once_with()


def test_register_without_ingest_settings_observes_nothing(monkeypatch) -> None:
    plugin = _load_plugin()
    monkeypatch.delenv("AGENT_ID", raising=False)

    with patch.object(plugin, "_install_ingress") as install:
        plugin.register(MagicMock())

    install.assert_not_called()


def _installed_at(path: str):
    plugin = _load_plugin()
    plugin.__file__ = path
    return plugin


def _owned_adapter(adapter_class, owner):
    adapter = adapter_class()
    adapter._owner_profile = owner
    return adapter


def test_each_profile_records_only_arrivals_on_its_own_adapters() -> None:
    parent, bot = _installed_at(_PARENT_INSTALL), _installed_at(_BOT_INSTALL)
    calls: list = []
    adapter_class = _adapter_class(calls)
    parent._patch_ingress(adapter_class)
    bot._patch_ingress(adapter_class)
    runner = _gateway_runner()

    with patch.object(parent, "_runner", return_value=runner), patch.object(bot, "_runner", return_value=runner):
        asyncio.run(_owned_adapter(adapter_class, None).handle_message(_inbound(message_id="to-parent")))
        asyncio.run(_owned_adapter(adapter_class, _PROFILE_BOT).handle_message(_inbound(message_id="to-bot")))

    assert len(calls) == 2
    assert [row["provider_message_id"] for row in _inbound_rows(parent)] == ["to-parent"]
    assert [row["provider_message_id"] for row in _inbound_rows(bot)] == ["to-bot"]


def test_each_profile_records_only_first_responses_through_its_own_adapters() -> None:
    parent, bot = _installed_at(_PARENT_INSTALL), _installed_at(_BOT_INSTALL)
    runner_class = _runner_class()
    parent._patch_first_response(runner_class)
    bot._patch_first_response(runner_class)
    adapter_class = _adapter_class([])

    for plugin in (parent, bot):
        patch.object(plugin, "_visible_text", side_effect=lambda text, _adapter: text).start()
    try:
        for owner, response in ((None, "From the parent."), (_PROFILE_BOT, "From the bot.")):
            asyncio.run(
                runner_class()._deliver_queued_first_response(
                    response, source=_source(), adapter=_owned_adapter(adapter_class, owner), metadata={}
                )
            )
    finally:
        patch.stopall()

    assert len(runner_class.delivered) == 2
    assert [row["content"] for row in _outbound_rows(parent)] == ["From the parent."]
    assert [row["content"] for row in _outbound_rows(bot)] == ["From the bot."]


def test_a_bot_install_belongs_to_its_profile_and_the_parents_to_none() -> None:
    assert _installed_at(_BOT_INSTALL)._own_profile() == _PROFILE_BOT
    assert _installed_at(_PARENT_INSTALL)._own_profile() is None
