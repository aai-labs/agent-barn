import copy
import json
from pathlib import Path
from uuid import UUID

from api.domains.agent_sizes.models import (
    STANDARD_CPU_LIMIT_MILLICORES,
    STANDARD_CPU_REQUEST_MILLICORES,
    STANDARD_MEMORY_LIMIT_BYTES,
    STANDARD_MEMORY_REQUEST_BYTES,
)
from api.domains.agents.builders import (
    build_config_map,
    build_deployment,
    build_openclaw_gateway_config,
    container_resources,
    native_discord_channel,
    native_slack_channel,
    native_telegram_channel,
    runtime_teams_channel,
)
from api.domains.agents.builders.openclaw import (
    LISTEN_IN_SYSTEM_PROMPT,
    OPENCLAW_WORKSPACE_DIR,
    START_SH,
    OpenClawBot,
    multi_agent_gateway_config,
    multi_agent_runtime_env,
)

PARENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
BOT_A = UUID("0000000a-0000-4000-8000-00000000000a")
BOT_B = UUID("0000000b-0000-4000-8000-00000000000b")
NS = "agent-farm"
PROXY = "http://localhost:8090"
STATE = "/home/node/.openclaw"
SCRIPTS = Path(__file__).resolve().parents[2] / "domains/agents/scripts/openclaw"
STANDARD = container_resources(
    cpu_request_millicores=STANDARD_CPU_REQUEST_MILLICORES,
    cpu_limit_millicores=STANDARD_CPU_LIMIT_MILLICORES,
    memory_request_bytes=STANDARD_MEMORY_REQUEST_BYTES,
    memory_limit_bytes=STANDARD_MEMORY_LIMIT_BYTES,
)
PARENT_SLACK = {
    "dm_policy": "allowlist",
    "dm_user_ids": ["U-PARENT"],
    "group_policy": "allowlist",
    "channel_ids": ["C1"],
}
BOT_SLACK = {"dm_policy": "off", "group_policy": "allowlist", "channel_ids": ["C2"]}
PARENT_TELEGRAM = {"dm_policy": "allowlist", "allowed_user_ids": ["111"], "allowed_chat_ids": ["-100"]}
BOT_TELEGRAM = {"dm_policy": "off", "allowed_chat_ids": ["-200"]}
POLICY_KEYS = {"dmPolicy", "groupPolicy", "allowFrom", "channels", "groups", "guilds", "groupAllowFrom"}


def _parent(channels=None, *, memory_enabled=False):
    channels = (
        {"slack": native_slack_channel(PARENT_SLACK), "telegram": native_telegram_channel(PARENT_TELEGRAM)}
        if channels is None
        else channels
    )
    return build_openclaw_gateway_config("litellm/gpt-5", PROXY, channels, memory_enabled=memory_enabled)


def _bot(bot_id, slot, channels, *, model="litellm/gpt-5-mini", memory_enabled=False):
    overlay = build_openclaw_gateway_config(model, PROXY, channels, memory_enabled=memory_enabled)
    return OpenClawBot(id=bot_id, slot=slot, overlay=overlay)


def _bots():
    return [
        _bot(BOT_A, 1, {"slack": native_slack_channel(BOT_SLACK), "telegram": native_telegram_channel(BOT_TELEGRAM)}),
        _bot(BOT_B, 2, {"discord": native_discord_channel({"allowed_user_ids": ["D1"]})}, model="litellm/gpt-5-nano"),
    ]


def test_a_parent_without_bots_keeps_its_single_agent_config():
    parent = _parent(memory_enabled=True)
    before = json.dumps(parent)

    config = multi_agent_gateway_config(parent, [])

    assert json.dumps(config) == before


def test_building_the_multi_agent_config_leaves_its_inputs_alone():
    parent, bots = _parent(), _bots()
    before = copy.deepcopy((parent, [bot.overlay for bot in bots]))

    multi_agent_gateway_config(parent, bots)

    assert (parent, [bot.overlay for bot in bots]) == before


def test_bots_make_the_gateway_multi_agent_with_main_as_the_parent():
    agents = multi_agent_gateway_config(_parent(), _bots())["agents"]

    assert agents["ownership"] == "explicit"
    assert agents["defaults"]["systemAgent"] == {"agentId": "main"}
    assert agents["entries"] == {
        "main": {"workspace": OPENCLAW_WORKSPACE_DIR},
        str(BOT_A): {
            "workspace": f"{STATE}/workspace-{BOT_A}",
            "agentDir": f"{STATE}/agents/{BOT_A}/agent",
            "model": {"primary": "litellm-bot-1/gpt-5-mini"},
        },
        str(BOT_B): {
            "workspace": f"{STATE}/workspace-{BOT_B}",
            "agentDir": f"{STATE}/agents/{BOT_B}/agent",
            "model": {"primary": "litellm-bot-2/gpt-5-nano"},
        },
    }
    assert agents["defaults"]["model"] == {"primary": "litellm/gpt-5"}


def test_each_bot_bills_its_own_key_read_from_a_private_file():
    config = multi_agent_gateway_config(_parent(), _bots())

    assert config["models"]["providers"]["litellm"] == _parent()["models"]["providers"]["litellm"]
    assert config["models"]["providers"]["litellm-bot-1"] == {
        "baseUrl": PROXY,
        "api": "openai-completions",
        "auth": "api-key",
        "apiKey": {"source": "file", "provider": "bot1", "id": "/LITELLM_API_KEY"},
        "models": [{"id": "gpt-5-mini", "name": "gpt-5-mini"}],
    }
    assert config["secrets"]["providers"] == {
        "bot1": {"source": "file", "path": f"/tmp/agentbarn-keys/{BOT_A}.json", "mode": "json"},
        "bot2": {"source": "file", "path": f"/tmp/agentbarn-keys/{BOT_B}.json", "mode": "json"},
    }


def test_a_platform_the_parent_shares_with_a_bot_moves_the_parent_to_its_own_account():
    parent = _parent()
    slack = multi_agent_gateway_config(parent, _bots())["channels"]["slack"]

    assert set(slack) == {"enabled", "defaultAccount", "accounts"}
    assert slack["defaultAccount"] == "default"
    expected_parent = {key: value for key, value in parent["channels"]["slack"].items() if key != "enabled"}
    assert slack["accounts"]["default"] == expected_parent


def test_a_bot_account_holds_only_its_own_policy_and_its_token_references():
    slack = multi_agent_gateway_config(_parent(), _bots())["channels"]["slack"]
    own = {key: value for key, value in native_slack_channel(BOT_SLACK).items() if key != "enabled"}

    assert slack["accounts"][str(BOT_A)] == {
        **own,
        "botToken": {"source": "file", "provider": "bot1", "id": "/SLACK_BOT_TOKEN"},
        "appToken": {"source": "file", "provider": "bot1", "id": "/SLACK_APP_TOKEN"},
    }
    assert "allowFrom" not in slack["accounts"][str(BOT_A)]
    assert not POLICY_KEYS & set(slack)


def test_telegram_and_discord_bot_accounts_reference_their_own_tokens():
    channels = multi_agent_gateway_config(_parent(), _bots())["channels"]

    assert channels["telegram"]["accounts"][str(BOT_A)]["botToken"] == {
        "source": "file",
        "provider": "bot1",
        "id": "/TELEGRAM_BOT_TOKEN",
    }
    assert channels["discord"]["accounts"][str(BOT_B)]["token"] == {
        "source": "file",
        "provider": "bot2",
        "id": "/DISCORD_BOT_TOKEN",
    }


def test_a_platform_only_a_bot_uses_has_no_parent_account():
    discord = multi_agent_gateway_config(_parent(), _bots())["channels"]["discord"]

    assert set(discord) == {"enabled", "accounts"}
    assert list(discord["accounts"]) == [str(BOT_B)]


def test_a_platform_only_the_parent_uses_stays_as_it_was():
    teams = runtime_teams_channel({})
    parent = _parent({"msteams": teams, "slack": native_slack_channel(PARENT_SLACK)})

    channels = multi_agent_gateway_config(parent, _bots())["channels"]

    assert channels["msteams"] == teams


def test_every_account_is_bound_to_its_own_agent():
    parent = _parent({"msteams": runtime_teams_channel({}), "slack": native_slack_channel(PARENT_SLACK)})

    bindings = multi_agent_gateway_config(parent, _bots())["bindings"]

    assert bindings == [
        {"type": "route", "agentId": "main", "match": {"channel": "msteams"}},
        {"type": "route", "agentId": "main", "match": {"channel": "slack", "accountId": "default"}},
        {"type": "route", "agentId": str(BOT_A), "match": {"channel": "slack", "accountId": str(BOT_A)}},
        {"type": "route", "agentId": str(BOT_A), "match": {"channel": "telegram", "accountId": str(BOT_A)}},
        {"type": "route", "agentId": str(BOT_B), "match": {"channel": "discord", "accountId": str(BOT_B)}},
    ]


def test_channel_plugins_and_the_observer_cover_every_bots_platform():
    plugins = multi_agent_gateway_config(_parent({}), _bots())["plugins"]

    assert {"slack", "telegram", "discord", "agentbarn-observer"} <= set(plugins["allow"])
    assert len(plugins["allow"]) == len(set(plugins["allow"]))
    for key in ("slack", "telegram", "discord"):
        assert plugins["entries"][key] == {"enabled": True}
    assert plugins["entries"]["agentbarn-observer"]["enabled"] is True
    assert plugins["load"]["paths"].count(f"{STATE}/local-plugins/agentbarn-observer") == 1


def test_bot_sessions_stay_out_of_the_parents_memory_bank():
    entry = multi_agent_gateway_config(_parent(memory_enabled=True), _bots())["plugins"]["entries"][
        "hindsight-openclaw"
    ]

    assert entry["enabled"] is True
    assert entry["config"]["ignoreSessionPatterns"] == [f"agent:{BOT_A}:**", f"agent:{BOT_B}:**"]


def test_a_bot_with_memory_does_not_turn_on_automatic_memory_for_the_pod():
    bot = _bot(BOT_A, 1, {}, memory_enabled=True)

    plugins = multi_agent_gateway_config(_parent(), [bot])["plugins"]

    assert plugins["entries"]["hindsight-openclaw"] == {"enabled": False}
    assert "hindsight-openclaw" not in plugins["allow"]


def test_every_agent_gets_active_memory_and_no_agent_can_message_another():
    config = multi_agent_gateway_config(_parent(), _bots())

    assert config["plugins"]["entries"]["active-memory"]["config"]["agents"] == ["main", str(BOT_A), str(BOT_B)]
    assert config["tools"]["agentToAgent"] == {"enabled": False}


def test_a_bots_listen_in_room_lets_room_events_through():
    listening = native_telegram_channel({"allowed_chat_ids": ["-300"], "listen_in_chat_ids": ["-300"]})
    assert listening["groups"]["-300"]["systemPrompt"] == LISTEN_IN_SYSTEM_PROMPT

    config = multi_agent_gateway_config(_parent({}), [_bot(BOT_A, 1, {"telegram": listening})])

    assert config["messages"]["groupChat"]["unmentionedInbound"] == "room_event"


def test_a_parent_with_bots_is_reached_as_main_and_installs_every_platform():
    parent_env = {"RUNTIME_MODEL": "openclaw/default", "AGENTBARN_NATIVE_CHANNELS": "slack,telegram"}

    env = multi_agent_runtime_env(parent_env, _bots())

    assert env == {
        "RUNTIME_MODEL": "openclaw/main",
        "RUNTIME_SESSION_PREFIX": "agent:main:",
        "AGENTBARN_NATIVE_CHANNELS": "slack,telegram,discord",
    }


def test_a_parent_without_bots_keeps_its_runtime_env():
    assert multi_agent_runtime_env({"RUNTIME_MODEL": "openclaw/default"}, []) == {}


def test_a_parent_without_bots_mounts_nothing_for_bots():
    pod = build_deployment(PARENT_ID, ORG_ID, NS, "openclaw:test", resources=STANDARD).spec.template.spec

    assert not [volume for volume in pod.volumes if volume.name.startswith("bot-")]


def test_each_bots_secret_and_config_map_are_mounted_read_only_and_optional():
    pod = build_deployment(
        PARENT_ID, ORG_ID, NS, "openclaw:test", resources=STANDARD, bot_ids=[BOT_A, BOT_B]
    ).spec.template.spec
    volumes = {volume.name: volume for volume in pod.volumes}
    mounts = {mount.name: mount for mount in pod.containers[0].volume_mounts}

    for bot in (BOT_A, BOT_B):
        secret = volumes[f"bot-{bot}-secret"].secret
        config = volumes[f"bot-{bot}-config"].config_map
        assert (secret.secret_name, secret.optional) == (f"agent-{bot}", True)
        assert (config.name, config.optional) == (f"agent-{bot}", True)
        assert (mounts[f"bot-{bot}-secret"].mount_path, mounts[f"bot-{bot}-secret"].read_only) == (
            f"/run/agentbarn/bots/{bot}",
            True,
        )
        assert mounts[f"bot-{bot}-config"].mount_path == f"/app/bots/{bot}"


def test_the_parents_config_map_carries_the_bot_manifest():
    manifest = json.dumps({"bots": [{"id": str(BOT_A), "slot": 1}], "deleted_ids": []})

    config_map = build_config_map(
        PARENT_ID,
        ORG_ID,
        NS,
        "soul",
        "identity",
        "user",
        "tools",
        "agents",
        "boot",
        "bootstrap",
        "heartbeat",
        openclaw_config_overlay=_parent(),
        bots_manifest=manifest,
    )

    assert config_map.data["bots.json"] == manifest
    assert config_map.data["bot-setup.py"] == (SCRIPTS / "bot-setup.py").read_text()
    assert config_map.data["bot-run.py"] == (SCRIPTS / "bot-run.py").read_text()
    plugin = SCRIPTS / "plugins/agentbarn-bot-env"
    assert config_map.data["agentbarn-bot-env-index.js"] == (plugin / "index.js").read_text()
    assert config_map.data["agentbarn-bot-env-package.json"] == (plugin / "package.json").read_text()
    assert config_map.data["agentbarn-bot-env-plugin.json"] == (plugin / "openclaw.plugin.json").read_text()


def test_a_parent_without_bots_ships_no_bot_manifest():
    config_map = build_config_map(
        PARENT_ID,
        ORG_ID,
        NS,
        "soul",
        "identity",
        "user",
        "tools",
        "agents",
        "boot",
        "bootstrap",
        "heartbeat",
        openclaw_config_overlay=_parent(),
    )

    assert not [name for name in config_map.data if name.startswith(("bots.json", "bot-", "agentbarn-bot-env"))]


def test_every_agents_commands_go_through_the_bot_env_plugin_with_the_parents_secret_names():
    config = multi_agent_gateway_config(_parent(), _bots(), parent_env_names=["MEMORY_API_KEY", "AGENT_ID"])
    plugins = config["plugins"]

    assert "agentbarn-bot-env" in plugins["allow"]
    assert plugins["load"]["paths"].count(f"{STATE}/local-plugins/agentbarn-bot-env") == 1
    assert plugins["entries"]["agentbarn-bot-env"] == {
        "enabled": True,
        "config": {
            "parentNames": ["AGENT_ID", "MEMORY_API_KEY"],
            "platforms": {"main": ["slack", "telegram"], str(BOT_A): ["slack", "telegram"], str(BOT_B): ["discord"]},
        },
    }


def test_a_parent_without_bots_does_not_load_the_bot_env_plugin():
    config = multi_agent_gateway_config(_parent(), [], parent_env_names=["AGENT_ID"])

    assert "agentbarn-bot-env" not in json.dumps(config)


def test_startup_installs_the_bot_env_plugin_only_for_a_parent_with_bots():
    guard = START_SH.index('if [ -f /app/config/bots.json ]; then\n  BOT_ENV_DIR="')
    install = START_SH.index('cp /app/config/agentbarn-bot-env-index.js "$BOT_ENV_DIR/index.js"')

    assert guard < install < START_SH.index("exec openclaw gateway")
