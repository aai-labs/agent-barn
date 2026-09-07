from uuid import UUID

from api.domains.agents.builders import (
    START_SH,
    build_config_map,
    build_deployment,
    build_openclaw_gateway_config,
    build_secret_runtime,
)
from api.domains.agents.builders.openclaw import OPENCLAW_GATEWAY_PORT

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


def test_gateway_config_is_headless_and_exposes_chat_completions() -> None:
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["channels"] == {}
    assert config["bindings"] == []
    assert config["gateway"]["http"]["endpoints"]["chatCompletions"]["enabled"] is True


def test_gateway_config_has_no_command_approval_support() -> None:
    """OpenClaw has no user-configurable command-approval control (AF-272): the
    builder takes no approval_mode parameter and must never fabricate one.
    """
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert "approvals" not in config


def test_config_map_contains_runtime_adapter_and_no_provider_bundle() -> None:
    config_map = build_config_map(
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

    assert "communications-runtime-adapter.py" in config_map.data
    assert not any(name.startswith(("slack-", "telegram-", "discord-")) for name in config_map.data)


def test_runtime_secret_contains_only_runtime_and_llm_credentials() -> None:
    secret = build_secret_runtime(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        runtime_api_key="runtime-key",
        litellm_api_key="llm-key",
        litellm_base_url="http://litellm:4000",
    )

    assert secret.string_data["RUNTIME_API_KEY"] == "runtime-key"
    assert secret.string_data["OPENCLAW_GATEWAY_TOKEN"] == "runtime-key"
    assert not any(key.startswith(("SLACK_", "TELEGRAM_", "DISCORD_", "MSTEAMS_")) for key in secret.string_data)


def test_deployment_runs_one_headless_runtime_container() -> None:
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test")

    assert deployment.spec.replicas == 1
    assert deployment.spec.template.spec.containers[0].name == "agent"


def test_adapter_targets_the_port_the_gateway_actually_binds() -> None:
    secret = build_secret_runtime(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        runtime_api_key="runtime-key",
        litellm_api_key="key",
        litellm_base_url="http://litellm:4000",
    )

    # A mismatch here is silent: the pod reports healthy, chat history fills in,
    # and every inbound delivery dead-letters with ECONNREFUSED because the
    # adapter posts to a port nothing is listening on.
    assert secret.string_data["RUNTIME_API_URL"] == f"http://127.0.0.1:{OPENCLAW_GATEWAY_PORT}"


def test_start_sh_does_not_move_the_gateway_off_its_default_port() -> None:
    # `openclaw health` resolves the default port with no override flag, so
    # pinning the gateway elsewhere breaks the health probe and leaves every
    # agent stuck reporting "initializing".
    assert "--port" not in START_SH


def test_deployment_declares_explicit_resources_rather_than_inheriting_limitrange() -> None:
    """Without a resources block the namespace LimitRange defaults every agent to
    512Mi/2Gi. requests.memory (20Gi quota) is the binding axis, so the request is
    what governs how many agents fit; the 1Gi limit both halves limits.memory
    consumption and caps V8's heap, which Node sizes at ~51% of the cgroup limit."""
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test")
    resources = deployment.spec.template.spec.containers[0].resources

    assert resources is not None
    assert resources.requests == {"memory": "320Mi", "cpu": "50m"}
    assert resources.limits == {"memory": "1Gi", "cpu": "500m"}


def test_deployment_recreates_rather_than_rolling_update() -> None:
    """replicas=1 on a ReadWriteOnce PVC: a RollingUpdate surge briefly wants two
    pods, doubling the agent's memory and deadlocking on the volume."""
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test")
    assert deployment.spec.strategy.type == "Recreate"


def test_deployment_carries_the_openclaw_runtime_label() -> None:
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test")
    assert deployment.metadata.labels["agentbarn.io/runtime"] == "openclaw"


def test_gateway_config_keeps_file_backed_memory_when_honcho_is_not_configured() -> None:
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    plugins = config["plugins"]
    assert plugins["slots"]["memory"] == "memory-core"
    assert "openclaw-honcho" not in plugins["allow"]
    assert config["memory"]["backend"] == "builtin"


def test_gateway_config_moves_the_memory_slot_to_honcho_when_configured() -> None:
    """Honcho occupies the single memory slot rather than running beside
    memory-core: two writers over the same semantic state is the condition the
    memory backend decision exists to remove."""
    config = build_openclaw_gateway_config(
        "litellm/gpt-5",
        "http://litellm:4000",
        honcho_base_url="http://honcho:8000",
        honcho_workspace_id="af-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    plugins = config["plugins"]
    assert plugins["slots"]["memory"] == "openclaw-honcho"
    assert "openclaw-honcho" in plugins["allow"]
    # memory-core has no entry, so it is not active — but it stays permitted so
    # start.sh can fall back to it when the plugin turns out to be missing.
    assert "memory-core" not in plugins["entries"]
    assert "memory-core" in plugins["allow"]
    # The runtime accepts only "builtin" (file-backed) or "qmd" (plugin-backed) here.
    # The slot is what actually decides, so an Agent runs on Honcho either way — but
    # a config that says "builtin" while Honcho holds the data sends anyone
    # debugging memory to the wrong place first.
    assert config["memory"]["backend"] == "qmd"

    entry = plugins["entries"]["openclaw-honcho"]
    assert entry["enabled"] is True
    assert entry["config"]["baseUrl"] == "http://honcho:8000"
    assert entry["config"]["workspaceId"] == "af-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_deployment_keeps_the_honcho_peer_map_on_the_persistent_volume() -> None:
    """The plugin defaults its sender-to-peer map to ~/.honcho, which is not the
    mounted volume. Held there it is lost on every pod recreation and each
    participant silently becomes a new peer with an empty representation."""
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test")
    container = deployment.spec.template.spec.containers[0]

    peers_file = next(var for var in container.env if var.name == "OPENCLAW_HONCHO_PEERS_FILE")
    mount = next(m for m in container.volume_mounts if m.name == "data")

    assert peers_file.value.startswith(f"{mount.mount_path}/")


def test_start_sh_installs_the_honcho_plugin_only_when_the_overlay_selects_it() -> None:
    """`openclaw plugins install` rewrites plugins.slots.memory, so installing it
    unconditionally would move every Agent off file-backed memory regardless of
    configuration."""
    assert "@honcho-ai/openclaw-honcho" in START_SH

    install_line = next(line for line in START_SH.splitlines() if "@honcho-ai/openclaw-honcho" in line)
    guard = START_SH[: START_SH.index(install_line)]
    assert "grep -q '\"openclaw-honcho\"' /app/config/openclaw-config-overlay.json" in guard


def test_honcho_entry_allows_conversation_access() -> None:
    """The runtime blocks a non-bundled plugin's `agent_end` hook unless this is
    set, so without it nothing is ever captured and memory stays silently empty.
    The plugin sets the flag itself and asks for a restart — meaning a first run
    captures nothing — so the builder has to emit it up front."""
    config = build_openclaw_gateway_config(
        "litellm/gpt-5",
        "http://litellm:4000",
        honcho_base_url="http://honcho:8000",
        honcho_workspace_id="af-x",
    )

    entry = config["plugins"]["entries"]["openclaw-honcho"]
    assert entry["hooks"]["allowConversationAccess"] is True


def test_recall_hook_gets_longer_than_the_runtime_default() -> None:
    """Recall runs a dialectic query on `before_prompt_build` — an LLM call with a
    tool loop, measured at ~25s against a real workspace. The runtime's 15s default
    kills it every turn, so capture works while recall silently never arrives."""
    config = build_openclaw_gateway_config(
        "litellm/gpt-5",
        "http://litellm:4000",
        honcho_base_url="http://honcho:8000",
        honcho_workspace_id="af-x",
    )

    assert config["plugins"]["entries"]["openclaw-honcho"]["hooks"]["timeoutMs"] > 25_000


def test_start_sh_falls_back_to_memory_core_when_the_plugin_is_missing() -> None:
    """Without a fallback the Agent starts with no memory backend at all — worse
    than the file-backed memory Honcho replaced."""
    assert "falling back to file-backed memory-core" in START_SH
    assert '"memory-core"' in START_SH


def test_start_sh_does_not_report_an_already_installed_plugin_as_a_failure() -> None:
    """The plugin lives on the PVC, so every restart after the first re-reports it
    as already present — the healthy steady state, not a failure."""
    assert "honcho plugin already installed" in START_SH
