from uuid import UUID

import yaml
from hamcrest import assert_that, contains_string, equal_to, has_key, is_not

from api.domains.agents.builders import (
    HERMES_START_SH,
    SLACK_CHANNEL_ALLOWLIST_PLUGIN_INIT,
    SLACK_DENY_DMS_PLUGIN_INIT,
    build_hermes_config,
    build_hermes_config_map,
    build_hermes_deployment,
    build_secret_hermes_slack,
)

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


def test_build_hermes_config_sets_model_and_base_url():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["model"]["model"], equal_to("qwen3"))
    assert_that(cfg["model"]["base_url"], equal_to("http://litellm:4000"))
    assert_that(cfg["model"]["api_mode"], equal_to("chat_completions"))


def test_build_hermes_config_unauthorized_dm_behavior_is_ignore():
    cfg = build_hermes_config("litellm/qwen3", "http://litellm:4000")
    assert_that(cfg["slack"]["unauthorized_dm_behavior"], equal_to("ignore"))


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
    cfg = build_hermes_config(
        "litellm/qwen3", "http://x:4000", group_policy="allowlist"
    )
    assert_that("slack-channel-allowlist" in cfg["plugins"]["enabled"], equal_to(True))


def test_open_group_and_dm_policy_drops_both_gating_plugins():
    cfg = build_hermes_config(
        "litellm/qwen3", "http://x:4000", dm_policy="open", group_policy="open"
    )
    enabled = cfg["plugins"]["enabled"]
    assert_that("slack-deny-dms" in enabled, equal_to(False))
    assert_that("slack-channel-allowlist" in enabled, equal_to(False))


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


def test_build_hermes_deployment_has_empty_dir_workspace():
    from kubernetes.client import V1EmptyDirVolumeSource

    dep = build_hermes_deployment(_AGENT_ID, _ORG_ID, _NS, "hermes:latest")
    workspace_vols = [
        v for v in dep.spec.template.spec.volumes if v.name == "workspace"
    ]
    assert_that(len(workspace_vols), equal_to(1))
    assert_that(
        isinstance(workspace_vols[0].empty_dir, V1EmptyDirVolumeSource), equal_to(True)
    )


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
