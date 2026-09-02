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
