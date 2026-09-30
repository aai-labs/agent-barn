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

from api.domains.agents.builders import (
    build_config_map,
    build_hermes_config_map,
    build_hermes_gateway_config,
    build_openclaw_gateway_config,
)

_SCRIPTS = Path(__file__).parents[2] / "domains/agents/scripts"
_AGENT_ID = uuid4()
_ORG_ID = uuid4()
_NS = "agent-farm"

# Supplied only for some Agents; start.sh guards each with `[ -f ... ]`.
_OPTIONAL = {"aai-cli-setup.sh", "aai-cli-config.toml", "gog-setup.sh", "skills.json"}


def _referenced_files(start_script: Path) -> set[str]:
    """Concrete /app/config/<name> reads. The `$f` loop variable is expanded separately."""
    text = start_script.read_text()
    names = set(re.findall(r"/app/config/([A-Za-z0-9_.-]+)", text))
    for loop in re.findall(r"for f in ([^;]+); do", text):
        names.update(loop.split())
    return names - _OPTIONAL


def _hermes_config_map():
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
    )


def _openclaw_config_map():
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
