from uuid import UUID

from hamcrest import assert_that, equal_to

from api.domains.agents.builders.openclaw import (
    build_deployment,
    build_openclaw_config_overlay,
    build_openclaw_config_overlay_teams,
)


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
