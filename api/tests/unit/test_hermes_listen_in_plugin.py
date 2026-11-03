import asyncio
import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

_PLUGIN = (
    Path(__file__).parents[2]
    / "domains"
    / "agents"
    / "scripts"
    / "hermes"
    / "plugins"
    / "agentbarn-listen-in"
    / "__init__.py"
)
_SLACK_ROOM = "C-ROOM"
_DISCORD_ROOM = "111"
_TELEGRAM_ROOM = "-100"
_KEY = "agent:main:discord:group:111"


@pytest.fixture
def plugin(monkeypatch):
    spec = importlib.util.spec_from_file_location("test_agentbarn_listen_in", _PLUGIN)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._rooms.update({"slack": {_SLACK_ROOM}, "discord": {_DISCORD_ROOM}, "telegram": {_TELEGRAM_ROOM}})
    runner = MagicMock()
    runner._session_key_for_source.return_value = _KEY
    monkeypatch.setattr(module, "_runner", lambda: runner)
    monkeypatch.setattr(module, "_is_known_command", lambda name: name in {"status", "new"})
    module.test_env = {"HERMES_SESSION_KEY": _KEY, "HERMES_SESSION_CHAT_ID": _DISCORD_ROOM}
    monkeypatch.setattr(module, "_session_env", lambda name: module.test_env.get(name, ""))
    return module


def _event(platform="discord", chat_id=_DISCORD_ROOM, text="hello", raw=None, **overrides):
    values = {
        "source": SimpleNamespace(
            platform=SimpleNamespace(value=platform),
            chat_id=chat_id,
            parent_chat_id=overrides.pop("parent_chat_id", None),
        ),
        "text": text,
        "raw_message": raw if raw is not None else SimpleNamespace(),
        "reply_to_is_own_message": False,
        "internal": False,
        "allow_gateway_control": True,
    }
    values.update(overrides)
    event = SimpleNamespace(**values)
    event.is_command = lambda: event.allow_gateway_control and (event.text or "").lstrip().startswith("/")
    event.get_command = lambda: (event.text or "").lstrip()[1:].split(" ")[0].lower()
    return event


def _discord(mentioned=False):
    return SimpleNamespace(_self_is_explicitly_mentioned=lambda _raw: mentioned)


def _telegram(mentions=False, reply=False, pattern=False):
    return SimpleNamespace(
        _message_mentions_bot=lambda _raw: mentions,
        _is_reply_to_bot=lambda _raw: reply,
        _message_matches_mention_patterns=lambda _raw: pattern,
    )


def _slack(plugin, monkeypatch, detected="", pattern=False, thread_policy_requires=True, owned=()):
    adapter_module: Any = ModuleType("fake_slack_adapter")
    adapter_module._slack_mention_detection_text = lambda _raw: detected
    monkeypatch.setitem(sys.modules, "fake_slack_adapter", adapter_module)
    adapter_type = type("SlackAdapter", (), {"__module__": "fake_slack_adapter"})
    adapter: Any = adapter_type()
    adapter._team_bot_user_ids = {"T1": "UBOT"}
    adapter._bot_user_id = "UBOT"
    adapter._slack_message_matches_mention_patterns = lambda _text: pattern
    adapter._slack_thread_require_mention = lambda: thread_policy_requires
    adapter._workspace_message_marker = lambda team, ts: (team, ts)
    adapter._bot_message_ts = set(owned)
    adapter._mentioned_threads = set()
    return adapter


def _listening(plugin) -> bool:
    return plugin._queues[_KEY][-1]


def _slack_event(raw):
    return _event(platform="slack", chat_id=_SLACK_ROOM, raw=raw)


@pytest.mark.parametrize(
    ("detected", "pattern", "addressed"),
    [("<@UBOT> hi", False, True), ("<@USOMEONE> hi", False, False), ("hi", True, True), ("hi", False, False)],
)
def test_slack_mentions_use_the_adapters_own_detection(plugin, monkeypatch, detected, pattern, addressed) -> None:
    adapter = _slack(plugin, monkeypatch, detected=detected, pattern=pattern)

    plugin._classify(adapter, _slack_event({"team": "T1", "ts": "1.0", "text": "ignored"}))

    assert _listening(plugin) is (not addressed)


def test_slack_start_only_replies_in_the_agents_own_thread_are_addressed(plugin, monkeypatch) -> None:
    adapter = _slack(plugin, monkeypatch, thread_policy_requires=False, owned={("T1", "1.0")})

    plugin._classify(adapter, _slack_event({"team": "T1", "ts": "2.0", "thread_ts": "1.0", "text": "more"}))

    assert _listening(plugin) is False


def test_slack_start_only_replies_in_someone_elses_thread_are_not_addressed(plugin, monkeypatch) -> None:
    adapter = _slack(plugin, monkeypatch, thread_policy_requires=False)

    plugin._classify(adapter, _slack_event({"team": "T1", "ts": "2.0", "thread_ts": "1.0", "text": "more"}))

    assert _listening(plugin) is True


def test_discord_user_mention_is_addressed(plugin) -> None:
    plugin._classify(_discord(mentioned=True), _event())

    assert _listening(plugin) is False


def test_discord_mention_of_the_bots_own_role_is_addressed(plugin) -> None:
    mine = SimpleNamespace(id=7)
    raw = SimpleNamespace(guild=SimpleNamespace(me=SimpleNamespace(roles=[mine])), role_mentions=[mine])

    plugin._classify(_discord(), _event(raw=raw))

    assert _listening(plugin) is False


def test_discord_mention_of_another_role_is_not_addressed(plugin) -> None:
    raw = SimpleNamespace(
        guild=SimpleNamespace(me=SimpleNamespace(roles=[SimpleNamespace(id=7)])),
        role_mentions=[SimpleNamespace(id=8)],
    )

    plugin._classify(_discord(), _event(raw=raw))

    assert _listening(plugin) is True


def test_discord_native_command_is_addressed(plugin) -> None:
    interaction = type("Interaction", (), {})()

    plugin._classify(_discord(), _event(text="/status", raw=interaction))

    assert _KEY not in plugin._queues or not plugin._queues[_KEY]


@pytest.mark.parametrize(
    "adapter_args",
    [{"mentions": True}, {"reply": True}, {"pattern": True}],
)
def test_telegram_mentions_replies_and_patterns_are_addressed(plugin, adapter_args) -> None:
    plugin._classify(_telegram(**adapter_args), _event(platform="telegram", chat_id=_TELEGRAM_ROOM))

    assert _listening(plugin) is False


def test_telegram_chatter_is_not_addressed(plugin) -> None:
    plugin._classify(_telegram(), _event(platform="telegram", chat_id=_TELEGRAM_ROOM))

    assert _listening(plugin) is True


def test_a_reply_to_the_agent_is_addressed(plugin) -> None:
    plugin._classify(_discord(), _event(reply_to_is_own_message=True))

    assert _listening(plugin) is False


def test_a_thread_under_a_listen_in_room_is_part_of_it(plugin) -> None:
    plugin._classify(_discord(), _event(chat_id="thread-1", parent_chat_id=_DISCORD_ROOM))

    assert _listening(plugin) is True


def test_other_rooms_are_left_alone(plugin) -> None:
    event = _event(chat_id="elsewhere")

    plugin._classify(_discord(), event)

    assert event.allow_gateway_control is True
    assert plugin._queues == {}


def test_a_room_id_on_another_platform_is_not_a_room(plugin) -> None:
    plugin._classify(_telegram(), _event(platform="telegram", chat_id=_DISCORD_ROOM))

    assert plugin._queues == {}


def test_internal_events_are_left_alone(plugin) -> None:
    plugin._classify(_discord(), _event(internal=True))

    assert plugin._queues == {}


def test_an_unaddressed_message_cannot_control_the_gateway(plugin) -> None:
    event = _event(text="/new")

    plugin._classify(_discord(), event)

    assert event.allow_gateway_control is False
    assert event.is_command() is False
    assert _listening(plugin) is True


def test_an_addressed_message_keeps_gateway_control(plugin) -> None:
    event = _event()

    plugin._classify(_discord(mentioned=True), event)

    assert event.allow_gateway_control is True


def test_an_addressed_known_command_runs_no_turn(plugin) -> None:
    plugin._classify(_discord(mentioned=True), _event(text="/status"))

    assert not plugin._queues.get(_KEY)


def test_an_addressed_path_that_looks_like_a_command_is_a_turn(plugin) -> None:
    plugin._classify(_discord(mentioned=True), _event(text="/tmp/foo is broken"))

    assert _listening(plugin) is False


def test_a_classification_error_means_listening(plugin) -> None:
    adapter = SimpleNamespace(_self_is_explicitly_mentioned=MagicMock(side_effect=RuntimeError("drift")))
    event = _event()

    plugin._classify(adapter, event)

    assert _listening(plugin) is True
    assert event.allow_gateway_control is False


def test_queued_messages_each_keep_their_own_classification(plugin) -> None:
    plugin._classify(_discord(mentioned=True), _event())
    plugin._classify(_discord(), _event())

    plugin._on_pre_llm_call()
    assert plugin._on_transform(response_text="answer") is None

    plugin._on_pre_llm_call()
    assert plugin._on_transform(response_text="private") == "NO_REPLY"


def test_a_later_message_does_not_change_the_running_turn(plugin) -> None:
    plugin._classify(_discord(mentioned=True), _event())
    plugin._on_pre_llm_call()

    plugin._classify(_discord(), _event())

    assert plugin._on_transform(response_text="answer") is None


def test_a_room_turn_with_no_classification_stays_silent(plugin) -> None:
    plugin._on_pre_llm_call()

    assert plugin._on_transform(response_text="resumed after restart") == "NO_REPLY"


def test_a_room_session_with_no_turn_state_stays_silent(plugin) -> None:
    assert plugin._on_transform(response_text="no state") == "NO_REPLY"


def test_a_session_outside_the_rooms_is_not_silenced(plugin) -> None:
    plugin.test_env = {"HERMES_SESSION_KEY": "agent:main:discord:dm:5", "HERMES_SESSION_CHAT_ID": "5"}

    plugin._on_pre_llm_call()

    assert plugin._on_transform(response_text="dm") is None


def test_a_scheduled_run_in_a_room_is_not_silenced(plugin) -> None:
    plugin.test_env = {**plugin.test_env, "HERMES_CRON_SESSION": "1"}

    plugin._on_pre_llm_call()

    assert plugin._on_transform(response_text="report") is None


def test_a_stray_marker_on_a_mention_is_removed(plugin) -> None:
    plugin._classify(_discord(mentioned=True), _event())
    plugin._on_pre_llm_call()

    assert plugin._on_transform(response_text="391\n\nNO_REPLY") == "391"


def test_background_review_neither_takes_a_turn_nor_is_silenced(plugin) -> None:
    plugin._classify(_discord(), _event())
    results = []

    def review():
        plugin._on_pre_llm_call()
        results.append(plugin._on_transform(response_text="Nothing to save"))

    thread = threading.Thread(target=review, name="bg-review")
    thread.start()
    thread.join()

    assert results == [None]
    assert list(plugin._queues[_KEY]) == [True]


def test_ingress_classifies_before_the_original_handler(plugin) -> None:
    seen = []

    class Base:
        async def handle_message(self, event):
            seen.append(event.allow_gateway_control)

    plugin._patch_ingress(Base)
    adapter: Any = Base()
    adapter._self_is_explicitly_mentioned = lambda _raw: False

    asyncio.run(adapter.handle_message(_event()))

    assert seen == [False]


def test_ingress_still_delivers_when_classification_breaks(plugin, monkeypatch) -> None:
    seen = []

    class Base:
        async def handle_message(self, event):
            seen.append(event)

    monkeypatch.setattr(plugin, "_classify", MagicMock(side_effect=RuntimeError("drift")))
    plugin._patch_ingress(Base)
    event = _event()

    asyncio.run(Base().handle_message(event))

    assert seen == [event]


def test_rooms_are_read_from_the_hermes_config(plugin, tmp_path) -> None:
    config = {
        "slack": {"free_response_channels": ["C1", "C2"]},
        "discord": {"free_response_channels": "111, 222"},
        "telegram": {"free_response_chats": ["-100"]},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))

    assert plugin._load_rooms(path) == {"slack": {"C1", "C2"}, "discord": {"111", "222"}, "telegram": {"-100"}}


@pytest.mark.parametrize("content", [None, "", "slack: {}\n"])
def test_a_config_without_rooms_has_none(plugin, tmp_path, content) -> None:
    path = tmp_path / "config.yaml"
    if content is not None:
        path.write_text(content)

    assert plugin._load_rooms(path) == {}


def test_without_rooms_the_plugin_changes_nothing(plugin, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    patch_ingress = MagicMock()
    monkeypatch.setattr(plugin, "_patch_ingress", patch_ingress)
    ctx = MagicMock()

    plugin.register(ctx)

    patch_ingress.assert_not_called()
    ctx.register_hook.assert_not_called()


def test_with_rooms_the_plugin_registers_its_hooks(plugin, monkeypatch, tmp_path) -> None:
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"discord": {"free_response_channels": ["111"]}}))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(plugin, "_install_ingress", MagicMock())
    ctx = MagicMock()

    plugin.register(ctx)

    assert {call.args[0] for call in ctx.register_hook.call_args_list} == {"pre_llm_call", "transform_llm_output"}
