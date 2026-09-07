from uuid import UUID

from api.domains.agents.builders import (
    build_hermes_config_map,
    build_hermes_deployment,
    build_hermes_gateway_config,
    build_honcho_config,
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


def test_gateway_config_enables_persistent_memory_for_scheduled_runs() -> None:
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["memory"]["memory_enabled"] is True
    assert config["memory"]["user_profile_enabled"] is True


def test_gateway_config_maps_approval_mode_onto_approvals_policy() -> None:
    """Hermes is the only runtime that maps approval_mode onto a runtime policy
    (AF-272): manual/auto/off must keep mapping to manual/smart/off.
    """
    assert build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", approval_mode="manual")["approvals"] == {
        "mode": "manual"
    }
    assert build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", approval_mode="auto")["approvals"] == {
        "mode": "smart"
    }
    assert build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", approval_mode="off")["approvals"] == {
        "mode": "off"
    }


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


def test_deployment_declares_explicit_resources_matching_openclaw() -> None:
    """Both runtimes get 1Gi so limits.memory (100Gi quota) never binds before
    requests.memory (20Gi) -- a 2Gi Hermes limit would cap an all-Hermes fleet at
    50 agents instead of 64. Unlike OpenClaw's V8 heap, this is a hard cap on
    Hermes' real working set, not a GC trigger."""
    deployment = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:test")
    resources = deployment.spec.template.spec.containers[0].resources

    assert resources is not None
    assert resources.requests == {"memory": "320Mi", "cpu": "50m"}
    assert resources.limits == {"memory": "1Gi", "cpu": "500m"}


def test_deployment_recreates_rather_than_rolling_update() -> None:
    deployment = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:test")
    assert deployment.spec.strategy.type == "Recreate"


def test_deployment_carries_the_hermes_runtime_label() -> None:
    deployment = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:test")
    assert deployment.metadata.labels["agentbarn.io/runtime"] == "hermes"


def _config_map(honcho_config: dict | None = None):
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
        honcho_config=honcho_config,
    )


def test_config_map_has_no_honcho_config_when_memory_is_not_backed_by_honcho() -> None:
    assert "honcho.json" not in _config_map().data


def test_config_map_carries_the_honcho_provider_config_when_configured() -> None:
    """Hermes resolves honcho.json from $HERMES_HOME first, and takes Honcho as a
    provider alongside MEMORY.md and USER.md rather than replacing them, which is
    the opposite of how OpenClaw's single memory slot works."""
    import json

    config = build_honcho_config(
        base_url="http://honcho:8000",
        workspace_id="af-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        agent_name="watcher",
    )
    honcho_json = json.loads(_config_map(config).data["honcho.json"])

    assert honcho_json["baseUrl"] == "http://honcho:8000"
    host = honcho_json["hosts"]["hermes"]
    assert host["enabled"] is True
    assert host["workspace"] == "af-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert host["aiPeer"]


def test_deployment_points_hermes_at_the_state_dir_it_actually_uses() -> None:
    """honcho.json is resolved from $HERMES_HOME before any other location. Without
    it Hermes looks in ~/.hermes, which is not the mounted state directory, and the
    provider config is silently never found."""
    deployment = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:test")
    container = deployment.spec.template.spec.containers[0]

    hermes_home = next(var for var in container.env if var.name == "HERMES_HOME")
    state_mount = next(m for m in container.volume_mounts if m.mount_path == "/opt/data")

    assert hermes_home.value == state_mount.mount_path


def test_start_sh_installs_the_honcho_provider_config_when_present() -> None:
    from api.domains.agents.builders.hermes import HERMES_START_SH

    assert "honcho.json" in HERMES_START_SH


def test_memory_provider_is_selected_when_honcho_is_enabled() -> None:
    """Writing honcho.json is not enough — Hermes activates an external provider
    through `memory.provider`, and without it runs built-in memory only while
    reporting "Provider: (none — built-in only)"."""
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", honcho_enabled=True)

    assert config["memory"]["provider"] == "honcho"
    assert config["memory"]["memory_enabled"] is True


def test_no_memory_provider_key_when_honcho_is_disabled() -> None:
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert "provider" not in config["memory"]
