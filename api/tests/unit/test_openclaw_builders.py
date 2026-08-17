from uuid import UUID

from hamcrest import assert_that, equal_to, has_key, is_not

from api.domains.agents.builders.openclaw import (
    INIT_OPENCLAW_JS,
    START_SH,
    build_deployment,
    build_openclaw_config_overlay,
    build_openclaw_config_overlay_discord,
    build_openclaw_config_overlay_teams,
    build_openclaw_config_overlay_telegram,
    build_secret_discord,
    build_secret_slack,
    build_secret_telegram,
)


def test_build_openclaw_config_overlay_exec_mode_is_full():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))


def test_build_openclaw_config_overlay_exec_mode_ignores_approval_mode():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000", approval_mode="manual")
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))


def test_build_openclaw_config_overlay_teams_exec_mode_is_full():
    overlay = build_openclaw_config_overlay_teams("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))


def test_build_openclaw_config_overlay_gateway_auth_is_none():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["gateway"]["auth"]["mode"], equal_to("none"))


def test_build_openclaw_config_overlay_teams_require_mention_is_enabled():
    overlay = build_openclaw_config_overlay_teams("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["channels"]["msteams"]["requireMention"], equal_to(True))


def test_build_openclaw_config_overlay_teams_gateway_auth_is_none():
    overlay = build_openclaw_config_overlay_teams("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["gateway"]["auth"]["mode"], equal_to("none"))


def test_build_openclaw_config_overlay_thread_requires_explicit_mention():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["channels"]["slack"]["thread"]["requireExplicitMention"], equal_to(True))


def test_build_openclaw_config_overlay_require_mention_is_enabled():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["channels"]["slack"]["requireMention"], equal_to(True))


def test_build_openclaw_config_overlay_allowlisted_channel_requires_mention():
    overlay = build_openclaw_config_overlay(
        "litellm/gpt-4o",
        "http://litellm:4000",
        slack_channel_ids=["C001"],
    )
    assert_that(overlay["channels"]["slack"]["channels"]["C001"]["requireMention"], equal_to(True))


def test_build_deployment_has_pvc_owner_init_container():
    dep = build_deployment(
        agent_id=UUID("00000000-0000-0000-0000-000000000001"),
        org_id=UUID("00000000-0000-0000-0000-000000000002"),
        namespace="default",
        image="registry.example.com/openclaw:0.4.0",
    )
    init_containers = dep.spec.template.spec.init_containers
    assert init_containers is not None
    assert len(init_containers) == 1
    ic = init_containers[0]
    assert ic.name == "fix-pvc-owner"
    assert ic.command == ["chown", "1000:1000", "/home/node/.openclaw"]
    assert ic.security_context.run_as_user == 0


def test_build_deployment_pod_carries_agent_component_label():
    dep = build_deployment(
        agent_id=UUID("00000000-0000-0000-0000-000000000001"),
        org_id=UUID("00000000-0000-0000-0000-000000000002"),
        namespace="default",
        image="registry.example.com/openclaw:0.4.0",
    )
    pod_labels = dep.spec.template.metadata.labels
    assert_that(pod_labels["agentfarm.io/component"], equal_to("agent"))
    # Selector must NOT include the new label, so existing agents keep matching.
    assert_that(
        dep.spec.selector.match_labels,
        equal_to({"app": "agent-00000000-0000-0000-0000-000000000001"}),
    )


_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


# --- Discord overlay --------------------------------------------------------


def test_build_openclaw_config_overlay_discord_defaults_to_private_mentions_only():
    overlay = build_openclaw_config_overlay_discord("litellm/gpt-4o", "http://litellm:4000")

    discord = overlay["channels"]["discord"]
    assert_that(discord["groupPolicy"], equal_to("allowlist"))
    assert_that(discord["guilds"], equal_to({}))
    assert_that(discord["dmPolicy"], equal_to("disabled"))
    assert_that(discord["dm"]["enabled"], equal_to(False))
    assert_that(overlay["bindings"][0]["match"]["channel"], equal_to("discord"))


def test_build_openclaw_config_overlay_discord_allowlists_guilds_with_mentions():
    overlay = build_openclaw_config_overlay_discord(
        "litellm/gpt-4o",
        "http://litellm:4000",
        guild_ids=["123", "456"],
        allowed_role_ids=["role-1"],
        home_channel_id="channel-1",
    )

    assert_that(
        overlay["channels"]["discord"]["guilds"],
        equal_to(
            {
                "123": {"requireMention": True, "roles": ["role-1"]},
                "456": {"requireMention": True, "roles": ["role-1"]},
            }
        ),
    )
    assert_that(
        overlay["agents"]["defaults"]["heartbeat"],
        equal_to({"target": "discord", "to": "channel:channel-1", "directPolicy": "block"}),
    )


def test_build_secret_discord_sets_runtime_token_and_platform():
    secret = build_secret_discord(_AGENT_ID, _ORG_ID, _NS, "discord-token", "key", "http://litellm")

    assert_that(secret.string_data["DISCORD_BOT_TOKEN"], equal_to("discord-token"))
    assert_that(secret.string_data["AGENT_PLATFORM"], equal_to("discord"))


# --- Telegram overlay -------------------------------------------------------


def test_build_openclaw_config_overlay_telegram_has_telegram_channel():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["channels"]["telegram"]["enabled"], equal_to(True))


def test_build_openclaw_config_overlay_telegram_no_slack_channel():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["channels"], is_not(has_key("slack")))


def test_build_openclaw_config_overlay_telegram_dm_off():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000", dm_policy="off")
    assert_that(overlay["channels"]["telegram"]["dmPolicy"], equal_to("allowlist"))
    assert_that(overlay["channels"]["telegram"]["allowFrom"], equal_to([]))


def test_build_openclaw_config_overlay_telegram_dm_open():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000", dm_policy="open")
    assert_that(overlay["channels"]["telegram"]["dmPolicy"], equal_to("open"))
    assert_that(overlay["channels"]["telegram"]["allowFrom"], equal_to(["*"]))


def test_build_openclaw_config_overlay_telegram_dm_allowlist():
    overlay = build_openclaw_config_overlay_telegram(
        "litellm/gpt-4o",
        "http://litellm:4000",
        dm_policy="allowlist",
        allowed_user_ids=["123", "456"],
    )
    assert_that(overlay["channels"]["telegram"]["dmPolicy"], equal_to("allowlist"))
    assert_that(overlay["channels"]["telegram"]["allowFrom"], equal_to(["123", "456"]))


def test_build_openclaw_config_overlay_telegram_gateway_auth_none():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["gateway"]["auth"]["mode"], equal_to("none"))


def test_build_openclaw_config_overlay_telegram_exec_mode_full():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))


def test_build_openclaw_config_overlay_telegram_binding_routes_to_telegram():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000")
    assert_that(len(overlay["bindings"]), equal_to(1))
    assert_that(overlay["bindings"][0]["match"]["channel"], equal_to("telegram"))


def test_build_openclaw_config_overlay_telegram_group_policy_open():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000", group_policy="open")
    assert_that(overlay["channels"]["telegram"]["groupPolicy"], equal_to("open"))


def test_build_openclaw_config_overlay_telegram_group_policy_allowlist():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000", group_policy="allowlist")
    assert_that(overlay["channels"]["telegram"]["groupPolicy"], equal_to("allowlist"))


def test_build_openclaw_config_overlay_telegram_allowed_chat_ids():
    overlay = build_openclaw_config_overlay_telegram(
        "litellm/gpt-4o",
        "http://litellm:4000",
        group_policy="allowlist",
        allowed_chat_ids=["-100123", "-100456"],
    )
    assert_that(
        overlay["channels"]["telegram"]["groups"],
        equal_to({"-100123": {"requireMention": True}, "-100456": {"requireMention": True}}),
    )


def test_build_openclaw_config_overlay_telegram_allowed_chat_ids_empty_when_none():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000", group_policy="allowlist")
    assert_that(overlay["channels"]["telegram"]["groups"], equal_to({}))


def test_build_openclaw_config_overlay_telegram_open_policy_gates_all_groups():
    overlay = build_openclaw_config_overlay_telegram("litellm/gpt-4o", "http://litellm:4000", group_policy="open")
    assert_that(
        overlay["channels"]["telegram"]["groups"],
        equal_to({"*": {"requireMention": True}}),
    )


# --- Telegram secret --------------------------------------------------------


def test_build_secret_telegram_contains_required_keys():
    secret = build_secret_telegram(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        telegram_bot_token="123:ABC",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
    )
    data = secret.string_data
    assert_that(data["TELEGRAM_BOT_TOKEN"], equal_to("123:ABC"))
    assert_that(data["LITELLM_API_KEY"], equal_to("sk-key"))
    assert_that(data["LITELLM_BASE_URL"], equal_to("http://litellm:4000"))
    assert_that(data["AGENT_PLATFORM"], equal_to("telegram"))


def test_build_secret_telegram_no_slack_keys():
    secret = build_secret_telegram(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        telegram_bot_token="123:ABC",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
    )
    for key in secret.string_data:
        assert_that(key.startswith("SLACK_"), equal_to(False))


def test_build_secret_slack_has_agent_platform():
    secret = build_secret_slack(
        _AGENT_ID,
        _ORG_ID,
        _NS,
        slack_bot_token="xoxb-bot",
        slack_app_token="xapp-app",
        litellm_api_key="sk-key",
        litellm_base_url="http://x:4000",
    )
    assert_that(secret.string_data["AGENT_PLATFORM"], equal_to("slack"))


# --- start.sh conditional Slack install --------------------------------------


def test_openclaw_start_sh_conditional_slack_install():
    assert_that(START_SH.count("@openclaw/slack"), equal_to(1))
    assert_that("AGENT_PLATFORM" in START_SH, equal_to(True))


# --- init-openclaw.js Telegram support ---------------------------------------


def test_init_openclaw_js_has_telegram_replace_paths():
    assert_that("'telegram'" in INIT_OPENCLAW_JS, equal_to(True))


def test_init_openclaw_js_has_telegram_credential_sync():
    assert_that("telegram-allowFrom.json" in INIT_OPENCLAW_JS, equal_to(True))


def test_init_openclaw_js_has_telegram_allowed_chats_replace_path():
    assert_that("'groups'" in INIT_OPENCLAW_JS, equal_to(True))
