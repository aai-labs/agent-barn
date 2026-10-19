import importlib.util
import threading
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from api.domains.agents.builders import build_hermes_config_map, build_hermes_gateway_config

_PLUGIN_DIR = (
    Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "hermes" / "plugins" / "agentbarn-first-conversation"
)
_SCRIPT_TEXT = "# First conversation\n\n1. Greet them.\n"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("test_agentbarn_first_conversation", _PLUGIN_DIR / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".agentbarn"
    directory.mkdir()
    return directory


@pytest.fixture
def plugin(state_dir: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_plugin()
    monkeypatch.setattr(module, "STATE_DIR", state_dir)
    return module


def _with_script(state_dir: Path) -> Path:
    script = state_dir / "BOOTSTRAP.md"
    script.write_text(_SCRIPT_TEXT, encoding="utf-8")
    return script


def _interactive_turn(plugin, **overrides):
    kwargs = {"session_id": "agent:main:telegram:dm:42", "platform": "telegram", "parent_session_id": ""}
    kwargs.update(overrides)
    return plugin.on_pre_llm_call(**kwargs)


def test_no_script_adds_nothing(plugin) -> None:
    assert _interactive_turn(plugin) is None


def test_an_interactive_turn_carries_the_wrapper_and_the_script(plugin, state_dir: Path) -> None:
    _with_script(state_dir)

    result = _interactive_turn(plugin)

    assert result is not None
    assert result["context"].startswith("[Agent Barn — first conversation]")
    assert "finish_first_conversation" not in result["context"]
    assert result["context"].endswith(_SCRIPT_TEXT)


@pytest.mark.parametrize("platform", ["api_server", "telegram", "slack", "discord", "teams", ""])
def test_every_chat_platform_is_interactive(plugin, state_dir: Path, platform: str) -> None:
    _with_script(state_dir)

    assert _interactive_turn(plugin, platform=platform) is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"platform": "cron"},
        {"platform": "curator"},
        {"platform": "subagent"},
        {"platform": "api_server", "session_id": "agentbarn-boot"},
        {"parent_session_id": "agent:main:telegram:dm:42"},
    ],
    ids=["cron", "curator", "subagent", "boot", "child-session"],
)
def test_runs_without_a_person_get_nothing_and_are_not_counted(plugin, state_dir: Path, overrides: dict) -> None:
    _with_script(state_dir)

    assert _interactive_turn(plugin, **overrides) is None
    assert not (state_dir / "bootstrap-turns").exists()


def _carries_script(result) -> bool:
    return result is not None and result["context"].endswith(_SCRIPT_TEXT)


def _is_close_note(result) -> bool:
    return result is not None and "script is complete" in result["context"] and _SCRIPT_TEXT not in result["context"]


def test_a_session_carries_the_script_once_and_hermes_replays_it(plugin, state_dir: Path) -> None:
    _with_script(state_dir)

    first = _interactive_turn(plugin)
    later = [_interactive_turn(plugin) for _ in range(2)]

    assert _carries_script(first)
    assert later == [None, None]


def test_every_new_session_gets_one_copy_of_its_own(plugin, state_dir: Path) -> None:
    _with_script(state_dir)

    telegram = _interactive_turn(plugin)
    web_chat = _interactive_turn(plugin, session_id="connection:abc:main", platform="api_server")
    telegram_again = _interactive_turn(plugin)

    assert _carries_script(telegram)
    assert _carries_script(web_chat)
    assert telegram_again is None


def test_the_script_retires_after_the_third_turn_with_a_person(plugin, state_dir: Path) -> None:
    script = _with_script(state_dir)

    three = [_interactive_turn(plugin) for _ in range(3)]
    fourth = _interactive_turn(plugin)

    assert _carries_script(three[0])
    assert three[1:] == [None, None]
    assert _is_close_note(fourth)
    assert not script.exists()
    assert not (state_dir / "bootstrap-turns").exists()
    assert _interactive_turn(plugin) is None


def test_retiring_closes_each_session_that_got_the_script_exactly_once(plugin, state_dir: Path) -> None:
    script = _with_script(state_dir)
    _interactive_turn(plugin)
    _interactive_turn(plugin, session_id="connection:abc:main", platform="api_server")
    _interactive_turn(plugin)

    telegram = [_interactive_turn(plugin) for _ in range(2)]
    web_chat = [_interactive_turn(plugin, session_id="connection:abc:main", platform="api_server") for _ in range(2)]
    stranger = _interactive_turn(plugin, session_id="agent:main:telegram:dm:99")

    assert not script.exists()
    assert not (state_dir / "bootstrap-turns").exists()
    assert _is_close_note(telegram[0]) and telegram[1] is None
    assert _is_close_note(web_chat[0]) and web_chat[1] is None
    assert stranger is None
    assert not (state_dir / "bootstrap-closing").exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"platform": "cron"},
        {"platform": "curator"},
        {"platform": "subagent"},
        {"session_id": "agentbarn-boot", "platform": "api_server"},
        {"parent_session_id": "agent:main:telegram:dm:42"},
    ],
    ids=["cron", "curator", "subagent", "boot", "child-session"],
)
def test_runs_without_a_person_do_not_consume_the_close_note(plugin, state_dir: Path, overrides: dict) -> None:
    _with_script(state_dir)
    for _ in range(3):
        _interactive_turn(plugin)
    _interactive_turn(plugin, session_id="connection:abc:main", platform="api_server")

    assert _interactive_turn(plugin, **overrides) is None
    assert _is_close_note(_interactive_turn(plugin))


def test_concurrent_turns_in_one_session_carry_one_copy_and_count_each_turn(plugin, state_dir: Path) -> None:
    _with_script(state_dir)
    barrier = threading.Barrier(3)
    results: list[object] = []

    def turn() -> None:
        barrier.wait()
        results.append(_interactive_turn(plugin))

    threads = [threading.Thread(target=turn) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(_carries_script(result) for result in results) == 1
    assert (state_dir / "bootstrap-turns").read_text(encoding="utf-8") == "3"
    assert _is_close_note(_interactive_turn(plugin))


def test_register_wires_only_the_hook(plugin) -> None:
    ctx = MagicMock()

    plugin.register(ctx)

    ctx.register_hook.assert_called_once_with("pre_llm_call", plugin.on_pre_llm_call)
    ctx.register_tool.assert_not_called()


def test_manifest_names_the_plugin() -> None:
    manifest = (_PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")

    assert "name: agentbarn-first-conversation" in manifest


def test_config_map_always_ships_the_plugin_files() -> None:
    data = build_hermes_config_map(
        uuid4(),
        uuid4(),
        "agent-farm",
        "soul",
        "identity",
        "user",
        "tools",
        "agents",
        "boot",
        "heartbeat",
        build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000"),
    ).data

    assert data["agentbarn-first-conversation-plugin.yaml"] == (_PLUGIN_DIR / "plugin.yaml").read_text()
    assert data["agentbarn-first-conversation-init.py"] == (_PLUGIN_DIR / "__init__.py").read_text()
