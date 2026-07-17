from uuid import UUID

from hamcrest import assert_that, equal_to, has_key, is_not

from api.domains.agents.builders.openclaw import (
    build_deployment,
    build_openclaw_config_overlay,
    build_openclaw_config_overlay_teams,
    build_secret_slack,
    build_secret_teams,
)


def test_build_openclaw_config_overlay_exec_mode_is_full():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))


def test_build_openclaw_config_overlay_exec_mode_ignores_approval_mode():
    overlay = build_openclaw_config_overlay(
        "litellm/gpt-4o", "http://litellm:4000", approval_mode="manual"
    )
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))


def test_build_openclaw_config_overlay_teams_exec_mode_is_full():
    overlay = build_openclaw_config_overlay_teams(
        "litellm/gpt-4o", "http://litellm:4000"
    )
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))


def test_build_openclaw_config_overlay_gateway_auth_is_none():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["gateway"]["auth"]["mode"], equal_to("none"))


def test_build_openclaw_config_overlay_teams_gateway_auth_is_none():
    overlay = build_openclaw_config_overlay_teams(
        "litellm/gpt-4o", "http://litellm:4000"
    )
    assert_that(overlay["gateway"]["auth"]["mode"], equal_to("none"))


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


_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


# --- Firecrawl (AF-152) ---


def test_build_openclaw_config_overlay_firecrawl_plugin():
    overlay = build_openclaw_config_overlay(
        "litellm/gpt-4o",
        "http://litellm:4000",
        firecrawl_base_url="http://firecrawl:3002",
        firecrawl_api_key="fc-key",
    )
    assert_that("firecrawl" in overlay["plugins"]["allow"], equal_to(True))
    fc = overlay["plugins"]["entries"]["firecrawl"]
    assert_that(fc["enabled"], equal_to(True))
    assert_that(fc["config"]["webSearch"]["baseUrl"], equal_to("http://firecrawl:3002"))
    assert_that(fc["config"]["webFetch"]["baseUrl"], equal_to("http://firecrawl:3002"))
    assert_that(fc["config"]["webFetch"]["onlyMainContent"], equal_to(True))
    assert_that(fc["config"]["webFetch"]["maxAgeMs"], equal_to(172800000))
    assert_that(fc["config"]["webFetch"]["timeoutSeconds"], equal_to(60))


def test_build_openclaw_config_overlay_firecrawl_tools():
    overlay = build_openclaw_config_overlay(
        "litellm/gpt-4o",
        "http://litellm:4000",
        firecrawl_base_url="http://firecrawl:3002",
        firecrawl_api_key="fc-key",
    )
    assert_that(overlay["tools"]["web"]["fetch"]["provider"], equal_to("firecrawl"))
    assert_that(overlay["tools"]["web"]["search"]["enabled"], equal_to(True))
    assert_that(overlay["tools"]["web"]["search"]["provider"], equal_to("firecrawl"))


def test_build_openclaw_config_overlay_no_firecrawl_by_default():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000")
    assert_that("firecrawl" in overlay["plugins"]["allow"], equal_to(False))
    assert_that(overlay["plugins"]["entries"], is_not(has_key("firecrawl")))
    assert_that(overlay["tools"], is_not(has_key("web")))


def test_build_openclaw_config_overlay_teams_firecrawl():
    overlay = build_openclaw_config_overlay_teams(
        "litellm/gpt-4o",
        "http://litellm:4000",
        firecrawl_base_url="http://firecrawl:3002",
        firecrawl_api_key="fc-key",
    )
    assert_that("firecrawl" in overlay["plugins"]["allow"], equal_to(True))
    assert_that(overlay["plugins"]["entries"], has_key("firecrawl"))
    assert_that(overlay["tools"]["web"]["fetch"]["provider"], equal_to("firecrawl"))


def test_build_secret_slack_firecrawl_key():
    secret = build_secret_slack(
        _AGENT_ID, _ORG_ID, _NS,
        slack_bot_token="xoxb-x",
        slack_app_token="xapp-x",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
        firecrawl_api_key="fc-secret",
    )
    assert_that(secret.string_data["FIRECRAWL_API_KEY"], equal_to("fc-secret"))


def test_build_secret_slack_no_firecrawl_by_default():
    secret = build_secret_slack(
        _AGENT_ID, _ORG_ID, _NS,
        slack_bot_token="xoxb-x",
        slack_app_token="xapp-x",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
    )
    assert_that(secret.string_data, is_not(has_key("FIRECRAWL_API_KEY")))


def test_build_secret_teams_firecrawl_key():
    secret = build_secret_teams(
        _AGENT_ID, _ORG_ID, _NS,
        msteams_app_id="app-id",
        msteams_app_password="app-pw",
        msteams_tenant_id="tenant-id",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
        firecrawl_api_key="fc-secret",
    )
    assert_that(secret.string_data["FIRECRAWL_API_KEY"], equal_to("fc-secret"))


def test_build_secret_teams_no_firecrawl_by_default():
    secret = build_secret_teams(
        _AGENT_ID, _ORG_ID, _NS,
        msteams_app_id="app-id",
        msteams_app_password="app-pw",
        msteams_tenant_id="tenant-id",
        litellm_api_key="sk-key",
        litellm_base_url="http://litellm:4000",
    )
    assert_that(secret.string_data, is_not(has_key("FIRECRAWL_API_KEY")))
