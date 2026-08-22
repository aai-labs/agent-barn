from uuid import UUID

from api.domains.agents.builders import (
    build_hermes_config_map,
    build_hermes_deployment,
    build_hermes_gateway_config,
    build_secret_hermes_runtime,
)

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


def test_gateway_config_is_headless_and_keeps_telemetry() -> None:
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["display"]["platforms"] == {}
    assert config["plugins"]["enabled"] == ["telemetry-push"]
    assert "slack" not in config
    assert "telegram" not in config
    assert "discord" not in config


def test_config_map_contains_runtime_adapter_and_no_provider_policy_plugins() -> None:
    config_map = build_hermes_config_map(
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

    assert "communications-runtime-adapter.py" in config_map.data
    assert not any("allowlist" in name or "deny-dms" in name for name in config_map.data)


def test_runtime_secret_contains_only_runtime_and_llm_credentials() -> None:
    secret = build_secret_hermes_runtime(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        "Test Agent",
        runtime_api_key="runtime-key",
        litellm_api_key="llm-key",
        litellm_base_url="http://litellm:4000",
    )

    assert secret.string_data["RUNTIME_API_KEY"] == "runtime-key"
    assert secret.string_data["API_SERVER_KEY"] == "runtime-key"
    assert not any(key.startswith(("SLACK_", "TELEGRAM_", "DISCORD_", "MSTEAMS_")) for key in secret.string_data)


def test_deployment_runs_one_headless_runtime_container() -> None:
    deployment = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:test")

    assert deployment.spec.replicas == 1
    assert deployment.spec.template.spec.containers[0].name == "agent"
