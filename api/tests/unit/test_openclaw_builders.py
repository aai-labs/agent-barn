from uuid import UUID

from api.domains.agent_sizes.models import (
    STANDARD_CPU_LIMIT_MILLICORES,
    STANDARD_CPU_REQUEST_MILLICORES,
    STANDARD_MEMORY_LIMIT_BYTES,
    STANDARD_MEMORY_REQUEST_BYTES,
)
from api.domains.agents.builders import (
    START_SH,
    agentbarn_telegram_channel,
    agentbarn_telegram_channel_env,
    build_config_map,
    build_deployment,
    build_openclaw_gateway_config,
    build_secret_runtime,
    container_resources,
    native_channel_env,
    native_discord_channel,
    native_slack_channel,
    native_telegram_channel,
    runtime_teams_channel,
)
from api.domains.agents.builders.openclaw import (
    LEGACY_WORKSPACE_MIGRATION_SH,
    LISTEN_IN_SYSTEM_PROMPT,
    OPENCLAW_GATEWAY_PORT,
    OPENCLAW_PLUGINS_SH,
    OPENCLAW_WORKSPACE_DIR,
)
from api.domains.communications.models import ConversationLocation
from api.domains.communications.plugins.agentbarn_telegram import AgentBarnTelegramRuntime

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"

# The Standard size, which every Agent ran on before sizes existed.
STANDARD = container_resources(
    cpu_request_millicores=STANDARD_CPU_REQUEST_MILLICORES,
    cpu_limit_millicores=STANDARD_CPU_LIMIT_MILLICORES,
    memory_request_bytes=STANDARD_MEMORY_REQUEST_BYTES,
    memory_limit_bytes=STANDARD_MEMORY_LIMIT_BYTES,
)


def test_gateway_config_is_headless_and_exposes_chat_completions() -> None:
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["channels"] == {}
    assert config["bindings"] == []
    assert config["gateway"]["http"]["endpoints"]["chatCompletions"]["enabled"] is True


def test_gateway_config_disables_ambient_model_backed_heartbeats() -> None:
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["agents"]["defaults"]["heartbeat"] == {"every": "0m", "target": "none"}


def test_gateway_config_isolates_each_persons_direct_messages() -> None:
    """OpenClaw's default dmScope ("main") puts every sender's DMs in one session, so a
    multi-user Agent would show one person's private conversation to the next."""
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["session"]["dmScope"] == "per-channel-peer"


def test_workspace_comes_from_one_constant() -> None:
    """The file-delivery policy names OPENCLAW_WORKSPACE_DIR as the place to write
    attachments, so the runtime config and the migration script must use the same path."""
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["agents"]["defaults"]["workspace"] == OPENCLAW_WORKSPACE_DIR
    assert f"workspace={OPENCLAW_WORKSPACE_DIR}\n" in LEGACY_WORKSPACE_MIGRATION_SH
    assert "@OPENCLAW_WORKSPACE_DIR@" not in LEGACY_WORKSPACE_MIGRATION_SH


def test_startup_migrates_legacy_state_after_config_and_plugin_dirs_exist() -> None:
    migration = START_SH.index("legacy-workspace-migration.sh")

    assert START_SH.index("init-openclaw.js") < migration
    assert START_SH.index("init-openclaw.js") < START_SH.index("retire-messaging.py") < migration
    assert START_SH.index("$OBSERVER_DIR/openclaw.plugin.json") < migration
    assert migration < START_SH.index("OPENCLAW_VERSION=")


def test_config_map_ships_the_legacy_workspace_migration_script() -> None:
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
        openclaw_config_overlay={},
    )

    assert config_map.data["legacy-workspace-migration.sh"] == LEGACY_WORKSPACE_MIGRATION_SH
    assert config_map.data["openclaw-plugins.sh"] == OPENCLAW_PLUGINS_SH


def test_startup_sources_the_plugin_installer_before_installing_plugins() -> None:
    """install_plugin, with its repair of half-installed plugins, lives in openclaw-plugins.sh."""
    sourced = START_SH.index(". /app/config/openclaw-plugins.sh")

    assert START_SH.index("OPENCLAW_VERSION=") < sourced < START_SH.index("install_plugin @openclaw/firecrawl-plugin")


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
    assert "agent-trigger-server.py" in config_map.data
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
    assert secret.string_data["RUNTIME_KIND"] == "openclaw"
    assert not any(key.startswith(("SLACK_", "TELEGRAM_", "DISCORD_", "MSTEAMS_")) for key in secret.string_data)


def test_deployment_runs_one_headless_runtime_container() -> None:
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test", resources=STANDARD)

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
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test", resources=STANDARD)
    resources = deployment.spec.template.spec.containers[0].resources

    assert resources is not None
    assert resources.requests == {"memory": "320Mi", "cpu": "50m"}
    assert resources.limits == {"memory": "1Gi", "cpu": "500m"}


def test_init_container_costs_no_more_quota_than_the_agent() -> None:
    """A pod is charged the larger of its containers added up and its biggest init
    container. Left without a block, the init container gets the LimitRange default,
    which is above the agent's own and raises what every agent costs."""
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test", resources=STANDARD)
    pod = deployment.spec.template.spec
    init = pod.init_containers[0]

    assert init.resources == pod.containers[0].resources


def test_a_larger_size_grows_the_agent_container_and_not_the_init_container() -> None:
    """The init container only runs chown, so it keeps its fixed block whatever the size."""
    large = container_resources(
        cpu_request_millicores=500,
        cpu_limit_millicores=2000,
        memory_request_bytes=2 * 1024**3,
        memory_limit_bytes=4 * 1024**3,
    )
    pod = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test", resources=large).spec.template.spec

    assert pod.containers[0].resources.requests == {"memory": "2Gi", "cpu": "500m"}
    assert pod.containers[0].resources.limits == {"memory": "4Gi", "cpu": "2000m"}
    assert pod.init_containers[0].resources == STANDARD


def test_deployment_recreates_rather_than_rolling_update() -> None:
    """replicas=1 on a ReadWriteOnce PVC: a RollingUpdate surge briefly wants two
    pods, doubling the agent's memory and deadlocking on the volume."""
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test", resources=STANDARD)
    assert deployment.spec.strategy.type == "Recreate"


def test_deployment_carries_the_openclaw_runtime_label() -> None:
    deployment = build_deployment(_AGENT_ID, _ORG_ID, _NS, "openclaw:test", resources=STANDARD)
    assert deployment.metadata.labels["agentbarn.io/runtime"] == "openclaw"


def test_native_channels_enable_installed_plugins_and_the_observer() -> None:
    config = build_openclaw_gateway_config(
        "litellm/gpt-5", "http://litellm:4000", {"slack": {"enabled": True}, "discord": {"enabled": True}}
    )

    assert config["channels"] == {"slack": {"enabled": True}, "discord": {"enabled": True}}
    assert {"slack", "discord", "agentbarn-observer"} <= set(config["plugins"]["allow"])
    assert not any("@openclaw" in path for path in config["plugins"]["load"]["paths"])
    assert config["plugins"]["entries"]["agentbarn-observer"]["enabled"] is True
    assert "agentbarn-observer" not in build_openclaw_gateway_config("litellm/gpt-5", "http://x")["plugins"]["allow"]


def test_gateway_config_turns_unmentioned_chatter_into_room_events_on_listen_in_platforms() -> None:
    for key in ("slack", "discord", "telegram"):
        config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000", {key: {"enabled": True}})

        assert config["messages"] == {"groupChat": {"unmentionedInbound": "room_event"}}


def test_gateway_config_writes_user_requests_explicitly_without_a_listen_in_platform() -> None:
    for channels in (None, {"msteams": {"enabled": True}}):
        config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000", channels)

        assert config["messages"] == {"groupChat": {"unmentionedInbound": "user_request"}}


def test_listen_in_prompt_says_when_to_stay_silent_and_when_to_speak() -> None:
    assert "Stay silent" in LISTEN_IN_SYSTEM_PROMPT
    assert "factual error" in LISTEN_IN_SYSTEM_PROMPT
    assert "@mention" in LISTEN_IN_SYSTEM_PROMPT


def test_native_slack_channel_listens_in_on_chosen_channels() -> None:
    allowlisted = native_slack_channel({"channel_ids": ["C1", "C2"], "listen_in_channel_ids": ["C2"]})
    assert allowlisted["requireMention"] is True
    assert allowlisted["channels"] == {
        "C1": {"enabled": True},
        "C2": {"enabled": True, "requireMention": False, "systemPrompt": LISTEN_IN_SYSTEM_PROMPT},
    }

    unlisted = native_slack_channel({"channel_ids": ["C1"], "listen_in_channel_ids": ["C2"]})
    assert unlisted["channels"] == {"C1": {"enabled": True}}

    open_ = native_slack_channel({"group_policy": "open", "listen_in_channel_ids": ["C9"]})
    assert open_["groupPolicy"] == "open"
    assert open_["channels"] == {"C9": {"requireMention": False, "systemPrompt": LISTEN_IN_SYSTEM_PROMPT}}


def test_native_slack_channel_maps_connection_policy() -> None:
    locked = native_slack_channel({"channel_ids": ["C1"], "dm_user_ids": ["U1"], "dm_policy": "allowlist"})
    assert locked["streaming"] == {"mode": "partial"}
    assert locked["groupPolicy"] == "allowlist"
    assert locked["channels"] == {"C1": {"enabled": True}}
    assert locked["dmPolicy"] == "allowlist"
    assert locked["allowFrom"] == ["U1"]
    assert locked["implicitMentions"] == {"threadParticipation": False}
    assert "botToken" not in locked

    open_ = native_slack_channel(
        {"group_policy": "open", "dm_policy": "open", "thread_mention_policy": "start_only"},
        ConversationLocation(type="CHANNEL", id="C9"),
    )
    assert "channels" not in open_
    assert open_["dmPolicy"] == "open"
    assert open_["allowFrom"] == ["*"]
    assert open_["implicitMentions"] == {"threadParticipation": True}
    assert open_["defaultTo"] == "channel:C9"

    unset = native_slack_channel({})
    assert unset["dmPolicy"] == "disabled"
    # Meeting recordings run well past OpenClaw's 20 MB default; an hour of MP3 is ~60-90 MB.
    assert unset["mediaMaxMb"] == 100
    assert unset["defaultTo"] == "channel:__agentbarn_no_home_channel__"


def test_native_discord_channel_maps_global_gates_to_every_guild() -> None:
    gated = native_discord_channel(
        {
            "allowed_channel_ids": ["c1"],
            "allowed_user_ids": ["u1"],
            "allowed_role_ids": ["r1"],
            "require_mention": False,
            "home_channel_id": "home",
        }
    )
    assert gated["groupPolicy"] == "allowlist"
    assert gated["guilds"] == {
        "*": {
            "requireMention": True,
            "users": ["u1"],
            "roles": ["r1"],
            "channels": {"c1": {"enabled": True, "autoThread": True}},
        }
    }
    assert (gated["dmPolicy"], gated["allowFrom"]) == ("allowlist", ["u1"])
    assert gated["defaultTo"] == "channel:home"

    everyone = native_discord_channel({"allow_all_users": True, "allowed_user_ids": ["u1"]})
    assert everyone["guilds"] == {
        "*": {"requireMention": True, "channels": {"*": {"enabled": True, "autoThread": True}}}
    }
    assert (everyone["dmPolicy"], everyone["allowFrom"]) == ("open", ["*"])
    assert everyone["defaultTo"] == "channel:__agentbarn_no_home_channel__"

    # Channel-only access admits anyone in those channels, and no DMs.
    channels_only = native_discord_channel({"allowed_channel_ids": ["c1"]})
    assert channels_only["guilds"]["*"] == {
        "requireMention": True,
        "channels": {"c1": {"enabled": True, "autoThread": True}},
    }
    assert channels_only["dmPolicy"] == "disabled"

    closed = native_discord_channel({})
    assert (closed["groupPolicy"], closed["dmPolicy"]) == ("disabled", "disabled")
    assert "guilds" not in closed


def test_native_telegram_channel_confines_groups_to_the_allowlist_and_requires_mentions() -> None:
    channel = native_telegram_channel(
        {"allowed_chat_ids": ["-1001"], "dm_policy": "allowlist", "allowed_user_ids": ["111"]}
    )

    assert channel == {
        "enabled": True,
        "dmPolicy": "allowlist",
        "allowFrom": ["111"],
        "groupPolicy": "open",
        "groups": {"-1001": {"requireMention": True}},
        "defaultTo": "channel:__agentbarn_no_home_channel__",
    }


def test_native_telegram_channel_opens_groups_and_dms() -> None:
    channel = native_telegram_channel({"group_policy": "open", "dm_policy": "open"})

    assert channel["groups"] == {"*": {"requireMention": True}}
    assert (channel["dmPolicy"], channel["allowFrom"]) == ("open", ["*"])


def test_native_telegram_channel_is_closed_by_default() -> None:
    assert native_telegram_channel({"allowed_chat_ids": [""]}) == {
        "enabled": True,
        "dmPolicy": "disabled",
        "groupPolicy": "disabled",
        "defaultTo": "channel:__agentbarn_no_home_channel__",
    }


def test_native_telegram_channel_closes_dms_for_an_empty_allowlist() -> None:
    # An empty allowlist drops every DM anyway, and OpenClaw warns about it.
    assert native_telegram_channel({"dm_policy": "allowlist"})["dmPolicy"] == "disabled"


def test_native_telegram_channel_sets_the_home_chat() -> None:
    assert native_telegram_channel({"home_channel_id": "-1009"})["defaultTo"] == "-1009"


def test_runtime_teams_channel_uses_environment_credentials_and_the_private_webhook() -> None:
    channel = runtime_teams_channel({"home_channel_id": "19:home@thread.tacv2"})

    assert channel == {
        "enabled": True,
        "webhook": {"port": 3978, "path": "/api/messages"},
        "dmPolicy": "open",
        "allowFrom": ["*"],
        "groupPolicy": "open",
        "groupAllowFrom": ["*"],
        "defaultTo": "conversation:19:home@thread.tacv2",
    }


def test_runtime_teams_channel_uses_no_home_sentinel() -> None:
    assert runtime_teams_channel({})["defaultTo"] == "conversation:__agentbarn_no_home_channel__"


def test_native_channel_env_carries_tokens_and_hands_over_scheduled_delivery() -> None:
    env = native_channel_env(
        {
            "slack": {"bot_token": "xoxb", "app_token": "xapp"},
            "discord": {"bot_token": "discord-token"},
            "telegram": {"bot_token": "123:abc"},
            "msteams": {"app_id": "app-id", "app_password": "secret", "tenant_id": "tenant-id"},
        }
    )

    assert env == {
        "AGENTBARN_NATIVE_CHANNELS": "slack,discord,telegram,msteams",
        "SLACK_BOT_TOKEN": "xoxb",
        "SLACK_APP_TOKEN": "xapp",
        "DISCORD_BOT_TOKEN": "discord-token",
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "MSTEAMS_APP_ID": "app-id",
        "MSTEAMS_APP_PASSWORD": "secret",
        "MSTEAMS_TENANT_ID": "tenant-id",
    }


_AGENTBARN_TELEGRAM = AgentBarnTelegramRuntime(
    api_root="http://communications:8002/communications/v1/telegram/c0ffee",
    api_token="424242:stand-in",
    webhook_secret="derived-secret",
    webhook_url="http://agent-x.agent-farm.svc.cluster.local:8443/telegram",
)


def test_agentbarn_telegram_channel_uses_the_proxy_and_a_private_webhook() -> None:
    assert agentbarn_telegram_channel(_AGENTBARN_TELEGRAM) == {
        "enabled": True,
        "dmPolicy": "open",
        "allowFrom": ["*"],
        "groupPolicy": "disabled",
        "apiRoot": "http://communications:8002/communications/v1/telegram/c0ffee",
        "webhookUrl": "http://agent-x.agent-farm.svc.cluster.local:8443/telegram",
        # Resolved from the Secret at startup, so the secret never sits in openclaw.json.
        "webhookSecret": "${AGENTBARN_TELEGRAM_WEBHOOK_SECRET}",
        "webhookHost": "0.0.0.0",
        "webhookPort": 8443,
        "webhookPath": "/telegram",
        "defaultTo": "channel:__agentbarn_no_home_channel__",
    }


def test_agentbarn_telegram_secret_entries_carry_the_stand_in_token_and_webhook_secret() -> None:
    assert agentbarn_telegram_channel_env(_AGENTBARN_TELEGRAM) == {
        "TELEGRAM_BOT_TOKEN": "424242:stand-in",
        "AGENTBARN_TELEGRAM_WEBHOOK_SECRET": "derived-secret",
    }


def test_gateway_config_allows_native_message_tool() -> None:
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert "message" not in config["tools"].get("deny", [])


def test_artifact_command_and_instructions_are_available_without_memory() -> None:
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
        artifacts_enabled=True,
    )
    assert "agentbarn_artifacts.py" in config_map.data
    assert "exec python3 /app/config/agentbarn_artifacts.py" in config_map.data["agentbarn-artifacts"]
    assert "/usr/local/bin/agentbarn-artifacts upload" in config_map.data["AGENTS.md"]
    assert "Do not wait for the user to mention artifacts, storage or the CLI" in config_map.data["AGENTS.md"]
    assert "Do not publish scratch/intermediate files" in config_map.data["AGENTS.md"]
    assert "Give the user a concise Markdown download link" in config_map.data["AGENTS.md"]


def test_artifact_instructions_are_absent_when_storage_is_disabled() -> None:
    config_map = build_config_map(
        _AGENT_ID, _ORG_ID, _NS, "soul", "identity", "user", "tools", "agents", "boot", "bootstrap", "heartbeat"
    )
    assert "Files and download links" not in config_map.data["AGENTS.md"]
