from uuid import UUID

from api.domains.agents.builders import (
    build_hermes_config_map,
    build_hermes_deployment,
    build_hermes_gateway_config,
    build_honcho_config,
    build_secret_hermes_runtime,
    native_discord_env,
    native_slack_env,
    native_telegram_env,
    runtime_teams_env,
)
from api.domains.agents.builders.hermes import HERMES_BOOTLOADER_FOOTER, HERMES_START_SH
from api.domains.communications.models import ConversationLocation

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


def test_gateway_config_is_headless_and_keeps_telemetry() -> None:
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["display"]["platforms"] == {}
    assert config["plugins"]["enabled"] == ["telemetry-push", "agentbarn-messaging"]
    assert "slack" not in config
    assert "telegram" not in config
    assert "discord" not in config


def test_native_slack_config_enables_the_observer_and_ignores_unknown_dms() -> None:
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", native_slack=True)

    assert config["plugins"]["enabled"] == ["telemetry-push", "agentbarn-messaging", "agentbarn-observer"]
    assert config["slack"]["unauthorized_dm_behavior"] == "ignore"
    assert config["platforms"]["slack"]["extra"]["markdown_blocks"] is True
    assert config["display"]["platforms"]["slack"]["tool_progress"] == "off"
    assert config["display"]["platforms"]["slack"]["interim_assistant_messages"] is False

    verbose = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", native_slack=True, verbose_mode=True)
    assert verbose["display"]["platforms"]["slack"]["tool_progress"] == "all"
    assert verbose["display"]["platforms"]["slack"]["tool_progress_grouping"] == "accumulate"
    assert verbose["display"]["platforms"]["slack"]["interim_assistant_messages"] is True


def test_native_slack_env_maps_connection_policy() -> None:
    credentials = {"bot_token": "xoxb-1", "app_token": "xapp-1"}

    locked = native_slack_env(
        {"group_policy": "allowlist", "channel_ids": ["C1", "C2"], "dm_policy": "off"},
        credentials,
    )
    assert locked["SLACK_BOT_TOKEN"] == "xoxb-1"
    assert locked["SLACK_APP_TOKEN"] == "xapp-1"
    assert locked["SLACK_ALLOWED_CHANNELS"] == "C1,C2"
    assert locked["SLACK_DISABLE_DMS"] == "true"
    assert locked["SLACK_ALLOW_ALL_USERS"] == "true"
    assert locked["SLACK_THREAD_REQUIRE_MENTION"] == "true"

    open_env = native_slack_env(
        {
            "group_policy": "open",
            "dm_policy": "allowlist",
            "dm_user_ids": ["U1"],
            "thread_mention_policy": "start_only",
        },
        credentials,
    )
    assert "SLACK_ALLOWED_CHANNELS" not in open_env
    assert open_env["SLACK_DISABLE_DMS"] == "false"
    assert open_env["SLACK_ALLOWED_USERS"] == "U1"
    assert "SLACK_ALLOW_ALL_USERS" not in open_env
    assert open_env["SLACK_THREAD_REQUIRE_MENTION"] == "false"
    assert open_env["AGENTBARN_SCHEDULED_DELIVERY"] == "0"
    assert open_env["SLACK_HOME_CHANNEL"] == "__agentbarn_no_home_channel__"

    home = native_slack_env(
        {},
        credentials,
        ConversationLocation(id="C9", type="CHANNEL", display_name="alerts", thread_id="1700000000.000100"),
    )
    assert home["SLACK_HOME_CHANNEL"] == "C9"
    assert home["SLACK_HOME_CHANNEL_NAME"] == "alerts"
    assert home["SLACK_HOME_CHANNEL_THREAD_ID"] == "1700000000.000100"


def test_native_discord_config_enables_observer_and_maps_verbose_mode() -> None:
    config = build_hermes_gateway_config(
        "litellm/gpt-5",
        "http://litellm:4000",
        native_discord=True,
        discord_require_mention=False,
    )

    assert config["plugins"]["enabled"] == ["telemetry-push", "agentbarn-messaging", "agentbarn-observer"]
    assert config["discord"] == {"require_mention": False, "thread_require_mention": False}
    assert config["display"]["platforms"]["discord"]["tool_progress"] == "off"

    verbose = build_hermes_gateway_config(
        "litellm/gpt-5", "http://litellm:4000", native_discord=True, verbose_mode=True
    )
    assert verbose["display"]["platforms"]["discord"]["tool_progress"] == "all"
    assert verbose["display"]["platforms"]["discord"]["tool_progress_grouping"] == "accumulate"
    assert verbose["display"]["platforms"]["discord"]["interim_assistant_messages"] is True


def test_native_discord_env_maps_hermes_authorization_gates() -> None:
    settings = {
        "allowed_channel_ids": ["channel-1"],
        "allowed_user_ids": ["user-1"],
        "allowed_role_ids": ["role-1"],
        "allow_all_users": False,
        "home_channel_id": "channel-home",
    }

    env = native_discord_env(settings, {"bot_token": "discord-token"})

    assert env["DISCORD_BOT_TOKEN"] == "discord-token"
    assert env["DISCORD_ALLOW_ALL_USERS"] == "false"
    assert env["DISCORD_ALLOWED_CHANNELS"] == "channel-1"
    assert env["DISCORD_ALLOWED_USERS"] == "user-1"
    assert env["DISCORD_ALLOWED_ROLES"] == "role-1"
    assert env["DISCORD_HOME_CHANNEL"] == "channel-home"
    assert env["AGENTBARN_SCHEDULED_DELIVERY"] == "0"
    assert "AGENTBARN_DISCORD_POLICY" not in env


def test_native_discord_env_uses_a_sentinel_when_home_is_unset() -> None:
    env = native_discord_env({}, {"bot_token": "discord-token"})

    assert env["DISCORD_HOME_CHANNEL"] == "__agentbarn_no_home_channel__"


_TELEGRAM_TOKEN = {"bot_token": "123:abc"}


def test_native_telegram_config_ignores_unknown_dms() -> None:
    config = build_hermes_gateway_config(
        "litellm/gpt-5", "http://litellm:4000", telegram_settings={"group_policy": "open"}
    )

    assert config["plugins"]["enabled"] == ["telemetry-push", "agentbarn-messaging", "agentbarn-observer"]
    assert config["telegram"] == {"unauthorized_dm_behavior": "ignore"}
    assert config["display"]["platforms"]["telegram"]["tool_progress"] == "off"


def test_native_telegram_config_closes_groups_without_an_allowlist() -> None:
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", telegram_settings={})

    assert config["telegram"]["group_allow_from"] == []


def test_native_telegram_config_treats_blank_chat_ids_as_no_allowlist() -> None:
    # Hermes reads a missing chat allowlist as "any group", so blanks must close groups.
    config = build_hermes_gateway_config(
        "litellm/gpt-5", "http://litellm:4000", telegram_settings={"allowed_chat_ids": [""], "dm_policy": "open"}
    )

    assert config["telegram"]["group_allow_from"] == []


def test_native_telegram_config_shows_tool_progress_in_verbose_mode() -> None:
    config = build_hermes_gateway_config(
        "litellm/gpt-5", "http://litellm:4000", telegram_settings={}, verbose_mode=True
    )

    assert config["display"]["platforms"]["telegram"]["tool_progress"] == "all"


def test_native_telegram_env_confines_groups_to_the_allowlist_and_requires_mentions() -> None:
    env = native_telegram_env({"allowed_chat_ids": ["-1001"], "allowed_user_ids": ["111"]}, _TELEGRAM_TOKEN)

    assert env == {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "TELEGRAM_REQUIRE_MENTION": "true",
        "AGENTBARN_SCHEDULED_DELIVERY": "0",
        "TELEGRAM_ALLOWED_CHATS": "-1001",
        "TELEGRAM_GROUP_ALLOWED_CHATS": "-1001",
        "TELEGRAM_HOME_CHANNEL": "__agentbarn_no_home_channel__",
    }


def test_native_telegram_env_opens_groups_and_dms() -> None:
    env = native_telegram_env({"group_policy": "open", "dm_policy": "open"}, _TELEGRAM_TOKEN)

    assert env["TELEGRAM_GROUP_ALLOWED_CHATS"] == "*"
    assert "TELEGRAM_ALLOWED_CHATS" not in env
    assert env["TELEGRAM_ALLOW_ALL_USERS"] == "true"


def test_native_telegram_env_maps_the_dm_allowlist() -> None:
    env = native_telegram_env({"dm_policy": "allowlist", "allowed_user_ids": ["111"]}, _TELEGRAM_TOKEN)

    assert env["TELEGRAM_ALLOWED_USERS"] == "111"
    assert "TELEGRAM_GROUP_ALLOWED_CHATS" not in env
    assert "TELEGRAM_ALLOW_ALL_USERS" not in env


def test_native_telegram_env_sets_the_home_chat() -> None:
    env = native_telegram_env({"home_channel_id": "-1009"}, _TELEGRAM_TOKEN)

    assert env["TELEGRAM_HOME_CHANNEL"] == "-1009"


def test_runtime_teams_config_enables_observer_and_verbose_progress() -> None:
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", runtime_teams=True, verbose_mode=True)

    assert "agentbarn-observer" in config["plugins"]["enabled"]
    assert config["display"]["platforms"]["teams"] == {
        "tool_progress": "all",
        "tool_progress_grouping": "accumulate",
        "interim_assistant_messages": True,
    }


def test_runtime_teams_env_keeps_credentials_in_the_secret_and_sets_home() -> None:
    env = runtime_teams_env(
        {"home_channel_id": "19:home@thread.tacv2"},
        {"app_id": "app-id", "app_password": "secret", "tenant_id": "tenant-id"},
    )

    assert env == {
        "TEAMS_CLIENT_ID": "app-id",
        "TEAMS_CLIENT_SECRET": "secret",
        "TEAMS_TENANT_ID": "tenant-id",
        "TEAMS_ALLOW_ALL_USERS": "true",
        "TEAMS_PORT": "3978",
        "TEAMS_HOME_CHANNEL": "19:home@thread.tacv2",
        "AGENTBARN_SCHEDULED_DELIVERY": "0",
    }


def test_runtime_teams_env_uses_no_home_sentinel() -> None:
    env = runtime_teams_env({}, {"app_id": "app-id", "app_password": "secret", "tenant_id": "tenant-id"})

    assert env["TEAMS_HOME_CHANNEL"] == "__agentbarn_no_home_channel__"


def test_native_gateway_does_not_drain_agent_barn_scheduled_completions() -> None:
    guarded = HERMES_START_SH.split(
        'if [ "${AGENTBARN_SCHEDULED_DELIVERY}" = "1" ]; then',
        1,
    )[1].split("\nfi", 1)[0]

    assert "python3 /app/config/agentbarn_message.py drain &" in guarded


def test_gateway_config_enables_persistent_memory_for_scheduled_runs() -> None:
    config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["memory"]["memory_enabled"] is True
    assert config["memory"]["user_profile_enabled"] is True


def test_hermes_startup_context_exposes_runtime_memory_paths() -> None:
    assert "/opt/data/memories/USER.md" in HERMES_BOOTLOADER_FOOTER
    assert "/opt/data/memories/MEMORY.md" in HERMES_BOOTLOADER_FOOTER
    assert "/workspace/memory/YYYY-MM-DD.md" in HERMES_BOOTLOADER_FOOTER
    assert "Do not\nread or write `/workspace/USER.md`" in HERMES_BOOTLOADER_FOOTER


def test_gateway_config_maps_approval_mode_onto_approvals_policy() -> None:
    """Hermes is the only runtime that maps approval_mode onto a runtime policy
    (AF-272): manual/auto/off must keep mapping to manual/smart/off.
    """

    def approvals(mode: str) -> dict:
        return build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", approval_mode=mode)["approvals"]

    policy = {"timeout": 300, "cron_mode": "deny", "single_query_mode": "deny"}
    assert approvals("manual") == {"mode": "manual", **policy}
    assert approvals("auto") == {"mode": "smart", **policy}
    assert approvals("off") == {"mode": "off", **policy}


def test_gateway_config_routes_auxiliary_llm_tasks_through_the_litellm_proxy() -> None:
    """Auxiliary tasks left on the openrouter lane reach the proxy without the
    agent's key; smart approval then escalates every flagged command to the user.
    """
    auxiliary = build_hermes_gateway_config("litellm/gpt-5", "http://localhost:8090")["auxiliary"]

    expected = {"provider": "custom", "base_url": "http://localhost:8090", "model": "gpt-5"}
    assert {"approval", "title_generation", "vision"} <= auxiliary.keys()
    assert all(task == expected for task in auxiliary.values())


def test_gateway_config_pins_approval_policy_rather_than_inheriting_upstream_defaults() -> None:
    """Every key here matches the pinned image's own default, so this changes no
    behaviour today -- it stops a Hermes upgrade from moving the policy silently.
    `unattended_mode` is deliberately absent: v2026.8.19 does not read it, so
    writing it would be a no-op rather than an error.
    """
    approvals = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")["approvals"]

    assert approvals == {
        "mode": "smart",
        "timeout": 300,
        "cron_mode": "deny",
        "single_query_mode": "deny",
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
    # Pinned Hermes ships no gateway:startup hook, so BOOT.md only runs if we drive it.
    assert "boot-run.py" in config_map.data
    assert "agentbarn_message.py" in config_map.data
    # OpenClaw's plugin has no business in a Hermes ConfigMap.
    assert "openclaw-messaging.js" not in config_map.data
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
    assert secret.string_data["RUNTIME_KIND"] == "hermes"
    assert secret.string_data["VERBOSE_MODE"] == "false"
    assert not any(key.startswith(("SLACK_", "TELEGRAM_", "DISCORD_", "MSTEAMS_")) for key in secret.string_data)


def test_runtime_secret_verbose_mode_toggle() -> None:
    secret = build_secret_hermes_runtime(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        "Test Agent",
        runtime_api_key="runtime-key",
        litellm_api_key="llm-key",
        litellm_base_url="http://litellm:4000",
        verbose_mode=True,
    )

    assert secret.string_data["VERBOSE_MODE"] == "true"


def test_runtime_secret_tells_the_adapter_the_approval_mode() -> None:
    secret = build_secret_hermes_runtime(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        "Test Agent",
        runtime_api_key="runtime-key",
        litellm_api_key="llm-key",
        litellm_base_url="http://litellm:4000",
        approval_mode="manual",
    )

    assert secret.string_data["APPROVAL_MODE"] == "manual"


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
