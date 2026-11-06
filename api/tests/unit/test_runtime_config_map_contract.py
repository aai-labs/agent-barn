"""Every file a start script reads from /app/config must actually ship in the ConfigMap.

start.sh runs under `set -e`, so a missing file is not a degraded feature -- the copy
fails and the container dies before the runtime ever starts. This caught a real
crash-loop: the messaging plugin was added to start.sh for one runtime while the
ConfigMap entry was added to the other.

Asserting the relationship rather than a list of filenames means a future file added
to a start script is covered without anyone remembering to update a test.
"""

import re
from pathlib import Path
from uuid import uuid4

import pytest

from api.domains.agent_sizes.models import (
    STANDARD_CPU_LIMIT_MILLICORES,
    STANDARD_CPU_REQUEST_MILLICORES,
    STANDARD_MEMORY_LIMIT_BYTES,
    STANDARD_MEMORY_REQUEST_BYTES,
)
from api.domains.agents.builders import (
    build_config_map,
    build_deployment,
    build_hermes_config_map,
    build_hermes_deployment,
    build_hermes_gateway_config,
    build_openclaw_gateway_config,
    container_resources,
)
from api.domains.agents.builders.memory import MEMORY_TOOL_INSTRUCTIONS
from api.domains.agents.builders.tasks import TASK_COMMAND, TASK_COMMAND_PATH, TASK_TOOL, TASK_TOOL_INSTRUCTIONS

_SCRIPTS = Path(__file__).parents[2] / "domains/agents/scripts"
_AGENT_ID = uuid4()
_ORG_ID = uuid4()
_NS = "agent-farm"
_STANDARD = container_resources(
    cpu_request_millicores=STANDARD_CPU_REQUEST_MILLICORES,
    cpu_limit_millicores=STANDARD_CPU_LIMIT_MILLICORES,
    memory_request_bytes=STANDARD_MEMORY_REQUEST_BYTES,
    memory_limit_bytes=STANDARD_MEMORY_LIMIT_BYTES,
)

# Supplied only for some Agents; start.sh guards each with `[ -f ... ]`.
_OPTIONAL = {"aai-cli-setup.sh", "aai-cli-config.toml", "gog-setup.sh", "skills.json"}


def _referenced_files(start_script: Path) -> set[str]:
    """Concrete /app/config/<name> reads. The `$f` loop variable is expanded separately."""
    text = start_script.read_text()
    names = set(re.findall(r"/app/config/([A-Za-z0-9_.-]+)", text))
    for loop in re.findall(r"for f in ([^;]+); do", text):
        names.update(loop.split())
    return names - _OPTIONAL


def _hermes_config_map(memory_enabled=False):
    return build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        "soul",
        "identity",
        "user",
        "tools",
        "agents",
        "boot",
        "heartbeat",
        build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000"),
        memory_enabled=memory_enabled,
    )


def _openclaw_config_map(memory_enabled=False):
    return build_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        "soul",
        "identity",
        "user",
        "tools",
        "agents",
        "boot",
        "bootstrap",
        "heartbeat",
        memory_enabled=memory_enabled,
        openclaw_config_overlay=build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000"),
    )


@pytest.mark.parametrize(
    "runtime,builder",
    [("hermes", _hermes_config_map), ("openclaw", _openclaw_config_map)],
)
def test_start_script_reads_only_files_the_config_map_ships(runtime, builder):
    referenced = _referenced_files(_SCRIPTS / runtime / "start.sh")
    shipped = set(builder().data)
    assert referenced, f"no /app/config reads found in {runtime}/start.sh -- parser is broken"
    assert referenced <= shipped, f"{runtime}/start.sh reads files the ConfigMap omits: {sorted(referenced - shipped)}"


@pytest.mark.parametrize(
    "runtime,builder,foreign",
    [
        ("hermes", _hermes_config_map, "openclaw-messaging.js"),
        ("openclaw", _openclaw_config_map, "hermes-messaging.py"),
    ],
)
def test_config_map_does_not_ship_the_other_runtime_plugin(runtime, builder, foreign):
    """A runtime's ConfigMap is mounted into its pod; the other runtime's plugin is dead weight."""
    assert foreign not in builder().data


@pytest.mark.parametrize("builder", [_hermes_config_map, _openclaw_config_map])
@pytest.mark.parametrize("enabled", [False, True])
def test_memory_writer_instructions_are_only_in_enabled_agents_startup_context(builder, enabled):
    data = builder(memory_enabled=enabled).data
    assert (MEMORY_TOOL_INSTRUCTIONS in data["AGENTS.md"]) == enabled
    assert data["AGENTS.md"].startswith("agents")
    assert data["TOOLS.md"] == "tools"


@pytest.mark.parametrize("builder", [_hermes_config_map, _openclaw_config_map])
@pytest.mark.parametrize("memory_enabled", [False, True])
def test_every_agent_ships_the_task_command_and_when_to_use_it(builder, memory_enabled):
    data = builder(memory_enabled=memory_enabled).data
    assert data["agentbarn_task.py"] == TASK_TOOL
    assert data["agentbarn-task"] == TASK_COMMAND
    assert TASK_TOOL_INSTRUCTIONS in data["AGENTS.md"]
    assert data["AGENTS.md"].startswith("agents")


@pytest.mark.parametrize("build", [build_hermes_deployment, build_deployment])
def test_the_task_command_is_installed_on_the_agents_path(build):
    pod = build(_AGENT_ID, _ORG_ID, _NS, "runtime:test", resources=_STANDARD).spec.template.spec
    [mount] = [m for m in pod.containers[0].volume_mounts if m.mount_path == TASK_COMMAND_PATH]
    [volume] = [v for v in pod.volumes if v.name == mount.name]
    [item] = volume.config_map.items
    assert (mount.sub_path, mount.read_only) == (item.path, True)
    assert (item.key, item.mode) == ("agentbarn-task", 0o555)


@pytest.mark.parametrize(
    "builder,files",
    [
        (_hermes_config_map, {"agentbarn-tasks-plugin.yaml", "agentbarn-tasks-init.py"}),
        (
            _openclaw_config_map,
            {"agentbarn-tasks-index.js", "agentbarn-tasks-package.json", "agentbarn-tasks-plugin.json"},
        ),
    ],
)
def test_every_agent_ships_the_tasks_plugin(builder, files):
    assert files <= set(builder().data)


@pytest.mark.parametrize("memory_enabled", [False, True])
def test_hermes_enables_the_tasks_plugin(memory_enabled):
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", memory_enabled=memory_enabled)
    assert "agentbarn-tasks" in config["plugins"]["enabled"]


@pytest.mark.parametrize("native_channels", [None, {"slack": {"enabled": True}}])
def test_openclaw_loads_and_enables_the_tasks_plugin(native_channels):
    plugins = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000", native_channels)["plugins"]
    assert "agentbarn-tasks" in plugins["allow"]
    assert "/home/node/.openclaw/local-plugins/agentbarn-tasks" in plugins["load"]["paths"]
    assert plugins["entries"]["agentbarn-tasks"] == {"enabled": True, "hooks": {"allowConversationAccess": True}}


@pytest.mark.parametrize(
    "runtime,installed",
    [
        ("hermes", "/opt/data/plugins/agentbarn-tasks/__init__.py"),
        ("openclaw", '/home/node/.openclaw/local-plugins/agentbarn-tasks"\n'),
    ],
)
def test_start_script_installs_the_tasks_plugin(runtime, installed):
    assert installed in (_SCRIPTS / runtime / "start.sh").read_text()


def test_hermes_offers_plugin_tools_directly_rather_than_behind_tool_search():
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")
    assert config["tools"]["tool_search"] == {"enabled": "off"}


def test_the_instructions_keep_task_bookkeeping_out_of_replies():
    assert "Do not mention Tasks in your replies unless the user asks" in TASK_TOOL_INSTRUCTIONS


def test_the_instructions_leave_closing_and_attaching_to_the_plugin():
    instructions = " ".join(TASK_TOOL_INSTRUCTIONS.split())
    assert "is marked `done` when your turn ends" in instructions
    assert "the files you wrote are attached to it" in instructions
