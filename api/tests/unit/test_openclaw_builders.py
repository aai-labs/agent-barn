from uuid import UUID

from api.domains.agents.builders import (
    START_SH,
    build_config_map,
    build_deployment,
    build_openclaw_gateway_config,
    build_secret_runtime,
    native_channel_env,
    native_discord_channel,
    native_slack_channel,
    native_telegram_channel,
    runtime_teams_channel,
)
from api.domains.agents.builders.openclaw import LEGACY_WORKSPACE_MIGRATION_SH, OPENCLAW_GATEWAY_PORT
from api.domains.communications.models import ConversationLocation

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


def test_gateway_config_is_headless_and_exposes_chat_completions() -> None:
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["channels"] == {}
    assert config["bindings"] == []
    assert config["gateway"]["http"]["endpoints"]["chatCompletions"]["enabled"] is True


def test_gateway_config_disables_ambient_model_backed_heartbeats() -> None:
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert config["agents"]["defaults"]["heartbeat"] == {"every": "0m", "target": "none"}


def test_startup_migrates_legacy_state_after_config_and_plugin_dirs_exist() -> None:
    migration = START_SH.index("legacy-workspace-migration.sh")

    assert START_SH.index("init-openclaw.js") < migration
    assert START_SH.index("$MESSAGE_PLUGIN_DIR/openclaw.plugin.json") < migration
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
    assert secret.string_data["RUNTIME_KIND"] == "openclaw"
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


def test_gateway_config_stays_the_default_agent_when_memory_is_off() -> None:
    """Without memory, nothing declares an explicit agent entry — the runtime's
    implicit default agent "main" is untouched, so memory-off Agents are
    byte-for-byte as before."""
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")

    assert "list" not in config["agents"]
    assert config["plugins"]["entries"]["active-memory"]["config"]["agents"] == ["main"]


def test_gateway_config_gives_a_distinct_agent_identity_when_memory_is_on() -> None:
    """In a shared pool, Agents must have distinct Honcho peers. An explicit agent
    entry keyed by the distinct logical id makes the plugin name the peer
    `agent-<id>`; its workspace/agentDir are pinned to OpenClaw's defaults so
    opting in never relocates the Agent's files."""
    config = build_openclaw_gateway_config(
        "litellm/gpt-5",
        "http://litellm:4000",
        honcho_base_url="http://honcho:8000",
        honcho_workspace_id="af-pool-org-1",
        honcho_agent_id="01a0682a-c0cd-7702-8b9f-46bac319438f",
    )

    # The runtime schema is agents.list (an array), not agents.entries (a map).
    entries = config["agents"]["list"]
    entry = next(e for e in entries if e["id"] == "01a0682a-c0cd-7702-8b9f-46bac319438f")
    assert entry["default"] is True
    # Pinned to today's implicit defaults — opting in must not move files/sessions.
    assert entry["workspace"] == "~/.openclaw/workspace"
    assert entry["agentDir"] == "~/.openclaw/agents/main"
    # active-memory follows the same logical id, not the shared "main".
    assert config["plugins"]["entries"]["active-memory"]["config"]["agents"] == ["01a0682a-c0cd-7702-8b9f-46bac319438f"]


def test_pool_recall_plugin_loads_only_when_memory_is_on() -> None:
    """The first-party pool-wide recall plugin runs beside the stock Honcho
    plugin. It is loaded (allow + load path + entry) only when memory is on;
    a memory-off Agent never loads it."""
    off = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")
    assert "honcho-pool-recall" not in off["plugins"]["allow"]
    assert not any("honcho-pool-recall" in p for p in off["plugins"]["load"]["paths"])
    assert "honcho-pool-recall" not in off["plugins"]["entries"]

    on = build_openclaw_gateway_config(
        "litellm/gpt-5",
        "http://litellm:4000",
        honcho_base_url="http://honcho:8000",
        honcho_workspace_id="af-pool-org-1",
        honcho_agent_id="01a0682a-c0cd-7702-8b9f-46bac319438f",
    )
    assert "honcho-pool-recall" in on["plugins"]["allow"]
    assert any("honcho-pool-recall" in p for p in on["plugins"]["load"]["paths"])
    entry = on["plugins"]["entries"]["honcho-pool-recall"]
    assert entry["enabled"] is True
    # It needs conversation access so its before_prompt_build hook can read the turn.
    assert entry["hooks"]["allowConversationAccess"] is True


def test_config_map_ships_the_pool_recall_plugin_files() -> None:
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
    assert "honcho-pool-recall-index.js" in config_map.data
    assert "honcho-pool-recall-package.json" in config_map.data
    assert "honcho-pool-recall-plugin.json" in config_map.data


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


def test_honcho_config_ships_noise_patterns_for_the_memory_subagent() -> None:
    """The plugin's memory-search sub-agent otherwise captures its own instruction
    prompt as conclusions about the user. The patterns drop those turns; a regex
    entry (leading "/") is what the plugin tests anywhere in a message, so plain
    substrings would not catch a phrase mid-prompt."""
    config = build_openclaw_gateway_config(
        "litellm/gpt-5",
        "http://litellm:4000",
        honcho_base_url="http://honcho:8000",
        honcho_workspace_id="af-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    patterns = config["plugins"]["entries"]["openclaw-honcho"]["config"]["noisePatterns"]
    assert any("memory search agent" in p for p in patterns)
    assert all(p.startswith("/") for p in patterns), "content-anywhere match needs regex form"


def test_noise_patterns_absent_when_honcho_is_not_configured() -> None:
    """memory-core has no such sub-agent, so the patterns would be meaningless."""
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")
    assert "openclaw-honcho" not in config["plugins"]["entries"]


def test_native_channels_enable_installed_plugins_and_the_observer() -> None:
    config = build_openclaw_gateway_config(
        "litellm/gpt-5", "http://litellm:4000", {"slack": {"enabled": True}, "discord": {"enabled": True}}
    )

    assert config["channels"] == {"slack": {"enabled": True}, "discord": {"enabled": True}}
    assert {"slack", "discord", "agentbarn-observer"} <= set(config["plugins"]["allow"])
    assert not any("@openclaw" in path for path in config["plugins"]["load"]["paths"])
    assert config["plugins"]["entries"]["agentbarn-observer"]["enabled"] is True
    assert "agentbarn-observer" not in build_openclaw_gateway_config("litellm/gpt-5", "http://x")["plugins"]["allow"]


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
            "requireMention": False,
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
        "AGENTBARN_SCHEDULED_DELIVERY": "0",
        "SLACK_BOT_TOKEN": "xoxb",
        "SLACK_APP_TOKEN": "xapp",
        "DISCORD_BOT_TOKEN": "discord-token",
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "MSTEAMS_APP_ID": "app-id",
        "MSTEAMS_APP_PASSWORD": "secret",
        "MSTEAMS_TENANT_ID": "tenant-id",
    }
