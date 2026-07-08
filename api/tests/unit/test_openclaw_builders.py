from hamcrest import assert_that, equal_to

from api.domains.agents.builders.openclaw import (
    build_openclaw_config_overlay,
    build_openclaw_config_overlay_teams,
)


def test_build_openclaw_config_overlay_default_approval_mode_is_auto():
    overlay = build_openclaw_config_overlay("litellm/gpt-4o", "http://litellm:4000")
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("auto"))


def test_build_openclaw_config_overlay_approval_mode_manual():
    overlay = build_openclaw_config_overlay(
        "litellm/gpt-4o", "http://litellm:4000", approval_mode="manual"
    )
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("ask"))


def test_build_openclaw_config_overlay_approval_mode_off():
    overlay = build_openclaw_config_overlay(
        "litellm/gpt-4o", "http://litellm:4000", approval_mode="off"
    )
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))


def test_build_openclaw_config_overlay_teams_default_approval_mode_is_auto():
    overlay = build_openclaw_config_overlay_teams(
        "litellm/gpt-4o", "http://litellm:4000"
    )
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("auto"))


def test_build_openclaw_config_overlay_teams_approval_mode_off():
    overlay = build_openclaw_config_overlay_teams(
        "litellm/gpt-4o", "http://litellm:4000", approval_mode="off"
    )
    assert_that(overlay["tools"]["exec"]["mode"], equal_to("full"))
