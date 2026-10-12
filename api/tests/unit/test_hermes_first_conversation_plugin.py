import importlib.util
import json
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
    assert "finish_first_conversation" in result["context"]
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


def test_the_seventh_turn_retires_the_script(plugin, state_dir: Path) -> None:
    script = _with_script(state_dir)

    carried = [_interactive_turn(plugin) is not None for _ in range(6)]
    seventh = _interactive_turn(plugin)

    assert carried == [True] * 6
    assert seventh is None
    assert not script.exists()
    assert not (state_dir / "bootstrap-turns").exists()
    assert _interactive_turn(plugin) is None


def test_finishing_removes_the_script_and_is_idempotent(plugin, state_dir: Path) -> None:
    script = _with_script(state_dir)
    _interactive_turn(plugin)

    first = json.loads(plugin.finish_first_conversation({}))
    second = json.loads(plugin.finish_first_conversation({}, task_id="t1"))

    assert first == {"status": "done"}
    assert second == {"status": "done"}
    assert not script.exists()
    assert not (state_dir / "bootstrap-turns").exists()
    assert _interactive_turn(plugin) is None


def test_concurrent_turns_count_each_turn_once(plugin, state_dir: Path) -> None:
    _with_script(state_dir)
    barrier = threading.Barrier(6)
    results: list[object] = []

    def turn() -> None:
        barrier.wait()
        results.append(_interactive_turn(plugin))

    threads = [threading.Thread(target=turn) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(result is not None for result in results)
    assert (state_dir / "bootstrap-turns").read_text(encoding="utf-8") == "6"
    assert _interactive_turn(plugin) is None


def test_register_wires_the_hook_and_the_tool_under_its_own_toolset(plugin) -> None:
    ctx = MagicMock()

    plugin.register(ctx)

    ctx.register_hook.assert_called_once_with("pre_llm_call", plugin.on_pre_llm_call)
    tool = ctx.register_tool.call_args.kwargs
    assert tool["name"] == "finish_first_conversation"
    assert tool["toolset"] == "agentbarn-first-conversation"
    assert tool["handler"] is plugin.finish_first_conversation
    assert tool["schema"]["name"] == "finish_first_conversation"
    assert tool["schema"]["parameters"] == {"type": "object", "properties": {}}


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
