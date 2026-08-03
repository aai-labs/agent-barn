from datetime import UTC, datetime
from typing import Any
from uuid import uuid7

from hamcrest import assert_that, contains_string, equal_to, is_not

from api.domains.templates.models import AgentTemplate, TemplateSource
from api.domains.templates.renderer import render_template
from api.domains.templates.slug import generate_template_slug, slugify


def _template(**overrides: Any) -> AgentTemplate:
    fields: dict[str, Any] = {
        "organization_id": uuid7(),
        "template_slug": "test",
        "template_name": "Test",
        "template_source": TemplateSource.CUSTOM,
        "version": 1,
        "soul_md": "# Soul",
        "identity_md": "# Identity",
        "user_md": "# User",
        "tools_md": "# Tools",
        "agents_md": "# Agents",
        "boot_md": "# Boot",
        "bootstrap_md": "# Bootstrap",
        "heartbeat_md": "# Heartbeat",
    }
    fields.update(overrides)
    return AgentTemplate(**fields)


def test_renders_all_known_variables():
    template = _template(
        soul_md=(
            "name={{ agent_display_name }} slug={{ agent_name }} "
            "app={{ slack_app_display_name }} date={{ deploy_date }}"
        )
    )

    rendered = render_template(template, "Maya Bot")

    today = datetime.now(UTC).date().isoformat()
    assert_that(
        rendered.soul_md,
        equal_to(f"name=Maya Bot slug=maya-bot app=Maya Bot date={today}"),
    )


def test_renders_placeholders_regardless_of_inner_spacing():
    template = _template(identity_md="{{agent_name}} and {{  agent_name  }}")

    rendered = render_template(template, "Maya")

    assert_that(rendered.identity_md, equal_to("maya and maya"))


def test_unknown_placeholders_pass_through():
    template = _template(boot_md="keep {{ not_a_variable }} as-is")

    rendered = render_template(template, "Maya")

    assert_that(rendered.boot_md, equal_to("keep {{ not_a_variable }} as-is"))


def test_broken_placeholders_pass_through():
    template = _template(user_md="{{ agent_name |}} {{agent_name")

    rendered = render_template(template, "Maya")

    assert_that(rendered.user_md, equal_to("{{ agent_name |}} {{agent_name"))


def test_agent_name_falls_back_when_name_has_no_alphanumerics():
    template = _template(soul_md="{{ agent_name }}")

    rendered = render_template(template, "!!!")

    assert_that(rendered.soul_md, equal_to("agent"))


def test_all_eight_fields_are_rendered():
    template = _template(
        soul_md="{{ agent_name }}",
        identity_md="{{ agent_name }}",
        user_md="{{ agent_name }}",
        tools_md="{{ agent_name }}",
        agents_md="{{ agent_name }}",
        boot_md="{{ agent_name }}",
        bootstrap_md="{{ agent_name }}",
        heartbeat_md="{{ agent_name }}",
    )

    rendered = render_template(template, "Maya")

    for field in (
        rendered.soul_md,
        rendered.identity_md,
        rendered.user_md,
        rendered.agents_md,
        rendered.boot_md,
        rendered.bootstrap_md,
        rendered.heartbeat_md,
    ):
        assert_that(field, equal_to("maya"))
    assert_that(rendered.tools_md, contains_string("maya"))
    assert_that(rendered.tools_md, is_not(contains_string("{{")))


def test_slugify_basic():
    assert_that(slugify("Scrum Master"), equal_to("scrum-master"))
    assert_that(slugify("  My!! Agent??  "), equal_to("my-agent"))
    assert_that(slugify("!!!"), equal_to(""))


def test_generate_template_slug_appends_hex_suffix():
    slug = generate_template_slug("Maya")
    base, _, suffix = slug.rpartition("-")
    assert_that(base, equal_to("maya"))
    assert_that(len(suffix), equal_to(8))
