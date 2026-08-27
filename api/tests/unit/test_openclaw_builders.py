from uuid import UUID

from api.domains.agents.builders import (
    START_SH,
    build_config_map,
    build_deployment,
    build_openclaw_gateway_config,
    build_secret_runtime,
)

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


def test_openclaw_gateway_port_is_pinned_to_the_adapter_target() -> None:
    # The in-pod communications adapter posts to RUNTIME_API_URL (127.0.0.1:8080).
    # Without an explicit --port the gateway binds its own default, the adapter
    # gets ECONNREFUSED, and every inbound delivery dead-letters while the pod
    # still reports healthy.
    assert "--port 8080" in START_SH
