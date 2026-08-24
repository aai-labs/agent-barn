from types import SimpleNamespace
from uuid import UUID

import yaml
from hamcrest import assert_that, contains_string, equal_to, has_key, is_not

from api.domains.agents.builders import (
    DISCORD_DENY_DMS_PLUGIN_INIT,
    DISCORD_GUILD_ALLOWLIST_PLUGIN_INIT,
    HERMES_START_SH,
    SLACK_CHANNEL_ALLOWLIST_PLUGIN_INIT,
    SLACK_DENY_DMS_PLUGIN_INIT,
    TELEGRAM_CHANNEL_ALLOWLIST_PLUGIN_INIT,
    TELEGRAM_DENY_DMS_PLUGIN_INIT,
    build_hermes_config,
    build_hermes_config_discord,
    build_hermes_config_map,
    build_hermes_config_telegram,
    build_hermes_deployment,
    build_secret_hermes_discord,
    build_secret_hermes_slack,
    build_secret_hermes_telegram,
)

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


def test_build_hermes_config_discord_uses_safe_mention_and_thread_defaults():
    cfg = build_hermes_config_discord("litellm/qwen3", "http://litellm:4000")

    assert_that(cfg["discord"]["require_mention"], equal_to(True))
    assert_that(cfg["discord"]["thread_require_mention"], equal_to(True))
    assert_that(cfg["discord"]["allow_mentions"], equal_to({"everyone": False, "roles": False}))
    assert_that("discord-deny-dms" in cfg["plugins"]["enabled"], equal_to(True))
    assert_that("discord-guild-allowlist" in cfg["plugins"]["enabled"], equal_to(True))


def test_build_hermes_config_discord_open_group_policy_drops_guild_gate():
    cfg = build_hermes_config_discord("litellm/qwen3", "http://litellm:4000", group_policy="open")

    assert_that("discord-deny-dms" in cfg["plugins"]["enabled"], equal_to(True))
    assert_that("discord-guild-allowlist" in cfg["plugins"]["enabled"], equal_to(False))


def test_discord_policy_plugin_sources_are_valid_python():
    compile(DISCORD_DENY_DMS_PLUGIN_INIT, "discord-deny-dms/__init__.py", "exec")
    compile(DISCORD_GUILD_ALLOWLIST_PLUGIN_INIT, "discord-guild-allowlist/__init__.py", "exec")


def test_discord_deny_dms_plugin_skips_direct_messages():
    namespace: dict = {}
    exec(DISCORD_DENY_DMS_PLUGIN_INIT, namespace)  # noqa: S102 - execute checked-in plugin source
    event = SimpleNamespace(source=SimpleNamespace(platform="discord", chat_type="dm"))

    assert_that(namespace["deny_discord_dms"](event), equal_to({"action": "skip", "reason": "discord-dm-denied"}))


def test_discord_guild_allowlist_plugin_fails_closed(monkeypatch):
    monkeypatch.setenv("DISCORD_GUILD_IDS", "guild-1")
    namespace: dict = {}
    exec(DISCORD_GUILD_ALLOWLIST_PLUGIN_INIT, namespace)  # noqa: S102 - execute checked-in plugin source
    allowed = SimpleNamespace(source=SimpleNamespace(platform="discord", chat_type="channel", guild_id="guild-1"))
    denied = SimpleNamespace(source=SimpleNamespace(platform="discord", chat_type="channel", guild_id="guild-2"))

    assert_that(namespace["filter_guild"](allowed), equal_to(None))
    assert_that(
        namespace["filter_guild"](denied),
        equal_to({"action": "skip", "reason": "discord-guild-not-allowlisted"}),
    )


def test_build_hermes_config_map_discord_contains_policy_plugins():
    cfg = build_hermes_config_discord("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
        platform="discord",
    )

    assert_that(cm.data, has_key("discord-deny-dms-plugin.yaml"))
    assert_that(cm.data, has_key("discord-guild-allowlist-plugin.yaml"))


def test_build_secret_hermes_discord_scopes_access_and_home_channel():
    secret = build_secret_hermes_discord(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        "Infra Sentinel",
        "discord-token",
        "key",
        "http://litellm",
        "api-key",
        ["channel-1"],
        ["user-1"],
        ["role-1"],
        False,
        "channel-1",
        ["guild-1"],
    )

    assert_that(secret.string_data["DISCORD_BOT_TOKEN"], equal_to("discord-token"))
    assert_that(secret.string_data["DISCORD_ALLOWED_CHANNELS"], equal_to("channel-1"))
    assert_that(secret.string_data["DISCORD_ALLOWED_USERS"], equal_to("user-1"))
    assert_that(secret.string_data["DISCORD_ALLOWED_ROLES"], equal_to("role-1"))
    assert_that(secret.string_data["DISCORD_ALLOW_ALL_USERS"], equal_to("false"))
    assert_that(secret.string_data["DISCORD_GUILD_IDS"], equal_to("guild-1"))
    assert_that(secret.string_data["DISCORD_HOME_CHANNEL"], equal_to("channel-1"))
    assert_that(secret.string_data["DISCORD_ALLOW_BOTS"], equal_to("none"))


def test_build_secret_hermes_discord_allows_users_with_channel_restrictions():
    secret = build_secret_hermes_discord(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        "Infra Sentinel",
        "discord-token",
        "key",
        "http://litellm",
        "api-key",
        ["channel-1"],
        [],
        [],
        True,
        None,
        ["guild-1"],
    )

    assert_that(secret.string_data["DISCORD_ALLOWED_CHANNELS"], equal_to("channel-1"))
    assert_that(secret.string_data["DISCORD_ALLOW_ALL_USERS"], equal_to("true"))


def test_build_hermes_config_sets_model_and_base_url():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["model"]["model"], equal_to("qwen3"))
    assert_that(cfg["model"]["base_url"], equal_to("http://litellm:4000"))
    assert_that(cfg["model"]["api_mode"], equal_to("chat_completions"))


def test_build_hermes_config_unauthorized_dm_behavior_is_ignore():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["slack"]["unauthorized_dm_behavior"], equal_to("ignore"))


def test_build_hermes_config_strict_mention_is_enabled():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["slack"]["strict_mention"], equal_to(True))


def test_build_hermes_config_require_mention_is_enabled():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["slack"]["require_mention"], equal_to(True))


def test_build_hermes_config_plugins_has_deny_dms():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    assert_that("slack-deny-dms" in cfg["plugins"]["enabled"], equal_to(True))


def test_build_hermes_config_model_stripped_of_prefix():
    cfg = build_hermes_config("litellm/my-special-model", "http://x:4000")
    assert_that(cfg["model"]["model"], equal_to("my-special-model"))


def test_build_hermes_config_model_no_prefix_stays_intact():
    cfg = build_hermes_config("qwen3", "http://x:4000")
    assert_that(cfg["model"]["model"], equal_to("qwen3"))


def test_build_hermes_config_map_contains_all_required_keys():
    cfg = build_hermes_config("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
    )
    for key in (
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "TOOLS.md",
        "AGENTS.md",
        "BOOT.md",
        "HEARTBEAT.md",
        "hermes-config.yaml",
        "slack-deny-dms-plugin.yaml",
        "slack-deny-dms-init.py",
        "healthz-server.py",
        "start.sh",
    ):
        assert_that(cm.data, has_key(key))


def test_build_hermes_config_map_soul_has_bootloader_footer():
    cfg = build_hermes_config("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
    )
    assert_that(cm.data["SOUL.md"], contains_string("# Soul"))
    assert_that(cm.data["SOUL.md"], contains_string("/workspace/IDENTITY.md"))


def test_build_hermes_config_map_no_bootstrap_md():
    cfg = build_hermes_config("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
    )
    assert_that(cm.data, is_not(has_key("BOOTSTRAP.md")))


def test_build_hermes_config_map_hermes_config_is_valid_yaml():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
    )
    parsed = yaml.safe_load(cm.data["hermes-config.yaml"])
    assert_that(parsed["model"]["base_url"], equal_to("http://litellm:4000"))


def test_build_secret_hermes_slack_contains_required_keys():
    secret = build_secret_hermes_slack(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        agent_name="myagent",
        slack_bot_token="xoxb-bot",
        slack_app_token="xapp-app",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
        api_server_key="secret-key-123",
        channel_ids=["C001", "C002"],
        dm_user_ids=["U001", "U002"],
        dm_policy="allowlist",
    )
    data = secret.string_data
    assert_that(data["SLACK_BOT_TOKEN"], equal_to("xoxb-bot"))
    assert_that(data["SLACK_APP_TOKEN"], equal_to("xapp-app"))
    assert_that(data["API_SERVER_KEY"], equal_to("secret-key-123"))
    assert_that(data["SLACK_HOME_CHANNEL"], equal_to("C001"))
    assert_that(data["SLACK_CHANNEL_IDS"], equal_to("C001,C002"))
    assert_that(data["SLACK_DM_ALLOWED_USERS"], equal_to("U001,U002"))
    assert_that(data["SLACK_ALLOW_ALL_USERS"], equal_to("true"))
    assert_that(data["API_SERVER_ENABLED"], equal_to("true"))
    assert_that(data["OPENAI_API_KEY"], equal_to("sk-key"))
    assert_that(data["OPENAI_BASE_URL"], equal_to("http://litellm:4000"))


def test_build_secret_hermes_slack_empty_lists_give_empty_strings():
    secret = build_secret_hermes_slack(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        agent_name="myagent",
        slack_bot_token="xoxb-bot",
        slack_app_token="xapp-app",
        litellm_api_key="sk-key",
        litellm_base_url="http://x:4000",
        api_server_key="k",
        channel_ids=[],
        dm_user_ids=[],
    )
    assert_that(secret.string_data["SLACK_HOME_CHANNEL"], equal_to("C0000000000"))
    assert_that(secret.string_data["SLACK_CHANNEL_IDS"], equal_to(""))
    assert_that(secret.string_data["SLACK_DM_ALLOWED_USERS"], equal_to(""))


def _secret_with(dm_user_ids, dm_policy):
    return build_secret_hermes_slack(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        agent_name="myagent",
        slack_bot_token="xoxb-bot",
        slack_app_token="xapp-app",
        litellm_api_key="sk-key",
        litellm_base_url="http://x:4000",
        api_server_key="k",
        channel_ids=[],
        dm_user_ids=dm_user_ids,
        dm_policy=dm_policy,
    )


def test_open_dm_policy_drops_deny_dms_plugin():
    cfg = build_hermes_config("litellm/qwen3", "http://x:4000", dm_policy="open")
    enabled = cfg["plugins"]["enabled"]
    # Open means no DM gate: the deny plugin is left out, channel allowlist stays.
    assert_that("slack-deny-dms" in enabled, equal_to(False))
    assert_that("slack-channel-allowlist" in enabled, equal_to(True))


def test_off_and_allowlist_keep_deny_dms_plugin():
    for policy in ("off", "allowlist"):
        cfg = build_hermes_config("litellm/qwen3", "http://x:4000", dm_policy=policy)
        assert_that("slack-deny-dms" in cfg["plugins"]["enabled"], equal_to(True))


def test_open_group_policy_drops_channel_allowlist_plugin():
    cfg = build_hermes_config("litellm/qwen3", "http://x:4000", group_policy="open")
    enabled = cfg["plugins"]["enabled"]
    # Open means reply everywhere even if a channel list is retained in config.
    assert_that("slack-channel-allowlist" in enabled, equal_to(False))


def test_allowlist_group_policy_keeps_channel_allowlist_plugin():
    cfg = build_hermes_config("litellm/qwen3", "http://x:4000", group_policy="allowlist")
    assert_that("slack-channel-allowlist" in cfg["plugins"]["enabled"], equal_to(True))


def test_open_group_and_dm_policy_drops_both_gating_plugins():
    cfg = build_hermes_config("litellm/qwen3", "http://x:4000", dm_policy="open", group_policy="open")
    enabled = cfg["plugins"]["enabled"]
    assert_that("slack-deny-dms" in enabled, equal_to(False))
    assert_that("slack-channel-allowlist" in enabled, equal_to(False))


def test_default_verbose_mode_enables_interim_assistant_messages():
    cfg = build_hermes_config("litellm/qwen3", "http://x:4000")
    slack_display = cfg["display"]["platforms"]["slack"]
    assert_that(slack_display["interim_assistant_messages"], equal_to(True))
    # Verbosity drives interim messages only; progress spam stays suppressed.
    assert_that(slack_display["tool_progress"], equal_to("off"))
    assert_that(slack_display["busy_ack_detail"], equal_to(False))


def test_concise_mode_disables_interim_assistant_messages():
    cfg = build_hermes_config("litellm/qwen3", "http://x:4000", verbose_mode=False)
    slack_display = cfg["display"]["platforms"]["slack"]
    assert_that(slack_display["interim_assistant_messages"], equal_to(False))
    assert_that(slack_display["tool_progress"], equal_to("off"))
    assert_that(slack_display["busy_ack_detail"], equal_to(False))


def test_allowlist_policy_seeds_dm_allowed_users():
    secret = _secret_with(["U001", "U002"], "allowlist")
    assert_that(secret.string_data["SLACK_DM_ALLOWED_USERS"], equal_to("U001,U002"))


def test_off_policy_clears_dm_allowed_users_even_with_user_ids():
    # Switching to "off" must not leave a stale allowlist that still grants DM access.
    secret = _secret_with(["U001", "U002"], "off")
    assert_that(secret.string_data["SLACK_DM_ALLOWED_USERS"], equal_to(""))


def test_open_policy_does_not_seed_dm_allowed_users():
    secret = _secret_with(["U001", "U002"], "open")
    assert_that(secret.string_data["SLACK_DM_ALLOWED_USERS"], equal_to(""))


def test_start_sh_includes_hermes_gateway_run():
    assert_that(HERMES_START_SH, contains_string("hermes gateway run"))


def test_start_sh_seeds_user_md_once():
    assert_that(HERMES_START_SH, contains_string("USER.md"))
    assert_that(HERMES_START_SH, contains_string("/opt/data/memories/USER.md"))


def test_build_hermes_config_plugins_has_both():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    enabled = cfg["plugins"]["enabled"]
    assert_that("slack-channel-allowlist" in enabled, equal_to(True))
    assert_that("slack-deny-dms" in enabled, equal_to(True))


def test_build_hermes_config_map_has_channel_allowlist_plugin():
    cfg = build_hermes_config("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
    )
    assert_that(cm.data, has_key("slack-channel-allowlist-plugin.yaml"))
    assert_that(cm.data, has_key("slack-channel-allowlist-init.py"))


def test_start_sh_copies_channel_allowlist_plugin():
    assert_that(HERMES_START_SH, contains_string("slack-channel-allowlist"))


def test_deny_dms_plugin_init_is_valid_python():
    compile(SLACK_DENY_DMS_PLUGIN_INIT, "<plugin>", "exec")


def test_channel_allowlist_plugin_init_is_valid_python():
    compile(SLACK_CHANNEL_ALLOWLIST_PLUGIN_INIT, "<plugin>", "exec")


def test_build_hermes_deployment_mounts_opt_data_and_workspace():
    dep = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:latest")
    mounts = {m.mount_path for m in dep.spec.template.spec.containers[0].volume_mounts}
    assert_that("/opt/data" in mounts, equal_to(True))
    assert_that("/workspace" in mounts, equal_to(True))


def test_build_hermes_deployment_restarts_a_circuit_breaker_paused_gateway():
    dep = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:latest")

    probe = dep.spec.template.spec.containers[0].liveness_probe
    assert_that(probe.http_get.path, equal_to("/live"))
    assert_that(probe.period_seconds, equal_to(60))
    assert_that(probe.failure_threshold, equal_to(5))


def test_build_hermes_deployment_workspace_is_pvc_backed():
    # /workspace must persist across restarts (AF-215): it is a subPath of the
    # per-agent PVC, not an ephemeral emptyDir — mirroring ocbw's persistent
    # ./agents/<name>/workspace bind-mount and OpenClaw's PVC-nested workspace.
    dep = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:latest")
    mounts = {m.mount_path: m for m in dep.spec.template.spec.containers[0].volume_mounts}
    workspace = mounts["/workspace"]
    assert_that(workspace.name, equal_to("data"))
    assert_that(workspace.sub_path, equal_to("workspace"))


def test_build_hermes_deployment_opt_data_stays_on_pvc_root():
    dep = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:latest")
    mounts = {m.mount_path: m for m in dep.spec.template.spec.containers[0].volume_mounts}
    data = mounts["/opt/data"]
    assert_that(data.name, equal_to("data"))
    assert_that(data.sub_path, equal_to(None))


def test_build_hermes_deployment_has_no_empty_dir_workspace_volume():
    dep = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:latest")
    volume_names = {v.name for v in dep.spec.template.spec.volumes}
    assert_that("workspace" in volume_names, equal_to(False))


def test_build_hermes_deployment_anchors_cwd_env_to_workspace():
    # The hermes process starts in its install dir (/opt/hermes) and the user's
    # HOME is /opt/data, so without these env vars the agent's shell is anchored
    # in the wrong place and relative writes miss the persistent /workspace.
    # ocbw sets both alongside terminal.cwd (openclaw_bootstrap/hermes.py) —
    # mirror that.
    dep = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:latest")
    env = {e.name: e.value for e in dep.spec.template.spec.containers[0].env or []}
    assert_that(env.get("TERMINAL_CWD"), equal_to("/workspace"))
    assert_that(env.get("MESSAGING_CWD"), equal_to("/workspace"))


def test_start_sh_prunes_stale_skills_before_seeding():
    # /workspace persists now, so a skill file from a removed integration would
    # linger without an explicit prune before re-seeding.
    assert_that(HERMES_START_SH, contains_string("rm -rf /workspace/skills"))
    prune_at = HERMES_START_SH.index("rm -rf /workspace/skills")
    seed_at = HERMES_START_SH.index("skills.json")
    assert_that(prune_at < seed_at, equal_to(True))


def test_build_hermes_config_map_includes_aai_cli_kwargs_when_provided():
    cfg = build_hermes_config("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
        aai_cli_config_toml="[profiles.jira-work]",
        aai_cli_setup_sh="#!/bin/sh\necho ok",
        skills_json='[{"path": "aai-cli/skill.md", "content": "# Skill"}]',
    )
    assert_that(cm.data, has_key("aai-cli-config.toml"))
    assert_that(cm.data, has_key("aai-cli-setup.sh"))
    assert_that(cm.data, has_key("skills.json"))
    assert_that(cm.data["aai-cli-config.toml"], contains_string("[profiles.jira-work]"))


def test_build_hermes_config_map_omits_aai_cli_keys_when_not_provided():
    cfg = build_hermes_config("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
    )
    assert_that(cm.data, is_not(has_key("aai-cli-config.toml")))
    assert_that(cm.data, is_not(has_key("aai-cli-setup.sh")))
    assert_that(cm.data, is_not(has_key("skills.json")))


def test_start_sh_includes_aai_cli_setup_hook():
    assert_that(HERMES_START_SH, contains_string("aai-cli-setup.sh"))


def test_start_sh_includes_skills_json_reconstruction():
    assert_that(HERMES_START_SH, contains_string("skills.json"))
    assert_that(HERMES_START_SH, contains_string("/workspace/skills"))


def test_build_hermes_config_approval_mode_auto_maps_to_smart():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000", approval_mode="auto")
    assert_that(cfg["approvals"]["mode"], equal_to("smart"))


def test_build_hermes_config_approval_mode_off():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000", approval_mode="off")
    assert_that(cfg["approvals"]["mode"], equal_to("off"))


def test_build_hermes_config_approval_mode_manual():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000", approval_mode="manual")
    assert_that(cfg["approvals"]["mode"], equal_to("manual"))


def test_build_hermes_config_default_approval_mode_is_smart():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["approvals"]["mode"], equal_to("smart"))


def test_build_hermes_deployment_pod_carries_agent_component_label():
    dep = build_hermes_deployment(
        agent_id=_AGENT_ID,
        org_id=_ORG_ID,
        namespace=_NS,
        image="registry.example.com/hermes:0.1.0",
    )
    pod_labels = dep.spec.template.metadata.labels
    assert_that(pod_labels["agentbarn.io/component"], equal_to("agent"))
    # Selector must NOT include the new label, so existing agents keep matching.
    assert_that(
        dep.spec.selector.match_labels,
        equal_to({"app": f"agent-{_AGENT_ID}"}),
    )


# --- Telegram config --------------------------------------------------------


def test_build_hermes_config_telegram_sets_model():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["model"]["model"], equal_to("qwen3"))
    assert_that(cfg["model"]["base_url"], equal_to("http://litellm:4000"))
    assert_that(cfg["model"]["api_mode"], equal_to("chat_completions"))


def test_build_hermes_config_telegram_has_no_slack_section():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg, is_not(has_key("slack")))


def test_build_hermes_config_telegram_require_mention_is_enabled():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["telegram"]["require_mention"], equal_to(True))


def test_build_hermes_config_telegram_exclusive_bot_mentions_is_enabled():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["telegram"]["exclusive_bot_mentions"], equal_to(True))


def test_build_hermes_config_telegram_has_telegram_platform():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["display"]["platforms"], has_key("telegram"))
    assert_that(cfg["display"]["platforms"], is_not(has_key("slack")))


def test_build_hermes_config_telegram_dm_off_enables_deny_plugin():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000", dm_policy="off")
    assert_that("telegram-deny-dms" in cfg["plugins"]["enabled"], equal_to(True))
    assert_that(cfg, is_not(has_key("allow_from")))


def test_build_hermes_config_telegram_dm_open_drops_deny_plugin():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000", dm_policy="open")
    assert_that("telegram-deny-dms" in cfg["plugins"]["enabled"], equal_to(False))
    assert_that(cfg, is_not(has_key("allow_from")))


def test_build_hermes_config_telegram_dm_allowlist_enables_deny_plugin():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000", dm_policy="allowlist")
    assert_that("telegram-deny-dms" in cfg["plugins"]["enabled"], equal_to(True))


def test_build_hermes_config_telegram_group_open_drops_channel_plugin():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000", group_policy="open")
    assert_that("telegram-channel-allowlist" in cfg["plugins"]["enabled"], equal_to(False))
    assert_that(cfg, is_not(has_key("guest_mode")))
    assert_that(cfg, is_not(has_key("group_allowed_chats")))


def test_build_hermes_config_telegram_group_allowlist_enables_channel_plugin():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000", group_policy="allowlist")
    assert_that("telegram-channel-allowlist" in cfg["plugins"]["enabled"], equal_to(True))
    assert_that(cfg, is_not(has_key("guest_mode")))
    assert_that(cfg, is_not(has_key("group_allowed_chats")))


def test_build_hermes_config_telegram_open_both_only_telemetry():
    cfg = build_hermes_config_telegram(
        "litellm/qwen3",
        "http://litellm:4000",
        dm_policy="open",
        group_policy="open",
    )
    assert_that(cfg["plugins"]["enabled"], equal_to(["telemetry-push"]))


def test_build_hermes_config_telegram_approval_mode():
    cfg = build_hermes_config_telegram("litellm/qwen3", "http://litellm:4000", approval_mode="manual")
    assert_that(cfg["approvals"]["mode"], equal_to("manual"))


# --- Telegram secret --------------------------------------------------------


def test_build_secret_hermes_telegram_contains_required_keys():
    secret = build_secret_hermes_telegram(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        agent_name="myagent",
        telegram_bot_token="123:ABC",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
        api_server_key="secret-key-123",
    )
    data = secret.string_data
    assert_that(data["TELEGRAM_BOT_TOKEN"], equal_to("123:ABC"))
    assert_that(data["OPENAI_API_KEY"], equal_to("sk-key"))
    assert_that(data["OPENAI_BASE_URL"], equal_to("http://litellm:4000"))
    assert_that(data["API_SERVER_KEY"], equal_to("secret-key-123"))
    assert_that(data["AGENT_PLATFORM"], equal_to("telegram"))
    assert_that(data["API_SERVER_ENABLED"], equal_to("true"))
    assert_that(data["TELEGRAM_HOME_CHANNEL"], equal_to("0000000000"))
    assert_that(data["TELEGRAM_HOME_CHANNEL_NAME"], equal_to("No Telegram Home Channel"))
    assert_that(data, has_key("TELEGRAM_CHANNEL_IDS"))
    assert_that(data, has_key("TELEGRAM_DM_ALLOWED_USERS"))


def test_build_secret_hermes_telegram_allowlist_seeds_dm_users():
    secret = build_secret_hermes_telegram(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        agent_name="myagent",
        telegram_bot_token="123:ABC",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
        api_server_key="k",
        dm_policy="allowlist",
        allowed_user_ids=["111", "222"],
        allowed_chat_ids=["-100999"],
    )
    data = secret.string_data
    assert_that(data["TELEGRAM_DM_ALLOWED_USERS"], equal_to("111,222"))
    assert_that(data["TELEGRAM_CHANNEL_IDS"], equal_to("-100999"))
    assert_that(data["TELEGRAM_HOME_CHANNEL"], equal_to("-100999"))
    assert_that(data["TELEGRAM_HOME_CHANNEL_NAME"], equal_to("-100999"))


def test_build_secret_hermes_telegram_off_policy_clears_dm_users():
    secret = build_secret_hermes_telegram(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        agent_name="myagent",
        telegram_bot_token="123:ABC",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
        api_server_key="k",
        dm_policy="off",
        allowed_user_ids=["111"],
    )
    assert_that(secret.string_data["TELEGRAM_DM_ALLOWED_USERS"], equal_to(""))


def test_build_secret_hermes_telegram_no_slack_bot_keys():
    secret = build_secret_hermes_telegram(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        agent_name="myagent",
        telegram_bot_token="123:ABC",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
        api_server_key="k",
    )
    for key in secret.string_data:
        assert_that(key.startswith("SLACK_"), equal_to(False))


def test_build_secret_hermes_slack_has_agent_platform():
    secret = build_secret_hermes_slack(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        agent_name="myagent",
        slack_bot_token="xoxb-bot",
        slack_app_token="xapp-app",
        litellm_api_key="sk-key",
        litellm_base_url="http://x:4000",
        api_server_key="k",
        channel_ids=[],
        dm_user_ids=[],
    )
    assert_that(secret.string_data["AGENT_PLATFORM"], equal_to("slack"))


# --- Telegram config map ----------------------------------------------------


def test_build_hermes_config_map_telegram_omits_slack_plugins():
    cfg = build_hermes_config_telegram("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
        platform="telegram",
    )
    assert_that(cm.data, is_not(has_key("slack-deny-dms-plugin.yaml")))
    assert_that(cm.data, is_not(has_key("slack-deny-dms-init.py")))
    assert_that(cm.data, is_not(has_key("slack-channel-allowlist-plugin.yaml")))
    assert_that(cm.data, is_not(has_key("slack-channel-allowlist-init.py")))


def test_build_hermes_config_map_telegram_has_telegram_plugins():
    cfg = build_hermes_config_telegram("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
        platform="telegram",
    )
    assert_that(cm.data, has_key("telegram-deny-dms-plugin.yaml"))
    assert_that(cm.data, has_key("telegram-deny-dms-init.py"))
    assert_that(cm.data, has_key("telegram-channel-allowlist-plugin.yaml"))
    assert_that(cm.data, has_key("telegram-channel-allowlist-init.py"))


def test_build_hermes_config_map_telegram_has_telemetry_plugin():
    cfg = build_hermes_config_telegram("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
        platform="telegram",
    )
    assert_that(cm.data, has_key("telemetry-push-plugin.yaml"))
    assert_that(cm.data, has_key("telemetry-push-init.py"))


def test_build_hermes_config_map_slack_default_still_has_slack_plugins():
    cfg = build_hermes_config("litellm/m", "http://x:4000")
    cm = build_hermes_config_map(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        soul_md="# Soul",
        identity_md="# Identity",
        user_md="# User",
        tools_md="# Tools",
        agents_md="# Agents",
        boot_md="# Boot",
        heartbeat_md="# Heartbeat",
        hermes_config=cfg,
    )
    assert_that(cm.data, has_key("slack-deny-dms-plugin.yaml"))
    assert_that(cm.data, has_key("slack-channel-allowlist-plugin.yaml"))


# --- start.sh conditional Slack plugins --------------------------------------


def test_hermes_start_sh_conditional_slack_plugins():
    assert_that(HERMES_START_SH, contains_string("if [ -f /app/config/slack-deny-dms"))
    assert_that(
        HERMES_START_SH,
        contains_string("if [ -f /app/config/slack-channel-allowlist"),
    )


def test_hermes_start_sh_conditional_telegram_plugins():
    assert_that(HERMES_START_SH, contains_string("if [ -f /app/config/telegram-deny-dms"))
    assert_that(
        HERMES_START_SH,
        contains_string("if [ -f /app/config/telegram-channel-allowlist"),
    )


def test_telegram_deny_dms_plugin_init_is_valid_python():
    compile(TELEGRAM_DENY_DMS_PLUGIN_INIT, "<plugin>", "exec")


def test_telegram_channel_allowlist_plugin_init_is_valid_python():
    compile(TELEGRAM_CHANNEL_ALLOWLIST_PLUGIN_INIT, "<plugin>", "exec")
